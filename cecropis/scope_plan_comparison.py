"""A bounded scope × fixed-plan schedule using the existing scope executor."""
import copy
import hashlib
import json
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from . import MODEL_VERSION
from .case import close_case, load_case
from .plan_reduction import FixedExperiment, _assess, reduction_conditions
from .scope_comparison import _canonical_ids, _request, compare_scopes, preview_scopes, discard_recordings
from .search import SearchOptions
from .scope_boundary import input_coverage
from .simulation import RecordPolicy


def _normalize(config):
    required = {'case_id', 'source_index_id', 'model_version', 'cases', 'experiment', 'plans', 'recording', 'max_tasks'}
    if not isinstance(config, dict) or not required <= set(config) or set(config)-required-{'search_options','source'}:
        raise ValueError('Fixed scope plans require explicit scope, protocol, plans, recording and task budget')
    request = copy.deepcopy(config)
    if request.get('source') is not None and not isinstance(request['source'],dict):
        raise ValueError('Source provenance must be an object')
    if 'condition_name' in (request.get('source') or {}) and (not isinstance(request['source']['condition_name'],str) or not request['source']['condition_name'].strip()):
        raise ValueError('Source condition_name must be nonempty')
    if not isinstance(request['case_id'], str) or not request['case_id']:
        raise ValueError('Source case_id is required')
    if not isinstance(request['plans'], list) or not 1 <= len(request['plans']) <= 2:
        raise ValueError('Choose one or at most two exact fixed plans')
    names, sets = set(), set()
    for plan in request['plans']:
        if not isinstance(plan, dict) or set(plan) != {'plan_id','label','body_ids'}:
            raise ValueError('Each fixed plan requires plan_id, label and exact body_ids')
        if any(not isinstance(plan[key], str) or not plan[key].strip() or len(plan[key])>80 for key in ('plan_id','label')) or plan['plan_id'] in names:
            raise ValueError('Plan identities must be distinct nonempty strings (maximum 80 characters)')
        ids = sorted(_canonical_ids(plan['body_ids'], 'plan.body_ids', allow_empty=True), key=int)
        if tuple(ids) in sets:
            raise ValueError('Identical fixed sets must be represented by one plan')
        names.add(plan['plan_id']);sets.add(tuple(ids));plan['body_ids']=ids
    if type(request['max_tasks']) is not int or not 1 <= request['max_tasks'] <= 24:
        raise ValueError('max_tasks must be an integer in 1..24')
    policy=RecordPolicy.from_dict(request['recording'])
    request['recording']=json.loads(json.dumps(asdict(policy)))
    # Parsing is shared with legacy scope comparison; role membership is bound
    # later separately in each saved scope, never by node-array position.
    experiment = copy.deepcopy(request['experiment'])
    if not isinstance(experiment,dict) or experiment.get('input_events') is None or experiment.get('observations') is None:
        raise ValueError('Fixed scope plans require explicit input events and observations')
    cfg=FixedExperiment.from_dict(experiment)
    from .interventions import require_legacy_intervention
    require_legacy_intervention(cfg, 'Scope node-plan comparison')
    cfg.intervention_ids=tuple(request['plans'][0]['body_ids'])
    if not cfg.intervention_ids:cfg.intervention_group='__fixed_no_intervention__'
    request['experiment']=json.loads(json.dumps(asdict(cfg)))
    raw_options=request.get('search_options')
    if raw_options is not None:
        if not raw_options.get('target_output') or raw_options.get('protected_limits') is None:
            raise ValueError('Preserved constraints require explicit target and protection requirements')
        options=SearchOptions.from_dict(raw_options);options.resolve(cfg)
        request['search_options']=asdict(options)
    else:request['search_options']=None
    _request(_single_config(request,request['plans'][0]),allow_empty=True)
    return request


def _single_config(request, plan, cases=None):
    cfg=copy.deepcopy(request['experiment']);cfg['intervention_ids']=list(plan['body_ids'])
    if not plan['body_ids']:cfg['intervention_group']='__fixed_no_intervention__'
    return dict(model_version=request['model_version'],source_index_id=request['source_index_id'],
        cases=copy.deepcopy(request['cases'] if cases is None else cases),experiment=cfg,recording=copy.deepcopy(request['recording']))


