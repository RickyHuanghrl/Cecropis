"""Budgeted joint-set search over one complete input/observation protocol."""
import json
import math
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import numpy as np
from . import MODEL_VERSION
from .simulation import (SimulationPlan, intervention_indices, simulate, observation_metrics,
                         effective_input_events, effective_observations)


@dataclass
class SearchOptions:
    # First six fields retain the existing positional API.
    max_nodes: int = 10
    max_evaluations: int = 1000
    max_protected_loss: float = .01
    min_target_loss: float = 0.
    shortlist: int = 24
    swap_passes: int = 1
    target_output: str | None = None
    target_metric: str = 'relative'
    protected_limits: dict | None = None
    candidate_policy: str = 'internal_only'
    candidate_order: str = 'signal_path'

    @classmethod
    def from_dict(cls, data, *, legacy=False):
        if not isinstance(data, dict) or set(data) - {field.name for field in fields(cls)}:
            raise ValueError('Unrecognized search option fields')
        values = dict(data)
        if legacy and 'candidate_policy' not in values:
            values['candidate_policy'] = 'allow_endpoints'
        if legacy and 'candidate_order' not in values:
            values['candidate_order'] = 'body_id'
        result = cls(**values)
        result.validate()
        return result

    def validate(self):
        for key, lo, hi in [('max_nodes',1,200),('max_evaluations',1,10000),('shortlist',1,200),('swap_passes',0,5)]:
            value = getattr(self, key)
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError(f'{key} must be an integer in [{lo}, {hi}]')
        for key in ('max_protected_loss', 'min_target_loss'):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f'{key} must be finite in [0, 1]')
        if self.target_output is not None and (not isinstance(self.target_output, str) or not self.target_output):
            raise ValueError('target_output must name an observation set')
        if self.target_metric not in ('relative', 'absolute'):
            raise ValueError('target_metric must be relative or absolute')
        if self.candidate_policy not in ('internal_only', 'allow_endpoints'):
            raise ValueError('candidate_policy must be internal_only or allow_endpoints')
        if self.candidate_order not in ('signal_path', 'body_id'):
            raise ValueError('candidate_order must be signal_path or body_id')
        if self.protected_limits is not None:
            if not isinstance(self.protected_limits, dict):
                raise ValueError('protected_limits must map observation names to limits')
            for name, limit in self.protected_limits.items():
                if not isinstance(name, str) or not name or not isinstance(limit, dict) or set(limit) != {'max_loss', 'metric'}:
                    raise ValueError('Each protected limit needs max_loss and metric')
                value = limit['max_loss']
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError('Protected max_loss must be finite in [0, 1]')
                if limit['metric'] not in ('relative', 'absolute'):
                    raise ValueError('Protected metric must be relative or absolute')

    def resolve(self, cfg):
        self.validate()
        target = self.target_output or cfg.outputs[0]
        protected = (dict(self.protected_limits) if self.protected_limits is not None else
                     ({cfg.outputs[1]: dict(max_loss=self.max_protected_loss, metric='relative')} if len(cfg.outputs) > 1 else {}))
        if target not in cfg.outputs or any(name not in cfg.outputs for name in protected):
            raise ValueError('Search target and protected sets must be configured observations')
        if target in protected:
            raise ValueError('The target observation cannot also be protected')
        return target, protected


def resolve_candidates(case, cfg, options, *, allow_empty=False):
    """Resolve search eligibility without running a baseline or altering the protocol.

    Operation roles supply the original selection. Current event and observation
    members determine endpoints, including nodes with overlapping roles.
    """
    from .interventions import require_legacy_intervention
    require_legacy_intervention(cfg,'Node search')
    cfg.validate(case['nodes'])
    options.validate()
    original = sorted((str(case['nodes'][index]['bodyId'])
                       for index in intervention_indices(case['nodes'], cfg)), key=int)
    endpoints = {body for event in effective_input_events(case['nodes'], cfg) for body in event['body_ids']}
    endpoints.update(body for observation in effective_observations(case['nodes'], cfg)
                     for body in observation['body_ids'])
    excluded = [body for body in original if body in endpoints] if options.candidate_policy == 'internal_only' else []
    excluded_set = set(excluded)
    eligible = [body for body in original if body not in excluded_set]
    if not eligible and not allow_empty:
        raise ValueError('No eligible search candidates remain under candidate_policy; select internal nodes or allow_endpoints')
    return dict(candidate_policy=options.candidate_policy,
                original_candidate_count=len(original), original_candidate_body_ids=original,
                candidate_count=len(eligible), candidate_body_ids=eligible,
                excluded_endpoint_count=len(excluded), excluded_endpoint_body_ids=excluded)


def _metric_loss(metrics, metric):
    return -metrics['relative_sum_delta'] if metric == 'relative' else -metrics['mean_delta']


