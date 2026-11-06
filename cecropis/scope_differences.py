"""O(N) window accumulation and paged queries for the entire source scope.

This module uses the shared simulation update. It never interprets a cumulative
node difference as a causal contribution, and never fabricates activity curves.
"""
import copy
import json
import zipfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import numpy as np

from .replay import _identity, _ids, _window, _resolve_source, _reuse, _history_headers
from .simulation import (RecordPolicy, SimulationPlan, SimulationCancelled,
    MAX_RECORD_BYTES, response_metrics, simulate)

_REQUEST_FIELDS={'task_id','condition_name','start','duration','body_ids','plan_body_ids','window','max_bytes'}
_PUBLIC_FIELDS=('kind','status','ready','config','window','sample_count','counts','memory',
                'simulations','reuse','display','error','needed_simulations')
_SORTS={'absolute','decrease','increase'}


def _memory(n,source_bytes,needs_simulations,maximum):
    stats=n*16
    body_ids=n*8
    mapping=n*256
    workspace=n*96 if needs_simulations else 0
    temporary=n*16
    estimate=stats+body_ids+mapping+workspace+temporary+source_bytes
    return dict(statistic_bytes=stats,body_id_bytes=body_ids,mapping_workspace_bytes=mapping,
        simulation_workspace_bytes=workspace,temporary_statistic_bytes=temporary,
        source_record_bytes=source_bytes,estimated_peak_bytes=estimate,max_bytes=maximum,
        within_limit=estimate<=maximum)


def _plan(case,source,request,*,loading=False):
    if request is None:request={}
    if not isinstance(request,dict) or set(request)-_REQUEST_FIELDS:
        raise ValueError('Unrecognized scope difference request fields')
    request=copy.deepcopy(request)
    maximum=request.get('max_bytes',64*1024**2)
    if type(maximum) is not int or not 1<=maximum<=MAX_RECORD_BYTES:
        raise ValueError(f'Difference max_bytes must be an integer in 1..{MAX_RECORD_BYTES}')
    view,cfg,chosen,canonical,reference=_resolve_source(case,source,request)
    identity=_identity(case)
    for item in (source,source.get('config',{})):
        if 'computation_node_ids_hash' in item and item['computation_node_ids_hash']!=identity['computation_node_ids_hash']:
            raise ValueError('Difference source node mapping does not match this computation scope')
    window=_window(request.get('window',cfg.observations[0]['evaluation_window']),cfg.steps)
    request.update(window=window,max_bytes=maximum)
    bodies=[str(node['bodyId']) for node in case['nodes']]
    available=set(bodies)
    if len(available)!=len(bodies):raise ValueError('Computation scope contains duplicate node IDs')
    _ids(bodies,available,'Difference computation mapping')
    reuse,source_bytes=_reuse(chosen,bodies,list(range(window['start']+1,window['stop']+1)),available,cfg.steps)
    previous=source.get('_difference_result',source if source.get('kind')=='scope_differences' else None)
    reusable_statistics=None
    if previous is not None:
        validate_differences(case,previous)
        matching=(previous['window']==window and json.dumps(previous['config']['experiment'],sort_keys=True)==json.dumps(asdict(cfg),sort_keys=True))
        if matching:
            reusable_statistics=previous['statistics']
            reuse.update(reusable=True,missing_node_ids=[],missing_time_steps=[],available_node_ids=[],
                         available_node_count=len(bodies),reason='Exact whole-scope statistics and analysis window match',kind='statistics')
            source_bytes=sum(values.nbytes for values in reusable_statistics)
    if reusable_statistics is None and '_history' in chosen and 'states' not in chosen:
        memory=_memory(len(bodies),source_bytes,False,maximum)
        if not reuse['reusable'] or not memory['within_limit']:
            if reuse['reusable']:reuse['reason']='Saved history exceeds the analysis memory limit; compact preparation is required'
            reuse['reusable']=False;source_bytes=0
    memory=_memory(len(bodies),source_bytes,not reuse['reusable'] and not loading,maximum)
    if not memory['within_limit']:
        raise ValueError(f'Difference estimated peak memory {memory["estimated_peak_bytes"]} bytes exceeds max_bytes={maximum}')
    # Coverage is counted globally, but polling must not transport the complete
    # node mapping or thousands of missing IDs as a secondary JSON array.
    for key in ('missing_node_ids','available_node_ids'):
        values=reuse.get(key,[])
        reuse['missing_node_count' if key=='missing_node_ids' else 'available_requested_node_count']=len(values)
        reuse[key]=values[:50]
    reuse['node_id_sample_limit']=50
    result=dict(kind='scope_differences',status='not_prepared',ready=False,
        config=dict(**identity,experiment=asdict(cfg),source=reference,source_result=canonical,
                    request=request,window=window),window=window,sample_count=window['stop']-window['start'],
        counts=dict(computation_node_count=len(bodies),statistic_node_count=len(bodies)),
        memory=memory,reuse=reuse,display={},needed_simulations=0 if reuse['reusable'] else 2,
        simulations=dict(baseline_started=0,baseline_completed=0,intervention_started=0,
                         intervention_completed=0,total_started=0,total_completed=0))
    if 'analysis_source' in source:result['config']['analysis_source']=copy.deepcopy(source['analysis_source'])
    if reusable_statistics is not None:result['_reuse_statistics']=reusable_statistics
    return result,view,cfg,chosen,bodies


