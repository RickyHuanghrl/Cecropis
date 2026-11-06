"use strict";

/* Frozen disk tasks outlive pages. Curves remain explicit legacy operations. */
const localTasksArea = document.createElement('details');
localTasksArea.className = 'panel';
localTasksArea.id = 'local_tasks_area';
localTasksArea.open = true;
localTasksArea.innerHTML = `<summary>${UI.htmlText("local.tasks.labels.local_compute_tasks_4710d8", {})}</summary><div class="buttons"><button id="local_tasks_refresh">${UI.htmlText("local.tasks.labels.refresh_tasks_e4c954", {})}</button><select id="local_tasks_filter" ${UI.htmlAttribute("aria-label", "local.tasks.labels.task_status_f850d9", {})}><option value="" data-i18n="local.tasks.labels.all_statuses_0a379c">${UI.t("local.tasks.labels.all_statuses_0a379c")}</option>${['pending','running','pause_requested','paused','interrupted','failed','complete','budget_exhausted','cancelled'].map(code => `<option value="${code}" ${UI.displayAttribute(UI.code(code))}>${UI.format(UI.code(code))}</option>`).join('')}</select><button id="local_queue">${UI.htmlText("local.tasks.labels.run_selected_in_order_d604d5", {})}</button></div><div id="local_tasks_status" role="status"></div><div class="tablewrap"><table><thead><tr><th>${UI.htmlText("local.tasks.labels.order_9249ca", {})}</th><th>${UI.htmlText("local.tasks.labels.name_scope_580ab0", {})}</th><th>${UI.htmlText("local.tasks.labels.status_6320b4", {})}</th><th>${UI.htmlText("local.tasks.labels.committed_budget_6c6692", {})}</th><th>${UI.htmlText("local.tasks.labels.propagations_reuse_e0ff81", {})}</th><th>${UI.htmlText("local.tasks.labels.actions_ed31fb", {})}</th></tr></thead><tbody id="local_tasks_rows"></tbody></table></div><details id="local_task_details"><summary>${UI.htmlText("local.tasks.labels.definition_stop_details_26f314", {})}</summary><pre id="local_task_info" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre></details>`;
$('workspace_status').after(localTasksArea);
const localLabels = {
  pending: UI.msg("local.tasks.labels.pending_a92ef9", {}),
  running: UI.msg("local.tasks.labels.running_1f0eb9", {}),
  pause_requested: UI.msg("local.tasks.labels.pause_requested_3e246f", {}),
  paused: UI.msg("local.tasks.labels.paused_eb0c32", {}),
  interrupted: UI.msg("local.tasks.labels.interrupted_88cf2d", {}),
  failed: UI.msg("local.tasks.labels.failed_28384d", {}),
  complete: UI.msg("local.tasks.labels.complete_c0b3fb", {}),
  budget_exhausted: UI.msg("local.tasks.labels.budget_exhausted_d9e9de", {}),
  cancelled: UI.msg("local.tasks.labels.cancelled_a37778", {})
};
let localTasks = [],
  localTimer = null,
  localEpoch = 0,
  localRunningId = null;