class Perturbations:
    """Baseline and jointly simulated set cache for a complete fixed protocol."""
    def __init__(self, case, cfg, budget, cancel, progress, options=None, *, context_only=False):
        self.options = options or SearchOptions()
        self.candidate_metadata = resolve_candidates(case, cfg, self.options, allow_empty=context_only)
        self.target, self.protected = self.options.resolve(cfg)
        self.case, self.cfg, self.budget = case, cfg, budget
        self.cancel, self.progress = cancel, progress
        by_id = {str(node['bodyId']): index for index, node in enumerate(case['nodes'])}
        self.candidates = [by_id[body] for body in self.candidate_metadata['candidate_body_ids']]
        self.plan = SimulationPlan(case, cfg, collect_signals=False)
        self.baseline = simulate(case, cfg, target_indices=[], plan=self.plan)
        self.baseline_metrics = {label: observation_metrics(case['nodes'], cfg, label, self.baseline, self.baseline) for label in cfg.outputs}
        self.sums = [self.baseline_metrics[label]['baseline_sum'] for label in cfg.outputs]
        requested_metrics = {self.target: self.options.target_metric, **{name: spec['metric'] for name, spec in self.protected.items()}}
        for label, metric in requested_metrics.items():
            if not context_only and metric == 'relative' and self.baseline_metrics[label]['baseline_near_zero']:
                raise ValueError(f'Observation {label!r} has a near-zero baseline; choose absolute loss or another observation')
        from .search_explanations import candidate_preselection, constraint_context
        self.candidates, self.candidate_preselection = candidate_preselection(case, [('single', cfg)],
            {'single': self.baseline}, self.candidates, self.target, self.options.candidate_order, cancel=cancel)
        self.constraint_context = constraint_context([('single', cfg)], {'single': self.baseline_metrics},
                                                     self.target, self.protected, self.options)
        self.cache = {}
        self.phase = 'sensitivity'

    def stopped(self):
        return self.cancel() or len(self.cache) >= self.budget

    def evaluate(self, indices):
        key = tuple(sorted(indices))
        if key in self.cache:
            return self.cache[key]
        if self.stopped():
            return None
        stats = simulate(self.case, self.cfg, target_indices=np.asarray(key, dtype=np.int32), gain=self.cfg.gain,
                         plan=self.plan, collect_curves=False)
        metrics = {label: observation_metrics(self.case['nodes'], self.cfg, label, self.baseline, stats) for label in self.cfg.outputs}
        sums = [metrics[label]['intervention_sum'] for label in self.cfg.outputs]
        losses = {name: _metric_loss(metrics[name], spec['metric']) for name, spec in self.protected.items()}
        row = dict(body_ids=[str(self.case['nodes'][i]['bodyId']) for i in key], node_count=len(key),
                   target_loss=_metric_loss(metrics[self.target], self.options.target_metric),
                   protected_loss=max(losses.values(), default=0.), protected_losses=losses,
                   output_sums=sums, output_metrics=metrics)
        self.cache[key] = row
        self.progress(dict(phase=self.phase, evaluations=len(self.cache), budget=self.budget,
                           candidate_count=len(self.candidates)))
        return row


def _protected_ok(row, limits):
    return all(row['protected_losses'][name] <= spec['max_loss'] + 1e-12 for name, spec in limits.items())


def annotate(row, options, target=None, protected=None):
    protected = protected if protected is not None else (options.protected_limits or {})
    constraints = {name: dict(metric=spec['metric'], limit=spec['max_loss'], loss=row['protected_losses'][name],
                              satisfied=row['protected_losses'][name] <= spec['max_loss'] + 1e-12)
                   for name, spec in protected.items()}
    target_ok = row['target_loss'] + 1e-12 >= options.min_target_loss
    violations = [f'protected:{name}' for name, spec in constraints.items() if not spec['satisfied']]
    if not target_ok:
        violations.append('minimum_target_loss')
    if any(not spec['satisfied'] for spec in constraints.values()):
        violations.append('maximum_protected_loss')
    return dict(row, feasible=not violations, violations=violations, protected_constraints=constraints,
                target_constraint=dict(observation=target, metric=options.target_metric,
                                       minimum=options.min_target_loss, loss=row['target_loss'], satisfied=target_ok))


def frontier(rows):
    """Non-dominance includes each protected dimension, rather than their mean."""
    ordered = sorted(rows, key=lambda r: (r['node_count'], -r['target_loss'], r['protected_loss'], r['body_ids']))
    result = []
    def dominates(previous, row):
        return (previous['node_count'] <= row['node_count'] and previous['target_loss'] >= row['target_loss'] and
                all(previous['protected_losses'][name] <= value for name, value in row['protected_losses'].items()))
    for row in ordered:
        if any(dominates(previous, row) for previous in result):
            continue
        result = [previous for previous in result if not dominates(row, previous)]
        result.append(row)
    return result