def difference_preview(case,source,request=None):
    result,*_=_plan(case,source,request)
    result['kind']='difference_preview'
    return public_differences(result)


def prepare_differences(case,source,request=None,*,cancel=lambda:False,progress=lambda p:None):
    result,view,cfg,chosen,bodies=_plan(case,source,request)
    def notify(phase):
        progress(dict(phase=phase,status=result['status'],ready=result['ready'],simulations=dict(result['simulations'])))
    try:
        if cancel():raise SimulationCancelled('Differences cancelled before preparation')
        result['status']='preparing'
        prepared=[]
        if result['reuse']['reusable']:
            if '_reuse_statistics' in result:
                prepared=list(result.pop('_reuse_statistics'))
                notify('reuse')
            else:
                prepared=_history_sums(chosen,bodies,result['window'],cancel,notify)
        else:
            plan=SimulationPlan(view,cfg,collect_signals=False)
            for branch,gain in (('baseline',1.),('intervention',cfg.gain)):
                if cancel():raise SimulationCancelled('Differences cancelled before '+branch+' propagation')
                result['simulations'][branch+'_started']+=1;result['simulations']['total_started']+=1
                notify(branch+'_started')
                stats=simulate(view,cfg,gain=gain,recording=RecordPolicy(mode='none'),plan=plan,
                    collect_curves=False,cancel=cancel,node_window=result['window'],
                    **(dict(apply_interventions=branch=='intervention') if cfg.intervention_events is not None else {}))
                prepared.append(stats.node_window_sum)
                result['simulations'][branch+'_completed']+=1;result['simulations']['total_completed']+=1
                # Other O(N) trajectory aggregates are not retained between branches.
                del stats
                notify(branch+'_completed')
        if cancel():raise SimulationCancelled('Differences cancelled before complete statistics publication')
        if len(prepared)!=2 or any(not np.isfinite(values).all() for values in prepared):
            raise ValueError('Difference statistics must be two finite complete scope vectors')
        result.update(status='complete',ready=True,node_body_ids=np.asarray(bodies,dtype=np.int64),statistics=tuple(prepared))
        previous=source.get('_difference_result',source if source.get('kind')=='scope_differences' else {})
        candidate=chosen if 'states' in chosen or '_history' in chosen else previous.get('_replay_source')
        history_source=_matching_history_source(case,result,candidate)
        if history_source is not None:result['_replay_source']=history_source
        notify('complete')
    except SimulationCancelled as error:
        result.update(status='cancelled',ready=False,error=str(error));notify('cancelled')
    except Exception as error:
        result.update(status='failed',ready=False,error=str(error));notify('failed')
    result.pop('_reuse_statistics',None)
    return result


