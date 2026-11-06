"""Small, reference-based analysis scenes; never load trajectories or simulate."""
import copy
import json
import math
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .replay import _identity, _ids, _resolve_source, _window
from .simulation import Experiment

MAX_SESSION_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_JSON_BYTES = 64 * 1024 * 1024
_ARTIFACT_FILES = ('scope-plan-comparison.json','differences.json', 'replay.json', 'plan-reduction.json', 'timing-exploration.json',
    'joint-search.json', 'pathways.json', 'search.json', 'comparison.json', 'result.json')
_SELECTION_FIELDS = {'condition_name', 'body_ids', 'plan_body_ids', 'start', 'duration','task_id'}


def _json(path, maximum):
    if path.stat().st_size > maximum:
        raise ValueError(f'JSON exceeds analysis scene budget: {path.name}')
    def reject(value):
        raise ValueError(f'Non-finite JSON number: {value}')
    return json.loads(path.read_text(encoding='utf-8-sig'), parse_constant=reject)


def _artifact_path(root, artifact_id):
    if (not isinstance(artifact_id, str) or not artifact_id or
        artifact_id in ('.', '..') or '/' in artifact_id or '\\' in artifact_id or
        ':' in artifact_id):
        raise ValueError('Artifact reference must be a single saved directory ID')
    root = Path(root).resolve()
    path = (root / artifact_id).resolve()
    if path.parent != root:
        raise ValueError('Artifact reference escapes the saved results directory')
    return path


def _check_identity(case, header):
    expected = _identity(case)
    found = []
    for value in (header, header.get('config'), header.get('data_scope'), header.get('scope')):
        if isinstance(value, dict):
            found.append(value)
            for key, actual in expected.items():
                if key in value and value[key] != actual:
                    raise ValueError(f'Analysis scene reference {key} does not match this calculation scope')
    if not any(value.get('case_id') == expected['case_id'] for value in found):
        raise ValueError('Analysis scene reference has no matching calculation scope identity')
    # Historical same-case results may lack index/hash fields. Explicit values
    # are always checked; no alternative scope or model is inferred.
    if not any(value.get('model_version') == expected['model_version'] for value in found):
        raise ValueError('Analysis scene reference has no matching model identity')


def _artifact(root, artifact_id, case, expected_kind=None, selection=None):
    folder = _artifact_path(root, artifact_id)
    if not folder.is_dir():
        return None
    result_file = next((folder / name for name in _ARTIFACT_FILES if (folder / name).is_file()), None)
    if result_file is None:
        return None
    header = _json(result_file, MAX_ARTIFACT_JSON_BYTES)
    if not isinstance(header, dict):
        raise ValueError('Saved result header must be an object')
    checked=header
    if header.get('kind')=='scope_plan_comparison':
        from .scope_plan_comparison import scope_plan_source
        checked=scope_plan_source(header,(selection or {}).get('task_id'))
    _check_identity(case, checked)
    kind = {'differences.json':'scope_differences', 'replay.json':'circuit_replay', 'plan-reduction.json':'plan_reduction',
        'pathways.json':'pathways'}.get(result_file.name)
    if expected_kind and kind != expected_kind:
        raise ValueError(f'{expected_kind} reference points to a different result type')
    # Required sidecar presence is checked without expanding arrays.
    required = {'differences.json':'statistics.npz', 'replay.json':'states.npz'}.get(result_file.name)
    if required and not (folder / required).is_file():
        return None
    return header


def _finite(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{label} must be finite')
    return value


def _small_json(value):
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError) as error:
        raise ValueError('Analysis scene must contain finite JSON display values') from error
    if len(encoded.encode('utf-8')) > MAX_SESSION_BYTES:
        raise ValueError('Analysis scene exceeds the 2 MiB display-state budget')
    return json.loads(encoded)


