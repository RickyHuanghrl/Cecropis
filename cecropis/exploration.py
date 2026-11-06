"""Exact selections and conditions sharing a computation and observation scope."""
import csv
import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import numpy as np

from . import MODEL_VERSION
from .simulation import (Experiment, SimulationPlan, compare, group_indices, simulate,
                         observation_indices, effective_observations, effective_input_events,
                         protocol_key)
from .signals import output_coefficients
from .interventions import effective_intervention_events, require_legacy_intervention, CompiledInterventions

PROTOCOL_FIELDS = ('steps', 'alpha', 'rho')


def select_nodes(case, cfg, count, method='id', output=None):
    require_legacy_intervention(cfg, 'Node candidate selection')
    cfg.validate(case['nodes'])
    candidates = group_indices(case['nodes'], 'internal', cfg.intervention_group)
    if type(count) is not int or not 1 <= count <= len(candidates):
        raise ValueError(f'Node count must be 1..{len(candidates)}')
    if method not in ('id', 'signal') or (method == 'signal' and output not in cfg.outputs):
        raise ValueError('Choose id or signal ranking and a configured output')
    scores = np.zeros(len(candidates))
    if method == 'signal':
        baseline = simulate(case, cfg, plan=SimulationPlan(case, cfg, collect_signals=False))
        post = observation_indices(case['nodes'], cfg, output)
        coeff = output_coefficients(case['matrix'], post)
        scores = cfg.alpha * cfg.rho * coeff[candidates] * baseline.activity_sum[candidates]
    order = sorted(range(len(candidates)), key=lambda k: (-scores[k], int(case['nodes'][candidates[k]]['bodyId'])))
    rows = [dict(bodyId=str(case['nodes'][candidates[k]]['bodyId']), type=case['nodes'][candidates[k]].get('group_label'),
                 baseline_direct_signal=float(scores[k])) for k in order[:count]]
    return dict(body_ids=[r['bodyId'] for r in rows], nodes=rows, method=method, output=output,
                candidate_count=len(candidates), active_direct_candidates=int(np.count_nonzero(scores)))


def compare_conditions(case, conditions, *, recording=None, cancel=lambda:False, simulation_progress=lambda p:None):
    if not isinstance(conditions, list) or not 1 <= len(conditions) <= 12:
        raise ValueError('Compare 1..12 conditions')
    parsed = []
    for item in conditions:
        if not isinstance(item, dict) or set(item) != {'name', 'experiment'}:
            raise ValueError('Each condition needs name and experiment')
        name = item['name']
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError('Condition name must contain 1..80 characters')
        raw=item['experiment']
        if isinstance(raw,dict) and raw.get('intervention_group')=='__fixed_no_intervention__' and raw.get('intervention_ids')==[]:
            from .plan_reduction import FixedExperiment
            cfg=FixedExperiment.from_dict(raw)
        else:cfg = raw if isinstance(raw, Experiment) else Experiment.from_dict(raw)
        cfg.validate(case['nodes'])
        if cfg.intervention_events is not None:
            CompiledInterventions(case, cfg)
        parsed.append((name, cfg))
    if len({n for n, _ in parsed}) != len(parsed):
        raise ValueError('Condition names must be unique')
    first = parsed[0][1]
    protocol = {key: getattr(first, key) for key in PROTOCOL_FIELDS}
    observations = protocol_key(case['nodes'], first)['observations']
    if any(any(getattr(cfg, key) != value for key, value in protocol.items()) or
           protocol_key(case['nodes'], cfg)['observations'] != observations for _, cfg in parsed):
        raise ValueError('All conditions must share model parameters, steps and exact observation sets')
    protocol['observations'] = observations
    protocol['outputs'] = list(first.outputs)
    baselines = {}
    results, rows = [], []
    for name, cfg in parsed:
        try:
            key = json.dumps(protocol_key(case['nodes'], cfg), sort_keys=True, separators=(',', ':'))
            # Distinct input timelines require their own unperturbed trajectories.
            if key not in baselines:
                simulation_progress(dict(kind='baseline', status='started', condition_name=name))
                baselines[key] = simulate(case, cfg, recording=recording, cancel=cancel)
                simulation_progress(dict(kind='baseline', status='completed', condition_name=name))
            baseline = baselines[key]
            result = compare(case, cfg, recording=recording, _baseline=baseline, cancel=cancel,
                simulation_progress=lambda p, condition=name: simulation_progress(dict(p, condition_name=condition)))
            results.append(result)
            rows.append(dict(name=name, intervention_group=cfg.intervention_group,
                intervention_node_count=result['intervention_node_count'], body_ids=result['intervention_body_ids'],
                gain=cfg.gain, start=cfg.intervention_start, stop=cfg.intervention_stop,
                intervention_events=effective_intervention_events(case['nodes'], cfg),
                intervention_semantics_version=cfg.intervention_semantics_version,
                intervention_edge_count=result['intervention_edge_count'], intervention_edge_pairs=result['intervention_edge_pairs'],
                input_events=effective_input_events(case['nodes'], cfg), outputs=result['summary']))
        except Exception as exc:
            exc.partial_comparison = dict(case_id=case['manifest']['case_id'], model_version=MODEL_VERSION,
                protocol=protocol, baseline_protocol_count=len(baselines),
                conditions=[dict(name=n, experiment=asdict(c)) for n, c in parsed[:len(results)]],
                rows=rows, results=results)
            raise
    return dict(case_id=case['manifest']['case_id'], model_version=MODEL_VERSION, protocol=protocol,
                baseline_protocol_count=len(baselines),
                conditions=[dict(name=name, experiment=asdict(cfg)) for name, cfg in parsed], rows=rows, results=results)


