"""Public case-bound API shared by scripts, CLI and HTTP transports."""
from pathlib import Path
from .case import load_case, close_case
from .simulation import Experiment, RecordPolicy, compare, forward, input_indices, observation_indices
from .exploration import compare_conditions, select_nodes
from .search import SearchOptions, search, sensitivity


def read_report_source(source):
    """Read saved numeric JSON only; never load recorded neuron trajectories."""
    if isinstance(source,dict):
        return source
    import json
    path=Path(source)
    if path.is_dir():path=path/'comparison.json'
    limit=64*1024*1024
    with path.open('rb') as stream:
        payload=stream.read(limit+1)
    if len(payload)>limit:
        raise ValueError('Saved comparison JSON exceeds the 64 MiB report input limit')
    data=json.loads(payload.decode('utf-8-sig'))
    if not isinstance(data,dict):raise ValueError('Saved comparison JSON must be an object')
    return data


def preview_result_report(source,*,condition_names=None,max_bytes=16*1024*1024,language='en',include_html=False):
    """Return exact offline output sizes without writing or propagating."""
    from .offline_report import render_report
    report=render_report(read_report_source(source),condition_names=condition_names,max_bytes=max_bytes,language=language)
    metadata = {key:value for key,value in report.items() if key not in ('files','report')}
    if include_html:
        metadata['preview_html'] = report['files']['report.html']
    return metadata


def export_result_report(source,destination,*,condition_names=None,max_bytes=16*1024*1024,language='en'):
    """Write a new self-contained report from already saved numeric results."""
    from .offline_report import export_report
    return export_report(read_report_source(source),destination,condition_names=condition_names,max_bytes=max_bytes,language=language)


def local_tasks(results_root):
    """Durable local task API; reading never propagates."""
    from .local_tasks import LocalTasks
    return LocalTasks(results_root)


