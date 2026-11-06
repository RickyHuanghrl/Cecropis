import json
import unittest

import numpy as np
from scipy import sparse

from cecropis.pathways import analyze_pathways


class PathwayChecks(unittest.TestCase):
    def fixture(self):
        ids = [10, 11, 20, 30, 40, 50, 60, 70, 80, 90]
        rows = [(10, 20, 5), (11, 20, 7), (20, 30, 5), (30, 50, 5),
                (20, 40, 5), (40, 60, 5), (20, 70, 5), (70, 20, 5),
                (20, 20, 3), (10, 90, 1), (90, 50, 1)]
        position = {body_id: index for index, body_id in enumerate(ids)}
        counts = sparse.csr_matrix(([value for _, _, value in rows],
                                    ([position[post] for _, post, _ in rows],
                                     [position[pre] for pre, _, _ in rows])), shape=(len(ids), len(ids)), dtype=np.int64)
        return {'nodes': [{'bodyId': body_id, 'type': 'shared' if body_id == 20 else 'T' + str(body_id), 'category': 'neuron'} for body_id in ids],
                'counts': counts, 'manifest': {'case_id': 'fixture', 'case_name': 'fixture'}}

    def request(self, **updates):
        result = {'source_ids': ['10', '11'], 'targets': {'A': ['50'], 'B': ['60']}, 'max_hops': 3, 'min_contacts': 2}
        result.update(updates)
        return result

    def test_multiple_sources_targets_shared_and_exclusive(self):
        result = analyze_pathways(self.fixture(), self.request())
        self.assertEqual(result['kind'], 'pathways')
        self.assertFalse(result['truncated'])
        self.assertEqual(result['shared_ids'], ['20'])
        self.assertEqual(result['exclusive_ids'], {'A': ['30'], 'B': ['40']})
        self.assertEqual(result['targets']['A']['min_hops'], 3)
        self.assertTrue(result['targets']['B']['reachable'])
        self.assertEqual(result['node_count'], 7)
        self.assertEqual(result['edge_count'], 6)
        self.assertEqual(result['scope']['node_count'], 10)
        self.assertEqual(next(node for node in result['nodes'] if node['bodyId'] == '20')['classification'], 'shared')
        self.assertEqual(next(edge for edge in result['edges'] if edge['body_pre'] == '11')['contacts'], 7)
        shared = next(node for node in result['nodes'] if node['bodyId'] == '20')
        self.assertEqual(shared['incoming_contacts'], 12)
        self.assertEqual(shared['outgoing_contacts'], 10)
        self.assertEqual(shared['target_labels'], ['A', 'B'])
        self.assertEqual(sum(group['contacts'] for group in result['groups']['nodes']), 32)
        json.dumps(result, allow_nan=False)

    def test_direction_threshold_and_unreachable(self):
        reverse = analyze_pathways(self.fixture(), self.request(source_ids=['50'], targets={'A': ['10']}))
        self.assertFalse(reverse['targets']['A']['reachable'])
        self.assertEqual(reverse['targets']['A']['intermediate_ids'], [])
        weak = analyze_pathways(self.fixture(), self.request(min_contacts=1, max_hops=2))
        self.assertEqual(weak['exclusive_ids']['A'], ['90'])
        self.assertFalse(weak['targets']['B']['reachable'])
        disconnected = analyze_pathways(self.fixture(), self.request(targets={'A': ['80']}))
        self.assertFalse(disconnected['targets']['A']['reachable'])

    def test_walk_corridor_includes_bounded_cycles(self):
        result = analyze_pathways(self.fixture(), self.request(max_hops=5))
        self.assertEqual(result['shared_ids'], ['20', '70'])
        edges = {(edge['body_pre'], edge['body_post']) for edge in result['edges']}
        self.assertIn(('20', '70'), edges)
        self.assertIn(('70', '20'), edges)
        self.assertIn(('20', '20'), edges)
        self.assertEqual(result['semantics'], 'bounded_directed_walk_corridor')

    def test_budgets_and_detail_limits_are_separate(self):
        constrained = analyze_pathways(self.fixture(), self.request(max_nodes=5, max_edges=20))
        self.assertTrue(constrained['truncated'])
        self.assertLessEqual(constrained['visited']['node_count'], 5)
        self.assertLessEqual(constrained['examined']['edge_count'], 20)
        edges = analyze_pathways(self.fixture(), self.request(max_edges=2))
        self.assertTrue(edges['truncated'])
        self.assertEqual(edges['examined']['edge_count'], 2)
        detail = analyze_pathways(self.fixture(), self.request(detail_nodes=1, detail_edges=1))
        self.assertFalse(detail['truncated'])
        self.assertTrue(detail['details_truncated'])
        self.assertEqual(len(detail['nodes']), 1)
        self.assertEqual(len(detail['edges']), 1)
        self.assertEqual(len(detail['node_ids']), 7)
        self.assertEqual(detail['shared_ids'], ['20'])
        self.assertEqual(sum(group['contacts'] for group in detail['groups']['nodes']), 32)

    def test_global_adapter_uses_existing_bidirectional_arrays(self):
        case = self.fixture()
        class GlobalFixture:
            ids = np.array([node['bodyId'] for node in case['nodes']], dtype=np.int64)
            incoming = case['counts']
            outgoing = case['counts'].transpose().tocsr()
            info = {'index_id': 'global-fixture', 'node_count': len(ids), 'edge_count': incoming.nnz}
            def position(self, body_id):
                index = int(np.searchsorted(self.ids, int(body_id)))
                if index == len(self.ids) or self.ids[index] != int(body_id):
                    raise KeyError(body_id)
                return index
            def nodes(self, body_ids):
                return [dict(case['nodes'][self.position(body_id)], bodyId=str(body_id)) for body_id in body_ids]
        result = analyze_pathways(GlobalFixture(), self.request())
        self.assertEqual(result['scope']['source_index_id'], 'global-fixture')
        self.assertEqual(result['shared_ids'], ['20'])

    def test_invalid_requests_fail_before_exploration(self):
        for update in ({'max_hops': True}, {'max_hops': 13}, {'max_nodes': 3},
                       {'max_edges': 0}, {'detail_nodes': -1}, {'min_contacts': 1.5},
                       {'source_ids': ['999']}, {'targets': {'A': ['50'], 'B': ['60'], 'C': ['80']}},
                       {'unexpected': 1}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                analyze_pathways(self.fixture(), self.request(**update))

    def test_detail_window_keeps_large_id_endpoints_and_shortest_witness(self):
        ids = list(range(1, 101)) + [1000, 2000]
        positions = {body_id: index for index, body_id in enumerate(ids)}
        connections = [(1000, node, 3) for node in range(1, 101)] + [(node, 2000, 2) for node in range(1, 101)]
        counts = sparse.csr_matrix(([contacts for _, _, contacts in connections],
                                    ([positions[post] for _, post, _ in connections],
                                     [positions[pre] for pre, _, _ in connections])), shape=(len(ids), len(ids)))
        case = {'nodes': [{'bodyId': body_id, 'type': 'T'} for body_id in ids], 'counts': counts, 'manifest': {'case_id': 'detail'}}
        result = analyze_pathways(case, {'source_ids': ['1000'], 'targets': {'Goal': ['2000']},
                                        'max_hops': 2, 'detail_nodes': 60, 'detail_edges': 60})
        shown = {node['bodyId'] for node in result['nodes']}
        self.assertTrue({'1000', '2000', '1'} <= shown)
        self.assertEqual(result['targets']['Goal']['witness_ids'], ['1000', '1', '2000'])
        self.assertTrue(result['targets']['Goal']['witness_details_complete'])
        self.assertEqual(result['omitted_endpoint_count'], 0)
        self.assertEqual({(edge['body_pre'], edge['body_post']) for edge in result['edges'][:2]}, {('1000', '1'), ('1', '2000')})


if __name__ == '__main__':
    unittest.main()
