"""Bounded circuit replay from exact protocols and sampled node trajectories.

Edges are real count-table edges. Their displayed signal is the pre-tanh term
alpha*rho*M[post,pre]*x_pre(t), not a decomposition of the final response.
"""
import copy
import hashlib
import json
import zipfile
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import numpy as np

from . import MODEL_VERSION
from .scope_comparison import _bound_case
from .simulation import (Experiment, RecordPolicy, SimulationPlan, SimulationCancelled,
    effective_input_events, effective_observations,
    intervention_indices, response_metrics, simulate)
from .interventions import (CompiledInterventions,
    intervention_node_ids, intervention_edge_ids)

_REQUEST_FIELDS = {'task_id','condition_name','start','duration','body_ids','plan_body_ids','node_ids',
                   'recording','max_nodes','max_edges','window'}
_PUBLIC_FIELDS = ('kind','status','ready','config','nodes','edges','time_steps','default_window',
                  'default_window_observation','counts','memory','recording_metadata','simulations',
                  'color_domain','display','error','reuse','output_series','output_time_steps')


def _ids(values, available, label, *, empty=False):
    if not isinstance(values,(list,tuple)) or (not values and not empty) or any(
        not isinstance(body,str) or not body.isascii() or not body.isdecimal() or
        str(int(body))!=body or not 0<int(body)<=np.iinfo(np.int64).max for body in values):
        raise ValueError(f'{label} needs exact canonical positive int64 body IDs')
    if len(set(values))!=len(values):raise ValueError(f'{label} contains duplicate IDs')
    missing=sorted(set(values)-available,key=int)
    if missing:raise ValueError(f'{label} contains nodes outside the computation scope: '+', '.join(missing))
    return sorted(values,key=int)


def _window(value, steps):
    if not isinstance(value,dict) or set(value)!={'start','stop'} or any(type(x) is not int for x in value.values()) or not 0<=value['start']<value['stop']<=steps:
        raise ValueError('Replay window must satisfy integer 0 <= start < stop <= steps')
    return dict(value)


def _identity(case):
    manifest=case['manifest']
    digest=hashlib.sha256(','.join(sorted((str(node['bodyId']) for node in case['nodes']),key=int)).encode()).hexdigest()
    return dict(case_id=manifest['case_id'],source_index_id=manifest.get('source_index_id'),
                model_version=MODEL_VERSION,computation_node_ids_hash=digest)


def _check_source_identity(case, source):
    identity=source.get('config',source)
    if identity.get('case_id')!=case['manifest']['case_id'] or identity.get('model_version')!=MODEL_VERSION:
        raise ValueError('Replay source case/model identity does not match this computation scope')
    scope=source.get('data_scope',{})
    if not isinstance(scope,dict):raise ValueError('Replay source data_scope must be identity metadata')
    for item in (source,identity,scope):
        if 'case_id' in item and item['case_id']!=case['manifest']['case_id']:
            raise ValueError('Replay source case identity does not match this computation scope')
        if 'source_index_id' in item and item['source_index_id']!=case['manifest'].get('source_index_id'):
            raise ValueError('Replay source index identity does not match this computation scope')


def _condition(source, request):
    conditions=source.get('conditions')
    if not isinstance(conditions,list) or not conditions:
        raise ValueError('Replay source has no saved conditions')
    names=[item.get('name') for item in conditions]
    name=request.get('condition_name')
    if name is None and len(names)==1:name=names[0]
    if name not in names or names.count(name)!=1:
        raise ValueError('Choose one exact saved condition_name for replay')
    return names.index(name),name,Experiment.from_dict(copy.deepcopy(conditions[names.index(name)]['experiment']))


