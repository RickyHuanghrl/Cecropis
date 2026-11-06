"""Explicit user-run plans/status/downloads of official local data, stdlib only."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait
import json
from pathlib import Path
import queue
import shutil
import threading
import time
import sys
from contextlib import contextmanager
import os

try:
    from . import download_precomputed_skeletons as transport
except ImportError:
    import download_precomputed_skeletons as transport

BASE = 'https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome/'
SOURCE = dict(dataset='MaleCNS',version='v1.0',confidence='minconf=0.5',
              official='https://male-cns.janelia.org/download/',
              license='CC BY 4.0',license_url='https://creativecommons.org/licenses/by/4.0/')
CONNECTIVITY = [dict(name='connectome-weights-male-cns-v1.0-minconf-0.5.feather',size=1051241946),
                dict(name='body-annotations-male-cns-v1.0-minconf-0.5.feather',size=14483314)]


def items_for(dataset, target, refresh=False):
    if dataset == 'connectivity':
        return [{**item,'url':BASE+item['name'],'size_basis':'official v1.0 local download inventory'} for item in CONNECTIVITY]
    if dataset != 'skeletons':
        raise ValueError('Choose connectivity or skeletons')
    control = target.parent / (target.name+'.download')
    if refresh:
        control.mkdir(parents=True,exist_ok=True)
    return transport.listing(control,offline=not refresh,quiet=True)


def download_plan(dataset, target, refresh=False):
    """Read cached metadata and file lengths only; never starts a transfer."""
    target=Path(target).expanduser().resolve()
    try:
        items=items_for(dataset,target,refresh)
    except FileNotFoundError as error:
        return dict(dataset=dataset,target=str(target),source=SOURCE,listing_available=False,
                    total_files=None,total_bytes=None,remaining_bytes=None,error=str(error),
                    action='Run plan --refresh-listing explicitly to fetch official metadata')
    files=[];complete=0;local=0;remaining=0
    for item in items:
        path=target/item['name'];partial=transport.partial_path(target,item['name'])
        size=path.stat().st_size if path.is_file() else 0
        partial_size=partial.stat().st_size if partial.is_file() else 0
        expected=item['size'];valid=path.is_file() and size==expected
        state='complete' if valid else 'partial' if partial_size else 'missing' if not path.exists() else 'length_mismatch'
        if partial_size>expected:state='partial_over_limit'
        complete+=int(valid);local+=expected if valid else min(expected,partial_size)
        remaining+=0 if valid else max(0,expected-partial_size)
        files.append(dict(name=item['name'],state=state,expected_bytes=expected,formal_bytes=size,partial_bytes=partial_size))
    summary=dict(dataset=dataset,target=str(target),source=SOURCE,listing_available=True,
                 total_files=len(items),total_bytes=sum(i['size'] for i in items),complete_files=complete,
                 locally_available_bytes=local,remaining_bytes=remaining,
                 partial_files=sum(f['state']=='partial' for f in files),
                 invalid_files=sum(f['state'] in ('length_mismatch','partial_over_limit') for f in files),
                 files=files if dataset=='connectivity' else None)
    return summary


class TransferProgress:
    def __init__(self):
        self.lock=threading.Lock();self.bytes=0;self.started=time.monotonic();self.previous=(self.started,0);self.samples=[]

    def add(self,n):
        with self.lock:self.bytes+=n

    def snapshot(self,remaining):
        now=time.monotonic()
        with self.lock:
            duration=now-self.previous[0];delta=self.bytes-self.previous[1];self.previous=(now,self.bytes)
            rate=delta/duration if duration>0 else 0;self.samples.append(rate);self.samples=self.samples[-6:]
            stable=len(self.samples)>=3 and min(self.samples)>0 and max(self.samples)/min(self.samples)<2
            mean=sum(self.samples)/len(self.samples)
            return dict(transferred_bytes=self.bytes,recent_bytes_per_second=rate,
                        elapsed_seconds=now-self.started,eta_seconds=max(0,remaining-self.bytes)/mean if stable and mean>0 else None)


@contextmanager
def download_owner(target):
    """An OS-held lock excludes concurrent writers; process exit releases it."""
    control=target.parent/(target.name+'.download');control.mkdir(parents=True,exist_ok=True)
    stream=(control/'transfer.lock').open('a+b')
    locked=False
    try:
        stream.seek(0,2)
        if stream.tell()==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            locked=True
        except OSError as error:raise RuntimeError('Another downloader owns this destination; wait or stop that process') from error
        yield
    finally:
        if locked:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
        stream.close()


def run_download(dataset,target,mode='plan',workers=8,refresh=False,emit=print):
    target=Path(target).expanduser().resolve()
    if mode not in ('plan','status','start'):raise ValueError('Choose plan, status or start')
    if mode=='start':
        from cecropis.process_signals import termination_as_interrupt
        with termination_as_interrupt(),download_owner(target):return _run_download(dataset,target,mode,workers,refresh,emit)
    return _run_download(dataset,target,mode,workers,refresh,emit)


def _run_download(dataset,target,mode,workers,refresh,emit):
    if not 1<=workers<=32:raise ValueError('workers must be between 1 and 32')
    target=Path(target).expanduser().resolve();plan=download_plan(dataset,target,refresh)
    emit(json.dumps(dict(kind='download_plan',**plan),ensure_ascii=False))
    if mode!='start':return 0 if plan['listing_available'] else 2
    if not plan['listing_available']:raise ValueError(plan['error'])
    if plan['invalid_files']:raise ValueError('Length mismatch or oversized partial found. Inspect status before starting; existing files are not overwritten.')
    if plan['complete_files']==plan['total_files']:return 0
    target.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(target).free<plan['remaining_bytes']+256*1024**2:raise OSError('Insufficient disk space for remaining payload and 256 MiB reserve')
    control=target.parent/(target.name+'.download');control.mkdir(parents=True,exist_ok=True)
    metadata={**SOURCE,'dataset_item':dataset,'target':str(target),'total_files':plan['total_files'],'total_bytes':plan['total_bytes']}
    temp=control/'source-metadata.tmp';temp.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(control/'source-metadata.json')
    items=items_for(dataset,target);work=queue.Queue()
    for item in items:
        path=target/item['name']
        if not path.is_file() or path.stat().st_size!=item['size']:work.put(item)
    stop=threading.Event();lock=threading.Lock();counts=dict(downloaded=0,skipped=0,failed=0);progress=TransferProgress()
    with (control/'failed-last-run.jsonl').open('w',encoding='utf-8') as failures:
        def worker():
            while not stop.is_set():
                try:item=work.get_nowait()
                except queue.Empty:return
                try:
                    state=transport.download_one(item,target,stop,progress.add)
                    with lock:
                        if state in counts:counts[state]+=1
                except Exception as error:
                    with lock:
                        counts['failed']+=1;failures.write(json.dumps(dict(name=item['name'],error=str(error)))+'\n');failures.flush()
                        if counts['failed']>=20:stop.set()
                finally:work.task_done()
        pool=ThreadPoolExecutor(max_workers=workers);futures=[pool.submit(worker) for _ in range(workers)]
        try:
            while True:
                _,pending=wait(futures,timeout=3)
                with lock:status=dict(complete_files=plan['complete_files']+counts['downloaded']+counts['skipped'],total_files=plan['total_files'],failed=counts['failed'],queued=work.qsize())
                emit(json.dumps(dict(kind='download_progress',**status,**progress.snapshot(plan['remaining_bytes'])),ensure_ascii=False))
                if not pending:break
        except KeyboardInterrupt:stop.set();emit(json.dumps(dict(kind='stopping',reason='interrupted',partial_files_retained=True)))
        finally:pool.shutdown(wait=True)
    complete=plan['complete_files']+counts['downloaded']+counts['skipped'];code=0 if complete==plan['total_files'] else 1
    emit(json.dumps(dict(kind='download_result',status='complete' if code==0 else 'incomplete',complete_files=complete,total_files=plan['total_files'],**counts,**progress.snapshot(plan['remaining_bytes'])),ensure_ascii=False))
    return code


def cli_emit(line):
    kind=json.loads(line).get('kind')
    print(line,file=sys.stderr if kind in ('download_progress','stopping') else sys.stdout,flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('plan','status','start'))
    parser.add_argument('--dataset',required=True,choices=('connectivity','skeletons'))
    parser.add_argument('--target',required=True,type=Path)
    parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--refresh-listing',action='store_true',help='Explicit metadata-only network request')
    args=parser.parse_args();return run_download(args.dataset,args.target,args.mode,args.workers,args.refresh_listing,emit=cli_emit)


if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    try:raise SystemExit(main())
    except KeyboardInterrupt:print(json.dumps(dict(status='interrupted',partial_files_retained=True)),file=sys.stderr);raise SystemExit(130)
    except (OSError,ValueError,RuntimeError) as error:print(json.dumps(dict(status='failed',error=str(error))),file=sys.stderr);raise SystemExit(1)