class Lab:
    """One saved calculation scope and its loaded sparse data.

    Methods delegate to shared domain modules; there is no separate HTTP model.
    Results are returned in memory unless a method explicitly saves them.
    Call close() after use to release mapped case arrays."""
    def response_preview(self, definition):
        from .response_exploration import preview_responses
        return preview_responses(self.case, definition)

    def explore_responses(self, definition, **options):
        from .response_exploration import explore_responses
        return explore_responses(self.case, definition, **options)

    def response_condition(self, report, condition, group_id, **options):
        from .response_exploration import response_condition
        return response_condition(self.case, report, condition, group_id, **options)

    def read_responses(self, path):
        from .response_exploration import load_responses
        return load_responses(path, self.case)

    def response_nodes(self, report, condition, **options):
        from .response_exploration import response_nodes
        from .replay import _identity
        if _identity(self.case)!={k:report.get(k) for k in _identity(self.case)}:
            raise ValueError('Response scope/index/model mismatch')
        return response_nodes(report, condition, **options)

    def response_curves(self, report, condition, group_id, **options):
        from .response_exploration import response_curves
        return self._scope(response_curves(self.case, report, condition, group_id, **options))

    def __init__(self,case_path,geometry_path=None):
        case_path=Path(case_path).expanduser()
        self.case=load_case(case_path)
        self.case_path=Path(case_path).resolve()
        self.geometry_path=Path(geometry_path).expanduser() if geometry_path else self.case_path.parent.parent/'geometry'/'male-cns-em'

    def default_experiment(self):
        """Read this case's default protocol; does not execute a model."""
        return Experiment.from_dict(self.case['manifest'].get('default_experiment',{}))

    def _recording(self,cfg,keep_states,recording):
        if isinstance(recording,dict):return RecordPolicy.from_dict(recording)
        if recording is not None:return recording
        if keep_states and self.case['manifest'].get('case_kind')=='selection':
            indices=set(input_indices(self.case['nodes'],cfg))
            for label in cfg.outputs:indices.update(observation_indices(self.case['nodes'],cfg,label))
            return RecordPolicy(body_ids=tuple(str(self.case['nodes'][i]['bodyId']) for i in sorted(indices)))
        return RecordPolicy(mode='all' if keep_states else 'none')

    def run(self,experiment=None,*,keep_states=False,recording=None):
        """Compute baseline and intervention responses in this scope.

        Recording is separately bounded; keep_states does not change which
        neurons participate in propagation. This method does not save a run."""
        cfg=experiment or self.default_experiment()
        cfg.validate(self.case['nodes'])
        return self._scope(compare(self.case,cfg,recording=self._recording(cfg,keep_states,recording)))

    def forward(self,experiment=None,*,recording=None):
        """Compute one branch, optionally recording selected state samples."""
        cfg=experiment or self.default_experiment()
        policy=RecordPolicy.from_dict(recording) if isinstance(recording,dict) else recording
        return self._scope(forward(self.case,cfg,recording=policy))

    def recording_preview(self,experiment=None,recording=None):
        """Use the allocation preflight used by a two-branch comparison."""
        cfg=experiment or self.default_experiment()
        cfg.validate(self.case['nodes'])
        policy=self._recording(cfg,True,recording)
        return policy.resolve(self.case,cfg,branch_count=2)[2]

    def pathways(self,request=None,*,experiment=None):
        """Structural corridors in this explicit computation scope."""
        from .pathways import analyze_pathways
        cfg=experiment or self.default_experiment()
        cfg.validate(self.case['nodes'])
        request=dict(request or {})
        request.setdefault('source_ids',[str(self.case['nodes'][i]['bodyId'])
            for i in input_indices(self.case['nodes'],cfg)])
        if 'targets' not in request:
            if len(cfg.outputs)>2:
                raise ValueError('Choose one or two observation sets in pathway targets')
            request['targets']={label:[str(self.case['nodes'][i]['bodyId'])
                for i in observation_indices(self.case['nodes'],cfg,label)] for label in cfg.outputs}
        result=self._scope(analyze_pathways(self.case,request))
        from dataclasses import asdict
        from . import MODEL_VERSION
        result.update(case_id=self.case['manifest']['case_id'],model_version=MODEL_VERSION,
                      experiment=asdict(cfg))
        return result

    def _scope(self,result):
        m=self.case['manifest']
        result['computation_node_count']=len(self.case['nodes'])
        result['data_scope']=dict(case_id=m['case_id'],case_name=m.get('case_name',self.case_path.name),
            source_index_id=m.get('source_index_id'),global_endpoint_count=m.get('source_graph_nodes'),
            annotated_record_count=m.get('source_annotated_records'),category_counts=m.get('category_counts'),
            external_input_contacts=m.get('external_input_contacts'),external_output_contacts=m.get('external_output_contacts'))
        return result

    def close(self):
        """Release the loaded case; do not reuse this Lab after closing it."""
        close_case(self.case)

    def compare(self,conditions):
        """Evaluate fixed conditions with the shared comparison implementation."""
        return self._scope(compare_conditions(self.case,conditions))

    def operation_search_preview(self,definition):
        from .operation_search import preview_operation_search
        return self._scope(preview_operation_search(self.case,definition))

    def search_operations(self,definition,**callbacks):
        from .operation_search import search_operations
        return self._scope(search_operations(self.case,definition,**callbacks))

    def operation_plan_curves(self,report,candidate_ids,**kwargs):
        from .operation_search import operation_plan_curves
        return self._scope(operation_plan_curves(self.case,report,candidate_ids,**kwargs))

    def intervention_preview(self,experiment):
        from .interventions import preview_interventions
        return self._scope(preview_interventions(self.case,experiment))

    def intervention_edges(self,source_ids,target_ids,**budgets):
        from .intervention_selection import select_real_edges
        return self._scope(select_real_edges(self.case,source_ids,target_ids,**budgets))

    def compare_operations(self,experiment,a_events,b_events,**kwargs):
        from .exploration import compare_operations
        return self._scope(compare_operations(self.case,experiment,a_events,b_events,**kwargs))

    def select(self,experiment,count,method='id',output=None):
        return self._scope(select_nodes(self.case,experiment,count,method,output))

    def sensitivity(self,experiment,**kwargs):
        return self._scope(sensitivity(self.case,experiment,**kwargs))

    def search(self,experiment,options=None,**kwargs):
        """Search bounded node sets under the supplied protocol and constraints."""
        return self._scope(search(self.case,experiment,options or SearchOptions(),**kwargs))

    def joint_search_preview(self,conditions,options=None,*,include_baselines=False):
        """Validate joint candidates; optional baselines require propagation."""
        from .joint_search import preview_joint_candidates
        return self._scope(preview_joint_candidates(self.case,conditions,options or SearchOptions(),
                                                   include_baselines=include_baselines))

    def search_context(self,experiment,options=None):
        """Inspect candidate ordering and baselines; this can run propagation."""
        from .search import preview_search_context
        return self._scope(preview_search_context(self.case,experiment,options or SearchOptions()))

    def joint_search(self,conditions,options=None,**kwargs):
        from .joint_search import joint_search
        return self._scope(joint_search(self.case,conditions,options or SearchOptions(),**kwargs))

    def evaluate_joint_plan(self,report,body_ids,extra_conditions=()):
        from .joint_search import evaluate_joint_plan
        return self._scope(evaluate_joint_plan(self.case,report,body_ids,list(extra_conditions)))

    def timing_preview(self,conditions,body_ids,starts,durations,options=None):
        from .timing_exploration import preview_timing
        return self._scope(preview_timing(self.case,conditions,body_ids,starts,durations,options or SearchOptions()))

    def explore_timing(self,conditions,body_ids,starts,durations,options=None,**kwargs):
        from .timing_exploration import explore_timing
        return self._scope(explore_timing(self.case,conditions,body_ids,starts,durations,options or SearchOptions(),**kwargs))

    def timing_plan_curves(self,report,start,duration,**kwargs):
        from .timing_exploration import timing_plan_curves
        return self._scope(timing_plan_curves(self.case,report,start,duration,**kwargs))

    def reduction_preview(self,conditions,body_ids,options,*,simplify=False,extra_conditions=None):
        from .plan_reduction import preview_reduction
        return self._scope(preview_reduction(self.case,conditions,body_ids,options,
            simplify=simplify,extra_conditions=extra_conditions))

    def analyze_reduction(self,conditions,body_ids,options,**kwargs):
        from .plan_reduction import analyze_reduction
        return self._scope(analyze_reduction(self.case,conditions,body_ids,options,**kwargs))

    def reduction_curves(self,report,body_ids,**kwargs):
        from .plan_reduction import reduction_plan_curves
        return self._scope(reduction_plan_curves(self.case,report,body_ids,**kwargs))

    def save_reduction(self,root,report):
        from .plan_reduction import save_reduction
        return save_reduction(root,report)

    def load_reduction(self,path):
        from .plan_reduction import load_reduction
        return self._scope(load_reduction(path,self.case))

    def replay_preview(self,source,request=None):
        from .replay import replay_preview
        return self._scope(replay_preview(self.case,source,request or {}))

    def prepare_replay(self,source,request=None,**kwargs):
        """Reuse compatible records or explicitly compute bounded trajectories."""
        from .replay import prepare_replay
        return self._scope(prepare_replay(self.case,source,request or {},**kwargs))

    def replay_frame(self,replay,state_step):
        from .replay import replay_frame
        return replay_frame(self.case,replay,state_step)

    def replay_node(self,replay,body_id):
        from .replay import replay_node
        return replay_node(self.case,replay,body_id)

    def replay_edge(self,replay,edge_id,state_step):
        from .replay import replay_edge
        return replay_edge(self.case,replay,edge_id,state_step)

    def replay_summary(self,replay,window=None,limit=100):
        from .replay import replay_summary
        return replay_summary(self.case,replay,window or replay['default_window'],limit)

    def difference_preview(self,source,request=None):
        from .scope_differences import difference_preview
        return self._scope(difference_preview(self.case,source,request or {}))

    def prepare_differences(self,source,request=None,**kwargs):
        """Prepare scope-wide window statistics, running missing branches if needed."""
        from .scope_differences import prepare_differences
        return self._scope(prepare_differences(self.case,source,request or {},**kwargs))

    def difference_rows(self,result,**kwargs):
        from .scope_differences import difference_rows
        return difference_rows(self.case,result,**kwargs)

    def difference_node(self,result,body_id):
        from .scope_differences import difference_node
        return difference_node(self.case,result,body_id)

    def difference_neighbors(self,result,body_id,**kwargs):
        from .scope_differences import difference_neighbors
        return difference_neighbors(self.case,result,body_id,**kwargs)

    def difference_pathways(self,result,source_ids,targets,request=None):
        from .scope_differences import validate_differences
        from .simulation import effective_observations
        from .replay import _ids
        validate_differences(self.case,result)
        cfg=Experiment.from_dict(result['config']['experiment'])
        available={str(node['bodyId']) for node in self.case['nodes']}
        sources=_ids(source_ids,available,'Pathway sources')
        observations={item['name']:item['body_ids'] for item in effective_observations(self.case['nodes'],cfg)}
        if not isinstance(targets,list) or not 1<=len(targets)<=2 or len(set(targets))!=len(targets) or any(name not in observations for name in targets):
            raise ValueError('Choose one or two exact source observation sets for pathway tracing')
        options=dict(request or {})
        if 'source_ids' in options or 'targets' in options:
            raise ValueError('Pathway endpoints come from the selected difference result')
        options.update(source_ids=sources,targets={name:observations[name] for name in targets})
        from .pathways import analyze_pathways
        from .scope_comparison import _bound_case
        from . import MODEL_VERSION
        from dataclasses import asdict
        view,cfg=_bound_case(self.case,cfg)
        cfg.validate(view['nodes'])
        paths=self._scope(analyze_pathways(self.case,options))
        paths.update(case_id=self.case['manifest']['case_id'],model_version=MODEL_VERSION,experiment=asdict(cfg))
        paths['analysis_source']=dict(kind='scope_differences',config=result['config'])
        return paths

    def _difference_replay_request(self,result,node_ids,request=None):
        from .scope_differences import validate_differences,replay_source_for_differences
        validate_differences(self.case,result)
        options=dict(request or {})
        allowed={'recording','max_nodes','max_edges','window'}
        if set(options)-allowed:raise ValueError('Replay uses the original fixed protocol; only recording/display limits may change')
        options.update(node_ids=node_ids)
        options.setdefault('window',result['config']['window'])
        return replay_source_for_differences(self.case,result),options

    def difference_replay_preview(self,result,node_ids,request=None):
        source,options=self._difference_replay_request(result,node_ids,request)
        return self.replay_preview(source,options)

    def prepare_difference_replay(self,result,node_ids,request=None,**kwargs):
        source,options=self._difference_replay_request(result,node_ids,request)
        replay=self.prepare_replay(source,options,**kwargs)
        # A durable definition, not a path to a mutable editor or an array dump.
        replay['config']['analysis_source']=dict(kind='scope_differences',config=result['config'])
        return replay

    def save_analysis_session(self,root,document):
        from .analysis_sessions import save_analysis_session
        return save_analysis_session(root,self.case,document)

    def read_analysis_session(self,path):
        from .analysis_sessions import read_analysis_session
        return read_analysis_session(path,self.case)

    @property
    def geometry(self):
        from .geometry import GeometryStore
        return GeometryStore(self.case,self.geometry_path)


