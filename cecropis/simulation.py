"""One numerical core shared by the command line and local interface."""
import csv
import json
import math
import time
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import numpy as np

from . import MODEL_VERSION
from .interventions import (normalize_intervention_events, neutral_legacy, LEGACY_FIELDS,
                            CompiledInterventions, intervention_node_ids, intervention_edge_ids,
                            effective_intervention_events)

RESPONSE_EPSILON = 1e-12
MAX_INPUT_EVENTS = 128
MAX_OBSERVATIONS = 32


class SimulationCancelled(RuntimeError):
    """A requested stop leaves no completed trajectory for this scope."""



def _body_ids(values, available):
    if not isinstance(values, (tuple, list)) or not values or any(
            not isinstance(x, str) or not x.isascii() or not x.isdecimal() or
            str(int(x)) != x or not 0 < int(x) <= np.iinfo(np.int64).max for x in values):
        raise ValueError('Select nonempty canonical positive int64 string body IDs')
    if len(set(values)) != len(values) or (available is not None and not set(values) <= available):
        raise ValueError('Body IDs must be unique and inside the computation scope')
    return tuple(values)


def _protocol_entries(values, kind, nodes=None, steps=None):
    maximum = MAX_INPUT_EVENTS if kind == 'input_events' else MAX_OBSERVATIONS
    if not isinstance(values, (tuple, list)) or not (0 if kind == 'input_events' else 1) <= len(values) <= maximum:
        raise ValueError(f'{kind} count exceeds its supported range (maximum {maximum})')
    available = {str(n['bodyId']) for n in nodes} if nodes is not None else None
    result, names = [], set()
    for item in values:
        expected = {'body_ids', 'start', 'stop', 'amplitude'} if kind == 'input_events' else {'name', 'body_ids'}
        allowed = expected | ({'evaluation_window'} if kind == 'observations' else set())
        if not isinstance(item, dict) or not expected <= set(item) or set(item)-allowed:
            raise ValueError(f'{kind} entries require {sorted(expected)}')
        entry = dict(item)
        ids = entry['body_ids']
        entry['body_ids'] = _body_ids(ids, available)
        if kind == 'input_events':
            if type(entry['start']) is not int or type(entry['stop']) is not int or not 0 <= entry['start'] < entry['stop'] or (steps is not None and entry['stop'] > steps):
                raise ValueError('Input event interval must satisfy 0 <= start < stop <= steps')
            value = entry['amplitude']
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError('Input event amplitude must be finite in [0, 1]')
        else:
            name = entry['name']
            if not isinstance(name, str) or not name.strip() or len(name) > 80 or name == '__all__' or name in names:
                raise ValueError('Observation names must be unique nonempty strings of at most 80 characters')
            names.add(name)
            if 'evaluation_window' in entry:
                entry['evaluation_window'] = _evaluation_window(entry['evaluation_window'], steps)
        result.append(entry)
    return tuple(result)


def _evaluation_window(value, steps):
    if not isinstance(value, dict) or set(value) != {'start', 'stop'} or any(type(value[key]) is not int for key in value):
        raise ValueError('evaluation_window requires integer start and stop')
    if not 0 <= value['start'] < value['stop'] or (steps is not None and value['stop'] > steps):
        raise ValueError('evaluation_window must satisfy 0 <= start < stop <= steps')
    return dict(value)


