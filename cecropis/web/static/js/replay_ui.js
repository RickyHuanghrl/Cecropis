"use strict";

/* A replay source is a trusted result handle, never the experiment editor. */
let replaySources = [],
  replaySource = null,
  replayArtifact = null,
  replayPreview = null,
  replayPreviewKey = null;
let replayResult = null,
  replayFrame = null,
  replayJob = null,
  replaySequence = 0,
  replayFrameSequence = 0,
  replayPickSequence = 0,
  replayPlaying = null,
  replayPositions = new Map(),
  replaySelected = new Set(),
  replaySelectedNode = null,
  replaySelectedEdge = null,
  replayLocks = new Map(),
  replayWindows = new Map();
let replayTopology = null,
  replayTopologyId = null,
  replayOutputId = null;
const replayClone = value => JSON.parse(JSON.stringify(value));
// Display messages stay typed in memory; JSON cloning would freeze their language.
const replayCloneSource = value => ({...replayClone(value), label: value.label});
function replayPercent(value) {
  return value != null && Number.isFinite(value) && value !== 0 && Math.abs(value * 100) < .0005 ? contextNumber(value * 100) + '%' : contextPercent(value);
}
function replayStatus(message, error = false) {
  UI.text($('replay_status'), message);
  $('replay_status').classList.toggle('error', error);
}
function replayExperiment(result) {
  return result?.config?.experiment || result?.experiment;
}
function replayBuildSources() {
  const choices = [],
    add = (label, source, experiment, window = null) => choices.push({
      label,
      source: replayClone(source),
      experiment: experiment ? replayClone(experiment) : null,
      window: window ? replayClone(window) : null
    });
  if (latest?.run_id && latest.kind !== 'forward') add(UI.msg("replay.replayBuildSources.run_7e7936", {}), {
    kind: 'run',
    run_id: latest.run_id
  }, replayExperiment(latest));
  if (comparison?.comparison_id) for (const [k, row] of comparison.rows.entries()) {
    const name = comparison.conditions?.[k]?.name || row.name;
    add(UI.join([UI.msg("replay.replayBuildSources.comparison_7cb4ed", {}), name]), {
      kind: 'comparison',
      comparison_id: comparison.comparison_id,
      condition_name: name
    }, replayExperiment(comparison.results[k]));
  }
  if (typeof jointResult !== 'undefined' && jointResult && jointSelectedPlan && (jointJobId || jointArtifactId)) for (const condition of jointResult.conditions) add(UI.join([UI.msg("replay.replayBuildSources.plan_25ec24", {}), condition.name]), {
    kind: 'joint',
    ...(jointJobId ? {
      job_id: jointJobId
    } : {
      artifact_id: jointArtifactId
    }),
    body_ids: jointSelectedPlan.body_ids,
    condition_name: condition.name
  }, {
    ...condition.experiment,
    intervention_ids: jointSelectedPlan.body_ids
  });
  if (typeof timingReport !== 'undefined' && timingReport && timingSelectedEntry()?.status === 'completed' && (timingJobId || timingArtifactId)) {
    const item = timingSelectedEntry();
    for (const condition of timingReport.conditions) add(UI.msg("replay.replayBuildSources.message_67b8cd", {
      p0: item.start,
      p1: item.stop,
      p2: condition.name
    }), {
      kind: 'timing',
      ...(timingJobId ? {
        job_id: timingJobId
      } : {
        artifact_id: timingArtifactId
      }),
      start: item.start,
      duration: item.duration,
      condition_name: condition.name
    }, {
      ...condition.experiment,
      intervention_ids: timingReport.body_ids,
      intervention_start: item.start,
      intervention_stop: item.stop
    });
  }
  if (replayArtifact?.result && ['run', 'comparison'].includes(replayArtifact.kind)) {
    const result = replayArtifact.result,
      id = replayArtifact.artifact_id || replayArtifact.id;
    if (result.results) for (const [k, row] of result.rows.entries()) {
      const name = result.conditions?.[k]?.name || row.name;
      add(UI.join([UI.msg("replay.replayBuildSources.save_92ce37", {}), name]), {
        kind: 'artifact',
        artifact_id: id,
        condition_name: name
      }, replayExperiment(result.results[k]));
    } else if (result.kind !== 'forward') add(UI.msg("replay.replayBuildSources.saverun_33d98f", {}), {
      kind: 'artifact',
      artifact_id: id
    }, replayExperiment(result));
  }
  if (replayResult?.ready && replayResult.replay_id) add(UI.msg("replay.replayBuildSources.replay_fixed_plan_9ea230", {}), {
    kind: 'replay',
    replay_id: replayResult.replay_id
  }, replayExperiment(replayResult), replayResult.display?.window || replayResult.default_window);
  return choices;
}
function refreshReplaySources(preferred = null) {
  replaySources = replayBuildSources();
  $('replay_source').replaceChildren(
    UI.option(UI.msg('replay.refreshReplaySources.select_an_existing_result_f83e28'), ''),
    ...replaySources.map((source, k) => UI.option(source.label, String(k)))
  );
  if (preferred) {
    const index = replaySources.findIndex(c => JSON.stringify(c.source) === JSON.stringify(preferred));
    if (index >= 0) $('replay_source').value = String(index);
  }
}
function selectReplaySource(index) {
  const source = replaySources[Number(index)];
  if (!source || index === '') return;
  pauseReplay();
  replaySource = replayCloneSource(source);
  invalidateReplayRequest();
  replayFrameSequence++;
  replayPickSequence++;
  $('replay_view').hidden = true;
  $('replay_save').disabled = true;
  UI.text($('replay_source_info'), source.label);
  replayStatus(UI.msg("replay.selectReplaySource.node_2cd24a", {}));
  $('replay_area').open = true;
  document.dispatchEvent(new CustomEvent('lab-replay-source', {
    detail: replayCloneSource(replaySource)
  }));
}
function replayRequest(nodeIds = null) {
  const ids = nodeIds ?? ($('replay_ids').value.trim() ? parseBodyIds($('replay_ids').value) : []),
    max_nodes = Number($('replay_max_nodes').value),
    max_edges = Number($('replay_max_edges').value),
    stride = Number($('replay_stride').value),
    max_bytes = Number($('replay_max_bytes').value) * 1024 ** 2;
  if (!Number.isInteger(max_nodes) || max_nodes < 1 || max_nodes > 500 || !Number.isInteger(max_edges) || max_edges < 1 || max_edges > 10000 || !Number.isInteger(stride) || stride < 1 || !Number.isSafeInteger(max_bytes) || max_bytes < 1) throw UI.error("replay.replayRequest.replaynode_budget_3e3fd5", {});
  return {
    node_ids: ids,
    max_nodes,
    max_edges,
    recording: {
      step_stride: stride,
      max_bytes
    }
  };
}
function replayPayload() {
  if (!replaySource) throw UI.error("replay.replayPayload.select_save_07a218", {});
  return {
    source: replayClone(replaySource.source),
    request: replayRequest()
  };
}
function replayRequestKey() {
  return JSON.stringify(replayPayload());
}
function pauseReplay() {
  if (replayPlaying) clearInterval(replayPlaying);
  replayPlaying = null;
  UI.text($('replay_play'), UI.msg("replay.pauseReplay.play_c33961", {}));
}
function invalidateReplayRequest() {
  replaySequence++;
  replayPreview = null;
  replayPreviewKey = null;
  $('replay_prepare').disabled = true;
  if (replayResult) replayStatus(UI.msg("replay.invalidateReplayRequest.replay_select_4bb42f", {}));
}
function replayCounts(result) {
  const counts = result.counts || {},
    memory = result.memory || {},
    sim = result.simulations || {};
  UI.text($('replay_counts'), UI.join([UI.list(Object.entries(counts).map(([key, value]) => UI.join([{
    computation_node_count: UI.msg("replay.controls.compute_nodes_d8bfe4", {}),
    intervention_node_count: UI.msg("replay.controls.interventionnode_7d73b2", {}),
    intervention_edge_count: UI.msg("replay.controls.intervention_a17006", {}),
    recorded_node_count: UI.msg("replay.controls.recorded_nodes_53b10d", {}),
    display_node_count: UI.msg("replay.controls.node_83ca12", {}),
    display_edge_count: UI.msg("replay.controls.message_bac628", {}),
    omitted_internal_edge_count: UI.msg("replay.controls.internal_edges_f1ee85", {}),
    omitted_node_count: UI.msg("replay.controls.node_6c7394", {}),
    selected_node_count: UI.msg("replay.controls.specified_nodes_1972ed", {}),
    context_node_count: UI.msg("replay.controls.node_bf2da6", {})
  }[key] || key, " ", num(value)])), ' · '), UI.msg("replay.replayCounts.mib_mib_mib_5e794b", {
    p0: UI.numeric((memory.record_bytes || 0) / 1024 ** 2, {
      notation: "scientific",
      minimumFractionDigits: 4,
      maximumFractionDigits: 4
    }),
    p1: UI.numeric((memory.estimated_peak_bytes || 0) / 1024 ** 2, {
      notation: "scientific",
      minimumFractionDigits: 4,
      maximumFractionDigits: 4
    }),
    p2: UI.numeric((memory.max_bytes || 0) / 1024 ** 2, {
      notation: "scientific",
      minimumFractionDigits: 4,
      maximumFractionDigits: 4
    }),
    p3: sim.total_completed ?? 0,
    p4: sim.total_started ?? 0
  })]));
}
async function previewReplay() {
  if (busy || searchRunning) return;
  const seq = ++replaySequence;
  try {
    const payload = replayPayload(),
      key = JSON.stringify(payload);
    $('replay_preview').disabled = true;
    replayStatus(UI.msg("replay.previewReplay.budget_c07e5f", {}));
    const result = await api('/api/replay-preview', payload);
    if (seq !== replaySequence || key !== replayRequestKey()) return;
    replayPreview = result;
    replayPreviewKey = key;
    replayCounts(result);
    replayStatus(result.reusable ? UI.msg("replay.previewReplay.message_7d42a2", {}) : UI.msg("replay.previewReplay.not_recorded_prepare_replay_node_59725e", {
      p0: result.missing_node_ids?.length || 0,
      p1: result.missing_time_steps?.length || 0,
      p2: result.needed_simulations ?? 2
    }));
    $('replay_prepare').disabled = false;
  } catch (error) {
    if (seq === replaySequence) replayStatus(UI.errorText(error), true);
  } finally {
    if (seq === replaySequence) $('replay_preview').disabled = !replaySource;
  }
}
function lockReplay(active) {
  if (active) {
    busy = true;
    for (const id of ['experiment', 'protocol_panel', 'global_panel', 'search_panel', 'joint_search_panel', 'scope_comparison_panel', 'timing_panel', 'replay_view', 'difference_area']) if ($(id)) {
      replayLocks.set('inert:' + id, $(id).inert);
      $(id).inert = true;
    }
    for (const id of ['run', 'baseline', 'load', 'export', 'save', 'compare_conditions', 'save_comparison', 'path_explore', 'path_create', 'path_save', 'replay_source', 'replay_sources_refresh', 'replay_ids', 'replay_max_nodes', 'replay_max_edges', 'replay_stride', 'replay_max_bytes', 'replay_preview', 'replay_prepare', 'replay_save', 'replay_use_path', 'replay_use_path_all']) if ($(id)) {
      replayLocks.set('disabled:' + id, $(id).disabled);
      $(id).disabled = true;
    }
    $('replay_cancel').disabled = false;
  } else {
    busy = false;
    for (const [key, value] of replayLocks) {
      const [field, id] = key.split(':');
      $(id)[field] = value;
    }
    replayLocks.clear();
    $('replay_cancel').disabled = true;
    $('replay_prepare').disabled = !replayPreview;
    $('replay_save').disabled = !replayResult?.ready;
    $('save_comparison').disabled = !canSaveComparison();
    $('save').disabled = !latest || dirty;
  }
}
async function prepareReplay() {
  if (busy || searchRunning) return;
  try {
    const payload = replayPayload();
    if (replayPreviewKey !== JSON.stringify(payload)) throw UI.error("replay.prepareReplay.replayscope_72b807", {});
    pauseReplay();
    lockReplay(true);
    const task = await api('/api/replay-prepare', payload);
    replayJob = task.job_id;
    pollReplay(replayJob);
  } catch (error) {
    lockReplay(false);
    replayStatus(UI.errorText(error), true);
  }
}
async function pollReplay(job) {
  try {
    const snapshot = await api('/api/replay-task?' + new URLSearchParams({
      job_id: job
    }));
    if (replayJob !== job) return;
    if (snapshot.status === 'running') {
      const p = snapshot.progress || {};
      replayStatus(UI.msg("replay.pollReplay.baseline_intervention_c0be57", {
        p0: {
          baseline_started: UI.msg("replay.pollReplay.baseline_b7692b", {}),
          baseline_completed: UI.msg("replay.pollReplay.baselinecomplete_ae2fc4", {}),
          intervention_started: UI.msg("replay.pollReplay.intervention_ec21cc", {}),
          intervention_completed: UI.msg("replay.pollReplay.interventioncomplete_451011", {}),
          complete: UI.msg("replay.pollReplay.complete_7a3adc", {})
        }[p.phase] || UI.msg("replay.pollReplay.message_871748", {}),
        p1: p.simulations?.baseline_completed ?? 0,
        p2: p.simulations?.baseline_started ?? 0,
        p3: p.simulations?.intervention_completed ?? 0,
        p4: p.simulations?.intervention_started ?? 0
      }));
      setTimeout(() => pollReplay(job), 650);
      return;
    }
    lockReplay(false);
    if (snapshot.result?.ready) await openReplay(snapshot.result, false);else {
      if (snapshot.result) replayCounts(snapshot.result);
      replayStatus(UI.jobText(snapshot, {
        cancelled: UI.msg("replay.pollReplay.cancelled_7743d6", {}),
        failed: UI.msg("replay.pollReplay.failed_a1e35e", {})
      }[snapshot.status] || UI.msg("replay.pollReplay.completereplay_1f7dd1", {})), true);
    }
  } catch (error) {
    if (replayJob === job) {
      lockReplay(false);
      replayStatus(UI.errorText(error), true);
    }
  }
}
function replayNodeId(node) {
  return String(node.body_id);
}
function layoutReplay(result) {
  const nodes = result.nodes.slice().sort((a, b) => BigInt(a.body_id) < BigInt(b.body_id) ? -1 : 1),
    levels = new Map(),
    links = new Map();
  for (const edge of result.edges) {
    if (!links.has(edge.pre_id)) links.set(edge.pre_id, []);
    links.get(edge.pre_id).push(edge.post_id);
  }
  let queue = nodes.filter(n => n.input).map(n => n.body_id);
  if (!queue.length && nodes.length) queue = [nodes[0].body_id];
  for (const id of queue) levels.set(id, 0);
  for (let k = 0; k < queue.length; k++) for (const id of links.get(queue[k]) || []) if (!levels.has(id)) {
    levels.set(id, Math.min(6, levels.get(queue[k]) + 1));
    queue.push(id);
  }
  for (const node of nodes) if (!levels.has(node.body_id)) levels.set(node.body_id, 7);
  const bands = new Map();
  for (const node of nodes) {
    const level = levels.get(node.body_id);
    if (!bands.has(level)) bands.set(level, []);
    bands.get(level).push(node);
  }
  const width = Math.max(650, (Math.max(1, ...bands.keys()) + 1) * 180),
    height = Math.max(220, ...[...bands.values()].map(list => list.length * 48 + 70)),
    positions = new Map();
  for (const [level, list] of bands) list.forEach((node, k) => positions.set(node.body_id, {
    x: 60 + level * (width - 120) / Math.max(1, ...bands.keys()),
    y: 40 + k * 48
  }));
  return {
    positions,
    width,
    height
  };
}
function replayColor(value, mode, edge = false) {
  if (value == null) return UI.color('muted');
  const d = replayResult.color_domain || {},
    max = mode === 'delta' ? edge ? d.edge_delta_abs_max : d.delta_abs_max : edge ? d.edge_activity_max : d.activity_max,
    fraction = max > 0 ? Math.max(-1, Math.min(1, value / max)) : 0;
  return UI.heatColor(fraction, 1, mode);
}
function renderReplayGraph() {
  if (!replayResult || !replayFrame) return;
  if (!replayTopology) {
    replayTopology = new TopologyView($('replay_graph'), {
      label: UI.msg("replay.renderReplayGraph.replay_4cba62", {}),
      onNode: (id, event) => selectReplayNode(id, event.shiftKey),
      onEdge: id => selectReplayEdge(id),
      onState: () => document.dispatchEvent(new Event('lab-analysis-display'))
    });
    window.replayTopology = replayTopology;
  }
  if (replayTopologyId !== replayResult.replay_id) {
    replayTopologyId = replayResult.replay_id;
    replayTopology.setGraph({
      nodes: replayResult.nodes,
      edges: replayResult.edges
    });
  }
  const mode = $('replay_mode').value;
  replayTopology.setSelection([...replaySelected], replaySelectedNode);
  replayTopology.setEdgeSelection(replaySelectedEdge);
  replayTopology.updateActivity(replayFrame, mode, replayColor);
  for (const row of replayFrame.nodes) {
    const node = replayTopology.nodes.get(String(row.body_id)),
      gain = row.active_gain ?? row.effective_gain ?? 1;
    if (node) {
      UI.attr(node.circle, 'stroke-dasharray', mode !== 'baseline' && gain < 1 ? '3 2' : '');
      UI.text(node.title, UI.join([UI.currentText(node.title), UI.msg("replay.renderReplayGraph.nodeactions_7fbf02", {
        p0: UI.numeric(gain, {
          notation: "scientific",
          minimumFractionDigits: 4,
          maximumFractionDigits: 4
        })
      })]));
    }
  }
  for (const row of replayFrame.edges) {
    const edge = replayTopology.edges.get(String(row.edge_id)),
      gain = row.effective_gain ?? row.active_gain ?? 1;
    if (edge) {
      UI.attr(edge.path, 'stroke-dasharray', mode !== 'baseline' && gain < 1 ? '5 3' : '');
      UI.text(edge.title, UI.join([UI.currentText(edge.title), UI.msg("replay.renderReplayGraph.message_a59e7a", {
        p0: UI.numeric(gain, {
          notation: "scientific",
          minimumFractionDigits: 4,
          maximumFractionDigits: 4
        })
      })]));
    }
  }
  const domain = replayResult.color_domain || {},
    max = mode === 'delta' ? domain.delta_abs_max : domain.activity_max;
  UI.text($('replay_color_scale'), UI.msg("replay.renderReplayGraph.fixed_node_color_domain_edges_76df93", {
    p0: mode === 'delta' ? '-' + contextNumber(max) : '0',
    p1: UI.numeric(max, {
      notation: "scientific",
      minimumFractionDigits: 4,
      maximumFractionDigits: 4
    }),
    p2: mode === 'delta' ? '-' + contextNumber(domain.edge_delta_abs_max) : '0',
    p3: UI.numeric(mode === 'delta' ? domain.edge_delta_abs_max : domain.edge_activity_max, {
      notation: "scientific",
      minimumFractionDigits: 4,
      maximumFractionDigits: 4
    })
  }));
}
function replayStateStep() {
  return replayResult?.time_steps?.[Number($('replay_scrub').value)];
}
function sampledReplayTrace(values, times, px, py, color, dashed = false) {
  const dense = times.every((step, k) => k === 0 || step === times[k - 1] + 1);
  if (dense) return `<polyline points="${values.map((v, k) => `${px(times[k])},${py(v)}`).join(' ')}" fill="none" stroke="${color}" ${dashed ? 'stroke-dasharray="5 3"' : ''}/>`;
  return values.map((v, k) => `<circle cx="${px(times[k])}" cy="${py(v)}" r="2.5" fill="${color}"><title>x(${times[k]}) · ${UI.html(contextNumber(v), true)}</title></circle>`).join('');
}
function renderReplayOutput() {
  const series = replayResult.output_series || replayResult.series,
    times = replayResult.output_time_steps || replayResult.time_steps;
  if (!series || !Object.keys(series).length) {
    UI.text($('replay_output'), UI.msg("replay.renderReplayOutput.observation_not_recorded_039161", {}));
    return;
  }
  const c = replayResult.config.experiment,
    W = 800,
    H = 160,
    L = 65,
    R = 20,
    step = replayStateStep(),
    markerX = L + step / c.steps * (W - L - R);
  if (replayOutputId === replayResult.replay_id && $('replay_output').querySelector('[data-replay-time-marker]')) {
    const marker = $('replay_output').querySelector('[data-replay-time-marker]'),
      text = $('replay_output').querySelector('[data-replay-time-label]');
    UI.attr(marker, 'x1', markerX);
    UI.attr(marker, 'x2', markerX);
    UI.attr(text, 'x', markerX);
    UI.text(text, `x(${step})`);
    return;
  }
  replayOutputId = replayResult.replay_id;
  let maximum = 1e-12;
  for (const s of Object.values(series)) for (const branch of ['baseline', 'intervention']) for (const value of s[branch] || []) maximum = Math.max(maximum, value);
  const px = t => L + t / c.steps * (W - L - R),
    py = v => H - 25 - v / maximum * (H - 40);
  let svg = `<svg class="plot" viewBox="0 0 ${W} ${H}" ${UI.htmlAttribute("aria-label", "replay.renderReplayOutput.observation_replay_8dcdc7", {})}>`;
  for (const [label, s] of Object.entries(series)) for (const branch of ['baseline', 'intervention']) if (s[branch]) svg += `<g><title>${UI.html(label, true)} · ${UI.html(branch === 'baseline' ? UI.msg("replay.renderReplayOutput.baseline_a7ac58", {}) : UI.msg("response.labels.intervention_c74feb"), true)}</title>${sampledReplayTrace(s[branch], times, px, py, observationColor(label), branch === 'intervention')}</g>`;
  svg += `<line data-replay-time-marker="" x1="${px(step)}" x2="${px(step)}" y1="5" y2="${H - 25}" stroke="var(--selection)"/><text data-replay-time-label="" x="${px(step)}" y="${H - 6}" fill="var(--selection)">x(${step})</text></svg>`;
  $('replay_output').innerHTML = UI.join([svg, protocolTimelineSvg([{
    config: {
      experiment: c
    },
    name: UI.msg("replay.renderReplayOutput.replay_0d9477", {})
  }], protocolObservations(c).map(o => o.name))]);
}
function renderReplayTime() {
  if (!replayFrame) return;
  const frame = replayFrame,
    values = {
      step: frame.state_step,
      update: frame.state_step
    };
  const state = UI.t(frame.connection_defined ? 'replay.state' : 'replay.finalState', values);
  const events = (frame.active_events || []).map(event => typeof event === 'string' ? event : UI.t('replay.namedEvent', {
    name: event.name,
    update: UI.t(event.type === 'node_gain' ? 'replay.nodeUpdate' : 'replay.edgeUpdate', {
      step: event.update_step
    })
  })).join(' / ');
  UI.text($('replay_time'), events ? UI.t('replay.activeState', {
    state,
    events
  }) : state);
}
document.addEventListener('ui-language', renderReplayTime);
async function readReplayFrame(index) {
  if (!replayResult?.ready) return;
  const seq = ++replayFrameSequence,
    id = replayResult.replay_id;
  index = Math.max(0, Math.min(replayResult.time_steps.length - 1, index));
  $('replay_scrub').value = String(index);
  const step = replayResult.time_steps[index];
  try {
    const frame = await api('/api/replay-frame?' + new URLSearchParams({
      replay_id: id,
      step
    }));
    if (seq !== replayFrameSequence || id !== replayResult?.replay_id) return;
    replayFrame = frame;
    renderReplayTime();
    renderReplayGraph();
    renderReplayOutput();
    updateReplayDetailValues();
  } catch (error) {
    if (seq === replayFrameSequence) {
      pauseReplay();
      replayStatus(UI.errorText(error), true);
    }
  }
}
function updateReplayDetailValues() {
  if (replaySelectedNode && $('replay_detail_values')) {
    const row = replayFrame.nodes.find(n => n.body_id === replaySelectedNode);
    UI.text($('replay_detail_values'), row ? UI.msg("replay.updateReplayDetailValues.statusx_baseline_intervention_difference_node_b38f0f", {
      p0: replayFrame.state_step,
      p1: UI.numeric(row.baseline, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      }),
      p2: UI.numeric(row.intervention, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      }),
      p3: UI.numeric(row.delta, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      }),
      p4: replayFrame.node_update_step ?? "—",
      p5: UI.numeric(row.active_gain ?? row.effective_gain ?? 1, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      })
    }) : UI.msg("replay.updateReplayDetailValues.not_recorded_7450cc", {}));
  } else if (replaySelectedEdge) {
    const row = replayFrame.edges.find(e => e.edge_id === replaySelectedEdge);
    if ($('replay_detail_values')) UI.text($('replay_detail_values'), row?.baseline == null ? UI.msg("replay.updateReplayDetailValues.status_connections_c4823b", {}) : UI.msg("replay.updateReplayDetailValues.baseline_intervention_difference_210298", {
      p0: replayFrame.state_step,
      p1: UI.numeric(row.baseline, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      }),
      p2: UI.numeric(row.intervention, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      }),
      p3: UI.numeric(row.delta, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      }),
      p4: UI.numeric(row.effective_gain ?? row.active_gain ?? 1, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      }),
      p5: UI.numeric((row.effective_gain ?? row.active_gain ?? 1) * (replayResult.edges.find(e => e.edge_id === replaySelectedEdge)?.weight ?? 0), {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      })
    }));
  }
}
function replayNodeCurve(node) {
  let max = 1e-12;
  for (const branch of ['baseline', 'intervention']) for (const value of node.series[branch] || []) max = Math.max(max, value);
  const W = 700,
    H = 170,
    L = 45,
    R = 15,
    steps = replayResult.config.experiment.steps,
    px = t => L + t / steps * (W - L - R),
    py = v => H - 25 - v / max * (H - 40);
  return `<svg viewBox="0 0 ${W} ${H}" class="plot" ${UI.htmlAttribute("aria-label", "replay.replayNodeCurve.node_e155a6", {})}>${['baseline', 'intervention'].map(branch => sampledReplayTrace(node.series[branch], node.time_steps, px, py, UI.color(branch), branch === 'intervention')).join('')}<text x="${L}" y="${H - 4}" fill="var(--muted)">${UI.svgText("replay.replayNodeCurve.recorded_states_baseline_dashed_intervention_solid_spars_50ccf6", {})}</text></svg>`;
}
async function selectReplayNode(id, additive = false, updateSelection = true) {
  if (!replayResult) return;
  const seq = ++replayPickSequence,
    replayId = replayResult.replay_id;
  replaySelectedNode = id;
  replaySelectedEdge = null;
  UI.text($('replay_detail'), UI.msg("replay.selectReplayNode.node_e4eb14", {}));
  if (updateSelection && additive) {
    if (window.analysisSelection) {
      window.analysisSelection.ids().includes(id) ? window.analysisSelection.remove(id) : window.analysisSelection.add([id]);
      replaySelected = new Set(window.analysisSelection.ids());
    } else {
      replaySelected.has(id) ? replaySelected.delete(id) : replaySelected.add(id);
    }
    $('replay_save').disabled = busy;
  }
  if (window.analysisSelection) window.analysisSelection.focus(id);
  renderReplayGraph();
  $('replay_add_selection').disabled = !replaySelected.size;
  $('replay_node_details').disabled = false;
  try {
    const detail = await api('/api/replay-node?' + new URLSearchParams({
      replay_id: replayId,
      id
    }));
    if (seq !== replayPickSequence || replayId !== replayResult?.replay_id) return;
    const meta = detail.meta || detail;
    const heading = document.createElement('strong'), values = document.createElement('div');
    UI.text(heading, id);
    values.id = 'replay_detail_values';
    $('replay_detail').replaceChildren(heading, document.createTextNode(' · ' + (meta.annotation?.type || meta.annotation?.instance || '')), values);
    for (const [direction, key] of [['upstream', 'analysis.controls.upstream_a9ab29'], ['downstream', 'analysis.controls.downstream_fde36e']]) {
      const row = document.createElement('div'), caption = document.createElement('span');
      UI.text(caption, UI.msg(key));
      row.append(caption, document.createTextNode(' '));
      const edges = detail[direction] || [];
      if (!edges.length) {
        const empty = document.createElement('span');
        UI.text(empty, UI.msg('replay.selectReplayNode.message_484d55'));
        row.append(empty);
      }
      for (const edge of edges) {
        const edgeId = typeof edge === 'string' ? edge : edge.edge_id;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'linkbtn';
        button.dataset.replayEdge = edgeId;
        UI.text(button, edgeId);
        row.append(button, document.createTextNode(' '));
      }
      $('replay_detail').append(row);
    }
    $('replay_node_chart').innerHTML = replayNodeCurve(detail);
    updateReplayDetailValues();
  } catch (error) {
    if (seq === replayPickSequence) replayStatus(UI.errorText(error), true);
  }
}
async function selectReplayEdge(id, displayEdit = true) {
  if (!replayResult) return;
  const seq = ++replayPickSequence,
    replayId = replayResult.replay_id;
  replaySelectedEdge = id;
  replaySelectedNode = null;
  if (displayEdit) $('replay_save').disabled = busy;
  UI.text($('replay_detail'), UI.msg("replay.selectReplayEdge.message_5b384f", {}));
  $('replay_node_details').disabled = true;
  renderReplayGraph();
  try {
    const detail = await api('/api/replay-edge?' + new URLSearchParams({
      replay_id: replayId,
      id,
      step: replayStateStep()
    }));
    if (seq !== replayPickSequence || replayId !== replayResult?.replay_id) return;
    $('replay_detail').innerHTML = `<strong>${UI.html(detail.pre_id)} → ${UI.html(detail.post_id)}</strong>${UI.htmlText("replay.selectReplayEdge.normalized_weight_a1d806", {
      p0: UI.numeric(detail.count, {}),
      p1: UI.numeric(detail.weight, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      })
    })}<div id="replay_detail_values"></div><div>${UI.htmlText("replay.selectReplayEdge.recursive_input_this_update_before_tanh_f10ac2", {})}</div><button class="small" data-operation-edge="${esc(JSON.stringify([detail.pre_id, detail.post_id]))}">${UI.htmlText("replay.selectReplayEdge.create_edge_event_f1e789", {})}</button>`;
    $('replay_node_chart').replaceChildren();
    updateReplayDetailValues();
  } catch (error) {
    if (seq === replayPickSequence) replayStatus(UI.errorText(error), true);
  }
}
function replayWindow() {
  const window = replayWindows.get($('replay_window').value);
  if (!window) throw UI.error("replay.replayWindow.select_an_item_replaywindow_4015d3", {});
  return {
    ...window
  };
}
function setReplayWindows(result) {
  const c = result.config.experiment,
    observations = protocolObservations(c),
    chosen = result.display?.window || result.default_window || {
      start: 0,
      stop: c.steps
    };
  replayWindows = new Map([['all', {
    start: 0,
    stop: c.steps
  }]]);
  let html = `<option value="all" data-i18n="replay.setReplayWindows.full_run_2d6445">${UI.t("replay.setReplayWindows.full_run_2d6445")}</option>`;
  for (const [o, k] of observations.map((o, k) => [o, k])) {
    const window = o.evaluation_window || {
      start: 0,
      stop: c.steps
    };
    replayWindows.set('observation:' + k, {
      ...window
    });
    html += `<option value="observation:${k}">${esc(o.name)} · [${window.start}, ${window.stop})</option>`;
  }
  const equal = window => window.start === chosen.start && window.stop === chosen.stop,
    preferred = observations.findIndex(o => o.name === result.default_window_observation),
    preferredKey = 'observation:' + preferred;
  let key = preferred >= 0 && equal(replayWindows.get(preferredKey)) ? preferredKey : [...replayWindows].find(([k, w]) => equal(w))?.[0];
  if (!key) {
    key = 'saved';
    replayWindows.set(key, {
      ...chosen
    });
    html += `<option value="saved">${UI.htmlText("replay.setReplayWindows.savewindow_7895fd", {
      p0: chosen.start,
      p1: chosen.stop
    })}</option>`;
  }
  $('replay_window').innerHTML = html;
  $('replay_window').value = key;
}
async function summarizeReplay() {
  if (!replayResult?.ready) return;
  const id = replayResult.replay_id,
    window = replayWindow(),
    key = JSON.stringify(window);
  try {
    UI.text($('replay_summary_status'), UI.msg("replay.summarizeReplay.window_046b47", {}));
    const result = await api('/api/replay-summary?' + new URLSearchParams({
      replay_id: id,
      start: window.start,
      stop: window.stop,
      limit: 50
    }));
    if (id !== replayResult?.replay_id || key !== JSON.stringify(replayWindow())) return;
    UI.text($('replay_summary_status'), UI.msg("replay.summarizeReplay.nodestatus_status_node_505d03", {
      p0: window.start,
      p1: window.stop,
      p2: window.start + 1,
      p3: window.stop,
      p4: window.start,
      p5: window.stop - 1,
      p6: result.nodes_defined && result.edges_defined ? '' : UI.msg("replay.summarizeReplay.window_definition_946f2e", {}),
      p7: result.missing_node_steps?.length ? UI.join([UI.msg("replay.summarizeReplay.nodestatus_5bcc4c", {}), result.missing_node_steps.join(', ')]) : '',
      p8: result.missing_edge_steps?.length ? UI.join([UI.msg("replay.summarizeReplay.status_8a4322", {}), result.missing_edge_steps.join(', ')]) : '',
      p9: (result.nodes || []).length,
      p10: result.node_total ?? '—',
      p11: (result.edges || []).length,
      p12: result.edge_total ?? '—'
    }));
    const cells = row => `<td>${UI.html(contextNumber(row.baseline_sum))}</td><td>${UI.html(contextNumber(row.intervention_sum))}</td><td>${UI.html(contextNumber(row.sum_delta))}</td><td>${UI.html(contextNumber(row.absolute_sum_delta))}</td><td>${replayPercent(row.relative_sum_delta)}</td>`;
    $('replay_node_rows').innerHTML = (result.nodes || []).map(row => `<tr><td><button class="linkbtn" data-replay-node="${esc(row.body_id)}">${UI.html(replayResult.nodes.find(n => n.body_id === row.body_id)?.annotation?.type || UI.msg("replay.controls.type_fb8761", {}))} · ${UI.html(row.body_id)}</button></td>${cells(row)}</tr>`).join('');
    $('replay_edge_rows').innerHTML = (result.edges || []).map(row => `<tr><td><button class="linkbtn" data-replay-edge="${esc(row.edge_id)}">${UI.html(row.edge_id)}</button></td>${cells(row)}</tr>`).join('');
  } catch (error) {
    if (id === replayResult?.replay_id) {
      UI.text($('replay_summary_status'), UI.errorText(error));
      $('replay_node_rows').replaceChildren();
      $('replay_edge_rows').replaceChildren();
    }
  }
}
async function openReplay(result, saved = true) {
  pauseReplay();
  const sequence = ++replaySequence;
  replayFrameSequence++;
  replayPickSequence++;
  replayResult = replayClone(result);
  replayFrame = null;
  replayTopologyId = null;
  replayOutputId = null;
  replaySelected.clear();
  replaySelectedNode = null;
  replaySelectedEdge = null;
  $('replay_area').open = true;
  $('replay_view').hidden = false;
  UI.text($('replay_source_info'), UI.msg("replay.openReplay.scope_intervention_8597f0", {
    p0: saved ? UI.msg("replay.openReplay.save_replay_c8ef39", {}) : UI.msg("replay.openReplay.prepare_replay_76b7f7", {}),
    p1: result.config.case_id,
    p2: result.config.experiment.intervention_ids?.join(', ') || UI.msg("replay.openReplay.save_330fb0", {})
  }));
  replayCounts(result);
  setReplayWindows(result);
  const display = result.display || {};
  const invalidSelection = (display.selected_nodes || []).filter(id => !result.nodes.some(n => n.body_id === id));
  for (const id of display.selected_nodes || []) if (!invalidSelection.includes(id)) replaySelected.add(id);
  if (window.analysisSelection) replaySelected = new Set(window.analysisSelection.ids());
  $('replay_add_selection').disabled = !replaySelected.size;
  $('replay_mode').value = ['baseline', 'intervention', 'delta'].includes(display.mode) ? display.mode : 'delta';
  $('replay_scrub').max = String(Math.max(0, result.time_steps.length - 1));
  const index = Math.max(0, result.time_steps.indexOf(display.state_step));
  $('replay_save').disabled = saved;
  $('replay_detail').replaceChildren();
  $('replay_node_chart').replaceChildren();
  $('replay_node_rows').replaceChildren();
  $('replay_edge_rows').replaceChildren();
  UI.text($('replay_summary_status'), '');
  replayStatus(UI.msg("replay.openReplay.play_recorded_state_steps_b2aab4", {
    p0: saved ? UI.msg("replay.openReplay.open_76ef4b", {}) : UI.msg("replay.openReplay.complete_7a3adc", {}),
    p1: result.time_steps.length
  }));
  await readReplayFrame(index);
  if (sequence !== replaySequence) return;
  if (display.selected_node && result.nodes.some(n => n.body_id === display.selected_node)) await selectReplayNode(display.selected_node, false, !Array.isArray(display.selected_nodes));else if (display.selected_edge && result.edges.some(e => e.edge_id === display.selected_edge)) await selectReplayEdge(display.selected_edge, false);
  if (sequence !== replaySequence) return;
  if (invalidSelection.length) replayStatus(UI.join([UI.msg("replay.openReplay.save_select_node_1c7e6a", {}), invalidSelection.join(', ')]), true);
  if (saved) $('replay_save').disabled = true;
}
function sendReplaySelection() {
  if (busy) throw UI.error("replay.sendReplaySelection.stop_b3daa7", {});
  const ids = [...replaySelected],
    allowed = new Set(candidateNodes('__all__').map(node => node.bodyId));
  if (!ids.length) throw UI.error("replay.sendReplaySelection.replaynode_9a683d", {});
  const missing = ids.filter(id => !allowed.has(id));
  if (missing.length) throw UI.errorValue(UI.join([UI.msg("replay.sendReplaySelection.node_intervention_d9962a", {}), missing.join(', ')]));
  const combined = [...new Set([...($('selection_mode').value === 'ids' ? currentSelectionIds() : []), ...ids])];
  $('intervention_group').value = '__all__';
  $('selection_mode').value = 'ids';
  $('selection_ids').value = combined.join(', ');
  changed();
  replayStatus(UI.join([UI.join([UI.msg("replay.sendReplaySelection.current_intervention_set_10f656", {}), ids.join(', ')]), UI.msg("replay.sendReplaySelection.not_run_b1872f", {})]));
}
$('replay_sources_refresh').onclick = () => {
  refreshReplaySources();
  $('replay_area').open = true;
  replayStatus(replaySources.length ? UI.msg("replay.controls.choose_an_existing_result_condition_0aa62a", {}) : UI.msg("replay.controls.run_save_479b4b", {}));
};
$('replay_source').onchange = () => selectReplaySource($('replay_source').value);
for (const [id, all] of [['replay_use_path', false], ['replay_use_path_all', true]]) $(id).onclick = () => {
  try {
    const ids = all ? (pathwayResult?.nodes || []).map(n => n.bodyId) : selectedRows('path_nodes_rows');
    if (!ids.length) throw UI.error("replay.controls.find_paths_selectnode_f04879", {});
    $('replay_ids').value = ids.join(', ');
    invalidateReplayRequest();
  } catch (error) {
    replayStatus(UI.errorText(error), true);
  }
};
for (const id of ['replay_ids', 'replay_max_nodes', 'replay_max_edges', 'replay_stride', 'replay_max_bytes']) $(id).addEventListener('input', invalidateReplayRequest);
$('replay_preview').onclick = previewReplay;
$('replay_prepare').onclick = prepareReplay;
$('replay_cancel').onclick = async () => {
  try {
    if (replayJob) await api('/api/cancel-replay', {
      job_id: replayJob
    });
    replayStatus(UI.msg("replay.controls.cancel_preparation_06122b", {}));
  } catch (error) {
    replayStatus(UI.errorText(error), true);
  }
};
$('replay_mode').onchange = () => renderReplayGraph();
$('replay_scrub').oninput = () => {
  pauseReplay();
  readReplayFrame(Number($('replay_scrub').value));
};
$('replay_previous').onclick = () => {
  if (replayResult?.ready) $('replay_save').disabled = busy;
  pauseReplay();
  readReplayFrame(Number($('replay_scrub').value) - 1);
};
$('replay_next').onclick = () => {
  if (replayResult?.ready) $('replay_save').disabled = busy;
  pauseReplay();
  readReplayFrame(Number($('replay_scrub').value) + 1);
};
$('replay_play').onclick = () => {
  if (replayPlaying) {
    pauseReplay();
    return;
  }
  if (!replayResult?.ready) return;
  $('replay_save').disabled = busy;
  UI.text($('replay_play'), UI.msg("replay.controls.pause_8d12fc", {}));
  replayPlaying = setInterval(() => {
    const next = Number($('replay_scrub').value) + 1;
    if (next >= replayResult.time_steps.length) {
      pauseReplay();
      return;
    }
    readReplayFrame(next);
  }, 450);
};
$('replay_summary').onclick = summarizeReplay;
$('replay_window').onchange = () => {
  $('replay_node_rows').replaceChildren();
  $('replay_edge_rows').replaceChildren();
  UI.text($('replay_summary_status'), UI.msg("replay.controls.window_3f03a5", {}));
};
$('replay_add_selection').onclick = () => {
  try {
    sendReplaySelection();
  } catch (error) {
    replayStatus(UI.errorText(error), true);
  }
};
$('replay_node_details').onclick = () => {
  if (replaySelectedNode) showNode(replaySelectedNode);
};
$('replay_save').onclick = async () => {
  const result = replayResult, sequence = replaySequence;
  try {
    if (!replayResult?.ready) throw UI.error("replay.controls.replay_c23049", {});
    const saved = await api('/api/save-replay', {
      replay_id: replayResult.replay_id,
      display: {
        mode: $('replay_mode').value,
        state_step: replayStateStep(),
        selected_node: replaySelectedNode,
        selected_nodes: [...replaySelected],
        selected_edge: replaySelectedEdge,
        window: replayWindow()
      }
    });
    if (result !== replayResult || sequence !== replaySequence) return;
    replayStatus(UI.join([UI.msg("replay.controls.replay_save_1f3711", {}), saved.folder]));
    document.dispatchEvent(new Event('lab-saved'));
  } catch (error) {
    if (result === replayResult && sequence === replaySequence) replayStatus(UI.errorText(error), true);
  }
};
document.addEventListener('click', event => {
  const node = event.target.closest('[data-replay-node]'),
    edge = event.target.closest('[data-replay-edge]');
  if (node) selectReplayNode(node.dataset.replayNode, event.shiftKey);else if (edge) selectReplayEdge(edge.dataset.replayEdge);
});
document.addEventListener('keydown', event => {
  const target = event.target.closest('[data-replay-node],[data-replay-edge]');
  if (target && ['Enter', ' '].includes(event.key)) {
    event.preventDefault();
    if (target.dataset.replayNode) selectReplayNode(target.dataset.replayNode, event.shiftKey);else if (target.dataset.replayEdge) selectReplayEdge(target.dataset.replayEdge);
  }
});
document.addEventListener('lab-artifact-open', event => {
  if (['run', 'comparison'].includes(event.detail.kind)) {
    replayArtifact = replayClone(event.detail);
    refreshReplaySources();
  }
});
document.addEventListener('lab-replay-open', async event => {
  await openReplay(event.detail.result, true);
  refreshReplaySources({
    kind: 'replay',
    replay_id: replayResult.replay_id
  });
  selectReplaySource($('replay_source').value);
  $('replay_view').hidden = false;
});
document.addEventListener('lab-case', () => {
  pauseReplay();
  replaySequence++;
  replayFrameSequence++;
  replayPickSequence++;
  replaySource = null;
  replayArtifact = null;
  replayResult = null;
  replayFrame = null;
  replayPreview = null;
  replayJob = null;
  replaySelected.clear();
  replaySelectedNode = null;
  replaySelectedEdge = null;
  replayTopology?.destroy();
  replayTopology = null;
  window.replayTopology = null;
  replayTopologyId = null;
  $('replay_view').hidden = true;
  UI.text($('replay_counts'), '');
  UI.text($('replay_source_info'), '');
  $('replay_source').innerHTML = `<option value="" data-i18n="replay.controls.select_an_existing_result_f83e28">${UI.t("replay.controls.select_an_existing_result_f83e28")}</option>`;
  for (const id of ['replay_prepare', 'replay_cancel', 'replay_save']) $(id).disabled = true;
  replayStatus('');
});
async function enterReplay(kind = null) {
  refreshReplaySources();
  let index = -1;
  if (!kind && isBatchCurves(curveSource)) {
    const k = Number($('signal_condition').value) || 0,
      name = comparison?.conditions?.[k]?.name || comparison?.rows?.[k]?.name;
    index = replaySources.findIndex(s => ['comparison', 'artifact'].includes(s.source.kind) && s.source.condition_name === name);
  }
  if (index < 0) index = replaySources.findIndex(s => kind ? s.source.kind === kind : ['run', 'comparison', 'artifact'].includes(s.source.kind));
  if (index < 0) {
    $('replay_area').open = true;
    replayStatus(UI.msg("replay.enterReplay.select_complete_save_84c577", {}), true);
    return;
  }
  $('replay_source').value = String(index);
  await selectReplaySource(String(index));
  $('pathway_panel').scrollIntoView({
    block: 'start'
  });
}
$('replay_enter_result').onclick = () => enterReplay();
$('replay_enter_timing').onclick = () => enterReplay('timing');
if ($('replay_enter_joint')) $('replay_enter_joint').onclick = () => enterReplay('joint');
const renderComparisonBeforeReplay = renderComparison;
renderComparison = function (result, saved = false, displayOnly = false) {
  renderComparisonBeforeReplay(result, saved, displayOnly);
  if(typeof renderComparisonUsability==='function')return;
  if (result.comparison_id) for (const [k, row] of [...$('comparison_rows').querySelectorAll('tr')].entries()) {
    const button = document.createElement('button');
    button.className = 'linkbtn';
    UI.text(button, UI.msg("replay.controls.result_analysis_6e6a12", {}));
    button.onclick = () => {
      refreshReplaySources();
      const name = result.conditions?.[k]?.name || result.rows[k].name,
        index = replaySources.findIndex(s => s.source.comparison_id === result.comparison_id && s.source.condition_name === name);
      if (index >= 0) {
        $('replay_source').value = String(index);
        selectReplaySource(String(index));
        $('pathway_panel').scrollIntoView({
          block: 'start'
        });
      }
    };
    row.lastElementChild.append(button);
  }
};
for (const id of ['replay_mode', 'replay_window', 'replay_scrub']) $(id).addEventListener('input', () => {
  if (replayResult?.ready && !busy) $('replay_save').disabled = false;
});
document.addEventListener('lab-analysis-selection', event => {
  const available = new Set((overview?.scope_nodes || []).map(n => String(n.bodyId)));
  replaySelected = new Set((event.detail.ids || []).filter(id => available.has(id)));
  if (replayTopology) replayTopology.setSelection([...replaySelected], event.detail.focus || replaySelectedNode);
  $('replay_add_selection').disabled = !replaySelected.size;
});
function captureReplayDisplay() {
  return replayResult ? {
    mode: $('replay_mode').value,
    state_step: replayStateStep(),
    selected_node: replaySelectedNode,
    selected_edge: replaySelectedEdge,
    window: replayWindow(),
    topology: replayTopology?.exportState()
  } : null;
}
async function restoreReplayDisplay(display) {
  if (!display || !replayResult?.ready) return;
  pauseReplay();
  if (['baseline', 'intervention', 'delta'].includes(display.mode)) $('replay_mode').value = display.mode;
  if (display.window) {
    let key = [...replayWindows].find(([key, value]) => value.start === display.window.start && value.stop === display.window.stop)?.[0];
    if (!key) {
      key = 'session';
      replayWindows.set(key, {
        ...display.window
      });
      const option = document.createElement('option');
      option.value = key;
      UI.text(option, UI.msg("replay.restoreReplayDisplay.window_ab348a", {
        p0: display.window.start,
        p1: display.window.stop
      }));
      $('replay_window').appendChild(option);
    }
    $('replay_window').value = key;
  }
  await readReplayFrame(Math.max(0, replayResult.time_steps.indexOf(display.state_step)));
  if (display.selected_node && replayResult.nodes.some(n => n.body_id === display.selected_node)) await selectReplayNode(display.selected_node, false, false);else if (display.selected_edge && replayResult.edges.some(e => e.edge_id === display.selected_edge)) await selectReplayEdge(display.selected_edge, false);
  replayTopology?.importState(display.topology);
}

for(const event of ['ui-language','ui-theme','ui-fonts'])document.addEventListener(event,()=>{if(replayResult?.ready){replayOutputId=null;renderReplayOutput();}});
