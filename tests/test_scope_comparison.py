"""Focused checks for fixed-ID comparisons across saved calculation scopes."""
import copy
from dataclasses import asdict
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy import sparse

from cecropis import MODEL_VERSION
from cecropis.case import close_case, load_case
from cecropis.simulation import Experiment, RecordPolicy, compare
from cecropis.scope_comparison import (compare_scopes, preview_scopes,
    save_scope_comparison, discard_recordings)


class ScopeComparisonChecks(unittest.TestCase):
    def make_case(self, root, name, ids, edges, index='tiny-index'):
        path = root / name
        path.mkdir()
        positions = {body: i for i, body in enumerate(ids)}
        counts = sparse.coo_matrix(([weight for _, _, weight in edges],
            ([positions[post] for pre, post, weight in edges],
             [positions[pre] for pre, post, weight in edges])),
            shape=(len(ids), len(ids)), dtype=np.int64).tocsr()
        matrix = (counts / 10).tocsr()
        for label, csr in [('counts', counts), ('propagation', matrix)]:
            for key in ('data', 'indices', 'indptr'):
                np.save(path / f'{label}_{key}.npy', getattr(csr, key))
        nodes = [dict(bodyId=body, type=f'node-{body}', role='context',
                      memberships={}, total_input=10) for body in ids]
        (path / 'nodes.json').write_text(json.dumps(nodes), encoding='utf-8')
        manifest = dict(case_id=name, case_name=name, source_index_id=index,
            format='csr-arrays-v1', node_count=len(ids), scan=dict(internal_edges=counts.nnz),
            internal_contacts=int(counts.sum()), external_input_contacts=20,
            external_output_contacts=30, total_input_contacts=20+int(counts.sum()))
        (path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        return dict(case_id=name, case_path=str(path))

    def fixture(self, root):
        small = self.make_case(root, 'small', [30, 10, 20], [(10,20,6),(20,30,8)])
        large = self.make_case(root, 'large', [40, 20, 30, 10],
            [(10,20,6),(20,30,8),(10,40,4),(40,30,3)])
        return dict(model_version=MODEL_VERSION, source_index_id='tiny-index',
            cases=[small,large], experiment=dict(steps=12,
                input_events=[dict(body_ids=['10'],start=0,stop=4,amplitude=.5),
                              dict(body_ids=['20'],start=3,stop=5,amplitude=.2)],
                observations=[dict(name='out',body_ids=['30']),
                              dict(name='overlap',body_ids=['20','30'])],
                intervention_ids=['10'], intervention_start=2,intervention_stop=9,gain=.3),
            recording=dict(mode='selected',body_ids=['30','10'],steps=[0,3,12]))

    def test_id_mapping_endpoint_intervention_and_independent_baselines(self):
        with tempfile.TemporaryDirectory() as temporary:
            config=self.fixture(Path(temporary))
            preview=preview_scopes(config)
            self.assertTrue(preview['compatible'])
            self.assertEqual([c['node_count'] for c in preview['cases']],[3,4])
            self.assertEqual(preview['recording_total_bytes'],192)
            self.assertEqual(preview['recording_peak_bytes'],96)
            report=compare_scopes(config)
            try:
                self.assertEqual(report['status'],'complete')
                a,b=[scope['result'] for scope in report['scopes']]
                self.assertNotEqual(a['series']['out']['baseline'],b['series']['out']['baseline'])
                self.assertEqual(a['intervention_body_ids'],['10'])
                for scope in report['scopes']:
                    self.assertEqual(scope['result']['config']['experiment'],
                        json.loads(json.dumps(asdict(Experiment.from_dict(config['experiment'])))))
                    self.assertEqual(scope['recording_metadata']['body_ids'],['30','10'])
                    self.assertNotIn('states',scope['result'])
                self.assertEqual(report['config']['experiment']['alpha'],.3)
                self.assertEqual(report['config']['experiment']['rho'],.9)
                # Changing array order cannot change the original-ID result.
                reordered=self.make_case(Path(temporary),'reordered',[10,20,30],[(10,20,6),(20,30,8)])
                same=copy.deepcopy(config)
                same['cases']=[config['cases'][0],reordered]
                again=compare_scopes(same)
                try:
                    self.assertEqual(again['scopes'][0]['result']['series'],again['scopes'][1]['result']['series'])
                finally: discard_recordings(again)
            finally: discard_recordings(report)

    def test_missing_members_and_versions_block_every_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            config=self.fixture(Path(temporary))
            missing=self.make_case(Path(temporary),'missing',[10],[])
            config['cases'][1]=missing
            preview=preview_scopes(config)
            self.assertFalse(preview['compatible'])
            self.assertEqual(preview['cases'][1]['missing_members'],dict(
                input=['20'],observations=['20','30'],intervention=[],recording=['30']))
            with patch('cecropis.scope_comparison.compare') as run:
                with self.assertRaises(ValueError): compare_scopes(config)
                run.assert_not_called()
            config['cases'][1]=self.make_case(Path(temporary),'different',[10,20,30],[],index='other')
            self.assertFalse(preview_scopes(config)['compatible'])
            config['model_version']='other-model'
            with self.assertRaises(ValueError): preview_scopes(config)

    def test_explicit_protocol_required_and_recording_cap_preflight(self):
        with tempfile.TemporaryDirectory() as temporary:
            config=self.fixture(Path(temporary))
            for field in ['input_events','observations','intervention_ids']:
                bad=copy.deepcopy(config);bad['experiment'].pop(field)
                with self.subTest(field=field),self.assertRaises(ValueError): preview_scopes(bad)
            config['recording']['max_bytes']=8
            with patch('cecropis.scope_comparison.compare') as run:
                self.assertFalse(preview_scopes(config)['compatible'])
                with self.assertRaises(ValueError): compare_scopes(config)
                run.assert_not_called()

    def test_sequential_release_cancel_failure_and_save_reopen(self):
        with tempfile.TemporaryDirectory() as temporary:
            config=self.fixture(Path(temporary))
            cancelled=[False]
            def progress(value):
                if value['completed']==1: cancelled[0]=True
            result=compare_scopes(config,cancel=lambda:cancelled[0],progress=progress)
            try:
                self.assertEqual(result['status'],'cancelled')
                self.assertEqual([c['status'] for c in result['scopes']],['completed','not_run'])
                folder=save_scope_comparison(Path(temporary)/'runs',result)
                saved=json.loads((folder/'scope-comparison.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['status'],'cancelled')
                self.assertNotIn('recording_files',saved)
                self.assertEqual(json.loads((folder/'config.json').read_text()),result['config'])
                arrays=list(folder.glob('*/states.npz'))
                self.assertEqual(len(arrays),1)
                self.assertEqual(np.load(arrays[0])['baseline'].shape,(3,2))
            finally: discard_recordings(result)
            calls=[0]
            def fail_second(*args,**kwargs):
                calls[0]+=1
                if calls[0]==2: raise RuntimeError('fixture failure')
                return compare(*args,**kwargs)
            with patch('cecropis.scope_comparison.compare',side_effect=fail_second):
                result=compare_scopes(config)
            try:
                self.assertEqual(result['status'],'failed')
                self.assertEqual([c['status'] for c in result['scopes']],['completed','failed'])
                self.assertIn('fixture failure',result['scopes'][1]['error'])
            finally: discard_recordings(result)

    def test_one_loaded_scope_and_cancellation_inside_updates(self):
        with tempfile.TemporaryDirectory() as temporary:
            config=self.fixture(Path(temporary))
            active=[0]
            def track_load(path):
                self.assertEqual(active[0],0,'another scope is still loaded')
                case=load_case(path);active[0]+=1
                return case
            def track_close(case):
                close_case(case);active[0]-=1
            cancelled=[False]
            from cecropis.simulation import _next_state
            def cancel_after_step(*args,**kwargs):
                next_state=_next_state(*args,**kwargs)
                cancelled[0]=True
                return next_state
            with patch('cecropis.scope_comparison.load_case',side_effect=track_load), \
                 patch('cecropis.scope_comparison.close_case',side_effect=track_close), \
                 patch('cecropis.simulation._next_state',side_effect=cancel_after_step):
                result=compare_scopes(config,cancel=lambda:cancelled[0])
            self.assertEqual(active[0],0)
            self.assertEqual(result['status'],'cancelled')
            self.assertEqual([row['status'] for row in result['scopes']],['cancelled','not_run'])
            self.assertEqual(result['recording_files'],{})
            self.assertIsNone(result['scopes'][0]['result'])

    def test_complete_saved_config_replay_and_owned_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            config=self.fixture(Path(temporary))
            result=compare_scopes(config)
            try:
                folder=save_scope_comparison(Path(temporary)/'runs',result)
                saved=json.loads((folder/'scope-comparison.json').read_text(encoding='utf-8'))
                with self.assertRaisesRegex(ValueError, 'trajectories are unavailable'):
                    save_scope_comparison(Path(temporary)/'bad-resave',saved)
                replay=compare_scopes(json.loads((folder/'config.json').read_text(encoding='utf-8')))
                try:
                    for left,right in zip(saved['scopes'],replay['scopes']):
                        self.assertEqual(left['result']['series'],right['result']['series'])
                        self.assertEqual(left['result']['summary'],right['result']['summary'])
                        with np.load(folder/left['recording_file']) as a, \
                             np.load(replay['recording_files'][right['case_id']]) as b:
                            np.testing.assert_array_equal(a['baseline'],b['baseline'])
                            np.testing.assert_array_equal(a['intervention'],b['intervention'])
                finally: discard_recordings(replay)
                unrelated=Path(temporary)/'keep.npz';unrelated.write_text('keep')
                with self.assertRaises(ValueError):
                    discard_recordings(dict(recording_files=dict(unrelated=str(unrelated))))
                self.assertTrue(unrelated.exists())
            finally: discard_recordings(result)


if __name__=='__main__': unittest.main()
