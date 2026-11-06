"""Explore bounded intervention intervals for one exact, fixed node set."""
import copy
import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import numpy as np

from . import MODEL_VERSION
from .exploration import compare_conditions
from .joint_search import annotate_joint_evaluation
from .scope_comparison import _bound_case
from .search import SearchOptions
from .simulation import (Experiment, SimulationCancelled, SimulationPlan,
    effective_input_events, effective_observations, observation_metrics,
    protocol_key, simulate)

MAX_COMBINATIONS = 10000
MAX_FIXED_NODES = 200


def _fixed_ids(case, values):
    if not isinstance(values, (tuple, list)) or not 1 <= len(values) <= MAX_FIXED_NODES or any(
        not isinstance(body, str) or not body.isascii() or not body.isdecimal()
        or str(int(body)) != body or not 0 < int(body) <= np.iinfo(np.int64).max for body in values):
        raise ValueError('Fixed intervention requires 1..200 exact positive int64 string body IDs')
    if len(set(values)) != len(values):
        raise ValueError('Fixed intervention body IDs must be unique')
    available = {str(node['bodyId']) for node in case['nodes']}
    missing = sorted(set(values)-available, key=int)
    if missing:
        raise ValueError('Fixed intervention members are missing from this scope: '+', '.join(missing))
    return sorted(values, key=int)


def _integers(values, label, minimum):
    if not isinstance(values, (tuple, list)) or not values or len(values) > MAX_COMBINATIONS:
        raise ValueError(f'{label} requires a nonempty integer list with at most {MAX_COMBINATIONS} entries')
    if any(type(value) is not int or value < minimum for value in values):
        raise ValueError(f'{label} entries must be strict integers >= {minimum}')
    return sorted(set(values))


def _options(options):
    if options is None:
        options = SearchOptions()
    elif isinstance(options, dict):
        options = SearchOptions.from_dict(options)
    elif not isinstance(options, SearchOptions):
        raise ValueError('options must be SearchOptions or its field dictionary')
    options.validate()
    return copy.deepcopy(options)


def _prepare(case, conditions, body_ids, starts, durations, options):
    options = _options(options)
    bodies = _fixed_ids(case, body_ids)
    starts = _integers(starts, 'starts', 0)
    durations = _integers(durations, 'durations', 1)
    if len(starts)*len(durations) > MAX_COMBINATIONS:
        raise ValueError(f'Timing grid exceeds {MAX_COMBINATIONS} unique combinations')
    if not isinstance(conditions, list) or not 1 <= len(conditions) <= 12:
        raise ValueError('Timing exploration requires 1..12 named conditions')
    parsed, names, reference, order, view = [], set(), None, None, None
    for item in conditions:
        if not isinstance(item, dict) or set(item) != {'name', 'experiment'}:
            raise ValueError('Each timing condition needs name and experiment')
        name = item['name']
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or name in names:
            raise ValueError('Timing condition names must be unique strings of 1..80 characters')
        names.add(name)
        raw = asdict(item['experiment']) if isinstance(item['experiment'], Experiment) else item['experiment']
        cfg = Experiment.from_dict(copy.deepcopy(raw))
        from .interventions import require_legacy_intervention
        require_legacy_intervention(cfg,'Fixed-node timing exploration')
        if type(cfg.steps) is not int or not 1 <= cfg.steps <= 2000:
            raise ValueError('steps must be a strict integer in 1..2000')
        invalid = [dict(start=start, duration=duration, stop=start+duration)
                   for start in starts for duration in durations if start+duration > cfg.steps]
        if invalid:
            raise ValueError(f'Condition {name!r} has timing intervals beyond steps={cfg.steps}: '
                             +json.dumps(invalid, separators=(',', ':')))
        # Original candidate roles and intervention interval are not search variables here.
        cfg = replace(cfg, intervention_ids=tuple(bodies),
            intervention_start=starts[0], intervention_stop=starts[0]+durations[0],
            input_events=tuple(effective_input_events(case['nodes'], cfg)),
            observations=tuple(effective_observations(case['nodes'], cfg)))
        if view is None:
            view, cfg = _bound_case(case, cfg)
        cfg.intervention_group = '__all__'
        cfg.validate(view['nodes'])
        current = dict(steps=cfg.steps, alpha=cfg.alpha, rho=cfg.rho, gain=cfg.gain,
                       observations=protocol_key(view['nodes'], cfg)['observations'])
        if reference is None:
            reference = current
            order = list(cfg.outputs)
        elif current != reference:
            different = ', '.join(key for key in current if current[key] != reference[key])
            raise ValueError(f'Timing condition {name!r} differs in {different}; only input protocols may differ')
        observations = {entry['name']: entry for entry in effective_observations(view['nodes'], cfg)}
        cfg = replace(cfg, observations=tuple(observations[label] for label in order))
        cfg.validate(view['nodes'])
        options.resolve(cfg)
        parsed.append((name, cfg))
    execution = [dict(start=start, duration=duration, stop=start+duration)
                 for start in starts for duration in durations]
    return view, parsed, bodies, options, dict(starts=starts, durations=durations,
        execution_order=execution, combination_count=len(execution), max_combinations=MAX_COMBINATIONS)


