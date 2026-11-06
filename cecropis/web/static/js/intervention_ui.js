"use strict";

/* A fixed event plan belongs to the editor; result sources retain their own plan. */
let interventionPlanMode = false,
  interventionEpoch = 0,
  operationsJob = null,
  operationsEpoch = 0;
const interventionClone = value => JSON.parse(JSON.stringify(value));
function interventionStatus(message, error = false) {
  UI.text($('intervention_status'), message);
  $('intervention_status').classList.toggle('error', error);
}
function interventionTargets(text, type) {
  if (type === 'node_gain') return [...new Set(text.trim().split(/[\s,，]+/).filter(Boolean))];
  const pairs = text.trim().split(/[\n;,；]+/).filter(s => s.trim()).map(s => {
    const p = s.trim().split(/\s*(?:->|→)\s*/);
    if (p.length !== 2 || p.some(v => !/^\d+$/.test(v))) throw UI.error("intervention.controls.connectionstarget_pre_post_c520c0", {});
    return p;
  });
  return [...new Map(pairs.map(p => [p.join('->'), p])).values()];
}
function interventionReadRows() {
  return [...$('intervention_rows').querySelectorAll('tr')].map(row => {
    const value = field => row.querySelector('[data-operation-field="' + field + '"]').value,
      type = value('type');
    return {
      name: value('name').trim(),
      type,
      [type === 'node_gain' ? 'body_ids' : 'edges']: interventionTargets(value('targets'), type),
      start: Number(value('start')),
      stop: Number(value('stop')),
      gain: Number(value('gain')),
      enabled: row.querySelector('[data-operation-field="enabled"]').checked
    };
  });
}
function interventionEventRow(event, index) {
  const edges = event.type === 'edge_gain',
    targets = edges ? (event.edges || []).map(p => p.join(' → ')).join('\n') : (event.body_ids || []).join(', ');
  return `<tr><td><input data-operation-field="enabled" type="checkbox" ${event.enabled !== false ? 'checked' : ''} ${UI.htmlAttribute("aria-label", "intervention.interventionEventRow.message_72c2a7", {
    p0: index + 1
  })}><input data-operation-field="name" value="${esc(event.name)}" ${UI.htmlAttribute("aria-label", "intervention.interventionEventRow.name_a47936", {
    p0: index + 1
  })} style="width:120px"><select data-operation-field="type" ${UI.htmlAttribute("aria-label", "intervention.interventionEventRow.type_d15a03", {
    p0: index + 1
  })}><option value="node_gain" ${edges ? '' : 'selected'} data-i18n="intervention.interventionEventRow.node_activity_gain_e89790">${UI.t("intervention.interventionEventRow.node_activity_gain_e89790")}</option><option value="edge_gain" ${edges ? 'selected' : ''} data-i18n="intervention.interventionEventRow.edge_transmission_gain_24cd33">${UI.t("intervention.interventionEventRow.edge_transmission_gain_24cd33")}</option></select></td><td><details class="member-editor" ${targets ? '' : 'open'}><summary><span data-operation-count>${UI.htmlText(edges ? 'editor.edges' : 'editor.members',{count:UI.numeric(edges ? (event.edges || []).length : (event.body_ids || []).length)})}</span><span class="member-edit-label">${UI.htmlText('editor.editMembers')}</span></summary><textarea data-operation-field="targets" rows="2" ${UI.htmlAttribute("aria-label", "intervention.interventionEventRow.target_cf1cc3", {
    p0: index + 1
  })} style="min-width:190px">${UI.html(targets)}</textarea></details></td><td><input data-operation-field="start" type="number" min="0" value="${event.start}" ${UI.htmlAttribute("aria-label", "intervention.interventionEventRow.start_update_993a3c", {
    p0: index + 1
  })} style="width:75px"><input data-operation-field="stop" type="number" min="1" value="${event.stop}" ${UI.htmlAttribute("aria-label", "intervention.interventionEventRow.stop_5da8c9", {
    p0: index + 1
  })} style="width:75px"></td><td><input data-operation-field="gain" type="number" min="0" max="1" step="any" value="${event.gain}" ${UI.htmlAttribute("aria-label", "intervention.interventionEventRow.retained_gain_925b12", {
    p0: index + 1
  })} style="width:85px"></td><td><label><input type="checkbox" data-operation-a ${index === 0 ? 'checked' : ''}>A</label><label><input type="checkbox" data-operation-b ${index === 1 ? 'checked' : ''}>B</label><button type="button" class="small" data-operation-delete="${index}">${UI.htmlText("intervention.interventionEventRow.remove_6135d4", {})}</button></td></tr>`;
}
function interventionGetEvents(c) {
  if (Array.isArray(c.intervention_events)) return interventionClone(c.intervention_events);
  const ids = c.intervention_ids ?? candidateNodes(c.intervention_group).map(n => String(n.bodyId));
  return ids.length ? [{
    name: UI.t("intervention.interventionGetEvents.nodeintervention_ac8dcd"),
    type: 'node_gain',
    body_ids: ids,
    start: c.intervention_start,
    stop: c.intervention_stop,
    gain: c.gain,
    enabled: true
  }] : [];
}
function interventionNeutral(c, events) {
  return {
    ...c,
    intervention_group: '__event_plan__',
    intervention_ids: [],
    gain: 1,
    intervention_start: 0,
    intervention_stop: c.steps,
    intervention_semantics_version: 1,
    intervention_events: interventionClone(events)
  };
}
function interventionSetPlan(events, edit = false) {
  interventionPlanMode = true;
  $('intervention_plan_mode').value = 'events';
  $('intervention_rows').innerHTML = events.map(interventionEventRow).join('');
  interventionModeVisibility();
  if (edit) interventionEdited();else interventionTimeline();
}
function interventionModeVisibility() {
  const on = interventionPlanMode;
  $('intervention_plan_editor').hidden = !on;
  const headerActions=document.getElementById('intervention_header_actions');
  if (headerActions) headerActions.hidden=!on;
  $('legacy_intervention_controls').hidden = on;
  for (const control of $('legacy_intervention_controls').querySelectorAll('input,select,textarea,button')) control.disabled = on;
  UI.text($('baseline'), on ? UI.msg("intervention.interventionModeVisibility.no_intervention_a00c0e", {}) : UI.msg("intervention.interventionModeVisibility.reset_gain_to_1_74aae2", {}));
}
const interventionCfgBefore = cfg;
cfg = function () {
  const c = interventionCfgBefore();
  return interventionPlanMode ? interventionNeutral(c, interventionReadRows()) : c;
};
const interventionValidateBefore = validateCondition;
validateCondition = function (c) {
  if (!Array.isArray(c?.intervention_events)) {
    if (c?.intervention_events != null || c?.intervention_semantics_version != null) throw UI.error("intervention.controls.intervention_1_ab52c2", {});
    const legacy = {
      ...c
    };
    delete legacy.intervention_events;
    delete legacy.intervention_semantics_version;
    return interventionValidateBefore(legacy);
  }
  if (c.intervention_semantics_version !== 1) throw UI.error("intervention.controls.intervention_1_ea654f", {});
  for (const [field, value] of Object.entries({
    intervention_group: '__event_plan__',
    intervention_ids: [],
    gain: 1,
    intervention_start: 0,
    intervention_stop: c.steps
  })) if (Object.hasOwn(c, field) && JSON.stringify(c[field]) !== JSON.stringify(value)) throw UI.errorValue(UI.join([UI.msg("intervention.controls.intervention_07e076", {}), field]));
  const legacy = {
    ...c,
    intervention_group: '__all__',
    intervention_ids: null,
    gain: 1,
    intervention_start: 0,
    intervention_stop: c.steps
  };
  delete legacy.intervention_events;
  delete legacy.intervention_semantics_version;
  interventionValidateBefore(legacy);
  const members = new Set((overview?.scope_nodes || []).map(n => String(n.bodyId))),
    names = new Set();
  if (c.intervention_events.length > 128) throw UI.error("intervention.controls.intervention_128_656c9a", {});
  for (const [index, e] of c.intervention_events.entries()) {
    if (!e || typeof e !== 'object') throw UI.error("intervention.controls.intervention_cf138e", {});
    const fields = ['name', 'type', 'start', 'stop', 'gain', 'enabled', e.type === 'node_gain' ? 'body_ids' : 'edges'];
    if (!e || Object.keys(e).sort().join('|') !== fields.sort().join('|')) throw UI.errorValue(UI.join([UI.join([UI.msg("intervention.controls.message_0352a9", {}), index + 1]), UI.msg("intervention.controls.message_29f0e4", {})]));
    if (typeof e.name !== 'string' || !e.name.trim() || e.name.length > 80 || names.has(e.name)) throw UI.errorValue(UI.join([UI.join([UI.msg("intervention.controls.message_0352a9", {}), index + 1]), UI.msg("intervention.controls.name_1499ed", {})]));
    names.add(e.name);
    if (!['node_gain', 'edge_gain'].includes(e.type) || typeof e.enabled !== 'boolean') throw UI.error("intervention.controls.type_status_b91e2c", {});
    if (!Number.isInteger(e.start) || !Number.isInteger(e.stop) || !(0 <= e.start && e.start < e.stop && e.stop <= c.steps) || !Number.isFinite(e.gain) || e.gain < 0 || e.gain > 1) throw UI.errorValue(UI.join([e.name, UI.msg("intervention.controls.message_e1382c", {})]));
    const targets = e.type === 'node_gain' ? e.body_ids : e.edges;
    if (!Array.isArray(targets) || !targets.length) throw UI.errorValue(UI.join([e.name, UI.msg("intervention.controls.target_beaec7", {})]));
    const ids = e.type === 'node_gain' ? targets : targets.flatMap(pair => {
      if (!Array.isArray(pair) || pair.length !== 2) throw UI.errorValue(UI.join([e.name, UI.msg("intervention.controls.connections_ef84e5", {})]));
      return pair;
    });
    const missing = [...new Set(ids.filter(id => typeof id !== 'string' || !members.has(id)))];
    if (missing.length) throw UI.errorValue(UI.join([UI.join([e.name, UI.msg("intervention.controls.scope_members_5c2c65", {})]), missing.join(', ')]));
    if (e.type === 'edge_gain' && targets.length > Number($('intervention_edge_limit').value)) throw UI.errorValue(UI.join([e.name, UI.msg("intervention.controls.connectionsselectbudget_9937bd", {})]));
  }
};
const interventionApplyBefore = apply;
apply = function (c) {
  if (Array.isArray(c?.intervention_events)) {
    validateCondition(c);
    interventionPlanMode = false;
    const plain = {
      ...c,
      intervention_group: '__all__',
      intervention_ids: null,
      gain: 1,
      intervention_start: 0,
      intervention_stop: c.steps
    };
    delete plain.intervention_events;
    delete plain.intervention_semantics_version;
    interventionApplyBefore(plain);
    interventionSetPlan(c.intervention_events);
  } else {
    interventionPlanMode = false;
    $('intervention_plan_mode').value = 'legacy';
    $('intervention_rows').replaceChildren();
    interventionModeVisibility();
    interventionApplyBefore(c);
  }
  invalidateInterventionPreview();
};
function invalidateInterventionPreview() {
  interventionEpoch++;
  interventionStatus('');
  UI.text($('intervention_preview_detail'), '');
}
function interventionEdited() {
  changed();
  UI.text($('record_status'), '');
  interventionTimeline();
  document.dispatchEvent(new Event('lab-protocol'));
}
function interventionTimeline() {
  try {
    const events = interventionReadRows(),
      steps = Number($('steps').value),
      W = 800,
      L = 180,
      H = events.length * 28 + 20,
      x = t => L + t / steps * (W - L - 20);
    $('intervention_timeline').innerHTML = events.length ? `<svg class="plot" viewBox="0 0 ${W} ${H}" ${UI.htmlAttribute("aria-label", "intervention.interventionTimeline.interventionupdates_801f2e", {})}>${events.map((e, k) => `<text x="4" y="${k * 28 + 18}" fill="var(--muted)" font-size="12">${UI.html(e.name, true)} · ${UI.html(e.type === 'edge_gain' ? UI.msg("intervention.controls.message_099db3", {}) : UI.msg("intervention.controls.node_2410d8", {}), true)} · ${e.gain}</text><line x1="${x(e.start)}" x2="${x(e.stop)}" y1="${k * 28 + 14}" y2="${k * 28 + 14}" stroke="${e.type === 'edge_gain' ? UI.color('teal') : UI.color('amber')}" stroke-width="7" opacity="${e.enabled ? .9 : .25}"><title>${UI.htmlText("intervention.controls.message_6f2f01", {
      p0: e.start,
      p1: e.stop,
      p2: e.enabled ? UI.msg("intervention.controls.message_f4f0ea", {}) : UI.msg("intervention.controls.message_4e6fd0", {})
    })}</title></line>`).join('')}</svg>` : `<div class="note">${UI.htmlText("intervention.interventionTimeline.empty_plan_no_intervention_4d4e84", {})}</div>`;
  } catch (e) {
    UI.text($('intervention_timeline'), UI.errorText(e));
  }
}
function interventionAdd(type, targets = null, name = null) {
  if (busy) throw UI.error("intervention.interventionAdd.wait_for_the_current_task_to_stop_2a5566", {});
  if (!overview) throw UI.error("intervention.interventionAdd.open_a_calculation_scope_first_59b2f9", {});
  const events = interventionPlanMode ? interventionReadRows() : [];
  if (events.length >= 128) throw UI.error("intervention.interventionAdd.128_2beb52", {});
  let label = name || UI.join([UI.join([type === 'edge_gain' ? UI.msg("intervention.interventionAdd.connections_55c001", {}) : UI.msg("intervention.interventionAdd.node_5625d6", {}), ' ']), UI.join([events.length, 1])]);
  while (events.some(e => e.name === label)) label += ' +';
  events.push({
    name: label,
    type,
    [type === 'node_gain' ? 'body_ids' : 'edges']: targets || [],
    start: 0,
    stop: Math.min(Number($('steps').value), 10),
    gain: .5,
    enabled: true
  });
  interventionSetPlan(events, true);
  $('intervention_editor').open = true;
  $('intervention_editor').scrollIntoView({
    block: 'start'
  });
}
async function interventionSelectEdges(source_ids, target_ids) {
  if (!overview) throw UI.error("intervention.interventionSelectEdges.open_a_calculation_scope_first_scope_members_scope_2f18d2", {});
  const epoch = interventionEpoch,
    generation = caseGeneration,
    result = await api('/api/intervention-edges', {
      source_ids,
      target_ids,
      max_edges: Number($('intervention_edge_limit').value),
      max_bytes: Number($('intervention_memory_limit').value) * 1024 ** 2
    });
  if (epoch !== interventionEpoch || generation !== caseGeneration) throw UI.error("intervention.interventionSelectEdges.select_scope_select_8afb86", {});
  const edges = result.edges.map(e => Array.isArray(e) ? e : [e.pre_id ?? e.body_pre, e.post_id ?? e.body_post]);
  if (!edges.length) throw UI.error("intervention.interventionSelectEdges.target_internal_edges_94b192", {});
  interventionAdd('edge_gain', edges);
  interventionStatus(UI.msg("intervention.interventionSelectEdges.node_connection_count_4a00e6", {
    p0: UI.numeric(edges.length, {}),
    p1: UI.numeric(result.node_count ?? new Set(edges.flat()).size, {}),
    p2: UI.numeric(result.contacts ?? result.contact_count ?? 0, {})
  }));
}
async function interventionPreview() {
  const epoch = interventionEpoch;
  try {
    const experiment = cfg(),
      key = JSON.stringify(experiment);
    validateCondition(experiment);
    interventionStatus(UI.msg("intervention.interventionPreview.target_02cae1", {}));
    const result = await api('/api/intervention-preview', {
      experiment
    });
    if (epoch !== interventionEpoch || key !== JSON.stringify(cfg())) return;
    UI.text($('intervention_preview_detail'), JSON.stringify(result, null, 2));
    interventionStatus(UI.msg("intervention.interventionPreview.node_a7ab70", {
      p0: UI.numeric(result.node_count, {}),
      p1: UI.numeric(result.edge_count, {})
    }));
  } catch (e) {
    if (epoch === interventionEpoch) interventionStatus(UI.errorText(e), true);
  }
}
function operationsSets() {
  const events = interventionReadRows(),
    rows = [...$('intervention_rows').querySelectorAll('tr')],
    a_events = events.filter((e, k) => rows[k].querySelector('[data-operation-a]').checked),
    b_events = events.filter((e, k) => rows[k].querySelector('[data-operation-b]').checked);
  if (!a_events.length || !b_events.length) throw UI.error("intervention.operationsSets.a_b_3cc11e", {});
  return {
    a_events,
    b_events
  };
}
function operationsLock(active) {
  busy = active;
  $('intervention_editor').inert = active;
  $('protocol_panel').inert = active;
  $('experiment').inert = active;
  for (const id of ['run', 'baseline', 'load', 'export', 'compare_conditions', 'operations_compare']) $(id).disabled = active;
  $('operations_cancel').disabled = !active;
  if (active) $('save_comparison').disabled = true;else {
    $('save_comparison').disabled = !canSaveComparison();
    $('save').disabled = !latest || dirty;
  }
}
async function operationsCompare() {
  if (busy || searchRunning) return;
  try {
    const experiment = cfg();
    validateCondition(experiment);
    const sets = operationsSets(),
      task = await api('/api/operations-compare', {
        experiment,
        ...sets,
        ...($('operations_constraints').checked ? {
          search_options: searchOptions()
        } : {})
      });
    operationsJob = task.job_id;
    const epoch = ++operationsEpoch;
    operationsLock(true);
    UI.text($('operations_status'), UI.msg("intervention.operationsCompare.compare_0_a_b_a_b_9eb7de", {}));
    pollOperations(operationsJob, epoch);
  } catch (e) {
    UI.text($('operations_status'), UI.errorText(e));
  }
}
async function pollOperations(job, epoch) {
  try {
    const task = await api('/api/operations-job?' + new URLSearchParams({
      job_id: job
    }));
    if (epoch !== operationsEpoch || job !== operationsJob) return;
    if (task.status === 'running') {
      const p = task.progress || {};
      UI.text($('operations_status'), JSON.stringify(p));
      setTimeout(() => pollOperations(job, epoch), 500);
      return;
    }
    if (task.result) {
      const result = await api('/api/operations-result', {
        job_id: job
      });
      if (epoch !== operationsEpoch) return;
      renderComparison(result);
      const state = result.status || task.status;
      UI.text($('operations_status'), UI.join([UI.join([['complete', 'completed'].includes(state) ? UI.msg("intervention.pollOperations.comparisoncomplete_c991f9", {}) : state === 'cancelled' ? UI.msg("intervention.pollOperations.cancelled_keepcompletecondition_835b4a", {}) : UI.msg("intervention.pollOperations.failed_keepcompletecondition_540eb5", {}), result.execution_counts ? UI.join([UI.join([UI.join([UI.msg("intervention.pollOperations.message_c12d8e", {}), result.execution_counts.physical_completed ?? 0]), ' / ']), result.execution_counts.physical_started ?? 0]) : '']), result.condition_states ? UI.join([' · ', result.condition_states.map(c => c.name + ' ' + ({
        complete: UI.msg("intervention.controls.complete_c0b3fb", {}),
        cancelled: UI.msg("intervention.controls.cancel_2cd0f3", {}),
        failed: UI.msg("intervention.controls.failed_28384d", {}),
        not_run: UI.msg("intervention.controls.run_62cdc8", {})
      }[c.status] || UI.code(c.status))).join(' / ')]) : '']));
    } else UI.text($('operations_status'), task.error ? UI.errorText(Error(task.error)) : UI.code(task.status));
    operationsLock(false);
  } catch (e) {
    if (epoch === operationsEpoch) {
      operationsLock(false);
      UI.text($('operations_status'), UI.errorText(e));
    }
  }
}
function renderOperationInteraction(report) {
  const data = report.interactions;
  if (!data) {
    $('operations_interaction').replaceChildren();
    return;
  }
  const rows = Array.isArray(data) ? data : Object.entries(data).map(([name, value]) => ({
    name,
    ...value
  }));
  $('operations_interaction').innerHTML = `<div>${UI.htmlText("intervention.renderOperationInteraction.non_additive_model_response_r_a_b_r_a_r_b_r_0_783691", {})}</div><div class="tablewrap"><table><thead><tr><th>${UI.htmlText("intervention.renderOperationInteraction.observation_sets_376101", {})}</th><th>${UI.htmlText("intervention.renderOperationInteraction.evaluation_window_a8bc11", {})}</th><th>R(0)</th><th>${UI.htmlText("intervention.renderOperationInteraction.a_absolute_change_af95bd", {})}</th><th>${UI.htmlText("intervention.renderOperationInteraction.b_absolute_change_0d0bf2", {})}</th><th>${UI.htmlText("intervention.renderOperationInteraction.a_b_absolute_change_c79798", {})}</th><th>${UI.htmlText("intervention.renderOperationInteraction.non_additive_difference_f4b59e", {})}</th></tr></thead><tbody>` + rows.map(row => `<tr><td>${UI.html(row.observation ?? row.type ?? row.name)}</td><td>${row.evaluation_window ? '[' + row.evaluation_window.start + ', ' + row.evaluation_window.stop + ')' : '—'}</td><td>${UI.html(contextNumber(row.baseline_sum ?? row.R0 ?? row.r0))}</td><td>${UI.html(contextNumber(row.a_sum_delta ?? row.delta_A ?? row.delta_a))}</td><td>${UI.html(contextNumber(row.b_sum_delta ?? row.delta_B ?? row.delta_b))}</td><td>${UI.html(contextNumber(row.ab_sum_delta ?? row.delta_AB ?? row.delta_ab))}</td><td>${UI.html(contextNumber(row.interaction))}</td></tr>`).join('') + '</tbody></table></div>';
}
const renderComparisonBeforeEvents = renderComparison;
renderComparison = function (report, saved = false, displayOnly = false) {
  renderComparisonBeforeEvents(report, saved, displayOnly);
  renderOperationInteraction(report);
};
const renderConditionsBeforeEvents = renderConditions;
renderConditions = function () {
  renderConditionsBeforeEvents();
  for (const [k, node] of [...$('condition_list').querySelectorAll('details')].entries()) {
    const c = conditions[k].experiment;
    if (Array.isArray(c.intervention_events)) {
      UI.text(node.querySelector('summary').firstChild, UI.join([conditions[k].name + ' · ' + c.intervention_events.length, UI.msg("intervention.controls.intervention_6a13d8", {})]));
      const p = node.querySelector('p');
      if (p) UI.text(p, UI.list(c.intervention_events.map(e => UI.join([e.name, " · ", e.type === 'node_gain' ? UI.join([UI.msg("intervention.controls.node_d0df5c", {}), e.body_ids.length]) : UI.join([UI.msg("intervention.controls.message_d32ec4", {}), e.edges.length]), " · gain ", e.gain, " · [", e.start, ", ", e.stop, ") · ", e.enabled ? UI.msg("intervention.controls.message_f4f0ea", {}) : UI.msg("intervention.controls.message_4e6fd0", {})])), '\n'));
    }
  }
};
const refreshSelectionBeforeEvents = refreshSelection;
refreshSelection = function () {
  refreshSelectionBeforeEvents();
  if (interventionPlanMode && overview) {
    const events = interventionReadRows().filter(e => e.enabled);
    UI.text($('selection_size'), UI.msg("intervention.controls.interventionnode_intervention_6c988d", {
      p0: UI.numeric(overview.manifest.node_count, {}),
      p1: UI.numeric(new Set(events.filter(e => e.type === 'node_gain').flatMap(e => e.body_ids)).size, {}),
      p2: UI.numeric(new Set(events.filter(e => e.type === 'edge_gain').flatMap(e => e.edges.map(p => p.join('->')))).size, {}),
      p3: events.length
    }));
  }
};
const baselineBeforeEvents = $('baseline').onclick;
$('baseline').onclick = () => {
  if (interventionPlanMode) {
    if (busy) return;
    interventionSetPlan([], true);
  } else baselineBeforeEvents();
};
$('intervention_plan_mode').onchange = () => {
  try {
    const next = $('intervention_plan_mode').value === 'events';
    if (next) interventionSetPlan(interventionGetEvents(interventionCfgBefore()), true);else {
      const events = interventionReadRows();
      if (events.length > 1 || events.some(e => e.type !== 'node_gain')) throw UI.error("intervention.controls.nodeactions_remove_7c7eff", {});
      interventionPlanMode = false;
      interventionModeVisibility();
      const e = events[0];
      if (e) apply({
        ...interventionCfgBefore(),
        intervention_group: '__all__',
        intervention_ids: e.body_ids,
        gain: e.enabled ? e.gain : 1,
        intervention_start: e.start,
        intervention_stop: e.stop
      });else {
        $('selection_mode').value = 'none';
        changed();
      }
      interventionEdited();
    }
  } catch (e) {
    $('intervention_plan_mode').value = interventionPlanMode ? 'events' : 'legacy';
    interventionStatus(UI.errorText(e), true);
  }
};
$('intervention_rows').addEventListener('input', () => {
  try {
    interventionEdited();
  } catch (e) {
    interventionStatus(UI.errorText(e), true);
  }
});
$('intervention_rows').addEventListener('click', event => {
  const button = event.target.closest('[data-operation-delete]');
  if (!button || busy) return;
  const events = interventionReadRows();
  events.splice(Number(button.dataset.operationDelete), 1);
  interventionSetPlan(events, true);
});
for (const [id, type] of [['intervention_add_node', 'node_gain'], ['intervention_add_edge', 'edge_gain']]) $(id).onclick = () => {
  try {
    interventionAdd(type);
  } catch (e) {
    interventionStatus(UI.errorText(e), true);
  }
};
$('intervention_from_selection').onclick = () => {
  try {
    const ids = window.analysisSelection?.ids() || [];
    if (!ids.length) throw UI.error("intervention.controls.analysis_selectnode_7e73db", {});
    interventionAdd('node_gain', ids, UI.msg("intervention.controls.node_123f0a", {}));
  } catch (e) {
    interventionStatus(UI.errorText(e), true);
  }
};
$('intervention_from_replay_edge').onclick = () => {
  try {
    const edge = replayResult?.edges.find(e => e.edge_id === replaySelectedEdge);
    if (!edge) throw UI.error("intervention.controls.replay_cea817", {});
    interventionAdd('edge_gain', [[edge.pre_id, edge.post_id]], UI.msg("intervention.controls.replay_2d2193", {}));
  } catch (e) {
    interventionStatus(UI.errorText(e), true);
  }
};
$('intervention_from_path').onclick = () => {
  try {
    if (!pathwayResult?.edges.length) throw UI.error("intervention.controls.openpaths_4d7003", {});
    const edges = pathwayResult.edges.map(e => [e.body_pre, e.body_post]);
    interventionAdd('edge_gain', edges, UI.msg("intervention.controls.paths_daaf4f", {}));
    interventionStatus(UI.msg("intervention.controls.paths_paths_fca241", {
      p0: edges.length,
      p1: pathwayResult.edge_count
    }));
  } catch (e) {
    interventionStatus(UI.errorText(e), true);
  }
};
$('intervention_between').onclick = async () => {
  try {
    await interventionSelectEdges(parseBodyIds($('intervention_pre_ids').value), parseBodyIds($('intervention_post_ids').value));
  } catch (e) {
    interventionStatus(UI.errorText(e), true);
  }
};
$('intervention_group_edges').onclick = async () => {
  try {
    if (!groupReport || !overview) throw UI.error("intervention.controls.open_scope_f4819d", {});
    const pair = groupPairIds(),
      epoch = interventionEpoch,
      generation = groupGeneration;
    const [a, b] = await Promise.all([api('/api/group-members', {
      report_id: pair.report_id,
      group_ids: [pair.a]
    }), api('/api/group-members', {
      report_id: pair.report_id,
      group_ids: [pair.b]
    })]);
    if (epoch !== interventionEpoch || generation !== groupGeneration) throw UI.error("intervention.controls.select_2c0f1b", {});
    await interventionSelectEdges(a.body_ids, b.body_ids);
  } catch (e) {
    interventionStatus(UI.errorText(e), true);
  }
};
$('intervention_preview').onclick = interventionPreview;
$('operations_compare').onclick = operationsCompare;
$('operations_cancel').onclick = async () => {
  try {
    if (operationsJob) await api('/api/operations-cancel', {
      job_id: operationsJob
    });
    UI.text($('operations_status'), UI.msg("intervention.controls.cancel_0a8b91", {}));
  } catch (e) {
    UI.text($('operations_status'), UI.errorText(e));
  }
};
document.addEventListener('click', event => {
  const button = event.target.closest('[data-operation-edge]');
  if (button) try {
    interventionAdd('edge_gain', [JSON.parse(button.dataset.operationEdge)], UI.msg("intervention.controls.message_5eb3e5", {}));
  } catch (e) {
    interventionStatus(UI.errorText(e), true);
  }
});
document.addEventListener('lab-case', () => {
  interventionEpoch++;
  operationsEpoch++;
  operationsJob = null;
  interventionStatus('');
  UI.text($('intervention_preview_detail'), '');
  $('operations_interaction').replaceChildren();
});
window.interventionUI = {
  setPlan: events => interventionSetPlan(events, true),
  events: interventionReadRows,
  addNodes: ids => interventionAdd('node_gain', ids),
  addEdges: edges => interventionAdd('edge_gain', edges),
  selectEdges: interventionSelectEdges,
  preview: interventionPreview,
  compare: operationsCompare,
  read: cfg
};

document.getElementById('intervention_rows').addEventListener('input', event => {
  if (event.target.dataset.operationField !== 'targets') return;
  const row=event.target.closest('tr'), type=row.querySelector('[data-operation-field="type"]').value;
  try {
    const members=interventionTargets(event.target.value,type);
    UI.text(row.querySelector('[data-operation-count]'),UI.msg(type==='edge_gain'?'editor.edges':'editor.members',{count:UI.numeric(members.length)}));
    event.target.removeAttribute('aria-invalid');
  } catch (error) {
    event.target.setAttribute('aria-invalid','true');
    interventionStatus(UI.errorText(error),true);
  }
});
