"use strict";

/* Workspace paths and portable fixed tasks share the existing comparison UI. */
let portableDraftMetadata = new Map();
let portableDefinition = null,
  portablePreview = null,
  portableJob = null,
  portableSequence = 0,
  portableJobKind = null,
  portablePrepared = false;
function taskStatus(message, error = false) {
  UI.text($('task_status'), message);
  $('task_status').classList.toggle('error', error);
}
function workspaceSummary(data) {
  workspaceState = data;
  const index = data?.index || {};
  UI.text($('workspace_status'), UI.msg(index.available === false?'prep.indexInvalid':'prep.ready'));
  if(index.available===false && index.error){
    const detail=document.createElement('details'),caption=document.createElement('summary'),text=document.createElement('pre');
    UI.text(caption,UI.msg('prep.technical'));text.textContent=index.error;
    detail.append(caption,text);$('workspace_status').append(detail);
  }
  $('workspace_status').classList.toggle('error', index.available === false);
  if ($('workspace_preparation') && data?.preparation) DataPreparation.render($('workspace_preparation'),data.preparation);
  for (const button of document.querySelectorAll('[data-path-assign]')) button.hidden = !overview;
  $('task_export').disabled = !overview;
  if (!overview) {
    $('scope_workspace').hidden = true;
    UI.text($('active_case'), UI.msg("workspace.workspaceSummary.no_scope_selected_01d49f", {}));
    $('global_q').closest('details').open = true;
  }
}
async function initializeWorkspace() {
  try {
    workspaceSummary(await api('/api/workspace'));
  } catch (error) {
    UI.text($('workspace_status'), UI.errorText(error));
    $('workspace_status').classList.add('error');
  }
}
function taskConditionText(condition) {
  const c = condition.experiment,
    events = c.input_events || [],
    observations = c.observations || [];
  return UI.msg("workspace.taskConditionText.updates_input_events_observation_sets_9aa004", {
    p0: condition.name,
    p1: condition.role === 'extra' ? UI.msg("workspace.taskConditionText.message_1b9624", {}) : UI.msg("workspace.taskConditionText.condition_b7cc94", {}),
    p2: c.steps,
    p3: events.length,
    p4: observations.length,
    p5: c.intervention_events != null ? UI.msg("workspace.taskConditionText.intervention_61d833", {
      p0: c.intervention_events.length
    }) : UI.msg("workspace.taskConditionText.intervention_node_gain_e5afb3", {
      p0: (c.intervention_ids || []).length,
      p1: c.gain,
      p2: c.intervention_start,
      p3: c.intervention_stop
    })
  });
}
function renderTaskPreview(preview) {
  const definition = preview.definition || portableDefinition,
    scope = preview.scope || {},
    estimates = preview.estimates || {},
    errors = preview.errors || [];
  $('task_name').value = definition.name || '';
  $('task_preview_summary').innerHTML = `<div class="note">${UI.htmlText("workspace.renderTaskPreview.task_definition_scope_node_condition_ea1c6d", {
    p0: definition.name,
    p1: UI.numeric(definition.scope.body_ids.length, {}),
    p2: definition.conditions.length,
    p3: scope.internal_edges != null ? UI.join([' · ' + num(scope.internal_edges), UI.msg("workspace.renderTaskPreview.internal_edges_5b2d5b", {})]) : ''
  })}</div>` + definition.conditions.map(c => `<div class="note">${UI.html(taskConditionText(c))}</div>`).join('') + `<div class="note">${UI.htmlText("workspace.renderTaskPreview.baseline_intervention_51329e", {
    p0: preview.estimated_propagations ?? '—',
    p1: preview.estimated_baseline_propagations ?? '—',
    p2: preview.estimated_intervention_propagations ?? '—',
    p3: UI.numeric(preview.estimated_recording_bytes ?? 0, {})
  })}</div>` + (preview.existing_case_path ? `<div class="note">${UI.htmlText("workspace.renderTaskPreview.an_exact_matching_scope_exists_open_it_directly_c4a367", {})}</div>` : '') + (Object.keys(estimates).length ? `<details><summary>${UI.htmlText("workspace.renderTaskPreview.resource_estimate_8f22fc", {})}</summary><pre style="white-space:pre-wrap">${UI.html(JSON.stringify(estimates, null, 2))}</pre></details>` : '') + (preview.verification_required ? `<div class="note">${UI.htmlText("workspace.renderTaskPreview.different_index_instance_verify_compatibility_before_run_662dbd", {})}</div>` : '') + (preview.definition?.schema_version === 1 ? `<div class="note">${UI.htmlText("workspace.renderTaskPreview.legacy_task_has_no_content_fingerprint_original_index_in_61504e", {})}</div>` : '') + errors.map(e => `<div class="error">${UI.html(typeof e === 'string' ? e : JSON.stringify(e))}</div>`).join('');
  $('task_members_detail').innerHTML = `<div>${UI.htmlText("workspace.renderTaskPreview.members_28283e", {
    p0: definition.scope.body_ids.join(', ')
  })}</div>` + definition.conditions.map(item => {
    const c = item.experiment;
    return `<details><summary>${UI.htmlText("workspace.controls.constraints_11cc3d", {
      p0: item.name
    })}</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${UI.html(JSON.stringify({
      role: item.role,
      input_events: c.input_events,
      observations: c.observations,
      intervention_events: c.intervention_events,
      intervention_semantics_version: c.intervention_semantics_version,
      intervention_ids: c.intervention_ids,
      gain: c.gain,
      intervention_start: c.intervention_start,
      intervention_stop: c.intervention_stop,
      steps: c.steps,
      alpha: c.alpha,
      rho: c.rho,
      recording: item.recording,
      search_options: item.search_options
    }, null, 2))}</pre></details>`;
  }).join('');
  const compatible = preview.compatible !== false && !errors.length;
  portablePrepared = !!preview.existing_case_path && !preview.verification_required;
  UI.text($('task_prepare'), preview.verification_required ? UI.msg("workspace.renderTaskPreview.verify_prepare_scope_db2e0b", {}) : UI.msg("workspace.renderTaskPreview.prepare_scope_da7238", {}));
  $('task_preview').disabled = false;
  $('task_prepare').disabled = !compatible || preview.build_allowed === false || portablePrepared;
  $('task_open_scope').disabled = !compatible || !portablePrepared;
  $('task_run').disabled = !compatible || !portablePrepared;
  $('task_edit').disabled = !compatible || !portablePrepared;
  taskStatus(compatible ? preview.verification_required ? UI.msg("workspace.renderTaskPreview.scope_4ef273", {}) : UI.msg("workspace.renderTaskPreview.definition_check_request_not_run_1434bb", {}) : UI.msg("workspace.renderTaskPreview.definition_check_request_19fc8f", {}), !compatible);
}
async function previewPortableTask() {
  if (busy || !portableDefinition) return;
  const sequence = ++portableSequence;
  try {
    taskStatus(UI.msg("workspace.previewPortableTask.check_requesttask_definition_b02152", {}));
    const result = await api('/api/task-preview', {
      definition: portableDefinition
    });
    if (sequence !== portableSequence) return;
    portablePreview = result;
    portableDefinition = JSON.parse(JSON.stringify(result.definition || portableDefinition));
    renderTaskPreview(result);
  } catch (error) {
    if (sequence !== portableSequence) return;
    portablePreview = null;
    $('task_prepare').disabled = true;
    $('task_run').disabled = true;
    $('task_edit').disabled = true;
    $('task_open_scope').disabled = true;
    taskStatus(UI.errorText(error), true);
  }
}
function lockPortableTask(active) {
  busy = active;
  $('scope_workspace').inert = active;
  for (const id of ['task_load', 'task_export', 'task_preview', 'task_prepare', 'task_open_scope', 'task_run', 'task_edit', 'create_case', 'open_saved_case', 'open_saved_result']) $(id).disabled = active;
  $('task_cancel').disabled = !active;
  if (!active) {
    $('task_export').disabled = !overview;
    $('create_case').disabled = !scopePreview;
    $('task_preview').disabled = !portableDefinition;
    const usable = portablePreview && portablePreview.compatible !== false && !(portablePreview.errors || []).length;
    $('task_prepare').disabled = !usable || portablePreview.build_allowed === false || portablePrepared;
    $('task_open_scope').disabled = !usable || !portablePrepared;
    $('task_run').disabled = !usable || !portablePrepared;
    $('task_edit').disabled = !usable || !portablePrepared;
    document.dispatchEvent(new Event('lab-operation-idle'));
  }
}
async function openPortableScope() {
  if (busy || !portableDefinition) return false;
  try {
    const caseId = portablePreview?.existing_case_id;
    if (overview && caseId === overview.manifest.case_id) return true;
    if (window.confirmAnalysisScope && !window.confirmAnalysisScope(caseId)) return false;
    const next = await api('/api/open-task-scope', {
      ...(portableJobKind === 'prepare' && portableJob ? {
        job_id: portableJob
      } : {
        definition: portableDefinition
      })
    });
    activateOverview(next);
    await refreshSaved();
    taskStatus(UI.msg("workspace.openPortableScope.scope_open_conditionnot_run_11b10b", {}));
    return true;
  } catch (error) {
    taskStatus(UI.errorText(error), true);
    return false;
  }
}
function portableEditorConditions() {
  return portableDefinition.conditions.map(item => ({
    name: item.name,
    experiment: {
      ...JSON.parse(JSON.stringify(item.experiment)),
      intervention_group: item.experiment.intervention_events != null ? '__event_plan__' : item.experiment.intervention_ids.length ? '__all__' : '__fixed_no_intervention__'
    }
  }));
}
async function adoptPortableDraft() {
  try {
    if (!portableDefinition || busy) return;
    if (!(await openPortableScope())) return;
    if (dirty && !confirm(UI.msg("workspace.adoptPortableDraft.condition_save_edit_continue_3a8dd9", {}))) return;
    const items = portableEditorConditions();
    const eligible = new Set(candidateNodes('__all__').map(node => String(node.bodyId))),
      scopeMembers = new Set(overview.scope_nodes.map(node => String(node.bodyId))),
      outside = [...new Set(items.flatMap(item => item.experiment.intervention_events != null ? item.experiment.intervention_events.flatMap(event => event.type === 'node_gain' ? event.body_ids : event.edges.flat()) : item.experiment.intervention_ids).filter(id => !scopeMembers.has(String(id))))];
    if (outside.length) throw UI.errorValue(UI.join([UI.join([UI.msg("workspace.adoptPortableDraft.interventioneditcandidate_set_9a4d32", {}), outside.join(', ')]), UI.msg("workspace.adoptPortableDraft.task_definition_run_c3d939", {})]));
    portableDraftMetadata = new Map(portableDefinition.conditions.map(item => [item.name, {
      role: item.role,
      recording: JSON.parse(JSON.stringify(item.recording)),
      search_options: JSON.parse(JSON.stringify(item.search_options))
    }]));
    loadConditions(items);
    apply(items[0].experiment);
    applyRecording(portableDefinition.conditions[0].recording);
    if (portableDefinition.conditions[0].search_options) applySearchOptions(portableDefinition.conditions[0].search_options);
    changed();
    taskStatus(UI.msg("workspace.adoptPortableDraft.condition_edit_current_draft_bc7956", {}));
    $('protocol_panel').scrollIntoView({
      block: 'start'
    });
  } catch (error) {
    taskStatus(UI.errorText(error), true);
  }
}
async function pollPortableTask(jobId, sequence) {
  try {
    const job = await api('/api/task-job?' + new URLSearchParams({
      job_id: jobId
    }));
    if (sequence !== portableSequence || jobId !== portableJob) return;
    const progress = job.progress || {};
    taskStatus(UI.join([portableJobKind === 'prepare' ? UI.msg("workspace.pollPortableTask.scope_daa5a4", {}) : UI.msg("workspace.pollPortableTask.run_task_27289d", {}), " · ", UI.code(progress.phase || job.status), progress.completed != null ? ' · ' + progress.completed + '/' + (progress.total ?? '—') : '']));
    if (['running', 'pending'].includes(job.status)) {
      setTimeout(() => pollPortableTask(jobId, sequence), 600);
      return;
    }
    lockPortableTask(false);
    if (!job.result) {
      taskStatus(UI.jobText(job, UI.msg("workspace.pollPortableTask.complete_e71fef", {})), true);
      return;
    }
    if (portableJobKind === 'prepare') {
      if (job.result.status === 'complete' || job.result.status === 'completed' || job.result.case_path) {
        portablePrepared = true;
        await previewPortableTask();
        taskStatus(UI.msg("workspace.pollPortableTask.scope_20f655", {}));
      } else taskStatus(UI.msg("workspace.pollPortableTask.scope_complete_8c4856", {
        p0: UI.code(job.result.status),
        p1: job.result.error ? ' · ' + job.result.error : ''
      }), true);
    } else {
      const result = await api('/api/task-result', {
        job_id: jobId
      });
      if (sequence !== portableSequence) return;
      if (result.results?.length) renderComparison(result);
      const counts = result.simulations || result.counters || result,
        started = counts.total_started ?? counts.started ?? (counts.baseline_simulations ?? 0) + (counts.intervention_simulations ?? 0),
        completed = counts.total_completed ?? counts.completed ?? (counts.completed_baseline_simulations ?? 0) + (counts.completed_intervention_simulations ?? 0);
      taskStatus(UI.msg("workspace.pollPortableTask.condition_e5893f", {
        p0: UI.code(result.status || 'complete'),
        p1: result.results?.length || 0,
        p2: result.task_definition?.conditions?.length || result.conditions?.length || 0,
        p3: started || completed ? UI.join([UI.join([UI.join([UI.msg("workspace.pollPortableTask.start_9e3e4e", {}), started]), UI.msg("workspace.pollPortableTask.complete_cd7f9e", {})]), completed]) : ''
      }));
      $('comparison_status').scrollIntoView({
        block: 'center'
      });
    }
  } catch (error) {
    if (sequence !== portableSequence) return;
    lockPortableTask(false);
    taskStatus(UI.errorText(error), true);
  }
}
async function startPortableTask(kind) {
  if (busy || !portableDefinition || !portablePreview) return;
  try {
    if (kind === 'run') {
      if (!(await openPortableScope())) return;
      if (!overview) throw UI.error("workspace.startPortableTask.open_scope_6b7c66", {});
    }
    const sequence = ++portableSequence;
    portableJobKind = kind;
    lockPortableTask(true);
    taskStatus(kind === 'prepare' ? UI.msg("workspace.startPortableTask.scope_1dc4bb", {}) : UI.msg("workspace.startPortableTask.runpincondition_fac8bc", {}));
    const job = await api(kind === 'prepare' ? '/api/start-task-prepare' : '/api/start-task-run', {
      definition: portableDefinition
    });
    portableJob = job.job_id;
    pollPortableTask(portableJob, sequence);
  } catch (error) {
    lockPortableTask(false);
    taskStatus(UI.errorText(error), true);
  }
}
async function exportPortableTask() {
  if (busy || !overview) return;
  try {
    const mode = $('task_export_mode').value,
      payload = {
        name: $('task_name').value.trim() || overview.manifest.case_name
      };
    if (mode === 'source') {
      if (!analysisCurrent?.source) throw UI.error("workspace.exportPortableTask.select_analysisplan_240be0", {});
      payload.source = JSON.parse(JSON.stringify(analysisCurrent.source));
    } else if (mode === 'comparison') {
      if (!comparison) throw UI.error("workspace.exportPortableTask.open_run_comparison_3187b0", {});
      if (!comparison.comparison_id) throw UI.error("workspace.exportPortableTask.comparison_open_savecomparison_0bda12", {});
      payload.source = {
        kind: 'comparison',
        comparison_id: comparison.comparison_id
      };
      payload.all_conditions = true;
    } else {
      payload.conditions = portableDraftConditions(conditions.length ? conditions : [{
        name: UI.t("workspace.exportPortableTask.condition_b14319"),
        experiment: cfg()
      }]);
    }
    const response = await api('/api/task-export', payload),
      definition = response.definition || response;
    const file = new Blob([JSON.stringify(definition, null, 2) + '\n'], {
        type: 'application/json'
      }),
      url = URL.createObjectURL(file),
      link = document.createElement('a');
    link.href = url;
    link.download = (definition.name || 'task').replace(/[\\/:*?"<>|]/g, '_') + '.json';
    link.click();
    URL.revokeObjectURL(url);
    taskStatus(UI.msg("workspace.exportPortableTask.task_definition_198075", {}));
  } catch (error) {
    taskStatus(UI.errorText(error), true);
  }
}
$('task_load').onclick = () => $('task_file').click();
$('task_file').onchange = async () => {
  try {
    if (busy) throw UI.error("workspace.controls.stop_542334", {});
    const file = $('task_file').files[0];
    if (!file) return;
    if (file.size > 16777216) throw UI.error("workspace.controls.task_definition_16_mib_086f43", {});
    const definition = JSON.parse(await file.text());
    portableSequence++;
    portableDefinition = definition;
    portablePreview = null;
    portablePrepared = false;
    portableJob = null;
    portableJobKind = null;
    $('task_definition_controls').open = true;
    await previewPortableTask();
  } catch (error) {
    taskStatus(UI.errorText(error), true);
  } finally {
    $('task_file').value = '';
  }
};
$('task_export').onclick = exportPortableTask;
$('task_preview').onclick = previewPortableTask;
$('task_prepare').onclick = () => startPortableTask('prepare');
$('task_open_scope').onclick = openPortableScope;
$('task_run').onclick = () => startPortableTask('run');
$('task_edit').onclick = adoptPortableDraft;
$('task_cancel').onclick = async () => {
  try {
    if (!portableJob) return;
    await api('/api/cancel-task', {
      job_id: portableJob
    });
    $('task_cancel').disabled = true;
    taskStatus(UI.msg("workspace.controls.cancel_keepcomplete_e434da", {}));
  } catch (error) {
    taskStatus(UI.errorText(error), true);
  }
};
document.addEventListener('lab-workspace', event => workspaceSummary(event.detail));
document.addEventListener('lab-case', () => {
  for (const button of document.querySelectorAll('[data-path-assign]')) button.hidden = false;
  $('task_export').disabled = false;
});
function portableConstraintText(result, name) {
  const item = result.constraints?.find(c => c.name === name),
    row = item?.constraints?.condition_results?.[0];
  if (!row) return UI.msg("workspace.portableConstraintText.no_constraints_035d9c", {});
  const target = row.target_constraint,
    protectedItems = Object.entries(row.protected_constraints || {});
  return (target ? UI.html(UI.join([target.observation, " ≥ ", searchLossText(target.minimum, target.metric), " · ", target.satisfied ? UI.msg("workspace.portableConstraintText.satisfied_4e8156", {}) : target.defined === false ? UI.msg("workspace.portableConstraintText.undefined_2c744a", {}) : UI.msg("workspace.portableConstraintText.not_satisfied_3b34e0", {})])) : '') + protectedItems.map(([label, c]) => `<br>${UI.html(label)} ≤ ${UI.html(searchLossText(c.limit, c.metric))} · ${UI.html(c.satisfied ? UI.msg("workspace.controls.satisfied_4e8156", {}) : c.defined === false ? UI.msg("workspace.controls.undefined_2c744a", {}) : UI.msg("workspace.controls.exceeded_314600", {}))}`).join('') + `<br>${UI.html(item.role === 'extra' ? UI.msg("workspace.portableConstraintText.message_1b9624", {}) : UI.msg("workspace.portableConstraintText.condition_b7cc94", {}))} · ${UI.html(row.feasible ? UI.msg("workspace.portableConstraintText.allsatisfied_c3dc37", {}) : esc((row.violations || []).join(' / ')))}`;
}
function portableDraftConditions(items) {
  return items.map(item => {
    const metadata = portableDraftMetadata.get(item.name) || {
      role: 'decision',
      recording: recordingPolicy(),
      search_options: searchOptions()
    };
    return JSON.parse(JSON.stringify({
      ...item,
      ...metadata
    }));
  });
}
document.addEventListener('lab-case', () => portableDraftMetadata.clear());
// Export display state never enters comparison identity or experiment definitions.
let reportPreviewHandle = null, reportSequence = 0;
let reportDisplay = null;
function reportRequest() {
  if (!comparison?.comparison_id) throw UI.error('workspace.reportRequest.open_save_pincomparison_0646b5');
  const selected=$('report_condition_mode').value === 'selected';
  if (selected && curveSource?.comparison_id !== comparison.comparison_id) throw UI.error('workspace.reportRequest.open_comparison_selectall_conditions_5eb77a');
  const condition_names=selected ? [...conditionSelected].map(k=>comparison.rows[k]?.name).filter(Boolean) : null;
  if (selected && !condition_names.length) throw UI.error('workspace.reportRequest.select_completecondition_40f0bb');
  return {comparison_id:comparison.comparison_id,condition_names,language:UI.preferences.language};
}
function reportMatches(request) {
  try { return JSON.stringify(request) === JSON.stringify(reportRequest()); } catch { return false; }
}
function renderReportDisplay() {
  if (!reportDisplay) return;
  if (reportDisplay.error) { UI.text($('report_status'),reportDisplay.error); return; }
  const language=reportDisplay.language;
  const value=UI.msg(reportDisplay.phase==='exported' ? 'report.exported' : 'report.preview', {
    language,size:UI.numeric(reportDisplay.total_bytes)
  });
  UI.text($('report_status'),value);
}
function invalidateReportPreview(clear=false) {
  reportSequence++;
  reportPreviewHandle=null;
  $('report_export').disabled=true;
  document.getElementById('report_html_preview')?.remove();
  if (clear) {
    reportDisplay=null;
    UI.text($('report_status'),'');
    $('report_links').replaceChildren();
  } else if (reportDisplay && reportDisplay.phase !== 'exported' && !reportDisplay.error) {
    UI.text($('report_status'),UI.msg('report.previewRequired'));
  } else renderReportDisplay();
}
$('report_preview').onclick = async () => {
  if (busy) return;
  const sequence=++reportSequence;
  reportPreviewHandle=null;
  $('report_export').disabled=true;
  try {
    const request=reportRequest();
    const result=await api('/api/report-preview',request);
    if (sequence !== reportSequence || !reportMatches(request)) return;
    reportPreviewHandle={...request,preview_id:result.preview_id};
    reportDisplay={...result,phase:'previewed'};
    renderReportDisplay();
    $('report_export').disabled=false;
    $('report_links').replaceChildren();
    document.getElementById('report_html_preview')?.remove();
    const preview=document.createElement('details');
    preview.id='report_html_preview';preview.className='report-preview';preview.open=true;
    const caption=document.createElement('summary');
    UI.text(caption,UI.msg('report.title'));
    const frame=document.createElement('iframe');
    frame.setAttribute('sandbox','');
    UI.attr(frame,'title',UI.msg('report.title'));
    frame.srcdoc=result.preview_html;
    preview.append(caption,frame);
    $('report_status').after(preview);
  } catch(error) {
    if (sequence !== reportSequence) return;
    reportDisplay={error:UI.errorText(error)};
    renderReportDisplay();
  }
};
$('report_export').onclick = async () => {
  if (busy || !reportPreviewHandle) return;
  const handle=reportPreviewHandle, sequence=++reportSequence;
  $('report_export').disabled=true;
  try {
    const {preview_id,...request}=handle;
    if (!reportMatches(request)) throw UI.error('report.previewRequired');
    const result=await api('/api/report-export',handle);
    if (sequence !== reportSequence || !reportMatches(request)) return;
    $('report_links').replaceChildren();
    for (const [name,url] of Object.entries(result.files)) {
      const link=document.createElement('a');link.href=url;link.download=name;
      UI.text(link,UI.join([name,' · ',UI.numeric(result.sizes[name]),' B']));
      $('report_links').append(link);
    }
    reportDisplay={...result,phase:'exported'};
    renderReportDisplay();
  } catch(error) {
    if (sequence !== reportSequence) return;
    reportDisplay={error:UI.errorText(error)};
    renderReportDisplay();
    $('report_export').disabled=!reportPreviewHandle;
  }
};
$('report_condition_mode').onchange=()=>invalidateReportPreview(true);
document.addEventListener('lab-case',()=>invalidateReportPreview(true));
document.addEventListener('lab-comparison',()=>invalidateReportPreview(true));
document.addEventListener('lab-artifact-open',()=>invalidateReportPreview(true));
document.addEventListener('lab-comparison-selection',()=>{if($('report_condition_mode').value==='selected')invalidateReportPreview();});
$('curve_conditions').addEventListener('change',()=>{if($('report_condition_mode').value==='selected')invalidateReportPreview();});
document.addEventListener('ui-language',()=>{
  const refresh=reportDisplay?.phase==='previewed' && document.getElementById('report_html_preview');
  invalidateReportPreview();
  if (refresh) $('report_preview').onclick();
});