def _matching_history_source(case,result,candidate):
    """Retain optional trusted history independently of the O(N) statistics."""
    if not isinstance(candidate,dict) or not ('states' in candidate or '_history' in candidate):return None
    _,cfg,chosen,canonical,_=_resolve_source(case,candidate,{})
    if json.dumps(asdict(cfg),sort_keys=True)!=json.dumps(result['config']['experiment'],sort_keys=True):
        raise ValueError('Difference replay history does not match its exact source experiment')
    identity=_identity(case)
    for item in (candidate,candidate.get('config',{})):
        if 'computation_node_ids_hash' in item and item['computation_node_ids_hash']!=identity['computation_node_ids_hash']:
            raise ValueError('Difference replay history node mapping does not match this scope')
    metadata=chosen.get('recording_metadata',{})
    available={str(node['bodyId']) for node in case['nodes']}
    _reuse(chosen,metadata.get('body_ids',[]),metadata.get('time_steps',[]),available,cfg.steps)
    canonical['config']['computation_node_ids_hash']=identity['computation_node_ids_hash']
    canonical['recording_metadata']=copy.deepcopy(metadata)
    if 'states' in chosen:canonical['states']=chosen['states']
    if '_history' in chosen:canonical['_history']=copy.deepcopy(chosen['_history'])
    return canonical


def replay_source_for_differences(case,result):
    """Canonical protocol plus any matching history, without copying arrays."""
    validate_differences(case,result)
    source=_matching_history_source(case,result,result.get('_replay_source'))
    if source is None:return copy.deepcopy(result['config']['source_result'])
    if '_history' in source and 'states' not in source and not Path(source['_history']['path']).is_file():
        return copy.deepcopy(result['config']['source_result'])
    return source


def _history_sums(chosen,bodies,window,cancel,notify):
    metadata=chosen['recording_metadata']
    rows={step:index for index,step in enumerate(metadata['time_steps'])}
    columns={body:index for index,body in enumerate(metadata['body_ids'])}
    positions=np.asarray([columns[body] for body in bodies],dtype=np.int64)
    times=range(window['start']+1,window['stop']+1)
    def accumulate(values):
        total=np.zeros(len(bodies),dtype=np.float64)
        for step in times:
            if cancel():raise SimulationCancelled('Differences cancelled during history accumulation')
            total+=values[rows[step],positions]
        return total
    notify('reuse')
    if 'states' in chosen:
        prepared=[accumulate(values) for values in chosen['states']]
    else:
        history=chosen['_history'];header=_history_headers(history['path'])
        if any(header[key]!=history[key] for key in ('bytes','shapes','dtype')):
            raise ValueError('Saved history changed after its dimensions were inspected')
        with np.load(history['path'],allow_pickle=False) as arrays:
            prepared=[accumulate(arrays[key]) for key in ('baseline','intervention')]
    return prepared


def public_differences(result):
    """Finite task metadata only; vectors and mapping never enter polling JSON."""
    return copy.deepcopy({key:result[key] for key in _PUBLIC_FIELDS if key in result})


def validate_differences(case,result):
    if not isinstance(result,dict) or not result.get('ready') or result.get('status')!='complete' or 'statistics' not in result:
        raise ValueError('Difference statistics are not ready; complete preparation first')
    identity=_identity(case)
    if any(result['config'].get(key)!=value for key,value in identity.items()):
        raise ValueError('Difference identity does not match this case/model/node mapping')
    n=len(case['nodes']);mapping=result.get('node_body_ids')
    if not isinstance(mapping,np.ndarray) or mapping.dtype!=np.int64 or mapping.shape!=(n,) or any(
            int(mapping[j])!=int(node['bodyId']) for j,node in enumerate(case['nodes'])):
        raise ValueError('Difference body ID mapping does not match every computation node')
    values=result['statistics']
    if len(values)!=2 or any(not isinstance(v,np.ndarray) or v.dtype!=np.float64 or v.shape!=(n,) for v in values):
        raise ValueError('Difference statistics do not match their whole-scope mapping')
    if any(not np.isfinite(v).all() for v in values):
        raise ValueError('Difference statistics contain nonfinite values')
    _window(result['window'],result['config']['experiment']['steps'])
    if result['window']!=result['config']['window'] or result['window']!=result['config']['request']['window']:
        raise ValueError('Difference analysis window does not match its saved definition')
    if result['sample_count']!=result['window']['stop']-result['window']['start']:
        raise ValueError('Difference sample count does not match its analysis window')
    return {str(body):index for index,body in enumerate(mapping)}


