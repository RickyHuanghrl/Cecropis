"""Finite fixed-operation beam search; metrics-only batch, explicit curve requests."""
import copy
import hashlib
import json
import re
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .interventions import normalize_intervention_events, neutral_legacy, CompiledInterventions, preview_interventions
from .simulation import Experiment, SimulationPlan, RecordPolicy, SimulationCancelled, simulate, observation_metrics, protocol_key, effective_input_events, effective_observations
from .search import SearchOptions
from .plan_reduction import _assess
from .replay import _identity
from .exploration import compare_conditions, annotate_operation_constraints

RANKING = ('feasible first; feasible: fewer operations, greater worst target loss, greater mean target loss, '
           'stable candidate IDs; infeasible: fewer undefined requirements, fewer failed requirements, '
           'lexicographic dimensionless deficits (target then protections by protocol/name), greater worst target loss, stable IDs')


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _cfg(base, events):
    return replace(base, intervention_events=tuple(copy.deepcopy(events)), intervention_semantics_version=1,
                   **neutral_legacy(base.steps))


def _coverage(events):
    nodes = sorted({b for e in events if e['type']=='node_gain' for b in e['body_ids']}, key=int)
    edges = sorted({tuple(p) for e in events if e['type']=='edge_gain' for p in e['edges']}, key=lambda p:tuple(map(int,p)))
    return dict(operation_count=len(events), node_count=len(nodes), edge_count=len(edges), body_ids=nodes,
                edges=[list(p) for p in edges], edge_endpoint_ids=sorted({b for p in edges for b in p},key=int))


