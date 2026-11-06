"""Read-only, self-contained exports of saved fixed-condition comparisons.

Only observation curves and saved metrics are exported.  This module never opens
state archives, loads a connectome, or fills missing records by simulation.
"""
import csv
import html
import io
import json
import math
import os
import re
import shutil
from pathlib import Path
from uuid import uuid4

REPORT_VERSION = 1
DEFAULT_MAX_BYTES = 16 * 1024 ** 2
METRIC_KEYS = ('node_count', 'baseline_sum', 'intervention_sum', 'sum_delta',
               'baseline_mean', 'intervention_mean', 'mean_delta',
               'relative_sum_delta', 'baseline_near_zero', 'sample_count',
               'baseline_peak', 'intervention_peak', 'evaluation_baseline_peak',
               'evaluation_intervention_peak')


def _text(value):
    """Discard local path spellings even when embedded in user descriptions."""
    value = str(value) if value is not None else ''
    return re.sub(r'(?:[A-Za-z]:[\\/]|\\\\|(?<![\w])/(?:[^/\s<>"\']+/)+)[^\s<>"\']*',
                  '[本地路径]', value)


def _number(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Saved report contains a non-finite or non-numeric observation value')
    return value


def _plain(value):
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        # Observation names may contain 'path'; redact path values, not arbitrary keys.
        return {_text(key): _plain(item) for key, item in value.items()}
    if value is None or isinstance(value, (bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError('Saved report contains a non-finite value')
        return value
    raise ValueError('Saved report must contain JSON values, not live histories or task objects')


def _load(source):
    if isinstance(source, dict):
        return source
    path = Path(source)
    if path.is_dir():
        path = path / 'comparison.json'
    limit = 64 * 1024 ** 2
    with path.open('rb') as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise ValueError('Saved comparison exceeds the 64 MiB JSON read limit')
    return json.loads(payload.decode('utf-8-sig'))


def _constraint_rows(source, name):
    for item in source.get('constraints', []):
        if item.get('name') == name:
            assessment = item.get('constraints') or {}
            return [_plain(row) for row in assessment.get('condition_results', []) if row.get('name') == name]
    # Existing fixed joint/timing/reduction evaluations store the same rows here.
    for key in ('joint_constraints', 'reduction_plan_assessment', 'timing_constraints'):
        block = source.get(key) or {}
        rows = block.get('condition_results', []) if isinstance(block, dict) else []
        matches = [_plain(row) for row in rows if row.get('name') == name]
        if matches:
            return matches
    return []


def extract_report(source, condition_names=None):
    """Extract saved definitions and values without evaluating any conditions."""
    source = _load(source)
    if not isinstance(source, dict) or not isinstance(source.get('results'), list) or not isinstance(source.get('rows'), list):
        raise ValueError('Choose a saved fixed-condition comparison with rows and results')
    if len(source['rows']) != len(source['results']):
        raise ValueError('Saved comparison rows and results do not have a consistent condition mapping')
    task = source.get('task_definition') or {}
    definitions = task.get('conditions') or source.get('requested_conditions') or source.get('conditions') or []
    definitions_by_name = {item['name']: item for item in definitions}
    statuses = {item['name']: item for item in source.get('condition_statuses', source.get('condition_states', []))}
    result_by_name = {row['name']: (row, result) for row, result in zip(source['rows'], source['results'])}
    names = list(dict.fromkeys([item['name'] for item in definitions] + list(statuses) + list(result_by_name)))
    if condition_names is not None:
        if not isinstance(condition_names, (list, tuple)) or not condition_names or len(set(condition_names)) != len(condition_names):
            raise ValueError('Select a non-empty list of distinct condition names')
        missing = [name for name in condition_names if name not in names]
        if missing:
            raise ValueError('Unknown saved conditions: ' + ', '.join(map(str, missing)))
        names = list(condition_names)
    if not names:
        raise ValueError('Saved comparison contains no conditions')
    conditions = []
    for name in names:
        definition = definitions_by_name.get(name, {})
        row, result = result_by_name.get(name, ({}, {}))
        status_row = statuses.get(name, {})
        status = status_row.get('status', 'completed' if result else 'not_run')
        if status=='complete':status='completed'
        cfg = definition.get('experiment') or result.get('config', {}).get('experiment') or {}
        observations = cfg.get('observations') or source.get('protocol', {}).get('observations') or []
        summaries = {item['type']: item for item in result.get('summary', row.get('outputs', []))}
        observation_names = list(dict.fromkeys([item['name'] for item in observations] + list(summaries) + list(result.get('series', {}))))
        metrics, curves = [], {}
        steps = result.get('steps', [])
        for label in observation_names:
            summary = summaries.get(label, {})
            observation = next((item for item in observations if item['name'] == label), {})
            window = summary.get('evaluation_window') or observation.get('evaluation_window')
            if window is None and cfg.get('steps') is not None:
                window = {'start': 0, 'stop': cfg['steps']}
            metrics.append(dict(observation=_text(label), body_ids=_plain(observation.get('body_ids')),
                                evaluation_window=_plain(window),
                                **{key: _plain(summary.get(key)) for key in METRIC_KEYS}))
            saved_curve = result.get('series', {}).get(label, {})
            if status == 'completed' and saved_curve:
                baseline = saved_curve.get('baseline')
                intervention = saved_curve.get('intervention')
                if baseline is not None and intervention is not None:
                    if len(baseline) != len(steps) or len(intervention) != len(steps):
                        raise ValueError('Saved curve length differs from its state-step list: ' + str(name))
                    if any(value is None for value in steps + baseline + intervention):
                        raise ValueError('Saved observation curves contain missing state samples')
                    curves[_text(label)] = dict(state_steps=[_number(t) for t in steps],
                                               baseline=[_number(v) for v in baseline],
                                               intervention=[_number(v) for v in intervention],
                                               delta=[_number(v) for v in saved_curve.get('delta', [])])
                    if curves[_text(label)]['delta'] and len(curves[_text(label)]['delta']) != len(steps):
                        raise ValueError('Saved delta curve length differs from its state-step list')
        events = cfg.get('input_events')
        if events is None:
            events = row.get('input_events')
        members = cfg.get('intervention_ids')
        if members is None:
            members = row.get('body_ids', result.get('intervention_body_ids'))
        conditions.append(dict(name=_text(name), role=_text(definition.get('role', status_row.get('role', row.get('role', '')))),
            status=_text(status), error=_text(status_row.get('error', '')), experiment=_plain(cfg),
            input_events=_plain(events), observations=_plain(observations),
            intervention_events=_plain(cfg.get('intervention_events')),
            intervention_semantics_version=_plain(cfg.get('intervention_semantics_version')),
            intervention=dict(body_ids=_plain(members), gain=_plain(cfg.get('gain', row.get('gain'))),
                              start=_plain(cfg.get('intervention_start', row.get('start'))),
                              stop=_plain(cfg.get('intervention_stop', row.get('stop')))),
            metrics=metrics, curves=curves, constraints=_constraint_rows(source, name),
            constraint_definition=_plain(definition.get('search_options'))))
    scope = source.get('data_scope') or {}
    runtime = source.get('actual_data_identity') or source.get('execution_identity') or source.get('local_identity') or {}
    actual_content = runtime.get('scope_content') or task.get('scope_content') or {}
    scope_members = task.get('scope', {}).get('body_ids')
    return dict(kind='offline_result_report', schema_version=REPORT_VERSION,
        name=_text(task.get('name') or source.get('name') or scope.get('case_name') or ''),
        description=_text(task.get('description', '')), status=_text(source.get('status', 'completed')),
        identity=_plain(dict(model_version=source.get('model_version', task.get('model_version')),
                            actual_case_id=runtime.get('case_id') or source.get('case_id', scope.get('case_id')),
                            actual_index_id=runtime.get('source_index_id') or source.get('source_index_id') or scope.get('source_index_id') or task.get('source_index_id'),
                            source_index_id=task.get('source_index_id'),
                            content_identity=task.get('scope_content') or task.get('scope_content_identity'),
                            data_source=task.get('source_data') or task.get('data_source'), execution_identity=runtime)),
        scope=dict(node_count=source.get('computation_node_count', len(scope_members) if scope_members is not None else None),
                   internal_edge_count=scope.get('internal_edge_count', scope.get('edge_count', actual_content.get('internal_edges'))),
                   external_input_contacts=scope.get('external_input_contacts'),
                   body_ids=_plain(scope_members)), conditions=conditions,
        operation_comparison=_plain(source.get('operation_comparison')),
        interactions=_plain(source.get('interactions')))


def _cell(value):
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def _csv(rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    for row in rows:
        writer.writerow([_cell(value) for value in row])
    return stream.getvalue()


def _judgments(condition, label):
    target, protected = {}, {}
    for row in condition['constraints']:
        target_row = row.get('target_constraint') or {}
        if target_row.get('observation') == label:
            target = target_row
        protected = row.get('protected_constraints', {}).get(label, protected)
    return target, protected


def _metrics_csv(report):
    header = ['condition', 'role', 'status', 'observation', 'body_ids', 'evaluation_start', 'evaluation_stop']
    header += list(METRIC_KEYS)
    header += ['target_metric', 'target_minimum', 'target_loss', 'target_satisfied', 'target_defined',
               'protection_metric', 'protection_limit', 'protection_loss', 'protection_satisfied', 'protection_defined']
    interaction_keys=('R0','RA','RB','RAB','delta_A','delta_B','delta_AB','interaction')
    if report['interactions'] is not None:
        header += ['joint_'+key for key in interaction_keys]
    rows = [header]
    for condition in report['conditions']:
        for metric in condition['metrics'] or [dict(observation='')]:
            window = metric.get('evaluation_window') or {}
            target, protection = _judgments(condition, metric['observation'])
            values=([condition['name'], condition['role'], condition['status'], metric['observation'],
                         metric.get('body_ids'), window.get('start'), window.get('stop')]
                        + [metric.get(key) for key in METRIC_KEYS]
                        + [target.get(key) for key in ('metric', 'minimum', 'loss', 'satisfied', 'defined')]
                        + [protection.get(key) for key in ('metric', 'limit', 'loss', 'satisfied', 'defined')])
            if report['interactions'] is not None:
                interaction=next((row for row in report['interactions'] if row['observation']==metric['observation']),{})
                values += [interaction.get(key) for key in interaction_keys]
            rows.append(values)
    return _csv(rows)


def _curves_csv(report):
    rows = [['condition', 'role', 'status', 'observation', 'state_step', 'baseline', 'intervention', 'delta']]
    for condition in report['conditions']:
        if not condition['curves']:
            rows.append([condition['name'], condition['role'], condition['status'], '', None, None, None, None])
        for observation, curve in condition['curves'].items():
            for index, t in enumerate(curve['state_steps']):
                rows.append([condition['name'], condition['role'], condition['status'], observation, t,
                             curve['baseline'][index], curve['intervention'][index],
                             curve['delta'][index] if curve['delta'] else None])
    return _csv(rows)


def _h(value):
    return html.escape(_text(value), quote=True)


LANGUAGES = ('zh-CN', 'en', 'ja', 'fr', 'de', 'es')


class ReportText:
    """Use the same compiled, authored messages as the workbench."""
    def __init__(self, language):
        if language not in LANGUAGES:
            from .ui_errors import DisplayError
            raise DisplayError('report_language', 'Unsupported report language')
        self.language = language
        self.messages = json.loads((Path(__file__).parent / 'locales' / (language + '.json')).read_text(encoding='utf-8'))

    def __call__(self, key, **params):
        return self.messages['report.' + key].format(**params)

    def code(self, category, value):
        aliases = {'complete':'completed','canceled':'cancelled','budget_exhausted':'budget_exceeded'}
        value = aliases.get(value, value)
        return self.messages.get('report.' + category + '.' + str(value), str(value) if value else self('unrecorded'))

    def fmt(self, value):
        if value is None:
            return self('undefined')
        if isinstance(value, bool):
            return self('yes' if value else 'no')
        return str(value)


def _json(value):
    return '<pre>' + _h(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)) + '</pre>'


def _plot(curve, condition, metric, text):
    steps = curve['state_steps']
    if not steps:
        return '<p>' + _h(text('noCurves')) + '</p>'
    left, right, top, bottom = 70, 770, 24, 230
    tmax = max(steps) or 1
    values = curve['baseline'] + curve['intervention']
    ymin, ymax = min(0, min(values)), max(0, max(values))
    scale = ymax - ymin or 1
    x = lambda t: left + (right - left) * t / tmax
    y = lambda v: bottom - (bottom - top) * (v - ymin) / scale
    bands = []
    def band(start, stop, color):
        if start is not None and stop is not None and start < stop:
            if stop - start == 1:
                bands.append(f'<path d="M{x(stop):.3f} {top}V{bottom}" stroke="{color}" stroke-width="2" opacity=".35"/>')
            else:
                bands.append(f'<rect x="{x(start + 1):.3f}" y="{top}" width="{max(0,x(stop)-x(start+1)):.3f}" height="{bottom-top}" fill="{color}" opacity=".14"/>')
    for event in condition['input_events'] or []:
        band(event.get('start'), event.get('stop'), '#13689d')
    if condition['intervention_events'] is None:
        band(condition['intervention']['start'], condition['intervention']['stop'], '#22804e')
    else:
        for event in condition['intervention_events']:
            if event['enabled']:
                band(event['start'],event['stop'],'#22804e' if event['type']=='node_gain' else '#7656a6')
    window = metric.get('evaluation_window') or {}
    band(window.get('start'), window.get('stop'), '#d18a04')
    lines = []
    for branch, color, dash in [('baseline', '#146cba', ''), ('intervention', '#bd3c33', 'stroke-dasharray="7 3"')]:
        points = ' '.join(f'{x(t):.3f},{y(v):.3f}' for t, v in zip(steps, curve[branch]))
        lines.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2" {dash}/>')
    return (f'<svg viewBox="0 0 800 275" role="img" aria-label="{_h(text("curveLabel", observation=metric["observation"]))}">'
            + ''.join(bands) + f'<path d="M{left} {top}V{bottom}H{right}" fill="none" stroke="#777"/>'
            + ''.join(lines) + f'<text x="{left-5}" y="{top}" text-anchor="end">{ymax:.6g}</text>'
            + f'<text x="{left-5}" y="{bottom}" text-anchor="end">{ymin:.6g}</text>'
            + f'<text x="{left}" y="250">0</text><text x="{right}" y="250" text-anchor="end">{tmax}</text>'
            + f'<text x="420" y="268" text-anchor="middle">{_h(text("axis"))}</text></svg>')


def _html_report(report, language='en'):
    text = ReportText(language)
    sections = []
    version = (report['identity'].get('data_source') or {}).get('dataset_version') or text('unrecorded')
    for condition in report['conditions']:
        panels = []
        for metric in condition['metrics']:
            label = metric['observation']
            window = metric.get('evaluation_window') or {}
            target, protection = _judgments(condition, label)
            rows = ''.join('<tr><th>' + _h(text(key)) + '</th><td>' + _h(text.fmt(metric.get(key))) + '</td></tr>'
                           for key in ('baseline_mean','intervention_mean','mean_delta','baseline_sum','intervention_sum',
                                       'sum_delta','relative_sum_delta','baseline_near_zero','sample_count'))
            judgments = []
            for role, item, bound in [('target', target, 'minimum'), ('protection', protection, 'limit')]:
                if item:
                    judgments.append('<p>' + _h(text('judgment', role=text(role),
                        metric=text(item['metric']) if item.get('metric') in ('relative','absolute') else text('unrecorded'),
                        direction=text('atLeast' if role == 'target' else 'atMost'),
                        bound=text.fmt(item.get(bound)), loss=text.fmt(item.get('loss')),
                        satisfied=text.fmt(item.get('satisfied')), defined=text.fmt(item.get('defined')))) + '</p>')
            plot = _plot(condition['curves'][label], condition, metric, text) if label in condition['curves'] else '<p>' + _h(text('noCurves')) + '</p>'
            panels.append('<article><h3>' + _h(label) + '</h3><p>' + _h(text('window', start=text.fmt(window.get('start')), stop=text.fmt(window.get('stop'))))
                          + '</p>' + plot + '<table>' + rows + '</table>' + ''.join(judgments) + '</article>')
        error = ('<details><summary>' + _h(text('failedDetails')) + '</summary><pre>' + _h(condition['error']) + '</pre></details>') if condition['error'] else ''
        sections.append('<section><h2>' + _h(condition['name']) + '</h2><p>'
            + _h(text('conditionStatus',status=text.code('status',condition['status']),role=text.code('role',condition['role']))) + '</p>' + error
            + '<details><summary>' + _h(text('configuration')) + '</summary>'
            + _json(dict(input_events=condition['input_events'],observations=condition['observations'],intervention=condition['intervention'],
                         intervention_events=condition['intervention_events'],intervention_semantics_version=condition['intervention_semantics_version'],
                         steps=condition['experiment'].get('steps'),alpha=condition['experiment'].get('alpha'),rho=condition['experiment'].get('rho')))
            + '</details>' + (''.join(panels) or '<p>' + _h(text('noMetrics')) + '</p>')
            + '<details><summary>' + _h(text('constraints')) + '</summary>'
            + _json(dict(definition=condition['constraint_definition'],judgments=condition['constraints'])) + '</details></section>')
    title = report['name'] or text('title')
    return ('<!doctype html><html lang="' + language + '"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
            + '<title>Cecropis · ' + _h(title) + '</title><style>'
            + 'body{font:14px/1.5 system-ui,sans-serif;color:#202A27;background:#F6F7F4;max-width:1100px;margin:32px auto;padding:0 20px}'
            + 'header{border-bottom:1px solid #DCE4DE;padding-bottom:16px}.brand{font-size:20px;font-weight:600}h1{font-size:20px}h2,h3{font-size:16px}'
            + 'section{border-top:1px solid #DCE4DE;margin-top:24px;padding-top:12px}article{padding:16px;border:1px solid #DCE4DE;border-radius:6px;background:#FFF;margin:16px 0}'
            + 'pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#E5F0E9;padding:12px}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}'
            + 'th,td{text-align:left;padding:6px 12px;border-bottom:1px solid #DCE4DE}svg{display:block;width:100%;height:auto}svg text{font-size:12px}details{margin:12px 0}'
            + '</style></head><body><header><div class="brand">Cecropis</div><h1>' + _h(title) + '</h1></header><p>'
            + _h(text('summary',status=text.code('status',report['status']),nodes=text.fmt(report['scope']['node_count']),conditions=len(report['conditions']))) + '</p>'
            + ('<p>' + _h(report['description']) + '</p>' if report['description'] else '')
            + '<p>' + _h(text('versions',model=report['identity'].get('model_version') or text('unrecorded'),dataset=version)) + '</p>'
            + '<details><summary>' + _h(text('identity')) + '</summary>' + _json(dict(identity=report['identity'],scope=report['scope'])) + '</details>'
            + '<p>' + _h(text('legend')) + '</p>'
            + ('<details><summary>' + _h(text('interactions')) + '</summary>' + _json(report['interactions']) + '</details>' if report['interactions'] is not None else '')
            + ''.join(sections) + '</body></html>')


def render_report(source, condition_names=None, max_bytes=DEFAULT_MAX_BYTES, *, language='en'):
    """Preview exact export sizes; no files are written and no data are computed."""
    if type(max_bytes) is not int or not 1 <= max_bytes <= 128 * 1024 ** 2:
        raise ValueError('max_bytes must be an integer in 1..134217728')
    report = extract_report(source, condition_names)
    files = {'report.html': _html_report(report, language), 'metrics.csv': _metrics_csv(report), 'curves.csv': _curves_csv(report)}
    sizes = {name: len(value.encode('utf-8')) for name, value in files.items()}
    total = sum(sizes.values())
    if total > max_bytes:
        raise ValueError(f'Offline report requires {total} bytes; export budget is {max_bytes}. Select fewer conditions or explicitly raise the budget.')
    return dict(kind='offline_report_export', schema_version=REPORT_VERSION, name=report['name'], language=language,
                condition_names=[item['name'] for item in report['conditions']],
                condition_statuses=[dict(name=item['name'], status=item['status']) for item in report['conditions']],
                files=files, sizes=sizes, total_bytes=total, max_bytes=max_bytes,
                propagation_count=0, report=report)


def export_report(source, destination, condition_names=None, max_bytes=DEFAULT_MAX_BYTES, *, language='en'):
    """Publish a new report directory atomically, never overwrite source/results."""
    rendered = render_report(source, condition_names, max_bytes, language=language)
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Report destination already exists; choose a new directory')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name('.' + destination.name + '-' + uuid4().hex + '.tmp')
    temporary.mkdir()
    try:
        for name, content in rendered['files'].items():
            (temporary / name).write_text(content, encoding='utf-8', newline='')
        if destination.exists():
            raise ValueError('Report destination was created during export; choose a new directory')
        os.rename(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {key: value for key, value in rendered.items() if key not in ('files', 'report')} | dict(
        directory=str(destination.resolve()), paths={name: str((destination / name).resolve()) for name in rendered['files']})