class Workspace:
    """Complete-data queries and saved independent analysis cases."""
    def __init__(self,index_path,cases_path):
        from .global_index import GlobalIndex
        self.index=GlobalIndex(Path(index_path).expanduser())
        self.cases_path=Path(cases_path).expanduser()

    def spatial(self,geometry_path=None):
        """Global annotation positions, independently of an active Lab."""
        from .spatial import SpatialStore
        if not hasattr(self,'_spatial'):
            self._spatial=SpatialStore(self.index,geometry_root=geometry_path)
        return self._spatial

    def skeletons(self, source_root=None, cache_root=None):
        """Published local precomputed geometry, independent of an active case.

        Reading this store does not scan the downloading directory or prepare
        geometry. Only its explicit prepare operation consumes complete files.
        """
        from .skeleton_spatial import SpatialSkeletonCache
        source = Path(source_root if source_root is not None else
            self.index.path.parent.parent / 'geometry/male-cns-em-precomputed').expanduser().resolve()
        # Let the geometry store derive its cache beside the selected data.
        # Neither an index-relative source nor a selected external source borrows the
        # development tree's data or previously prepared cache.
        cache = Path(cache_root).expanduser().resolve() if cache_root is not None else None
        key = (str(source), str(cache) if cache is not None else None)
        if getattr(self, '_skeleton_key', None) != key:
            self._skeleton_store = SpatialSkeletonCache(source, cache,
                index_id=self.index.manifest['index_id'],
                annotation_ids=self.index.ids[self.index.annotated_positions])
            self._skeleton_key = key
        return self._skeleton_store

    def find(self,filters=None,limit=100,offset=0):
        """Page through global annotation matches without model propagation."""
        return self.index.find(filters,limit,offset)

    def preview_grouping(self, definition, *, case_path=None, reuse_case_path=None):
        """Check structural aggregation resources without scanning raw data."""
        from .group_connections import preview_grouping
        return preview_grouping(self.index, definition, case_path=case_path,
                                reuse_case_path=reuse_case_path)

    def aggregate_groups(self, definition, *, case_path=None, reuse_case_path=None,
                         cancel=None, progress=None):
        """Aggregate real directed contacts; never execute a propagation model."""
        from .group_connections import aggregate_groups
        return aggregate_groups(self.index, definition, case_path=case_path,
                                reuse_case_path=reuse_case_path,
                                cancel=(lambda: False) if cancel is None else cancel,
                                progress=progress)

    def load_grouping(self, path):
        """Open a saved aggregation bound to this local data index."""
        from .group_connections import load_grouping
        return load_grouping(path, index=self.index)

    def group_pair(self, report, source_group, target_group, **kwargs):
        from .group_connections import pair_details
        return pair_details(self.index, report, source_group, target_group, **kwargs)

    def group_members(self, report, group_ids, *, filters=None):
        """Select exact complete group membership independently of display pages."""
        from .group_connections import select_group_members
        return select_group_members(self.index, report, group_ids, filters=filters)

    def scope(self,spec,preview_limit=1000):
        """Resolve a selection and summarize real edges without writing a case."""
        from .selection import select_scope
        import numpy as np
        selection=select_scope(self.index,spec)
        positions=np.searchsorted(self.index.ids,np.asarray(selection['body_ids'],dtype=np.int64))
        counts=self.index.incoming[positions][:,positions]
        total_in=int(self.index.total_input[positions].sum());total_out=int(self.index.total_output[positions].sum())
        contacts=int(counts.sum())
        return dict(selection,nodes=self.index.nodes(selection['body_ids'][:preview_limit]),preview_limit=preview_limit,
                    internal_edges=counts.nnz,internal_contacts=contacts,external_input_contacts=total_in-contacts,
                    external_output_contacts=total_out-contacts,total_input_contacts=total_in)

    def create_case(self,config,destination=None):
        """Write a bounded calculation case using this index's full input totals."""
        from .selection import build_case
        from uuid import uuid4
        destination=Path(destination) if destination is not None else self.cases_path/('case-'+uuid4().hex[:12])
        return build_case(self.index,config,destination)

    def pathways(self,request):
        from .pathways import analyze_pathways
        return analyze_pathways(self.index,request)

    def preview_scopes(self,config):
        from .scope_comparison import preview_scopes
        if config.get('source_index_id')!=self.index.manifest['index_id']:
            raise ValueError('Scope comparison belongs to a different data index')
        return preview_scopes(config)

    def compare_scopes(self,config,**kwargs):
        from .scope_comparison import compare_scopes
        if config.get('source_index_id')!=self.index.manifest['index_id']:
            raise ValueError('Scope comparison belongs to a different data index')
        return compare_scopes(config,**kwargs)

    def close(self):
        """Release index resources after all dependent operations have finished."""
        self.index.close()

    def preview_task(self, definition, **kwargs):
        """Check identity, content and resource requirements without executing."""
        from .task_definition import preview_task
        return preview_task(self.index, self.cases_path, definition, **kwargs)

    def prepare_task(self, definition, **kwargs):
        """Explicitly verify or build the local scope needed by a portable task."""
        from .task_definition import prepare_task
        return prepare_task(self.index, self.cases_path, definition, **kwargs)

    def run_task(self, case_path, definition, **kwargs):
        """Execute an explicitly prepared fixed task against this bound index."""
        from .task_definition import run_task
        # Preparation and execution both bind the explicitly configured index.
        preview = self.preview_task(definition)
        if not preview['compatible'] or preview['errors']:
            raise ValueError('; '.join(preview['errors']))
        if preview.get('verification_required'):
            raise ValueError('Task scope content requires explicit prepare_task verification before execution')
        import json
        manifest=json.loads((Path(case_path)/'manifest.json').read_text(encoding='utf-8-sig'))
        if not isinstance(manifest,dict) or manifest.get('source_index_id')!=self.index.manifest['index_id']:
            raise ValueError('Selected task scope does not belong to the bound local index; use the locally prepared scope')
        return run_task(case_path, definition, **kwargs)

    def boundary(self, case, experiment=None, node_ids=None):
        from .scope_boundary import input_coverage, _check_index
        _check_index(self.index, case)
        return input_coverage(case, experiment, node_ids)

    def external_inputs(self, case, body_ids, **kwargs):
        from .scope_boundary import external_inputs
        return external_inputs(self.index, case, body_ids, **kwargs)

    def preview_expansion(self, base_case_path, config):
        from .scope_expansion import preview_expansion
        return preview_expansion(self.index, base_case_path, config)

    def build_expansion(self, base_case_path, config, **kwargs):
        from .scope_expansion import build_expansion
        return build_expansion(self.index, base_case_path, config, self.cases_path, **kwargs)

    def preview_scope_plans(self, config):
        from .scope_plan_comparison import preview_scope_plans
        if config.get('source_index_id') != self.index.manifest['index_id']:
            raise ValueError('Fixed plans belong to a different data index')
        return preview_scope_plans(config)

    def compare_scope_plans(self, config, **kwargs):
        from .scope_plan_comparison import compare_scope_plans
        if config.get('source_index_id') != self.index.manifest['index_id']:
            raise ValueError('Fixed plans belong to a different data index')
        return compare_scope_plans(config, **kwargs)
