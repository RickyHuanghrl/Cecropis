"""Bounded structural corridors shared by saved cases and the complete index.

Edges point pre -> post. A corridor contains nodes/edges occurring in a directed
walk of at most H edges, so a node may appear at different walk layers. This is
not enumeration of simple paths, a propagation result or causal attribution.
"""
from collections import defaultdict, deque

import numpy as np
from scipy import sparse
from .selection import canonical_ids


DEFAULTS = dict(max_hops=4, min_contacts=1, max_nodes=10000, max_edges=200000,
                detail_nodes=200, detail_edges=500)
BOUNDS = dict(max_hops=(0, 12), min_contacts=(1, 2147483647),
              max_nodes=(1, 200000), max_edges=(1, 5000000),
              detail_nodes=(0, 2000), detail_edges=(0, 5000))


def _ids(value, field):
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 200000:
        raise ValueError(f'{field} requires 1–200000 body IDs')
    return canonical_ids(value)


def _request(request):
    if not isinstance(request, dict):
        raise ValueError('Pathway request must be an object')
    if set(request) - (set(DEFAULTS) | {'source_ids', 'targets'}):
        raise ValueError('Unsupported pathway request field')
    result = dict(DEFAULTS, **request)
    result['source_ids'] = _ids(request.get('source_ids'), 'source_ids')
    targets = request.get('targets')
    if not isinstance(targets, dict) or not 1 <= len(targets) <= 2:
        raise ValueError('targets requires one or two labeled body-ID sets')
    result['targets'] = {}
    reserved = {'shared', 'endpoint', '__proto__', 'constructor', 'prototype'}
    for label, body_ids in targets.items():
        if not isinstance(label, str) or not label.strip() or len(label) > 80 or label in reserved:
            raise ValueError('Target labels must be nonempty, at most 80 characters and unreserved')
        result['targets'][label] = _ids(body_ids, f'targets[{label}]')
    for field, (low, high) in BOUNDS.items():
        value = result[field]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f'{field} must be an integer in [{low}, {high}]')
    seeds = set(result['source_ids'])
    for body_ids in result['targets'].values():
        seeds.update(body_ids)
    if len(seeds) > result['max_nodes']:
        raise ValueError('Source and target endpoints already exceed max_nodes')
    return result


class _Graph:
    def __init__(self, graph):
        self.graph = graph
        self.is_case = isinstance(graph, dict)
        if self.is_case:
            if 'nodes' not in graph or 'counts' not in graph:
                raise ValueError('Case requires real integer connection counts')
            self.ids = np.array([int(node['bodyId']) for node in graph['nodes']], dtype=np.int64)
            self.positions = {int(body_id): index for index, body_id in enumerate(self.ids)}
            if len(self.positions) != len(self.ids):
                raise ValueError('Case body IDs must be unique')
            if not sparse.issparse(graph['counts']):
                raise ValueError('Case connection counts must be a sparse matrix')
            self.incoming = graph['counts'].tocsr(copy=False)
            if not self.incoming.has_canonical_format:
                self.incoming = self.incoming.copy()
                self.incoming.sum_duplicates()
            # A saved case may supply its outgoing view. The global adapter
            # always uses existing disk-backed bidirectional CSR arrays.
            self.outgoing = graph.get('outgoing')
            if self.outgoing is None:
                self.outgoing = self.incoming.transpose().tocsr()
            else:
                self.outgoing = self.outgoing.tocsr(copy=False)
            manifest = graph.get('manifest', {})
            self.scope = dict(kind='case', case_id=manifest.get('case_id'),
                              case_name=manifest.get('case_name'),
                              source_index_id=manifest.get('source_index_id'),
                              node_count=len(self.ids), edge_count=int(self.incoming.nnz))
        else:
            try:
                self.ids, self.incoming, self.outgoing = graph.ids, graph.incoming, graph.outgoing
                info = graph.info
            except AttributeError as error:
                raise ValueError('Graph must be a case or complete GlobalIndex') from error
            self.scope = dict(kind='global', source_index_id=info.get('index_id'),
                              node_count=len(self.ids), edge_count=int(self.incoming.nnz),
                              annotated_record_count=info.get('annotated_record_count'),
                              category_counts=info.get('category_counts'))
        if self.incoming.shape != (len(self.ids), len(self.ids)) or self.incoming.dtype.kind not in 'iu':
            raise ValueError('Connection counts require square integer CSR data matching graph nodes')
        if self.outgoing.shape != self.incoming.shape or self.outgoing.dtype.kind not in 'iu':
            raise ValueError('Outgoing connection counts must match incoming graph shape and integer units')

    def position(self, body_id):
        if self.is_case:
            try:
                return self.positions[int(body_id)]
            except KeyError as error:
                raise ValueError(f'Body ID outside analysis graph: {body_id}') from error
        try:
            return self.graph.position(body_id)
        except KeyError as error:
            raise ValueError(f'Body ID outside analysis graph: {body_id}') from error

    def metadata(self, positions):
        if self.is_case:
            return [self.graph['nodes'][index] for index in positions]
        return self.graph.nodes([str(int(self.ids[index])) for index in positions])