@dataclass
class Experiment:
    steps: int = 100
    alpha: float = .3
    rho: float = .9
    input_group: str = 'DA1_lPN'
    input_start: int = 5
    input_stop: int = 25
    amplitude: float = 1.
    intervention_group: str = 'KCg-m'
    intervention_start: int = 10
    intervention_stop: int = 35
    gain: float = .2
    outputs: tuple = ('MBON01', 'MBON02')
    intervention_ids: tuple | None = None
    input_events: tuple | None = None
    observations: tuple | None = None
    intervention_events: tuple | None = None
    intervention_semantics_version: int | None = None

    @classmethod
    def from_dict(cls, data):
        allowed = {field.name for field in fields(cls)}
        if not isinstance(data, dict) or set(data) - allowed:
            raise ValueError('Unrecognized experiment fields')
        data = dict(data)
        if data.get('intervention_events') is not None:
            if type(data.get('intervention_semantics_version')) is not int or data['intervention_semantics_version'] != 1:
                raise ValueError('intervention_events requires intervention_semantics_version=1')
            steps = data.get('steps', cls.steps)
            neutral = neutral_legacy(steps)
            for key in LEGACY_FIELDS:
                if key in data and data[key] != neutral[key] and not (key == 'intervention_ids' and data[key] == []):
                    raise ValueError('New intervention plan conflicts with explicit legacy intervention fields')
            data['intervention_events'] = normalize_intervention_events(data['intervention_events'], steps)
            data.update(neutral)
        elif data.get('intervention_semantics_version') is not None:
            raise ValueError('intervention_semantics_version requires an explicit intervention_events plan')
        if 'outputs' in data:
            if not isinstance(data['outputs'], (list, tuple)):
                raise ValueError('outputs must be a list of observation names')
            data['outputs'] = tuple(data['outputs'])
        if data.get('intervention_ids') is not None:
            if not isinstance(data['intervention_ids'], (list, tuple)):
                raise ValueError('intervention_ids must be a list of body IDs')
            data['intervention_ids'] = tuple(data['intervention_ids'])
        for key in ('input_events', 'observations'):
            if data.get(key) is not None:
                data[key] = _protocol_entries(data[key], key, steps=data.get('steps', cls.steps))
        if data.get('observations') is not None:
            data['outputs'] = tuple(item['name'] for item in data['observations'])
        return cls(**data)

    def validate(self, nodes):
        for name in ['steps'] + (['intervention_start', 'intervention_stop'] if self.intervention_events is None else []) + (['input_start', 'input_stop'] if self.input_events is None else []):
            value = getattr(self, name)
            if type(value) is not int:
                raise ValueError(f'{name} must be an integer')
        if not 1 <= self.steps <= 2000:
            raise ValueError('steps must be 1..2000')
        for prefix in (['input'] if self.input_events is None else []) + (['intervention'] if self.intervention_events is None else []):
            if not 0 <= getattr(self, prefix + '_start') < getattr(self, prefix + '_stop') <= self.steps:
                raise ValueError(f'{prefix} interval must satisfy 0 <= start < stop <= steps')
        for name, low, high in [('alpha', .001, 1), ('rho', 0, 1)] + ([('gain', 0, 1)] if self.intervention_events is None else []) + ([('amplitude', 0, 1)] if self.input_events is None else []):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'{name} must be finite in [{low}, {high}]')
        available = {role: {label for n in nodes for label in node_groups(n, role)}
                     for role in ['input', 'internal', 'output']}
        if self.input_events is not None:
            self.input_events = _protocol_entries(self.input_events, 'input_events', nodes, self.steps)
        elif not len(group_indices(nodes, 'input', self.input_group)):
            raise ValueError('Unknown input group')
        if self.intervention_events is not None:
            if type(self.intervention_semantics_version) is not int or self.intervention_semantics_version != 1:
                raise ValueError('intervention_events requires intervention_semantics_version=1')
            self.intervention_events = normalize_intervention_events(self.intervention_events, self.steps, nodes)
            neutral = neutral_legacy(self.steps)
            # Dataclass construction is supported, but explicit conflicting legacy
            # fields are never silently discarded. Use from_dict for new plans.
            if any(getattr(self, key) != value for key, value in neutral.items()):
                raise ValueError('New intervention plan conflicts with legacy fields; use Experiment.from_dict')
        elif self.intervention_semantics_version is not None:
            raise ValueError('intervention_semantics_version requires intervention_events')
        if self.intervention_events is None and not len(group_indices(nodes, 'internal', self.intervention_group)):
            raise ValueError('Intervention must select internal nodes')
        if self.intervention_events is None and self.intervention_ids is not None:
            ids = self.intervention_ids
            if not isinstance(ids, (list, tuple)) or not ids or any(
                    not isinstance(x, str) or not x.isascii() or not x.isdecimal() or str(int(x)) != x for x in ids):
                raise ValueError('Select a nonempty list of canonical string body IDs')
            allowed_ids = {str(nodes[i]['bodyId']) for i in group_indices(nodes, 'internal', self.intervention_group)}
            if len(ids) != len(set(ids)) or not set(ids) <= allowed_ids:
                raise ValueError('Selected IDs must be unique internal nodes in the selected group')
        if self.observations is not None:
            self.observations = _protocol_entries(self.observations, 'observations', nodes, self.steps)
            self.outputs = tuple(item['name'] for item in self.observations)
        elif not isinstance(self.outputs, (list, tuple)) or not 1 <= len(self.outputs) <= MAX_OBSERVATIONS or any(
                not isinstance(x, str) or x not in available['output'] for x in self.outputs) or len(set(self.outputs)) != len(self.outputs):
            raise ValueError('Choose 1..32 distinct output groups')


