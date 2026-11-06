"""Baseline-based proposal order and factual constraint/search explanations."""
import numpy as np

from .signals import output_coefficients
from .simulation import observation_indices

PRESELECTION_HOPS = 3


def candidate_preselection(case, parsed, baselines, candidate_indices, target, method, *, cancel=lambda:False):
    """Rank eligible IDs without changing eligibility or claiming causal effects.

    Matrix rows receive from columns. Its transpose is a zero-copy sparse view;
    only one dense node vector per reverse multiplication is retained.
    """
    candidates = sorted(candidate_indices, key=lambda index: int(case['nodes'][index]['bodyId']))
    ids = lambda indices: [str(case['nodes'][index]['bodyId']) for index in indices]
    base = dict(method=method, hops=PRESELECTION_HOPS if method == 'signal_path' else 0,
        basis=('minimum then mean across whole-protocol baseline activity means times summed normalized 0..3-hop target influence '
               '(0 hops is the target readout coefficient); '
               'not restricted to the intervention interval; gain and time effects require actual perturbation runs; ID ties'
               if method == 'signal_path' else 'ascending numeric body ID'),
        definition='proposal proxy, not perturbation effect, causal attribution or complete pathway enumeration',
        ordered_body_ids=ids(candidates), zero_score_count=None, details=[], available=False)
    if method == 'body_id':
        base.update(available=True, details=[dict(bodyId=body, rank=index+1, score=None,
            min_score=None, mean_score=None, condition_scores={}) for index, body in enumerate(base['ordered_body_ids'][:50])])
        return candidates, base
    if len(baselines) != len(parsed) or cancel():
        return candidates, base
    post = observation_indices(case['nodes'], parsed[0][1], target)
    wave = output_coefficients(case['matrix'], post)
    influence = wave.copy()
    reverse = case['matrix'].transpose(copy=False)
    for _ in range(1, PRESELECTION_HOPS):
        if cancel():
            return candidates, base
        wave = reverse @ wave
        influence += wave
    influence[post] += 1./len(post)
    positions = np.asarray(candidates, dtype=np.int32)
    scores = []
    for name, cfg in parsed:
        activity = baselines[name].activity_sum[positions]/cfg.steps
        scores.append(activity*influence[positions])
    values = np.asarray(scores)
    minimum = values.min(axis=0) if len(candidates) else np.empty(0)
    means = values.mean(axis=0) if len(candidates) else np.empty(0)
    rank = sorted(range(len(candidates)), key=lambda index: (-minimum[index], -means[index],
                    int(case['nodes'][candidates[index]]['bodyId'])))
    ordered = [candidates[index] for index in rank]
    details = []
    for place, index in enumerate(rank[:50]):
        node = candidates[index]
        details.append(dict(bodyId=str(case['nodes'][node]['bodyId']), rank=place+1,
            score=float(minimum[index]), min_score=float(minimum[index]), mean_score=float(means[index]),
            condition_scores={name: dict(baseline_activity_mean=float(baselines[name].activity_sum[node]/cfg.steps),
                target_influence=float(influence[node]), score=float(values[condition][index]))
                for condition, (name, cfg) in enumerate(parsed)}))
    base.update(ordered_body_ids=ids(ordered), zero_score_count=int(np.count_nonzero(minimum == 0)),
                details=details, available=True)
    return ordered, base


def constraint_context(parsed, baseline_metrics, target, protected, options):
    def mean(metrics, cfg):
        return float(metrics.get('baseline_mean', metrics['baseline_sum']/metrics.get('sample_count', cfg.steps)))
    conditions = []
    for name, cfg in parsed:
        if name not in baseline_metrics:
            continue
        metrics = baseline_metrics[name]
        target_mean = mean(metrics[target], cfg)
        near = bool(metrics[target]['baseline_near_zero'])
        relative_defined = not near
        required_absolute = (options.min_target_loss*target_mean if relative_defined else None) if options.target_metric == 'relative' else options.min_target_loss
        required_relative = options.min_target_loss if options.target_metric == 'relative' and relative_defined else (
            required_absolute/target_mean if relative_defined else None)
        target_context = dict(observation=target, metric=options.target_metric, limit=options.min_target_loss,
            baseline_mean=target_mean, near_zero=near, required_absolute_loss=required_absolute,
            required_relative_loss=required_relative, defined=options.target_metric == 'absolute' or relative_defined,
            evaluation_window=metrics[target].get('evaluation_window',dict(start=0,stop=cfg.steps)),
            sample_count=metrics[target].get('sample_count',cfg.steps),
            exceeds_nonnegative_bound=None if required_absolute is None else required_absolute > target_mean+1e-12)
        protected_context = {}
        for label, spec in protected.items():
            value = mean(metrics[label], cfg)
            near = bool(metrics[label]['baseline_near_zero'])
            absolute = spec['max_loss'] if spec['metric'] == 'absolute' else (None if near else spec['max_loss']*value)
            relative = None if near else absolute/value
            protected_context[label] = dict(observation=label, metric=spec['metric'], limit=spec['max_loss'],
                baseline_mean=value, near_zero=near, allowed_absolute_loss=absolute, allowed_relative_loss=relative,
                evaluation_window=metrics[label].get('evaluation_window',dict(start=0,stop=cfg.steps)),
                sample_count=metrics[label].get('sample_count',cfg.steps),
                defined=spec['metric'] == 'absolute' or not near,
                allows_full_suppression=None if absolute is None else value <= absolute+1e-12)
        conditions.append(dict(name=name, target=target_context, protected=protected_context))
    return dict(conditions=conditions, absolute_unit='mean activity per update step', relative_unit='fraction of baseline mean',
                bound='nonnegative model activity; theoretical bounds do not establish attainability by any candidate set')


