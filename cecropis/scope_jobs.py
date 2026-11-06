"""One sequential scope comparison with explicit progress and cancellation."""
import copy
import threading
from uuid import uuid4

from .scope_comparison import compare_scopes, discard_recordings


class ScopeComparisonJob:
    def __init__(self, results_root=None):
        self.results_root=results_root
        self.lock=threading.Lock()
        self.cancel_event=threading.Event()
        self.state=None
        self.closed=False

    def running(self):
        with self.lock:
            return bool(self.state and self.state['status']=='running')

    def start(self,config):
        from .local_tasks import LocalSlot
        slot=LocalSlot(self.results_root/'local-tasks') if self.results_root is not None else None
        with self.lock:
            if self.closed or (self.state and self.state['status']=='running'):
                raise ValueError('A scope comparison is already running or the server is closing')
            if slot:slot.__enter__()
            if self.state and self.state.get('result'):
                discard_recordings(self.state['result'])
            self.cancel_event=threading.Event()
            event=self.cancel_event
            self.state=dict(job_id=uuid4().hex,status='running',progress={},result=None,error=None)
            job_id=self.state['job_id']
        request=copy.deepcopy(config)
        def progress(value):
            with self.lock:
                self.state['progress']=copy.deepcopy(value)
        def work():
            result=None
            try:
                result=compare_scopes(request,cancel=event.is_set,progress=progress)
                with self.lock:
                    self.state.update(status=result['status'],result=result)
            except Exception as error:
                with self.lock:
                    self.state.update(status='failed',error=str(error))
            finally:
                if slot:slot.__exit__()
                with self.lock:
                    if self.closed and result:
                        discard_recordings(result)
        threading.Thread(target=work,daemon=True).start()
        return dict(job_id=job_id,status='running')

    def snapshot(self,job_id,*,include_files=False):
        with self.lock:
            if not self.state or self.state['job_id']!=job_id:
                raise ValueError('Unknown scope comparison job')
            snapshot=copy.deepcopy(self.state)
        if snapshot.get('result') and not include_files:
            snapshot['result'].pop('recording_files',None)
        return snapshot

    def cancel(self,job_id):
        with self.lock:
            if not self.state or self.state['job_id']!=job_id:
                raise ValueError('Unknown scope comparison job')
            if self.state['status']!='running':
                raise ValueError('This scope comparison has already ended')
            self.cancel_event.set()
        return dict(job_id=job_id,cancel_requested=True)

    def close(self):
        with self.lock:
            self.closed=True
            self.cancel_event.set()
            if self.state and self.state['status']!='running' and self.state.get('result'):
                discard_recordings(self.state['result'])
