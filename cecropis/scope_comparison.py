"""Compare one exact protocol and intervention across saved scopes sequentially.

The propagation implementation remains simulation.compare. Temporary trajectory
files keep retained history independent of how many scopes are compared.
"""
import copy
import json
import shutil
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import numpy as np

from . import MODEL_VERSION
from .case import close_case, load_case
from .simulation import Experiment, RecordPolicy, compare

_TEMP_PREFIX = 'malecns-scope-recordings-'
_OWNED_RECORDINGS = set()
_FIELDS = {'model_version', 'source_index_id', 'cases', 'experiment', 'recording'}


def _canonical_ids(values, label, *, allow_empty=False):
    if not isinstance(values, (list, tuple)) or (not values and not allow_empty):
        raise ValueError(f'{label} requires exact nonempty body IDs')
    if any(not isinstance(body, str) or not body.isascii() or not body.isdecimal()
           or str(int(body)) != body or not 0 < int(body) <= np.iinfo(np.int64).max
           for body in values) or len(set(values)) != len(values):
        raise ValueError(f'{label} requires unique canonical positive int64 string IDs')
    return list(values)


def _request(config, *, allow_single=False, allow_empty=False):
    if not isinstance(config, dict) or set(config) != _FIELDS:
        raise ValueError('Scope comparison requires model_version, source_index_id, cases, experiment and recording')
    if config['model_version'] != MODEL_VERSION:
        raise ValueError('Scope comparison model version does not match the current model')
    if not isinstance(config['source_index_id'], str) or not config['source_index_id'].strip():
        raise ValueError('Scope comparison requires a nonempty source_index_id')
    cases = config['cases']
    if not isinstance(cases, list) or not (1 if allow_single else 2) <= len(cases) <= 12:
        raise ValueError('Select 2..12 saved computation scopes')
    identities, paths = set(), set()
    for item in cases:
        if not isinstance(item, dict) or set(item) != {'case_id', 'case_path'} or any(
                not isinstance(item[key], str) or not item[key].strip() for key in item):
            raise ValueError('Each scope requires an exact case_id and case_path')
        path = str(Path(item['case_path']).resolve())
        if item['case_id'] in identities or path in paths:
            raise ValueError('Scope identities and saved paths must be distinct')
        identities.add(item['case_id']); paths.add(path)
    experiment = config['experiment']
    if not isinstance(experiment, dict) or experiment.get('input_events') is None or experiment.get('observations') is None:
        raise ValueError('Cross-scope comparisons require explicit input_events and observations')
    if allow_empty and experiment.get('intervention_events') is None and experiment.get('intervention_ids') == []:
        from .plan_reduction import FixedExperiment
        cfg = FixedExperiment.from_dict(copy.deepcopy(experiment))
        cfg.intervention_group = '__fixed_no_intervention__'
    else:
        cfg = Experiment.from_dict(copy.deepcopy(experiment))
    if cfg.intervention_events is None:
        _canonical_ids(cfg.intervention_ids, 'intervention_ids', allow_empty=allow_empty)
    policy = RecordPolicy.from_dict(config['recording'])
    if policy.body_ids is not None:
        _canonical_ids(policy.body_ids, 'recording.body_ids')
    return cfg, policy


def _bound_case(case, cfg):
    """Use exact IDs even when saved operation roles differ between scopes."""
    if cfg.intervention_events is not None:
        return case, copy.deepcopy(cfg)
    selected = set(cfg.intervention_ids)
    occupied = {label for node in case['nodes'] for label in node.get('memberships', {}).get('internal', [])}
    occupied.update(node.get('group_label') for node in case['nodes'])
    label = '__scope_fixed_intervention__'
    while label in occupied:
        label += '_'
    nodes = []
    for node in case['nodes']:
        if str(node['bodyId']) not in selected:
            nodes.append(node)
            continue
        member = {role: list(labels) for role, labels in node.get('memberships', {}).items()}
        member.setdefault('internal', []).append(label)
        nodes.append(dict(node, memberships=member))
    bound = copy.deepcopy(cfg)
    bound.intervention_group = label
    return dict(case, nodes=nodes), bound


