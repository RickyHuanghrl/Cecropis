"""Read local saved analysis sources without expanding an unbounded history."""
import json
from pathlib import Path


def read_saved_source(path, max_bytes=64 * 1024 * 1024):
    path=Path(path)
    if path.is_dir():
        files=('scope-plan-comparison.json','result.json','comparison.json','plan-reduction.json','timing-exploration.json','joint-search.json','search.json')
        path=next((path/name for name in files if (path/name).is_file()),path)
    if not path.is_file():raise ValueError('Select a saved run, comparison or fixed-plan report')
    source=json.loads(path.read_text(encoding='utf-8-sig'))
    history=path.parent/'states.npz'
    if path.name=='result.json' and history.is_file():
        if type(max_bytes) is not int or max_bytes<1:raise ValueError('Replay memory limit must be a positive integer')
        from .replay import _history_headers
        # Headers only; allocation is governed by the shared core preflight.
        source['_history']=dict(path=str(history.resolve()),**_history_headers(history))
    if path.name=='comparison.json':
        from .replay import _history_headers
        for item in source.get('results', []):
            filename=item.get('recording_file')
            if filename is None:continue
            if not isinstance(filename,str) or Path(filename).name!=filename or not filename.endswith('.npz'):
                raise ValueError('Invalid comparison recording reference')
            history=path.parent/filename
            if history.is_file():
                item['_history']=dict(path=str(history.resolve()),**_history_headers(history))
    return source


def read_replay_source(path,case):
    """Validate a saved replay's definition/mapping and inspect only NPZ headers.

    The consuming analysis/replay preflight decides whether its memory budget
    permits expanding this history. No activity array is allocated here.
    """
    from .replay import _identity,_plan,_history_headers
    folder=Path(path);folder=folder.parent if folder.is_file() else folder
    saved=json.loads((folder/'replay.json').read_text(encoding='utf-8-sig'))
    config=saved.get('config',{})
    if saved.get('kind')!='circuit_replay' or not saved.get('ready') or saved.get('status')!='complete':
        raise ValueError('Select a complete saved circuit replay')
    if any(config.get(key)!=value for key,value in _identity(case).items()):
        raise ValueError('Saved replay source scope/index/model identity mismatch')
    expected,*_=_plan(case,config['source_result'],config['request'],loading=True)
    for key in ('experiment','recording','source_result'):
        if json.dumps(config[key],sort_keys=True)!=json.dumps(expected['config'][key],sort_keys=True):
            raise ValueError('Saved replay source exact protocol mismatch')
    for key in ('nodes','edges','time_steps','recording_metadata'):
        if saved[key]!=expected[key]:raise ValueError('Saved replay source node/time/edge mapping mismatch')
    history=folder/'states.npz'
    descriptor=dict(path=str(history.resolve()),**_history_headers(history))
    shape=[len(saved['time_steps']),len(saved['nodes'])]
    if descriptor['shapes']!={'baseline':shape,'intervention':shape}:
        raise ValueError('Saved replay source archive dimensions mismatch')
    return dict(config['source_result'],recording_metadata=saved['recording_metadata'],_history=descriptor,
        analysis_source=dict(kind='circuit_replay',config=config,artifact_path=str(folder.resolve())))
