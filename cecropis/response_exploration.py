"""Case-bound input response distributions; no full-state histories are retained."""
import copy
import hashlib
import json
import math
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import numpy as np

from .group_connections import FIELDS
from .replay import _identity
from .simulation import (Experiment, RecordPolicy, SimulationPlan, SimulationCancelled,
                         _evaluation_window, effective_input_events, effective_observations,
                         response_metrics, simulate)

ARRAYS = ('body_ids', 'membership', 'baseline', 'intervention')
DEFAULT_BUDGETS = dict(max_conditions=64, max_propagations=128,
                       max_bytes=512*1024**2, max_storage_bytes=256*1024**2)


def generate_input(name, body_ids, start, stop, strength, mode='per_node'):
    """Only generate existing input events; neither observations nor inputs are reweighted later."""
    if mode not in ('per_node', 'fixed_total'):
        raise ValueError('Input generation mode must be per_node or fixed_total')
    _evaluation_window(dict(start=start,stop=stop),None)
    if not isinstance(body_ids,list) or any(isinstance(i,bool) or not isinstance(i,(str,int)) or not str(i).isdigit() or not 0<=int(i)<2**63 for i in body_ids):
        raise ValueError('Input body IDs must be exact nonnegative int64 integers or decimal strings')
    ids=sorted({str(int(i)) for i in body_ids},key=int)
    if not ids:raise ValueError('Input collection is empty')
    if isinstance(strength,bool) or not isinstance(strength,(float,int)) or not math.isfinite(strength) or strength<0:
        raise ValueError('Input strength must be finite and nonnegative')
    amplitude=strength if mode=='per_node' else strength/len(ids)
    if amplitude>1:raise ValueError('Generated per-node amplitude exceeds 1')
    return dict(name=name,input_events=[dict(body_ids=ids,start=start,stop=stop,amplitude=amplitude)],
                generation=dict(mode=mode,member_count=len(ids),per_node_amplitude=amplitude,
                                total_amplitude=amplitude*len(ids)))


def _cfg(case, definition, condition):
    # An internal readout permits the existing simulation validator to operate;
    # it is not a new user observation or goal and is never exported as such.
    obs=condition['observations'] or [dict(name='响应统计',body_ids=[str(case['nodes'][0]['bodyId'])])]
    return Experiment.from_dict(dict(steps=definition['steps'],alpha=definition['alpha'],rho=definition['rho'],
        input_events=condition['input_events'],observations=obs,
        intervention_events=definition['intervention_events'] or [],intervention_semantics_version=1))


