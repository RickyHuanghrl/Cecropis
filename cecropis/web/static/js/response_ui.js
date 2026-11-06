"use strict";

/* Window summaries are immutable results, distinct from the protocol editor and replay frames. */
const responseTab = document.createElement('button');
responseTab.dataset.analysisTab = 'responses';
UI.attr(responseTab, 'role', 'tab');
UI.text(responseTab, UI.msg("response.labels.input_responses_ed303c", {}));
$('analysis_workspace').querySelector('[role=tablist]').append(responseTab);
const responseArea = document.createElement('div');
responseArea.id = 'analysis_responses';
responseArea.hidden = true;
responseArea.innerHTML = `<details open id="response_setup"><summary>${UI.htmlText("response.labels.batch_input_definition_60ae9a", {})}</summary>
<div class="buttons"><label>${UI.htmlText("response.labels.name_1f7866", {})}<input id="response_name" placeholder="${UI.t('default.responseName')}" data-i18n-placeholder="default.responseName" maxlength="120"></label><label>${UI.htmlText("response.labels.updates_4402f3", {})}<input id="response_steps" type="number" value="32" min="1" max="2000" style="width:70px"></label><label>α <input id="response_alpha" type="number" value="0.3" step="any" style="width:70px"></label><label>ρ <input id="response_rho" type="number" value="0.9" step="any" style="width:70px"></label></div>
<div class="buttons"><label>${UI.htmlText("response.labels.summary_updates_50ffbc", {})}<input id="response_start" type="number" value="0" style="width:65px"></label><label>, <input id="response_stop" type="number" value="32" style="width:65px"> )</label><label>${UI.htmlText("response.labels.response_groups_25f752", {})}<select id="response_field"><option value="superclass" data-i18n="field.superclass">superclass</option><option value="class" data-i18n="field.class">class</option><option value="type" data-i18n="field.type">type</option><option value="somaSide" data-i18n="field.somaSide">somaSide</option></select></label><label><input id="response_plan" type="checkbox">${UI.htmlText("response.labels.use_current_fixed_event_plan_2e72b3", {})}</label></div>
<div class="buttons"><button id="response_import">${UI.htmlText("response.labels.add_comparison_protocols_49e269", {})}</button><button id="response_current">${UI.htmlText("response.labels.add_current_input_protocol_bbc950", {})}</button><label>${UI.htmlText("response.labels.generate_from_scope_groups_e54731", {})}<select id="response_input_field"><option value="superclass" data-i18n="field.superclass">superclass</option><option value="class" data-i18n="field.class">class</option><option value="type" data-i18n="field.type">type</option><option value="somaSide" data-i18n="field.somaSide">somaSide</option></select></label><select id="response_input_group" ${UI.htmlAttribute("aria-label", "response.labels.message_373bd1", {})}></select><button id="response_group_add">${UI.htmlText("response.labels.add_group_input_ea102c", {})}</button><button id="response_selection_add">${UI.htmlText("response.labels.add_input_from_shared_selection_a6e109", {})}</button><button id="response_query_add">${UI.htmlText("response.labels.add_all_query_members_2cee0a", {})}</button><button id="response_global_group_add">${UI.htmlText("response.labels.add_complete_group_selection_23eebb", {})}</button></div>
<div class="buttons"><label>${UI.htmlText("response.labels.pulse_7f5a0b", {})}<input id="response_pulse_start" type="number" value="2" style="width:65px"></label><label>, <input id="response_pulse_stop" type="number" value="12" style="width:65px"> )</label><select id="response_strength_mode"><option value="per_node" data-i18n="response.labels.same_amplitude_per_node_bd9d43">${UI.t("response.labels.same_amplitude_per_node_bd9d43")}</option><option value="fixed_total" data-i18n="response.labels.fixed_group_total_53a03d">${UI.t("response.labels.fixed_group_total_53a03d")}</option></select><label>${UI.htmlText("response.labels.amplitude_dcd367", {})}<input id="response_strength" type="number" value="0.5" step="any" style="width:70px"></label></div>
<div class="tablewrap"><table><thead><tr><th>${UI.htmlText("response.labels.input_conditions_1cc45e", {})}</th><th>${UI.htmlText("response.labels.exact_members_interval_amplitude_5f8880", {})}</th><th>${UI.htmlText("response.labels.actions_ed31fb", {})}</th></tr></thead><tbody id="response_inputs"></tbody></table></div>
<details id="response_edit_area" hidden><summary>${UI.htmlText("response.labels.edit_a_condition_82e992", {})}</summary><label>${UI.htmlText("response.labels.name_1f7866", {})}<input id="response_edit_name"></label><textarea id="response_edit_events" rows="5" ${UI.htmlAttribute("aria-label", "response.labels.input_eventsjson_f5e910", {})}></textarea><button id="response_edit_apply">${UI.htmlText("response.labels.save_draft_changes_275625", {})}</button></details>
<details><summary>${UI.htmlText("response.labels.budget_bd8dbd", {})}</summary><div class="buttons"><label>${UI.htmlText("response.labels.maximum_conditions_debc2d", {})}<input id="response_conditions_budget" type="number" value="64" style="width:80px"></label><label>${UI.htmlText("response.labels.maximum_propagations_21c090", {})}<input id="response_propagations_budget" type="number" value="128" style="width:80px"></label><label>${UI.htmlText("response.labels.memory_mib_1ba4fd", {})}<input id="response_memory" type="number" value="512" style="width:80px"></label><label>${UI.htmlText("response.labels.storage_mib_590e23", {})}<input id="response_storage" type="number" value="256" style="width:80px"></label></div></details>
<div class="buttons"><button id="response_preview">${UI.htmlText("response.labels.check_request_3b5e10", {})}</button><button id="response_run" disabled>${UI.htmlText("response.labels.run_batch_responses_6a6217", {})}</button><button id="response_cancel" disabled>${UI.htmlText("response.labels.cancel_2cd0f3", {})}</button></div><div id="response_preview_info"></div></details>
<div id="response_status" role="status"></div><div id="response_result_context"></div>
<div id="response_results" hidden><div class="buttons"><select id="response_mode"><option value="baseline" data-i18n="response.labels.no_intervention_mean_bc6282">${UI.t("response.labels.no_intervention_mean_bc6282")}</option><option value="intervention" data-i18n="response.labels.intervention_mean_ed07c3">${UI.t("response.labels.intervention_mean_ed07c3")}</option><option value="delta" data-i18n="response.labels.intervention_no_intervention_mean_253118">${UI.t("response.labels.intervention_no_intervention_mean_253118")}</option></select><label>${UI.htmlText("response.labels.color_domain_upper_bound_3e10ad", {})}<input id="response_domain" type="number" value="1" min="0.000000000001" step="any" style="width:100px"></label><input id="response_group_filter" ${UI.htmlAttribute("placeholder", "response.labels.filter_9dd91d", {})} ${UI.htmlAttribute("aria-label", "response.labels.filter_9dd91d", {})}><select id="response_group_sort"><option value="name" data-i18n="response.labels.name_d44e9b">${UI.t("response.labels.name_d44e9b")}</option><option value="size" data-i18n="response.labels.member_count_0bcb3d">${UI.t("response.labels.member_count_0bcb3d")}</option><option value="response" data-i18n="response.labels.current_condition_responses_443f6c">${UI.t("response.labels.current_condition_responses_443f6c")}</option></select><button id="response_matrix_prev">${UI.htmlText("response.labels.previous_30f69e", {})}</button><button id="response_matrix_next">${UI.htmlText("response.labels.next_9376bc", {})}</button></div><div id="response_matrix_context"></div><canvas id="response_matrix" ${UI.htmlAttribute("aria-label", "response.labels.input_conditions_740e17", {})} style="display:block;width:100%"></canvas>
<div class="buttons"><select id="response_condition" ${UI.htmlAttribute("aria-label", "response.labels.condition_95bf38", {})}></select><select id="response_group" ${UI.htmlAttribute("aria-label", "response.labels.message_e01078", {})}></select><select id="response_other" ${UI.htmlAttribute("aria-label", "response.labels.input_conditions_29fd89", {})}></select><label><input id="response_hide_inputs" type="checkbox" checked>${UI.htmlText("response.labels.exclude_current_direct_inputs_from_ranking_00e947", {})}</label><button id="response_nodes_refresh">${UI.htmlText("response.labels.node_ranking_d332b4", {})}</button><button id="response_group_select">${UI.htmlText("response.labels.select_complete_response_group_6018a2", {})}</button><button id="response_space">${UI.htmlText("response.labels.spatial_window_summary_19ab37", {})}</button></div><div id="response_group_value"></div>
<div class="tablewrap"><table><thead><tr><th>${UI.htmlText("response.labels.body_id_type_8d5575", {})}</th><th>${UI.htmlText("response.labels.no_intervention_269771", {})}</th><th>${UI.htmlText("response.labels.intervention_c74feb", {})}</th><th>${UI.htmlText("response.labels.absolute_change_8ab166", {})}</th><th>${UI.htmlText("response.labels.two_input_difference_5e0997", {})}</th><th>${UI.htmlText("response.labels.actions_ed31fb", {})}</th></tr></thead><tbody id="response_nodes"></tbody></table></div><div class="buttons"><button id="response_nodes_prev">${UI.htmlText("response.labels.previous_30f69e", {})}</button><span id="response_nodes_page"></span><button id="response_nodes_next">${UI.htmlText("response.labels.next_9376bc", {})}</button></div>
<div class="buttons"><label>${UI.htmlText("response.labels.new_observation_name_dec81c", {})}<input id="response_observation_name" ${UI.htmlAttribute("placeholder", "response.labels.message_a8245a", {})}></label><button id="response_copy_definition">${UI.htmlText("response.labels.copy_historical_definition_to_a_new_draft_4b36d0", {})}</button><button id="response_to_draft">${UI.htmlText("response.labels.use_as_comparison_draft_6c8bc0", {})}</button><button id="response_curve_preview">${UI.htmlText("response.labels.check_full_curve_request_4db7a9", {})}</button><button id="response_curves" disabled>${UI.htmlText("response.labels.compute_curves_be1304", {})}</button><button id="response_export">${UI.htmlText("response.labels.export_selected_fixed_task_296ded", {})}</button><button id="response_save">${UI.htmlText("response.labels.save_exploration_and_display_1dd0b8", {})}</button></div><div id="response_curve_info"></div></div>`;
$('analysis_workspace').append(responseArea);
let responseInputs = [],
  responseNodesMeta = [],
  responseDraftPlan = null,
  responsePreview = null,
  responseReport = null,
  responseRef = null,
  responseJob = null,
  responseEpoch = 0,
  responseRowsEpoch = 0,
  responsePage = 0,
  responseMatrixPage = 0,
  responseEdit = null,
  responseSpaceSummary = null;
