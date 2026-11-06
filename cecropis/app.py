"""Loopback-only local interface; no framework or external assets required."""
import argparse
import json
import math
import threading
from dataclasses import asdict
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode, parse_qs, urlparse
from uuid import uuid4

from . import MODEL_VERSION
from .case import groups, load_case
from .simulation import Experiment, compare, group_indices, save_run, node_groups
from .exploration import compare_conditions, save_comparison, select_nodes
from .api import Lab, Workspace
from .search import SearchOptions, save_search, resolve_candidates
from .jobs import SearchJob
from .pathway_results import save_pathways
from .scope_comparison import preview_scopes,save_scope_comparison
from .scope_jobs import ScopeComparisonJob
from .joint_search import save_joint_search
from .timing_exploration import save_timing
from . import group_connections as grouping
from . import response_exploration as responses

ROOT = Path(__file__).resolve().parents[1]


def fixed_experiment(data):
    """Only the explicit fixed-plan empty adapter permits no intervention IDs."""
    cfg=Experiment.from_dict(data)
    if cfg.intervention_group=='__fixed_no_intervention__' and cfg.intervention_ids==():
        from .plan_reduction import FixedExperiment
        return FixedExperiment.from_dict(asdict(cfg))
    return cfg


def public_node(node):
    return dict(node, bodyId=str(node['bodyId']))


def case_overview(case):
    relations = []
    for source in ['input', 'internal', 'output']:
        pre = group_indices(case['nodes'], source, '__all__')
        for target in ['input', 'internal', 'output']:
            post = group_indices(case['nodes'], target, '__all__')
            sub = case['counts'][post][:, pre]
            relations.append({'source': source, 'target': target,
                              'edges': sub.nnz, 'contacts': int(sub.sum())})
    return {'manifest': case['manifest'], 'groups': groups(case), 'relations': relations,
            'defaults': asdict(Experiment.from_dict(case['manifest'].get('default_experiment',{}))), 'model_version': MODEL_VERSION,
            'group_body_ids':{role:{label:[str(case['nodes'][i]['bodyId']) for i in group_indices(case['nodes'],role,label)]
                                   for label in labels} for role,labels in groups(case).items()},
            'scope_nodes':[{'bodyId':str(n['bodyId']),'type':n.get('type')} for n in case['nodes']],
            'internal_nodes': [{'bodyId': str(n['bodyId']), 'type': n['group_label'], 'groups':list(node_groups(n,'internal'))} for n in case['nodes'] if node_groups(n,'internal')],
            'group_counts': {role: {label: len(group_indices(case['nodes'], role, label)) for label in labels}
                             for role, labels in groups(case).items()}}


def connections(case, source_role, source_label, target_role, target_label):
    available = groups(case)
    for role, label in [(source_role, source_label), (target_role, target_label)]:
        if role not in available or (label != '__all__' and label not in available[role]):
            raise ValueError('Unknown connection group')
    pre = group_indices(case['nodes'], source_role, source_label)
    post = group_indices(case['nodes'], target_role, target_label)
    sub = case['counts'][post][:, pre].tocoo()
    order = sub.data.argsort()[::-1][:100]
    edges = []
    for k in order:
        a, b = case['nodes'][pre[sub.col[k]]], case['nodes'][post[sub.row[k]]]
        edges.append({'body_pre': str(a['bodyId']), 'body_post': str(b['bodyId']),
                      'pre_type': a['group_label'], 'post_type': b['group_label'],
                      'weight': int(sub.data[k]), 'total_post_input': b['total_input'],
                      'normalized_weight': float(sub.data[k] / b['total_input']),
                      'external_post_input': b['external_input']})
    return {'edges': edges, 'edge_count': sub.nnz, 'contacts': int(sub.data.sum()),
            'source_node_count': len(pre), 'target_node_count': len(post),
            'target_nodes': [public_node(case['nodes'][i]) for i in post],
            'source_nodes': [public_node(case['nodes'][i]) for i in pre]}


def node_detail(case, body_id):
    matches = [n for n in case['nodes'] if str(n['bodyId']) == body_id]
    if not matches:
        raise ValueError('Unknown body ID')
    node = matches[0]
    idx = node['index']
    incoming = case['counts'].getrow(idx).tocoo()
    outgoing = case['counts'].getcol(idx).tocoo()
    def neighbors(coo, axis):
        return [{'node': public_node(case['nodes'][int(getattr(coo, axis)[k])]),
                 'weight': int(coo.data[k])}
                for k in coo.data.argsort()[::-1][:20]]
    return {'node': public_node(node), 'incoming': neighbors(incoming, 'col'),
            'outgoing': neighbors(outgoing, 'row')}


