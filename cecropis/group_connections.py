"""Bounded structural grouping of exact annotated members and indexed edges.

Group matrices use sender rows and receiver columns. Saved arrays contain group
summaries and membership only; real neuron edges remain in the local CSR index.
"""
import json
import math
import time
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy import sparse

FIELDS = ('superclass', 'class', 'type', 'somaSide')
DEFAULT_BUDGETS = dict(max_nodes=200000, max_edges=300000000,
                       max_bytes=1024 ** 3, max_groups=10000)
ARRAY_NAMES = ('members', 'membership', 'source', 'target', 'contacts', 'edges',
               'senders', 'receivers', 'self_edges')


def _definition(index, definition):
    if not isinstance(definition, dict) or set(definition) - {'mode', 'field', 'filters', 'body_ids', 'budgets', 'name'}:
        raise ValueError('Unknown grouping definition fields')
    result = dict(definition)
    result.setdefault('mode', 'global')
    result.setdefault('field', 'superclass')
    result.setdefault('filters', {})
    result.setdefault('name', result['field'])
    if result['mode'] not in ('global', 'case') or result['field'] not in FIELDS:
        raise ValueError('Choose global/case mode and a supported grouping field')
    if result['field'] not in index.filter_fields:
        raise ValueError('Grouping field is absent from the local index')
    if not isinstance(result['name'], str) or not result['name'].strip() or len(result['name']) > 100:
        raise ValueError('Grouping name must contain 1..100 characters')
    if not isinstance(result['filters'], dict):
        raise ValueError('filters must be an object')
    index._where(result['filters'])
    budgets = dict(DEFAULT_BUDGETS)
    supplied = result.get('budgets', {})
    if not isinstance(supplied, dict) or set(supplied) - set(budgets):
        raise ValueError('Unknown grouping budget')
    budgets.update(supplied)
    if any(type(value) is not int or value <= 0 for value in budgets.values()):
        raise ValueError('Grouping budgets must be positive integers')
    result['budgets'] = budgets
    if 'body_ids' in result:
        values = result['body_ids']
        if not isinstance(values, list) or not values:
            raise ValueError('body_ids must be a nonempty exact member list')
        if any(not isinstance(x, str) or not x.isascii() or not x.isdecimal() or str(int(x)) != x or not 0 < int(x) <= np.iinfo(np.int64).max for x in values):
            raise ValueError('body_ids must be canonical positive int64 strings')
        if len(set(values)) != len(values):
            raise ValueError('body_ids must not contain duplicates')
        result['body_ids'] = sorted(values, key=int)
    return result


def _scope_file(path):
    path = Path(path)
    manifest = json.loads((path / 'manifest.json').read_text(encoding='utf-8'))
    exact = manifest.get('selection', {}).get('body_ids')
    if manifest.get('format') == 'csr-arrays-v1' and isinstance(exact, list):
        # write_selected_case writes node rows and CSR in this exact selection
        # order. Do not expand the full rich annotation file just to get IDs.
        ids = np.asarray(exact, dtype=np.int64)
        if len(ids) != manifest.get('node_count') or len(np.unique(ids)) != len(ids):
            raise ValueError('Saved scope exact member definition is inconsistent')
    elif not (path / 'nodes.json').exists():
        from .case import load_case, close_case
        case = load_case(path)
        try:
            ids = np.asarray([int(n['bodyId']) for n in case['nodes']], dtype=np.int64)
        finally:
            close_case(case)
    else:
        nodes = json.loads((path / 'nodes.json').read_text(encoding='utf-8'))
        ids = np.asarray([int(n['bodyId']) for n in nodes], dtype=np.int64)
    return manifest, ids


