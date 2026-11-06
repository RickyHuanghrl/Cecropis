"""Bounded exact intervention plans on the existing propagation model.

Connection pairs are (sending body ID, receiving body ID). Original counts and
normalization are immutable; event multipliers change only the current update.
"""
import math

import numpy as np

INTERVENTION_SEMANTICS_VERSION = 1
MAX_INTERVENTION_EVENTS = 128
MAX_NODE_TARGETS = 200_000
MAX_EDGE_TARGETS = 100_000
LEGACY_FIELDS = ('intervention_group', 'intervention_ids', 'gain', 'intervention_start', 'intervention_stop')


def neutral_legacy(steps):
    return dict(intervention_group='__event_plan__', intervention_ids=(), gain=1.,
                intervention_start=0, intervention_stop=steps)


def _ids(values, available=None, *, allow_empty=False):
    if not isinstance(values, (list, tuple)) or (not values and not allow_empty):
        raise ValueError('Intervention targets require a nonempty list of body IDs')
    result = []
    for body in values:
        if not isinstance(body, str) or not body.isascii() or not body.isdecimal() or str(int(body)) != body or not 0 < int(body) <= np.iinfo(np.int64).max:
            raise ValueError('Intervention body IDs require canonical positive int64 strings')
        if available is not None and body not in available:
            raise ValueError(f'Intervention body ID outside computation scope: {body}')
        result.append(body)
    return sorted(set(result), key=int)


def normalize_intervention_events(events, steps, nodes=None):
    if not isinstance(events, (list, tuple)) or len(events) > MAX_INTERVENTION_EVENTS:
        raise ValueError(f'intervention_events must contain 0..{MAX_INTERVENTION_EVENTS} events')
    available = {str(n['bodyId']) for n in nodes} if nodes is not None else None
    normalized, names = [], set()
    node_targets = edge_targets = 0
    for raw in events:
        common = {'name', 'type', 'start', 'stop', 'gain', 'enabled'}
        kind = raw.get('type') if isinstance(raw, dict) else None
        targets = {'body_ids'} if kind == 'node_gain' else {'edges'} if kind == 'edge_gain' else set()
        if not isinstance(raw, dict) or not targets or set(raw) != common | targets:
            raise ValueError('Intervention event requires name, type, exact targets, start, stop, gain and enabled')
        name = raw['name']
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or name in names:
            raise ValueError('Intervention names must be distinct nonempty strings of at most 80 characters')
        names.add(name)
        if type(raw['enabled']) is not bool:
            raise ValueError('Intervention enabled must be boolean')
        if type(raw['start']) is not int or type(raw['stop']) is not int or not 0 <= raw['start'] < raw['stop'] <= steps:
            raise ValueError('Intervention interval must satisfy 0 <= start < stop <= steps')
        gain = raw['gain']
        if isinstance(gain, bool) or not isinstance(gain, (int, float)) or not math.isfinite(gain) or not 0 <= gain <= 1:
            raise ValueError('Intervention gain must be finite in [0, 1]')
        item = dict(raw, gain=float(gain))
        if kind == 'node_gain':
            if not isinstance(raw['body_ids'], (list, tuple)) or len(raw['body_ids']) > MAX_NODE_TARGETS:
                raise ValueError(f'Node event exceeds {MAX_NODE_TARGETS} target IDs')
            item['body_ids'] = _ids(raw['body_ids'], available)
            node_targets += len(item['body_ids'])
        else:
            pairs = raw['edges']
            if not isinstance(pairs, (list, tuple)) or not pairs or len(pairs) > MAX_EDGE_TARGETS:
                raise ValueError(f'Edge event requires 1..{MAX_EDGE_TARGETS} real directed pairs')
            checked = []
            for pair in pairs:
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    raise ValueError('Edge targets require [pre body ID, post body ID]')
                _ids(pair, available)
                checked.append(tuple(pair))
            item['edges'] = [list(pair) for pair in sorted(set(checked), key=lambda p: (int(p[0]), int(p[1])))]
            edge_targets += len(item['edges'])
        if node_targets > MAX_NODE_TARGETS or edge_targets > MAX_EDGE_TARGETS:
            raise ValueError(f'Intervention plan exceeds {MAX_NODE_TARGETS} node or {MAX_EDGE_TARGETS} edge targets')
        normalized.append(item)
    return tuple(normalized)


