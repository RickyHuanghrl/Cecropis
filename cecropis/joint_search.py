"""One fixed intervention set evaluated against every selected input protocol."""
import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import numpy as np

from . import MODEL_VERSION
from .exploration import compare_conditions
from .search import (SearchOptions, annotate, bounded_search, resolve_candidates,
                     _metric_loss)
from .simulation import (Experiment, SimulationPlan, SimulationCancelled, simulate,
                         effective_input_events, effective_observations,
                         protocol_key, observation_metrics)


def _parse_conditions(case, conditions, options, *, minimum=2, require_candidate_match=True):
    if not isinstance(conditions, list) or not minimum <= len(conditions) <= 12:
        raise ValueError(f'Joint search requires {minimum}..12 named conditions')
    parsed, names = [], set()
    signature = None
    observation_order = None
    for item in conditions:
        if not isinstance(item, dict) or set(item) != {'name', 'experiment'}:
            raise ValueError('Each condition needs name and experiment')
        name = item['name']
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or name in names:
            raise ValueError('Condition names must be unique nonempty strings of at most 80 characters')
        names.add(name)
        value = item['experiment']
        cfg = Experiment.from_dict(asdict(value) if isinstance(value, Experiment) else value)
        from .interventions import require_legacy_intervention
        require_legacy_intervention(cfg,'Joint node search')
        cfg.validate(case['nodes'])
        metadata = resolve_candidates(case, cfg, options, allow_empty=True)
        current = dict(steps=cfg.steps, alpha=cfg.alpha, rho=cfg.rho,
            observations=protocol_key(case['nodes'], cfg)['observations'],
            gain=cfg.gain, start=cfg.intervention_start, stop=cfg.intervention_stop)
        if require_candidate_match:
            current.update(intervention_group=cfg.intervention_group,
                           candidate_body_ids=metadata['original_candidate_body_ids'])
        if signature is None:
            signature = current
            observation_order = list(cfg.outputs)
        elif current != signature:
            differing = ', '.join(key for key in signature if current[key] != signature[key])
            required = ('model, steps, exact observations, candidate group and original IDs, gain and intervention interval'
                        if require_candidate_match else 'model, steps, exact observations, gain and intervention interval')
            raise ValueError(f'Condition {name!r} differs in {differing}; joint search requires the same '
                             + required)
        observations = {item['name']: item for item in effective_observations(case['nodes'], cfg)}
        cfg = replace(cfg, input_events=tuple(effective_input_events(case['nodes'], cfg)),
            observations=tuple(dict(observations[label], body_ids=sorted(observations[label]['body_ids'], key=int))
                               for label in observation_order),
            intervention_ids=tuple(metadata['original_candidate_body_ids']))
        cfg.validate(case['nodes'])
        options.resolve(cfg)
        parsed.append((name, cfg))
    return parsed


def _candidate_union(case, parsed, options):
    original = resolve_candidates(case, parsed[0][1], options, allow_empty=True)['original_candidate_body_ids']
    endpoints = set()
    for _, cfg in parsed:
        endpoints.update(body for event in effective_input_events(case['nodes'], cfg) for body in event['body_ids'])
        endpoints.update(body for observation in effective_observations(case['nodes'], cfg) for body in observation['body_ids'])
    excluded = [body for body in original if body in endpoints] if options.candidate_policy == 'internal_only' else []
    excluded_set = set(excluded)
    return dict(candidate_policy=options.candidate_policy, original_candidate_count=len(original),
        original_candidate_body_ids=original, candidate_count=len(original)-len(excluded),
        candidate_body_ids=[body for body in original if body not in excluded_set],
        excluded_endpoint_count=len(excluded), excluded_endpoint_body_ids=excluded,
        endpoint_body_ids=sorted(endpoints, key=int))