def _members(index, definition, case_path):
    filters = dict(definition['filters'])
    if definition['mode'] == 'global':
        if 'category' in filters and filters['category'] != 'neuron':
            raise ValueError('Global grouping is restricted to annotated Traced neurons')
        filters['category'] = 'neuron'
        if definition.get('body_ids'):
            ids = np.asarray(definition['body_ids'], dtype=np.int64)
            ids = _filtered_ids(index, ids, filters)
        else:
            ids = np.asarray(index.ids_for(filters, max_count=definition['budgets']['max_nodes']), dtype=np.int64)
        case_id = None
    else:
        if not case_path:
            raise ValueError('Case grouping requires a saved calculation scope')
        manifest, ids = _scope_file(case_path)
        if manifest.get('source_index_id') != index.manifest['index_id']:
            raise ValueError('Calculation scope belongs to a different index instance')
        case_id = manifest['case_id']
        ids = np.sort(ids)
        if filters:
            ids = _filtered_ids(index, ids, filters)
    if definition.get('body_ids'):
        requested = np.asarray(definition['body_ids'], dtype=np.int64)
        positions = np.searchsorted(index.ids, requested)
        valid = positions < len(index.ids)
        valid &= index.ids[np.minimum(positions, len(index.ids)-1)] == requested
        if not valid.all():
            raise ValueError('Missing grouping members: ' + ', '.join(str(x) for x in requested[~valid]))
        # An explicit drill-down core must belong to the chosen scope before
        # additional annotation filters are applied.
        if definition['mode'] == 'case':
            _, original = _scope_file(case_path)
            outside = np.setdiff1d(requested, original)
            if len(outside):
                raise ValueError('Drill-down members outside calculation scope: ' + ', '.join(map(str, outside)))
        ids = np.intersect1d(ids, requested, assume_unique=True)
    if len(ids) > definition['budgets']['max_nodes']:
        raise MemoryError('Grouping member count exceeds max_nodes')
    if not len(ids):
        raise ValueError('Grouping selection has no members')
    return ids, case_id


def _filtered_ids(index, ids, filters):
    """Filter only explicit bounded members, including missing annotations."""
    index._where(filters)
    kept = []
    for first in range(0, len(ids), 900):
        for node in index.nodes(ids[first:first+900]):
            accepted = True
            for field, wanted in filters.items():
                if wanted is None or wanted == '':
                    continue
                if field == 'q':
                    if node['category'] == 'unannotated':
                        matches = wanted == node['bodyId']
                    else:
                        matches = any(wanted.casefold() in str(node.get(key) or '').casefold() for key in ('bodyId', 'name', 'instance', 'type'))
                    accepted &= matches
                else:
                    values = wanted if isinstance(wanted, (list, tuple)) else [wanted]
                    accepted &= (str(node.get(field)) in [str(value) for value in values])
                if not accepted:
                    break
            if accepted:
                kept.append(int(node['bodyId']))
    return np.asarray(kept, dtype=np.int64)


def _values(index, ids, field):
    values = [None] * len(ids)
    connection = index._connect()
    try:
        for first in range(0, len(ids), 900):
            block = [int(x) for x in ids[first:first+900]]
            query = 'SELECT bodyId,metadata FROM nodes WHERE bodyId IN (' + ','.join('?' for _ in block) + ')'
            for body_id, payload in connection.execute(query, block):
                value = json.loads(payload).get(field) if payload else None
                if value is not None and not (isinstance(value, float) and not math.isfinite(value)):
                    value = str(value)
                    if not value.strip():
                        value = None
                values[int(np.searchsorted(ids, body_id))] = value
    finally:
        connection.close()
    labels = sorted(set(values), key=lambda x: (x is None, x or ''))
    mapping = {value: i for i, value in enumerate(labels)}
    membership = np.fromiter((mapping[value] for value in values), dtype=np.int32, count=len(values))
    return labels, membership