def _state(case, state, steps):
    if not isinstance(state, dict):
        raise ValueError('Analysis scene state must be an object')
    fields = {'active_view','selected_nodes','focus_node','window','difference_display','replay_display','graphs','reduction_display','spatial','experiment_draft'}
    if set(state) - fields:
        raise ValueError('Unsupported analysis scene state fields')
    state = copy.deepcopy(state)
    if 'experiment_draft' in state:
        draft = Experiment.from_dict(state['experiment_draft'])
        draft.validate(case['nodes'])
        from .interventions import CompiledInterventions
        CompiledInterventions(case, draft)
        state['experiment_draft'] = asdict(draft)
    if state.get('active_view','ranking') not in ('ranking','connections','replay','reduction','boundary','spatial'):
        raise ValueError('Unknown analysis view')
    state.setdefault('active_view','ranking')
    if 'spatial' in state:
        from .spatial import validate_spatial_state
        state['spatial']=validate_spatial_state(state['spatial'],case['manifest'].get('source_index_id'))
    available = {str(node['bodyId']) for node in case['nodes']}
    state['selected_nodes'] = _ids(state.get('selected_nodes',[]),available,'Scene selection',empty=True)
    focus = state.get('focus_node')
    if focus is not None:
        _ids([focus],available,'Scene focused node')
    if 'window' in state:
        state['window'] = _window(state['window'],steps)
    display=state.get('reduction_display',{})
    if not isinstance(display,dict) or set(display)-{'artifact_id','body_ids','condition_name'}:
        raise ValueError('Unsupported reduction display fields')
    if 'artifact_id' in display:_artifact_path(Path('.'),display['artifact_id'])
    if 'body_ids' in display:display['body_ids']=_ids(display['body_ids'],available,'Reduction display plan',empty=True)
    if 'condition_name' in display and not isinstance(display['condition_name'],str):
        raise ValueError('Reduction display condition must be a string')
    for key in ('difference_display','replay_display'):
        display = state.get(key,{})
        if not isinstance(display,dict):
            raise ValueError(f'{key} must be an object')
        allowed = ({'sort','body_id','type_filter','hide_endpoints','offset','selected_node','selected_nodes'}
            if key=='difference_display' else {'mode','state_step','selected_node','selected_edge','selected_nodes','window'})
        if set(display)-allowed:
            raise ValueError(f'Unsupported {key} fields')
        if 'selected_node' in display and display['selected_node'] is not None:
            _ids([display['selected_node']],available,'Display focused node')
        if 'selected_nodes' in display:
            display['selected_nodes'] = _ids(display['selected_nodes'],available,'Display selection',empty=True)
        if 'window' in display:display['window'] = _window(display['window'],steps)
        if key=='difference_display':
            if display.get('sort','absolute') not in ('absolute','decrease','increase'):
                raise ValueError('Unknown difference sort')
            if type(display.get('offset',0)) is not int or display.get('offset',0)<0:
                raise ValueError('Difference offset must be a nonnegative integer')
            if type(display.get('hide_endpoints',True)) is not bool:
                raise ValueError('hide_endpoints must be boolean')
            if any(not isinstance(display.get(field,''),str) for field in ('body_id','type_filter')):
                raise ValueError('Difference filters must be strings')
        else:
            if display.get('mode','delta') not in ('baseline','intervention','delta'):
                raise ValueError('Unknown replay display mode')
            if type(display.get('state_step',0)) is not int or not 0<=display.get('state_step',0)<=steps:
                raise ValueError('Replay state step is outside the protocol')
            if display.get('selected_edge') is not None:
                edge = display['selected_edge']
                if not isinstance(edge,str) or len(edge.split('->'))!=2:
                    raise ValueError('Replay edge must contain exact pre->post IDs')
                pre,post=edge.split('->')
                _ids(list(set((pre,post))),available,'Display edge')
                positions={str(node['bodyId']):i for i,node in enumerate(case['nodes'])}
                if case['counts'][positions[post],positions[pre]]<=0:
                    raise ValueError('Selected scene edge is not a real connection in this scope')
        state[key]=display
    graphs=state.get('graphs',{})
    if not isinstance(graphs,dict) or set(graphs)-{'replay','pathways'}:
        raise ValueError('Scene graphs may only contain replay and pathways layouts')
    for graph in graphs.values():
        if not isinstance(graph,dict) or set(graph)-{'positions','transform','label_mode'}:
            raise ValueError('Unsupported graph display state')
        positions=graph.get('positions',[])
        if not isinstance(positions,list) or len(positions)>10000:
            raise ValueError('Graph positions exceed the 10000-node scene budget')
        bodies=[]
        for position in positions:
            if not isinstance(position,dict) or set(position)!={'body_id','x','y','fixed'}:
                raise ValueError('Each graph position needs body_id,x,y,fixed')
            bodies.append(position['body_id'])
            _finite(position['x'],'Node x');_finite(position['y'],'Node y')
            if type(position['fixed']) is not bool:raise ValueError('Node fixed must be boolean')
        _ids(bodies,available,'Graph positions',empty=True)
        transform=graph.get('transform',dict(x=0,y=0,k=1))
        if not isinstance(transform,dict) or set(transform)!={'x','y','k'}:
            raise ValueError('Graph transform needs x,y,k')
        for key,value in transform.items():_finite(value,f'Transform {key}')
        if not .02<=transform['k']<=100:raise ValueError('Graph scale must be between .02 and 100')
        if graph.get('label_mode','auto') not in ('auto','all','selected','none'):
            raise ValueError('Unknown graph label mode')
    state['graphs']=graphs
    return state


