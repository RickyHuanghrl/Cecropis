"use strict";

/* Global annotation browsing and explicit, saved computation scopes. */
let globalInfo = null,
  globalQuery = null,
  querySequence = 0,
  scopeSequence = 0,
  globalNodeSequence = 0;
let scopePreview = null,
  scopeSpec = null;
const categoryNames = {
  neuron: UI.msg("global.labels.neurons_traced_a0ae4c", {}),
  glia: UI.msg("global.labels.glia_d77f0b", {}),
  other: UI.msg("global.labels.other_d2909f", {}),
  unannotated: UI.msg("global.labels.unannotated_endpoints_0aeb6e", {})
};
function globalStatus(message, error = false) {
  UI.text($('global_status'), message);
  $('global_status').classList.toggle('error', error);
}
function parseBodyIds(text, allowEmpty = false) {
  const ids = text.trim().split(/[\s,，]+/).filter(Boolean);
  if (!ids.length && !allowEmpty || ids.some(id => !/^[1-9][0-9]*$/.test(id) || BigInt(id) > 9223372036854775807n) || new Set(ids).size !== ids.length) throw UI.error("global.parseBodyIds.body_ids_must_be_unique_positive_integers_20c8b8", {});
  return ids;
}
function globalFilters() {
  const filters = {},
    q = $('global_q').value.trim(),
    type = $('global_type').value.trim(),
    category = $('global_category').value;
  if (q) filters.q = q;
  if (type) filters.type = type;
  if (category !== 'all') filters.category = category;
  const field = $('global_field').value,
    value = $('global_field_value').value.trim();
  if (field && value) filters[field] = value;
  return filters;
}
function requestedScope() {
  const spec = {
    hops: Number($('scope_hops').value),
    direction: $('scope_direction').value,
    max_nodes: Number($('scope_limit').value),
    category: $('global_category').value
  };
  if (!Number.isInteger(spec.hops) || spec.hops < 0 || spec.hops > 3 || !Number.isInteger(spec.max_nodes) || spec.max_nodes < 1 || spec.max_nodes > 200000) throw UI.error("global.requestedScope.adjacency_layers_0_3_compute_node_limit_1_200000_e23111", {});
  if ($('scope_seed_mode').value === 'ids') spec.body_ids = parseBodyIds($('scope_ids').value);else spec.seed_filter = {
    q: '',
    ...globalFilters()
  };
  return spec;
}
function selectedRows(table) {
  return [...$(table).querySelectorAll('input[data-body]:checked')].map(input => input.dataset.body);
}
function tableSelectionControls(table) {
  const body = $(table);
  let controls = $(table + '_selection_controls');
  if (!controls) {
    controls = document.createElement('div');
    controls.id = table + '_selection_controls';
    controls.className = 'buttons';
    for (const [action, key] of [['all', 'table.selectPage'], ['none', 'table.clearPage']]) {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.tableSelection = action;
      UI.text(button, UI.msg(key));
      button.onclick = () => {
        for (const input of body.querySelectorAll('input[data-body]')) input.checked = action === 'all';
        body.dispatchEvent(new Event('change', {bubbles: true}));
      };
      controls.append(button);
    }
    const count = document.createElement('span');
    count.id = table + '_selection_count';
    count.setAttribute('role', 'status');
    controls.append(count);
    body.closest('.tablewrap').before(controls);
    body.addEventListener('change', () => tableSelectionControls(table));
  }
  const total = body.querySelectorAll('input[data-body]').length, count = selectedRows(table).length;
  controls.querySelector('[data-table-selection="all"]').disabled = !total || count === total;
  controls.querySelector('[data-table-selection="none"]').disabled = !count;
  UI.text($(table + '_selection_count'), UI.msg('table.pageSelection', {selected: UI.numeric(count), total: UI.numeric(total)}));
}
function globalRows(nodes, table) {
  const selected = new Set(selectedRows(table));
  $(table).innerHTML = nodes.map(node => `<tr><td><input type="checkbox" data-body="${esc(node.bodyId)}" ${UI.htmlAttribute("aria-label", "global.controls.select_f0f5c3", {
    p0: node.bodyId
  })}></td><td><button class="linkbtn" data-global-node="${esc(node.bodyId)}">${UI.html(node.bodyId)}</button></td><td data-user-text>${UI.html(node.type || node.instance)}</td><td>${UI.html(categoryNames[node.category] || node.category)}</td><td>${UI.htmlNumber(UI.numeric(node.total_input, {}), false)}</td><td>${UI.htmlNumber(UI.numeric(node.total_output, {}), false)}</td></tr>`).join('');
  for (const input of $(table).querySelectorAll('input[data-body]')) input.checked = selected.has(input.dataset.body);
  tableSelectionControls(table);
}
async function findGlobal(offset = 0) {
  const seq = ++querySequence,
    filters = globalFilters();
  if (globalQuery && JSON.stringify(globalQuery.filters) !== JSON.stringify(filters)) offset = 0;
  $('global_find').disabled = true;
  try {
    const result = await api('/api/global/find', {
      filters,
      limit: 100,
      offset
    });
    if (seq !== querySequence) return;
    globalQuery = {
      ...result,
      filters
    };
    globalRows(result.nodes, 'global_nodes');
    UI.text($('global_query_status'), UI.msg("global.findGlobal.matches_showing_3c19a9", {
      p0: UI.numeric(result.total, {}),
      p1: result.total ? offset + 1 : 0,
      p2: Math.min(offset + result.nodes.length, result.total)
    }));
    $('global_prev').disabled = offset === 0;
    $('global_next').disabled = offset + result.nodes.length >= result.total;
  } catch (error) {
    if (seq === querySequence) globalStatus(UI.errorText(error), true);
  } finally {
    if (seq === querySequence) $('global_find').disabled = false;
  }
}
async function previewScope() {
  const seq = ++scopeSequence;
  let spec;
  try {
    spec = requestedScope();
  } catch (error) {
    globalStatus(UI.errorText(error), true);
    return;
  }
  scopePreview = null;
  scopeSpec = null;
  $('scope_preview').disabled = true;
  $('create_case').disabled = true;
  UI.text($('scope_status'), UI.msg("global.previewScope.scope_82b724", {}));
  try {
    const result = await api('/api/global/scope', spec);
    if (seq !== scopeSequence) return;
    if (JSON.stringify(spec) !== JSON.stringify(requestedScope())) throw UI.error("global.previewScope.scopecondition_d7ecbc", {});
    scopePreview = result;
    scopeSpec = spec;
    globalRows(result.nodes || [], 'scope_nodes');
    const boundary = result.boundary || result;
    UI.text($('scope_status'), UI.msg("global.previewScope.node_connection_count_omitted_inputs_omitted_outputs_6ea370", {
      p0: UI.numeric(result.selected_node_count, {}),
      p1: UI.numeric(result.seed_ids?.length || 0, {}),
      p2: UI.numeric(result.nodes?.length || 0, {}),
      p3: result.truncated ? UI.msg("global.previewScope.node_limit_e9d9d0", {}) : UI.msg("global.previewScope.scope_313561", {}),
      p4: UI.numeric(boundary.internal_contacts || 0, {}),
      p5: UI.numeric(boundary.external_input_contacts || 0, {}),
      p6: UI.numeric(boundary.external_output_contacts || 0, {})
    }));
    globalStatus('');
  } catch (error) {
    if (seq === scopeSequence) {
      UI.text($('scope_status'), UI.msg("global.previewScope.scope_568b54", {}));
      globalStatus(UI.errorText(error), true);
    }
  } finally {
    if (seq === scopeSequence) {
      $('scope_preview').disabled = false;
      $('create_case').disabled = !scopePreview;
    }
  }
}
function assignRole(role, ids) {
  if (!ids.length) throw UI.error("global.assignRole.select_one_or_more_nodes_first_4658a7", {});
  const key = {
    input: 'input',
    a: 'a',
    b: 'b',
    candidate: 'candidate'
  }[role];
  if (!key) throw UI.error("global.assignRole.noderole_6447b9", {});
  const existing = parseBodyIds($('role_' + key + '_ids').value, true);
  $('role_' + key + '_ids').value = [...new Set([...existing, ...ids])].join(', ');
  if (key === 'candidate') {
    $('role_candidate_mode').value = 'ids';
    $('role_candidate_ids').disabled = false;
  }
  globalStatus(UI.msg("global.assignRole.node_84d995", {
    p0: ids.length
  }));
}
function appendSeeds(ids) {
  if (!ids.length) throw UI.error("global.appendSeeds.select_one_or_more_nodes_first_4658a7", {});
  const existing = parseBodyIds($('scope_ids').value, true);
  $('scope_ids').value = [...new Set([...existing, ...ids])].join(', ');
  $('scope_seed_mode').value = 'ids';
  scopePreview = null;
  scopeSpec = null;
  $('create_case').disabled = true;
  UI.text($('scope_status'), UI.msg("global.appendSeeds.message_2b7c7b", {}));
}
function canSwitchCase() {
  if (busy || typeof searchRunning !== 'undefined' && searchRunning) throw UI.error("global.canSwitchCase.stop_cancelsearch_scope_fe7ee2", {});
}
async function switchAction(operation) {
  canSwitchCase();
  busy = true;
  $('experiment').inert = true;
  if ($('analysis_workspace')) $('analysis_workspace').inert = true;
  for (const id of ['create_case', 'open_saved_case', 'open_saved_result']) $(id).disabled = true;
  try {
    await operation();
  } finally {
    busy = false;
    $('experiment').inert = false;
    if ($('analysis_workspace')) $('analysis_workspace').inert = false;
    $('create_case').disabled = !scopePreview;
    $('open_saved_case').disabled = false;
    $('open_saved_result').disabled = false;
    spatialSelection();
    document.dispatchEvent(new Event('lab-operation-idle'));
  }
}
async function createScopeCase() {
  try {
    if (!scopePreview || JSON.stringify(scopeSpec) !== JSON.stringify(requestedScope())) throw UI.error("global.createScopeCase.current_scope_d8a79e", {});
    const name = $('case_name').value.trim();
    if (!name) throw UI.error("global.createScopeCase.scope_name_6e4c2b", {});
    const label = role => {
      const value = $('role_' + role + '_name').value.trim() || (role === 'input' ? UI.t('default.inputName') : role === 'candidate' ? UI.t('default.candidateName') : role === 'a' ? UI.t('default.outputA') : role === 'b' ? UI.t('default.outputB') : '');
      if (!value || value === '__all__') throw UI.error("global.label.name_c0f17b", {});
      return value;
    };
    const a = label('a'),
      b = label('b');
    if (a === b) throw UI.error("global.createScopeCase.observation_sets_name_ace4a9", {});
    const mode = $('role_candidate_mode').value;
    const groups = {
      input: {
        [label('input')]: parseBodyIds($('role_input_ids').value)
      },
      internal: {
        [label('candidate')]: mode === 'remaining' ? '__remaining__' : mode === 'scope' ? '__scope__' : parseBodyIds($('role_candidate_ids').value)
      },
      output: {
        [a]: parseBodyIds($('role_a_ids').value),
        [b]: parseBodyIds($('role_b_ids').value)
      }
    };
    await switchAction(async () => {
      globalStatus(UI.msg("global.controls.savescope_f52e35", {}));
      activateOverview(await api('/api/create-case', {
        name,
        scope: scopeSpec,
        groups
      }));
      await refreshSaved();
      globalStatus(UI.msg("global.controls.scope_save_126a41", {}));
    });
  } catch (error) {
    globalStatus(UI.errorText(error), true);
  }
}
let savedArtifactCatalog = [],
  savedCaseCatalog = [];