def _resolve_source(case, source, request):
    if not isinstance(source,dict):raise ValueError('Replay source must be a trusted saved result')
    if source.get('kind')=='scope_plan_comparison':
        from .scope_plan_comparison import scope_plan_source
        source=scope_plan_source(source,request.get('task_id'))
    _check_source_identity(case,source)
    kind=source.get('kind','conditions' if 'conditions' in source else 'comparison')
    chosen=source
    selection={}
    name=request.get('condition_name')
    available={str(node['bodyId']) for node in case['nodes']}
    plan=request.get('body_ids',request.get('plan_body_ids'))
    empty_fixed=(kind=='plan_reduction' or source.get('fixed_no_intervention') is True
                 or isinstance(source.get('reduction_evaluation'),dict))
    if not empty_fixed:
        raw=source.get('config',{}).get('experiment',{})
        empty_fixed=raw.get('intervention_group')=='__fixed_no_intervention__' and raw.get('intervention_ids')==[]
    if plan is not None:plan=_ids(plan,available,'Fixed plan selection',empty=empty_fixed)
    if 'body_ids' in request and 'plan_body_ids' in request:
        alias=_ids(request['plan_body_ids'],available,'Fixed plan selection',empty=empty_fixed)
        if set(plan or [])!=set(alias):raise ValueError('body_ids and plan_body_ids specify different fixed plans')
    if kind=='plan_reduction':
        from .plan_reduction import validate_reduction
        validate_reduction(case,source)
        if source.get('computation_node_ids_hash')!=_identity(case)['computation_node_ids_hash']:
            raise ValueError('Reduction source calculation node identity mismatch')
        _,name,cfg=_condition(dict(source,conditions=source['conditions']+source.get('extra_conditions',[])),request)
        if plan is None:
            row=source.get('final') or source.get('original')
            plan=None if row is None else row['body_ids']
        if plan is None or not any(row.get('status')=='completed' and set(row.get('body_ids',[]))==set(plan) for row in source.get('entries',[])):
            raise ValueError('Replay requires an actually completed reduction set')
        if name in [item['name'] for item in source.get('extra_conditions',[])] and not any(
            set(item.get('body_ids',[]))==set(plan) or
            (item.get('include_original') and set(source['original_body_ids'])==set(plan))
            for item in source.get('curve_requests',[])):
            raise ValueError('This extra condition has not been evaluated for the selected reduction set')
        bodies=plan
        cfg=replace(cfg,intervention_ids=tuple(bodies))
        selection=dict(body_ids=list(bodies))
        chosen={}
    elif kind=='timing_exploration':
        _,name,cfg=_condition(source,request)
        start,duration=request.get('start'),request.get('duration')
        if type(start) is not int or type(duration) is not int or not any(
            item.get('status')=='completed' and item.get('start')==start and item.get('duration')==duration for item in source.get('entries',[])):
            raise ValueError('Replay requires an actually completed timing interval')
        bodies=source['body_ids']
        if plan is not None and set(plan)!=set(bodies):raise ValueError('Replay cannot change the completed timing fixed plan')
        cfg=replace(cfg,intervention_ids=tuple(bodies),intervention_start=start,intervention_stop=start+duration)
        selection=dict(start=start,duration=duration,stop=start+duration)
        chosen={}
    elif kind=='joint_search':
        _,name,cfg=_condition(source,request)
        if plan is None and source.get('best'):plan=source['best']['body_ids']
        proposals=[source.get('best')]+[item for key in ('evaluated','frontier','sensitivity') for item in source.get(key,[])]
        if plan is None or not any(item and set(item.get('body_ids',[]))==set(plan) for item in proposals):
            raise ValueError('Replay requires an actually evaluated joint-search fixed plan')
        bodies=plan
        cfg=replace(cfg,intervention_ids=tuple(bodies))
        selection=dict(body_ids=list(bodies))
        chosen={}
    elif 'conditions' in source:
        index,name,cfg=_condition(source,request)
        results=source.get('results')
        if not isinstance(results,list) or len(results)!=len(source['conditions']):
            raise ValueError('Replay comparison requires complete saved condition results')
        chosen=results[index]
        _check_source_identity(case,chosen)
        saved=Experiment.from_dict(copy.deepcopy(chosen['config']['experiment']))
        # Compare all saved parameters, allowing JSON tuple/list representation.
        if json.dumps(asdict(cfg),sort_keys=True)!=json.dumps(asdict(saved),sort_keys=True):
            raise ValueError('Selected comparison result does not match its saved experiment')
        bodies=chosen.get('intervention_body_ids',cfg.intervention_ids)
    else:
        if kind=='forward':raise ValueError('Replay needs a baseline and an actual intervention result')
        cfg=Experiment.from_dict(copy.deepcopy(source['config']['experiment']))
        bodies=source.get('intervention_body_ids',cfg.intervention_ids)
        if bodies is None:
            bodies=[str(case['nodes'][i]['bodyId']) for i in intervention_indices(case['nodes'],cfg)]
    event_plan = cfg.intervention_events is not None
    if event_plan:
        bodies = intervention_node_ids(case['nodes'], cfg)
    empty_fixed = empty_fixed or event_plan or (cfg.intervention_group == '__fixed_no_intervention__' and cfg.intervention_ids in ([], ()))
    bodies=_ids(bodies,available,'Fixed intervention',empty=empty_fixed)
    if empty_fixed and not bodies and not event_plan:
        from .plan_reduction import FixedExperiment
        cfg=FixedExperiment.from_dict(asdict(cfg))
    if kind not in ('joint_search','timing_exploration','plan_reduction'):
        defined=intervention_node_ids(case['nodes'],cfg) if event_plan else cfg.intervention_ids
        if defined is None:
            defined=[str(case['nodes'][index]['bodyId']) for index in intervention_indices(case['nodes'],cfg)]
        if set(defined)!=set(bodies):
            raise ValueError('Saved result intervention IDs do not match its experiment')
    if kind not in ('joint_search','timing_exploration','plan_reduction') and plan is not None and set(plan)!=set(bodies):
        raise ValueError('Replay cannot change the saved intervention node set')
    if event_plan and ('start' in request or 'duration' in request):
        raise ValueError('Replay event plans retain every saved interval; a single replacement interval is not allowed')
    if not event_plan and kind!='timing_exploration' and ('start' in request or 'duration' in request):
        if request.get('start')!=cfg.intervention_start or request.get('duration')!=cfg.intervention_stop-cfg.intervention_start:
            raise ValueError('Replay cannot change the saved intervention interval')
    # Resolve legacy roles once, then bind the fixed plan independently of roles.
    cfg=replace(cfg,input_events=tuple(effective_input_events(case['nodes'],cfg)),
                observations=tuple(effective_observations(case['nodes'],cfg)),
                **({} if event_plan else dict(intervention_ids=tuple(bodies))))
    view,cfg=_bound_case(case,cfg)
    cfg.validate(view['nodes'])
    CompiledInterventions(view,cfg)
    canonical=dict(kind='comparison',config=dict(case_id=case['manifest']['case_id'],
        source_index_id=case['manifest'].get('source_index_id'),model_version=MODEL_VERSION,experiment=asdict(cfg)),
        intervention_body_ids=bodies)
    if empty_fixed and not bodies and not intervention_edge_ids(cfg):canonical['fixed_no_intervention']=True
    return view,cfg,chosen,canonical,dict(kind=kind,condition_name=name,selection=selection)


