"use strict";

/* Protocol editing uses exact body IDs; all numerical work remains in Python. */
let protocolReady = false,
  curveSource = null,
  signalContextResult = null;
let comparisonFocusIndex = 0;
const curveSelected = new Set(),
  conditionSelected = new Set();
function protocolIds(role, label) {
  const groups = overview?.group_body_ids?.[role] || {};
  return label === '__all__' ? [...new Set(Object.values(groups).flat())] : [...(groups[label] || [])];
}
function protocolEvents(c) {
  return Array.isArray(c.input_events) ? c.input_events.map(e => ({
    body_ids: [...e.body_ids],
    start: e.start,
    stop: e.stop,
    amplitude: e.amplitude
  })) : [{
    body_ids: protocolIds('input', c.input_group),
    start: c.input_start,
    stop: c.input_stop,
    amplitude: c.amplitude
  }];
}
function protocolObservations(c) {
  return Array.isArray(c.observations) ? c.observations.map(o => ({
    name: o.name,
    body_ids: [...o.body_ids],
    ...(o.evaluation_window ? {
      evaluation_window: {
        ...o.evaluation_window
      }
    } : {})
  })) : (c.outputs || []).map(name => ({
    name,
    body_ids: protocolIds('output', name)
  }));
}
function canonicalEvents(c) {
  return protocolEvents(c).map(e => ({
    ...e,
    body_ids: e.body_ids.slice().sort()
  })).sort((a, b) => a.start - b.start || a.stop - b.stop || a.amplitude - b.amplitude || JSON.stringify(a.body_ids).localeCompare(JSON.stringify(b.body_ids)));
}
function canonicalObservations(c) {
  return protocolObservations(c).map(o => ({
    ...o,
    body_ids: o.body_ids.slice().sort(),
    evaluation_window: {
      start: o.evaluation_window?.start ?? 0,
      stop: o.evaluation_window?.stop ?? c.steps
    }
  })).sort((a, b) => a.name.localeCompare(b.name));
}
function protocolSources(c) {
  return [...new Set(protocolEvents(c).flatMap(e => e.body_ids))];
}
function protocolObservationIds(c, label) {
  return protocolObservations(c).find(o => o.name === label)?.body_ids || [];
}
function currentSelectionIds() {
  const group = $('intervention_group').value;
  return $('selection_mode').value === 'all' ? candidateNodes(group).map(n => n.bodyId) : parseBodyIds($('selection_ids').value, true);
}
function groupShortcutOptions() {
  return '<option value="">' + UI.format(UI.msg("protocol.groupShortcutOptions.exact_body_ids_07c86e", {})) + '</option>' + Object.entries(overview?.groups || {}).flatMap(([role, labels]) => labels.map(label => `<option value="${esc(JSON.stringify([role, label]))}">${esc(UI.format(roles[role] || role) + ' · ' + label)}</option>`)).join('') + '<option value="selection">' + UI.format(UI.msg("protocol.groupShortcutOptions.current_intervention_set_d6edaa", {})) + '</option>';
}
function collectionCell(ids, kind, k) {
  const source = Object.entries(overview?.group_body_ids || {}).flatMap(([role, groups]) => Object.entries(groups).map(([name, members]) => ({role, name, members}))).find(group => group.members.length === ids.length && group.members.every(id => ids.includes(id)));
  return `<details class="member-editor" ${ids.length ? '' : 'open'}><summary><span data-count>${UI.htmlText('editor.members', {count:UI.numeric(ids.length)})}</span>${source ? '<span class="member-source">' + UI.html(source.name) + '</span>' : ''}<span class="member-edit-label">${UI.htmlText('editor.editMembers')}</span></summary><div class="buttons"><select data-protocol-shortcut="${kind}" data-row="${k}" ${UI.htmlAttribute("aria-label", "protocol.collectionCell.node_select_cde95a", {
    p0: kind === 'event' ? UI.msg("protocol.collectionCell.input_events_409b10", {}) : UI.msg("protocol.collectionCell.observation_sets_376101", {}),
    p1: k + 1
  })}>${groupShortcutOptions()}</select></div><input type="text" data-field="body_ids" value="${esc(ids.join(', '))}" ${UI.htmlAttribute('aria-label','editor.bodyIds',{role:UI.msg(kind === 'event' ? 'protocol.collectionCell.input_events_409b10' : 'protocol.collectionCell.observation_sets_376101'),number:k+1})}></details>`;
}
function eventRow(e, k) {
  return `<tr>${'<td>' + collectionCell(e.body_ids, 'event', k) + '</td>'}<td><input data-field="start" type="number" min="0" value="${e.start}" ${UI.htmlAttribute("aria-label", "protocol.eventRow.input_events_start_update_ed662d", {
    p0: k + 1
  })} style="width:85px"></td><td><input data-field="stop" type="number" min="1" value="${e.stop}" ${UI.htmlAttribute("aria-label", "protocol.eventRow.input_events_stop_e36ef4", {
    p0: k + 1
  })} style="width:85px"></td><td><input data-field="amplitude" type="number" min="0" max="1" step="any" value="${e.amplitude}" ${UI.htmlAttribute("aria-label", "protocol.eventRow.input_events_amplitude_14961f", {
    p0: k + 1
  })} style="width:85px"></td><td><button type="button" class="small" data-delete-event="${k}">${UI.htmlText("protocol.eventRow.remove_6135d4", {})}</button></td></tr>`;
}
function observationRow(o, k, steps = Number($('steps').value)) {
  if (typeof steps !== 'number') steps = Number($('steps').value);
  const window = o.evaluation_window || {
      start: 0,
      stop: steps
    },
    full = !o.evaluation_window || window.start === 0 && window.stop === steps;
  return `<tr><td><input data-field="name" type="text" maxlength="80" value="${esc(o.name)}" ${UI.htmlAttribute("aria-label", "protocol.observationRow.observation_sets_name_9eed40", {
    p0: k + 1
  })} style="width:140px"></td><td>${collectionCell(o.body_ids, 'observation', k)}</td><td><label class="pill"><input data-window-full type="checkbox" ${full ? 'checked' : ''}>${UI.htmlText("protocol.observationRow.full_run_2d6445", {})}</label><div class="buttons"><input data-field="evaluation_start" type="number" min="0" value="${window.start}" ${full ? 'disabled' : ''} ${UI.htmlAttribute("aria-label", "protocol.observationRow.start_update_8092fd", {
    p0: o.name
  })} style="width:80px"><span>${UI.htmlText("protocol.observationRow.to_65edbf", {})}</span><input data-field="evaluation_stop" type="number" min="1" value="${window.stop}" ${full ? 'disabled' : ''} ${UI.htmlAttribute("aria-label", "protocol.observationRow.stop_4ff4d5", {
    p0: o.name
  })} style="width:80px"></div></td><td><button type="button" class="small" data-delete-observation="${k}">${UI.htmlText("protocol.observationRow.remove_6135d4", {})}</button></td></tr>`;
}
function rawProtocolRows(id) {
  return [...$(id).querySelectorAll('tr')].map(row => {
    const fields = Object.fromEntries([...row.querySelectorAll('[data-field]')].map(input => [input.dataset.field, input.dataset.field === 'body_ids' ? input.value.trim().split(/[\s,，]+/).filter(Boolean) : input.type === 'number' ? Number(input.value) : input.value.trim()]));
    if (id === 'observations') {
      if (!row.querySelector('[data-window-full]').checked) fields.evaluation_window = {
        start: fields.evaluation_start,
        stop: fields.evaluation_stop
      };
      delete fields.evaluation_start;
      delete fields.evaluation_stop;
    }
    return fields;
  });
}
function setProtocol(c) {
  $('input_events').innerHTML = protocolEvents(c).map(eventRow).join('');
  $('observations').innerHTML = protocolObservations(c).map((o, k) => observationRow(o, k, c.steps)).join('');
  protocolReady = true;
  refreshProtocolTargets();
}
const legacyCfg = cfg;
cfg = function () {
  const c = legacyCfg();
  if (protocolReady) {
    c.input_events = rawProtocolRows('input_events');
    c.observations = rawProtocolRows('observations');
    c.outputs = c.observations.map(o => o.name);
  }
  return c;
};
const legacyApply = apply;
apply = function (c) {
  validateCondition(c);
  setProtocol(c);
  legacyApply(c);
  refreshProtocolTargets();
};
validateCondition = function (c) {
  if (!c || typeof c !== 'object' || Array.isArray(c)) throw UI.error("protocol.controls.condition_95077c", {});
  const fields = new Set(['steps', 'alpha', 'rho', 'input_group', 'input_start', 'input_stop', 'amplitude', 'intervention_group', 'intervention_start', 'intervention_stop', 'gain', 'outputs', 'intervention_ids', 'input_events', 'observations', 'intervention_events', 'intervention_semantics_version']);
  if (Object.keys(c).some(k => !fields.has(k))) throw UI.error("protocol.controls.condition_263052", {});
  for (const name of ['steps', 'intervention_start', 'intervention_stop']) if (!Number.isInteger(c[name])) throw UI.errorValue(UI.join([name, UI.msg("protocol.controls.message_0cea83", {})]));
  if (c.steps < 1 || c.steps > 2000 || !(0 <= c.intervention_start && c.intervention_start < c.intervention_stop && c.intervention_stop <= c.steps)) throw UI.error("protocol.controls.intervention_interval_must_fit_within_the_total_updates_af3339", {});
  for (const [name, min] of [['alpha', .001], ['rho', 0], ['gain', 0]]) if (!Number.isFinite(c[name]) || c[name] < min || c[name] > 1) throw UI.errorValue(UI.join([name, UI.msg("protocol.controls.scope_3bbd98", {})]));
  const allowed = new Set((overview.scope_nodes || [...(overview.internal_nodes || []), ...Object.values(overview.group_body_ids || {}).flatMap(g => Object.values(g).flat().map(bodyId => ({
    bodyId
  })))]).map(n => n.bodyId));
  const ids = values => {
    if (!Array.isArray(values) || !values.length || new Set(values).size !== values.length || values.some(id => typeof id !== 'string' || !allowed.has(id))) throw UI.error("protocol.ids.node_sets_require_unique_body_ids_within_the_calculation_bf9ad0", {});
  };
  const events = protocolEvents(c),
    observations = protocolObservations(c);
  if (events.length > 128) throw UI.error("protocol.controls.input_events_128_a74588", {});
  for (const e of events) {
    ids(e.body_ids);
    if (!Number.isInteger(e.start) || !Number.isInteger(e.stop) || !(0 <= e.start && e.start < e.stop && e.stop <= c.steps) || !Number.isFinite(e.amplitude) || e.amplitude < 0 || e.amplitude > 1) throw UI.error("protocol.controls.invalid_input_event_interval_or_amplitude_a8c113", {});
  }
  if (!observations.length || observations.length > 32) throw UI.error("protocol.controls.observation_sets_1_32_527e5d", {});
  const names = new Set();
  for (const o of observations) {
    if (typeof o.name !== 'string' || !o.name.trim() || o.name.length > 80 || o.name === '__all__' || names.has(o.name)) throw UI.error("protocol.controls.observation_names_must_be_nonempty_and_unique_765db4", {});
    names.add(o.name);
    ids(o.body_ids);
    const window = o.evaluation_window || {
      start: 0,
      stop: c.steps
    };
    if (Object.keys(window).sort().join('|') !== 'start|stop' || !Number.isInteger(window.start) || !Number.isInteger(window.stop) || !(0 <= window.start && window.start < window.stop && window.stop <= c.steps)) throw UI.error("protocol.controls.observation_window_must_fit_within_the_total_updates_6bd639", {});
  }
  if (c.intervention_group !== '__all__' && !overview.groups.internal.includes(c.intervention_group)) throw UI.error("protocol.controls.candidate_set_scope_422b41", {});
  if (c.intervention_ids != null) {
    const candidates = new Set(candidateNodes(c.intervention_group).map(n => n.bodyId));
    if (!Array.isArray(c.intervention_ids) || !c.intervention_ids.length || new Set(c.intervention_ids).size !== c.intervention_ids.length || c.intervention_ids.some(id => !candidates.has(id))) throw UI.error("protocol.controls.interventionnode_candidate_set_body_id_593ee3", {});
  }
};
function refreshProtocolTargets() {
  if (!protocolReady) return;
  const labels = rawProtocolRows('observations').map(o => o.name).filter(Boolean),
    previous = {};
  for (const id of ['path_observation_a', 'path_observation_b', 'search_target', 'selection_output']) {
    previous[id] = $(id).value;
    options(id, labels);
    if (labels.includes(previous[id])) $(id).value = previous[id];
  }
  if (labels.length > 1 && $('path_observation_b').value === $('path_observation_a').value) $('path_observation_b').value = labels.find(n => n !== $('path_observation_a').value);
  $('path_observation_controls').hidden = $('path_endpoint_mode').value === 'ids';
  $('path_explore').disabled = $('path_endpoint_mode').value !== 'ids' && labels.length < 2;
  refreshProtectedRows();
}
function readProtectedRows() {
  return [...$('protected_observations').querySelectorAll('tr')].map(row => ({
    name: row.dataset.label,
    enabled: row.querySelector('[data-protect]').checked,
    metric: row.querySelector('[data-protect-metric]').value,
    value: Number(row.querySelector('[data-protect-limit]').value)
  }));
}
function refreshProtectedRows(saved = null) {
  const previous = new Map(readProtectedRows().map(o => [o.name, o])),
    target = $('search_target').value;
  $('protected_observations').innerHTML = rawProtocolRows('observations').filter(o => o.name && o.name !== target).map(o => {
    const prior = saved?.[o.name],
      old = previous.get(o.name),
      metric = prior?.metric || old?.metric || 'relative',
      value = prior ? prior.max_loss * (metric === 'relative' ? 100 : 1) : old?.value ?? 1,
      enabled = prior !== undefined || old?.enabled !== false;
    return `<tr data-label="${esc(o.name)}"><td><input type="checkbox" data-protect ${enabled ? 'checked' : ''} ${UI.htmlAttribute("aria-label", "protocol.controls.protection_5e7311", {
      p0: o.name
    })}></td><td>${UI.html(o.name)}</td><td><select data-protect-metric ${UI.htmlAttribute("aria-label", "protocol.controls.protectionmetric_f52221", {
      p0: o.name
    })}><option value="relative" ${metric === 'relative' ? 'selected' : ''} data-i18n="protocol.controls.relative_87577c">${UI.t("protocol.controls.relative_87577c")}</option><option value="absolute" ${metric === 'absolute' ? 'selected' : ''} data-i18n="protocol.controls.absolute_mean_activity_24d3f6">${UI.t("protocol.controls.absolute_mean_activity_24d3f6")}</option></select></td><td><input data-protect-limit type="number" min="0" step="any" value="${value}" ${UI.htmlAttribute("aria-label", "protocol.controls.maximum_decrease_5d15df", {
      p0: o.name
    })} style="width:110px"></td></tr>`;
  }).join('');
}
function searchOptions() {
  return {
    candidate_policy: $('search_candidate_policy').value,
    candidate_order: $('search_candidate_order').value,
    target_output: $('search_target').value,
    target_metric: $('search_metric').value,
    min_target_loss: Number($('search_min').value) / ($('search_metric').value === 'relative' ? 100 : 1),
    protected_limits: Object.fromEntries(readProtectedRows().filter(o => o.enabled).map(o => [o.name, {
      metric: o.metric,
      max_loss: o.value / (o.metric === 'relative' ? 100 : 1)
    }])),
    max_nodes: Number($('search_size').value),
    max_evaluations: Number($('search_budget').value)
  };
}
function applySearchOptions(o = {}, legacy = false) {
  $('search_candidate_order').value = o.candidate_order || (legacy ? 'body_id' : 'signal_path');
  $('search_candidate_policy').value = o.candidate_policy || (legacy ? 'allow_endpoints' : 'internal_only');
  const labels = cfg().outputs;
  $('search_target').value = o.target_output || labels[0];
  $('search_metric').value = o.target_metric || 'relative';
  $('search_min').value = (o.min_target_loss || 0) * ($('search_metric').value === 'relative' ? 100 : 1);
  $('search_size').value = o.max_nodes || 10;
  $('search_budget').value = o.max_evaluations || 1000;
  const protectedLimits = o.protected_limits ?? {
    [o.protected_output || labels[1]]: {
      metric: 'relative',
      max_loss: o.max_protected_loss ?? .01
    }
  };
  refreshProtectedRows(protectedLimits);
  for (const row of $('protected_observations').querySelectorAll('tr')) row.querySelector('[data-protect]').checked = Object.hasOwn(protectedLimits, row.dataset.label);
}
$('search_target').onchange = () => refreshProtectedRows();
function protocolEdited() {
  refreshProtocolTargets();
  changed();
  UI.text($('record_status'), '');
  document.dispatchEvent(new Event('lab-protocol'));
}
for (const id of ['input_events', 'observations']) $(id).addEventListener('input', event => {
  const row = event.target.closest('tr');
  if (event.target.dataset.field === 'body_ids') {
    UI.text(row.querySelector('[data-count]'), UI.msg('editor.members', {count:UI.numeric(event.target.value.trim().split(/[\s,，]+/).filter(Boolean).length)}));
    row.querySelector('.member-source')?.remove();
  }
  if (id === 'observations' && event.target.dataset.field === 'name') {
    for (const field of ['evaluation_start', 'evaluation_stop']) {
      const input = row.querySelector(`[data-field="${field}"]`);
      const params = {p0:event.target.value.trim()};
      input.setAttribute('data-i18n-label-params', JSON.stringify(params));
      UI.attr(input, 'aria-label', UI.msg(input.dataset.i18nLabel, params));
    }
  }
  protocolEdited();
});
document.addEventListener('change', event => {
  if (!event.target.dataset.protocolShortcut) return;
  try {
    const value = event.target.value;
    if (!value) return;
    const ids = value === 'selection' ? currentSelectionIds() : protocolIds(...JSON.parse(value)),
      row = event.target.closest('tr');
    row.querySelector('[data-field="body_ids"]').value = ids.join(', ');
    UI.text(row.querySelector('[data-count]'), UI.msg('editor.members', {count:UI.numeric(ids.length)}));
    row.querySelector('.member-source')?.remove();
    event.target.value = '';
    protocolEdited();
  } catch (e) {
    status(UI.errorText(e), true);
  }
});
$('add_input_event').onclick = () => {
  if (busy) return;
  const rows = rawProtocolRows('input_events');
  if (rows.length >= 128) return;
  rows.push({
    body_ids: protocolIds('input', $('input_group').value),
    start: 0,
    stop: Math.min(10, Number($('steps').value)),
    amplitude: 1
  });
  $('input_events').innerHTML = rows.map(eventRow).join('');
  protocolEdited();
};
$('add_observation').onclick = () => {
  if (busy) return;
  const rows = rawProtocolRows('observations');
  if (rows.length >= 32) return;
  let number = rows.length + 1;
  let name = UI.t('editor.observationName', {number});
  while (rows.some(o => o.name === name)) name = UI.t('editor.observationName', {number:++number});
  rows.push({
    name,
    body_ids: []
  });
  $('observations').innerHTML = rows.map(observationRow).join('');
  protocolEdited();
};
document.addEventListener('click', event => {
  if (busy) return;
  const button = event.target.closest('button[data-delete-event], button[data-delete-observation]');
  if (!button) return;
  for (const [key, id, render] of [['deleteEvent', 'input_events', eventRow], ['deleteObservation', 'observations', observationRow]]) if (button.dataset[key] !== undefined) {
    const rows = rawProtocolRows(id);
    if (id === 'observations' && rows.length === 1) {
      status(UI.msg("protocol.controls.keep_observation_sets_a5ca37", {}), true);
      return;
    }
    rows.splice(Number(button.dataset[key]), 1);
    $(id).innerHTML = rows.map(render).join('');
    protocolEdited();
  }
});
$('replace_single_input').onclick = () => {
  const c = legacyCfg();
  $('input_events').innerHTML = protocolEvents(c).map(eventRow).join('');
  protocolEdited();
};
$('replace_legacy_observations').onclick = () => {
  const c = legacyCfg();
  $('observations').innerHTML = protocolObservations(c).map((o, k) => observationRow(o, k, c.steps)).join('');
  protocolEdited();
};
function observationColor(label) {
  return UI.observationColor(label);
}
function isBatchCurves(result) {
  return Array.isArray(result?.results) && Array.isArray(result?.rows);
}
function activeSignalResult() {
  return signalContextResult || latest;
}
function setSignalContext(result, name) {
  signalContextResult = result;
  const previous = $('signal_output').value;
  options('signal_output', result?.config?.experiment?.outputs || Object.keys(result?.signals || {}));
  if ([...$('signal_output').options].some(o => o.value === previous)) $('signal_output').value = previous;
  $('signal_output').disabled = !result?.signals;
  UI.text($('signal_context'), UI.join([name, result?.signals ? '' : UI.msg("protocol.setSignalContext.incoming_signals_aa8377", {})]));
  renderSignals(result);
}
function setSignalChoices(result) {
  const choices = isBatchCurves(result) ? result.results.map((r, k) => ({
    result: r,
    name: result.rows[k].name
  })) : [{
    result,
    name: result.kind === 'forward' ? UI.msg("protocol.setSignalChoices.forward_run_66b095", {}) : UI.msg("protocol.setSignalChoices.message_a2ebfb", {})
  }];
  $('signal_condition').replaceChildren();
  for (const [k, choice] of choices.entries()) {
    const option = document.createElement('option');
    option.value = k;
    UI.text(option, choice.name);
    $('signal_condition').append(option);
  }
  $('signal_condition').disabled = choices.length < 2;
  $('signal_condition').onchange = () => {
    const choice = choices[Number($('signal_condition').value)];
    setSignalContext(choice.result, choice.name);
  };
  if (!choices.length) {
    setSignalContext(null, UI.msg("protocol.setSignalChoices.condition_770deb", {}));
    return;
  }
  setSignalContext(choices[0].result, choices[0].name);
}
function curveSummaryCells(o, forward) {
  return forward ? `<td>${UI.html(fmt(o.baseline_sum))}</td><td>${UI.html(fmt(o.baseline_peak))}</td><td>${UI.html(fmt(o.final_response))}</td>` : `<td>${UI.html(fmt(o.baseline_sum))}</td><td>${UI.html(fmt(o.intervention_sum))}</td><td>${UI.html(changeText(o))}</td>`;
}
function changeText(o) {
  if (!o) return '—';
  const relative = o.relative_sum_delta;
  return relative == null ? UI.join([UI.msg("protocol.changeText.message_b00d5f", {}), fmt(o.sum_delta)]) : UI.percent(relative, 2);
}
function renderUnifiedCurves() {
  if (!curveSource) return;
  const results = isBatchCurves(curveSource) ? curveSource.results.map((r, k) => ({
      ...r,
      name: UI.name(curveSource.rows[k])
    })) : [{
      name: UI.msg("protocol.renderUnifiedCurves.message_a2ebfb", {}),
      ...curveSource
    }],
    labels = results[0]?.config?.experiment?.outputs || Object.keys(results[0]?.series || {});
  $('curve_observations').innerHTML = labels.map(label => `<label class="pill" style="color:${observationColor(label)}"><input type="checkbox" data-curve-observation="${esc(label)}" ${curveSelected.has(label) ? 'checked' : ''}> ${UI.html(label)}</label>`).join('');
  $('curve_conditions').innerHTML = isBatchCurves(curveSource) ? results.map((r, k) => `<label class="pill"><input type="checkbox" data-curve-condition="${k}" ${conditionSelected.has(k) ? 'checked' : ''}> ${UI.html(r.name || curveSource.rows[k]?.name)}</label>`).join('') : '';
  const forward = curveSource.kind === 'forward',
    chosen = results.filter((r, k) => !isBatchCurves(curveSource) || conditionSelected.has(k)),
    lines = [];
  chosen.forEach((r, k) => labels.filter(label => curveSelected.has(label)).forEach(label => {
    const s = r.series[label];
    if (!s) return;
    for (const branch of ['baseline', 'intervention']) if (s[branch]) lines.push({
      values: s[branch],
      label,
      color: observationColor(label),
      branch,
      condition: r.name || UI.msg("protocol.controls.message_a2ebfb", {}),
      conditionIndex: results.indexOf(r)
    });
  }));
  const W = Math.max(280,($('charts').clientWidth || document.querySelector('.app-content')?.clientWidth-48 || 900)-32),
    H = 240,
    L = 65,
    R = 20,
    T = 20,
    B = 44,
    steps = results[0]?.config?.experiment?.steps || results[0]?.experiment?.steps || Math.max(1, ...lines.map(l => l.values.length - 1));
  let maximum = 1e-12;
  for (const line of lines) for (const v of line.values) maximum = Math.max(maximum, v);
  maximum *= 1.1;
  const px = k => L + k / steps * (W - L - R),
    py = v => H - B - v / maximum * (H - T - B);
  let svg = `<svg class="plot" viewBox="0 0 ${W} ${H}" role="img" ${UI.htmlAttribute("aria-label", "protocol.renderUnifiedCurves.observation_sets_condition_f790ac", {})}>`;
  for (let k = 0; k <= 4; k++) {
    const v = maximum * k / 4,
      t = Math.round(steps * k / 4);
    svg += `<line x1="${L}" x2="${W - R}" y1="${py(v)}" y2="${py(v)}" stroke="var(--chart-grid)"/><text x="${L - 8}" y="${py(v) + 4}" text-anchor="end" fill="var(--muted)" font-size="12">${UI.html(fmt(v), true)}</text><text x="${px(t)}" y="${H - B + 20}" text-anchor="middle" fill="var(--muted)" font-size="12">${t}</text>`;
  }
  const baseSvg=svg;
  const lineMarkup=line=> `<polyline points="${line.values.map((v, k) => px(k) + ',' + py(v)).join(' ')}" stroke="${line.color}" fill="none" stroke-width="2" ${line.branch === 'intervention' && !forward ? 'stroke-dasharray="6 4"' : ''}><title>${UI.html(line.condition, true)} · ${UI.html(line.label, true)} · ${UI.html(line.branch === 'baseline' ? UI.msg("protocol.renderUnifiedCurves.baseline_a7ac58", {}) : UI.msg("response.labels.intervention_c74feb"), true)}</title></polyline>`;
  const endSvg= `<text x="${L}" y="${H - 3}" fill="var(--muted)" font-size="12">${UI.svgText("protocol.renderUnifiedCurves.set_mean_activity_model_units_41850f", {})}</text><text x="${W - R}" y="${H - 3}" text-anchor="end" fill="var(--muted)" font-size="12">${UI.svgText("protocol.renderUnifiedCurves.state_step_ebe1ee", {})}</text></svg>`;
  svg+=lines.map(lineMarkup).join('')+endSvg;
  const legend='<div class="curve-legend"><span><i class="curve-line"></i>'+UI.htmlText('use.baseline')+'</span><span><i class="curve-line dashed"></i>'+UI.htmlText('use.intervention')+'</span>'+[...curveSelected].map(label=>'<span><i class="curve-line" style="--curve-color:'+observationColor(label)+'"></i>'+esc(label)+'</span>').join('')+'</div>';
  const plots=isBatchCurves(curveSource)&&chosen.length>1 ? chosen.map(r=>'<section class="condition-plot"><h3>'+UI.html(r.name)+'</h3>'+baseSvg+lines.filter(l=>l.conditionIndex===results.indexOf(r)).map(lineMarkup).join('')+endSvg+'</section>').join('') : svg;
  $('charts').innerHTML = `<section class="panel chart"><div class="note">${legend}</div>${lines.length ? plots + protocolTimelineSvg(chosen, [...curveSelected]) : `<div class="empty">${UI.htmlText("protocol.renderUnifiedCurves.select_observations_and_conditions_91b06f", {})}</div>`}<div class="tablewrap"><table><thead><tr><th>${UI.htmlText("protocol.renderUnifiedCurves.condition_16bb1d", {})}</th><th>${UI.htmlText("protocol.renderUnifiedCurves.observation_sets_376101", {})}</th><th>${UI.htmlText("protocol.renderUnifiedCurves.node_2410d8", {})}</th>${forward ? `<th>${UI.htmlText("protocol.renderUnifiedCurves.response_sum_651711", {})}</th><th>${UI.htmlText("protocol.renderUnifiedCurves.peak_response_f55417", {})}</th><th>${UI.htmlText("protocol.renderUnifiedCurves.final_state_response_8ab619", {})}</th>` : `<th>${UI.htmlText("protocol.renderUnifiedCurves.baseline_evaluation_sum_847dd3", {})}</th><th>${UI.htmlText("protocol.renderUnifiedCurves.intervention_evaluation_sum_ca83eb", {})}</th><th>${UI.htmlText("protocol.renderUnifiedCurves.evaluation_sum_change_923c0f", {})}</th>`}</tr></thead><tbody>${chosen.flatMap(r => (r.summary || []).filter(o => curveSelected.has(o.type)).map(o => `<tr><td>${UI.html(r.name || UI.msg("protocol.controls.message_a2ebfb", {}))}</td><td>${isBatchCurves(curveSource) ? `<span style="color:${observationColor(o.type)}">${UI.html(o.type)}</span>` : `<button class="linkbtn" data-output="${esc(o.type)}" style="color:${observationColor(o.type)}">${UI.html(o.type)}</button>`}</td><td>${UI.html(num(o.node_count))}</td>${curveSummaryCells(o, forward)}</tr>`)).join('')}</tbody></table></div></section>`;
  const metrics = $('charts').querySelector('.tablewrap');
  if (metrics) {
    const details = document.createElement('details');
    const summary = document.createElement('summary');
    UI.text(summary, UI.msg('view.numbers'));
    metrics.before(details);
    details.append(summary, metrics);
  }
}
function setCurveSource(r) {
  const old = curveSource;
  curveSource = r;
  const results = isBatchCurves(r) ? r.results : [r],
    labels = results[0]?.config?.experiment?.outputs || Object.keys(results[0]?.series || {});
  if (!old || JSON.stringify([...curveSelected].sort()) !== JSON.stringify(labels.filter(l => curveSelected.has(l)).sort())) {
    curveSelected.clear();
    labels.slice(0, 3).forEach(l => curveSelected.add(l));
  }
  if (!curveSelected.size) labels.slice(0, 3).forEach(l => curveSelected.add(l));
  if (isBatchCurves(r)) {
    conditionSelected.clear();
    r.results.slice(0, 1).forEach((_, k) => conditionSelected.add(k));
  }
  renderUnifiedCurves();
}
const legacyRun = run;
run = async function () {
  if (busy) return;
  $('protocol_panel').inert = true;
  try {
    await legacyRun();
  } finally {
    $('protocol_panel').inert = false;
  }
};
const legacyRenderResult = renderResult;
renderResult = function (r) {
  signalContextResult = null;
  legacyRenderResult(r);
  setCurveSource(r);
  setSignalChoices(r);
};
document.addEventListener('change', event => {
  if (event.target.dataset.curveObservation !== undefined) {
    const label = event.target.dataset.curveObservation;
    event.target.checked ? curveSelected.add(label) : curveSelected.delete(label);
    renderUnifiedCurves();
  }
  if (event.target.dataset.curveCondition !== undefined) {
    const k = Number(event.target.dataset.curveCondition);
    event.target.checked ? conditionSelected.add(k) : conditionSelected.delete(k);
    renderUnifiedCurves();
  }
});
function canSaveComparison() {
  return !!(comparison?.comparison_id && comparisonView?.origin === 'calculated' && !busy && !comparisonSavingId);
}
function comparisonStateKey() {
  if (comparisonView?.origin === 'search-preview') return 'view.searchPreview';
  return comparisonView?.origin === 'saved' && comparisonView.artifactId ? 'view.saved' : 'view.unsavedComparison';
}
function refreshComparisonStatus() {
  if (!comparison) return;
  const saved = comparisonView?.origin === 'saved' && !!comparisonView.artifactId;
  UI.text($('comparison_status'), UI.msg(comparisonView?.origin === 'search-preview' ? 'view.searchPreview' : saved ? 'comparison.saved' : 'comparison.ready', {
    conditions: UI.numeric(comparison.rows.length), observations: UI.numeric(comparison.protocol.outputs.length)
  }));
  $('save_comparison').disabled = !canSaveComparison();
  $('save_comparison').hidden = saved || comparisonView?.origin === 'search-preview';
}
function renderComparison(r, {origin = 'calculated', artifactId = null, sourceArtifactId = null} = {}) {
  comparisonFocusIndex = 0;
  comparison = r;
  comparisonView = {origin, artifactId, sourceArtifactId};
  refreshComparisonStatus();
  setCurveSource({...r,kind:'comparison'});setSignalChoices({...r,kind:'comparison'});conditionSelected.clear();conditionSelected.add(comparisonFocusIndex);
  renderComparisonUsability(r);renderUnifiedCurves();
  document.dispatchEvent(new Event('lab-comparison'));
}
document.addEventListener('ui-language', () => {
  if (comparison) {refreshComparisonStatus();renderComparisonUsability(comparison);}
  renderUnifiedCurves();
});
document.addEventListener('ui-theme', () => renderUnifiedCurves());
document.addEventListener('ui-fonts', () => renderUnifiedCurves());
$('compare_conditions').onclick = async () => {
  if (busy) return;
  try {
    validateConditions(conditions);
  } catch (e) {
    status(UI.errorText(e), true);
    return;
  }
  busy = true;
  $('experiment').inert = true;
  $('protocol_panel').inert = true;
  for (const id of ['run', 'baseline', 'load', 'export', 'save', 'compare_conditions', 'save_comparison']) $(id).disabled = true;
  try {
    const r = await api('/api/compare', {
      conditions
    });
    renderComparison(r);
    status(UI.msg("protocol.controls.multi_condition_comparisoncomplete_1ba199", {}));
  } catch (e) {
    status(UI.errorText(e), true);
  } finally {
    busy = false;
    $('experiment').inert = false;
    $('protocol_panel').inert = false;
    for (const id of ['run', 'baseline', 'load', 'export', 'compare_conditions']) $(id).disabled = false;
    $('save').disabled = !latest || dirty;
    $('save_comparison').disabled = !canSaveComparison();
  }
};
function searchLossText(value, metric) {
  return value == null ? UI.msg("protocol.searchLossText.baseline_b345a1", {}) : metric === 'absolute' ? fmt(value) : UI.percent(value, 3);
}
renderSearch = function (r, restoreOptions = true) {
  searchResult = r;
  if (restoreOptions) applySearchOptions({
    ...r.options,
    target_output: r.target_output,
    protected_output: r.protected_output
  }, true);
  const plans = (r.best ? [r.best] : []).concat((r.frontier || []).filter(p => JSON.stringify(p.body_ids) !== JSON.stringify(r.best?.body_ids))).slice(0, 30);
  r.displayPlans = plans;
  const protectedLabels = Object.keys(r.options?.protected_limits || r.best?.protected_losses || {});
  if (!protectedLabels.length && r.protected_output) protectedLabels.push(r.protected_output);
  const metric = r.options?.target_metric || 'relative',
    loss = (p, label) => p.protected_losses?.[label] ?? (label === r.protected_output ? p.protected_loss : null),
    pmetric = label => r.options?.protected_limits?.[label]?.metric || 'relative';
  $('search_head').innerHTML = `<tr><th>${UI.htmlText("protocol.controls.plan_6f949a", {})}</th><th>${UI.htmlText("protocol.controls.node_count_2e797c", {})}</th><th>${UI.htmlText("protocol.controls.message_5154a5", {
    p0: r.target_output
  })}</th>${protectedLabels.map(l => `<th>${UI.htmlText("protocol.controls.message_5154a5", {
    p0: l
  })}</th>`).join('')}<th>${UI.htmlText("protocol.controls.constraints_ba0934", {})}</th><th>${UI.htmlText("protocol.controls.actions_ed31fb", {})}</th></tr>`;
  $('search_rows').innerHTML = plans.map((p, k) => `<tr><td>${UI.html(k === 0 ? UI.msg("protocol.controls.message_1234ab", {}) : UI.join([UI.msg("protocol.controls.message_3d7752", {}), k]))}</td><td>${p.node_count}</td><td>${UI.html(searchLossText(p.target_loss, metric))}</td>${protectedLabels.map(l => `<td>${UI.html(searchLossText(loss(p, l), pmetric(l)))}${UI.html(p.protected_constraints?.[l] ? UI.join([' · ', p.protected_constraints[l].satisfied ? UI.msg("protocol.controls.satisfied_4e8156", {}) : UI.msg("protocol.controls.exceeded_314600", {})]) : '')}</td>`).join('')}<td>${UI.html(p.feasible ? UI.msg("protocol.controls.satisfied_4e8156", {}) : esc((p.violations || []).join(' / ')))}</td><td><button class="linkbtn" data-plan="${k}">${UI.htmlText("protocol.controls.load_nodes_34138c", {})}</button></td></tr>`).join('');
  $('sensitivity_head').innerHTML = `<tr><th>body ID</th><th>${UI.htmlText("protocol.controls.type_ba4001", {})}</th><th>${UI.htmlText("protocol.controls.message_5154a5", {
    p0: r.target_output
  })}</th>${protectedLabels.map(l => `<th>${UI.htmlText("protocol.controls.message_5154a5", {
    p0: l
  })}</th>`).join('')}</tr>`;
  $('sensitivity_rows').innerHTML = (r.sensitivity || []).slice(0, 100).map(n => `<tr><td>${idButton(n.bodyId)}</td><td>${UI.html(n.type)}</td><td>${UI.html(searchLossText(n.target_loss, metric))}</td>${protectedLabels.map(l => `<td>${UI.html(searchLossText(loss(n, l), pmetric(l)))}</td>`).join('')}</tr>`).join('');
  UI.text($('search_status'), UI.msg("protocol.controls.message_4bcce2", {
    p0: {
      complete: UI.msg("protocol.controls.searchstop_8728a6", {}),
      budget_exhausted: UI.msg("protocol.controls.budget_exhausted_d9e9de", {}),
      cancelled: UI.msg("protocol.controls.cancelled_a37778", {})
    }[r.status] || UI.code(r.status),
    p1: r.target_output,
    p2: r.screened_candidates,
    p3: r.candidate_count,
    p4: r.evaluations,
    p5: r.options.max_evaluations,
    p6: r.best?.feasible ? UI.msg("protocol.controls.satisfiedindividual_constraints_plan_6481a8", {}) : UI.msg("protocol.controls.satisfiedindividual_constraints_plan_29c3fd", {})
  }));
  document.dispatchEvent(new Event('lab-search'));
};
$('search_start').onclick = async () => {
  if (busy || $('search_start').disabled) return;
  try {
    const c = cfg();
    validateCondition(c);
    $('search_start').disabled = true;
    $('search_save').disabled = true;
    const d = await api('/api/search', {
      experiment: c,
      options: searchOptions()
    });
    searchJob = d.job_id;
    searchResult = null;
    document.dispatchEvent(new Event('lab-search'));
    $('search_cancel').disabled = false;
    $('search_rows').replaceChildren();
    $('sensitivity_rows').replaceChildren();
    pollSearch(searchJob);
  } catch (e) {
    UI.text($('search_status'), UI.errorText(e));
    $('search_start').disabled = false;
  }
};
document.addEventListener('lab-case', () => {
  applySearchOptions({});
  signalContextResult = null;
  $('signal_condition').replaceChildren();
  UI.text($('signal_context'), '');
  curveSource = null;
  curveSelected.clear();
  conditionSelected.clear();
  $('curve_observations').replaceChildren();
  $('curve_conditions').replaceChildren();
});