def node_groups(node, role):
    """Membership roles are operation sets; context is still computed."""
    if 'memberships' in node:
        return node['memberships'].get(role, ())
    return (node.get('group_label', node.get('type')),) if node.get('role') == role else ()


def group_indices(nodes, role, label):
    return np.array([i for i, node in enumerate(nodes) if node_groups(node, role) and
                     (label == '__all__' or label in node_groups(node, role))], dtype=np.int32)


def effective_input_events(nodes, cfg):
    if cfg.input_events is not None:
        return [dict(event, body_ids=list(event['body_ids'])) for event in cfg.input_events]
    return [dict(body_ids=[str(nodes[i]['bodyId']) for i in group_indices(nodes, 'input', cfg.input_group)],
                 start=cfg.input_start, stop=cfg.input_stop, amplitude=cfg.amplitude)]


def effective_observations(nodes, cfg):
    if cfg.observations is not None:
        return [dict(item, body_ids=list(item['body_ids']), evaluation_window=_evaluation_window(
            item.get('evaluation_window', dict(start=0, stop=cfg.steps)), cfg.steps)) for item in cfg.observations]
    return [dict(name=label, body_ids=[str(nodes[i]['bodyId']) for i in group_indices(nodes, 'output', label)],
                 evaluation_window=dict(start=0, stop=cfg.steps))
            for label in cfg.outputs]


def input_indices(nodes, cfg):
    wanted = {body for event in effective_input_events(nodes, cfg) for body in event['body_ids']}
    return np.array([i for i, node in enumerate(nodes) if str(node['bodyId']) in wanted], dtype=np.int32)


def observation_indices(nodes, cfg, label):
    observations = effective_observations(nodes, cfg)
    matches = [item for item in observations if item['name'] == label]
    if not matches:
        raise ValueError('Unknown observation set')
    wanted = set(matches[0]['body_ids'])
    return np.array([i for i, node in enumerate(nodes) if str(node['bodyId']) in wanted], dtype=np.int32)


def observation_window(nodes, cfg, label):
    if cfg.observations is not None:
        for item in cfg.observations:
            if item['name'] == label:
                return _evaluation_window(item.get('evaluation_window', dict(start=0,stop=cfg.steps)), cfg.steps)
    elif label in cfg.outputs:
        return dict(start=0,stop=cfg.steps)
    raise ValueError('Unknown observation set')


def _window_sum(values, window):
    total = 0.
    for value in values[window['start']+1:window['stop']+1]:
        total += float(value)
    return total


def observation_metrics(nodes, cfg, label, baseline, intervention):
    """Read x(start+1)..x(stop), independently of full-trajectory recording."""
    window = observation_window(nodes, cfg, label)
    count = window['stop']-window['start']
    def total(stats):
        if isinstance(stats, TrajectoryStats):
            observations = stats.config.get('observations')
            original_window = dict(start=0,stop=stats.config['steps'])
            if observations is not None:
                matching = next((item for item in observations if item['name'] == label), None)
                original_window = matching.get('evaluation_window', original_window) if matching else None
            if original_window == window and stats.observation_sums is not None:
                return stats.observation_sums[label]
            if label not in stats.series:
                raise ValueError('Metrics-only trajectory does not contain this evaluation window')
            values = stats.series[label]
        else:
            values = np.asarray(stats)
        if values.ndim != 1 or len(values) != cfg.steps+1:
            raise ValueError('Observation trajectory must contain state rows 0..steps')
        return _window_sum(values, window)
    return dict(response_metrics(total(baseline), total(intervention), count),
                evaluation_window=window, sample_count=count)


def protocol_key(nodes, cfg):
    """Semantic baseline identity; intervention and recording remain independent."""
    return dict(steps=cfg.steps, alpha=cfg.alpha, rho=cfg.rho,
                input_events=sorted([dict(event, body_ids=sorted(event['body_ids']))
                                     for event in effective_input_events(nodes, cfg)],
                                    key=lambda event: (event['start'], event['stop'], event['amplitude'], event['body_ids'])),
                observations=sorted([dict(item, body_ids=sorted(item['body_ids']))
                                     for item in effective_observations(nodes, cfg)], key=lambda item: item['name']))