def _roles(result):
    cfg=result['config']['experiment']
    inputs={body for event in cfg['input_events'] for body in event['body_ids']}
    observations={body for item in cfg['observations'] for body in item['body_ids']}
    targets=({body for event in cfg['intervention_events'] if event['enabled'] and event['type']=='node_gain' for body in event['body_ids']}
             if cfg.get('intervention_events') is not None else set(cfg['intervention_ids']))
    return inputs,observations,targets


def _row(case,result,index):
    body=str(result['node_body_ids'][index]);node=case['nodes'][index]
    inputs,observations,targets=_roles(result)
    b,i=(float(v[index]) for v in result['statistics'])
    metric=response_metrics(b,i,result['sample_count'])
    return dict(body_id=body,type=node.get('type'),
        annotation={key:value for key,value in node.items() if key not in ('bodyId','index')},
        input=body in inputs,intervention=body in targets,
        observation_names=[item['name'] for item in result['config']['experiment']['observations'] if body in item['body_ids']],
        **metric,absolute_sum_delta=abs(metric['sum_delta']))


def _query(sort,body_id,type_filter,hide_endpoints,offset,limit):
    if sort not in _SORTS:raise ValueError('Difference sort must be absolute, decrease or increase')
    if not isinstance(body_id,str) or (body_id and (not body_id.isascii() or not body_id.isdecimal() or str(int(body_id))!=body_id or not 0<int(body_id)<=np.iinfo(np.int64).max)):
        raise ValueError('Difference body_id filter must be an exact canonical ID or empty')
    if not isinstance(type_filter,str) or len(type_filter)>256:raise ValueError('Difference type_filter must be a string of at most 256 characters')
    if type(hide_endpoints) is not bool:raise ValueError('Difference hide_endpoints must be boolean')
    if type(offset) is not int or offset<0:raise ValueError('Difference offset must be a nonnegative integer')
    if type(limit) is not int or not 1<=limit<=1000:raise ValueError('Difference limit must be 1..1000')


def difference_rows(case,result,*,sort='absolute',body_id='',type_filter='',hide_endpoints=True,offset=0,limit=50):
    validate_differences(case,result)
    _query(sort,body_id,type_filter,hide_endpoints,offset,limit)
    inputs,observations,targets=_roles(result);endpoints=inputs|observations|targets
    selected=[];pattern=type_filter.casefold()
    for index,node in enumerate(case['nodes']):
        body=str(node['bodyId'])
        if body_id and body!=body_id:continue
        if pattern not in str(node.get('type') or '').casefold():continue
        if hide_endpoints and body in endpoints:continue
        selected.append(index)
    index=np.asarray(selected,dtype=np.int64)
    delta=result['statistics'][1][index]-result['statistics'][0][index]
    score=np.abs(delta) if sort=='absolute' else (-delta if sort=='decrease' else delta)
    ordered=index[np.lexsort((result['node_body_ids'][index],-score))]
    rows=[_row(case,result,int(j)) for j in ordered[offset:offset+limit]]
    return dict(rows=rows,total=len(selected),returned=len(rows),offset=offset,limit=limit,sort=sort,
        filters=dict(body_id=body_id,type_filter=type_filter,hide_endpoints=hide_endpoints),
        window=copy.deepcopy(result['window']),sample_count=result['sample_count'],
        ranking={'absolute':'absolute cumulative change','decrease':'signed cumulative decrease','increase':'signed cumulative increase'}[sort])


