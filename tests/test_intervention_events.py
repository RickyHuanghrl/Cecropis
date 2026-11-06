import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix

from cecropis.simulation import Experiment, RecordPolicy, compare, simulate, propagate
from cecropis.exploration import compare_conditions


def fork_case():
    nodes = [dict(bodyId=str(i), type='node', role='internal', group_label='all', total_input=10)
             for i in (1, 2, 3)]
    counts = csr_matrix(np.array([[0, 0, 0], [5, 0, 0], [7, 0, 0]], dtype=np.int64))
    return dict(nodes=nodes, counts=counts, matrix=counts.astype(float) / 10,
                manifest=dict(case_id='fork'))


def config(events=None):
    data = dict(steps=4, alpha=1., rho=1., input_events=[dict(body_ids=['1'], start=0, stop=1, amplitude=1.)],
                observations=[dict(name='B', body_ids=['2']), dict(name='C', body_ids=['3'])],
                intervention_group='all', intervention_ids=['1'], intervention_start=0, intervention_stop=4, gain=.5)
    if events is not None:
        for key in ('intervention_group', 'intervention_ids', 'intervention_start', 'intervention_stop', 'gain'):
            data.pop(key)
        data.update(intervention_events=events, intervention_semantics_version=1)
    return Experiment.from_dict(data)


def node_event(name='node', gain=.5, start=0, stop=3):
    return dict(name=name, type='node_gain', body_ids=['1', '1'], start=start, stop=stop, gain=gain, enabled=True)


def edge_event(name='edge', gain=.5, start=1, stop=3):
    return dict(name=name, type='edge_gain', edges=[['1', '2'], ['1', '2']], start=start, stop=stop, gain=gain, enabled=True)