def _report_protocol(evaluator):
    return dict(target_output=evaluator.target, target_metric=evaluator.options.target_metric,
                protected_outputs=list(evaluator.protected), protected_limits=evaluator.protected,
                protected_output=next(iter(evaluator.protected), None), baseline_sums=evaluator.sums,
                baseline_metrics=evaluator.baseline_metrics,
                candidate_preselection=evaluator.candidate_preselection, constraint_context=evaluator.constraint_context)


def preview_search_context(case, cfg, options=None):
    """Explicit baseline-only preview; no perturbation evaluation or threshold changes."""
    options = options or SearchOptions()
    evaluator = Perturbations(case, cfg, options.max_evaluations, lambda:False, lambda p:None, options, context_only=True)
    return dict(case_id=case['manifest']['case_id'], model_version=MODEL_VERSION,
                **evaluator.candidate_metadata, **_report_protocol(evaluator), baseline_simulations=1,
                evaluations=0, intervention_simulations=0)


def sensitivity(case, cfg, max_evaluations=10000, *, options=None, cancel=lambda:False, progress=lambda p:None):
    if type(max_evaluations) is not int or not 1 <= max_evaluations <= 10000:
        raise ValueError('max_evaluations must be an integer in [1, 10000]')
    evaluator = Perturbations(case, cfg, max_evaluations, cancel, progress, options)
    rows = []
    for index in evaluator.candidates:
        row = evaluator.evaluate([index])
        if row is None:
            break
        rows.append(dict(annotate(row, evaluator.options, evaluator.target, evaluator.protected),
                         bodyId=row['body_ids'][0], type=case['nodes'][index].get('group_label', case['nodes'][index].get('type'))))
    rows.sort(key=lambda r: (-r['target_loss'], r['protected_loss'], int(r['bodyId'])))
    fixed_cfg = asdict(replace(cfg, intervention_ids=tuple(evaluator.candidate_metadata['original_candidate_body_ids'])))
    result = dict(case_id=case['manifest']['case_id'], model_version=MODEL_VERSION, experiment=fixed_cfg,
                options=asdict(evaluator.options), **_report_protocol(evaluator), nodes=rows,
                **evaluator.candidate_metadata, evaluations=len(rows),
                status='cancelled' if cancel() else ('complete' if len(rows)==len(evaluator.candidates) else 'budget_exhausted'))
    from .search_explanations import search_diagnostics
    result['search_diagnostics'] = search_diagnostics(result, evaluator.constraint_context)
    return result


def _effect_order(evaluator, row):
    # Joint protocols may break equal worst effects by their mean effect. This
    # changes proposal order only; feasibility always uses every constraint.
    if hasattr(evaluator, 'effect_order'):
        return evaluator.effect_order(row)
    return (-row['target_loss'], row['protected_loss'])


def _improves(evaluator, row, previous):
    if hasattr(evaluator, 'improves'):
        return evaluator.improves(row, previous)
    return row['target_loss'] > (previous['target_loss'] if previous else 0.) + 1e-15


def _annotate(evaluator, row):
    if hasattr(evaluator, 'annotate'):
        return evaluator.annotate(row)
    return annotate(row, evaluator.options, evaluator.target, evaluator.protected)