// Context comes from an explicit baseline run; changing a threshold never changes its value here.
function contextNumber(value) {
  return value == null ? '—' : Number.isFinite(Number(value)) ? UI.numeric(Number(value), {
    notation: 'scientific',
    minimumFractionDigits: 4,
    maximumFractionDigits: 4
  }) : '—';
}
function contextPercent(value) {
  return value == null ? UI.msg("protocol.contextPercent.undefined_2c744a", {}) : UI.percent(Number(value), 3);
}
function clearSearchContext(prefix, message = '') {
  for (const suffix of ['context_rows', 'preselection_rows']) $(prefix + '_' + suffix).replaceChildren();
  UI.text($(prefix + '_context_status'), message);
  UI.text($(prefix + '_preselection_summary'), '');
}
function clearSearchDiagnostics(prefix) {
  UI.text($(prefix + '_diagnostic_status'), '');
  $(prefix + '_diagnostic_rows').replaceChildren();
}
function renderSearchContext(report, prefix, historical = false) {
  const conditions = report.constraint_context?.conditions;
  if (!conditions) {
    clearSearchContext(prefix, UI.msg("protocol.renderSearchContext.not_recordedbaseline_54f2d2", {}));
    return;
  }
  UI.text($(prefix + '_context_status'), UI.join([historical ? UI.msg("protocol.renderSearchContext.save_92ce37", {}) : '', UI.msg("protocol.renderSearchContext.baseline_mean_activity_model_units_fe1585", {})]));
  $(prefix + '_context_rows').innerHTML = conditions.flatMap(condition => {
    const entries = [[true, condition.target], ...Object.entries(condition.protected || {}).map(([name, item]) => [false, {
      observation: name,
      ...item
    }])];
    return entries.filter(([, item]) => item).map(([target, item]) => {
      const role = target ? UI.msg("protocol_ui.label.57060c88a3") : UI.msg("protocol.controls.protection_0f810a"),
        absolute = target ? item.required_absolute_loss : item.allowed_absolute_loss,
        relative = target ? item.required_relative_loss : item.allowed_relative_loss,
        meaning = item.near_zero && item.metric === 'relative' ? UI.msg("protocol.controls.metricundefined_d5fdbb", {}) : target ? item.exceeds_nonnegative_bound ? UI.msg("protocol.controls.baseline_7edda1", {}) : UI.msg("protocol.controls.message_29e6d0", {}) : item.allows_full_suppression ? UI.msg("protocol.controls.message_582f92", {}) : UI.msg("protocol.controls.maximum_decrease_23a30e", {});
      return `<tr><td>${UI.html(condition.name === 'single' ? UI.msg("protocol.controls.condition_b14319", {}) : condition.name)}</td><td>${UI.html(role)}</td><td>${UI.html(item.observation)}${UI.html(item.evaluation_window ? UI.join([UI.join([UI.join([UI.join([UI.msg("protocol.controls.message_e4cb6f", {}), item.evaluation_window.start]), ', ']), item.evaluation_window.stop]), ')']) : '')}</td><td>${UI.html(contextNumber(item.baseline_mean))}</td><td>${target ? '≥' : '≤'} ${UI.html(contextNumber(absolute))}</td><td>${target ? '≥' : '≤'} ${UI.html(contextPercent(relative))}</td><td>${UI.html(meaning)}</td></tr>`;
    });
  }).join('');
  const preselection = report.candidate_preselection;
  if (!preselection) {
    UI.text($(prefix + '_preselection_summary'), report.kind === 'joint_plan_evaluation' ? UI.msg("protocol.renderSearchContext.fixed_plan_90fc7e", {}) : UI.msg("protocol.renderSearchContext.not_recorded_order_78d15e", {}));
    $(prefix + '_preselection_rows').replaceChildren();
    return;
  }
  UI.text($(prefix + '_preselection_summary'), UI.msg("protocol.renderSearchContext.sort_42880b", {
    p0: preselection.method === 'signal_path' ? UI.msg("protocol.renderSearchContext.baseline_target_3_connections_mean_score_id_255159", {}) : UI.msg("protocol.renderSearchContext.by_body_id_94e546", {}),
    p1: preselection.ordered_body_ids?.length ?? 0,
    p2: preselection.zero_score_count == null ? UI.msg("protocol.renderSearchContext.message_20cc08", {}) : UI.join([UI.join([UI.msg("protocol.renderSearchContext.0_eadba9", {}), preselection.zero_score_count]), UI.msg("protocol.renderSearchContext.keep_a361e0", {})]),
    p3: preselection.available === false ? UI.msg("protocol.renderSearchContext.complete_66b07f", {}) : ''
  }));
  $(prefix + '_preselection_rows').innerHTML = (preselection.details || []).slice(0, 50).map(item => `<tr><td>${item.rank}</td><td>${UI.html(item.bodyId)}</td><td>${UI.html(contextNumber(item.min_score ?? item.score))}</td><td>${UI.html(contextNumber(item.mean_score))}</td><td style="white-space:normal">${UI.htmlList(Object.entries(item.condition_scores || {}).map(([name, score]) => UI.msg("protocol.controls.targetconnections_5a826a", {
    p0: name === 'single' ? UI.msg("protocol.controls.condition_b14319", {}) : name,
    p1: UI.numeric(score.baseline_activity_mean, {
      notation: "scientific",
      minimumFractionDigits: 4,
      maximumFractionDigits: 4
    }),
    p2: UI.numeric(score.target_influence, {
      notation: "scientific",
      minimumFractionDigits: 4,
      maximumFractionDigits: 4
    }),
    p3: UI.numeric(score.score, {
      notation: "scientific",
      minimumFractionDigits: 4,
      maximumFractionDigits: 4
    })
  })), '<br>')}</td></tr>`).join('');
}
function renderSearchDiagnostics(report, prefix, historical = false, selectedPlan = null) {
  const diagnostics = report.search_diagnostics;
  if (!diagnostics) {
    UI.text($(prefix + '_diagnostic_status'), UI.msg("protocol.renderSearchDiagnostics.not_recordedsearch_8cbfa0", {}));
    $(prefix + '_diagnostic_rows').replaceChildren();
    return;
  }
  const coverage = diagnostics.candidate_coverage || {},
    reasons = {
      evaluation_budget: UI.msg("protocol.renderSearchDiagnostics.set_evaluation_budget_510523", {}),
      cancelled: UI.msg("protocol.renderSearchDiagnostics.cancel_d8ccc0", {}),
      completed: UI.msg("protocol.renderSearchDiagnostics.searchcomplete_a06444", {}),
      search_complete: UI.msg("protocol.renderSearchDiagnostics.searchcomplete_a06444", {}),
      complete: UI.msg("protocol.renderSearchDiagnostics.searchcomplete_a06444", {}),
      no_feasible_solution: UI.msg("protocol.renderSearchDiagnostics.scope_plan_61ad76", {}),
      fixed_plan_evaluation: UI.msg("protocol.renderSearchDiagnostics.fixed_plan_f0aa75", {}),
      fixed_plan_evaluated: UI.msg("protocol.renderSearchDiagnostics.fixed_plan_0c8d8d", {}),
      bounded_shortlist_search_finished: UI.msg("protocol.renderSearchDiagnostics.searchcomplete_050044", {})
    },
    reason = reasons[diagnostics.termination_reason] || {
      'complete': UI.msg("protocol.renderSearchDiagnostics.searchcomplete_a06444", {}),
      'budget_exhausted': UI.msg("protocol.renderSearchDiagnostics.set_evaluation_budget_510523", {}),
      'cancelled': UI.msg("protocol.renderSearchDiagnostics.cancel_d8ccc0", {}),
      'fixed_plan_evaluation': UI.msg("protocol.renderSearchDiagnostics.fixed_plan_f0aa75", {})
    }[diagnostics.status] || UI.msg("protocol.renderSearchDiagnostics.searchstop_184860", {});
  const facts = {
    uncovered_candidates: UI.msg("protocol.renderSearchDiagnostics.message_2dcb68", {}),
    shortlist_limited: UI.msg("protocol.renderSearchDiagnostics.combinationscope_4d8682", {}),
    protection_rejected_singles: UI.msg("protocol.renderSearchDiagnostics.nodeplan_protectionconstraints_404132", {}),
    protection_rejected_sets: UI.msg("protocol.renderSearchDiagnostics.nodeplan_protectionconstraints_3f13bf", {}),
    no_protection_eligible_screened_candidates: UI.msg("protocol.renderSearchDiagnostics.satisfiedprotectionconstraints_9f8c35", {}),
    target_not_reached: UI.msg("protocol.renderSearchDiagnostics.plan_condition_target_c443d3", {}),
    evaluation_budget_reached: UI.msg("protocol.renderSearchDiagnostics.budget_d2eacc", {}),
    cancelled: UI.msg("protocol.renderSearchDiagnostics.cancelled_ac25a3", {}),
    target_exceeds_nonnegative_bound: UI.msg("protocol.renderSearchDiagnostics.target_decrease_baseline_41d44a", {}),
    zero_proxy_scores_present: UI.msg("protocol.renderSearchDiagnostics.0_scope_0322aa", {}),
    fixed_plan_not_optimized: UI.msg("protocol.renderSearchDiagnostics.fixed_plan_f81c71", {}),
    bounded_sets_not_exhaustive: UI.msg("protocol.renderSearchDiagnostics.nodecombination_budget_plan_95a08e", {})
  };
  UI.text($(prefix + '_diagnostic_status'), UI.join(["", historical ? UI.msg("protocol.renderSearchDiagnostics.save_92ce37", {}) : '', "", reason, "", diagnostics.candidate_coverage ? UI.msg("protocol.renderSearchDiagnostics.protection_node_set_91ee07", {
    p0: coverage.screened_count,
    p1: coverage.eligible_count,
    p2: coverage.uncovered_count,
    p3: diagnostics.protected_rejected_single_count,
    p4: diagnostics.protected_rejected_set_count,
    p5: diagnostics.shortlist_count,
    p6: diagnostics.shortlist_limited ? UI.msg("protocol.renderSearchDiagnostics.message_77cde5", {}) : ''
  }) : '', " · ", UI.list((diagnostics.facts || []).map(fact => facts[fact]).filter(Boolean)), ""]));
  const rows = (selectedPlan ? savedPlanExplanations(report, selectedPlan) : diagnostics.best?.condition_results) || !selectedPlan && report.rows?.filter(row => row.constraints?.explanation).map(row => ({
    name: row.name,
    ...row.constraints.explanation
  })) || [];
  if (selectedPlan) {
    UI.text($(prefix + '_diagnostic_status'), UI.join([UI.currentText($(prefix + '_diagnostic_status')), UI.msg("protocol.renderSearchDiagnostics.plannode_824363"), selectedPlan.body_ids.join(', '), rows.length ? '' : UI.msg("protocol.renderSearchDiagnostics.plannot_recorded_95cad5")]));
  } else if (report.best?.body_ids) UI.text($(prefix + '_diagnostic_status'), UI.join([UI.currentText($(prefix + '_diagnostic_status')), UI.msg("protocol.renderSearchDiagnostics.plannode_290894"), report.best.body_ids.join(', ')]));
  $(prefix + '_diagnostic_rows').innerHTML = rows.flatMap(row => [[true, row.target], ...Object.entries(row.protected || {}).map(([name, item]) => [false, {
    observation: name,
    ...item
  }])].filter(([, item]) => item).map(([target, item]) => {
    const role = target ? UI.msg("protocol_ui.label.57060c88a3") : UI.msg("protocol.controls.protection_0f810a"),
      absolute = target ? item.required_absolute_loss : item.allowed_absolute_loss,
      relative = target ? item.required_relative_loss : item.allowed_relative_loss,
      difference = target ? item.gap : item.excess,
      undefinedMetric = item.metric === 'relative' && item.actual_relative_loss == null,
      loose = !target && (item.allows_full_suppression || report.constraint_context?.conditions?.find(condition => condition.name === row.name)?.protected?.[item.observation]?.allows_full_suppression);
    return `<tr><td>${UI.html(row.name === 'single' ? UI.msg("protocol.controls.condition_b14319", {}) : row.name)}</td><td>${UI.html(role)}</td><td>${UI.html(item.observation || report.target_output || report.search_options?.target_output || report.options?.target_output || '')}</td><td>${UI.html(contextNumber(item.actual_absolute_loss))}</td><td>${UI.html(contextPercent(item.actual_relative_loss))}</td><td>${target ? '≥' : '≤'} ${UI.html(contextNumber(absolute))}</td><td>${target ? '≥' : '≤'} ${UI.html(contextPercent(relative))}</td><td>${UI.html(contextNumber(difference))}${UI.html(item.metric === 'relative' ? UI.msg("protocol.controls.message_ff6110", {}) : UI.msg("protocol.controls.message_3bdcc9", {}))}</td><td>${UI.html(undefinedMetric ? UI.msg("protocol.controls.metricundefined_d5fdbb", {}) : loose ? UI.msg("protocol.controls.constraints_06d78e", {}) : item.satisfied ? UI.msg("protocol.controls.satisfied_4e8156", {}) : target ? UI.msg("protocol.controls.target_aa63db", {}) : UI.msg("protocol.controls.protectionexceeded_9a9e68", {}))}</td></tr>`;
  })).join('');
}
function renderSearchEvidence(report, prefix, historical = false) {
  renderSearchContext(report, prefix, historical);
  renderSearchDiagnostics(report, prefix, historical);
}
const searchContextLocks = new Map();
function setSearchContextBusy(active) {
  if (active) {
    busy = true;
    for (const id of ['run', 'baseline', 'load', 'export', 'save', 'compare_conditions', 'save_comparison', 'search_start', 'search_cancel', 'search_save', 'search_context_check', 'joint_context_check', 'joint_preview', 'joint_start', 'joint_evaluate', 'joint_save', 'scope_compare_preview', 'scope_compare_run', 'open_saved_case', 'open_saved_result']) {
      searchContextLocks.set(id, $(id).disabled);
      $(id).disabled = true;
    }
  } else {
    busy = false;
    for (const [id, disabled] of searchContextLocks) $(id).disabled = disabled;
    searchContextLocks.clear();
  }
}
function savedPlanExplanations(report, plan) {
  const contexts = report.constraint_context?.conditions;
  if (!contexts) return null;
  const saved = plan.condition_results || plan.conditions || [{
      ...plan,
      name: 'single'
    }],
    rows = [];
  for (const row of saved) {
    const context = contexts.find(item => item.name === row.name),
      metrics = row.output_metrics;
    if (!context || !metrics) return null;
    function explain(threshold, target) {
      const metric = metrics[threshold.observation];
      if (!metric || !Number.isFinite(metric.mean_delta) || !(metric.relative_sum_delta === null || Number.isFinite(metric.relative_sum_delta))) return null;
      const absolute = -metric.mean_delta,
        relative = metric.relative_sum_delta === null ? null : -metric.relative_sum_delta,
        loss = threshold.metric === 'relative' ? relative : absolute,
        limit = threshold.limit ?? (threshold.metric === 'relative' ? target ? threshold.required_relative_loss : threshold.allowed_relative_loss : target ? threshold.required_absolute_loss : threshold.allowed_absolute_loss);
      if (!Number.isFinite(limit)) return null;
      return {
        ...threshold,
        actual_absolute_loss: absolute,
        actual_relative_loss: relative,
        [target ? 'gap' : 'excess']: loss === null ? null : Math.max(0, target ? limit - loss : loss - limit),
        satisfied: loss !== null && (target ? loss + 1e-12 >= limit : loss <= limit + 1e-12)
      };
    }
    const target = explain(context.target, true),
      protectedItems = {};
    if (!target) return null;
    for (const [label, threshold] of Object.entries(context.protected || {})) {
      const item = explain({
        observation: label,
        ...threshold
      }, false);
      if (!item) return null;
      protectedItems[label] = item;
    }
    rows.push({
      name: row.name,
      target,
      protected: protectedItems
    });
  }
  return rows;
}
document.addEventListener('click', event => {
  if (event.target.dataset.plan !== undefined && searchResult) {
    const plan = searchResult.displayPlans?.[Number(event.target.dataset.plan)];
    if (plan) renderSearchDiagnostics(searchResult, 'search', !!searchResult._historical, plan);
  }
});
document.addEventListener('change', event => {
  if (event.target.dataset.windowFull !== undefined) {
    const row = event.target.closest('tr');
    for (const field of ['evaluation_start', 'evaluation_stop']) row.querySelector('[data-field="' + field + '"]').disabled = event.target.checked;
    if (event.target.checked) {
      row.querySelector('[data-field="evaluation_start"]').value = 0;
      row.querySelector('[data-field="evaluation_stop"]').value = Number($('steps').value);
    }
    protocolEdited();
  }
});
function protocolTimelineSvg(results, labels) {
  if (!results.length) return '';
  const first = results[0].config?.experiment || results[0].experiment;
  if (!first) return '';
  const rows = [];
  for (const result of results) {
    const c = result.config?.experiment || result.experiment;
    if (!c) continue;
    rows.push({
      name: UI.join([result.name || UI.msg("protocol.protocolTimelineSvg.condition_b14319", {}), UI.msg("protocol.protocolTimelineSvg.message_826379", {})]),
      segments: protocolEvents(c).map(e => ({
        ...e,
        color: '#c89df9'
      }))
    });
    if (Array.isArray(c.intervention_events)) {
      for (const e of c.intervention_events.filter(e => e.enabled)) rows.push({
        name: UI.join([UI.join([UI.join([UI.join([result.name || UI.msg("protocol.protocolTimelineSvg.condition_b14319", {}), ' · ']), e.name]), ' · ']), e.type === 'edge_gain' ? UI.msg("protocol.protocolTimelineSvg.message_099db3", {}) : UI.msg("protocol.protocolTimelineSvg.node_2410d8", {})]),
        segments: [{
          start: e.start,
          stop: e.stop,
          color: e.type === 'edge_gain' ? '#63d4c5' : '#ec9b68'
        }]
      });
    } else rows.push({
      name: UI.join([result.name || UI.msg("protocol.protocolTimelineSvg.condition_b14319", {}), UI.msg("protocol.protocolTimelineSvg.nodeintervention_01240a", {})]),
      segments: [{
        start: c.intervention_start,
        stop: c.intervention_stop,
        color: '#ec9b68'
      }]
    });
  }
  for (const observation of protocolObservations(first).filter(o => labels.includes(o.name))) rows.push({
    name: UI.join([observation.name, UI.msg("protocol.protocolTimelineSvg.message_f3570b", {})]),
    segments: [{
      ...(observation.evaluation_window || {
        start: 0,
        stop: first.steps
      }),
      color: observationColor(observation.name)
    }]
  });
  const W = 800,
    L = 65,
    R = 20,
    H = rows.length * 30 + 35,
    x = step => L + step / first.steps * (W - L - R);
  return `<svg class="plot protocol-timeline" viewBox="0 0 ${W} ${H}" role="img" ${UI.htmlAttribute("aria-label", "protocol.protocolTimelineSvg.intervention_observation_status_updates_9a81d9", {})}>${rows.map((row, k) => `<text x="${L}" y="${k * 30 + 10}" fill="var(--muted)" font-size="12">${UI.html(row.name, true)}</text><line x1="${L}" x2="${W - R}" y1="${k * 30 + 21}" y2="${k * 30 + 21}" stroke="var(--chart-grid)"/>${row.segments.map(segment => `<line x1="${x(segment.start + 1)}" x2="${x(segment.stop)}" y1="${k * 30 + 21}" y2="${k * 30 + 21}" stroke="${segment.color}" stroke-width="6" stroke-linecap="round"><title>${UI.htmlText("protocol.controls.status_ac6d05", {
    p0: row.name,
    p1: segment.start,
    p2: segment.stop,
    p3: segment.start + 1,
    p4: segment.stop
  })}</title></line>`).join('')}`).join('')}<text x="${L}" y="${H - 3}" fill="var(--muted)" font-size="12">${UI.svgText("protocol.protocolTimelineSvg.response_state_step_0_0ff3ff", {})}</text><text x="${W - R}" y="${H - 3}" text-anchor="end" fill="var(--muted)" font-size="12">${first.steps}</text></svg>`;
}
$('steps').addEventListener('input', () => {
  for (const row of $('observations').querySelectorAll('tr')) if (row.querySelector('[data-window-full]')?.checked) {
    row.querySelector('[data-field=\"evaluation_start\"]').value = 0;
    row.querySelector('[data-field=\"evaluation_stop\"]').value = $('steps').value;
  }
});
document.addEventListener('ui-language', () => {
  for (const option of document.querySelectorAll('[data-protocol-shortcut] option')) {
    if (option.value === '') UI.text(option, UI.msg("protocol.controls.exact_body_ids_07c86e", {}));else if (option.value === 'selection') UI.text(option, UI.msg("protocol.controls.current_intervention_set_d6edaa", {}));else {
      const [role, name] = JSON.parse(option.value);
      UI.text(option, UI.join([UI.join([roles[role] || role, ' · ']), name]));
    }
  }
});
