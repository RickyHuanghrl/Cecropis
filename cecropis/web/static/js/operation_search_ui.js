"use strict";

/* Frozen finite operations are distinct from the editable experiment and report. */
let operationLibrary = [],
  operationReport = null,
  operationReportRef = null,
  operationSelected = null,
  operationPreview = null,
  operationPreviewKey = null,
  operationJob = null,
  operationSequence = 0;
const operationClone = v => JSON.parse(JSON.stringify(v));
const operationMarkup = `<details id="operation_search_area"><summary>${UI.htmlText("operation.search.labels.candidate_operation_search_51ad3b", {})}</summary>
<div class="buttons"><button id="operation_import">${UI.htmlText("operation.search.labels.add_editor_events_to_candidates_663097", {})}</button><button id="operation_update">${UI.htmlText("operation.search.labels.update_selected_candidate_from_editor_592d12", {})}</button><button id="operation_restore">${UI.htmlText("operation.search.labels.use_saved_report_definition_e5c521", {})}</button></div>
<div class="tablewrap"><table><thead><tr><th>${UI.htmlText("operation.search.labels.id_name_aa5e31", {})}</th><th>${UI.htmlText("operation.search.labels.operation_size_interval_gain_2baae1", {})}</th><th>${UI.htmlText("operation.search.labels.exclusive_group_edfbfc", {})}</th><th>${UI.htmlText("operation.search.labels.actions_ed31fb", {})}</th></tr></thead><tbody id="operation_library"></tbody></table></div>
<label>${UI.htmlText("operation.search.labels.task_name_247956", {})}<input id="operation_name" placeholder="${UI.t('default.operationName')}" data-i18n-placeholder="default.operationName" maxlength="80"></label><div id="operation_protocols"></div>
<div class="buttons"><button id="operation_requirements">${UI.htmlText("operation.search.labels.set_target_and_protection_6db144", {})}</button><span id="operation_requirements_info"></span></div>
<div class="pair"><label>${UI.htmlText("operation.search.labels.maximum_operations_c9364c", {})}<input id="operation_max_operations" type="number" value="3" min="0" max="32"></label><label>${UI.htmlText("operation.search.labels.direct_node_intervention_limit_dd58b7", {})}<input id="operation_max_nodes" type="number" value="20" min="0" max="200"></label><label>${UI.htmlText("operation.search.labels.directed_edge_limit_446444", {})}<input id="operation_max_edges" type="number" value="100" min="0" max="100000"></label><label>${UI.htmlText("operation.search.labels.combination_evaluation_budget_a8d57b", {})}<input id="operation_max_evaluations" type="number" value="20" min="1" max="10000"></label><label>${UI.htmlText("operation.search.labels.beam_width_8ca4bd", {})}<input id="operation_beam_width" type="number" value="3" min="1" max="64"></label></div>
<div class="buttons"><button id="operation_preview">${UI.htmlText("operation.search.labels.check_request_3b5e10", {})}</button><button id="operation_start" disabled>${UI.htmlText("operation.search.labels.search_44ce7a", {})}</button><button id="operation_cancel" disabled>${UI.htmlText("operation.search.labels.cancel_2cd0f3", {})}</button><button id="operation_save" disabled>${UI.htmlText("operation.search.labels.save_report_6d8b82", {})}</button></div><div id="operation_status" role="status"></div><div id="operation_preview_info"></div>
<div id="operation_report_context"></div><div class="tablewrap"><table><thead><tr><th>${UI.htmlText("operation.search.labels.combination_ce3df9", {})}</th><th>${UI.htmlText("operation.search.labels.operations_nodes_edges_b7e026", {})}</th><th>${UI.htmlText("operation.search.labels.worst_target_effect_2b51f8", {})}</th><th>${UI.htmlText("operation.search.labels.status_constraints_3652e2", {})}</th><th>${UI.htmlText("operation.search.labels.search_retention_reason_2bde95", {})}</th><th>${UI.htmlText("operation.search.labels.select_c11330", {})}</th></tr></thead><tbody id="operation_results"></tbody></table></div><div class="buttons"><button id="operation_prev">${UI.htmlText("operation.search.labels.previous_page_c9b9ae", {})}</button><span id="operation_page"></span><button id="operation_next">${UI.htmlText("operation.search.labels.next_page_8a8542", {})}</button></div><details><summary>${UI.htmlText("operation.search.labels.unrun_combinations_and_coverage_c04b4b", {})}</summary><pre id="operation_unrun" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre></details>
<div id="operation_selected"></div><div id="operation_extras"></div><div class="buttons"><button id="operation_curves" disabled>${UI.htmlText("operation.search.labels.compute_selected_plan_curves_4b7d00", {})}</button><button id="operation_overlap" disabled>${UI.htmlText("operation.search.labels.inspect_selected_plan_coverage_522fb7", {})}</button><button id="operation_adopt" disabled>${UI.htmlText("operation.search.labels.use_as_event_draft_aedf65", {})}</button></div><div id="operation_curve_status" role="status"></div></details>`;
$('intervention_editor').insertAdjacentHTML('beforeend', operationMarkup);
function operationStatus(msg) {
  UI.text($('operation_status'), msg);
}
const operationCurrentProtocolName = UI.t('operation.search.operationProtocolChoices.current_protocol_7bc8cb');
function operationProtocolChoices() {
  const list = [{
    name: operationCurrentProtocolName,
    experiment: cfg()
  }, ...conditions.filter(c => c.name !== operationCurrentProtocolName)];
  return list;
}
function operationRefreshProtocols() {
  try {
    const list = operationProtocolChoices();
    $('operation_protocols').innerHTML = `<div>${UI.htmlText("operation.search.operationRefreshProtocols.decision_protocols_48e70c", {})}</div>` + list.map((c, k) => `<label class="pill"><input type="checkbox" data-operation-protocol="${k}" ${k === 0 ? 'checked' : ''}>${UI.html(k === 0 ? UI.msg("operation.search.operationProtocolChoices.current_protocol_7bc8cb") : c.name)}</label>`).join('');
  } catch (_) {
    UI.text($('operation_protocols'), UI.msg("operation.search.operationRefreshProtocols.open_a_calculation_scope_first_59b2f9", {}));
  }
}
function operationRequirements() {
  const s = searchOptions();
  return {
    target_output: s.target_output,
    target_metric: s.target_metric,
    min_target_loss: s.min_target_loss,
    protected_limits: s.protected_limits ?? {}
  };
}
function operationReadLibrary() {
  return operationLibrary.map((c, k) => ({
    ...operationClone(c),
    id: $('operation_library').children[k].querySelector('[data-candidate-id]').value.trim(),
    name: $('operation_library').children[k].querySelector('[data-candidate-name]').value.trim(),
    exclusive_group: $('operation_library').children[k].querySelector('[data-candidate-exclusive]').value.trim() || null
  }));
}
function operationRenderLibrary() {
  operationPreview = null;
  operationPreviewKey = null;
  $('operation_start').disabled = true;
  $('operation_library').innerHTML = operationLibrary.map((c, k) => `<tr><td><input ${UI.htmlAttribute("aria-label", "operation.search.controls.candidate_id_5daa12", {
    p0: k + 1
  })} data-candidate-id value="${esc(c.id)}" style="width:100px"><input ${UI.htmlAttribute("aria-label", "operation.search.controls.candidate_name_6091f3", {
    p0: k + 1
  })} data-candidate-name value="${esc(c.name)}" style="width:160px"></td><td>${UI.html(c.event.type === 'node_gain' ? UI.join([UI.msg("operation.search.controls.node_d0df5c", {}), c.event.body_ids.length]) : UI.join([UI.msg("operation.search.controls.message_d32ec4", {}), c.event.edges.length]))} · [${c.event.start},${c.event.stop}) · ${c.event.gain}</td><td><input ${UI.htmlAttribute("aria-label", "operation.search.controls.candidate_exclusive_group_d9e227", {
    p0: k + 1
  })} data-candidate-exclusive value="${esc(c.exclusive_group || '')}" style="width:120px"></td><td><button data-candidate-edit="${k}">${UI.htmlText("operation.search.controls.edit_in_event_editor_33a049", {})}</button><button data-candidate-remove="${k}">${UI.htmlText("operation.search.controls.remove_2f9daa", {})}</button></td></tr>`).join('');
}
let operationEditing = null,
  operationPage = 0;
