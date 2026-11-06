"use strict";

/* Timing exploration keeps the node set fixed; selecting stored rows performs no simulation. */
let timingCachedConditions = null,
  timingCachedOptions = null,
  timingPreview = null,
  timingPreviewSignature = null,
  timingReport = null,
  timingJobId = null,
  timingArtifactId = null,
  timingRunning = false,
  timingSequence = 0,
  timingRequestSignature = null,
  timingSelected = null,
  timingCurveChanged = false,
  timingRowsPage = 0;
let timingCurrentName = null;
const timingConditionKeys = new Set(['current']),
  timingLocks = new Map();
function timingStatus(message, error = false) {
  UI.text($('timing_status'), message);
  $('timing_status').classList.toggle('error', error);
}
function timingChoices() {
  if (timingCachedConditions) return timingCachedConditions.map(c => ({
    key: 'saved:' + c.name,
    ...c
  }));
  let name = timingCurrentName || UI.t("timing.timingChoices.condition_b14319");
  while (conditions.some(c => c.name === name)) name += ' +';
  timingCurrentName = name;
  return [{
    key: 'current',
    name,
    experiment: cfg()
  }, ...conditions.map(c => ({
    key: 'condition:' + c.name,
    ...c
  }))];
}
function selectedTimingConditions() {
  return timingChoices().filter(c => timingConditionKeys.has(c.key)).map(({
    name,
    experiment
  }) => ({
    name,
    experiment: JSON.parse(JSON.stringify(experiment))
  }));
}
function timingOptions() {
  return JSON.parse(JSON.stringify(timingCachedOptions || searchOptions()));
}
function timingIntegerList(id, positive = false) {
  const tokens = $(id).value.trim().split(/[\s,，]+/).filter(Boolean);
  if (!tokens.length || tokens.some(value => !/^\d+$/.test(value)) || tokens.some(value => !Number.isSafeInteger(Number(value)) || Number(value) < (positive ? 1 : 0))) throw Error(positive ? UI.msg("timing.timingIntegerList.duration_3aea84", {}) : UI.msg("timing.timingIntegerList.start_update_2df526", {}));
  const values = tokens.map(Number);
  return [...new Set(values)].sort((a, b) => a - b);
}
function timingPayload() {
  const selected = selectedTimingConditions();
  if (selected.length < 1 || selected.length > 12) throw UI.error("timing.timingPayload.timing_exploration_select_1_12_f8287c", {});
  return {
    conditions: selected,
    body_ids: parseBodyIds($('timing_ids').value),
    starts: timingIntegerList('timing_starts'),
    durations: timingIntegerList('timing_durations', true),
    options: timingOptions()
  };
}
function timingProtocolIdentity(c) {
  return {
    steps: c.steps,
    alpha: c.alpha,
    rho: c.rho,
    gain: c.gain,
    input_events: canonicalEvents(c),
    observations: canonicalObservations(c)
  };
}
function timingSignature(payload = timingPayload(), caseId = overview.manifest.case_id) {
  return JSON.stringify({
    case_id: caseId,
    conditions: payload.conditions.map(c => ({
      name: c.name,
      experiment: timingProtocolIdentity(c.experiment)
    })).sort((a, b) => a.name.localeCompare(b.name)),
    body_ids: payload.body_ids.slice().sort(),
    starts: payload.starts.slice().sort((a, b) => a - b),
    durations: payload.durations.slice().sort((a, b) => a - b),
    options: normalizedSearchOptions(payload.options, {
      experiment: payload.conditions[0].experiment
    })
  });
}
function timingReportSignature(report) {
  return timingSignature({
    conditions: report.conditions,
    body_ids: report.body_ids,
    starts: report.grid.starts,
    durations: report.grid.durations,
    options: report.search_options
  }, report.case_id);
}
function timingMatchesCurrent() {
  try {
    return !!timingReport && timingReportSignature(timingReport) === timingSignature();
  } catch (_) {
    return false;
  }
}
function timingSaveEnabled() {
  return !busy && !timingRunning && !!timingReport && timingMatchesCurrent() && (!!timingJobId || !!timingArtifactId && timingCurveChanged);
}
function refreshTimingChoices() {
  const choices = timingChoices(),
    valid = new Set(choices.map(c => c.key));
  for (const key of timingConditionKeys) if (!valid.has(key)) timingConditionKeys.delete(key);
  $('timing_conditions').innerHTML = choices.map(c => `<label class="pill"><input data-timing-condition="${esc(c.key)}" type="checkbox" ${timingConditionKeys.has(c.key) ? 'checked' : ''}>${UI.html(c.name)}</label>`).join('');
  updateTimingSummary();
}
function updateTimingSummary() {
  try {
    const selected = selectedTimingConditions(),
      options = timingOptions();
    UI.text($('timing_protocol_summary'), UI.msg("timing.updateTimingSummary.target_budget_combination_combinationrun_3ba526", {
      p0: timingCachedConditions ? UI.msg("timing.updateTimingSummary.save_74cd42", {}) : UI.msg("timing.updateTimingSummary.current_protocol_compare_conditions_4a9245", {}),
      p1: selected.length,
      p2: timingCachedOptions ? UI.msg("timing.updateTimingSummary.save_constraints_1e1bcd", {}) : UI.msg("timing.updateTimingSummary.searchconstraints_03eb7c", {}),
      p3: options.target_output || UI.msg("timing.updateTimingSummary.select_1182c5", {}),
      p4: options.target_metric === 'absolute' ? UI.msg("timing.updateTimingSummary.message_d22418", {}) : UI.msg("timing.updateTimingSummary.message_76b164", {}),
      p5: options.max_evaluations
    }));
    $('timing_protocol_details').innerHTML = selected.map(c => `<div style="margin-bottom:8px"><b>${UI.html(c.name)}</b>${UI.htmlText("timing.controls.updates_gain_7b1c70", {
      p0: c.experiment.steps,
      p1: c.experiment.gain,
      p2: protocolEvents(c.experiment).map(e => `<div>${UI.htmlText("timing.controls.message_9ad48b", {
        p0: e.start,
        p1: e.stop,
        p2: e.amplitude,
        p3: e.body_ids.join(', ')
      })}</div>`).join(''),
      p3: canonicalObservations(c.experiment).map(o => `<div>${UI.htmlText("timing.controls.observation_01868c", {
        p0: o.name,
        p1: o.evaluation_window.start,
        p2: o.evaluation_window.stop,
        p3: o.body_ids.join(', ')
      })}</div>`).join('')
    })}</div>`).join('') + Object.entries(options.protected_limits || {}).map(([name, spec]) => `<div>${UI.htmlText("timing.controls.protection_53d8fc", {
      p0: name,
      p1: spec.metric === 'absolute' ? UI.msg("timing.controls.message_d22418", {}) : UI.msg("timing.controls.message_76b164", {}),
      p2: searchLossText(spec.max_loss, spec.metric)
    })}</div>`).join('');
  } catch (_) {
    UI.text($('timing_protocol_summary'), UI.msg("timing.updateTimingSummary.message_1067cd", {}));
  }
}
function invalidateTiming() {
  timingSequence++;
  timingPreview = null;
  timingPreviewSignature = null;
  $('timing_run').disabled = true;
  $('timing_save').disabled = true;
  if (timingReport && !timingMatchesCurrent()) timingStatus(UI.msg("timing.invalidateTiming.current_protocol_node_set_scope_constraints_58668e", {}));
  updateTimingSummary();
}
function timingEntries(report = timingReport || timingPreview) {
  return report?.entries || report?.grid.execution_order.map(e => ({
    ...e,
    status: 'not_run'
  })) || [];
}
function timingEntryLabel(entry) {
  if (entry.status === 'completed') return entry.undefined_condition_names?.length ? UI.msg("timing.timingEntryLabel.complete_metricundefined_18209c", {}) : entry.feasible ? UI.msg("timing.timingEntryLabel.complete_satisfiedconstraints_77e4db", {}) : UI.msg("timing.timingEntryLabel.complete_not_satisfied_d7a950", {});
  return {
    not_run: UI.msg("timing.timingEntryLabel.run_62cdc8", {}),
    cancelled: UI.msg("timing.timingEntryLabel.cancelled_a37778", {}),
    failed: UI.msg("timing.timingEntryLabel.failed_28384d", {})
  }[entry.status] || entry.status;
}
function timingCounters(report) {
  UI.text($('timing_counts'), UI.msg("timing.timingCounters.complete_baseline_intervention_baseline_intervention_7a9907", {
    p0: report.evaluations ?? 0,
    p1: report.budget,
    p2: report.attempted_evaluations ?? 0,
    p3: report.completed_baseline_simulations ?? 0,
    p4: report.baseline_simulations ?? 0,
    p5: report.completed_intervention_simulations ?? 0,
    p6: report.intervention_simulations ?? 0,
    p7: report.completed_curve_baseline_simulations ?? 0,
    p8: report.curve_baseline_simulations ?? 0,
    p9: report.completed_curve_intervention_simulations ?? 0,
    p10: report.curve_intervention_simulations ?? 0
  }));
}
function renderTimingGrid(reset = false) {
  const report = timingReport || timingPreview;
  if (!report) return;
  const entries = timingEntries(report),
    lookup = new Map(entries.map((e, k) => [e.start + ':' + e.duration, {
      entry: e,
      index: k
    }]));
  for (const [id, values] of [['timing_grid_start_page', report.grid.starts], ['timing_grid_duration_page', report.grid.durations]]) {
    const previous = reset ? 0 : Number($(id).value) || 0;
    $(id).disabled = false;
    $(id).innerHTML = Array.from({
      length: Math.ceil(values.length / 20)
    }, (_, k) => `<option value="${k}" ${k === previous ? 'selected' : ''}>${values[k * 20]}–${values[Math.min(values.length - 1, k * 20 + 19)]}</option>`).join('');
  }
  const starts = report.grid.starts.slice((Number($('timing_grid_start_page').value) || 0) * 20, (Number($('timing_grid_start_page').value) || 0) * 20 + 20),
    durations = report.grid.durations.slice((Number($('timing_grid_duration_page').value) || 0) * 20, (Number($('timing_grid_duration_page').value) || 0) * 20 + 20);
  $('timing_grid_head').innerHTML = `<tr><th>${UI.htmlText("timing.renderTimingGrid.start_duration_d45924", {})}</th>` + durations.map(duration => '<th>' + duration + '</th>').join('') + '</tr>';
  $('timing_grid_rows').innerHTML = starts.map(start => `<tr><th>${start}</th>${durations.map(duration => {
    const value = lookup.get(start + ':' + duration);
    if (!value) return `<td>${UI.htmlText("timing.controls.outside_scope_789ca1", {})}</td>`;
    const e = value.entry;
    return `<td><button class="linkbtn" data-timing-entry="${value.index}" ${UI.htmlAttribute("title", "editor.interval", {start:e.start,stop:e.stop})}>${UI.html(timingEntryLabel(e))}${e.status === 'completed' ? '<br>' + searchLossText(e.worst_target_loss, report.search_options.target_metric) : ''}</button></td>`;
  }).join('')}</tr>`).join('');
  const maxPage = Math.max(0, Math.ceil(entries.length / 100) - 1);
  timingRowsPage = Math.min(timingRowsPage, maxPage);
  $('timing_rows').innerHTML = entries.slice(timingRowsPage * 100, timingRowsPage * 100 + 100).map((entry, k) => `<tr><td>${entry.start}</td><td>${entry.duration}</td><td>${entry.stop}</td><td>${UI.html(timingEntryLabel(entry))}</td><td>${entry.status === 'completed' ? searchLossText(entry.worst_target_loss, report.search_options.target_metric) : '—'}</td><td>${UI.html(entry.failed_condition_names?.join(' / ') || (entry.error ? UI.jobText(entry) : '—'))}</td><td><button class="linkbtn" data-timing-entry="${timingRowsPage * 100 + k}">${UI.htmlText("timing.controls.view_db8db0", {})}</button></td></tr>`).join('');
  UI.text($('timing_rows_page'), UI.msg("timing.renderTimingGrid.combination_20_c2ec17", {
    p0: timingRowsPage + 1,
    p1: maxPage + 1,
    p2: entries.length
  }));
  $('timing_rows_prev').disabled = timingRowsPage === 0;
  $('timing_rows_next').disabled = timingRowsPage === maxPage;
}
function timingSelectedEntry() {
  return timingReport && timingSelected ? timingReport.entries.find(e => e.start === timingSelected.start && e.duration === timingSelected.duration) : null;
}
function selectTimingEntry(index) {
  const entry = timingEntries()[index];
  if (!entry) return;
  timingSelected = {
    start: entry.start,
    duration: entry.duration
  };
  UI.text($('timing_selected'), UI.msg("timing.selectTimingEntry.duration_pinnode_b8b8a1", {
    p0: entry.start,
    p1: entry.stop,
    p2: entry.duration,
    p3: timingEntryLabel(entry),
    p4: (timingReport || timingPreview).body_ids.join(', ')
  }));
  clearSearchContext('timing');
  clearSearchDiagnostics('timing');
  $('timing_curves').disabled = busy || entry.status !== 'completed' || !timingReport || timingReport.case_id !== overview.manifest.case_id || !timingJobId && !timingArtifactId;
  UI.text($('timing_curve_status'), entry.status === 'completed' ? UI.msg("timing.selectTimingEntry.selection_keepmetric_854b65", {}) : UI.jobText(entry, UI.msg("timing.selectTimingEntry.message_078710", {})));
  if (entry.status !== 'completed' || !timingReport) return;
  const explanations = (entry.condition_results || []).map(c => c.explanation).filter(Boolean),
    context = {
      conditions: explanations.map(e => ({
        name: e.name,
        target: e.target,
        protected: e.protected
      }))
    };
  const evidence = {
    kind: 'joint_plan_evaluation',
    conditions: timingReport.conditions,
    search_options: timingReport.search_options,
    constraint_context: context,
    search_diagnostics: {
      status: 'fixed_evaluation',
      termination_reason: 'fixed_plan_evaluated',
      best: {
        condition_results: explanations
      },
      facts: ['fixed_plan_not_optimized']
    }
  };
  renderSearchEvidence(evidence, 'timing', !timingJobId);
  renderSearchDiagnostics(evidence, 'timing', !timingJobId, {
    body_ids: timingReport.body_ids,
    condition_results: entry.condition_results
  });
}
async function previewTiming() {
  if (busy || searchRunning) return;
  const sequence = ++timingSequence;
  try {
    const payload = timingPayload(),
      signature = timingSignature(payload);
    $('timing_preview').disabled = true;
    timingStatus(UI.msg("timing.previewTiming.node_scope_93f53b", {}));
    const result = await api('/api/timing-preview', payload);
    if (sequence !== timingSequence || signature !== timingSignature()) return;
    timingPreview = result;
    timingPreviewSignature = signature;
    timingReport = null;
    timingSelected = null;
    timingRowsPage = 0;
    renderTimingGrid(true);
    $('timing_run').disabled = !result.compatible;
    UI.text($('timing_counts'), UI.msg("timing.previewTiming.pinnode_combination_budget_baseline_intervention_84b925", {
      p0: result.fixed_node_count,
      p1: result.grid.combination_count,
      p2: result.estimated_evaluations,
      p3: result.estimated_baseline_simulations,
      p4: result.estimated_intervention_simulations
    }));
    timingStatus(UI.msg("timing.previewTiming.scope_b569a4", {}));
    clearSearchContext('timing');
    clearSearchDiagnostics('timing');
    $('timing_curves').disabled = true;
    $('timing_save').disabled = true;
  } catch (error) {
    if (sequence === timingSequence) timingStatus(UI.errorText(error), true);
  } finally {
    if (sequence === timingSequence) $('timing_preview').disabled = false;
  }
}
function lockTiming(active) {
  if (active) {
    busy = true;
    timingRunning = true;
    for (const id of ['experiment', 'protocol_panel', 'global_panel', 'pathway_panel', 'search_panel', 'joint_search_panel', 'scope_comparison_panel', 'timing_conditions']) {
      timingLocks.set('inert:' + id, $(id).inert);
      $(id).inert = true;
    }
    for (const id of ['run', 'baseline', 'load', 'export', 'save', 'compare_conditions', 'save_comparison', 'add_condition', 'clear_conditions', 'search_start', 'search_cancel', 'search_save', 'search_context_check', 'joint_preview', 'joint_context_check', 'joint_start', 'joint_save', 'joint_evaluate', 'timing_preview', 'timing_run', 'timing_save', 'timing_curves', 'timing_use_current', 'timing_use_options', 'timing_use_selection', 'timing_use_joint', 'timing_ids', 'timing_starts', 'timing_durations']) {
      timingLocks.set('disabled:' + id, $(id).disabled);
      $(id).disabled = true;
    }
    $('timing_cancel').disabled = false;
  } else {
    busy = false;
    timingRunning = false;
    for (const [key, value] of timingLocks) {
      const [field, id] = key.split(':');
      $(id)[field] = value;
    }
    timingLocks.clear();
    $('timing_cancel').disabled = true;
    let signature = null;
    try {
      signature = timingSignature();
    } catch (_) {}
    $('timing_run').disabled = !timingPreview?.compatible || timingPreviewSignature !== signature;
    $('timing_save').disabled = !timingSaveEnabled();
    const selected = timingSelectedEntry();
    $('timing_curves').disabled = !selected || selected.status !== 'completed' || !timingJobId && !timingArtifactId;
    $('save_comparison').disabled = !canSaveComparison();
    scheduleCandidatePreview();
  }
}
async function startTiming() {
  if (busy || searchRunning) return;
  try {
    const payload = timingPayload(),
      signature = timingSignature(payload);
    if (!timingPreview?.compatible || signature !== timingPreviewSignature) throw UI.error("timing.startTiming.scope_fcf3fa", {});
    timingRequestSignature = signature;
    timingArtifactId = null;
    timingCurveChanged = false;
    timingReport = null;
    timingSelected = null;
    clearSearchContext('timing');
    clearSearchDiagnostics('timing');
    lockTiming(true);
    timingStatus(UI.msg("timing.startTiming.starttiming_exploration_293413", {}));
    const started = await api('/api/timing-explore', payload);
    timingJobId = started.job_id;
    pollTiming(timingJobId);
  } catch (error) {
    lockTiming(false);
    timingStatus(UI.errorText(error), true);
  }
}
async function pollTiming(id) {
  try {
    const snapshot = await api('/api/timing-explore?' + new URLSearchParams({
      job_id: id
    }));
    if (timingJobId !== id) return;
    if (snapshot.status === 'running') {
      const p = snapshot.progress || {};
      timingStatus(UI.msg("timing.pollTiming.timing_exploration_complete_2ba84e", {
        p0: p.evaluations ?? p.completed ?? 0,
        p1: p.budget ?? timingPreview?.budget ?? '—',
        p2: p.current_interval?.start ?? '—',
        p3: p.current_interval?.stop ?? '—'
      }));
      setTimeout(() => pollTiming(id), 700);
      return;
    }
    lockTiming(false);
    if (!snapshot.result) {
      timingStatus(UI.jobText(snapshot, UI.msg("timing.pollTiming.timing_explorationfailed_b64b44", {})), true);
      return;
    }
    renderTimingReport(snapshot.result, false);
    $('timing_save').disabled = !timingSaveEnabled();
  } catch (error) {
    if (timingJobId !== id) return;
    lockTiming(false);
    timingStatus(UI.errorText(error), true);
  }
}
function renderTimingReport(report, saved = false) {
  timingReport = report;
  timingCounters(report);
  renderTimingGrid(true);
  const labels = {
    complete: UI.msg("timing.renderTimingReport.complete_bb88ba", {}),
    budget_exhausted: UI.msg("timing.renderTimingReport.budget_exhausted_7ae4d2", {}),
    cancelled: UI.msg("timing.renderTimingReport.cancelled_a37778", {}),
    failed: UI.msg("timing.renderTimingReport.failed_a1244b", {})
  };
  timingStatus(UI.join([saved ? UI.msg("timing.renderTimingReport.save_92ce37", {}) : '', labels[report.status] || report.status, !timingMatchesCurrent() ? UI.msg("timing.renderTimingReport.message_c33b67", {}) : '', report.error ? ' · ' + report.error : '']));
  $('timing_save').disabled = !timingSaveEnabled();
  const selected = timingSelectedEntry();
  if (selected) selectTimingEntry(report.entries.indexOf(selected));else {
    UI.text($('timing_selected'), UI.msg("timing.renderTimingReport.select_view_condition_f34ade", {}));
    $('timing_curves').disabled = true;
  }
}
async function requestTimingCurves() {
  if (busy || searchRunning) return;
  const selected = timingSelectedEntry();
  if (!selected || selected.status !== 'completed') return;
  try {
    lockTiming(true);
    $('timing_cancel').disabled = true;
    UI.text($('timing_curve_status'), UI.msg("timing.requestTimingCurves.compute_selected_interval_curves_524bd6", {}));
    const result = await api('/api/timing-curves', {
      ...(timingArtifactId ? {
        artifact_id: timingArtifactId
      } : {
        job_id: timingJobId
      }),
      start: selected.start,
      duration: selected.duration
    });
    if (result.timing_report) {
      timingCurveChanged = true;
      renderTimingReport(result.timing_report, !timingJobId);
    }
    const labeled = {
      ...result,
      rows: result.rows.map(row => ({
        ...row,
        name_display: {key: "timing.controls.message_67b8cd", params: {
          p0: selected.start,
          p1: selected.stop,
          p2: row.name
        }}
      }))
    };
    renderComparison(labeled);
    UI.text($('resultstate'), UI.msg("timing.requestTimingCurves.pinnode_5e3f35", {
      p0: selected.start,
      p1: selected.stop
    }));
    $('save').disabled = true;
    UI.text($('timing_curve_status'), UI.msg("timing.requestTimingCurves.multi_condition_comparison_save_ec2120", {}));
  } catch (error) {
    let refreshed = false;
    try {
      const source = timingArtifactId ? {
          artifact_id: timingArtifactId
        } : {
          job_id: timingJobId
        },
        snapshot = await api('/api/timing-report?' + new URLSearchParams(source)),
        updated = snapshot.result || snapshot.report || snapshot;
      const counters = ['curve_baseline_simulations', 'completed_curve_baseline_simulations', 'curve_intervention_simulations', 'completed_curve_intervention_simulations'];
      timingCurveChanged = timingCurveChanged || counters.some(key => (updated[key] ?? 0) !== (timingReport?.[key] ?? 0));
      renderTimingReport(updated, !timingJobId);
      refreshed = true;
    } catch (_) {}
    UI.text($('timing_curve_status'), UI.join([UI.errorText(error), refreshed ? UI.msg("timing.requestTimingCurves.message_7ae12b", {}) : UI.msg("timing.requestTimingCurves.message_1006ed", {})]));
  } finally {
    lockTiming(false);
    if (comparison?.timing_evaluation) $('save').disabled = true;
  }
}
function openTiming(saved) {
  const report = saved.result;
  timingSequence++;
  timingJobId = null;
  timingArtifactId = saved.artifact_id || saved.id || null;
  timingCurveChanged = false;
  timingPreview = null;
  timingPreviewSignature = null;
  timingCachedConditions = JSON.parse(JSON.stringify(report.conditions));
  timingCachedOptions = JSON.parse(JSON.stringify(report.search_options));
  timingConditionKeys.clear();
  timingCachedConditions.forEach(c => timingConditionKeys.add('saved:' + c.name));
  $('timing_ids').value = report.body_ids.join(', ');
  $('timing_starts').value = report.grid.starts.join(', ');
  $('timing_durations').value = report.grid.durations.join(', ');
  timingSelected = null;
  timingRowsPage = 0;
  refreshTimingChoices();
  clearSearchContext('timing');
  clearSearchDiagnostics('timing');
  renderTimingReport(report, true);
  $('timing_save').disabled = true;
  $('timing_run').disabled = true;
  $('timing_cancel').disabled = true;
  UI.text($('timing_curve_status'), UI.msg("timing.openTiming.opensavemetric_38b71b", {}));
}
$('timing_preview').onclick = previewTiming;
$('timing_run').onclick = startTiming;
$('timing_curves').onclick = requestTimingCurves;
$('timing_cancel').onclick = async () => {
  try {
    await api('/api/cancel-timing', {
      job_id: timingJobId
    });
    $('timing_cancel').disabled = true;
    timingStatus(UI.msg("timing.controls.cancel_keep_complete_fdf07b", {}));
  } catch (error) {
    timingStatus(UI.errorText(error), true);
  }
};
$('timing_save').onclick = async () => {
  if (!timingSaveEnabled()) return;
  $('timing_save').disabled = true;
  try {
    const saved = await api('/api/save-timing', {
      ...(timingArtifactId ? {
        artifact_id: timingArtifactId
      } : {
        job_id: timingJobId
      })
    });
    timingStatus(UI.join([UI.msg("timing.controls.timing_exploration_save_b65b0d", {}), saved.folder]));
    document.dispatchEvent(new Event('lab-saved'));
  } catch (error) {
    timingStatus(UI.errorText(error), true);
  } finally {
    $('timing_save').disabled = !timingSaveEnabled();
  }
};
$('timing_use_selection').onclick = () => {
  if (busy) return;
  $('timing_ids').value = currentSelectionIds().join(', ');
  invalidateTiming();
};
$('timing_use_joint').onclick = () => {
  if (busy) return;
  if (!jointSelectedPlan) {
    timingStatus(UI.msg("timing.controls.selectjoint_search_plan_07135f", {}), true);
    return;
  }
  $('timing_ids').value = jointSelectedPlan.body_ids.join(', ');
  invalidateTiming();
};
$('timing_use_current').onclick = () => {
  if (busy) return;
  timingCachedConditions = null;
  timingConditionKeys.clear();
  timingConditionKeys.add('current');
  refreshTimingChoices();
  invalidateTiming();
};
$('timing_use_options').onclick = () => {
  if (busy) return;
  timingCachedOptions = null;
  invalidateTiming();
};
for (const id of ['timing_ids', 'timing_starts', 'timing_durations']) $(id).addEventListener('input', invalidateTiming);
$('search_panel').addEventListener('input', invalidateTiming);
$('timing_rows_prev').onclick = () => {
  timingRowsPage = Math.max(0, timingRowsPage - 1);
  renderTimingGrid();
};
$('timing_rows_next').onclick = () => {
  timingRowsPage++;
  renderTimingGrid();
};
for (const id of ['timing_grid_start_page', 'timing_grid_duration_page']) $(id).onchange = () => renderTimingGrid();
document.addEventListener('change', event => {
  if (event.target.dataset.timingCondition !== undefined) {
    event.target.checked ? timingConditionKeys.add(event.target.dataset.timingCondition) : timingConditionKeys.delete(event.target.dataset.timingCondition);
    invalidateTiming();
  }
});
document.addEventListener('click', event => {
  if (event.target.dataset.timingEntry !== undefined && !busy) selectTimingEntry(Number(event.target.dataset.timingEntry));
});
const changedBeforeTiming = changed;
changed = function () {
  changedBeforeTiming();
  refreshTimingChoices();
  invalidateTiming();
};
const conditionsBeforeTiming = renderConditions;
renderConditions = function () {
  conditionsBeforeTiming();
  refreshTimingChoices();
  invalidateTiming();
};
document.addEventListener('lab-timing-open', event => openTiming(event.detail));
document.addEventListener('lab-case', () => {
  timingSequence++;
  timingCachedConditions = null;
  timingCachedOptions = null;
  timingPreview = null;
  timingPreviewSignature = null;
  timingReport = null;
  timingJobId = null;
  timingArtifactId = null;
  timingCurveChanged = false;
  timingSelected = null;
  timingConditionKeys.clear();
  timingConditionKeys.add('current');
  for (const id of ['timing_grid_head', 'timing_grid_rows', 'timing_rows']) $(id).replaceChildren();
  UI.text($('timing_counts'), '');
  UI.text($('timing_selected'), '');
  UI.text($('timing_curve_status'), '');
  $('timing_curves').disabled = true;
  clearSearchContext('timing');
  clearSearchDiagnostics('timing');
  refreshTimingChoices();
  invalidateTiming();
});
function openTimingCurves(result, artifactId) {
  const selected = result.timing_evaluation;
  timingSequence++;
  timingJobId = null;
  timingArtifactId = null;
  timingCurveChanged = false;
  timingPreview = null;
  timingPreviewSignature = null;
  timingReport = null;
  timingSelected = null;
  timingCachedConditions = JSON.parse(JSON.stringify(result.conditions || []));
  timingCachedOptions = JSON.parse(JSON.stringify(selected.search_options || result.search_options || {}));
  timingConditionKeys.clear();
  timingCachedConditions.forEach(c => timingConditionKeys.add('saved:' + c.name));
  $('timing_ids').value = selected.body_ids.join(', ');
  $('timing_starts').value = String(selected.start);
  $('timing_durations').value = String(selected.duration);
  refreshTimingChoices();
  for (const id of ['timing_grid_head', 'timing_grid_rows', 'timing_rows', 'timing_grid_start_page', 'timing_grid_duration_page']) $(id).replaceChildren();
  UI.text($('timing_rows_page'), '');
  for (const id of ['timing_grid_start_page', 'timing_grid_duration_page', 'timing_rows_prev', 'timing_rows_next']) $(id).disabled = true;
  const counts = result.timing_simulation_counts;
  UI.text($('timing_counts'), counts ? UI.msg("timing.openTimingCurves.baseline_intervention_5619a7", {
    p0: counts.completed_curve_baseline_simulations,
    p1: counts.curve_baseline_simulations,
    p2: counts.completed_curve_intervention_simulations,
    p3: counts.curve_intervention_simulations
  }) : UI.msg("timing.openTimingCurves.not_recorded_7c925a", {}));
  UI.text($('timing_selected'), UI.msg("timing.openTimingCurves.savepinnode_98c8de", {
    p0: selected.start,
    p1: selected.start + selected.duration,
    p2: selected.body_ids.join(', ')
  }));
  timingStatus(UI.msg("timing.openTimingCurves.savefixed_interval_curves_run_timing_exploration_634d3d", {}));
  UI.text($('timing_curve_status'), UI.msg("timing.openTimingCurves.message_2c3986", {}));
  for (const id of ['timing_save', 'timing_run', 'timing_cancel', 'timing_curves']) $(id).disabled = true;
  renderSearchEvidence(result, 'timing', true);
  renderComparison({
    ...result,
    rows: result.rows.map(row => ({
      ...row,
      name_display: {key: "timing.controls.message_67b8cd", params: {
        p0: selected.start,
        p1: selected.start + selected.duration,
        p2: row.name
      }}
    }))
  }, {origin: 'saved', artifactId});
  $('save').disabled = true;
}
document.addEventListener('lab-timing-curves-open', event => openTimingCurves(event.detail.result, event.detail.artifactId));
