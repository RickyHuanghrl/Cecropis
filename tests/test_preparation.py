"""Only first-use preparation semantics; tiny Arrow sources, no simulation."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pyarrow as pa
import pyarrow.feather as feather
from cecropis.preparation import (ANNOTATIONS,WEIGHTS,resolve_preparation_paths,
                                    check_preparation,prepare_local,write_workspace)
from cecropis.workspace_config import load_workspace_config
from cecropis.global_index import GlobalIndex


class PreparationChecks(unittest.TestCase):
    def fixture(self,root):
        raw=root/'原始 数据';raw.mkdir()
        feather.write_feather(pa.table({'bodyId':pa.array([10,20,30],type=pa.int64()),
            'type':['input','output',None],'status':['Traced','Traced','Glia']}),raw/ANNOTATIONS)
        feather.write_feather(pa.table({'body_pre':pa.array([10,99,10,20],type=pa.int64()),
            'body_post':pa.array([20,20,20,10],type=pa.int64()),
            'weight':pa.array([2,5,3,7],type=pa.int64())}),raw/WEIGHTS)
        return resolve_preparation_paths(dict(raw=raw,index=root/'连接 索引',cases=root/'范围 目录',runs=root/'结果 目录'))

    def test_first_build_readonly_check_reuse_and_configuration(self):
        with tempfile.TemporaryDirectory(prefix='准备 中文 ') as folder:
            root=Path(folder).resolve();paths=self.fixture(root);output=root/'工作 区'/'workspace.json'
            with patch('cecropis.global_index.ds.dataset',side_effect=AssertionError('Check must not scan')):
                report=check_preparation(paths)
            self.assertTrue(report['can_build']);self.assertFalse(output.parent.exists())
            phases=[]
            result=prepare_local(paths,action='build',output=output,batch_size=2,progress=phases.append)
            self.assertEqual(result['status'],'ready');self.assertEqual(load_workspace_config(output),paths)
            self.assertEqual(phases[0]['phase'],'source_scan');self.assertEqual(phases[-1]['phase'],'complete')
            index=GlobalIndex(paths['index'])
            try:self.assertEqual(index.node('20')['total_input'],10);self.assertEqual(index.incoming.nnz,3)
            finally:index.close()
            identity=result['preparation']['index']['index_id']
            with patch('cecropis.global_index.build_global_index',side_effect=AssertionError('No repeated scan')):
                again=prepare_local(paths,action='build',output=output)
            self.assertTrue(again['index_reused']);self.assertTrue(again['workspace']['reused'])
            self.assertEqual(again['preparation']['index']['index_id'],identity)
            with self.assertRaises(FileExistsError):write_workspace(dict(paths,runs=root/'另一个结果'),output)
            relative=root/'relative.json';relative.write_text(json.dumps(dict(kind='workspace_config',version=1,
                paths={k:str(v.relative_to(root)) for k,v in paths.items()})),encoding='utf-8')
            other=root/'不同 当前目录';other.mkdir()
            self.assertEqual(resolve_preparation_paths(workspace=relative,cwd=other),paths)

    def test_wrong_schema_and_incomplete_scan_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);paths=self.fixture(root)
            control=paths['raw'].parent/(paths['raw'].name+'.download');control.mkdir()
            metadata=control/'source-metadata.json'
            metadata.write_text(json.dumps(dict(dataset='MaleCNS',version='v2.0',confidence='minconf=0.5',dataset_item='connectivity')),encoding='utf-8')
            self.assertEqual(check_preparation(paths)['raw']['status'],'incompatible')
            metadata.unlink()
            feather.write_feather(pa.table({'body_pre':[10],'body_post':[20],'weight':[.5]}),paths['raw']/WEIGHTS)
            report=check_preparation(paths)
            self.assertEqual(report['raw']['status'],'incompatible');self.assertFalse(report['can_build'])
            paths['index'].mkdir();partial=paths['index']/'stage_pre.bin';partial.write_bytes(b'12345678')
            self.assertEqual(check_preparation(paths)['index']['status'],'partial')
            self.assertFalse(check_preparation(paths)['can_resume'])
            self.assertEqual(prepare_local(paths,action='resume')['status'],'blocked')
            self.assertEqual(partial.read_bytes(),b'12345678')

    def test_completed_scan_recovery_and_dependency_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);paths=self.fixture(root)
            with patch('cecropis.global_index._finalize_staging',side_effect=OSError('simulated finalization interruption')):
                with self.assertRaises(OSError):prepare_local(paths,action='build',batch_size=2)
            self.assertTrue(check_preparation(paths)['can_resume'])
            with patch('cecropis.global_index.ds.dataset',side_effect=AssertionError('Resume must not access raw')):
                # Removing only the binding shows resume does not require raw.
                resumed=prepare_local({k:v for k,v in paths.items() if k!='raw'},action='resume',batch_size=2)
            self.assertEqual(resumed['status'],'ready')
            with patch('cecropis.preparation.dependencies',return_value=[dict(name=n,available=False) for n in ('numpy','scipy','pyarrow')]):
                report=check_preparation(paths)
            self.assertFalse(report['ready']);self.assertEqual(report['index']['status'],'unchecked')

    def test_missing_index_serves_preparation_without_workspace(self):
        from cecropis.app import serve
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch('cecropis.app.Workspace',side_effect=AssertionError('No invalid Workspace')),patch('cecropis.preparation_app.serve_preparation',return_value=None) as page:
                self.assertIsNone(serve(None,8512,root/'results',None,root/'absent-index',root/'cases'))
                page.assert_called_once()
                self.assertFalse((root/'results').exists())


if __name__=='__main__':unittest.main()