def effective_intervention_events(nodes, cfg):
    if cfg.intervention_events is not None:
        return [dict(event) for event in normalize_intervention_events(cfg.intervention_events, cfg.steps, nodes)]
    from .simulation import intervention_indices
    ids = [str(nodes[i]['bodyId']) for i in intervention_indices(nodes, cfg)]
    if not ids:
        return []
    return [dict(name='legacy', type='node_gain', body_ids=ids, start=cfg.intervention_start,
                 stop=cfg.intervention_stop, gain=cfg.gain, enabled=True)]


def intervention_node_ids(nodes, cfg):
    return sorted({body for e in effective_intervention_events(nodes, cfg)
                   if e['enabled'] and e['type'] == 'node_gain' for body in e['body_ids']}, key=int)


def intervention_edge_ids(cfg):
    return sorted({tuple(pair) for e in (cfg.intervention_events or ())
                   if e['enabled'] and e['type'] == 'edge_gain' for pair in e['edges']},
                  key=lambda pair: (int(pair[0]), int(pair[1])))


def require_legacy_intervention(cfg, operation):
    if cfg.intervention_events is not None:
        raise ValueError(f'{operation} requires the existing single node intervention configuration; event plans are not optimized')
    return cfg


class CompiledInterventions:
    """Resolve IDs and CSR positions once; retain one interval's gain vectors.

    effective_gains(step) returns (node gains, edge gains), indexed by nodes and
    edge_pairs respectively. They are invalidated on the next interval change.
    weighted_adjustment(current, step) is (edge_gain-1)*weight*x_pre(t).
    """
    def __init__(self, case, cfg):
        self.events = effective_intervention_events(case['nodes'], cfg)
        by_id = {str(n['bodyId']): i for i, n in enumerate(case['nodes'])}
        self.node_ids = intervention_node_ids(case['nodes'], cfg)
        self.edge_pairs = intervention_edge_ids(cfg)
        self.node_indices = np.asarray([by_id[b] for b in self.node_ids], dtype=np.int32)
        self.edge_pre = np.asarray([by_id[p] for p, q in self.edge_pairs], dtype=np.int32)
        self.edge_post = np.asarray([by_id[q] for p, q in self.edge_pairs], dtype=np.int32)
        self._node_pos = {b: i for i, b in enumerate(self.node_ids)}
        self._edge_pos = {pair: i for i, pair in enumerate(self.edge_pairs)}
        self.edge_weights = np.zeros(len(self.edge_pairs), dtype=np.float64)
        counts = case.get('counts', case['matrix'])
        matrix = case['matrix']
        # Validate all supplied edges, including disabled events, before running.
        all_pairs = {tuple(pair) for e in self.events if e['type'] == 'edge_gain' for pair in e['edges']}
        for pre, post in all_pairs:
            row, col = by_id[post], by_id[pre]
            if float(counts[row, col]) <= 0:
                raise ValueError(f'Intervention edge does not exist as a real directed connection: {pre} -> {post}')
            if (pre, post) in self._edge_pos:
                self.edge_weights[self._edge_pos[(pre, post)]] = float(matrix[row, col])
        self._compiled = []
        for e in sorted(self.events, key=lambda item: item['name']):
            if not e['enabled']:
                continue
            node = e['type'] == 'node_gain'
            positions = ([self._node_pos[b] for b in e['body_ids']] if node else
                         [self._edge_pos[tuple(pair)] for pair in e['edges']])
            self._compiled.append((e['start'], e['stop'], e['gain'], node, np.asarray(positions, dtype=np.int32)))
        self.boundaries = np.asarray(sorted({0, cfg.steps} | {t for e in self.events if e['enabled'] for t in (e['start'], e['stop'])}), dtype=np.int32)
        self.node_gains = np.ones(len(self.node_ids), dtype=np.float64)
        self.edge_gains = np.ones(len(self.edge_pairs), dtype=np.float64)
        self._interval = None

    def effective_gains(self, step):
        interval = int(np.searchsorted(self.boundaries, step, side='right') - 1)
        if interval != self._interval:
            self.node_gains.fill(1)
            self.edge_gains.fill(1)
            for start, stop, gain, node, positions in self._compiled:
                if start <= step < stop:
                    (self.node_gains if node else self.edge_gains)[positions] *= gain
            self._interval = interval
        return self.node_gains, self.edge_gains

    def weighted_adjustment(self, current, step):
        _, gains = self.effective_gains(step)
        return (gains - 1.) * self.edge_weights * current[self.edge_pre]

    def edge_gain(self, pre_id, post_id, step):
        key = (str(pre_id), str(post_id))
        _, gains = self.effective_gains(step)
        return float(gains[self._edge_pos[key]]) if key in self._edge_pos else 1.

    def node_gain(self, body_id, step):
        gains, _ = self.effective_gains(step)
        key = str(body_id)
        return float(gains[self._node_pos[key]]) if key in self._node_pos else 1.