def resolve_reduction_scope_request(case, report, cases, body_ids, condition_name, *, include_original=True, recording=None, max_tasks=None):
    """Freeze one actually evaluated protocol/set without modifying its report."""
    if type(include_original) is not bool:raise ValueError('include_original must be boolean')
    _, fixed, options, decision, bodies=reduction_conditions(case,report,body_ids)
    if condition_name not in decision:
        raise ValueError('Choose a recorded decision protocol; extra conditions are not decision evidence')
    matching=next(item for item in fixed if item['name']==condition_name)
    plans=[]
    if include_original and bodies!=report['original_body_ids']:
        reduction_conditions(case,report,report['original_body_ids'])
        plans.append(dict(plan_id='original',label='原方案',body_ids=list(report['original_body_ids'])))
    plans.append(dict(plan_id='selected',label='所选方案',body_ids=list(bodies)))
    return _normalize(dict(case_id=case['manifest']['case_id'],source_index_id=report['source_index_id'],
        model_version=MODEL_VERSION,cases=cases,experiment=asdict(matching['experiment']),plans=plans,
        search_options=asdict(options),recording=recording if recording is not None else dict(mode='none'),
        max_tasks=len(cases)*len(plans) if max_tasks is None else max_tasks,
        source=dict(kind='plan_reduction',case_id=report['case_id'],cache_identity=report['cache_identity'],condition_name=condition_name)))


def preview_scope_plans(config):
    request=_normalize(config)
    previews=[]
    for plan in request['plans']:
        previews.append(dict(plan_id=plan['plan_id'],**preview_scopes(_single_config(request,plan),_allow_empty=True)))
    # Canonical paths are available even for incompatible records.
    request['cases']=[dict(item,case_path=str(Path(item['case_path']).resolve())) for item in request['cases']]
    count=len(request['cases'])*len(request['plans']);scheduled=min(count,request['max_tasks'])
    sizes=[p['recording_total_bytes'] for p in previews]
    return dict(kind='scope_plan_preview',config=request,compatible=all(p['compatible'] for p in previews),
        cases=previews[0]['cases'],plans=previews,errors=[f"{p['plan_id']}: {error}" for p in previews for error in p['errors']],
        logical_task_count=count,scheduled_tasks=scheduled,budget=request['max_tasks'],
        estimated_baseline_simulations=scheduled,estimated_intervention_simulations=scheduled,
        estimated_total_simulations=2*scheduled,baseline_reuse_policy='none; each fixed plan uses its own same-scope baseline',
        recording_total_bytes=sum(sizes),recording_peak_bytes=max((p['recording_peak_bytes'] for p in previews),default=0),
        execution_policy='saved scope order, then fixed plan order; sequential; no optimization')


