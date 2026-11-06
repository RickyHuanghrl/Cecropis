"""Exact-set withdrawal analysis and bounded, traceable feasible deletion."""
import copy
import hashlib
import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .exploration import compare_conditions
from .joint_search import annotate_joint_evaluation
from .replay import _identity, _ids
from .simulation import Experiment, SimulationPlan, SimulationCancelled, observation_metrics, simulate, effective_input_events, effective_observations, protocol_key
from .timing_exploration import _prepare as prepare_timing, _minimal_comparison, _key


class FixedExperiment(Experiment):
    """Explicit fixed-plan adapter; () means no intervention, never a group default."""
    def validate(self,nodes):
        if self.intervention_ids == () or self.intervention_ids == []:
            check=replace(self,intervention_ids=None,intervention_group='__all__')
            # Scope roles are operation annotations. A zero-intervention set
            # needs no eligible internal role; all other checks remain identical.
            checked_nodes=[]
            for node in nodes:
                membership={role:list(labels) for role,labels in node.get('memberships',{}).items()}
                if not membership:
                    membership={node.get('role','context'):[node.get('group_label',node.get('type'))]}
                membership.setdefault('internal',[]).append('__fixed_empty_validation__')
                checked_nodes.append(dict(node,memberships=membership))
            Experiment.validate(check,checked_nodes)
            self.input_events=check.input_events;self.observations=check.observations;self.outputs=check.outputs
            return
        return Experiment.validate(self,nodes)


def _prepare(case, conditions, body_ids, options, extra_conditions=None):
    available = {str(n['bodyId']) for n in case['nodes']}
    bodies = _ids(body_ids, available, 'Reduction intervention', empty=True)
    if len(bodies) > 200:
        raise ValueError('Reduction supports at most 200 exact intervention members')
    if options is None:
        raise ValueError('Reduction requires explicit target and protection requirements')
    raw_options = asdict(options) if not isinstance(options, dict) else options
    if not raw_options.get('target_output') or raw_options.get('protected_limits') is None:
        raise ValueError('Set target_output and protected_limits explicitly ({} means no protected outputs)')
    if not isinstance(conditions, list) or not 1 <= len(conditions) <= 12:
        raise ValueError('Reduction requires 1..12 decision protocols')
    extra = [] if extra_conditions is None else extra_conditions
    if not isinstance(extra, list) or len(conditions)+len(extra) > 12:
        raise ValueError('Decision and extra protocols together require at most 12 conditions')
    combined = conditions+extra
    original_cfgs = [item['experiment'] if isinstance(item['experiment'], Experiment)
                    else Experiment.from_dict(item['experiment']) for item in combined]
    from .interventions import require_legacy_intervention
    for cfg in original_cfgs:
        require_legacy_intervention(cfg,'Node withdrawal and reduction')
    first = original_cfgs[0]
    if any((cfg.intervention_start,cfg.intervention_stop,cfg.gain) !=
           (first.intervention_start,first.intervention_stop,first.gain) for cfg in original_cfgs):
        raise ValueError('All reduction protocols must use the same gain and intervention interval')
    if bodies:
        view, parsed, _, options, _ = prepare_timing(case, combined, bodies,
            [first.intervention_start], [first.intervention_stop-first.intervention_start], options)
    else:
        from .search import SearchOptions
        options=SearchOptions.from_dict(raw_options)
        view=case;parsed=[];reference=None;names=set()
        for item,raw in zip(combined,original_cfgs):
            if set(item)!={'name','experiment'} or not isinstance(item['name'],str) or not item['name'].strip() or len(item['name'])>80 or item['name'] in names:
                raise ValueError('Reduction conditions require unique named protocols')
            names.add(item['name'])
            cfg=FixedExperiment.from_dict(asdict(raw));cfg.intervention_ids=()
            cfg.input_events=tuple(effective_input_events(case['nodes'],cfg))
            cfg.observations=tuple(effective_observations(case['nodes'],cfg));cfg.validate(case['nodes'])
            current=dict(steps=cfg.steps,alpha=cfg.alpha,rho=cfg.rho,observations=protocol_key(case['nodes'],cfg)['observations'])
            if reference is not None and current!=reference:raise ValueError('Reduction protocols must share model parameters and observations')
            reference=current;options.resolve(cfg);parsed.append((item['name'],cfg))
    return view, parsed, bodies, options, [item['name'] for item in conditions]