def response_metrics(bsum, isum, steps):
    """Mean is over updated states 1..steps (the initial state is zero)."""
    near_zero = abs(bsum / steps) <= RESPONSE_EPSILON
    return dict(baseline_sum=bsum, intervention_sum=isum, sum_delta=isum - bsum,
                baseline_mean=bsum / steps, intervention_mean=isum / steps,
                mean_delta=(isum - bsum) / steps, baseline_near_zero=near_zero,
                relative_sum_delta=None if near_zero else (isum - bsum) / bsum)


def intervention_indices(nodes, cfg):
    if cfg.intervention_events is not None:
        ids = set(intervention_node_ids(nodes, cfg))
        return np.asarray([i for i, node in enumerate(nodes) if str(node['bodyId']) in ids], dtype=np.int32)
    candidates = group_indices(nodes, 'internal', cfg.intervention_group)
    if cfg.intervention_ids is None:
        return candidates
    ids = set(cfg.intervention_ids)
    return np.array([idx for idx in candidates if str(nodes[idx]['bodyId']) in ids], dtype=np.int32)


def propagate(matrix, cfg, input_indices, intervention_indices, gain, *, nodes=None, apply_interventions=None):
    """Legacy full-history wrapper around the same numerical update."""
    # Row t is state x(t). Input/gain at step t produces row t+1.
    states = np.zeros((cfg.steps + 1, matrix.shape[0]), dtype=np.float64)
    drive = np.zeros(matrix.shape[0])
    if cfg.input_events is not None and nodes is None:
        raise ValueError('Explicit input events require nodes= for body ID mapping')
    events = _compiled_events(nodes, cfg) if nodes is not None else None
    active = (cfg.intervention_events is not None and gain != 1.) if apply_interventions is None else apply_interventions
    if cfg.intervention_events is not None and nodes is None:
        raise ValueError('Intervention event plans require nodes= for body ID mapping')
    compiled = CompiledInterventions(dict(nodes=nodes, matrix=matrix, counts=matrix), cfg) if active else None
    for t in range(cfg.steps):
        states[t + 1] = _next_state(matrix, cfg, states[t], drive, t, input_indices, intervention_indices, gain, events, compiled)
    return states


def _compiled_events(nodes, cfg):
    if cfg.input_events is None:
        return None
    by_id = {str(n['bodyId']): i for i, n in enumerate(nodes)}
    events = sorted(cfg.input_events, key=lambda event: (event['start'], event['stop'], event['amplitude'], sorted(event['body_ids'])))
    return [(event['start'], event['stop'], event['amplitude'], np.asarray(
        [by_id[body] for body in event['body_ids']], dtype=np.int32)) for event in events]


def _next_state(matrix, cfg, current, drive, step, inputs, targets, gain, events=None, interventions=None):
    drive.fill(0)
    if events is not None:
        # Events are additive per node. Saturation is still the existing tanh.
        for start, stop, amplitude, indices in events:
            if start <= step < stop:
                drive[indices] += amplitude
    elif cfg.input_start <= step < cfg.input_stop:
        drive[inputs] = cfg.amplitude
    recursive = matrix @ current
    if interventions is not None and len(interventions.edge_pairs):
        np.add.at(recursive, interventions.edge_post, interventions.weighted_adjustment(current, step))
    following = np.tanh((1 - cfg.alpha) * current + cfg.alpha * (cfg.rho * recursive + drive))
    if interventions is not None:
        node_gains, _ = interventions.effective_gains(step)
        following[interventions.node_indices] *= node_gains
    elif cfg.intervention_events is None and cfg.intervention_start <= step < cfg.intervention_stop:
        following[targets] *= gain
    return following


DEFAULT_RECORD_BYTES = 256 * 1024 ** 2
MAX_RECORD_BYTES = 1024 ** 3