def _edges(case, bodies, maximum):
    if 'counts' not in case:raise ValueError('Replay requires real connection counts and the propagation matrix')
    by_id={str(node['bodyId']):index for index,node in enumerate(case['nodes'])}
    selected={by_id[body]:body for body in bodies}
    counts,matrix=case['counts'],case['matrix']
    result=[]
    for post in sorted(selected):
        for pointer in range(counts.indptr[post],counts.indptr[post+1]):
            pre=int(counts.indices[pointer]); count=int(counts.data[pointer])
            if pre not in selected or count<=0:continue
            result.append(dict(edge_id=selected[pre]+'->'+selected[post],pre_id=selected[pre],post_id=selected[post],
                count=count,weight=float(matrix[post,pre])))
            if len(result)>maximum:
                raise ValueError(f'Replay has more than max_edges={maximum}; choose fewer nodes or explicitly raise the limit')
    return sorted(result,key=lambda edge:(int(edge['pre_id']),int(edge['post_id'])))


def _memory(nodes, edges, times, source_bytes, computation_nodes, needs_simulations, maximum, observations):
    records=2*nodes*times*8
    # Two branch buffers plus bounded subset/save temporaries. Metadata, summary
    # dictionaries and indexing are included; no edges*time history is allocated.
    curves=observations*times*3*128
    metadata=nodes*4096+edges*2048+times*128+65536+curves
    # Full-scope ID sets/dictionaries, temporary bound-node lists and identity
    # hashing exist even on read-only loads. The already resident CSR/model is
    # excluded; these new mapping allocations remain subject to the same cap.
    mapping=256*computation_nodes
    workspace=12*computation_nodes*8 if needs_simulations else 0
    estimate=source_bytes+records*3+metadata+mapping+workspace
    return dict(record_bytes=records,source_record_bytes=source_bytes,
        metadata_and_summary_bytes=metadata,simulation_workspace_bytes=workspace,
        mapping_workspace_bytes=mapping,
        observation_curve_bytes=curves,
        temporary_record_bytes=records*2,estimated_peak_bytes=estimate,max_bytes=maximum,
        within_limit=estimate<=maximum)


def _history_headers(path):
    """Inspect existing NPZ dimensions before allocating any activity arrays."""
    shapes={};size=0
    with zipfile.ZipFile(path) as archive:
        if set(archive.namelist())!={'baseline.npy','intervention.npy'}:
            raise ValueError('Replay history must contain exactly two activity branches')
        for key in ('baseline','intervention'):
            with archive.open(key+'.npy') as stream:
                version=np.lib.format.read_magic(stream)
                if version==(1,0):shape,_,dtype=np.lib.format.read_array_header_1_0(stream)
                elif version==(2,0):shape,_,dtype=np.lib.format.read_array_header_2_0(stream)
                else:raise ValueError('Unsupported replay history NPY header')
            if len(shape)!=2 or dtype!=np.dtype(np.float64) or any(type(value) is not int or value<0 for value in shape):
                raise ValueError('Replay history must contain two-dimensional float64 activity')
            byte_count=shape[0]*shape[1]*8
            if not byte_count<archive.getinfo(key+'.npy').file_size<=byte_count+65536:
                raise ValueError('Replay history payload size does not match its NPY header')
            shapes[key]=list(shape);size+=byte_count
    return dict(bytes=size,shapes=shapes,dtype='float64')


