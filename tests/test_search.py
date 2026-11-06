import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
import numpy as np
from scipy import sparse
from cecropis.simulation import Experiment, compare
from cecropis.search import SearchOptions, sensitivity, search, save_search


class SearchChecks(unittest.TestCase):
    def fixture(self):
        # Node 20 has no direct edge to A: its effect travels via node 21.
        nodes = [dict(bodyId=b, role=r, type=t, group_label=t, index=i, total_input=10)
                 for i, (b, r, t) in enumerate([(10,'input','PN'), (20,'internal','KC'),
                      (21,'internal','KC'), (22,'internal','KC'), (30,'output','A'), (40,'output','B')])]
        matrix = sparse.csr_matrix(([.8,.8,.8,.8,.5,.8],([1,2,3,4,4,5],[0,1,0,2,3,3])),shape=(6,6))
        case = dict(nodes=nodes,matrix=matrix,manifest={'case_id':'fixture'})
        cfg = Experiment(steps=18,input_group='PN',input_start=0,input_stop=6,
                         intervention_group='KC',intervention_start=1,intervention_stop=10,gain=.1,outputs=('A','B'))
        return case,cfg

    def test_indirect_effect_joint_run_and_saved_conditions(self):
        case,cfg=self.fixture()
        s=sensitivity(case,cfg)
        self.assertGreater(next(n for n in s['nodes'] if n['bodyId']=='20')['target_loss'],0)
        r=search(case,cfg,SearchOptions(max_nodes=2,max_evaluations=30,max_protected_loss=.01,shortlist=3))
        self.assertTrue(r['best']['feasible'])
        self.assertNotIn('22',r['best']['body_ids'])
        actual=compare(case,replace(cfg,intervention_ids=tuple(r['best']['body_ids'])))
        self.assertAlmostEqual(r['best']['target_loss'],-actual['summary'][0]['relative_sum_delta'])
        self.assertAlmostEqual(r['best']['protected_loss'],-actual['summary'][1]['relative_sum_delta'])
        with tempfile.TemporaryDirectory() as tmp:
            p=save_search(tmp,r)
            self.assertTrue((p/'conditions.json').is_file())
            self.assertTrue((p/'search.json').is_file())

    def test_budget_cancel_unreachable_and_zero_baseline(self):
        case,cfg=self.fixture()
        r=search(case,cfg,SearchOptions(max_nodes=2,max_evaluations=2,shortlist=3,min_target_loss=1))
        self.assertLessEqual(r['evaluations'],2)
        self.assertFalse(r['best']['feasible'])
        self.assertIn('minimum_target_loss',r['best']['violations'])
        self.assertLess(r['screened_candidates'],r['candidate_count'])
        cancelled=search(case,cfg,SearchOptions(),cancel=lambda:True)
        self.assertEqual(cancelled['status'],'cancelled')
        self.assertIsNone(cancelled['best'])
        with tempfile.TemporaryDirectory() as tmp:
            path=save_search(tmp,cancelled)
            self.assertTrue((path/'search.json').exists())
            self.assertFalse((path/'conditions.json').exists())
        with self.assertRaises(ValueError):
            search(case,replace(cfg,amplitude=0),SearchOptions())
        with self.assertRaises(ValueError):
            search(case,cfg,SearchOptions(max_protected_loss=float('nan')))

    def test_time_window_and_exact_candidate_domain(self):
        case,cfg=self.fixture()
        s=sensitivity(case,replace(cfg,intervention_ids=('20',),intervention_start=16,intervention_stop=18))
        self.assertEqual(s['candidate_count'],1)
        early=sensitivity(case,replace(cfg,intervention_ids=('20',)))
        self.assertGreater(early['nodes'][0]['target_loss'],s['nodes'][0]['target_loss'])

if __name__=='__main__': unittest.main()