@dataclass(frozen=True)
class RecordPolicy:
    mode: str = 'selected'
    body_ids: tuple | None = None
    step_stride: int = 1
    steps: tuple | None = None
    max_bytes: int = DEFAULT_RECORD_BYTES

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) - {field.name for field in fields(cls)}:
            raise ValueError('Unrecognized recording fields')
        values = dict(data)
        for name in ('body_ids', 'steps'):
            if values.get(name) is not None:
                if not isinstance(values[name], (list, tuple)):
                    raise ValueError(f'{name} must be a list')
                values[name] = tuple(values[name])
        return cls(**values)

    def resolve(self, case, cfg, branch_count=1):
        if self.mode not in ('selected', 'all', 'none'):
            raise ValueError('Recording mode must be selected, all or none')
        if type(self.step_stride) is not int or not 1 <= self.step_stride <= 2000:
            raise ValueError('Recording step_stride must be 1..2000')
        if type(self.max_bytes) is not int or not 1 <= self.max_bytes <= MAX_RECORD_BYTES:
            raise ValueError(f'Recording max_bytes must be 1..{MAX_RECORD_BYTES}')
        if self.body_ids is not None:
            if not isinstance(self.body_ids, (tuple, list)) or not self.body_ids or any(
                    not isinstance(x, str) or not x.isascii() or not x.isdecimal() or
                    str(int(x)) != x for x in self.body_ids) or len(set(self.body_ids)) != len(self.body_ids):
                raise ValueError('Recording body_ids must contain unique canonical string IDs')
        if self.steps is not None:
            if not isinstance(self.steps, (tuple, list)) or not self.steps or any(
                    type(t) is not int or not 0 <= t <= cfg.steps for t in self.steps) or len(set(self.steps)) != len(self.steps):
                raise ValueError('Recording steps must be unique integers in 0..steps')
        if self.mode in ('none', 'all') and self.body_ids is not None:
            raise ValueError('body_ids are only valid for selected recording')
        if self.mode == 'none':
            indices, times = [], []
        else:
            times = sorted(self.steps) if self.steps is not None else sorted(set(
                list(range(0, cfg.steps + 1, self.step_stride)) + [cfg.steps]))
            if self.mode == 'all':
                indices = list(range(len(case['nodes'])))
            elif self.body_ids is not None:
                by_id = {str(n['bodyId']): i for i, n in enumerate(case['nodes'])}
                if any(body not in by_id for body in self.body_ids):
                    raise ValueError('Recording includes a body ID outside the computation scope')
                indices = [by_id[body] for body in self.body_ids]
            else:
                edge_endpoints = {body for pair in intervention_edge_ids(cfg) for body in pair}
                edge_indices = np.asarray([i for i, node in enumerate(case['nodes']) if str(node['bodyId']) in edge_endpoints], dtype=np.int32)
                indices = np.unique(np.concatenate([
                    input_indices(case['nodes'], cfg),
                    intervention_indices(case['nodes'], cfg), edge_indices] +
                    [observation_indices(case['nodes'], cfg, label) for label in cfg.outputs])).tolist()
        size = len(indices) * len(times) * np.dtype(np.float64).itemsize * branch_count
        if size > self.max_bytes:
            raise ValueError(f'Recording needs {size} bytes; limit is {self.max_bytes}; select fewer nodes or time steps')
        metadata = dict(mode=self.mode, body_ids=[str(case['nodes'][i]['bodyId']) for i in indices],
                        time_steps=times, node_count=len(indices), time_count=len(times),
                        branch_count=branch_count, bytes=size, dtype='float64', max_bytes=self.max_bytes)
        return np.asarray(indices, dtype=np.int32), times, metadata


@dataclass
class TrajectoryStats:
    series: dict
    node_sum: np.ndarray
    node_peak: np.ndarray
    activity_sum: np.ndarray
    final: np.ndarray
    signal_traces: dict
    recorded_states: np.ndarray | None
    recording_metadata: dict
    config: dict
    observation_sums: dict | None = None
    observation_peaks: dict | None = None
    node_window_sum: np.ndarray | None = None
    node_window: dict | None = None
    edge_adjustment_sums: dict | None = None


class SimulationPlan:
    """Reusable readouts for one protocol; no counts in the propagation hot loop."""
    def __init__(self, case, cfg, *, collect_signals=True):
        cfg.validate(case['nodes'])
        self.case, self.cfg = case, cfg
        self.inputs = input_indices(case['nodes'], cfg)
        self.events = _compiled_events(case['nodes'], cfg)
        self.protocol = protocol_key(case['nodes'], cfg)
        self.outputs = {label: observation_indices(case['nodes'], cfg, label) for label in cfg.outputs}
        self.windows = {label: observation_window(case['nodes'], cfg, label) for label in cfg.outputs}
        self.signal_coefficients = {}
        if collect_signals:
            from .signals import output_coefficients
            for label, indices in self.outputs.items():
                coeff = output_coefficients(case['matrix'], indices)
                relevant = np.flatnonzero(coeff)
                self.signal_coefficients[label] = (relevant, coeff[relevant])