def preview_responses(case, definition):
    if not isinstance(definition,dict):raise ValueError('Response definition must be an object')
    allowed={'name','conditions','steps','alpha','rho','window','group_field','intervention_events','budgets'}
    if set(definition)-allowed:raise ValueError('Unknown response fields: '+', '.join(sorted(set(definition)-allowed)))
    d=copy.deepcopy(definition)
    d.setdefault('name','输入响应');d.setdefault('steps',100);d.setdefault('alpha',.3);d.setdefault('rho',.9)
    if not isinstance(d['name'],str) or not d['name'].strip() or len(d['name'])>120:raise ValueError('Task name must contain 1..120 characters')
    d.setdefault('group_field','superclass')
    if d['group_field'] not in FIELDS:raise ValueError('Unsupported response grouping field')
    # Validate steps before default window arithmetic, including bool rejection.
    template=Experiment.from_dict(dict(steps=d['steps'],alpha=d['alpha'],rho=d['rho'],input_events=[],
        observations=[dict(name='校验',body_ids=[str(case['nodes'][0]['bodyId'])])],
        intervention_events=[],intervention_semantics_version=1))
    template.validate(case['nodes'])
    d['window']=_evaluation_window(d.get('window',dict(start=0,stop=d['steps'])),d['steps'])
    d.setdefault('intervention_events',None)
    if d['intervention_events'] is not None:
        from .interventions import normalize_intervention_events, CompiledInterventions
        d['intervention_events']=normalize_intervention_events(d['intervention_events'],d['steps'],case['nodes'])
        values=asdict(template);values['intervention_events']=d['intervention_events']
        CompiledInterventions(case,Experiment.from_dict(values)) # verifies real directed edges
    budgets=dict(DEFAULT_BUDGETS)
    if set(d.get('budgets',{}))-set(budgets):raise ValueError('Unknown response budget')
    budgets.update(d.get('budgets',{}))
    for key,value in budgets.items():
        if type(value) is not int or value<1:raise ValueError(key+' must be a positive integer')
    if budgets['max_conditions']>256:raise ValueError('At most 256 input conditions per task')
    d['budgets']=budgets
    conditions=d.get('conditions')
    if not isinstance(conditions,list) or not 1<=len(conditions)<=budgets['max_conditions']:
        raise ValueError('Input condition count exceeds budget or is empty')
    names=set();prepared=[];available={str(n['bodyId']) for n in case['nodes']}
    def check_members(item,name):
        for field in ('input_events','observations'):
            for k,entry in enumerate(item.get(field) or []):
                missing=[str(i) for i in entry.get('body_ids',[]) if str(i) not in available]
                if missing:raise ValueError(f'{name}.{field}[{k}] outside scope: '+', '.join(missing))
    for item in conditions:
        if not isinstance(item,dict) or set(item)-{'name','input_events','observations','experiment','generation','search_options','role'}:
            raise ValueError('Invalid input condition fields')
        name=item.get('name')
        if not isinstance(name,str) or not name.strip() or len(name)>80 or name in names:raise ValueError('Unique input condition names of 1..80 characters required')
        names.add(name)
        check_members(item.get('experiment',item),name)
        if 'experiment' in item:
            if 'input_events' in item or 'observations' in item:raise ValueError(name+': experiment conflicts with explicit protocol fields')
            source=Experiment.from_dict(item['experiment']);source.validate(case['nodes'])
            if any(getattr(source,k)!=d[k] for k in ('steps','alpha','rho')):raise ValueError(name+': source model/steps differ from common definition')
            inputs=effective_input_events(case['nodes'],source);obs=effective_observations(case['nodes'],source)
        else:
            if 'input_events' not in item:raise ValueError(name+': input_events required')
            inputs=item['input_events'];obs=item.get('observations',[])
        condition=dict(name=name,input_events=inputs,observations=obs,
                       generation=item.get('generation',dict(mode='protocol')),
                       search_options=item.get('search_options'),role=item.get('role','decision'))
        if condition['role'] not in ('decision','extra'):raise ValueError(name+': role must be decision or extra')
        cfg=_cfg(case,d,condition);cfg.validate(case['nodes'])
        condition['input_events']=effective_input_events(case['nodes'],cfg)
        if obs:condition['observations']=effective_observations(case['nodes'],cfg)
        # Supplied constraints remain bound to the original observations.
        if condition['search_options'] is not None:
            from .search import SearchOptions
            options=SearchOptions.from_dict(condition['search_options']);options.validate()
            if not obs:raise ValueError(name+': constraints require original observations')
            options.resolve(cfg)
        prepared.append(condition)
    d['conditions']=prepared
    serialized=json.dumps(d,sort_keys=True,ensure_ascii=False,allow_nan=False).encode('utf-8')
    nodes=len(case['nodes']);count=len(prepared);branches=1+int(d['intervention_events'] is not None)
    propagations=count*branches
    # Two float64 matrices are allocated, with NaN distinguishing unavailable branches.
    array_bytes=count*nodes*16+nodes*12
    group_count=len({None if n.get(d['group_field']) in (None,'') else str(n[d['group_field']]) for n in case['nodes']})
    metadata_bytes=len(json.dumps(d,ensure_ascii=False).encode('utf-8'))+nodes*192+group_count*count*256
    if metadata_bytes>64*1024**2:raise ValueError('Response metadata/matrix exceeds 64 MiB; reduce conditions or use a coarser grouping')
    storage_bytes=array_bytes+metadata_bytes
    memory_bytes=array_bytes+nodes*256+metadata_bytes
    if propagations>budgets['max_propagations']:raise ValueError('Propagation count exceeds max_propagations')
    if memory_bytes>budgets['max_bytes']:raise ValueError(f'Response memory estimate {memory_bytes} exceeds max_bytes')
    if storage_bytes>budgets['max_storage_bytes']:raise ValueError(f'Response storage estimate {storage_bytes} exceeds max_storage_bytes')
    return dict(definition=d,identity=_identity(case),node_count=nodes,condition_count=count,
        expected_propagations=propagations,group_count=group_count,array_bytes=array_bytes,estimated_memory_bytes=memory_bytes,
        estimated_storage_bytes=storage_bytes,
        definition_hash=hashlib.sha256(serialized).hexdigest())


