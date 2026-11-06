"""Direct input terms before tanh, with bounded signal-detail working memory.

Whole-output statistics include every selected receiving row. Only detail rows
are ranked and truncated; this is not a decomposition of causal output effects.
"""
import heapq
import numpy as np

from .simulation import observation_indices
from .interventions import CompiledInterventions

MAX_DETAIL_ROWS = 20_000
EDGE_BLOCK_SIZE = 65_536


def output_coefficients(matrix, post):
    """Mean incoming weights for receiving rows, using original CSR buffers.

    Allocate one source-node vector, never a receiving submatrix. Both the
    simulation readout plan and signal report use the same accumulation order.
    """
    if matrix.format != 'csr':
        raise ValueError('Output coefficients expect a CSR propagation matrix')
    if not len(post):
        raise ValueError('Output coefficients need a nonempty receiving group')
    coefficients = np.zeros(matrix.shape[1], dtype=np.float64)
    for row in post:
        start, stop = matrix.indptr[int(row):int(row) + 2]
        for offset in range(int(start), int(stop), EDGE_BLOCK_SIZE):
            end = min(offset + EDGE_BLOCK_SIZE, int(stop))
            np.add.at(coefficients, matrix.indices[offset:end], matrix.data[offset:end])
    coefficients /= len(post)
    return coefficients


def _offer(heap, item, limit):
    if limit <= 0:
        return
    if len(heap) < limit:
        heapq.heappush(heap, item)
    elif item[:3] > heap[0][:3]:
        heapq.heapreplace(heap, item)


def _row_lookup(matrix, row):
    """A row-sized lookup when propagation/counts storage patterns differ."""
    start, stop = matrix.indptr[row:row + 2]
    columns, weights = matrix.indices[start:stop], matrix.data[start:stop]
    if not len(columns):
        return columns, weights
    if np.any(columns[1:] <= columns[:-1]):
        order = np.argsort(columns, kind='stable')
        columns, weights = columns[order], weights[order]
        boundaries = np.r_[0, np.flatnonzero(columns[1:] != columns[:-1]) + 1]
        columns, weights = columns[boundaries], np.add.reduceat(weights, boundaries)
    return columns, weights


def _lookup_weights(columns, weights, requested):
    result = np.zeros(len(requested), dtype=np.float64)
    if not len(columns):
        return result
    positions = np.searchsorted(columns, requested)
    candidates = np.flatnonzero(positions < len(columns))
    matched = candidates[columns[positions[candidates]] == requested[candidates]]
    result[matched] = weights[positions[matched]]
    return result