def bounded_search(evaluator, options):
    """Shared finite set proposal loop; evaluators own simulation and budget units."""
    case = evaluator.case
    single = []
    reserved = min(options.shortlist, len(evaluator.candidates), options.max_evaluations // 2)
    scan_count = min(len(evaluator.candidates), max(1, options.max_evaluations-reserved))
    for index in evaluator.candidates[:scan_count]:
        row = evaluator.evaluate([index])
        if row is None:
            break
        single.append((index, row))
    ranked = sorted(single, key=lambda pair: (*_effect_order(evaluator, pair[1]), int(pair[1]['body_ids'][0])))
    eligible = [index for index, row in ranked if _protected_ok(row, evaluator.protected)][:options.shortlist]
    selected, current = [], None
    evaluator.phase = 'greedy'
    while len(selected) < options.max_nodes:
        choices = []
        for index in eligible:
            if index in selected:
                continue
            row = evaluator.evaluate(selected+[index])
            if row is None:
                break
            if _protected_ok(row, evaluator.protected):
                choices.append((index, row))
        if not choices:
            break
        index, row = min(choices, key=lambda pair: (*_effect_order(evaluator, pair[1]), pair[0]))
        if not _improves(evaluator, row, current):
            break
        selected.append(index)
        current = row
        if evaluator.stopped():
            break
    evaluator.phase = 'swap'
    for _ in range(options.swap_passes):
        if not selected or evaluator.stopped():
            break
        best_swap = None
        for old in selected:
            for new in eligible:
                if new in selected:
                    continue
                proposed = [index for index in selected if index != old]+[new]
                row = evaluator.evaluate(proposed)
                if row is None:
                    break
                if _protected_ok(row, evaluator.protected) and _improves(evaluator, row, current):
                    if best_swap is None or (hasattr(evaluator, 'effect_order') and
                            _effect_order(evaluator, row) < _effect_order(evaluator, best_swap[1])) or (
                            not hasattr(evaluator, 'effect_order') and row['target_loss'] > best_swap[1]['target_loss']):
                        best_swap = (proposed, row)
            if evaluator.stopped():
                break
        if best_swap is None:
            break
        selected, current = best_swap
    rows = [_annotate(evaluator, row)
            for row in evaluator.cache.values() if row['node_count'] <= options.max_nodes]
    feasible = [row for row in rows if row['feasible']]
    pool = feasible or rows
    def preference(row):
        excesses = [max(0., row['protected_losses'][name]-spec['max_loss']) for name, spec in evaluator.protected.items()]
        tie = (-row['mean_target_loss'],) if hasattr(evaluator, 'effect_order') else ()
        return (sum(value > 1e-12 for value in excesses), sum(excesses),
                max(0., options.min_target_loss-row['target_loss']), -row['target_loss'], *tie, row['node_count'])
    best = min(pool, key=preference) if pool else None
    candidates = [str(case['nodes'][index]['bodyId']) for index in evaluator.candidates]
    screened = [dict(_annotate(evaluator, row), bodyId=row['body_ids'][0],
                    type=case['nodes'][index].get('group_label', case['nodes'][index].get('type'))) for index, row in ranked]
    status = 'cancelled' if evaluator.cancel() or getattr(evaluator, 'cancelled', False) else ('budget_exhausted' if len(evaluator.cache) >= options.max_evaluations else 'complete')
    result = dict(screened_candidates=len(single),
                  evaluated_candidate_body_ids=[str(case['nodes'][index]['bodyId']) for index, _ in single],
                  evaluations=len(evaluator.cache), status=status,
                  termination_reason={'cancelled':'cancelled', 'budget_exhausted':'evaluation_budget',
                                      'complete':'bounded_shortlist_search_finished'}[status],
                  best=best, sensitivity=screened,
                  frontier=frontier([row for row in rows if _protected_ok(row, evaluator.protected)]),
                  evaluated=rows, shortlist_body_ids=[str(case['nodes'][index]['bodyId']) for index in eligible],
                  method='single perturbations, bounded shortlist, greedy joint runs, local swaps')
    evaluator.progress(dict(phase=status, evaluations=len(evaluator.cache), budget=evaluator.budget, candidate_count=len(candidates)))
    return result


def search(case, cfg, options=None, *, cancel=lambda:False, progress=lambda p:None):
    options = options or SearchOptions()
    options.validate()
    evaluator = Perturbations(case, cfg, options.max_evaluations, cancel, progress, options)
    result = bounded_search(evaluator, options)
    fixed_cfg = asdict(replace(cfg, intervention_ids=tuple(evaluator.candidate_metadata['original_candidate_body_ids'])))
    result = dict(case_id=case['manifest']['case_id'], model_version=MODEL_VERSION, experiment=fixed_cfg,
                options=asdict(options), **_report_protocol(evaluator), **evaluator.candidate_metadata, **result)
    from .search_explanations import search_diagnostics
    result['search_diagnostics'] = search_diagnostics(result, evaluator.constraint_context)
    return result


def save_search(root, result):
    folder = Path(root)/('search-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8])
    folder.mkdir(parents=True)
    (folder/'search.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    replay = dict(case_id=result['case_id'], model_version=result['model_version'],
                  experiment=result['experiment'], search_options=result['options'])
    # Older reports retain their original fields; only new reports carry policy metadata.
    for key in ('candidate_policy', 'original_candidate_count', 'original_candidate_body_ids',
                'candidate_count', 'candidate_body_ids', 'excluded_endpoint_count', 'excluded_endpoint_body_ids'):
        if key in result:
            replay[key] = result[key]
    (folder/'config.json').write_text(json.dumps(replay, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    plans = ([result['best']] if result['best'] else []) + [plan for plan in result['frontier'] if plan != result['best']]
    conditions = [dict(name=f'方案 {index+1}', experiment=dict(result['experiment'], intervention_ids=plan['body_ids']))
                  for index, plan in enumerate(plans[:12])]
    config = dict(case_id=result['case_id'], model_version=result['model_version'], conditions=conditions)
    if conditions:
        (folder/'conditions.json').write_text(json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return folder