def preview_operation_search(case, definition):
    if not isinstance(definition,dict) or set(definition)-{'name','conditions','candidates','requirements','settings'}:
        raise ValueError('Operation search needs name, conditions, candidates, requirements and settings')
    name=definition.get('name','Operation combinations')
    if not isinstance(name,str) or not name.strip() or len(name)>80:raise ValueError('name must contain 1..80 characters')
    conditions=definition.get('conditions')
    if not isinstance(conditions,list) or not 1<=len(conditions)<=12:raise ValueError('conditions requires 1..12 decision protocols')
    parsed=[];names=set();ref=None
    for item in conditions:
        if not isinstance(item,dict) or set(item)!={'name','experiment'} or not isinstance(item['name'],str) or not item['name'].strip() or len(item['name'])>80 or item['name'] in names:
            raise ValueError('conditions require unique names and complete experiment definitions')
        names.add(item['name'])
        # The protocol is frozen independently of the candidate plans.
        base=Experiment.from_dict(item['experiment']);base.validate(case['nodes']);CompiledInterventions(case,base)
        cfg=_cfg(base,[])
        cfg.input_events=tuple(effective_input_events(case['nodes'],cfg))
        cfg.observations=tuple(effective_observations(case['nodes'],cfg));cfg.validate(case['nodes'])
        key=protocol_key(case['nodes'],cfg);current={k:key[k] for k in key if k!='input_events'}
        if ref is not None and current!=ref:raise ValueError('Decision protocols must share steps, model, observations and evaluation windows')
        ref=current;parsed.append(dict(name=item['name'],experiment=asdict(cfg)))
    req=definition.get('requirements')
    if not isinstance(req,dict) or set(req)!={'target_output','target_metric','min_target_loss','protected_limits'}:
        raise ValueError('requirements must explicitly set target_output, target_metric, min_target_loss and protected_limits')
    options=SearchOptions.from_dict(req);options.resolve(cfg)
    settings=dict(max_operations=3,max_nodes=200,max_edges=10000,max_evaluations=100,beam_width=4)
    raw=definition.get('settings',{})
    if not isinstance(raw,dict) or set(raw)-set(settings):raise ValueError('Unknown operation search setting')
    settings.update(raw)
    # The fixed-task constraint transport currently supports at most 200
    # directly manipulated nodes. Edge endpoints are not charged to this cap.
    limits=dict(max_operations=(0,32),max_nodes=(0,200),max_edges=(0,100000),max_evaluations=(1,10000),beam_width=(1,64))
    for k,(lo,hi) in limits.items():
        if type(settings[k]) is not int or not lo<=settings[k]<=hi:raise ValueError(f'{k} must be integer in [{lo}, {hi}]')
    library=definition.get('candidates')
    if not isinstance(library,list) or len(library)>64:raise ValueError('candidates must be a finite list of at most 64 operations')
    candidates=[];ids=set();contents={};excluded=[]
    for item in library:
        if not isinstance(item,dict) or set(item)-{'id','name','event','exclusive_group'} or 'id' not in item or 'event' not in item:
            raise ValueError('Candidate needs stable id and event; name/exclusive_group are optional')
        ident=item['id']
        if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',ident) or ident in ids:raise ValueError('Candidate IDs must be unique ASCII identifiers (1..64)')
        ids.add(ident);group=item.get('exclusive_group') or None
        if group is not None and (not isinstance(group,str) or len(group)>80):raise ValueError('exclusive_group must be text <=80 characters')
        event=normalize_intervention_events([item['event']],cfg.steps,case['nodes'])[0]
        CompiledInterventions(case,_cfg(cfg,[event]))
        label=item.get('name',event['name'])
        if not isinstance(label,str) or not label.strip() or len(label)>80:raise ValueError('Candidate name must contain 1..80 characters')
        candidate=dict(id=ident,name=label,event=event,exclusive_group=group)
        content=dict(event);content.pop('name');content.pop('enabled')
        if 'body_ids' in content:content['body_ids']=sorted(content['body_ids'],key=int)
        if 'edges' in content:content['edges']=sorted(content['edges'],key=lambda p:tuple(map(int,p)))
        fingerprint=_json(content)
        if not event['enabled'] or event['gain']==1 or not event.get('body_ids',event.get('edges')):
            excluded.append(dict(candidate,reason='no_effect'));continue
        if fingerprint in contents:
            raise ValueError(f'Duplicate execution content: {ident} and {contents[fingerprint]} (names do not distinguish operations)')
        contents[fingerprint]=ident;candidates.append(candidate)
    candidates.sort(key=lambda c:c['id'])
    if sum(len(c['event'].get('body_ids',[])) for c in candidates)>200000 or sum(len(c['event'].get('edges',[])) for c in candidates)>100000:
        raise ValueError('Candidate library exceeds 200000 node targets or 100000 edge targets')
    frozen=dict(name=name,conditions=parsed,candidates=candidates,requirements=copy.deepcopy(req),settings=settings)
    # Saved entries include exact plans as well as metrics. Large real-edge
    # libraries must not bypass the report budget through repeated event JSON.
    event_sizes=sorted((len(json.dumps(dict(c['event'],name=c['id']),ensure_ascii=False,indent=2).encode('utf-8'))
        +32*(_json(c['event']).count('[')+_json(c['event']).count('{')) for c in candidates),reverse=True)
    plan_bytes=sum(event_sizes[:settings['max_operations']])
    report_estimate=len(_json(frozen).encode('utf-8'))*6+settings['max_evaluations']*(len(parsed)*len(cfg.outputs)*6000+plan_bytes)
    if report_estimate>64*1024*1024:raise ValueError('Metrics and exact-plan report estimate exceeds 64 MiB; reduce evaluation budget, targets or observations')
    RecordPolicy(mode='none').resolve(case,cfg,branch_count=1)
    identity=dict(**_identity(case),definition=frozen)
    distinct=len({_json(protocol_key(case['nodes'],Experiment.from_dict(i['experiment']))) for i in parsed})
    return dict(kind='operation_search_preview',schema_version=1,**_identity(case),definition=frozen,
        computation_node_count=len(case['nodes']),internal_edge_count=int(case['counts'].nnz),
        definition_hash=hashlib.sha256(_json(identity).encode()).hexdigest(),excluded_candidates=excluded,
        candidate_count=len(candidates),coverage=_coverage([c['event'] for c in candidates]),
        exclusive_groups={g:[c['id'] for c in candidates if c['exclusive_group']==g] for g in sorted({c['exclusive_group'] for c in candidates if c['exclusive_group']})},
        condition_count=len(parsed),baseline_protocol_count=distinct,
        estimated_propagations_upper_bound=distinct+(settings['max_evaluations']-1)*len(parsed),
        evaluation_unit='distinct combination completed across all decision protocols; empty plan reuses baselines',
        ranking=RANKING,estimated_report_bytes=report_estimate,recording=dict(mode='none'))


def _assess_events(case, parsed, summaries, requirements):
    # Only the metric adapter uses the old set shape. Actual execution always
    # goes through CompiledInterventions, never through a node search evaluator.
    metric_parsed=[(name,replace(cfg,intervention_events=None,intervention_semantics_version=None,
        intervention_ids=(),intervention_group='__event_metrics__')) for name,cfg in parsed]
    return _assess(case,metric_parsed,[],summaries,SearchOptions.from_dict(requirements),[n for n,_ in parsed])


