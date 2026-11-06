"""Stream the source graph; retain only the selected case and boundary totals."""
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.feather as feather
from scipy import sparse

ANNOTATIONS = 'body-annotations-male-cns-v1.0-minconf-0.5.feather'
WEIGHTS = 'connectome-weights-male-cns-v1.0-minconf-0.5.feather'
CLASSES = {'ALPN': 'input', 'Kenyon_Cell': 'internal', 'MBON': 'output'}


def select_nodes(raw, side='L'):
    columns = ['bodyId', 'type', 'class', 'subclass', 'superclass', 'supertype',
               'somaSide', 'rootSide', 'instance', 'status', 'statusLabel']
    dataset = ds.dataset(Path(raw) / ANNOTATIONS, format='ipc')
    filt = ds.field('class').isin(list(CLASSES)) & (ds.field('somaSide') == side)
    nodes = dataset.to_table(columns=columns, filter=filt).to_pylist()
    nodes.sort(key=lambda node: node['bodyId'])
    if not nodes or len({n['bodyId'] for n in nodes}) != len(nodes):
        raise ValueError('Case nodes must be nonempty and have unique bodyId values')
    for index, node in enumerate(nodes):
        node['index'] = index
        node['role'] = CLASSES[node['class']]
        node['group_label'] = node['type'] or f"({node['class']} 未细分)"
    return nodes


def map_ids(ids, values):
    positions = np.searchsorted(ids, values)
    safe = np.minimum(positions, len(ids) - 1)
    matches = (positions < len(ids)) & (ids[safe] == values)
    return positions, matches


def extract_batches(ids, batches, progress=None):
    """IDs sorted int64; only case edges survive a batch. Counts stay integer."""
    ids = np.asarray(ids, dtype=np.int64)
    if not len(ids) or np.any(ids[1:] <= ids[:-1]):
        raise ValueError('Expected sorted unique int64 case IDs')
    totals = {key: np.zeros(len(ids), dtype=np.int64) for key in
              ['total_input', 'total_output', 'external_input', 'external_output']}
    rows, cols, values = [], [], []
    stats = {'scanned_rows': 0, 'batches': 0, 'internal_source_rows': 0}
    start = time.perf_counter()
    for batch in batches:
        arrays = []
        for name in ['body_pre', 'body_post', 'weight']:
            col = batch.column(batch.schema.get_field_index(name))
            if col.null_count or not pa.types.is_int64(col.type):
                raise ValueError(f'{name}: expected non-null int64')
            arrays.append(col.to_numpy(zero_copy_only=False))
        pre, post, weight = arrays
        if np.any(weight <= 0):
            raise ValueError('Connection counts must be positive')
        pi, in_pre = map_ids(ids, pre)
        qi, in_post = map_ids(ids, post)
        inside = in_pre & in_post
        np.add.at(totals['total_input'], qi[in_post], weight[in_post])
        np.add.at(totals['total_output'], pi[in_pre], weight[in_pre])
        ext_in, ext_out = in_post & ~in_pre, in_pre & ~in_post
        np.add.at(totals['external_input'], qi[ext_in], weight[ext_in])
        np.add.at(totals['external_output'], pi[ext_out], weight[ext_out])
        if np.any(inside):
            rows.append(qi[inside].astype(np.int32))
            cols.append(pi[inside].astype(np.int32))
            values.append(weight[inside].copy())
        stats['scanned_rows'] += batch.num_rows
        stats['batches'] += 1
        stats['internal_source_rows'] += int(inside.sum())
        if progress and stats['batches'] % 250 == 0:
            progress(dict(stats, elapsed_seconds=round(time.perf_counter() - start, 2)))
        # Do not retain full batches or outside edge details.
        del arrays, pre, post, weight, batch, pi, qi, in_pre, in_post, inside, ext_in, ext_out
    n = len(ids)
    if values:
        counts = sparse.coo_matrix((np.concatenate(values),
                                    (np.concatenate(rows), np.concatenate(cols))),
                                   shape=(n, n), dtype=np.int64).tocsr()
        counts.sum_duplicates()
        counts.sort_indices()
    else:
        counts = sparse.csr_matrix((n, n), dtype=np.int64)
    stats['duplicate_internal_rows'] = stats['internal_source_rows'] - counts.nnz
    stats['internal_edges'] = counts.nnz
    stats['elapsed_seconds'] = round(time.perf_counter() - start, 3)
    internal_in = np.asarray(counts.sum(axis=1)).ravel()
    internal_out = np.asarray(counts.sum(axis=0)).ravel()
    np.testing.assert_array_equal(internal_in + totals['external_input'], totals['total_input'])
    np.testing.assert_array_equal(internal_out + totals['external_output'], totals['total_output'])
    return counts, totals, stats