def _explore(graph, sources, targets, request):
    """Alternate bounded forward/reverse layers; retain observed actual edges.

    Node budget is a shared union, including every endpoint. Edge budget counts
    each inspected CSR entry, including below-threshold entries and inspection
    of the same edge from a different frontier. This bounds work as well as
    storage. Rejected new endpoints are counted but never retained in a set.
    """
    admitted = set(sources)
    for values in targets.values():
        admitted.update(values)
    fronts = [(graph.outgoing, False, dict.fromkeys(sources, 0))]
    fronts.extend((graph.incoming, True, dict.fromkeys(values, 0)) for values in targets.values())
    queues = [sorted(depths) for _, _, depths in fronts]
    observed, examined, below, rejected = {}, 0, 0, 0
    node_limited, edge_limited = False, False
    for depth in range(request['max_hops']):
        next_queues = []
        for queue, (matrix, reverse, depths) in zip(queues, fronts):
            following = []
            for node in queue:
                start, stop = matrix.indptr[node:node + 2]
                for offset in range(int(start), int(stop)):
                    if examined == request['max_edges']:
                        edge_limited = True
                        break
                    examined += 1
                    other, contacts = int(matrix.indices[offset]), int(matrix.data[offset])
                    if contacts <= 0:
                        raise ValueError('Connection counts must be positive')
                    if contacts < request['min_contacts']:
                        below += 1
                        continue
                    if other not in admitted:
                        if len(admitted) == request['max_nodes']:
                            rejected += 1
                            node_limited = True
                            continue
                        admitted.add(other)
                    pre, post = (other, node) if reverse else (node, other)
                    observed[(pre, post)] = contacts
                    if other not in depths:
                        depths[other] = depth + 1
                        following.append(other)
                if edge_limited:
                    break
            next_queues.append(sorted(following))
            if edge_limited:
                break
        if edge_limited:
            break
        queues = next_queues
        if not any(queues):
            break
    reasons = []
    if node_limited:
        reasons.append('node_limit')
    if edge_limited:
        reasons.append('edge_limit')
    visited = dict(node_count=len(admitted), source_forward_node_count=len(fronts[0][2]),
                   target_reverse_node_counts={label: len(fronts[index + 1][2]) for index, label in enumerate(targets)},
                   retained_edge_count=len(observed))
    examined_info = dict(edge_count=examined, below_threshold_edge_count=below,
                         omitted_node_incidents=rejected, retained_edge_count=len(observed))
    return observed, visited, examined_info, reasons


def _depths(adjacency, seeds, max_hops, parents=None):
    depths = dict.fromkeys(seeds, 0)
    queue = deque(seeds)
    while queue:
        node = queue.popleft()
        if depths[node] == max_hops:
            continue
        for other in adjacency.get(node, ()):
            if other not in depths:
                depths[other] = depths[node] + 1
                if parents is not None:
                    parents[other] = node
                queue.append(other)
    return depths