def simulate(case, cfg, *, gain=1., target_indices=None, recording=None, plan=None, cancel=lambda:False, collect_curves=True, node_window=None, apply_interventions=None):
    """Advance every computation node, retaining only requested history."""
    if node_window is not None:
        node_window = _evaluation_window(node_window, cfg.steps)
    plan = plan or SimulationPlan(case, cfg, collect_signals='counts' in case)
    if type(collect_curves) is not bool:
        raise ValueError('collect_curves must be boolean')
    if isinstance(gain, bool) or not isinstance(gain, (float, int)) or not math.isfinite(gain) or not 0 <= gain <= 1:
        raise ValueError('gain must be finite in [0, 1]')
    if plan.case is not case or plan.protocol != protocol_key(case['nodes'], cfg):
        raise ValueError('Simulation plan does not match case/input protocol')
    policy = recording or RecordPolicy(mode='none')
    indices, times, metadata = policy.resolve(case, cfg)
    target = intervention_indices(case['nodes'], cfg) if target_indices is None else np.asarray(target_indices, dtype=np.int32)
    if apply_interventions is not None and type(apply_interventions) is not bool:
        raise ValueError('apply_interventions must be boolean')
    enabled = False if apply_interventions is None else apply_interventions
    interventions = CompiledInterventions(case, cfg) if enabled else None
    if apply_interventions is False:
        gain = 1.
    edge_adjustment_sums = np.zeros(len(interventions.edge_pairs)) if interventions is not None else np.empty(0)
    edge_readout = {}
    if interventions is not None and len(interventions.edge_pairs) and collect_curves:
        for label, post in plan.outputs.items():
            mask = np.isin(interventions.edge_post, post)
            edge_readout[label] = (mask, 1. / len(post))
    n = case['matrix'].shape[0]
    current = np.zeros(n, dtype=np.float64)
    drive = np.zeros(n, dtype=np.float64)
    sums, peaks, presums = np.zeros(n), np.zeros(n), np.zeros(n)
    window_sum = np.zeros(n) if node_window is not None else None
    series = {label: np.zeros(cfg.steps + 1) for label in cfg.outputs} if collect_curves else {}
    traces = {label: np.zeros(cfg.steps) for label in plan.signal_coefficients} if collect_curves else {}
    observation_sums = {label: 0. for label in cfg.outputs}
    observation_peaks = {label: 0. for label in cfg.outputs}
    recorded = np.zeros((len(times), len(indices)), dtype=np.float64) if policy.mode != 'none' else None
    recorded_at = {t: i for i, t in enumerate(times)}
    for t in range(cfg.steps):
        if cancel():
            raise SimulationCancelled('Simulation cancelled during propagation')
        presums += current
        adjustment = interventions.weighted_adjustment(current, t) if interventions is not None else np.empty(0)
        edge_adjustment_sums += adjustment
        for label, (pre, coeff) in (plan.signal_coefficients.items() if collect_curves else ()):
            traces[label][t] = cfg.alpha * cfg.rho * np.dot(current[pre], coeff)
            if label in edge_readout:
                mask, divisor = edge_readout[label]
                traces[label][t] += cfg.alpha * cfg.rho * float(adjustment[mask].sum()) * divisor
        current = _next_state(case['matrix'], cfg, current, drive, t, plan.inputs, target, gain, plan.events, interventions)
        sums += current
        if node_window is not None and node_window['start'] <= t < node_window['stop']:
            window_sum += current
        np.maximum(peaks, current, out=peaks)
        for label, post in plan.outputs.items():
            value = float(current[post].mean())
            if collect_curves:
                series[label][t + 1] = value
            window = plan.windows[label]
            if window['start'] <= t < window['stop']:
                observation_sums[label] += value
                observation_peaks[label] = max(observation_peaks[label], value)
        if t + 1 in recorded_at:
            recorded[recorded_at[t + 1]] = current[indices]
    return TrajectoryStats(series, sums, peaks, presums, current, traces, recorded, metadata, asdict(cfg),
                           observation_sums, observation_peaks, window_sum, node_window,
                           {pair: float(value) for pair, value in zip(interventions.edge_pairs, edge_adjustment_sums)} if interventions is not None else {})