def _source_definition(case, header, selection):
    if header.get('kind')=='scope_plan_comparison':
        from .scope_plan_comparison import scope_plan_source
        header=scope_plan_source(header,selection.get('task_id'))
    if header.get('kind') in ('scope_differences','circuit_replay'):
        header=header['config']['source_result']
    # Single-protocol search reports predate replay's result-shaped source.
    # Select only an actually evaluated set, then use the existing resolver.
    if 'evaluated' in header and 'conditions' not in header and 'experiment' in header:
        if set(selection)-{'body_ids','plan_body_ids'}:
            raise ValueError('Single-protocol search only accepts its evaluated fixed node set')
        bodies=selection.get('body_ids',selection.get('plan_body_ids'))
        if bodies is None:bodies=(header.get('best') or {}).get('body_ids')
        bodies=_ids(bodies,{str(n['bodyId']) for n in case['nodes']},'Search scene plan')
        proposals=[header.get('best')]+[row for key in ('evaluated','frontier','sensitivity') for row in header.get(key,[])]
        if not any(row and set(row.get('body_ids',[]))==set(bodies) for row in proposals):
            raise ValueError('Search scene requires an actually evaluated fixed plan')
        cfg=replace(Experiment.from_dict(header['experiment']),intervention_ids=tuple(bodies))
        header=dict(kind='comparison',config=dict(case_id=case['manifest']['case_id'],
            source_index_id=case['manifest'].get('source_index_id'),model_version=_identity(case)['model_version'],
            experiment=asdict(cfg)),intervention_body_ids=bodies)
    return _resolve_source(case,header,selection)


