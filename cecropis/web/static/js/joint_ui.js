"use strict";

/* One exact node set is evaluated under every selected protocol. */
let jointSavedConditions = null,
  jointSavedOptions = null,
  jointPreviewResult = null,
  jointPreviewSignature = null;
let jointResult = null,
  jointPlans = [],
  jointSelectedPlan = null,
  jointJobId = null,
  jointArtifactId = null,
  jointRunning = false,
  jointHistorical = false,
  jointSequence = 0,
  jointRequestSignature = null;
const jointTrainingNames = new Set(),
  jointExtraNames = new Set(),
  jointLocks = new Map();
let jointManualSelection = false,
  jointDisplayedSignature = null,
  jointContextSignature = null,
  jointContextSequence = 0;
function jointStatus(message, error = false) {
  UI.text($('joint_status'), message);
  $('joint_status').classList.toggle('error', error);
}
function jointAvailableConditions() {
  return jointSavedConditions || conditions;
}
function jointAvailableExtraConditions() {
  return [...new Map([...conditions, ...(jointSavedConditions || [])].map(c => [c.name, c])).values()];
}
function jointTrainingConditions() {
  return jointAvailableConditions().filter(c => jointTrainingNames.has(c.name)).map(c => ({
    name: c.name,
    experiment: JSON.parse(JSON.stringify(c.experiment))
  }));
}
function jointOptions() {
  const options = JSON.parse(JSON.stringify(jointSavedOptions || searchOptions()));
  return {
    ...options,
    candidate_order: options.candidate_order || (jointSavedOptions ? 'body_id' : 'signal_path')
  };
}
function jointPayload() {
  const selected = jointTrainingConditions();
  if (selected.length < 2 || selected.length > 12) throw UI.error("joint.jointPayload.joint_search_select_2_12_condition_b3aa7d", {});
  return {
    conditions: selected,
    options: jointOptions()
  };
}
function jointSignature(payload = jointPayload(), caseId = overview.manifest.case_id) {
  return JSON.stringify({
    case_id: caseId,
    conditions: payload.conditions.map(c => ({
      name: c.name,
      experiment: normalizedExperiment(c.experiment)
    })).sort((a, b) => a.name.localeCompare(b.name)),
    options: normalizedSearchOptions(payload.options, {
      experiment: payload.conditions[0].experiment
    })
  });
}
function jointReportSignature(report) {
  return jointSignature({
    conditions: report.conditions,
    options: report.options || report.search_options
  }, report.case_id || overview.manifest.case_id);
}
function jointMatchesCurrent() {
  try {
    return !!jointResult && jointDisplayedSignature === jointSignature();
  } catch (_) {
    return false;
  }
}
function invalidateJoint() {
  invalidateJointSearchContext();
  jointSequence++;
  jointPreviewResult = null;
  jointPreviewSignature = null;
  $('joint_start').disabled = true;
  $('joint_preview').disabled = busy || searchRunning || jointRunning;
  $('joint_save').disabled = true;
  if (jointResult && !jointMatchesCurrent()) jointStatus(UI.msg("joint.invalidateJoint.condition_search_scope_2d5f2a", {}));
  updateJointProtocolSummary();
}
function updateJointProtocolSummary() {
  const train = jointTrainingConditions(),
    options = jointOptions();
  UI.text($('joint_protocol_status'), UI.msg("joint.updateJointProtocolSummary.target_node_9cd02f", {
    p0: jointSavedConditions ? UI.msg("joint.updateJointProtocolSummary.save_condition_121c95", {}) : UI.msg("joint.updateJointProtocolSummary.compare_conditions_649fb9", {}),
    p1: train.length,
    p2: jointAvailableConditions().length,
    p3: jointSavedOptions ? UI.msg("joint.updateJointProtocolSummary.save_constraints_1e1bcd", {}) : UI.msg("joint.updateJointProtocolSummary.search_f5687a", {}),
    p4: options.target_output || UI.msg("joint.updateJointProtocolSummary.message_7409a6", {}),
    p5: options.target_metric === 'absolute' ? UI.msg("joint.updateJointProtocolSummary.absolute_mean_activity_24d3f6", {}) : UI.msg("joint.updateJointProtocolSummary.message_76b164", {}),
    p6: options.max_nodes,
    p7: options.max_evaluations,
    p8: options.candidate_order === 'signal_path' ? UI.msg("joint.updateJointProtocolSummary.targetconnections_95dd3c", {}) : UI.msg("joint.updateJointProtocolSummary.by_body_id_94e546", {})
  }));
  $('joint_protocol_details').innerHTML = train.map(item => {
    const c = item.experiment;
    return `<div style="margin-bottom:8px"><b>${UI.html(item.name)}</b>${UI.htmlText("joint.controls.updates_gain_intervention_65cc22", {
      p0: c.steps,
      p1: c.gain,
      p2: c.intervention_start,
      p3: c.intervention_stop,
      p4: protocolEvents(c).map((e, k) => `<div>${UI.htmlText("joint.controls.message_4c5893", {
        p0: k + 1,
        p1: e.start,
        p2: e.stop,
        p3: e.amplitude,
        p4: e.body_ids.join(', ')
      })}</div>`).join(''),
      p5: protocolObservations(c).map(o => `<div>${UI.htmlText("joint.controls.observation_01868c", {
        p0: o.name,
        p1: o.evaluation_window?.start ?? 0,
        p2: o.evaluation_window?.stop ?? c.steps,
        p3: o.body_ids.join(', ')
      })}</div>`).join('')
    })}</div>`;
  }).join('') + Object.entries(options.protected_limits || {}).map(([name, spec]) => `<div>${UI.htmlText("joint.controls.protection_53d8fc", {
    p0: name,
    p1: spec.metric === 'absolute' ? UI.msg("joint.controls.message_cf6ba9", {}) : UI.msg("joint.controls.message_76b164", {}),
    p2: searchLossText(spec.max_loss, spec.metric)
  })}</div>`).join('');
}
function refreshJointChoices() {
  const available = jointAvailableConditions(),
    valid = new Set(available.map(c => c.name));
  for (const name of jointTrainingNames) if (!valid.has(name)) jointTrainingNames.delete(name);
  if (!jointManualSelection) available.slice(0, 12).forEach(c => jointTrainingNames.add(c.name));
  $('joint_condition_choices').innerHTML = available.length ? available.map(c => `<label class="pill"><input type="checkbox" data-joint-training="${esc(c.name)}" ${jointTrainingNames.has(c.name) ? 'checked' : ''}>${UI.htmlText("joint.controls.input_events_2ee982", {
    p0: c.name,
    p1: protocolEvents(c.experiment).length
  })}</label>`).join('') : `<div class="note">${UI.htmlText("joint.refreshJointChoices.add_comparison_conditions_or_open_a_saved_comparison_45b611", {})}</div>`;
  const extras = jointAvailableExtraConditions().filter(c => !jointTrainingNames.has(c.name)),
    validExtras = new Set(extras.map(c => c.name));
  for (const name of jointExtraNames) if (!validExtras.has(name)) jointExtraNames.delete(name);
  $('joint_extra_choices').innerHTML = extras.length ? extras.map(c => `<label class="pill"><input type="checkbox" data-joint-extra="${esc(c.name)}" ${jointExtraNames.has(c.name) ? 'checked' : ''}> ${UI.html(c.name)}</label>`).join('') : `<div class="note">${UI.htmlText("joint.refreshJointChoices.no_extra_conditions_add_conditions_to_the_comparison_fir_47b185", {})}</div>`;
  updateJointProtocolSummary();
}
const renderOriginalConditions = renderConditions;
renderConditions = function () {
  renderOriginalConditions();
  refreshJointChoices();
  invalidateJoint();
};
async function previewJointSearch() {
  if (busy || searchRunning || jointRunning) return;
  const seq = ++jointSequence;
  try {
    const payload = jointPayload(),
      signature = jointSignature(payload);
    $('joint_preview').disabled = true;
    $('joint_start').disabled = true;
    jointStatus(UI.msg("joint.previewJointSearch.check_joint_candidates_913aee", {}));
    const result = await api('/api/joint-search-preview', payload);
    if (seq !== jointSequence || signature !== jointSignature()) return;
    jointPreviewResult = result;
    jointPreviewSignature = signature;
    UI.text($('joint_candidate_status'), UI.msg("joint.previewJointSearch.message_310bc8", {
      p0: result.condition_count || result.protocol_count || payload.conditions.length,
      p1: UI.numeric(result.original_candidate_count, {}),
      p2: UI.numeric(result.excluded_endpoint_count, {}),
      p3: UI.numeric(result.candidate_count, {}),
      p4: result.candidate_count ? '' : UI.msg("joint.previewJointSearch.searchnode_ed5f6e", {})
    }));
    $('joint_start').disabled = !result.candidate_count;
    jointStatus(result.candidate_count ? UI.msg("joint.previewJointSearch.message_448a59", {}) : UI.msg("joint.previewJointSearch.candidate_set_6038ce", {}));
  } catch (error) {
    if (seq === jointSequence) jointStatus(UI.errorText(error), true);
  } finally {
    if (seq === jointSequence) $('joint_preview').disabled = false;
  }
}
function lockJointTask(active) {
  if (active) {
    busy = true;
    jointRunning = true;
    for (const id of ['experiment', 'protocol_panel', 'global_panel', 'pathway_panel', 'search_panel', 'scope_comparison_panel', 'condition_list', 'joint_condition_choices', 'joint_extra_choices']) {
      jointLocks.set('inert:' + id, $(id).inert);
      $(id).inert = true;
    }
    for (const id of ['run', 'baseline', 'load', 'export', 'save', 'add_condition', 'compare_conditions', 'save_comparison', 'clear_conditions', 'search_start', 'search_cancel', 'search_save', 'joint_use_conditions', 'joint_use_options', 'joint_preview', 'joint_context_check', 'search_context_check', 'joint_start', 'joint_save', 'joint_evaluate']) {
      jointLocks.set('disabled:' + id, $(id).disabled);
      $(id).disabled = true;
    }
    $('joint_cancel').disabled = false;
  } else {
    busy = false;
    jointRunning = false;
    for (const [key, value] of jointLocks) {
      const [property, id] = key.split(':');
      $(id)[property] = value;
    }
    jointLocks.clear();
    $('joint_cancel').disabled = true;
    let currentSignature = null;
    try {
      currentSignature = jointSignature();
    } catch (_) {}
    $('joint_start').disabled = !jointPreviewResult?.candidate_count || jointPreviewSignature !== currentSignature;
    $('joint_save').disabled = jointHistorical || !jointJobId || !jointMatchesCurrent();
    scheduleCandidatePreview();
  }
}
async function startJointSearch() {
  if (busy || searchRunning || jointRunning) return;
  try {
    const payload = jointPayload(),
      signature = jointSignature(payload);
    if (!jointPreviewResult?.candidate_count || jointPreviewSignature !== signature) throw UI.error("joint.startJointSearch.message_d3c2f0", {});
    jointRequestSignature = signature;
    jointArtifactId = null;
    jointResult = null;
    jointPlans = [];
    jointSelectedPlan = null;
    jointHistorical = false;
    for (const id of ['joint_plan_head', 'joint_plan_rows', 'joint_condition_head', 'joint_condition_rows', 'joint_evaluation_head', 'joint_evaluation_rows']) $(id).replaceChildren();
    UI.text($('joint_selected_plan'), '');
    UI.text($('joint_evaluation_status'), '');
    lockJointTask(true);
    jointStatus(UI.msg("joint.startJointSearch.startjoint_search_febb29", {}));
    const started = await api('/api/joint-search', payload);
    jointJobId = started.job_id;
    pollJointSearch(jointJobId);
  } catch (error) {
    lockJointTask(false);
    jointStatus(UI.errorText(error), true);
  }
}
async function pollJointSearch(id) {
  try {
    const snapshot = await api('/api/joint-search?' + new URLSearchParams({
      job_id: id
    }));
    if (jointJobId !== id) return;
    if (snapshot.status === 'running') {
      const p = snapshot.progress || {};
      jointStatus(UI.msg("joint.pollJointSearch.intervention_788763", {
        p0: UI.code(p.phase || 'baseline') || UI.msg("joint.pollJointSearch.baseline_1bea37", {}),
        p1: p.evaluations || 0,
        p2: p.budget || jointOptions().max_evaluations,
        p3: p.intervention_simulations ?? p.simulations ?? '—'
      }));
      setTimeout(() => pollJointSearch(id), 700);
      return;
    }
    let matches = false;
    try {
      matches = jointRequestSignature === jointSignature();
    } catch (_) {}
    lockJointTask(false);
    if (snapshot.result) renderJointSearch(snapshot.result, false, matches);else jointStatus(UI.jobText(snapshot, UI.msg("joint.pollJointSearch.joint_searchfailed_8e4e7f", {})), true);
    $('joint_save').disabled = !snapshot.result || !matches;
  } catch (error) {
    if (jointJobId !== id) return;
    lockJointTask(false);
    jointStatus(UI.errorText(error), true);
  }
}
function jointConditionRows(plan) {
  return plan?.condition_results || plan?.conditions || [];
}
function jointProtectedLabels(report) {
  return Object.keys(report.requested_protected_limits || report.options?.protected_limits || report.search_options?.protected_limits || {});
}
function jointMetric(report, label = null) {
  const options = report.options || report.search_options || {};
  return label ? (report.requested_protected_limits || options.protected_limits || {})[label]?.metric || 'relative' : options.target_metric || report.target_metric || 'relative';
}
function jointConstraintLabel(row) {
  if (row.feasible) return UI.msg("joint.jointConstraintLabel.satisfied_4e8156", {});
  const violations = row.violations || [];
  return violations.length ? UI.list(violations.map(v => v.includes('undefined') ? UI.join([UI.msg("joint.controls.metricundefined_d5fdbb", {}), v.includes(':') ? ' ' + v.split(':').slice(1).join(':') : '']) : v === 'minimum_target_loss' ? UI.msg("joint.controls.targetnot_satisfied_c17f5e", {}) : v.startsWith('protected:') ? UI.join([UI.msg("joint.controls.protectionexceeded_4c253b", {}), v.slice(10)]) : v === 'maximum_protected_loss' ? UI.msg("joint.controls.protectionexceeded_9a9e68", {}) : v), ' / ') : UI.msg("joint.jointConstraintLabel.satisfied_ec9205", {});
}
function jointComparisonForPlan(report, plan) {
  const evaluated = jointConditionRows(plan);
  if (!evaluated.length || evaluated.some(row => !row.series || !Object.keys(row.series).length)) return null;
  const definitions = new Map(report.conditions.map(c => [c.name, c.experiment])),
    first = report.conditions[0].experiment,
    outputs = protocolObservations(first).map(o => o.name);
  const results = [],
    rows = [];
  for (const row of evaluated) {
    const c = definitions.get(row.name);
    if (!c) return null;
    const experiment = {
        ...JSON.parse(JSON.stringify(c)),
        intervention_ids: plan.body_ids
      },
      metrics = row.output_metrics || {},
      summary = outputs.map(label => ({
        type: label,
        node_count: protocolObservationIds(c, label).length,
        ...metrics[label]
      }));
    results.push({
      kind: 'comparison',
      config: {
        experiment
      },
      series: row.series,
      summary
    });
    rows.push({
      name: row.name,
      name_display: {key: 'name.search', params: {name: row.name}},
      condition_role: 'search',
      intervention_node_count: plan.node_count,
      gain: c.gain,
      start: c.intervention_start,
      stop: c.intervention_stop,
      outputs: summary
    });
  }
  return {
    protocol: {
      outputs,
      observations: protocolObservations(first),
      steps: first.steps,
      alpha: first.alpha,
      rho: first.rho
    },
    results,
    rows,
    conditions: report.conditions
  };
}
function selectJointPlan(index, showCurves = true) {
  const plan = jointPlans[index];
  if (!plan || !jointResult) return;
  jointSelectedPlan = plan;
  renderSearchDiagnostics(jointResult, 'joint', jointHistorical, plan);
  const labels = jointProtectedLabels(jointResult),
    metric = jointMetric(jointResult),
    failed = plan.failed_condition_names || jointConditionRows(plan).filter(c => !c.feasible).map(c => c.name);
  UI.text($('joint_selected_plan'), UI.msg("joint.selectJointPlan.node_worst_target_decrease_6ba6ee", {
    p0: plan.node_count,
    p1: searchLossText(plan.worst_target_loss ?? plan.target_loss, metric),
    p2: plan.feasible ? UI.msg("joint.selectJointPlan.all_conditionssatisfiedconstraints_665d9d", {}) : UI.join([UI.msg("joint.selectJointPlan.failed_conditions_8c2d9b", {}), failed.join(' / ') || UI.msg("joint.selectJointPlan.message_b47241", {})]),
    p3: plan.body_ids.join(', ')
  }));
  $('joint_condition_head').innerHTML = `<tr><th>${UI.htmlText("joint.selectJointPlan.condition_16bb1d", {})}</th><th>${UI.htmlText("joint.selectJointPlan.target_decrease_9eced2", {})}</th>${labels.map(l => `<th>${UI.htmlText("joint.controls.protection_151e67", {
    p0: l
  })}</th>`).join('')}<th>${UI.htmlText("joint.selectJointPlan.constraints_per_condition_5a5cf4", {})}</th></tr>`;
  $('joint_condition_rows').innerHTML = jointConditionRows(plan).map(row => `<tr><td>${UI.html(row.name)}</td><td>${UI.html(searchLossText(row.target_loss, metric))}${UI.html(row.target_constraint ? UI.join([' · ', row.target_constraint.satisfied ? UI.msg("joint.controls.satisfied_4e8156", {}) : UI.msg("joint.controls.not_satisfied_3b34e0", {})]) : '')}</td>${labels.map(label => `<td>${UI.html(searchLossText(row.protected_losses?.[label], jointMetric(jointResult, label)))}${UI.html(row.protected_constraints?.[label] ? UI.join([' · ', row.protected_constraints[label].satisfied ? UI.msg("joint.controls.satisfied_4e8156", {}) : UI.msg("joint.controls.exceeded_314600", {})]) : '')}</td>`).join('')}<td>${UI.html(jointConstraintLabel(row))}</td></tr>`).join('');
  $('joint_evaluate').disabled = busy || !plan.body_ids.length || jointResult.case_id !== overview.manifest.case_id;
  if (showCurves) {
    const adapted = jointComparisonForPlan(jointResult, plan);
    if (adapted) {
      renderComparison(adapted, {origin: 'search-preview', sourceArtifactId: jointArtifactId});
      $('save').disabled = true;
      UI.text($('resultstate'), UI.msg("joint.selectJointPlan.plan_searchcondition_94c621", {}));
      UI.text($('joint_evaluation_status'), UI.msg("joint.selectJointPlan.plan_searchcondition_condition_f17860", {}));
      if (!plan.body_ids.length) $('comparison_rows').querySelectorAll('[data-inspect]').forEach(button => button.disabled = true);
    } else {
      curveSource = null;
      comparison = null;
      comparisonView = null;
      for (const id of ['charts', 'curve_observations', 'curve_conditions', 'comparison_head', 'comparison_rows']) $(id).replaceChildren();
      $('save_comparison').disabled = true;
      signalContextResult = null;
      renderSignals(null);
      UI.text($('signal_context'), UI.msg("joint.selectJointPlan.plannot_recordedincoming_signals_34851a", {}));
      UI.text($('resultstate'), UI.msg("joint.selectJointPlan.plannot_recorded_e76059", {}));
      UI.text($('joint_evaluation_status'), UI.msg("joint.selectJointPlan.plankeep_conditionmetric_fixed_plan_5764a5", {}));
    }
  }
}
function renderJointSearch(report, historical = false, current = true) {
  renderSearchDiagnostics(report, 'joint', historical);
  if (current || historical) {
    renderSearchContext(report, 'joint', historical);
    jointContextSignature = jointReportSignature(report);
  } else {
    jointContextSignature = null;
    clearSearchContext('joint', UI.msg("joint.renderJointSearch.baseline_current_protocol_887410", {}));
  }
  jointResult = report;
  jointHistorical = historical;
  jointDisplayedSignature = jointReportSignature(report);
  const best = report.best;
  jointPlans = (best ? [best] : []).concat((report.frontier || []).filter(p => JSON.stringify(p.body_ids) !== JSON.stringify(best?.body_ids))).slice(0, 30);
  const metric = jointMetric(report);
  $('joint_plan_head').innerHTML = `<tr><th>${UI.htmlText("joint.renderJointSearch.plan_6f949a", {})}</th><th>${UI.htmlText("joint.renderJointSearch.shared_node_count_81cce7", {})}</th><th>${UI.htmlText("joint.renderJointSearch.worst_target_decrease_32281b", {})}</th><th>${UI.htmlText("joint.renderJointSearch.all_conditions_75aceb", {})}</th><th>${UI.htmlText("joint.renderJointSearch.failed_conditions_a2c8b0", {})}</th><th>${UI.htmlText("joint.renderJointSearch.details_979a33", {})}</th></tr>`;
  $('joint_plan_rows').innerHTML = jointPlans.map((plan, k) => `<tr><td>${UI.html(k === 0 ? UI.msg("joint.controls.message_1234ab", {}) : UI.join([UI.msg("joint.controls.message_3d7752", {}), k]))}</td><td>${plan.node_count}</td><td>${UI.html(searchLossText(plan.worst_target_loss ?? plan.target_loss, metric))}</td><td>${UI.html(plan.feasible ? UI.msg("joint.controls.satisfied_4e8156", {}) : UI.msg("joint.controls.satisfied_ec9205", {}))}</td><td>${UI.html((plan.failed_condition_names || []).join(' / ') || '—')}</td><td><button class="linkbtn" data-joint-plan="${k}">${UI.htmlText("joint.controls.view_conditions_f268bc", {})}</button></td></tr>`).join('');
  const statuses = {
    complete: UI.msg("joint.renderJointSearch.searchstop_8728a6", {}),
    budget_exhausted: UI.msg("joint.renderJointSearch.budget_exhausted_d9e9de", {}),
    cancelled: UI.msg("joint.renderJointSearch.cancelled_a37778", {}),
    failed: UI.msg("joint.renderJointSearch.failed_28384d", {})
  };
  jointStatus(UI.msg("joint.renderJointSearch.intervention_complete_baseline_e3b48e", {
    p0: historical ? UI.msg("joint.renderJointSearch.save_92ce37", {}) : '',
    p1: !current ? UI.msg("joint.renderJointSearch.message_c35110", {}) : '',
    p2: statuses[report.status] || UI.code(report.status),
    p3: report.conditions.length,
    p4: report.screened_candidates ?? 0,
    p5: report.candidate_count,
    p6: report.evaluations,
    p7: (report.options || report.search_options).max_evaluations,
    p8: report.intervention_simulations ?? '—',
    p9: report.completed_intervention_simulations ?? '—',
    p10: report.baseline_simulations ?? '—',
    p11: report.result_simulations ?? '—'
  }));
  $('joint_save').disabled = historical || !current || !jointJobId;
  UI.text($('joint_candidate_status'), UI.msg("joint.renderJointSearch.message_182d0c", {
    p0: UI.numeric(report.original_candidate_count ?? report.candidate_count, {}),
    p1: UI.numeric(report.excluded_endpoint_count ?? 0, {}),
    p2: UI.numeric(report.candidate_count, {})
  }));
  if (jointPlans.length) selectJointPlan(0, current || historical);else {
    UI.text($('joint_selected_plan'), UI.msg("joint.renderJointSearch.plan_1e7edf", {}));
    $('joint_evaluate').disabled = true;
  }
}
function jointExtraConditions() {
  return jointAvailableExtraConditions().filter(c => jointExtraNames.has(c.name) && !jointResult.conditions.some(t => t.name === c.name));
}
function renderJointEvaluation(result, saved = false, artifactId = null) {
  renderSearchEvidence(result, 'joint_evaluation', saved);
  if (saved) {
    jointContextSequence++;
    jointContextSignature = null;
    clearSearchContext('joint', UI.msg("joint.renderJointEvaluation.openpin_search_dc71d0", {}));
    clearSearchDiagnostics('joint');
    jointSequence++;
    jointResult = null;
    jointPlans = [];
    jointSelectedPlan = null;
    jointJobId = null;
    jointArtifactId = null;
    jointPreviewResult = null;
    jointPreviewSignature = null;
    jointRequestSignature = null;
    jointDisplayedSignature = null;
    jointHistorical = true;
    jointSavedConditions = JSON.parse(JSON.stringify(result.conditions || []));
    jointSavedOptions = JSON.parse(JSON.stringify(result.search_options || {}));
    jointTrainingNames.clear();
    jointExtraNames.clear();
    const classified = result.joint_constraints || {},
      train = classified.search_condition_names || result.rows.filter(row => (row.evidence_classification || row.condition_role) !== 'extra').map(row => row.name),
      extra = classified.extra_condition_names || result.rows.filter(row => (row.evidence_classification || row.condition_role) === 'extra').map(row => row.name);
    train.forEach(name => jointTrainingNames.add(name));
    extra.forEach(name => jointExtraNames.add(name));
    jointManualSelection = true;
    refreshJointChoices();
    for (const id of ['joint_plan_head', 'joint_plan_rows', 'joint_condition_head', 'joint_condition_rows']) $(id).replaceChildren();
    UI.text($('joint_selected_plan'), '');
    UI.text($('joint_candidate_status'), '');
    $('joint_start').disabled = true;
    $('joint_cancel').disabled = true;
    $('joint_save').disabled = true;
    $('joint_evaluate').disabled = true;
    jointStatus(UI.msg("joint.renderJointEvaluation.savepin_searchcondition_condition_keep_b7089c", {}));
  }
  const settings = {
      options: result.search_options || jointResult?.options || jointResult?.search_options || {}
    },
    labels = jointProtectedLabels(settings),
    bodyIds = result.body_ids || jointSelectedPlan?.body_ids || [];
  const labeled = {
    ...result,
    rows: result.rows.map(row => ({
      ...row,
      name: row.name,
      name_display: {key: (row.condition_role || row.evidence_classification) === 'extra' ? 'name.extra' : 'name.search', params: {name: row.name}}
    }))
  };
  renderComparison(labeled, {origin: saved ? 'saved' : 'calculated', artifactId});
  $('joint_evaluation_head').innerHTML = `<tr><th>${UI.htmlText("joint.renderJointEvaluation.condition_16bb1d", {})}</th><th>${UI.htmlText("joint.renderJointEvaluation.role_05b366", {})}</th><th>${UI.htmlText("joint.renderJointEvaluation.target_decrease_9eced2", {})}</th>${labels.map(label => `<th>${UI.htmlText("joint.controls.protection_151e67", {
    p0: label
  })}</th>`).join('')}<th>${UI.htmlText("joint.renderJointEvaluation.individual_constraints_9717f6", {})}</th></tr>`;
  $('joint_evaluation_rows').innerHTML = result.rows.map(row => {
    const constraint = row.constraints || {},
      target = constraint.target_constraint || constraint;
    return `<tr><td>${UI.html(row.name)}</td><td>${UI.html((row.condition_role || row.evidence_classification) === 'extra' ? UI.msg("joint.controls.message_1b9624", {}) : UI.msg("joint.controls.searchcondition_a949f8", {}))}</td><td>${UI.html(searchLossText(constraint.target_loss ?? target.loss, jointMetric(settings)))}${UI.html(target.defined === false ? UI.msg("joint.controls.metricundefined_edfd0e", {}) : '')}</td>${labels.map(label => {
      const item = constraint.protected_constraints?.[label];
      return `<td>${UI.html(searchLossText(constraint.protected_losses?.[label], jointMetric(settings, label)))}${UI.html(item ? UI.join([' · ', item.satisfied ? UI.msg("joint.controls.satisfied_4e8156", {}) : item.defined === false || item.loss === null ? UI.msg("joint.controls.metricundefined_d5fdbb", {}) : UI.msg("joint.controls.exceeded_314600", {})]) : '')}</td>`;
    }).join('')}<td>${UI.html(jointConstraintLabel(constraint))}</td></tr>`;
  }).join('');
  UI.text($('joint_evaluation_status'), UI.msg("joint.renderJointEvaluation.pin_node_condition_plan_multi_condition_comparison_231978", {
    p0: saved ? UI.msg("joint.renderJointEvaluation.save_92ce37", {}) : '',
    p1: bodyIds.length,
    p2: result.rows.filter(r => (r.condition_role || r.evidence_classification) === 'extra').length
  }));
}
async function evaluateJointPlan() {
  if (busy || searchRunning || jointRunning || !jointResult || !jointSelectedPlan) return;
  const seq = jointSequence;
  try {
    const extra = jointExtraConditions();
    if (!jointSelectedPlan.body_ids.length) throw UI.error("joint.evaluateJointPlan.0_nodebaselineplan_pinintervention_eb9009", {});
    if (jointResult.conditions.length + extra.length > 12) throw UI.error("joint.evaluateJointPlan.searchcondition_condition_12_a217b2", {});
    if (!jointArtifactId && !jointJobId) throw UI.error("joint.evaluateJointPlan.open_save_joint_search_complete_a706ba", {});
    if (jointResult.case_id !== overview.manifest.case_id) throw UI.error("joint.evaluateJointPlan.current_scope_plan_opensave_b60951", {});
    lockJointTask(true);
    $('joint_cancel').disabled = true;
    UI.text($('joint_evaluation_status'), UI.msg("joint.evaluateJointPlan.pinnode_set_3fdf54", {}));
    const result = await api('/api/joint-evaluate', {
      ...(jointArtifactId ? {
        artifact_id: jointArtifactId
      } : {
        job_id: jointJobId
      }),
      body_ids: jointSelectedPlan.body_ids,
      extra_conditions: extra
    });
    lockJointTask(false);
    if (seq !== jointSequence) return;
    renderJointEvaluation(result);
  } catch (error) {
    lockJointTask(false);
    UI.text($('joint_evaluation_status'), UI.errorText(error));
  }
}
function openJointSearch(saved) {
  const report = saved.result,
    config = saved.config || {};
  jointJobId = null;
  jointArtifactId = saved.artifact_id || saved.id || null;
  jointRunning = false;
  jointHistorical = true;
  jointSavedConditions = JSON.parse(JSON.stringify(report.conditions || config.conditions));
  jointSavedOptions = JSON.parse(JSON.stringify(report.options || report.search_options || config.search_options || config.options));
  jointTrainingNames.clear();
  jointSavedConditions.forEach(c => jointTrainingNames.add(c.name));
  jointManualSelection = true;
  refreshJointChoices();
  invalidateJoint();
  renderJointSearch(report, true, true);
  $('joint_cancel').disabled = true;
  $('joint_save').disabled = true;
}
$('joint_context_check').onclick = checkJointSearchContext;
$('joint_preview').onclick = previewJointSearch;
$('joint_start').onclick = startJointSearch;
$('joint_evaluate').onclick = evaluateJointPlan;
$('joint_use_conditions').onclick = () => {
  if (busy) return;
  jointSavedConditions = null;
  jointManualSelection = false;
  jointTrainingNames.clear();
  refreshJointChoices();
  invalidateJoint();
};
$('joint_use_options').onclick = () => {
  if (busy) return;
  jointSavedOptions = null;
  invalidateJoint();
};
$('joint_edit_options').onclick = () => workspaceShell.openSearchTool('search_panel');
$('joint_cancel').onclick = async () => {
  try {
    await api('/api/cancel-joint-search', {
      job_id: jointJobId
    });
    $('joint_cancel').disabled = true;
    jointStatus(UI.msg("joint.controls.cancel_keep_plan_151196", {}));
  } catch (error) {
    jointStatus(UI.errorText(error), true);
  }
};
$('joint_save').onclick = async () => {
  if (jointRunning || jointHistorical || !jointJobId || !jointMatchesCurrent()) return;
  $('joint_save').disabled = true;
  try {
    const saved = await api('/api/save-joint-search', {
      job_id: jointJobId
    });
    jointStatus(UI.join([UI.msg("joint.controls.joint_search_save_10faa0", {}), saved.folder]));
    document.dispatchEvent(new Event('lab-saved'));
  } catch (error) {
    jointStatus(UI.errorText(error), true);
  } finally {
    $('joint_save').disabled = jointHistorical || jointRunning || !jointMatchesCurrent();
  }
};
document.addEventListener('change', event => {
  const data = event.target.dataset;
  if (data.jointTraining !== undefined) {
    jointManualSelection = true;
    event.target.checked ? jointTrainingNames.add(data.jointTraining) : jointTrainingNames.delete(data.jointTraining);
    refreshJointChoices();
    invalidateJoint();
  }
  if (data.jointExtra !== undefined) {
    event.target.checked ? jointExtraNames.add(data.jointExtra) : jointExtraNames.delete(data.jointExtra);
    UI.text($('joint_evaluation_status'), UI.msg("joint.controls.condition_fixed_plan_b2d5da", {}));
  }
});
document.addEventListener('click', event => {
  if (event.target.dataset.jointPlan !== undefined && !busy) selectJointPlan(Number(event.target.dataset.jointPlan));
});
$('search_panel').addEventListener('input', invalidateJoint);
document.addEventListener('lab-joint-open', event => openJointSearch(event.detail));
document.addEventListener('lab-joint-evaluation-open', event => renderJointEvaluation(event.detail.result, true, event.detail.artifactId));
document.addEventListener('lab-case', () => {
  jointContextSequence++;
  jointContextSignature = null;
  for (const prefix of ['joint', 'joint_evaluation']) {
    clearSearchContext(prefix);
    clearSearchDiagnostics(prefix);
  }
  jointJobId = null;
  jointArtifactId = null;
  jointRunning = false;
  jointPreviewResult = null;
  jointPreviewSignature = null;
  jointSequence++;
  jointSavedConditions = null;
  jointSavedOptions = null;
  jointTrainingNames.clear();
  jointExtraNames.clear();
  jointManualSelection = false;
  jointResult = null;
  jointPlans = [];
  jointSelectedPlan = null;
  for (const id of ['joint_plan_head', 'joint_plan_rows', 'joint_condition_head', 'joint_condition_rows', 'joint_evaluation_head', 'joint_evaluation_rows']) $(id).replaceChildren();
  UI.text($('joint_selected_plan'), '');
  UI.text($('joint_candidate_status'), '');
  UI.text($('joint_evaluation_status'), '');
  $('joint_start').disabled = true;
  $('joint_save').disabled = true;
  $('joint_evaluate').disabled = true;
  refreshJointChoices();
  jointStatus('');
});
function invalidateJointSearchContext() {
  if (!jointContextSignature) return;
  let current = null;
  try {
    current = jointSignature();
  } catch (_) {}
  if (current !== jointContextSignature) {
    jointContextSequence++;
    jointContextSignature = null;
    clearSearchContext('joint', UI.msg("joint.invalidateJointSearchContext.search_baseline_16a806", {}));
  }
}
async function checkJointSearchContext() {
  if (busy || searchRunning || jointRunning) return;
  const seq = ++jointContextSequence;
  let signature;
  try {
    const payload = jointPayload();
    signature = jointSignature(payload);
    jointContextSignature = signature;
    setSearchContextBusy(true);
    UI.text($('joint_context_status'), UI.msg("joint.checkJointSearchContext.conditionbaseline_f2fc94", {}));
    const result = await api('/api/joint-search-context', payload);
    if (seq !== jointContextSequence || signature !== jointSignature()) return;
    renderSearchContext(result, 'joint');
  } catch (error) {
    if (seq === jointContextSequence) {
      jointContextSignature = null;
      clearSearchContext('joint', UI.errorText(error));
    }
  } finally {
    setSearchContextBusy(false);
    let current = null;
    try {
      current = jointSignature();
    } catch (_) {}
    $('joint_start').disabled = !jointPreviewResult?.candidate_count || jointPreviewSignature !== current;
    $('joint_save').disabled = jointHistorical || !jointJobId || !jointMatchesCurrent();
    scheduleCandidatePreview();
  }
}
