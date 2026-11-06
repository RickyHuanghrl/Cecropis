import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from cecropis import MODEL_VERSION
from cecropis.case import load_case, close_case
from cecropis.selection import build_case
from cecropis.simulation import Experiment
from cecropis.task_definition import normalize_task, export_task, preview_task, prepare_task, run_task, validate_task_case

fixture = importlib.util.spec_from_file_location('_task_fixture',Path(__file__).with_name('test_scope_expansion.py'))
fixture_module=importlib.util.module_from_spec(fixture);fixture.loader.exec_module(fixture_module)


class TaskDefinitionChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name);self.index=fixture_module.Index()
        self.index.manifest['source_version']='MaleCNS v1.0 minconf=0.5'
        self.original=build_case(self.index,dict(name='source',scope=dict(body_ids=['10','20','30','80'],hops=0,max_nodes=4),
            groups=dict(input={'I':['10']},internal={'S':['30']},output={'A':['20'],'zero':['80']})),self.root/'original')
        case=load_case(self.original)
        try:
            cfg=Experiment(steps=4,input_group='I',input_start=0,input_stop=2,amplitude=.4,
                intervention_group='S',intervention_start=0,intervention_stop=4,gain=.2,outputs=('A','zero'),
                observations=({'name':'A','body_ids':['20'],'evaluation_window':{'start':1,'stop':4}},
                              {'name':'zero','body_ids':['80'],'evaluation_window':{'start':0,'stop':4}}))
            self.definition=export_task(case,[dict(name='fixed',experiment=cfg,search_options=dict(
                max_nodes=1,target_output='A',min_target_loss=.01,protected_limits={'zero':{'metric':'absolute','max_loss':.1}}))],'portable')
            empty=copy.deepcopy(self.definition['conditions'][0]);empty['name']='empty';empty['role']='extra';empty['experiment']['intervention_ids']=[]
            self.definition['conditions'].append(empty)
            self.definition=normalize_task(self.definition)
        finally:close_case(case)
    def tearDown(self):self.temp.cleanup()

    def test_no_input_events_do_not_create_a_placeholder_input_role(self):
        definition=copy.deepcopy(self.definition)
        for condition in definition['conditions']:
            condition['experiment']['input_events']=[]
        with patch('cecropis.task_definition.compare',side_effect=AssertionError('preparation cannot propagate')):
            built=prepare_task(self.index,self.root/'no-input',definition)
        self.assertEqual(built['status'],'complete')
        case=load_case(built['case_path'])
        try:
            self.assertEqual(case['manifest']['roles']['input'],0)
            self.assertEqual(case['manifest']['groups']['input'],{})
            self.assertTrue(all(not node['memberships']['input'] for node in case['nodes']))
        finally:close_case(case)

    def test_exact_scope_preview_build_dense_execution_and_reuse(self):
        destination=self.root/'independent'/'cases'
        with patch('cecropis.task_definition.compare',side_effect=AssertionError('preview/preparation cannot propagate')):
            preview=preview_task(self.index,destination,self.definition)
            self.assertTrue(preview['build_allowed']);self.assertEqual(preview['scope']['node_count'],4)
            self.assertFalse(destination.exists());self.assertIsNone(preview['existing_case_path'])
            built=prepare_task(self.index,destination,self.definition)
            self.assertEqual(built['status'],'complete');self.assertFalse(built['reused'])
            reused=prepare_task(self.index,destination,self.definition)
            self.assertTrue(reused['reused']);self.assertEqual(reused['case_path'],built['case_path'])
        original=load_case(self.original);prepared=load_case(built['case_path'])
        try:
            np.testing.assert_array_equal(prepared['counts'].toarray(),original['counts'].toarray())
            np.testing.assert_array_equal(prepared['matrix'].toarray(),original['matrix'].toarray())
            self.assertEqual([n['total_input'] for n in prepared['nodes']],[n['total_input'] for n in original['nodes']])
            matrix=prepared['matrix'].toarray();lookup={n['bodyId']:i for i,n in enumerate(prepared['nodes'])}
        finally:close_case(original);close_case(prepared)
        result=run_task(built['case_path'],self.definition)
        self.assertEqual(result['status'],'complete');self.assertEqual(result['baseline_simulations'],2)
        self.assertEqual(result['completed_intervention_simulations'],2)
        self.assertEqual(result['rows'][1]['body_ids'],[])
        self.assertEqual(result['constraints'][1]['constraints']['condition_results'][0]['evidence_classification'],'extra')
        # Independently hand-code the current recurrence and exact window indices.
        trajectories=[]
        for bodies in ([],['30']):
            history=[np.zeros(4)]
            for t in range(4):
                drive=np.zeros(4)
                if t<2:drive[lookup['10']]=.4
                activation=np.tanh((1-.3)*history[-1]+.3*(drive+.9*matrix@history[-1]))
                for body in bodies:activation[lookup[body]]*=.2
                history.append(activation)
            trajectories.append(np.array(history))
        summary=result['results'][0]['summary'][0]
        self.assertAlmostEqual(summary['baseline_mean'],trajectories[0][2:5,lookup['20']].sum()/3)
        self.assertAlmostEqual(summary['intervention_mean'],trajectories[1][2:5,lookup['20']].sum()/3)
        self.assertEqual(result['results'][1]['series']['A']['baseline'],result['results'][1]['series']['A']['intervention'])

    def test_active_scope_validation_and_selected_recording(self):
        case=load_case(self.original)
        try:
            self.assertEqual(validate_task_case(case,self.definition),self.definition)
            other=copy.deepcopy(self.definition);other['scope']['body_ids'].append('99')
            with self.assertRaisesRegex(ValueError,'exact members'):validate_task_case(case,other)
            changed=dict(case,manifest=dict(case['manifest'],model_version='other-model'))
            with self.assertRaisesRegex(ValueError,'model identity'):validate_task_case(changed,self.definition)
        finally:close_case(case)
        selected=copy.deepcopy(self.definition)
        for item in selected['conditions']:item['recording']=dict(mode='selected',body_ids=['20'],steps=[0,2,4])
        preview=preview_task(self.index,self.root/'cases',selected)
        self.assertEqual(preview['estimated_recording_bytes'],2*2*3*8)
        result=run_task(self.original,selected)
        self.assertEqual(result['counters']['completed_baseline_simulations'],2)
        for row in result['results']:
            self.assertEqual(row['recording_metadata']['body_ids'],['20'])
            self.assertEqual(row['states'][0].shape,(3,1))
        case=load_case(self.original)
        try:
            exported=export_task(case,[dict(name='again',experiment=result['results'][1]['config']['experiment'])],'reexport')
            self.assertEqual(exported['conditions'][0]['experiment']['intervention_ids'],[])
            exported=export_task(case,[dict(name='again',experiment=result['results'][0]['config']['experiment'])],'reexport')
            self.assertEqual(exported['conditions'][0]['experiment']['intervention_ids'],['30'])
        finally:close_case(case)

    def test_identity_missing_members_invalid_fields_and_cancel(self):
        bad=copy.deepcopy(self.definition);bad['conditions'][1]['name']='fixed'
        with self.assertRaisesRegex(ValueError,'unique'):normalize_task(bad)
        bad=copy.deepcopy(self.definition);bad['conditions'][0]['experiment']['observations'][0]['evaluation_window']['stop']=5
        with self.assertRaisesRegex(ValueError,'evaluation_window'):normalize_task(bad)
        bad=copy.deepcopy(self.definition);bad['script']='malicious'
        with self.assertRaisesRegex(ValueError,'fields'):normalize_task(bad)
        bad=copy.deepcopy(self.definition);bad['source_index_id']='different'
        bad['schema_version']=1;bad.pop('scope_content');bad.pop('source_data')
        self.assertFalse(preview_task(self.index,self.root/'cases',bad)['compatible'])
        bad=copy.deepcopy(self.definition);bad['scope']['body_ids'].append('999')
        preview=preview_task(self.index,self.root/'cases',bad)
        self.assertEqual(preview['scope']['missing_body_ids'],['999']);self.assertFalse(preview['build_allowed'])
        self.assertFalse(preview_task(self.index,self.root/'cases',self.definition,dict(max_bytes=1))['build_allowed'])
        stopped={'yes':False}
        def progress(value):
            if value['phase']=='build':stopped['yes']=True
        cancelled=prepare_task(self.index,self.root/'cases',self.definition,cancel=lambda:stopped['yes'],progress=progress)
        self.assertEqual(cancelled['status'],'cancelled')
        self.assertEqual(list((self.root/'cases').glob('*/manifest.json')),[])
        built=prepare_task(self.index,self.root/'othercases',self.definition)
        stopped['yes']=False
        def execution(value):
            if value.get('kind')=='baseline' and value.get('status')=='completed':stopped['yes']=True
        result=run_task(built['case_path'],self.definition,cancel=lambda:stopped['yes'],progress=execution)
        self.assertEqual(result['status'],'cancelled');self.assertEqual(result['completed_conditions'],0)
        self.assertEqual(result['baseline_simulations'],1);self.assertEqual(result['completed_baseline_simulations'],1)
        self.assertEqual(result['intervention_simulations'],1);self.assertEqual(result['completed_intervention_simulations'],0)
        self.assertEqual([r['status'] for r in result['condition_statuses']],['cancelled','not_run'])


if __name__=='__main__':unittest.main()