def _reuse(chosen, bodies, times, available, steps):
    states=chosen.get('states');metadata=chosen.get('recording_metadata',{})
    oldbodies=metadata.get('body_ids',[]);oldtimes=metadata.get('time_steps',[])
    if oldbodies:_ids(oldbodies,available,'Source recorded node mapping')
    recorded_nodes=set(oldbodies)
    if not isinstance(oldtimes,(list,tuple)) or any(type(step) is not int or not 0<=step<=steps for step in oldtimes) or len(set(oldtimes))!=len(oldtimes):
        raise ValueError('Source recording has invalid state-step mapping')
    missing_nodes=sorted(set(bodies)-set(oldbodies),key=int)
    missing_times=sorted(set(times)-set(oldtimes))
    available=False;reason=chosen.get('_recording_unavailable_reason')
    source_bytes=0
    if isinstance(states,(list,tuple)) and len(states)==2:
        if len(set(oldbodies))!=len(oldbodies) or len(set(oldtimes))!=len(oldtimes):
            raise ValueError('Source recording has ambiguous node or time mapping')
        shape=(len(oldtimes),len(oldbodies))
        for values in states:
            if not isinstance(values,np.ndarray) or values.ndim!=2 or values.shape!=shape or values.dtype!=np.float64:
                raise ValueError('Source recording shape/dtype does not match its metadata')
            source_bytes+=values.nbytes
        available=not missing_nodes and not missing_times
    elif isinstance(chosen.get('_history'),dict):
        history=chosen['_history'];shape=[len(oldtimes),len(oldbodies)]
        if history.get('dtype')!='float64' or history.get('shapes')!={'baseline':shape,'intervention':shape} or type(history.get('bytes')) is not int or history['bytes']!=2*shape[0]*shape[1]*8:
            raise ValueError('Source lazy history shape/dtype does not match its recording metadata')
        source_bytes=history['bytes']
        available=not missing_nodes and not missing_times
    else:
        reason=reason or 'No two-branch node trajectories were recorded'
    return dict(reusable=available,missing_node_ids=missing_nodes,missing_time_steps=missing_times,
        available_node_ids=[body for body in bodies if body in recorded_nodes],available_node_count=len(oldbodies),
        available_time_steps=list(oldtimes),reason=reason),source_bytes