const previousResponseTab = analysisTab;
analysisTab = view => {
  previousResponseTab(view);
  responseArea.hidden = view !== 'responses';
};
responseTab.onclick = () => {
  analysisTab('responses');
  responseInputGroups();
  if (!overview?.manifest) UI.text($('response_status'), UI.msg("response.controls.search_openscope_3d285c", {}));
};
function responseStatus(s, error = false) {
  UI.text($('response_status'), s);
  $('response_status').classList.toggle('error', error);
}
function responseInvalidate() {
  responsePreview = null;
  $('response_run').disabled = true;
  UI.text($('response_preview_info'), UI.msg("response.responseInvalidate.definition_changed_check_again_3efc2e", {}));
  if (responseReport) responseStatus(UI.msg("response.responseInvalidate.definition_edit_run_14ca70", {}));
}
function responseDefaultName(name) {
  name = String(name);
  let n = name,
    k = 2;
  while (responseInputs.some(c => c.name === n)) n = name + ' ' + k++;
  return n;
}
function responseDefinition() {
  return {
    name: $('response_name').value.trim() || UI.t('default.responseName'),
    steps: Number($('response_steps').value),
    alpha: Number($('response_alpha').value),
    rho: Number($('response_rho').value),
    window: {
      start: Number($('response_start').value),
      stop: Number($('response_stop').value)
    },
    group_field: $('response_field').value,
    conditions: responseInputs,
    intervention_events: $('response_plan').checked ? responseDraftPlan ?? interventionUI.events() : null,
    budgets: {
      max_conditions: Number($('response_conditions_budget').value),
      max_propagations: Number($('response_propagations_budget').value),
      max_bytes: Number($('response_memory').value) * 1048576,
      max_storage_bytes: Number($('response_storage').value) * 1048576
    }
  };
}
function responseInputRender() {
  $('response_inputs').innerHTML = responseInputs.map((c, k) => {
    const es = c.input_events || protocolEvents(c.experiment);
    return `<tr><td>${UI.html(c.name)}</td><td>${UI.htmlList(es.map(e => UI.msg("response.controls.node_node_0f1dc9", {
      p0: e.body_ids.length,
      p1: e.start,
      p2: e.stop,
      p3: UI.numeric(e.amplitude, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      }),
      p4: UI.numeric(e.amplitude * e.body_ids.length, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      })
    })), '<br>')}</td><td><button data-response-edit="${k}">${UI.htmlText("response.controls.edit_051836", {})}</button><button data-response-delete="${k}">${UI.htmlText("response.controls.remove_6135d4", {})}</button></td></tr>`;
  }).join('');
  responseInvalidate();
}
async function responseInputGroups() {
  if (!overview?.manifest) return;
  const id = overview.manifest.case_id,
    seq = ++responseRowsEpoch;
  try {
    const r = await api('/api/responses-scope-groups', {
      field: $('response_input_field').value
    });
    if (seq !== responseRowsEpoch || overview.manifest.case_id !== id) return;
    responseNodesMeta = r.groups;
    $('response_input_group').replaceChildren(...r.groups.map(g => UI.option(UI.join(["", g.name ?? UI.msg("response.controls.message_9c54e4", {}), " · ", g.body_ids.length, ""]), String(g.id))));
  } catch (e) {
    responseStatus(UI.errorText(e), true);
  }
}
function responseLocalCheck(ids) {
  const scoped = new Set((overview?.scope_nodes || []).map(n => String(n.bodyId))),
    missing = ids.filter(i => !scoped.has(String(i)));
  if (missing.length) throw UI.errorValue(UI.join([UI.msg("response.responseLocalCheck.members_current_scope_scope_62b753", {}), missing.join(', ')]));
}
async function responseAddGenerated(ids, name) {
  try {
    responseLocalCheck(ids);
    const item = await api('/api/responses-generate', {
      name: responseDefaultName(name),
      body_ids: ids,
      start: Number($('response_pulse_start').value),
      stop: Number($('response_pulse_stop').value),
      strength: Number($('response_strength').value),
      mode: $('response_strength_mode').value
    });
    responseInputs.push(item);
    responseInputRender();
  } catch (e) {
    responseStatus(UI.errorText(e), true);
  }
}
function responseImport(items) {
  for (const c of items) {
    const e = c.experiment;
    responseInputs.push({
      name: responseDefaultName(c.name),
      experiment: JSON.parse(JSON.stringify(e)),
      search_options: c.search_options ?? null,
      role: c.role || 'decision'
    });
  }
  responseInputRender();
}
function responseFrozenParameters() {
  if (!responseInputs.length) {
    const c = cfg();
    for (const k of ['steps', 'alpha', 'rho']) $('response_' + k).value = c[k];
    $('response_stop').value = c.steps;
  }
}
$('response_import').onclick = () => {
  responseFrozenParameters();
  responseImport(conditions);
};
$('response_current').onclick = () => {
  responseFrozenParameters();
  responseImport([{
    name: UI.t("response.controls.message_3636c3"),
    experiment: cfg()
  }]);
};
$('response_group_add').onclick = () => {
  const g = responseNodesMeta.find(g => g.id === Number($('response_input_group').value));
  if (g) responseAddGenerated(g.body_ids, g.name ?? UI.msg("response.controls.message_9c54e4", {}));
};
$('response_selection_add').onclick = () => responseAddGenerated(analysisSelection.ids(), UI.msg("response.controls.message_b6469a", {}));
$('response_global_group_add').onclick = () => responseAddGenerated(groupMemberSelection?.body_ids || [], UI.msg("response.controls.select_86b531", {}));
$('response_input_field').onchange = responseInputGroups;
$('response_inputs').onclick = e => {
  const k = e.target.dataset.responseDelete;
  if (k != null) {
    responseInputs.splice(Number(k), 1);
    responseInputRender();
  }
  const i = e.target.dataset.responseEdit;
  if (i != null) {
    responseEdit = Number(i);
    const c = responseInputs[responseEdit];
    $('response_edit_area').hidden = false;
    $('response_edit_area').open = true;
    $('response_edit_name').value = c.name;
    $('response_edit_events').value = JSON.stringify(c.input_events || protocolEvents(c.experiment), null, 2);
  }
};
$('response_edit_apply').onclick = () => {
  try {
    const c = responseInputs[responseEdit],
      events = JSON.parse($('response_edit_events').value);
    responseInputs[responseEdit] = {
      name: $('response_edit_name').value.trim(),
      input_events: events,
      observations: c.observations || protocolObservations(c.experiment || {
        observations: []
      }),
      search_options: c.search_options,
      role: c.role,
      generation: {
        mode: 'edited_protocol'
      }
    };
    responseInputRender();
    $('response_edit_area').hidden = true;
  } catch (e) {
    responseStatus(UI.errorText(e), true);
  }
};
for (const el of $('response_setup').querySelectorAll('input,select')) el.addEventListener('change', responseInvalidate);
async function responseDoPreview() {
  try {
    const r = await api('/api/responses-preview', {
      definition: responseDefinition()
    });
    responsePreview = r;
    $('response_run').disabled = false;
    UI.text($('response_preview_info'), UI.msg("response.responseDoPreview.node_condition_mib_mib_mib_6e047c", {
      p0: r.node_count,
      p1: r.condition_count,
      p2: r.group_count,
      p3: r.expected_propagations,
      p4: UI.numeric(r.array_bytes / 1048576, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }),
      p5: UI.numeric(r.estimated_memory_bytes / 1048576, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }),
      p6: UI.numeric(r.estimated_storage_bytes / 1048576, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      })
    }));
    responseStatus(UI.msg("response.responseDoPreview.check_requestcomplete_80af31", {}));
  } catch (e) {
    responsePreview = null;
    $('response_run').disabled = true;
    responseStatus(UI.errorText(e), true);
  }
}
$('response_preview').onclick = responseDoPreview;
function responseLock(active) {
  operationsLock(active);
  $('response_setup').querySelectorAll('input,select,textarea,button').forEach(el => el.disabled = active);
  $('response_cancel').disabled = !active;
  $('response_run').disabled = active || !responsePreview;
  $('response_results').inert = active;
}
async function responsePoll(id, curves, epoch) {
  try {
    const task = await api('/api/responses-job?' + new URLSearchParams({
      job_id: id
    }));
    if (epoch !== responseEpoch) return;
    if (task.status === 'running') {
      responseStatus(UI.msg("response.responsePoll.condition_completebaseline_intervention_b102a9", {
        p0: task.progress.condition || '—',
        p1: task.progress.condition_count || '—',
        p2: task.progress.name || '',
        p3: UI.code(task.progress.branch || task.progress.status) || UI.msg("response.responsePoll.message_ddcf6e", {}),
        p4: task.progress.baseline_completed || 0,
        p5: task.progress.intervention_completed || 0
      }));
      setTimeout(() => responsePoll(id, curves, epoch), 500);
      return;
    }
    if (task.result) {
      const result = await api('/api/responses-result', {
        job_id: id
      });
      if (epoch !== responseEpoch) return;
      if (curves) {
        responseLock(false);
        if (result.results?.length) {
          renderComparison(result);
          enterReplay();
        }
        UI.text($('response_curve_info'), UI.msg("response.responsePoll.start_complete_result_analysis_c34fcd", {
          p0: result.status === 'complete' ? UI.msg("response.responsePoll.message_42098f", {}) : UI.code(result.status),
          p1: result.execution_counts?.physical_started ?? 0,
          p2: result.execution_counts?.physical_completed ?? 0
        }));
      } else {
        responseRef = {
          report_id: result.report_id
        };
        await responseRender(result);
      }
    } else responseStatus(UI.jobText(task), true);
    responseLock(false);
  } catch (e) {
    if (epoch === responseEpoch) {
      responseLock(false);
      responseStatus(UI.errorText(e), true);
    }
  }
}
$('response_run').onclick = async () => {
  try {
    if (!responsePreview) throw UI.error("response.controls.check_the_definition_first_0d5767", {});
    const definition = responsePreview.definition;
    responseLock(true);
    const r = await api('/api/responses-start', {
      definition
    });
    responseJob = r.job_id;
    responsePoll(r.job_id, false, ++responseEpoch);
  } catch (e) {
    responseLock(false);
    responseStatus(UI.errorText(e), true);
  }
};
$('response_cancel').onclick = async () => {
  try {
    await api('/api/responses-cancel', {
      job_id: responseJob
    });
    responseStatus(UI.msg("response.controls.cancel_complete_keep_73b6c2", {}));
  } catch (e) {
    responseStatus(UI.errorText(e), true);
  }
};
function responseParams() {
  return {
    ...responseRef,
    condition: Number($('response_condition').value),
    group_id: $('response_group').value === '' ? null : Number($('response_group').value),
    observation_name: $('response_observation_name').value.trim() || null
  };
}
function responseDisplay() {
  return {
    condition: Number($('response_condition').value),
    group_id: $('response_group').value,
    mode: $('response_mode').value,
    other: $('response_other').value,
    exclude_inputs: $('response_hide_inputs').checked,
    node_offset: responsePage,
    group_page: responseMatrixPage,
    group_filter: $('response_group_filter').value,
    group_sort: $('response_group_sort').value,
    domain: Number($('response_domain').value),
    selected_nodes: analysisSelection.ids(),
    spatial: spaceSnapshot(),
    summary_condition: responseSpaceSummary?.condition ?? null,
    summary_mode: responseSpaceSummary?.mode ?? null
  };
}
async function responseRender(report, restore = false) {
  responseReport = report;
  responsePage = 0;
  responseMatrixPage = 0;
  $('response_results').hidden = false;
  $('response_condition').replaceChildren(...report.definition.conditions.map((c, k) => UI.option(UI.join([c.name, ' · ', UI.code(report.condition_states[k].status)]), String(k))));
  $('response_other').replaceChildren(UI.option(UI.msg("response.responseRender.comparison_b56bd6", {}), ''), ...report.definition.conditions.map((c, k) => UI.option(c.name, String(k))));
  $('response_group').replaceChildren(UI.option(UI.msg("response.responseRender.all_calculation_nodes_c3d6e0", {}), ''), ...report.groups.map(g => UI.option(UI.join(["", g.name ?? UI.msg("response.controls.message_9c54e4", {}), " · ", g.member_count, ""]), String(g.id))));
  const w = report.definition.window;
  UI.text($('response_result_context'), UI.msg("response.responseRender.scope_node_cad55c", {
    p0: report.definition.name,
    p1: report.case_id,
    p2: report.preview.node_count,
    p3: report.definition.conditions.length,
    p4: w.start,
    p5: w.stop,
    p6: w.stop - w.start
  }));
  responseStatus(UI.msg("response.responseRender.start_complete_run_failed_d6f61a", {
    p0: report.status,
    p1: report.execution_counts.physical_started,
    p2: report.execution_counts.physical_completed
  }));
  if (restore) {
    const d = report.display || {};
    for (const [id, k] of [['response_condition', 'condition'], ['response_group', 'group_id'], ['response_mode', 'mode'], ['response_other', 'other'], ['response_group_filter', 'group_filter'], ['response_group_sort', 'group_sort'], ['response_domain', 'domain']]) if (d[k] != null) $(id).value = d[k];
    $('response_hide_inputs').checked = d.exclude_inputs ?? true;
    responsePage = d.node_offset || 0;
    responseMatrixPage = d.group_page || 0;
    if (d.selected_nodes) {
      const local = new Set((overview?.scope_nodes || []).map(n => String(n.bodyId)));
      if (d.selected_nodes.some(id => !local.has(id))) await spaceLoad();
      analysisSelection.set(d.selected_nodes);
    }
  }
  responseDrawMatrix();
  await responseReadNodes();
  $('response_curves').disabled = true;
}
async function openResponses(saved) {
  responseEpoch++;
  responseRowsEpoch++;
  responseRef = saved.task_id ? {
    task_id: saved.task_id
  } : {
    artifact_id: saved.artifact_id
  };
  await responseRender(saved.result, true);
  analysisTab('responses');
  const d = saved.result.display || {};
  if (d.spatial) {
    await spaceRestore(d.spatial);
    if (d.summary_condition != null) {
      const condition = $('response_condition').value,
        mode = $('response_mode').value;
      $('response_condition').value = d.summary_condition;
      $('response_mode').value = d.summary_mode;
      await responseToSpace(false);
      $('response_condition').value = condition;
      $('response_mode').value = mode;
    }
  }
}
function responseVisibleGroups() {
  const filter = $('response_group_filter').value.toLowerCase(),
    condition = Number($('response_condition').value),
    mode = $('response_mode').value;
  return responseReport.groups.filter(g => String(g.name ?? UI.msg("response.controls.message_9c54e4", {})).toLowerCase().includes(filter)).slice().sort((a, b) => $('response_group_sort').value === 'size' ? b.member_count - a.member_count || a.id - b.id : $('response_group_sort').value === 'response' ? (responseMetric(responseReport.group_responses[condition].groups[b.id], mode) ?? -Infinity) - (responseMetric(responseReport.group_responses[condition].groups[a.id], mode) ?? -Infinity) || a.id - b.id : String(a.name ?? '').localeCompare(String(b.name ?? '')));
}
function responseMetric(g, mode) {
  return mode === 'delta' ? g.delta : g[mode + '_mean'];
}
function responseDrawMatrix() {
  if (!responseReport) return;
  const all = responseVisibleGroups(),
    groups = all.slice(responseMatrixPage * 12, responseMatrixPage * 12 + 12),
    rows = responseReport.group_responses,
    canvas = $('response_matrix'),
    width = Math.max(550, canvas.clientWidth),
    left = 170,
    top = 110,
    cw = (width - left) / Math.max(1, groups.length),
    height = top + rows.length * 28;
  canvas.width = width * devicePixelRatio;
  canvas.height = height * devicePixelRatio;
  canvas.style.height = height + 'px';
  const c = canvas.getContext('2d');
  c.scale(devicePixelRatio, devicePixelRatio);
  c.clearRect(0, 0, width, height);
  c.font = UI.canvasFont(12);
  const mode = $('response_mode').value,
    domain = Number($('response_domain').value);
  if (!Number.isFinite(domain) || domain <= 0) {
    responseStatus(UI.msg("response.responseDrawMatrix.color_domain_upper_bound_43d8f4", {}), true);
    return;
  }
  groups.forEach((g, k) => {
    c.save();
    c.translate(left + k * cw + cw / 2, top - 8);
    c.rotate(-.55);
    c.fillStyle = UI.color('text');
    c.fillText(g.name ?? UI.msg("response.controls.message_9c54e4", {}), 0, 0);
    c.restore();
  });
  let min = Infinity,
    max = -Infinity;
  rows.forEach((row, i) => {
    c.fillStyle = UI.color('text');
    c.fillText(row.name.slice(0, 22), 4, top + i * 28 + 18);
    groups.forEach((g, k) => {
      const v = responseMetric(row.groups[g.id], mode),
        x = left + k * cw,
        y = top + i * 28;
      const background = UI.heatColor(v, domain, mode);
      c.fillStyle = background;
      c.fillRect(x, y, cw - 2, 26);
      if (v == null) {
        c.fillStyle = UI.contrastText(background);
        c.fillText(row.status === 'complete' ? UI.msg("response.controls.message_e34475", {}) : UI.code(row.status), x + 3, y + 17);
      } else {
        min = Math.min(min, v);
        max = Math.max(max, v);
        c.fillStyle = UI.contrastText(background);
        c.fillText(contextNumber(v), x + 3, y + 17);
      }
    });
  });
  UI.text($('response_matrix_context'), UI.msg("response.responseDrawMatrix.input_conditions_membersnode_pin_3774f6", {
    p0: groups.length,
    p1: all.length,
    p2: responseReport.groups.length,
    p3: mode === 'delta' ? '±' : '0…',
    p4: UI.numeric(domain, {
      notation: "scientific",
      minimumFractionDigits: 4,
      maximumFractionDigits: 4
    }),
    p5: Number.isFinite(min) ? contextNumber(min) + '…' + contextNumber(max) : UI.msg("response.responseDrawMatrix.not_recorded_7450cc", {})
  }));
  $('response_matrix_prev').disabled = responseMatrixPage === 0;
  $('response_matrix_next').disabled = (responseMatrixPage + 1) * 12 >= all.length;
  canvas.onclick = event => {
    const r = canvas.getBoundingClientRect(),
      k = Math.floor((event.clientX - r.left - left) / cw),
      i = Math.floor((event.clientY - r.top - top) / 28);
    if (k >= 0 && k < groups.length && i >= 0 && i < rows.length) {
      $('response_condition').value = i;
      $('response_group').value = groups[k].id;
      responsePage = 0;
      $('response_curves').disabled = true;
      responseReadNodes();
      if (responseSpaceSummary) responseToSpace(false);
    }
  };
}
async function responseReadNodes() {
  if (!responseReport) return;
  const seq = ++responseRowsEpoch,
    p = responseParams(),
    mode = $('response_mode').value;
  try {
    const r = await api('/api/responses-nodes', {
      ...p,
      mode,
      other: $('response_other').value === '' ? null : Number($('response_other').value),
      exclude_inputs: $('response_hide_inputs').checked,
      offset: responsePage,
      limit: 50
    });
    if (seq !== responseRowsEpoch) return;
    $('response_nodes').innerHTML = r.rows.map(n => `<tr><td><button data-response-focus="${esc(n.body_id)}">${UI.html(n.type || UI.msg("response.controls.message_9c54e4", {}))} · ${UI.html(n.body_id)}</button></td><td>${UI.html(n.baseline == null ? UI.msg("response.controls.not_recorded_7450cc", {}) : contextNumber(n.baseline))}</td><td>${UI.html(n.intervention == null ? UI.msg("response.controls.message_e34475", {}) : contextNumber(n.intervention))}</td><td>${UI.html(n.delta == null ? UI.msg("response.controls.definition_2ba10d", {}) : contextNumber(n.delta))}</td><td>${n.condition_difference == null ? '—' : contextNumber(n.condition_difference)}</td><td><button data-response-add="${esc(n.body_id)}">${UI.htmlText("response.controls.add_to_selection_c3ce5d", {})}</button></td></tr>`).join('');
    UI.text($('response_nodes_page'), `${responsePage + 1}–${Math.min(responsePage + r.rows.length, r.total)} / ${r.total}`);
    $('response_nodes_prev').disabled = responsePage === 0;
    $('response_nodes_next').disabled = responsePage + 50 >= r.total;
    const g = p.group_id == null ? null : responseReport.group_responses[p.condition].groups[p.group_id];
    UI.text($('response_group_value'), g ? UI.msg("response.responseReadNodes.members_no_intervention_mean_intervention_mean_relative__81419d", {
      p0: g.member_count,
      p1: g.baseline_mean == null ? UI.msg("response.responseReadNodes.not_recorded_7450cc", {}) : contextNumber(g.baseline_mean),
      p2: g.baseline_node_mean_sum == null ? UI.msg("response.responseReadNodes.not_recorded_7450cc", {}) : contextNumber(g.baseline_node_mean_sum),
      p3: g.intervention_mean == null ? UI.msg("response.responseReadNodes.message_e34475", {}) : contextNumber(g.intervention_mean),
      p4: g.relative_delta == null ? UI.msg("response.responseReadNodes.definition_2ba10d", {}) : (g.relative_delta * 100).toFixed(4) + '%'
    }) : UI.msg("response.responseReadNodes.all_calculation_nodes_7c717c", {}));
  } catch (e) {
    if (seq === responseRowsEpoch) {
      $('response_nodes').replaceChildren();
      responseStatus(UI.errorText(e), true);
    }
  }
}
for (const id of ['response_condition', 'response_group', 'response_other', 'response_hide_inputs']) $(id).onchange = () => {
  responsePage = 0;
  $('response_curves').disabled = true;
  responseReadNodes();
  responseDrawMatrix();
  if (responseSpaceSummary) responseToSpace(false);
};
$('response_mode').onchange = () => {
  responsePage = 0;
  responseReadNodes();
  responseDrawMatrix();
  if (responseSpaceSummary) responseToSpace(false);
};
for (const id of ['response_group_filter', 'response_group_sort', 'response_domain']) $(id).onchange = () => {
  responseMatrixPage = 0;
  responseDrawMatrix();
};
$('response_nodes_refresh').onclick = () => responseReadNodes();
$('response_nodes_prev').onclick = () => {
  responsePage = Math.max(0, responsePage - 50);
  responseReadNodes();
};
$('response_nodes_next').onclick = () => {
  responsePage += 50;
  responseReadNodes();
};
$('response_matrix_prev').onclick = () => {
  responseMatrixPage--;
  responseDrawMatrix();
};
$('response_matrix_next').onclick = () => {
  responseMatrixPage++;
  responseDrawMatrix();
};
$('response_nodes').onclick = e => {
  try {
    if (e.target.dataset.responseAdd) analysisSelection.add([e.target.dataset.responseAdd]);
    if (e.target.dataset.responseFocus) {
      analysisSelection.focus(e.target.dataset.responseFocus);
      analysisTab('connections');
      $('analysis_node_details').open = true;
    }
  } catch (e) {
    responseStatus(UI.errorText(e), true);
  }
};
$('response_group_select').onclick = async () => {
  try {
    const p = responseParams();
    if (p.group_id == null) throw UI.error("response.controls.select_266b4b", {});
    const r = await api('/api/responses-members', p);
    analysisSelection.set(r.body_ids);
    responseStatus(UI.msg("response.controls.select_members_0d4ef6", {
      p0: r.body_ids.length
    }));
  } catch (e) {
    responseStatus(UI.errorText(e), true);
  }
};
async function responseToSpace(scroll = true) {
  const epoch = ++responseEpoch,
    p = responseParams(),
    mode = $('response_mode').value,
    scope = overview.manifest.case_id;
  try {
    await spaceLoad();
    if (epoch !== responseEpoch) return;
    const rows = [];
    let offset = 0;
    while (true) {
      const r = await api('/api/responses-values', {
        ...p,
        mode,
        offset,
        limit: 20000
      });
      if (epoch !== responseEpoch || scope !== overview.manifest.case_id) return;
      r.body_ids.forEach((id, k) => rows.push({
        body_id: id,
        [mode]: r.values[k]
      }));
      offset += r.values.length;
      if (offset >= r.total) break;
      if (!r.values.length) throw UI.error("response.responseToSpace.message_7488f8", {});
    }
    spaceUnbind();
    responseSpaceSummary = {
      condition: p.condition,
      mode,
      scope,
      report_id: responseReport.definition_hash,
      rows
    };
    globalSpace.setActivity({
      nodes: rows
    }, mode, Number($('response_domain').value));
    $('space_mode').value = mode;
    const w = responseReport.definition.window;
    let shown = 0,
      zero = 0,
      min = Infinity,
      max = -Infinity;
    rows.forEach(r => {
      if (globalSpace.idIndex.has(r.body_id) && globalSpace.kinds[globalSpace.idIndex.get(r.body_id)]) shown++;
      if (r[mode] === 0) zero++;
      min = Math.min(min, r[mode]);
      max = Math.max(max, r[mode]);
    });
    UI.text($('space_frame_label'), UI.msg("response.responseToSpace.window_6f3603", {
      p0: responseReport.definition.conditions[p.condition].name,
      p1: w.start,
      p2: w.stop
    }));
    UI.text($('space_activity_info'), UI.msg("response.responseToSpace.node_space_no_position_scope_keep_3881e4", {
      p0: rows.length,
      p1: shown,
      p2: rows.length - shown,
      p3: zero,
      p4: UI.numeric(min, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      }),
      p5: UI.numeric(max, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      }),
      p6: mode === 'delta' ? '±' : '0…',
      p7: UI.numeric(globalSpace.domain, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      })
    }));
    spaceUpdateFocusValue();
    if (scroll) $('spatial_panel').scrollIntoView({
      block: 'start'
    });
  } catch (e) {
    responseStatus(UI.errorText(e), true);
  }
}
$('response_space').onclick = responseToSpace;
const responseOldSpaceUnbind = spaceUnbind;
spaceUnbind = () => {
  responseSpaceSummary = null;
  responseOldSpaceUnbind();
};
const responseOldFocusValue = spaceUpdateFocusValue;
spaceUpdateFocusValue = () => {
  if (!responseSpaceSummary) {
    responseOldFocusValue();
    return;
  }
  if (!spaceFocusData) return;
  let v = $('space_focus_value');
  if (!v) {
    v = document.createElement('div');
    v.id = 'space_focus_value';
    $('space_node_detail').append(v);
  }
  const row = globalSpace.activity.get(spaceFocusId);
  UI.text(v, row ? UI.msg("response.controls.window_status_replay_1696ed", {
    p0: UI.numeric(row[responseSpaceSummary.mode], {
      notation: "scientific",
      minimumFractionDigits: 4,
      maximumFractionDigits: 4
    }),
    p1: responseSpaceSummary.mode
  }) : UI.msg("response.controls.outside_this_calculation_c5d1ba", {}));
};
const responseOldSpaceMode = $('space_mode').onchange;
$('space_mode').onchange = () => {
  if (responseSpaceSummary) {
    responseStatus(UI.msg("response.controls.window_input_responses_9b03ab", {}));
    $('space_mode').value = responseSpaceSummary.mode;
    return;
  }
  responseOldSpaceMode();
};
$('response_to_draft').onclick = async () => {
  try {
    if (conditions.length >= 12) throw UI.error("response.controls.compare_conditions_12_1aade4", {});
    const selected = await api('/api/responses-condition', responseParams());
    const baseName = UI.t('editor.responseName',{name:selected.name});
    let name=baseName, number=2;
    while (conditions.some(c=>c.name===name)) name=baseName+' ('+(number++)+')';
    const next = [...conditions, {
      name,
      experiment: selected.experiment
    }];
    validateConditions(next);
    apply(selected.experiment);
    conditions = next;
    renderConditions();
    if (selected.search_options) applySearchOptions(selected.search_options);
    changed();
    responseStatus(UI.msg("response.controls.pincomparison_keep_not_run_24a428", {}));
  } catch (e) {
    responseStatus(UI.errorText(e), true);
  }
};
$('response_curve_preview').onclick = async () => {
  try {
    const r = await api('/api/responses-curves-preview', responseParams());
    UI.text($('response_curve_info'), UI.msg("response.controls.observation_978220", {
      p0: r.expected_propagations,
      p1: JSON.stringify(r.recording)
    }));
    $('response_curves').disabled = false;
  } catch (e) {
    responseStatus(UI.errorText(e), true);
  }
};
$('response_curves').onclick = async () => {
  try {
    responseLock(true);
    const r = await api('/api/responses-curves', responseParams());
    responseJob = r.job_id;
    responsePoll(r.job_id, true, ++responseEpoch);
  } catch (e) {
    responseLock(false);
    responseStatus(UI.errorText(e), true);
  }
};
$('response_export').onclick = async () => {
  try {
    const r = await api('/api/responses-export', {
      ...responseParams(),
      name: responseReport.definition.name + ' · ' + responseReport.definition.conditions[Number($('response_condition').value)].name
    });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([JSON.stringify(r.definition, null, 2)], {
      type: 'application/json'
    }));
    link.download = 'fixed-response-task.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    responseStatus(UI.msg("response.controls.export_selected_fixed_task_604d59", {}));
  } catch (e) {
    responseStatus(UI.errorText(e), true);
  }
};
$('response_save').onclick = async () => {
  try {
    const r = await api('/api/responses-save', {
      ...responseRef,
      display: responseDisplay()
    });
    responseRef = {
      artifact_id: r.artifact_id
    };
    responseStatus(UI.join([UI.msg("response.controls.save_894c5d", {}), r.artifact_id]));
    document.dispatchEvent(new Event('lab-saved'));
  } catch (e) {
    responseStatus(UI.errorText(e), true);
  }
};
const responseAfterOpen = window.afterAnalysisOpen;
window.afterAnalysisOpen = async (saved, options) => {
  if (saved.kind === 'response_exploration') {
    analysisOpening = false;
    analysisCurrent = null;
    analysisContext();
    UI.text($('analysis_context'), UI.join([UI.join([UI.join([UI.msg("response.controls.input_responses_d8cbcf", {}), saved.result.definition.name]), ' · ']), saved.result.case_id]));
    analysisStatus(UI.msg("response.controls.openwindow_29d91f", {}));
    analysisTab('responses');
    return;
  }
  await responseAfterOpen(saved, options);
};
document.addEventListener('lab-case', () => {
  responseEpoch++;
  responseRowsEpoch++;
  responseReport = null;
  responseRef = null;
  responseInputs = [];
  responseInputRender();
  $('response_results').hidden = true;
  responseInputGroups();
  spaceUnbind();
});
$('response_observation_name').oninput = () => {
  $('response_curves').disabled = true;
};
$('response_plan').addEventListener('change', () => {
  responseDraftPlan = null;
});
$('response_copy_definition').onclick = () => {
  try {
    if (!responseReport) throw UI.error("response.controls.open_aac452", {});
    const d = responseReport.definition;
    responseInputs = JSON.parse(JSON.stringify(d.conditions));
    for (const k of ['name', 'steps', 'alpha', 'rho']) $('response_' + k).value = d[k];
    $('response_start').value = d.window.start;
    $('response_stop').value = d.window.stop;
    $('response_field').value = d.group_field;
    $('response_plan').checked = d.intervention_events !== null;
    responseDraftPlan = JSON.parse(JSON.stringify(d.intervention_events));
    for (const [id, key] of [['response_conditions_budget', 'max_conditions'], ['response_propagations_budget', 'max_propagations']]) $(id).value = d.budgets[key];
    $('response_memory').value = d.budgets.max_bytes / 1048576;
    $('response_storage').value = d.budgets.max_storage_bytes / 1048576;
    responseInputRender();
    $('response_setup').open = true;
    responseStatus(UI.msg("response.controls.check_request_pin_edit_d94674", {}));
  } catch (e) {
    responseStatus(UI.errorText(e), true);
  }
};
const responsePreviousSpaceBind = spaceBind;
spaceBind = async () => {
  responseSpaceSummary = null;
  return responsePreviousSpaceBind();
};
$('space_bind').onclick = spaceBind;
$('response_query_add').onclick = async () => {
  try {
    const r = await api('/api/responses-query-input', {
      filters: globalFilters()
    });
    await responseAddGenerated(r.body_ids, UI.msg("response.controls.search_e0473c", {}));
  } catch (e) {
    responseStatus(UI.errorText(e), true);
  }
};

for(const event of ['ui-language','ui-theme','ui-fonts'])document.addEventListener(event,()=>{responseDrawMatrix();});