def difference_node(case,result,body_id):
    mapping=validate_differences(case,result)
    _ids([body_id],set(mapping),'Difference node')
    return dict(_row(case,result,mapping[body_id]),window=copy.deepcopy(result['window']),sample_count=result['sample_count'])


def difference_neighbors(case,result,body_id,*,direction='both',offset=0,limit=50):
    mapping=validate_differences(case,result)
    _ids([body_id],set(mapping),'Difference neighbors node')
    _query('absolute','','',False,offset,limit)
    if direction not in ('both','upstream','downstream'):raise ValueError('Neighbor direction must be both, upstream or downstream')
    index=mapping[body_id];rows=[]
    def append(pre,post,count,kind,neighbor):
        nid=str(case['nodes'][neighbor]['bodyId'])
        rows.append(dict(edge_id=f'{pre}->{post}',pre_id=pre,post_id=post,count=int(count),
            weight=float(case['matrix'][mapping[post],mapping[pre]]),direction=kind,neighbor=nid,neighbor_id=nid,
            annotation={key:value for key,value in case['nodes'][neighbor].items() if key not in ('bodyId','index')},
            type=case['nodes'][neighbor].get('type')))
    if direction in ('both','upstream'):
        row=case['counts'].getrow(index)
        for neighbor,count in zip(row.indices,row.data):append(str(case['nodes'][neighbor]['bodyId']),body_id,count,'upstream',neighbor)
    if direction in ('both','downstream'):
        column=case['counts'].getcol(index).tocoo()
        for neighbor,count in zip(column.row,column.data):append(body_id,str(case['nodes'][neighbor]['bodyId']),count,'downstream',neighbor)
    rows.sort(key=lambda r:(0 if r['direction']=='upstream' else 1,int(r['neighbor']),int(r['pre_id']),int(r['post_id'])))
    return dict(body_id=body_id,direction=direction,total=len(rows),returned=len(rows[offset:offset+limit]),
                rows=rows[offset:offset+limit],offset=offset,limit=limit,scope='current computation scope')


def _display(result,value):
    allowed={'sort','body_id','type_filter','hide_endpoints','offset','selected_node','selected_nodes'}
    if not isinstance(value,dict) or set(value)-allowed:raise ValueError('Difference display contains unsupported fields')
    _query(value.get('sort','absolute'),value.get('body_id',''),value.get('type_filter',''),value.get('hide_endpoints',True),value.get('offset',0),50)
    available={str(body) for body in result['node_body_ids']}
    if value.get('selected_node') is not None:_ids([value['selected_node']],available,'Difference selected_node')
    if 'selected_nodes' in value:_ids(value['selected_nodes'],available,'Difference selected_nodes',empty=True)
    return copy.deepcopy(value)