def initialize_responses(case,definition):
    preview=preview_responses(case,definition);d=preview['definition'];nodes=case['nodes'];count=len(d['conditions'])
    values=[None if n.get(d['group_field']) in (None,'') else str(n[d['group_field']]) for n in nodes]
    labels=sorted(set(values),key=lambda v:(v is None,v or ''));lookup={v:i for i,v in enumerate(labels)}
    membership=np.asarray([lookup[v] for v in values],dtype=np.int32)
    sizes=np.bincount(membership,minlength=len(labels))
    report=dict(kind='response_exploration',schema_version=1,**preview['identity'],preview={k:v for k,v in preview.items() if k!='definition'},
        definition=d,definition_hash=preview['definition_hash'],status='running',
        body_ids=np.asarray([int(n['bodyId']) for n in nodes],dtype=np.uint64),membership=membership,
        node_annotations=[dict(type=n.get('type'),instance=n.get('instance')) for n in nodes],
        groups=[dict(id=i,name=v,member_count=int(sizes[i])) for i,v in enumerate(labels)],
        baseline=np.full((count,len(nodes)),np.nan),intervention=np.full((count,len(nodes)),np.nan),
        condition_states=[dict(name=c['name'],status='not_run',baseline_status='not_run',intervention_status='not_run' if d['intervention_events'] is not None else 'not_requested') for c in d['conditions']],
        execution_counts=dict(baseline_started=0,baseline_completed=0,intervention_started=0,intervention_completed=0),
        display={},elapsed_seconds=0,curve_requests=[])
    return report


def explore_responses(case,definition,*,cancel=lambda:False,progress=lambda p:None,
                      resume=None,pause=lambda:False,checkpoint=lambda report,unit:None):
    preview=preview_responses(case,definition)
    report=resume if resume is not None else initialize_responses(case,definition)
    if report['definition_hash']!=preview['definition_hash'] or any(report.get(k)!=v for k,v in preview['identity'].items()):
        raise ValueError('Response checkpoint scope/definition mismatch')
    d=report['definition'];count=len(d['conditions']);report['status']='running'
    began=time.perf_counter()
    for i,condition in enumerate(d['conditions']):
        state=report['condition_states'][i]
        branches=('baseline','intervention')[:1+int(d['intervention_events'] is not None)]
        if all(state[b+'_status']=='complete' for b in branches):continue
        if pause():report['status']='paused';break
        if cancel():report['status']='cancelled';break
        cfg=_cfg(case,d,condition);plan=SimulationPlan(case,cfg,collect_signals=False)
        state['status']='running'
        for branch in branches:
            if state[branch+'_status']=='complete':continue
            if pause():report['status']='paused';break
            if cancel():state.update(status='cancelled');report['status']='cancelled';break
            report['execution_counts'][branch+'_started']+=1;state[branch+'_status']='running'
            state.pop('error',None)
            checkpoint(report,dict(kind='started',condition=i,branch=branch))
            progress(dict(condition=i+1,condition_count=count,name=condition['name'],branch=branch,**report['execution_counts']))
            try:
                stats=simulate(case,cfg,plan=plan,recording=RecordPolicy(mode='none'),collect_curves=False,
                    node_window=d['window'],apply_interventions=branch=='intervention',cancel=cancel)
                report['execution_counts'][branch+'_completed']+=1
                if cancel():
                    checkpoint(report,dict(kind='physical_completed',condition=i,branch=branch))
                    raise SimulationCancelled('Cancelled before branch publication')
                report[branch][i]=stats.node_window_sum;state[branch+'_status']='complete'
                state['status']='complete' if all(state[b+'_status']=='complete' for b in ('baseline','intervention')[:1+int(d['intervention_events'] is not None)]) else 'partial'
                checkpoint(report,dict(kind='committed',condition=i,branch=branch))
            except Exception as exc:
                status='cancelled' if isinstance(exc,SimulationCancelled) else 'failed'
                state.update(status=status,error=str(exc));state[branch+'_status']=status;report['status']=status;break
        if report['status']!='running':break
        state['status']='complete'
    if report['status']=='running':report['status']='complete'
    report['elapsed_seconds']+=time.perf_counter()-began
    counts=report['execution_counts'];counts['physical_started']=counts['baseline_started']+counts['intervention_started']
    counts['physical_completed']=counts['baseline_completed']+counts['intervention_completed']
    progress(dict(status=report['status'],**counts));return report