def _plan(case, source, request, *, loading=False):
    if request is None:request={}
    if not isinstance(request,dict) or set(request)-_REQUEST_FIELDS:
        raise ValueError('Unrecognized replay request fields')
    request=copy.deepcopy(request)
    for key,default,maximum in (('max_nodes',200,500),('max_edges',1500,10000)):
        value=request.get(key,default)
        if type(value) is not int or not 1<=value<=maximum:raise ValueError(f'{key} must be an integer in 1..{maximum}')
        request[key]=value
    view,cfg,chosen,canonical,reference=_resolve_source(case,source,request)
    available={str(node['bodyId']) for node in case['nodes']}
    supplied=_ids(request.get('node_ids',[]),available,'Replay node_ids',empty=True)
    inputs={body for event in cfg.input_events for body in event['body_ids']}
    observed={body for item in cfg.observations for body in item['body_ids']}
    affected_nodes=set(intervention_node_ids(view['nodes'],cfg))
    affected_edges=intervention_edge_ids(cfg)
    bodies=sorted(set(supplied)|inputs|observed|affected_nodes|{body for edge in affected_edges for body in edge},key=int)
    if len(bodies)>request['max_nodes']:
        raise ValueError(f'Replay requires {len(bodies)} exact nodes; max_nodes={request["max_nodes"]}; narrow the requested set or explicitly raise the limit')
    edges=_edges(case,bodies,request['max_edges'])
    recording=request.get('recording',{})
    if not isinstance(recording,dict) or set(recording)-{'steps','step_stride','max_bytes'}:
        raise ValueError('Replay recording accepts only steps, step_stride and max_bytes')
    policy=RecordPolicy.from_dict(dict(recording,mode='selected',body_ids=bodies))
    indices,times,metadata=policy.resolve(view,cfg,branch_count=2)
    reuse,source_bytes=_reuse(chosen,bodies,times,available,cfg.steps)
    # Unloaded old histories are optional. A nonmatching or over-budget archive
    # is never expanded; a new bounded recording can still be prepared.
    if '_history' in chosen and 'states' not in chosen:
        reuse_memory=_memory(len(bodies),len(edges),len(times),source_bytes,len(case['nodes']),False,policy.max_bytes,len(cfg.observations))
        if not reuse['reusable'] or not reuse_memory['within_limit']:
            if reuse['reusable']:reuse['reason']='Saved history cannot be loaded within the replay memory limit; bounded preparation is needed'
            reuse['reusable']=False;source_bytes=0
    memory=_memory(len(bodies),len(edges),len(times),source_bytes,len(case['nodes']),not reuse['reusable'] and not loading,policy.max_bytes,len(cfg.observations))
    if not memory['within_limit']:
        raise ValueError(f'Replay estimated peak memory {memory["estimated_peak_bytes"]} bytes exceeds max_bytes={policy.max_bytes}; narrow nodes/recording or raise the explicit limit')
    default=cfg.observations[0]['evaluation_window']
    window=_window(request.get('window',default),cfg.steps)
    request['node_ids']=supplied
    request['recording']={key:value for key,value in asdict(policy).items() if key in ('steps','step_stride','max_bytes')}
    request['window']=window
    nodes=[]
    for index,body in zip(indices,bodies):
        node=case['nodes'][index]
        nodes.append(dict(body_id=body,annotation={key:value for key,value in node.items() if key not in ('bodyId','index')},
            input=body in inputs,intervention=body in affected_nodes,
            observation_names=[item['name'] for item in cfg.observations if body in item['body_ids']]))
    counters=dict(baseline_started=0,baseline_completed=0,intervention_started=0,intervention_completed=0,
                  total_started=0,total_completed=0)
    public=dict(kind='circuit_replay',status='not_prepared',ready=False,
        config=dict(**_identity(case),experiment=asdict(cfg),source=reference,source_result=canonical,
                    request=request,recording=asdict(policy)),
        nodes=nodes,edges=edges,time_steps=times,default_window=window,
        default_window_observation=cfg.observations[0]['name'],recording_metadata=metadata,
        counts=dict(computation_node_count=len(case['nodes']),recorded_node_count=len(bodies),
            intervention_node_count=len(affected_nodes),intervention_edge_count=len(affected_edges),
            display_node_count=len(bodies),display_edge_count=len(edges),omitted_node_count=len(case['nodes'])-len(bodies),
            omitted_internal_edge_count=int(case['counts'].nnz)-len(edges)),
        memory=memory,simulations=counters,reuse=reuse,display={})
    public['_interventions']=CompiledInterventions(view,cfg)
    return public,view,cfg,chosen,policy,indices


def replay_preview(case, source, request=None):
    public,*_=_plan(case,source,request)
    public.update(kind='replay_preview',reusable=public['reuse']['reusable'],
        missing_node_ids=public['reuse']['missing_node_ids'],missing_time_steps=public['reuse']['missing_time_steps'],
        needed_simulations=0 if public['reuse']['reusable'] else 2)
    public.pop('_interventions',None)
    return public


def _scales(replay):
    baseline,intervention=replay['states']
    activity=float(max(baseline.max(initial=0.),intervention.max(initial=0.)))
    delta=float(np.max(np.abs(intervention-baseline),initial=0.))
    cfg=replay['config']['experiment'];bodies=replay['recording_metadata']['body_ids']
    indices={body:index for index,body in enumerate(bodies)}
    edge_max,edge_delta=0.,0.
    positions=[index for index,step in enumerate(replay['time_steps']) if step<cfg['steps']]
    for edge in replay['edges']:
        column=indices[edge['pre_id']];factor=cfg['alpha']*cfg['rho']*edge['weight']
        if positions:
            gains=np.asarray([replay['_interventions'].edge_gain(edge['pre_id'],edge['post_id'],replay['time_steps'][position]) for position in positions])
            b=baseline[positions,column]*factor;i=intervention[positions,column]*factor*gains
            edge_max=max(edge_max,float(max(b.max(initial=0.),i.max(initial=0.))))
            edge_delta=max(edge_delta,float(np.max(np.abs(i-b),initial=0.)))
    return dict(activity_max=activity,delta_abs_max=delta,edge_activity_max=edge_max,edge_delta_abs_max=edge_delta)


def _output_curves(case,replay):
    columns={body:index for index,body in enumerate(replay['recording_metadata']['body_ids'])}
    result={}
    for item in replay['config']['experiment']['observations']:
        members=set(item['body_ids'])
        positions=[columns[str(node['bodyId'])] for node in case['nodes'] if str(node['bodyId']) in members]
        b=replay['states'][0][:,positions].mean(axis=1)
        i=replay['states'][1][:,positions].mean(axis=1)
        result[item['name']]=dict(baseline=b.tolist(),intervention=i.tolist(),delta=(i-b).tolist())
    replay['output_time_steps']=list(replay['time_steps'])
    replay['output_series']=result