def analyze_pathways(graph, request):
    """Return JSON-safe complete corridor ID sets and bounded display details.

    If exploration is truncated, the found corridor is a witnessed subset:
    every reported edge still belongs to a qualifying directed walk, but missing
    paths and shared/exclusive labels cannot be generalized beyond this scope.
    Display truncation is separate and does not shorten exact selection ID sets.
    """
    request = _request(request)
    graph = _Graph(graph)
    sources = [graph.position(body_id) for body_id in request['source_ids']]
    source_set = set(sources)
    targets = {label: [graph.position(body_id) for body_id in body_ids]
               for label, body_ids in request['targets'].items()}
    target_sets = {label: set(values) for label, values in targets.items()}
    observed, visited, examined, reasons = _explore(graph, sources, targets, request)
    outgoing, incoming = defaultdict(list), defaultdict(list)
    for pre, post in observed:
        outgoing[pre].append(post)
        incoming[post].append(pre)
    source_parents = {}
    source_hops = _depths(outgoing, sources, request['max_hops'], source_parents)
    target_hops = {label: _depths(incoming, values, request['max_hops']) for label, values in targets.items()}
    endpoints = set(sources)
    for values in targets.values():
        endpoints.update(values)
    memberships, edge_memberships = defaultdict(list), defaultdict(list)
    intermediate, target_results, witnesses = {}, {}, {}
    canonical = lambda positions: [str(int(graph.ids[index])) for index in sorted(positions, key=lambda item: int(graph.ids[item]))]
    for label, reverse_hops in target_hops.items():
        members = {node for node, hops in source_hops.items()
                   if node in reverse_hops and hops + reverse_hops[node] <= request['max_hops']}
        for node in members:
            memberships[node].append(label)
        qualified_edges = {(pre, post) for pre, post in observed
                           if pre in source_hops and post in reverse_hops and
                           source_hops[pre] + 1 + reverse_hops[post] <= request['max_hops']}
        for edge in qualified_edges:
            edge_memberships[edge].append(label)
        intermediate[label] = members - endpoints
        reachable_targets = [node for node in targets[label] if node in source_hops and source_hops[node] <= request['max_hops']]
        reachable = bool(reachable_targets)
        witness = []
        if reachable:
            witness_node = min(reachable_targets, key=lambda node: (source_hops[node], int(graph.ids[node])))
            witness = [witness_node]
            while witness_node in source_parents:
                witness_node = source_parents[witness_node]
                witness.append(witness_node)
            witness.reverse()
        witnesses[label] = witness
        target_results[label] = dict(reachable=reachable,
            reachability_status='found' if reachable else ('not_found_in_explored_scope' if reasons else 'not_reachable_within_hops'),
            reachable_target_ids=canonical(reachable_targets), intermediate_ids=canonical(intermediate[label]),
            node_ids=canonical(members), node_count=len(members), edge_count=len(qualified_edges),
            min_hops=min((source_hops[node] for node in reachable_targets), default=None),
            witness_ids=[str(int(graph.ids[node])) for node in witness])
    shared = set.intersection(*intermediate.values()) if len(intermediate) == 2 else set()
    exclusive = {label: values - shared for label, values in intermediate.items()}
    selected = set(memberships) | endpoints
    incoming_contacts, outgoing_contacts = defaultdict(int), defaultdict(int)
    for pre, post in edge_memberships:
        outgoing_contacts[pre] += observed[(pre, post)]
        incoming_contacts[post] += observed[(pre, post)]
    # Keep representative real paths visible before filling a display window.
    # Large source/target groups cannot all fit; exact endpoint IDs remain in
    # request/node_ids, and omitted endpoints are reported below.
    priority, prioritized = [], set()
    def prioritize(node):
        if node not in prioritized:
            prioritized.add(node)
            priority.append(node)
    witness_edges = set()
    for label, witness in witnesses.items():
        if witness:
            prioritize(witness[0])
            prioritize(witness[-1])
            witness_edges.update(zip(witness, witness[1:]))
        else:
            prioritize(targets[label][0])
    for witness in witnesses.values():
        for node in witness:
            prioritize(node)
    for node in sorted(endpoints, key=lambda item: int(graph.ids[item])):
        prioritize(node)
    ordered = priority + sorted(selected - prioritized, key=lambda item: (-incoming_contacts[item], int(graph.ids[item])))
    displayed = set(ordered[:request['detail_nodes']])
    for label, witness in witnesses.items():
        target_results[label]['witness_details_complete'] = bool(witness) and all(node in displayed for node in witness)
    node_details, group_nodes, group_edges, types = [], {}, {}, {}
    for start in range(0, len(ordered), 1000):
        positions = ordered[start:start + 1000]
        for position, annotation in zip(positions, graph.metadata(positions)):
            body_id = str(int(graph.ids[position]))
            classification = 'endpoint' if position in endpoints else ('shared' if position in shared else memberships[position][0])
            group_type = annotation.get('type') or annotation.get('group_label') or '(untyped)'
            types[position] = group_type
            group = group_nodes.setdefault(group_type, dict(type=group_type, node_count=0, body_ids=[], classifications={},
                                                           contacts=0, incoming_contacts=0, outgoing_contacts=0))
            group['node_count'] += 1
            group['body_ids'].append(body_id)
            group['incoming_contacts'] += incoming_contacts[position]
            group['outgoing_contacts'] += outgoing_contacts[position]
            group['contacts'] += outgoing_contacts[position]
            group['classifications'][classification] = group['classifications'].get(classification, 0) + 1
            if len(node_details) < request['detail_nodes']:
                detail = {key: annotation.get(key) for key in ('type', 'instance', 'class', 'category', 'status', 'role')}
                detail.update(bodyId=body_id, source=position in source_set,
                              target_labels=memberships.get(position, []),
                              endpoint_target_labels=[label for label, values in target_sets.items() if position in values],
                              corridor_labels=memberships.get(position, []), classification=classification,
                              incoming_contacts=incoming_contacts[position], outgoing_contacts=outgoing_contacts[position],
                              source_hops=source_hops.get(position),
                              target_hops={label: hops[position] for label, hops in target_hops.items() if position in hops})
                node_details.append(detail)
    ordered_edges = sorted(edge_memberships,
        key=lambda edge: (0 if edge in witness_edges and edge[0] in displayed and edge[1] in displayed else
                          (1 if edge[0] in displayed and edge[1] in displayed else 2),
                          -observed[edge], int(graph.ids[edge[0]]), int(graph.ids[edge[1]])))
    displayed_edges = set(ordered_edges[:request['detail_edges']])
    for label, witness in witnesses.items():
        target_results[label]['witness_details_complete'] &= all(edge in displayed_edges for edge in zip(witness, witness[1:]))
    edge_details = []
    for pre, post in ordered_edges:
        group_key = (types[pre], types[post])
        group = group_edges.setdefault(group_key, dict(source_type=group_key[0], target_type=group_key[1], edge_count=0, contacts=0))
        group['edge_count'] += 1
        group['contacts'] += observed[(pre, post)]
        if len(edge_details) < request['detail_edges']:
            edge_details.append(dict(body_pre=str(int(graph.ids[pre])), body_post=str(int(graph.ids[post])),
                                     contacts=observed[(pre, post)], target_labels=edge_memberships[(pre, post)]))
    return dict(kind='pathways', semantics='bounded_directed_walk_corridor', request=request, scope=graph.scope,
                node_count=len(selected), edge_count=len(ordered_edges), node_ids=canonical(selected),
                truncated=bool(reasons), truncation_reasons=reasons,
                classification_scope='observed_edges' if reasons else 'analysis_graph_within_hop_limit',
                budgets={key: request[key] for key in DEFAULTS}, visited=visited, examined=examined,
                targets=target_results, shared_ids=canonical(shared), exclusive_ids={label: canonical(values) for label, values in exclusive.items()},
                nodes=node_details, edges=edge_details,
                details_truncated=len(node_details) < len(selected) or len(edge_details) < len(ordered_edges),
                omitted_endpoint_count=len(endpoints - displayed),
                groups=dict(nodes=[group_nodes[label] for label in sorted(group_nodes)],
                            edges=[group_edges[key] for key in sorted(group_edges)]))