def public_responses(report):
    _check_definition(report)
    result={k:v for k,v in report.items() if k not in (*ARRAYS,'node_annotations')}
    length=report['definition']['window']['stop']-report['definition']['window']['start']
    rows=[]
    for i,state in enumerate(report['condition_states']):
        groups=[]
        sums={branch:np.bincount(report['membership'],weights=report[branch][i]/length,minlength=len(report['groups']))
              for branch in ('baseline','intervention') if state[branch+'_status']=='complete'}
        for group in report['groups']:
            n=group['member_count'];k=group['id']
            b=float(sums['baseline'][k]) if 'baseline' in sums else None
            x=float(sums['intervention'][k]) if 'intervention' in sums else None
            metric=response_metrics(b/n,x/n,1) if b is not None and x is not None else None
            groups.append(dict(group_id=group['id'],member_count=n,baseline_mean=None if b is None else b/n,
                intervention_mean=None if x is None else x/n,baseline_node_mean_sum=b,intervention_node_mean_sum=x,
                delta=None if metric is None else metric['mean_delta'],relative_delta=None if metric is None else metric['relative_sum_delta']))
        rows.append(dict(**state,groups=groups))
    return dict(result,group_responses=rows)


def response_values(report,condition,mode='baseline'):
    _check_definition(report)
    if type(condition) is not int or not 0<=condition<len(report['condition_states']):raise ValueError('Unknown response condition')
    if mode not in ('baseline','intervention','delta'):raise ValueError('Unknown response mode')
    state=report['condition_states'][condition]
    required=('baseline','intervention') if mode=='delta' else (mode,)
    if any(state[b+'_status']!='complete' for b in required):raise ValueError('Requested response branch is not complete')
    length=report['definition']['window']['stop']-report['definition']['window']['start']
    values=(report['intervention'][condition]-report['baseline'][condition]) if mode=='delta' else report[mode][condition]
    return values/length


def response_nodes(report,condition,*,group_id=None,mode='baseline',other=None,exclude_inputs=False,offset=0,limit=50):
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=500:raise ValueError('Invalid node page')
    values=response_values(report,condition,mode);mask=np.ones(len(values),dtype=bool)
    if group_id is not None:
        if type(group_id) is not int or not 0<=group_id<len(report['groups']):raise ValueError('Unknown response group')
        mask&=report['membership']==group_id
    if exclude_inputs:
        inputs={int(i) for e in report['definition']['conditions'][condition]['input_events'] for i in e['body_ids']}
        mask&=~np.isin(report['body_ids'],list(inputs))
    other_values=response_values(report,other,mode) if other is not None else None
    scores=np.abs(values-other_values) if other_values is not None else np.abs(values) if mode=='delta' else values
    indices=np.flatnonzero(mask);indices=indices[np.lexsort((report['body_ids'][indices],-scores[indices]))]
    rows=[]
    for k in indices[offset:offset+limit]:
        state=report['condition_states'][condition];length=report['definition']['window']['stop']-report['definition']['window']['start']
        b=float(report['baseline'][condition,k]/length) if state['baseline_status']=='complete' else None
        x=float(report['intervention'][condition,k]/length) if state['intervention_status']=='complete' else None
        m=response_metrics(b,x,1) if b is not None and x is not None else None
        rows.append(dict(body_id=str(report['body_ids'][k]),**report['node_annotations'][k],value=float(values[k]),
            baseline=b,intervention=x,delta=None if m is None else m['mean_delta'],relative_delta=None if m is None else m['relative_sum_delta'],
            other_value=None if other_values is None else float(other_values[k]),
            condition_difference=None if other_values is None else float(values[k]-other_values[k])))
    return dict(rows=rows,total=len(indices),offset=offset,limit=limit)


