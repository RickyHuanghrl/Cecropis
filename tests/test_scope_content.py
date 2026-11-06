import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather

from cecropis.global_index import build_global_index, GlobalIndex, ANNOTATIONS, WEIGHTS
from cecropis.selection import build_case
from cecropis.case import load_case, close_case
from cecropis.task_definition import export_task, prepare_task, preview_task, run_task, normalize_task
from cecropis.scope_content import content_identity


class ScopeContentChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name);self.indexes=[]
    def tearDown(self):
        for index in self.indexes:index.close()
        self.temp.cleanup()
    def index(self,name,weight=5,external=7,missing=False,reverse=False):
        raw=self.root/(name+'-small-source');raw.mkdir()
        ids=[1,2,3,4] if not missing else [1,2,4]
        edges=[(1,2,weight),(2,3,3),(4,2,external),(3,2,1)]
        if missing:edges=[edge for edge in edges if 3 not in edge[:2]]
        if reverse:ids.reverse();edges.reverse()
        feather.write_feather(pa.table(dict(bodyId=ids,status=['Traced']*len(ids),type=['T'+str(i) for i in ids])),raw/ANNOTATIONS)
        feather.write_feather(pa.table(dict(body_pre=[e[0] for e in edges],body_post=[e[1] for e in edges],weight=[e[2] for e in edges])),raw/WEIGHTS)
        target=self.root/(name+'-index')
        build_global_index(raw,target,batch_size=2)
        index=GlobalIndex(target);self.indexes.append(index);return index
    def task(self,index):
        path=build_case(index,dict(name='source',scope=dict(body_ids=['1','2','3'],hops=0,max_nodes=3),
            groups=dict(input={'I':['1']},internal={'S':['2']},output={'O':['3']})),self.root/'source-scope')
        case=load_case(path)
        try:
            cfg=dict(steps=3,alpha=.3,rho=.9,input_events=[dict(body_ids=['1'],start=0,stop=2,amplitude=.4)],
                observations=[dict(name='O',body_ids=['3'])],intervention_ids=['2'],gain=.2,
                intervention_start=0,intervention_stop=3)
            return export_task(case,[dict(name='fixed',experiment=cfg)],'shared')
        finally:close_case(case)
    def test_independent_index_order_local_identity_and_reexport(self):
        sender=self.index('sender');receiver=self.index('receiver',reverse=True)
        self.assertNotEqual(sender.manifest['index_id'],receiver.manifest['index_id'])
        definition=self.task(sender);root=self.root/'receiver-cases'
        before=preview_task(receiver,root,definition)
        self.assertTrue(before['compatible']);self.assertTrue(before['verification_required'])
        self.assertIsNone(before['existing_case_path'])
        with patch('cecropis.task_definition.compare',side_effect=AssertionError('prepare must not propagate')):
            prepared=prepare_task(receiver,root,definition)
        self.assertEqual(prepared['status'],'complete',prepared)
        after=preview_task(receiver,root,definition)
        self.assertFalse(after['verification_required'])
        result=run_task(prepared['case_path'],definition)
        self.assertEqual(result['source_index_id'],receiver.manifest['index_id'])
        self.assertEqual(result['task_definition']['source_index_id'],sender.manifest['index_id'])
        case=load_case(prepared['case_path'])
        try:
            actual=content_identity(case)
            self.assertEqual(actual['digest'],definition['scope_content']['digest'])
            # Matrix/node storage permutation is not numerical-content identity.
            order=np.array([2,0,1]);permuted=dict(case,nodes=[case['nodes'][i] for i in order],
                counts=case['counts'][order][:,order].tocsr(),matrix=case['matrix'][order][:,order].tocsr())
            self.assertEqual(content_identity(permuted)['digest'],actual['digest'])
            renamed=copy.deepcopy(case['nodes']);renamed[0]['type']='renamed'
            self.assertEqual(content_identity(dict(case,nodes=renamed))['digest'],actual['digest'])
            self.assertNotEqual(content_identity(dict(case,nodes=renamed))['annotation_digest'],actual['annotation_digest'])
            reexport=export_task(case,result['conditions'],'local-shared')
            self.assertEqual(reexport['source_index_id'],receiver.manifest['index_id'])
        finally:close_case(case)
    def test_mismatch_missing_legacy_rules_and_cancel(self):
        definition=self.task(self.index('sender'))
        for label,kwargs,category in [('edge',dict(weight=6),'internal directed'),('denominator',dict(external=8),'full input')]:
            report=prepare_task(self.index(label,**kwargs),self.root/(label+'-cases'),definition)
            self.assertEqual(report['status'],'failed');self.assertIn(category,report['error'])
            self.assertEqual(list((self.root/(label+'-cases')).glob('*/manifest.json')),[])
        missing=preview_task(self.index('missing',missing=True),self.root/'missing-cases',definition)
        self.assertEqual(missing['scope']['missing_body_ids'],['3']);self.assertFalse(missing['compatible'])
        local=self.index('same');legacy=copy.deepcopy(definition);legacy['schema_version']=1
        legacy.pop('scope_content');legacy.pop('source_data')
        self.assertFalse(preview_task(local,self.root/'legacy',legacy)['compatible'])
        wrong=copy.deepcopy(definition);wrong['scope_content']['rules']['initial_state']='unknown'
        with self.assertRaisesRegex(ValueError,'rules'):normalize_task(wrong)
        wrong=copy.deepcopy(definition);wrong['model_version']='other'
        self.assertFalse(preview_task(local,self.root/'wrong',wrong)['compatible'])
        stopped={'yes':False}
        def progress(value):
            if value['phase']=='verify_scope_content':stopped['yes']=True
        report=prepare_task(local,self.root/'cancelled',definition,cancel=lambda:stopped['yes'],progress=progress)
        self.assertEqual(report['status'],'cancelled',report)
        self.assertEqual(list((self.root/'cancelled').glob('*/manifest.json')),[])
        self.assertTrue(preview_task(local,self.root/'cancelled',definition)['verification_required'])


if __name__=='__main__':unittest.main()
