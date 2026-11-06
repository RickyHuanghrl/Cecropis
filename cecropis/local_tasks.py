"""Single-machine ownership and durable completed-unit journals for two executors."""
import copy
import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np

SEMANTICS = 'local-completed-units-v1'
KINDS = ('response_exploration', 'operation_search')
RUNNABLE = ('pending', 'paused', 'interrupted', 'failed', 'cancelled')


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    payload=json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
    if len(payload)>64*1024**2:raise ValueError('Task checkpoint exceeds 64 MiB')
    temp=path.with_name('.'+path.name+'.'+uuid4().hex)
    try:
        with temp.open('wb') as stream:
            stream.write(payload);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:
        if temp.exists():temp.unlink()


class LocalSlot:
    """Kernel byte lock, released by process death; the lock file is never deleted."""
    def __init__(self, root, name='compute.lock'):
        self.root=Path(root).expanduser().resolve();self.name=name;self.stream=None

    def __enter__(self):
        self.root.mkdir(parents=True,exist_ok=True)
        self.stream=(self.root/self.name).open('a+b')
        if self.stream.seek(0,os.SEEK_END)==0:self.stream.write(b'0');self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close();self.stream=None
            raise ValueError('The local workspace computation slot is owned by another executor') from exc
        return self

    def __exit__(self,*args):
        if self.stream is None:return
        try:
            self.stream.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(),fcntl.LOCK_UN)
        finally:self.stream.close();self.stream=None