def serve(case_path=None, port=8501, run_root=None, geometry_path=None,index_path=None,cases_path=None,
          skeleton_path=None,skeleton_cache_path=None,raw_path=None,configuration_path=None,*,banner=True,access_log=False):
    from .service_control import LocalRequestHandler, ServiceControl, service_path
    service_path(port)  # Validate before loading data or binding a socket.
    from .workspace_config import resolve_workspace_paths
    resolved=resolve_workspace_paths(root=ROOT,command='serve',workspace=configuration_path,
        case=case_path,index=index_path,cases=cases_path,runs=run_root,geometry=geometry_path,
        raw=raw_path,skeletons=skeleton_path,skeleton_cache=skeleton_cache_path)
    case_path,index_path,cases_path,run_root=[resolved.get(k) for k in ('case','index','cases','runs')]
    geometry_path,raw_path,skeleton_path,skeleton_cache_path=[resolved.get(k) for k in ('geometry','raw','skeletons','skeleton_cache')]
    from .preparation import check_preparation
    preparation_paths={key:Path(value).resolve() for key,value in
        dict(index=index_path,cases=cases_path,runs=run_root,raw=raw_path,geometry=geometry_path,
             skeletons=skeleton_path,skeleton_cache=skeleton_cache_path).items() if value is not None}
    preparation_report=check_preparation(preparation_paths)
    if case_path is None and not preparation_report['ready']:
        from .preparation_app import serve_preparation,open_prepared_workspace
        binding=serve_preparation(preparation_paths,port,configuration_path,banner=banner,access_log=access_log)
        return open_prepared_workspace(binding,port,banner=False,access_log=access_log) if binding else None
    lab = Lab(case_path, geometry_path) if case_path is not None else None
    case = lab.case if lab is not None else None
    overview = case_overview(case) if case is not None else None
    token = uuid4().hex
    lock = threading.RLock()
    rebind={}
    state = {'last': None, 'run_id': None, 'comparison': None, 'comparison_id': None,
             'pathways':None,'pathways_id':None,'timing_report':None,'timing_source':None,
             'replay':None,'replay_id':None,'replay_origin_job_id':None,'replay_origin':None,
             'differences':None,'difference_id':None,'reduction_report':None,'reduction_source':None}
    run_root = Path(run_root).resolve()
    cases_root = Path(cases_path).resolve()
    index_root = Path(index_path).resolve() if index_path is not None else None
    from .web_assets import WebAssets, template
    assets = WebAssets()
    html = template('ui.html')
    from .ui_errors import error_payload
    from .local_tasks import LocalTasks, LocalSlot
    local_tasks=LocalTasks(run_root)
    job = SearchJob(run_root)
    scope_job=ScopeComparisonJob(run_root)
    scope_suspended=False
    workspace=None
    index_error=None
    if index_root is not None:
        try:
            workspace=Workspace(index_root,cases_root)
        except (ValueError,OSError,KeyError,TypeError) as error:
            index_error=str(error)
    else:
        index_error='No complete connection index is bound'
    initial_case=Path(case_path).resolve() if case_path is not None else None
    group_reports={}
    group_jobs={}

    def global_spatial():
        return global_workspace().spatial(geometry_path)

    def global_skeletons():
        return global_workspace().skeletons(skeleton_path,skeleton_cache_path)

    def geometry_scene_status(scene):
        """Check published geometry references without preparing or simulating."""
        saved=scene.get('document',{}).get('state',{}).get('spatial',{}).get('geometry')
        if not saved:
            return scene
        try:
            current=global_skeletons().overview(limit=0)
        except (ValueError,OSError) as error:
            scene['geometry_status']=dict(saved_cache_id=saved.get('cache_id'),
                current_cache_id=None,status='unavailable',error=str(error))
            return scene
        expected=saved.get('cache_id')
        actual=current.get('cache_id')
        scene['geometry_status']=dict(saved_cache_id=expected,current_cache_id=actual,
            status='available' if actual and actual==expected else 'missing' if not actual else 'updated')
        return scene

    def workspace_summary():
        return dict(active_case=case is not None,
            preparation=preparation_report,
            paths=dict(index=str(index_root) if index_root is not None else None,cases=str(cases_root),runs=str(run_root)),
            index=dict(available=workspace is not None,path=str(index_root) if index_root is not None else None,error=index_error,
                       index_id=workspace.index.manifest['index_id'] if workspace else None))

    def current_overview():
        return dict(overview or {},active_case=case is not None,token=token,workspace=workspace_summary())

    def cases():
        paths=[initial_case] if initial_case is not None else []
        parent=cases_root
        if parent.is_dir():
            paths.extend(sorted(p for p in parent.iterdir() if p.is_dir() and not p.name.startswith('.')))
        output=[]
        for path in dict.fromkeys(paths):
            if not (path/'manifest.json').is_file():
                continue
            m=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
            output.append(dict(id='initial' if path==initial_case else path.name,path=path,
                               name=m.get('case_name',path.name),node_count=m['node_count'],case_id=m['case_id'],
                               source_index_id=m.get('source_index_id')))
        return output

    def artifacts():
        output=[]
        if not run_root.is_dir():
            return output
        for path in sorted(run_root.iterdir(),key=lambda p:p.name,reverse=True):
            config_file=path/'config.json'
            kind='run'
            result_file=path/'result.json'
            if path.name=='conditions' and path.is_dir():
                for f in sorted(path.glob('*.json'),reverse=True):
                    c=json.loads(f.read_text(encoding='utf-8'))
                    output.append(dict(id='conditions/'+f.name,label=f.stem,case_id=c.get('case_id'),kind='condition',config=c,result=None))
                continue
            if not path.is_dir():
                continue
            if path.name.startswith('.'):
                continue
            if (path/'group-connections.json').is_file():
                header=json.loads((path/'group-connections.json').read_text(encoding='utf-8'))
                output.append(dict(id=path.name,label=header['definition'].get('name',path.name),
                    case_id=header['identity'].get('case_id'),kind='group_connections',
                    config=header['identity'],status=header['status'],
                    result_path=path/'group-connections.json'))
                continue
            if (path/'scope-expansion.json').is_file():
                from .scope_expansion import load_expansion
                r=load_expansion(path)
                c=dict(case_id=r['identity']['base_case_id'],model_version=r['identity']['model_version'],source_index_id=r['identity']['source_index_id'])
                output.append(dict(id=path.name,label=path.name,case_id=c['case_id'],kind='scope_expansion',config=c,result_path=path/'scope-expansion.json'))
                continue
            if (path/'session.json').is_file():
                scene=json.loads((path/'session.json').read_text(encoding='utf-8'))
                output.append(dict(id=path.name,label=scene['name'],case_id=scene['identity']['case_id'],kind='analysis_session',config=scene['identity'],result_path=path/'session.json'))
                continue
            if (path/'response-exploration.json').is_file():
                result_file=path/'response-exploration.json'
                kind='response_exploration'
            elif (path/'operation-search.json').is_file():
                result_file=path/'operation-search.json'
                kind='operation_search'
            elif (path/'scope-plan-comparison.json').is_file():
                result_file=path/'scope-plan-comparison.json'
                kind='scope_plan_comparison'
            elif (path/'plan-reduction.json').is_file():
                result_file=path/'plan-reduction.json'
                kind='plan_reduction'
            elif (path/'differences.json').is_file():
                result_file=path/'differences.json'
                kind='scope_differences'
            elif (path/'replay.json').is_file():
                result_file=path/'replay.json'
                kind='circuit_replay'
            elif (path/'timing-exploration.json').is_file():
                result_file=path/'timing-exploration.json'
                kind='timing_exploration'
            elif (path/'joint-search.json').is_file():
                result_file=path/'joint-search.json'
                kind='joint_search'
            elif (path/'scope-comparison.json').is_file():
                result_file=path/'scope-comparison.json'
                kind='scope_comparison'
            elif (path/'pathways.json').is_file():
                result_file=path/'pathways.json'
                kind='pathways'
            elif (path/'search.json').is_file():
                result_file=path/'search.json'
                kind='search'
                config_file=path/'config.json' if (path/'config.json').is_file() else path/'conditions.json'
            elif (path/'comparison.json').is_file():
                result_file=path/'comparison.json'
                kind='comparison'
                config_file=path/'conditions.json'
            if not config_file.is_file():
                if kind!='search':
                    continue
                report=json.loads(result_file.read_text(encoding='utf-8'))
                c={k:report[k] for k in ('case_id','model_version','experiment')}
            else:
                c=json.loads(config_file.read_text(encoding='utf-8'))
            if kind=='run' and result_file.is_file():
                # Config has no run kind; a forward history has only one branch.
                with result_file.open(encoding='utf-8') as stream:
                    if '"kind": "forward"' in stream.read(2048):
                        kind='forward'
            output.append(dict(id=path.name,label=c.get('definition',{}).get('name',path.name) if kind=='response_exploration' else path.name,
                case_id=c.get('case_id'),kind=kind,config=c,result_path=result_file))
        return output

    def switch_case(path, expected_identity=None):
        nonlocal lab,case,overview,scope_suspended
        if scope_job.running():
            raise ValueError('Cancel or finish the scope comparison before switching cases')
        with job.lock:
            if job.state and job.state['status']=='running':
                raise ValueError('Cancel or finish the search before switching cases')
        new_lab=Lab(path,geometry_path)
        try:
            if expected_identity is not None:
                from .replay import _identity
                if _identity(new_lab.case)!=expected_identity:
                    raise ValueError('Task result scope/index/model identity changed; numerical result is still available through local-result CLI')
            new_overview=case_overview(new_lab.case)
        except Exception:
            new_lab.close()
            raise
        if lab is not None:
            lab.close()
        lab=new_lab
        case=lab.case
        overview=new_overview
        scope_suspended=False
        state.update(last=None,run_id=None,comparison=None,comparison_id=None,pathways=None,pathways_id=None,
                     timing_report=None,timing_source=None,replay=None,replay_id=None,
                     replay_origin_job_id=None,replay_origin=None,differences=None,difference_id=None,
                     reduction_report=None,reduction_source=None)
        with job.lock:
            job.state=None
        return current_overview()

    response_slot=dict(report=None,report_id=None,artifact_id=None)
    def response_report(payload):
        if payload.get('task_id'):
            report=local_tasks.result(payload['task_id'])
            if report['kind']!='response_exploration':
                raise ValueError('Not a response task')
        elif payload.get('report_id') and payload['report_id']==response_slot['report_id']:
            report=response_slot['report']
        elif payload.get('artifact_id'):
            match=next((a for a in artifacts() if a['id']==payload['artifact_id'] and a['kind']=='response_exploration'),None)
            if not match:
                raise ValueError('Unknown saved response analysis')
            if response_slot['artifact_id']!=match['id']:
                report=responses.load_responses(match['result_path'],case)
                response_slot.update(report=report,report_id=uuid4().hex,artifact_id=match['id'])
            report=response_slot['report']
        else:
            raise ValueError('Select or reopen a response analysis')
        from .replay import _identity
        if _identity(case)!={k:report.get(k) for k in _identity(case)}:
            raise ValueError('Response scope changed; reopen its scope')
        return report

    operation_reports={} 
    def operation_report(payload):
        if payload.get('task_id'):
            report=local_tasks.result(payload['task_id'])
            from .replay import _identity
            if report['kind']!='operation_search' or _identity(case)!={k:report.get(k) for k in _identity(case)}:
                raise ValueError('Operation task scope mismatch')
            return report
        key=payload.get('report_id')
        if key in operation_reports:
            return operation_reports[key]
        match=next((a for a in artifacts() if a['id']==payload.get('artifact_id') and a['kind']=='operation_search'),None)
        if not match:
            raise ValueError('Select a completed search or reopen its saved report')
        if len(operation_reports)>=8:
            raise ValueError('Save the current operation report before preparing more plans; live report limit is 8')
        from .operation_search import load_operation_search
        report=load_operation_search(match['result_path'])
        if report['case_id']!=case['manifest']['case_id']:
            raise ValueError('Operation report scope mismatch')
        operation_reports[match['id']]=report
        return report

    def global_workspace():
        if workspace is None:
            raise ValueError(f'Index unavailable at {index_root}: {index_error}. Select an existing compatible processed index with --index; no data was rebuilt.')
        return workspace

    def grouping_scope(definition):
        """Only configured complete scopes are eligible for exact CSR reuse."""
        w=global_workspace()
        if definition.get('mode','global')=='case':
            if lab is None:
                raise ValueError('Open a saved calculation scope first')
            if case['manifest'].get('source_index_id')!=w.index.manifest['index_id']:
                raise ValueError('Current scope belongs to a different index')
            return lab.case_path,None
        reuse=None
        for saved in cases():
            if saved['source_index_id']!=w.index.manifest['index_id']:
                continue
            manifest=json.loads((saved['path']/'manifest.json').read_text(encoding='utf-8'))
            if (manifest.get('format')=='csr-arrays-v1' and
                saved['node_count']==w.index.manifest.get('category_counts',{}).get('neuron')):
                reuse=saved['path']
                break
        return None,reuse

    def group_room():
        # A small number of live structural analyses; saved layers can be read
        # lazily again without rescanning the graph. Never deep-copy arrays.
        live=[slot for slot in group_reports.values() if slot['report'] is not None]
        if len(live)>=8:
            reusable=next((slot for slot in live if slot['path']),None)
            if reusable is None:
                raise ValueError('Save a grouping before opening more analysis layers')
            reusable['report']=None

    def retain_group(report, path=None):
        group_room()
        reference=uuid4().hex
        group_reports[reference]=dict(report=report,path=path)
        return dict(grouping.group_summary(report),report_id=reference)

    def owned_group(reference):
        slot=group_reports.get(reference)
        if slot is None:
            raise ValueError('Unknown grouping result; reopen its saved analysis')
        if slot['report'] is None:
            group_room()
            slot['report']=grouping.load_grouping(slot['path'],index=global_workspace().index)
        return slot['report']

    def source_task_snapshot(job_id,kind):
        snapshot=job.source_snapshot(job_id,kind,state['replay_origin_job_id'],state['replay_origin'])
        report=snapshot['result']
        if report is not None and (report.get('case_id')!=case['manifest']['case_id'] or report.get('model_version')!=MODEL_VERSION):
            raise ValueError('Source task case/model identity changed')
        return snapshot

    def timing_report(payload):
        """Resolve only a server-owned job or saved artifact, never client metrics."""
        if bool(payload.get('job_id'))==bool(payload.get('artifact_id')):
            raise ValueError('Select one completed timing job or saved artifact')
        if payload.get('job_id'):
            snapshot=source_task_snapshot(payload['job_id'],'timing_exploration')
            if snapshot.get('kind')!='timing_exploration' or snapshot['status']=='running' or snapshot['result'] is None:
                raise ValueError('Wait for the timing exploration result')
            report=snapshot['result']
        else:
            source=payload['artifact_id']
            artifact=next((a for a in artifacts() if a['id']==source),None)
            if not artifact or artifact['kind']!='timing_exploration' or artifact['case_id']!=case['manifest']['case_id']:
                raise ValueError('Select a saved timing exploration in this scope')
            report=state['timing_report'] if state['timing_source']==source else json.loads(artifact['result_path'].read_text(encoding='utf-8'))
        if report.get('case_id')!=case['manifest']['case_id'] or report.get('model_version')!=MODEL_VERSION:
            raise ValueError('Timing exploration case/model mismatch')
        return report

    def retain_timing_report(payload,report):
        # Reading saved results never rewrites the original artifact. A later
        # explicit save creates a new record including on-demand curve counts.
        if payload.get('job_id'):
            with job.lock:
                retained=False
                if job.state and job.state['job_id']==payload['job_id'] and job.state['kind']=='timing_exploration':
                    job.state['result']=report
                    retained=True
                if payload['job_id']==state['replay_origin_job_id'] and state['replay_origin'].get('kind')=='timing_exploration':
                    state['replay_origin']=report
                    retained=True
                if not retained:
                    raise ValueError('Timing job changed')
        else:
            state.update(timing_report=report,timing_source=payload['artifact_id'])

    def replay_source(payload):
        """Bind a trusted result and selection; never accept editor experiments."""
        handle=payload.get('source')
        if not isinstance(handle,dict):
            raise ValueError('Select an existing result for replay')
        allowed={'kind','run_id','comparison_id','artifact_id','job_id','condition_name','body_ids','start','duration','replay_id','difference_id','task_id'}
        if set(handle)-allowed:
            raise ValueError('Unknown replay source fields')
        request=dict(payload.get('request') or {})
        for name in ('condition_name','body_ids','start','duration','task_id'):
            if name in handle:
                if name in request and request[name]!=handle[name]:
                    raise ValueError('Replay selection conflicts with its source')
                request[name]=handle[name]
        kind=handle.get('kind')
        if kind=='run':
            if not state['last'] or handle.get('run_id')!=state['run_id']:
                raise ValueError('Run result is no longer available; open its saved result')
            source=state['last']
        elif kind=='comparison':
            if not state['comparison'] or handle.get('comparison_id')!=state['comparison_id']:
                raise ValueError('Comparison result changed; select its saved result')
            source=state['comparison']
        elif kind in ('replay','difference'):
            result=owned_replay(handle) if kind=='replay' else owned_differences(handle)
            # Keep exact numerical definition independent of source files. A
            # bounded replay may supply reusable history but never full stats.
            source=dict(result['config']['source_result'])
            source['analysis_source']=dict(kind=result['kind'],config=result['config'])
            if kind=='replay':
                source.update(states=result['states'],recording_metadata=result['recording_metadata'])
            else:
                source['_difference_result']=result
        elif kind in ('timing','joint','reduction') and handle.get('job_id'):
            task_kind={'timing':'timing_exploration','joint':'joint_search','reduction':'plan_reduction'}[kind]
            if handle['job_id']==state['replay_origin_job_id']:
                source=state['replay_origin']
                if source.get('kind')!=task_kind:
                    raise ValueError('Source task kind does not match the selected result')
            else:
                source=job.owned_result(handle['job_id'],task_kind)
                # The shared task controller replaces its last result when
                # preparation begins. Keep one trusted origin, by reference,
                # so returning to that result can select another fixed plan.
                state.update(replay_origin_job_id=handle['job_id'],replay_origin=source)
        elif kind in ('artifact','timing','joint','reduction') and handle.get('artifact_id'):
            artifact=next((a for a in artifacts() if a['id']==handle['artifact_id']),None)
            if artifact and artifact['kind']=='scope_plan_comparison':
                from .scope_plan_comparison import load_scope_plan_comparison,scope_plan_source
                from .replay import _check_source_identity
                source=scope_plan_source(load_scope_plan_comparison(artifact['result_path']),request.get('task_id'))
                _check_source_identity(case,source)
                return source,request
            if not artifact or artifact['case_id']!=case['manifest']['case_id']:
                raise ValueError('Select a saved result in this calculation scope')
            if artifact['kind'] not in ('run','comparison','timing_exploration','joint_search','circuit_replay','scope_differences','search','plan_reduction'):
                raise ValueError('This saved artifact is not a baseline/intervention replay source')
            if artifact['kind']=='search':
                from .analysis_sessions import _source_definition, _check_identity
                header=json.loads(artifact['result_path'].read_text(encoding='utf-8'))
                _check_identity(case,header)
                source=_source_definition(case,header,{k:request[k] for k in ('body_ids',) if k in request})[3]
            elif artifact['kind'] in ('circuit_replay','scope_differences'):
                saved=json.loads(artifact['result_path'].read_text(encoding='utf-8'))
                from .replay import _identity
                if any(saved['config'].get(key)!=value for key,value in _identity(case).items()):
                    raise ValueError('Saved analysis source scope/index/model identity mismatch')
                if artifact['kind']=='circuit_replay':
                    from .replay_sources import read_replay_source
                    source=read_replay_source(artifact['result_path'],case)
                else:
                    source=dict(saved['config']['source_result'])
                source['analysis_source']=dict(kind=artifact['kind'],config=saved['config'],artifact_id=artifact['id'])
            else:
                from .replay_sources import read_saved_source
                source=read_saved_source(artifact['result_path'],request.get('recording',{}).get('max_bytes',64*1024*1024))
        else:
            raise ValueError('Unknown or unavailable replay source')
        return source,request

    def expansion_request(payload):
        config=dict(payload.get('config') or {})
        selected=config.pop('base_case_id',None)
        saved=next((c for c in cases() if c['id']==selected),None) if selected else next((c for c in cases() if c['case_id']==case['manifest']['case_id']),None)
        if not saved or saved['case_id']!=case['manifest']['case_id']:
            raise ValueError('Choose the current saved scope as the retained core')
        return saved['path'],config

    def scope_plan_request(payload):
        from .scope_plan_comparison import resolve_reduction_scope_request
        from .replay import _resolve_source
        selected=payload.get('scope_ids')
        available={c['id']:c for c in cases()}
        if not isinstance(selected,list) or not 2<=len(selected)<=12 or len(set(selected))!=len(selected) or any(i not in available for i in selected):
            raise ValueError('Choose 2..12 distinct saved scopes')
        scopes=[dict(case_id=available[i]['case_id'],case_path=str(available[i]['path'].resolve())) for i in selected]
        source,request=replay_source(payload)
        if source.get('kind')=='plan_reduction':
            return resolve_reduction_scope_request(case,source,scopes,request.get('body_ids'),request.get('condition_name'),
                include_original=payload.get('include_original',True),recording=payload.get('recording',{'mode':'none'}),max_tasks=payload.get('max_tasks'))
        _,cfg,_,_,_= _resolve_source(case,source,request)
        return dict(case_id=case['manifest']['case_id'],source_index_id=case['manifest'].get('source_index_id'),
            model_version=MODEL_VERSION,cases=scopes,experiment=asdict(cfg),
            plans=[dict(plan_id='selected',label='所选方案',body_ids=list(cfg.intervention_ids))],
            recording=payload.get('recording',{'mode':'none'}),max_tasks=payload.get('max_tasks',len(scopes)),
            search_options=source.get('search_options'))

    def reduction_request(payload):
        """Historical sources own protocols; editor requests are explicitly new tasks."""
        from .replay import _resolve_source
        if 'options' not in payload:
            raise ValueError('Define target, protection and evaluation budget first')
        options=SearchOptions.from_dict(payload['options'])
        if options.target_output is None or options.protected_limits is None:
            raise ValueError('Choose an explicit target and protected observation limits')
        if 'source' not in payload:
            return payload['conditions'],payload['body_ids'],options,payload.get('extra_conditions',[])
        if any(k in payload for k in ('conditions','body_ids')):
            raise ValueError('A saved source cannot be replaced by editor protocols or members')
        source,selection=replay_source(payload)
        mode=payload.get('decision_mode','selected')
        if mode not in ('selected','all'):
            raise ValueError('Choose selected or all saved decision protocols')
        names=[item['name'] for item in source.get('conditions',[])]
        if mode=='all' and not names:
            raise ValueError('This source has only one fixed protocol')
        selected=names if mode=='all' else [selection.get('condition_name')]
        conditions=[]
        bodies=None
        for name in selected:
            request=dict(selection)
            if name is not None:
                request['condition_name']=name
            _,cfg,_,_,origin=_resolve_source(case,source,request)
            actual=list(cfg.intervention_ids)
            if bodies is not None and actual!=bodies:
                raise ValueError('Decision protocols must use one exact original set')
            bodies=actual
            conditions.append(dict(name=name or origin.get('condition_name') or '当前方案',experiment=asdict(cfg)))
        return conditions,bodies,options,payload.get('extra_conditions',[])

    def reduction_report(payload):
        from .plan_reduction import load_reduction
        if bool(payload.get('job_id'))==bool(payload.get('artifact_id')):
            raise ValueError('Choose one reduction task or saved report')
        if payload.get('job_id'):
            snapshot=source_task_snapshot(payload['job_id'],'plan_reduction')
            if snapshot['status']=='running' or snapshot['result'] is None:
                raise ValueError('Wait for reduction completion')
            return snapshot['result']
        artifact=next((a for a in artifacts() if a['id']==payload['artifact_id']),None)
        if not artifact or artifact['kind']!='plan_reduction' or artifact['case_id']!=case['manifest']['case_id']:
            raise ValueError('Choose a saved reduction report in this scope')
        if state['reduction_source']==artifact['id']:
            return state['reduction_report']
        return load_reduction(artifact['result_path'],case)

    def retain_reduction(payload,report):
        if payload.get('job_id'):
            with job.lock:
                if job.state and job.state['job_id']==payload['job_id']:
                    job.state['result']=report
                elif state['replay_origin_job_id']==payload['job_id']:
                    state['replay_origin']=report
                else:
                    raise ValueError('Reduction task changed; reopen the saved report')
        else:
            state.update(reduction_report=report,reduction_source=payload['artifact_id'])

    def owned_replay(payload):
        if not state['replay'] or payload.get('replay_id')!=state['replay_id']:
            raise ValueError('Replay changed; reopen its saved result')
        return state['replay']

    def owned_differences(payload):
        if not state['differences'] or payload.get('difference_id')!=state['difference_id']:
            raise ValueError('Difference result changed; reopen its saved result')
        return state['differences']

    def public_task_differences(job_id):
        from .scope_differences import public_differences
        snapshot=job.snapshot(job_id,public_result=public_differences)
        if snapshot.get('kind')!='scope_differences':
            raise ValueError('This is not a node difference preparation task')
        if snapshot['result'] and snapshot['result'].get('ready'):
            result=job.owned_result(job_id,'scope_differences')
            if state['differences'] is not result:
                state.update(differences=result,difference_id=uuid4().hex)
            snapshot['result']['difference_id']=state['difference_id']
        return snapshot

    def public_task_replay(job_id):
        from .replay import public_replay
        snapshot=job.snapshot(job_id,public_result=public_replay)
        if snapshot.get('kind')!='circuit_replay':
            raise ValueError('This is not a replay preparation task')
        if snapshot['result'] and snapshot['result'].get('ready'):
            replay=job.owned_result(job_id,'circuit_replay')
            if state['replay'] is not replay:
                state.update(replay=replay,replay_id=uuid4().hex)
            snapshot['result']['replay_id']=state['replay_id']
        return snapshot

    def ensure_lab():
        nonlocal lab,case,scope_suspended
        if case is None or lab is None:
            raise ValueError('Open or prepare a calculation scope first')
        if scope_job.running():
            raise ValueError('Cancel or finish the scope comparison first')
        if scope_suspended:
            lab=Lab(lab.case_path,geometry_path)
            case=lab.case
            scope_suspended=False

    def public_task_result(result):
        if result is None:
            return None
        clean={key:value for key,value in result.items() if key!='states'}
        if 'results' in clean:
            clean['results']=[{key:value for key,value in item.items() if key!='states'} for item in clean['results']]
        return clean

    def report_source(payload):
        from .api import read_report_source
        if payload.get('comparison_id'):
            if state['comparison'] is None or payload['comparison_id']!=state['comparison_id']:
                raise ValueError('Comparison changed; reopen its saved result')
            saved=state.get('saved_comparison')
            if not saved or saved['comparison_id']!=payload['comparison_id']:
                raise ValueError('Save this fixed-condition comparison before exporting its report')
            return read_report_source(saved['path'])
        artifact=next((a for a in artifacts() if a['id']==payload.get('artifact_id')),None)
        if not artifact or artifact['kind']!='comparison':
            raise ValueError('Choose a saved fixed-condition comparison')
        return read_report_source(artifact['result_path'])

    def task_export(payload):
        from .task_definition import export_task
        from .task_sources import export_saved_task
        ensure_lab()
        name=payload.get('name','当前任务')
        if payload.get('source'):
            source,request=replay_source(payload)
            handle=payload['source']
            if handle.get('artifact_id'):
                artifact=next((item for item in artifacts() if item['id']==handle['artifact_id']),None)
                if artifact and artifact['kind']=='search':
                    # Export the report before replay's canonical fixed-plan
                    # adaptation, which intentionally omits search constraints.
                    from .replay_sources import read_saved_source
                    source=read_saved_source(artifact['result_path'])
            if payload.get('all_conditions'):
                if 'conditions' not in source or not source.get('results'):
                    raise ValueError('Select a completed comparison to export all conditions')
                request=None
            return export_saved_task(case,source,name,request=request,description=payload.get('description',''))
        conditions=payload.get('conditions')
        if not isinstance(conditions,list):
            raise ValueError('Define one or more explicit conditions')
        entries=[dict(item,recording=item.get('recording',payload.get('recording',{'mode':'none'})),
                      role=item.get('role','decision'),search_options=item.get('search_options',payload.get('search_options')))
                 for item in conditions]
        return export_task(case,entries,name,description=payload.get('description',''))

    def suspend_lab():
        nonlocal scope_suspended
        with job.lock:
            if job.state and job.state['status']=='running':
                raise ValueError('Cancel or finish the search before comparing scopes')
        if lab is not None and not scope_suspended:
            lab.close()
            scope_suspended=True
        state.update(last=None,run_id=None)

    def scope_request(payload):
        selected=payload.get('scope_ids')
        if not isinstance(selected,list) or len(set(selected))!=len(selected):
            raise ValueError('Select distinct saved computation scopes')
        available={c['id']:c for c in cases()}
        if any(identifier not in available for identifier in selected):
            raise ValueError('Unknown saved computation scope')
        source=overview['manifest'].get('source_index_id')
        if not source:
            raise ValueError('The current scope has no data index identity')
        cfg=Experiment.from_dict(payload['experiment'])
        if cfg.input_events is None or cfg.observations is None or (cfg.intervention_events is None and not cfg.intervention_ids):
            raise ValueError('Scope comparisons require exact events, observations and intervention IDs')
        return dict(model_version=MODEL_VERSION,source_index_id=source,
            cases=[dict(case_id=available[i]['case_id'],case_path=str(available[i]['path'].resolve())) for i in selected],
            experiment=asdict(cfg),recording=payload.get('recording') or {'mode':'selected'})

    class Handler(LocalRequestHandler):
        def reply(self, status, data, content_type='application/json; charset=utf-8', cache_control='no-store'):
            payload = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
            try:
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Cache-Control', cache_control)
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # Navigation or an obsolete geometry request may close the socket.
                # The completed server-side read remains valid; do not reply twice.
                return

        def local_request(self):
            hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
            if self.headers.get('Host') not in hosts:
                self.reply(403, {'error': 'Local host only'})
                return False
            origin = self.headers.get('Origin')
            if origin and origin not in {f'http://{host}' for host in hosts}:
                self.reply(403, {'error': 'Local origin only'})
                return False
            return True

        def do_GET(self):
            if control.handle(self):
                return
            if not self.local_request():
                return
            parsed = urlparse(self.path)
            if assets.reply(self, parsed.path):
                return
            q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            lock.acquire()
            try:
                if (case is None and parsed.path.startswith('/api/') and
                    not parsed.path.startswith('/api/local-') and
                    not parsed.path.startswith('/api/global/') and
                    not parsed.path.startswith('/api/group-') and
                    not parsed.path.startswith('/api/spatial/') and
                    not parsed.path.startswith('/api/skeleton-cache/') and
                    parsed.path not in ('/api/case','/api/workspace','/api/cases','/api/artifacts','/api/task-job','/api/report-file','/api/search-job')):
                    raise ValueError('Open or prepare a calculation scope first')
                if parsed.path == '/':
                    self.reply(200, html, 'text/html; charset=utf-8')
                elif parsed.path=='/api/local-tasks':
                    self.reply(200,dict(tasks=local_tasks.list(),busy=local_tasks.busy()))
                elif parsed.path=='/api/local-task':
                    self.reply(200,local_tasks.read(q['task_id']))
                elif parsed.path=='/api/report-file':
                    folder=q.get('id','')
                    filename=q.get('file','')
                    if (not folder.startswith('offline-report-') or Path(folder).name!=folder or
                        filename not in ('report.html','metrics.csv','curves.csv')):
                        raise ValueError('Unknown report file')
                    target=run_root/folder/filename
                    if not target.is_file():
                        raise ValueError('Report file is missing')
                    if target.stat().st_size>16777216:
                        raise ValueError('Report file exceeds download limit')
                    self.reply(200,target.read_bytes(),'text/html; charset=utf-8' if filename.endswith('.html') else 'text/csv; charset=utf-8')
                elif parsed.path in ('/api/skeleton-cache/overview','/api/skeleton-cache/catalog'):
                    self.reply(200,global_skeletons().overview(limit=int(q.get('limit',2000)),offset=int(q.get('offset',0))))
                elif parsed.path == '/api/skeleton-cache/detail':
                    data=global_skeletons().detail(q.get('id',''),level=int(q.get('level',0)),cache_id=q.get('cache_id'))
                    if len(data)>16*1024*1024:
                        raise ValueError('Skeleton detail exceeds the 16 MiB transfer budget')
                    self.reply(200,data,'application/octet-stream')
                elif parsed.path == '/api/skeleton-cache/background':
                    store=global_skeletons()
                    if q.get('cache_id')!=store.overview(limit=0)['cache_id']:
                        raise ValueError('Skeleton cache changed; reload geometry overview')
                    data,_metadata=store.background_bytes(max_edges=int(q.get('max_edges',64000)),
                        bounds=json.loads(q['bounds']) if q.get('bounds') else None,
                        planes=json.loads(q['planes']) if q.get('planes') else None)
                    self.reply(200,data,'application/octet-stream')
                elif parsed.path in ('/api/skeleton-cache/job','/api/search-job'):
                    snapshot=job.snapshot(q.get('job_id',q.get('job','')),public_result=public_task_result)
                    if snapshot['kind']!='skeleton_cache':
                        raise ValueError('Not a skeleton preparation task')
                    self.reply(200,snapshot)
                elif parsed.path == '/api/spatial/overview':
                    self.reply(200,global_spatial().overview())
                elif parsed.path == '/api/spatial/chunk':
                    s=global_spatial()
                    if q.get('cache_id')!=s.overview()['cache_id']:
                        raise ValueError('Spatial dataset changed; reload background')
                    self.reply(200,s.chunk(int(q.get('offset',0)),int(q.get('limit',20000))),'application/octet-stream')
                elif parsed.path == '/api/responses-job':
                    snapshot=job.snapshot(q.get('job_id',''),public_result=lambda r:dict(status=r['status']) if r else None)
                    if snapshot['kind'] not in ('response_exploration','response_curves'):
                        raise ValueError('Not a response exploration task')
                    self.reply(200,snapshot)
                elif parsed.path == '/api/operation-search-job':
                    snapshot=job.snapshot(q.get('job_id',''),public_result=public_task_result)
                    if snapshot['kind'] not in ('operation_search','operation_search_curves'):
                        raise ValueError('Not an operation search task')
                    self.reply(200,snapshot)
                elif parsed.path == '/api/operations-job':
                    snapshot=job.snapshot(q.get('job_id',''),public_result=public_task_result)
                    if snapshot['kind']!='operations_comparison':
                        raise ValueError('Not an operations comparison task')
                    self.reply(200,snapshot)
                elif parsed.path == '/api/group-fields':
                    fields=global_workspace().index.filter_fields
                    self.reply(200,dict(fields=[field for field in grouping.FIELDS if field in fields],
                        annotation_fields=[field for field in fields if field not in ('bodyId','q','category')]))
                elif parsed.path == '/api/group-job':
                    snapshot=job.snapshot(q.get('job_id',''),public_result=grouping.group_summary)
                    if snapshot['kind']!='group_connections':
                        raise ValueError('Not a grouping task')
                    self.reply(200,snapshot)
                elif parsed.path == '/api/group-page':
                    self.reply(200,grouping.group_page(owned_group(q.get('report_id','')),
                        q=q.get('q',''),sort=q.get('sort','name'),offset=int(q.get('offset',0)),limit=int(q.get('limit',30))))
                elif parsed.path == '/api/group-relations':
                    self.reply(200,grouping.group_relations(owned_group(q.get('report_id','')),
                        int(q['group_id']),direction=q.get('direction','outgoing'),limit=int(q.get('limit',50))))
                elif parsed.path == '/api/group-features':
                    self.reply(200,grouping.compare_group_features(owned_group(q.get('report_id','')),
                        int(q['a']),int(q['b']),direction=q.get('direction','outgoing')))
                elif parsed.path == '/api/group-similar':
                    self.reply(200,grouping.similar_groups(owned_group(q.get('report_id','')),
                        int(q['group_id']),direction=q.get('direction','outgoing'),limit=int(q.get('limit',50))))
                elif parsed.path == '/api/group-pair':
                    self.reply(200,global_workspace().group_pair(owned_group(q.get('report_id','')),
                        int(q['a']),int(q['b']),offset=int(q.get('offset',0)),limit=int(q.get('limit',100)),
                        scan_limit=int(q.get('scan_limit',1000000))))
                elif parsed.path == '/api/global/info':
                    w=global_workspace()
                    self.reply(200,dict(manifest=w.index.manifest,filter_fields=w.index.filter_fields))
                elif parsed.path == '/api/global/node':
                    self.reply(200,dict(node=global_workspace().index.node(q.get('id',''))))
                elif parsed.path == '/api/global/neighbors':
                    self.reply(200,global_workspace().index.neighbors(q.get('id',''),q.get('direction','incoming'),int(q.get('limit',100)),int(q.get('offset',0))))
                elif parsed.path == '/api/cases':
                    self.reply(200,dict(cases=[{k:v for k,v in c.items() if k!='path'} for c in cases()]))
                elif parsed.path == '/api/artifacts':
                    self.reply(200,dict(artifacts=[{k:v for k,v in a.items() if k not in ('config','result_path','result')} for a in artifacts()]))
                elif parsed.path == '/api/case':
                    self.reply(200,current_overview())
                elif parsed.path == '/api/workspace':
                    self.reply(200,workspace_summary())
                elif parsed.path == '/data-settings':
                    from .preparation_app import settings_html
                    self.reply(200,settings_html(preparation_paths,token,configuration_path,back=True),'text/html; charset=utf-8')
                elif parsed.path == '/api/preparation':
                    self.reply(200,check_preparation(preparation_paths))
                elif parsed.path == '/api/task-job':
                    snapshot=job.snapshot(q.get('job_id',''),public_result=public_task_result)
                    if snapshot['kind'] not in ('task_prepare','task_run'):
                        raise ValueError('Not a portable task operation')
                    self.reply(200,snapshot)
                elif parsed.path == '/api/connections':
                    ensure_lab()
                    self.reply(200, connections(case, q.get('source_role', 'internal'), q.get('source', 'KCg-m'),
                                                 q.get('target_role', 'output'), q.get('target', 'MBON01')))
                elif parsed.path == '/api/node':
                    ensure_lab()
                    self.reply(200, node_detail(case, q.get('id', '')))
                elif parsed.path == '/api/geometry':
                    ensure_lab()
                    self.reply(200, lab.geometry.overview())
                elif parsed.path == '/api/skeleton':
                    ensure_lab()
                    self.reply(200, lab.geometry.skeleton(q.get('id','')))
                elif parsed.path == '/api/search':
                    snapshot=job.snapshot(q.get('job_id',''))
                    if snapshot.get('kind')!='search':
                        raise ValueError('This is not a single-protocol search job')
                    self.reply(200,snapshot)
                elif parsed.path == '/api/joint-search':
                    snapshot=source_task_snapshot(q.get('job_id',''),'joint_search')
                    if snapshot.get('kind')!='joint_search':
                        raise ValueError('This is not a joint search job')
                    self.reply(200,snapshot)
                elif parsed.path == '/api/timing-explore':
                    snapshot=source_task_snapshot(q.get('job_id',''),'timing_exploration')
                    if snapshot.get('kind')!='timing_exploration':
                        raise ValueError('This is not a timing exploration job')
                    self.reply(200,snapshot)
                elif parsed.path == '/api/timing-report':
                    with lock:
                        self.reply(200,timing_report(q))
                elif parsed.path == '/api/reduction-job':
                    snapshot=source_task_snapshot(q.get('job_id',''),'plan_reduction')
                    if snapshot.get('kind')!='plan_reduction':
                        raise ValueError('This is not a reduction task')
                    self.reply(200,snapshot)
                elif parsed.path in ('/api/expansion-job','/api/scope-plan-job'):
                    snapshot=job.snapshot(q.get('job_id',''))
                    expected='scope_expansion' if parsed.path=='/api/expansion-job' else 'scope_plan_comparison'
                    if snapshot.get('kind')!=expected:
                        raise ValueError('Task type mismatch')
                    self.reply(200,snapshot)
                elif parsed.path == '/api/replay-task':
                    self.reply(200,public_task_replay(q.get('job_id','')))
                elif parsed.path == '/api/difference-task':
                    self.reply(200,public_task_differences(q.get('job_id','')))
                elif parsed.path == '/api/difference-rows':
                    ensure_lab()
                    flag=q.get('hide_endpoints','true')
                    if flag not in ('true','false'):
                        raise ValueError('hide_endpoints must be true or false')
                    self.reply(200,lab.difference_rows(owned_differences(q),sort=q.get('sort','absolute'),
                        body_id=q.get('body_id',''),type_filter=q.get('type_filter',''),hide_endpoints=flag=='true',
                        offset=int(q.get('offset','0')),limit=int(q.get('limit','50'))))
                elif parsed.path == '/api/difference-node':
                    ensure_lab()
                    self.reply(200,lab.difference_node(owned_differences(q),q.get('id','')))
                elif parsed.path == '/api/difference-neighbors':
                    ensure_lab()
                    self.reply(200,lab.difference_neighbors(owned_differences(q),q.get('id',''),
                        direction=q.get('direction','both'),offset=int(q.get('offset','0')),limit=int(q.get('limit','50'))))
                elif parsed.path == '/api/replay-frame':
                    ensure_lab()
                    self.reply(200,lab.replay_frame(owned_replay(q),int(q.get('step','0'))))
                elif parsed.path == '/api/replay-node':
                    ensure_lab()
                    self.reply(200,lab.replay_node(owned_replay(q),q.get('id','')))
                elif parsed.path == '/api/replay-edge':
                    ensure_lab()
                    self.reply(200,lab.replay_edge(owned_replay(q),q.get('id',''),int(q.get('step','0'))))
                elif parsed.path == '/api/replay-summary':
                    ensure_lab()
                    self.reply(200,lab.replay_summary(owned_replay(q),
                        dict(start=int(q.get('start','0')),stop=int(q.get('stop','0'))),int(q.get('limit','100'))))
                elif parsed.path == '/api/scope-compare':
                    self.reply(200,scope_job.snapshot(q.get('job_id','')))
                elif parsed.path == '/api/activity':
                    with lock:
                        if state['last'] is None or q.get('run_id') != state['run_id']:
                            raise ValueError('Activity belongs to a different run; run again')
                        t=int(q.get('step','0'))
                        result=state['last']
                        b,i=result['states']
                        metadata=result['recording_metadata']
                        if t not in metadata['time_steps']:
                            raise ValueError('This time step was not recorded')
                        row=metadata['time_steps'].index(t)
                        self.reply(200,dict(run_id=state['run_id'],step=t,
                            nodes=[dict(bodyId=body,baseline=float(b[row,k]),intervention=float(i[row,k]),
                                        delta=float(i[row,k]-b[row,k])) for k,body in enumerate(metadata['body_ids'])]))
                elif parsed.path == '/favicon.ico':
                    self.reply(204, b'')
                else:
                    self.reply(404, {'error': 'Unknown endpoint'})
            except (ValueError, KeyError, TypeError, OSError, MemoryError) as error:
                self.reply(400, error_payload(error))
            finally:
                lock.release()

        def do_POST(self):
            if control.handle(self):
                return
            if not self.local_request():
                return
            if self.headers.get('X-Local-Token') != token:
                self.reply(403, {'error': 'Refresh this local page before running'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                task_body = self.path.startswith('/api/task-') or self.path in (
                    '/api/start-task-prepare','/api/start-task-run','/api/open-task-scope')
                task_body=task_body or self.path.startswith('/api/group-') or self.path in (
                    '/api/global/scope','/api/create-case','/api/global/pathways')
                task_body=task_body or self.path.startswith('/api/local-')
                task_body=task_body or self.path.startswith('/api/responses-') or self.path.startswith('/api/operation-search-') or self.path.startswith('/api/intervention-') or self.path.startswith('/api/operations-')
                task_body=task_body or self.path.startswith('/api/spatial/') or self.path.startswith('/api/skeleton-cache/') or self.path=='/api/save-analysis-session'
                limit = 16777216 if task_body else 1048576
                if not 0 < length <= limit:
                    raise ValueError(f'Expected a JSON body of at most {limit // 1048576} MiB')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('Expected a JSON object')
                from contextlib import nullcontext
                if rebind:
                    raise ValueError('Workspace is switching; wait for it to open')
                if self.path in ('/api/preparation/check','/api/preparation/open','/api/preparation/forget'):
                    from .preparation_app import binding_operation
                    with lock:
                        if control.stopping:
                            raise ValueError('Service is stopping')
                        if self.path.endswith('/open'):
                            with job.lock:
                                running=bool(job.state and job.state['status']=='running')
                            if running or scope_job.running() or local_tasks.busy():
                                self.reply(409,dict(code='workspaceBusy'))
                                return
                        result,binding=binding_operation(self.path.rsplit('/',1)[-1],payload)
                        self.reply(400 if result.get('code') else 200,result)
                        if binding:
                            rebind.update(binding)
                    if binding:
                        server.shutdown()
                    return
                heavy=self.path in ('/api/run','/api/compare','/api/select','/api/sensitivity','/api/joint-evaluate')
                with lock, (LocalSlot(local_tasks.root) if heavy else nullcontext()):
                    if control.stopping:
                        raise ValueError('Service is stopping')
                    scope_free=('/api/global/find','/api/global/scope','/api/create-case','/api/open-case','/api/reopen',
                        '/api/task-preview','/api/start-task-prepare','/api/open-task-scope','/api/cancel-task',
                        '/api/report-preview','/api/report-export','/api/global/pathways','/api/save-pathways')
                    if case is None and not self.path.startswith('/api/local-') and self.path not in scope_free and not self.path.startswith('/api/group-') and not self.path.startswith('/api/spatial/') and not self.path.startswith('/api/skeleton-cache/'):
                        raise ValueError('Open or prepare a calculation scope first')
                    boundary_routes=('/api/boundary','/api/boundary-external','/api/expansion-preview','/api/start-expansion',
                        '/api/cancel-expansion','/api/save-expansion','/api/scope-plan-preview','/api/start-scope-plan-comparison',
                        '/api/cancel-scope-plan-comparison','/api/save-scope-plan-comparison','/api/open-scope-plan-result')
                    if self.path in boundary_routes and self.headers.get('X-Case-Id')!=case['manifest']['case_id']:
                        raise ValueError('Calculation scope changed; refresh this page')
                    with job.lock:
                        active_kind=job.state['kind'] if job.state and job.state['status']=='running' else None
                    if self.path.startswith('/api/responses-') and self.headers.get('X-Case-Id')!=case['manifest']['case_id']:
                        raise ValueError('Calculation scope changed; refresh this page')
                    if active_kind in ('response_exploration','response_curves') and self.path!='/api/responses-cancel':
                        raise ValueError('Cancel or finish response exploration first')
                    if active_kind in ('task_prepare','task_run') and self.path!='/api/cancel-task':
                        raise ValueError('Cancel or finish the current task first')
                    if active_kind=='group_connections' and self.path!='/api/group-cancel':
                        raise ValueError('Cancel or finish the grouping task first')
                    if active_kind in ('operation_search','operation_search_curves') and self.path!='/api/operation-search-cancel':
                        raise ValueError('Cancel or finish the operation search task first')
                    if active_kind=='operations_comparison' and self.path!='/api/operations-cancel':
                        raise ValueError('Cancel or finish the operations comparison first')
                    if active_kind in ('scope_expansion','scope_plan_comparison'):
                        permitted='/api/cancel-expansion' if active_kind=='scope_expansion' else '/api/cancel-scope-plan-comparison'
                        if self.path!=permitted:
                            raise ValueError('Cancel or finish the current scope task first')
                    if self.path in ('/api/run','/api/select','/api/compare','/api/export','/api/search',
                                     '/api/intervention-preview','/api/intervention-edges','/api/operations-compare',
                                     '/api/operations-result','/api/operations-cancel',
                                     '/api/operation-search-preview','/api/operation-search-start','/api/operation-search-result',
                                     '/api/operation-search-save','/api/operation-search-curves','/api/operation-search-cancel',
                                     '/api/save','/api/save-comparison','/api/save-search',
                                     '/api/pathways','/api/save-pathways','/api/recording-preview',
                                     '/api/search-candidates','/api/scope-preview','/api/scope-compare',
                                     '/api/joint-search-preview','/api/joint-search','/api/save-joint-search',
                                     '/api/joint-evaluate','/api/cancel-joint-search',
                                     '/api/search-context','/api/joint-search-context',
                                     '/api/timing-preview','/api/timing-explore','/api/timing-curves',
                                     '/api/save-timing','/api/cancel-timing',
                                     '/api/reduction-preview','/api/start-reduction','/api/reduction-curves','/api/save-reduction','/api/cancel-reduction',
                                     '/api/replay-preview','/api/replay-prepare','/api/cancel-replay','/api/save-replay',
                                     '/api/difference-preview','/api/difference-prepare','/api/cancel-differences','/api/save-differences','/api/save-analysis-session',
                                     '/api/difference-replay-preview','/api/difference-replay-prepare','/api/difference-pathways',
                                     '/api/task-export','/api/start-task-run','/api/task-result'):
                        if self.headers.get('X-Case-Id')!=case['manifest']['case_id']:
                            raise ValueError('Calculation scope changed in another page; reopen or refresh the case')
                    if scope_job.running() and self.path not in ('/api/cancel-scope-compare',):
                        raise ValueError('Cancel or finish the scope comparison first')
                    with job.lock:
                        joint_running=bool(job.state and job.state.get('kind')=='joint_search' and job.state['status']=='running')
                        timing_running=bool(job.state and job.state.get('kind')=='timing_exploration' and job.state['status']=='running')
                        replay_running=bool(job.state and job.state.get('kind')=='circuit_replay' and job.state['status']=='running')
                        difference_running=bool(job.state and job.state.get('kind')=='scope_differences' and job.state['status']=='running')
                        reduction_running=bool(job.state and job.state.get('kind')=='plan_reduction' and job.state['status']=='running')
                    if reduction_running and self.path!='/api/cancel-reduction':
                        raise ValueError('Cancel or finish the reduction analysis first')
                    if joint_running and self.path not in ('/api/cancel-joint-search',):
                        raise ValueError('Cancel or finish the joint search first')
                    if timing_running and self.path!='/api/cancel-timing':
                        raise ValueError('Cancel or finish the timing exploration first')
                    if replay_running and self.path!='/api/cancel-replay':
                        raise ValueError('Cancel or finish replay preparation first')
                    if difference_running and self.path!='/api/cancel-differences':
                        raise ValueError('Cancel or finish node difference preparation first')
                    if self.path in ('/api/run','/api/select','/api/compare','/api/export','/api/search',
                                     '/api/pathways','/api/recording-preview','/api/search-candidates',
                                     '/api/joint-search-preview','/api/joint-search','/api/joint-evaluate',
                                     '/api/search-context','/api/joint-search-context',
                                     '/api/timing-preview','/api/timing-explore','/api/timing-curves',
                                     '/api/reduction-preview','/api/start-reduction','/api/reduction-curves',
                                     '/api/replay-preview','/api/replay-prepare','/api/save-replay',
                                     '/api/difference-preview','/api/difference-prepare','/api/save-differences','/api/save-analysis-session',
                                     '/api/difference-replay-preview','/api/difference-replay-prepare','/api/difference-pathways'):
                        ensure_lab()
                    if self.path in boundary_routes:
                        ensure_lab()
                    if self.path.startswith('/api/skeleton-cache/'):
                        store=global_skeletons()
                        if self.path=='/api/skeleton-cache/view':
                            self.reply(200,store.query_view(payload.get('bounds'),
                                limit=payload.get('limit',512),cache_id=payload.get('cache_id'),
                                planes=payload.get('planes')))
                        elif self.path=='/api/skeleton-cache/locate':
                            self.reply(200,store.locate(payload.get('body_ids',[])))
                        elif self.path=='/api/skeleton-cache/update':
                            allowed={'max_files','max_input_mib','max_cache_mib'}
                            if set(payload)-allowed:
                                raise ValueError('Unsupported skeleton preparation option')
                            mib=payload.get('max_input_mib',512)
                            if type(mib) not in (int,float) or not math.isfinite(mib) or not 1<=mib<=8192:
                                raise ValueError('Skeleton input budget must be 1..8192 MiB')
                            cache_mib=payload.get('max_cache_mib',2048)
                            if type(cache_mib) not in (int,float) or not math.isfinite(cache_mib) or not 1<=cache_mib<=16384:
                                raise ValueError('Skeleton cache budget must be 1..16384 MiB')
                            options=dict(max_files=payload.get('max_files'),max_bytes=int(mib*1024*1024),
                                max_cache_bytes=int(cache_mib*1024*1024))
                            self.reply(200,job._start(lambda cancel,progress:store.prepare(
                                **options,cancel=cancel,progress=progress),'skeleton_cache'))
                        elif self.path=='/api/skeleton-cache/cancel':
                            snapshot=job.snapshot(payload.get('job_id',''),public_result=lambda r:None)
                            if snapshot['kind']!='skeleton_cache':
                                raise ValueError('Not a skeleton preparation task')
                            self.reply(200,job.cancel(payload['job_id']))
                        else:
                            raise ValueError('Unknown skeleton operation')
                    elif self.path.startswith('/api/spatial/'):
                        s=global_spatial()
                        if payload.get('source_index_id')!=s.identity['source_index_id']:
                            raise ValueError('Spatial index identity changed')
                        if self.path=='/api/spatial/locate':
                            result=s.locate(payload.get('body_ids',[]))
                        elif self.path=='/api/spatial/query':
                            ids=global_workspace().index.ids_for(payload.get('filters',{}),max_count=200000)
                            result=dict(body_ids=[str(b) for b in ids],member_count=len(ids))
                        elif self.path=='/api/spatial/filter':
                            result=s.filter(payload.get('field'),payload.get('value'))
                        elif self.path=='/api/spatial/edges':
                            result=s.edges(payload.get('edges',[]),payload.get('max_edges',2000))
                        elif self.path=='/api/spatial/geometry':
                            result=s.geometry(payload.get('body_ids',[]),bool(payload.get('load',False)))
                        else:
                            raise ValueError('Unknown spatial operation')
                        self.reply(200,result)
                    elif self.path in ('/api/group-preview','/api/group-start'):
                        definition=payload.get('definition',{})
                        if not isinstance(definition,dict):
                            raise ValueError('Expected a grouping definition')
                        if definition.get('mode')=='case' and (case is None or self.headers.get('X-Case-Id')!=case['manifest']['case_id']):
                            raise ValueError('Calculation scope changed; refresh this page')
                        selected,reuse=grouping_scope(definition)
                        w=global_workspace()
                        preview=w.preview_grouping(definition,case_path=selected,reuse_case_path=reuse)
                        if self.path=='/api/group-preview':
                            self.reply(200,preview)
                        else:
                            if not preview['build_allowed']:
                                raise ValueError('; '.join(preview['errors']))
                            self.reply(200,job._start(lambda cancel,progress:w.aggregate_groups(definition,
                                case_path=selected,reuse_case_path=reuse,cancel=cancel,progress=progress),'group_connections'))
                    elif self.path=='/api/group-cancel':
                        snapshot=job.snapshot(payload.get('job_id',''),public_result=grouping.group_summary)
                        if snapshot['kind']!='group_connections':
                            raise ValueError('Not a grouping task')
                        self.reply(200,job.cancel(payload['job_id']))
                    elif self.path=='/api/group-result':
                        reference=group_jobs.get(payload.get('job_id',''))
                        if reference is None:
                            summary=retain_group(job.owned_result(payload.get('job_id',''),'group_connections'))
                            reference=summary['report_id']
                            group_jobs[payload['job_id']]=reference
                        self.reply(200,dict(grouping.group_summary(owned_group(reference)),report_id=reference))
                    elif self.path=='/api/group-matrix':
                        self.reply(200,grouping.matrix_page(owned_group(payload.get('report_id','')),
                            payload.get('source_ids',[]),payload.get('target_ids',[])))
                    elif self.path=='/api/group-members':
                        self.reply(200,global_workspace().group_members(owned_group(payload.get('report_id','')),
                            payload.get('group_ids',[]),filters=payload.get('filters')))
                    elif self.path=='/api/group-save':
                        reference=payload.get('report_id','')
                        report=owned_group(reference)
                        saved=grouping.save_grouping(run_root,report)
                        group_reports[reference]['path']=saved['path']
                        self.reply(200,saved)
                    elif self.path=='/api/report-preview':
                        from .api import preview_result_report
                        source=report_source(payload)
                        names=payload.get('condition_names')
                        language=payload.get('language','en')
                        metadata=preview_result_report(source,condition_names=names,language=language,include_html=True)
                        preview_id=uuid4().hex
                        state['report_preview']=dict(preview_id=preview_id,comparison_id=payload.get('comparison_id'),
                            artifact_id=payload.get('artifact_id'),condition_names=names,language=language,sizes=metadata['sizes'])
                        self.reply(200,dict(metadata,preview_id=preview_id))
                    elif self.path=='/api/report-export':
                        from .api import preview_result_report,export_result_report
                        checked=state.get('report_preview') or {}
                        if (not payload.get('preview_id') or checked.get('preview_id')!=payload['preview_id'] or
                            any(checked.get(key)!=payload.get(key) for key in ('comparison_id','artifact_id','condition_names')) or checked.get('language')!=payload.get('language','en')):
                            from .ui_errors import DisplayError
                            raise DisplayError('report_preview_required','Preview the selected report and language before exporting')
                        source=report_source(payload)
                        names=payload.get('condition_names')
                        language=payload.get('language','en')
                        if preview_result_report(source,condition_names=names,language=language)['sizes']!=checked['sizes']:
                            raise ValueError('Saved result changed; preview again')
                        directory='offline-report-'+uuid4().hex[:16]
                        result=export_result_report(source,run_root/directory,condition_names=names,language=language)
                        self.reply(200,dict(id=directory,language=language,sizes=result['sizes'],
                            files={name:'/api/report-file?'+urlencode(dict(id=directory,file=name)) for name in result['sizes']}))
                    elif self.path=='/api/task-export':
                        self.reply(200,task_export(payload))
                    elif self.path=='/api/task-preview':
                        self.reply(200,global_workspace().preview_task(payload['definition'],budgets=payload.get('budgets')))
                    elif self.path=='/api/start-task-prepare':
                        w=global_workspace()
                        definition=payload['definition']
                        budgets=payload.get('budgets')
                        preview=w.preview_task(definition,budgets=budgets)
                        if not preview.get('build_allowed',preview.get('compatible')):
                            raise ValueError('; '.join(preview.get('errors',[])) or 'Task cannot be prepared')
                        self.reply(200,job._start(lambda cancel,progress:w.prepare_task(definition,budgets=budgets,cancel=cancel,progress=progress),'task_prepare'))
                    elif self.path=='/api/open-task-scope':
                        if 'job_id' in payload:
                            result=job.owned_result(payload['job_id'],'task_prepare')
                            if result.get('status')!='complete' or not result.get('case_path'):
                                raise ValueError('Task scope has not completed preparation')
                            path=result['case_path']
                        else:
                            preview=global_workspace().preview_task(payload['definition'])
                            if not preview['compatible'] or preview['errors'] or not preview.get('existing_case_path'):
                                raise ValueError('; '.join(preview['errors']) or 'Prepare the exact task scope first')
                            path=preview['existing_case_path']
                        self.reply(200,switch_case(path))
                    elif self.path=='/api/start-task-run':
                        ensure_lab()
                        w=global_workspace()
                        definition=payload['definition']
                        path=lab.case_path
                        from .task_definition import validate_task_case
                        validate_task_case(case,definition,lab.case_path)
                        self.reply(200,job._start(lambda cancel,progress:w.run_task(path,definition,cancel=cancel,progress=progress),'task_run'))
                    elif self.path=='/api/task-result':
                        result=job.owned_result(payload['job_id'],'task_run')
                        if result.get('results'):
                            state.update(comparison=result,comparison_id=uuid4().hex)
                            self.reply(200,dict(public_task_result(result),comparison_id=state['comparison_id']))
                        else:
                            self.reply(200,public_task_result(result))
                    elif self.path=='/api/cancel-task':
                        snapshot=job.snapshot(payload['job_id'],public_result=public_task_result)
                        if snapshot['kind'] not in ('task_prepare','task_run'):
                            raise ValueError('Not a portable task operation')
                        self.reply(200,job.cancel(payload['job_id']))
                    elif self.path=='/api/boundary':
                        if payload.get('source'):
                            from .replay import _resolve_source
                            source,request=replay_source(payload)
                            _,cfg,_,_,_=_resolve_source(case,source,request)
                        else:
                            cfg=fixed_experiment(payload['experiment'])
                        self.reply(200,global_workspace().boundary(case,cfg,payload.get('node_ids')))
                    elif self.path=='/api/boundary-external':
                        self.reply(200,global_workspace().external_inputs(case,payload['body_ids'],**{key:payload[key] for key in ('category','scan_limit','limit','offset') if key in payload}))
                    elif self.path in ('/api/expansion-preview','/api/start-expansion'):
                        base_path,config=expansion_request(payload)
                        preview=global_workspace().preview_expansion(base_path,config)
                        if self.path=='/api/expansion-preview':
                            self.reply(200,preview)
                        else:
                            if not preview['build_allowed']:
                                raise ValueError('Expansion preflight refused construction: '+json.dumps([r['errors'] for r in preview['levels']],ensure_ascii=False))
                            self.reply(200,job._start(lambda cancel,progress:global_workspace().build_expansion(base_path,config,cancel=cancel,progress=progress),'scope_expansion'))
                    elif self.path in ('/api/scope-plan-preview','/api/start-scope-plan-comparison'):
                        config=scope_plan_request(payload)
                        preview=global_workspace().preview_scope_plans(config)
                        if self.path=='/api/scope-plan-preview':
                            self.reply(200,preview)
                        else:
                            if not preview['compatible']:
                                raise ValueError('Scope compatibility failed: '+'; '.join(preview['errors']))
                            suspend_lab()
                            self.reply(200,job._start(lambda cancel,progress:global_workspace().compare_scope_plans(config,cancel=cancel,progress=progress),'scope_plan_comparison'))
                    elif self.path in ('/api/cancel-expansion','/api/cancel-scope-plan-comparison'):
                        expected='scope_expansion' if self.path=='/api/cancel-expansion' else 'scope_plan_comparison'
                        snapshot=job.snapshot(payload['job_id'])
                        if snapshot['kind']!=expected:
                            raise ValueError('Task type mismatch')
                        self.reply(200,job.cancel(payload['job_id']))
                    elif self.path in ('/api/save-expansion','/api/save-scope-plan-comparison'):
                        from .scope_expansion import save_expansion
                        from .scope_plan_comparison import save_scope_plan_comparison
                        expected='scope_expansion' if self.path=='/api/save-expansion' else 'scope_plan_comparison'
                        result=job.owned_result(payload['job_id'],expected)
                        folder=(save_expansion if expected=='scope_expansion' else save_scope_plan_comparison)(run_root,result)
                        self.reply(200,dict(folder=str(folder),artifact_id=folder.name))
                    elif self.path=='/api/open-scope-plan-result':
                        from .scope_plan_comparison import load_scope_plan_comparison,scope_plan_source
                        artifact=next((a for a in artifacts() if a['id']==payload.get('artifact_id')),None)
                        if not artifact or artifact['kind']!='scope_plan_comparison':
                            raise ValueError('Choose a saved fixed scope comparison')
                        report=load_scope_plan_comparison(artifact['result_path'])
                        result=scope_plan_source(report,payload.get('task_id'))
                        selected=next((c for c in cases() if c['case_id']==result['config']['case_id']),None)
                        if not selected or selected['source_index_id']!=report['config']['source_index_id']:
                            raise ValueError('Selected comparison scope is unavailable or its index differs')
                        if selected['case_id']!=case['manifest']['case_id']:
                            switch_case(selected['path'])
                        from .replay import _resolve_source
                        _resolve_source(case,result,{})
                        task=next(t for t in report['tasks'] if t['task_id']==payload['task_id'])
                        self.reply(200,dict(overview=dict(overview,token=token),source=dict(kind='artifact',artifact_id=artifact['id'],task_id=task['task_id']),
                            experiment=result['config']['experiment'],task=task,result=result))
                    elif self.path == '/api/global/find':
                        self.reply(200,global_workspace().find(payload.get('filters',{}),payload.get('limit',100),payload.get('offset',0)))
                    elif self.path == '/api/global/scope':
                        self.reply(200,global_workspace().scope(payload))
                    elif self.path == '/api/global/pathways':
                        result=global_workspace().pathways(payload)
                        state['pathways']=result
                        state['pathways_id']=uuid4().hex
                        self.reply(200,dict(result,pathways_id=state['pathways_id']))
                    elif self.path == '/api/pathways':
                        result=lab.pathways(payload.get('request'),experiment=Experiment.from_dict(payload['experiment']))
                        state['pathways']=result
                        state['pathways_id']=uuid4().hex
                        self.reply(200,dict(result,pathways_id=state['pathways_id']))
                    elif self.path in ('/api/reduction-preview','/api/start-reduction'):
                        conditions,bodies,options,extra=reduction_request(payload)
                        kwargs=dict(simplify=payload.get('simplify',False),extra_conditions=extra)
                        if self.path=='/api/reduction-preview':
                            self.reply(200,lab.reduction_preview(conditions,bodies,options,**kwargs))
                        else:
                            self.reply(200,job.start_reduction(lab,conditions,bodies,options,**kwargs))
                    elif self.path=='/api/cancel-reduction':
                        snapshot=job.snapshot(payload.get('job_id',''))
                        if snapshot.get('kind')!='plan_reduction':
                            raise ValueError('This is not a reduction task')
                        self.reply(200,job.cancel(payload['job_id']))
                    elif self.path=='/api/save-reduction':
                        from .plan_reduction import save_reduction
                        self.reply(200,dict(folder=str(save_reduction(run_root,reduction_report(payload)))))
                    elif self.path=='/api/reduction-curves':
                        report=reduction_report(payload)
                        try:
                            comparison=lab.reduction_curves(report,payload['body_ids'],include_original=payload.get('include_original',True))
                        finally:
                            retain_reduction(payload,report)
                        state.update(comparison=comparison,comparison_id=uuid4().hex)
                        self.reply(200,dict(comparison=dict(comparison,comparison_id=state['comparison_id']),report=report))
                    elif self.path == '/api/save-analysis-session':
                        # Resolve server-owned completed results before writing a scene.
                        # Successful sidecar saves remain visible if a later step fails.
                        from .replay import save_replay
                        from .scope_differences import save_differences
                        persisted={}
                        def persist(handle,display=None):
                            key=json.dumps({k:v for k,v in handle.items() if k not in ('condition_name','body_ids','start','duration')},sort_keys=True)
                            if key in persisted:
                                return persisted[key]
                            if handle.get('artifact_id'):
                                a=next((a for a in artifacts() if a['id']==handle['artifact_id']),None)
                                if a and a['kind']=='scope_plan_comparison':
                                    replay_source(dict(source=handle))
                                    return a['id']
                                if not a or a['case_id']!=case['manifest']['case_id']:
                                    raise ValueError('Saved source is missing or belongs to another scope')
                                return a['id']
                            kind=handle.get('kind')
                            if kind=='difference':
                                folder=save_differences(run_root,owned_differences(handle),display)
                            elif kind=='replay':
                                folder=save_replay(run_root,owned_replay(handle),display)
                            elif kind=='pathways':
                                if handle.get('pathways_id')!=state['pathways_id'] or state['pathways'] is None:
                                    raise ValueError('Pathway result changed')
                                folder=save_pathways(run_root,state['pathways'])
                            elif kind=='run':
                                source,_=replay_source(dict(source=handle))
                                folder=save_run(run_root,source)
                            elif kind=='comparison':
                                source,_=replay_source(dict(source=handle))
                                folder=save_comparison(run_root,source)
                            elif kind=='timing':
                                folder=save_timing(run_root,timing_report(handle))
                            elif kind=='reduction':
                                from .plan_reduction import save_reduction
                                folder=save_reduction(run_root,reduction_report(handle))
                            elif kind=='joint':
                                snapshot=source_task_snapshot(handle.get('job_id',''),'joint_search')
                                if snapshot['status']=='running' or snapshot['result'] is None:
                                    raise ValueError('Wait for the completed source')
                                folder=save_joint_search(run_root,snapshot['result'])
                            else:
                                raise ValueError('Save or reopen this source result first')
                            persisted[key]=folder.name
                            return folder.name
                        source=payload.get('source') or {}
                        source_id=persist(source,payload.get('state',{}).get('replay_display') if source.get('kind')=='replay' else payload.get('state',{}).get('difference_display'))
                        refs={}
                        for role,handle in payload.get('references',{}).items():
                            display=payload.get('state',{}).get('replay_display' if role=='replay' else 'difference_display')
                            refs[role]=persist(handle,display)
                        selection={k:source[k] for k in ('condition_name','body_ids','start','duration','task_id') if k in source}
                        display=dict(payload.get('state',{}))
                        if display.get('reduction_display') and refs.get('reduction'):
                            display['reduction_display']=dict(display['reduction_display'],artifact_id=refs['reduction'])
                        document=dict(name=payload['name'],source=dict(artifact_id=source_id,selection=selection),references=refs,state=display)
                        if display.get('spatial'):
                            from .spatial import validate_spatial_state
                            display['spatial']=validate_spatial_state(display['spatial'],global_spatial().identity['source_index_id'])
                            global_spatial().locate(list(dict.fromkeys(display['spatial']['selected_nodes']+display['spatial']['highlight_ids']+display['spatial']['skeleton_ids']+([display['spatial']['focus_node']] if display['spatial'].get('focus_node') else []))))
                            if display['spatial'].get('edge_pairs'):
                                global_spatial().edges(display['spatial']['edge_pairs'])
                            if display['spatial'].get('replay_id'):
                                if not refs.get('replay'):
                                    raise ValueError('Spatial activity requires its saved replay reference')
                                display['spatial']['replay_id']=refs['replay']
                        folder=lab.save_analysis_session(run_root,document)
                        self.reply(200,dict(folder=str(folder),artifact_id=folder.name,session=geometry_scene_status(lab.read_analysis_session(folder))))
                    elif self.path == '/api/save-pathways':
                        if state['pathways'] is None or payload.get('pathways_id')!=state['pathways_id']:
                            raise ValueError('Explore this pathway again before saving')
                        self.reply(200,dict(folder=str(save_pathways(run_root,state['pathways']))))
                    elif self.path == '/api/recording-preview':
                        self.reply(200,lab.recording_preview(fixed_experiment(payload['experiment']),payload.get('recording')))
                    elif self.path in ('/api/difference-preview','/api/difference-prepare'):
                        source,request=replay_source(payload)
                        if self.path=='/api/difference-preview':
                            self.reply(200,lab.difference_preview(source,request))
                        else:
                            self.reply(200,job.start_differences(lab,source,request))
                    elif self.path=='/api/cancel-differences':
                        snapshot=job.snapshot(payload.get('job_id',''),public_result=lambda _:None)
                        if snapshot.get('kind')!='scope_differences':
                            raise ValueError('This is not a node difference preparation task')
                        self.reply(200,job.cancel(payload.get('job_id','')))
                    elif self.path=='/api/save-differences':
                        from .scope_differences import save_differences
                        self.reply(200,dict(folder=str(save_differences(run_root,owned_differences(payload),payload.get('display')))))
                    elif self.path in ('/api/difference-replay-preview','/api/difference-replay-prepare'):
                        result=owned_differences(payload)
                        nodes=payload.get('node_ids')
                        request=payload.get('request') or {}
                        if self.path=='/api/difference-replay-preview':
                            self.reply(200,lab.difference_replay_preview(result,nodes,request))
                        else:
                            self.reply(200,job.start_difference_replay(lab,result,nodes,request))
                    elif self.path=='/api/difference-pathways':
                        result=lab.difference_pathways(owned_differences(payload),payload.get('source_ids'),payload.get('targets'),payload.get('request'))
                        state.update(pathways=result,pathways_id=uuid4().hex)
                        self.reply(200,dict(result,pathways_id=state['pathways_id']))
                    elif self.path in ('/api/replay-preview','/api/replay-prepare'):
                        source,request=replay_source(payload)
                        if self.path=='/api/replay-preview':
                            self.reply(200,lab.replay_preview(source,request))
                        else:
                            self.reply(200,job.start_replay(lab,source,request))
                    elif self.path=='/api/cancel-replay':
                        snapshot=job.snapshot(payload.get('job_id',''),public_result=lambda _:None)
                        if snapshot.get('kind')!='circuit_replay':
                            raise ValueError('This is not a replay preparation task')
                        self.reply(200,job.cancel(payload.get('job_id','')))
                    elif self.path=='/api/save-replay':
                        from .replay import save_replay
                        self.reply(200,dict(folder=str(save_replay(run_root,owned_replay(payload),payload.get('display')))))
                    elif self.path == '/api/search-candidates':
                        cfg=Experiment.from_dict(payload['experiment'])
                        self.reply(200,resolve_candidates(case,cfg,SearchOptions.from_dict(payload.get('options',{})),allow_empty=True))
                    elif self.path in ('/api/timing-preview','/api/timing-explore','/api/timing-curves'):
                        with job.lock:
                            if job.state and job.state['status']=='running':
                                raise ValueError('Cancel or finish the active search first')
                        if self.path=='/api/timing-curves':
                            report=timing_report(payload)
                            try:
                                result=lab.timing_plan_curves(report,payload['start'],payload['duration'])
                            finally:
                                retain_timing_report(payload,report)
                            state['comparison']=result
                            state['comparison_id']=uuid4().hex
                            self.reply(200,dict(result,comparison_id=state['comparison_id'],timing_report=report))
                        else:
                            options=SearchOptions.from_dict(payload.get('options',{}))
                            values=(payload['conditions'],payload['body_ids'],payload['starts'],payload['durations'],options)
                            if self.path=='/api/timing-preview':
                                self.reply(200,lab.timing_preview(*values))
                            else:
                                state.update(timing_report=None,timing_source=None)
                                self.reply(200,job.start_timing(lab,*values))
                    elif self.path=='/api/cancel-timing':
                        snapshot=job.snapshot(payload.get('job_id',''))
                        if snapshot.get('kind')!='timing_exploration':
                            raise ValueError('This is not a timing exploration job')
                        self.reply(200,job.cancel(payload['job_id']))
                    elif self.path=='/api/save-timing':
                        self.reply(200,dict(folder=str(save_timing(run_root,timing_report(payload)))))
                    elif self.path in ('/api/search-context','/api/joint-search-context'):
                        with job.lock:
                            if job.state and job.state['status']=='running':
                                raise ValueError('Cancel or finish the active search before computing baselines')
                        options=SearchOptions.from_dict(payload.get('options',{}))
                        if self.path=='/api/search-context':
                            result=lab.search_context(Experiment.from_dict(payload['experiment']),options)
                        else:
                            result=lab.joint_search_preview(payload['conditions'],options,include_baselines=True)
                        self.reply(200,result)
                    elif self.path in ('/api/joint-search-preview','/api/joint-search','/api/joint-evaluate'):
                        with job.lock:
                            if job.state and job.state['status']=='running':
                                raise ValueError('Cancel or finish the active search first')
                        if self.path=='/api/joint-evaluate':
                            if payload.get('job_id'):
                                snapshot=source_task_snapshot(payload['job_id'],'joint_search')
                                if snapshot.get('kind')!='joint_search' or snapshot['status']=='running' or snapshot['result'] is None:
                                    raise ValueError('Select a completed joint search')
                                report=snapshot['result']
                            elif payload.get('artifact_id'):
                                artifact=next((a for a in artifacts() if a['id']==payload['artifact_id']),None)
                                if not artifact or artifact['kind']!='joint_search' or artifact['case_id']!=case['manifest']['case_id']:
                                    raise ValueError('Select a saved joint search in this computation scope')
                                report=json.loads(artifact['result_path'].read_text(encoding='utf-8'))
                            else:
                                raise ValueError('Evaluate a live job or a saved joint search artifact')
                            result=lab.evaluate_joint_plan(report,payload['body_ids'],payload.get('extra_conditions',[]))
                            state['comparison']=result
                            state['comparison_id']=uuid4().hex
                            self.reply(200,dict(result,comparison_id=state['comparison_id']))
                        else:
                            options=SearchOptions.from_dict(payload.get('options',{}))
                            if self.path=='/api/joint-search-preview':
                                self.reply(200,lab.joint_search_preview(payload['conditions'],options))
                            else:
                                self.reply(200,job.start_joint(lab,payload['conditions'],options))
                    elif self.path=='/api/cancel-joint-search':
                        snapshot=job.snapshot(payload.get('job_id',''))
                        if snapshot.get('kind')!='joint_search':
                            raise ValueError('This is not a joint search job')
                        self.reply(200,job.cancel(payload['job_id']))
                    elif self.path=='/api/save-joint-search':
                        snapshot=source_task_snapshot(payload.get('job_id',''),'joint_search')
                        if snapshot.get('kind')!='joint_search' or snapshot['status']=='running' or snapshot['result'] is None:
                            raise ValueError('Wait for the joint search result before saving')
                        self.reply(200,dict(folder=str(save_joint_search(run_root,snapshot['result']))))
                    elif self.path in ('/api/scope-preview','/api/scope-compare'):
                        config=scope_request(payload)
                        suspend_lab()
                        preview=preview_scopes(config)
                        if self.path=='/api/scope-preview':
                            self.reply(200,preview)
                        else:
                            if not preview['compatible']:
                                raise ValueError('Selected scopes are incompatible; check missing members first')
                            self.reply(200,scope_job.start(config))
                    elif self.path=='/api/cancel-scope-compare':
                        self.reply(200,scope_job.cancel(payload.get('job_id','')))
                    elif self.path=='/api/save-scope-comparison':
                        snapshot=scope_job.snapshot(payload.get('job_id',''),include_files=True)
                        if snapshot['status']=='running' or snapshot['result'] is None:
                            raise ValueError('Wait for the comparison to end before saving')
                        self.reply(200,dict(folder=str(save_scope_comparison(run_root,snapshot['result']))))
                    elif self.path == '/api/create-case':
                        with job.lock:
                            if job.state and job.state['status']=='running':
                                raise ValueError('Cancel or finish the search before creating a case')
                        path=global_workspace().create_case(payload)
                        self.reply(200,switch_case(path))
                    elif self.path == '/api/open-case':
                        match=next((c for c in cases() if c['id']==payload.get('id')),None)
                        if not match:
                            raise ValueError('Unknown saved case')
                        self.reply(200,switch_case(match['path']))
                    elif self.path == '/api/reopen':
                        match=next((a for a in artifacts() if a['id']==payload.get('id')),None)
                        if not match:
                            raise ValueError('Unknown saved result')
                        if match['kind']=='operation_search':
                            from .operation_search import load_operation_search
                            self.reply(200,dict(kind='operation_search',artifact_id=match['id'],config=match['config'],result=load_operation_search(match['result_path'])))
                            return
                        if match['kind']=='group_connections':
                            report=grouping.load_grouping(match['result_path'],index=global_workspace().index)
                            self.reply(200,dict(kind='group_connections',artifact_id=match['id'],
                                result=retain_group(report,match['result_path'])))
                            return
                        if match['kind']=='pathways' and not match['case_id']:
                            saved=json.loads(match['result_path'].read_text(encoding='utf-8'))
                            if saved['scope'].get('source_index_id')!=global_workspace().index.manifest['index_id']:
                                raise ValueError('Saved pathway belongs to a different global index')
                            self.reply(200,dict(case_id=None,kind='pathways',config=match['config'],result=saved))
                            return
                        if match['config'].get('model_version')!=MODEL_VERSION:
                            raise ValueError('Saved result model version mismatch')
                        if match['kind']=='scope_comparison':
                            configs=match['config']
                            available={c['case_id']:c for c in cases()}
                            first=available.get(configs['cases'][0]['case_id'])
                            if not first or first['source_index_id']!=configs['source_index_id']:
                                raise ValueError('The saved comparison needs its matching first computation scope')
                            if case is None or first['case_id']!=case['manifest']['case_id']:
                                switch_case(first['path'])
                            result=json.loads(match['result_path'].read_text(encoding='utf-8'))
                            self.reply(200,dict(case_id=first['case_id'],kind=match['kind'],config=configs,result=result))
                            return
                        c=next((c for c in cases() if c['case_id']==match['case_id']),None)
                        if not c:
                            raise ValueError('Reopen the matching saved case first')
                        if case is None or c['case_id']!=case['manifest']['case_id']:
                            switch_case(c['path'])
                        if match['kind']=='response_exploration':
                            report=responses.load_responses(match['result_path'],case)
                            response_slot.update(report=report,report_id=uuid4().hex,artifact_id=match['id'])
                            self.reply(200,dict(kind=match['kind'],artifact_id=match['id'],config=match['config'],
                                result=dict(responses.public_responses(report),report_id=response_slot['report_id'])))
                            return
                        if match['kind']=='analysis_session':
                            self.reply(200,dict(kind='analysis_session',artifact_id=match['id'],session=geometry_scene_status(lab.read_analysis_session(match['result_path']))))
                            return
                        if match['kind']=='plan_reduction':
                            from .plan_reduction import load_reduction
                            result=load_reduction(match['result_path'],case)
                            state.update(reduction_report=result,reduction_source=match['id'])
                            self.reply(200,dict(kind='plan_reduction',artifact_id=match['id'],config=match['config'],result=result))
                            return
                        if match['kind']=='scope_differences':
                            from .scope_differences import load_differences,public_differences
                            ensure_lab()
                            result=load_differences(match['result_path'].parent,case)
                            state.update(differences=result,difference_id=uuid4().hex)
                            self.reply(200,dict(case_id=match['case_id'],kind=match['kind'],config=match['config'],
                                result=dict(public_differences(result),difference_id=state['difference_id']),artifact_id=match['id']))
                            return
                        if match['kind']=='circuit_replay':
                            from .replay import load_replay,public_replay
                            ensure_lab()
                            result=load_replay(match['result_path'].parent,case)
                            state.update(replay=result,replay_id=uuid4().hex)
                            self.reply(200,dict(case_id=match['case_id'],kind=match['kind'],config=match['config'],
                                result=dict(public_replay(result),replay_id=state['replay_id']),artifact_id=match['id']))
                            return
                        if match['kind']=='comparison' and match.get('result_path'):
                            from .replay_sources import read_saved_source
                            result=read_saved_source(match['result_path'])
                            state.update(comparison=result,comparison_id=uuid4().hex)
                            state['saved_comparison']=dict(comparison_id=state['comparison_id'],path=match['result_path'])
                            result=dict(public_task_result(result),comparison_id=state['comparison_id'])
                        else:
                            result=json.loads(match['result_path'].read_text(encoding='utf-8')) if match.get('result_path') and match['result_path'].is_file() else None
                        self.reply(200,dict(case_id=match['case_id'],kind=match['kind'],config=match['config'],result=result,
                                            artifact_id=match['id']))
                    elif self.path == '/api/run':
                        cfg = fixed_experiment(payload.get('experiment',payload))
                        result = lab.run(cfg, keep_states=True,recording=payload.get('recording') if 'experiment' in payload else None)
                        if cfg.intervention_events is None and cfg.intervention_ids==():
                            result['fixed_no_intervention']=True
                        state['last'] = result
                        state['run_id'] = uuid4().hex
                        self.reply(200, dict({k: v for k, v in result.items() if k != 'states'}, run_id=state['run_id']))
                    elif self.path == '/api/save':
                        if state['last'] is None or payload.get('run_id') != state['run_id']:
                            raise ValueError('Run again before saving this comparison')
                        folder = save_run(run_root, state['last'])
                        self.reply(200, {'folder': str(folder)})
                    elif self.path == '/api/select':
                        cfg = Experiment.from_dict(payload['experiment'])
                        self.reply(200, lab.select(cfg, payload['count'], payload['method'], payload.get('output')))
                    elif self.path == '/api/intervention-preview':
                        ensure_lab()
                        self.reply(200,lab.intervention_preview(Experiment.from_dict(payload['experiment'])))
                    elif self.path == '/api/intervention-edges':
                        ensure_lab()
                        self.reply(200,lab.intervention_edges(payload['source_ids'],payload['target_ids'],
                            max_edges=payload.get('max_edges',100000),max_bytes=payload.get('max_bytes',64*1024**2)))
                    elif self.path == '/api/responses-preview':
                        self.reply(200,lab.response_preview(payload['definition']))
                    elif self.path == '/api/responses-scope-groups':
                        self.reply(200,responses.scope_input_groups(case,payload['field']))
                    elif self.path == '/api/responses-query-input':
                        ids=global_workspace().index.ids_for(payload.get('filters',{}),max_count=200000)
                        self.reply(200,dict(body_ids=[str(i) for i in ids],member_count=len(ids)))
                    elif self.path == '/api/responses-generate':
                        generated=responses.generate_input(payload['name'],payload['body_ids'],payload['start'],payload['stop'],payload['strength'],payload['mode'])
                        # Full case membership/window validation remains in the shared preview.
                        self.reply(200,generated)
                    elif self.path == '/api/local-submit':
                        if lab is None:
                            raise ValueError('Open a scope before submitting')
                        self.reply(200,local_tasks.submit(lab.case_path,payload['task_type'],payload['definition']))
                    elif self.path == '/api/local-run':
                        self.reply(200,local_tasks.execute(payload['task_ids'],background=True))
                    elif self.path in ('/api/local-pause','/api/local-cancel'):
                        self.reply(200,local_tasks.request(payload['task_id'],'pause' if self.path.endswith('pause') else 'cancel'))
                    elif self.path == '/api/local-copy':
                        self.reply(200,local_tasks.copy(payload['task_id']))
                    elif self.path == '/api/local-check':
                        self.reply(200,local_tasks.check(payload['task_id']))
                    elif self.path == '/api/local-display':
                        local_tasks.save_display(payload['task_id'],payload['display'])
                        self.reply(200,dict(saved=True))
                    elif self.path == '/api/local-result':
                        doc=local_tasks.read(payload['task_id'])
                        if case is None or str(lab.case_path.resolve())!=doc['case_path']:
                            opened=switch_case(Path(doc['case_path']),doc['identity'])
                        else:
                            from .replay import _identity
                            if _identity(case)!=doc['identity']:
                                raise ValueError('Task result scope/index/model identity changed')
                            opened=current_overview()
                        report=local_tasks.result(payload['task_id'])
                        result=responses.public_responses(report) if doc['task_type']=='response_exploration' else report
                        self.reply(200,dict(task=local_tasks.summary(doc),overview=opened,result=result))
                    elif self.path == '/api/responses-start':
                        definition=lab.response_preview(payload['definition'])['definition']
                        self.reply(200,job._start(lambda cancel,progress:lab.explore_responses(definition,cancel=cancel,progress=progress),'response_exploration'))
                    elif self.path == '/api/responses-cancel':
                        snapshot=job.snapshot(payload['job_id'],public_result=lambda r:None)
                        if snapshot['kind'] not in ('response_exploration','response_curves'):
                            raise ValueError('Not a response task')
                        self.reply(200,job.cancel(payload['job_id']))
                    elif self.path == '/api/responses-result':
                        snapshot=job.snapshot(payload['job_id'],public_result=lambda r:None)
                        result=job.owned_result(payload['job_id'],snapshot['kind'])
                        if snapshot['kind']=='response_exploration':
                            response_slot.update(report=result,report_id=uuid4().hex,artifact_id=None)
                            self.reply(200,dict(responses.public_responses(result),report_id=response_slot['report_id']))
                        elif snapshot['kind']=='response_curves':
                            state.update(comparison=result,comparison_id=uuid4().hex)
                            self.reply(200,dict(public_task_result(result),comparison_id=state['comparison_id']))
                        else:
                            raise ValueError('Not a response task')
                    elif self.path == '/api/responses-nodes':
                        report=response_report(payload)
                        self.reply(200,responses.response_nodes(report,payload['condition'],group_id=payload.get('group_id'),
                            mode=payload.get('mode','baseline'),other=payload.get('other'),exclude_inputs=payload.get('exclude_inputs',False),
                            offset=payload.get('offset',0),limit=payload.get('limit',50)))
                    elif self.path == '/api/responses-values':
                        report=response_report(payload)
                        offset=payload.get('offset',0)
                        limit=payload.get('limit',10000)
                        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=20000:
                            raise ValueError('Invalid response values page')
                        values=responses.response_values(report,payload['condition'],payload.get('mode','baseline'))
                        self.reply(200,dict(body_ids=[str(i) for i in report['body_ids'][offset:offset+limit]],
                            values=values[offset:offset+limit].tolist(),total=len(values)))
                    elif self.path == '/api/responses-members':
                        report=response_report(payload)
                        group=payload['group_id']
                        if type(group) is not int or not 0<=group<len(report['groups']):
                            raise ValueError('Unknown response group')
                        self.reply(200,dict(body_ids=[str(i) for i in report['body_ids'][report['membership']==group]]))
                    elif self.path == '/api/responses-condition':
                        selected=lab.response_condition(response_report(payload),payload['condition'],payload.get('group_id'),observation_name=payload.get('observation_name'))
                        self.reply(200,selected)
                    elif self.path == '/api/responses-export':
                        from .task_definition import export_task
                        selected=lab.response_condition(response_report(payload),payload['condition'],payload.get('group_id'),observation_name=payload.get('observation_name'))
                        self.reply(200,dict(definition=export_task(case,[selected],payload['name'])))
                    elif self.path == '/api/responses-curves-preview':
                        selected=lab.response_condition(response_report(payload),payload['condition'],payload.get('group_id'),observation_name=payload.get('observation_name'))
                        preview=lab.recording_preview(Experiment.from_dict(selected['experiment']),dict(mode='none'))
                        self.reply(200,dict(recording=preview,expected_propagations=2))
                    elif self.path == '/api/responses-curves':
                        report=response_report(payload)
                        selected=lab.response_condition(report,payload['condition'],payload.get('group_id'),observation_name=payload.get('observation_name'))
                        self.reply(200,job._start(lambda cancel,progress:lab.response_curves(report,payload['condition'],payload.get('group_id'),
                            observation_name=payload.get('observation_name'),cancel=cancel,progress=progress),'response_curves'))
                    elif self.path == '/api/responses-save':
                        report=response_report(payload)
                        folder=responses.save_responses(run_root,report,payload.get('display'))
                        response_slot['artifact_id']=folder.name
                        self.reply(200,dict(folder=str(folder),artifact_id=folder.name))
                    elif self.path == '/api/operation-search-preview':
                        self.reply(200,lab.operation_search_preview(payload['definition']))
                    elif self.path == '/api/operation-search-start':
                        if len(operation_reports)>=8:
                            raise ValueError('Save the current operation report before starting more searches; live report limit is 8')
                        lab.operation_search_preview(payload['definition'])
                        self.reply(200,job._start(lambda cancel,progress:lab.search_operations(payload['definition'],cancel=cancel,progress=progress),'operation_search'))
                    elif self.path == '/api/operation-search-cancel':
                        snapshot=job.snapshot(payload['job_id'],public_result=public_task_result)
                        if snapshot['kind'] not in ('operation_search','operation_search_curves'):
                            raise ValueError('Not an operation search task')
                        self.reply(200,job.cancel(payload['job_id']))
                    elif self.path == '/api/operation-search-result':
                        snapshot=job.snapshot(payload['job_id'],public_result=public_task_result)
                        result=job.owned_result(payload['job_id'],snapshot['kind'])
                        if snapshot['kind']=='operation_search':
                            key=uuid4().hex
                            operation_reports[key]=result
                            self.reply(200,dict(result,report_id=key))
                        elif snapshot['kind']=='operation_search_curves':
                            state.update(comparison=result,comparison_id=uuid4().hex)
                            self.reply(200,dict(public_task_result(result),comparison_id=state['comparison_id']))
                        else:
                            raise ValueError('Not an operation search task')
                    elif self.path == '/api/operation-search-save':
                        from .operation_search import save_operation_search
                        report=operation_report(payload)
                        folder=save_operation_search(run_root,report)
                        for key,value in list(operation_reports.items()):
                            if value is report:
                                operation_reports.pop(key)
                        self.reply(200,dict(folder=str(folder),artifact_id=folder.name))
                    elif self.path == '/api/operation-search-curves':
                        report=operation_report(payload)
                        self.reply(200,job._start(lambda cancel,progress:lab.operation_plan_curves(report,payload['candidate_ids'],
                            extra_conditions=payload.get('extra_conditions'),cancel=cancel,progress=progress),'operation_search_curves'))
                    elif self.path == '/api/operations-compare':
                        ensure_lab()
                        cfg=Experiment.from_dict(payload['experiment'])
                        lab.intervention_preview(cfg)
                        from .interventions import normalize_intervention_events
                        a=normalize_intervention_events(payload['a_events'],cfg.steps,case['nodes'])
                        b=normalize_intervention_events(payload['b_events'],cfg.steps,case['nodes'])
                        self.reply(200,job._start(lambda cancel,progress:lab.compare_operations(cfg,a,b,
                            search_options=payload.get('search_options'),cancel=cancel,simulation_progress=progress),'operations_comparison'))
                    elif self.path == '/api/operations-cancel':
                        snapshot=job.snapshot(payload['job_id'],public_result=public_task_result)
                        if snapshot['kind']!='operations_comparison':
                            raise ValueError('Not an operations comparison task')
                        self.reply(200,job.cancel(payload['job_id']))
                    elif self.path == '/api/operations-result':
                        result=job.owned_result(payload['job_id'],'operations_comparison')
                        state.update(comparison=result,comparison_id=uuid4().hex)
                        self.reply(200,dict(public_task_result(result),comparison_id=state['comparison_id']))
                    elif self.path == '/api/compare':
                        result = lab.compare(payload['conditions'])
                        state['comparison'] = result
                        state['comparison_id'] = uuid4().hex
                        self.reply(200, dict(result, comparison_id=state['comparison_id']))
                    elif self.path == '/api/save-comparison':
                        if state['comparison'] is None or payload.get('comparison_id') != state['comparison_id']:
                            raise ValueError('Run the comparison again before saving')
                        folder = save_comparison(run_root, state['comparison'])
                        state['saved_comparison']=dict(comparison_id=state['comparison_id'],path=folder/'comparison.json')
                        self.reply(200, {'folder': str(folder), 'artifact_id': folder.name})
                    elif self.path == '/api/export':
                        cfg = fixed_experiment(payload)
                        cfg.validate(case['nodes'])
                        folder = run_root / 'conditions'
                        folder.mkdir(parents=True, exist_ok=True)
                        path = folder / ('condition-' + uuid4().hex[:12] + '.json')
                        content = {'case_id': case['manifest']['case_id'],
                                   'model_version': MODEL_VERSION, 'experiment': asdict(cfg)}
                        path.write_text(json.dumps(content, ensure_ascii=False, indent=2,
                                                   allow_nan=False), encoding='utf-8')
                        self.reply(200, {'path': str(path)})
                    elif self.path == '/api/search':
                        cfg=Experiment.from_dict(payload['experiment'])
                        options=SearchOptions.from_dict(payload.get('options',{}))
                        self.reply(200,job.start(lab,cfg,options))
                    elif self.path == '/api/cancel-search':
                        self.reply(200,job.cancel(payload.get('job_id','')))
                    elif self.path == '/api/save-search':
                        snapshot=job.snapshot(payload.get('job_id',''))
                        if snapshot.get('kind')!='search':
                            raise ValueError('This is not a single-protocol search job')
                        if snapshot['result'] is None:
                            raise ValueError('Wait for the search result before saving')
                        folder=save_search(run_root,snapshot['result'])
                        self.reply(200,{'folder':str(folder)})
                    else:
                        self.reply(404, {'error': 'Unknown endpoint'})
            except (ValueError, KeyError, TypeError, MemoryError) as error:
                self.reply(400, error_payload(error))
            except OSError as error:
                self.reply(500, {'error': str(error)})

    Handler.access_log = access_log
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)

    def stop_if_idle():
        # Check workers and close the mutation gate under the same workspace lock.
        # A queued POST must observe stopping before it starts a new operation.
        if not lock.acquire(blocking=False):
            return False
        try:
            with job.lock:
                running = bool(job.state and job.state['status'] == 'running')
            if rebind or running or scope_job.running() or local_tasks.busy():
                return False
            control.stopping = True
            return True
        finally:
            lock.release()

    control = ServiceControl(server, port, stop_if_idle)
    from .process_signals import termination_as_interrupt
    try:
        control.publish(banner=banner)
        with termination_as_interrupt():
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if local_tasks.thread and local_tasks.thread.is_alive():
            for ident in local_tasks.task_ids:
                if local_tasks.read(ident)['status'] in ('running','pause_requested'):
                    try:
                        local_tasks.request(ident,'pause')
                    except ValueError:
                        pass
            local_tasks.thread.join(timeout=30)
        job.cancel_event.set()
        scope_job.close()
        control.close()
        server.server_close()
        # Active worker retains its case until it completes; do not unmap it.
        with job.lock:
            active=job.state and job.state['status']=='running'
        if not active and lab is not None:
            lab.close()
        if workspace:
            workspace.close()
    if rebind:
        from .preparation_app import open_prepared_workspace
        return open_prepared_workspace(rebind,port,banner=False,access_log=access_log)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Start the local Cecropis workbench')
    parser.add_argument('--case', type=Path)
    parser.add_argument('--port', type=int, default=8501)
    args = parser.parse_args()
    serve(args.case, args.port)