def _rank(entry, req):
    undefined=0;failed=0;gaps=[]
    for row in entry['condition_results']:
        values=[(row['target_loss'],req['min_target_loss'],True)]
        values += [(row['protected_losses'][label],spec['max_loss'],False) for label,spec in sorted(req['protected_limits'].items())]
        for value,limit,target in values:
            if value is None:undefined+=1;failed+=1;gaps.append(float('inf'))
            else:
                gap=max(0,limit-value if target else value-limit);failed+=int(gap>0)
                gaps.append(gap/max(abs(limit),1e-12))
    worst=entry['worst_target_loss'];mean=entry['mean_target_loss']
    if entry['feasible']:return (0,len(entry['candidate_ids']),-(worst or 0),-(mean or 0),tuple(entry['candidate_ids']))
    return (1,undefined,failed,tuple(gaps),-(worst or 0),tuple(entry['candidate_ids']))


def _coverage_constraints(rows,coverage,settings):
    for row in rows:
        row.update(body_ids=coverage['body_ids'],node_count=coverage['node_count'],
            node_constraint=dict(maximum=settings['max_nodes'],node_count=coverage['node_count'],satisfied=coverage['node_count']<=settings['max_nodes']),
            edge_constraint=dict(maximum=settings['max_edges'],edge_count=coverage['edge_count'],satisfied=coverage['edge_count']<=settings['max_edges']),
            operation_constraint=dict(maximum=settings['max_operations'],operation_count=coverage['operation_count'],satisfied=coverage['operation_count']<=settings['max_operations']))


def initialize_operation_search(case, definition):
    preview=preview_operation_search(case,definition);d=preview['definition']
    report=dict(preview,kind='operation_search',status='complete',termination_reason=None,entries=[],layers=[],
        execution_order=[],cache_hits=0,combination_duplicates=0,attempted_evaluations=0,evaluations=0,baseline_started=0,baseline_completed=0,
        intervention_started=0,intervention_completed=0,baseline_reused=0,empty_baseline_reuses=0,
        pruned_combinations=[],feasible_candidate_sets=[],recommended_candidate_ids=None,curve_requests=[],error=None,
        physical_started=0,physical_completed=0,covered_candidate_ids=[],uncovered_candidate_ids=[c['id'] for c in d['candidates']],
        unexplored_policy='not_run lists this generated layer only; descendants of discarded beams and ungenerated layers have not been evaluated')
    return dict(version=1,report=report,baselines={},baseline_names=[],phase='baselines',
        depth=1,beam=[[]],pending=None,position=0,evaluated=[],generated=[])