def _stats_from_history(case, cfg, states):
    """Compatibility for existing callers supplying a baseline ndarray."""
    if states.shape != (cfg.steps + 1, len(case['nodes'])):
        raise ValueError('Baseline trajectory shape does not match computation scope')
    plan = SimulationPlan(case, cfg, collect_signals='counts' in case)
    traces = {label: cfg.alpha * cfg.rho * (states[:-1, pre] @ coeff)
              for label, (pre, coeff) in plan.signal_coefficients.items()}
    series = {label: states[:, post].mean(axis=1) for label, post in plan.outputs.items()}
    return TrajectoryStats(series,
                           states.sum(axis=0), states.max(axis=0), states[:-1].sum(axis=0),
                           states[-1], traces, states, {}, asdict(cfg),
                           {label: _window_sum(values, plan.windows[label]) for label, values in series.items()},
                           {label: float(values[plan.windows[label]['start']+1:plan.windows[label]['stop']+1].max())
                            for label, values in series.items()})


def compare(case, cfg, keep_states=False, recording=None, _baseline=None, *, cancel=lambda:False, simulation_progress=lambda value:None):
    if cancel():
        raise SimulationCancelled('Simulation cancelled before propagation')
    cfg.validate(case['nodes'])
    if cfg.intervention_events is not None:
        CompiledInterventions(case, cfg)
    start = time.perf_counter()
    policy = recording or RecordPolicy(mode='all' if keep_states else 'none')
    _, _, record_metadata = policy.resolve(case, cfg, branch_count=2)
    inp = input_indices(case['nodes'], cfg)
    target = intervention_indices(case['nodes'], cfg)
    plan = SimulationPlan(case, cfg, collect_signals='counts' in case)
    def run_branch(kind, **kwargs):
        simulation_progress(dict(kind=kind, status='started'))
        stats = simulate(case, cfg, recording=policy, plan=plan, cancel=cancel, **kwargs)
        simulation_progress(dict(kind=kind, status='completed'))
        return stats
    if isinstance(_baseline, np.ndarray):
        baseline = _stats_from_history(case, cfg, _baseline)
    elif _baseline is None:
        baseline = run_branch('baseline')
    elif isinstance(_baseline, TrajectoryStats):
        baseline = _baseline
        if protocol_key(case['nodes'], Experiment.from_dict(baseline.config)) != plan.protocol:
            raise ValueError('Baseline does not match input protocol')
    else:
        raise ValueError('Baseline must be trajectory statistics or a legacy ndarray')
    if not baseline.series or (policy.mode != 'none' and (baseline.recording_metadata.get('body_ids') != record_metadata['body_ids'] or
                                 baseline.recording_metadata.get('time_steps') != record_metadata['time_steps'])):
        baseline = run_branch('baseline')
    intervention = run_branch('intervention', gain=cfg.gain, target_indices=target,
                              apply_interventions=True if cfg.intervention_events is not None else None)
    series, summary = {}, []
    for label in cfg.outputs:
        ix = plan.outputs[label]
        b, i = baseline.series[label], intervention.series[label]
        series[label] = {'baseline': b.tolist(), 'intervention': i.tolist(), 'delta': (i - b).tolist()}
        summary.append({'type': label, 'node_count': len(ix), 'baseline_peak': float(b.max()),
                        'intervention_peak': float(i.max()),
                        'evaluation_baseline_peak': (baseline.observation_peaks[label] if baseline.observation_peaks is not None
                            else float(b[plan.windows[label]['start']+1:plan.windows[label]['stop']+1].max())),
                        'evaluation_intervention_peak': intervention.observation_peaks[label],
                        **observation_metrics(case['nodes'], cfg, label, baseline, intervention)})
    edge_pairs = intervention_edge_ids(cfg)
    endpoint_ids = {body for pair in edge_pairs for body in pair}
    endpoint_indices = np.asarray([i for i, node in enumerate(case['nodes']) if str(node['bodyId']) in endpoint_ids], dtype=np.int32)
    selected = np.unique(np.concatenate([inp, target, endpoint_indices] + list(plan.outputs.values())))
    node_deltas = [{'bodyId': str(case['nodes'][idx]['bodyId']), 'type': case['nodes'][idx].get('type'),
                    'role': case['nodes'][idx].get('role', 'context'), 'baseline_peak': float(baseline.node_peak[idx]),
                    'intervention_peak': float(intervention.node_peak[idx]),
                    'sum_delta': float(intervention.node_sum[idx] - baseline.node_sum[idx])}
                   for idx in selected]
    result = {'config': {'case_id': case['manifest']['case_id'], 'model_version': MODEL_VERSION,
                         'experiment': asdict(cfg), 'recording': asdict(policy)},
              'kind': 'comparison', 'steps': list(range(cfg.steps + 1)), 'series': series, 'summary': summary,
              'node_deltas': sorted(node_deltas, key=lambda n: abs(n['sum_delta']), reverse=True),
              'timing': 'state row t+1 follows update t; active intervals are [start, stop)',
              'input_node_count': len(inp), 'intervention_node_count': len(target),
              'computation_node_count': len(case['nodes']), 'recording_metadata': record_metadata}
    result['intervention_events'] = effective_intervention_events(case['nodes'], cfg)
    result['intervention_semantics_version'] = 1 if cfg.intervention_events is not None else None
    result['intervention_edge_count'] = len(edge_pairs)
    result['intervention_edge_pairs'] = [list(pair) for pair in edge_pairs]
    result['intervention_edge_endpoint_body_ids'] = sorted({body for pair in edge_pairs for body in pair}, key=int)
    result['intervention_edge_endpoint_node_count'] = len(result['intervention_edge_endpoint_body_ids'])
    result['intervention_body_ids'] = [str(case['nodes'][idx]['bodyId']) for idx in target]
    if 'counts' in case:
        from .signals import incoming_signals
        result['signals'] = {label: incoming_signals(case, cfg, label, baseline, intervention, target)
                             for label in cfg.outputs}
    result['elapsed_seconds'] = round(time.perf_counter() - start, 4)
    if policy.mode != 'none':
        result['states'] = (baseline.recorded_states, intervention.recorded_states)
    return result


