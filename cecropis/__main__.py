"""One CLI over the same complete-data and numerical APIs as the website."""
import json
import signal
import sys
from pathlib import Path
from uuid import uuid4
from . import MODEL_VERSION
from .api import Lab,Workspace
from .simulation import RecordPolicy,load_experiment,save_run
from .exploration import save_comparison
from .search import SearchOptions,save_search
from .pathway_results import save_pathways
from .local_tasks import LocalSlot

ROOT=Path(__file__).resolve().parents[1]

def read_json(path):
    return json.loads(Path(path).expanduser().read_text(encoding='utf-8-sig'))

def main(argv=None):
    from .cli.arguments import build_parser
    parser = build_parser()
    args=parser.parse_args(argv)
    lab=None
    workspace=None
    try:
        if args.command in ('status','stop'):
            from .service_control import control_service
            print(json.dumps(control_service(args.port, stop=args.command == 'stop')))
            return
        if args.command == 'start':
            args.command = 'serve'
        # Read-only reporting needs neither workspace paths nor a case/index.
        if args.command in ('responses-read','responses-nodes'):
            from .response_exploration import load_responses,public_responses,response_nodes
            report=load_responses(args.report)
            result=public_responses(report) if args.command=='responses-read' else response_nodes(report,args.condition,
                group_id=args.group,mode=args.mode,other=args.other,exclude_inputs=args.exclude_inputs,offset=args.offset,limit=args.limit)
            print(json.dumps(result,ensure_ascii=False,allow_nan=False))
            return
        if args.command=='comparison-read':
            from .offline_report import extract_report
            print(json.dumps(extract_report(args.source),ensure_ascii=False,allow_nan=False))
            return
        if args.command in ('group-read','group-features','group-similar'):
            from .group_connections import load_grouping,group_summary,compare_group_features,similar_groups
            report=load_grouping(args.report)
            if args.command=='group-read':
                result=group_summary(report)
            elif args.command=='group-features':
                result=compare_group_features(report,args.a,args.b,args.direction)
            else:
                result=similar_groups(report,args.group,args.direction,args.limit)
            print(json.dumps(result,ensure_ascii=False,allow_nan=False))
            return
        if args.command in ('report-preview','report-export'):
            from .api import preview_result_report,export_result_report
            options=dict(condition_names=args.condition_names,max_bytes=args.max_bytes,language=args.language)
            result=preview_result_report(args.source,**options) if args.command=='report-preview' else export_result_report(args.source,args.destination,**options)
            print(json.dumps(result,ensure_ascii=False,allow_nan=False))
            return
        from .workspace_config import resolve_workspace_paths
        explicit_case=args.case
        paths=resolve_workspace_paths(root=ROOT,command=args.command,workspace=args.workspace,
            case=args.case,index=args.index,cases=args.cases,runs=args.runs,raw=args.raw,geometry=getattr(args,'geometry',None),
            skeletons=getattr(args,'skeleton_directory',None) or getattr(args,'directory',None),
            skeleton_cache=getattr(args,'skeleton_cache',None) or getattr(args,'cache',None))
        for key,value in paths.items():
            setattr(args,key,value)
        if args.command.startswith('skeleton-'):
            args.directory=paths['skeletons']
            args.cache=paths['skeleton_cache']
        if args.command.startswith('local-'):
            from .local_tasks import LocalTasks
            tasks=LocalTasks(args.runs)
            if args.command=='local-submit':
                if args.case is None:
                    raise ValueError('Submitting requires an explicit --case or workspace paths.case')
                result=tasks.submit(args.case,args.type,read_json(args.config))
            elif args.command=='local-list':
                result=tasks.list()
            elif args.command=='local-read':
                result=tasks.read(args.id)
            elif args.command=='local-check':
                result=tasks.check(args.id)
            elif args.command=='local-copy':
                result=tasks.copy(args.id)
            elif args.command in ('local-pause','local-cancel'):
                result=tasks.request(args.id,'pause' if args.command=='local-pause' else 'cancel')
            elif args.command=='local-result':
                result=tasks.result(args.id)
                if result['kind']=='response_exploration':
                    from .response_exploration import public_responses
                    result=public_responses(result)
            else:
                def stop(*_):
                    for ident in args.ids:
                        try:
                            tasks.request(ident,'cancel')
                        except ValueError:
                            pass
                signals=(signal.SIGINT,signal.SIGTERM) if sys.platform!='win32' else (signal.SIGINT,)
                old={s:signal.signal(s,stop) for s in signals}
                try:
                    result=tasks.execute(args.ids)
                finally:
                    for s,handler in old.items():
                        signal.signal(s,handler)
            print(json.dumps(result,ensure_ascii=False,allow_nan=False))
            return
        if args.command.startswith('skeleton-'):
            workspace=Workspace(args.index,args.cases)
            store=workspace.skeletons(args.directory,args.cache)
            if args.command=='skeleton-status':
                result=store.overview(offset=args.offset,limit=args.limit)
            elif args.command=='skeleton-query':
                result=store.query_view([args.bounds[:3],args.bounds[3:]],limit=args.limit)
            elif args.command=='skeleton-node':
                result=store.locate([args.id])
                if args.output is not None:
                    if args.output.exists():
                        raise ValueError('Skeleton export destination already exists')
                    data=store.detail(args.id,level=args.level,cache_id=result['cache_id'])
                    with args.output.open('xb') as stream:
                        stream.write(data)
                    result.update(exported_bytes=len(data),level=args.level,output=str(args.output.resolve()))
            else:
                if not 1<=args.max_input_mib<=8192:
                    raise ValueError('--max-input-mib must be 1..8192')
                if not 1<=args.max_cache_mib<=16384:
                    raise ValueError('--max-cache-mib must be 1..16384')
                cancelled=False
                def cancel_geometry(*_):
                    nonlocal cancelled
                    cancelled=True
                old=signal.signal(signal.SIGINT,cancel_geometry)
                try:
                    with LocalSlot(args.runs/'local-tasks'):
                        result=store.prepare(max_files=args.max_files,max_bytes=int(args.max_input_mib*1024*1024),
                            max_cache_bytes=int(args.max_cache_mib*1024*1024),cancel=lambda:cancelled,
                            progress=(lambda value:print(json.dumps(value),file=sys.stderr,flush=True)) if args.progress else None)
                finally:
                    signal.signal(signal.SIGINT,old)
            print(json.dumps(result,ensure_ascii=False,allow_nan=False))
            return
        if args.command.startswith('spatial-'):

            workspace=Workspace(args.index,args.cases)
            try:
                space=workspace.spatial(getattr(args,'geometry',None))
                result=space.overview() if args.command=='spatial-overview' else space.locate(args.ids) if args.command=='spatial-locate' else space.geometry(args.ids)
                print(json.dumps(result,ensure_ascii=False,allow_nan=False))
                return
            finally:
                workspace.close()
        if args.command in ('group-analyze','group-members','group-pair'):
            workspace=Workspace(args.index,args.cases)
            if args.command!='group-analyze':
                report=workspace.load_grouping(args.report)
                if args.command=='group-members':
                    result=workspace.group_members(report,args.groups,filters=read_json(args.filters) if args.filters else None)
                else:
                    result=workspace.group_pair(report,args.source,args.target,offset=args.offset,
                                                limit=args.limit,scan_limit=args.scan_limit)
                print(json.dumps(result,ensure_ascii=False,allow_nan=False))
                return
            config=read_json(args.config)
            # An implicit legacy sample is never the scope of a global request.
            if config.get('mode')=='case' and explicit_case is None and args.workspace is None:
                raise ValueError('Case grouping requires an explicit --case or workspace paths.case')
            case_path=args.case if config.get('mode')=='case' else None
            reuse=args.reuse_case.resolve() if args.reuse_case else None
            if args.preview:
                result=workspace.preview_grouping(config,case_path=case_path,reuse_case_path=reuse)
                print(json.dumps(result,ensure_ascii=False,allow_nan=False))
                return
            cancelled=False
            def cancel_grouping(*_):
                nonlocal cancelled
                cancelled=True
            old=signal.signal(signal.SIGINT,cancel_grouping)
            try:
                from .group_connections import group_summary,save_grouping
                result=workspace.aggregate_groups(config,case_path=case_path,reuse_case_path=reuse,
                                                  cancel=lambda:cancelled)
                saved=save_grouping(args.runs,result)
                print(json.dumps(dict(group_summary(result),artifact=saved),ensure_ascii=False,allow_nan=False))
                return
            finally:
                signal.signal(signal.SIGINT,old)
        if args.command=='serve':
            from .app import serve
            serve(args.case,args.port,args.runs,args.geometry,args.index,args.cases,
                  args.skeletons,args.skeleton_cache,args.raw,args.workspace,banner=not args.no_banner,access_log=args.access_log)
            return
        if args.command=='operation-search-read':
            from .operation_search import load_operation_search
            print(json.dumps(load_operation_search(args.report),ensure_ascii=False,allow_nan=False))
            return
        if args.command in ('task-read','task-preview','task-prepare','task-run','task-export'):
            from .task_definition import normalize_task
            if args.command=='task-export':
                if args.case is None:
                    raise ValueError('task-export requires --case for the selected actual computation scope')
                from .replay_sources import read_saved_source
                from .task_sources import export_saved_task
                lab=Lab(args.case)
                definition=export_saved_task(lab.case,read_saved_source(args.source),args.name,
                    read_json(args.request) if args.request else None,args.description)
                destination=args.output.resolve()
                if destination.exists():
                    raise ValueError(f'Task output already exists: {destination}; select a new filename')
                destination.parent.mkdir(parents=True,exist_ok=True)
                destination.write_text(json.dumps(definition,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
                print(json.dumps(dict(path=str(destination),definition=definition),ensure_ascii=False,allow_nan=False))
                return
            definition=normalize_task(read_json(args.definition))
            if args.command=='task-read':
                print(json.dumps(definition,ensure_ascii=False,allow_nan=False))
                return
            workspace=Workspace(args.index,args.cases)
            budgets=read_json(args.budgets) if getattr(args,'budgets',None) else None
            if args.command=='task-preview':
                print(json.dumps(workspace.preview_task(definition,budgets=budgets),ensure_ascii=False,allow_nan=False))
                return
            cancelled=False
            def cancel_portable_task(*_):
                nonlocal cancelled
                cancelled=True
            old=signal.signal(signal.SIGINT,cancel_portable_task)
            try:
                if args.command=='task-prepare':
                    result=workspace.prepare_task(definition,budgets=budgets,cancel=lambda:cancelled)
                    args.runs.mkdir(parents=True,exist_ok=True)
                    path=args.runs/('task-preparation-'+uuid4().hex[:12]+'.json')
                    path.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
                    print(json.dumps(dict(path=str(path.resolve()),**result),ensure_ascii=False,allow_nan=False))
                    return
                check=workspace.preview_task(definition)
                if not check['compatible']:
                    raise ValueError('Task is incompatible with this workspace: '+ '; '.join(check['errors']))
                if check.get('verification_required'):
                    raise ValueError('Task scope content requires verification. Run task-prepare explicitly before task-run; --scope does not bypass verification')
                path=args.scope.resolve() if args.scope else check.get('existing_case_path')
                if not path:
                    raise ValueError('No exact prepared scope exists. Run task-prepare explicitly before task-run, or select an exact existing --scope')
                result=workspace.run_task(path,definition,cancel=lambda:cancelled)
                folder=save_comparison(args.runs,result)
                print(json.dumps(dict(folder=str(folder.resolve()),status=result['status'],
                    counters=result['counters'],condition_statuses=result['condition_statuses']),ensure_ascii=False,allow_nan=False))
                return
            finally:
                signal.signal(signal.SIGINT,old)
        if args.command in ('scope-expansion-read','scope-plan-read'):
            if args.command=='scope-expansion-read':
                from .scope_expansion import load_expansion
                result=load_expansion(args.report)
            else:
                from .scope_plan_comparison import load_scope_plan_comparison,scope_plan_source
                result=load_scope_plan_comparison(args.report)
                if args.task_id:
                    result=scope_plan_source(result,args.task_id)
            print(json.dumps(result,ensure_ascii=False,allow_nan=False))
            return
        if args.command in ('scope-expand','compare-scope-plans'):
            workspace=Workspace(args.index,args.cases)
            config=read_json(args.config)
            if args.preview:
                result=workspace.preview_expansion(args.case,config) if args.command=='scope-expand' else workspace.preview_scope_plans(config)
                print(json.dumps(result,ensure_ascii=False,allow_nan=False))
                return
            cancelled=False
            def cancel_new_scope(*_):
                nonlocal cancelled
                cancelled=True
            old=signal.signal(signal.SIGINT,cancel_new_scope)
            result=None
            try:
                if args.command=='scope-expand':
                    from .scope_expansion import save_expansion
                    result=workspace.build_expansion(args.case,config,cancel=lambda:cancelled)
                    folder=save_expansion(args.runs,result)
                else:
                    from .scope_plan_comparison import save_scope_plan_comparison
                    result=workspace.compare_scope_plans(config,cancel=lambda:cancelled)
                    folder=save_scope_plan_comparison(args.runs,result)
                print(json.dumps(dict(folder=str(folder),status=result['status']),ensure_ascii=False,allow_nan=False))
            finally:
                signal.signal(signal.SIGINT,old)
                if result and args.command=='compare-scope-plans':
                    from .scope_comparison import discard_recordings
                    discard_recordings(result)
            return
        if args.command=='compare-scopes':
            from .scope_comparison import preview_scopes,compare_scopes,save_scope_comparison,discard_recordings
            config=read_json(args.config)
            if args.preview:
                print(json.dumps(preview_scopes(config),ensure_ascii=False,allow_nan=False))
                return
            cancelled=False
            def cancel_scope(*_):
                nonlocal cancelled
                cancelled=True
            old=signal.signal(signal.SIGINT,cancel_scope)
            result=None
            try:
                result=compare_scopes(config,cancel=lambda:cancelled)
                folder=save_scope_comparison(args.runs,result)
                print(json.dumps(dict(folder=str(folder),status=result['status'],
                    completed=sum(s['status']=='completed' for s in result['scopes']),
                    total=len(result['scopes'])),ensure_ascii=False))
            finally:
                signal.signal(signal.SIGINT,old)
                if result:
                    discard_recordings(result)
            return
        if args.command in ('find','neighbors','case','scope') or (args.command=='pathways' and args.global_graph):
            workspace=Workspace(args.index,args.cases)
            if args.command=='find':
                filters=read_json(args.filters) if args.filters else {}
                for key,value in [('q',args.query),('type',args.type),('bodyId',args.body_id),('category',None if args.category=='all' else args.category)]:
                    if value is not None:
                        filters[key]=value
                result=workspace.find(filters,args.limit,args.offset)
            elif args.command=='neighbors':
                result=workspace.index.neighbors(args.id,args.direction,args.limit)
            elif args.command=='scope':
                result=workspace.scope(read_json(args.config))
            elif args.command=='pathways':
                if not args.config:
                    raise ValueError('Global pathways requires --config with exact source_ids and targets')
                data=read_json(args.config)
                if data.get('scope',{}).get('source_index_id') not in (None,workspace.index.manifest['index_id']):
                    raise ValueError('Pathway query global index mismatch')
                result=workspace.pathways(data.get('request',data))
                folder=save_pathways(args.runs,result)
                print(json.dumps(dict(folder=str(folder),node_count=result['node_count'],edge_count=result['edge_count'],truncated=result['truncated']),ensure_ascii=False))
                return
            else:
                config=read_json(args.selection)
                config.pop('selection_result',None)
                path=workspace.create_case(config,args.destination)
                m=read_json(path/'manifest.json')
                result=dict(path=str(path),case_id=m['case_id'],name=m['case_name'],node_count=m['node_count'],
                    internal_edges=m['scan']['internal_edges'],external_input_contacts=m['external_input_contacts'],
                    external_output_contacts=m['external_output_contacts'])
            print(json.dumps(result,ensure_ascii=False,allow_nan=False))
            return
        if args.case is None:
            raise ValueError(f'{args.command} requires an active scope; specify --case or workspace paths.case')
        lab=Lab(args.case,getattr(args,'directory',None))
        if args.command in ('responses','responses-curves','responses-export'):
            from .response_exploration import load_responses,save_responses,public_responses
            if args.command=='responses' and args.preview:
                print(json.dumps(lab.response_preview(read_json(args.config)),ensure_ascii=False,allow_nan=False))
                return
            cancelled=False
            def cancel_responses(*_):
                nonlocal cancelled
                cancelled=True
            old=signal.signal(signal.SIGINT,cancel_responses)
            try:
                if args.command=='responses':
                    with LocalSlot(args.runs / 'local-tasks'):
                        result=lab.explore_responses(read_json(args.config),cancel=lambda:cancelled)
                    folder=save_responses(args.runs,result)
                    output=dict(folder=str(folder),status=result['status'],execution_counts=result['execution_counts'],
                        node_count=len(result['body_ids']),condition_count=len(result['condition_states']))
                elif args.command=='responses-curves':
                    with LocalSlot(args.runs / 'local-tasks'):
                        result=lab.response_curves(load_responses(args.report,lab.case),args.condition,args.group,observation_name=args.observation_name,cancel=lambda:cancelled)
                    folder=save_comparison(args.runs,result)
                    output=dict(folder=str(folder),execution_counts=result.get('execution_counts'))
                else:
                    from .task_definition import export_task
                    selected=lab.response_condition(load_responses(args.report,lab.case),args.condition,args.group,observation_name=args.observation_name)
                    task=export_task(lab.case,[selected],args.name)
                    if args.output.exists():
                        raise ValueError('Task output exists; choose a new file')
                    args.output.write_text(json.dumps(task,ensure_ascii=False,indent=2),encoding='utf-8')
                    output=dict(output=str(args.output))
            finally:
                signal.signal(signal.SIGINT,old)
            print(json.dumps(output,ensure_ascii=False,allow_nan=False))
            return
        if args.command in ('operation-search','operation-search-evaluate'):
            from .operation_search import load_operation_search,save_operation_search
            if args.command=='operation-search' and args.preview:
                print(json.dumps(lab.operation_search_preview(read_json(args.config)),ensure_ascii=False,allow_nan=False))
                return
            cancelled=False
            def cancel_operations_search(*_):
                nonlocal cancelled
                cancelled=True
            old=signal.signal(signal.SIGINT,cancel_operations_search)
            try:
                if args.command=='operation-search':
                    with LocalSlot(args.runs / 'local-tasks'):
                        result=lab.search_operations(read_json(args.config),cancel=lambda:cancelled)
                    folder=save_operation_search(args.runs,result)
                    output=dict(folder=str(folder),status=result['status'],evaluations=result['evaluations'],
                        termination_reason=result['termination_reason'],recommended_candidate_ids=result['recommended_candidate_ids'],
                        physical_started=result['physical_started'],physical_completed=result['physical_completed'])
                else:
                    report=load_operation_search(args.report)
                    with LocalSlot(args.runs / 'local-tasks'):
                        result=lab.operation_plan_curves(report,args.ids,extra_conditions=read_json(args.extra) if args.extra else None,cancel=lambda:cancelled)
                    folder=save_comparison(args.runs,result)
                    updated=save_operation_search(args.runs,report)
                    output=dict(folder=str(folder),updated_report=str(updated),execution_counts=result['execution_counts'])
            finally:
                signal.signal(signal.SIGINT,old)
            print(json.dumps(output,ensure_ascii=False,allow_nan=False))
            return
        if args.command in ('intervention-preview','intervention-edges','operations-compare'):
            if args.command=='intervention-edges':
                from .intervention_selection import select_real_edges
                result=select_real_edges(lab.case,args.source,args.target,max_edges=args.max_edges,max_bytes=args.max_bytes)
                print(json.dumps(result,ensure_ascii=False,allow_nan=False))
                return
            data=read_json(args.config)
            if data.get('case_id') not in (None,lab.case['manifest']['case_id']) or data.get('model_version') not in (None,MODEL_VERSION):
                raise ValueError('Intervention definition case/model identity mismatch')
            from .simulation import Experiment
            from .interventions import preview_interventions
            cfg=Experiment.from_dict(data.get('experiment',data))
            if args.command=='intervention-preview':
                print(json.dumps(preview_interventions(lab.case,cfg),ensure_ascii=False,allow_nan=False))
                return
            from .exploration import compare_operations
            cancelled=False
            def cancel_operations(*_):
                nonlocal cancelled
                cancelled=True
            old=signal.signal(signal.SIGINT,cancel_operations)
            try:
                result=lab._scope(compare_operations(lab.case,cfg,data['a_events'],data['b_events'],
                    recording=RecordPolicy.from_dict(data.get('recording',{'mode':'selected'})),search_options=data.get('search_options'),cancel=lambda:cancelled))
            finally:
                signal.signal(signal.SIGINT,old)
            folder=save_comparison(args.runs,result)
            print(json.dumps(dict(folder=str(folder),status=result.get('status','complete'),
                interactions=result.get('interactions'),execution_counts=result.get('execution_counts')),ensure_ascii=False,allow_nan=False))
            return
        if args.command in ('scope-boundary','scope-external'):
            workspace=Workspace(args.index,args.cases)
            if args.command=='scope-boundary':
                data=read_json(args.config) if args.config else None
                result=workspace.boundary(lab.case,None if data is None else data.get('experiment',data),args.ids)
            else:
                result=workspace.external_inputs(lab.case,args.ids,category=args.category,scan_limit=args.scan_limit,limit=args.limit,offset=args.offset)
            print(json.dumps(result,ensure_ascii=False,allow_nan=False))
            return
        if args.command in ('reduction-analyze','reduction-read','reduction-evaluate'):
            from .plan_reduction import load_reduction,save_reduction
            if args.command=='reduction-read':
                print(json.dumps(load_reduction(args.report,lab.case),ensure_ascii=False,allow_nan=False))
                return
            if args.command=='reduction-evaluate':
                report=load_reduction(args.report,lab.case)
                ids=args.ids if args.ids is not None else (report.get('final') or report.get('original') or {}) .get('body_ids')
                if ids is None:
                    raise ValueError('Choose an actually completed reduction set')
                result=lab.reduction_curves(report,ids,include_original=args.include_original)
                folder=save_comparison(args.runs,result)
                print(json.dumps(dict(folder=str(folder),reduction_evaluation=result['reduction_evaluation']),ensure_ascii=False,allow_nan=False))
                return
            data=read_json(args.config)
            from .replay import _identity
            if any(data.get(k)!=v for k,v in _identity(lab.case).items() if k in data) or data.get('case_id')!=lab.case['manifest']['case_id']:
                raise ValueError('Reduction definition scope/index/model identity mismatch')
            values=(data['conditions'],data.get('original_body_ids',data.get('body_ids')),data['search_options'])
            kwargs=dict(simplify=data.get('simplify',False),extra_conditions=data.get('extra_conditions',[]))
            if args.preview:
                print(json.dumps(lab.reduction_preview(*values,**kwargs),ensure_ascii=False,allow_nan=False))
                return
            cancelled=False
            def cancel_reduction(*_):
                nonlocal cancelled
                cancelled=True
            old=signal.signal(signal.SIGINT,cancel_reduction)
            try:
                report=lab.analyze_reduction(*values,**kwargs,cancel=lambda:cancelled)
            finally:
                signal.signal(signal.SIGINT,old)
            folder=save_reduction(args.runs,report)
            print(json.dumps(dict(folder=str(folder),status=report['status'],termination_reason=report['termination_reason'],
                evaluations=report['evaluations'],baseline_simulations=report['baseline_simulations'],
                intervention_simulations=report['intervention_simulations'],cache_hits=report['cache_hits']),ensure_ascii=False,allow_nan=False))
            return
        if args.command=='session-read':
            print(json.dumps(lab.read_analysis_session(args.session),ensure_ascii=False,allow_nan=False))
            return
        if args.command=='replay-prepare':
            from .replay import public_replay,save_replay
            from .replay_sources import read_saved_source
            if args.config:
                config=read_json(args.config)
                source=config['source_result']
                request=config['request']
                if args.request:
                    raise ValueError('Saved replay config already defines its request')
            else:
                if not args.request:
                    raise ValueError('Specify --request for bounded replay nodes and recording')
                request=read_json(args.request)
                source=read_saved_source(args.source,request.get('recording',{}).get('max_bytes',64*1024*1024))
            if args.preview:
                print(json.dumps(lab.replay_preview(source,request),ensure_ascii=False,allow_nan=False))
                return
            cancelled=False
            def cancel_replay(*_):
                nonlocal cancelled
                cancelled=True
            old=signal.signal(signal.SIGINT,cancel_replay)
            try:
                result=lab.prepare_replay(source,request,cancel=lambda:cancelled)
            finally:
                signal.signal(signal.SIGINT,old)
            folder=save_replay(args.runs,result) if result.get('ready') else None
            print(json.dumps(dict(folder=str(folder) if folder else None,result=public_replay(result)),ensure_ascii=False,allow_nan=False))
            return
        if args.command=='difference-prepare':
            from .scope_differences import public_differences,save_differences,load_differences
            from .replay_sources import read_saved_source
            if args.config:
                if args.request:
                    raise ValueError('--request applies to --source; saved config already contains the request')
                saved=read_json(args.config)
                source=dict(saved['source_result'])
                source['analysis_source']=dict(kind='scope_differences',config=saved)
                request=saved.get('request',{})
            else:
                request=read_json(args.request) if args.request else {}
                path=args.source
                if path.is_file() and path.name in ('differences.json','replay.json'):
                    path=path.parent
                if path.is_dir() and (path/'differences.json').is_file():
                    result=load_differences(path,lab.case,max_bytes=request.get('max_bytes',64*1024*1024))
                    source=dict(result['config']['source_result'],_difference_result=result,
                        analysis_source=dict(kind='scope_differences',config=result['config']))
                elif path.is_dir() and (path/'replay.json').is_file():
                    from .replay_sources import read_replay_source
                    source=read_replay_source(path,lab.case)
                else:
                    source=read_saved_source(path,request.get('max_bytes',64*1024*1024))
            if args.preview:
                print(json.dumps(lab.difference_preview(source,request),ensure_ascii=False,allow_nan=False))
                return
            cancelled=False
            def cancel_differences(*_):
                nonlocal cancelled
                cancelled=True
            previous=signal.signal(signal.SIGINT,cancel_differences)
            try:
                result=lab.prepare_differences(source,request,cancel=lambda:cancelled)
                folder=save_differences(args.runs,result) if result['ready'] else None
                print(json.dumps(dict(folder=str(folder) if folder else None,result=public_differences(result)),ensure_ascii=False,allow_nan=False))
            finally:
                signal.signal(signal.SIGINT,previous)
            return
        if args.command=='difference-read':
            from .scope_differences import load_differences,public_differences
            result=load_differences(args.differences,lab.case)
            display=result.get('display',{})
            ranking=lab.difference_rows(result,sort=args.sort or display.get('sort','absolute'),
                body_id=args.body_id if args.body_id is not None else display.get('body_id',''),
                type_filter=args.type_filter if args.type_filter is not None else display.get('type_filter',''),
                hide_endpoints=False if args.include_endpoints else display.get('hide_endpoints',True),
                offset=args.offset if args.offset is not None else display.get('offset',0),limit=args.limit)
            output=dict(analysis=public_differences(result),ranking=ranking)
            if args.node:
                output['node']=lab.difference_node(result,args.node)
            if args.neighbors:
                if not args.node:
                    raise ValueError('--neighbors requires --node')
                output['neighbors']=lab.difference_neighbors(result,args.node,direction=args.neighbors,limit=args.limit)
            print(json.dumps(output,ensure_ascii=False,allow_nan=False))
            return
        if args.command=='replay-read':
            from .replay import load_replay,public_replay
            result=load_replay(args.replay,lab.case)
            if (args.start is None)!=(args.stop is None):
                raise ValueError('Specify both --start and --stop')
            window=dict(start=args.start,stop=args.stop) if args.start is not None else result.get('display',{}).get('window',result['default_window'])
            output=dict(replay=public_replay(result),summary=lab.replay_summary(result,window,args.limit))
            if args.step is not None:
                output['frame']=lab.replay_frame(result,args.step)
            if args.node:
                output['node']=lab.replay_node(result,args.node)
            if args.edge:
                if args.step is None:
                    raise ValueError('An edge frame requires --step')
                output['edge']=lab.replay_edge(result,args.edge,args.step)
            print(json.dumps(output,ensure_ascii=False,allow_nan=False))
            return
        if args.command in ('timing-explore','timing-evaluate'):
            from .timing_exploration import save_timing
            data=read_json(args.config if args.command=='timing-explore' else args.report)
            if data.get('case_id')!=lab.case['manifest']['case_id'] or data.get('model_version')!=MODEL_VERSION:
                raise ValueError('Timing exploration case/model version mismatch')
            if data.get('source_index_id')!=lab.case['manifest'].get('source_index_id'):
                raise ValueError('Timing exploration data index mismatch')
            if args.command=='timing-evaluate':
                result=lab.timing_plan_curves(data,args.start,args.duration)
                folder=save_comparison(args.runs,result)
                print(json.dumps(dict(folder=str(folder),timing_evaluation=result['timing_evaluation'],
                    curve_baseline_simulations=data['curve_baseline_simulations'],
                    curve_intervention_simulations=data['curve_intervention_simulations']),ensure_ascii=False,allow_nan=False))
                return
            options=SearchOptions.from_dict(data.get('search_options',{}))
            values=(data['conditions'],data['body_ids'],data['grid']['starts'],data['grid']['durations'],options)
            if args.preview:
                print(json.dumps(lab.timing_preview(*values),ensure_ascii=False,allow_nan=False))
                return
            cancelled=False
            def cancel_timing(*_):
                nonlocal cancelled
                cancelled=True
            old=signal.signal(signal.SIGINT,cancel_timing)
            try:
                result=lab.explore_timing(*values,cancel=lambda:cancelled)
            finally:
                signal.signal(signal.SIGINT,old)
            folder=save_timing(args.runs,result)
            print(json.dumps(dict(folder=str(folder),status=result['status'],evaluations=result['evaluations'],
                intervention_simulations=result['intervention_simulations'],
                completed_intervention_simulations=result['completed_intervention_simulations']),ensure_ascii=False,allow_nan=False))
            return
        if args.command in ('joint-search','joint-evaluate'):
            from .joint_search import save_joint_search
            data=read_json(args.config if args.command=='joint-search' else args.report)
            if data.get('case_id')!=lab.case['manifest']['case_id'] or data.get('model_version')!=MODEL_VERSION:
                raise ValueError('Joint search case/model version mismatch')
            if args.command=='joint-evaluate':
                ids=args.ids or (data.get('best') or {}).get('body_ids')
                if not ids:
                    raise ValueError('No saved joint plan available to evaluate')
                extras=read_json(args.extra_conditions) if args.extra_conditions else []
                extras=extras.get('conditions',extras) if isinstance(extras,dict) else extras
                result=lab.evaluate_joint_plan(data,ids,extras)
                folder=save_comparison(args.runs,result)
            else:
                option_data=dict(data.get('search_options',{}))
                if args.candidate_order:
                    option_data['candidate_order']=args.candidate_order
                options=SearchOptions.from_dict(option_data,legacy='search_options' in data)
                if args.preview or args.context:
                    print(json.dumps(lab.joint_search_preview(data['conditions'],options,include_baselines=args.context),ensure_ascii=False,allow_nan=False))
                    return
                cancelled=False
                def cancel_joint(*_):
                    nonlocal cancelled
                    cancelled=True
                old=signal.signal(signal.SIGINT,cancel_joint)
                try:
                    result=lab.joint_search(data['conditions'],options,cancel=lambda:cancelled)
                finally:
                    signal.signal(signal.SIGINT,old)
                folder=save_joint_search(args.runs,result)
            print(json.dumps(dict(folder=str(folder),status=result.get('status','complete'),
                evaluations=result.get('evaluations'),intervention_simulations=result.get('intervention_simulations')),
                ensure_ascii=False,allow_nan=False))
            return
        if args.command=='geometry':
            print(json.dumps(lab.geometry.skeleton(args.id) if args.id else lab.geometry.overview(),ensure_ascii=False,allow_nan=False))
            return
        if args.command=='pathways':
            data=read_json(args.config) if args.config else {}
            if data.get('case_id') not in (None,lab.case['manifest']['case_id']):
                raise ValueError('Pathway query case mismatch')
            if data.get('model_version') not in (None,MODEL_VERSION):
                raise ValueError('Pathway query model mismatch')
            from .simulation import Experiment
            cfg=Experiment.from_dict(data['experiment']) if 'experiment' in data else lab.default_experiment()
            result=lab.pathways(data.get('request',data) if 'experiment' not in data else data.get('request'),experiment=cfg)
            folder=save_pathways(args.runs,result)
            print(json.dumps(dict(folder=str(folder),node_count=result['node_count'],edge_count=result['edge_count'],truncated=result['truncated']),ensure_ascii=False))
            return
        if args.command=='compare':
            data=read_json(args.config)
            if data.get('case_id')!=lab.case['manifest']['case_id'] or data.get('model_version')!=MODEL_VERSION:
                raise ValueError('Configuration case/model version mismatch')
            if 'timing_evaluation' in data:
                from .timing_exploration import timing_conditions
                from .joint_search import annotate_joint_evaluation
                from .exploration import compare_conditions
                metadata=data['timing_evaluation']
                options=SearchOptions.from_dict(metadata['search_options'])
                view,conditions=timing_conditions(lab.case,data['conditions'],metadata['body_ids'],
                    metadata['start'],metadata['duration'],options)
                result=lab._scope(compare_conditions(view,conditions))
                from dataclasses import replace
                annotate_joint_evaluation(result,replace(options,max_nodes=max(options.max_nodes,len(metadata['body_ids']))),
                                          metadata['condition_names'])
                result['search_options']=metadata['search_options']
                result['timing_evaluation']=metadata
            elif 'reduction_evaluation' in data:
                from .scope_comparison import _bound_case
                from .exploration import compare_conditions
                from .simulation import Experiment
                from dataclasses import replace
                union=sorted({body for item in data['conditions'] for body in item['experiment']['intervention_ids']},key=int)
                probe=Experiment.from_dict(data['conditions'][0]['experiment'])
                view,_=_bound_case(lab.case,replace(probe,intervention_ids=tuple(union)))
                result=lab._scope(compare_conditions(view,data['conditions']))
            else:
                result=lab.compare(data['conditions'])
            if 'reduction_evaluation' in data:
                from .plan_reduction import _assess
                from .simulation import Experiment
                metadata=data['reduction_evaluation']
                options=SearchOptions.from_dict(metadata['search_options'])
                paired=metadata.get('include_original') and metadata['body_ids']!=metadata['original_body_ids']
                groups=([('original',metadata['original_body_ids']),('selected',metadata['body_ids'])] if paired
                    else [('selected',metadata['body_ids'])])
                assessments=[]
                for label,bodies in groups:
                    indexes=[i for i,item in enumerate(result['conditions']) if not paired or item['name'].startswith(label+' · ')]
                    parsed=[(result['conditions'][i]['name'],Experiment.from_dict(result['conditions'][i]['experiment'])) for i in indexes]
                    decision=[label+' · '+name if paired else name for name in metadata['condition_names']]
                    assessment=_assess(lab.case,parsed,bodies,[result['results'][i]['summary'] for i in indexes],options,decision)
                    assessment.update(search_condition_names=decision,
                        extra_condition_names=[name for name,_ in parsed if name not in decision])
                    for i,metrics in zip(indexes,assessment['condition_results']):
                        classification=metrics['evidence_classification']
                        result['rows'][i].update(constraints=metrics,evidence_classification=classification)
                        result['results'][i]['evidence_classification']=classification
                    assessments.append(dict(label=label,body_ids=bodies,constraints=assessment))
                if paired:
                    result['reduction_plan_assessments']=assessments
                else:
                    result['joint_constraints']=assessments[0]['constraints']
                result['reduction_evaluation']=metadata
            if ('joint_evaluation' in data and 'timing_evaluation' not in data
                    and 'reduction_evaluation' not in data):
                from .joint_search import annotate_joint_evaluation
                metadata=data['joint_evaluation']
                annotate_joint_evaluation(result,SearchOptions.from_dict(metadata['search_options'],legacy=True),
                                          metadata['search_condition_names'])
            folder=save_comparison(args.runs,result)
            print(json.dumps(dict(folder=str(folder),computation_node_count=len(lab.case['nodes']),conditions=len(result['rows'])),ensure_ascii=False))
            return
        cfg=load_experiment(args.config,lab.case['manifest']['case_id']) if args.config else lab.default_experiment()
        if cfg.intervention_group=='__fixed_no_intervention__' and cfg.intervention_ids==():
            from .plan_reduction import FixedExperiment
            from dataclasses import asdict
            cfg=FixedExperiment.from_dict(asdict(cfg))
        if args.command in ('run','forward'):
            data=read_json(args.config).get('recording') if args.config else None
            overrides={'mode':args.record_mode,'body_ids':args.record_ids,'step_stride':args.record_stride,'steps':args.record_steps}
            if any(v is not None for v in overrides.values()):
                data=dict(data or {'mode':'selected'})
                data.update({k:v for k,v in overrides.items() if v is not None})
            policy=RecordPolicy.from_dict(data) if data is not None else None
            result=lab.run(cfg,keep_states=True,recording=policy) if args.command=='run' else lab.forward(cfg,recording=policy)
            if cfg.intervention_events is None and cfg.intervention_ids==():
                result['fixed_no_intervention']=True
            folder=save_run(args.runs,result)
            print(json.dumps(dict(folder=str(folder),kind=result['kind'],computation_node_count=result['computation_node_count'],
                recording=result['recording_metadata'],elapsed_seconds=result['elapsed_seconds'],summary=result['summary']),ensure_ascii=False))
            return
        def progress(p):
            if p['evaluations']%50==0 or p['phase'] in ('complete','cancelled','budget_exhausted'):
                print(f"{p['phase']}: {p['evaluations']}/{p['budget']}",flush=True)
        saved_options=read_json(args.config) if args.config else {}
        option_data=saved_options.get('search_options',{})
        if not isinstance(option_data,dict):
            raise ValueError('search_options must be an object')
        option_data=dict(option_data)
        overrides={'max_evaluations':args.budget,'target_output':args.target_output,'target_metric':args.target_metric}
        overrides['candidate_policy']=args.candidate_policy
        overrides['candidate_order']=args.candidate_order
        if args.protected_limits is not None:
            overrides['protected_limits']=read_json(args.protected_limits)
        if args.command=='search':
            overrides.update(max_nodes=args.max_nodes,max_protected_loss=args.max_protected_loss,
                min_target_loss=args.min_target_loss,shortlist=args.shortlist,swap_passes=args.swap_passes)
        option_data.update({k:v for k,v in overrides.items() if v is not None})
        options=SearchOptions.from_dict(option_data,legacy='search_options' in saved_options)
        if args.context:
            print(json.dumps(lab.search_context(cfg,options),ensure_ascii=False,allow_nan=False))
            return
        if args.command=='sensitivity':
            result=lab.sensitivity(cfg,max_evaluations=options.max_evaluations,options=options,progress=progress)
            args.runs.mkdir(parents=True,exist_ok=True)
            path=args.runs/('sensitivity-'+uuid4().hex[:12]+'.json')
            path.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
            print(json.dumps(dict(path=str(path),status=result['status'],evaluations=result['evaluations'])))
            return
        cancelled=False
        def stop(*_):
            nonlocal cancelled
            cancelled=True
        old=signal.signal(signal.SIGINT,stop)
        try:
            result=lab.search(cfg,options,cancel=lambda:cancelled,progress=progress)
        finally:
            signal.signal(signal.SIGINT,old)
        folder=save_search(args.runs,result)
        print(json.dumps(dict(folder=str(folder),computation_node_count=len(lab.case['nodes']),candidate_count=result['candidate_count'],
            status=result['status'],evaluations=result['evaluations'],screened_candidates=result['screened_candidates'],best=result['best']),ensure_ascii=False))
    except (ValueError,KeyError,TypeError,OSError) as error:
        parser.exit(2,f'{error}\n')
    finally:
        if lab:
            lab.close()
        if workspace:
            workspace.close()

if __name__=='__main__':
    main()
