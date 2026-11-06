"use strict";

/* Boundary counts and nested scope definitions never alter the source protocol. */
let boundaryReport = null,
  boundarySource = null,
  boundaryBaseId = null,
  boundarySequence = 0,
  boundaryExternalSequence = 0,
  boundaryExternalOffset = 0;
let boundaryExpansion = null,
  boundaryExpansionSignature = null,
  boundaryExpansionJob = null,
  boundaryExpansionArtifact = null;
let boundaryComparison = null,
  boundaryComparisonPreview = null,
  boundaryComparisonSignature = null,
  boundaryComparisonJob = null,
  boundaryComparisonArtifact = null,
  boundaryFixedSource = null;
let boundaryTask = null,
  boundaryTaskEpoch = 0;
const boundaryChosenCases = new Set(),
  boundaryExternalSeeds = new Set();
const analysisTabBeforeBoundary = analysisTab;
analysisTab = function (view) {
  analysisTabBeforeBoundary(view);
  $('analysis_boundary').hidden = view !== 'boundary';
};
function boundaryStatus(id, text, error = false) {
  UI.text($(id), text);
  $(id).classList.toggle('error', error);
}
function boundaryCount(v) {
  return v == null ? UI.msg("boundary.boundaryCount.not_recorded_7450cc", {}) : num(v);
}
function boundaryPercent(v) {
  return v == null ? UI.msg("boundary.boundaryPercent.definition_0_8bcf5a", {}) : UI.percent(Number(v), 3);
}
function boundaryCoverage(s) {
  return UI.msg("boundary.boundaryCoverage.contact_count_coverage_1342e1", {
    p0: boundaryCount(s?.internal_input_contacts),
    p1: boundaryCount(s?.total_input_contacts),
    p2: boundaryCount(s?.external_input_contacts),
    p3: boundaryPercent(s?.input_fraction)
  });
}
function boundarySourceKey() {
  return JSON.stringify({
    case_id: overview?.manifest.case_id,
    source: analysisCurrent?.source
  });
}
function boundaryInvalidate() {
  boundarySequence++;
  boundaryExternalSequence++;
  boundaryExpansionSignature = null;
  boundaryComparisonSignature = null;
  boundaryComparisonPreview = null;
  $('boundary_expand_create').disabled = true;
  $('boundary_compare_run').disabled = true;
}
async function boundaryLoad(fromSource = true) {
  try {
    if (busy || searchRunning) throw UI.error("boundary.boundaryLoad.stop_43ed5c", {});
    const seq = ++boundarySequence;
    if (fromSource) {
      if (!analysisCurrent?.source) throw UI.error("boundary.boundaryLoad.open_a_source_result_first_692119", {});
      await analysisPersistHandles();
      boundarySource = replayClone(analysisCurrent.source);
    } else boundarySource = null;
    const key = boundarySourceKey(),
      payload = {
        node_ids: parseBodyIds($('boundary_ids').value, true)
      };
    if (boundarySource) payload.source = boundarySource;else payload.experiment = cfg();
    boundaryStatus('boundary_status', UI.msg("boundary.boundaryLoad.connections_e3bf2e", {}));
    const result = await api('/api/boundary', payload);
    if (seq !== boundarySequence || key !== boundarySourceKey()) return;
    boundaryReport = result;
    boundaryBaseId = result.scope?.registry_id || result.scope?.id || savedCaseCatalog.find(c => c.case_id === overview.manifest.case_id)?.id;
    renderBoundary(result);
    boundaryStatus('boundary_status', UI.msg("boundary.boundaryLoad.contact_count_coverage_scope_members_796854", {}));
    analysisTab('boundary');
  } catch (e) {
    boundaryStatus('boundary_status', UI.errorText(e), true);
  }
}
function renderBoundary(r) {
  const s = r.scope || {},
    b = s.boundary || s,
    rule = s.selection || s.selection_definition || s.extraction || {};
  UI.text($('boundary_scope'), UI.msg("boundary.renderBoundary.node_internal_edges_internal_input_contacts_omitted_inpu_6a6f7f", {
    p0: boundaryCount(s.node_count ?? s.selected_node_count),
    p1: boundaryCount(s.internal_edges),
    p2: boundaryCount(b.internal_contacts ?? b.internal_input_contacts),
    p3: boundaryCount(b.external_input_contacts),
    p4: boundaryCount(b.total_input_contacts),
    p5: s.truncated ?? rule.truncated ? UI.msg("boundary.renderBoundary.message_4fb9aa", {}) : UI.msg("boundary.renderBoundary.message_9a1828", {})
  }));
  $('boundary_base').innerHTML = `<div>${UI.htmlText("boundary.renderBoundary.keepall_scopemembers_category_adjacency_layers_4fa501", {
    p0: s.case_name || s.name || r.identity?.case_id || overview.manifest.case_id,
    p1: categoryNames[rule.category] || rule.category || UI.msg("boundary.renderBoundary.not_recorded_7450cc", {}),
    p2: boundaryCount(rule.hops ?? rule.requested_hops),
    p3: {
      incoming: UI.msg("boundary.renderBoundary.upstream_a9ab29", {}),
      outgoing: UI.msg("boundary.renderBoundary.downstream_fde36e", {}),
      both: UI.msg("boundary.renderBoundary.bidirectional_52904a", {})
    }[rule.direction] || rule.direction || UI.msg("boundary.renderBoundary.not_recorded_7450cc", {}),
    p4: boundaryCount(rule.max_nodes ?? s.max_nodes)
  })}</div><details><summary>${UI.htmlText("boundary.renderBoundary.original_scope_extraction_definition_f29c78", {})}</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${UI.html(JSON.stringify(rule, null, 2))}</pre></details>`;
  $('boundary_groups').innerHTML = (r.groups || []).map((g, k) => `<details><summary>${UI.htmlText("boundary.controls.members_407cb2", {
    p0: g.name || g.key,
    p1: g.body_ids?.length ?? g.nodes?.length ?? '—',
    p2: boundaryCoverage(g.summary)
  })}</summary><div class="tablewrap"><table><thead><tr><th>${UI.htmlText("boundary.controls.body_id_type_category_d26bac", {})}</th><th>${UI.htmlText("boundary.controls.internal_inputs_b062ed", {})}</th><th>${UI.htmlText("boundary.controls.complete_input_fecafe", {})}</th><th>${UI.htmlText("boundary.controls.omitted_inputs_620a7a", {})}</th><th>${UI.htmlText("boundary.controls.contact_count_coverage_10ab5d", {})}</th></tr></thead><tbody>${(g.nodes || []).map(n => `<tr><td>${UI.html(n.body_id)} · ${UI.html(n.type || '')} · ${UI.html(categoryNames[n.category] || n.category || UI.msg("boundary.controls.unannotated_endpoints_0aeb6e", {}))}</td><td>${UI.html(boundaryCount(n.internal_input_contacts))}</td><td>${UI.html(boundaryCount(n.total_input_contacts))}</td><td>${UI.html(boundaryCount(n.external_input_contacts))}</td><td>${UI.html(boundaryPercent(n.input_fraction))}</td></tr>`).join('')}</tbody></table></div></details>`).join('');
  $('boundary_group').replaceChildren();
  for (const [k, g] of (r.groups || []).entries()) $('boundary_group').append(UI.option(g.name || g.key, String(k)));
  boundaryExpansionSignature = null;
  $('boundary_expand_create').disabled = true;
}
async function boundaryExternal(offset = 0) {
  try {
    if (!boundaryReport) throw UI.error("boundary.boundaryExternal.scope_boundary_66c4af", {});
    const group = boundaryReport.groups[Number($('boundary_group').value)];
    if (!group?.body_ids?.length) throw UI.error("boundary.boundaryExternal.members_0da47b", {});
    const seq = ++boundaryExternalSequence,
      key = boundarySourceKey();
    const result = await api('/api/boundary-external', {
      body_ids: group.body_ids,
      category: $('boundary_category').value,
      scan_limit: Number($('boundary_scan').value),
      limit: 50,
      offset
    });
    if (seq !== boundaryExternalSequence || key !== boundarySourceKey()) return;
    boundaryExternalOffset = offset;
    const rows = result.nodes || result.rows || [];
    boundaryStatus('boundary_external_status', UI.msg("boundary.boundaryExternal.members_category_7787ca", {
      p0: boundaryCount(result.scanned_edges),
      p1: boundaryCount(result.total_required_edges),
      p2: result.scan_complete ? UI.msg("boundary.boundaryExternal.connection_countsort_1ba996", {}) : UI.msg("boundary.boundaryExternal.sort_f4072d", {}),
      p3: boundaryCount(result.matching_external_count),
      p4: rows.length,
      p5: categoryNames[$('boundary_category').value] || UI.msg("boundary.boundaryExternal.all_categories_33f222", {})
    }));
    $('boundary_external_rows').innerHTML = rows.map(n => `<tr><td><input type="checkbox" data-boundary-external="${esc(n.body_id)}" ${boundaryExternalSeeds.has(n.body_id) ? 'checked' : ''} ${n.eligible ? '' : 'disabled'} ${UI.htmlAttribute("aria-label", "boundary.controls.message_7bcb04", {
      p0: n.body_id
    })}></td><td>${UI.html(n.body_id)}</td><td>${UI.html(n.type || '')} / ${UI.html(categoryNames[n.category] || n.category || UI.msg("boundary.controls.unannotated_endpoints_0aeb6e", {}))}</td><td>${UI.html(boundaryCount(n.count))}</td><td>${(n.targets || []).map(t => esc(t.body_id) + ' (' + boundaryCount(t.count) + ')').join(', ')}</td><td>${UI.html(n.eligible ? UI.msg("boundary.controls.eligible_for_inclusion_de6a80", {}) : UI.msg("boundary.controls.category_c8d0ff", {}))}</td></tr>`).join('');
    $('boundary_prev').disabled = offset === 0;
    $('boundary_next').disabled = offset + rows.length >= (result.matching_external_count ?? offset + rows.length);
  } catch (e) {
    boundaryStatus('boundary_external_status', UI.errorText(e), true);
  }
}
function boundaryExpansionConfig() {
  if (!boundaryBaseId) throw UI.error("boundary.boundaryExpansionConfig.savescope_9aef30", {});
  const budgets = $('boundary_budgets').value.trim().split(/[\s,，]+/).filter(Boolean).map(Number);
  if (!budgets.length || budgets.some(v => !Number.isInteger(v) || v < 1) || budgets.some((v, k) => k && v <= budgets[k - 1])) throw UI.error("boundary.boundaryExpansionConfig.nodebudget_10134f", {});
  return {
    base_case_id: boundaryBaseId,
    budgets: budgets,
    added_body_ids: parseBodyIds($('boundary_seeds').value, true),
    hops: Number($('boundary_hops').value),
    direction: $('boundary_direction').value,
    category: $('boundary_category').value,
    scan_limit: Number($('boundary_scan').value),
    max_internal_edges: Number($('boundary_max_edges').value),
    max_bytes: Number($('boundary_max_bytes').value) * 1024 ** 2,
    max_disk_bytes: Number($('boundary_max_disk').value) * 1024 ** 2
  };
}
function boundaryRenderLevels(r) {
  $('boundary_levels').innerHTML = (r.levels || []).map((l, k) => {
    const e = l.estimates || l.estimate || l,
      labels = {
        completed: UI.msg("boundary.controls.run_897b61", {}),
        built: UI.msg("boundary.controls.run_897b61", {}),
        reused: UI.msg("boundary.controls.savescope_78e73b", {}),
        existing: UI.msg("boundary.controls.savescope_78e73b", {}),
        not_run: UI.msg("boundary.controls.message_195803", {}),
        cancelled: UI.msg("boundary.controls.cancelled_a37778", {}),
        failed: UI.msg("boundary.controls.failed_28384d", {}),
        preview: UI.msg("boundary.controls.message_13d61f", {})
      };
    return `<div class="analysis-member"><strong>${UI.htmlText("boundary.controls.message_60545b", {
      p0: k + 1,
      p1: labels[l.status] || UI.code(l.status) || UI.msg("boundary.controls.message_13d61f", {})
    })}</strong><div>${UI.htmlText("boundary.controls.keep_nodebudget_679ff7", {
      p0: boundaryCount(l.retained_node_count ?? l.core_node_count ?? l.previous_node_count),
      p1: boundaryCount(l.added_node_count ?? l.new_node_count),
      p2: boundaryCount(l.node_count ?? l.body_ids?.length),
      p3: boundaryCount(l.budget ?? l.max_nodes ?? l.node_budget),
      p4: l.truncated ?? l.selection?.truncated ? UI.msg("boundary.controls.message_dc26ee", {}) : UI.msg("boundary.controls.message_9a1828", {})
    })}</div><div>${UI.htmlText("boundary.controls.internal_edges_366984", {
      p0: boundaryCount(l.internal_edges ?? e.internal_edges ?? e.internal_edges_estimate),
      p1: l.internal_edge_count_exact === true ? UI.msg("boundary.controls.message_d1c1ea", {}) : l.internal_edge_count_exact === false ? UI.msg("boundary.controls.message_f874b9", {}) : UI.msg("boundary.controls.not_recorded_c44900", {}),
      p2: (e.estimated_peak_memory_bytes ?? e.memory_bytes) == null ? UI.msg("boundary.controls.not_recorded_7450cc", {}) : scopeBytes(e.estimated_peak_memory_bytes ?? e.memory_bytes),
      p3: (e.estimated_disk_bytes ?? e.disk_bytes) == null ? UI.msg("boundary.controls.not_recorded_7450cc", {}) : scopeBytes(e.estimated_disk_bytes ?? e.disk_bytes)
    })}</div><div>${UI.html(UI.list((l.truncation_reasons || l.reasons || [l.selection?.truncation_reason].filter(Boolean)).map(UI.code)))}${l.error ? ' · ' + esc(l.error) : ''}</div>${l.case_id ? '<div>' + esc(l.case_id) + '</div>' : ''}<details><summary>${UI.htmlText("boundary.controls.exact_members_and_rules_b494dd", {})}</summary><div style="overflow-wrap:anywhere">${UI.html((l.body_ids || []).join(', '))}</div><div>${UI.html(JSON.stringify(l.rule || r.config || {}))}</div></details></div>`;
  }).join('');
}
async function boundaryPreviewExpansion() {
  try {
    if (busy || searchRunning) return;
    const config = boundaryExpansionConfig(),
      signature = JSON.stringify(config),
      seq = ++boundarySequence;
    boundaryStatus('boundary_expand_status', UI.msg("boundary.boundaryPreviewExpansion.members_3d8273", {}));
    $('boundary_expand_create').disabled = true;
    const r = await api('/api/expansion-preview', {
      config
    });
    if (seq !== boundarySequence || signature !== JSON.stringify(boundaryExpansionConfig())) return;
    boundaryExpansion = r;
    boundaryExpansionSignature = signature;
    boundaryRenderLevels(r);
    $('boundary_expand_create').disabled = r.compatible === false || r.can_build === false || r.build_allowed === false;
    boundaryStatus('boundary_expand_status', (r.errors || []).join(' / ') || UI.msg("boundary.boundaryPreviewExpansion.complete_save_scope_fcc09e", {}));
  } catch (e) {
    boundaryStatus('boundary_expand_status', UI.errorText(e), true);
  }
}
function boundaryLock(kind, active) {
  if (active) {
    boundaryTask = kind;
    busy = true;
  } else {
    boundaryTask = null;
    busy = false;
  }
  for (const id of ['boundary_expand_setup', 'boundary_compare_setup']) $(id).inert = active;
  for (const id of ['experiment', 'protocol_panel', 'global_panel']) if ($(id)) $(id).inert = active;
  $('boundary_expand_cancel').disabled = !active || kind !== 'expansion';
  $('boundary_compare_cancel').disabled = !active || kind !== 'comparison';
  $('boundary_expand_save').disabled = active || !boundaryExpansionJob && !boundaryExpansionArtifact;
  $('boundary_compare_save').disabled = active || !boundaryComparisonJob && !boundaryComparisonArtifact;
}
async function boundaryStart(kind) {
  try {
    if (busy || searchRunning) return;
    const payload = kind === 'expansion' ? {
      config: boundaryExpansionConfig()
    } : boundaryComparePayload();
    if (kind === 'expansion' ? boundaryExpansionSignature !== JSON.stringify(payload.config) : boundaryComparisonSignature !== JSON.stringify(payload)) throw UI.error("boundary.boundaryStart.definition_check_request_4dd56b", {});
    boundaryLock(kind, true);
    await analysisPersistHandles();
    if (boundaryExpansionJob && !boundaryExpansionArtifact) await boundarySave('expansion');
    if (boundaryComparisonJob && !boundaryComparisonArtifact) await boundarySave('comparison');
    const r = await api(kind === 'expansion' ? '/api/start-expansion' : '/api/start-scope-plan-comparison', payload);
    if (kind === 'expansion') {
      boundaryExpansionJob = r.job_id;
      boundaryExpansionArtifact = null;
    } else {
      boundaryComparisonJob = r.job_id;
      boundaryComparisonArtifact = null;
    }
    boundaryPoll(kind, r.job_id, ++boundaryTaskEpoch);
  } catch (e) {
    boundaryLock(kind, false);
    boundaryStatus(kind === 'expansion' ? 'boundary_expand_status' : 'boundary_compare_status', UI.errorText(e), true);
  }
}
async function boundaryPoll(kind, id, epoch) {
  const target = kind === 'expansion' ? 'boundary_expand_status' : 'boundary_compare_status';
  try {
    const snapshot = await api((kind === 'expansion' ? '/api/expansion-job?' : '/api/scope-plan-job?') + new URLSearchParams({
      job_id: id
    }));
    if (epoch !== boundaryTaskEpoch) return;
    if (snapshot.status === 'running') {
      const p = snapshot.progress || {};
      boundaryStatus(target, UI.msg("boundary.boundaryPoll.complete_942918", {
        p0: UI.code(p.phase || 'build') || UI.msg("boundary.boundaryPoll.message_32c8d3", {}),
        p1: p.logical_completed ?? p.completed ?? p.completed_tasks ?? p.level ?? 0,
        p2: p.logical_task_count ?? p.total ?? p.total_tasks ?? p.level_count ?? '—',
        p3: p.current_case_id || ''
      }));
      setTimeout(() => boundaryPoll(kind, id, epoch), 700);
      return;
    }
    boundaryLock(kind, false);
    if (snapshot.result) {
      if (kind === 'expansion') {
        boundaryExpansion = snapshot.result;
        boundaryRenderLevels(snapshot.result);
        await refreshSaved();
        boundaryRefreshCases();
      } else boundaryRenderComparison(snapshot.result);
      if (kind === 'expansion') boundaryStatus(target, UI.join([UI.code(snapshot.result.status || snapshot.status),' · ',snapshot.result.termination_reason ? UI.code(snapshot.result.termination_reason) : snapshot.error ? UI.errorText(Error(snapshot.error)) : '']));
    } else boundaryStatus(target, UI.jobText(snapshot, UI.msg("boundary.boundaryPoll.message_29e1b0", {})), true);
  } catch (e) {
    if (epoch !== boundaryTaskEpoch) return;
    boundaryLock(kind, false);
    boundaryStatus(target, UI.errorText(e), true);
  }
}
async function boundarySave(kind) {
  const artifact = kind === 'expansion' ? boundaryExpansionArtifact : boundaryComparisonArtifact;
  if (artifact) return artifact;
  const job_id = kind === 'expansion' ? boundaryExpansionJob : boundaryComparisonJob;
  if (!job_id) throw UI.error("boundary.boundarySave.save_2b1f79", {});
  const result = await api(kind === 'expansion' ? '/api/save-expansion' : '/api/save-scope-plan-comparison', {
    job_id
  });
  const id = result.artifact_id || result.folder.split(/[\\/]/).pop();
  if (kind === 'expansion') boundaryExpansionArtifact = id;else boundaryComparisonArtifact = id;
  document.dispatchEvent(new Event('lab-saved'));
  return id;
}
function boundaryRefreshCases() {
  const catalog = savedCaseCatalog || [];
  $('boundary_cases').innerHTML = catalog.map(c => `<label class="pill"><input type="checkbox" data-boundary-case="${esc(c.id)}" ${boundaryChosenCases.has(c.id) ? 'checked' : ''}>${UI.htmlText("boundary.controls.node_b31582", {
    p0: c.name || c.case_id,
    p1: boundaryCount(c.node_count)
  })}</label>`).join('');
}
async function boundaryAdoptFixed() {
  try {
    if (!analysisCurrent?.source) throw UI.error("boundary.boundaryAdoptFixed.open_fixed_plan_c6d806", {});
    await analysisPersistHandles();
    boundaryFixedSource = replayClone(analysisCurrent.source);
    boundaryComparisonSignature = null;
    $('boundary_compare_run').disabled = true;
    UI.text($('boundary_fixed'), UI.msg("boundary.boundaryAdoptFixed.pin_intervention_gain_ba0eb9", {
      p0: analysisCurrent.label,
      p1: (analysisCurrent.experiment?.intervention_ids || []).join(', ') || UI.msg("boundary.boundaryAdoptFixed.no_intervention_269771", {}),
      p2: analysisCurrent.experiment?.gain,
      p3: analysisCurrent.experiment?.intervention_start,
      p4: analysisCurrent.experiment?.intervention_stop
    }));
    boundaryChosenCases.clear();
    const c = savedCaseCatalog.find(c => c.case_id === overview.manifest.case_id);
    if (c) boundaryChosenCases.add(c.id);
    for (const l of boundaryExpansion?.levels || []) {
      const item = savedCaseCatalog.find(c => c.case_id === l.case_id);
      if (item && ['completed', 'built', 'existing', 'reused'].includes(l.status)) boundaryChosenCases.add(item.id);
    }
    boundaryRefreshCases();
  } catch (e) {
    boundaryStatus('boundary_compare_status', UI.errorText(e), true);
  }
}
function boundaryComparePayload() {
  if (!boundaryFixedSource) throw UI.error("boundary.boundaryComparePayload.fixed_plan_9c42bd", {});
  if (!boundaryChosenCases.size) throw UI.error("boundary.boundaryComparePayload.select_a_calculation_scope_first_e2a6ce", {});
  return {
    source: replayClone(boundaryFixedSource),
    scope_ids: [...boundaryChosenCases],
    include_original: $('boundary_original').checked,
    recording: {
      mode: 'none'
    },
    max_tasks: Number($('boundary_max_tasks').value)
  };
}
async function boundaryPreviewComparison() {
  try {
    if (busy || searchRunning) return;
    const payload = boundaryComparePayload(),
      signature = JSON.stringify(payload),
      seq = ++boundarySequence;
    const r = await api('/api/scope-plan-preview', payload);
    if (seq !== boundarySequence || signature !== JSON.stringify(boundaryComparePayload())) return;
    boundaryComparisonPreview = r;
    boundaryComparisonSignature = signature;
    UI.text($('boundary_compare_preflight'), UI.join([UI.msg("boundary.boundaryPreviewComparison.budget_baseline_intervention_18ea13", {
      p0: boundaryCount(r.logical_task_count ?? r.task_count ?? r.tasks?.length),
      p1: payload.max_tasks,
      p2: boundaryCount(r.estimated_baseline_simulations),
      p3: boundaryCount(r.estimated_intervention_simulations),
      p4: r.recording_peak_bytes == null ? UI.msg("boundary.boundaryPreviewComparison.not_recorded_7450cc", {}) : scopeBytes(r.recording_peak_bytes)
    }), UI.list((r.cases || r.scopes || []).map(c => UI.msg("boundary.controls.node_106f60", {
      p0: c.name || c.case_id,
      p1: boundaryCount(c.node_count),
      p2: boundaryCount(c.internal_edges),
      p3: c.compatible === false || (c.errors || []).length || missingScopeMembers(c.missing_members) ? UI.msg("boundary.controls.message_4ae9eb", {}) : UI.msg("boundary.controls.message_e1ba81", {}),
      p4: (c.errors || []).join(' / '),
      p5: missingScopeMembers(c.missing_members)
    })), '\n')]));
    $('boundary_compare_preflight').style.whiteSpace = 'pre-wrap';
    $('boundary_compare_run').disabled = r.compatible === false;
    boundaryStatus('boundary_compare_status', (r.errors || []).join(' / ') || UI.msg("boundary.boundaryPreviewComparison.members_scope_no_interventionbaseline_b224be", {}));
  } catch (e) {
    boundaryStatus('boundary_compare_status', UI.errorText(e), true);
  }
}
function boundaryConstraints(c) {
  if (!c) return `<div>${UI.htmlText("boundary.boundaryConstraints.constraints_not_recorded_6955ce", {})}</div>`;
  const fail = {
    minimum_target_loss: UI.msg("boundary.boundaryConstraints.target_decrease_c52d3b", {}),
    undefined_target_metric: UI.msg("boundary.boundaryConstraints.target_metric_definition_d98e2e", {}),
    maximum_protected_loss: UI.msg("boundary.boundaryConstraints.protection_exceeded_aefea8", {}),
    maximum_nodes: UI.msg("boundary.boundaryConstraints.node_count_exceeded_730c06", {})
  };
  return (c.condition_results || []).map(row => {
    const target = row.target_constraint;
    return `<div>${UI.html(row.name)} · ${UI.html(target ? UI.msg("boundary.controls.target_d8cc5a", {
      p0: target.observation,
      p1: searchLossText(target.loss, target.metric),
      p2: searchLossText(target.minimum, target.metric),
      p3: target.satisfied ? UI.msg("boundary.controls.satisfied_4e8156", {}) : UI.msg("boundary.controls.satisfied_ec9205", {})
    }) : UI.msg("boundary.controls.targetnot_recorded_be2b66", {}))}</div>` + Object.entries(row.protected_constraints || {}).map(([name, p]) => `<div>${UI.htmlText("boundary.controls.protection_7fbdf3", {
      p0: name,
      p1: searchLossText(p.loss, p.metric),
      p2: searchLossText(p.limit, p.metric),
      p3: p.satisfied ? UI.msg("boundary.controls.satisfied_4e8156", {}) : UI.msg("boundary.controls.satisfied_ec9205", {})
    })}</div>`).join('') + (!row.feasible ? `<div>${UI.htmlText('constraint.failures')}` + (row.violations || []).map(v => UI.html(fail[v] || UI.code(v))).join(' / ') + '</div>' : '');
  }).join('');
}
function boundaryTaskCompleted(t) {
  return t.status === 'completed' && t.result;
}
function boundaryRenderComparison(r, artifact = null) {
  boundaryComparison = r;
  if (artifact) {
    boundaryComparisonArtifact = artifact;
    boundaryComparisonJob = null;
  }
  const all = r.tasks || [],
    complete = all.filter(boundaryTaskCompleted);
  const scopes = [...new Map(all.map(t => [t.case_id, t.name || t.case_id])).entries()],
    plans = [...new Map(all.map(t => [t.plan_id, t.label || t.plan_id])).entries()];
  for (const [id, items] of [['boundary_curve_range', scopes], ['boundary_curve_plan', plans]]) {
    $(id).replaceChildren();
    for (const [value, label] of items) $(id).append(UI.option(label, value));
  }
  const labels = Object.keys(complete[0]?.result.series || {});
  $('boundary_curve_observation').replaceChildren();
  for (const label of labels) $('boundary_curve_observation').append(UI.option(label, label));
  const s = r.simulations || r;
  boundaryStatus('boundary_compare_status', UI.msg("boundary.boundaryRenderComparison.baseline_intervention_770687", {
    p0: UI.code(r.status),
    p1: complete.length,
    p2: all.length,
    p3: boundaryCount(s.completed_baseline_simulations ?? s.baseline_completed),
    p4: boundaryCount(s.baseline_simulations ?? s.baseline_started),
    p5: boundaryCount(s.completed_intervention_simulations ?? s.intervention_completed),
    p6: boundaryCount(s.intervention_simulations ?? s.intervention_started),
    p7: boundaryCount(s.baseline_reuses ?? s.cache_hits)
  }));
  $('boundary_compare_save').disabled = !boundaryComparisonJob && !boundaryComparisonArtifact;
  boundaryRenderCurves();
}
function boundaryRenderCurves() {
  if (!boundaryComparison) return;
  const range = $('boundary_curve_range').value,
    plan = $('boundary_curve_plan').value,
    label = $('boundary_curve_observation').value,
    t = (boundaryComparison.tasks || []).find(t => t.case_id === range && t.plan_id === plan),
    r = t?.result;
  const status = {
    completed: UI.msg("boundary.boundaryRenderCurves.complete_c0b3fb", {}),
    not_run: UI.msg("boundary.boundaryRenderCurves.run_62cdc8", {}),
    cancelled: UI.msg("boundary.boundaryRenderCurves.cancel_2cd0f3", {}),
    failed: UI.msg("boundary.boundaryRenderCurves.failed_28384d", {})
  };
  $('boundary_compare_rows').innerHTML = (boundaryComparison.tasks || []).filter(t => (!range || t.case_id === range) && (!plan || t.plan_id === plan)).map(t => `<div><strong>${UI.html(t.name || t.case_id)} · ${UI.html(t.label || t.plan_id)} · ${UI.html(status[t.status] || UI.code(t.status))}</strong><div>${UI.htmlText("boundary.controls.compute_nodes_internal_edges_omitted_inputs_omitted_outp_be33e7", {
    p0: boundaryCount(t.node_count),
    p1: boundaryCount(t.internal_edges),
    p2: boundaryCount(t.external_input_contacts),
    p3: boundaryCount(t.external_output_contacts),
    p4: boundaryCount(t.total_input_contacts),
    p5: (t.body_ids || []).join(', ') || UI.msg("boundary.controls.no_intervention_269771", {})
  })}</div>${boundaryTaskCompleted(t) ? `<div>${UI.html(t.constraints?.feasible === false ? UI.msg("boundary.controls.constraints_satisfied_1fd22e", {}) : UI.join([UI.msg("boundary.controls.constraints_14c6f0", {}), t.constraints ? UI.msg("boundary.controls.satisfied_4e8156", {}) : UI.msg("boundary.controls.not_recorded_7450cc", {})]))} · ${UI.html((t.constraints?.failed_condition_names || []).join(', '))}</div>${boundaryConstraints(t.constraints)}<div class="tablewrap"><table><thead><tr><th>${UI.htmlText("boundary.controls.observation_f262ba", {})}</th><th>${UI.htmlText("boundary.controls.absolute_baseline_mean_4600de", {})}</th><th>${UI.htmlText("boundary.controls.absolute_intervention_mean_d3b8b3", {})}</th><th>${UI.htmlText("boundary.controls.absolute_change_8ab166", {})}</th><th>${UI.htmlText("boundary.controls.relative_change_d26b48", {})}</th><th>${UI.htmlText("boundary.controls.fixed_observation_input_coverage_ea7266", {})}</th></tr></thead><tbody>${(t.result.summary || []).map(o => {
    const cover = (t.observation_coverage || []).find(g => g.name === o.type);
    return `<tr><td>${UI.html(o.type)}</td><td>${UI.html(contextNumber(o.baseline_mean))}</td><td>${UI.html(contextNumber(o.intervention_mean))}</td><td>${UI.html(contextNumber(o.mean_delta))}</td><td>${UI.html(o.relative_sum_delta == null ? UI.msg("boundary.controls.definition_2ba10d", {}) : (100 * o.relative_sum_delta).toFixed(3) + '%')}</td><td>${UI.html(cover ? boundaryCoverage(cover.summary || cover) : UI.msg("boundary.controls.not_recorded_7450cc", {}))}</td></tr>`;
  }).join('')}</tbody></table></div><button data-boundary-analyze="${esc(t.task_id)}">${UI.htmlText("boundary.controls.result_analysis_6e6a12", {})}</button>` : `<div>${UI.html(UI.jobText(t, UI.msg("boundary.controls.assessment_5c46a3", {})))}</div>`}</div>`).join('');
  if (!boundaryTaskCompleted(t) || !r.series?.[label]) {
    UI.text($('boundary_compare_chart'), UI.msg("boundary.boundaryRenderCurves.scope_plan_4a6631", {}));
    return;
  }
  const values = r.series[label],
    W = 800,
    H = 270,
    L = 65,
    R = 20,
    T = 20,
    B = 38,
    c = r.config?.experiment || boundaryComparison.config.experiment,
    steps = c.steps;
  let max = 1e-12;
  for (const branch of ['baseline', 'intervention']) for (const v of values[branch] || []) max = Math.max(max, v);
  max *= 1.1;
  const x = k => L + k / steps * (W - L - R),
    y = v => H - B - v / max * (H - T - B),
    color = observationColor(label);
  let svg = `<div>${UI.htmlText("boundary.boundaryRenderCurves.baseline_intervention_cf88f3", {
    p0: t.name,
    p1: t.label,
    p2: label
  })}</div><svg class="plot" viewBox="0 0 ${W} ${H}" role="img" ${UI.htmlAttribute("aria-label", "boundary.boundaryRenderCurves.fixed_plan_scope_5f7004", {})}>`;
  for (let k = 0; k < 5; k++) {
    const v = max * k / 4;
    svg += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--chart-grid)"/><text x="${L - 8}" y="${y(v) + 4}" fill="var(--muted)" text-anchor="end" font-size="12">${UI.html(fmt(v), true)}</text>`;
  }
  for (const branch of ['baseline', 'intervention']) if (values[branch]) svg += `<polyline points="${values[branch].map((v, k) => x(k) + ',' + y(v)).join(' ')}" fill="none" stroke="${color}" stroke-width="2" ${branch === 'intervention' ? 'stroke-dasharray="6 4"' : ''}><title>${UI.html(t.name, true)} · ${UI.html(t.label, true)} · ${UI.html(label, true)} · ${UI.html(branch === 'baseline' ? UI.msg("boundary.boundaryRenderCurves.baseline_a7ac58", {}) : UI.msg("response.labels.intervention_c74feb"), true)}</title></polyline>`;
  svg += `<text x="${L}" y="${H - 3}" fill="var(--muted)" font-size="12">${UI.svgText("boundary.boundaryRenderCurves.set_mean_activity_model_units_state_step0_95b502", {
    p0: steps
  })}</text></svg>`;
  $('boundary_compare_chart').innerHTML = svg + protocolTimelineSvg([{
    name: t.name + ' · ' + t.label,
    config: {
      experiment: c
    }
  }], [label]);
}
async function boundaryAnalyze(taskId) {
  try {
    if (busy || searchRunning) throw UI.error("boundary.boundaryAnalyze.stop_43ed5c", {});
    const task = boundaryComparison?.tasks.find(t => t.task_id === taskId);
    if (!boundaryTaskCompleted(task)) throw UI.error("boundary.boundaryAnalyze.open_dc85c4", {});
    const artifact = await boundarySave('comparison');
    if (!(await beforeAnalysisOpen(artifact, {
      case_id: task.case_id
    }))) return;
    await switchAction(async () => {
      const opened = await api('/api/open-scope-plan-result', {
        artifact_id: artifact,
        task_id: taskId
      });
      if (opened.overview && opened.overview.manifest.case_id !== overview.manifest.case_id) activateOverview(opened.overview);
      analysisClearExceptOpened('source');
      const source = {
        label: task.name + ' · ' + task.label,
        source: opened.source || {
          kind: 'artifact',
          artifact_id: artifact,
          task_id: taskId
        },
        experiment: opened.experiment || task.result.config.experiment
      };
      replaySource = source;
      bindDifferenceSource(source);
      document.dispatchEvent(new CustomEvent('lab-replay-source', {
        detail: source
      }));
      analysisOpening = false;
      analysisTab('ranking');
      analysisContext();
    });
  } catch (e) {
    analysisOpening = false;
    boundaryStatus('boundary_compare_status', UI.errorText(e), true);
  }
}
$('boundary_source').onclick = () => boundaryLoad(true);
$('boundary_current').onclick = () => boundaryLoad(false);
$('boundary_selection').onclick = () => {
  $('boundary_ids').value = analysisSelection.ids().join(', ');
  boundaryLoad(!!analysisCurrent?.source);
};
$('boundary_external').onclick = () => boundaryExternal();
$('boundary_prev').onclick = () => boundaryExternal(Math.max(0, boundaryExternalOffset - 50));
$('boundary_next').onclick = () => boundaryExternal(boundaryExternalOffset + 50);
$('boundary_add_seeds').onclick = () => {
  try {
    $('boundary_seeds').value = [...new Set([...parseBodyIds($('boundary_seeds').value, true), ...boundaryExternalSeeds])].join(', ');
    boundaryInvalidate();
    boundaryStatus('boundary_expand_status', UI.msg("boundary.controls.message_62aa43", {
      p0: boundaryExternalSeeds.size
    }));
  } catch (e) {
    boundaryStatus('boundary_expand_status', UI.errorText(e), true);
  }
};
$('boundary_expand_preview').onclick = boundaryPreviewExpansion;
$('boundary_expand_create').onclick = () => boundaryStart('expansion');
$('boundary_compare_preview').onclick = boundaryPreviewComparison;
$('boundary_compare_run').onclick = () => boundaryStart('comparison');
$('boundary_use_source').onclick = boundaryAdoptFixed;
$('boundary_cases_refresh').onclick = async () => {
  await refreshSaved();
  boundaryRefreshCases();
};
for (const kind of ['expand', 'compare']) $('boundary_' + kind + '_save').onclick = async () => {
  try {
    const k = kind === 'expand' ? 'expansion' : 'comparison',
      id = await boundarySave(k);
    boundaryStatus('boundary_' + kind + '_status', UI.join([UI.msg("boundary.controls.save_cfe6f5", {}), id]));
  } catch (e) {
    boundaryStatus('boundary_' + kind + '_status', UI.errorText(e), true);
  }
};
$('boundary_expand_cancel').onclick = () => api('/api/cancel-expansion', {
  job_id: boundaryExpansionJob
}).catch(e => boundaryStatus('boundary_expand_status', UI.errorText(e), true));
$('boundary_compare_cancel').onclick = () => api('/api/cancel-scope-plan-comparison', {
  job_id: boundaryComparisonJob
}).catch(e => boundaryStatus('boundary_compare_status', UI.errorText(e), true));
for (const id of ['boundary_curve_range', 'boundary_curve_plan', 'boundary_curve_observation']) $(id).onchange = boundaryRenderCurves;
document.addEventListener('change', event => {
  const d = event.target.dataset;
  if (d.boundaryExternal) {
    event.target.checked ? boundaryExternalSeeds.add(d.boundaryExternal) : boundaryExternalSeeds.delete(d.boundaryExternal);
  }
  if (d.boundaryCase) {
    event.target.checked ? boundaryChosenCases.add(d.boundaryCase) : boundaryChosenCases.delete(d.boundaryCase);
    boundaryComparisonSignature = null;
    $('boundary_compare_run').disabled = true;
  }
});
document.addEventListener('click', event => {
  if (event.target.dataset.boundaryAnalyze) boundaryAnalyze(event.target.dataset.boundaryAnalyze);
});
for (const id of ['boundary_budgets', 'boundary_hops', 'boundary_direction', 'boundary_category', 'boundary_seeds', 'boundary_scan', 'boundary_max_edges', 'boundary_max_bytes', 'boundary_max_disk', 'boundary_original', 'boundary_max_tasks']) $(id).addEventListener('input', boundaryInvalidate);
document.addEventListener('lab-case', () => {
  boundaryReport = null;
  boundarySource = null;
  boundaryBaseId = null;
  boundaryExternalSeeds.clear();
  boundaryInvalidate();
  boundaryRefreshCases();
});
document.addEventListener('lab-replay-source', () => {
  boundaryInvalidate();
  boundaryFixedSource = null;
  UI.text($('boundary_fixed'), UI.msg("boundary.controls.fixed_plan_completecomparisonkeep_4c916a", {}));
});
document.addEventListener('lab-saved', boundaryRefreshCases);
document.addEventListener('lab-artifact-open', event => {
  const saved = event.detail;
  if (saved.kind === 'scope_expansion') {
    boundaryExpansion = saved.result;
    boundaryExpansionArtifact = saved.artifact_id;
    boundaryExpansionJob = null;
    boundaryRenderLevels(saved.result);
    $('boundary_expand_save').disabled = false;
    boundaryStatus('boundary_expand_status', UI.join([UI.msg("boundary.controls.save_scope_sequence_602207", {}), saved.artifact_id]));
    analysisTab('boundary');
  }
  if (saved.kind === 'scope_plan_comparison') {
    boundaryRenderComparison(saved.result, saved.artifact_id);
    analysisTab('boundary');
  }
});
boundaryRefreshCases();

for(const event of ['ui-language','ui-theme','ui-fonts'])document.addEventListener(event,()=>{if(boundaryComparison)boundaryRenderCurves();});