def forward(case, cfg, recording=None):
    """One baseline forward pass over the whole explicit computation scope."""
    start = time.perf_counter()
    policy = recording or RecordPolicy(mode='none')
    stats = simulate(case, cfg, recording=policy)
    summary = []
    for label, values in stats.series.items():
        metrics = observation_metrics(case['nodes'], cfg, label, stats, stats)
        summary.append(dict(type=label, node_count=len(observation_indices(case['nodes'], cfg, label)),
                            **metrics, baseline_peak=float(values.max()),
                            evaluation_baseline_peak=stats.observation_peaks[label], final_response=float(values[-1])))
    result = dict(kind='forward', config=dict(case_id=case['manifest']['case_id'], model_version=MODEL_VERSION,
                  experiment=asdict(cfg), recording=asdict(policy)), steps=list(range(cfg.steps + 1)),
                  series={label: {'baseline': values.tolist()} for label, values in stats.series.items()},
                  summary=summary, input_node_count=len(input_indices(case['nodes'], cfg)),
                  computation_node_count=len(case['nodes']), intervention_node_count=0, intervention_body_ids=[],
                  recording_metadata=stats.recording_metadata,
                  node_statistics=dict(body_ids=[str(n['bodyId']) for n in case['nodes']],
                      sum=stats.node_sum.tolist(), peak=stats.node_peak.tolist(), final=stats.final.tolist()),
                  final_summary=dict(active_node_count=int(np.count_nonzero(stats.final)),
                      activity_sum=float(stats.final.sum()), peak=float(stats.final.max(initial=0.))),
                  timing='state row t+1 follows update t; active intervals are [start, stop)',
                  elapsed_seconds=round(time.perf_counter() - start, 4))
    if stats.recorded_states is not None:
        result['states'] = (stats.recorded_states,)
    return result


def save_run(root, result):
    folder = Path(root) / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8])
    folder.mkdir(parents=True)
    clean = {key: value for key, value in result.items() if key != 'states'}
    for name, content in [('config.json', clean['config']), ('result.json', clean)]:
        (folder / name).write_text(json.dumps(content, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    with (folder / 'responses.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['step', 'type', 'baseline', 'intervention', 'delta'])
        for label, values in clean['series'].items():
            for t in clean['steps']:
                writer.writerow([t, label, values['baseline'][t],
                                 values['intervention'][t] if 'intervention' in values else '',
                                 values['delta'][t] if 'delta' in values else ''])
    if 'states' in result:
        arrays = {'baseline': result['states'][0]}
        if len(result['states']) == 2:
            arrays['intervention'] = result['states'][1]
        np.savez_compressed(folder / 'states.npz', **arrays)
    return folder


def load_experiment(path, case_id):
    content = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if content.get('case_id') != case_id or content.get('model_version') != MODEL_VERSION:
        raise ValueError('Configuration case/model version does not match this case')
    return Experiment.from_dict(content['experiment'])
