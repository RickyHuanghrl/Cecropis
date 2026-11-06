"""Portable, declarative fixed-condition tasks over one exact indexed scope."""
import copy
import hashlib
import json
import shutil
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

import numpy as np

from . import MODEL_VERSION
from .scope_content import content_identity, compare_identity, validate_identity, source_data, INTERPRETATION
from .case import load_case, close_case
from .plan_reduction import FixedExperiment, _assess
from .search import SearchOptions
from .selection import canonical_ids, induced_stats, write_selected_case
from .scope_expansion import _estimates
from .simulation import (Experiment, RecordPolicy, SimulationCancelled, compare,
                         effective_input_events, effective_observations, intervention_indices,
                         protocol_key)

_TOP = {'kind', 'schema_version', 'name', 'description', 'source_index_id',
        'model_version', 'scope', 'conditions', 'scope_content', 'source_data'}
_REQUIRED_EXPERIMENT = {'steps', 'alpha', 'rho', 'input_events', 'observations',
                        'intervention_ids', 'gain', 'intervention_start', 'intervention_stop'}
_BUDGETS = dict(scan_limit=5000000, max_internal_edges=5000000,
                max_nodes=200000, max_bytes=512*1024**2, max_disk_bytes=1024**3)


def _json(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _view_nodes(nodes):
    # This only binds operation eligibility, never changes matrix membership.
    return [dict(node, memberships=dict(node.get('memberships', {}),
                                      internal=['__portable_task__'])) for node in nodes]


def _cfg(raw, nodes):
    values = asdict(raw) if isinstance(raw, Experiment) else copy.deepcopy(raw)
    if not isinstance(values, dict):
        raise ValueError('experiment must be an object')
    if values.get('intervention_events') is not None:
        cfg = Experiment.from_dict(values)
    elif values.get('intervention_ids') == [] or values.get('intervention_ids') == ():
        cfg = FixedExperiment.from_dict(values)
    else:
        cfg = Experiment.from_dict(values)
    if cfg.intervention_events is None:
        cfg.intervention_group = '__fixed_no_intervention__' if cfg.intervention_ids == () or cfg.intervention_ids == [] else '__portable_task__'
    cfg.validate(_view_nodes(nodes))
    return cfg


def _validate_plan_edges(case, definition):
    from .interventions import preview_interventions
    for item in definition['conditions']:
        if item['experiment'].get('intervention_events') is not None:
            preview_interventions(case,_cfg(item['experiment'],case['nodes']))


def normalize_task(definition):
    """Parse and validate declarations only; no files, index or propagation."""
    if not isinstance(definition, dict) or set(definition)-_TOP:
        raise ValueError('Unrecognized task fields')
    value = _json(definition)
    if value.get('kind') != 'portable_task' or type(value.get('schema_version')) is not int or value['schema_version'] not in (1,2):
        raise ValueError('Task requires kind=portable_task and schema_version=1 or 2')
    if value['schema_version']==2:
        validate_identity(value.get('scope_content'))
        data=value.get('source_data')
        if not isinstance(data,dict) or set(data)!={'dataset_version','record_interpretation'} or not isinstance(data['dataset_version'],str) or data['record_interpretation']!=INTERPRETATION:
            raise ValueError('Task source_data interpretation is unsupported')
    elif 'scope_content' in value or 'source_data' in value:
        raise ValueError('Legacy tasks cannot declare version-2 content fields')
    for key, maximum in [('name', 100), ('source_index_id', 256), ('model_version', 256)]:
        if not isinstance(value.get(key), str) or not value[key].strip() or len(value[key]) > maximum:
            raise ValueError(f'{key} requires a nonempty string of at most {maximum} characters')
    description = value.setdefault('description', '')
    if not isinstance(description, str) or len(description) > 2000:
        raise ValueError('description must be at most 2000 characters')
    scope = value.get('scope')
    if not isinstance(scope, dict) or set(scope)-{'body_ids', 'selection_description'} or 'body_ids' not in scope:
        raise ValueError('scope requires exact body_ids; only selection_description is optional')
    scope['body_ids'] = canonical_ids(scope['body_ids'])
    if len(scope['body_ids']) > 200000:
        raise ValueError('scope.body_ids exceeds 200000 members')
    if 'selection_description' in scope and (not isinstance(scope['selection_description'], str) or len(scope['selection_description']) > 2000):
        raise ValueError('scope.selection_description must be text of at most 2000 characters')
    # Annotation-free operation metadata checks membership without loading a graph.
    nodes = [dict(bodyId=body, memberships={'internal':['__portable_task__']}) for body in scope['body_ids']]
    conditions = value.get('conditions')
    if not isinstance(conditions, list) or not 1 <= len(conditions) <= 12:
        raise ValueError('conditions requires 1..12 fixed conditions')
    names = set(); reference = None
    for index, item in enumerate(conditions):
        prefix = f'conditions[{index}]'
        try:
            if not isinstance(item, dict) or set(item)-{'name','role','experiment','recording','search_options'} or not {'name','experiment'} <= set(item):
                raise ValueError('requires name, experiment and optional role, recording, search_options')
            name = item['name']
            if not isinstance(name, str) or not name.strip() or len(name) > 80 or name in names:
                raise ValueError('name must be unique nonempty text of at most 80 characters')
            names.add(name)
            if item.setdefault('role','decision') not in ('decision','extra'):
                raise ValueError('role must be decision or extra')
            raw = item['experiment']
            event_plan = isinstance(raw, dict) and raw.get('intervention_events') is not None
            required = _REQUIRED_EXPERIMENT if not event_plan else {'steps','alpha','rho','input_events','observations','intervention_events','intervention_semantics_version'}
            if not isinstance(raw, dict) or not required <= set(raw):
                raise ValueError('experiment must explicitly define model, input_events, observations and a versioned intervention plan or legacy members/gain/interval')
            if raw['input_events'] is None or raw['observations'] is None or (not event_plan and raw['intervention_ids'] is None):
                raise ValueError('events, observations and intervention members must be explicit (empty intervention means no intervention)')
            if not event_plan and raw['intervention_ids']:
                raw['intervention_ids'] = canonical_ids(raw['intervention_ids'])
            elif not event_plan and not isinstance(raw['intervention_ids'], list):
                raise ValueError('intervention_ids must be a list')
            cfg = _cfg(raw, nodes)
            cfg.input_events = tuple(effective_input_events(nodes, cfg))
            cfg.observations = tuple(effective_observations(nodes, cfg))
            item['experiment'] = _json(asdict(cfg))
            recording = RecordPolicy.from_dict(item.get('recording', dict(mode='none')))
            recording.resolve(dict(nodes=nodes), cfg, branch_count=2)
            item['recording'] = _json(asdict(recording))
            if item.get('search_options') is not None:
                options = SearchOptions.from_dict(item['search_options'], legacy=True)
                options.resolve(cfg)
                item['search_options'] = _json(asdict(options))
            else:
                item['search_options'] = None
            comparable = dict(steps=cfg.steps, alpha=cfg.alpha, rho=cfg.rho,
                              observations=protocol_key(nodes,cfg)['observations'])
            if reference is not None and comparable != reference:
                raise ValueError('fixed comparison conditions must share steps, model parameters, exact observations and evaluation windows')
            reference = comparable
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError(prefix+': '+str(error)) from error
    return value


def export_task(case, conditions, name, description=''):
    """Resolve legacy roles to exact IDs, discarding machine-local references."""
    prepared = []
    for item in conditions:
        raw = item['experiment']
        cfg = raw if isinstance(raw, Experiment) else (
            FixedExperiment.from_dict(raw) if raw.get('intervention_ids') == [] else Experiment.from_dict(raw))
        if cfg.intervention_events is not None:
            cfg = _cfg(cfg,case['nodes'])
            from .interventions import preview_interventions
            preview_interventions(case,cfg)
            bodies = []
        elif cfg.intervention_ids is not None:
            cfg = _cfg(cfg,case['nodes'])
            bodies = list(cfg.intervention_ids)
        else:
            cfg.validate(case['nodes'])
            bodies = [str(case['nodes'][i]['bodyId']) for i in intervention_indices(case['nodes'],cfg)]
        values = asdict(cfg)
        values.update(input_events=effective_input_events(case['nodes'],cfg),
                      observations=effective_observations(case['nodes'],cfg))
        if cfg.intervention_events is None:
            values.update(intervention_ids=bodies,intervention_group='__portable_task__')
        prepared.append(dict(name=item['name'], role=item.get('role','decision'),
                             experiment=values, recording=item.get('recording',dict(mode='none')),
                             search_options=item.get('search_options')))
    identity = case['manifest'].get('source_index_id')
    if not identity:
        raise ValueError('The source scope has no confirmed source_index_id; portable data identity cannot be inferred from its name')
    return normalize_task(dict(kind='portable_task', schema_version=2, name=name,
        description=description, source_index_id=identity, model_version=MODEL_VERSION,
        scope=dict(body_ids=[str(node['bodyId']) for node in case['nodes']]), conditions=prepared,
        scope_content=content_identity(case), source_data=source_data(case['manifest'])))


def _verification_path(case_path, definition):
    return Path(case_path)/('.portable-content-'+definition['scope_content']['digest']+'.json')


def _verified(case_path, manifest, definition):
    if definition['schema_version']!=2:return False
    try:
        record=json.loads(_verification_path(case_path,definition).read_text(encoding='utf-8'))
        return (record['local_case_id']==manifest['case_id'] and
                record['local_index_id']==manifest['source_index_id'] and
                record['content_digest']==definition['scope_content']['digest'])
    except (OSError,ValueError,KeyError):return False


def _verify_case(case, definition, *, cancel=lambda:False, progress=lambda value:None):
    actual=content_identity(case,cancel=cancel,progress=progress)
    match=compare_identity(definition['scope_content'],actual)
    if not match['matched']:
        raise ValueError('Task scope content mismatch: '+', '.join(match['mismatch_categories']))
    return actual,match


def _save_verification(path, case, definition, actual, match):
    record=dict(local_case_id=case['manifest']['case_id'],local_index_id=case['manifest']['source_index_id'],
                source_index_id=definition['source_index_id'],content_digest=actual['digest'],
                annotation_difference=match['annotation_difference'])
    target=_verification_path(path,definition)
    pending=target.with_suffix('.pending-'+uuid4().hex)
    pending.write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8')
    pending.replace(target)
    return record


def validate_task_case(case, definition, case_path=None, *, cancel=lambda:False, progress=lambda value:None):
    """Local instance ownership stays local; version 2 binds exact numerical content."""
    definition=normalize_task(definition);manifest=case['manifest']
    if (definition['model_version']!=MODEL_VERSION or
            manifest.get('model_version',MODEL_VERSION)!=definition['model_version']):
        raise ValueError('Task model identity does not match prepared scope')
    if canonical_ids([str(node['bodyId']) for node in case['nodes']])!=definition['scope']['body_ids']:
        raise ValueError('Task exact members do not match the active scope')
    cross=manifest.get('source_index_id')!=definition['source_index_id']
    if cross and (definition['schema_version']==1 or case_path is None or not _verified(case_path,manifest,definition)):
        raise ValueError('Task data identity differs; explicitly task-prepare to verify the scope content first')
    if definition['schema_version']==2:
        case['_verified_scope_content']=_verify_case(case,definition,cancel=cancel,progress=progress)[0]
    _validate_plan_edges(case,definition)
    return definition


def _budgets(value):
    if value is not None and (not isinstance(value, dict) or set(value)-set(_BUDGETS)):
        raise ValueError('Unknown task preparation budget fields')
    cfg = dict(_BUDGETS, **(value or {}))
    if any(type(number) is not int or number < 1 for number in cfg.values()):
        raise ValueError('Task preparation budgets must be positive integers')
    if cfg['max_nodes'] > 200000 or cfg['scan_limit'] > 10000000:
        raise ValueError('max_nodes must be <=200000 and scan_limit <=10000000')
    return cfg


def _reusable(root, definition, local_index_id=None):
    required = ['nodes.json']+[f'{name}_{part}.npy' for name in ('counts','propagation') for part in ('data','indices','indptr')]
    for path in sorted(Path(root).glob('*/manifest.json')):
        if path.parent.name.startswith('.'):
            continue
        try:
            manifest = json.loads(path.read_text(encoding='utf-8'))
            if manifest.get('source_index_id') != (local_index_id or definition['source_index_id']):
                continue
            if manifest.get('model_version',MODEL_VERSION) != definition['model_version']:
                continue
            if not all((path.parent/name).is_file() for name in required):
                continue
            nodes = json.loads((path.parent/'nodes.json').read_text(encoding='utf-8'))
            if canonical_ids([str(node['bodyId']) for node in nodes]) == definition['scope']['body_ids']:
                return path.parent.resolve(), manifest
        except (OSError,ValueError,KeyError):
            continue
    return None


def preview_task(index, cases_root, definition, budgets=None, *, cancel=lambda:False, progress=lambda value:None):
    definition = normalize_task(definition); cfg = _budgets(budgets)
    errors = []; bodies = definition['scope']['body_ids']
    cross=definition['source_index_id'] != index.manifest.get('index_id')
    if cross and definition['schema_version']==1:
        errors.append('source_index_id does not match the bound local index: '+str(index.manifest.get('index_id')))
    if definition['schema_version']==2 and definition['source_data']['dataset_version']!=source_data(index.manifest)['dataset_version']:
        errors.append('source_data.dataset_version differs; cross-data-version conversion is unsupported')
    if definition['model_version'] != MODEL_VERSION:
        errors.append('model_version is incompatible: '+definition['model_version'])
    raw = np.array(bodies,dtype=np.int64); positions = np.searchsorted(index.ids,raw)
    present = (positions < len(index.ids)) & (index.ids[np.minimum(positions,len(index.ids)-1)] == raw)
    missing = [body for body,found in zip(bodies,present) if not found]
    if missing:errors.append('scope.body_ids missing from local index: '+', '.join(missing))
    scope = dict(node_count=len(bodies),body_ids=bodies,missing_body_ids=missing,
                 internal_edges=None,internal_contacts=None,scan_complete=False)
    report = dict(kind='portable_task_preview',definition=definition,compatible=not errors,
                  errors=errors,scope=scope,conditions=definition['conditions'],budgets=cfg,
                  build_allowed=False,estimates=None,existing_case_path=None,verification_required=cross,
                  local_index_id=index.manifest.get('index_id'),
                  estimated_baseline_propagations=len(definition['conditions']),
                  estimated_intervention_propagations=len(definition['conditions']),
                  estimated_propagations=2*len(definition['conditions']))
    nodes = [dict(bodyId=body,memberships={'internal':['__portable_task__']}) for body in bodies]
    report['estimated_recording_bytes'] = sum(RecordPolicy.from_dict(item['recording']).resolve(
        dict(nodes=nodes),_cfg(item['experiment'],nodes),branch_count=2)[2]['bytes']
        for item in definition['conditions'])
    if errors:return report
    reused = _reusable(cases_root,definition,index.manifest.get('index_id'))
    report['intervention_edges_verified']=not any(
        event['type']=='edge_gain' for item in definition['conditions']
        for event in (item['experiment'].get('intervention_events') or []))
    if reused:
        report['candidate_case_path']=str(reused[0])
        if not report['intervention_edges_verified']:
            existing=load_case(reused[0])
            try:
                _validate_plan_edges(existing,definition)
                report['intervention_edges_verified']=True
            except ValueError as error:
                errors.append(str(error));report['compatible']=False
            finally:close_case(existing)
        if not cross or _verified(reused[0],reused[1],definition):
            report.update(existing_case_path=str(reused[0]),existing_case_id=reused[1]['case_id'],verification_required=False)
    if len(bodies) > cfg['max_nodes']:errors.append(f"scope exceeds max_nodes={cfg['max_nodes']}")
    if errors:return report
    progress(dict(phase='preview',node_count=len(bodies)))
    try:
        stats = induced_stats(index,bodies,scan_limit=cfg['scan_limit'],max_edges=cfg['max_internal_edges'],cancel=cancel)
    except MemoryError as error:
        errors.append(str(error));return report
    scope.update({key:stats[key] for key in ('internal_edges','internal_contacts','scan_complete','required_edges','scanned_edges')})
    if not stats['scan_complete']:
        errors.append(f"Complete induced scope needs {stats['required_edges']} indexed edges; scan_limit={cfg['scan_limit']}")
        return report
    estimates = _estimates(len(bodies),stats['internal_edges'],0);report['estimates']=estimates
    estimates['recording_bytes_exact'] = report['estimated_recording_bytes']
    estimates['estimated_run_peak_memory_bytes'] = (estimates['estimated_peak_memory_bytes']+
        report['estimated_recording_bytes']+len(bodies)*64)
    if estimates['estimated_peak_memory_bytes'] > cfg['max_bytes']:
        errors.append('Estimated scope memory exceeds max_bytes')
    elif estimates['estimated_run_peak_memory_bytes'] > cfg['max_bytes']:
        errors.append('Estimated scope plus retained condition recordings exceeds max_bytes')
    if not reused and estimates['estimated_disk_bytes'] > cfg['max_disk_bytes']:
        errors.append('Estimated new scope disk exceeds max_disk_bytes')
    report['build_allowed'] = not errors
    return report


def prepare_task(index, cases_root, definition, budgets=None, *, cancel=lambda:False, progress=lambda value:None):
    try:
        report = preview_task(index,cases_root,definition,budgets,cancel=cancel,progress=progress)
    except InterruptedError as error:
        return dict(kind='portable_task_preparation',definition=normalize_task(definition),
                    status='cancelled',reused=False,error=str(error))
    report['kind']='portable_task_preparation'; report['status']='failed';report['reused']=False
    if not report['build_allowed']:return report
    if cancel():report['status']='cancelled';return report
    candidate=report.get('candidate_case_path')
    if candidate:
        case=load_case(candidate)
        try:
            _validate_plan_edges(case,report['definition'])
            if report['definition']['schema_version']==2:
                actual,match=_verify_case(case,report['definition'],cancel=cancel,progress=progress)
                if cancel():raise InterruptedError('Verification cancelled before publication')
                report['verification']=_save_verification(candidate,case,report['definition'],actual,match)
                report['scope_content']=actual
            report.update(status='complete',case_path=candidate,case_id=case['manifest']['case_id'],reused=True,verification_required=False)
        except InterruptedError as error:report.update(status='cancelled',error=str(error))
        except ValueError as error:report.update(status='failed',error=str(error))
        finally:close_case(case)
        return report
    root = Path(cases_root);root.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(root).free < report['estimates']['estimated_disk_bytes']:
        report['errors'].append('Available disk is smaller than scope estimate');return report
    definition = report['definition']; bodies = definition['scope']['body_ids']
    first = definition['conditions'][0]['experiment']
    inputs = sorted({body for item in definition['conditions'] for event in item['experiment']['input_events'] for body in event['body_ids']},key=int)
    # Named groups are UI conveniences only; exact task events/observations remain authoritative.
    groups = dict(input={'任务输入':inputs} if inputs else {},internal={'__portable_task__':bodies},
                  output={item['name']:item['body_ids'] for item in first['observations']})
    selection = dict(body_ids=bodies,seed_ids=bodies,selected_node_count=len(bodies),requested_hops=0,hops_completed=0,
        max_nodes=len(bodies),direction='both',category='all',truncated=False,
        selection_rule='portable task exact members; no filtering or neighborhood selection')
    fingerprint = hashlib.sha256(json.dumps(dict(source=index.manifest.get('index_id'),bodies=bodies),sort_keys=True).encode()).hexdigest()[:20]
    destination = root/('task-'+fingerprint);staging=root/('.task-preparation-'+uuid4().hex)
    try:
        if destination.exists():raise FileExistsError('Destination exists but is not a complete matching scope: '+str(destination))
        progress(dict(phase='build',node_count=len(bodies),internal_edges=report['scope']['internal_edges']))
        write_selected_case(index,dict(name=definition['name'],groups=groups),selection,staging,
            default_experiment=first,scan_limit=report['budgets']['scan_limit'],
            max_edges=report['budgets']['max_internal_edges'],cancel=cancel)
        if cancel():raise InterruptedError('Task preparation cancelled before publication')
        manifest=json.loads((staging/'manifest.json').read_text(encoding='utf-8'))
        manifest['model_version']=MODEL_VERSION
        (staging/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        local_case=load_case(staging)
        try:
            _validate_plan_edges(local_case,definition)
            if definition['schema_version']==2:
                actual,match=_verify_case(local_case,definition,cancel=cancel,progress=progress)
                if cancel():raise InterruptedError('Verification cancelled before publication')
                report['verification']=_save_verification(staging,local_case,definition,actual,match)
                report['scope_content']=actual
        finally:close_case(local_case)
        if cancel():raise InterruptedError('Preparation cancelled before publication')
        staging.rename(destination)
        report.update(status='complete',case_path=str(destination.resolve()),case_id=manifest['case_id'],verification_required=False)
    except InterruptedError as error:
        report.update(status='cancelled',error=str(error))
    except Exception as error:
        report.update(status='failed',error=str(error))
    finally:
        if staging.exists() and (staging/'manifest.json').exists():
            (staging/'manifest.json').unlink()
    return report


def run_task(case_path, definition, *, cancel=lambda:False, progress=lambda value:None):
    """Run fixed conditions through compare; do not search or rebuild a scope."""
    case=load_case(case_path)
    try:
        definition=validate_task_case(case,definition,case_path,cancel=cancel,progress=progress)
        view=dict(case,nodes=_view_nodes(case['nodes']))
        first=_cfg(definition['conditions'][0]['experiment'],case['nodes'])
        report=dict(kind='conditions',case_id=case['manifest']['case_id'],model_version=MODEL_VERSION,
            task_definition=definition,conditions=[],requested_condition_count=len(definition['conditions']),
            protocol=dict(steps=first.steps,alpha=first.alpha,rho=first.rho,outputs=list(first.outputs),observations=effective_observations(view['nodes'],first)),
            status='complete',rows=[],results=[],condition_statuses=[],constraints=[],
            baseline_simulations=0,completed_baseline_simulations=0,intervention_simulations=0,
            completed_intervention_simulations=0,baseline_reuses=0,baseline_protocol_count=0,
            computation_node_count=len(case['nodes']),
            data_scope=dict(case_id=case['manifest']['case_id'],source_index_id=case['manifest']['source_index_id'],case_name=case['manifest'].get('case_name'),
                            external_input_contacts=case['manifest'].get('external_input_contacts'),external_output_contacts=case['manifest'].get('external_output_contacts')))
        report['source_index_id']=case['manifest']['source_index_id']
        report['actual_data_identity']=dict(source_index_id=case['manifest']['source_index_id'],case_id=case['manifest']['case_id'],
            model_version=MODEL_VERSION,scope_content=case.get('_verified_scope_content'),source_data=source_data(case['manifest']))
        statuses=report['condition_statuses']
        for item in definition['conditions']:
            statuses.append(dict(name=item['name'],role=item['role'],status='not_run'))
        for index,item in enumerate(definition['conditions']):
            current=statuses[index]
            if cancel():report['status']='cancelled';current['status']='cancelled';break
            cfg=_cfg(item['experiment'],case['nodes']);policy=RecordPolicy.from_dict(item['recording'])
            policy.resolve(view,cfg,branch_count=2)
            def physical(value):
                key=('completed_' if value['status']=='completed' else '')+value['kind']+'_simulations'
                report[key]+=1
                progress(dict(phase='run',condition_name=item['name'],condition_index=index,condition_count=len(statuses),**value,
                    baseline_simulations=report['baseline_simulations'],completed_baseline_simulations=report['completed_baseline_simulations'],
                    intervention_simulations=report['intervention_simulations'],completed_intervention_simulations=report['completed_intervention_simulations']))
            current['status']='running'
            try:
                result=compare(view,cfg,recording=policy,cancel=cancel,simulation_progress=physical)
                result['data_scope']=report['data_scope']
                constraints=None
                if item['search_options'] is not None:
                    assessment_cfg=cfg
                    bodies=item['experiment']['intervention_ids']
                    if cfg.intervention_events is not None:
                        from .simulation import intervention_node_ids
                        bodies=intervention_node_ids(view['nodes'],cfg)
                        # The legacy constraint annotator only consumes saved
                        # observation metrics and node count, never propagates.
                        assessment_cfg=replace(cfg,intervention_events=None,intervention_semantics_version=None,
                            intervention_ids=tuple(bodies),intervention_group='__portable_task__')
                    constraints=_assess(view,[(item['name'],assessment_cfg)],bodies,[result['summary']],
                                        SearchOptions.from_dict(item['search_options']),[item['name']])
                    constraints['condition_role']=item['role']
                    for row in constraints['condition_results']:
                        row['evidence_classification']=item['role']
                report['constraints'].append(dict(name=item['name'],role=item['role'],constraints=constraints))
                report['results'].append(result)
                report['conditions'].append(dict(name=item['name'],experiment=item['experiment']))
                report['rows'].append(dict(name=item['name'],role=item['role'],intervention_group=cfg.intervention_group,
                    intervention_node_count=result['intervention_node_count'],body_ids=result['intervention_body_ids'],
                    gain=cfg.gain,start=cfg.intervention_start,stop=cfg.intervention_stop,
                    intervention_events=item['experiment'].get('intervention_events'),
                    intervention_semantics_version=item['experiment'].get('intervention_semantics_version'),
                    intervention_edge_count=result.get('intervention_edge_count',0),
                    input_events=effective_input_events(view['nodes'],cfg),outputs=result['summary']))
                current['status']='completed';report['baseline_protocol_count']+=1
            except SimulationCancelled as error:
                current.update(status='cancelled',error=str(error));report['status']='cancelled';break
            except Exception as error:
                current.update(status='failed',error=str(error));report['status']='failed';break
        report['completed_conditions']=len(report['results'])
        report['termination_reason']=report['status']
        report['counters']={key:report[key] for key in ('baseline_simulations','completed_baseline_simulations',
            'intervention_simulations','completed_intervention_simulations','baseline_reuses','baseline_protocol_count')}
        report['counters']['started_propagations']=report['baseline_simulations']+report['intervention_simulations']
        report['counters']['completed_propagations']=report['completed_baseline_simulations']+report['completed_intervention_simulations']
        return report
    finally:
        close_case(case)