def _definition(case, parsed, bodies, options, decision_names, simplify):
    conditions = [dict(name=name, experiment=asdict(replace(cfg, intervention_ids=tuple(bodies),
        intervention_group=cfg.intervention_group if bodies else '__fixed_no_intervention__')))
                  for name,cfg in parsed]
    definition = dict(**_identity(case), conditions=[item for item in conditions if item['name'] in decision_names],
        extra_conditions=[item for item in conditions if item['name'] not in decision_names],
        original_body_ids=bodies, search_options=asdict(options), simplify=simplify)
    fingerprint = {key:value for key,value in definition.items() if key not in ('original_body_ids','simplify')}
    # Protocol configs contain source-set IDs; the cache key is this full task
    # definition plus the independently canonicalized evaluated exact set.
    definition['cache_identity'] = hashlib.sha256(json.dumps(fingerprint,sort_keys=True,
        separators=(',',':')).encode()).hexdigest()
    return definition


def preview_reduction(case, conditions, body_ids, options, *, simplify=False, extra_conditions=None):
    if type(simplify) is not bool:
        raise ValueError('simplify must be a boolean')
    view, parsed, bodies, options, decision = _prepare(case,conditions,body_ids,options,extra_conditions)
    definition = _definition(case,parsed,bodies,options,decision,simplify)
    distinct = len({_key(view['nodes'],cfg) for name,cfg in parsed if name in decision})
    initial = 1+len(bodies) if bodies else 1
    maximum = 1+len(bodies)*(len(bodies)+1)//2 if simplify else initial
    count = min(maximum, options.max_evaluations)
    return dict(definition, kind='reduction_preview', computation_node_count=len(case['nodes']),
        original_node_count=len(bodies), condition_count=len(decision), extra_condition_count=len(parsed)-len(decision),
        budget=options.max_evaluations, initial_plan_count=initial, maximum_plan_count=maximum,
        estimated_evaluations=count, estimated_baseline_simulations=distinct,
        estimated_intervention_simulations=count*len(decision), estimated_total_simulations=distinct+count*len(decision),
        estimate_policy='upper bound; cached sets and empty intervention need no perturbation propagation',
        evaluation_unit='one distinct exact set completed across every decision protocol',recording=dict(mode='none'))


def _assess(view, parsed, bodies, summaries, options, decision):
    bound = [(name,replace(cfg,intervention_ids=tuple(bodies))) for name,cfg in parsed]
    comparison = annotate_joint_evaluation(_minimal_comparison(view,bound,bodies,summaries),
        replace(options,max_nodes=max(options.max_nodes,len(bodies))), decision, allow_empty=not bodies)
    rows = comparison['joint_constraints']['condition_results']
    if len(bodies)>options.max_nodes:
        for row in rows:
            row['feasible']=False
            row['violations'].append('maximum_nodes')
    for row in rows:
        row['node_constraint']=dict(maximum=options.max_nodes,node_count=len(bodies),satisfied=len(bodies)<=options.max_nodes)
    relevant = [row for row in rows if row['name'] in decision]
    worst = None if any(row['target_loss'] is None for row in relevant) else min(row['target_loss'] for row in relevant)
    protected = [value for row in relevant for value in row['protected_losses'].values()]
    return dict(condition_results=rows, feasible=all(row['feasible'] for row in relevant),
        worst_target_loss=worst, target_loss=worst,
        mean_target_loss=None if worst is None else sum(row['target_loss'] for row in relevant)/len(relevant),
        protected_loss=None if any(value is None for value in protected) else max(protected,default=0.),
        failed_condition_names=[row['name'] for row in relevant if not row['feasible']],
        undefined_condition_names=[row['name'] for row in relevant if row['target_loss'] is None or
            any(value is None for value in row['protected_losses'].values())])


def _withdrawal(parent, child, removed, nodes):
    rows = []
    for before,after in zip(parent['condition_results'],child['condition_results']):
        difference = lambda a,b: None if a is None or b is None else b-a
        outputs = {}
        for name,metrics in before['output_metrics'].items():
            current = after['output_metrics'][name]
            outputs[name] = dict(parent=metrics,child=current,
                intervention_mean_change=current['intervention_mean']-metrics['intervention_mean'],
                intervention_sum_change=current['intervention_sum']-metrics['intervention_sum'])
        rows.append(dict(name=before['name'], evidence_classification=before['evidence_classification'],
            parent_target_loss=before['target_loss'],child_target_loss=after['target_loss'],
            target_loss_change=difference(before['target_loss'],after['target_loss']),
            protected_loss_changes={label:difference(value,after['protected_losses'][label])
                                    for label,value in before['protected_losses'].items()}, outputs=outputs,
            child_feasible=after['feasible'],violations=after['violations']))
    return dict(parent_body_ids=parent['body_ids'],removed_body_id=removed,removed_node=nodes[removed],
        child_body_ids=child['body_ids'],condition_results=rows,child_feasible=child['feasible'],
        failed_condition_names=child['failed_condition_names'],
        reference='output changes child minus parent; target/protection losses retain the same no-intervention baseline')