def _key(nodes, cfg):
    return json.dumps(protocol_key(nodes, cfg), sort_keys=True, separators=(',', ':'))


def preview_timing(case, conditions, body_ids, starts, durations, options=None):
    """Validate a deduplicated grid without running a baseline or perturbation."""
    view, parsed, bodies, options, grid = _prepare(case, conditions, body_ids, starts, durations, options)
    distinct = len({_key(view['nodes'], cfg) for _, cfg in parsed})
    count = min(grid['combination_count'], options.max_evaluations)
    return dict(kind='timing_preview', case_id=case['manifest']['case_id'], model_version=MODEL_VERSION,
        source_index_id=case['manifest'].get('source_index_id'),
        computation_node_count=len(case['nodes']), conditions=[dict(name=name, experiment=asdict(cfg)) for name, cfg in parsed],
        condition_count=len(parsed), body_ids=bodies, fixed_node_count=len(bodies), gain=parsed[0][1].gain,
        search_options=asdict(options), grid=grid, budget=options.max_evaluations,
        estimated_evaluations=count, estimated_baseline_simulations=distinct,
        estimated_intervention_simulations=count*len(parsed),
        estimated_total_simulations=distinct+count*len(parsed),
        evaluation_unit='one complete fixed interval across every selected input condition',
        node_count_policy='fixed exact IDs; max_nodes is not a timing variable',
        recording=dict(mode='none'), compatible=True)


def _minimal_comparison(view, parsed, bodies, summaries):
    first = parsed[0][1]
    conditions = [dict(name=name, experiment=asdict(cfg)) for name, cfg in parsed]
    rows = [dict(name=name, body_ids=list(bodies), intervention_node_count=len(bodies),
        intervention_group=cfg.intervention_group, gain=cfg.gain, start=cfg.intervention_start,
        stop=cfg.intervention_stop, outputs=summary)
        for (name, cfg), summary in zip(parsed, summaries)]
    results = [dict(config=dict(case_id=view['manifest']['case_id'], model_version=MODEL_VERSION,
                    experiment=asdict(cfg)), summary=summary)
               for (_, cfg), summary in zip(parsed, summaries)]
    protocol = {key: getattr(first, key) for key in ('steps', 'alpha', 'rho')}
    protocol.update(observations=protocol_key(view['nodes'], first)['observations'], outputs=list(first.outputs))
    return dict(case_id=view['manifest']['case_id'], model_version=MODEL_VERSION,
                protocol=protocol, conditions=conditions, rows=rows, results=results)


def _assessment(view, parsed, bodies, summaries, options):
    # The set is fixed. max_nodes may not silently truncate it during timing exploration.
    limits = replace(options, max_nodes=max(options.max_nodes, len(bodies)))
    comparison = annotate_joint_evaluation(_minimal_comparison(view, parsed, bodies, summaries),
        limits, [name for name, _ in parsed])
    return comparison['joint_constraints']


