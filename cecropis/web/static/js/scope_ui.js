"use strict";

/* Search eligibility and comparisons of immutable computation scopes. */
let candidatePreview = null,
  candidateSequence = 0,
  candidateTimer = null,
  searchRunning = false,
  searchRequestSignature = null;
let scopeRegistry = [],
  scopePreviewResult = null,
  scopePreviewSignature = null,
  scopeCompareResult = null,
  scopeCompareJob = null,
  scopeCompareSequence = 0,
  savedScopeProtocol = null,
  savedScopeApplied = false;
const selectedScopeIds = new Set(),
  shownScopeIds = new Set(),
  shownScopeObservations = new Set();
function normalizedExperiment(c) {
  return {
    intervention_events: c.intervention_events ?? null,
    intervention_semantics_version: c.intervention_semantics_version ?? null,
    steps: c.steps,
    alpha: c.alpha,
    rho: c.rho,
    gain: c.gain,
    intervention_start: c.intervention_start,
    intervention_stop: c.intervention_stop,
    input_events: canonicalEvents(c),
    observations: canonicalObservations(c),
    intervention_group: c.intervention_group,
    intervention_ids: (c.intervention_ids ?? candidateNodes(c.intervention_group).map(n => n.bodyId)).slice().sort()
  };
}
function normalizedSearchOptions(o, report = null) {
  const labels = report?.experiment?.outputs || cfg().outputs,
    target = o.target_output || report?.target_output || labels[0],
    protectedLimits = o.protected_limits ?? {
      [o.protected_output || report?.protected_output || labels[1]]: {
        metric: 'relative',
        max_loss: o.max_protected_loss ?? .01
      }
    };
  return {
    candidate_order: o.candidate_order || report?.candidate_order || 'body_id',
    candidate_policy: o.candidate_policy || report?.candidate_policy || 'allow_endpoints',
    target_output: target,
    target_metric: o.target_metric || 'relative',
    min_target_loss: o.min_target_loss || 0,
    max_nodes: o.max_nodes ?? 10,
    max_evaluations: o.max_evaluations ?? 1000,
    protected_limits: Object.fromEntries(Object.entries(protectedLimits).filter(([label]) => label !== 'undefined').sort(([a], [b]) => a.localeCompare(b)))
  };
}
function searchSignature(experiment = cfg(), options = searchOptions(), report = null) {
  return JSON.stringify({
    case_id: report?.case_id || overview.manifest.case_id,
    experiment: normalizedExperiment(experiment),
    options: normalizedSearchOptions(options, report)
  });
}
function markSearchMismatch() {
  if (!searchResult) return;
  try {
    searchResult._matchesCurrent = searchResult._signature === searchSignature();
  } catch (_) {
    searchResult._matchesCurrent = false;
  }
  $('search_save').disabled = !searchJob || searchRunning || searchResult._historical || !searchResult._matchesCurrent;
  renderSearchStatus();
  document.dispatchEvent(new Event('lab-search'));
}
function scheduleCandidatePreview() {
  invalidateSingleSearchContext();
  candidatePreview = null;
  candidateSequence++;
  clearTimeout(candidateTimer);
  if (!searchRunning) $('search_start').disabled = true;
  markSearchMismatch();
  candidateTimer = setTimeout(refreshSearchCandidates, 180);
}
async function refreshSearchCandidates() {
  if (!overview || busy) return;
  const seq = ++candidateSequence;
  let payload, signature;
  try {
    const experiment = cfg();
    if (Array.isArray(experiment.intervention_events)) {
      candidatePreview = null;
      $('search_start').disabled = true;
      UI.text($('search_candidate_status'), UI.msg("scope.refreshSearchCandidates.pin_operation_search_nodesearch_definition_d48696", {}));
      return;
    }
    validateCondition(experiment);
    payload = {
      experiment,
      options: searchOptions()
    };
    signature = searchSignature(experiment, payload.options);
    UI.text($('search_candidate_status'), UI.msg("scope.refreshSearchCandidates.scope_a24a44", {}));
    const result = await api('/api/search-candidates', payload);
    if (seq !== candidateSequence || signature !== searchSignature()) return;
    candidatePreview = {
      ...result,
      signature
    };
    const policy = result.candidate_policy === 'internal_only' ? UI.msg("scope.refreshSearchCandidates.circuit_66bc50", {}) : UI.msg("scope.refreshSearchCandidates.message_583323", {});
    UI.text($('search_candidate_status'), UI.msg("scope.refreshSearchCandidates.message_7f42db", {
      p0: policy,
      p1: UI.numeric(result.original_candidate_count, {}),
      p2: UI.numeric(result.excluded_endpoint_count, {}),
      p3: UI.numeric(result.candidate_count, {}),
      p4: result.candidate_count ? '' : UI.msg("scope.refreshSearchCandidates.searchnode_9bc438", {})
    }));
    if (!searchRunning) $('search_start').disabled = busy || !result.candidate_count;
    markSearchMismatch();
  } catch (error) {
    if (seq !== candidateSequence) return;
    candidatePreview = null;
    UI.text($('search_candidate_status'), UI.errorText(error));
    if (!searchRunning) $('search_start').disabled = true;
  }
}
const renderSearchWithMetrics = renderSearch;
let searchStatusMessage = null;
function renderSearchStatus() {
  if (!searchResult || !searchStatusMessage) {
    if (searchResult && !searchResult._matchesCurrent) UI.text($('search_status'), UI.msg('search.mismatch'));
    return;
  }
  UI.text($('search_status'), UI.msg('search.resultStatus', {
    origin: UI.msg(searchResult._historical ? 'search.originSaved' : 'search.originCalculated'),
    match: UI.msg(searchResult._matchesCurrent ? 'search.matches' : 'search.mismatch'),
    summary: searchStatusMessage
  }));
}
renderSearch = function (result, restoreOptions = true, historical = false) {
  renderSearchWithMetrics(result, restoreOptions);
  renderSearchEvidence(result, 'search', historical);
  cacheSingleSearchContext(result);
  result._signature = searchSignature(result.experiment, result.options || {}, result);
  result._historical = historical;
  try {
    result._matchesCurrent = result._signature === searchSignature();
  } catch (_) {
    result._matchesCurrent = false;
  }
  const policy = result.options?.candidate_policy || result.candidate_policy || 'allow_endpoints';
  searchStatusMessage = UI.msg('search.candidateSummary', {
    status:UI.code(result.status || 'completed'),
    policy: UI.msg(policy === 'internal_only' ? 'scope.controls.circuit_66bc50' : 'scope.controls.message_583323'),
    candidates:UI.numeric(result.original_candidate_count ?? result.candidate_count),
    excluded:UI.numeric(result.excluded_endpoint_count ?? 0)
  });
  renderSearchStatus();
  $('search_save').disabled = historical || !result._matchesCurrent || !searchJob;
  document.dispatchEvent(new Event('lab-search'));
  scheduleCandidatePreview();
};
pollSearch = async function (id) {
  try {
    const data = await api('/api/search?' + new URLSearchParams({
      job_id: id
    }));
    if (searchJob !== id) return;
    if (data.status === 'running') {
      UI.text($('search_status'), UI.msg("scope.controls.message_d6ce0c", {
        p0: UI.code(data.progress.phase || 'baseline') || UI.msg("scope.controls.baseline_1bea37", {}),
        p1: data.progress.evaluations || 0,
        p2: data.progress.budget || '—',
        p3: searchRequestSignature !== searchSignature() ? UI.msg("scope.controls.message_93471a", {}) : ''
      }));
      setTimeout(() => pollSearch(id), 700);
      return;
    }
    searchRunning = false;
    const matches = searchRequestSignature === searchSignature();
    if (data.result) renderSearch(data.result, matches, false);else UI.text($('search_status'), UI.apiErrorText(data));
    $('search_cancel').disabled = true;
    $('search_save').disabled = !data.result || !matches;
    scheduleCandidatePreview();
  } catch (error) {
    if (searchJob !== id) return;
    searchRunning = false;
    UI.text($('search_status'), UI.errorText(error));
    $('search_cancel').disabled = true;
    scheduleCandidatePreview();
  }
};
$('search_start').onclick = async () => {
  if (busy || searchRunning) return;
  try {
    const experiment = cfg(),
      options = searchOptions();
    validateCondition(experiment);
    const signature = searchSignature(experiment, options);
    if (!candidatePreview || candidatePreview.signature !== signature || !candidatePreview.candidate_count) throw UI.error("scope.controls.scope_86a0e2", {});
    searchRequestSignature = signature;
    searchRunning = true;
    $('search_start').disabled = true;
    $('search_save').disabled = true;
    const data = await api('/api/search', {
      experiment,
      options
    });
    searchJob = data.job_id;
    searchResult = null;
    document.dispatchEvent(new Event('lab-search'));
    $('search_cancel').disabled = false;
    $('search_rows').replaceChildren();
    $('sensitivity_rows').replaceChildren();
    pollSearch(searchJob);
  } catch (error) {
    searchRunning = false;
    UI.text($('search_status'), UI.errorText(error));
    scheduleCandidatePreview();
  }
};
$('search_save').onclick = async () => {
  if (searchRunning || !searchResult || searchResult._historical || searchResult._signature !== searchSignature()) return;
  const id = searchJob;
  $('search_save').disabled = true;
  try {
    const saved = await api('/api/save-search', {
      job_id: id
    });
    status(UI.join([UI.msg("scope.controls.search_save_7ce157", {}), saved.folder]));
    document.dispatchEvent(new Event('lab-saved'));
  } catch (error) {
    status(UI.errorText(error), true);
  } finally {
    markSearchMismatch();
  }
};
const changedProtocol = changed;
changed = function () {
  changedProtocol();
  invalidateScopePreview();
  scheduleCandidatePreview();
};
const applyProtocolOptions = applySearchOptions;
applySearchOptions = function (options = {}, legacy = false) {
  applyProtocolOptions(options, legacy);
  scheduleCandidatePreview();
};
function scopeStatus(message, error = false) {
  UI.text($('scope_compare_status'), message);
  $('scope_compare_status').classList.toggle('error', error);
}
function updateScopeRegistry(cases) {
  scopeRegistry = cases || [];
  const valid = new Set(scopeRegistry.map(c => c.id));
  for (const id of selectedScopeIds) if (!valid.has(id)) selectedScopeIds.delete(id);
  $('scope_case_choices').innerHTML = scopeRegistry.map(c => `<label class="pill"><input type="checkbox" data-scope-case="${esc(c.id)}" ${selectedScopeIds.has(c.id) ? 'checked' : ''}>${UI.htmlText("scope.controls.nodes_44b0c5", {
    p0: c.name,
    p1: scopeNumber(c.node_count)
  })}</label>`).join('');
  updateScopeProtocolSummary();
}
function fixedScopeProtocol() {
  if (savedScopeProtocol) return {
    experiment: JSON.parse(JSON.stringify(savedScopeProtocol.experiment)),
    recording: JSON.parse(JSON.stringify(savedScopeProtocol.recording))
  };
  const c = cfg();
  validateCondition(c);
  return {
    experiment: {
      ...c,
      input_events: protocolEvents(c),
      observations: protocolObservations(c),
      intervention_ids: c.intervention_events != null ? [] : currentSelectionIds()
    },
    recording: recordingPolicy()
  };
}
function scopePayload() {
  if (selectedScopeIds.size < 2 || selectedScopeIds.size > 12) throw UI.error("scope.scopePayload.select_2_12_scope_527f0f", {});
  return {
    scope_ids: [...selectedScopeIds],
    ...fixedScopeProtocol()
  };
}
function updateScopeProtocolSummary() {
  if (!overview) return;
  try {
    const protocol = fixedScopeProtocol(),
      c = protocol.experiment,
      events = c.input_events,
      observations = c.observations;
    UI.text($('scope_protocol_summary'), UI.msg("scope.updateScopeProtocolSummary.input_events_observation_sets_updates_scope_303dd7", {
      p0: savedScopeProtocol ? UI.join([UI.msg("scope.updateScopeProtocolSummary.save_2af02f", {}), savedScopeApplied ? '' : UI.msg("scope.updateScopeProtocolSummary.condition_3943f8", {})]) : UI.msg("scope.updateScopeProtocolSummary.condition_b14319", {}),
      p1: events.length,
      p2: observations.length,
      p3: c.intervention_events != null ? UI.msg("scope.updateScopeProtocolSummary.intervention_892607", {
        p0: c.intervention_events.length
      }) : UI.msg("scope.updateScopeProtocolSummary.interventionnode_468aef", {
        p0: UI.numeric(c.intervention_ids.length, {}),
        p1: c.gain,
        p2: c.intervention_start,
        p3: c.intervention_stop
      }),
      p4: c.steps,
      p5: selectedScopeIds.size
    }));
    $('scope_protocol_details').innerHTML = events.map((event, k) => `<div>${UI.htmlText("scope.controls.message_c69840", {
      p0: k + 1,
      p1: event.start,
      p2: event.stop,
      p3: event.amplitude,
      p4: event.body_ids.join(', ')
    })}</div>`).join('') + observations.map(o => `<div>${UI.htmlText("scope.controls.observation_01868c", {
      p0: o.name,
      p1: o.evaluation_window?.start ?? 0,
      p2: o.evaluation_window?.stop ?? c.steps,
      p3: o.body_ids.join(', ')
    })}</div>`).join('') + `<div>${UI.htmlText("scope.updateScopeProtocolSummary.intervention_de33b8", {
      p0: c.intervention_events != null ? c.intervention_events.map(e => e.name + ' · ' + e.type + ' · [' + e.start + ', ' + e.stop + ') · gain ' + e.gain).join(' / ') : c.intervention_ids.join(', ')
    })}</div><div>${UI.htmlText("scope.updateScopeProtocolSummary.alpha_rho_c1fad8", {
      p0: c.alpha,
      p1: c.rho
    })}</div><div>${UI.htmlText("scope.updateScopeProtocolSummary.message_637a50", {
      p0: {
        all: UI.msg("scope.updateScopeProtocolSummary.all_calculation_nodes_c3d6e0", {}),
        selected: UI.msg("scope.updateScopeProtocolSummary.specified_nodes_1972ed", {}),
        none: UI.msg("scope.updateScopeProtocolSummary.message_e08381", {})
      }[protocol.recording.mode] || protocol.recording.mode,
      p1: protocol.recording.steps ? UI.join([UI.msg("scope.updateScopeProtocolSummary.state_step_32edc3", {}), esc(protocol.recording.steps.join(', '))]) : UI.join([UI.msg("scope.updateScopeProtocolSummary.message_a4d2c2", {}), protocol.recording.step_stride || 1]),
      p2: scopeBytes(protocol.recording.max_bytes),
      p3: protocol.recording.body_ids ? ' · ' + esc(protocol.recording.body_ids.join(', ')) : ''
    })}</div>`;
  } catch (_) {
    UI.text($('scope_protocol_summary'), UI.msg("scope.updateScopeProtocolSummary.condition_880a77", {}));
    $('scope_protocol_details').replaceChildren();
  }
}
function invalidateScopePreview() {
  scopeCompareSequence++;
  scopePreviewResult = null;
  scopePreviewSignature = null;
  if (!busy) $('scope_compare_preview').disabled = false;
  $('scope_compare_run').disabled = true;
  UI.text($('scope_memory'), '');
  if (scopeCompareResult) UI.text($('scope_compare_status'), UI.msg("scope.invalidateScopePreview.scope_scope_58b536", {}));else scopeStatus(UI.msg("scope.invalidateScopePreview.check_protocol_and_scopes_f0de16", {}));
  updateScopeProtocolSummary();
}
function missingScopeMembers(missing) {
  if (!missing) return '';
  if (Array.isArray(missing)) return missing.join(', ');
  return Object.entries(missing).map(([key, value]) => {
    const detail = typeof value === 'object' ? missingScopeMembers(value) : String(value ?? '');
    return detail ? key + ': ' + detail : '';
  }).filter(Boolean).join(' / ');
}
function scopeNumber(value) {
  return value == null ? '—' : num(value);
}
function scopeBytes(value) {
  return value < 1024 ? UI.msg("scope.scopeBytes.message_8180a4", {
    p0: UI.numeric(value, {})
  }) : UI.join([UI.fixed(value / 1024 ** 2, 3), " MiB"]);
}
function renderScopeRows(cases) {
  const statuses = {
    completed: UI.msg("scope.renderScopeRows.complete_c0b3fb", {}),
    not_run: UI.msg("scope.renderScopeRows.run_62cdc8", {}),
    failed: UI.msg("scope.renderScopeRows.failed_28384d", {}),
    cancelled: UI.msg("scope.renderScopeRows.cancelled_a37778", {})
  };
  $('scope_compare_rows').innerHTML = (cases || []).map(c => {
    const missing = missingScopeMembers(c.missing_members),
      errors = (c.errors || []).join(' / ');
    return `<tr><td>${UI.html(c.name)}<div class="hint">${UI.html(c.case_id)}</div></td><td>${UI.html(scopeNumber(c.node_count))}</td><td>${UI.html(scopeNumber(c.internal_edges))}</td><td>${UI.html(scopeNumber(c.external_input_contacts))}</td><td>${UI.html(scopeNumber(c.external_output_contacts))}</td><td>${UI.html(scopeNumber(c.total_input_contacts))}</td><td style="white-space:normal;min-width:200px">${UI.html(statuses[c.status] || (missing || errors ? UI.msg("scope.controls.message_4ae9eb", {}) : UI.msg("scope.controls.message_e1ba81", {})))}${missing ? '<div>' + UI.htmlText('scope.missingMembers', {members: missing}) + '</div>' : ''}${errors ? '<div>' + esc(errors) + '</div>' : ''}${c.error ? '<div>' + esc(c.error) + '</div>' : ''}</td></tr>`;
  }).join('');
}
async function previewScopeComparison() {
  if (busy || searchRunning) return;
  const seq = ++scopeCompareSequence;
  try {
    const payload = scopePayload(),
      signature = JSON.stringify(payload);
    $('scope_compare_preview').disabled = true;
    $('scope_compare_run').disabled = true;
    scopeStatus(UI.msg("scope.previewScopeComparison.members_7581fe", {}));
    suspendDisplayedRun();
    const report = await api('/api/scope-preview', payload);
    suspendDisplayedRun();
    if (seq !== scopeCompareSequence || signature !== JSON.stringify(scopePayload())) return;
    scopePreviewResult = report;
    scopePreviewSignature = signature;
    renderScopeRows(report.cases);
    UI.text($('scope_memory'), UI.msg("scope.previewScopeComparison.order_allscope_2d6047", {
      p0: report.compatible ? '' : UI.msg("scope.previewScopeComparison.message_a61985", {}),
      p1: scopeBytes(report.recording_peak_bytes),
      p2: scopeBytes(report.recording_total_bytes)
    }));
    $('scope_compare_run').disabled = !report.compatible;
    scopeStatus(report.compatible ? UI.msg("scope.previewScopeComparison.members_scope_comparison_233dc0", {}) : (report.errors || []).join(' / ') || UI.msg("scope.previewScopeComparison.scope_view_members_f024fc", {}));
  } catch (error) {
    if (seq === scopeCompareSequence) scopeStatus(UI.errorText(error), true);
  } finally {
    if (seq === scopeCompareSequence) $('scope_compare_preview').disabled = false;
  }
}
function suspendDisplayedRun() {
  activitySequence++;
  activityRows = [];
  spatial.setActivity([], $('geometry_mode').value);
  updateFocusActivity();
  $('geometry_time').disabled = true;
  $('save').disabled = true;
  if (latest) {
    latest = {
      ...latest,
      run_id: null
    };
    dirty = true;
    UI.text($('resultstate'), UI.msg("scope.suspendDisplayedRun.run_save_d5b35b", {}));
  }
}
const scopeLocks = new Map();
function lockScopeTask(active) {
  if (active) {
    busy = true;
    for (const id of ['experiment', 'protocol_panel', 'global_panel', 'pathway_panel', 'search_panel', 'scope_case_choices']) {
      $(id).inert = true;
    }
    for (const id of ['run', 'baseline', 'load', 'export', 'save', 'compare_conditions', 'save_comparison', 'search_start', 'search_cancel', 'search_save', 'open_saved_case', 'open_saved_result', 'scope_cases_refresh', 'scope_use_current', 'scope_compare_preview', 'scope_compare_run']) {
      scopeLocks.set(id, $(id).disabled);
      $(id).disabled = true;
    }
    $('scope_compare_cancel').disabled = false;
    $('scope_compare_save').disabled = true;
  } else {
    busy = false;
    for (const id of ['experiment', 'protocol_panel', 'global_panel', 'pathway_panel', 'search_panel', 'scope_case_choices']) $(id).inert = false;
    for (const [id, disabled] of scopeLocks) $(id).disabled = disabled;
    scopeLocks.clear();
    $('scope_compare_cancel').disabled = true;
    $('scope_compare_run').disabled = !scopePreviewResult?.compatible;
    scheduleCandidatePreview();
  }
}
async function startScopeComparison() {
  if (busy || searchRunning) return;
  try {
    const payload = scopePayload();
    if (!scopePreviewResult?.compatible || JSON.stringify(payload) !== scopePreviewSignature) throw UI.error("scope.startScopeComparison.current_protocol_scope_041367", {});
    suspendDisplayedRun();
    scopeCompareResult = null;
    for (const id of ['scope_curve_cases', 'scope_curve_observations', 'scope_compare_chart', 'scope_response_rows']) $(id).replaceChildren();
    renderScopeRows(scopePreviewResult.cases.map(row => ({
      ...row,
      status: 'not_run'
    })));
    lockScopeTask(true);
    scopeStatus(UI.msg("scope.startScopeComparison.startscope_comparison_3c2602", {}));
    const started = await api('/api/scope-compare', payload);
    scopeCompareJob = started.job_id;
    pollScopeComparison(scopeCompareJob);
  } catch (error) {
    lockScopeTask(false);
    scopeStatus(UI.errorText(error), true);
  }
}
async function pollScopeComparison(id) {
  try {
    const data = await api('/api/scope-compare?' + new URLSearchParams({
      job_id: id
    }));
    if (scopeCompareJob !== id) return;
    if (data.status === 'running') {
      const p = data.progress || {};
      scopeStatus(UI.msg("scope.pollScopeComparison.complete_scope_2ef386", {
        p0: p.completed ?? 0,
        p1: p.total ?? selectedScopeIds.size,
        p2: p.current_case_id || UI.msg("scope.pollScopeComparison.message_b53be0", {})
      }));
      setTimeout(() => pollScopeComparison(id), 700);
      return;
    }
    lockScopeTask(false);
    if (data.result) renderScopeComparison(data.result, false);else scopeStatus(UI.jobText(data, UI.msg("scope.pollScopeComparison.scope_comparisonfailed_82349e", {})), true);
    $('scope_compare_save').disabled = !data.result;
  } catch (error) {
    if (scopeCompareJob !== id) return;
    lockScopeTask(false);
    scopeStatus(UI.errorText(error), true);
  }
}
function scopeColor(caseId) {
  let h = 0;
  for (const ch of caseId) h = h * 31 + ch.charCodeAt(0) >>> 0;
  return UI.observationColor(caseId);
}
function renderScopeCurves() {
  if (!scopeCompareResult) return;
  const completed = scopeCompareResult.scopes.filter(s => s.status === 'completed' && s.result),
    labels = scopeCompareResult.config.experiment.observations.map(o => o.name);
  $('scope_curve_cases').innerHTML = completed.map((s,k) => `<label class="pill"><input type="checkbox" data-scope-curve="${esc(s.case_id)}" ${shownScopeIds.has(s.case_id) ? 'checked' : ''}>${UI.htmlText('scope.controls.message_68543f',{p0:s.name,p1:UI.numeric(2+k*.5)})}</label>`).join('');
  $('scope_curve_observations').innerHTML = labels.map(label => `<label class="pill" style="color:${observationColor(label)}"><input type="checkbox" data-scope-observation="${esc(label)}" ${shownScopeObservations.has(label) ? 'checked' : ''}>${UI.html(label)}</label>`).join('');
  const shown = completed.filter(s => shownScopeIds.has(s.case_id)),
    lines = [];
  for (const scope of shown) for (const [k, label] of labels.entries()) if (shownScopeObservations.has(label)) for (const branch of ['baseline', 'intervention']) {
    const values = scope.result.series[label]?.[branch];
    if (values) lines.push({
      values,
      color: observationColor(label),
      width: 2 + completed.indexOf(scope) * .5,
      branch,
      label,
      scope
    });
  }
  const W = 800,
    H = 310,
    L = 68,
    R = 18,
    T = 15,
    B = 40,
    steps = scopeCompareResult.config.experiment.steps;
  let max = 1e-12;
  for (const line of lines) for (const value of line.values) max = Math.max(max, value);
  max *= 1.1;
  const x = k => L + k / steps * (W - L - R),
    y = v => H - B - v / max * (H - T - B);
  let svg = `<svg class="plot" viewBox="0 0 ${W} ${H}" role="img" ${UI.htmlAttribute("aria-label", "scope.renderScopeCurves.scope_observation_sets_1e19ad", {})}>`;
  for (let k = 0; k < 5; k++) {
    const v = max * k / 4,
      t = Math.round(steps * k / 4);
    svg += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--chart-grid)"/><text x="${L - 8}" y="${y(v) + 4}" fill="var(--muted)" text-anchor="end" font-size="12">${UI.html(fmt(v), true)}</text><text x="${x(t)}" y="${H - B + 19}" fill="var(--muted)" text-anchor="middle" font-size="12">${t}</text>`;
  }
  for (const line of lines) svg += `<polyline points="${line.values.map((v, k) => x(k) + ',' + y(v)).join(' ')}" stroke="${line.color}" stroke-width="${line.width}" fill="none" ${line.branch === 'intervention' ? 'stroke-dasharray="6 4"' : ''}><title>${UI.html(line.scope.name, true)} · ${UI.html(line.label, true)} · ${UI.html(line.branch === 'baseline' ? UI.msg("scope.renderScopeCurves.baseline_a7ac58", {}) : UI.msg("response.labels.intervention_c74feb"), true)}</title></polyline>`;
  svg += `<text x="${L}" y="${H - 2}" fill="var(--muted)" font-size="12">${UI.svgText("scope.renderScopeCurves.set_mean_activity_model_units_41850f", {})}</text><text x="${W - R}" y="${H - 2}" fill="var(--muted)" font-size="12" text-anchor="end">${UI.svgText("scope.renderScopeCurves.state_step_ebe1ee", {})}</text></svg>`;
  $('scope_compare_chart').innerHTML = lines.length ? `<div class="note">${UI.htmlText("scope.renderScopeCurves.baseline_dashed_intervention_solid_faecdb", {})}</div>` + svg + protocolTimelineSvg(shown.map(scope => ({
    name: scope.name,
    config: {
      experiment: scopeCompareResult.config.experiment
    }
  })), labels.filter(label => shownScopeObservations.has(label))) : `<div class="empty">${UI.htmlText("scope.renderScopeCurves.no_complete_responses_or_scope_and_observations_not_sele_815968", {})}</div>`;
  $('scope_response_rows').innerHTML = shown.flatMap(scope => labels.filter(label => shownScopeObservations.has(label)).map(label => {
    const o = scope.result.summary.find(row => row.type === label);
    if (!o) return '';
    return `<tr><td>${UI.html(scope.name)}</td><td>${UI.html(label)}</td><td>${UI.html(fmt(o.baseline_sum))}</td><td>${UI.html(fmt(o.intervention_sum))}</td><td>${UI.html(fmt(o.sum_delta))}</td><td>${UI.html(fmt(o.baseline_mean))}</td><td>${UI.html(fmt(o.intervention_mean))}</td><td>${UI.html(fmt(o.mean_delta))}</td><td>${UI.html(o.relative_sum_delta === null ? UI.msg("scope.controls.baseline_60a4ed", {}) : (100 * o.relative_sum_delta).toFixed(3) + '%')}</td></tr>`;
  })).join('');
}
function renderScopeComparison(result, historical = false) {
  scopeCompareResult = result;
  renderScopeRows(result.scopes);
  shownScopeIds.clear();
  shownScopeObservations.clear();
  result.scopes.filter(s => s.status === 'completed' && s.result).slice(0, 2).forEach(s => shownScopeIds.add(s.case_id));
  result.config.experiment.observations.slice(0, 3).forEach(o => shownScopeObservations.add(o.name));
  renderScopeCurves();
  const count = result.scopes.filter(s => s.status === 'completed').length,
    labels = {
      complete: UI.msg("scope.renderScopeComparison.comparisoncomplete_16db80", {}),
      cancelled: UI.msg("scope.renderScopeComparison.cancelled_a37778", {}),
      failed: UI.msg("scope.renderScopeComparison.comparisonfailed_b295c9", {})
    };
  scopeStatus(UI.msg("scope.renderScopeComparison.complete_scope_ea633c", {
    p0: historical ? UI.msg("scope.renderScopeComparison.save_92ce37", {}) : '',
    p1: labels[result.status] || result.status,
    p2: count,
    p3: result.scopes.length,
    p4: result.status !== 'complete' ? UI.msg("scope.renderScopeComparison.complete_scope_9da0b2", {}) : ''
  }));
  $('scope_compare_save').disabled = historical || !scopeCompareJob;
}
async function applyScopeConfig(config) {
  const response = await api('/api/cases');
  updateScopeRegistry(response.cases);
  selectedScopeIds.clear();
  const missing = [];
  for (const identity of config.cases || []) {
    const found = scopeRegistry.find(c => c.case_id === identity.case_id);
    if (found) selectedScopeIds.add(found.id);else missing.push(identity.case_id);
  }
  savedScopeProtocol = JSON.parse(JSON.stringify(config));
  savedScopeApplied = false;
  try {
    apply(config.experiment);
    applyRecording(config.recording);
    savedScopeApplied = true;
    changed();
  } catch (_) {/* Exact cross-scope IDs remain available independently of local operation roles. */}
  updateScopeRegistry(scopeRegistry);
  invalidateScopePreview();
  scopeCompareJob = null;
  if (missing.length) scopeStatus(UI.join([UI.msg("scope.applyScopeConfig.save_scope_b31ae2", {}), missing.join(', ')]), true);
}
$('scope_use_current').onclick = () => {
  if (busy) return;
  savedScopeProtocol = null;
  savedScopeApplied = false;
  invalidateScopePreview();
};
$('scope_compare_preview').onclick = previewScopeComparison;
$('scope_compare_run').onclick = startScopeComparison;
$('scope_cases_refresh').onclick = async () => {
  if (busy) return;
  try {
    const data = await api('/api/cases');
    updateScopeRegistry(data.cases);
    invalidateScopePreview();
  } catch (error) {
    scopeStatus(UI.errorText(error), true);
  }
};
$('scope_compare_cancel').onclick = async () => {
  try {
    await api('/api/cancel-scope-compare', {
      job_id: scopeCompareJob
    });
    $('scope_compare_cancel').disabled = true;
    scopeStatus(UI.msg("scope.controls.cancel_keep_completescope_e77790", {}));
  } catch (error) {
    scopeStatus(UI.errorText(error), true);
  }
};
$('scope_compare_save').onclick = async () => {
  if (busy || !scopeCompareJob || !scopeCompareResult) return;
  const id = scopeCompareJob;
  $('scope_compare_save').disabled = true;
  try {
    const saved = await api('/api/save-scope-comparison', {
      job_id: id
    });
    scopeStatus(UI.msg("scope.controls.scope_comparison_save_cd7aab", {
      p0: scopeCompareResult.status,
      p1: saved.folder
    }));
    document.dispatchEvent(new Event('lab-saved'));
  } catch (error) {
    scopeStatus(UI.errorText(error), true);
  } finally {
    if (scopeCompareJob === id) $('scope_compare_save').disabled = false;
  }
};
document.addEventListener('change', event => {
  const target = event.target;
  if (target.dataset.scopeCase !== undefined) {
    target.checked ? selectedScopeIds.add(target.dataset.scopeCase) : selectedScopeIds.delete(target.dataset.scopeCase);
    invalidateScopePreview();
  }
  if (target.dataset.scopeCurve !== undefined) {
    target.checked ? shownScopeIds.add(target.dataset.scopeCurve) : shownScopeIds.delete(target.dataset.scopeCurve);
    renderScopeCurves();
  }
  if (target.dataset.scopeObservation !== undefined) {
    target.checked ? shownScopeObservations.add(target.dataset.scopeObservation) : shownScopeObservations.delete(target.dataset.scopeObservation);
    renderScopeCurves();
  }
});
$('search_panel').addEventListener('input', scheduleCandidatePreview);
$('experiment').addEventListener('input', invalidateScopePreview);
document.addEventListener('lab-case', () => {
  searchRunning = false;
  searchRequestSignature = null;
  candidatePreview = null;
  scopePreviewResult = null;
  scopePreviewSignature = null;
  scopeCompareSequence++;
  scheduleCandidatePreview();
  updateScopeProtocolSummary();
});
let singleSearchContextSignature = null,
  singleSearchContextSequence = 0;