def _validate(case, document, root, *, saving):
    document=_small_json(document)
    fields={'kind','schema_version','name','identity','source','source_definition','references','state','created_at'}
    if not isinstance(document,dict) or set(document)-fields:
        raise ValueError('Unsupported analysis scene document fields')
    if (document.get('kind','analysis_session')!='analysis_session' or
        type(document.get('schema_version',1)) is not int or document.get('schema_version',1)!=1):
        raise ValueError('Unsupported analysis scene kind/schema version')
    if not saving and not {'kind','schema_version','identity','source_definition','state'}<=set(document):
        raise ValueError('Saved scene is missing its identity or exact source definition')
    name=document.get('name')
    if not isinstance(name,str) or not name.strip() or len(name.strip())>120:
        raise ValueError('Scene name must contain 1–120 characters')
    identity=_identity(case)
    if 'identity' in document and document['identity']!=identity:
        raise ValueError('Analysis scene scope/index/model identity mismatch')
    source=document.get('source')
    if not isinstance(source,dict) or set(source)-{'artifact_id','selection'} or 'artifact_id' not in source:
        raise ValueError('Scene source needs a saved artifact ID and exact selection')
    selection=source.get('selection',{})
    if not isinstance(selection,dict) or set(selection)-_SELECTION_FIELDS:
        raise ValueError('Unsupported scene source selection')
    references=document.get('references',{})
    if not isinstance(references,dict) or set(references)-{'differences','replay','pathways','reduction'}:
        raise ValueError('Unsupported scene artifact references')
    missing=[];available={};linked={}
    source_header=_artifact(root,source['artifact_id'],case,selection=selection)
    if source_header is None:missing.append(dict(role='source',artifact_id=source['artifact_id']))
    else:available['source']=source['artifact_id']
    for role,artifact_id in references.items():
        header=_artifact(root,artifact_id,case,{'differences':'scope_differences','replay':'circuit_replay','pathways':'pathways','reduction':'plan_reduction'}[role])
        if header is None:
            missing.append(dict(role=role,artifact_id=artifact_id))
        else:available[role]=artifact_id;linked[role]=header
    if saving and missing:raise ValueError('Cannot save a complete scene; missing references: '+json.dumps(missing,ensure_ascii=False))
    canonical=document.get('source_definition')
    if source_header is not None:
        _,cfg,_,resolved,_=_source_definition(case,source_header,selection)
        if canonical is not None and canonical!=_small_json(resolved):
            raise ValueError('Scene source definition does not match its saved result/condition')
        canonical=_small_json(resolved)
    elif canonical is not None:
        # A missing reference is not repaired. Its stored exact definition only
        # validates display state and remains available as provenance.
        _,cfg,_,canonical,_=_resolve_source(case,canonical,{})
        canonical=_small_json(canonical)
    else:raise ValueError('Missing scene source has no saved exact definition')
    for role,header in linked.items():
        experiment=header.get('config',{}).get('experiment',header.get('experiment'))
        if experiment is not None:
            # Resolve legacy roles and default observation windows by the same
            # source resolver; raw JSON list/tuple/default forms may differ.
            related=dict(kind='comparison',config=dict(case_id=identity['case_id'],
                source_index_id=identity['source_index_id'],model_version=identity['model_version'],
                experiment=experiment))
            _,_,_,related,_=_resolve_source(case,related,{})
            if _small_json(related['config']['experiment'])!=canonical['config']['experiment']:
                raise ValueError(f'Scene {role} reference belongs to a different exact protocol')
    state=_state(case,document.get('state',{}),cfg.steps)
    reduction_display=state.get('reduction_display',{})
    if reduction_display:
        if reduction_display.get('artifact_id')!=references.get('reduction'):
            raise ValueError('Reduction display must reference the associated saved report')
        if 'reduction' in linked:
            header=linked['reduction']
            _,_,_,related,_=_resolve_source(case,header,dict(
                body_ids=reduction_display.get('body_ids'),condition_name=reduction_display.get('condition_name')))
            # A different exact intervention is allowed in the plan browser,
            # while input, observations, windows, model and gain/time stay fixed.
            def protocol(value):
                return {key:item for key,item in value.items() if key not in ('intervention_ids','intervention_group')}
            if protocol(_small_json(related['config']['experiment']))!=protocol(canonical['config']['experiment']):
                raise ValueError('Reduction display belongs to a different fixed protocol')
    result=dict(kind='analysis_session',schema_version=1,name=name.strip(),identity=identity,
        source=dict(artifact_id=source['artifact_id'],selection=selection),source_definition=canonical,
        references=references,state=state)
    if 'created_at' in document:result['created_at']=document['created_at']
    _small_json(result)
    return dict(document=result,status='partial' if missing else 'complete',missing=missing,available=available)


def save_analysis_session(root, case, document):
    """Validate every existing reference, then write only a bounded scene JSON."""
    validated=_validate(case,document,root,saving=True)
    data=validated['document']
    data['created_at']=datetime.now().astimezone().isoformat(timespec='seconds')
    encoded=json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)
    if len(encoded.encode('utf-8'))>MAX_SESSION_BYTES:raise ValueError('Analysis scene exceeds 2 MiB')
    folder=Path(root)/('session-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8])
    folder.mkdir(parents=True)
    try:(folder/'session.json').write_text(encoded,encoding='utf-8')
    except Exception:
        if not any(folder.iterdir()):folder.rmdir()
        raise
    return folder


def read_analysis_session(path, case):
    """Read display/provenance only. Missing references never trigger compute."""
    path=Path(path)
    if path.is_dir():path=path/'session.json'
    return _validate(case,_json(path,MAX_SESSION_BYTES),path.parent.parent,saving=False)