def preview_joint_candidates(case, conditions, options=None, *, include_baselines=False):
    options = options or SearchOptions()
    parsed = _parse_conditions(case, conditions, options)
    result = dict(case_id=case['manifest']['case_id'], model_version=MODEL_VERSION,
        conditions=[dict(name=name, experiment=asdict(cfg)) for name, cfg in parsed],
        condition_count=len(parsed), **_candidate_union(case, parsed, options))
    if include_baselines:
        evaluator = JointPerturbations(case, conditions, options, lambda:False, lambda p:None, context_only=True)
        result.update(baseline_metrics=evaluator.baseline_metrics(), constraint_context=evaluator.constraint_context,
            candidate_preselection=evaluator.candidate_preselection, baseline_simulations=evaluator.baseline_simulations,
            evaluations=0, intervention_simulations=0)
    return result


def _dimension(condition, observation):
    # JSON encodes both strings without delimiter collisions.
    return json.dumps([condition, observation], ensure_ascii=False, separators=(',', ':'))


def _condition_metrics(name, cfg, baseline, stats, options, target, protected, *, curves=False):
    metrics = {label: observation_metrics([], cfg, label, baseline, stats) for label in cfg.outputs}
    requested = {target: options.target_metric, **{label: spec['metric'] for label, spec in protected.items()}}
    for label, metric in requested.items():
        if metric == 'relative' and metrics[label]['baseline_near_zero']:
            raise ValueError(f'Condition {name!r}, observation {label!r} has a near-zero baseline; choose absolute loss')
    losses = {label: _metric_loss(metrics[label], spec['metric']) for label, spec in protected.items()}
    row = dict(name=name, target_loss=_metric_loss(metrics[target], options.target_metric),
               protected_loss=max(losses.values(), default=0.), protected_losses=losses,
               output_metrics=metrics, output_sums=[metrics[label]['intervention_sum'] for label in cfg.outputs])
    row = annotate(row, options, target, protected)
    if curves:
        row['series'] = {label: dict(baseline=baseline.series[label].tolist(), intervention=stats.series[label].tolist(),
                                     delta=(stats.series[label]-baseline.series[label]).tolist()) for label in cfg.outputs}
    return row