def prepare_replay(case, source, request=None, *, cancel=lambda:False, progress=lambda p:None):
    replay,view,cfg,chosen,policy,indices=_plan(case,source,request)
    def notify(phase):progress(dict(phase=phase,status=replay['status'],ready=False,simulations=dict(replay['simulations'])))
    try:
        if cancel():raise SimulationCancelled('Replay cancelled before trajectory preparation')
        if replay['reuse']['reusable']:
            old=chosen['recording_metadata']
            rows={step:index for index,step in enumerate(old['time_steps'])}
            columns={body:index for index,body in enumerate(old['body_ids'])}
            index=np.ix_([rows[step] for step in replay['time_steps']],
                         [columns[body] for body in replay['recording_metadata']['body_ids']])
            if 'states' in chosen:
                states=tuple(values[index] for values in chosen['states'])
            else:
                history=chosen['_history'];header=_history_headers(history['path'])
                if any(header[key]!=history[key] for key in ('bytes','shapes','dtype')):
                    raise ValueError('Saved source history changed after its metadata was inspected')
                with np.load(history['path'],allow_pickle=False) as arrays:
                    states=tuple(arrays[key][index] for key in ('baseline','intervention'))
        else:
            plan=SimulationPlan(view,cfg,collect_signals=False)
            prepared=[]
            for kind,gain in (('baseline',1.),('intervention',cfg.gain)):
                if cancel():raise SimulationCancelled('Replay cancelled before '+kind+' propagation')
                replay['status']='preparing'
                replay['simulations'][kind+'_started']+=1;replay['simulations']['total_started']+=1
                notify(kind+'_started')
                stats=simulate(view,cfg,gain=gain,recording=policy,plan=plan,collect_curves=False,cancel=cancel,
                    **(dict(apply_interventions=kind=='intervention') if cfg.intervention_events is not None else {}))
                replay['simulations'][kind+'_completed']+=1;replay['simulations']['total_completed']+=1
                prepared.append(stats.recorded_states)
                notify(kind+'_completed')
            states=tuple(prepared)
        if cancel():raise SimulationCancelled('Replay cancelled before completed trajectories were published')
        if any(not np.isfinite(values).all() for values in states):raise ValueError('Replay recording contains nonfinite activity')
        replay.update(status='complete',ready=True,states=states)
        replay['color_domain']=_scales(replay)
        _output_curves(case,replay)
        progress(dict(phase='complete',status='complete',ready=True,simulations=dict(replay['simulations'])))
    except SimulationCancelled as error:
        replay.pop('states',None);replay.update(status='cancelled',ready=False,error=str(error));notify('cancelled')
    except Exception as error:
        replay.pop('states',None);replay.update(status='failed',ready=False,error=str(error));notify('failed')
    return replay


def public_replay(replay):
    """JSON metadata only; never copy or serialize the trajectory arrays."""
    return copy.deepcopy({key:replay[key] for key in _PUBLIC_FIELDS if key in replay})


def _ready(case,replay):
    if not isinstance(replay,dict) or not replay.get('ready') or replay.get('status')!='complete' or 'states' not in replay:
        raise ValueError('Replay is not ready; prepare complete trajectories first')
    identity=_identity(case)
    if any(replay['config'].get(key)!=value for key,value in identity.items()):
        raise ValueError('Replay identity does not match this case/model/node mapping')
    metadata=replay['recording_metadata']
    if replay['time_steps']!=metadata['time_steps'] or [node['body_id'] for node in replay['nodes']]!=metadata['body_ids']:
        raise ValueError('Replay recording node/time mapping is inconsistent')
    shape=(len(replay['time_steps']),len(metadata['body_ids']))
    if len(replay['states'])!=2 or any(values.shape!=shape or values.dtype!=np.float64 for values in replay['states']):
        raise ValueError('Replay trajectory shape/dtype does not match its mapping')
    if '_interventions' not in replay:
        # Saved legacy plans carry exact IDs and a temporary role label. Rebuild
        # that bound view, as preparation does, before resolving effective gains.
        view, cfg = _bound_case(case, Experiment.from_dict(replay['config']['experiment']))
        replay['_interventions'] = CompiledInterventions(view, cfg)
    return {body:index for index,body in enumerate(metadata['body_ids'])}


def _position(replay, state_step):
    if type(state_step) is not int or state_step not in replay['time_steps']:
        raise ValueError('Choose an actually recorded state step; missing states are not interpolated')
    return replay['time_steps'].index(state_step)


