"""Evaluation windows affect metrics, never propagation or recording scope."""
import copy
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
from scipy import sparse

from cecropis.simulation import (Experiment, SimulationPlan, SimulationCancelled,
    RecordPolicy, simulate, compare, forward, observation_metrics, observation_window,
    protocol_key)
from cecropis.search import SearchOptions, search, preview_search_context
from cecropis.joint_search import (joint_search, preview_joint_candidates,
    annotate_joint_evaluation)
from cecropis.exploration import compare_conditions, save_comparison
from cecropis.scope_comparison import compare_scopes, discard_recordings
from tests import test_scope_comparison as scope_checks


class EvaluationWindowChecks(unittest.TestCase):
    def fixture(self):
        nodes = [dict(bodyId=body,role='internal',group_label='cells',type='cell',total_input=10)
                 for body in (10,20,30,40)]
        counts = sparse.csr_matrix(([8,8,3],([1,2,3],[0,1,1])),shape=(4,4))
        case = dict(nodes=nodes,counts=counts,matrix=counts/10,manifest={'case_id':'windows-small'})
        cfg = Experiment(steps=10,intervention_group='cells',intervention_ids=('20',),
            intervention_start=2,intervention_stop=8,gain=.1,
            input_events=[dict(body_ids=['10'],start=0,stop=4,amplitude=.7),
                          dict(body_ids=['10'],start=6,stop=8,amplitude=.4)],
            observations=[dict(name='early',body_ids=['30'],evaluation_window=dict(start=0,stop=3)),
                          dict(name='late',body_ids=['30'],evaluation_window=dict(start=3,stop=9)),
                          dict(name='protected',body_ids=['40'],evaluation_window=dict(start=5,stop=10))])
        return case,cfg

    def test_window_boundaries_and_metrics_only_equal_full_curves(self):
        case,cfg=self.fixture()
        full=simulate(case,cfg,gain=cfg.gain)
        light=simulate(case,cfg,gain=cfg.gain,collect_curves=False)
        self.assertEqual(light.series,{})
        self.assertEqual(light.signal_traces,{})
        self.assertIsNone(light.recorded_states)
        np.testing.assert_array_equal(light.activity_sum,full.activity_sum)
        np.testing.assert_array_equal(light.final,full.final)
        for label in cfg.outputs:
            window=observation_window(case['nodes'],cfg,label)
            expected=full.series[label][window['start']+1:window['stop']+1]
            metric=observation_metrics(case['nodes'],cfg,label,full,light)
            self.assertAlmostEqual(metric['baseline_sum'],float(expected.sum()))
            self.assertAlmostEqual(metric['baseline_mean'],float(expected.mean()))
            self.assertEqual(metric['sample_count'],len(expected))
            self.assertEqual(metric['mean_delta'],0.)
            self.assertEqual(full.observation_sums[label],light.observation_sums[label])
            self.assertEqual(full.observation_peaks[label],float(expected.max()))
        policy=RecordPolicy(mode='selected',body_ids=('30',),steps=(0,4,10))
        recorded=simulate(case,cfg,recording=policy,collect_curves=False)
        np.testing.assert_array_equal(recorded.recorded_states[:,0],simulate(case,cfg,
            recording=policy).recorded_states[:,0])
        self.assertEqual(recorded.observation_sums,simulate(case,cfg).observation_sums)

    def test_default_window_identity_legacy_history_and_validation(self):
        case,cfg=self.fixture()
        missing=replace(cfg,observations=[dict(name='target',body_ids=['30'])])
        explicit=replace(missing,observations=[dict(name='target',body_ids=['30'],
            evaluation_window=dict(start=0,stop=cfg.steps))])
        missing.validate(case['nodes']);explicit.validate(case['nodes'])
        self.assertEqual(protocol_key(case['nodes'],missing),protocol_key(case['nodes'],explicit))
        self.assertEqual(compare(case,missing)['summary'],compare(case,explicit)['summary'])
        whole=simulate(case,cfg,recording=RecordPolicy(mode='all'))
        cached=compare(case,cfg,_baseline=whole.recorded_states)
        self.assertEqual(cached['summary'],compare(case,cfg)['summary'])
        oldstats=replace(whole,observation_sums=None,observation_peaks=None)
        self.assertEqual(compare(case,cfg,_baseline=oldstats)['summary'],cached['summary'])
        for window in (dict(start=0,stop=0),dict(start=-1,stop=3),dict(start=1,stop=11),
                       dict(start=True,stop=3),dict(start=0,stop=3.0),dict(start=0,stop=3,extra=1),None):
            with self.subTest(window=window),self.assertRaisesRegex(ValueError,'evaluation_window'):
                Experiment.from_dict(dict(asdict(cfg),observations=[dict(name='x',body_ids=['30'],evaluation_window=window)]))
        shifted=replace(cfg,observations=[dict(item,evaluation_window=dict(start=1,stop=4)) if item['name']=='early' else item
                                        for item in cfg.observations])
        with self.assertRaisesRegex(ValueError,'plan'):
            simulate(case,shifted,plan=SimulationPlan(case,cfg))
        with self.assertRaisesRegex(ValueError,'Baseline'):
            compare(case,shifted,_baseline=whole)

    def test_window_search_context_and_full_activity_preselection(self):
        case,cfg=self.fixture()
        options=SearchOptions(target_output='late',target_metric='absolute',min_target_loss=.001,
            protected_limits={'protected':dict(metric='absolute',max_loss=.01)},
            max_nodes=1,max_evaluations=2,shortlist=1,swap_passes=0)
        result=search(case,cfg,options)
        expected=compare(case,cfg)
        metrics={item['type']:item for item in expected['summary']}
        row=result['best']
        self.assertAlmostEqual(row['target_loss'],-metrics['late']['mean_delta'])
        self.assertEqual(row['output_metrics']['late']['sample_count'],6)
        context=preview_search_context(case,cfg,options)['constraint_context']['conditions'][0]
        self.assertEqual(context['target']['evaluation_window'],dict(start=3,stop=9))
        self.assertAlmostEqual(context['protected']['protected']['baseline_mean'],metrics['protected']['baseline_mean'])
        self.assertEqual(context['protected']['protected']['sample_count'],5)
        zero=replace(cfg,observations=[dict(name='late',body_ids=['30'],evaluation_window=dict(start=0,stop=1))])
        zero_options=replace(options,target_metric='relative',protected_limits={})
        preview=preview_search_context(case,zero,zero_options)
        self.assertTrue(preview['baseline_metrics']['late']['baseline_near_zero'])
        self.assertFalse(preview['constraint_context']['conditions'][0]['target']['defined'])
        with self.assertRaisesRegex(ValueError,'near-zero'):
            search(case,zero,zero_options)
        self.assertEqual(search(case,zero,replace(zero_options,target_metric='absolute'))['best']['target_loss'],0.)
        # The ranking remains based on activity throughout the protocol, independently of evaluation windows.
        allwindows=replace(cfg,observations=[dict(item,evaluation_window=dict(start=0,stop=10)) for item in cfg.observations])
        self.assertEqual(preview_search_context(case,cfg,options)['candidate_preselection'],
                         preview_search_context(case,allwindows,options)['candidate_preselection'])

    def test_joint_fixed_single_annotation_and_compatibility(self):
        case,cfg=self.fixture()
        later=replace(cfg,input_events=[dict(body_ids=['10'],start=4,stop=7,amplitude=.7)])
        conditions=[dict(name='first',experiment=cfg),dict(name='later',experiment=later)]
        options=SearchOptions(target_output='late',target_metric='absolute',min_target_loss=0.,
            protected_limits={'protected':dict(metric='absolute',max_loss=1.)},
            max_nodes=1,max_evaluations=2,shortlist=1,swap_passes=0)
        report=joint_search(case,conditions,options)
        for item,c in zip(report['best']['condition_results'],conditions):
            expected=compare(case,c['experiment'])
            metrics={row['type']:row for row in expected['summary']}
            self.assertEqual(item['output_metrics']['late']['mean_delta'],metrics['late']['mean_delta'])
        changed=replace(later,observations=[dict(item,evaluation_window=dict(start=2,stop=9))
            if item['name']=='late' else item for item in later.observations])
        for operation in (compare_conditions,lambda case,items:preview_joint_candidates(case,items,options)):
            with self.assertRaisesRegex(ValueError,'observation'):
                operation(case,[conditions[0],dict(name='bad',experiment=changed)])
        comparison=compare_conditions(case,[conditions[0]])
        comparison['results'][0].pop('series')
        annotated=annotate_joint_evaluation(comparison,options,['first'])
        self.assertEqual(annotated['constraint_context']['conditions'][0]['target']['sample_count'],6)
        self.assertEqual(annotated['joint_constraints']['condition_results'][0]['target_loss'],report['best']['condition_results'][0]['target_loss'])
        annotated['conditions'][0]['experiment']['observations'][1]['evaluation_window']['start']=2
        with self.assertRaisesRegex(ValueError,'exact observations'):
            annotate_joint_evaluation(annotated,options,['first'])

    def test_comparison_counters_cancel_and_timing_metadata(self):
        case,cfg=self.fixture()
        conditions=[dict(name='same1',experiment=cfg),dict(name='same2',experiment=copy.deepcopy(cfg))]
        events=[]
        comparison=compare_conditions(case,conditions,simulation_progress=events.append)
        self.assertEqual([(row['kind'],row['status']) for row in events],
            [('baseline','started'),('baseline','completed'),('intervention','started'),('intervention','completed'),
             ('intervention','started'),('intervention','completed')])
        cancelled=[]
        with self.assertRaises(SimulationCancelled):
            compare_conditions(case,conditions,cancel=lambda:True,simulation_progress=cancelled.append)
        self.assertEqual(cancelled,[dict(kind='baseline',status='started',condition_name='same1')])
        comparison['timing_evaluation']=dict(body_ids=['20'],start=2,duration=6,
            search_options=asdict(SearchOptions()),condition_names=['same1','same2'])
        with tempfile.TemporaryDirectory() as root:
            folder=save_comparison(root,comparison)
            saved=json.loads((folder/'conditions.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['timing_evaluation'],comparison['timing_evaluation'])
            self.assertEqual(compare_conditions(case,saved['conditions'])['rows'],comparison['rows'])
        self.assertEqual(forward(case,cfg)['summary'][1]['sample_count'],6)

    def test_cross_scope_windows_use_fixed_ids_and_own_baselines(self):
        fixture=scope_checks.ScopeComparisonChecks()
        with tempfile.TemporaryDirectory() as root:
            config=fixture.fixture(Path(root))
            config['experiment']['observations'][0]['evaluation_window']=dict(start=3,stop=7)
            config['experiment']['observations'][1]['evaluation_window']=dict(start=1,stop=5)
            result=compare_scopes(config)
            try:
                for scope in result['scopes']:
                    observed=scope['result']
                    for metrics in observed['summary']:
                        window=metrics['evaluation_window']
                        curve=observed['series'][metrics['type']]['baseline']
                        self.assertEqual(metrics['sample_count'],4)
                        self.assertAlmostEqual(metrics['baseline_mean'],sum(curve[window['start']+1:window['stop']+1])/4)
            finally:
                discard_recordings(result)


if __name__=='__main__':
    unittest.main()