def response_condition(case,report,condition,group_id,observation_name=None):
    if _identity(case)!={k:report.get(k) for k in _identity(case)}:raise ValueError('Response scope/index/model mismatch')
    _check_definition(report)
    if type(condition) is not int or not 0<=condition<len(report['condition_states']):raise ValueError('Unknown response condition')
    if report['condition_states'][condition]['status']!='complete':raise ValueError('Select a completely evaluated input condition')
    item=copy.deepcopy(report['definition']['conditions'][condition]);obs=item['observations']
    if group_id is not None:
        if type(group_id) is not int or not 0<=group_id<len(report['groups']):raise ValueError('Unknown response group')
        name=observation_name or '响应 · '+str(report['groups'][group_id]['name'] or '缺注释')
        if name in {o['name'] for o in obs}:raise ValueError('New observation name conflicts with a source observation')
        obs.append(dict(name=name,body_ids=[str(i) for i in report['body_ids'][report['membership']==group_id]],
                        evaluation_window=report['definition']['window']))
    if not obs:raise ValueError('Select a response group to create an observation')
    cfg=_cfg(case,report['definition'],item)
    cfg.validate(case['nodes'])
    return dict(name=item['name'],experiment=asdict(cfg),search_options=item.get('search_options'),role=item['role'])


def response_curves(case,report,condition,group_id,*,observation_name=None,recording=None,cancel=lambda:False,progress=lambda p:None):
    from .exploration import compare_conditions
    selected=response_condition(case,report,condition,group_id,observation_name=observation_name)
    counts=dict(baseline_started=0,baseline_completed=0,intervention_started=0,intervention_completed=0)
    request=dict(condition=condition,group_id=group_id,status='running',execution_counts=counts)
    report.setdefault('curve_requests',[]).append(request)
    def tick(value):
        key=value.get('kind','')+'_'+value.get('status','')
        if key in counts:counts[key]+=1
        progress(value)
    try:
        result=compare_conditions(case,[dict(name=selected['name'],experiment=selected['experiment'])],
            recording=recording or RecordPolicy(mode='none'),cancel=cancel,simulation_progress=tick)
        request['status']='complete'
    except Exception as exc:
        request.update(status='cancelled' if isinstance(exc,SimulationCancelled) else 'failed',error=str(exc))
        result=getattr(exc,'partial_comparison',dict(case_id=report['case_id'],model_version=report['model_version'],
            conditions=[],results=[],rows=[],protocol={}))
        result['error']=str(exc)
    counts['physical_started']=counts['baseline_started']+counts['intervention_started']
    counts['physical_completed']=counts['baseline_completed']+counts['intervention_completed']
    result['execution_counts']=dict(counts);result['status']=request['status']
    result['response_exploration_source']=dict(definition_hash=report['definition_hash'],condition=condition,group_id=group_id)
    if selected.get('search_options') is not None and result['results']:
        from .operation_search import _assess_events
        assessments=_assess_events(case,[(selected['name'],Experiment.from_dict(selected['experiment']))],
            [r['summary'] for r in result['results']],selected['search_options'])
        result['rows'][0]['constraints']=assessments['condition_results'][0]
        result['constraints']=[dict(name=selected['name'],role=selected['role'],
            constraints=dict(condition_results=assessments['condition_results'],feasible=assessments['feasible']))]
        result['search_options']=selected['search_options']
    return result