def preview_interventions(case, cfg):
    cfg.validate(case['nodes'])
    compiled = CompiledInterventions(case, cfg)
    endpoint_ids = sorted({b for pair in compiled.edge_pairs for b in pair}, key=int)
    events = []
    for event in compiled.events:
        entry = dict(event)
        if event['type'] == 'edge_gain':
            by_id = {str(n['bodyId']): i for i, n in enumerate(case['nodes'])}
            entry['edge_count'] = len(event['edges'])
            entry['endpoint_node_count'] = len({b for pair in event['edges'] for b in pair})
            entry['contacts'] = sum(int(case['counts'][by_id[q], by_id[p]]) for p, q in event['edges'])
        else:
            entry['node_count'] = len(event['body_ids'])
        events.append(entry)
    intervals = []
    remaining = 2_000
    for start, stop in zip(compiled.boundaries[:-1], compiled.boundaries[1:]):
        ng, eg = compiled.effective_gains(int(start))
        ni, ei = np.flatnonzero(ng != 1), np.flatnonzero(eg != 1)
        shown_n = ni[:remaining]
        remaining -= len(shown_n)
        shown_e = ei[:remaining]
        remaining -= len(shown_e)
        intervals.append(dict(start=int(start), stop=int(stop),
            active_event_names=[e['name'] for e in compiled.events if e['enabled'] and e['start'] <= start < e['stop']],
            active_node_count=len(ni), active_edge_count=len(ei),
            detail_truncated=(len(shown_n) != len(ni) or len(shown_e) != len(ei)),
            node_gains=[dict(body_id=compiled.node_ids[i], gain=float(ng[i])) for i in shown_n],
            edge_gains=[dict(pre=compiled.edge_pairs[i][0], post=compiled.edge_pairs[i][1], gain=float(eg[i])) for i in shown_e]))
    return dict(intervention_semantics_version=1, events=events,
                node_count=len(compiled.node_ids), edge_count=len(compiled.edge_pairs),
                edge_endpoint_node_count=len(endpoint_ids), edge_endpoint_body_ids=endpoint_ids,
                computation_node_count=len(case['nodes']),
                estimated_working_bytes=(len(compiled.node_ids) * 32 + len(compiled.edge_pairs) * 96),
                intervals=intervals, limits=dict(events=MAX_INTERVENTION_EVENTS, node_targets=MAX_NODE_TARGETS, edge_targets=MAX_EDGE_TARGETS))