def compare_scope_plans(config, *, cancel=lambda:False, progress=lambda value:None):
    preview=preview_scope_plans(config);request=preview['config']
    if not preview['compatible']:raise ValueError('Incompatible calculation scopes: '+'; '.join(preview['errors']))
    tasks=[]
    for scope in preview['cases']:
        for plan in request['plans']:
            key=hashlib.sha256((scope['case_id']+'\0'+plan['plan_id']).encode()).hexdigest()[:16]
            tasks.append(dict(scope,task_id='scope-plan-'+key,plan_id=plan['plan_id'],label=plan['label'],body_ids=plan['body_ids'],
                status='not_run',result=None,constraints=None,observation_coverage=None,error=None))
    result=dict(kind='scope_plan_comparison',schema_version=1,config=request,status='complete',tasks=tasks,
        logical_started=0,logical_completed=0,logical_task_count=len(tasks),budget=request['max_tasks'],
        baseline_simulations=0,completed_baseline_simulations=0,intervention_simulations=0,completed_intervention_simulations=0,
        baseline_reuses=0,cache_hits=0,execution_order=[],recording_files={},
        recording_total_bytes=preview['recording_total_bytes'],recording_peak_bytes=preview['recording_peak_bytes'])
    def notify():
        progress({key:result[key] for key in ('status','logical_started','logical_completed','logical_task_count','budget',
            'baseline_simulations','completed_baseline_simulations','intervention_simulations','completed_intervention_simulations')})
    for task in tasks:
        if cancel():result['status']='cancelled';break
        if result['logical_completed']>=result['budget']:result['status']='budget_exhausted';break
        plan=next(p for p in request['plans'] if p['plan_id']==task['plan_id'])
        result['logical_started']+=1;result['execution_order'].append(task['task_id']);notify()
        def physical(value):
            key=('completed_' if value['status']=='completed' else '')+value['kind']+'_simulations'
            result[key]+=1
            progress(dict(task_id=task['task_id'],case_id=task['case_id'],plan_id=task['plan_id'],**value,
                logical_completed=result['logical_completed'],budget=result['budget']))
        try:
            single=compare_scopes(_single_config(request,plan,[dict(case_id=task['case_id'],case_path=task['case_path'])]),
                _allow_single=True,_allow_empty=True,cancel=cancel,simulation_progress=physical)
        except Exception as error:
            task.update(status='failed',error=str(error));result['status']='failed';break
        row=single['scopes'][0]
        task.update(status=row['status'],result=row['result'],error=row['error'])
        if task['status']=='completed':
            case=None
            try:
                case=load_case(task['case_path'])
                cfg=FixedExperiment.from_dict(task['result']['config']['experiment'])
                task['observation_coverage']=[group for group in input_coverage(case,cfg)['groups']
                    if group['role']=='observation']
                if request['search_options'] is not None:
                    name=(request.get('source') or {}).get('condition_name','固定协议')
                    task['constraints']=_assess(case,[(name,cfg)],plan['body_ids'],[task['result']['summary']],
                        SearchOptions.from_dict(request['search_options']),[name])
                source=single['recording_files'].get(task['case_id'])
                if source:result['recording_files'][task['task_id']]=source
                result['logical_completed']+=1
            except Exception as error:
                task.update(status='failed',result=None,constraints=None,error=str(error));result['status']='failed'
                discard_recordings(single)
            finally:
                if case is not None:close_case(case)
        elif task['status']=='not_run':
            # Cancellation between scheduling and the existing executor.
            task['status']='cancelled';result['status']='cancelled'
        if task['status']!='completed':
            result['status']='cancelled' if task['status']=='cancelled' else 'failed';break
        notify()
    result['termination_reason']=dict(complete='all_fixed_tasks_completed',budget_exhausted='logical_task_budget_reached',
        cancelled='user_cancelled',failed='execution_failed')[result['status']]
    notify();return result


def _validate_report(report):
    if not isinstance(report,dict) or report.get('kind')!='scope_plan_comparison' or report.get('schema_version')!=1:
        raise ValueError('Expected a saved fixed scope-plan comparison')
    request=_normalize(report['config'])
    if report.get('status') not in ('complete','budget_exhausted','cancelled','failed'):raise ValueError('Invalid comparison status')
    expected=[(case,plan) for case in request['cases'] for plan in request['plans']]
    if len(report.get('tasks',[]))!=len(expected):raise ValueError('Saved task schedule does not match scopes and plans')
    completed=0;started=[]
    for task,(scope,plan) in zip(report['tasks'],expected):
        key='scope-plan-'+hashlib.sha256((scope['case_id']+'\0'+plan['plan_id']).encode()).hexdigest()[:16]
        if any(task.get(name)!=value for name,value in dict(case_id=scope['case_id'],case_path=scope['case_path'],plan_id=plan['plan_id'],body_ids=plan['body_ids'],task_id=key).items()):
            raise ValueError('Saved task identity/set does not match the fixed schedule')
        if task.get('status') not in ('completed','cancelled','failed','not_run'):raise ValueError('Invalid saved task status')
        if task['status']!='not_run':started.append(task['task_id'])
        if task['status']=='completed':
            completed+=1;actual=task.get('result')
            expected_cfg=json.loads(json.dumps(asdict(FixedExperiment.from_dict(_single_config(request,plan)['experiment']))))
            if not actual or actual.get('config',{}).get('case_id')!=scope['case_id'] or actual['config'].get('model_version')!=request['model_version'] or actual['config'].get('experiment')!=expected_cfg:
                raise ValueError('Completed task must retain its exact scope and fixed protocol')
            if set(actual.get('series',{}))!={item['name'] for item in request['experiment']['observations']}:
                raise ValueError('Completed task observations do not match its protocol')
            if actual.get('intervention_body_ids')!=plan['body_ids']:
                # The numerical core lists targets in scope-array order.
                if sorted(actual.get('intervention_body_ids',[]),key=int)!=plan['body_ids']:
                    raise ValueError('Completed task intervention IDs do not match its fixed set')
            cfg=FixedExperiment.from_dict(expected_cfg)
            if request['search_options'] is not None:
                name=(request.get('source') or {}).get('condition_name','固定协议')
                # Exact protocol readouts are enough for a read-only constraint
                # check; this synthetic view supplies identity, never dynamics.
                view=dict(nodes=[],manifest=dict(case_id=scope['case_id']))
                actual_constraints=_assess(view,[(name,cfg)],plan['body_ids'],[actual['summary']],
                    SearchOptions.from_dict(request['search_options']),[name])
                if task.get('constraints')!=actual_constraints:
                    raise ValueError('Saved constraints do not match the completed task metrics')
            elif task.get('constraints') is not None:
                raise ValueError('A task without explicit requirements cannot claim constraint status')
        elif task.get('result') is not None or task.get('constraints') is not None:
            raise ValueError('Incomplete tasks cannot have completed metrics or constraints')
    if report.get('logical_completed')!=completed or completed>request['max_tasks'] or report.get('logical_started')!=len(report.get('execution_order',[])):
        raise ValueError('Saved logical task counts are inconsistent')
    if report['execution_order']!=started:raise ValueError('Saved execution order does not match attempted tasks')
    if report['status']=='complete' and completed!=len(expected):raise ValueError('Partial schedule cannot claim a complete comparison')
    for prefix in ('baseline','intervention'):
        a=report.get(prefix+'_simulations');b=report.get('completed_'+prefix+'_simulations')
        if type(a) is not int or type(b) is not int or not 0<=b<=a:raise ValueError('Saved physical propagation counts are inconsistent')
    return report


