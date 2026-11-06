"use strict";

/* Analysis display state and immutable sources are separate from the experiment draft. */
let analysisCurrent = null,
  analysisActiveView = 'ranking',
  analysisFocus = null,
  analysisRestoring = false,
  analysisOpening = false,
  analysisOpenSequence = 0,
  analysisNodeSequence = 0;
const analysisMembers = new Set(),
  analysisScenes = new Map();
function analysisStatus(message, error = false) {
  UI.text($('analysis_status'), message);
  $('analysis_status').classList.toggle('error', error);
}
window.analysisStatus = analysisStatus;
function analysisSet(ids) {
  const allowed = new Set((overview?.scope_nodes || []).map(n => String(n.bodyId)));
  const exact = [...new Set(ids.map(String))],
    missing = exact.filter(id => !allowed.has(id) && !window.spatialKnownIds?.has(id));
  if (exact.length > 200000) throw UI.error("analysis.analysisSet.selection_200000nodebudget_fbb479", {});
  if (missing.length) throw UI.errorValue(UI.join([UI.msg("analysis.analysisSet.members_select_63a053", {}), missing.join(', ')]));
  analysisMembers.clear();
  exact.forEach(id => analysisMembers.add(id));
  analysisPublish();
}
function analysisPublish() {
  const scoped = new Set((overview?.scope_nodes || []).map(n => String(n.bodyId))),
    local = [...analysisMembers].filter(id => scoped.has(id));
  differenceSelected = new Set(local);
  replaySelected = new Set(local);
  const restoring = analysisRestoring;
  analysisRestoring = true;
  try {
    renderDifferenceSelection();
  } finally {
    analysisRestoring = restoring;
  }
  window.replayTopology?.setSelection(local, analysisFocus);
  window.pathwayTopology?.setSelection([...analysisMembers], analysisFocus);
  renderAnalysisSelection();
  document.dispatchEvent(new CustomEvent('lab-analysis-selection', {
    detail: {
      ids: [...analysisMembers],
      focus: analysisFocus
    }
  }));
}
function analysisFocusNode(id) {
  analysisNodeSequence++;
  analysisFocus = id == null ? null : String(id);
  renderAnalysisSelection();
  window.replayTopology?.setSelection([...analysisMembers], analysisFocus);
  window.pathwayTopology?.setSelection([...analysisMembers], analysisFocus);
  document.dispatchEvent(new CustomEvent('lab-analysis-focus', {
    detail: {
      id: analysisFocus
    }
  }));
  const inScope = (overview?.scope_nodes || []).some(n => String(n.bodyId) === analysisFocus);
  if ($('analysis_node_details')) $('analysis_node_details').hidden = analysisActiveView !== 'connections' || !inScope;
  if (analysisFocus && analysisActiveView === 'connections' && inScope) analysisReadNode(analysisFocus);
}
window.analysisSelection = {
  ids: () => [...analysisMembers],
  set: analysisSet,
  add: ids => analysisSet([...analysisMembers, ...ids]),
  remove: id => analysisSet([...analysisMembers].filter(n => n !== String(id))),
  clear: () => analysisSet([]),
  focus: analysisFocusNode
};
function renderAnalysisSelection() {
  const label = id => {
    const n = overview?.scope_nodes.find(n => String(n.bodyId) === id);
    return UI.join([UI.join([n?.type || UI.msg("analysis.label.node_2410d8", {}), ' · ']), id]);
  };
  $('analysis_selection').innerHTML = `<span>${UI.htmlText("analysis.renderAnalysisSelection.selected_577202", {
    p0: analysisMembers.size,
    p1: analysisMembers.size > 50 ? UI.msg("analysis.renderAnalysisSelection.50_6a1fd9", {}) : ''
  })}</span>` + [...analysisMembers].slice(0, 50).map(id => `<span class="analysis-member" aria-current="${analysisFocus === id}"><button class="linkbtn" data-analysis-focus="${esc(id)}">${UI.html(label(id))}</button><button class="small" data-analysis-remove="${esc(id)}" ${UI.htmlAttribute("aria-label", "analysis.controls.remove_912bb1", {
    p0: id
  })}>×</button></span>`).join('');
  $('analysis_add_focus').disabled = !analysisFocus;
  if (analysisFocus) UI.text($('analysis_add_focus'), UI.join([UI.msg("analysis.renderAnalysisSelection.message_fa2c54", {}), label(analysisFocus)]));else UI.text($('analysis_add_focus'), UI.msg("analysis.renderAnalysisSelection.add_focused_node_eb2d76", {}));
}
function analysisTab(view) {
  analysisActiveView = view;
  const inScope = (overview?.scope_nodes || []).some(n => String(n.bodyId) === analysisFocus);
  if ($('analysis_node_details')) $('analysis_node_details').hidden = view !== 'connections' || !inScope;
  if (view === 'connections' && analysisFocus && inScope) analysisReadNode(analysisFocus);
  for (const key of ['ranking', 'connections', 'replay', 'reduction']) $('analysis_' + key).hidden = key !== view;
  for (const button of document.querySelectorAll('[data-analysis-tab]')) UI.attr(button, 'aria-selected', String(button.dataset.analysisTab === view));
  if (view === 'replay') window.replayTopology?.resize?.();
  if (view === 'connections') window.pathwayTopology?.resize?.();
}
function analysisSendDraft() {
  try {
    if (busy) throw UI.error("analysis.analysisSendDraft.stop_actions_f9d6a3", {});
    const ids = [...analysisMembers];
    if (!ids.length) throw UI.error("analysis.analysisSendDraft.select_nodes_first_24135a", {});
    if (window.interventionUI && Array.isArray(cfg().intervention_events)) {
      const scoped = new Set((overview?.scope_nodes || []).map(n => String(n.bodyId))),
        outside = ids.filter(id => !scoped.has(id));
      if (outside.length) throw UI.errorValue(UI.join([UI.msg("analysis.analysisSendDraft.members_scope_scope_63c19c", {}), outside.join(', ')]));
      if ($('analysis_draft_mode').value === 'replace') window.interventionUI.setPlan([]);
      window.interventionUI.addNodes(ids);
      analysisStatus(UI.msg("analysis.analysisSendDraft.select_node_result_source_not_run_6ab7fc", {}));
      return;
    }
    const allowed = new Set(candidateNodes('__all__').map(n => String(n.bodyId))),
      missing = ids.filter(id => !allowed.has(id));
    if (missing.length) throw UI.errorValue(UI.join([UI.msg("analysis.analysisSendDraft.members_intervention_50b255", {}), missing.join(', ')]));
    const previous = $('analysis_draft_mode').value === 'append' ? ['ids', 'none'].includes($('selection_mode').value) ? currentSelectionIds() : candidateNodes($('intervention_group').value).map(n => String(n.bodyId)) : [];
    $('intervention_group').value = '__all__';
    $('selection_mode').value = 'ids';
    $('selection_ids').value = [...new Set([...previous, ...ids])].join(', ');
    changed();
    analysisStatus(UI.msg("analysis.analysisSendDraft.intervention_node_not_run_ebab53", {
      p0: $('analysis_draft_mode').value === 'append' ? UI.msg("analysis.analysisSendDraft.message_d91017", {}) : UI.msg("analysis.analysisSendDraft.message_131b13", {}),
      p1: ids.length
    }));
  } catch (error) {
    analysisStatus(UI.errorText(error), true);
  }
}
function normalizeAnalysisGraph(graph) {
  if (!graph) return null;
  const fixed = new Set(graph.fixed_nodes || []);
  return {
    positions: Object.entries(graph.positions || {}).map(([id, p]) => ({
      body_id: String(id),
      x: p.x,
      y: p.y,
      fixed: p.fixed ?? fixed.has(String(id))
    })),
    transform: graph.transform,
    label_mode: graph.label_mode
  };
}
function restoredAnalysisGraph(graph) {
  return graph ? {
    ...graph,
    positions: Object.fromEntries(graph.positions.map(p => [p.body_id, {
      x: p.x,
      y: p.y
    }])),
    fixed_nodes: graph.positions.filter(p => p.fixed).map(p => p.body_id)
  } : null;
}
function analysisSnapshot() {
  const replay = captureReplayDisplay(),
    graphs = {};
  if (window.replayTopology && analysisCurrent?.references.replay) graphs.replay = normalizeAnalysisGraph(replayTopology.exportState());
  if (window.pathwayTopology && analysisCurrent?.references.pathways) graphs.pathways = normalizeAnalysisGraph(pathwayTopology.exportState());
  const state = {
    active_view: analysisActiveView,
    selected_nodes: [...analysisMembers],
    focus_node: analysisFocus,
    difference_display: differenceResult?.ready ? differenceDisplay() : {},
    replay_display: replayResult?.ready && replay ? {
      mode: replay.mode,
      state_step: replay.state_step,
      selected_node: replay.selected_node,
      selected_edge: replay.selected_edge,
      window: replay.window
    } : {},
    graphs
  };
  if (differenceResult?.ready) state.window = differenceWindow();
  if (typeof reductionSelected !== 'undefined' && reductionSelected && analysisCurrent?.references.reduction) state.reduction_display = {
    body_ids: reductionSelected.body_ids,
    condition_name: document.getElementById('reduction_condition').value
  };
  return state;
}
function analysisSourceKey(source) {
  const selection = Object.fromEntries(Object.entries(source).filter(([k]) => ['condition_name', 'body_ids', 'start', 'duration', 'task_id'].includes(k)));
  return source.artifact_id ? source.artifact_id + (Object.keys(selection).length ? JSON.stringify(selection) : '') : JSON.stringify(source);
}
function analysisCapture() {
  if (analysisCurrent && !analysisRestoring) {
    const scene = replayClone({
      ...analysisCurrent,
      state: analysisSnapshot()
    });
    scene.label = analysisCurrent.label;
    analysisScenes.set(analysisCurrent.key, scene);
    if (analysisCurrent.source.artifact_id) analysisScenes.set(analysisCurrent.source.artifact_id, scene);
  }
}
function analysisClearViews() {
  pauseReplay();
  replaySequence++;
  replayFrameSequence++;
  replayPickSequence++;
  differenceSequence++;
  differenceRowsSequence++;
  differenceNodeSequence++;
  differenceNeighborSequence++;
  differenceResult = null;
  differenceSource = null;
  replayResult = null;
  replaySource = null;
  pathwayResult = null;
  $('difference_view').hidden = true;
  $('replay_view').hidden = true;
  $('path_graph').replaceChildren();
  window.pathwayTopology?.destroy();
  window.pathwayTopology = null;
  pathwayTopology = null;
  window.replayTopology?.destroy();
  window.replayTopology = null;
  replayTopology = null;
  replayTopologyId = null;
  analysisFocus = null;
  analysisSet([]);
}
function analysisContext() {
  $('difference_area').hidden = !analysisCurrent;
  $('analysis_save').disabled = !analysisCurrent || analysisOpening;
  const sourceKind = savedArtifactCatalog.find(a => a.id === analysisCurrent?.source.artifact_id)?.kind;
  $('analysis_source_controls').hidden = ['scope_differences', 'circuit_replay'].includes(sourceKind);
  if (!analysisCurrent) {
    if ($('analysis_source_details')) UI.text($('analysis_source_details'), '');
    UI.text($('analysis_context'), UI.msg("analysis.analysisContext.select_a_saved_result_b82304", {}));
    return;
  }
  const c = analysisCurrent.experiment,
    source = analysisCurrent.source;
  UI.text($('analysis_context'), UI.msg('analysis.condition', {
    name: source.condition_name || UI.msg("analysis.analysisContext.fixed_plan_3b7d6e"),
    steps: c?.steps ?? '—'
  }));
  const info = $('analysis_source_details');
  if (info) UI.text(info, JSON.stringify({
    source,
    experiment: c
  }, null, 2));
}
window.confirmAnalysisScope = caseId => {
  if (caseId && overview && caseId !== overview.manifest.case_id && (dirty || analysisMembers.size)) return confirm(UI.msg("analysis.controls.scope_selection_saveintervention_continue_56911b", {}));
  return true;
};
async function analysisPersistHandles() {
  if (!analysisCurrent) return;
  const current = analysisCurrent, epoch = analysisOpenSequence;
  const saved = new Map();
  async function persist(handle, role) {
    if (handle.artifact_id) return handle;
    const key = JSON.stringify(handle);
    if (saved.has(key)) return {
      artifact_id: saved.get(key)
    };
    const paths = {
      replay: '/api/save-replay',
      difference: '/api/save-differences',
      pathways: '/api/save-pathways',
      run: '/api/save',
      comparison: '/api/save-comparison',
      joint: '/api/save-joint-search',
      timing: '/api/save-timing',
      reduction: '/api/save-reduction'
    };
    const path = paths[handle.kind];
    if (!path) throw UI.error("analysis.persist.save_21a9fe", {});
    const payload = {
      ...handle
    };
    delete payload.kind;
    if (role === 'replay' || handle.kind === 'replay') payload.display = analysisSnapshot().replay_display;
    if (role === 'differences' || handle.kind === 'difference') payload.display = differenceDisplay();
    const result = await api(path, payload),
      id = result.folder.split(/[\\/]/).pop();
    saved.set(key, id);
    return {
      artifact_id: id
    };
  }
  const selection = Object.fromEntries(Object.entries(current.source).filter(([k]) => ['condition_name', 'body_ids', 'start', 'duration', 'task_id'].includes(k)));
  const source = {
    kind: 'artifact',
    ...(await persist(current.source)),
    ...selection
  };
  const references = {};
  for (const [role, handle] of Object.entries(current.references)) references[role] = await persist(handle, role);
  if (current !== analysisCurrent || epoch !== analysisOpenSequence) return;
  current.source = source;
  current.references = references;
}
// Invalidate only result-dependent state. Drafts, shared selection, camera and
// cached scenes survive; a restored scene will explicitly rebind its references.
function analysisInvalidateSources(clearChoices = true) {
  ++analysisOpenSequence;
  document.dispatchEvent(new Event('lab-analysis-source-changing'));
  analysisClearExceptOpened('source');
  analysisCurrent = null;
  differenceSource = null;
  replaySource = null;
  differenceJob = null;
  replayJob = null;
  replayArtifact = null;
  analysisRestoring = false;
  if (clearChoices) {
    replaySources = [];
    $('replay_source').replaceChildren(UI.option(UI.msg('replay.refreshReplaySources.select_an_existing_result_f83e28'), ''));
    $('replay_source').value = '';
  }
  for (const id of ['difference_source_info', 'replay_source_info', 'difference_counts', 'replay_counts']) UI.text($(id), '');
  differenceStatus('');
  replayStatus('');
  for (const id of ['difference_preview', 'replay_preview', 'difference_prepare', 'replay_prepare', 'difference_save', 'replay_save', 'difference_replay_prepare']) $(id).disabled = true;
  analysisContext();
}
function analysisBindCurrentSource(window = null) {
  if (!analysisCurrent?.experiment) return;
  replaySource = {
    source: replayClone(analysisCurrent.source),
    experiment: replayClone(analysisCurrent.experiment),
    label: analysisCurrent.label,
    window
  };
  invalidateReplayRequest();
  bindDifferenceSource(replaySource);
  refreshReplaySources(replaySource.source);
  let index = replaySources.findIndex(s => JSON.stringify(s.source) === JSON.stringify(replaySource.source));
  if (index < 0) {
    index = replaySources.push(replayCloneSource(replaySource)) - 1;
    $('replay_source').append(UI.option(replaySource.label, String(index)));
  }
  $('replay_source').value = String(index);
  UI.text($('replay_source_info'), replaySource.label);
  $('difference_preview').disabled = false;
  $('replay_preview').disabled = false;
}
window.beforeAnalysisOpen = async (id, options) => {
  if (busy || searchRunning) throw UI.error('analysis.saveAnalysisScene.wait_for_the_current_task_to_stop_2a5566');
  const meta = savedArtifactCatalog.find(a => a.id === id);
  if (!confirmAnalysisScope(options?.case_id ?? meta?.case_id)) return false;
  const epoch = ++analysisOpenSequence;
  analysisOpening = true;
  invalidateDifferenceRequest();
  invalidateReplayRequest();
  replayFrameSequence++;
  replayPickSequence++;
  for (const id of ['difference_preview', 'replay_preview', 'difference_save', 'replay_save', 'analysis_save']) $(id).disabled = true;
  analysisStatus(UI.msg("analysis.controls.opening_source_7b763e", {}));
  try {
    await analysisPersistHandles();
  } catch (error) {
    if (epoch === analysisOpenSequence) {
      analysisOpening = false;
      analysisBindCurrentSource();
      analysisContext();
    }
    throw error;
  }
  if (epoch !== analysisOpenSequence) return false;
  analysisCapture();
  analysisInvalidateSources();
  analysisOpening = true;
  replaySequence++;
  replayFrameSequence++;
  replayPickSequence++;
  differenceSequence++;
  differenceRowsSequence++;
  differenceNodeSequence++;
  differenceNeighborSequence++;
  pathSequence++;
  return true;
};
async function analysisLoadReference(id, role) {
  const epoch = analysisOpenSequence,
    saved = await api('/api/reopen', {
      id
    });
  if (epoch !== analysisOpenSequence) return null;
  if (role === 'differences') await openDifferences(saved.result, true);else if (role === 'replay') await openReplay(saved.result, true);else if (role === 'pathways') {
    applyPathwayRequest(saved.result);
    renderPathways(saved.result);
  } else if (role === 'reduction') renderReduction(saved.result, id);
  return saved;
}
async function analysisRestore(state, available) {
  const epoch = analysisOpenSequence;
  analysisRestoring = true;
  try {
    for (const role of ['reduction', 'differences', 'pathways', 'replay']) {
      if (epoch !== analysisOpenSequence) return;
      if (available[role]) await analysisLoadReference(available[role], role);
    }
    if (epoch !== analysisOpenSequence) return;
    analysisSet(state.selected_nodes || []);
    analysisFocusNode(state.focus_node || null);
    if (differenceResult?.ready) {
      const d = state.difference_display || {};
      $('difference_sort').value = d.sort || 'absolute';
      $('difference_body').value = d.body_id || '';
      $('difference_type').value = d.type_filter || '';
      $('difference_hide_endpoints').checked = d.hide_endpoints ?? true;
      if (state.window) setDifferenceWindows(differenceResult.config.experiment, state.window);
      await readDifferenceRows(d.offset || 0);
      if (d.selected_node) await selectDifferenceNode(d.selected_node);
      if (epoch !== analysisOpenSequence) return;
      analysisPublish();
    }
    if (replayResult?.ready) await restoreReplayDisplay({
      ...state.replay_display,
      topology: {
        ...restoredAnalysisGraph(state.graphs?.replay),
        selected_node: state.replay_display?.selected_node,
        selected_edge: state.replay_display?.selected_edge
      }
    });
    if (epoch !== analysisOpenSequence) return;
    if (state.graphs?.pathways) window.pathwayTopology?.importState(restoredAnalysisGraph(state.graphs.pathways));
    analysisFocusNode(state.focus_node || null);
    if (available.reduction && state.reduction_display && typeof reductionSelect === 'function') {
      reductionSelect(state.reduction_display.body_ids);
      document.getElementById('reduction_condition').value = state.reduction_display.condition_name;
    }
    analysisTab(state.active_view || 'ranking');
  } finally {
    if (epoch === analysisOpenSequence) analysisRestoring = false;
  }
}
window.afterAnalysisOpen = async (saved, options = {}) => {
  const epoch = analysisOpenSequence;
  analysisOpening = false;
  if (saved.kind === 'plan_reduction') {
    analysisContext();
    analysisTab('reduction');
    $('analysis_workspace').scrollIntoView({block: 'start'});
    return;
  }
  // Reports describe many plans/protocols. Their existing renderer/selection
  // flow owns navigation until the user produces or selects a fixed experiment.
  if (['operation_search', 'search', 'joint_search', 'timing_exploration', 'response_exploration', 'scope_comparison', 'scope_expansion', 'scope_plan_comparison'].includes(saved.kind) || saved.result?.kind === 'forward') {
    analysisContext();
    return;
  }
  if (['scope_expansion', 'scope_plan_comparison'].includes(saved.kind)) {
    analysisTab('boundary');
    return;
  }
  if (saved.kind === 'analysis_session') {
    const read = saved.session,
      doc = read.document;
    analysisClearViews();
    analysisCurrent = {
      key: analysisSourceKey({
        artifact_id: doc.source.artifact_id,
        ...doc.source.selection
      }),
      source: {
        kind: 'artifact',
        artifact_id: doc.source.artifact_id,
        ...doc.source.selection
      },
      label: doc.name,
      references: Object.fromEntries(Object.entries(doc.references).filter(([k]) => read.available[k]).map(([k, id]) => [k, {
        artifact_id: id
      }])),
      experiment: doc.source_definition.config.experiment
    };
    $('analysis_name').value = doc.name;
    await analysisRestore(doc.state, read.available);
    if (epoch !== analysisOpenSequence || analysisCurrent?.source.artifact_id !== doc.source.artifact_id) return;
    analysisBindCurrentSource(doc.state.window || null);
    if(doc.state.experiment_draft){
      const different=JSON.stringify(cfg())!==JSON.stringify(doc.state.experiment_draft);
      if(!different||!window.workflowDraftEdited||confirm(UI.t('use.restoreDraft'))){
        apply(doc.state.experiment_draft);changed();window.workflowDraftEdited=false;
      }
    }
    analysisContext();
    analysisStatus(read.status === 'complete' ? UI.msg("analysis.controls.analysis_session_restored_d23d36", {}) : UI.join([UI.msg("analysis.controls.message_18c4c8", {}), read.missing.map(m => m.role + ' ' + m.artifact_id).join(', ')]), read.status !== 'complete');
    return;
  }
  const key = saved.artifact_id,
    cache = analysisScenes.get(key),
    c = saved.result?.config?.experiment || saved.config?.experiment || saved.result?.experiment;
  if (!c && !['comparison', 'plan_reduction'].includes(saved.kind)) {
    analysisContext();
    return;
  }
  // A saved analysis can associate another record only when its exact protocol agrees.
  const related = analysisCurrent && c && JSON.stringify(c) === JSON.stringify(analysisCurrent.experiment);
  const oldReferences = related ? analysisCurrent.references : {};
  const relatedState = related ? analysisScenes.get(analysisCurrent.key)?.state : null;
  if (!related) analysisClearExceptOpened(saved.kind);
  const role = {
    scope_differences: 'differences',
    circuit_replay: 'replay',
    pathways: 'pathways'
  }[saved.kind];
  analysisCurrent = {
    key,
    source: {
      kind: 'artifact',
      artifact_id: key
    },
    label: UI.join([savedKindLabels[saved.kind] || saved.kind, ' · ', key]),
    references: {
      ...oldReferences,
      ...(role ? {
        [role]: {
          artifact_id: key
        }
      } : {})
    },
    experiment: c
  };
  analysisOpening = true;
  if (saved.kind === 'plan_reduction') reductionBindOpened();else if (['run', 'comparison'].includes(saved.kind)) await enterReplay();
  if (epoch !== analysisOpenSequence) return;
  analysisOpening = false;
  // The source picker creates an in-memory handle. An opened saved result must
  // retain its artifact identity and the picker's exact condition selection.
  if (['run', 'comparison', 'joint_search', 'timing_exploration'].includes(saved.kind) && analysisCurrent) {
    const selection = Object.fromEntries(Object.entries(analysisCurrent.source || {}).filter(([name]) => ['condition_name', 'body_ids', 'start', 'duration', 'task_id'].includes(name)));
    analysisCurrent.source = {
      kind: 'artifact',
      artifact_id: key,
      ...selection
    };
    analysisCurrent.key = analysisSourceKey(analysisCurrent.source);
  }
  if (cache) {
    analysisCurrent = {
      ...cache
    };
    const state = saved.kind === 'comparison' ? {...cache.state, active_view: 'ranking'} : cache.state;
    await analysisRestore(state, Object.fromEntries(Object.entries(cache.references).map(([k, v]) => [k, v.artifact_id])));
    if (epoch !== analysisOpenSequence) return;
  } else {
    if (saved.kind === 'scope_differences') {
      analysisSet(saved.result.display?.selected_nodes || []);
      analysisFocusNode(saved.result.display?.selected_node || null);
      analysisTab('ranking');
    } else if (saved.kind === 'circuit_replay') {
      analysisSet(saved.result.display?.selected_nodes || []);
      analysisFocusNode(saved.result.display?.selected_node || null);
      analysisTab('replay');
    } else if (saved.kind === 'pathways') analysisTab('connections');else if (saved.kind === 'plan_reduction') analysisTab('reduction');
  }
  if (relatedState && !cache) {
    analysisSet(relatedState.selected_nodes || []);
    analysisFocusNode(relatedState.focus_node || null);
  }
  analysisBindCurrentSource(cache?.state?.window || differenceResult?.window || null);
  analysisContext();
  analysisStatus(UI.msg("analysis.controls.source_opened_intervention_draft_retained_677021", {}));
  $('analysis_workspace').scrollIntoView({
    block: 'start'
  });
};
function analysisClearExceptOpened(kind) {
  pauseReplay();
  pathSequence++;
  replaySequence++;
  differenceSequence++;
  analysisNodeSequence++;
  invalidateDifferenceRequest();
  invalidateReplayRequest();
  differenceReplayPreviewKey = null;
  $('difference_replay_prepare').disabled = true;
  $('difference_save').disabled = true;
  $('replay_save').disabled = true;
  if (kind !== 'scope_differences') {
    differenceRowsSequence++;
    differenceNodeSequence++;
    differenceNeighborSequence++;
    differenceResult = null;
    $('difference_view').hidden = true;
  }
  if (kind !== 'circuit_replay') {
    replayFrameSequence++;
    replayPickSequence++;
    replayResult = null;
    $('replay_view').hidden = true;
  }
  if (kind !== 'pathways') {
    pathwayResult = null;
    if (window.pathwayTopology) {
      pathwayTopology.destroy();
      pathwayTopology = null;
      window.pathwayTopology = null;
    }
    $('path_graph').replaceChildren();
  }
}
async function saveAnalysisScene() {
  const current = analysisCurrent, epoch = analysisOpenSequence;
  try {
    if (busy || searchRunning) throw UI.error("analysis.saveAnalysisScene.wait_for_the_current_task_to_stop_2a5566", {});
    if (!analysisCurrent?.source) throw UI.error("analysis.saveAnalysisScene.open_a_source_result_first_692119", {});
    const name = $('analysis_name').value.trim();
    if (!name) throw UI.error("analysis.saveAnalysisScene.enter_a_session_name_20eb1c", {});
    $('analysis_save').disabled = true;
    analysisStatus(UI.msg("analysis.saveAnalysisScene.saving_source_references_and_session_e64cbe", {}));
    const state=analysisSnapshot();
    if($('scene_include_draft')?.checked){validateCondition(cfg());state.experiment_draft=cfg();}
    const result = await api('/api/save-analysis-session', {
      name,
      source: analysisCurrent.source,
      references: analysisCurrent.references,
      state
    });
    if (current !== analysisCurrent || epoch !== analysisOpenSequence) return {artifact_id: result.artifact_id};
    analysisCurrent.source = {
      kind: 'artifact',
      artifact_id: result.session.document.source.artifact_id,
      ...result.session.document.source.selection
    };
    analysisCurrent.references = Object.fromEntries(Object.entries(result.session.document.references).map(([k, id]) => [k, {
      artifact_id: id
    }]));
    analysisCapture();
    analysisStatus(UI.join([UI.msg("analysis.saveAnalysisScene.analysis_session_save_fc07ac", {}), result.artifact_id]));
    document.dispatchEvent(new Event('lab-saved'));
    return {artifact_id:result.artifact_id};
  } catch (error) {
    if (current === analysisCurrent && epoch === analysisOpenSequence) analysisStatus(UI.errorText(error), true);
    return {error};
  } finally {
    $('analysis_save').disabled = !analysisCurrent || analysisOpening;
  }
}
// Move existing controls, preserving IDs, event handlers and calculation interfaces.
const selectionLine = document.createElement('div');
selectionLine.className = 'analysis-selection-line';
$('analysis_workspace').insertBefore(selectionLine, $('analysis_selection'));
selectionLine.append($('analysis_selection'), $('analysis_clear').parentElement);
const saveDetails = document.createElement('details');
saveDetails.id = 'analysis_save_controls';
const saveSummary = document.createElement('summary');
UI.text(saveSummary, UI.msg("analysis.labels.save_analysis_session_f7835f", {}));
saveDetails.append(saveSummary, $('analysis_name').parentElement);
$('analysis_workspace').insertBefore(saveDetails, $('analysis_source_controls'));
const replayBody = document.createElement('div');
replayBody.className = 'analysis-replay-body';
const replayAside = document.createElement('div');
replayAside.className = 'analysis-replay-aside';
$('replay_graph').parentElement.insertBefore(replayBody, $('replay_graph'));
replayBody.append($('replay_graph'), replayAside);
replayAside.append($('replay_detail'), $('replay_node_chart'), $('replay_node_details'));
const replaySetup = document.createElement('details');
replaySetup.id = 'replay_setup';
const replaySetupSummary = document.createElement('summary');
UI.text(replaySetupSummary, UI.msg("analysis.labels.recording_and_preparation_83221c", {}));
replaySetup.append(replaySetupSummary);
for (const element of [...$('replay_area').children]) if (element.tagName !== 'SUMMARY' && element.id !== 'difference_area' && element.id !== 'replay_view' && !element.contains($('difference_area'))) replaySetup.append(element);
$('replay_area').insertBefore(replaySetup, $('replay_view'));
$('analysis_source_controls').append($('replay_source').parentElement, $('replay_source_info'));
$('analysis_ranking').append($('difference_area'));
$('analysis_replay').append($('replay_area'));
const openPaths = document.createElement('button');
openPaths.type = 'button';
UI.text(openPaths, UI.msg('page.labels.explore_paths_45f762'));
openPaths.onclick = () => $('pathway_panel').scrollIntoView({block: 'start'});
$('analysis_connections').append(openPaths);
UI.text($('path_selected'), UI.msg("analysis.labels.add_to_selection_f6e6d5", {}));
$('replay_source_info').hidden = true;
$('analysis_clear').onclick = () => analysisSelection.clear();
$('analysis_add_focus').onclick = () => {
  try {
    analysisSelection.add([analysisFocus]);
  } catch (e) {
    analysisStatus(UI.errorText(e), true);
  }
};
$('analysis_to_draft').onclick = analysisSendDraft;
$('analysis_save').onclick = saveAnalysisScene;
$('analysis_expand').onclick = () => {
  $('analysis_workspace').classList.toggle('expanded');
  UI.text($('analysis_expand'), $('analysis_workspace').classList.contains('expanded') ? UI.msg("analysis.controls.back_572cf4", {}) : UI.msg("analysis.controls.expand_00bd39", {}));
};
for (const b of document.querySelectorAll('[data-analysis-tab]')) b.onclick = () => analysisTab(b.dataset.analysisTab);
UI.text($('replay_add_selection'), UI.msg("analysis.labels.use_as_intervention_draft_165e49", {}));
$('replay_add_selection').onclick = analysisSendDraft;
UI.text($('difference_intervention'), UI.msg("analysis.labels.use_as_intervention_draft_165e49", {}));
$('difference_intervention').onclick = analysisSendDraft;
$('difference_clear').onclick = () => analysisSelection.clear();
const oldSelectDifferenceNode = selectDifferenceNode;
selectDifferenceNode = async id => {
  analysisFocusNode(id);
  return oldSelectDifferenceNode(id);
};
const oldRenderDifferenceSelection = renderDifferenceSelection;
renderDifferenceSelection = () => {
  oldRenderDifferenceSelection();
  if (!analysisRestoring && JSON.stringify([...analysisMembers]) !== JSON.stringify([...differenceSelected])) {
    const scoped = new Set((overview?.scope_nodes || []).map(n => String(n.bodyId)));
    for (const id of [...analysisMembers]) if (scoped.has(id)) analysisMembers.delete(id);
    differenceSelected.forEach(id => analysisMembers.add(id));
    replaySelected = new Set(analysisMembers);
    renderAnalysisSelection();
    window.replayTopology?.setSelection([...analysisMembers], analysisFocus);
    window.pathwayTopology?.setSelection([...analysisMembers], analysisFocus);
    document.dispatchEvent(new CustomEvent('lab-analysis-selection', {
      detail: {
        ids: [...analysisMembers],
        focus: analysisFocus
      }
    }));
  }
};
const oldOpenDifferences = openDifferences;
openDifferences = async (result, saved) => {
  const epoch = analysisOpenSequence;
  await oldOpenDifferences(result, saved);
  if (epoch !== analysisOpenSequence || differenceResult?.difference_id !== result.difference_id) return;
  if (!analysisRestoring && !analysisOpening && analysisCurrent) {
    analysisCurrent.references.differences = {
      kind: 'difference',
      difference_id: result.difference_id
    };
    analysisCurrent.experiment = result.config.experiment;
    analysisTab('ranking');
  }
};
const oldOpenReplay = openReplay;
openReplay = async (result, saved) => {
  const epoch = analysisOpenSequence;
  await oldOpenReplay(result, saved);
  if (epoch !== analysisOpenSequence || replayResult?.replay_id !== result.replay_id) return;
  $('replay_setup').open = false;
  if (!analysisRestoring && !analysisOpening && analysisCurrent) {
    analysisCurrent.references.replay = {
      kind: 'replay',
      replay_id: result.replay_id
    };
    analysisCurrent.experiment = result.config.experiment;
    analysisTab('replay');
  }
};
const oldRenderPathways = renderPathways;
renderPathways = result => {
  oldRenderPathways(result);
  if (pathwayTopology) pathwayTopology.options.onEdge = id => analysisReadPathEdge(id);
  if (!analysisOpening && !analysisRestoring && analysisCurrent && result.scope?.kind === 'case' && result.pathways_id) {
    analysisCurrent.references.pathways = {
      kind: 'pathways',
      pathways_id: result.pathways_id
    };
    analysisTab('connections');
  }
};
document.addEventListener('lab-replay-source', async event => {
  if (analysisRestoring) return;
  const source = event.detail,
    key = analysisSourceKey(source.source),
    cached = analysisScenes.get(key),
    epoch = analysisOpening ? analysisOpenSequence : ++analysisOpenSequence;
  if (!analysisCurrent || JSON.stringify(analysisCurrent.experiment) !== JSON.stringify(source.experiment)) {
    analysisCapture();
    analysisClearExceptOpened('source');
    analysisCurrent = {
      key,
      source: source.source,
      label: source.label,
      experiment: source.experiment,
      references: {}
    };
  } else {
    analysisCurrent.source = source.source;
    analysisCurrent.key = key;
    analysisCurrent.label = source.label;
  }
  analysisContext();
  analysisTab('ranking');
  if (cached && !analysisOpening) {
    $('analysis_workspace').inert = true;
    try {
      analysisCurrent = replayCloneSource(cached);
      await analysisRestore(cached.state, Object.fromEntries(Object.entries(cached.references).filter(([, v]) => v.artifact_id).map(([k, v]) => [k, v.artifact_id])));
      if (epoch === analysisOpenSequence) analysisContext();
    } catch (e) {
      if (epoch === analysisOpenSequence) analysisStatus(UI.errorText(e), true);
    } finally {
      if (epoch === analysisOpenSequence) $('analysis_workspace').inert = false;
    }
  }
  if (epoch === analysisOpenSequence) {
    analysisBindCurrentSource(cached?.state?.window || null);
    analysisContext();
  }
});
document.addEventListener('click', event => {
  const d = event.target.dataset;
  if (d.analysisRemove) analysisSelection.remove(d.analysisRemove);
  if (d.analysisFocus) {
    analysisFocusNode(d.analysisFocus);
    if (!(overview?.scope_nodes || []).some(n => String(n.bodyId) === d.analysisFocus)) {
      analysisTab('spatial');
    } else if (replayResult?.nodes.some(n => n.body_id === d.analysisFocus)) {
      analysisTab('replay');
      selectReplayNode(d.analysisFocus, false, false);
    } else if (differenceResult?.ready) {
      analysisTab('ranking');
      selectDifferenceNode(d.analysisFocus);
    } else showNode(d.analysisFocus);
  }
});
document.addEventListener('lab-case', () => {
  analysisScenes.clear();
  analysisCurrent = null;
  analysisClearViews();
  analysisContext();
});
analysisTab('ranking');
renderAnalysisSelection();
$('difference_area').hidden = true;
const originalSelectReplaySource = selectReplaySource;
selectReplaySource = async index => {
  if (busy && !analysisOpening) {
    analysisStatus(UI.msg("analysis.controls.open_7aa466", {}));
    return;
  }
  if (!analysisOpening) {
    try {
      await analysisPersistHandles();
      analysisCapture();
      analysisInvalidateSources(false);
    } catch (e) {
      analysisStatus(UI.errorText(e), true);
      return;
    }
  }
  return originalSelectReplaySource(index);
};
let analysisSearchArtifact = null;
async function analyzeSearchPlan(plan) {
  try {
    if (busy) throw UI.error("analysis.analyzeSearchPlan.actions_a6ab18", {});
    analysisCapture();
    let artifact = analysisSearchArtifact;
    if (!artifact && searchJob) {
      const saved = await api('/api/save-search', {
        job_id: searchJob
      });
      artifact = saved.folder.split(/[\\/]/).pop();
      analysisSearchArtifact = artifact;
      document.dispatchEvent(new Event('lab-saved'));
    }
    if (!artifact) throw UI.error("analysis.analyzeSearchPlan.save_open_search_6763e4", {});
    const c = {
      ...searchResult.experiment,
      intervention_ids: plan.body_ids
    };
    const source = {
      label: UI.join([UI.msg("analysis.analyzeSearchPlan.searchplan_7aa29f", {}), plan.body_ids.join(', ')]),
      source: {
        kind: 'artifact',
        artifact_id: artifact,
        body_ids: plan.body_ids
      },
      experiment: c
    };
    analysisClearExceptOpened('source');
    replaySource = source;
    bindDifferenceSource(source);
    document.dispatchEvent(new CustomEvent('lab-replay-source', {
      detail: source
    }));
    analysisTab('ranking');
    $('analysis_workspace').scrollIntoView({
      block: 'start'
    });
  } catch (e) {
    analysisStatus(UI.errorText(e), true);
  }
}
const previousRenderSearch = renderSearch;
renderSearch = (...args) => {
  previousRenderSearch(...args);
  for (const [k, row] of [...$('search_rows').querySelectorAll('tr')].entries()) {
    const p = searchResult.displayPlans?.[k];
    if (!p) continue;
    const button = document.createElement('button');
    button.className = 'linkbtn';
    UI.text(button, UI.msg("analysis.controls.analysisplan_6efb1e", {}));
    button.onclick = () => analyzeSearchPlan(p);
    row.lastElementChild.append(button);
  }
};
document.addEventListener('lab-artifact-open', event => {
  analysisSearchArtifact = event.detail.kind === 'search' ? event.detail.artifact_id : null;
});
async function analysisReadNode(id) {
  const seq = ++analysisNodeSequence,
    epoch = analysisOpenSequence;
  $('analysis_node_details').hidden = false;
  try {
    const d = await api('/api/node?' + new URLSearchParams({
      id
    }));
    if (seq !== analysisNodeSequence || epoch !== analysisOpenSequence || id !== analysisFocus) return;
    $('analysis_node_content').innerHTML = `<strong>${UI.html(d.node.type || d.node.instance || UI.msg("analysis.analysisReadNode.node_2410d8", {}))} · ${UI.html(id)}</strong>` + ['incoming', 'outgoing'].map(direction => `<div>${UI.htmlText("analysis.controls.20_0f606c", {
      p0: direction === 'incoming' ? UI.msg("analysis.controls.upstream_a9ab29", {}) : UI.msg("analysis.controls.downstream_fde36e", {})
    })}</div>` + (d[direction] || []).map(e => `<span class="analysis-member"><button class="linkbtn" data-analysis-focus="${esc(e.node.bodyId)}">${UI.html(e.node.type || e.node.instance || '')} · ${UI.html(e.node.bodyId)}</button> ${UI.html(num(e.weight))} <button class="small" data-analysis-add="${esc(e.node.bodyId)}">${UI.htmlText("analysis.controls.add_to_selection_c3ce5d", {})}</button></span>`).join('')).join('');
  } catch (e) {
    if (seq === analysisNodeSequence) UI.text($('analysis_node_content'), UI.errorText(e));
  }
}
document.addEventListener('click', event => {
  if (event.target.dataset.analysisAdd) try {
    analysisSelection.add([event.target.dataset.analysisAdd]);
  } catch (e) {
    analysisStatus(UI.errorText(e), true);
  }
});
async function analysisReadPathEdge(id) {
  const edge = pathwayResult?.edges.find(e => e.body_pre + '->' + e.body_post === id);
  if (!edge) return;
  const seq = ++analysisNodeSequence,
    epoch = analysisOpenSequence,
    origin = pathwayResult;
  analysisFocus = null;
  pathStatus(id);
  try {
    const d = await api((origin.scope.kind === 'global' ? '/api/global/node?' : '/api/node?') + new URLSearchParams({
      id: edge.body_post
    }));
    if (seq !== analysisNodeSequence || epoch !== analysisOpenSequence || origin !== pathwayResult) return;
    const total = d.node.total_input,
      weight = total > 0 ? edge.contacts / total : null;
    const info = document.createElement('span');
    UI.text(info, UI.msg("analysis.analysisReadPathEdge.normalized_weight_803935", {
      p0: edge.body_pre,
      p1: edge.body_post,
      p2: UI.numeric(edge.contacts, {}),
      p3: UI.numeric(total, {}),
      p4: weight == null ? UI.msg("analysis.analysisReadPathEdge.definition_2ba10d", {}) : contextNumber(weight)
    }));
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'small';
    UI.text(button, UI.msg("analysis.analysisReadPathEdge.create_edge_event_f1e789", {}));
    button.dataset.operationEdge = JSON.stringify([edge.body_pre, edge.body_post]);
    pathStatus('');
    $('path_status').append(info, document.createTextNode(' '), button);
    $('path_status').scrollIntoView({block: 'nearest'});
    renderAnalysisSelection();
  } catch (e) {
    if (seq === analysisNodeSequence && epoch === analysisOpenSequence && origin === pathwayResult) pathStatus(UI.errorText(e), true);
  }
}
document.addEventListener('ui-language', () => {
  analysisContext();
  renderAnalysisSelection();
});
