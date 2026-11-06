"""A single asynchronous search job with bounded retained state."""
import copy
import threading
from uuid import uuid4


class SearchJob:
    def __init__(self, results_root=None):
        self.results_root=results_root
        self.lock=threading.Lock()
        self.cancel_event=threading.Event()
        self.state=None

    def start(self,lab,cfg,options):
        cfg.validate(lab.case['nodes']);options.validate()
        from .search import resolve_candidates
        resolve_candidates(lab.case,cfg,options)
        return self._start(lambda cancel,progress:lab.search(cfg,options,cancel=cancel,progress=progress),'search')

    def start_joint(self,lab,conditions,options):
        preview=lab.joint_search_preview(conditions,options)
        if not preview['candidate_count']:
            raise ValueError('No eligible joint candidates remain; all selected protocols define the endpoint exclusions')
        request=copy.deepcopy(conditions)
        selected_options=copy.deepcopy(options)
        return self._start(lambda cancel,progress:lab.joint_search(request,selected_options,
                           cancel=cancel,progress=progress),'joint_search')

    def start_timing(self,lab,conditions,body_ids,starts,durations,options):
        # Use the same bounded task/cancel state; preflight never propagates.
        lab.timing_preview(conditions,body_ids,starts,durations,options)
        request=copy.deepcopy((conditions,body_ids,starts,durations,options))
        return self._start(lambda cancel,progress:lab.explore_timing(*request,
                           cancel=cancel,progress=progress),'timing_exploration')

    def start_reduction(self,lab,conditions,body_ids,options,*,simplify=False,extra_conditions=None):
        lab.reduction_preview(conditions,body_ids,options,simplify=simplify,extra_conditions=extra_conditions)
        request=copy.deepcopy((conditions,body_ids,options))
        extras=copy.deepcopy(extra_conditions)
        return self._start(lambda cancel,progress:lab.analyze_reduction(*request,
            simplify=simplify,extra_conditions=extras,cancel=cancel,progress=progress),'plan_reduction')

    def start_replay(self,lab,source,request):
        lab.replay_preview(source,request)
        # The server owns source histories. Do not deep-copy a large NPZ history
        # merely to dispatch a read-only, explicitly bounded replay preparation.
        options=copy.deepcopy(request)
        return self._start(lambda cancel,progress:lab.prepare_replay(source,options,
                           cancel=cancel,progress=progress),'circuit_replay')

    def start_differences(self,lab,source,request):
        lab.difference_preview(source,request)
        options=copy.deepcopy(request)
        return self._start(lambda cancel,progress:lab.prepare_differences(source,options,
                           cancel=cancel,progress=progress),'scope_differences')

    def start_difference_replay(self,lab,result,node_ids,request):
        lab.difference_replay_preview(result,node_ids,request)
        options=copy.deepcopy(request)
        nodes=copy.deepcopy(node_ids)
        return self._start(lambda cancel,progress:lab.prepare_difference_replay(result,nodes,options,
                           cancel=cancel,progress=progress),'circuit_replay')

    def _start(self,operation,kind):
        from .local_tasks import LocalSlot
        slot=LocalSlot(self.results_root/'local-tasks') if self.results_root is not None else None
        with self.lock:
            if self.state and self.state['status']=='running':
                raise ValueError('A search is already running')
            if slot:slot.__enter__()
            self.cancel_event=threading.Event()
            event=self.cancel_event
            self.state=dict(job_id=uuid4().hex,status='running',progress={},result=None,error=None,kind=kind)
            job_id=self.state['job_id']
        def progress(value):
            with self.lock:self.state['progress']=value
        def work():
            try:
                result=operation(event.is_set,progress)
                with self.lock:self.state.update(status=result['status'],result=result)
            except Exception as error:
                with self.lock:self.state.update(status='failed',error=str(error))
            finally:
                if slot:slot.__exit__()
        threading.Thread(target=work,daemon=True).start()
        return dict(job_id=job_id,status='running')

    def snapshot(self,job_id,public_result=None):
        with self.lock:
            if not self.state or self.state['job_id']!=job_id:raise ValueError('Unknown search job')
            if public_result is None:return copy.deepcopy(self.state)
            result={key:copy.deepcopy(value) for key,value in self.state.items() if key!='result'}
            result['result']=public_result(self.state['result']) if self.state['result'] is not None else None
            return result

    def owned_result(self,job_id,kind):
        """Trusted in-process history reference; callers must not return arrays."""
        with self.lock:
            if not self.state or self.state['job_id']!=job_id or self.state['kind']!=kind:
                raise ValueError('Unknown task result')
            if self.state['status']=='running' or self.state['result'] is None:
                raise ValueError('Wait for task completion')
            return self.state['result']

    def source_snapshot(self,job_id,kind,origin_job_id=None,origin=None):
        """Read the current task or one exact completed replay origin."""
        if kind not in ('joint_search','timing_exploration','plan_reduction'):
            raise ValueError('Only fixed-plan source tasks can be retained')
        with self.lock:
            if self.state and self.state['job_id']==job_id:
                if self.state['kind']!=kind:raise ValueError('Task kind does not match the requested source')
                return copy.deepcopy(self.state)
            completed_statuses=('complete','cancelled','failed','budget_exhausted') if kind=='plan_reduction' else ('complete','cancelled','failed')
            if job_id!=origin_job_id or not isinstance(origin,dict) or origin.get('kind')!=kind or origin.get('status') not in completed_statuses:
                raise ValueError('Unknown completed replay source task')
            return dict(job_id=job_id,kind=kind,status=origin['status'],result=copy.deepcopy(origin),progress={},error=None)

    def cancel(self,job_id):
        with self.lock:
            if not self.state or self.state['job_id']!=job_id:raise ValueError('Unknown search job')
            self.cancel_event.set()
        return dict(job_id=job_id,cancel_requested=True)