def search_operations(case, definition, *, cancel=lambda:False, progress=lambda p:None,
                      resume=None,pause=lambda:False,checkpoint=lambda state,event:None):
    # The explicit frontier is also used for ordinary in-memory runs. Ranking,
    # layer construction and numerical execution remain the original algorithm.
    preview=preview_operation_search(case,definition)
    state=resume if resume is not None else initialize_operation_search(case,definition)
    report=state['report'];d=report['definition'];settings=d['settings']
    if state.get('version')!=1 or report['definition_hash']!=preview['definition_hash']:
        raise ValueError('Operation checkpoint definition/scope mismatch')
    report.update(status='complete',termination_reason=None,error=None)
    for entry in report['entries']:
        if entry['status']!='completed' and entry['status']!='interrupted':
            entry.update(status='interrupted',feasible=None,retention_reason='incomplete')
    parsed=[(i['name'],Experiment.from_dict(i['experiment'])) for i in d['conditions']]
    library={c['id']:c for c in d['candidates']}
    plans={name:SimulationPlan(case,cfg,collect_signals=False) for name,cfg in parsed}
    cache={tuple(e['candidate_ids']):e for e in report['entries'] if e['status']=='completed'}
    def refresh():
        complete=list(cache.values())
        report['recommended_candidate_ids']=min(complete,key=lambda e:_rank(e,d['requirements']))['candidate_ids'] if complete else None
        report['covered_candidate_ids']=sorted({i for e in complete for i in e['candidate_ids']})
        report['uncovered_candidate_ids']=sorted(set(library)-set(report['covered_candidate_ids']))
        report['physical_started']=report['baseline_started']+report['intervention_started']
        report['physical_completed']=report['baseline_completed']+report['intervention_completed']
    def publish(event):
        refresh();checkpoint(state,event)
    def notify(phase,ids=None,condition=None):
        progress(dict(phase=phase,candidate_ids=ids,condition=condition,evaluations=report['evaluations'],budget=settings['max_evaluations'],
            baseline_completed=report['baseline_completed'],intervention_completed=report['intervention_completed']))
    def boundary():
        if cancel():report.update(status='cancelled',termination_reason='cancelled');return True
        if pause():report.update(status='paused',termination_reason='pause_requested');return True
        return False
    def baseline_stats(data):
        from .simulation import TrajectoryStats
        import numpy as np
        empty=np.empty(0)
        return TrajectoryStats({},empty,empty,empty,empty,{},None,{},data['config'],observation_sums=data['observation_sums'])
    def interrupted(exc):
        report.update(status='cancelled' if isinstance(exc,SimulationCancelled) else 'failed',
            termination_reason='cancelled' if isinstance(exc,SimulationCancelled) else 'execution_failed',error=str(exc))
    def evaluate(ids):
        key=tuple(sorted(ids))
        if key in cache:report['cache_hits']+=1;return cache[key]
        if boundary():return None
        if report['evaluations']>=settings['max_evaluations']:
            report.update(status='budget_exhausted',termination_reason='evaluation_budget_reached');return None
        events=[dict(library[i]['event'],name=i) for i in key]
        entry=dict(candidate_ids=list(key),events=events,coverage=_coverage(events),status='running',feasible=None,
            condition_results=[],unfinished_condition_names=[n for n,_ in parsed],retention_reason='not_ranked')
        report['entries'].append(entry);report['attempted_evaluations']+=1;report['execution_order'].append(list(key))
        summaries=[]
        try:
            for name,cfg in parsed:
                if cancel():raise SimulationCancelled('Cancelled during incomplete combination')
                base=baseline_stats(state['baselines'][_json(protocol_key(case['nodes'],cfg))])
                if key:
                    report['intervention_started']+=1
                    publish(dict(kind='started',branch='intervention',unit=list(key),condition=name));notify('evaluation',list(key),name)
                    stats=simulate(case,_cfg(cfg,events),plan=plans[name],recording=RecordPolicy(mode='none'),collect_curves=False,cancel=cancel,apply_interventions=True)
                    report['intervention_completed']+=1
                    publish(dict(kind='physical_completed',branch='intervention',unit=list(key),condition=name))
                else:stats=base;report['empty_baseline_reuses']+=1
                summaries.append([dict(type=label,**observation_metrics(case['nodes'],cfg,label,base,stats)) for label in cfg.outputs])
                entry['condition_results']=_assess_events(case,parsed[:len(summaries)],summaries,d['requirements'])['condition_results']
                _coverage_constraints(entry['condition_results'],entry['coverage'],settings)
                entry['unfinished_condition_names'].remove(name)
            if cancel():raise SimulationCancelled('Cancelled before complete combination publication')
            entry.update(status='completed',**_assess_events(case,parsed,summaries,d['requirements']))
            _coverage_constraints(entry['condition_results'],entry['coverage'],settings)
            entry['retention_reason']='evaluated';report['evaluations']+=1;cache[key]=entry
            if entry['feasible']:report['feasible_candidate_sets'].append(list(key))
            notify('evaluation_completed',list(key));return entry
        except Exception as exc:
            interrupted(exc);entry.update(status=report['status'],error=str(exc),feasible=None,retention_reason='incomplete');return None
    try:
        if state['phase']=='baselines':
            for name,cfg in parsed:
                if name in state['baseline_names']:continue
                if boundary():break
                key=_json(protocol_key(case['nodes'],cfg))
                if key not in state['baselines']:
                    report['baseline_started']+=1
                    publish(dict(kind='started',branch='baseline',unit=key,condition=name));notify('baseline',condition=name)
                    stats=simulate(case,cfg,plan=plans[name],recording=RecordPolicy(mode='none'),collect_curves=False,cancel=cancel,apply_interventions=False)
                    report['baseline_completed']+=1
                    state['baselines'][key]=dict(config=stats.config,observation_sums=stats.observation_sums)
                else:report['baseline_reused']+=1
                state['baseline_names'].append(name)
                publish(dict(kind='baseline_committed',branch='baseline',unit=key,condition=name))
            if len(state['baseline_names'])==len(parsed):state['phase']='empty'
        if report['status']=='complete' and state['phase']=='empty':
            empty=evaluate([])
            if empty is not None:
                if empty['feasible']:
                    empty['retention_reason']='empty_plan_satisfies_constraints';report['termination_reason']='no_intervention_needed';state['phase']='done'
                else:state['phase']='layers'
                publish(dict(kind='combination_committed',unit=[]))
        while report['status']=='complete' and state['phase']=='layers':
            if boundary():break
            if state['depth']>min(settings['max_operations'],len(library)):
                state['phase']='done';report['termination_reason']='bounded_layers_completed' if library else 'no_effective_candidates';break
            if state['pending'] is None:
                pending=[];generated={tuple(p) for p in state['generated']}
                for parent in state['beam']:
                    for ident in sorted(library):
                        if ident in parent:continue
                        key=tuple(sorted(parent+[ident]))
                        if key in generated:
                            report['combination_duplicates']+=1
                            if key in cache:report['cache_hits']+=1
                            continue
                        generated.add(key)
                        groups=[library[i]['exclusive_group'] for i in key if library[i]['exclusive_group']]
                        coverage=_coverage([library[i]['event'] for i in key]);reason=None
                        if len(groups)!=len(set(groups)):reason='exclusive_group'
                        elif coverage['node_count']>settings['max_nodes']:reason='node_budget'
                        elif coverage['edge_count']>settings['max_edges']:reason='edge_budget'
                        if reason:report['pruned_combinations'].append(dict(candidate_ids=list(key),reason=reason))
                        else:pending.append(list(key))
                state.update(pending=sorted(pending),position=0,evaluated=[],generated=[list(p) for p in sorted(generated)])
                publish(dict(kind='frontier'))
            while state['position']<len(state['pending']):
                key=state['pending'][state['position']];row=evaluate(key)
                if row is None:break
                state['evaluated'].append(key);state['position']+=1
                publish(dict(kind='combination_committed',unit=key))
            if report['status']!='complete':break
            ranked=sorted((cache[tuple(k)] for k in state['evaluated']),key=lambda e:_rank(e,d['requirements']))
            beam=ranked[:settings['beam_width']]
            for row in ranked:row['retention_reason']='retained_for_next_layer' if row in beam else 'beam_width'
            report['layers'].append(dict(depth=state['depth'],retained=[e['candidate_ids'] for e in beam],not_run=[],evaluated=state['evaluated']))
            state.update(beam=[e['candidate_ids'] for e in beam],depth=state['depth']+1,pending=None,position=0,evaluated=[])
            if not beam:state['phase']='done';report['termination_reason']='bounded_layers_completed'
            publish(dict(kind='layer_committed'))
    except Exception as exc:interrupted(exc)
    refresh()
    # Partial layers remain a frontier, never a next-layer beam. This read-only
    # summary supports the existing result table without altering the frontier.
    report['pending_layer']=None if state['pending'] is None else dict(depth=state['depth'],position=state['position'],
        pending=state['pending'][state['position']:],evaluated=state['evaluated'],parent_beam=state['beam'])
    if report['status']=='budget_exhausted' and state['pending'] is not None:
        # Keep the established historical not_run representation at terminal budget.
        report['layers'].append(dict(depth=state['depth'],retained=[],not_run=state['pending'][state['position']:],evaluated=state['evaluated']))
    notify(report['status'])
    checkpoint(state,dict(kind='stopped'))
    return report


