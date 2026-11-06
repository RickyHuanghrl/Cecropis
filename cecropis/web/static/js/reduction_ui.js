"use strict";

/* Exact-set withdrawal analysis uses trusted sources; the editor remains a new task. */
let reductionReport = null,
  reductionJobId = null,
  reductionArtifactId = null,
  reductionSelected = null,
  reductionOptions = null,
  reductionInput = null,
  reductionPreviewSignature = null,
  reductionRunning = false,
  reductionEpoch = 0,
  reductionDirty = false;
let reductionPage = 0;
const reductionLocks = new Map();
const cfgBeforeReduction = cfg;
cfg = function () {
  const c = cfgBeforeReduction();
  if ($('selection_mode').value === 'none') {
    c.intervention_ids = [];
    c.intervention_group = '__fixed_no_intervention__';
  }
  return c;
};
const validateBeforeReduction = validateCondition;
validateCondition = function (c) {
  if (c.intervention_group === '__fixed_no_intervention__') {
    if (!Array.isArray(c.intervention_ids) || c.intervention_ids.length) throw UI.error("reduction.controls.no_intervention_85265c", {});
    return validateBeforeReduction({
      ...c,
      intervention_group: '__all__',
      intervention_ids: null
    });
  }
  return validateBeforeReduction(c);
};
const selectedBeforeReduction = currentSelectionIds;
currentSelectionIds = function () {
  return $('selection_mode').value === 'none' ? [] : selectedBeforeReduction();
};
const applyBeforeReduction = apply;
apply = function (c) {
  if (c.intervention_group === '__fixed_no_intervention__') {
    validateCondition(c);
    applyBeforeReduction({
      ...c,
      intervention_group: '__all__',
      intervention_ids: null
    });
    $('selection_mode').value = 'none';
    $('selection_ids').value = '';
    refreshSelection();
  } else applyBeforeReduction(c);
};
const refreshBeforeReduction = refreshSelection;
refreshSelection = function () {
  refreshBeforeReduction();
  if (overview && $('selection_mode').value === 'none') UI.text($('selection_size'), UI.msg("reduction.controls.intervention_0_no_intervention_b73893", {
    p0: UI.numeric(overview.manifest.node_count, {})
  }));
};
function reductionStatus(text, error = false) {
  UI.text($('reduction_status'), text);
  $('reduction_status').classList.toggle('error', error);
}
function reductionInvalidate() {
  reductionPreviewSignature = null;
  $('reduction_run').disabled = true;
}
function reductionDefinition() {
  if (!reductionInput) throw UI.error("reduction.reductionDefinition.select_plan_selection_b4d62d", {});
  if (!reductionOptions) throw UI.error("reduction.reductionDefinition.target_protectionconstraints_budget_1a601c", {});
  return {
    ...replayClone(reductionInput),
    extra_conditions: [...$('reduction_extra_conditions').querySelectorAll('input:checked')].map(e => replayClone(conditions.find(c => c.name === e.value))),
    decision_mode: $('reduction_decision_mode').value,
    options: replayClone(reductionOptions),
    simplify: $('reduction_simplify').checked
  };
}
function reductionRefreshExtras() {
  $('reduction_extra_conditions').innerHTML = conditions.map(c => `<label class="pill"><input type="checkbox" value="${esc(c.name)}">${UI.html(c.name)}</label>`).join('');
}
function reductionSignature() {
  return JSON.stringify({
    case_id: overview.manifest.case_id,
    definition: reductionDefinition()
  });
}
function reductionBindOpened() {
  if (!reductionSelected || !reductionArtifactId) return;
  const name = $('reduction_condition').value || reductionReport.conditions[0].name,
    condition = [...reductionReport.conditions, ...(reductionReport.extra_conditions || [])].find(c => c.name === name);
  const source = {
    label: UI.join([UI.msg("reduction.reductionBindOpened.plan_a68dcd", {}), name]),
    source: {
      kind: 'artifact',
      artifact_id: reductionArtifactId,
      body_ids: reductionSelected.body_ids,
      condition_name: name
    },
    experiment: {
      ...replayClone(condition.experiment),
      intervention_ids: reductionSelected.body_ids
    }
  };
  replaySource = source;
  bindDifferenceSource(source);
  document.dispatchEvent(new CustomEvent('lab-replay-source', {
    detail: source
  }));
  analysisCurrent.references.reduction = {
    artifact_id: reductionArtifactId
  };
  analysisTab('reduction');
}
function reductionShowDefinition() {
  const options = reductionOptions;
  UI.text($('reduction_definition'), options ? UI.join([UI.msg("reduction.reductionShowDefinition.target_budget_protection_3bb57a", {
    p0: options.target_output,
    p1: searchLossText(options.min_target_loss, options.target_metric),
    p2: options.max_evaluations
  }), Object.entries(options.protected_limits || {}).map(([name, spec]) => `${name} ≤ ${searchLossText(spec.max_loss, spec.metric)}`).join(' / ')]) : UI.msg("reduction.reductionShowDefinition.target_protection_budget_c1e4fa", {}));
}
async function reductionUseSource() {
  try {
    if (busy) throw UI.error("reduction.reductionUseSource.stop_actions_f9d6a3", {});
    if (!analysisCurrent?.source) throw UI.error("reduction.reductionUseSource.open_plan_27f436", {});
    await analysisPersistHandles();
    reductionInput = {
      source: replayClone(analysisCurrent.source)
    };
    reductionOptions = null;
    reductionRefreshExtras();
    reductionInvalidate();
    const exact = analysisCurrent.experiment;
    UI.text($('reduction_input_summary'), UI.join([UI.join([UI.msg("reduction.reductionUseSource.plan_5d42bd", {}), analysisCurrent.label]), exact ? ' · gain ' + exact.gain + ' / [' + exact.intervention_start + ', ' + exact.intervention_stop + ') · ' + (exact.intervention_ids || []).join(', ') : '']));
    reductionShowDefinition();
    analysisTab('reduction');
  } catch (e) {
    reductionStatus(UI.errorText(e), true);
  }
}
function reductionUseSelection() {
  try {
    if (busy) throw UI.error("reduction.reductionUseSelection.stop_actions_f9d6a3", {});
    const ids = analysisSelection.ids();
    if (!ids.length) throw UI.error("reduction.reductionUseSelection.intervention_f239cd", {});
    const experiment = replayClone(cfg());
    validateCondition(experiment);
    reductionInput = {
      conditions: [{
        name: UI.t("reduction.reductionUseSelection.message_e456c3"),
        experiment
      }],
      body_ids: ids,
      extra_conditions: []
    };
    reductionOptions = null;
    reductionRefreshExtras();
    reductionInvalidate();
    UI.text($('reduction_input_summary'), UI.msg("reduction.reductionUseSelection.node_gain_ab7337", {
      p0: ids.length,
      p1: experiment.gain,
      p2: experiment.intervention_start,
      p3: experiment.intervention_stop,
      p4: ids.join(', ')
    }));
    reductionShowDefinition();
    analysisTab('reduction');
  } catch (e) {
    reductionStatus(UI.errorText(e), true);
  }
}
async function reductionCheck() {
  try {
    if (busy) return;
    const definition = reductionDefinition(),
      signature = reductionSignature();
    $('reduction_preview').disabled = true;
    reductionStatus(UI.msg("reduction.reductionCheck.plan_50f44e", {}));
    const result = await api('/api/reduction-preview', definition);
    if (signature !== reductionSignature()) return;
    reductionPreviewSignature = signature;
    UI.text($('reduction_preview_detail'), UI.join([UI.msg("reduction.reductionCheck.node_plan_node_view_plan_budget_baseline_intervention_eac16e", {
      p0: UI.numeric(result.computation_node_count, {}),
      p1: result.original_node_count,
      p2: result.original_body_ids.join(', ') || UI.msg("reduction.reductionCheck.no_intervention_269771", {}),
      p3: result.condition_count,
      p4: result.extra_condition_count,
      p5: result.initial_plan_count,
      p6: result.budget,
      p7: result.estimated_baseline_simulations,
      p8: result.estimated_intervention_simulations,
      p9: result.estimated_total_simulations
    }), UI.list(result.conditions.map(c => UI.join([UI.join([UI.join([UI.msg("reduction.controls.gain_intervention_259c65", {
      p0: c.name,
      p1: c.experiment.gain,
      p2: c.experiment.intervention_start,
      p3: c.experiment.intervention_stop
    }), protocolEvents(c.experiment).map(e => UI.msg("reduction.controls.amplitude_88c90b", {
      p0: e.start,
      p1: e.stop,
      p2: e.amplitude,
      p3: e.body_ids.join(', ')
    })).join('\n')]), '\n']), protocolObservations(c.experiment).map(o => UI.msg("reduction.controls.message_1e7400", {
      p0: o.name,
      p1: o.evaluation_window?.start ?? 0,
      p2: o.evaluation_window?.stop ?? c.experiment.steps,
      p3: o.body_ids.join(', ')
    })).join('\n')])), '\n')]));
    $('reduction_run').disabled = false;
    reductionStatus(UI.msg("reduction.reductionCheck.check_requestcomplete_definition_d5ee6c", {}));
  } catch (e) {
    reductionStatus(UI.errorText(e), true);
  } finally {
    $('reduction_preview').disabled = false;
  }
}
function reductionLock(active) {
  reductionRunning = active;
  busy = active;
  if (active) {
    for (const id of ['experiment', 'protocol_panel', 'global_panel', 'search_panel', 'joint_search_panel', 'timing_panel']) if ($(id)) {
      reductionLocks.set(id, $(id).inert);
      $(id).inert = true;
    }
  } else {
    for (const [id, value] of reductionLocks) $(id).inert = value;
    reductionLocks.clear();
  }
  $('reduction_setup').inert = active;
  $('reduction_cancel').disabled = !active;
  $('reduction_save').disabled = active || !reductionReport;
}
async function reductionStart() {
  try {
    if (busy) return;
    if (reductionPreviewSignature !== reductionSignature()) throw UI.error("reduction.reductionStart.check_request_plan_9a9ad6", {});
    const payload = reductionDefinition();
    reductionLock(true);
    reductionArtifactId = null;
    reductionDirty = false;
    const started = await api('/api/start-reduction', payload);
    reductionJobId = started.job_id;
    reductionReport = null;
    pollReduction(reductionJobId, ++reductionEpoch);
  } catch (e) {
    reductionLock(false);
    reductionStatus(UI.errorText(e), true);
  }
}
async function pollReduction(id, epoch) {
  try {
    const snapshot = await api('/api/reduction-job?' + new URLSearchParams({
      job_id: id
    }));
    if (epoch !== reductionEpoch) return;
    if (snapshot.status === 'running') {
      const p = snapshot.progress || {};
      reductionStatus(UI.msg("reduction.pollReduction.intervention_bf5152", {
        p0: UI.code(p.phase || 'evaluation') || UI.msg("reduction.pollReduction.message_d70857", {}),
        p1: p.evaluations ?? 0,
        p2: p.intervention_simulations ?? '—'
      }));
      setTimeout(() => pollReduction(id, epoch), 700);
      return;
    }
    reductionLock(false);
    if (snapshot.result) renderReduction(snapshot.result);else reductionStatus(UI.jobText(snapshot, UI.msg("reduction.pollReduction.save_05aa8a", {})), true);
  } catch (e) {
    if (epoch !== reductionEpoch) return;
    reductionLock(false);
    reductionStatus(UI.errorText(e), true);
  }
}
function reductionRows() {
  return reductionReport?.entries || [];
}
function reductionCompleted(row) {
  return row && row.status === 'completed';
}
function reductionLossChange(value, metric) {
  if (value == null) return UI.msg("reduction.reductionLossChange.definition_2ba10d", {});
  return metric === 'relative' ? UI.join([contextNumber(value * 100), UI.msg("reduction.reductionLossChange.message_05e23c", {})]) : contextNumber(value);
}
function reductionParentImpacts(row) {
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b),
    relations = [...(reductionReport.withdrawals || [])];
  for (const round of reductionReport.rounds || []) for (const child of round.candidates || []) if (same(child.body_ids, row.body_ids) && !relations.some(r => same(r.parent_body_ids, round.parent_body_ids) && same(r.child_body_ids, row.body_ids))) {
    const parent = reductionRows().find(r => same(r.body_ids, round.parent_body_ids));
    if (!reductionCompleted(parent)) continue;
    relations.push({
      parent_body_ids: parent.body_ids,
      child_body_ids: row.body_ids,
      removed_body_id: child.removed_body_id,
      condition_results: row.condition_results.map(c => {
        const before = parent.condition_results.find(p => p.name === c.name);
        return {
          name: c.name,
          parent_target_loss: before.target_loss,
          child_target_loss: c.target_loss,
          target_loss_change: c.target_loss == null || before.target_loss == null ? null : c.target_loss - before.target_loss,
          protected_loss_changes: Object.fromEntries(Object.entries(c.protected_losses).map(([k, v]) => [k, v == null || before.protected_losses[k] == null ? null : v - before.protected_losses[k]])),
          outputs: Object.fromEntries(Object.entries(c.output_metrics).map(([k, m]) => [k, {
            intervention_mean_change: m.intervention_mean - before.output_metrics[k].intervention_mean
          }]))
        };
      })
    });
  }
  return relations.filter(r => same(r.child_body_ids, row.body_ids));
}
function reductionRenderImpacts(row) {
  const options = reductionReport.search_options;
  const impacts = reductionParentImpacts(row);
  UI.text($('reduction_impact'), impacts.length ? UI.list(impacts.map(p => UI.join([UI.msg("reduction.controls.message_4a64b5", {
    p0: p.parent_body_ids.join(', ') || UI.msg("reduction.controls.no_intervention_269771", {}),
    p1: p.removed_node?.type || '',
    p2: p.removed_body_id,
    p3: p.child_body_ids.join(', ') || UI.msg("reduction.controls.no_intervention_269771", {})
  }), p.condition_results.map(c => UI.join([UI.msg("reduction.controls.target_difference_41392f", {
    p0: c.name,
    p1: searchLossText(c.parent_target_loss, options.target_metric),
    p2: searchLossText(c.child_target_loss, options.target_metric),
    p3: reductionLossChange(c.target_loss_change, options.target_metric)
  }), Object.entries(c.protected_loss_changes || {}).map(([name, v]) => UI.msg("reduction.controls.protection_absolute_change_d1d1ea", {
    p0: name,
    p1: reductionLossChange(v, options.protected_limits[name].metric),
    p2: UI.numeric(c.outputs?.[name]?.intervention_mean_change, {
      notation: "scientific",
      minimumFractionDigits: 4,
      maximumFractionDigits: 4
    })
  })).join('\n')])).join('\n')])), '\n\n') : UI.msg("reduction.reductionRenderImpacts.not_recorded_fb4e28", {}));
}
function reductionRenderChain(report) {
  UI.text($('reduction_chain'), (report.chain || []).length ? UI.list(report.chain.map((c, k) => UI.msg("reduction.controls.all_constraintssatisfied_worst_target_effect_target_prot_d36d4a", {
    p0: k + 1,
    p1: c.parent_body_ids.join(', '),
    p2: c.removed_body_id,
    p3: c.child_body_ids.join(', ') || UI.msg("reduction.controls.no_intervention_269771", {})
  })), '\n') : UI.msg("reduction.reductionRenderChain.remove_beb800", {}));
  const unchecked = (report.rounds || []).filter(r => r.unchecked_removed_body_ids?.length);
  UI.text($('reduction_coverage'), unchecked.length ? UI.list(unchecked.map(r => UI.msg("reduction.controls.message_8e6b8c", {
    p0: r.parent_body_ids.join(', ') || UI.msg("reduction.controls.no_intervention_269771", {}),
    p1: r.unchecked_removed_body_ids.join(', ')
  })), '\n') : UI.msg("reduction.reductionRenderChain.save_othercombination_scope_309c0c", {}));
  const previous = $('reduction_condition').value;
  $('reduction_condition').replaceChildren();
  for (const c of [...report.conditions, ...(report.extra_conditions || [])]) $('reduction_condition').append(UI.option(UI.join([c.name, report.conditions.some(d => d.name === c.name) ? UI.msg("reduction.reductionRenderChain.message_93efc4", {}) : UI.msg("reduction.reductionRenderChain.message_e21fe3", {})]), c.name));
  if ([...$('reduction_condition').options].some(o => o.value === previous)) $('reduction_condition').value = previous;
}
async function reductionUseSourceOptions() {
  try {
    const id = reductionInput?.source?.artifact_id;
    if (!id) throw UI.error("reduction.reductionUseSourceOptions.plan_2553aa", {});
    const saved = await api('/api/reopen', {
        id
      }),
      options = saved.result?.search_options || saved.result?.options || saved.config?.search_options;
    if (!options) throw UI.error("reduction.reductionUseSourceOptions.not_recordedconstraints_use_current_search_constraints_c9bbb8", {});
    reductionOptions = replayClone(options);
    reductionInvalidate();
    reductionShowDefinition();
  } catch (e) {
    reductionStatus(UI.errorText(e), true);
  }
}
function reductionSendDraft() {
  if (!reductionSelected) return;
  const name = $('reduction_condition').value,
    condition = [...reductionReport.conditions, ...(reductionReport.extra_conditions || [])].find(c => c.name === name);
  if (!condition) throw UI.error("reduction.reductionSendDraft.select_cd1c4c", {});
  const exact = {
    ...replayClone(condition.experiment),
    intervention_ids: reductionSelected.body_ids,
    intervention_group: reductionSelected.body_ids.length ? '__all__' : '__fixed_no_intervention__'
  };
  validateCondition(exact);
  apply(exact);
  changed();
  analysisSelection.set(reductionSelected.body_ids);
  analysisStatus(UI.msg("reduction.reductionSendDraft.node_not_run_782731", {
    p0: reductionSelected.body_ids.length,
    p1: name
  }));
}
function reductionSelect(ids) {
  const key = JSON.stringify(ids.map(String).sort()),
    row = reductionRows().find(r => JSON.stringify(r.body_ids.map(String).sort()) === key);
  if (!reductionCompleted(row)) return;
  reductionSelected = row;
  const options = reductionReport.search_options,
    labels = Object.keys(options.protected_limits || {});
  UI.text($('reduction_selected'), UI.msg("reduction.reductionSelect.keep_ed6d21", {
    p0: row.body_ids.length,
    p1: row.body_ids.join(', ') || UI.msg("reduction.reductionSelect.no_intervention_269771", {}),
    p2: (reductionReport.original_body_ids || []).filter(id => !row.body_ids.includes(id)).join(', ') || UI.msg("reduction.reductionSelect.message_484d55", {}),
    p3: row.feasible ? UI.msg("reduction.reductionSelect.all_constraintssatisfied_47ac8b", {}) : UI.join([UI.msg("reduction.reductionSelect.satisfied_failed_7ff401", {}), (row.failed_condition_names || []).join(', ')])
  }));
  $('reduction_condition_head').innerHTML = `<tr><th>${UI.htmlText("reduction.reductionSelect.protocol_and_role_c00b25", {})}</th><th>${UI.htmlText("reduction.reductionSelect.target_effect_relative_to_no_intervention_baseline_798824", {})}</th>${labels.map(l => `<th>${UI.htmlText("reduction.controls.message_5154a5", {
    p0: l
  })}</th>`).join('')}<th>${UI.htmlText("reduction.reductionSelect.constraints_per_protocol_8651d1", {})}</th></tr>`;
  $('reduction_condition_rows').innerHTML = (row.condition_results || []).map(c => `<tr><td>${UI.html(c.name)} · ${UI.html(reductionReport.conditions.some(d => d.name === c.name) ? UI.msg("reduction.controls.message_710fba", {}) : UI.msg("reduction.controls.message_1b9624", {}))}</td><td>${UI.html(searchLossText(c.target_loss, options.target_metric))}</td>${labels.map(l => `<td>${UI.html(searchLossText(c.protected_losses?.[l], options.protected_limits[l].metric))}</td>`).join('')}<td>${UI.html(jointConstraintLabel(c))}</td></tr>`).join('');
  $('reduction_restart').disabled = busy || !row.feasible;
  reductionRenderImpacts(row);
  for (const id of ['reduction_curves', 'reduction_analyze', 'reduction_draft']) $(id).disabled = busy;
  reductionMarkGraph();
}
function reductionMarkGraph() {
  const cfg = analysisCurrent?.experiment,
    identity = c => JSON.stringify({
      steps: c.steps,
      alpha: c.alpha,
      rho: c.rho,
      gain: c.gain,
      start: c.intervention_start,
      stop: c.intervention_stop,
      inputs: canonicalEvents(c),
      observations: canonicalObservations(c)
    });
  const exact = ids => JSON.stringify((ids || []).map(String).sort());
  const matches = cfg && reductionSelected && exact(cfg.intervention_ids) === exact(reductionSelected.body_ids) && [...reductionReport.conditions, ...(reductionReport.extra_conditions || [])].some(c => identity(c.experiment) === identity(cfg));
  const removed = matches ? (reductionReport.original_body_ids || []).filter(id => !reductionSelected.body_ids.includes(id)) : [];
  for (const graph of [window.replayTopology, window.pathwayTopology]) graph?.setInterventionMembership?.(matches ? reductionSelected.body_ids : [], removed);
}
function renderReduction(report, artifactId = null) {
  reductionReport = report;
  if (artifactId) {
    reductionArtifactId = artifactId;
    reductionJobId = null;
    reductionDirty = false;
  }
  const options = report.search_options;
  reductionShowDefinition();
  UI.text($('reduction_result_constraints'), UI.join([UI.msg("reduction.renderReduction.target_protection_c53b18", {
    p0: options.target_output,
    p1: searchLossText(options.min_target_loss, options.target_metric)
  }), Object.entries(options.protected_limits).map(([name, spec]) => `${name} ≤ ${searchLossText(spec.max_loss, spec.metric)}`).join(' / ')]));
  const reason = {
    original_infeasible: UI.msg("reduction.renderReduction.plannot_satisfied_3ff535", {}),
    evaluation_budget_reached: UI.msg("reduction.renderReduction.budget_exhausted_7ae4d2", {}),
    local_irreducible: UI.msg("reduction.renderReduction.condition_remove_members_constraints_92bb3a", {}),
    empty_set_reached: UI.msg("reduction.renderReduction.message_1ed77c", {}),
    withdrawals_completed: UI.msg("reduction.renderReduction.plan_complete_aaba47", {}),
    cancelled: UI.msg("reduction.renderReduction.cancelled_a37778", {}),
    baseline_failed: UI.msg("reduction.renderReduction.baseline_failed_14773f", {}),
    evaluation_failed: UI.msg("reduction.renderReduction.plan_failed_52f140", {})
  };
  UI.text($('reduction_counts'), UI.msg("reduction.renderReduction.decision_protocols_plan_baseline_intervention_baseline_i_bebe03", {
    p0: report.conditions.length,
    p1: report.original_body_ids.length,
    p2: report.evaluations,
    p3: report.budget ?? options.max_evaluations,
    p4: report.distinct_plan_count ?? report.entries.length,
    p5: report.cache_hits ?? 0,
    p6: report.completed_baseline_simulations ?? 0,
    p7: report.baseline_simulations ?? 0,
    p8: report.completed_intervention_simulations ?? 0,
    p9: report.intervention_simulations ?? 0,
    p10: report.completed_curve_baseline_simulations ?? 0,
    p11: report.curve_baseline_simulations ?? 0,
    p12: report.completed_curve_intervention_simulations ?? 0,
    p13: report.curve_intervention_simulations ?? 0
  }));
  reductionStatus(reason[report.termination_reason] || UI.code(report.termination_reason || report.status));
  reductionRenderChain(report);
  const pages = Math.max(1, Math.ceil(reductionRows().length / 50));
  reductionPage = Math.min(reductionPage, pages - 1);
  UI.text($('reduction_page'), UI.msg("reduction.renderReduction.50plan_9612f4", {
    p0: reductionPage + 1,
    p1: pages
  }));
  $('reduction_prev').disabled = reductionPage === 0;
  $('reduction_next').disabled = reductionPage + 1 >= pages;
  $('reduction_rows').innerHTML = reductionRows().slice(reductionPage * 50, reductionPage * 50 + 50).map((r, local) => {
    const k = reductionPage * 50 + local;
    return `<tr><td>${k}</td><td>${r.body_ids?.length ?? '—'}</td><td>${UI.html(r.body_ids?.join(', ') || UI.msg("reduction.controls.no_intervention_269771", {}))}</td><td>${UI.html({
      completed: UI.msg("reduction.controls.message_df49f2", {}),
      not_run: UI.msg("reduction.controls.run_62cdc8", {}),
      cancelled: UI.msg("reduction.controls.cancel_2cd0f3", {}),
      failed: UI.msg("reduction.controls.failed_28384d", {}),
      partial: UI.msg("reduction.controls.complete_6707de", {})
    }[r.status] || UI.code(r.status))}</td><td>${UI.html(reductionCompleted(r) ? searchLossText(r.worst_target_loss ?? r.target_loss, options.target_metric) : UI.msg("reduction.controls.not_recorded_7450cc", {}))}</td><td>${UI.html(reductionCompleted(r) ? r.feasible ? UI.msg("reduction.controls.satisfied_4e8156", {}) : UI.msg("reduction.controls.satisfied_ec9205", {}) : UI.msg("reduction.controls.assessment_677ee7", {}))}</td><td><button data-reduction-row="${k}" ${reductionCompleted(r) ? '' : 'disabled'}>${UI.htmlText("reduction.controls.view_db8db0", {})}</button></td></tr>`;
  }).join('');
  $('reduction_save').disabled = busy || !reductionJobId && !reductionArtifactId;
  const selected = report.final || report.original;
  if (selected) reductionSelect(selected.body_ids);
}
async function reductionSave() {
  if (reductionArtifactId && !reductionDirty) return reductionArtifactId;
  const saved = await api('/api/save-reduction', reductionArtifactId ? {
    artifact_id: reductionArtifactId
  } : {
    job_id: reductionJobId
  });
  reductionArtifactId = saved.artifact_id || saved.folder.split(/[\\/]/).pop();
  reductionDirty = false;
  document.dispatchEvent(new Event('lab-saved'));
  return reductionArtifactId;
}
async function reductionAnalyze() {
  try {
    if (!reductionCompleted(reductionSelected)) throw UI.error("reduction.reductionAnalyze.select_an_item_plan_16a0d5", {});
    const artifact = await reductionSave(),
      name = $('reduction_condition').value || reductionReport.conditions[0].name,
      condition = [...reductionReport.conditions, ...(reductionReport.extra_conditions || [])].find(c => c.name === name);
    await analysisPersistHandles();
    analysisCapture();
    const source = {
      label: UI.join([UI.msg("reduction.reductionAnalyze.plan_a68dcd", {}), name]),
      source: {
        kind: 'artifact',
        artifact_id: artifact,
        body_ids: reductionSelected.body_ids,
        condition_name: name
      },
      experiment: {
        ...replayClone(condition.experiment),
        intervention_ids: reductionSelected.body_ids
      }
    };
    analysisClearExceptOpened('source');
    replaySource = source;
    bindDifferenceSource(source);
    document.dispatchEvent(new CustomEvent('lab-replay-source', {
      detail: source
    }));
    analysisCurrent.references.reduction = {
      artifact_id: artifact
    };
    analysisTab('ranking');
    reductionMarkGraph();
  } catch (e) {
    reductionStatus(UI.errorText(e), true);
  }
}
async function reductionCurves() {
  if (busy || !reductionSelected) return;
  const ids = reductionSelected.body_ids.slice();
  try {
    busy = true;
    reductionDirty = true;
    $('reduction_curves').disabled = true;
    reductionStatus(UI.msg("reduction.reductionCurves.plan_c7f1fc", {}));
    const result = await api('/api/reduction-curves', {
      ...(reductionArtifactId ? {
        artifact_id: reductionArtifactId
      } : {
        job_id: reductionJobId
      }),
      body_ids: ids,
      include_original: $('reduction_compare_original').checked
    });
    renderComparison(result.comparison || result);
    if (result.report) renderReduction(result.report);
    $('save_comparison').disabled = !canSaveComparison();
    reductionStatus(UI.msg("reduction.reductionCurves.comparison_ae2f32", {}));
    $('comparison_status').scrollIntoView({
      block: 'center'
    });
  } catch (e) {
    reductionStatus(UI.errorText(e), true);
  } finally {
    busy = false;
    if (reductionReport) reductionSelect(ids);
  }
}
$('reduction_from_source').onclick = reductionUseSource;
$('reduction_from_selection').onclick = reductionUseSelection;
$('reduction_use_options').onclick = () => {
  reductionOptions = replayClone(searchOptions());
  reductionInvalidate();
  reductionShowDefinition();
};
$('reduction_source_options').onclick = reductionUseSourceOptions;
$('reduction_preview').onclick = reductionCheck;
$('reduction_run').onclick = reductionStart;
$('reduction_curves').onclick = reductionCurves;
$('reduction_analyze').onclick = reductionAnalyze;
$('reduction_save').onclick = async () => {
  try {
    reductionStatus(UI.join([UI.msg("reduction.controls.save_cfe6f5", {}), await reductionSave()]));
  } catch (e) {
    reductionStatus(UI.errorText(e), true);
  }
};
$('reduction_cancel').onclick = async () => {
  try {
    await api('/api/cancel-reduction', {
      job_id: reductionJobId
    });
    reductionStatus(UI.msg("reduction.controls.cancel_keep_complete_f5b61c", {}));
  } catch (e) {
    reductionStatus(UI.errorText(e), true);
  }
};
$('reduction_draft').onclick = () => {
  try {
    reductionSendDraft();
  } catch (e) {
    reductionStatus(UI.errorText(e), true);
  }
};
for (const id of ['reduction_decision_mode', 'reduction_simplify']) $(id).onchange = reductionInvalidate;
document.addEventListener('click', e => {
  if (e.target.dataset.reductionRow !== undefined && !busy) reductionSelect(reductionRows()[Number(e.target.dataset.reductionRow)].body_ids);
});
document.addEventListener('lab-case', () => {
  reductionEpoch++;
  reductionReport = null;
  reductionInput = null;
  reductionOptions = null;
  reductionSelected = null;
  reductionArtifactId = null;
  reductionJobId = null;
  reductionInvalidate();
  $('reduction_rows').replaceChildren();
});
document.addEventListener('lab-analysis-display', reductionMarkGraph);
// Stored report navigation does not replace the new-task protocol or source.
$('reduction_extra_conditions').addEventListener('change', reductionInvalidate);
const saveSceneBeforeReduction = saveAnalysisScene;
saveAnalysisScene = async function () {
  try {
    await analysisPersistHandles();
    return await saveSceneBeforeReduction();
  } catch (e) {
    analysisStatus(UI.errorText(e), true);
    return {error:e};
  }
};
$('analysis_save').onclick = saveAnalysisScene;
for (const id of ['experiment', 'protocol_panel']) $(id).addEventListener('input', () => {
  if (reductionInput?.conditions) {
    reductionInput = null;
    reductionInvalidate();
    reductionStatus(UI.msg("reduction.controls.edit_use_current_selection_and_protocol_f2fb07", {}));
  }
});
document.addEventListener('lab-artifact-open', reductionMarkGraph);
document.addEventListener('lab-analysis-selection', () => {
  if (reductionInput?.conditions && JSON.stringify(analysisSelection.ids().slice().sort()) !== JSON.stringify(reductionInput.body_ids.slice().sort())) {
    reductionInput = null;
    reductionInvalidate();
    reductionStatus(UI.msg("reduction.controls.selection_9ea974", {}));
  }
});
$('reduction_prev').onclick = () => {
  if (reductionPage > 0) {
    reductionPage--;
    const ids = reductionSelected?.body_ids;
    renderReduction(reductionReport);
    if (ids) reductionSelect(ids);
  }
};
$('reduction_next').onclick = () => {
  reductionPage++;
  const ids = reductionSelected?.body_ids;
  renderReduction(reductionReport);
  if (ids) reductionSelect(ids);
};
$('reduction_restart').onclick = async () => {
  try {
    if (busy || !reductionSelected?.feasible) return;
    const options = replayClone(reductionReport.search_options);
    await reductionAnalyze();
    await reductionUseSource();
    reductionOptions = options;
    $('reduction_simplify').checked = true;
    reductionInvalidate();
    reductionShowDefinition();
    reductionStatus(UI.msg("reduction.controls.plan_starting_nodes_constraints_check_request_50200d", {}));
  } catch (e) {
    reductionStatus(UI.errorText(e), true);
  }
};
document.addEventListener('lab-operation-idle', () => {
  if (!reductionRunning && reductionSelected) reductionSelect(reductionSelected.body_ids);
});