class InterventionEventsTests(unittest.TestCase):
    def test_new_plan_branch_order_overlap_and_fork(self):
        case = fork_case()
        cfg = config([node_event(), node_event('node2'), edge_event(), edge_event('edge2', gain=.5)])
        out = compare(case, cfg, keep_states=True)
        b, i = out['states']
        self.assertAlmostEqual(i[1, 0], np.tanh(1) * .25)
        self.assertAlmostEqual(i[2, 1], np.tanh(.5 * .25 * i[1, 0]))
        self.assertAlmostEqual(i[2, 2], np.tanh(.7 * i[1, 0]))
        np.testing.assert_allclose(b[1], [np.tanh(1), 0, 0])
        np.testing.assert_allclose(case['counts'].toarray(), [[0, 0, 0], [5, 0, 0], [7, 0, 0]])
        self.assertEqual(out['intervention_edge_count'], 1)
        self.assertEqual(out['intervention_node_count'], 1)
        self.assertEqual(len(cfg.intervention_events[0]['body_ids']), 1)
        reloaded = Experiment.from_dict(json.loads(json.dumps(asdict(cfg))))
        np.testing.assert_allclose(compare(case, reloaded, keep_states=True)['states'][1], i)

    def test_empty_unit_and_legacy(self):
        case = fork_case()
        legacy = compare(case, config(), keep_states=True)
        empty = compare(case, config([]), keep_states=True)
        unit = compare(case, config([node_event(gain=1), edge_event(gain=1)]), keep_states=True)
        np.testing.assert_allclose(empty['states'][0], empty['states'][1])
        np.testing.assert_allclose(unit['states'][0], unit['states'][1])
        converted = compare(case, config([node_event(stop=4)]), keep_states=True)
        np.testing.assert_allclose(legacy['states'][1], converted['states'][1])

    def test_plan_validation(self):
        case = fork_case()
        bad = edge_event(); bad['edges'] = [['2', '1']]
        with self.assertRaisesRegex(ValueError, 'real|exist'):
            compare(case, config([bad]))
        bad = node_event(); bad['stop'] = 5
        with self.assertRaises(ValueError): config([bad])
        bad = node_event(); bad['body_ids'] = ['99']
        with self.assertRaises(ValueError): compare(case, config([bad]))
        raw = asdict(config()); raw['intervention_events'] = []
        raw['intervention_semantics_version'] = 1
        with self.assertRaisesRegex(ValueError, 'conflict|legacy'):
            Experiment.from_dict(raw)

    def test_signal_terms_streamed_and_full_history(self):
        from cecropis.signals import incoming_signals
        case = fork_case(); cfg = config([edge_event(gain=0)])
        out = compare(case, cfg, keep_states=True)
        b, i = out['states']
        detail = incoming_signals(case, cfg, 'B', b, i, [])
        expected = sum(cfg.alpha * cfg.rho * .5 * i[t, 0] * (0 if 1 <= t < 3 else 1) for t in range(cfg.steps))
        self.assertAlmostEqual(out['signals']['B']['intervention_signal'], expected)
        self.assertAlmostEqual(detail['intervention_signal'], expected)
        self.assertAlmostEqual(out['signals']['B']['edges'][0]['intervention_signal'], expected)
        np.testing.assert_allclose(out['signals']['B']['intervention_trace'], detail['intervention_trace'])

    def test_edge_gain_never_scales_drive_or_sender(self):
        case = fork_case(); cfg = config([edge_event(start=0, stop=4, gain=0)])
        raw = asdict(cfg)
        raw['input_events'] = list(raw['input_events']) + [dict(body_ids=['2'], start=1, stop=2, amplitude=.4)]
        cfg = Experiment.from_dict(raw)
        out = compare(case, cfg, keep_states=True)
        b, i = out['states']
        np.testing.assert_allclose(i[:, 0], b[:, 0])
        np.testing.assert_allclose(i[:, 2], b[:, 2])
        self.assertAlmostEqual(i[2, 1], np.tanh(.4))

    def test_operations_interaction(self):
        from cecropis.exploration import compare_operations
        case = fork_case(); raw = asdict(config([]))
        raw['observations'][0]['evaluation_window'] = dict(start=1, stop=3)
        cfg = Experiment.from_dict(raw)
        out = compare_operations(case, cfg, [edge_event()], [node_event()])
        self.assertEqual(len(out['results']), 4)
        self.assertEqual(out['baseline_protocol_count'], 1)
        by_name = {row['name']: row for row in out['rows']}
        actual = out['interaction'][0]
        vals = [by_name[name]['outputs'][0]['intervention_sum'] for name in ('0', 'A', 'B', 'A+B')]
        self.assertAlmostEqual(actual['interaction'], vals[3] - vals[1] - vals[2] + vals[0])
        self.assertEqual(out['execution_counts']['physical_started'], 5)
        self.assertEqual(out['execution_counts']['physical_completed'], 5)
        self.assertEqual(out['execution_counts']['baseline_reused'], 3)
        self.assertEqual(actual['evaluation_window'], dict(start=1, stop=3))
        self.assertAlmostEqual(actual['R0'], np.tanh(.5 * np.tanh(1.)))

    def test_comparison_save_keeps_plan_and_direction(self):
        from cecropis.exploration import compare_operations, save_comparison
        out = compare_operations(fork_case(), config([]), [edge_event()], [node_event()])
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            path = save_comparison(root, out)
            saved = json.loads((path/'comparison.json').read_text(encoding='utf-8'))
            reloaded = Experiment.from_dict(saved['conditions'][3]['experiment'])
            self.assertEqual(reloaded.intervention_events[0]['edges'], [['1','2']])
            self.assertEqual(saved['interactions'], out['interactions'])
            self.assertEqual(saved['execution_counts'], out['execution_counts'])
            self.assertIn('intervention_events_json', (path/'comparison.csv').read_text(encoding='utf-8-sig'))

    def test_cancel_preserves_complete_condition_only(self):
        from cecropis.exploration import compare_operations
        stopped = [False]
        def progress(value):
            if value.get('kind') == 'intervention' and value.get('status') == 'started' and value.get('condition_name') == 'A':
                stopped[0] = True
        out = compare_operations(fork_case(), config([]), [edge_event()], [node_event()],
            cancel=lambda: stopped[0], simulation_progress=progress)
        self.assertEqual(out['status'], 'cancelled')
        self.assertEqual([row['name'] for row in out['rows']], ['0'])
        self.assertEqual(out['interactions'], [])
        self.assertEqual(out['execution_counts']['physical_started'], 3)
        self.assertEqual(out['execution_counts']['physical_completed'], 2)
        self.assertEqual([row['status'] for row in out['condition_states']], ['complete','cancelled','not_run','not_run'])

    def test_enabled_time_boundaries_and_independent_gain(self):
        from cecropis.interventions import CompiledInterventions, preview_interventions
        case = fork_case()
        disabled = node_event('disabled', gain=0); disabled['enabled'] = False
        cfg = config([edge_event(start=0, stop=1, gain=.2), edge_event('later', start=1, stop=3, gain=.3), disabled])
        compiled = CompiledInterventions(case, cfg)
        self.assertEqual([compiled.edge_gain('1','2',t) for t in range(4)], [.2,.3,.3,1.])
        self.assertEqual(compiled.edge_gain('1','3',1), 1.)
        self.assertEqual(compiled.node_gain('1',1), 1.)
        preview = preview_interventions(case, cfg)
        self.assertEqual(preview['edge_count'], 1)
        self.assertEqual(preview['node_count'], 0)
        with self.assertRaisesRegex(ValueError, 'version'):
            raw = asdict(cfg); raw['intervention_semantics_version'] = None
            Experiment.from_dict(raw)


if __name__ == '__main__': unittest.main()