def analyze_reduction(case, conditions, body_ids, options, *, simplify=False, extra_conditions=None,
                      cancel=lambda:False, progress=lambda value:None):
    preview = preview_reduction(case,conditions,body_ids,options,simplify=simplify,extra_conditions=extra_conditions)
    view,parsed,bodies,options,decision = _prepare(case,conditions,body_ids,options,extra_conditions)
    report = dict(preview,kind='plan_reduction',schema_version=1,status='complete',termination_reason=None,
        entries=[],withdrawals=[],chain=[],rounds=[],original=None,final=None,evaluations=0,
        attempted_evaluations=0,cache_hits=0,baseline_reuses=0,empty_baseline_reuses=0,
        baseline_simulations=0,completed_baseline_simulations=0,intervention_simulations=0,
        completed_intervention_simulations=0,curve_baseline_simulations=0,completed_curve_baseline_simulations=0,
        curve_intervention_simulations=0,completed_curve_intervention_simulations=0,curve_requests=[],
        execution_order=[],uncompleted_sets=[],distinct_plan_count=0,error=None,
        extra_evaluation_status='not_run',extra_evaluation_policy='extra protocols are evaluated only on explicit curve/fixed-plan request; never decision or batch budget units',
        ranking='largest worst target loss, then largest mean target loss, then smallest maximum protection loss, then smallest numeric removed body ID',
        optimality='local single-member deletion only; no global minimum or uniqueness claim')
    # The logical budget is precisely decision protocols. Extra conditions are
    # retained and validated, then evaluated on explicit selected-plan requests.
    parsed=[(name,cfg) for name,cfg in parsed if name in decision]
    plans,baselines,shared,cache = {},{},{},{}
    node_map = {str(n['bodyId']):n for n in case['nodes']}
    by_id = {str(n['bodyId']):i for i,n in enumerate(case['nodes'])}
    def notify(phase, current=None, condition=None):
        progress(dict(phase=phase,evaluations=report['evaluations'],budget=report['budget'],
            current_body_ids=current,current_condition_name=condition,cache_hits=report['cache_hits'],
            baseline_simulations=report['baseline_simulations'],completed_baseline_simulations=report['completed_baseline_simulations'],
            intervention_simulations=report['intervention_simulations'],completed_intervention_simulations=report['completed_intervention_simulations']))
    def interrupted(error, phase):
        cancelled = isinstance(error,SimulationCancelled)
        report.update(status='cancelled' if cancelled else 'failed',termination_reason='cancelled' if cancelled else phase+'_failed',error=str(error))
    try:
        for name,cfg in parsed:
            if cancel(): raise SimulationCancelled('Cancelled before baseline completion')
            plans[name] = SimulationPlan(view,cfg,collect_signals=False)
            key = _key(view['nodes'],cfg)
            if key not in shared:
                report['baseline_simulations'] += 1
                notify('baseline',condition=name)
                shared[key] = simulate(view,cfg,target_indices=[],plan=plans[name],collect_curves=False,cancel=cancel)
                report['completed_baseline_simulations'] += 1
            else: report['baseline_reuses'] += 1
            baselines[name] = shared[key]
    except Exception as error:
        interrupted(error,'baseline');notify(report['status']);return report

    def evaluate(values):
        key = tuple(sorted(values,key=int))
        if key in cache:
            report['cache_hits'] += 1;return cache[key]
        if cancel():
            report.update(status='cancelled',termination_reason='cancelled');return None
        if report['evaluations'] >= report['budget']:
            report.update(status='budget_exhausted',termination_reason='evaluation_budget_reached');return None
        entry = dict(body_ids=list(key),node_count=len(key),status='not_run',condition_results=[],feasible=None,
                     worst_target_loss=None,failed_condition_names=[],unfinished_condition_names=[n for n,_ in parsed],error=None)
        report['entries'].append(entry);report['execution_order'].append(list(key));report['attempted_evaluations'] += 1
        summaries=[]
        try:
            for name,cfg in parsed:
                if cancel(): raise SimulationCancelled('Cancelled during incomplete set evaluation')
                if key:
                    report['intervention_simulations'] += 1;notify('evaluation',list(key),name)
                    stats = simulate(view,cfg,gain=cfg.gain,target_indices=[by_id[body] for body in key],
                        plan=plans[name],collect_curves=False,cancel=cancel)
                    report['completed_intervention_simulations'] += 1
                else:
                    stats=baselines[name];report['empty_baseline_reuses'] += 1
                summaries.append([dict(type=label,**observation_metrics(view['nodes'],cfg,label,baselines[name],stats)) for label in cfg.outputs])
                partial_decision=[n for n,_ in parsed[:len(summaries)] if n in decision]
                if partial_decision:
                    entry['condition_results']=_assess(view,parsed[:len(summaries)],list(key),summaries,options,partial_decision)['condition_results']
                entry['unfinished_condition_names'].remove(name)
            if cancel(): raise SimulationCancelled('Cancelled before set publication')
            entry.update(status='completed',**_assess(view,parsed,list(key),summaries,options,decision))
            report['evaluations'] += 1;cache[key]=entry;notify('evaluation_completed',list(key));return entry
        except Exception as error:
            interrupted(error,'evaluation');entry.update(status=report['status'],error=str(error),feasible=None)
            return None

    original = evaluate(bodies)
    report['original']=copy.deepcopy(original)
    current=original
    if current is not None:
        # Evaluate original withdrawals even when original constraints fail.
        first_candidates=[]
        for removed in bodies:
            child=evaluate([body for body in bodies if body!=removed])
            if child is None: break
            first_candidates.append((removed,child))
            report['withdrawals'].append(_withdrawal(original,child,removed,node_map))
        report['rounds'].append(dict(parent_body_ids=bodies,candidates=[dict(removed_body_id=b,body_ids=r['body_ids']) for b,r in first_candidates],
            unchecked_removed_body_ids=[body for body in bodies if body not in {b for b,_ in first_candidates}]))
        if report['status'] == 'complete' and simplify and not original['feasible']:
            report['termination_reason']='original_infeasible'
        elif report['status'] == 'complete' and not simplify:
            report['termination_reason']='withdrawals_completed'
        elif simplify and original['feasible'] and report['status'] not in ('failed','cancelled'):
            # Reuse the exact completed withdrawal cache when the first deletion
            # round starts; this is a cache lookup, not another budget unit.
            candidates=[(removed,evaluate(row['body_ids'])) for removed,row in first_candidates]
            while True:
                if cancel(): report.update(status='cancelled',termination_reason='cancelled');break
                feasible=[(removed,row) for removed,row in candidates if row['feasible']]
                if not feasible:
                    if report['status']=='complete': report['termination_reason']='local_irreducible' if current['body_ids'] else 'empty_set_reached'
                    break
                removed,chosen=min(feasible,key=lambda pair:(-pair[1]['worst_target_loss'],-pair[1]['mean_target_loss'],pair[1]['protected_loss'],int(pair[0])))
                report['chain'].append(dict(parent_body_ids=current['body_ids'],removed_body_id=removed,
                    child_body_ids=chosen['body_ids'],condition_results=copy.deepcopy(chosen['condition_results']),
                    accepted_reason='satisfies every decision constraint; '+report['ranking']))
                current=chosen
                if not current['body_ids']:
                    report.update(status='complete',termination_reason='empty_set_reached');break
                candidates=[];checked=[]
                for removed in current['body_ids']:
                    child=evaluate([body for body in current['body_ids'] if body!=removed])
                    if child is None:break
                    candidates.append((removed,child));checked.append(removed)
                    report['withdrawals'].append(_withdrawal(current,child,removed,node_map))
                report['rounds'].append(dict(parent_body_ids=current['body_ids'],
                    candidates=[dict(removed_body_id=b,body_ids=r['body_ids']) for b,r in candidates],
                    unchecked_removed_body_ids=[body for body in current['body_ids'] if body not in checked]))
                if report['status'] in ('cancelled','failed'):break
    report['final']=copy.deepcopy(current)
    report['uncompleted_sets']=[dict(body_ids=row['body_ids'],status=row['status'],unfinished_condition_names=row['unfinished_condition_names']) for row in report['entries'] if row['status']!='completed']
    if report['termination_reason'] is None:report['termination_reason']='empty_set_reached' if not bodies else 'withdrawals_completed'
    report['distinct_plan_count']=len(report['entries'])
    notify(report['status']);return report