def normalize_counts(counts, total_input):
    inverse = np.divide(1., total_input, out=np.zeros(len(total_input)), where=total_input > 0)
    return (sparse.diags(inverse) @ counts).tocsr()


def prepare_case(raw, destination, side='L', batch_size=65536):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(f'Case already exists; reuse it: {destination}')
    nodes = select_nodes(raw, side)
    ids = np.array([node['bodyId'] for node in nodes], dtype=np.int64)
    source = ds.dataset(Path(raw) / WEIGHTS, format='ipc')
    scanner = source.scanner(columns=['body_pre', 'body_post', 'weight'],
                             batch_size=batch_size, batch_readahead=1,
                             fragment_readahead=1, use_threads=False)
    print(f'Selected {len(nodes)} nodes; streaming weights', flush=True)
    counts, totals, stats = extract_batches(ids, scanner.to_batches(),
                                           lambda info: print(json.dumps(info), flush=True))
    matrix = normalize_counts(counts, totals['total_input'])
    for i, node in enumerate(nodes):
        for key, values in totals.items():
            node[key] = int(values[i])
        node['internal_input_fraction'] = float(matrix[i].sum())
    fingerprint = hashlib.sha256()
    fingerprint.update(json.dumps(nodes, sort_keys=True, ensure_ascii=False).encode())
    for array in [counts.indptr, counts.indices, counts.data]:
        fingerprint.update(array.tobytes())
    roles = {role: sum(node['role'] == role for node in nodes) for role in CLASSES.values()}
    manifest = {
        'case_id': 'malecns-v1.0-' + fingerprint.hexdigest()[:20],
        'case_name': f'PN-KC-MBON · somaSide={side}', 'source_version': 'MaleCNS v1.0 minconf=0.5',
        'selection': {'class': list(CLASSES), 'somaSide': side, 'minimum_weight': 1,
                      'note': 'Soma side is an annotation filter, not a guarantee of unilateral arbors.'},
        'node_count': len(nodes), 'roles': roles, 'scan': stats,
        'internal_contacts': int(counts.sum()),
        'external_input_contacts': int(totals['external_input'].sum()),
        'external_output_contacts': int(totals['external_output'].sum()),
        'total_input_contacts': int(totals['total_input'].sum()),
        'orientation': 'row=post, column=pre',
        'normalization': 'All source-table incoming counts, including sources outside the case; fixed during intervention.',
        'source_files': [ANNOTATIONS, WEIGHTS],
        'source_url': 'https://male-cns.janelia.org/download/',
        'data_attribution': 'MaleCNS dataset, Janelia Research Campus / FlyEM and collaborators. See docs/reference/data-sources.md.',
        'batch_size': batch_size,
    }
    destination.mkdir(parents=True)
    feather.write_feather(pa.Table.from_pylist(nodes), destination / 'nodes.feather')
    coo = counts.tocoo()
    feather.write_feather(pa.table({'body_pre': ids[coo.col], 'body_post': ids[coo.row],
                                  'weight': coo.data, 'pre_index': coo.col, 'post_index': coo.row}),
                         destination / 'edges.feather')
    sparse.save_npz(destination / 'counts.npz', counts)
    sparse.save_npz(destination / 'propagation.npz', matrix)
    (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    return manifest


def load_case(path):
    path = Path(path)
    manifest = json.loads((path / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') == 'csr-arrays-v1':
        nodes = json.loads((path / 'nodes.json').read_text(encoding='utf-8'))
        arrays = {name: [np.load(path / f'{name}_{key}.npy', mmap_mode='r')
                        for key in ('data','indices','indptr')] for name in ('counts','propagation')}
        matrices = {name: sparse.csr_matrix(tuple(values),shape=(len(nodes),len(nodes)),copy=False)
                    for name,values in arrays.items()}
        return dict(nodes=nodes,counts=matrices['counts'],matrix=matrices['propagation'],manifest=manifest,
                    _mmap_arrays=[array for values in arrays.values() for array in values])
    nodes = feather.read_table(path / 'nodes.feather').to_pylist()
    return {'nodes': nodes, 'matrix': sparse.load_npz(path / 'propagation.npz'),
            'counts': sparse.load_npz(path / 'counts.npz'),
            'manifest': json.loads((path / 'manifest.json').read_text(encoding='utf-8'))}


def close_case(case):
    """Release mmap handles before switching/deleting a case on Windows."""
    for array in case.pop('_mmap_arrays', []):
        array._mmap.close()


def groups(case):
    if case['nodes'] and 'memberships' in case['nodes'][0]:
        return {role: sorted({label for n in case['nodes'] for label in n['memberships'].get(role,[])})
                for role in ('input','internal','output')}
    return {role: sorted({n['group_label'] for n in case['nodes'] if n['role'] == role})
            for role in CLASSES.values()}
