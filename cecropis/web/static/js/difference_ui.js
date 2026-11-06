"use strict";

/* Whole-scope statistics retain the immutable result; selection edits a new draft. */
let differenceSource = null,
  differenceResult = null,
  differencePreview = null,
  differencePreviewKey = null,
  differenceJob = null;
let differenceSequence = 0,
  differenceRowsSequence = 0,
  differenceNodeSequence = 0,
  differenceNeighborSequence = 0;
let differenceSelected = new Set(),
  differenceSelectedNode = null,
  differencePage = null,
  differenceNeighborPage = null;
let differenceReplayPreviewKey = null,
  differenceLocks = new Map(),
  differenceWindows = new Map();
const differenceLabels = {
  absolute: UI.msg("difference.labels.absolute_sum_difference_d268a6", {}),
  decrease: UI.msg("difference.labels.message_4df672", {}),
  increase: UI.msg("difference.labels.message_5ef095", {})
};
function differenceStatus(text, error = false) {
  UI.text($('difference_status'), text);
  $('difference_status').classList.toggle('error', error);
}
function differenceExperiment() {
  return differenceSource?.experiment || differenceResult?.config?.experiment;
}
function differenceLabel(node) {
  return UI.join([UI.join([node.annotation?.type || node.annotation?.instance || UI.msg("difference.differenceLabel.type_fb8761", {}), ' · ']), node.body_id]);
}
function differenceRoles(node) {
  return [node.input ? UI.msg("difference_ui.label.2087c777c0") : null, node.intervention ? UI.msg("difference.differenceRoles.intervention_54b347", {}) : null, ...(node.observation_names || []).map(name => UI.join([UI.msg("difference.controls.observation_ddf5ff", {}), name]))].filter(Boolean).join(' / ') || UI.msg("difference.differenceRoles.node_9fefe7", {});
}
function differenceMetricCells(row) {
  return `<td>${UI.html(contextNumber(row.baseline_sum))}</td><td>${UI.html(contextNumber(row.intervention_sum))}</td><td>${UI.html(contextNumber(row.sum_delta))}</td><td>${UI.html(contextNumber(row.absolute_sum_delta))}</td><td>${UI.html(contextNumber(row.mean_delta))}</td><td>${UI.html(row.baseline_near_zero ? UI.msg("difference.differenceMetricCells.baseline_definition_079637", {}) : replayPercent(row.relative_sum_delta))}</td>`;
}
function setDifferenceWindows(experiment, chosen = null) {
  if (!experiment) return;
  const steps = experiment.steps;
  differenceWindows = new Map([['all', {
    start: 0,
    stop: steps
  }]]);
  let html = `<option value="all" ${UI.displayAttribute(UI.msg('window.full', {steps: UI.numeric(steps)}))}>${UI.t('window.full', {steps: UI.numeric(steps)})}</option>`;
  for (const [o, k] of protocolObservations(experiment).map((o, k) => [o, k])) {
    const window = o.evaluation_window || {
      start: 0,
      stop: steps
    };
    differenceWindows.set('observation:' + k, {
      ...window
    });
    html += `<option value="observation:${k}">${esc(o.name)} · [${window.start}, ${window.stop})</option>`;
  }
  html += `<option value="custom" data-i18n="difference.setDifferenceWindows.custom_window_55a653">${UI.t("difference.setDifferenceWindows.custom_window_55a653")}</option>`;
  $('difference_window').innerHTML = html;
  const selected = chosen || {
      start: 0,
      stop: steps
    },
    key = [...differenceWindows].find(([, w]) => w.start === selected.start && w.stop === selected.stop)?.[0] || 'custom';
  $('difference_window').value = key;
  $('difference_start').value = selected.start;
  $('difference_stop').value = selected.stop;
  $('difference_start').max = steps - 1;
  $('difference_stop').max = steps;
  $('difference_custom_window').hidden = key !== 'custom';
}
function differenceWindow() {
  const c = differenceExperiment();
  if (!c) throw UI.error("difference.differenceWindow.select_an_existing_result_first_d13a87", {});
  const selected = $('difference_window').value,
    window = selected === 'custom' ? {
      start: Number($('difference_start').value),
      stop: Number($('difference_stop').value)
    } : differenceWindows.get(selected);
  if (!window || !Number.isInteger(window.start) || !Number.isInteger(window.stop) || window.start < 0 || window.start >= window.stop || window.stop > c.steps) throw UI.error("difference.differenceWindow.analysiswindow_satisfied_0_start_update_stop_e54ec9", {
    p0: c.steps
  });
  return {
    ...window
  };
}
function differenceRequest() {
  const max_bytes = Number($('difference_max_bytes').value) * 1024 ** 2;
  if (!Number.isSafeInteger(max_bytes) || max_bytes < 1) throw UI.error("difference.differenceRequest.message_36b793", {});
  return {
    window: differenceWindow(),
    max_bytes
  };
}
function differencePayload() {
  if (!differenceSource?.source) throw UI.error("difference.differencePayload.select_an_existing_result_first_d13a87", {});
  return {
    source: replayClone(differenceSource.source),
    request: differenceRequest()
  };
}
function invalidateDifferenceRequest() {
  differenceSequence++;
  differencePreview = null;
  differencePreviewKey = null;
  $('difference_prepare').disabled = true;
  if (differenceResult) differenceStatus(UI.msg("difference.invalidateDifferenceRequest.analysis_window_cf55ad", {}));
}
function bindDifferenceSource(source) {
  differenceSource = replayCloneSource(source);
  invalidateDifferenceRequest();
  setDifferenceWindows(differenceSource.experiment, differenceSource.window);
  UI.text($('difference_source_info'), UI.join([source.label || UI.msg("difference.bindDifferenceSource.fixed_plan_ae406b", {}), UI.msg("difference.bindDifferenceSource.message_e5d34a", {})]));
  $('difference_area').open = true;
  differenceStatus(differenceResult ? UI.msg("difference.bindDifferenceSource.complete_analysis_00cbc9", {}) : UI.msg("difference.bindDifferenceSource.check_difference_statistics_budget_fc02c7", {}));
}
function differenceCounts(result) {
  const c = result.counts || {},
    m = result.memory || {},
    s = result.simulations || {};
  UI.text($('difference_counts'), UI.msg("difference.differenceCounts.node_node_mib_mib_complete_start_d1cb1b", {
    p0: UI.numeric(c.computation_node_count ?? c.node_count ?? 0, {}),
    p1: UI.numeric(c.statistic_node_count ?? 0, {}),
    p2: UI.numeric((m.estimated_peak_bytes || 0) / 1024 ** 2, {
      notation: "scientific",
      minimumFractionDigits: 4,
      maximumFractionDigits: 4
    }),
    p3: UI.numeric((m.max_bytes || 0) / 1024 ** 2, {
      notation: "scientific",
      minimumFractionDigits: 4,
      maximumFractionDigits: 4
    }),
    p4: s.total_completed ?? 0,
    p5: s.total_started ?? 0
  }));
}
async function previewDifferences() {
  if (busy || searchRunning) return;
  const sequence = ++differenceSequence;
  try {
    const payload = differencePayload(),
      key = JSON.stringify(payload);
    $('difference_preview').disabled = true;
    differenceStatus(UI.msg("difference.previewDifferences.budget_50525b", {}));
    const result = await api('/api/difference-preview', payload);
    if (sequence !== differenceSequence || key !== JSON.stringify(differencePayload())) return;
    differencePreview = result;
    differencePreviewKey = key;
    differenceCounts(result);
    differenceStatus(result.reuse?.reusable ? UI.msg("difference.previewDifferences.window_0_968213", {}) : UI.msg("difference.previewDifferences.window_86ffd1", {
      p0: result.needed_simulations ?? 2
    }));
    $('difference_prepare').disabled = result.memory?.within_limit === false;
  } catch (error) {
    if (sequence === differenceSequence) differenceStatus(UI.errorText(error), true);
  } finally {
    if (sequence === differenceSequence) $('difference_preview').disabled = !differenceSource;
  }
}
function lockDifferences(active) {
  if (active) {
    busy = true;
    for (const id of ['experiment', 'protocol_panel', 'global_panel', 'search_panel', 'joint_search_panel', 'scope_comparison_panel', 'timing_panel', 'replay_view', 'difference_view']) if ($(id)) {
      differenceLocks.set('inert:' + id, $(id).inert);
      $(id).inert = true;
    }
    for (const id of ['run', 'baseline', 'load', 'export', 'save', 'compare_conditions', 'save_comparison', 'path_explore', 'path_create', 'path_save', 'replay_source', 'replay_sources_refresh', 'replay_preview', 'replay_prepare', 'replay_save', 'difference_preview', 'difference_prepare', 'difference_save', 'difference_window', 'difference_start', 'difference_stop', 'difference_max_bytes']) if ($(id)) {
      differenceLocks.set('disabled:' + id, $(id).disabled);
      $(id).disabled = true;
    }
    $('difference_cancel').disabled = false;
  } else {
    busy = false;
    for (const [key, value] of differenceLocks) {
      const [field, id] = key.split(':');
      $(id)[field] = value;
    }
    differenceLocks.clear();
    $('difference_cancel').disabled = true;
    $('difference_prepare').disabled = !differencePreview || differencePreview.memory?.within_limit === false;
    $('difference_save').disabled = !differenceResult?.ready;
    $('save').disabled = !latest || dirty;
    $('save_comparison').disabled = !canSaveComparison();
  }
}
async function prepareDifferences() {
  if (busy || searchRunning) return;
  try {
    const payload = differencePayload();
    if (differencePreviewKey !== JSON.stringify(payload)) throw UI.error("difference.prepareDifferences.window_budget_de5c4f", {});
    pauseReplay();
    lockDifferences(true);
    const task = await api('/api/difference-prepare', payload);
    differenceJob = task.job_id;
    pollDifferences(differenceJob);
  } catch (error) {
    lockDifferences(false);
    differenceStatus(UI.errorText(error), true);
  }
}
async function pollDifferences(job) {
  try {
    const task = await api('/api/difference-task?' + new URLSearchParams({
      job_id: job
    }));
    if (job !== differenceJob) return;
    if (task.status === 'running') {
      const p = task.progress || {},
        s = p.simulations || {};
      differenceStatus(UI.msg("difference.pollDifferences.baseline_intervention_c0be57", {
        p0: {
          baseline_started: UI.msg("difference.pollDifferences.baseline_b7692b", {}),
          baseline_completed: UI.msg("difference.pollDifferences.baselinecomplete_ae2fc4", {}),
          intervention_started: UI.msg("difference.pollDifferences.intervention_ec21cc", {}),
          intervention_completed: UI.msg("difference.pollDifferences.interventioncomplete_451011", {})
        }[p.phase] || UI.msg("difference.pollDifferences.message_afa5aa", {}),
        p1: s.baseline_completed ?? 0,
        p2: s.baseline_started ?? 0,
        p3: s.intervention_completed ?? 0,
        p4: s.intervention_started ?? 0
      }));
      setTimeout(() => pollDifferences(job), 650);
      return;
    }
    lockDifferences(false);
    if (task.result?.ready) await openDifferences({
      ...task.result,
      difference_id: task.result.difference_id || task.difference_id
    }, false);else {
      if (task.result) differenceCounts(task.result);
      differenceStatus(UI.jobText(task, {
        cancelled: UI.msg("difference.pollDifferences.cancelled_a8aa2a", {}),
        failed: UI.msg("difference.pollDifferences.failed_b5d444", {})
      }[task.status] || UI.msg("difference.pollDifferences.complete_99cc11", {})), true);
    }
  } catch (error) {
    if (job === differenceJob) {
      lockDifferences(false);
      differenceStatus(UI.errorText(error), true);
    }
  }
}
function differenceDisplay() {
  return {
    sort: $('difference_sort').value,
    body_id: $('difference_body').value.trim(),
    type_filter: $('difference_type').value.trim(),
    hide_endpoints: $('difference_hide_endpoints').checked,
    offset: differencePage?.offset || 0,
    selected_nodes: [...differenceSelected],
    selected_node: differenceSelectedNode
  };
}
async function readDifferenceRows(offset = 0) {
  if (!differenceResult?.ready) return;
  const sequence = ++differenceRowsSequence,
    id = differenceResult.difference_id,
    filters = differenceDisplay();
  try {
    const result = await api('/api/difference-rows?' + new URLSearchParams({
      difference_id: id,
      sort: filters.sort,
      body_id: filters.body_id,
      type_filter: filters.type_filter,
      hide_endpoints: String(filters.hide_endpoints),
      offset,
      limit: 50
    }));
    if (sequence !== differenceRowsSequence || id !== differenceResult?.difference_id) return;
    differencePage = result;
    $('difference_rows').innerHTML = result.rows.map(row => `<tr class="${differenceSelectedNode === row.body_id ? 'selectedrow' : ''}"><td><input type="checkbox" data-difference-select="${esc(row.body_id)}" ${differenceSelected.has(row.body_id) ? 'checked' : ''} ${UI.htmlAttribute("aria-label", "difference.controls.select_f0f5c3", {
      p0: row.body_id
    })}></td><td><button class="linkbtn" data-difference-node="${esc(row.body_id)}">${UI.html(differenceLabel(row))}</button></td><td>${UI.html(differenceRoles(row))}</td>${differenceMetricCells(row)}</tr>`).join('');
    const returned = result.returned ?? result.rows.length,
      total = result.total;
    UI.text($('difference_rows_status'), UI.msg("difference.readDifferenceRows.node_back_3c1132", {
      p0: differenceLabels[filters.sort],
      p1: UI.numeric(total, {}),
      p2: UI.numeric(differenceResult.counts.statistic_node_count, {}),
      p3: UI.numeric(returned, {}),
      p4: total ? result.offset + 1 : 0,
      p5: Math.min(result.offset + returned, total)
    }));
    $('difference_prev').disabled = result.offset === 0;
    $('difference_next').disabled = result.offset + returned >= total;
  } catch (error) {
    if (sequence === differenceRowsSequence) {
      UI.text($('difference_rows_status'), UI.errorText(error));
      $('difference_rows').replaceChildren();
    }
  }
}
function renderDifferenceSelection() {
  $('difference_selection').innerHTML = `<span class="pill">${UI.htmlText("difference.renderDifferenceSelection.node_c2d1d4", {
    p0: UI.numeric(differenceSelected.size, {})
  })}</span>` + [...differenceSelected].map(id => `<button class="small" data-difference-remove="${esc(id)}" ${UI.htmlAttribute("aria-label", "difference.controls.remove_912bb1", {
    p0: id
  })}>${UI.html(id)} ×</button>`).join('');
  $('difference_intervention').disabled = !differenceSelected.size;
  $('difference_replay_preview').disabled = !differenceSelected.size;
  for (const input of document.querySelectorAll('[data-difference-select]')) input.checked = differenceSelected.has(input.dataset.differenceSelect);
  differenceReplayPreviewKey = null;
  $('difference_replay_prepare').disabled = true;
  UI.text($('difference_replay_status'), '');
  $('difference_save').disabled = !differenceResult?.ready;
}
async function selectDifferenceNode(id) {
  if (!differenceResult?.ready) return;
  const sequence = ++differenceNodeSequence,
    resultId = differenceResult.difference_id;
  differenceSelectedNode = id;
  UI.text($('difference_node_detail'), UI.msg("difference.selectDifferenceNode.node_e4eb14", {}));
  try {
    const row = await api('/api/difference-node?' + new URLSearchParams({
      difference_id: resultId,
      id
    }));
    if (sequence !== differenceNodeSequence || resultId !== differenceResult?.difference_id) return;
    $('difference_node_detail').innerHTML = `<h3 style="margin-top:14px">${UI.html(differenceLabel(row))}</h3><div>${UI.htmlText("difference.selectDifferenceNode.baseline_sum_intervention_sum_sum_difference_mean_differ_bec6c2", {
      p0: differenceRoles(row),
      p1: UI.numeric(row.baseline_sum, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      }),
      p2: UI.numeric(row.intervention_sum, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      }),
      p3: UI.numeric(row.sum_delta, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      }),
      p4: UI.numeric(row.absolute_sum_delta, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      }),
      p5: UI.numeric(row.mean_delta, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      }),
      p6: row.baseline_near_zero ? UI.msg("difference.selectDifferenceNode.baseline_relative_change_definition_36f676", {}) : UI.join([UI.msg("difference.selectDifferenceNode.relative_change_6c3b68", {}), replayPercent(row.relative_sum_delta)])
    })}</div>`;
    $('difference_node_full').disabled = false;
    $('difference_save').disabled = false;
    for (const tr of $('difference_rows').querySelectorAll('tr')) tr.classList.toggle('selectedrow', tr.querySelector('[data-difference-node]')?.dataset.differenceNode === id);
    await readDifferenceNeighbors(0);
  } catch (error) {
    if (sequence === differenceNodeSequence) UI.text($('difference_node_detail'), UI.errorText(error));
  }
}
async function readDifferenceNeighbors(offset = 0) {
  if (!differenceSelectedNode || !differenceResult?.ready) return;
  const sequence = ++differenceNeighborSequence,
    id = differenceResult.difference_id,
    node = differenceSelectedNode,
    direction = $('difference_neighbor_direction').value;
  try {
    const result = await api('/api/difference-neighbors?' + new URLSearchParams({
      difference_id: id,
      id: node,
      direction,
      offset,
      limit: 30
    }));
    if (sequence !== differenceNeighborSequence || id !== differenceResult?.difference_id || node !== differenceSelectedNode) return;
    differenceNeighborPage = result;
    $('difference_neighbors').innerHTML = result.rows.map(edge => {
      const neighbor = typeof edge.neighbor === 'object' ? String(edge.neighbor.body_id || edge.neighbor.bodyId) : String(edge.neighbor || (edge.pre_id === node ? edge.post_id : edge.pre_id)),
        annotation = edge.annotation || edge.neighbor?.annotation || edge.neighbor || {};
      return `<tr><td><input type="checkbox" data-difference-select="${esc(neighbor)}" ${differenceSelected.has(neighbor) ? 'checked' : ''} ${UI.htmlAttribute("aria-label", "difference.controls.select_913910", {
        p0: neighbor
      })}></td><td><button class="linkbtn" data-difference-node="${esc(neighbor)}">${UI.html(annotation.type || annotation.instance || UI.msg("difference.controls.type_fb8761", {}))} · ${UI.html(neighbor)}</button></td><td>${UI.html(edge.pre_id)} → ${UI.html(edge.post_id)}</td><td>${UI.htmlNumber(UI.numeric(edge.count, {}), false)}</td><td>${UI.htmlNumber(UI.numeric(edge.weight, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      }), false)}</td></tr>`;
    }).join('');
    const returned = result.rows.length;
    UI.text($('difference_neighbors_status'), UI.msg("difference.readDifferenceNeighbors.current_scope_connections_back_28d285", {
      p0: node,
      p1: UI.numeric(result.total, {}),
      p2: returned,
      p3: result.total ? result.offset + 1 : 0,
      p4: Math.min(result.offset + returned, result.total)
    }));
    $('difference_neighbor_prev').disabled = result.offset === 0;
    $('difference_neighbor_next').disabled = result.offset + returned >= result.total;
  } catch (error) {
    if (sequence === differenceNeighborSequence) {
      UI.text($('difference_neighbors_status'), UI.errorText(error));
      $('difference_neighbors').replaceChildren();
    }
  }
}
async function openDifferences(result, saved = true) {
  const sequence = ++differenceSequence;
  differenceRowsSequence++;
  differenceNodeSequence++;
  differenceNeighborSequence++;
  differenceResult = replayClone(result);
  differenceSelected = new Set(result.display?.selected_nodes || []);
  differenceSelectedNode = null;
  differenceNeighborPage = null;
  differenceSource = {
    label: UI.msg("difference.openDifferences.scope_differences_fixed_plan_524b92", {}),
    source: {
      kind: 'difference',
      difference_id: result.difference_id
    },
    experiment: replayClone(result.config.experiment)
  };
  setDifferenceWindows(result.config.experiment, result.window || result.config.window || result.config.request?.window);
  $('difference_max_bytes').value = (result.memory?.max_bytes || 64 * 1024 ** 2) / 1024 ** 2;
  $('difference_area').open = true;
  $('replay_area').open = true;
  $('difference_view').hidden = false;
  const w = result.window || result.config.window || result.config.request.window,
    c = result.config.experiment;
  UI.text($('difference_source_info'), UI.msg("difference.openDifferences.fixed_plan_ab707a", {}));
  UI.text($('difference_result_context'), UI.msg("difference.openDifferences.scope_status_observation_2b5066", {
    p0: saved ? UI.msg("difference.openDifferences.saveanalysis_2c23f9", {}) : UI.msg("difference.openDifferences.completeanalysis_e48646", {}),
    p1: result.config.case_id,
    p2: w.start,
    p3: w.stop,
    p4: w.start + 1,
    p5: w.stop,
    p6: protocolSources(c).length,
    p7: protocolObservations(c).length,
    p8: Array.isArray(c.intervention_events) ? UI.msg("difference.openDifferences.intervention_9c72a3", {
      p0: c.intervention_events.length,
      p1: c.intervention_events.filter(e => e.enabled).map(e => e.name + " [" + e.start + ", " + e.stop + ")").join(" / ")
    }) : UI.msg("difference.openDifferences.intervention_node_35359d", {
      p0: c.intervention_ids?.length || 0,
      p1: c.gain,
      p2: c.intervention_start,
      p3: c.intervention_stop
    })
  }));
  differenceCounts(result);
  const d = result.display || {};
  $('difference_sort').value = d.sort || 'absolute';
  $('difference_body').value = d.body_id || '';
  $('difference_type').value = d.type_filter || '';
  $('difference_hide_endpoints').checked = d.hide_endpoints ?? true;
  $('difference_node_detail').replaceChildren();
  $('difference_neighbors').replaceChildren();
  UI.text($('difference_neighbors_status'), '');
  $('difference_node_full').disabled = true;
  renderDifferenceSelection();
  $('difference_save').disabled = saved;
  $('difference_path_targets').innerHTML = protocolObservations(c).map((o, k) => `<label class="pill"><input type="checkbox" data-difference-target="${esc(o.name)}" ${k < 2 ? 'checked' : ''}> ${UI.html(o.name)}</label>`).join('');
  differencePreview = null;
  differencePreviewKey = null;
  $('difference_prepare').disabled = true;
  differenceStatus(UI.msg("difference.openDifferences.node_open_sort_filter_select_955afe", {}));
  await readDifferenceRows(d.offset || 0);
  if (sequence !== differenceSequence) return;
  if (d.selected_node) await selectDifferenceNode(d.selected_node);
  if (sequence !== differenceSequence) return;
  if (saved) $('difference_save').disabled = true;
}
function sendDifferenceSelection() {
  if (busy) throw UI.error("difference.sendDifferenceSelection.stop_b3daa7", {});
  const ids = [...differenceSelected],
    allowed = new Set(candidateNodes('__all__').map(node => node.bodyId));
  if (!ids.length) throw UI.error("difference.sendDifferenceSelection.select_nodes_first_24135a", {});
  const invalid = ids.filter(id => !allowed.has(id));
  if (invalid.length) throw UI.errorValue(UI.join([UI.msg("difference.sendDifferenceSelection.node_intervention_node_9e037c", {}), invalid.join(', ')]));
  const previous = $('selection_mode').value === 'ids' ? currentSelectionIds() : [];
  $('intervention_group').value = '__all__';
  $('selection_mode').value = 'ids';
  $('selection_ids').value = [...new Set([...previous, ...ids])].join(', ');
  changed();
  differenceStatus(UI.msg("difference.sendDifferenceSelection.intervention_not_run_result_source_plan_a7705e", {}));
}
async function exploreDifferencePathways() {
  if (busy || !differenceResult) return;
  try {
    const source_ids = [...differenceSelected],
      targets = [...$('difference_path_targets').querySelectorAll('input:checked')].map(input => input.dataset.differenceTarget);
    if (!source_ids.length) throw UI.error("difference.exploreDifferencePathways.selectpathsstarting_nodes_79d725", {});
    if (!targets.length || targets.length > 2) throw UI.error("difference.exploreDifferencePathways.select1_2_observation_sets_217d3b", {});
    const result = await api('/api/difference-pathways', {
      difference_id: differenceResult.difference_id,
      source_ids,
      targets,
      request: {
        max_hops: Number($('path_hops').value),
        min_contacts: Number($('path_contacts').value),
        max_nodes: Number($('path_nodes').value),
        max_edges: Number($('path_edges').value),
        detail_nodes: 60,
        detail_edges: 180
      }
    });
    applyPathwayRequest(result);
    renderPathways(result);
    UI.text($('difference_path_status'), UI.msg("difference.exploreDifferencePathways.scope_paths_starting_nodes_target_node_5228ac", {
      p0: source_ids.length,
      p1: targets.join(' / '),
      p2: UI.numeric(result.node_count, {}),
      p3: UI.numeric(result.edge_count, {})
    }));
  } catch (error) {
    UI.text($('difference_path_status'), UI.errorText(error));
  }
}
function differenceReplayPayload() {
  if (!differenceResult?.ready) throw UI.error("difference.differenceReplayPayload.complete_scope_differences_df0717", {});
  if (!differenceSelected.size) throw UI.error("difference.differenceReplayPayload.selectreplaynode_64d7e1", {});
  return {
    difference_id: differenceResult.difference_id,
    node_ids: [...differenceSelected],
    request: {
      ...replayRequest([]),
      node_ids: undefined,
      window: differenceResult.window || differenceResult.config.window
    }
  };
}
async function previewDifferenceReplay() {
  if (busy || searchRunning) return;
  const sequence = differenceSequence;
  try {
    const payload = differenceReplayPayload(),
      key = JSON.stringify(payload);
    differenceReplayPreviewKey = null;
    $('difference_replay_prepare').disabled = true;
    const result = await api('/api/difference-replay-preview', payload);
    if (sequence !== differenceSequence || key !== JSON.stringify(differenceReplayPayload())) return;
    differenceReplayPreviewKey = key;
    replayCounts(result);
    UI.text($('difference_replay_status'), UI.msg("difference.previewDifferenceReplay.node_members_node_node_4640ce", {
      p0: differenceSelected.size,
      p1: UI.numeric(result.counts.display_node_count, {}),
      p2: UI.numeric(result.counts.display_edge_count, {}),
      p3: result.missing_node_ids?.length || 0,
      p4: result.missing_time_steps?.length || 0,
      p5: result.needed_simulations ?? (result.reusable ? 0 : 2)
    }));
    $('difference_replay_prepare').disabled = result.memory?.within_limit === false;
  } catch (error) {
    if (sequence === differenceSequence) UI.text($('difference_replay_status'), UI.errorText(error));
  }
}
async function prepareDifferenceReplay() {
  if (busy || searchRunning) return;
  try {
    const payload = differenceReplayPayload();
    if (differenceReplayPreviewKey !== JSON.stringify(payload)) throw UI.error("difference.prepareDifferenceReplay.circuit_budget_6f4c90", {});
    pauseReplay();
    lockReplay(true);
    const task = await api('/api/difference-replay-prepare', payload);
    replayJob = task.job_id;
    pollReplay(replayJob);
  } catch (error) {
    lockReplay(false);
    UI.text($('difference_replay_status'), UI.errorText(error));
  }
}
$('difference_preview').onclick = previewDifferences;
$('difference_prepare').onclick = prepareDifferences;
$('difference_cancel').onclick = async () => {
  try {
    if (differenceJob) await api('/api/cancel-differences', {
      job_id: differenceJob
    });
    differenceStatus(UI.msg("difference.controls.cancel_complete_analysis_keep_87aa15", {}));
  } catch (error) {
    differenceStatus(UI.errorText(error), true);
  }
};
$('difference_save').onclick = async () => {
  const result = differenceResult, sequence = differenceSequence;
  try {
    if (!differenceResult?.ready) throw UI.error("difference.controls.complete_74d35b", {});
    const saved = await api('/api/save-differences', {
      difference_id: differenceResult.difference_id,
      display: differenceDisplay()
    });
    if (result !== differenceResult || sequence !== differenceSequence) return;
    differenceStatus(UI.join([UI.msg("difference.controls.analysis_save_0002bf", {}), saved.folder]));
    document.dispatchEvent(new Event('lab-saved'));
  } catch (error) {
    if (result === differenceResult && sequence === differenceSequence) differenceStatus(UI.errorText(error), true);
  }
};
$('difference_filter').onclick = () => readDifferenceRows();
$('difference_sort').onchange = () => readDifferenceRows();
$('difference_hide_endpoints').onchange = () => readDifferenceRows();
$('difference_prev').onclick = () => readDifferenceRows(Math.max(0, (differencePage?.offset || 0) - 50));
$('difference_next').onclick = () => readDifferenceRows((differencePage?.offset || 0) + 50);
$('difference_clear').onclick = () => {
  differenceSelected.clear();
  renderDifferenceSelection();
};
$('difference_intervention').onclick = () => {
  try {
    sendDifferenceSelection();
  } catch (error) {
    differenceStatus(UI.errorText(error), true);
  }
};
$('difference_node_full').onclick = () => {
  if (differenceSelectedNode) showNode(differenceSelectedNode);
};
$('difference_neighbor_direction').onchange = () => readDifferenceNeighbors();
$('difference_neighbor_prev').onclick = () => readDifferenceNeighbors(Math.max(0, (differenceNeighborPage?.offset || 0) - 30));
$('difference_neighbor_next').onclick = () => readDifferenceNeighbors((differenceNeighborPage?.offset || 0) + 30);
$('difference_pathways').onclick = exploreDifferencePathways;
$('difference_add_path').onclick = () => {
  try {
    const ids = selectedRows('path_nodes_rows');
    if (!ids.length) throw UI.error("difference.controls.select_paths_node_6681ac", {});
    if (pathwayResult?.scope.kind !== 'case' || pathwayResult.scope.case_id && pathwayResult.scope.case_id !== differenceResult.config.case_id) throw UI.error("difference.controls.paths_analysis_scope_83f268", {});
    ids.forEach(id => differenceSelected.add(id));
    renderDifferenceSelection();
  } catch (error) {
    UI.text($('difference_path_status'), UI.errorText(error));
  }
};
$('difference_replay_preview').onclick = previewDifferenceReplay;
$('difference_replay_prepare').onclick = prepareDifferenceReplay;
$('difference_window').onchange = () => {
  $('difference_custom_window').hidden = $('difference_window').value !== 'custom';
  invalidateDifferenceRequest();
};
for (const id of ['difference_start', 'difference_stop', 'difference_max_bytes']) $(id).addEventListener('input', invalidateDifferenceRequest);
for (const id of ['replay_max_nodes', 'replay_max_edges', 'replay_stride', 'replay_max_bytes']) $(id).addEventListener('input', () => {
  differenceReplayPreviewKey = null;
  $('difference_replay_prepare').disabled = true;
});
document.addEventListener('change', event => {
  const id = event.target.dataset.differenceSelect;
  if (id) {
    event.target.checked ? differenceSelected.add(id) : differenceSelected.delete(id);
    renderDifferenceSelection();
  }
});
document.addEventListener('click', event => {
  const node = event.target.closest('[data-difference-node]'),
    remove = event.target.dataset.differenceRemove;
  if (node) selectDifferenceNode(node.dataset.differenceNode);
  if (remove) {
    differenceSelected.delete(remove);
    renderDifferenceSelection();
  }
});
document.addEventListener('lab-replay-source', event => bindDifferenceSource(event.detail));
document.addEventListener('lab-differences-open', event => openDifferences(event.detail.result, true));
document.addEventListener('lab-case', () => {
  differenceSequence++;
  differenceRowsSequence++;
  differenceNodeSequence++;
  differenceNeighborSequence++;
  differenceSource = null;
  differenceResult = null;
  differencePreview = null;
  differenceJob = null;
  differenceSelected.clear();
  differenceSelectedNode = null;
  $('difference_view').hidden = true;
  UI.text($('difference_source_info'), '');
  UI.text($('difference_counts'), '');
  differenceStatus('');
  for (const id of ['difference_prepare', 'difference_cancel', 'difference_save']) $(id).disabled = true;
});