def save_differences(root,result,display=None):
    if not result.get('ready') or result.get('status')!='complete' or 'statistics' not in result:
        raise ValueError('Only ready complete scope differences can be saved')
    if any(not np.isfinite(v).all() for v in result['statistics']):raise ValueError('Difference statistics must be finite')
    clean=public_differences(result)
    clean['display']=_display(result,result.get('display',{}) if display is None else display)
    folder=Path(root)/('differences-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8])
    folder.mkdir(parents=True)
    for name,value in (('differences.json',clean),('config.json',clean['config'])):
        (folder/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    np.savez_compressed(folder/'statistics.npz',body_ids=result['node_body_ids'],
        baseline_sum=result['statistics'][0],intervention_sum=result['statistics'][1])
    history_source=result.get('_replay_source',{})
    if '_history' in history_source:
        descriptor=dict(source_result=clean['config']['source_result'],
            recording_metadata=history_source['recording_metadata'],history=history_source['_history'])
        (folder/'history-source.json').write_text(json.dumps(descriptor,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return folder


def _statistics_header(path,n):
    expected={'body_ids':np.dtype(np.int64),'baseline_sum':np.dtype(np.float64),'intervention_sum':np.dtype(np.float64)}
    with zipfile.ZipFile(path) as archive:
        if len(archive.namelist())!=len(expected) or set(archive.namelist())!={key+'.npy' for key in expected}:
            raise ValueError('Difference NPZ contains duplicate or unexpected members')
        for key,dtype_expected in expected.items():
            with archive.open(key+'.npy') as stream:
                version=np.lib.format.read_magic(stream)
                if version==(1,0):shape,_,dtype=np.lib.format.read_array_header_1_0(stream)
                elif version==(2,0):shape,_,dtype=np.lib.format.read_array_header_2_0(stream)
                else:raise ValueError('Unsupported difference statistic NPY header')
            if shape!=(n,) or dtype!=dtype_expected or not n*8<archive.getinfo(key+'.npy').file_size<=n*8+65536:
                raise ValueError('Difference NPZ dimensions/dtype do not match its scope')


def load_differences(path,case,*,max_bytes=None):
    folder=Path(path);folder=folder.parent if folder.is_file() else folder
    result=json.loads((folder/'differences.json').read_text(encoding='utf-8-sig'))
    if result.get('kind')!='scope_differences' or not result.get('ready') or result.get('status')!='complete':
        raise ValueError('Saved scope differences are not complete')
    config=result['config']
    if any(config.get(key)!=value for key,value in _identity(case).items()):
        raise ValueError('Saved difference identity does not match this computation scope')
    request=copy.deepcopy(config['request'])
    original_maximum=request.get('max_bytes',64*1024**2)
    if type(original_maximum) is not int or not 1<=original_maximum<=MAX_RECORD_BYTES:
        raise ValueError('Saved difference memory limit is invalid')
    if max_bytes is not None:request['max_bytes']=max_bytes
    expected,*_=_plan(case,config['source_result'],request,loading=True)
    for key in ('experiment','source_result','request','window'):
        expected_value=copy.deepcopy(expected['config'][key])
        # A stricter allocation cap is a read operation, not a rewritten source
        # experiment or historical analysis definition.
        if key=='request' and max_bytes is not None:expected_value['max_bytes']=original_maximum
        if json.dumps(config[key],sort_keys=True)!=json.dumps(expected_value,sort_keys=True):
            raise ValueError(f'Saved difference {key} does not match its exact source protocol')
    for key in ('window','sample_count','counts'):
        if result[key]!=expected[key]:raise ValueError(f'Saved difference {key} does not match its scope/window')
    _statistics_header(folder/'statistics.npz',len(case['nodes']))
    with np.load(folder/'statistics.npz',allow_pickle=False) as arrays:
        result['node_body_ids']=arrays['body_ids']
        result['statistics']=(arrays['baseline_sum'],arrays['intervention_sum'])
    validate_differences(case,result)
    if any(not np.isfinite(v).all() for v in result['statistics']):raise ValueError('Saved difference statistics must be finite')
    result['display']=_display(result,result.get('display',{}))
    # Loading allocates compact statistics and mapping only, never simulation workspace.
    result['memory']=expected['memory']
    history_path=folder/'history-source.json'
    if history_path.is_file():
        descriptor=json.loads(history_path.read_text(encoding='utf-8-sig'))
        if not isinstance(descriptor,dict) or set(descriptor)!={'source_result','recording_metadata','history'}:
            raise ValueError('Difference optional history descriptor has unsupported fields')
        if json.dumps(descriptor['source_result'],sort_keys=True)!=json.dumps(config['source_result'],sort_keys=True):
            raise ValueError('Difference optional history descriptor changes its saved source definition')
        history=descriptor['history']
        if not isinstance(history,dict) or set(history)!={'path','bytes','shapes','dtype'} or not isinstance(history['path'],str):
            raise ValueError('Difference optional history descriptor is malformed')
        if Path(history['path']).is_file():
            header=_history_headers(history['path'])
            if any(header[key]!=history[key] for key in ('bytes','shapes','dtype')):
                raise ValueError('Difference optional history archive does not match its saved descriptor')
            candidate=dict(descriptor['source_result'],recording_metadata=descriptor['recording_metadata'],_history=history)
            result['_replay_source']=_matching_history_source(case,result,candidate)
    return result