def compare_operations(case, cfg, a_events, b_events, *, recording=None, search_options=None, cancel=lambda:False, simulation_progress=lambda p:None):
    """Four fixed plans; interaction uses window cumulative response, not ratios."""
    from .interventions import normalize_intervention_events, neutral_legacy
    from .simulation import SimulationCancelled
    cfg = cfg if isinstance(cfg, Experiment) else Experiment.from_dict(cfg)
    cfg.validate(case['nodes'])
    if search_options is not None:
        from .search import SearchOptions
        search_options=search_options if isinstance(search_options,SearchOptions) else SearchOptions.from_dict(search_options)
        search_options.resolve(cfg)
    a = normalize_intervention_events(a_events, cfg.steps, case['nodes'])
    b = normalize_intervention_events(b_events, cfg.steps, case['nodes'])
    # Distinct operation labels keep equal targets as separate events while
    # allowing users to select the same named event for both operations.
    def rename(events, prefix):
        return [dict(event, name=f'{prefix}:{i+1} {event["name"]}'[:80]) for i, event in enumerate(events)]
    plans = [[], rename(a, 'A'), rename(b, 'B'), rename(a, 'A') + rename(b, 'B')]
    conditions = [dict(name=name, experiment=asdict(replace(cfg, intervention_events=tuple(events),
                  intervention_semantics_version=1, **neutral_legacy(cfg.steps))))
                  for name, events in zip(('0', 'A', 'B', 'A+B'), plans)]
    counts = dict(baseline_started=0, baseline_completed=0, intervention_started=0, intervention_completed=0,
                  baseline_reused=0, curve_started=0, curve_completed=0)
    def count_progress(p):
        kind, status = p.get('kind'), p.get('status')
        key = f'{kind}_{status}'
        if key in counts:
            counts[key] += 1
        simulation_progress(p)
    # compare_conditions owns protocol baseline reuse. A single cancellation
    # leaves completed conditions available through its progress accumulator.
    try:
        result = compare_conditions(case, conditions, recording=recording, cancel=cancel, simulation_progress=count_progress)
        result['status'] = 'complete'
    except Exception as exc:
        # A partially executed operation cannot produce an interaction value.
        # The shared comparison exposes already completed entries on the error.
        result = getattr(exc, 'partial_comparison', dict(case_id=case['manifest']['case_id'],
            model_version=MODEL_VERSION, protocol=protocol_key(case['nodes'], cfg), rows=[], results=[], conditions=[]))
        result['status'] = 'cancelled' if isinstance(exc, SimulationCancelled) else 'failed'
        result['error'] = str(exc)
    completed_names = {row['name'] for row in result['rows']}
    result['condition_states'] = [dict(name=item['name'], status=('complete' if item['name'] in completed_names else
        result['status'] if len(completed_names) == idx and result['status'] != 'complete' else 'not_run')) for idx, item in enumerate(conditions)]
    result['requested_conditions'] = conditions
    result['operation_comparison'] = dict(a_events=list(a), b_events=list(b), response='window_cumulative',
        definition='R(A+B)-R(A)-R(B)+R(0)', condition_names=['0', 'A', 'B', 'A+B'])
    interactions = []
    if result['status'] == 'complete':
        by_name = {row['name']: {item['type']: item for item in row['outputs']} for row in result['rows']}
        for label in cfg.outputs:
            r0, ra, rb, rab = (by_name[name][label]['intervention_sum'] for name in ('0','A','B','A+B'))
            interactions.append(dict(observation=label, evaluation_window=by_name['0'][label]['evaluation_window'],
                R0=r0, RA=ra, RB=rb, RAB=rab, delta_A=ra-r0, delta_B=rb-r0, delta_AB=rab-r0,
                interaction=rab-ra-rb+r0))
    result['interactions'] = interactions
    result['interaction'] = interactions
    counts['baseline_reused'] = max(0, len(result['results']) - counts['baseline_completed'])
    counts['physical_started'] = counts['baseline_started'] + counts['intervention_started']
    counts['physical_completed'] = counts['baseline_completed'] + counts['intervention_completed']
    result['execution_counts'] = counts
    if search_options is not None:
        annotate_operation_constraints(case,result,search_options)
    return result