class JointPerturbations:
    """Metrics-only set cache; one logical evaluation completes every protocol."""
    def __init__(self, case, conditions, options, cancel, progress, *, context_only=False):
        self.case, self.options, self.cancel, self.progress = case, options, cancel, progress
        self.parsed = _parse_conditions(case, conditions, options)
        self.candidate_metadata = _candidate_union(case, self.parsed, options)
        if not context_only and not self.candidate_metadata['candidate_count']:
            raise ValueError('No eligible joint search candidates remain after excluding the union of endpoints')
        self.target, self.requested_protected = options.resolve(self.parsed[0][1])
        self.protected = {_dimension(name, label): dict(spec) for name, _ in self.parsed
                          for label, spec in self.requested_protected.items()}
        self.budget, self.cache, self.phase = options.max_evaluations, {}, 'baseline'
        self.cancelled = False
        self.baseline_simulations = self.completed_baseline_simulations = 0
        self.intervention_simulations = self.completed_intervention_simulations = 0
        self.result_simulations = self.completed_result_simulations = 0
        by_id = {str(node['bodyId']): index for index, node in enumerate(case['nodes'])}
        self.candidates = [by_id[body] for body in self.candidate_metadata['candidate_body_ids']]
        self.plans, self.baselines = {}, {}
        shared = {}
        for name, cfg in self.parsed:
            if self.cancel():
                self.cancelled = True
                break
            plan = SimulationPlan(case, cfg, collect_signals=False)
            self.plans[name] = plan
            key = json.dumps(protocol_key(case['nodes'], cfg), sort_keys=True, separators=(',', ':'))
            if key not in shared:
                self.baseline_simulations += 1
                try:
                    shared[key] = simulate(case, cfg, target_indices=[], plan=plan, cancel=self.cancel)
                except SimulationCancelled:
                    self.cancelled = True
                    break
                self.completed_baseline_simulations += 1
            baseline = self.baselines[name] = shared[key]
            if not context_only:
                _condition_metrics(name, cfg, baseline, baseline, options, self.target, self.requested_protected)
            self.notify()
        from .search_explanations import candidate_preselection, constraint_context
        self.candidates, self.candidate_preselection = candidate_preselection(case, self.parsed,
            self.baselines, self.candidates, self.target, options.candidate_order, cancel=cancel)
        self.constraint_context = constraint_context(self.parsed, self.baseline_metrics(),
                                                     self.target, self.requested_protected, options)
        self.phase = 'sensitivity'

    def baseline_metrics(self):
        return {name: {label: observation_metrics(self.case['nodes'], cfg, label, base, base)
                       for label in cfg.outputs}
                for name, cfg in self.parsed if (base := self.baselines.get(name)) is not None}

    def notify(self):
        self.progress(dict(phase=self.phase, evaluations=len(self.cache), budget=self.budget,
            candidate_count=len(self.candidates), condition_count=len(self.parsed),
            baseline_simulations=self.baseline_simulations,
            intervention_simulations=self.intervention_simulations, result_simulations=self.result_simulations))

    def stopped(self):
        return self.cancelled or self.cancel() or len(self.cache) >= self.budget

    def evaluate(self, indices):
        key = tuple(sorted(indices))
        if key in self.cache:
            return self.cache[key]
        if self.stopped():
            return None
        condition_results = []
        for name, cfg in self.parsed:
            if self.cancel():
                self.cancelled = True
                return None
            self.intervention_simulations += 1
            try:
                stats = simulate(self.case, cfg, target_indices=np.asarray(key, dtype=np.int32),
                    gain=cfg.gain, plan=self.plans[name], cancel=self.cancel, collect_curves=False)
            except SimulationCancelled:
                self.cancelled = True
                return None
            self.completed_intervention_simulations += 1
            condition_results.append(_condition_metrics(name, cfg, self.baselines[name], stats,
                self.options, self.target, self.requested_protected))
        # A stop during or immediately after the final physical run cannot publish
        # a partial logical evaluation. The previous completed cache stays intact.
        if self.cancel():
            self.cancelled = True
            return None
        bodies = [str(self.case['nodes'][index]['bodyId']) for index in key]
        for row in condition_results:
            row.update(body_ids=bodies, node_count=len(bodies))
        worst = min(row['target_loss'] for row in condition_results)
        protected_losses = {_dimension(row['name'], label): loss for row in condition_results
                            for label, loss in row['protected_losses'].items()}
        row = dict(body_ids=bodies, node_count=len(bodies), condition_results=condition_results,
            target_loss=worst, worst_target_loss=worst,
            mean_target_loss=sum(item['target_loss'] for item in condition_results)/len(condition_results),
            protected_losses=protected_losses, protected_loss=max(protected_losses.values(), default=0.))
        self.cache[key] = row
        self.notify()
        return row

    def annotate(self, row):
        result = annotate(row, self.options, self.target, self.protected)
        result['failed_condition_names'] = [item['name'] for item in row['condition_results'] if not item['feasible']]
        result['feasible'] = not result['failed_condition_names']
        return result

    def effect_order(self, row):
        return (-row['target_loss'], -row['mean_target_loss'], row['protected_loss'])

    def improves(self, row, previous):
        old_worst = previous['target_loss'] if previous else 0.
        old_mean = previous['mean_target_loss'] if previous else 0.
        return (row['target_loss'] > old_worst+1e-15 or
                (abs(row['target_loss']-old_worst) <= 1e-15 and row['mean_target_loss'] > old_mean+1e-15))

    def best_curves(self, row):
        if row is None or self.cancelled or self.cancel():
            return row
        self.phase = 'result_curves'
        by_id = {str(n['bodyId']): index for index, n in enumerate(self.case['nodes'])}
        indices = np.asarray([by_id[body] for body in row['body_ids']], dtype=np.int32)
        complete = []
        for name, cfg in self.parsed:
            if self.cancel():
                self.cancelled = True
                return row
            self.result_simulations += 1
            try:
                stats = simulate(self.case, cfg, target_indices=indices, gain=cfg.gain,
                                 plan=self.plans[name], cancel=self.cancel)
            except SimulationCancelled:
                self.cancelled = True
                return row
            self.completed_result_simulations += 1
            item = _condition_metrics(name, cfg, self.baselines[name], stats,
                self.options, self.target, self.requested_protected, curves=True)
            item.update(body_ids=row['body_ids'], node_count=row['node_count'])
            complete.append(item)
            self.notify()
        if self.cancel():
            self.cancelled = True
            return row
        return dict(row, condition_results=complete)