def save_scope_plan_comparison(root, result):
    _validate_report(result)
    folder=Path(root)/('scope-plan-comparison-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8])
    folder.mkdir(parents=True)
    clean=copy.deepcopy({key:value for key,value in result.items() if key!='recording_files'})
    try:
        for index,task in enumerate(clean['tasks']):
            if task['status']!='completed':continue
            if (task['result'].get('recording_metadata') or {}).get('mode','none')=='none':continue
            source=result.get('recording_files',{}).get(task['task_id'])
            if source is None:raise ValueError('Recorded trajectories are unavailable; retain the saved artifact or rerun explicitly')
            destination=folder/f'task-{index:02d}'/'states.npz';destination.parent.mkdir();shutil.copyfile(source,destination)
            task['recording_file']=destination.relative_to(folder).as_posix()
        for filename,value in [('config.json',clean['config']),('scope-plan-comparison.json',clean)]:
            (folder/filename).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    except Exception:
        # A failed write is not a usable result; remove only this new folder.
        if folder.resolve().parent != Path(root).resolve():
            raise ValueError('Refusing to remove an artifact outside the requested result root')
        shutil.rmtree(folder);raise
    return folder


def load_scope_plan_comparison(path):
    path=Path(path);file=path/'scope-plan-comparison.json' if path.is_dir() else path
    report=_validate_report(json.loads(file.read_text(encoding='utf-8-sig')))
    report['recording_files']={}
    for task in report['tasks']:
        relative=task.get('recording_file')
        if relative:
            target=(file.parent/relative).resolve()
            if not target.is_relative_to(file.parent.resolve()):raise ValueError('Recording reference escapes saved artifact')
            if target.is_file():report['recording_files'][task['task_id']]=str(target)
    return report


def scope_plan_source(report, task_id):
    """Return one completed canonical comparison; no loading graph or propagation."""
    _validate_report(report)
    task=next((item for item in report['tasks'] if item['task_id']==task_id),None)
    if task is None or task['status']!='completed':raise ValueError('Choose an actually completed fixed scope-plan task')
    source=copy.deepcopy(task['result'])
    source.update(source_index_id=report['config']['source_index_id'],
        data_scope=dict(case_id=task['case_id'],source_index_id=report['config']['source_index_id']),
        scope_plan_reference=dict(task_id=task_id,plan_id=task['plan_id'],body_ids=task['body_ids']),
        search_options=copy.deepcopy(report['config'].get('search_options')))
    if not task['body_ids']:source['fixed_no_intervention']=True
    return source
