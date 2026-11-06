"""Connection-count coverage and bounded external input queries."""
import copy
import numpy as np
from . import MODEL_VERSION
from .selection import canonical_ids
from .simulation import Experiment, effective_observations, intervention_indices


def _summary(rows):
    inside = sum(row['internal_input_contacts'] for row in rows)
    total = sum(row['total_input_contacts'] for row in rows)
    return dict(internal_input_contacts=inside, total_input_contacts=total,
                external_input_contacts=total-inside, input_fraction=inside/total if total else None)


def input_coverage(case, experiment=None, node_ids=None):
    nodes = case['nodes']
    internal = np.asarray(case['counts'].sum(axis=1)).ravel()
    rows = {}
    for pos, node in enumerate(nodes):
        total = int(node['total_input']); inside = int(internal[pos])
        if inside > total:
            raise ValueError('Internal input exceeds saved full-input denominator')
        body = str(node['bodyId'])
        rows[body] = dict(body_id=body, type=node.get('type'), category=node.get('category', 'other'),
                         internal_input_contacts=inside, total_input_contacts=total,
                         external_input_contacts=total-inside, input_fraction=inside/total if total else None)
    groups = []
    def add(key, name, role, ids):
        selected = list(ids)
        missing = sorted(set(selected)-set(rows), key=int)
        if missing:
            raise ValueError('Coverage members outside current scope: '+', '.join(missing))
        members = [rows[body] for body in sorted(set(selected), key=int)]
        groups.append(dict(key=key, name=name, role=role, body_ids=[row['body_id'] for row in members],
                           summary=_summary(members), nodes=members))
    if experiment is not None:
        cfg = Experiment.from_dict(experiment) if isinstance(experiment, dict) else experiment
        for item in effective_observations(nodes, cfg):
            add('observation:'+item['name'], item['name'], 'observation', item['body_ids'])
        if cfg.intervention_events is not None:
            from .interventions import intervention_node_ids,intervention_edge_ids
            selected=intervention_node_ids(nodes,cfg)
            add('intervention-edges','干预连接端点','edge_endpoint',
                sorted({body for edge in intervention_edge_ids(cfg) for body in edge},key=int))
        elif cfg.intervention_ids is not None:
            selected = list(cfg.intervention_ids)
        else:
            selected = [str(nodes[pos]['bodyId']) for pos in intervention_indices(nodes, cfg)]
        add('intervention', '干预节点', 'intervention', selected)
    if node_ids is not None:
        add('selected', '指定节点', 'selected', canonical_ids(node_ids) if node_ids else [])
    manifest = case['manifest']
    return dict(kind='scope_boundary', schema_version=1,
                identity=dict(case_id=manifest['case_id'], source_index_id=manifest.get('source_index_id'),
                              model_version=manifest.get('model_version', MODEL_VERSION)),
                scope=dict(node_count=len(nodes), internal_edges=int(case['counts'].nnz),
                           **_summary(list(rows.values())), selection=copy.deepcopy(manifest.get('selection', {}))),
                groups=groups, quantity='connection-count coverage')


def _check_index(index, case):
    if case['manifest'].get('source_index_id') != index.manifest.get('index_id'):
        raise ValueError('Scope and global index identities differ')


def external_inputs(index, case, body_ids, *, category='neuron', scan_limit=1000000, limit=50, offset=0):
    _check_index(index, case)
    if category not in ('neuron', 'glia', 'other', 'unannotated', 'all'):
        raise ValueError('Unknown record category')
    if type(scan_limit) is not int or not 1 <= scan_limit <= 5000000:
        raise ValueError('scan_limit must be 1..5000000 indexed edges')
    if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
        raise ValueError('External input pagination requires limit 1..1000 and nonnegative offset')
    ids = canonical_ids(body_ids)
    available = {str(n['bodyId']) for n in case['nodes']}
    if not set(ids) <= available:
        raise ValueError('External input targets must belong to the current scope')
    core = set(map(int, available)); matrix = index.incoming
    positions = np.searchsorted(index.ids, np.array(ids, dtype=np.int64))
    total_required = sum(int(matrix.indptr[p+1]-matrix.indptr[p]) for p in positions)
    scanned = 0; aggregate = {}
    for body, pos in zip(ids, positions):
        start, stop = map(int, matrix.indptr[pos:pos+2])
        for first in range(start, stop, 65536):
            last = min(stop, first+65536, first+scan_limit-scanned)
            if last <= first:break
            for upstream, value in zip(matrix.indices[first:last], matrix.data[first:last]):
                upstream = int(index.ids[upstream])
                if upstream in core:continue
                entry = aggregate.setdefault(upstream, dict(count=0, targets={}))
                entry['count'] += int(value)
                entry['targets'][body] = entry['targets'].get(body, 0)+int(value)
            scanned += last-first
            if scanned >= scan_limit:break
        if scanned >= scan_limit:break
    ordered = sorted(aggregate, key=lambda body:(-aggregate[body]['count'], body))
    page = ordered[offset:offset+limit]
    metadata = index.nodes([str(body) for body in page]) if hasattr(index, 'nodes') else [index.node(str(body)) for body in page]
    rows = []
    for body, node in zip(page, metadata):
        entry = aggregate[body]; cat = node.get('category', 'unannotated')
        rows.append(dict(body_id=str(body), type=node.get('type'), category=cat, count=entry['count'],
                         targets=[dict(body_id=target, count=count) for target, count in sorted(entry['targets'].items(), key=lambda p:int(p[0]))],
                         eligible=category=='all' or cat==category))
    return dict(kind='scope_external_inputs', case_id=case['manifest']['case_id'],
                source_index_id=index.manifest.get('index_id'), body_ids=ids, category=category, nodes=rows,
                scanned_edges=scanned, total_required_edges=total_required, scan_complete=scanned==total_required,
                truncated=scanned<total_required, matching_external_count=len(ordered), offset=offset, limit=limit,
                ranking_scope='all requested indexed input edges' if scanned==total_required else 'scanned indexed input prefix',
                aggregate_budget_edges=scan_limit, excluded_members_visible=True)
