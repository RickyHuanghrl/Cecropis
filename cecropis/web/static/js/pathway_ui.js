"use strict";

/* Directed structural exploration shares exact body IDs with experiments. */
let pathwayResult = null,
  pathSequence = 0,
  pathwayTopology = null;
function pathStatus(message, error = false) {
  UI.text($('path_status'), message);
  $('path_status').classList.toggle('error', error);
}
function endpointIds(role, label) {
  const groups = overview.group_body_ids?.[role] || {};
  return label === '__all__' ? [...new Set(Object.values(groups).flat())] : groups[label] || [];
}
function pathwayRequest() {
  const custom = $('path_endpoint_mode').value === 'ids',
    c = custom ? null : cfg();
  const a = custom ? $('path_a_label').value.trim() : $('path_observation_a').value,
    b = custom ? $('path_b_label').value.trim() : $('path_observation_b').value;
  if (!a || !b || a === b) throw UI.error("pathway.pathwayRequest.paths_targetname_abaf58", {});
  return {
    source_ids: custom ? parseBodyIds($('path_source_ids').value) : protocolSources(c),
    targets: {
      [a]: custom ? parseBodyIds($('path_a_ids').value) : protocolObservationIds(c, a),
      [b]: custom ? parseBodyIds($('path_b_ids').value) : protocolObservationIds(c, b)
    },
    max_hops: Number($('path_hops').value),
    min_contacts: Number($('path_contacts').value),
    max_nodes: Number($('path_nodes').value),
    max_edges: Number($('path_edges').value),
    detail_nodes: 60,
    detail_edges: 180
  };
}
function applyPathwayRequest(result) {
  const request = result.request,
    labels = Object.keys(request.targets);
  $('path_scope').value = result.scope.kind === 'global' ? 'global' : 'case';
  $('path_endpoint_mode').value = 'ids';
  $('path_endpoints').hidden = false;
  $('path_source_ids').value = request.source_ids.join(', ');
  for (const [key, label] of [['a', labels[0]], ['b', labels[1]]]) {
    $('path_' + key + '_label').value = label || '';
    $('path_' + key + '_ids').value = (request.targets[label] || []).join(', ');
  }
  for (const [id, key] of [['path_hops', 'max_hops'], ['path_contacts', 'min_contacts'], ['path_nodes', 'max_nodes'], ['path_edges', 'max_edges']]) $(id).value = request[key];
}
function pathClassification(node) {
  return node.classification === 'shared' ? UI.msg("pathway.pathClassification.message_4d6a4b", {}) : node.classification === 'endpoint' ? UI.msg("pathway.pathClassification.target_ad8c36", {}) : node.classification;
}
function pathFocus(id, event) {
  if (pathwayResult?.scope.kind === 'global') {
    showGlobalNode(id);
    return;
  }
  if (event.shiftKey && window.analysisSelection) {
    window.analysisSelection.ids().includes(id) ? window.analysisSelection.remove(id) : window.analysisSelection.add([id]);
  }
  if (window.analysisSelection) window.analysisSelection.focus(id);else showNode(id);
}
function renderPathRows() {
  if (!pathwayResult) return;
  const current = overview ? cfg() : null,
    prior = overview ? searchResult?.experiment : null;
  const labels = Object.keys(pathwayResult.request.targets),
    sameIds = (a, b) => JSON.stringify(a.slice().sort()) === JSON.stringify(b.slice().sort());
  const sameProtocol = prior && searchResult._matchesCurrent !== false && pathwayResult.scope.case_id === overview.manifest.case_id && ['steps', 'alpha', 'rho', 'gain', 'intervention_start', 'intervention_stop'].every(k => current[k] === prior[k]) && JSON.stringify(canonicalEvents(current)) === JSON.stringify(canonicalEvents(prior)) && JSON.stringify(canonicalObservations(current)) === JSON.stringify(canonicalObservations(prior)) && sameIds(pathwayResult.request.source_ids, protocolSources(current)) && labels.every(label => sameIds(pathwayResult.request.targets[label], protocolObservationIds(current, label)));
  const effectText = (effect, label) => {
    if (!effect) return UI.msg("pathway.effectText.message_e29a2e", {});
    const metrics = effect.output_metrics?.[label];
    if (metrics) return metrics.relative_sum_delta == null ? UI.join([UI.msg("pathway.effectText.message_b00d5f", {}), fmt(metrics.absolute_loss ?? -metrics.sum_delta)]) : searchLossText(metrics.relative_loss ?? -metrics.relative_sum_delta, 'relative');
    if (label === searchResult.target_output) return searchLossText(effect.target_loss, searchResult.options?.target_metric || 'relative');
    if (label === searchResult.protected_output) return searchLossText(effect.protected_loss, 'relative');
    return UI.msg("pathway.effectText.message_e29a2e", {});
  };
  const effects = new Map((sameProtocol ? searchResult.sensitivity : []).map(n => [n.bodyId, n]));
  $('path_nodes_rows').innerHTML = pathwayResult.nodes.map(node => {
    const effect = effects.get(node.bodyId);
    return `<tr><td><input type="checkbox" data-body="${esc(node.bodyId)}" ${UI.htmlAttribute("aria-label", "pathway.controls.selectpathsnode_b1741b", {
      p0: node.bodyId
    })}></td><td><button class="linkbtn" data-path-node="${esc(node.bodyId)}">${UI.html(node.bodyId)}</button></td><td>${UI.html(node.type)}</td><td>${UI.html(pathClassification(node))}</td><td>${node.source_hops ?? '—'}</td><td>${UI.htmlNumber(UI.numeric(node.incoming_contacts ?? 0, {}), false)}</td><td>${effectText(effect, labels[0])}</td><td>${effectText(effect, labels[1])}</td></tr>`;
  }).join('');
}
function renderPathGraph(result) {
  if (!pathwayTopology) {
    pathwayTopology = new TopologyView($('path_graph'), {
      label: UI.msg("pathway.renderPathGraph.paths_432a15", {}),
      onNode: pathFocus,
      onEdge: id => {
        const edge = pathwayResult.edges.find(e => String(e.edge_id || `${e.body_pre}->${e.body_post}`) === id);
        if (edge) pathStatus(UI.msg("pathway.onEdge.message_b5f302", {
          p0: edge.body_pre,
          p1: edge.body_post,
          p2: UI.numeric(edge.contacts, {}),
          p3: edge.weight != null ? UI.join([UI.msg("pathway.onEdge.message_710cd3", {}), contextNumber(edge.weight)]) : ''
        }));
      },
      onState: () => document.dispatchEvent(new Event('lab-analysis-display'))
    });
    window.pathwayTopology = pathwayTopology;
  }
  const graph = {
    nodes: result.nodes.map(n => ({
      ...n,
      body_id: n.bodyId,
      color: n.classification === 'shared' ? 'var(--highlight)' : n.classification === 'endpoint' ? 'var(--baseline)' : 'var(--muted)'
    })),
    edges: result.edges.map(e => ({
      ...e,
      edge_id: e.edge_id || `${e.body_pre}->${e.body_post}`,
      pre_id: e.body_pre,
      post_id: e.body_post,
      count: e.contacts
    }))
  };
  pathwayTopology.setGraph(graph);
  pathwayTopology.updateActivity(null, 'structure');
  pathwayTopology.setSelection(window.analysisSelection?.ids() || []);
}
function renderPathways(result) {
  pathwayResult = result;
  const labels = Object.keys(result.targets),
    a = labels[0],
    b = labels[1];
  UI.text($('path_shared'), UI.msg("pathway.renderPathways.select_shared_intermediate_nodes_d4c136", {
    p0: UI.numeric(result.shared_ids.length, {})
  }));
  for (const [id, label] of [['path_a', a], ['path_b', b]]) {
    UI.text($(id), UI.msg("pathway.renderPathways.select_7e06c0", {
      p0: label,
      p1: UI.numeric(result.exclusive_ids[label]?.length || 0, {})
    }));
    $(id).disabled = !result.exclusive_ids[label]?.length;
  }
  $('path_shared').disabled = !result.shared_ids.length;
  $('path_selected').disabled = !result.nodes.length;
  $('path_create').disabled = result.scope.kind !== 'global' || result.node_count > 200000 || !labels.every(label => result.targets[label].reachable) || !Object.values(result.targets).some(t => t.intermediate_ids.length);
  $('path_save').disabled = !result.pathways_id;
  const unreachable = labels.filter(label => !result.targets[label].reachable);
  pathStatus(UI.msg("pathway.renderPathways.paths_node_node_node_d79f14", {
    p0: result.scope.kind === 'global' ? UI.msg("pathway.renderPathways.connections_79db50", {}) : UI.msg("pathway.renderPathways.current_scope_35ba27", {}),
    p1: UI.numeric(result.node_count, {}),
    p2: UI.numeric(result.edge_count, {}),
    p3: result.truncated ? UI.msg("pathway.renderPathways.membership_3bc8a5", {}) : UI.msg("pathway.renderPathways.complete_bb88ba", {}),
    p4: UI.numeric(result.examined.edge_count, {}),
    p5: UI.numeric(result.budgets.max_edges, {}),
    p6: UI.numeric(result.visited.node_count, {}),
    p7: UI.numeric(result.budgets.max_nodes, {}),
    p8: unreachable.length ? UI.join([UI.join([UI.msg("pathway.renderPathways.message_41864c", {}), unreachable.join(' / ')]), UI.msg("pathway.renderPathways.paths_66815b", {})]) : '',
    p9: result.nodes.length,
    p10: result.edges.length
  }));
  renderPathGraph(result);
  renderPathRows();
  const groups = Array.isArray(result.groups) ? result.groups : result.groups?.nodes || [];
  $('path_groups').innerHTML = groups.map(g => `<tr><td>${UI.html(g.type)}</td><td>${UI.html(num(g.node_count))}</td><td>${UI.html(num(g.contacts ?? g.incoming_contacts ?? 0))}</td></tr>`).join('');
}
async function explorePathways() {
  if (busy) return;
  const sequence = ++pathSequence,
    generation = caseGeneration;
  try {
    const request = pathwayRequest(),
      scope = $('path_scope').value;
    $('path_explore').disabled = true;
    $('path_save').disabled = true;
    pathStatus(UI.msg("pathway.explorePathways.find_paths_47d4a5", {}));
    const result = await api(scope === 'global' ? '/api/global/pathways' : '/api/pathways', scope === 'global' ? request : {
      request,
      experiment: cfg()
    });
    if (sequence !== pathSequence || generation !== caseGeneration) return;
    if (JSON.stringify(request) !== JSON.stringify(pathwayRequest()) || scope !== $('path_scope').value) {
      pathStatus(UI.msg("pathway.explorePathways.searchcondition_3e3c7d", {}));
      return;
    }
    renderPathways(result);
  } catch (error) {
    if (sequence === pathSequence) pathStatus(UI.errorText(error), true);
  } finally {
    if (sequence === pathSequence) $('path_explore').disabled = false;
  }
}
function pathUseIds(ids) {
  if (busy) throw UI.error("pathway.pathUseIds.stop_b3daa7", {});
  if (!ids.length) throw UI.error("pathway.pathUseIds.selectpathsnode_6c32e0", {});
  if (pathwayResult?.scope.kind === 'global' && (!overview || pathwayResult.scope.case_id !== overview.manifest.case_id)) {
    appendSeeds(ids);
    pathStatus(UI.msg("pathway.pathUseIds.new_scope_seeds_node_010537", {
      p0: UI.numeric(ids.length, {})
    }));
    return;
  }
  if (window.analysisSelection) {
    window.analysisSelection.add(ids);
    pathStatus(UI.msg("pathway.pathUseIds.add_to_selection_node_1073ea", {
      p0: UI.numeric(ids.length, {})
    }));
    return;
  }
  const allowed = new Set(candidateNodes('__all__').map(n => n.bodyId)),
    missing = ids.filter(id => !allowed.has(id));
  if (missing.length) throw UI.errorValue(UI.join([UI.msg("pathway.pathUseIds.node_intervention_d9962a", {}), missing.join(', ')]));
  $('intervention_group').value = '__all__';
  $('selection_mode').value = 'ids';
  $('selection_ids').value = ids.join(', ');
  changed();
  pathStatus(UI.msg("pathway.pathUseIds.interventionnode_c2e68c", {
    p0: UI.numeric(ids.length, {})
  }));
}
async function createPathCase() {
  const result = pathwayResult;
  if (!result) return;
  try {
    const labels = Object.keys(result.request.targets),
      candidates = [...new Set(Object.values(result.targets).flatMap(t => t.intermediate_ids))];
    if (labels.length !== 2 || !candidates.length) throw UI.error("pathway.createPathCase.scope_node_3cd287", {});
    await switchAction(async () => {
      const config = {
        name: UI.t('editor.pathScopeName',{sources:result.request.source_ids.slice(0,2).join(','),targets:labels.join(' / ')}),
        scope: {
          body_ids: [...new Set([...result.node_ids, ...result.request.source_ids, ...Object.values(result.request.targets).flat()])],
          hops: 0,
          max_nodes: 200000,
          category: 'all'
        },
        groups: {
          input: {
            [UI.t('pathway.defaults.input')]: result.request.source_ids
          },
          internal: {
            [UI.t('pathway.defaults.candidates')]: candidates
          },
          output: result.request.targets
        }
      };
      activateOverview(await api('/api/create-case', config));
      await refreshSaved();
      $('path_scope').value = 'case';
      $('path_endpoint_mode').value = 'groups';
      $('path_endpoints').hidden = true;
      pathStatus(UI.msg("pathway.controls.pathsscope_save_noderoleloaded_f801ee", {}));
    });
    await explorePathways();
  } catch (error) {
    pathStatus(UI.errorText(error), true);
  }
}
function recordingPolicy() {
  const mode = $('record_mode').value,
    policy = {
      mode: mode === 'observed' ? 'selected' : mode,
      step_stride: Number($('record_stride').value),
      max_bytes: Number($('record_limit').value) * 1024 ** 2
    };
  if (mode === 'observed') {
    const c = cfg();
    policy.body_ids = [...new Set([...protocolSources(c), ...protocolObservations(c).flatMap(o => o.body_ids)])];
  } else if (mode === 'selected' && $('record_ids').value.trim()) policy.body_ids = parseBodyIds($('record_ids').value);
  const rawSteps = $('record_steps').value.trim();
  if (rawSteps) {
    const values = rawSteps.split(/[\s,，]+/);
    if (values.some(value => !/^\d+$/.test(value))) throw UI.error("pathway.recordingPolicy.recorded_state_steps_9465fa", {});
    policy.steps = values.map(Number);
    if (new Set(policy.steps).size !== policy.steps.length) throw UI.error("pathway.recordingPolicy.recorded_state_steps_8f3b94", {});
  }
  return policy;
}
function applyRecording(policy) {
  $('record_mode').value = policy?.mode || 'observed';
  $('record_ids').value = (policy?.body_ids || []).join(', ');
  $('record_stride').value = policy?.step_stride || 1;
  $('record_limit').value = (policy?.max_bytes || 256 * 1024 ** 2) / 1024 ** 2;
  $('record_steps').value = (policy?.steps || []).join(', ');
  $('record_ids').disabled = $('record_mode').value !== 'selected';
  UI.text($('record_status'), '');
}
$('record_preview').onclick = async () => {
  try {
    const generation = caseGeneration,
      requested = JSON.stringify({
        experiment: cfg(),
        recording: recordingPolicy()
      }),
      metadata = await api('/api/recording-preview', JSON.parse(requested));
    if (generation !== caseGeneration || requested !== JSON.stringify({
      experiment: cfg(),
      recording: recordingPolicy()
    })) return;
    UI.text($('record_status'), UI.msg("pathway.controls.node_mib_ee6a19", {
      p0: UI.numeric(metadata.node_count, {}),
      p1: UI.numeric(metadata.time_count, {}),
      p2: metadata.branch_count,
      p3: UI.numeric(metadata.bytes / 1024 ** 2, {
        minimumFractionDigits: 3,
        maximumFractionDigits: 3
      })
    }));
  } catch (error) {
    UI.text($('record_status'), UI.errorText(error));
  }
};
$('record_mode').addEventListener('change', () => {
  $('record_ids').disabled = $('record_mode').value !== 'selected';
});
$('path_explore').onclick = explorePathways;
$('path_create').onclick = createPathCase;
$('path_endpoint_mode').onchange = () => {
  $('path_endpoints').hidden = $('path_endpoint_mode').value !== 'ids';
  $('path_observation_controls').hidden = $('path_endpoint_mode').value === 'ids';
};
$('path_shared').onclick = () => {
  try {
    pathUseIds(pathwayResult.shared_ids);
  } catch (e) {
    pathStatus(UI.errorText(e), true);
  }
};
for (const [id, index] of [['path_a', 0], ['path_b', 1]]) $(id).onclick = () => {
  try {
    pathUseIds(pathwayResult.exclusive_ids[Object.keys(pathwayResult.targets)[index]]);
  } catch (e) {
    pathStatus(UI.errorText(e), true);
  }
};
$('path_selected').onclick = () => {
  try {
    pathUseIds(selectedRows('path_nodes_rows'));
  } catch (e) {
    pathStatus(UI.errorText(e), true);
  }
};
$('path_save').onclick = async () => {
  try {
    const id = pathwayResult?.pathways_id;
    if (!id) throw UI.error("pathway.controls.search_save_paths_27a637", {});
    const saved = await api('/api/save-pathways', {
      pathways_id: id
    });
    pathStatus(UI.join([UI.msg("pathway.controls.paths_save_f023be", {}), saved.folder]));
    document.dispatchEvent(new Event('lab-saved'));
  } catch (e) {
    pathStatus(UI.errorText(e), true);
  }
};
document.addEventListener('click', event => {
  const target = event.target.closest('[data-path-node]');
  if (target) pathFocus(target.dataset.pathNode, event);
  if (event.target.dataset.pathRole) {
    const role = event.target.dataset.pathRole,
      body = event.target.dataset.pathBody;
    $({
      source: 'path_source_ids',
      a: 'path_a_ids',
      b: 'path_b_ids'
    }[role]).value = body;
    $('path_scope').value = 'global';
    $('path_endpoint_mode').value = 'ids';
    $('path_endpoints').hidden = false;
    $('nodeDialog').close();
    $('pathway_panel').scrollIntoView({
      block: 'start'
    });
  }
  if (event.target.dataset.pathAssign) {
    try {
      const ids = selectedRows('global_nodes');
      if (!ids.length) throw UI.error("pathway.controls.selectsearch_node_d1d9fc", {});
      $({
        source: 'path_source_ids',
        a: 'path_a_ids',
        b: 'path_b_ids'
      }[event.target.dataset.pathAssign]).value = ids.join(', ');
      $('path_scope').value = 'global';
      $('path_endpoint_mode').value = 'ids';
      $('path_endpoints').hidden = false;
      $('pathway_panel').scrollIntoView({
        block: 'start'
      });
    } catch (e) {
      globalStatus(UI.errorText(e), true);
    }
  }
});
document.addEventListener('keydown', event => {
  const target = event.target.closest('[data-path-node]');
  if (target && ['Enter', ' '].includes(event.key)) {
    event.preventDefault();
    target.click();
  }
});
document.addEventListener('lab-case', () => {
  pathSequence++;
  pathwayResult = null;
  pathwayTopology?.destroy();
  pathwayTopology = null;
  window.pathwayTopology = null;
  applyRecording(null);
  for (const id of ['path_graph', 'path_nodes_rows', 'path_groups']) $(id).replaceChildren();
  for (const id of ['path_save', 'path_shared', 'path_a', 'path_b', 'path_selected', 'path_create']) $(id).disabled = true;
  $('path_explore').disabled = $('path_endpoint_mode').value !== 'ids' && cfg().outputs.length < 2;
  pathStatus($('path_endpoint_mode').value !== 'ids' && cfg().outputs.length < 2 ? UI.msg("pathway.controls.pathscomparison_select_observation_sets_1c9da9", {}) : '');
});
document.addEventListener('lab-result', () => {
  if (pathwayResult) renderPathRows();
});
document.addEventListener('lab-search', () => {
  if (pathwayResult) renderPathRows();
});
document.getElementById('experiment').addEventListener('input', () => {
  if (pathwayResult) renderPathRows();
  UI.text($('record_status'), '');
});
for (const id of ['path_scope', 'path_endpoint_mode', 'path_observation_a', 'path_observation_b', 'path_source_ids', 'path_a_ids', 'path_b_ids', 'path_a_label', 'path_b_label', 'path_hops', 'path_contacts', 'path_nodes', 'path_edges']) $(id).addEventListener('input', () => {
  pathSequence++;
  $('path_explore').disabled = $('path_endpoint_mode').value !== 'ids' && cfg().outputs.length < 2;
  if (pathwayResult) {
    $('path_save').disabled = true;
    pathStatus(UI.msg("pathway.controls.filter_node_search_c5cca6", {}));
  }
});
document.addEventListener('lab-protocol', () => {
  if (pathwayResult) {
    renderPathRows();
    $('path_save').disabled = true;
    pathStatus(UI.msg("pathway.controls.observation_sets_node_search_e7bdb2", {}));
  }
});
document.addEventListener('lab-analysis-selection', event => {
  pathwayTopology?.setSelection(event.detail.ids || [], event.detail.focus || null);
});