def incoming_signals(case, cfg, label, baseline, intervention, selected):
    """Aggregate CSR buffers directly, keeping at most MAX_DETAIL_ROWS details.

    Additional storage is O(N + K + B + R): N computation nodes, K detail
    rows, B bounded edge-block length, R the largest receiving row when the
    two CSR storage patterns differ. No output COO/submatrix or all-edge
    temporary is built. Counts and propagation may have different row order.
    """
    post = observation_indices(case['nodes'], cfg, label)
    if not len(post):
        raise ValueError('Signal analysis needs a nonempty output group')
    counts, matrix = case['counts'], case['matrix']
    if counts.format != 'csr' or matrix.format != 'csr':
        raise ValueError('Signal analysis expects CSR counts and propagation matrices')
    n = len(case['nodes'])
    coefficients = output_coefficients(matrix, post)
    contacts_by_source = np.zeros(n, dtype=np.int64)
    selected_mask = np.zeros(n, dtype=bool)
    selected_mask[np.asarray(list(selected), dtype=np.intp)] = True
    body_ids = np.fromiter((int(node['bodyId']) for node in case['nodes']), dtype=np.int64, count=n)
    scale = cfg.alpha * cfg.rho
    streamed = hasattr(baseline, 'activity_sum') and hasattr(intervention, 'activity_sum')
    bsum = np.asarray(baseline.activity_sum) if streamed else baseline[:-1].sum(axis=0)
    isum = np.asarray(intervention.activity_sum) if streamed else intervention[:-1].sum(axis=0)
    adjustments = {}
    compiled = None
    if cfg.intervention_events is not None:
        compiled = CompiledInterventions(case, cfg)
        if streamed:
            adjustments = getattr(intervention, 'edge_adjustment_sums', None) or {}
        else:
            totals = np.zeros(len(compiled.edge_pairs))
            for t in range(cfg.steps):
                totals += compiled.weighted_adjustment(intervention[t], t)
            adjustments = {pair: float(value) for pair, value in zip(compiled.edge_pairs, totals)}
    edge_heap, node_heap = [], []
    direct_contacts, selected_contacts, edge_count = 0, 0, 0
    limit = MAX_DETAIL_ROWS
    for row in post:
        row = int(row)
        ps, pe = matrix.indptr[row:row + 2]
        cs, ce = counts.indptr[row:row + 2]
        norm_columns = matrix.indices[ps:pe]
        count_columns = counts.indices[cs:ce]
        # These are views of at most one receiving row, without copying all
        # selected output edges into another sparse matrix.
        same_pattern = matrix.has_canonical_format and len(norm_columns) == len(count_columns) and np.array_equal(norm_columns, count_columns)
        lookup = None if same_pattern else _row_lookup(matrix, row)
        post_id = int(body_ids[row])
        edge_count += int(ce - cs)
        for start in range(int(cs), int(ce), EDGE_BLOCK_SIZE):
            stop = min(start + EDGE_BLOCK_SIZE, int(ce))
            columns, values = counts.indices[start:stop], counts.data[start:stop]
            np.add.at(contacts_by_source, columns, values)
            direct_contacts += int(values.sum(dtype=np.int64))
            selected_contacts += int(values[selected_mask[columns]].sum(dtype=np.int64))
            if limit <= 0:
                continue
            if same_pattern:
                weights = matrix.data[int(ps) + start - int(cs):int(ps) + stop - int(cs)]
            else:
                weights = _lookup_weights(*lookup, columns)
            signals = scale * weights * bsum[columns] / len(post)
            if len(edge_heap) < limit:
                candidates = range(len(columns))
            else:
                worst = edge_heap[0]
                equal = signals == worst[0]
                pre_ids = body_ids[columns]
                better_tie = (pre_ids < -worst[1]) | ((pre_ids == -worst[1]) & (post_id < -worst[2]))
                candidates = np.flatnonzero((signals > worst[0]) | (equal & better_tie))
            for offset in candidates:
                pre = int(columns[offset])
                _offer(edge_heap, (float(signals[offset]), -int(body_ids[pre]), -post_id,
                                  pre, row, int(values[offset]), float(weights[offset])), limit)
    bsignal, isignal = scale * coefficients * bsum, scale * coefficients * isum
    by_id = {str(node['bodyId']): idx for idx, node in enumerate(case['nodes'])}
    receiving_ids = {str(case['nodes'][int(idx)]['bodyId']) for idx in post}
    for (pre_id, post_id), correction in adjustments.items():
        if post_id in receiving_ids:
            isignal[by_id[pre_id]] += scale * correction / len(post)
    trace_b = np.asarray(baseline.signal_traces[label]) if streamed else scale * (baseline[:-1] @ coefficients)
    trace_i = np.asarray(intervention.signal_traces[label]) if streamed else scale * (intervention[:-1] @ coefficients)
    if not streamed and compiled is not None and len(compiled.edge_pairs):
        mask = np.isin(compiled.edge_post, post)
        for t in range(cfg.steps):
            trace_i[t] += scale * float(compiled.weighted_adjustment(intervention[t], t)[mask].sum()) / len(post)
    total_bsignal = float(trace_b.sum())
    grouped, source_node_count, selected_baseline_signal = {}, 0, 0.
    # Aggregate groups without constructing one dictionary per source node.
    for idx in np.flatnonzero(coefficients):
        idx = int(idx)
        source_node_count += 1
        node = case['nodes'][idx]
        group, role = node.get('group_label', node.get('type')), node.get('role', 'context')
        b, i, contacts = float(bsignal[idx]), float(isignal[idx]), int(contacts_by_source[idx])
        key = (role, group)
        g = grouped.get(key)
        if g is None:
            g = grouped[key] = dict(type=group, role=role, node_count=0,
                contacts=0, baseline_signal=0., intervention_signal=0., selected_signal=0.)
        g['node_count'] += 1
        g['contacts'] += contacts
        g['baseline_signal'] += b
        g['intervention_signal'] += i
        if selected_mask[idx]:
            g['selected_signal'] += b
            selected_baseline_signal += b
        _offer(node_heap, (b, -int(body_ids[idx]), idx), limit)
    for g in grouped.values():
        g['signal_delta'] = g['intervention_signal'] - g['baseline_signal']
    nodes = []
    for _, _, idx in sorted(node_heap, reverse=True):
        node = case['nodes'][idx]
        b, i = float(bsignal[idx]), float(isignal[idx])
        nodes.append(dict(bodyId=str(node['bodyId']), type=node.get('group_label', node.get('type')),
            role=node.get('role', 'context'), selected=bool(selected_mask[idx]),
            contacts=int(contacts_by_source[idx]), normalized_weight=float(coefficients[idx]),
            baseline_activity_sum=float(bsum[idx]), intervention_activity_sum=float(isum[idx]),
            baseline_signal=b, intervention_signal=i, signal_delta=i - b,
            baseline_signal_fraction=b / total_bsignal if total_bsignal > 0 else None))
    edge_rows = []
    for b, _, _, pre, row, count, weight in sorted(edge_heap, reverse=True):
        pair = (str(case['nodes'][pre]['bodyId']), str(case['nodes'][row]['bodyId']))
        i = float(scale * (weight * isum[pre] + adjustments.get(pair, 0.)) / len(post))
        edge_rows.append(dict(body_pre=str(case['nodes'][pre]['bodyId']),
            body_post=str(case['nodes'][row]['bodyId']), contacts=count, normalized_weight=weight,
            baseline_signal=b, intervention_signal=i, signal_delta=i - b))
    total_input = sum(case['nodes'][int(idx)]['total_input'] for idx in post)
    return dict(output=label, output_node_count=len(post), direct_contacts=direct_contacts,
        total_input_contacts=total_input, selected_contacts=selected_contacts,
        selected_input_fraction=selected_contacts / total_input if total_input else 0.,
        external_input_fraction=(total_input - direct_contacts) / total_input if total_input else 0.,
        baseline_signal=total_bsignal, intervention_signal=float(trace_i.sum()),
        signal_delta=float(trace_i.sum() - trace_b.sum()),
        selected_baseline_signal=float(selected_baseline_signal),
        update_steps=list(range(cfg.steps)), baseline_trace=trace_b.tolist(), intervention_trace=trace_i.tolist(),
        nodes=nodes, groups=sorted(grouped.values(), key=lambda g: (-g['baseline_signal'], g['role'], str(g['type']))),
        edges=edge_rows, source_node_count=source_node_count, edge_count=edge_count, detail_row_limit=limit,
        nodes_truncated=source_node_count > len(nodes), edges_truncated=edge_count > len(edge_rows),
        definition='alpha*rho*P(post,pre)*effective_edge_gain(t)*x_pre(t), averaged over output nodes; before tanh; not causal attribution')
