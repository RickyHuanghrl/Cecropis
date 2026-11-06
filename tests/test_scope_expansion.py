import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scipy import sparse
from cecropis.selection import build_case
from cecropis.case import load_case, close_case
from cecropis.scope_boundary import input_coverage, external_inputs
from cecropis.scope_expansion import preview_expansion, build_expansion, save_expansion, load_expansion


class Index:
    """Independent directed contacts: includes cross edges absent from traversal."""
    def __init__(self):
        self.ids=np.array([10,20,30,40,50,60,70,80,99])
        # sender, receiver, contacts. 80 is zero-input; 99 lacks annotation.
        self.edges=[(10,20,8),(30,20,5),(99,20,13),(50,20,2),(40,30,7),
                    (60,30,6),(30,40,4),(40,20,1),(60,40,3),(70,40,20),
                    (10,30,1),(20,60,2),(60,70,2),(70,60,3)]
        lookup={int(body):i for i,body in enumerate(self.ids)}
        self.incoming=sparse.csr_matrix(([w for a,b,w in self.edges],
            ([lookup[b] for a,b,w in self.edges],[lookup[a] for a,b,w in self.edges])),shape=(9,9),dtype=np.int64)
        self.outgoing=self.incoming.T.tocsr()
        self.total_input=np.asarray(self.incoming.sum(axis=1)).ravel()
        self.total_output=np.asarray(self.incoming.sum(axis=0)).ravel()
        self.annotations={int(body):dict(bodyId=str(body),type='T'+str(body),category='glia' if body==50 else 'neuron') for body in self.ids if body!=99}
        self.manifest=dict(index_id='test-index',node_count=9,edge_count=len(self.edges))
    def node(self,body):
        return dict(self.annotations.get(int(body),dict(bodyId=str(body),type=None,category='unannotated')))
    def nodes(self,bodies):return [self.node(body) for body in bodies]


class ExpansionChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.index=Index()
        self.base=build_case(self.index,dict(name='base',scope=dict(body_ids=['10','20','30','80'],hops=0,max_nodes=4),
            groups=dict(input={'I':['10']},internal={'S':['30']},output={'A':['20'],'zero':['80']})),self.root/'cases'/'base')
        self.cfg=dict(budgets=[5,7],hops=1,direction='incoming')
    def tearDown(self):self.tmp.cleanup()
    def test_counts_nested_induced_denominators_and_reuse(self):
        report=build_expansion(self.index,self.base,self.cfg,self.root/'cases')
        self.assertEqual(report['status'],'completed')
        previous={'10','20','30','80'};coverage=[]
        base=load_case(self.base)
        try:
            base_matrix=base['matrix'].toarray().copy()
            base_groups=copy.deepcopy(base['manifest']['groups'])
            for item in report['levels']:
                bodies=set(item['body_ids']);self.assertTrue(previous<=bodies)
                case=load_case(item['case_path'])
                try:
                    self.assertEqual(case['manifest']['groups'],base_groups)
                    metadata={n['bodyId']:n for n in case['nodes']}
                    for body in bodies-{'10','20','30','80'}:self.assertEqual(metadata[body]['role'],'context')
                    ordered=[int(n['bodyId']) for n in case['nodes']];positions={body:i for i,body in enumerate(ordered)}
                    expected=np.zeros((len(ordered),len(ordered)),dtype=np.int64)
                    for sender,receiver,count in self.index.edges:
                        if sender in positions and receiver in positions:expected[positions[receiver],positions[sender]]+=count
                    np.testing.assert_array_equal(case['counts'].toarray(),expected)
                    for bi,node in enumerate(base['nodes']):
                        ni=positions[int(node['bodyId'])]
                        self.assertEqual(metadata[node['bodyId']]['total_input'],node['total_input'])
                        for bj,other in enumerate(base['nodes']):self.assertEqual(case['matrix'][ni,positions[int(other['bodyId'])]],base_matrix[bi,bj])
                    boundary=input_coverage(case,node_ids=['20','80'])
                    rows=boundary['groups'][0]['nodes'];self.assertIsNone(rows[1]['input_fraction'])
                    summary=boundary['groups'][0]['summary'];self.assertEqual(summary['input_fraction'],rows[0]['input_fraction'])
                    coverage.append(rows[0]['internal_input_contacts']);previous=bodies
                finally:close_case(case)
            self.assertLessEqual(*coverage)
        finally:close_case(base)
        again=build_expansion(self.index,self.base,self.cfg,self.root/'cases')
        self.assertTrue(all(item['reused'] for item in again['levels']))
        saved=save_expansion(self.root/'runs',report);opened=load_expansion(saved)
        self.assertEqual(opened['levels'],report['levels'])
        self.assertEqual(len(list((self.root/'cases').glob('*/manifest.json'))),3)
    def test_boundary_aggregate_zero_category_and_partial(self):
        case=load_case(self.base)
        try:
            coverage=input_coverage(case,node_ids=['20','30','80'])
            group=coverage['groups'][0];rows=group['nodes'];summary=group['summary']
            self.assertEqual(summary['internal_input_contacts'],14)
            self.assertEqual(summary['total_input_contacts'],43)
            self.assertAlmostEqual(summary['input_fraction'],14/43)
            self.assertNotEqual(summary['input_fraction'],np.mean([row['input_fraction'] for row in rows if row['input_fraction'] is not None]))
            external=external_inputs(self.index,case,['20','30'])
            self.assertEqual([row['body_id'] for row in external['nodes']],['99','40','60','50'])
            self.assertEqual(external['nodes'][1]['count'],8)
            self.assertEqual(external['nodes'][1]['targets'],[dict(body_id='20',count=1),dict(body_id='30',count=7)])
            self.assertFalse(external['nodes'][0]['eligible']);self.assertFalse(external['nodes'][-1]['eligible'])
            self.assertTrue(external['scan_complete'])
            partial=external_inputs(self.index,case,['20','30'],scan_limit=2)
            self.assertFalse(partial['scan_complete']);self.assertTrue(partial['truncated'])
            self.assertEqual(partial['ranking_scope'],'scanned indexed input prefix')
            self.assertEqual(external_inputs(self.index,case,['20','30'],offset=1,limit=1)['nodes'],[external['nodes'][1]])
        finally:close_case(case)
        with self.assertRaisesRegex(ValueError,'excluded'):preview_expansion(self.index,self.base,dict(self.cfg,added_body_ids=['50']))
        preview=preview_expansion(self.index,self.base,dict(self.cfg,max_internal_edges=1))
        self.assertFalse(preview['build_allowed']);self.assertIsNone(preview['levels'][0]['internal_edges'])
        self.assertEqual(build_expansion(self.index,self.base,dict(self.cfg,max_bytes=1),self.root/'cases')['status'],'failed')
        scan=preview_expansion(self.index,self.base,dict(self.cfg,scan_limit=1))
        self.assertFalse(scan['build_allowed']);self.assertEqual(scan['levels'][0]['selection']['truncation_reason'],'neighbor_scan_budget')
    def test_cancel_retains_prior_and_no_partial_runnable(self):
        cancelled={'yes':False}
        def progress(value):
            if value['phase']=='build' and value['level']==2:cancelled['yes']=True
        report=build_expansion(self.index,self.base,self.cfg,self.root/'cases',cancel=lambda:cancelled['yes'],progress=progress)
        self.assertEqual(report['status'],'cancelled');self.assertEqual(report['completed_levels'],1)
        self.assertEqual(report['levels'][0]['status'],'completed');self.assertEqual(report['levels'][1]['status'],'cancelled')
        self.assertTrue((Path(report['levels'][0]['case_path'])/'manifest.json').exists())
        for staging in (self.root/'cases').glob('.scope-expansion-*'):self.assertFalse((staging/'manifest.json').exists())
        self.assertEqual(load_expansion(save_expansion(self.root/'runs',report))['status'],'cancelled')
        unchanged=load_case(self.base)
        try:self.assertEqual(len(unchanged['nodes']),4)
        finally:close_case(unchanged)


if __name__=='__main__':unittest.main()
