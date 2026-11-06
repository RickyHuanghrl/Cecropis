import unittest
from dataclasses import replace

import numpy as np
from scipy import sparse

from cecropis.simulation import (Experiment, RecordPolicy, SimulationPlan, compare,
    effective_input_events, effective_observations, input_indices, observation_indices,
    propagate, protocol_key, response_metrics, simulate)
from cecropis.selection import _groups


class MultiProtocolCoreChecks(unittest.TestCase):
    def fixture(self):
        nodes = [dict(bodyId=body, type=kind, role=role, group_label=kind, total_input=10)
                 for body, kind, role in [(10, 'I', 'input'), (20, 'K', 'internal'),
                                          (30, 'A', 'output'), (40, 'B', 'output')]]
        counts = sparse.csr_matrix(([6, 8, 3, 1], ([1, 2, 3, 1], [0, 1, 1, 2])), shape=(4, 4))
        case = dict(nodes=nodes, counts=counts, matrix=counts / 10, manifest={'case_id': 'multi-core'})
        cfg = Experiment(steps=8, input_group='I', input_start=0, input_stop=3,
            intervention_group='K', intervention_start=1, intervention_stop=6, outputs=('A', 'B'))
        return case, cfg

    def test_overlapping_repeated_events_add_before_existing_update(self):
        case, cfg = self.fixture()
        cfg = replace(cfg, alpha=1., rho=0., input_events=(
            dict(body_ids=['10', '30'], start=0, stop=2, amplitude=.6),
            dict(body_ids=['10'], start=1, stop=3, amplitude=.7),
            dict(body_ids=['10'], start=4, stop=5, amplitude=.2)))
        stats = simulate(case, cfg, recording=RecordPolicy(mode='all'))
        expected = np.array([0, np.tanh(.6), np.tanh(1.3), np.tanh(.7), 0, np.tanh(.2), 0, 0, 0])
        np.testing.assert_array_equal(stats.recorded_states[:, 0], expected)
        np.testing.assert_array_equal(stats.recorded_states[:, 2], [0, np.tanh(.6), np.tanh(.6), 0, 0, 0, 0, 0, 0])
        self.assertEqual(input_indices(case['nodes'], cfg).tolist(), [0, 2])

    def test_three_overlapping_observations_signal_and_sampled_recording(self):
        case, cfg = self.fixture()
        cfg = replace(cfg, observations=(dict(name='a', body_ids=['30']),
            dict(name='joint', body_ids=['30', '40']), dict(name='upstream', body_ids=['20', '30'])))
        full = compare(case, cfg, recording=RecordPolicy(mode='all'))
        sampled = compare(case, cfg, recording=RecordPolicy(body_ids=('20', '30'), steps=(0, 2, 8)))
        self.assertEqual(list(full['series']), ['a', 'joint', 'upstream'])
        for label, indices in [('a', [2]), ('joint', [2, 3]), ('upstream', [1, 2])]:
            np.testing.assert_array_equal(full['series'][label]['baseline'], full['states'][0][:, indices].mean(axis=1))
            self.assertEqual(full['signals'][label]['output_node_count'], len(indices))
        self.assertEqual(sampled['series'], full['series'])
        np.testing.assert_array_equal(sampled['states'][0], full['states'][0][[0, 2, 8]][:, [1, 2]])
        self.assertEqual(observation_indices(case['nodes'], cfg, 'upstream').tolist(), [1, 2])

    def test_explicit_legacy_equivalence_and_plan_baseline_identity(self):
        case, legacy = self.fixture()
        explicit = replace(legacy, input_events=tuple(effective_input_events(case['nodes'], legacy)),
                           observations=tuple(effective_observations(case['nodes'], legacy)))
        self.assertEqual(protocol_key(case['nodes'], legacy), protocol_key(case['nodes'], explicit))
        expected = compare(case, legacy, recording=RecordPolicy(mode='all'))
        actual = compare(case, explicit, recording=RecordPolicy(mode='all'))
        self.assertEqual(expected['series'], actual['series'])
        self.assertEqual(expected['summary'], actual['summary'])
        np.testing.assert_array_equal(expected['states'][0], actual['states'][0])
        history = propagate(case['matrix'], explicit, [0], [1], 1., nodes=case['nodes'])
        np.testing.assert_array_equal(history, actual['states'][0])
        baseline = simulate(case, explicit)
        other = replace(explicit, input_events=(dict(body_ids=['10'], start=0, stop=3, amplitude=.5),))
        with self.assertRaises(ValueError): compare(case, other, _baseline=baseline)
        with self.assertRaises(ValueError): simulate(case, other, plan=SimulationPlan(case, explicit))

    def test_empty_drive_zero_and_near_zero_percentages(self):
        case, cfg = self.fixture()
        result = compare(case, replace(cfg, input_events=()))
        self.assertEqual(result['input_node_count'], 0)
        for row in result['summary']:
            self.assertTrue(row['baseline_near_zero'])
            self.assertIsNone(row['relative_sum_delta'])
            self.assertEqual(row['mean_delta'], 0.)
        self.assertIsNone(response_metrics(1e-12, 0., 10)['relative_sum_delta'])
        self.assertAlmostEqual(response_metrics(1e-9, 0., 10)['relative_sum_delta'], -1.)

    def test_explicit_protocol_ignores_inactive_legacy_input_and_derives_outputs(self):
        case, cfg = self.fixture()
        cfg = Experiment.from_dict(dict(steps=3, input_events=[dict(body_ids=['20'], start=0, stop=1, amplitude=.2)],
            observations=[dict(name='mid', body_ids=['20'])], intervention_group='K', intervention_start=0,
            intervention_stop=2))
        result = compare(case, cfg)
        self.assertEqual(cfg.outputs, ('mid',))
        self.assertEqual(result['summary'][0]['type'], 'mid')
        self.assertEqual(result['input_node_count'], 1)

    def test_invalid_explicit_protocol_rejected(self):
        case, cfg = self.fixture()
        invalid = [dict(input_events=[dict(body_ids=['010'], start=0, stop=2, amplitude=.2)]),
                   dict(input_events=[dict(body_ids=['999'], start=0, stop=2, amplitude=.2)]),
                   dict(input_events=[dict(body_ids=['10'], start=0, stop=9, amplitude=.2)]),
                   dict(input_events=[dict(body_ids=['10'], start=0, stop=2, amplitude=1.1)]),
                   dict(observations=[]), dict(observations=[dict(name='x', body_ids=['30']), dict(name='x', body_ids=['40'])]),
                   dict(observations=[dict(name='x', body_ids=['30', '30'])])]
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ValueError): replace(cfg, **fields).validate(case['nodes'])

    def test_saved_case_groups_allow_three_overlapping_observation_roles(self):
        nodes = [dict(bodyId=str(body)) for body in (10, 20, 30, 40)]
        parsed = _groups(nodes, dict(input={'I': ['10']}, internal={'K': ['20']},
            output={'A': ['30'], 'B': ['40'], 'AB': ['30', '40']}))
        self.assertEqual(list(parsed['output']), ['A', 'B', 'AB'])
        self.assertEqual(nodes[2]['memberships']['output'], ['A', 'AB'])
        self.assertEqual(nodes[3]['memberships']['output'], ['B', 'AB'])
        _groups(nodes, dict(input={'I': ['10']}, internal={'K': ['20']}, output={'only': ['30']}))


if __name__ == '__main__': unittest.main()