def explain_condition(name, metrics, context, target_constraint=None, protected_constraints=None):
    target = context['target']
    actual_absolute = -metrics[target['observation']]['mean_delta']
    relative_delta = metrics[target['observation']]['relative_sum_delta']
    actual_relative = None if relative_delta is None else -relative_delta
    selected_loss = actual_relative if target['metric'] == 'relative' else actual_absolute
    gap = None if selected_loss is None else max(0., target['limit']-selected_loss)
    explanation = dict(name=name, target=dict(target,
        actual_absolute_loss=actual_absolute, actual_relative_loss=actual_relative, gap=gap,
        satisfied=(target_constraint or {}).get('satisfied', selected_loss is not None and selected_loss+1e-12 >= target['limit'])), protected={})
    for label, threshold in context['protected'].items():
        absolute = -metrics[label]['mean_delta']
        relative = None if metrics[label]['relative_sum_delta'] is None else -metrics[label]['relative_sum_delta']
        loss = relative if threshold['metric'] == 'relative' else absolute
        explanation['protected'][label] = dict(threshold, actual_absolute_loss=absolute, actual_relative_loss=relative,
            excess=None if loss is None else max(0., loss-threshold['limit']),
            satisfied=(protected_constraints or {}).get(label, {}).get('satisfied', loss is not None and loss <= threshold['limit']+1e-12))
    return explanation


def search_diagnostics(report, context, *, fixed_evaluation=False):
    contexts = {item['name']: item for item in context['conditions']}
    if fixed_evaluation:
        assessments = report['joint_constraints']['condition_results']
        explanations = [explain_condition(row['name'], row['output_metrics'], contexts[row['name']],
            row['target_constraint'], row['protected_constraints']) for row in assessments]
        return dict(status='fixed_evaluation', termination_reason='fixed_plan_evaluated',
                    best=dict(condition_results=explanations), facts=['fixed_plan_not_optimized'],
                    conclusion_scope='the selected fixed set and evaluated conditions only', proves_global_infeasibility=False)
    singles = report.get('sensitivity', report.get('nodes', []))
    evaluated = report.get('evaluated', singles)
    eligible = report['candidate_body_ids']
    screened = report.get('evaluated_candidate_body_ids', [row['bodyId'] for row in singles])
    covered = set(screened)
    uncovered = [body for body in eligible if body not in covered]
    def protected_failed(row):
        return any(not constraint['satisfied'] for constraint in row.get('protected_constraints', {}).values())
    rejected_singles = sum(protected_failed(row) for row in singles)
    rejected_sets = sum(row['node_count'] > 1 and protected_failed(row) for row in evaluated)
    protected_eligible = sum(not protected_failed(row) for row in singles)
    shortlist = len(report.get('shortlist_body_ids', []))
    shortlist_limited = 'shortlist_body_ids' in report and protected_eligible > shortlist
    best = report.get('best')
    explanations = []
    if best:
        rows = best.get('condition_results', [dict(best, name='single')])
        explanations = [explain_condition(row['name'], row['output_metrics'], contexts[row['name']],
            row['target_constraint'], row['protected_constraints']) for row in rows]
    facts = []
    if uncovered: facts.append('uncovered_candidates')
    if shortlist_limited: facts.append('shortlist_limited')
    if rejected_singles: facts.append('protection_rejected_singles')
    if rejected_sets: facts.append('protection_rejected_sets')
    if singles and not protected_eligible: facts.append('no_protection_eligible_screened_candidates')
    if any(row['target']['gap'] is not None and row['target']['gap'] > 1e-12 for row in explanations): facts.append('target_not_reached')
    if report['status'] == 'budget_exhausted': facts.append('evaluation_budget_reached')
    if report['status'] == 'cancelled': facts.append('cancelled')
    if any(item['target']['exceeds_nonnegative_bound'] for item in context['conditions']): facts.append('target_exceeds_nonnegative_bound')
    if report.get('candidate_preselection', {}).get('zero_score_count'): facts.append('zero_proxy_scores_present')
    allowed_sets_fully_evaluated = None
    if 'shortlist_body_ids' in report:
        # Count only until exceeding the actual completed evaluations. This
        # avoids inventing a limitation when max_nodes=1 and every ID was run.
        maximum = min(report['options']['max_nodes'], len(eligible))
        combinations, allowed_count = 1, 0
        for size in range(1, maximum+1):
            combinations = combinations*(len(eligible)-size+1)//size
            allowed_count += combinations
            if allowed_count > len(evaluated):
                break
        allowed_sets_fully_evaluated = allowed_count == len(evaluated)
        if not allowed_sets_fully_evaluated: facts.append('bounded_sets_not_exhaustive')
    return dict(status=report['status'], termination_reason=report.get('termination_reason', report['status']),
        candidate_coverage=dict(eligible_count=len(eligible), screened_count=len(covered), uncovered_count=len(uncovered),
            uncovered_body_ids=uncovered, coverage_fraction=len(covered)/len(eligible) if eligible else None),
        protected_rejected_single_count=rejected_singles, protected_rejected_set_count=rejected_sets,
        protected_rejected_evaluation_count=sum(protected_failed(row) for row in evaluated),
        protection_eligible_screened_count=protected_eligible, shortlist_count=shortlist, shortlist_limited=shortlist_limited,
        best=dict(condition_results=explanations), facts=facts,
        allowed_fixed_sets_fully_evaluated=allowed_sets_fully_evaluated,
        conclusion_scope='completed single-node and set evaluations only; uncovered nodes and untested combinations remain unknown',
        proves_global_infeasibility=False,
        count_definition='distinct completed evaluations; set rejection count includes node_count > 1 only')