def _edge_values(replay,edge,row,state_step,columns):
    if state_step==replay['config']['experiment']['steps']:
        return dict(edge,baseline=None,intervention=None,delta=None,connection_defined=False)
    cfg=replay['config']['experiment'];factor=cfg['alpha']*cfg['rho']*edge['weight']
    gain=replay['_interventions'].edge_gain(edge['pre_id'],edge['post_id'],state_step)
    index=columns[edge['pre_id']];b=float(replay['states'][0][row,index])*factor;i=float(replay['states'][1][row,index])*factor*gain
    return dict(edge,baseline=b,intervention=i,delta=i-b,effective_gain=gain,
        effective_weight=edge['weight']*gain,connection_defined=True)


def replay_frame(case,replay,state_step):
    columns=_ready(case,replay);row=_position(replay,state_step)
    b,i=replay['states']
    return dict(state_step=state_step,connection_defined=state_step<replay['config']['experiment']['steps'],
        node_update_step=state_step-1 if state_step else None,edge_update_step=state_step if state_step<replay['config']['experiment']['steps'] else None,
        active_events=[dict(event,update_step=state_step-1 if event['type']=='node_gain' else state_step)
            for event in replay['_interventions'].events
            if event['enabled'] and event['start'] <= (state_step-1 if event['type']=='node_gain' else state_step) < event['stop']],
        nodes=[dict(body_id=body,baseline=float(b[row,column]),intervention=float(i[row,column]),delta=float(i[row,column]-b[row,column]),
            effective_gain=replay['_interventions'].node_gain(body,state_step-1) if state_step else 1.)
               for body,column in columns.items()],
        edges=[_edge_values(replay,edge,row,state_step,columns) for edge in replay['edges']])


def replay_node(case,replay,body_id):
    columns=_ready(case,replay)
    if body_id not in columns:raise ValueError('Node was not recorded in this replay')
    index=columns[body_id];b=replay['states'][0][:,index];i=replay['states'][1][:,index]
    node=next(node for node in replay['nodes'] if node['body_id']==body_id)
    return dict(node,time_steps=list(replay['time_steps']),series=dict(baseline=b.tolist(),intervention=i.tolist(),delta=(i-b).tolist()),
        upstream=[edge for edge in replay['edges'] if edge['post_id']==body_id],
        downstream=[edge for edge in replay['edges'] if edge['pre_id']==body_id],
        adjacency_scope='recorded induced circuit')


def replay_edge(case,replay,edge_id,state_step):
    columns=_ready(case,replay);row=_position(replay,state_step)
    edge=next((edge for edge in replay['edges'] if edge['edge_id']==edge_id),None)
    if edge is None:raise ValueError('Edge is not a real edge in this recorded circuit')
    return dict(_edge_values(replay,edge,row,state_step,columns),state_step=state_step)


def _summary_metric(b,i,count):
    metrics=response_metrics(float(b.sum()),float(i.sum()),count)
    return dict(metrics,defined=True,absolute_sum_delta=abs(metrics['sum_delta']),sum_absolute_delta=float(np.abs(i-b).sum()))


def _undefined():
    return dict(defined=False,baseline_sum=None,intervention_sum=None,sum_delta=None,mean_delta=None,
        baseline_mean=None,intervention_mean=None,relative_sum_delta=None,baseline_near_zero=None,
        absolute_sum_delta=None,sum_absolute_delta=None)


def replay_summary(case,replay,window=None,limit=100):
    columns=_ready(case,replay);window=_window(replay['default_window'] if window is None else window,replay['config']['experiment']['steps'])
    if type(limit) is not int or not 1<=limit<=1000:raise ValueError('Replay summary limit must be 1..1000')
    a,b=window['start'],window['stop'];positions={step:index for index,step in enumerate(replay['time_steps'])}
    node_steps=list(range(a+1,b+1));edge_steps=list(range(a,b))
    missing_nodes=[step for step in node_steps if step not in positions]
    missing_edges=[step for step in edge_steps if step not in positions]
    baseline,intervention=replay['states'];nodes=[];edges=[]
    if not missing_nodes:
        rows=[positions[step] for step in node_steps]
        for body,column in columns.items():
            nodes.append(dict(body_id=body,**_summary_metric(baseline[rows,column],intervention[rows,column],b-a)))
    else:nodes=[dict(body_id=body,**_undefined()) for body in columns]
    if not missing_edges:
        rows=[positions[step] for step in edge_steps];cfg=replay['config']['experiment']
        # Fixed chunks bound temporary work; no persistent edge*time matrix.
        for start in range(0,len(replay['edges']),128):
            for edge in replay['edges'][start:start+128]:
                column=columns[edge['pre_id']];factor=cfg['alpha']*cfg['rho']*edge['weight']
                gains=np.asarray([replay['_interventions'].edge_gain(edge['pre_id'],edge['post_id'],step) for step in edge_steps])
                edges.append(dict(edge,**_summary_metric(baseline[rows,column]*factor,intervention[rows,column]*factor*gains,b-a)))
    else:edges=[dict(edge,**_undefined()) for edge in replay['edges']]
    rank=lambda row:(-(row['absolute_sum_delta'] or 0.),row.get('body_id',row.get('edge_id')))
    nodes.sort(key=rank);edges.sort(key=rank)
    return dict(window=window,sample_count=b-a,nodes_defined=not missing_nodes,edges_defined=not missing_edges,
        missing_node_steps=missing_nodes,missing_edge_steps=missing_edges,nodes=nodes[:limit],edges=edges[:limit],
        node_total=len(nodes),edge_total=len(edges),limit=limit,node_state_steps=[a+1,b],edge_update_steps=[a,b-1],
        ranking='absolute cumulative change within the recorded induced circuit')


