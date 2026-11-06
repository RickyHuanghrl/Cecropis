"""Freeze real directed connections from a bounded calculation scope."""
import numpy as np


def select_real_edges(case, source_ids, target_ids, *, max_edges=100000, max_bytes=64*1024**2):
    from .simulation import _body_ids
    available = {str(node['bodyId']) for node in case['nodes']}
    sources = _body_ids(source_ids, available)
    targets = _body_ids(target_ids, available)
    if type(max_edges) is not int or not 1 <= max_edges <= 100000:
        raise ValueError('max_edges must be an integer in 1..100000')
    if type(max_bytes) is not int or not 1 <= max_bytes <= 256*1024**2:
        raise ValueError('max_bytes must be an integer in 1..268435456')
    by_id = {str(node['bodyId']): i for i, node in enumerate(case['nodes'])}
    source_indices = np.asarray([by_id[body] for body in sources], dtype=np.int64)
    matrix = case['counts']
    if matrix.format != 'csr':
        raise ValueError('Real connection selection requires CSR counts')
    # Count first; no partially truncated selection is ever returned.
    count, contacts, involved = 0, 0, set()
    edges = []
    scanned = 0
    for body in sorted(targets, key=int):
        row = by_id[body]
        start, stop = map(int, matrix.indptr[row:row+2])
        for offset in range(start, stop, 65536):
            end = min(offset+65536, stop)
            columns, values = matrix.indices[offset:end], matrix.data[offset:end]
            scanned += len(columns)
            positions = np.flatnonzero(np.isin(columns, source_indices) & (values > 0))
            count += len(positions)
            estimated = count*256 + (len(sources)+len(targets))*64 + 65536*24
            if count > max_edges or estimated > max_bytes:
                raise ValueError(f'Real connection selection exceeds budget: at least {count} edges / {estimated} estimated bytes; narrow endpoints or raise the explicit budget')
            for position in positions:
                pre = str(case['nodes'][int(columns[position])]['bodyId'])
                edges.append([pre, body])
                involved.update((pre, body))
                contacts += int(values[position])
    return dict(edges=sorted(edges,key=lambda edge:(int(edge[0]),int(edge[1]))),
        edge_count=count,node_count=len(involved),contacts=contacts,
        source_ids=sorted(sources,key=int),target_ids=sorted(targets,key=int),
        estimated_bytes=count*256+(len(sources)+len(targets))*64+65536*24,
        scanned_edges=scanned,definition='real pre body ID -> post body ID; positive counts within the calculation scope')