def joint_search(case, conditions, options=None, *, cancel=lambda:False, progress=lambda p:None):
    options = options or SearchOptions()
    options.validate()
    evaluator = JointPerturbations(case, conditions, options, cancel, progress)
    result = bounded_search(evaluator, options)
    result['best'] = evaluator.best_curves(result['best'])
    if evaluator.cancelled or cancel():
        result.update(status='cancelled', termination_reason='cancelled')
    normal = [dict(name=name, experiment=asdict(cfg)) for name, cfg in evaluator.parsed]
    result.update(kind='joint_search', case_id=case['manifest']['case_id'], model_version=MODEL_VERSION,
        conditions=normal, condition_count=len(normal), options=asdict(options), search_options=asdict(options),
        target_output=evaluator.target, target_metric=options.target_metric,
        requested_protected_limits=evaluator.requested_protected, protected_limits=evaluator.protected,
        protected_outputs=list(evaluator.requested_protected),
        baseline_metrics=evaluator.baseline_metrics(),
        constraint_context=evaluator.constraint_context, candidate_preselection=evaluator.candidate_preselection,
        baseline_simulations=evaluator.baseline_simulations,
        completed_baseline_simulations=evaluator.completed_baseline_simulations,
        intervention_simulations=evaluator.intervention_simulations,
        completed_intervention_simulations=evaluator.completed_intervention_simulations,
        result_simulations=evaluator.result_simulations,
        completed_result_simulations=evaluator.completed_result_simulations,
        total_intervention_simulations=evaluator.intervention_simulations+evaluator.result_simulations,
        evaluation_unit='one complete fixed node set across every selected condition',
        curves_available=bool(result['best'] and all('series' in item for item in result['best']['condition_results'])),
        **evaluator.candidate_metadata)
    result['method'] = 'single perturbations, bounded shortlist, greedy joint runs, local swaps; worst target loss with mean tie-break only'
    from .search_explanations import search_diagnostics
    result['search_diagnostics'] = search_diagnostics(result, evaluator.constraint_context)
    evaluator.phase = result['status']
    evaluator.notify()
    return result