def explore_timing(case, conditions, body_ids, starts, durations, options=None,
                   *, cancel=lambda: False, progress=lambda value: None):
    """Evaluate complete grid entries with rolling state and metrics-only readouts."""
    preview = preview_timing(case, conditions, body_ids, starts, durations, options)
    view, parsed, bodies, options, grid = _prepare(case, conditions, body_ids, starts, durations, options)
    report = dict(preview, kind='timing_exploration', status='complete', termination_reason='grid_completed',
        entries=[dict(interval, status='not_run', condition_results=[], feasible=None,
                      worst_target_loss=None, failed_condition_names=[], error=None)
                 for interval in grid['execution_order']],
        evaluations=0, attempted_evaluations=0, best=None, error=None,
        baseline_simulations=0, completed_baseline_simulations=0,
        intervention_simulations=0, completed_intervention_simulations=0,
        curve_baseline_simulations=0, completed_curve_baseline_simulations=0,
        curve_intervention_simulations=0, completed_curve_intervention_simulations=0,
        curve_requests=[], selected_interval=None,
        method='deterministic bounded interval grid; one fixed exact node set and gain',
        conclusion_scope='completed timing intervals only; untested entries remain unknown',
        optimality='no claim beyond evaluated grid entries')
    plans, baselines, shared = {}, {}, {}
    current_name = None
    def notify(phase, interval=None):
        progress(dict(phase=phase, evaluations=report['evaluations'], budget=report['budget'],
            combination_count=grid['combination_count'], current_condition_name=current_name,
            current_interval=interval, baseline_simulations=report['baseline_simulations'],
            completed_baseline_simulations=report['completed_baseline_simulations'],
            intervention_simulations=report['intervention_simulations'],
            completed_intervention_simulations=report['completed_intervention_simulations']))
    try:
        for name, cfg in parsed:
            current_name = name
            if cancel():
                raise SimulationCancelled('Timing exploration cancelled before baseline completion')
            plan = plans[name] = SimulationPlan(view, cfg, collect_signals=False)
            key = _key(view['nodes'], cfg)
            if key not in shared:
                report['baseline_simulations'] += 1
                notify('baseline')
                shared[key] = simulate(view, cfg, target_indices=[], plan=plan,
                    collect_curves=False, cancel=cancel)
                report['completed_baseline_simulations'] += 1
            baselines[name] = shared[key]
            notify('baseline')
    except SimulationCancelled as error:
        report.update(status='cancelled', termination_reason='cancelled', error=str(error))
    except Exception as error:
        report.update(status='failed', termination_reason='baseline_failed',
                      error=f'Condition {current_name!r}: {error}')
    if report['status'] != 'complete':
        notify(report['status'])
        return report
    by_id = {str(node['bodyId']): index for index, node in enumerate(view['nodes'])}
    targets = np.asarray([by_id[body] for body in bodies], dtype=np.int32)
    for entry in report['entries']:
        if cancel():
            report.update(status='cancelled', termination_reason='cancelled')
            break
        if report['evaluations'] >= report['budget']:
            report.update(status='budget_exhausted', termination_reason='evaluation_budget_reached')
            break
        report['attempted_evaluations'] += 1
        interval_parsed, summaries = [], []
        try:
            for name, original in parsed:
                current_name = name
                if cancel():
                    raise SimulationCancelled('Timing exploration cancelled during an incomplete interval')
                cfg = replace(original, intervention_start=entry['start'], intervention_stop=entry['stop'])
                interval_parsed.append((name, cfg))
                report['intervention_simulations'] += 1
                notify('interval', dict(start=entry['start'], duration=entry['duration'], stop=entry['stop']))
                stats = simulate(view, cfg, gain=cfg.gain, target_indices=targets, plan=plans[name],
                    collect_curves=False, cancel=cancel)
                report['completed_intervention_simulations'] += 1
                summaries.append([dict(type=label, **observation_metrics(view['nodes'], cfg, label,
                    baselines[name], stats)) for label in cfg.outputs])
                # Retain completed member metrics for partial evidence, never publish it as a valid entry.
                partial = _assessment(view, interval_parsed, bodies, summaries, options)
                entry['condition_results'] = partial['condition_results']
            if cancel():
                raise SimulationCancelled('Timing exploration cancelled before interval publication')
            assessment = _assessment(view, interval_parsed, bodies, summaries, options)
            entry.update(status='completed', **{key: assessment[key] for key in
                ('condition_results', 'feasible', 'worst_target_loss', 'failed_condition_names', 'undefined_condition_names')})
            report['evaluations'] += 1
            if entry['worst_target_loss'] is not None:
                def rank(value):
                    return (value['feasible'], value['worst_target_loss'],
                            -value['duration'], -value['start'])
                if report['best'] is None or rank(entry) > rank(report['best']):
                    report['best'] = copy.deepcopy(entry)
            notify('interval_completed', dict(start=entry['start'], duration=entry['duration'], stop=entry['stop']))
        except SimulationCancelled as error:
            entry.update(status='cancelled', error=str(error), failed_condition_names=[current_name])
            report.update(status='cancelled', termination_reason='cancelled', error=str(error))
            break
        except Exception as error:
            entry.update(status='failed', error=str(error), failed_condition_names=[current_name])
            report.update(status='failed', termination_reason='interval_failed',
                          error=f'Condition {current_name!r}, interval [{entry["start"]},{entry["stop"]}): {error}')
            break
    notify(report['status'])
    return report