def operation_plan_curves(case, report, candidate_ids, *, extra_conditions=None, recording=None, cancel=lambda:False, progress=lambda p:None):
    if _identity(case)!={k:report.get(k) for k in _identity(case)}:raise ValueError('Operation report scope/index/model mismatch')
    if preview_operation_search(case,report['definition'])['definition_hash']!=report['definition_hash']:
        raise ValueError('Saved operation definition no longer matches its frozen identity')
    row=next((r for r in report['entries'] if r['candidate_ids']==sorted(candidate_ids) and r['status']=='completed'),None)
    if row is None:raise ValueError('Select an actually completed combination')
    library={c['id']:c for c in report['definition']['candidates']}
    expected=[dict(library[i]['event'],name=i) for i in row['candidate_ids']]
    if _json(expected)!=_json(row['events']):raise ValueError('Saved combination no longer matches the frozen library')
    if isinstance(recording,dict):recording=RecordPolicy.from_dict(recording)
    conditions=copy.deepcopy(report['definition']['conditions']);decision=[i['name'] for i in conditions]
    extra=extra_conditions or []
    for item in extra:
        conditions.append(copy.deepcopy(item))
    for item in conditions:
        item['experiment']=asdict(_cfg(Experiment.from_dict(item['experiment']),row['events']))
    request=dict(candidate_ids=list(row['candidate_ids']),extra_condition_names=[i['name'] for i in extra],
        baseline_started=0,baseline_completed=0,intervention_started=0,intervention_completed=0,status='running')
    report['curve_requests'].append(request)
    def tick(p):
        key=p.get('kind','')+'_'+p.get('status','')
        if key in request:request[key]+=1
        progress(p)
    try:
        result=compare_conditions(case,conditions,recording=recording or RecordPolicy(mode='none'),cancel=cancel,simulation_progress=tick)
        request['status']='complete'
    except Exception as exc:
        request.update(status='cancelled' if isinstance(exc,SimulationCancelled) else 'failed',error=str(exc))
        result=getattr(exc,'partial_comparison',dict(case_id=case['manifest']['case_id'],model_version=report['model_version'],
            conditions=[],rows=[],results=[],protocol={}))
        result['error']=str(exc)
    if result['conditions']:
        assessed=_assess_events(case,[(i['name'],Experiment.from_dict(i['experiment'])) for i in conditions],
            [r['summary'] for r in result['results']],report['definition']['requirements']) if len(result['results'])==len(conditions) else _assess_events(case,
                [(i['name'],Experiment.from_dict(i['experiment'])) for i in result['conditions']],
                [r['summary'] for r in result['results']],report['definition']['requirements'])
        result['constraints']=[]
        _coverage_constraints(assessed['condition_results'],_coverage(row['events']),report['definition']['settings'])
        for condition_row,assessment in zip(result['rows'],assessed['condition_results']):
            condition_row['constraints']=assessment
            result['constraints'].append(dict(name=assessment['name'],role='decision' if assessment['name'] in decision else 'extra',
                constraints=dict(condition_results=[assessment],feasible=assessment['feasible'])))
        for item in result['rows']:item['evidence_classification']='decision' if item['name'] in decision else 'extra'
    result['status']=request['status']
    result['operation_search_evaluation']=dict(definition_hash=report['definition_hash'],candidate_ids=row['candidate_ids'],decision_condition_names=decision)
    result['search_options']=asdict(SearchOptions.from_dict(dict(report['definition']['requirements'],max_nodes=max(1,report['definition']['settings']['max_nodes']))))
    result['requested_conditions']=conditions
    done={i['name'] for i in result['conditions']}
    result['condition_states']=[dict(name=i['name'],status='complete' if i['name'] in done else request['status'] if k==len(done) else 'not_run') for k,i in enumerate(conditions)]
    request['baseline_reused']=max(0,len(result['results'])-request['baseline_completed'])
    request['physical_started']=request['baseline_started']+request['intervention_started']
    request['physical_completed']=request['baseline_completed']+request['intervention_completed']
    result['execution_counts']=dict(request)
    return result