def _inspect(case, item, config, cfg, policy):
    manifest = case['manifest']
    available = {str(node['bodyId']) for node in case['nodes']}
    from .interventions import intervention_node_ids, intervention_edge_ids, CompiledInterventions
    endpoints = {body for edge in intervention_edge_ids(cfg) for body in edge}
    required = {
        'input': {body for event in cfg.input_events for body in event['body_ids']},
        'observations': {body for observation in cfg.observations for body in observation['body_ids']},
        'intervention': set(intervention_node_ids(case['nodes'], cfg)) | endpoints,
        'recording': set(policy.body_ids or ())}
    missing = {role: sorted(members-available, key=int) for role, members in required.items()}
    errors = []
    if manifest.get('case_id') != item['case_id']:
        errors.append('Saved scope case_id does not match the requested identity')
    if manifest.get('source_index_id') != config['source_index_id']:
        errors.append('Saved scope data index version does not match source_index_id')
    if manifest.get('model_version', MODEL_VERSION) != config['model_version']:
        errors.append('Saved scope model version does not match model_version')
    for role, members in missing.items():
        if members:
            errors.append(f'Missing {role} members: '+', '.join(members))
    recording = None
    if not any(missing.values()):
        try:
            view, bound = _bound_case(case, cfg)
            bound.validate(view['nodes'])
            CompiledInterventions(view, bound)
            _, _, recording = policy.resolve(view, bound, branch_count=2)
        except ValueError as error:
            errors.append(str(error))
    return dict(item, name=manifest.get('case_name', item['case_id']),
        node_count=len(case['nodes']), internal_edges=int(case['counts'].nnz),
        internal_contacts=int(manifest['internal_contacts'] if 'internal_contacts' in manifest else case['counts'].sum()),
        external_input_contacts=int(manifest.get('external_input_contacts', 0)),
        external_output_contacts=int(manifest.get('external_output_contacts', 0)),
        total_input_contacts=int(manifest.get('total_input_contacts', 0)),
        normalization=manifest.get('normalization'), missing_members=missing,
        compatible=not errors, errors=errors, recording_metadata=recording)


def preview_scopes(config, *, _allow_single=False, _allow_empty=False):
    """Validate every saved scope and estimate retained trajectories before running."""
    cfg, policy = _request(config, allow_single=_allow_single, allow_empty=_allow_empty)
    rows = []
    for item in config['cases']:
        case = None
        try:
            case = load_case(item['case_path'])
            row = _inspect(case, item, config, cfg, policy)
        except (OSError, ValueError, KeyError) as error:
            row = dict(item, name=item['case_id'], node_count=None,
                internal_edges=None, internal_contacts=None, external_input_contacts=None,
                external_output_contacts=None, total_input_contacts=None,
                missing_members={key: [] for key in ('input', 'observations', 'intervention', 'recording')},
                compatible=False, errors=[str(error)], recording_metadata=None)
        finally:
            if case is not None:
                close_case(case)
        rows.append(row)
    sizes = [(row['recording_metadata'] or {}).get('bytes', 0) for row in rows]
    return dict(compatible=all(row['compatible'] for row in rows),
        source_index_id=config['source_index_id'], model_version=config['model_version'],
        cases=rows, errors=[f"{row['name']}: {error}" for row in rows for error in row['errors']],
        recording_total_bytes=sum(sizes), recording_peak_bytes=max(sizes, default=0))