def validate_reduction(case,report):
    if not isinstance(report,dict) or report.get('kind')!='plan_reduction':raise ValueError('Expected a plan reduction report')
    if any(report.get(key)!=value for key,value in _identity(case).items()):raise ValueError('Reduction scope/index/model identity does not match')
    view,parsed,bodies,options,decision=_prepare(case,report['conditions'],report['original_body_ids'],report['search_options'],report.get('extra_conditions'))
    parsed=[(name,cfg) for name,cfg in parsed if name in decision]
    entries=report.get('entries')
    if not isinstance(entries,list):raise ValueError('Reduction entries must be a list')
    seen=set();completed={}
    for entry in entries:
        ids=_ids(entry.get('body_ids'),set(bodies),'Recorded reduction set',empty=True)
        if ids!=entry['body_ids'] or tuple(ids) in seen:raise ValueError('Reduction sets must be canonical and distinct')
        seen.add(tuple(ids))
        if entry.get('status') not in ('completed','cancelled','failed','not_run'):raise ValueError('Unknown reduction entry status')
        if entry['status']=='completed':
            rows=entry.get('condition_results')
            if not isinstance(rows,list) or [row.get('name') for row in rows]!=decision:raise ValueError('Completed set lacks every exact decision protocol')
            summaries=[[dict(row['output_metrics'][label],type=label) for label in cfg.outputs] for (_,cfg),row in zip(parsed,rows)]
            actual=_assess(view,parsed,ids,summaries,options,decision)
            if any(entry.get(key)!=actual[key] for key in ('feasible','worst_target_loss','failed_condition_names')):
                raise ValueError('Recorded reduction constraints do not match its metrics')
            completed[tuple(ids)]=entry
        elif entry.get('feasible') is not None:raise ValueError('Incomplete reduction set cannot claim feasibility')
    if type(report.get('evaluations')) is not int or report['evaluations']!=len(completed) or report['evaluations']>options.max_evaluations:
        raise ValueError('Reduction evaluation count/budget does not match completed distinct sets')
    for key in ('original','final'):
        row=report.get(key)
        if row is not None and (tuple(row['body_ids']) not in completed or row!=completed[tuple(row['body_ids'])]):
            raise ValueError('Reduction selected rows must be exact completed evidence')
    parent=bodies
    for link in report.get('chain',[]):
        child=[body for body in parent if body!=link['removed_body_id']]
        if link.get('parent_body_ids')!=parent or link.get('child_body_ids')!=child or link['removed_body_id'] not in parent:
            raise ValueError('Reduction chain does not describe a single actual member withdrawal')
        before=completed.get(tuple(parent));after=completed.get(tuple(child))
        if before is None or after is None or not before['feasible'] or not after['feasible']:
            raise ValueError('Accepted deletion chain requires completed feasible parent and child')
        parent=child
    for prefix in ('baseline','intervention','curve_baseline','curve_intervention'):
        started=report.get(prefix+'_simulations',0);finished=report.get('completed_'+prefix+'_simulations',0)
        if type(started) is not int or type(finished) is not int or not 0<=finished<=started:
            raise ValueError('Reduction propagation counts must be nonnegative started/completed integers')
    return report