class LocalTasks:
    def __init__(self, results_root):
        self.root=Path(results_root).expanduser().resolve()/'local-tasks'
        self.thread=None
        self.task_ids=[]

    def folder(self, task_id):
        if not isinstance(task_id,str) or not re.fullmatch(r'local-[a-f0-9]{32}',task_id):raise ValueError('Invalid local task ID')
        return self.root/task_id

    def _read(self, task_id):
        path=self.folder(task_id)/'task.json'
        if path.stat().st_size>64*1024**2:raise ValueError('Task document exceeds 64 MiB')
        doc=json.loads(path.read_text(encoding='utf-8'))
        if doc.get('kind')!='local_task' or doc.get('version')!=1 or doc.get('task_id')!=task_id:raise ValueError('Unsupported local task')
        return doc

    def _write(self, doc):
        doc['updated_at']=now();atomic_json(self.folder(doc['task_id'])/'task.json',doc)

    def busy(self):
        try:
            with LocalSlot(self.root):return False
        except ValueError:return True

    def _recover(self):
        try:
            with LocalSlot(self.root):
                for path in sorted(self.root.glob('local-*/task.json')):
                    doc=self._read(path.parent.name)
                    if doc['status'] not in ('running','pause_requested'):continue
                    doc.update(status='interrupted',stop_reason='executor_ended_without_final_commit')
                    for attempt in doc['attempts']:
                        if attempt['status']=='started':attempt['status']='completion_unknown'
                    doc['uncommitted_attempts']=[a['id'] for a in doc['attempts'] if a['status'] in ('completion_unknown','completed_uncommitted')]
                    self._write(doc)
        except ValueError as exc:
            if 'slot is owned' not in str(exc):raise

    def read(self, task_id):
        self._recover();doc=self._read(task_id)
        control=self._control(task_id)
        if doc['status']=='running' and control.get('pause'):doc['status']='pause_requested'
        return doc

    def list(self):
        self._recover()
        values=[self.summary(self._read(path.parent.name)) for path in sorted(self.root.glob('local-*/task.json'))]
        return sorted(values,key=lambda d:(d['created_at'],d['task_id']))

    def summary(self, doc):
        report=doc['checkpoint']['report'];kind=doc['task_type']
        if kind=='response_exploration':
            done=len(doc['branch_files']);total=report['preview']['expected_propagations']
            counts=report['execution_counts'];remaining=total-done
        else:
            done=report['evaluations'];total=report['definition']['settings']['max_evaluations'];remaining=None
            counts={k:report.get(k,0) for k in ('baseline_started','baseline_completed','intervention_started','intervention_completed','physical_started','physical_completed','cache_hits')}
        status=doc['status']
        if status=='running' and self._control(doc['task_id']).get('pause'):status='pause_requested'
        return dict(task_id=doc['task_id'],task_type=kind,name=doc['name'],created_at=doc['created_at'],
            status=status,identity=doc['identity'],completed_units=done,total_or_budget=total,remaining_units=remaining,
            progress=doc.get('progress',{}),counts=counts,reused_units=doc['reused_units'],
            retries=sum(a.get('retry',False) for a in doc['attempts']),stop_reason=doc.get('stop_reason'),error=doc.get('error'),
            elapsed_seconds=doc.get('elapsed_seconds',0),
            estimated_persistent_bytes=doc.get('estimated_persistent_bytes'),
            estimated_executor_and_reader_bytes=doc.get('estimated_executor_and_reader_bytes'),
            uncommitted_attempt_count=sum(a['status'] in ('started','completion_unknown','completed_uncommitted','cancelled_uncommitted') for a in doc['attempts']),
            frontier=doc['checkpoint'].get('pending'),frontier_position=doc['checkpoint'].get('position'),
            checkpoint_reference='task.json',result_reference='task.json#checkpoint.report')

    def submit(self, case_path, task_type, definition):
        if task_type not in KINDS:raise ValueError('Only responses and operation searches support durable execution')
        from .api import Lab
        from .scope_content import content_identity
        from .replay import _identity
        from .response_exploration import initialize_responses, preview_responses, ARRAYS
        from .operation_search import initialize_operation_search
        lab=Lab(case_path)
        try:
            if task_type=='response_exploration':
                preview=preview_responses(lab.case,definition)
                # Incremental uncompressed arrays are also the final numerical
                # store; no second condition matrix is created on completion.
                expected=preview['estimated_storage_bytes']+4096*(preview['expected_propagations']+4)
                if expected>preview['definition']['budgets']['max_storage_bytes']:raise ValueError('Persistent branch files and headers exceed response storage budget')
                peak=preview['estimated_memory_bytes']+preview['array_bytes']
                if peak>preview['definition']['budgets']['max_bytes']:raise ValueError('Executor plus one partial-result reader exceeds response memory budget')
                report=initialize_responses(lab.case,preview['definition']);state={'report':{k:v for k,v in report.items() if k not in ARRAYS}}
            else:
                state=initialize_operation_search(lab.case,definition);report=state['report']
            ident='local-'+uuid4().hex;folder=self.folder(ident);folder.mkdir(parents=True)
            doc=dict(kind='local_task',version=1,task_id=ident,task_type=task_type,name=report['definition']['name'],
                created_at=now(),status='pending',semantics=SEMANTICS,case_path=str(Path(case_path).resolve()),
                identity=_identity(lab.case),scope_content=content_identity(lab.case),
                member_order=[str(n['bodyId']) for n in lab.case['nodes']],
                definition=copy.deepcopy(report['definition']),definition_hash=report['definition_hash'],checkpoint=state,
                attempts=[],branch_files={},reused_units=0,progress={},error=None,stop_reason=None,elapsed_seconds=0)
            if task_type=='response_exploration':
                for key in ('body_ids','membership'):self._array(folder/(key+'.npy'),report[key])
                doc['estimated_persistent_bytes']=expected
                doc['estimated_executor_and_reader_bytes']=peak
            self._write(doc);atomic_json(folder/'control.json',{})
            return self.summary(doc)
        finally:lab.close()

    @staticmethod
    def _array(path, values):
        temp=path.with_name('.'+path.name+'.'+uuid4().hex)
        try:
            with temp.open('wb') as stream:
                np.save(stream,values,allow_pickle=False);stream.flush();os.fsync(stream.fileno())
            os.replace(temp,path)
        finally:
            if temp.exists():temp.unlink()

    def _control(self, task_id):
        path=self.folder(task_id)/'control.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}

    def _member_order(self, doc, case):
        if 'member_order' in doc:return doc['member_order']
        # Early files produced during this segment already freeze the response
        # order in body_ids.npy. Search checkpoints contain named scalar sums,
        # not position-indexed baseline vectors.
        if doc['task_type']=='response_exploration':
            return [str(i) for i in np.load(self.folder(doc['task_id'])/'body_ids.npy',allow_pickle=False)]
        return [str(n['bodyId']) for n in case['nodes']]

    def request(self, task_id, action):
        if action not in ('pause','cancel'):raise ValueError('Request pause or cancel')
        with LocalSlot(self.folder(task_id),'control.lock'):
            doc=self._read(task_id)
            if doc['status']=='pending' and action=='cancel':
                doc.update(status='cancelled',stop_reason='cancelled_before_start');self._write(doc)
            elif doc['status']=='running':
                values=self._control(task_id);values[action]=True;atomic_json(self.folder(task_id)/'control.json',values)
            else:raise ValueError('This task is not running')
        return self.summary(doc)

    def copy(self, task_id):
        doc=self.read(task_id)
        return self.submit(doc['case_path'],doc['task_type'],doc['definition'])

    def result(self, task_id):
        doc=self.read(task_id);report=copy.deepcopy(doc['checkpoint']['report'])
        if doc['task_type']=='operation_search':
            state=doc['checkpoint'];report['pending_layer']=None if state['pending'] is None else dict(
                depth=state['depth'],position=state['position'],pending=state['pending'][state['position']:],
                evaluated=state['evaluated'],parent_beam=state['beam'])
        else:
            folder=self.folder(task_id)
            for k in ('body_ids','membership'):report[k]=np.load(folder/(k+'.npy'),allow_pickle=False)
            n=len(report['body_ids']);c=len(report['definition']['conditions'])
            for branch in ('baseline','intervention'):report[branch]=np.full((c,n),np.nan)
            for key,file in doc['branch_files'].items():
                i,b=key.split(':');values=np.load(folder/file,allow_pickle=False)
                if values.shape!=(n,) or not np.isfinite(values).all():raise ValueError('Committed response branch is missing or invalid')
                report[b][int(i)]=values
        display=self.folder(task_id)/'display.json'
        if display.exists():report['display']=json.loads(display.read_text(encoding='utf-8'))
        report['local_task_id']=task_id;report['status']=doc['status']
        return report

    def _run_one(self, task_id, progress, expected_status=None):
        import time
        from .api import Lab
        from .scope_content import content_identity
        from .response_exploration import explore_responses, preview_responses, ARRAYS
        from .operation_search import search_operations, preview_operation_search
        doc=self._read(task_id)
        if expected_status is not None and doc['status']!=expected_status:return self.summary(doc)
        if doc['status'] not in RUNNABLE:raise ValueError('Task cannot continue from '+doc['status'])
        lab=None;began=time.perf_counter();save_failed=[False]
        try:
            lab=Lab(doc['case_path'])
            preview=(preview_responses if doc['task_type']=='response_exploration' else preview_operation_search)(lab.case,doc['definition'])
            from .replay import _identity
            if (doc['semantics']!=SEMANTICS or _identity(lab.case)!=doc['identity'] or
                [str(n['bodyId']) for n in lab.case['nodes']]!=self._member_order(doc,lab.case) or
                preview['definition_hash']!=doc['definition_hash'] or content_identity(lab.case)!=doc['scope_content']):
                raise ValueError('Task scope/data/model/execution definition does not match; existing results retained')
            # Record prior unfinished attempts rather than erasing their costs.
            for a in doc['attempts']:
                if a['status']=='started':a['status']='completion_unknown'
            doc['reused_units']+=len(doc['branch_files']) if doc['task_type']=='response_exploration' else len(doc['checkpoint']['baselines'])+doc['checkpoint']['report']['evaluations']
            with LocalSlot(self.folder(task_id),'control.lock'):
                latest=self._read(task_id)
                if latest['status']!=doc['status']:return self.summary(latest)
                if doc['status']!='pending':
                    doc.setdefault('stop_history',[]).append(dict(status=doc['status'],reason=doc.get('stop_reason'),error=doc.get('error'),at=now()))
                atomic_json(self.folder(task_id)/'control.json',{})
                doc.update(status='running',owner=dict(pid=os.getpid(),lease=uuid4().hex,started_at=now()),error=None,stop_reason=None)
                self._write(doc)
            def tick(p):
                doc['progress']=p;progress(dict(task_id=task_id,**p))
            def store(state, event):
                if save_failed[0]:raise OSError('Checkpoint writer failed; no later state can be published')
                try:
                    report=state if doc['task_type']=='response_exploration' else state['report']
                    branch=event.get('branch');unit=event.get('unit',event.get('condition'))
                    if isinstance(unit,str) and len(unit)>100:unit=hashlib.sha256(unit.encode()).hexdigest()
                    if event['kind']=='started':
                        prior=any(a['branch']==branch and a['unit']==unit and a.get('condition')==event.get('condition') for a in doc['attempts'])
                        doc['attempts'].append(dict(id=uuid4().hex,branch=branch,unit=unit,condition=event.get('condition'),
                            evaluation_attempt=report.get('attempted_evaluations') if branch=='intervention' and doc['task_type']=='operation_search' else None,
                            status='started',retry=prior,started_at=now()))
                    if event['kind'] in ('physical_completed','committed','baseline_committed'):
                        active=next((a for a in reversed(doc['attempts']) if a['status']=='started'),None)
                        if active:active.update(status='completed_uncommitted',completed_at=now())
                    if doc['task_type']=='response_exploration':
                        counts=report['execution_counts'];counts['physical_started']=counts['baseline_started']+counts['intervention_started'];counts['physical_completed']=counts['baseline_completed']+counts['intervention_completed']
                        if event['kind']=='committed':
                            # Publish known physical completion first, never the
                            # branch marker before the numerical file is durable.
                            old=doc['checkpoint']['report'];old['execution_counts']=copy.deepcopy(counts);self._write(doc)
                            i=event['condition'];file=f'{i}-{branch}.npy'
                            self._array(self.folder(task_id)/file,report[branch][i])
                            doc['branch_files'][f'{i}:{branch}']=file
                        doc['checkpoint']={'report':copy.deepcopy({k:v for k,v in report.items() if k not in ARRAYS})}
                    else:doc['checkpoint']=copy.deepcopy(state)
                    if event['kind'] in ('committed','baseline_committed','combination_committed'):
                        if event['kind']=='combination_committed':
                            for a in doc['attempts']:
                                if (a['status']=='completed_uncommitted' and a['branch']=='intervention' and a['unit']==unit and
                                    a.get('evaluation_attempt')==report['attempted_evaluations']):a['status']='committed'
                        else:
                            # A retried unit does not retroactively submit the
                            # numerical work discarded by an earlier attempt.
                            current=next((a for a in reversed(doc['attempts']) if a['status']=='completed_uncommitted' and
                                a['unit']==unit and a['branch']==branch and a.get('condition')==event.get('condition')),None)
                            if current:current['status']='committed'
                    self._write(doc)
                except Exception:
                    save_failed[0]=True;raise
            cancel=lambda:self._control(task_id).get('cancel',False)
            pause=lambda:self._control(task_id).get('pause',False)
            if doc['task_type']=='response_exploration':
                result=self.result(task_id)
                result=explore_responses(lab.case,doc['definition'],resume=result,cancel=cancel,pause=pause,progress=tick,checkpoint=store)
                if not save_failed[0]:store(result,dict(kind='stopped'))
            else:
                result=search_operations(lab.case,doc['definition'],resume=copy.deepcopy(doc['checkpoint']),cancel=cancel,pause=pause,progress=tick,checkpoint=store)
            if save_failed[0]:raise OSError('Checkpoint write failed; last published units retained')
            doc.update(status=result['status'],stop_reason=result.get('termination_reason',result['status']),error=result.get('error'))
            for a in doc['attempts']:
                if a['status']=='started':a['status']='cancelled_uncommitted' if doc['status']=='cancelled' else 'completion_unknown'
            doc['elapsed_seconds']+=time.perf_counter()-began;self._write(doc)
        except Exception as exc:
            saved=self._read(task_id);saved.update(status='failed',error=str(exc),stop_reason='execution_or_checkpoint_failed')
            for a in saved['attempts']:
                if a['status']=='started':a['status']='completion_unknown'
            saved['elapsed_seconds']+=time.perf_counter()-began;self._write(saved)
        finally:
            if lab is not None:lab.close()
        return self.summary(self._read(task_id))

    def execute(self, task_ids, *, background=False, progress=lambda p:None):
        ids=list(task_ids)
        if not ids or len(ids)!=len(set(ids)):raise ValueError('Choose distinct tasks in execution order')
        initial={}
        for ident in ids:
            initial[ident]=self.read(ident)['status']
            if initial[ident] not in RUNNABLE:raise ValueError('Task is not resumable: '+ident)
        slot=LocalSlot(self.root);slot.__enter__()
        def work():
            outputs=[]
            try:
                atomic_json(self.root/'owner.json',dict(pid=os.getpid(),task_ids=ids,created_at=now()))
                for ident in ids:
                    result=self._run_one(ident,progress,initial[ident]);outputs.append(result)
                    if result['status'] not in ('complete','budget_exhausted'):break
                return outputs
            finally:slot.__exit__()
        if background:
            self.task_ids=ids
            self.thread=threading.Thread(target=work,daemon=True);self.thread.start()
            return dict(task_ids=ids,status='starting')
        return work()

    def save_display(self, task_id, display):
        """Keep presentation separate from the immutable execution checkpoint."""
        if not isinstance(display,dict):raise ValueError('Display state must be an object')
        atomic_json(self.folder(task_id)/'display.json',display)

    def check(self, task_id):
        """Read-only resume qualification; no unit is started or repaired."""
        from .api import Lab
        from .scope_content import content_identity
        from .response_exploration import preview_responses
        from .operation_search import preview_operation_search
        doc=self.read(task_id);lab=Lab(doc['case_path'])
        try:
            preview=(preview_responses if doc['task_type']=='response_exploration' else preview_operation_search)(lab.case,doc['definition'])
            from .replay import _identity
            if (doc['semantics']!=SEMANTICS or _identity(lab.case)!=doc['identity'] or
                [str(n['bodyId']) for n in lab.case['nodes']]!=self._member_order(doc,lab.case) or
                preview['definition_hash']!=doc['definition_hash'] or content_identity(lab.case)!=doc['scope_content']):
                raise ValueError('Task scope/data/model/execution definition does not match; existing results retained')
            return dict(task_id=task_id,compatible=True,resumable=doc['status'] in RUNNABLE,preview=preview)
        finally:lab.close()