function localStatus(s) {
  UI.text($('local_tasks_status'), s);
}
function localRender() {
  const filter = $('local_tasks_filter').value,
    selected = new Set([...$('local_tasks_rows').querySelectorAll('input:checked')].map(e => e.value));
  $('local_tasks_rows').innerHTML = localTasks.filter(t => !filter || t.status === filter).map(t => {
    const ready = ['pending', 'paused', 'interrupted', 'failed', 'cancelled'].includes(t.status),
      active = ['running', 'pause_requested'].includes(t.status),
      c = t.counts;
    return `<tr><td><input type="checkbox" value="${t.task_id}" ${selected.has(t.task_id) ? 'checked' : ''} ${ready ? '' : 'disabled'} ${UI.htmlAttribute("aria-label", "local.tasks.controls.select_8ca62b", {})}></td><td><strong data-user-text>${UI.html(t.name)}</strong><br>${UI.html(UI.code(t.task_type))} · ${UI.html(t.identity.case_id)}<br><time datetime="${esc(t.created_at)}">${UI.date(t.created_at)}</time></td><td>${UI.html(localLabels[t.status] || UI.code(t.status))}${t.stop_reason ? '<br>' + UI.html(UI.code(t.stop_reason)) : ''}${t.error ? '<details><summary>' + UI.htmlText('error.details') + '</summary>' + esc(t.error) + '</details>' : ''}</td><td>${t.completed_units} / ${t.total_or_budget}${t.frontier ? '<br>' + UI.htmlText('task.layerPosition', {position: UI.numeric(t.frontier_position), total: UI.numeric(t.frontier.length)}) : ''}</td><td>${c.physical_completed ?? 0} / ${c.physical_started ?? 0}<br>${UI.htmlText("local.tasks.controls.message_565087", {
      p0: t.reused_units,
      p1: t.retries
    })}</td><td><button data-local-action="open" data-task="${t.task_id}">${UI.htmlText("local.tasks.controls.open_result_89597b", {})}</button> <button data-local-action="details" data-task="${t.task_id}">${UI.htmlText("local.tasks.controls.definition_b4d7d4", {})}</button> <button data-local-action="run" data-task="${t.task_id}" ${ready ? '' : 'disabled'}>${UI.html(t.status === 'pending' ? UI.msg("local.tasks.controls.start_56410f", {}) : UI.msg("local.tasks.controls.continue_7c9691", {}))}</button> <button data-local-action="pause" data-task="${t.task_id}" ${t.status === 'running' ? '' : 'disabled'}>${UI.htmlText("local.tasks.controls.pause_8d12fc", {})}</button> <button data-local-action="cancel" data-task="${t.task_id}" ${active || t.status === 'pending' ? '' : 'disabled'}>${UI.htmlText("local.tasks.controls.cancel_immediately_3740f7", {})}</button> <button data-local-action="copy" data-task="${t.task_id}">${UI.htmlText("local.tasks.controls.copy_as_new_task_9b577e", {})}</button></td></tr>`;
  }).join('');
  if (!$('local_tasks_rows').children.length) $('local_tasks_rows').innerHTML = '<tr><td colspan="6"><strong>' + UI.htmlText("local.tasks.localRender.no_tasks_yet_da9688") + '</strong><div>' + UI.htmlText("local.tasks.localRender.submit_a_task_from_input_responses_or_operation_search_63a710") + '</div></td></tr>';
}
async function localRefresh() {
  try {
    const r = await api('/api/local-tasks');
    localTasks = r.tasks;
    localRender();
    localStatus(r.busy ? UI.msg("local.tasks.localRefresh.compute_slot_occupied_4d254d", {}) : UI.msg("local.tasks.localRefresh.compute_slot_available_d602bc", {}));
    clearTimeout(localTimer);
    if (localTasks.some(t => ['running', 'pause_requested'].includes(t.status))) localTimer = setTimeout(localRefresh, 1000);
  } catch (e) {
    localStatus(UI.errorText(e));
  }
}
async function localOpen(id) {
  const epoch = ++localEpoch;
  try {
    if (busy) throw UI.error("local.tasks.localOpen.viewactionsstop_00412c", {});
    const t = localTasks.find(t => t.task_id === id);
    if (t && overview?.manifest.case_id !== t.identity.case_id && window.confirmAnalysisScope && !window.confirmAnalysisScope(t.identity.case_id)) return;
    const r = await api('/api/local-result', {
      task_id: id
    });
    if (epoch !== localEpoch) return;
    if (overview?.manifest.case_id !== r.overview.manifest.case_id) activateOverview(r.overview);
    if (r.task.task_type === 'response_exploration') {
      analysisCapture();
      analysisCurrent = null;
      analysisContext();
      await openResponses({
        task_id: id,
        result: r.result
      });
      UI.text($('analysis_context'), UI.join([UI.join([UI.join([UI.msg("local.tasks.localOpen.input_responses_d8cbcf", {}), r.result.definition.name]), ' · ']), r.result.case_id]));
    } else {
      operationSequence++;
      operationReportRef = {
        task_id: id
      };
      operationPage = 0;
      operationRenderReport(r.result);
      $('intervention_editor').open = true;
      $('operation_search_area').open = true;
      $('operation_search_area').scrollIntoView({
        block: 'start'
      });
    }
    localStatus(UI.join([UI.msg("local.tasks.localOpen.open_9017d9", {}), localLabels[r.task.status] || UI.code(r.task.status)]));
  } catch (e) {
    localStatus(UI.errorText(e));
  }
}
async function localSubmit(kind, definition, start) {
  const t = await api('/api/local-submit', {
    task_type: kind,
    definition
  });
  localRunningId = t.task_id;
  localStatus(UI.join([UI.msg("local.tasks.localSubmit.message_5a8cdd", {}), t.task_id]));
  if (start) await api('/api/local-run', {
    task_ids: [t.task_id]
  });
  await localRefresh();
  localTasksArea.open = true;
  return t;
}
$('local_tasks_refresh').onclick = localRefresh;
$('local_tasks_filter').onchange = localRender;
$('local_queue').onclick = async () => {
  try {
    const ids = [...$('local_tasks_rows').querySelectorAll('input:checked')].map(e => e.value);
    if (!ids.length) throw UI.error("local.tasks.controls.select_order_cf04fc", {});
    await api('/api/local-run', {
      task_ids: ids
    });
    await localRefresh();
  } catch (e) {
    localStatus(UI.errorText(e));
  }
};
$('local_tasks_rows').onclick = async e => {
  const action = e.target.dataset.localAction,
    id = e.target.dataset.task;
  if (!action) return;
  try {
    if (action === 'open') {
      await localOpen(id);
      return;
    }
    if (action === 'details') {
      const d = await api('/api/local-task?' + new URLSearchParams({
        task_id: id
      }));
      UI.text($('local_task_info'), JSON.stringify({
        task_id: id,
        status: d.status,
        definition: d.definition,
        identity: d.identity,
        attempts: d.attempts,
        remaining: d.checkpoint.pending?.slice(d.checkpoint.position),
        error: d.error,
        stop_reason: d.stop_reason
      }, null, 2));
      $('local_task_details').open = true;
      return;
    }
    await api('/api/local-' + action, action === 'run' ? {
      task_ids: [id]
    } : {
      task_id: id
    });
    await localRefresh();
  } catch (err) {
    localStatus(UI.errorText(err));
  }
};
// Submission never holds the editable protocol hostage. Opening results is explicit.
UI.text($('response_run'), UI.msg("local.tasks.labels.submit_start_1725cd", {}));
$('response_run').onclick = async () => {
  try {
    if (!responsePreview) throw UI.error("local.tasks.controls.check_the_definition_first_0d5767", {});
    await localSubmit('response_exploration', responsePreview.definition, true);
    responseStatus(UI.msg("local.tasks.controls.continueedit_open_c409b1", {}));
  } catch (e) {
    responseStatus(UI.errorText(e), true);
  }
};
const responseSubmit = document.createElement('button');
responseSubmit.id = 'response_submit';
UI.text(responseSubmit, UI.msg("local.tasks.labels.submit_only_201079", {}));
$('response_run').after(responseSubmit);
responseSubmit.onclick = async () => {
  try {
    if (!responsePreview) throw UI.error("local.tasks.controls.check_the_definition_first_0d5767", {});
    await localSubmit('response_exploration', responsePreview.definition, false);
  } catch (e) {
    responseStatus(UI.errorText(e), true);
  }
};
UI.text($('operation_start'), UI.msg("local.tasks.labels.submit_start_1725cd", {}));
$('operation_start').onclick = async () => {
  try {
    const d = operationDefinition();
    if (!operationPreview || JSON.stringify(d) !== operationPreviewKey) throw UI.error("local.tasks.controls.check_the_current_definition_first_675d86", {});
    await localSubmit('operation_search', d, true);
    operationStatus(UI.msg("local.tasks.controls.edit_0b7089", {}));
  } catch (e) {
    operationStatus(UI.errorText(e));
  }
};
const operationSubmit = document.createElement('button');
operationSubmit.id = 'operation_submit';
UI.text(operationSubmit, UI.msg("local.tasks.labels.submit_only_201079", {}));
$('operation_start').after(operationSubmit);
operationSubmit.onclick = async () => {
  try {
    const d = operationDefinition();
    if (!operationPreview || JSON.stringify(d) !== operationPreviewKey) throw UI.error("local.tasks.controls.check_the_current_definition_first_675d86", {});
    await localSubmit('operation_search', d, false);
  } catch (e) {
    operationStatus(UI.errorText(e));
  }
};
const responseSaveBefore = $('response_save').onclick;
$('response_save').onclick = async () => {
  if (!responseRef?.task_id) return responseSaveBefore();
  try {
    await api('/api/local-display', {
      task_id: responseRef.task_id,
      display: responseDisplay()
    });
    responseStatus(UI.msg("local.tasks.controls.save_588001", {}));
  } catch (e) {
    responseStatus(UI.errorText(e), true);
  }
};
document.addEventListener('lab-workspace', localRefresh);
document.addEventListener('DOMContentLoaded', localRefresh);
localRefresh();
document.addEventListener('ui-language', localRender);