def _display(replay,value):
    allowed={'mode','state_step','selected_node','selected_nodes','selected_edge','window'}
    if not isinstance(value,dict) or set(value)-allowed:
        raise ValueError('Replay display contains unsupported fields')
    nodes={node['body_id'] for node in replay['nodes']};edges={edge['edge_id'] for edge in replay['edges']}
    if 'mode' in value and value['mode'] not in ('baseline','intervention','delta'):
        raise ValueError('Replay display mode must be baseline, intervention or delta')
    if 'state_step' in value:_position(replay,value['state_step'])
    if value.get('selected_node') is not None and (not isinstance(value['selected_node'],str) or value['selected_node'] not in nodes):
        raise ValueError('Replay display selected_node was not recorded')
    if value.get('selected_edge') is not None and (not isinstance(value['selected_edge'],str) or value['selected_edge'] not in edges):
        raise ValueError('Replay display selected_edge is not a recorded real edge')
    if 'selected_nodes' in value:_ids(value['selected_nodes'],nodes,'Replay display selected_nodes',empty=True)
    if 'window' in value:_window(value['window'],replay['config']['experiment']['steps'])
    return copy.deepcopy(value)


def save_replay(root,replay,display=None):
    if not replay.get('ready') or 'states' not in replay:raise ValueError('Only a ready complete replay can be saved')
    clean=public_replay(replay)
    clean['display']=_display(replay,replay.get('display',{}) if display is None else display)
    folder=Path(root)/('replay-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8])
    folder.mkdir(parents=True)
    for name,value in (('replay.json',clean),('config.json',clean['config'])):
        (folder/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    np.savez_compressed(folder/'states.npz',baseline=replay['states'][0],intervention=replay['states'][1])
    return folder


def load_replay(path,case):
    folder=Path(path);folder=folder.parent if folder.is_file() else folder
    replay=json.loads((folder/'replay.json').read_text(encoding='utf-8-sig'))
    if replay.get('kind')!='circuit_replay' or not replay.get('ready') or replay.get('status')!='complete':
        raise ValueError('Saved replay is not a complete circuit replay')
    config=replay['config']
    if any(config.get(key)!=value for key,value in _identity(case).items()):
        raise ValueError('Saved replay identity does not match this computation scope')
    expected,*_=_plan(case,config['source_result'],config['request'],loading=True)
    for key in ('experiment','recording','source_result'):
        if json.dumps(config[key],sort_keys=True)!=json.dumps(expected['config'][key],sort_keys=True):
            raise ValueError(f'Saved replay {key} does not match its resolved exact protocol')
    for key in ('nodes','edges','time_steps','recording_metadata','default_window'):
        if replay[key]!=expected[key]:raise ValueError(f'Saved replay {key} does not match the exact protocol and node mapping')
    replay['display']=_display(replay,replay.get('display',{}))
    shape=(len(replay['time_steps']),len(replay['nodes']))
    # Check uncompressed member sizes before loading the existing NPZ format.
    header=_history_headers(folder/'states.npz')
    if header['shapes']!={'baseline':list(shape),'intervention':list(shape)} or header['bytes']!=expected['memory']['record_bytes']:
        raise ValueError('Replay NPZ exceeds the declared recording dimensions')
    with np.load(folder/'states.npz',allow_pickle=False) as arrays:
        states=(arrays['baseline'],arrays['intervention'])
    if any(values.shape!=shape or values.dtype!=np.float64 or not np.isfinite(values).all() for values in states):
        raise ValueError('Saved replay states do not match finite float64 recording dimensions')
    replay['states']=states
    _ready(case,replay)
    replay['color_domain']=_scales(replay)
    _output_curves(case,replay)
    return replay