def timing_conditions(case, conditions, body_ids, start, duration, options=None):
    """Bind a fixed interval by exact ID for the ordinary comparison implementation."""
    view, parsed, _, _, _ = _prepare(case, conditions, body_ids, [start], [duration], options)
    return view, [dict(name=name, experiment=cfg) for name, cfg in parsed]


def timing_plan_curves(case, report, start, duration, *, cancel=lambda: False):
    """Generate curves only for an already completed interval; count added physical work."""
    if not isinstance(report, dict) or report.get('kind') != 'timing_exploration' or report.get('case_id') != case['manifest']['case_id'] or report.get('model_version') != MODEL_VERSION:
        raise ValueError('Timing report case/model identity does not match this scope')
    if report.get('source_index_id') != case['manifest'].get('source_index_id'):
        raise ValueError('Timing report source index version does not match this scope')
    if type(start) is not int or type(duration) is not int:
        raise ValueError('Select an exact completed integer timing interval')
    if not any(row['status'] == 'completed' and row['start'] == start and row['duration'] == duration
               for row in report['entries']):
        raise ValueError('Curves require an actually completed timing interval')
    options = SearchOptions.from_dict(report['search_options'])
    view, fixed = timing_conditions(case, report['conditions'], report['body_ids'], start, duration, options)
    def count(value):
        kind = value['kind']
        key = f'curve_{kind}_simulations' if value['status'] == 'started' else f'completed_curve_{kind}_simulations'
        report[key] = report.get(key, 0)+1
    comparison = compare_conditions(view, fixed, cancel=cancel, simulation_progress=count)
    comparison = annotate_joint_evaluation(comparison,
        replace(options, max_nodes=max(options.max_nodes, len(report['body_ids']))),
        [item['name'] for item in fixed])
    comparison['search_options'] = asdict(options)
    comparison['timing_evaluation'] = dict(start=start, duration=duration, body_ids=list(report['body_ids']),
        search_options=asdict(options), condition_names=[item['name'] for item in fixed])
    report.setdefault('curve_requests', []).append(dict(start=start, duration=duration, stop=start+duration))
    report['selected_interval'] = dict(start=start, duration=duration, stop=start+duration)
    comparison['timing_simulation_counts'] = {key: report.get(key, 0) for key in
        ('curve_baseline_simulations', 'completed_curve_baseline_simulations',
         'curve_intervention_simulations', 'completed_curve_intervention_simulations')}
    return comparison


def save_timing(root, report):
    """Save metrics, full protocols, grid, limits and started/completed work counters."""
    if report.get('kind') != 'timing_exploration':
        raise ValueError('Expected a timing exploration report')
    folder = Path(root)/('timing-exploration-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8])
    folder.mkdir(parents=True)
    config = {key: report[key] for key in ('case_id', 'model_version', 'source_index_id', 'conditions', 'body_ids', 'search_options')}
    config.update(grid=copy.deepcopy(report['grid']), starts=report['grid']['starts'], durations=report['grid']['durations'])
    for filename, content in [('timing-exploration.json', report), ('config.json', config)]:
        (folder/filename).write_text(json.dumps(content, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return folder