def annotate_operation_constraints(case,result,options):
    """Apply existing constraints to saved metrics, never execute a propagation."""
    from dataclasses import replace
    from .plan_reduction import _assess
    from .search import SearchOptions
    from .interventions import intervention_node_ids
    options=options if isinstance(options,SearchOptions) else SearchOptions.from_dict(options)
    result['search_options']=asdict(options)
    result['constraints']=[]
    for condition,row,run in zip(result['conditions'],result['rows'],result['results']):
        cfg=Experiment.from_dict(condition['experiment']);options.resolve(cfg)
        bodies=intervention_node_ids(case['nodes'],cfg)
        metric_cfg=replace(cfg,intervention_events=None,intervention_semantics_version=None,
            intervention_group='__event_metrics__',intervention_ids=tuple(bodies))
        assessed=_assess(case,[(condition['name'],metric_cfg)],bodies,[run['summary']],options,[condition['name']])
        result['constraints'].append(dict(name=condition['name'],role='decision',constraints=assessed))
        row['constraints']=assessed['condition_results'][0]
    return result


def save_comparison(root, result):
    folder = Path(root) / ('comparison-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8])
    folder.mkdir(parents=True)
    config = {k: result[k] for k in ('case_id', 'model_version', 'conditions')}
    if 'operation_comparison' in result:
        config['operation_comparison'] = result['operation_comparison']
        if result.get('search_options') is not None:config['search_options']=result['search_options']
    if result.get('kind') == 'joint_plan_evaluation':
        config['joint_evaluation'] = dict(search_options=result['search_options'],
            search_condition_names=result['joint_constraints']['search_condition_names'])
    if 'timing_evaluation' in result:
        config['timing_evaluation'] = result['timing_evaluation']
    if 'reduction_evaluation' in result:
        config['reduction_evaluation'] = result['reduction_evaluation']
    if 'task_definition' in result:
        config['task_definition'] = result['task_definition']
    saved = dict(result)
    saved['results'] = []
    for index, item in enumerate(result['results']):
        entry = {key: value for key, value in item.items() if key not in ('states', '_history')}
        if 'states' in item:
            filename = f'condition-{index}-states.npz'
            np.savez_compressed(folder / filename, baseline=item['states'][0], intervention=item['states'][1])
            entry['recording_file'] = filename
        saved['results'].append(entry)
    for name, data in [('conditions.json', config), ('comparison.json', saved)]:
        (folder / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    with (folder / 'comparison.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['condition', 'node_count', 'body_ids', 'gain', 'start', 'stop', 'output', 'baseline_sum', 'intervention_sum', 'mean_delta', 'relative_delta', 'baseline_near_zero', 'intervention_edge_count', 'intervention_semantics_version', 'intervention_events_json'])
        for row in result['rows']:
            event_plan = row.get('intervention_semantics_version') == 1
            for output in row['outputs']:
                writer.writerow([row['name'], row['intervention_node_count'], ' '.join(row['body_ids']), '' if event_plan else row['gain'],
                    '' if event_plan else row['start'], '' if event_plan else row['stop'], output['type'], output['baseline_sum'], output['intervention_sum'],
                    output['mean_delta'], output['relative_sum_delta'], output['baseline_near_zero'], row.get('intervention_edge_count', 0),
                    row.get('intervention_semantics_version'), json.dumps(row.get('intervention_events', []), ensure_ascii=False, separators=(',', ':'))])
    return folder