function cacheSingleSearchContext(report) {
  singleSearchContextSequence++;
  try {
    singleSearchContextSignature = searchSignature(report.experiment, report.options || {}, report);
  } catch (_) {
    singleSearchContextSignature = null;
  }
}
function invalidateSingleSearchContext() {
  if (!singleSearchContextSignature) return;
  let current = null;
  try {
    current = searchSignature();
  } catch (_) {}
  if (current !== singleSearchContextSignature) {
    singleSearchContextSequence++;
    singleSearchContextSignature = null;
    clearSearchContext('search', UI.msg("scope.invalidateSingleSearchContext.search_baseline_16a806", {}));
  }
}
async function checkSingleSearchContext() {
  if (busy || searchRunning) return;
  const seq = ++singleSearchContextSequence;
  let signature;
  try {
    const experiment = cfg(),
      options = searchOptions();
    validateCondition(experiment);
    signature = searchSignature(experiment, options);
    singleSearchContextSignature = signature;
    setSearchContextBusy(true);
    UI.text($('search_context_status'), UI.msg("scope.checkSingleSearchContext.baseline_1ea43d", {}));
    const result = await api('/api/search-context', {
      experiment,
      options
    });
    if (seq !== singleSearchContextSequence || signature !== searchSignature()) return;
    renderSearchContext(result, 'search');
  } catch (error) {
    if (seq === singleSearchContextSequence) {
      singleSearchContextSignature = null;
      clearSearchContext('search', UI.errorText(error));
    }
  } finally {
    setSearchContextBusy(false);
    scheduleCandidatePreview();
  }
}
$('search_context_check').onclick = checkSingleSearchContext;
document.addEventListener('lab-case', () => {
  singleSearchContextSequence++;
  singleSearchContextSignature = null;
  clearSearchContext('search');
  clearSearchDiagnostics('search');
});

for(const event of ['ui-language','ui-theme','ui-fonts'])document.addEventListener(event,()=>{renderScopeCurves();});
