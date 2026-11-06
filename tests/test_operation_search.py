import copy
import json
import tempfile
import unittest
from dataclasses import asdict
from unittest.mock import patch
from tests.test_intervention_events import fork_case,config,edge_event,node_event
from cecropis.operation_search import preview_operation_search,search_operations,operation_plan_curves,save_operation_search,load_operation_search
from cecropis.simulation import simulate


def definition():
    # Each half-gain alone fails 65%; their product succeeds, without touching C.
    return dict(name='fork fixed operations',conditions=[dict(name='first',experiment=asdict(config([])))],
        candidates=[dict(id='a',event=edge_event('half-early',stop=2)),dict(id='b',event=edge_event('half-long'))],
        requirements=dict(target_output='B',target_metric='relative',min_target_loss=.65,
            protected_limits={'C':dict(metric='relative',max_loss=0)}),
        settings=dict(max_operations=2,max_nodes=0,max_edges=1,max_evaluations=4,beam_width=2))


class OperationSearchTests(unittest.TestCase):
    def test_actual_combination_and_selection(self):
        case=fork_case();d=definition();r=search_operations(case,d)
        self.assertEqual(r['recommended_candidate_ids'],['a','b'])
        self.assertEqual([e['feasible'] for e in r['entries']],[False,False,False,True])
        self.assertEqual(r['evaluations'],4);self.assertEqual(r['intervention_completed'],3)
        self.assertEqual(r['baseline_completed'],1);self.assertEqual(r['combination_duplicates'],1)
        # Independent manual value: B at x2 = tanh(.5 * .25 * tanh(1)).
        import numpy as np
        best=r['entries'][-1]['condition_results'][0]['output_metrics']['B']
        self.assertAlmostEqual(best['intervention_sum'],np.tanh(.125*np.tanh(1)))
        curves=operation_plan_curves(case,r,['a','b'])
        self.assertEqual(len(curves['conditions'][0]['experiment']['intervention_events']),2)
        self.assertEqual(r['entries'][-1]['condition_results'][0]['edge_constraint']['edge_count'],1)
        self.assertEqual(curves['constraints'][0]['constraints']['condition_results'][0]['node_count'],0)
        changed=copy.deepcopy(r);changed['definition']['candidates'][0]['event']['gain']=.3
        with patch('cecropis.operation_search.compare_conditions',side_effect=AssertionError('edited report must not propagate')):
            with self.assertRaisesRegex(ValueError,'frozen identity'):operation_plan_curves(case,changed,['a','b'])
        with tempfile.TemporaryDirectory() as root:
            saved=load_operation_search(save_operation_search(root,r))
            self.assertEqual(saved,json.loads(json.dumps(r)))
            legacy=copy.deepcopy(r);legacy['entries'][-1]['condition_results'][0]['node_count']=999
            folder=save_operation_search(root,legacy)
            with patch('cecropis.operation_search.simulate',side_effect=AssertionError('read must not propagate')):
                restored=load_operation_search(folder)
            self.assertEqual(restored['entries'][-1]['condition_results'][0]['node_count'],0)
            self.assertEqual(json.loads((folder/'operation-search.json').read_text())['entries'][-1]['condition_results'][0]['node_count'],999)

    def test_duplicate_exclusive_noop_and_budget(self):
        case=fork_case();d=definition();d['candidates'][1]['event']=dict(d['candidates'][0]['event'],name='another')
        with self.assertRaisesRegex(ValueError,'Duplicate'):preview_operation_search(case,d)
        d=definition()
        for c in d['candidates']:c['exclusive_group']='alternative'
        r=search_operations(case,d);self.assertFalse(any(e['feasible'] for e in r['entries']))
        self.assertEqual(r['pruned_combinations'][0]['reason'],'exclusive_group')
        d=definition();d['candidates'].append(dict(id='unit',event=edge_event(gain=1)))
        self.assertEqual(preview_operation_search(case,d)['excluded_candidates'][0]['reason'],'no_effect')
        d['settings']['max_evaluations']=2;r=search_operations(case,d)
        self.assertEqual(r['status'],'budget_exhausted');self.assertEqual(r['evaluations'],2)
        self.assertTrue(r['layers'][0]['not_run'])

    def test_multi_protocol_protection_and_partial_cancel(self):
        case=fork_case();d=definition()
        d['conditions'].append(dict(name='second',experiment=asdict(config([]))))
        d['candidates'][0]['event']=node_event();d['settings']['max_nodes']=1
        r=search_operations(case,d)
        self.assertEqual(r['baseline_completed'],1);self.assertEqual(r['baseline_reused'],1)
        self.assertTrue(all(len(e['condition_results'])==2 for e in r['entries']))
        self.assertFalse(next(e for e in r['entries'] if e['candidate_ids']==['a'])['feasible'])
        calls=[0];cancelled=[False]
        def runner(*a,**k):
            out=simulate(*a,**k)
            if k.get('apply_interventions'):calls[0]+=1;cancelled[0]=True
            return out
        with patch('cecropis.operation_search.simulate',side_effect=runner):
            r=search_operations(case,d,cancel=lambda:cancelled[0])
        self.assertEqual(r['evaluations'],1);self.assertEqual(r['intervention_completed'],1)
        self.assertEqual(r['entries'][-1]['status'],'cancelled');self.assertIsNone(r['entries'][-1]['feasible'])
        self.assertEqual(r['entries'][-1]['unfinished_condition_names'],['second'])

    def test_empty_and_undefined(self):
        case=fork_case();d=definition();d['requirements']['min_target_loss']=0
        r=search_operations(case,d);self.assertEqual(r['termination_reason'],'no_intervention_needed');self.assertEqual(r['recommended_candidate_ids'],[])
        d=definition();d['conditions'][0]['experiment']['input_events'][0]['amplitude']=0
        r=search_operations(case,d);self.assertFalse(any(e['feasible'] for e in r['entries']))
        self.assertIsNone(r['entries'][0]['worst_target_loss'])

    def test_extra_roles_fixed_export_and_read_only_cli(self):
        import contextlib,io
        from cecropis.__main__ import main
        from cecropis.task_sources import export_saved_task
        case=fork_case();r=search_operations(case,definition());before=copy.deepcopy(r['recommended_candidate_ids'])
        curves=operation_plan_curves(case,r,['a','b'],extra_conditions=[dict(name='unseen',experiment=asdict(config([])))])
        self.assertEqual(r['recommended_candidate_ids'],before)
        self.assertEqual([c['role'] for c in curves['constraints']],['decision','extra'])
        with patch('cecropis.task_definition.export_task',side_effect=lambda case,conditions,name,description:conditions):
            exported=export_saved_task(case,curves,'chosen')
        self.assertEqual([i['role'] for i in exported],['decision','extra'])
        self.assertEqual(len(exported[0]['experiment']['intervention_events']),2)
        with tempfile.TemporaryDirectory() as root:
            folder=save_operation_search(root,r);stream=io.StringIO()
            with patch('cecropis.__main__.Lab',side_effect=AssertionError('read must not load a scope')),contextlib.redirect_stdout(stream):
                main(['operation-search-read','--report',str(folder)])
            self.assertEqual(json.loads(stream.getvalue())['definition_hash'],r['definition_hash'])

    def test_curve_cancel_and_scope_mismatch(self):
        case=fork_case();r=search_operations(case,definition())
        curves=operation_plan_curves(case,r,['a','b'],cancel=lambda:True)
        self.assertEqual(curves['status'],'cancelled');self.assertEqual(curves['results'],[])
        self.assertEqual(curves['execution_counts']['baseline_completed'],0)
        case['manifest']['case_id']='other'
        with self.assertRaisesRegex(ValueError,'mismatch'):operation_plan_curves(case,r,['a','b'])

    def test_preview_and_failure_do_not_publish_incomplete(self):
        case=fork_case();d=definition()
        with patch('cecropis.operation_search.simulate',side_effect=AssertionError('preview must not propagate')):
            preview_operation_search(case,d)
        def runner(*a,**k):
            if k.get('apply_interventions'):raise RuntimeError('injected propagation failure')
            return simulate(*a,**k)
        with patch('cecropis.operation_search.simulate',side_effect=runner):r=search_operations(case,d)
        self.assertEqual(r['status'],'failed');self.assertEqual(r['evaluations'],1)
        self.assertEqual(r['intervention_started'],1);self.assertEqual(r['intervention_completed'],0)
        self.assertEqual(r['entries'][-1]['status'],'failed');self.assertIsNone(r['entries'][-1]['feasible'])


if __name__=='__main__':unittest.main()