def save_operation_search(root,report):
    payload=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)
    if len(payload.encode('utf-8'))>64*1024*1024:raise ValueError('Operation report exceeds 64 MiB; no artifact was published')
    folder=Path(root)/('operation-search-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8]);folder.mkdir(parents=True)
    (folder/'operation-search.json').write_text(payload,encoding='utf-8')
    (folder/'config.json').write_text(json.dumps({k:report[k] for k in ('case_id','source_index_id','model_version','definition')},ensure_ascii=False,indent=2),encoding='utf-8')
    return folder


def load_operation_search(path):
    path=Path(path)
    folder=path if path.is_dir() else path.parent
    if (folder/'task.json').is_file():
        from .local_tasks import LocalTasks
        return LocalTasks(folder.parent.parent).result(folder.name)
    path=path/'operation-search.json' if path.is_dir() else path
    if path.stat().st_size>64*1024*1024:raise ValueError('Operation report exceeds 64 MiB')
    report=json.loads(path.read_text(encoding='utf-8-sig'))
    if report.get('kind')!='operation_search' or report.get('schema_version')!=1:raise ValueError('Unsupported operation search report')
    # Early reports used a neutral node-set adapter for metric assessment.
    # Recover only its coverage metadata from the already saved exact plan;
    # preserve all simulated metrics, ranking and historical completion status.
    for entry in report.get('entries',[]):
        if entry.get('coverage') is not None:
            _coverage_constraints(entry.get('condition_results',[]),entry['coverage'],report['definition']['settings'])
    return report