def save_joint_search(root, result):
    if result.get('kind') != 'joint_search':
        raise ValueError('Expected a joint search report')
    folder = Path(root)/('joint-search-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8])
    folder.mkdir(parents=True)
    replay = dict(case_id=result['case_id'], model_version=result['model_version'],
        conditions=result['conditions'], search_options=result['options'])
    for key in ('candidate_policy', 'original_candidate_count', 'original_candidate_body_ids', 'candidate_count',
                'candidate_body_ids', 'excluded_endpoint_count', 'excluded_endpoint_body_ids', 'endpoint_body_ids'):
        replay[key] = result[key]
    for name, value in [('joint-search.json', result), ('config.json', replay)]:
        (folder/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    if result['best']:
        conditions = [dict(item, experiment=dict(item['experiment'], intervention_ids=result['best']['body_ids']))
                      for item in result['conditions']]
        fixed = dict(case_id=result['case_id'], model_version=result['model_version'],
            conditions=conditions, evidence_classification='search', body_ids=result['best']['body_ids'],
            search_options=result['options'], joint_evaluation=dict(search_options=result['options'],
                search_condition_names=[item['name'] for item in result['conditions']]))
        (folder/'conditions.json').write_text(json.dumps(fixed, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return folder


def evaluate_joint_plan(case, report, body_ids, extra_conditions=None):
    """Evaluate an already proposed fixed set; extra conditions never influence search."""
    if not isinstance(report, dict) or report.get('case_id') != case['manifest']['case_id'] or report.get('model_version') != MODEL_VERSION:
        raise ValueError('Joint report case/model version does not match the computation scope')
    if report.get('kind') != 'joint_search':
        raise ValueError('Expected a joint search report')
    options = SearchOptions.from_dict(report.get('options', report.get('search_options', {})), legacy=True)
    parsed = _parse_conditions(case, report['conditions'], options)
    metadata = _candidate_union(case, parsed, options)
    if not isinstance(body_ids, (tuple, list)) or not body_ids or len(body_ids) > options.max_nodes or any(
            not isinstance(body, str) or body not in metadata['candidate_body_ids'] for body in body_ids) or len(set(body_ids)) != len(body_ids):
        raise ValueError('Fixed plan must contain unique actual eligible candidate IDs within max_nodes')
    requested = tuple(sorted(body_ids, key=int))
    proposals = [report.get('best')] + [row for key in ('evaluated', 'frontier', 'sensitivity') for row in report.get(key, [])]
    if not any(row and tuple(sorted(row.get('body_ids', []), key=int)) == requested for row in proposals):
        raise ValueError('Fixed plan must be an actually evaluated joint search set')
    extra_conditions = [] if extra_conditions is None else extra_conditions
    if not isinstance(extra_conditions, list) or len(parsed)+len(extra_conditions) > 12:
        raise ValueError('Training and extra conditions together must contain at most 12 conditions')
    # Validate every extra protocol, name and compatibility before any simulation.
    combined = [dict(name=name, experiment=cfg) for name, cfg in parsed] + extra_conditions
    all_parsed = _parse_conditions(case, combined, options, require_candidate_match=False)
    fixed = [dict(name=name, experiment=replace(cfg, intervention_group=parsed[0][1].intervention_group,
                                               intervention_ids=requested)) for name, cfg in all_parsed]
    comparison = compare_conditions(case, fixed)
    comparison['body_ids'] = list(requested)
    return annotate_joint_evaluation(comparison, options, [name for name, _ in parsed])


def annotate_joint_evaluation(comparison, options, search_condition_names, *, allow_empty=False):
    """Classify a fixed comparison without optimizing or suppressing undefined metrics."""
    options = options if isinstance(options, SearchOptions) else SearchOptions.from_dict(options, legacy=True)
    if not isinstance(search_condition_names, (list, tuple)) or not search_condition_names or any(
            not isinstance(name, str) for name in search_condition_names) or len(set(search_condition_names)) != len(search_condition_names):
        raise ValueError('Search condition names must be a unique nonempty list')
    names = [item['name'] for item in comparison['conditions']]
    if not set(search_condition_names) <= set(names) or len(set(names)) != len(names):
        raise ValueError('Search condition names must match unique comparison conditions')
    cfg = Experiment.from_dict(comparison['conditions'][0]['experiment'])
    target, protected = options.resolve(cfg)
    if len(comparison['rows']) != len(names) or len(comparison['results']) != len(names):
        raise ValueError('Every fixed evaluation condition requires its own complete result')
    fixed_ids = sorted(comparison['rows'][0]['body_ids'], key=int)
    if (not fixed_ids and not allow_empty) or len(fixed_ids) != len(set(fixed_ids)) or len(fixed_ids) > options.max_nodes:
        raise ValueError('Fixed evaluation requires unique node IDs within max_nodes')
    fixed_interval = (cfg.gain, cfg.intervention_start, cfg.intervention_stop)
    reference_observations = comparison['protocol']['observations']
    for item, row, result in zip(comparison['conditions'], comparison['rows'], comparison['results']):
        current = Experiment.from_dict(item['experiment'])
        if sorted(row['body_ids'], key=int) != fixed_ids or (current.gain, current.intervention_start, current.intervention_stop) != fixed_interval:
            raise ValueError('Every fixed evaluation condition must use the same exact node set, gain and intervention interval')
        if any(getattr(current, key) != getattr(cfg, key) for key in ('steps', 'alpha', 'rho')):
            raise ValueError('Every fixed evaluation condition must share model parameters and steps')
        if current.observations is not None:
            normalized = lambda values: sorted((item['name'], tuple(sorted(item['body_ids'], key=int)),
                item.get('evaluation_window', dict(start=0,stop=current.steps))['start'],
                item.get('evaluation_window', dict(start=0,stop=current.steps))['stop']) for item in values)
            if normalized(current.observations) != normalized(reference_observations):
                raise ValueError('Every fixed evaluation condition must share exact observations')
        elif set(current.outputs) != {item['name'] for item in reference_observations}:
            raise ValueError('Every fixed evaluation condition must share observation names')
        if result['config']['case_id'] != comparison['case_id'] or result['config']['model_version'] != comparison['model_version']:
            raise ValueError('Fixed evaluation result case/model identity does not match')
    constraints, failed = [], []
    undefined = []
    for name, row, result in zip(names, comparison['rows'], comparison['results']):
        metrics = {item['type']: item for item in result['summary']}
        def loss(label, metric):
            return None if metric == 'relative' and metrics[label]['relative_sum_delta'] is None else _metric_loss(metrics[label], metric)
        losses = {label: loss(label, spec['metric']) for label, spec in protected.items()}
        target_loss = loss(target, options.target_metric)
        target_ok = target_loss is not None and target_loss+1e-12 >= options.min_target_loss
        protected_constraints = {label: dict(metric=spec['metric'], limit=spec['max_loss'], loss=losses[label],
            satisfied=losses[label] is not None and losses[label] <= spec['max_loss']+1e-12,
            defined=losses[label] is not None) for label, spec in protected.items()}
        violations = []
        if not target_ok:
            violations.append('undefined_target_metric' if target_loss is None else 'minimum_target_loss')
        for label, constraint in protected_constraints.items():
            if not constraint['satisfied']:
                violations.append(f'undefined_protected_metric:{label}' if not constraint['defined'] else f'protected:{label}')
        if any(not constraint['satisfied'] for constraint in protected_constraints.values()):
            violations.append('maximum_protected_loss')
        assessment = dict(name=name, body_ids=list(row['body_ids']), node_count=len(row['body_ids']),
            target_loss=target_loss, protected_losses=losses,
            protected_loss=None if any(value is None for value in losses.values()) else max(losses.values(), default=0.),
            output_metrics=metrics, feasible=not violations, violations=violations,
            protected_constraints=protected_constraints,
            target_constraint=dict(observation=target, metric=options.target_metric, minimum=options.min_target_loss,
                                   loss=target_loss, satisfied=target_ok, defined=target_loss is not None))
        classification = 'search' if name in search_condition_names else 'extra'
        assessment['evidence_classification'] = classification
        row.update(evidence_classification=classification, constraints=assessment)
        result['evidence_classification'] = classification
        constraints.append(assessment)
        if not assessment['feasible']:
            failed.append(name)
        if target_loss is None or any(value is None for value in losses.values()):
            undefined.append(name)
    comparison.update(kind='joint_plan_evaluation', body_ids=fixed_ids, search_options=asdict(options),
        evidence_classification='fixed_plan_evaluation',
        search_condition_names=list(search_condition_names),
        joint_constraints=dict(feasible=not failed, failed_condition_names=failed,
            worst_target_loss=None if any(row['target_loss'] is None for row in constraints) else min(row['target_loss'] for row in constraints),
            undefined_condition_names=undefined, condition_results=constraints,
            search_condition_names=list(search_condition_names), extra_condition_names=[name for name in names if name not in search_condition_names]))
    from .search_explanations import constraint_context, explain_condition, search_diagnostics
    parsed = [(item['name'], Experiment.from_dict(item['experiment'])) for item in comparison['conditions']]
    means = {row['name']: row['output_metrics'] for row in constraints}
    context = constraint_context(parsed, means, target, protected, options)
    comparison['constraint_context'] = context
    contexts = {item['name']: item for item in context['conditions']}
    for row in comparison['rows']:
        assessment = row['constraints']
        assessment['explanation'] = explain_condition(row['name'], assessment['output_metrics'], contexts[row['name']],
            assessment['target_constraint'], assessment['protected_constraints'])
    comparison['search_diagnostics'] = search_diagnostics(comparison, context, fixed_evaluation=True)
    return comparison