def reduction_conditions(case,report,body_ids):
    validate_reduction(case,report)
    available={str(n['bodyId']) for n in case['nodes']}
    bodies=_ids(body_ids,available,'Evaluated reduction plan',empty=True)
    if not any(row['status']=='completed' and row['body_ids']==bodies for row in report['entries']):
        raise ValueError('Choose an actually completed exact reduction set')
    view,parsed,_,options,decision=_prepare(case,report['conditions'],report['original_body_ids'],report['search_options'],report.get('extra_conditions'))
    if bodies:
        from .scope_comparison import _bound_case
        view,_=_bound_case(view,replace(parsed[0][1],intervention_ids=tuple(bodies)))
    fixed=[]
    for name,cfg in parsed:
        exact=FixedExperiment.from_dict(asdict(cfg));exact.intervention_group='__all__' if bodies else '__fixed_no_intervention__';exact.intervention_ids=tuple(bodies)
        fixed.append(dict(name=name,experiment=exact))
    return view,fixed,options,decision,bodies


def reduction_plan_curves(case,report,body_ids,*,include_original=False,cancel=lambda:False):
    view,fixed,options,decision,bodies=reduction_conditions(case,report,body_ids)
    if type(include_original) is not bool:raise ValueError('include_original must be a boolean')
    groups=[dict(label='selected',bodies=bodies,decision=decision,conditions=fixed)]
    if include_original and bodies!=report['original_body_ids']:
        _,original,_,original_decision,original_bodies=reduction_conditions(case,report,report['original_body_ids'])
        # Bind the union for exact-membership validation; propagation matrix is unchanged.
        from .scope_comparison import _bound_case
        view,_=_bound_case(view,replace(original[0]['experiment'],intervention_ids=tuple(original_bodies)))
        groups.insert(0,dict(label='original',bodies=original_bodies,decision=original_decision,conditions=original))
        if sum(len(group['conditions']) for group in groups)>12:
            raise ValueError('Original plus selected curve comparison exceeds 12 conditions; view them separately')
        fixed=[]
        for group in groups:
            renames={item['name']:group['label']+' · '+item['name'] for item in group['conditions']}
            group['decision']=[renames[name] for name in group['decision']]
            group['conditions']=[dict(item,name=renames[item['name']]) for item in group['conditions']]
            fixed.extend(group['conditions'])
    def count(value):
        key=('curve_' if value['status']=='started' else 'completed_curve_')+value['kind']+'_simulations'
        report[key]=report.get(key,0)+1
    comparison=compare_conditions(view,fixed,cancel=cancel,simulation_progress=count)
    if len(groups)==1:
        comparison=annotate_joint_evaluation(comparison,replace(options,max_nodes=max(options.max_nodes,len(bodies))),decision,allow_empty=not bodies)
        assessment=_assess(view,[(item['name'],item['experiment']) for item in fixed],bodies,
            [result['summary'] for result in comparison['results']],options,decision)
        comparison['joint_constraints'].update(assessment)
        for row,metrics in zip(comparison['rows'],assessment['condition_results']):row['constraints']=metrics
    else:
        offset=0;assessments=[]
        for group in groups:
            count_conditions=len(group['conditions']);subset=dict(comparison,
                conditions=comparison['conditions'][offset:offset+count_conditions],rows=comparison['rows'][offset:offset+count_conditions],
                results=comparison['results'][offset:offset+count_conditions])
            assessed=annotate_joint_evaluation(subset,replace(options,max_nodes=max(options.max_nodes,len(group['bodies']))),group['decision'],allow_empty=not group['bodies'])
            assessment=_assess(view,[(item['name'],item['experiment']) for item in group['conditions']],group['bodies'],
                [result['summary'] for result in subset['results']],options,group['decision'])
            assessed['joint_constraints'].update(assessment)
            for row,metrics in zip(subset['rows'],assessment['condition_results']):row['constraints']=metrics
            assessments.append(dict(label=group['label'],body_ids=group['bodies'],constraints=assessed['joint_constraints']))
            offset+=count_conditions
        comparison['reduction_plan_assessments']=assessments
    comparison['reduction_evaluation']=dict(body_ids=bodies,original_body_ids=report['original_body_ids'],
        cache_identity=report['cache_identity'],search_options=asdict(options),condition_names=decision,include_original=include_original)
    report['curve_requests'].append(dict(body_ids=bodies,include_original=include_original))
    if report['extra_conditions']:report['extra_evaluation_status']='selected_plan_curves_completed'
    comparison['reduction_simulation_counts']={key:report[key] for key in report if 'curve_' in key and key.endswith('_simulations')}
    return comparison


def save_reduction(root,report):
    if report.get('kind')!='plan_reduction':raise ValueError('Expected a plan reduction report')
    folder=Path(root)/('plan-reduction-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8]);folder.mkdir(parents=True)
    config={key:report[key] for key in ('case_id','source_index_id','model_version','computation_node_ids_hash',
        'conditions','extra_conditions','search_options','original_body_ids','simplify')}
    for filename,value in [('plan-reduction.json',report),('config.json',config)]:
        (folder/filename).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return folder


def load_reduction(path,case):
    path=Path(path)
    if path.is_dir():path=path/'plan-reduction.json'
    return validate_reduction(case,json.loads(path.read_text(encoding='utf-8')))