const operationInputLocks = new Map();
function operationDefinition() {
  const list = operationProtocolChoices(),
    selected = [...$('operation_protocols').querySelectorAll('input:checked')].map(el => list[Number(el.dataset.operationProtocol)]);
  if (!selected.length) throw UI.error("operation.search.operationDefinition.select_decision_protocols_f308dc", {});
  return {
    name: $('operation_name').value.trim() || UI.t('default.operationName'),
    conditions: operationClone(selected),
    candidates: operationReadLibrary(),
    requirements: operationRequirements(),
    settings: Object.fromEntries(['max_operations', 'max_nodes', 'max_edges', 'max_evaluations', 'beam_width'].map(k => [k, Number($('operation_' + k).value)]))
  };
}
function operationChanged() {
  operationPreview = null;
  operationPreviewKey = null;
  $('operation_start').disabled = true;
  if (operationReport) operationStatus(UI.msg("operation.search.operationChanged.message_2a5c46", {}));
}
function operationReportPayload() {
  if (!operationReportRef) throw UI.error("operation.search.operationReportPayload.completesearch_opensave_report_72087e", {});
  return operationReportRef;
}
function operationLock(on) {
  operationsLock(on);
  for (const el of $('operation_search_area').querySelectorAll('input,select,textarea')) {
    if (on) {
      operationInputLocks.set(el, el.disabled);
      el.disabled = true;
    } else if (operationInputLocks.has(el)) {
      el.disabled = operationInputLocks.get(el);
      operationInputLocks.delete(el);
    }
  }
  $('operation_start').disabled = on || !operationPreview;
  $('operation_cancel').disabled = !on;
  for (const id of ['operation_import', 'operation_update', 'operation_restore', 'operation_preview', 'operation_curves', 'operation_adopt', 'operation_overlap', 'operation_save']) $(id).disabled = on; /* Cancellation remains outside inert editor. */
  $('intervention_editor').inert = false;
  $('intervention_plan_editor').inert = on;
  for (const id of ['operation_library', 'operation_protocols', 'operation_extras']) $(id).inert = on;
  if (!on) {
    $('operation_save').disabled = !operationReport;
    $('operation_curves').disabled = operationSelected?.status !== 'completed';
    $('operation_adopt').disabled = operationSelected?.status !== 'completed';
    $('operation_overlap').disabled = operationSelected?.status !== 'completed';
  }
}
async function operationPoll(id, seq, curves = false) {
  try {
    const task = await api('/api/operation-search-job?' + new URLSearchParams({
      job_id: id
    }));
    if (seq !== operationSequence) return;
    if (task.status === 'running') {
      operationStatus(UI.msg("operation.search.operationPoll.combination_completeintervention_014f46", {
        p0: curves ? UI.msg("operation.search.operationPoll.message_cde4d5", {}) : UI.msg("operation.search.operationPoll.search_44ce7a", {}),
        p1: task.progress?.evaluations ?? 0,
        p2: task.progress?.condition || '—',
        p3: task.progress?.intervention_completed ?? 0
      }));
      setTimeout(() => operationPoll(id, seq, curves), 500);
      return;
    }
    if (task.result) {
      const result = await api('/api/operation-search-result', {
        job_id: id
      });
      if (seq !== operationSequence) return;
      if (curves) {
        renderComparison(result);
        UI.text($('operation_curve_status'), UI.msg('operation.report.curves', {state: operationState(result.status)}));
      } else {
        operationReportRef = {
          report_id: result.report_id
        };
        operationPage = 0;
        operationRenderReport(result);
      }
    } else operationStatus(task.error ? UI.errorText(Error(task.error)) : UI.code(task.status));
    operationLock(false);
  } catch (e) {
    if (seq === operationSequence) {
      operationLock(false);
      operationStatus(UI.errorText(e));
    }
  }
}
function operationState(s) {
  return {
    paused: UI.msg("operation.search.operationState.paused_eb0c32", {}),
    pause_requested: UI.msg("operation.search.operationState.pause_requested_3e246f", {}),
    interrupted: UI.msg("operation.search.operationState.interrupted_88cf2d", {}),
    running: UI.msg("operation.search.operationState.running_1f0eb9", {}),
    completed: UI.msg("operation.search.operationState.complete_c0b3fb", {}),
    complete: UI.msg("operation.search.operationState.complete_c0b3fb", {}),
    budget_exhausted: UI.msg("operation.search.operationState.budget_exhausted_d9e9de", {}),
    evaluation_budget_reached: UI.msg("operation.search.operationState.combination_evaluation_budget_13e1d8", {}),
    bounded_layers_completed: UI.msg("operation.search.operationState.complete_99eb38", {}),
    no_intervention_needed: UI.msg("operation.search.operationState.no_intervention_satisfied_e3a627", {}),
    no_effective_candidates: UI.msg("operation.search.operationState.message_c81472", {}),
    cancelled: UI.msg("operation.search.operationState.cancel_2cd0f3", {}),
    failed: UI.msg("operation.search.operationState.failed_28384d", {}),
    execution_failed: UI.msg("operation.search.operationState.failed_934459", {}),
    evaluated: UI.msg("operation.search.operationState.message_df49f2", {}),
    retained_for_next_layer: UI.msg("operation.search.operationState.message_60f374", {}),
    beam_width: UI.msg("operation.search.operationState.beam_width_683d20", {}),
    incomplete: UI.msg("operation.search.operationState.complete_6707de", {}),
    not_ranked: UI.msg("operation.search.operationState.sort_6407a6", {}),
    empty_plan_satisfies_constraints: UI.msg("operation.search.operationState.satisfiedconstraints_326996", {})
  }[s] || UI.code(s);
}
function operationLoss(value, metric) {
  return value == null ? UI.msg("operation.search.operationLoss.definition_2ba10d", {}) : metric === 'relative' ? (value * 100).toFixed(3) + '%' : contextNumber(value);
}
function operationSelect(index) {
  const row = operationReport.entries[index];
  operationSelected = row;
  const req = operationReport.definition.requirements;
  const events = UI.list(row.events.map(e => UI.join([e.name, " · ", e.type === 'node_gain' ? UI.join([UI.msg("operation.search.controls.node_d0df5c", {}), e.body_ids.join(', ')]) : UI.join([UI.msg("operation.search.controls.message_d32ec4", {}), e.edges.map(p => p.join(' → ')).join(', ')]), " · [", e.start, ",", e.stop, ") · ", e.gain])), '\n');
  $('operation_selected').replaceChildren();
  const heading = document.createElement('pre');
  heading.style.whiteSpace = 'pre-wrap';
  UI.text(heading, UI.join([UI.join([row.candidate_ids.join(' + ') || UI.msg("operation.search.operationSelect.message_780f6a", {}), '\n']), events]));
  $('operation_selected').append(heading);
  $('operation_selected').insertAdjacentHTML('beforeend', `<div class="tablewrap"><table><thead><tr><th>${UI.htmlText("operation.search.operationSelect.decision_protocols_48e70c", {})}</th><th>${UI.htmlText("operation.search.operationSelect.target_effect_requirement_a5a5ec", {})}</th><th>${UI.htmlText("operation.search.operationSelect.protection_loss_limit_b9d483", {})}</th><th>${UI.htmlText("operation.search.operationSelect.failed_constraints_9a9b7b", {})}</th></tr></thead><tbody>` + row.condition_results.map(c => `<tr><td>${UI.html(c.name)}</td><td>${UI.html(operationLoss(c.target_loss, req.target_metric))} / ${UI.html(operationLoss(req.min_target_loss, req.target_metric))}</td><td>${Object.entries(c.protected_constraints).map(([n, s]) => esc(n) + ': ' + operationLoss(s.loss, s.metric) + ' / ' + operationLoss(s.limit, s.metric)).join('<br>')}</td><td>${UI.html(c.violations.join(', ') || '—')}</td></tr>`).join('') + '</tbody></table></div>');
  $('operation_curves').disabled = row.status !== 'completed';
  $('operation_adopt').disabled = row.status !== 'completed';
  $('operation_overlap').disabled = row.status !== 'completed';
  $('operation_selected').insertAdjacentHTML('beforeend', `<div class="tablewrap"><table><thead><tr><th>${UI.htmlText("operation.search.operationSelect.protocol_observation_d42d8a", {})}</th><th>${UI.htmlText("operation.search.operationSelect.baseline_mean_a882a3", {})}</th><th>${UI.htmlText("operation.search.operationSelect.intervention_mean_ed07c3", {})}</th><th>${UI.htmlText("operation.search.operationSelect.absolute_mean_change_ddee3c", {})}</th><th>${UI.htmlText("operation.search.operationSelect.relative_change_d26b48", {})}</th></tr></thead><tbody>` + row.condition_results.flatMap(c => Object.entries(c.output_metrics).map(([name, m]) => `<tr><td>${UI.html(c.name)} / ${UI.html(name)}</td><td>${UI.html(contextNumber(m.baseline_mean))}</td><td>${UI.html(contextNumber(m.intervention_mean))}</td><td>${UI.html(contextNumber(m.mean_delta))}</td><td>${UI.html(operationLoss(m.relative_sum_delta, 'relative'))}</td></tr>`)).join('') + '</tbody></table></div>');
  $('operation_extras').innerHTML = `<div>${UI.htmlText("operation.search.operationSelect.extra_evaluation_only_excluded_from_search_ranking_5cfb97", {})}</div>` + conditions.filter(c => !operationReport.definition.conditions.some(t => t.name === c.name)).map(c => `<label class="pill"><input type="checkbox" data-operation-extra="${esc(c.name)}">${UI.html(c.name)}</label>`).join('');
}
function operationRenderReport(report) {
  operationReport = report;
  UI.text($('operation_report_context'), UI.msg('operation.report.context', {
    name: report.definition.name,
    scope: report.data_scope?.case_name || report.case_id,
    nodes: report.computation_node_count ?? UI.msg('operation.search.operationRenderReport.not_recorded_7450cc'),
    protocols: report.definition.conditions.map(c => c.name).join(' / ')
  }));
  const req = report.definition.requirements;
  $('operation_results').innerHTML = report.entries.slice(operationPage * 50, (operationPage + 1) * 50).map((e, offset) => {
    const k = operationPage * 50 + offset;
    return `<tr><td>${UI.html(e.candidate_ids.join(' + ') || UI.msg("operation.search.controls.message_780f6a", {}))}${UI.html(JSON.stringify(e.candidate_ids) === JSON.stringify(report.recommended_candidate_ids) ? UI.msg("operation.search.controls.message_37e1ec", {}) : '')}</td><td>${e.coverage.operation_count} / ${e.coverage.node_count} / ${e.coverage.edge_count}</td><td>${UI.html(operationLoss(e.worst_target_loss, req.target_metric))}</td><td>${UI.html(operationState(e.status))} · ${UI.html(e.feasible === null ? UI.msg("operation.search.controls.complete_6707de", {}) : e.feasible ? UI.msg("operation.search.controls.satisfied_4e8156", {}) : UI.msg("operation.search.controls.satisfied_ec9205", {}))}</td><td>${UI.html(operationState(e.retention_reason))}</td><td><button data-operation-result="${k}">${UI.htmlText("operation.search.controls.view_db8db0", {})}</button></td></tr>`;
  }).join('');
  UI.text($('operation_page'), UI.msg("operation.search.operationRenderReport.showing_of_21a5ae", {
    p0: report.entries.length ? operationPage * 50 + 1 : 0,
    p1: Math.min((operationPage + 1) * 50, report.entries.length),
    p2: report.entries.length
  }));
  $('operation_prev').disabled = operationPage === 0;
  $('operation_next').disabled = (operationPage + 1) * 50 >= report.entries.length;
  const combinations = ids => ids.length ? ids.map(row => row.length ? row.join(' + ') : UI.msg('operation.search.controls.message_780f6a')) : [UI.msg('operation.report.none')];
  const unrun = [];
  if (report.pending_layer && report.status !== 'budget_exhausted') {
    const layer = report.pending_layer;
    unrun.push(UI.msg('operation.report.pending', {
      depth: layer.depth, evaluated: layer.position, count: layer.pending.length,
      ids: UI.list(combinations(layer.pending), '; ')
    }));
  }
  for (const layer of report.layers || []) unrun.push(UI.msg('operation.report.unrun', {
    depth: layer.depth, count: layer.not_run.length,
    ids: UI.list(combinations(layer.not_run), '; ')
  }));
  if (!unrun.length) unrun.push(UI.msg('operation.report.noUnrun'));
  unrun.push(UI.msg('operation.search.operationRenderReport.keep_1c8b6c'));
  UI.text($('operation_unrun'), UI.list(unrun, '\n'));
  operationStatus(UI.msg("operation.search.operationRenderReport.baseline_intervention_b0c926", {
    p0: operationState(report.status),
    p1: report.termination_reason ? operationState(report.termination_reason) : UI.msg('operation.search.operationRenderReport.not_recorded_7450cc'),
    p2: report.evaluations,
    p3: report.definition.settings.max_evaluations,
    p4: (report.covered_candidate_ids || []).length,
    p5: report.candidate_count,
    p6: report.baseline_completed,
    p7: report.baseline_started,
    p8: report.intervention_completed,
    p9: report.intervention_started,
    p10: report.physical_completed ?? 0,
    p11: report.physical_started ?? 0,
    p12: report.combination_duplicates ?? 0,
    p13: (report.uncovered_candidate_ids || []).join(', ') || UI.msg('operation.report.none')
  }));
  $('operation_save').disabled = false;
  const k = report.entries.findIndex(e => JSON.stringify(e.candidate_ids) === JSON.stringify(report.recommended_candidate_ids));
  if (k >= 0) operationSelect(k);
}
function openOperationSearch(saved) {
  operationSequence++;
  operationReportRef = {
    artifact_id: saved.artifact_id
  };
  operationPage = 0;
  operationRenderReport(saved.result);
  $('intervention_editor').open = true;
  $('operation_search_area').open = true;
  $('operation_search_area').scrollIntoView({
    block: 'start'
  });
}
$('operation_library').onclick = e => {
  try {
    if (busy) return;
    const edit = e.target.dataset.candidateEdit,
      remove = e.target.dataset.candidateRemove;
    operationLibrary = operationReadLibrary();
    if (edit !== undefined) {
      operationEditing = Number(edit);
      window.interventionUI.setPlan([operationClone(operationLibrary[operationEditing].event)]);
      operationStatus(UI.msg("operation.search.controls.edit_update_selected_candidate_from_editor_33e4ba", {}));
    }
    if (remove !== undefined) {
      operationLibrary.splice(Number(remove), 1);
      operationEditing = null;
      operationRenderLibrary();
    }
  } catch (err) {
    operationStatus(UI.errorText(err));
  }
};
$('operation_import').onclick = () => {
  try {
    operationLibrary = operationReadLibrary();
    const events = window.interventionUI.events();
    for (const event of events) {
      let id = 'op' + (operationLibrary.length + 1);
      while (operationLibrary.some(c => c.id === id)) id += 'x';
      operationLibrary.push({
        id,
        name: event.name,
        event: operationClone(event),
        exclusive_group: null
      });
    }
    operationRenderLibrary();
    operationStatus(UI.msg("operation.search.controls.edit_check_request_216d67", {}));
  } catch (e) {
    operationStatus(UI.errorText(e));
  }
};
$('operation_update').onclick = () => {
  try {
    if (operationEditing === null) throw UI.error("operation.search.controls.select_edit_86bc09", {});
    const events = window.interventionUI.events();
    if (events.length !== 1) throw UI.error("operation.search.controls.edit_79a4ac", {});
    operationLibrary = operationReadLibrary();
    operationLibrary[operationEditing].event = operationClone(events[0]);
    operationLibrary[operationEditing].name = events[0].name;
    operationEditing = null;
    operationRenderLibrary();
  } catch (e) {
    operationStatus(UI.errorText(e));
  }
};
$('operation_requirements').onclick = () => {
  workspaceShell.openSearchTool('search_panel');
};
$('operation_preview').onclick = async () => {
  try {
    const d = operationDefinition(),
      key = JSON.stringify(d),
      seq = ++operationSequence;
    const p = await api('/api/operation-search-preview', {
      definition: d
    });
    if (seq !== operationSequence || key !== JSON.stringify(operationDefinition())) return;
    operationPreview = p;
    operationPreviewKey = key;
    UI.text($('operation_preview_info'), UI.msg("operation.search.controls.node_maximum_propagations_edede0", {
      p0: p.candidate_count,
      p1: p.coverage.node_count,
      p2: p.coverage.edge_count,
      p3: p.coverage.edge_endpoint_ids.length,
      p4: p.condition_count,
      p5: p.estimated_propagations_upper_bound,
      p6: p.excluded_candidates.map(c => UI.join([c.id, ': ', UI.code(c.reason)])).join(', ') || '—',
      p7: JSON.stringify(p.exclusive_groups)
    }));
    UI.text($('operation_requirements_info'), UI.join([UI.join([UI.join([UI.join([UI.join([UI.msg("operation.search.controls.target_536d56", {}), d.requirements.target_output]), ' ≥ ']), operationLoss(d.requirements.min_target_loss, d.requirements.target_metric)]), UI.msg("operation.search.controls.protection_7ba7bc", {})]), Object.entries(d.requirements.protected_limits).map(([n, s]) => n + ' ≤ ' + operationLoss(s.max_loss, s.metric)).join(' / ')]));
    $('operation_start').disabled = false;
    operationStatus(UI.msg("operation.search.controls.check_requestcomplete_actions_c93820", {}));
  } catch (e) {
    operationStatus(UI.errorText(e));
  }
};
$('operation_start').onclick = async () => {
  try {
    if (busy) return;
    const d = operationDefinition();
    if (!operationPreview || JSON.stringify(d) !== operationPreviewKey) throw UI.error("operation.search.controls.definition_changed_check_it_again_166dcb", {});
    const task = await api('/api/operation-search-start', {
      definition: d
    });
    operationJob = task.job_id;
    operationLock(true);
    operationPoll(operationJob, ++operationSequence);
  } catch (e) {
    operationStatus(UI.errorText(e));
  }
};
$('operation_cancel').onclick = async () => {
  try {
    if (operationJob) await api('/api/operation-search-cancel', {
      job_id: operationJob
    });
  } catch (e) {
    operationStatus(UI.errorText(e));
  }
};
$('operation_results').onclick = e => {
  if (e.target.dataset.operationResult !== undefined) operationSelect(Number(e.target.dataset.operationResult));
};
$('operation_save').onclick = async () => {
  try {
    const r = await api('/api/operation-search-save', operationReportPayload());
    operationReportRef = {
      artifact_id: r.artifact_id
    };
    operationStatus(UI.join([UI.msg("operation.search.controls.save_c2e69b", {}), r.folder]));
    refreshSaved();
  } catch (e) {
    operationStatus(UI.errorText(e));
  }
};
$('operation_curves').onclick = async () => {
  try {
    if (busy || operationSelected?.status !== 'completed') return;
    const names = [...$('operation_extras').querySelectorAll('input:checked')].map(c => c.dataset.operationExtra),
      extra_conditions = conditions.filter(c => names.includes(c.name));
    const task = await api('/api/operation-search-curves', {
      ...operationReportPayload(),
      candidate_ids: operationSelected.candidate_ids,
      extra_conditions
    });
    operationJob = task.job_id;
    operationLock(true);
    operationPoll(operationJob, ++operationSequence, true);
  } catch (e) {
    operationStatus(UI.errorText(e));
  }
};
$('operation_adopt').onclick = () => {
  if (operationSelected?.status === 'completed') {
    window.interventionUI.setPlan(operationSelected.events);
    operationStatus(UI.msg("operation.search.controls.message_574f9b", {}));
  }
};
$('operation_restore').onclick = () => {
  if (!operationReport) return;
  const d = operationReport.definition;
  operationLibrary = operationClone(d.candidates);
  operationRenderLibrary();
  $('operation_name').value = d.name;
  for (const [k, v] of Object.entries(d.settings)) $('operation_' + k).value = v;
  apply(d.conditions[0].experiment);
  conditions = operationClone(d.conditions);
  renderConditions();
  operationRefreshProtocols();
  for (const c of $('operation_protocols').querySelectorAll('input')) c.checked = Number(c.dataset.operationProtocol) > 0;
  $('search_target').value = d.requirements.target_output;
  $('search_metric').value = d.requirements.target_metric;
  $('search_min').value = d.requirements.min_target_loss; /* Protection editor is updated by its existing renderer. */
  if (typeof applySearchOptions === 'function') applySearchOptions(d.requirements);
  operationStatus(UI.msg("operation.search.controls.savedefinition_keep_1acab8", {}));
};
$('operation_search_area').addEventListener('input', operationChanged);
document.addEventListener('lab-protocol', operationChanged);
document.addEventListener('lab-case', () => {
  operationSequence++;
  operationLibrary = [];
  operationReport = null;
  operationReportRef = null;
  operationSelected = null;
  operationRenderLibrary();
  $('operation_results').replaceChildren();
  $('operation_selected').replaceChildren();
  operationRefreshProtocols();
});
document.addEventListener('DOMContentLoaded', operationRefreshProtocols);
$('operation_search_area').addEventListener('toggle', () => {
  if ($('operation_search_area').open && !$('operation_protocols').querySelector('input')) operationRefreshProtocols();
});
$('operation_overlap').onclick = async () => {
  try {
    const experiment = interventionNeutral(operationReport.definition.conditions[0].experiment, operationSelected.events);
    const r = await api('/api/intervention-preview', {
      experiment
    });
    UI.text($('operation_curve_status'), UI.join([UI.msg("operation.search.controls.node_765575", {
      p0: r.node_count,
      p1: r.edge_count
    }), UI.list(r.intervals.map(i => UI.join([UI.join([UI.join([UI.join(['[' + i.start + ',' + i.stop + ') ' + (i.active_event_names.join(' + ') || UI.msg("operation.search.controls.actions_1ee2ec", {})), UI.msg("operation.search.controls.node_191ba7", {})]), i.node_gains.map(v => v.body_id + ':' + v.gain).join(',')]), UI.msg("operation.search.controls.message_0e81fd", {})]), i.edge_gains.map(v => v.pre + '→' + v.post + ':' + v.gain).join(',')])), ' / ')]));
  } catch (e) {
    operationStatus(UI.errorText(e));
  }
};
const operationRenderConditionsBefore = renderConditions;
renderConditions = function () {
  operationRenderConditionsBefore();
  operationRefreshProtocols();
  operationChanged();
};
for (const id of ['search_target', 'search_metric', 'search_min', 'protected_observations']) $(id).addEventListener('input', operationChanged);
$('operation_prev').onclick = () => {
  if (operationPage > 0) {
    operationPage--;
    operationRenderReport(operationReport);
  }
};
$('operation_next').onclick = () => {
  if ((operationPage + 1) * 50 < operationReport.entries.length) {
    operationPage++;
    operationRenderReport(operationReport);
  }
};