def _plan(index, definition, case_path, reuse_case_path):
    definition = _definition(index, definition)
    ids, case_id = _members(index, definition, case_path)
    positions = np.searchsorted(index.ids, ids)
    labels, membership = _values(index, ids, definition['field'])
    incoming, outgoing = index.incoming, index.outgoing
    scan_edges = int(np.sum(incoming.indptr[positions+1] - incoming.indptr[positions]))
    scan_edges += int(np.sum(outgoing.indptr[positions+1] - outgoing.indptr[positions]))
    reuse = None
    candidates = [p for p in (reuse_case_path, case_path if definition['mode'] == 'case' else None) if p]
    for candidate in candidates:
        try:
            manifest, case_ids = _scope_file(candidate)
            if (manifest.get('source_index_id') == index.manifest['index_id'] and
                    manifest.get('format') == 'csr-arrays-v1' and np.array_equal(np.sort(case_ids), ids)):
                reuse = str(candidate)
                scan_edges = int(manifest.get('scan', {}).get('internal_edges', 0)) * 2
                if scan_edges == 0:
                    scan_edges = int(np.load(Path(candidate)/'counts_data.npy', mmap_mode='r').size) * 2
                break
        except (OSError, ValueError, KeyError):
            continue
    # Conservative group-key dictionary bound plus numeric member/transpose
    # workspace; no dense neuron adjacency or global-position lookup is made.
    pair_bound = min(len(labels) ** 2, scan_edges // 2)
    estimated = len(ids) * 96 + pair_bound * 256 + (scan_edges // 2 * 20 if reuse else 4 * 1024 ** 2)
    errors = []
    if len(labels) > definition['budgets']['max_groups']:
        errors.append(f"{len(labels)} groups exceed max_groups={definition['budgets']['max_groups']}")
    if scan_edges > definition['budgets']['max_edges']:
        errors.append(f"Complete incoming/outgoing scan requires {scan_edges} edges; max_edges={definition['budgets']['max_edges']}")
    if estimated > definition['budgets']['max_bytes']:
        errors.append(f"Conservative aggregation workspace {estimated} bytes exceeds max_bytes={definition['budgets']['max_bytes']}")
    preview = dict(compatible=not errors, build_allowed=not errors, errors=errors,
                   node_count=len(ids), group_count=len(labels), scan_edges=scan_edges,
                   estimated_bytes=estimated, estimate_kind='conservative bound, not measured RSS',
                   reuse_case_path=reuse, definition=definition,
                   identity=dict(source_index_id=index.manifest['index_id'], case_id=case_id))
    return preview, ids, positions, labels, membership


def preview_grouping(index, definition, case_path=None, reuse_case_path=None):
    try:
        return _plan(index, definition, case_path, reuse_case_path)[0]
    except (ValueError, KeyError, MemoryError, OSError) as error:
        return dict(compatible=False, build_allowed=False, errors=[str(error)], node_count=None,
                    group_count=None, scan_edges=None, estimated_bytes=None, reuse_case_path=None)


def aggregate_groups(index, definition, case_path=None, reuse_case_path=None,
                     cancel=lambda: False, progress=None):
    cancel = cancel or (lambda: False)
    started = time.perf_counter()
    preview, ids, positions, labels, membership = _plan(index, definition, case_path, reuse_case_path)
    base = dict(kind='group_connections', schema_version=1, identity=preview['identity'],
                definition=preview['definition'], status='budget_exceeded', errors=preview['errors'],
                metrics=dict(node_count=len(ids), group_count=len(labels), scanned_edges=0,
                             estimated_bytes=preview['estimated_bytes']))
    if not preview['build_allowed']:
        return base
    pairs = defaultdict(lambda: [0, 0, 0, 0, 0])
    scanned = 0
    arrays = []
    if cancel():
        base['status'] = 'cancelled'
        return base
    if preview['reuse_case_path']:
        path = Path(preview['reuse_case_path'])
        _, case_ids = _scope_file(path)
        arrays = [np.load(path / f'counts_{name}.npy', mmap_mode='r') for name in ('data', 'indices', 'indptr')]
        original = sparse.csr_matrix(tuple(arrays), shape=(len(ids), len(ids)), copy=False)
        order = np.argsort(case_ids)
        matrix = original if np.array_equal(order, np.arange(len(ids))) else original[order][:, order]
        outgoing = matrix.transpose().tocsr()
        incoming = matrix
        row_positions = np.arange(len(ids))
        direct = True
    else:
        incoming, outgoing = index.incoming, index.outgoing
        row_positions = positions
        direct = False
    try:
        for direction, matrix in (('incoming', incoming), ('outgoing', outgoing)):
            for local_row, pos in enumerate(row_positions):
                if cancel():
                    base['status'] = 'cancelled'
                    base['metrics'].update(scanned_edges=scanned, elapsed_seconds=time.perf_counter()-started)
                    return base
                start, stop = map(int, matrix.indptr[pos:pos+2])
                row_groups = []
                for first in range(start, stop, 65536):
                    if cancel():
                        base['status'] = 'cancelled'
                        base['metrics'].update(scanned_edges=scanned, elapsed_seconds=time.perf_counter()-started)
                        return base
                    last = min(stop, first+65536)
                    neighbors = matrix.indices[first:last]
                    values = matrix.data[first:last]
                    scanned += last-first
                    if direct:
                        local = neighbors
                    else:
                        local = np.searchsorted(positions, neighbors)
                        mask = local < len(positions)
                        mask &= positions[np.minimum(local, len(positions)-1)] == neighbors
                        local, values = local[mask], values[mask]
                    if not len(local):
                        continue
                    partner_groups = membership[local]
                    unique, inverse = np.unique(partner_groups, return_inverse=True)
                    row_groups.append(unique)
                    if direction == 'incoming':
                        contacts = np.zeros(len(unique), dtype=np.int64)
                        np.add.at(contacts, inverse, values)
                        edges = np.bincount(inverse, minlength=len(unique))
                        target = int(membership[local_row])
                        for i, source in enumerate(unique):
                            item = pairs[(int(source), target)]
                            item[0] += int(contacts[i])
                            item[1] += int(edges[i])
                        self_mask = local == local_row
                        if np.any(self_mask):
                            pairs[(target, target)][4] += int(self_mask.sum())
                if row_groups:
                    unique = np.unique(np.concatenate(row_groups))
                    group = int(membership[local_row])
                    for partner in unique:
                        key = (int(partner), group) if direction == 'incoming' else (group, int(partner))
                        pairs[key][3 if direction == 'incoming' else 2] += 1
                if progress and (local_row % 512 == 0 or local_row+1 == len(ids)):
                    progress(dict(phase='group_'+direction, completed=local_row+1, total=len(ids),
                                  scanned_edges=scanned, required_edges=preview['scan_edges']))
        if cancel():
            base['status'] = 'cancelled'
            base['metrics'].update(scanned_edges=scanned, elapsed_seconds=time.perf_counter()-started)
            return base
        keys = sorted(pairs)
        count = len(labels)
        arrays_out = dict(members=ids, membership=membership,
                          source=np.asarray([key[0] for key in keys], dtype=np.int32),
                          target=np.asarray([key[1] for key in keys], dtype=np.int32))
        for column, name in enumerate(('contacts', 'edges', 'senders', 'receivers', 'self_edges')):
            arrays_out[name] = np.fromiter((pairs[key][column] for key in keys), dtype=np.int64, count=len(keys))
        full_in, full_out = np.zeros(count, dtype=np.int64), np.zeros(count, dtype=np.int64)
        np.add.at(full_in, membership, index.total_input[positions])
        np.add.at(full_out, membership, index.total_output[positions])
        internal_in, internal_out = np.zeros(count, dtype=np.int64), np.zeros(count, dtype=np.int64)
        np.add.at(internal_in, arrays_out['target'], arrays_out['contacts'])
        np.add.at(internal_out, arrays_out['source'], arrays_out['contacts'])
        group_counts = np.bincount(membership, minlength=count)
        groups = [dict(group_id=i, name=label if label is not None else '(缺失注释)', value=label,
                       node_count=int(group_counts[i]), full_input=int(full_in[i]), full_output=int(full_out[i]),
                       internal_input=int(internal_in[i]), internal_output=int(internal_out[i]),
                       external_input=int(full_in[i]-internal_in[i]), external_output=int(full_out[i]-internal_out[i]))
                  for i, label in enumerate(labels)]
        base.update(status='complete', groups=groups, arrays=arrays_out, errors=[])
        base['metrics'].update(internal_edges=int(arrays_out['edges'].sum()),
                               internal_contacts=int(arrays_out['contacts'].sum()),
                               group_pairs=len(keys), scanned_edges=scanned,
                               elapsed_seconds=time.perf_counter()-started,
                               reuse_case=bool(preview['reuse_case_path']))
        return base
    finally:
        # Close only our reuse mmap handles; never close the shared global index.
        for array in arrays:
            if getattr(array, '_mmap', None) is not None:
                array._mmap.close()


def _complete(report):
    if report.get('kind') != 'group_connections' or report.get('status') != 'complete':
        raise ValueError('Grouping statistics are not complete; no zero/connection claims available')


def _group(report, group_id):
    _complete(report)
    if type(group_id) is not int or not 0 <= group_id < len(report['groups']):
        raise ValueError('Unknown group_id')
    return report['groups'][group_id]


def group_summary(report):
    return {key: value for key, value in report.items() if key != 'arrays'}


def group_page(report, q='', sort='name', offset=0, limit=30):
    _complete(report)
    _paging(offset, limit, maximum=200)
    if not isinstance(q, str) or len(q) > 500:
        raise ValueError('Group search must be text of at most 500 characters')
    fields = {'name': ('name', False), 'members': ('node_count', True), 'node_count': ('node_count', True),
              'contacts': ('internal_output', True), 'input': ('internal_input', True), 'output': ('internal_output', True)}
    if sort not in fields:
        raise ValueError('Unknown group sort')
    groups = [group for group in report['groups'] if q.casefold() in group['name'].casefold()]
    field, descending = fields[sort]
    groups.sort(key=lambda g: ((-g[field] if descending else g[field]), g['name'], g['group_id']))
    return dict(groups=groups[offset:offset+limit], total=len(groups), offset=offset, limit=limit)


def _cell(report, k):
    arrays = report['arrays']
    source, target = int(arrays['source'][k]), int(arrays['target'][k])
    contacts = int(arrays['contacts'][k])
    full_input = report['groups'][target]['full_input']
    return dict(source=source, target=target, contacts=contacts,
                edges=int(arrays['edges'][k]), senders=int(arrays['senders'][k]),
                receivers=int(arrays['receivers'][k]), self_edges=int(arrays['self_edges'][k]),
                input_share=contacts/full_input if full_input else None)


def matrix_page(report, source_ids, target_ids):
    _complete(report)
    if not isinstance(source_ids, list) or not isinstance(target_ids, list) or len(source_ids)*len(target_ids) > 10000:
        raise ValueError('Matrix page exceeds 10000 cells')
    for item in source_ids + target_ids:
        _group(report, item)
    arrays = report['arrays']
    mask = np.isin(arrays['source'], source_ids) & np.isin(arrays['target'], target_ids)
    return dict(cells=[_cell(report, int(k)) for k in np.flatnonzero(mask)],
                source_ids=source_ids, target_ids=target_ids, complete=True)


def group_relations(report, group_id, direction='outgoing', limit=50):
    group = _group(report, group_id)
    _direction(direction)
    _paging(0, limit, maximum=10000)
    arrays = report['arrays']
    field, partner = ('source', 'target') if direction == 'outgoing' else ('target', 'source')
    indices = np.flatnonzero(arrays[field] == group_id)
    indices = sorted(indices, key=lambda k: (-int(arrays['contacts'][k]), int(arrays[partner][k])))
    rows = []
    for k in indices[:limit]:
        row = _cell(report, int(k))
        other = report['groups'][int(arrays[partner][k])]
        row.update(group_id=other['group_id'], name=other['name'])
        rows.append(row)
    return dict(relations=rows, group=group, direction=direction, total=len(indices))


def _direction(direction):
    if direction not in ('incoming', 'outgoing'):
        raise ValueError('Direction must be incoming or outgoing')


def _vector(report, group_id, direction):
    _group(report, group_id)
    _direction(direction)
    a = report['arrays']
    field, partner = ('source', 'target') if direction == 'outgoing' else ('target', 'source')
    mask = a[field] == group_id
    return {int(k): int(v) for k, v in zip(a[partner][mask], a['contacts'][mask])}


def _totals(group, direction):
    side = 'output' if direction == 'outgoing' else 'input'
    return dict(internal=group['internal_'+side], external=group['external_'+side], full=group['full_'+side])


def compare_group_features(report, a, b, direction='outgoing'):
    ga, gb = _group(report, a), _group(report, b)
    va, vb = _vector(report, a, direction), _vector(report, b, direction)
    total_a, total_b = sum(va.values()), sum(vb.values())
    partners = []
    for key in sorted(set(va) | set(vb), key=lambda k: (-max(va.get(k, 0), vb.get(k, 0)), k)):
        ca, cb = va.get(key, 0), vb.get(key, 0)
        partners.append(dict(group_id=key, name=report['groups'][key]['name'], a_contacts=ca, b_contacts=cb,
                             a_share=ca/total_a if total_a else None, b_share=cb/total_b if total_b else None,
                             relation='shared' if ca and cb else ('a_only' if ca else 'b_only')))
    return dict(a=ga, b=gb, direction=direction, partners=partners,
                a_totals=_totals(ga, direction), b_totals=_totals(gb, direction),
                share_denominator='all within-analysis partners in this direction')


def similar_groups(report, group_id, direction='outgoing', limit=50):
    _group(report, group_id)
    _direction(direction)
    _paging(0, limit, maximum=10000)
    arrays = report['arrays']
    n = len(report['groups'])
    matrix = sparse.csr_matrix((arrays['contacts'].astype(np.float64), (arrays['source'], arrays['target'])), shape=(n, n))
    if direction == 'incoming':
        matrix = matrix.transpose().tocsr()
    squared = np.asarray(matrix.multiply(matrix).sum(axis=1)).ravel()
    dot = np.asarray((matrix @ matrix.getrow(group_id).transpose()).toarray()).ravel()
    rows = []
    for k, group in enumerate(report['groups']):
        if k == group_id:
            continue
        denominator = math.sqrt(float(squared[k]*squared[group_id]))
        similarity = min(1., max(0., float(dot[k]/denominator))) if denominator else None
        row = dict(group, similarity=similarity)
        rows.append(row)
    rows.sort(key=lambda row: (row['similarity'] is None, -row['similarity'] if row['similarity'] is not None else 0,
                               row['name'], row['group_id']))
    return dict(groups=rows[:limit], direction=direction, group_id=group_id, total=len(rows),
                dimensions=n, definition='cosine of complete within-analysis group contact vectors')


def _paging(offset, limit, maximum=1000):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= maximum:
        raise ValueError(f'offset must be nonnegative and limit must be 1..{maximum}')


def _identity(index, report):
    _complete(report)
    if report['identity']['source_index_id'] != index.manifest['index_id']:
        raise ValueError('Grouping belongs to a different local index instance')


def pair_details(index, report, a, b, offset=0, limit=100, scan_limit=1000000):
    _identity(index, report)
    _group(report, a)
    _group(report, b)
    _paging(offset, limit)
    if type(scan_limit) is not int or scan_limit <= 0:
        raise ValueError('scan_limit must be positive')
    arrays = report['arrays']
    sources = arrays['members'][arrays['membership'] == a]
    targets = arrays['members'][arrays['membership'] == b]
    source_positions = np.searchsorted(index.ids, sources)
    target_positions = np.searchsorted(index.ids, targets)
    outgoing = index.outgoing
    required = int(np.sum(outgoing.indptr[source_positions+1]-outgoing.indptr[source_positions]))
    if required > scan_limit:
        return dict(edges=[], total=None, offset=offset, limit=limit, scan_complete=False,
                    required_edges=required, scanned_edges=0)
    found_source, found_target, found_contacts = [], [], []
    for pos in source_positions:
        start, stop = map(int, outgoing.indptr[pos:pos+2])
        for first in range(start, stop, 65536):
            last = min(stop, first+65536)
            neighbors = outgoing.indices[first:last]
            local = np.searchsorted(target_positions, neighbors)
            mask = local < len(target_positions)
            mask &= target_positions[np.minimum(local, len(target_positions)-1)] == neighbors
            if mask.any():
                count = int(mask.sum())
                found_source.append(np.full(count, index.ids[pos], dtype=np.int64))
                found_target.append(index.ids[neighbors[mask]])
                found_contacts.append(outgoing.data[first:last][mask])
    src = np.concatenate(found_source) if found_source else np.empty(0, dtype=np.int64)
    dst = np.concatenate(found_target) if found_target else np.empty(0, dtype=np.int64)
    contacts = np.concatenate(found_contacts) if found_contacts else np.empty(0, dtype=np.int64)
    order = np.lexsort((dst, src, -contacts))[offset:offset+limit]
    node_ids = np.union1d(src[order], dst[order])
    metadata = {node['bodyId']: node for node in index.nodes(node_ids)}
    rows = [dict(source=str(src[k]), target=str(dst[k]), contacts=int(contacts[k]),
                 source_node=metadata[str(src[k])], target_node=metadata[str(dst[k])]) for k in order]
    return dict(edges=rows, total=len(src), offset=offset, limit=limit,
                scan_complete=True, required_edges=required, scanned_edges=required)


def select_group_members(index, report, group_ids, filters=None):
    _identity(index, report)
    if not isinstance(group_ids, list) or not group_ids:
        raise ValueError('Select at least one group')
    for group_id in group_ids:
        _group(report, group_id)
    arrays = report['arrays']
    ids = arrays['members'][np.isin(arrays['membership'], group_ids)]
    if filters:
        ids = _filtered_ids(index, ids, filters)
    return dict(body_ids=[str(value) for value in ids], node_count=len(ids),
                group_ids=sorted(set(group_ids)), identity=report['identity'], filters=filters or {})


def save_grouping(root, report):
    if report.get('kind') != 'group_connections' or report.get('schema_version') != 1:
        raise ValueError('Unsupported grouping report')
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    name = 'group-connections-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    destination = root / name
    staging = root / ('.'+name+'.partial')
    staging.mkdir()
    try:
        header = group_summary(report)
        header['artifact_id'] = name
        if report.get('status') == 'complete':
            np.savez_compressed(staging / 'arrays.npz', **{key: report['arrays'][key] for key in ARRAY_NAMES})
            header['arrays_file'] = 'arrays.npz'
        (staging / 'group-connections.json').write_text(json.dumps(header, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        staging.rename(destination)
    except Exception:
        # A hidden incomplete artifact is deliberately not published as usable.
        raise
    return dict(artifact_id=name, path=str(destination), summary_path=str(destination/'group-connections.json'))


def load_grouping(path, index=None):
    path = Path(path)
    header_path = path / 'group-connections.json' if path.is_dir() else path
    report = json.loads(header_path.read_text(encoding='utf-8'))
    if report.get('kind') != 'group_connections' or report.get('schema_version') != 1:
        raise ValueError('Unsupported grouping report format')
    identity = report.get('identity')
    if (not isinstance(identity, dict) or not isinstance(identity.get('source_index_id'), str)
            or not identity['source_index_id'] or 'case_id' not in identity
            or (identity['case_id'] is not None and not isinstance(identity['case_id'], str))):
        raise ValueError('Saved grouping has no valid local data identity')
    if report.get('status') not in ('complete', 'cancelled', 'budget_exceeded', 'failed'):
        raise ValueError('Saved grouping has an unknown completion status')
    if index is not None and report['identity']['source_index_id'] != index.manifest['index_id']:
        raise ValueError('Saved grouping belongs to a different index instance')
    if report['status'] == 'complete':
        if not isinstance(report.get('groups'), list) or not isinstance(report.get('metrics'), dict):
            raise ValueError('Complete grouping is missing group summaries')
        if report.get('arrays_file') != 'arrays.npz':
            raise ValueError('Invalid grouping array reference')
        with np.load(header_path.parent/'arrays.npz', allow_pickle=False) as arrays:
            if set(arrays.files) != set(ARRAY_NAMES):
                raise ValueError('Complete grouping is missing required sparse/membership arrays')
            report['arrays'] = {key: arrays[key] for key in ARRAY_NAMES}
        members, membership = report['arrays']['members'], report['arrays']['membership']
        if len(members) != len(membership) or len(members) != report['metrics']['node_count']:
            raise ValueError('Saved grouping membership size mismatch')
        if len(members) and (np.any(members[1:] <= members[:-1]) or np.any(membership < 0) or np.any(membership >= len(report['groups']))):
            raise ValueError('Invalid saved grouping membership')
    return report
