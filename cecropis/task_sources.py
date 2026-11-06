"""Export only explicitly selected fixed conditions from trusted saved results."""
import copy
from dataclasses import asdict


def export_saved_task(case, source, name, request=None, description=''):
    """Share source resolution between HTTP and CLI; never prepare or propagate."""
    from .task_definition import export_task
    from .replay import _resolve_source
    if not isinstance(source, dict):
        raise ValueError('Task export needs a saved result')
    request = {} if request is None else copy.deepcopy(request)
    if not isinstance(request, dict):
        raise ValueError('Task export request must be an object')
    if set(request)-{'task_id','conditions','condition_names','condition_name','body_ids',
                     'plan_body_ids','start','duration','name','role'}:
        raise ValueError('Unknown task export selection fields')
    selected_source = source
    if source.get('kind') == 'scope_plan_comparison':
        from .scope_plan_comparison import scope_plan_source
        if not request.get('task_id'):
            raise ValueError('Task export needs an explicitly selected completed task_id')
        selected_source = scope_plan_source(source, request['task_id'])
    kind = selected_source.get('kind', 'comparison')
    is_comparison = 'conditions' in selected_source and 'results' in selected_source
    if 'conditions' in request:
        selections = request.pop('conditions')
        if not isinstance(selections, list) or not selections or any(not isinstance(item, dict) for item in selections):
            raise ValueError('Task export request.conditions must list exact fixed selections')
        if set(request) - {'task_id'}:
            raise ValueError('Task export selections cannot be mixed with other selection fields')
    elif 'condition_names' in request:
        if not is_comparison or set(request) - {'condition_names', 'task_id'}:
            raise ValueError('condition_names selects saved comparison conditions only')
        names = request['condition_names']
        if not isinstance(names, list) or not names or len(set(names)) != len(names):
            raise ValueError('Task export condition_names must be nonempty and unique')
        selections = [dict(condition_name=value) for value in names]
    elif is_comparison and not any(key in request for key in ('condition_name', 'body_ids', 'plan_body_ids')):
        selections = [dict(condition_name=item['name']) for item in selected_source['conditions']]
    else:
        selections = [request]
    single_search = 'evaluated' in selected_source and 'conditions' not in selected_source and 'experiment' in selected_source
    options = (selected_source.get('search_options') or selected_source.get('options')
        or selected_source.get('reduction_evaluation', {}).get('search_options')
        or selected_source.get('timing_evaluation', {}).get('search_options')
        or selected_source.get('config', {}).get('search_options')
        or selected_source.get('config', {}).get('joint_evaluation', {}).get('search_options'))
    decisions = selected_source.get('joint_constraints', {}).get('search_condition_names')
    if decisions is None:
        decisions = selected_source.get('operation_search_evaluation',{}).get('decision_condition_names')
    assessments = selected_source.get('reduction_plan_assessments')
    if decisions is None and isinstance(assessments,list):
        decisions = [condition for item in assessments
                     for condition in item.get('constraints',{}).get('search_condition_names',[])]
    if decisions is None:
        decisions = selected_source.get('reduction_evaluation', {}).get('condition_names')
    if decisions is None and kind in ('joint_search', 'plan_reduction', 'timing_exploration'):
        decisions = [item['name'] for item in selected_source.get('conditions', [])]
    original_task = selected_source.get('task_definition', {})
    original_conditions = {item['name']: item for item in original_task.get('conditions', [])}
    conditions = []
    for raw in selections:
        selection = copy.deepcopy(raw)
        output_name = selection.pop('name', None)
        role = selection.pop('role', None)
        if set(selection)-{'task_id','condition_name','body_ids','plan_body_ids','start','duration'}:
            raise ValueError('Unknown fixed-condition selection fields')
        if (single_search or kind in ('search', 'joint_search', 'plan_reduction')) and not any(
                field in selection for field in ('body_ids', 'plan_body_ids')):
            raise ValueError('Task export requires an explicitly selected evaluated body_ids set')
        if kind == 'timing_exploration' and not all(field in selection for field in ('start', 'duration')):
            raise ValueError('Task export requires an explicitly selected evaluated start and duration')
        if request.get('task_id'):
            selection['task_id'] = request['task_id']
        if single_search:
            from .analysis_sessions import _source_definition
            from .replay import _check_source_identity
            _check_source_identity(case,selected_source)
            _, experiment, chosen, _, resolved = _source_definition(case,selected_source,selection)
        else:
            _, experiment, chosen, _, resolved = _resolve_source(case, selected_source, selection)
        condition_name = resolved.get('condition_name') or '固定方案'
        saved = original_conditions.get(condition_name, {})
        condition = dict(name=output_name or condition_name, experiment=asdict(experiment),
            role=role or saved.get('role') or ('extra' if decisions is not None and condition_name not in decisions else 'decision'),
            recording=copy.deepcopy(saved.get('recording') or chosen.get('config',{}).get('recording')
                or selected_source.get('config', {}).get('recording') or dict(mode='none')))
        condition_options = saved.get('search_options', options)
        if condition_options is not None:
            condition['search_options'] = copy.deepcopy(condition_options)
        conditions.append(condition)
    return export_task(case, conditions, name, description or f'Fixed conditions from {kind}')