def compare_scopes(config, *, cancel=lambda: False, progress=lambda value: None,
                   simulation_progress=lambda value:None, _allow_single=False, _allow_empty=False):
    """Run each range's own baseline and the same fixed intervention, one at a time."""
    request = copy.deepcopy(config)
    cfg, policy = _request(request, allow_single=_allow_single, allow_empty=_allow_empty)
    request['experiment']=json.loads(json.dumps(asdict(cfg)))
    request['recording']=json.loads(json.dumps(asdict(policy)))
    request['cases']=[dict(item,case_path=str(Path(item['case_path']).resolve())) for item in request['cases']]
    preview = preview_scopes(request, _allow_single=_allow_single, _allow_empty=_allow_empty)
    if not preview['compatible']:
        raise ValueError('Incompatible calculation scopes: '+'; '.join(preview['errors']))
    cfg, policy = _request(request, allow_single=_allow_single, allow_empty=_allow_empty)
    scopes = [dict(row, status='not_run', result=None, error=None) for row in preview['cases']]
    result = dict(kind='scope_comparison', config=request, source_index_id=request['source_index_id'],
        model_version=request['model_version'], status='complete', scopes=scopes,
        recording_total_bytes=preview['recording_total_bytes'],
        recording_peak_bytes=preview['recording_peak_bytes'], recording_files={})
    staging = None
    completed = 0
    for index, scope in enumerate(scopes):
        if cancel():
            result['status'] = 'cancelled'
            break
        progress(dict(index=index, total=len(scopes), current_case_id=scope['case_id'], completed=completed))
        case = view = None
        try:
            case = load_case(scope['case_path'])
            check = _inspect(case, scope, request, cfg, policy)
            if not check['compatible']:
                raise ValueError('; '.join(check['errors']))
            view, bound = _bound_case(case, cfg)
            single = compare(view, bound, recording=policy, cancel=cancel,
                             simulation_progress=simulation_progress)
            states = single.pop('states', None)
            if states is not None:
                if staging is None:
                    staging = Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX))
                path = staging / f'{index:02d}.npz'
                result['recording_files'][scope['case_id']] = str(path)
                _OWNED_RECORDINGS.add(str(path.resolve()))
                np.savez_compressed(path, baseline=states[0], intervention=states[1])
                del states
            # The private operation group used for binding is not part of the saved protocol.
            single['config']['experiment'] = copy.deepcopy(request['experiment'])
            scope.update(status='completed', result=single,
                         recording_metadata=single['recording_metadata'])
            completed += 1
        except Exception as error:
            from .simulation import SimulationCancelled
            if isinstance(error, SimulationCancelled):
                scope.update(status='cancelled', error=str(error))
                result['status'] = 'cancelled'
            else:
                scope.update(status='failed', error=str(error))
                result['status'] = 'failed'
            break
        finally:
            view = None
            if case is not None:
                close_case(case)
            case = None
        progress(dict(index=index+1, total=len(scopes), current_case_id=None, completed=completed))
    progress(dict(index=completed, total=len(scopes), current_case_id=None,
                  completed=completed, status=result['status']))
    return result


def save_scope_comparison(root, result):
    """Save completed scopes and honest status for failed/cancelled partial tasks."""
    if result.get('kind') != 'scope_comparison':
        raise ValueError('Expected a scope comparison result')
    for scope in result['scopes']:
        if scope['status'] == 'completed' and (scope.get('recording_metadata') or {}).get('mode', 'none') != 'none' and scope['case_id'] not in result.get('recording_files', {}):
            raise ValueError('Recorded trajectories are unavailable; keep the original saved result or rerun its config before saving again')
    folder = Path(root) / ('scope-comparison-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8])
    folder.mkdir(parents=True)
    clean = copy.deepcopy({key: value for key, value in result.items() if key != 'recording_files'})
    for index, scope in enumerate(clean['scopes']):
        source = result.get('recording_files', {}).get(scope['case_id'])
        if source is not None and scope['status'] == 'completed':
            destination = folder / f'scope-{index:02d}' / 'states.npz'
            destination.parent.mkdir()
            shutil.copyfile(source, destination)
            scope['recording_file'] = destination.relative_to(folder).as_posix()
    for filename, value in [('config.json', clean['config']), ('scope-comparison.json', clean)]:
        (folder / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return folder


def discard_recordings(result):
    """Remove only temporary files created for this comparison, never saved runs."""
    folders = set()
    for value in result.get('recording_files', {}).values():
        path = Path(value).resolve()
        if str(path) not in _OWNED_RECORDINGS or path.parent.parent != Path(tempfile.gettempdir()).resolve() or not path.parent.name.startswith(_TEMP_PREFIX) or path.suffix != '.npz':
            raise ValueError('Refusing to discard a recording outside this comparison staging directory')
        path.unlink(missing_ok=True)
        _OWNED_RECORDINGS.discard(str(path))
        folders.add(path.parent)
    for folder in folders:
        try:
            folder.rmdir()
        except FileNotFoundError:
            pass
    result['recording_files'] = {}