const savedKindLabels = {
  response_exploration: UI.msg("global.labels.input_response_exploration_3cb1e0", {}),
  operation_search: UI.msg("global.labels.operation_search_469176", {}),
  run: UI.msg("global.labels.run_75b269", {}),
  condition: UI.msg("global.labels.condition_16bb1d", {}),
  comparison: UI.msg("global.labels.comparison_fb8791", {}),
  search: UI.msg("global.labels.search_44ce7a", {}),
  joint_search: UI.msg("global.labels.joint_search_1c82c5", {}),
  timing_exploration: UI.msg("global.labels.timing_exploration_692e7a", {}),
  plan_reduction: UI.msg("global.labels.removal_reduction_a403f8", {}),
  circuit_replay: UI.msg("global.labels.replay_27b68e", {}),
  scope_differences: UI.msg("global.labels.scope_differences_c876a0", {}),
  scope_comparison: UI.msg("global.labels.scope_comparison_8b47a9", {}),
  scope_expansion: UI.msg("global.labels.scope_sequence_a9decd", {}),
  scope_plan_comparison: UI.msg("global.labels.fixed_plans_across_scopes_4cd451", {}),
  forward: UI.msg("global.labels.forward_run_8bbc4d", {}),
  pathways: UI.msg("global.labels.paths_a35b41", {}),
  analysis_session: UI.msg("global.labels.analysis_session_73541d", {}),
  group_connections: UI.msg("global.labels.group_connections_43fdd4", {})
};
function filterSaved() {
  const previous = $('saved_results').value,
    kind = $('artifact_kind').value,
    scope = $('artifact_scope').value,
    q = $('artifact_query').value.trim().toLowerCase();
  $('saved_results').replaceChildren(UI.option(UI.msg("global.filterSaved.select_an_item_da590a", {}), ''));
  for (const item of savedArtifactCatalog.filter(a => (!kind || a.kind === kind) && (!scope || a.case_id === scope) && (!q || (a.label + ' ' + a.id).toLowerCase().includes(q)))) $('saved_results').append(UI.option(UI.join(["", savedKindLabels[item.kind] || item.kind, " · ", item.label, " · ", item.id, ""]), item.id));
  if ([...$('saved_results').options].some(o => o.value === previous)) $('saved_results').value = previous;
}
async function refreshSaved() {
  const results = await Promise.allSettled([api('/api/cases'), api('/api/artifacts')]);
  if (results[0].status === 'fulfilled') {
    savedCaseCatalog = results[0].value.cases;
    if (typeof updateScopeRegistry === 'function') updateScopeRegistry(savedCaseCatalog);
    const prev = $('saved_cases').value;
    $('saved_cases').replaceChildren(UI.option(UI.msg("global.refreshSaved.select_an_item_da590a", {}), ''));
    for (const c of savedCaseCatalog) $('saved_cases').append(UI.option(UI.plural('scope.option', c.node_count, {
      name: c.name,
      n: num(c.node_count)
    }), c.id));
    $('saved_cases').value = prev;
    const scope = $('artifact_scope').value;
    $('artifact_scope').replaceChildren(UI.option(UI.msg("global.refreshSaved.all_5c55a6", {}), ''));
    for (const c of savedCaseCatalog) $('artifact_scope').append(UI.option(c.name, c.case_id));
    $('artifact_scope').value = scope;
  } else globalStatus(UI.errorText(results[0].reason), true);
  if (results[1].status === 'fulfilled') {
    savedArtifactCatalog = results[1].value.artifacts;
    const kind = $('artifact_kind').value;
    $('artifact_kind').replaceChildren(UI.option(UI.msg("global.refreshSaved.all_5c55a6", {}), ''));
    for (const k of new Set(savedArtifactCatalog.map(a => a.kind))) $('artifact_kind').append(UI.option(savedKindLabels[k] || k, k));
    $('artifact_kind').value = kind;
    filterSaved();
  } else globalStatus(UI.errorText(results[1].reason), true);
}
for (const id of ['artifact_kind', 'artifact_scope', 'artifact_query']) $(id).addEventListener('input', filterSaved);
function renderSavedComparison(result, artifactId) {
  if (result.timing_evaluation) document.dispatchEvent(new CustomEvent('lab-timing-curves-open', {
    detail: {result, artifactId}
  }));else if (result.kind === 'joint_plan_evaluation') document.dispatchEvent(new CustomEvent('lab-joint-evaluation-open', {
    detail: {result, artifactId}
  }));else renderComparison(result, {origin: 'saved', artifactId});
}
async function reopenArtifact(requestedId = null, options = {}) {
  try {
    const id = typeof requestedId === 'string' ? requestedId : $('saved_results').value;
    if (!id) throw UI.error("global.reopenArtifact.select_a_saved_item_e39e3b", {});
    if (window.beforeAnalysisOpen && !(await window.beforeAnalysisOpen(id, options))) return;
    const epoch = analysisOpenSequence;
    await switchAction(async () => {
      const saved = await api('/api/reopen', {
        id
      });
      if (epoch !== analysisOpenSequence) return;
      if (saved.kind === 'group_connections') {
        groupParentStack = [];
        await renderGroupReport(saved.summary || saved.result);
        if (typeof analysisOpening !== 'undefined') analysisOpening = false;
        globalStatus(UI.msg("global.controls.opensave_group_connectionsanalysis_a14421", {}));
        return;
      }
      if (saved.kind === 'pathways' && !saved.case_id) {
        applyPathwayRequest(saved.result);
        renderPathways(saved.result);
        if (typeof analysisOpening !== 'undefined') analysisOpening = false;
        globalStatus(UI.msg("global.controls.opensave_paths_5788c1", {}));
        return;
      }
      const next = await api('/api/case');
      if (epoch !== analysisOpenSequence) return;
      // Opening another analysis of the same immutable case keeps the pathway
      // workspace available beside its curves and candidate evaluation.
      if (next.manifest.case_id !== overview?.manifest?.case_id) activateOverview(next);else {
        overview = next;
        localToken = next.token || localToken;
        const m = next.manifest;
        UI.text($('active_case'), UI.msg('page.activateOverview.scope_node_internal_edges_62b27b', {
          p0: m.case_name,
          p1: UI.numeric(m.node_count),
          p2: UI.numeric(m.scan?.internal_edges ?? m.internal_edges ?? 0)
        }));
        window.workspaceShell?.refreshContext();
      }
      const config = saved.config;
      if (['scope_differences', 'differences'].includes(saved.kind) && saved.result) await openDifferences(saved.result, true);
      if (['replay', 'circuit_replay'].includes(saved.kind) && saved.result) await openReplay(saved.result, true);
      if (epoch !== analysisOpenSequence) return;
      if (saved.kind === 'timing_exploration' && saved.result) document.dispatchEvent(new CustomEvent('lab-timing-open', {
        detail: saved
      }));
      if (saved.kind === 'joint_search' && saved.result) document.dispatchEvent(new CustomEvent('lab-joint-open', {
        detail: saved
      }));
      if (saved.kind === 'response_exploration') await openResponses(saved);
      if (saved.kind === 'operation_search' && saved.result) openOperationSearch(saved);
      if (saved.kind === 'plan_reduction' && saved.result) renderReduction(saved.result, saved.artifact_id);
      if (saved.kind === 'scope_comparison' && saved.result) {
        renderScopeComparison(saved.result, true);
      }
      if (saved.kind === 'pathways' && saved.result) {
        applyPathwayRequest(saved.result);
        renderPathways(saved.result);
      }
      if (saved.kind === 'search' && saved.result) {
        searchJob = null;
        renderSearch(saved.result, false, true);
        $('search_save').disabled = true;
        $('search_cancel').disabled = true;
      } else if (saved.kind === 'comparison' && saved.result) renderSavedComparison(saved.result, saved.artifact_id || id);else if (saved.result?.series) {
        activitySequence++;
        activityRows = [];
        spatial.setActivity([], $('geometry_mode').value);
        updateFocusActivity();
        latest = saved.result;
        renderResult(latest);
        $('save').disabled = true;
        $('geometry_time').disabled = true;
      }
      if (saved.result?.series) UI.text($('resultstate'), UI.msg('view.saved'));
      document.dispatchEvent(new CustomEvent('lab-artifact-open', {
        detail: saved
      }));
      if (window.afterAnalysisOpen) await window.afterAnalysisOpen(saved, options);
      if (epoch !== analysisOpenSequence) return;
      if (saved.kind === 'comparison') window.workspaceShell?.navigate('compare');
      globalStatus(UI.msg("global.controls.saved_result_and_scope_opened_6e9413", {}));
      status(UI.msg("global.controls.saved_item_opened_275e20", {}));
    });
  } catch (error) {
    globalStatus(UI.errorText(error), true);
    if (typeof analysisOpening !== 'undefined') analysisOpening = false;
    if (window.analysisStatus) window.analysisStatus(UI.errorText(error), true);
    throw error;
  }
}
async function showGlobalNode(id) {
  const seq = ++globalNodeSequence;
  try {
    const results = await Promise.allSettled([api('/api/global/node?' + new URLSearchParams({
      id
    })), api('/api/global/neighbors?' + new URLSearchParams({
      id,
      direction: 'incoming',
      limit: 20
    })), api('/api/global/neighbors?' + new URLSearchParams({
      id,
      direction: 'outgoing',
      limit: 20
    }))]);
    if (seq !== globalNodeSequence) return;
    for (const result of results) if (result.status !== 'fulfilled') throw result.reason;
    const node = results[0].value.node;
    UI.text($('nodetitle'), UI.join(["", node.type || node.instance || UI.msg("global.showGlobalNode.node_2410d8", {}), " · body ", id, ""]));
    const fields = {
      bodyId: 'body ID',
      name: UI.msg("global.showGlobalNode.name_d44e9b", {}),
      instance: 'instance',
      type: UI.msg("global.showGlobalNode.type_ba4001", {}),
      superclass: 'superclass',
      class: 'class',
      category: UI.msg("global.showGlobalNode.category_0d12cb", {}),
      status: UI.msg("global.showGlobalNode.status_6320b4", {}),
      statusLabel: UI.msg("global.showGlobalNode.status_3cf45f", {}),
      somaSide: UI.msg("global.showGlobalNode.message_0f783c", {}),
      total_input: UI.msg("global.showGlobalNode.input_contacts_a6abcc", {}),
      total_output: UI.msg("global.showGlobalNode.output_contacts_25997f", {}),
      incoming_edges: UI.msg("global.showGlobalNode.upstream_2149fe", {}),
      outgoing_edges: UI.msg("global.showGlobalNode.downstream_6e4f06", {})
    };
    $('nodedetail').innerHTML = '<div class="annotation">' + Object.entries(fields).map(([key, label]) => `<div><span>${UI.html(label)}</span><b>${UI.html(key === 'category' ? categoryNames[node[key]] || node[key] : node[key])}</b></div>`).join('') + '</div>' + `<div class="buttons"><button class="small" data-path-role="source" data-path-body="${esc(id)}">${UI.htmlText("global.showGlobalNode.use_as_path_source_777393", {})}</button><button class="small" data-path-role="a" data-path-body="${esc(id)}">${UI.htmlText("global.showGlobalNode.use_as_path_target_a_d9e3f0", {})}</button><button class="small" data-path-role="b" data-path-body="${esc(id)}">${UI.htmlText("global.showGlobalNode.use_as_path_target_b_7803ab", {})}</button><button class="small" data-global-seed="${esc(id)}">${UI.htmlText("global.showGlobalNode.add_as_seeds_8b644d", {})}</button><button class="small" data-global-role="input" data-global-body="${esc(id)}">${UI.htmlText("global.showGlobalNode.add_as_inputs_7a7d9c", {})}</button><button class="small" data-global-role="a" data-global-body="${esc(id)}">${UI.htmlText("global.showGlobalNode.add_to_output_a_b300f3", {})}</button><button class="small" data-global-role="b" data-global-body="${esc(id)}">${UI.htmlText("global.showGlobalNode.add_to_output_b_02f1a7", {})}</button></div>` + results.slice(1).map((result, index) => `<h3 style="margin-top:14px">${UI.htmlText("global.controls.20_5c5181", {
      p0: index === 0 ? UI.msg("global.controls.upstream_a9ab29", {}) : UI.msg("global.controls.downstream_fde36e", {}),
      p1: UI.numeric(result.value.edge_count, {})
    })}</h3><div class="tablewrap"><table><thead><tr><th>body ID</th><th>${UI.htmlText("global.controls.type_ba4001", {})}</th><th>${UI.htmlText("global.controls.connection_count_93e376", {})}</th></tr></thead><tbody>${result.value.nodes.map(edge => `<tr><td><button class="linkbtn" data-global-node="${esc(edge.node.bodyId)}">${UI.html(edge.node.bodyId)}</button></td><td>${UI.html(edge.node.type || edge.node.instance)}</td><td>${UI.html(num(edge.weight))}</td></tr>`).join('')}</tbody></table></div>`).join('');
    if (!$('nodeDialog').open) $('nodeDialog').showModal();
  } catch (error) {
    if (seq === globalNodeSequence) globalStatus(UI.errorText(error), true);
  }
}
async function initializeGlobal() {
  tableSelectionControls('global_nodes');
  tableSelectionControls('scope_nodes');
  $('create_case').disabled = true;
  $('global_prev').disabled = true;
  $('global_next').disabled = true;
  try {
    globalInfo = await api('/api/global/info');
    const m = globalInfo.manifest,
      c = m.category_counts || {};
    UI.text($('global_coverage'), UI.msg("global.initializeGlobal.annotated_traced_glia_other_unannotated_endpoints_total__8f4479", {
      p0: UI.numeric(m.annotated_record_count ?? 0, {}),
      p1: UI.numeric(c.neuron ?? 0, {}),
      p2: UI.numeric(c.glia ?? 0, {}),
      p3: UI.numeric(c.other ?? 0, {}),
      p4: UI.numeric(c.unannotated ?? 0, {}),
      p5: UI.numeric(m.node_count ?? 0, {})
    }));
    const none = document.createElement('option');
    none.value = '';
    UI.text(none, UI.msg("global.initializeGlobal.no_additional_filter_3be094", {}));
    none.dataset.i18n = "text.3be0945335ef";
    $('global_field').replaceChildren(none);
    for (const field of globalInfo.filter_fields.filter(field => !['q', 'type', 'category', 'bodyId'].includes(field))) {
      const option = document.createElement('option');
      option.value = field;
      UI.text(option, UI.field(field));
      $('global_field').append(option);
    }
  } catch (error) {
    UI.text($('global_coverage'), UI.errorText(error));
    $('global_find').disabled = true;
    $('scope_preview').disabled = true;
  }
  await refreshSaved();
}
$('global_find').onclick = () => findGlobal();
$('global_prev').onclick = () => findGlobal(Math.max(0, (globalQuery?.offset || 0) - 100));
$('global_next').onclick = () => findGlobal((globalQuery?.offset || 0) + 100);
$('scope_preview').onclick = previewScope;
$('create_case').onclick = createScopeCase;
$('query_add_seeds').onclick = () => {
  try {
    appendSeeds(selectedRows('global_nodes'));
  } catch (error) {
    globalStatus(UI.errorText(error), true);
  }
};
$('role_candidate_mode').onchange = () => {
  $('role_candidate_ids').disabled = $('role_candidate_mode').value !== 'ids';
};
$('refresh_saved').onclick = () => refreshSaved();
$('open_saved_case').onclick = async () => {
  try {
    const id = $('saved_cases').value;
    if (!id) throw UI.error("global.controls.select_a_calculation_scope_cf6421", {});
    if (window.confirmAnalysisScope && !window.confirmAnalysisScope(savedCaseCatalog.find(c => c.id === id)?.case_id)) return;
    await switchAction(async () => {
      activateOverview(await api('/api/open-case', {
        id
      }));
      globalStatus(UI.msg("global.controls.scope_opened_9721bf", {}));
    });
  } catch (error) {
    globalStatus(UI.errorText(error), true);
  }
};
$('open_saved_result').onclick = () => reopenArtifact().catch(() => {});
document.addEventListener('click', event => {
  const data = event.target.dataset;
  if (data.globalNode) showGlobalNode(data.globalNode);
  try {
    if (data.assign) assignRole(data.assign, selectedRows('scope_nodes'));
    if (data.globalSeed) appendSeeds([data.globalSeed]);
    if (data.globalRole) assignRole(data.globalRole, [data.globalBody]);
  } catch (error) {
    globalStatus(UI.errorText(error), true);
  }
});
for (const id of ['global_q', 'global_type', 'global_category', 'global_field', 'global_field_value', 'scope_seed_mode', 'scope_ids', 'scope_hops', 'scope_direction', 'scope_limit']) $(id).addEventListener('input', () => {
  scopeSequence++;
  scopePreview = null;
  scopeSpec = null;
  $('create_case').disabled = true;
  $('scope_preview').disabled = !globalInfo;
  UI.text($('scope_status'), UI.msg("global.controls.scopecondition_00ba18", {}));
});
for (const id of ['global_q', 'global_type', 'global_category', 'global_field', 'global_field_value']) $(id).addEventListener('input', () => {
  querySequence++;
  $('global_find').disabled = !globalInfo;
  $('global_prev').disabled = true;
  $('global_next').disabled = true;
  UI.text($('global_query_status'), UI.msg("global.controls.filter_search_b40c04", {}));
});
document.addEventListener('lab-saved', () => refreshSaved());
document.addEventListener('DOMContentLoaded', () => init().then(() => {
  initializeGlobal();
  if (typeof initializeWorkspace === 'function') initializeWorkspace();
  if (typeof initializeGroups === 'function') initializeGroups();
}));
document.addEventListener("ui-language", () => {
  filterSaved();
  const previous = $("saved_cases").value;
  $("saved_cases").replaceChildren(UI.option(UI.msg("global.controls.select_an_item_da590a", {}), ""));
  for (const c of savedCaseCatalog) $("saved_cases").append(UI.option(UI.plural("scope.option", c.node_count, {
    name: c.name,
    n: num(c.node_count)
  }), c.id));
  $("saved_cases").value = previous;
  for (const option of $("artifact_kind").options) UI.text(option, option.value ? savedKindLabels[option.value] || option.value : UI.msg("global.controls.all_5c55a6"));
});
