import json
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

import numpy as np
from scipy import sparse

from cecropis.simulation import (Experiment, RecordPolicy, compare, forward,
                                    group_indices, propagate, save_run, simulate)
from cecropis.exploration import compare_conditions, select_nodes
from cecropis.search import sensitivity


class RecordingChecks(unittest.TestCase):
    def fixture(self):
        nodes = [dict(bodyId=b, type=t, role=r, group_label=t, total_input=10)
                 for b, t, r in [(10, 'I', 'input'), (20, 'K', 'internal'),
                                  (30, 'A', 'output'), (40, 'B', 'output')]]
        counts = sparse.csr_matrix(([6, 8, 3, 1], ([1, 2, 3, 1], [0, 1, 1, 2])), shape=(4, 4))
        case = dict(nodes=nodes, counts=counts, matrix=counts / 10, manifest={'case_id': 'record-test'})
        cfg = Experiment(steps=12, input_group='I', input_start=0, input_stop=4,
                         intervention_group='K', intervention_start=2, intervention_stop=7,
                         outputs=('A', 'B'))
        return case, cfg

    def test_selected_times_bind_saved_values_and_full_computation(self):
        case, cfg = self.fixture()
        full = compare(case, cfg, keep_states=True)
        policy = RecordPolicy(body_ids=('40', '20'), steps=(0, 3, 12))
        result = compare(case, cfg, recording=policy)
        self.assertEqual(result['computation_node_count'], 4)
        self.assertEqual(result['intervention_node_count'], 1)
        self.assertEqual(result['series'], full['series'])
        self.assertEqual(result['summary'], full['summary'])
        metadata = result['recording_metadata']
        self.assertEqual(metadata['body_ids'], ['40', '20'])
        self.assertEqual(metadata['time_steps'], [0, 3, 12])
        self.assertEqual(metadata['bytes'], 2 * 3 * 2 * 8)
        for recorded, states in zip(result['states'], full['states']):
            np.testing.assert_array_equal(recorded, states[[0, 3, 12]][:, [3, 1]])
        with tempfile.TemporaryDirectory() as tmp:
            folder = save_run(tmp, result)
            config = json.loads((folder / 'config.json').read_text())
            replay = compare(case, Experiment.from_dict(config['experiment']),
                             recording=RecordPolicy.from_dict(config['recording']))
            self.assertEqual(replay['recording_metadata'], metadata)
            np.testing.assert_array_equal(replay['states'][1], result['states'][1])
            self.assertEqual(json.loads((folder / 'result.json').read_text())['recording_metadata'], metadata)

    def test_streamed_analysis_and_production_paths_do_not_require_history(self):
        case, cfg = self.fixture()
        legacy_b = propagate(case['matrix'], cfg, [0], [1], 1.)
        stats = simulate(case, cfg)
        self.assertIsNone(stats.recorded_states)
        np.testing.assert_array_equal(stats.final, legacy_b[-1])
        np.testing.assert_allclose(stats.activity_sum, legacy_b[:-1].sum(axis=0), rtol=0, atol=0)
        np.testing.assert_allclose(stats.node_sum, legacy_b.sum(axis=0), rtol=0, atol=0)
        from cecropis.signals import incoming_signals
        legacy_i = propagate(case['matrix'], cfg, [0], [1], cfg.gain)
        expected = incoming_signals(case, cfg, 'A', legacy_b, legacy_i, [1])
        with patch('cecropis.simulation.propagate', side_effect=AssertionError('full history used')):
            result = compare(case, cfg)
            select_nodes(case, cfg, 1, 'signal', 'A')
            compare_conditions(case, [dict(name='one', experiment=cfg),
                                      dict(name='two', experiment=replace(cfg, gain=.5))])
            sensitivity(case, cfg)
        self.assertNotIn('states', result)
        np.testing.assert_allclose(result['signals']['A']['baseline_trace'], expected['baseline_trace'], rtol=1e-14)
        self.assertAlmostEqual(result['signals']['A']['baseline_signal'], expected['baseline_signal'])
        self.assertEqual(result['signals']['A']['selected_input_fraction'], expected['selected_input_fraction'])
        wider = dict(case, counts=case['counts'] + sparse.csr_matrix(([1], ([2], [0])), shape=(4, 4)))
        wider['matrix'] = wider['counts'] / 10
        uncapped = compare(wider, cfg)['signals']['A']
        with patch('cecropis.signals.MAX_DETAIL_ROWS', 1):
            capped = compare(wider, cfg)['signals']['A']
        self.assertEqual(capped['baseline_signal'], uncapped['baseline_signal'])
        self.assertEqual(capped['direct_contacts'], uncapped['direct_contacts'])
        self.assertEqual(capped['selected_baseline_signal'], uncapped['selected_baseline_signal'])
        self.assertEqual(len(capped['edges']), 1)
        self.assertTrue(capped['edges_truncated'])
        self.assertEqual(capped['edge_count'], 2)

    def test_generic_membership_keeps_context_nodes_in_state_update(self):
        case, cfg = self.fixture()
        for node in case['nodes']:
            node['memberships'] = {}
            node['role'] = 'context'
        case['nodes'][0]['memberships'] = {'input': ['drive']}
        case['nodes'][2]['memberships'] = {'internal': ['candidate'], 'output': ['readout-a']}
        case['nodes'][3]['memberships'] = {'output': ['readout-b']}
        cfg = replace(cfg, input_group='drive', intervention_group='candidate',
                      outputs=('readout-a', 'readout-b'))
        self.assertEqual(group_indices(case['nodes'], 'internal', '__all__').tolist(), [2])
        result = forward(case, cfg, RecordPolicy(mode='all'))
        self.assertEqual(result['computation_node_count'], 4)
        self.assertGreater(result['states'][0][-1, 1], 0)
        self.assertGreater(result['summary'][0]['baseline_sum'], 0)
        self.assertEqual(result['input_node_count'], 1)

    def test_recording_limits_and_invalid_policies_fail_before_allocating_history(self):
        case, cfg = self.fixture()
        for policy in [RecordPolicy(mode='bogus'), RecordPolicy(step_stride=0),
                       RecordPolicy(body_ids=('999',)), RecordPolicy(body_ids=('20', '20')),
                       RecordPolicy(steps=(13,)), RecordPolicy(steps=(1, 1)),
                       RecordPolicy(max_bytes=2 ** 31), RecordPolicy(mode='all', max_bytes=8)]:
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                compare(case, cfg, recording=policy)
        result = forward(case, cfg, RecordPolicy(body_ids=('20',), step_stride=5))
        self.assertEqual(result['recording_metadata']['time_steps'], [0, 5, 10, 12])
        with tempfile.TemporaryDirectory() as tmp:
            path = save_run(tmp, result)
            self.assertEqual(np.load(path / 'states.npz')['baseline'].shape, (4, 1))
        none = forward(case, cfg, RecordPolicy(mode='none'))
        self.assertNotIn('states', none)
        self.assertEqual(none['recording_metadata']['bytes'], 0)


if __name__ == '__main__':
    unittest.main()