def scope_input_groups(case,field):
    if field not in FIELDS:raise ValueError('Unsupported response grouping field')
    groups={}
    for node in case['nodes']:
        value=None if node.get(field) in (None,'') else str(node[field])
        groups.setdefault(value,[]).append(str(node['bodyId']))
    return dict(field=field,groups=[dict(id=i,name=name,body_ids=groups[name])
        for i,name in enumerate(sorted(groups,key=lambda v:(v is None,v or '')))])


def save_responses(root,report,display=None):
    _check_definition(report)
    header={k:v for k,v in report.items() if k not in ARRAYS}
    if display is not None:header['display']=copy.deepcopy(display)
    payload=json.dumps(header,ensure_ascii=False,allow_nan=False).encode('utf-8')
    if len(payload)>64*1024**2:raise ValueError('Response metadata exceeds 64 MiB')
    budget=report['definition']['budgets']['max_storage_bytes']
    if len(payload)+sum(report[k].nbytes for k in ARRAYS)>budget:raise ValueError('Response artifact exceeds storage budget')
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    name='responses-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8]
    folder=root/('.'+name);folder.mkdir()
    try:
        np.savez_compressed(folder/'responses.npz',**{k:report[k] for k in ARRAYS})
        (folder/'response-exploration.json').write_bytes(payload)
        (folder/'config.json').write_text(json.dumps({k:report[k] for k in ('case_id','source_index_id','model_version','definition')},ensure_ascii=False),encoding='utf-8')
        folder.rename(root/name)
    except Exception:
        # An unpublished hidden artifact never enters the runnable catalog.
        raise
    return root/name


def load_responses(path,case=None):
    folder=Path(path);folder=folder.parent if folder.is_file() else folder
    if (folder/'task.json').is_file():
        from .local_tasks import LocalTasks
        report=LocalTasks(folder.parent.parent).result(folder.name)
        _check_definition(report)
        if case is not None and _identity(case)!={k:report.get(k) for k in _identity(case)}:raise ValueError('Response scope/index/model mismatch')
        return report
    header=folder/'response-exploration.json'
    if header.stat().st_size>64*1024**2:raise ValueError('Response metadata exceeds 64 MiB')
    report=json.loads(header.read_text(encoding='utf-8-sig'))
    if report.get('kind')!='response_exploration' or report.get('schema_version')!=1:raise ValueError('Unsupported response result')
    _check_definition(report)
    if case is not None and _identity(case)!={k:report.get(k) for k in _identity(case)}:raise ValueError('Response scope/index/model mismatch')
    from zipfile import ZipFile
    with ZipFile(folder/'responses.npz') as archive:
        if sum(i.file_size for i in archive.infolist())>report['definition']['budgets']['max_storage_bytes']:raise ValueError('Response arrays exceed storage budget')
    with np.load(folder/'responses.npz',allow_pickle=False) as arrays:
        report.update({k:arrays[k] for k in ARRAYS})
    n=len(report['body_ids']);c=len(report['definition']['conditions'])
    if report['baseline'].shape!=(c,n) or report['intervention'].shape!=(c,n) or report['membership'].shape!=(n,):raise ValueError('Response array shape mismatch')
    if case is not None and [str(i) for i in report['body_ids']]!=[str(i['bodyId']) for i in case['nodes']]:raise ValueError('Response body ID order mismatch')
    if len(report['condition_states'])!=c or len(report['node_annotations'])!=n:raise ValueError('Response metadata dimensions mismatch')
    if len(set(report['body_ids'].tolist()))!=n or np.any(report['membership']<0) or np.any(report['membership']>=len(report['groups'])):
        raise ValueError('Response member/group mapping is invalid')
    for i,state in enumerate(report['condition_states']):
        for branch in ('baseline','intervention'):
            if state[branch+'_status']=='complete' and not np.isfinite(report[branch][i]).all():raise ValueError('Completed response branch contains missing values')
    return report


def _check_definition(report):
    actual=hashlib.sha256(json.dumps(report['definition'],sort_keys=True,ensure_ascii=False,allow_nan=False).encode('utf-8')).hexdigest()
    if actual!=report['definition_hash']:raise ValueError('Response definition changed; saved arrays still belong to their original definition')
