"use strict";

const $ = id => document.getElementById(id),
  roles = {
    input: UI.msg("page.labels.input_sets_d6f1d2", {}),
    internal: UI.msg("page.labels.candidate_sets_dd7a3d", {}),
    output: UI.msg("page.labels.observation_sets_32d048", {}),
    context: UI.msg("page.labels.message_6fc38e", {})
  };
let overview,
  latest = null,
  dirty = false,
  busy = false,
  caseGeneration = 0,
  localToken = null,
  workspaceState = null;
let conditions = [],
  comparison = null,
  comparisonView = null,
  comparisonSavingId = null;
const esc = s => String(s ?? '—').replace(/[&<>"']/g, c => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
})[c]);
const num = n => UI.numeric(Number(n)),
  fmt = n => UI.value(n);
function status(s, error = false) {
  UI.text($('status'), s);
  $('status').classList.toggle('error', error);
}
async function api(path, data) {
  const opt = data === undefined ? {} : {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Local-Token': localToken || overview?.token || '',
      ...(overview?.manifest?.case_id ? {
        'X-Case-Id': overview.manifest.case_id
      } : {})
    },
    body: JSON.stringify(data)
  };
  const res = await fetch(path, opt),
    body = await res.json();
  if (!res.ok) throw UI.apiError(body);
  return body;
}
function options(id, values, all = false) {
  $(id).replaceChildren();
  for (const value of [...(all ? ['__all__'] : []), ...values]) {
    const o = document.createElement('option');
    o.value = value;
    UI.text(o, value === '__all__' ? UI.msg("page.options.all_defined_sets_006101") : value);
    if (value === '__all__') o.dataset.i18n = "text.006101ccd648";else o.dataset.userText = 'true';
    $(id).append(o);
  }
}
function cfg() {
  const c = {};
  for (const name of ['steps', 'alpha', 'rho', 'input_start', 'input_stop', 'amplitude', 'intervention_start', 'intervention_stop', 'gain']) c[name] = Number($(name).value);
  c.input_group = $('input_group').value;
  c.intervention_group = $('intervention_group').value;
  c.outputs = [$('output_a').value, $('output_b').value];
  c.intervention_ids = $('selection_mode').value === 'all' ? null : $('selection_ids').value.trim().split(/[\s,，]+/).filter(Boolean);
  return c;
}
function validateCondition(c) {
  c = {
    intervention_ids: null,
    ...c
  };
  if (!c || typeof c !== 'object' || Object.keys(c).sort().join('|') !== Object.keys(overview.defaults).sort().join('|')) throw UI.error("page.validateCondition.condition_edb0d7", {});
  for (const name of ['steps', 'input_start', 'input_stop', 'intervention_start', 'intervention_stop']) if (!Number.isInteger(c[name])) throw UI.errorValue(UI.join([name, UI.msg("page.validateCondition.message_0cea83", {})]));
  if (c.steps < 1 || c.steps > 2000) throw UI.error("page.validateCondition.1_2000_c4209c", {});
  for (const prefix of ['input', 'intervention']) if (!(0 <= c[prefix + '_start'] && c[prefix + '_start'] < c[prefix + '_stop'] && c[prefix + '_stop'] <= c.steps)) throw UI.error("page.validateCondition.scope_7ccde6", {});
  for (const [name, min] of [['alpha', .001], ['rho', 0], ['amplitude', 0], ['gain', 0]]) if (typeof c[name] !== 'number' || !Number.isFinite(c[name]) || c[name] < min || c[name] > 1) throw UI.errorValue(UI.join([name, UI.msg("page.validateCondition.scope_3bbd98", {})]));
  for (const [name, role] of [['input_group', 'input'], ['intervention_group', 'internal']]) if (c[name] !== '__all__' && !overview.groups[role].includes(c[name])) throw UI.error("page.validateCondition.condition_7b50e4", {});
  if (c.intervention_ids !== null) {
    const allowed = new Set(candidateNodes(c.intervention_group).map(n => n.bodyId));
    if (!Array.isArray(c.intervention_ids) || !c.intervention_ids.length || new Set(c.intervention_ids).size !== c.intervention_ids.length || c.intervention_ids.some(id => typeof id !== 'string' || !allowed.has(id))) throw UI.error("page.validateCondition.node_set_body_id_b3acbd", {});
  }
  if (!Array.isArray(c.outputs) || c.outputs.length !== 2 || c.outputs[0] === c.outputs[1] || c.outputs.some(s => !overview.groups.output.includes(s))) throw UI.error("page.validateCondition.select_an_item_a77f30", {});
}
function apply(c) {
  c = {
    intervention_ids: null,
    ...c
  };
  validateCondition(c);
  for (const [key, value] of Object.entries(c)) {
    if (key === 'outputs') {
      $('output_a').value = value[0];
      $('output_b').value = value[1];
    } else if ($(key)) $(key).value = value;
  }
  $('selection_mode').value = c.intervention_ids === null ? 'all' : 'ids';
  $('selection_ids').value = (c.intervention_ids || []).join(', ');
  refreshValues();
  refreshSelection();
}
function refreshValues() {
  UI.text($('gain_value'), Math.round(Number($('gain').value) * 100) + '%');
  UI.text($('amplitude_value'), Number($('amplitude').value).toFixed(2));
}
function changed() {
  if (typeof invalidateInterventionPreview === 'function') invalidateInterventionPreview();
  conditionFeedback('');
  dirty = true;
  refreshValues();
  refreshSelection();
  $('save').disabled = true;
  UI.text($('resultstate'), latest ? UI.msg("page.changed.condition_46f19b", {}) : UI.msg("page.changed.pending_a92ef9", {}));
}
function plot(b, i, c) {
  const W = 470,
    H = 226,
    l = 65,
    r = 16,
    t = 15,
    bot = 38,
    max = Math.max(...b, ...(i || [])) * 1.15 || 1;
  const px = n => l + n / (b.length - 1) * (W - l - r),
    py = n => H - bot - n / max * (H - t - bot);
  let out = `<svg class="plot" viewBox="0 0 ${W} ${H}" role="img" ${UI.htmlAttribute("aria-label", "page.plot.baseline_intervention_c40ccd", {})}>`;
  for (const [start, end, color] of [[c.input_start, c.input_stop, UI.color('teal')], [c.intervention_start, c.intervention_stop, UI.color('amber')]]) out += `<rect x="${px(start + .5)}" y="${t}" width="${px(end + .5) - px(start + .5)}" height="${H - t - bot}" fill="${color}" opacity=".06"/>`;
  for (let k = 0; k <= 4; k++) {
    const y = py(max * k / 4);
    out += `<line x1="${l}" x2="${W - r}" y1="${y}" y2="${y}" stroke="var(--chart-grid)"/><text x="${l - 8}" y="${y + 4}" text-anchor="end" fill="var(--muted)" font-size="12">${UI.html(fmt(max * k / 4), true)}</text>`;
    const v = Math.round(c.steps * k / 4);
    out += `<text x="${px(v)}" y="${H - bot + 19}" text-anchor="middle" fill="var(--muted)" font-size="12">${UI.html(v)}</text>`;
  }
  for (const [arr, color] of [[b, UI.color('baseline')], [i, UI.color('intervention')]].filter(([arr]) => arr)) out += `<polyline points="${arr.map((v, k) => px(k) + ',' + py(v)).join(' ')}" stroke="${color}" stroke-width="2.4" fill="none"/>`;
  out += `<text x="${l}" y="${H - 2}" fill="var(--muted)" font-size="12">${UI.svgText("page.plot.mean_activity_model_units_6c4900", {})}</text><text x="${W - r}" y="${H - 2}" fill="var(--muted)" font-size="12" text-anchor="end">${UI.svgText("page.plot.state_step_ebe1ee", {})}</text></svg>`;
  return out;
}
function renderResult(r) {
  const c = r.config.experiment,
    forwardOnly = r.kind === 'forward';
  $('charts').innerHTML = r.summary.map(s => {
    const v = r.series[s.type],
      delta = s.relative_sum_delta;
    return `<section class="panel chart"><div class="charttop"><div><button class="linkbtn" data-output="${esc(s.type)}" style="font-size:16px;font-weight:600">${UI.html(s.type)}</button><div class="hint">${UI.htmlText("page.controls.node_d2f3cd", {
      p0: UI.numeric(s.node_count, {}),
      p1: forwardOnly ? UI.msg("page.controls.response_sum_651711", {}) : UI.msg("page.controls.response_sum_change_c60870", {})
    })}</div></div><div class="change">${UI.html(forwardOnly ? fmt(s.baseline_sum) : delta === null ? UI.msg("page.controls.no_baseline_response_dca6a4", {}) : (delta > 0 ? '+' : '') + (100 * delta).toFixed(1) + '%')}</div></div>${plot(v.baseline, v.intervention, c)}<div class="stats"><div><span>${UI.htmlText("page.controls.baseline_peak_1ab69f", {})}</span><b>${UI.htmlNumber(UI.numeric(s.baseline_peak, {
      maximumSignificantDigits: 4
    }), false)}</b></div><div><span>${UI.html(forwardOnly ? UI.msg("page.controls.final_state_response_8ab619", {}) : UI.msg("page.controls.intervention_peak_92bb03", {}))}</span><b>${UI.htmlNumber(UI.numeric(forwardOnly ? s.final_response : s.intervention_peak, {
      maximumSignificantDigits: 4
    }), false)}</b></div><div><span>${UI.html(forwardOnly ? UI.msg("page.controls.response_sum_651711", {}) : UI.msg("page.controls.sum_difference_6005c7", {}))}</span><b>${UI.htmlNumber(UI.numeric(forwardOnly ? s.baseline_sum : s.sum_delta, {
      maximumSignificantDigits: 4
    }), false)}</b></div><div><span>${UI.htmlText("page.controls.vertical_axis_957dd0", {})}</span><b class="hint">${UI.htmlText("page.controls.independent_scale_9b2d30", {})}</b></div></div></section>`;
  }).join('');
  $('deltas').innerHTML = (r.node_deltas || []).slice(0, 100).map(n => `<tr><td>${idButton(n.bodyId)}</td><td>${UI.html(n.type)}</td><td>${UI.html(fmt(n.baseline_peak))}</td><td>${UI.html(fmt(n.intervention_peak))}</td><td>${UI.html(fmt(n.sum_delta))}</td></tr>`).join('');
  UI.text($('resultstate'), UI.msg("page.renderResult.interventionnode_intervention_recorded_nodes_e02679", {
    p0: UI.numeric(Number(r.elapsed_seconds), {
      minimumFractionDigits: 3,
      maximumFractionDigits: 3
    }),
    p1: UI.numeric(r.computation_node_count ?? overview.manifest.node_count, {}),
    p2: UI.numeric(r.input_node_count, {}),
    p3: UI.numeric(r.intervention_node_count, {}),
    p4: UI.numeric(r.intervention_edge_count ?? 0, {}),
    p5: UI.numeric(r.recording_metadata?.node_count ?? 0, {})
  }));
  options('signal_output', c.outputs);
  renderSignals();
  document.dispatchEvent(new Event('lab-result'));
}
async function run() {
  if (busy) return;
  if (!$('experiment').reportValidity()) return;
  const requested = cfg();
  let recording;
  try {
    validateCondition(requested);
    recording = recordingPolicy();
  } catch (e) {
    status(UI.errorText(e), true);
    return;
  }
  dirty = !latest || Object.keys(requested).some(k => JSON.stringify(requested[k]) !== JSON.stringify(latest.config.experiment[k])) || ['mode', 'body_ids', 'step_stride', 'steps', 'max_bytes'].some(k => JSON.stringify(recording[k] ?? null) !== JSON.stringify(latest.config.recording?.[k] ?? null));
  busy = true;
  $('run').disabled = true;
  $('baseline').disabled = true;
  $('load').disabled = true;
  $('export').disabled = true;
  $('experiment').classList.add('busy');
  $('save').disabled = true;
  status(UI.msg("page.run.message_e1fa1b", {}));
  $('experiment').inert = true;
  try {
    const r = await api('/api/run', {
      experiment: requested,
      recording
    });
    latest = r;
    dirty = JSON.stringify(cfg()) !== JSON.stringify(requested) || JSON.stringify(recordingPolicy()) !== JSON.stringify(recording);
    renderResult(r);
    $('save').disabled = dirty;
    if (dirty) UI.text($('resultstate'), UI.join([UI.currentText($('resultstate')), UI.msg("page.run.condition_e45330", {})]));
    status(dirty ? UI.msg("page.run.condition_b5d0e0", {}) : UI.msg("page.run.comparisoncomplete_16db80", {}));
    setEdge('edge_source', 'internal', Array.isArray(r.config.experiment.intervention_events) ? '__all__' : r.config.experiment.intervention_group);
    if (overview.groups.output.includes(r.summary[0].type)) {
      setEdge('edge_target', 'output', r.summary[0].type);
      await loadEdges();
    }
  } catch (e) {
    status(UI.errorText(e), true);
  } finally {
    busy = false;
    $('save_comparison').disabled = !canSaveComparison();
    $('save').disabled = !latest || dirty;
    $('run').disabled = false;
    $('baseline').disabled = false;
    $('load').disabled = false;
    $('export').disabled = false;
    $('experiment').classList.remove('busy');
    $('experiment').inert = false;
    spatialSelection();
  }
}
function idButton(id) {
  return `<button class="linkbtn" data-id="${esc(id)}">${UI.html(id)}</button>`;
}
function fillEdgeSelect(id) {
  $(id).replaceChildren();
  for (const [role, labels] of Object.entries(overview.groups)) {
    const group = document.createElement('optgroup');
    UI.attr(group, 'label', roles[role]);
    for (const label of ['__all__', ...labels]) {
      const o = document.createElement('option');
      o.value = JSON.stringify([role, label]);
      UI.text(o, label === '__all__' ? UI.join([roles[role], UI.msg("page.fillEdgeSelect.all_55864d", {})]) : label);
      group.append(o);
    }
    $(id).append(group);
  }
}
function setEdge(id, role, label) {
  $(id).value = JSON.stringify([role, label]);
}
let edgeSequence = 0;
async function loadEdges() {
  const seq = ++edgeSequence,
    [sr, s] = JSON.parse($('edge_source').value),
    [tr, t] = JSON.parse($('edge_target').value);
  try {
    const q = new URLSearchParams({
      source_role: sr,
      source: s,
      target_role: tr,
      target: t
    });
    const d = await api('/api/connections?' + q);
    if (seq !== edgeSequence) return;
    UI.text($('edgesummary'), UI.msg("page.loadEdges.node_node_connection_count_9aa57d", {
      p0: d.source_node_count,
      p1: d.target_node_count,
      p2: UI.numeric(d.edge_count, {}),
      p3: UI.numeric(d.contacts, {})
    }));
    $('edges').innerHTML = d.edges.length ? d.edges.map(e => `<tr><td>${idButton(e.body_pre)}</td><td>${idButton(e.body_post)}</td><td>${UI.html(e.pre_type)}</td><td>${UI.html(e.post_type)}</td><td>${UI.htmlNumber(UI.numeric(e.weight, {}), false)}</td><td>${(e.normalized_weight * 100).toFixed(3)}% <button class="small" data-operation-edge="${esc(JSON.stringify([e.body_pre, e.body_post]))}">${UI.htmlText("page.controls.create_edge_event_f1e789", {})}</button></td></tr>`).join('') : `<tr><td colspan="6">${UI.htmlText("page.loadEdges.no_connection_1f1a28", {})}</td></tr>`;
  } catch (e) {
    if (seq === edgeSequence) status(UI.errorText(e), true);
  }
}
async function showNode(id) {
  const generation = caseGeneration;
  try {
    const d = await api('/api/node?' + new URLSearchParams({
        id
      })),
      n = d.node;
    if (generation !== caseGeneration) return;
    focusGeometry(id, d);
    UI.text($('nodetitle'), `${n.group_label} · body ID ${n.bodyId}`);
    const keys = {
      bodyId: UI.msg("page.showNode.id_84e559", {}),
      type: UI.msg("page.showNode.type_400657", {}),
      class: UI.msg("page.showNode.class_a96748", {}),
      somaSide: UI.msg("page.showNode.message_0f783c", {}),
      instance: 'instance',
      status: 'status',
      statusLabel: 'statusLabel',
      total_input: UI.msg("page.showNode.input_contacts_a6abcc", {}),
      external_input: UI.msg("page.showNode.input_contacts_385127", {}),
      total_output: UI.msg("page.showNode.output_contacts_25997f", {}),
      external_output: UI.msg("page.showNode.output_contacts_8bfe35", {}),
      internal_input_fraction: UI.msg("page.showNode.message_1c2e96", {})
    };
    $('nodedetail').innerHTML = '<div class="annotation">' + Object.entries(keys).map(([key, label]) => `<div><span>${UI.html(label)}</span><b>${UI.html(key === 'internal_input_fraction' ? (100 * n[key]).toFixed(2) + '%' : n[key])}</b></div>`).join('') + '</div>' + [['incoming', UI.msg("page.showNode.internal_inputs_20_7b0a35", {})], ['outgoing', UI.msg("page.showNode.20_276644", {})]].map(([key, title]) => `<h3>${UI.html(title)}</h3><div class="tablewrap" style="max-height:210px"><table><thead><tr><th>${UI.htmlText("page.controls.adjacent_body_ids_200fa9", {})}</th><th>${UI.htmlText("page.controls.type_ba4001", {})}</th><th>${UI.htmlText("page.controls.connection_count_93e376", {})}</th></tr></thead><tbody>${d[key].map(e => `<tr><td>${idButton(e.node.bodyId)}</td><td>${UI.html(e.node.group_label)}</td><td>${UI.html(num(e.weight))}</td></tr>`).join('')}</tbody></table></div>`).join('');
    if (!$('nodeDialog').open) $('nodeDialog').showModal();
  } catch (e) {
    status(UI.errorText(e), true);
  }
}
$('experiment').addEventListener('submit', e => {
  e.preventDefault();
  run();
});
$('experiment').addEventListener('input', changed);
$('baseline').onclick = () => {
  $('gain').value = 1;
  refreshValues();
  run();
};
$('edge_source').onchange = loadEdges;
$('edge_target').onchange = loadEdges;
$('closeDialog').onclick = () => $('nodeDialog').close();
document.addEventListener('click', e => {
  if (e.target.dataset.id) showNode(e.target.dataset.id);
  if (e.target.dataset.output && activeSignalResult()?.signals) {
    $('signal_output').value = e.target.dataset.output;
    renderSignals();
    $('signal_panel').scrollIntoView({
      block: 'start',
      behavior: 'smooth'
    });
    setEdge('edge_source', 'internal', Array.isArray(activeSignalResult().config.experiment.intervention_events) ? '__all__' : activeSignalResult().config.experiment.intervention_group);
    if (overview.groups.output.includes(e.target.dataset.output)) {
      setEdge('edge_target', 'output', e.target.dataset.output);
      loadEdges();
    }
  }
  if (e.target.dataset.relation) {
    const [s, t] = JSON.parse(e.target.dataset.relation);
    setEdge('edge_source', s, '__all__');
    setEdge('edge_target', t, '__all__');
    loadEdges();
  }
});
$('export').onclick = async () => {
  if (busy) return;
  try {
    validateCondition(cfg());
    $('export').disabled = true;
    const d = await api('/api/export', cfg());
    if (!busy) status(UI.join([UI.msg("page.controls.condition_10cd04", {}), d.path]));
    document.dispatchEvent(new Event('lab-saved'));
  } catch (e) {
    if (!busy) status(UI.errorText(e), true);
  } finally {
    $('export').disabled = busy;
  }
};
$('load').onclick = () => $('loadfile').click();
$('loadfile').onchange = async () => {
  const file = $('loadfile').files[0];
  if (!file) return;
  try {
    if (file.size > 1048576) throw UI.error("page.controls.condition_1_mib_39bba4", {});
    const data = JSON.parse(await file.text());
    if (busy) throw UI.error("page.controls.stop_load_condition_c45c9d", {});
    if (data.case_id !== overview.manifest.case_id || data.model_version !== overview.model_version) throw UI.error("page.controls.condition_ee4c48", {});
    if (data.conditions) {
      loadConditions(data.conditions);
      status(UI.msg("page.controls.compare_conditionsloaded_pending_ad0c2d", {}));
    } else {
      apply(data.experiment);
      applyRecording(data.recording);
      changed();
      status(UI.msg("page.controls.conditionloaded_pending_78fe92", {}));
    }
  } catch (e) {
    status(UI.errorText(e), true);
  } finally {
    $('loadfile').value = '';
  }
};
$('save').onclick = async () => {
  if (busy || !latest || dirty) return;
  $('save').disabled = true;
  try {
    const d = await api('/api/save', {
      run_id: latest.run_id
    });
    if (!busy) status(UI.join([UI.msg("page.controls.save_node_e11e20", {}), d.folder]));
    document.dispatchEvent(new Event('lab-saved'));
  } catch (e) {
    if (!busy) status(UI.errorText(e), true);
  } finally {
    $('save').disabled = busy || dirty;
  }
};
function candidateNodes(group) {
  return (overview?.internal_nodes || []).filter(n => group === '__all__' || (n.groups || n.memberships?.internal || [n.type]).includes(group));
}
function activateOverview(next) {
  localToken = next.token || localToken;
  $('scope_workspace').hidden = false;
  caseGeneration++;
  edgeSequence++;
  focusSequence++;
  activitySequence++;
  overview = next;
  latest = null;
  dirty = false;
  conditions = [];
  comparison = null;
  comparisonView = null;
  searchJob = null;
  searchResult = null;
  focusNode = null;
  activityRows = [];
  geometryData = null;
  const m = overview.manifest;
  UI.text($('active_case'), UI.msg("page.activateOverview.scope_node_internal_edges_62b27b", {
    p0: m.case_name,
    p1: UI.numeric(m.node_count, {}),
    p2: UI.numeric(m.scan?.internal_edges ?? m.internal_edges ?? 0, {})
  }));
  $('metrics').innerHTML = [[UI.msg("page.activateOverview.compute_nodes_d8bfe4", {}), num(m.node_count)], [UI.msg("page.activateOverview.message_9baadd", {}), num(m.scan?.internal_edges ?? m.internal_edges ?? 0)], [UI.msg("page.activateOverview.connection_count_f6a32e", {}), num(m.internal_contacts)], [UI.msg("page.activateOverview.omitted_inputs_0353ea", {}), (100 * (m.external_input_contacts || 0) / (m.total_input_contacts || 1)).toFixed(1) + '%']].map(([label, value]) => `<div class="metric"><span>${UI.html(label)}</span><b>${value}</b></div>`).join('');
  options('input_group', overview.groups.input, true);
  options('intervention_group', overview.groups.internal, true);
  options('output_a', overview.groups.output);
  options('output_b', overview.groups.output);
  apply(overview.defaults);
  for (const id of ['edge_source', 'edge_target']) fillEdgeSelect(id);
  setEdge('edge_source', 'internal', overview.defaults.intervention_group);
  setEdge('edge_target', 'output', overview.defaults.outputs[0]);
  $('flow').innerHTML = ['input', 'internal', 'output'].map((role, i) => `${i ? '<span class="arrow">→</span>' : ''}<div class="flowbox"><span>${roles[role]}</span><b>${UI.htmlNumber(UI.numeric(m.roles?.[role] ?? 0, {}), false)}</b><small>${UI.htmlText("page.controls.sets_b9c599", {
    p0: overview.groups[role].length
  })}</small></div>`).join('');
  $('relations').innerHTML = (overview.relations || []).map(r => `<tr><td><button class="linkbtn" data-relation='${esc(JSON.stringify([r.source, r.target]))}'>${UI.html(roles[r.source] || r.source)} → ${UI.html(roles[r.target] || r.target)}</button></td><td>${UI.html(num(r.edges))}</td><td>${UI.html(num(r.contacts))}</td></tr>`).join('');
  const fraction = (m.internal_contacts || 0) / (m.total_input_contacts || 1);
  $('boundarybar').style.width = 100 * fraction + '%';
  $('boundarypills').innerHTML = `<span class="pill">${UI.htmlText("page.activateOverview.internal_input_7a7b34", {
    p0: UI.numeric(100 * fraction, {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1
    })
  })}</span><span class="pill">${UI.htmlText("page.activateOverview.omitted_input_178a22", {
    p0: UI.numeric(100 * (1 - fraction), {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1
    })
  })}</span>`;
  $('boundarystats').innerHTML = [[UI.msg("page.activateOverview.internal_input_contacts_d8337a", {}), m.internal_contacts], [UI.msg("page.activateOverview.omitted_external_inputs_3d0149", {}), m.external_input_contacts], [UI.msg("page.activateOverview.complete_input_denominator_sum_449c0c", {}), m.total_input_contacts], [UI.msg("page.activateOverview.omitted_external_outputs_c094ec", {}), m.external_output_contacts]].map(([l, v]) => `<div><span>${UI.html(l)}</span><b>${UI.html(num(v))}</b></div>`).join('');
  $('charts').innerHTML = `<div class="panel empty">${UI.htmlText("page.activateOverview.no_results_dc568b", {})}</div>`;
  UI.text($('resultstate'), UI.msg("page.activateOverview.not_run_7adc85", {}));
  for (const id of ['deltas', 'signal_stats', 'signal_groups', 'signal_nodes', 'signal_edges', 'condition_list', 'comparison_head', 'comparison_rows', 'search_head', 'search_rows', 'sensitivity_head', 'sensitivity_rows', 'edges']) $(id).replaceChildren();
  UI.text($('comparison_status'), UI.msg("page.activateOverview.0_12_conditions_4cfa06", {}));
  UI.text($('search_status'), UI.msg("page.activateOverview.search_not_run_11689d", {}));
  UI.text($('edgesummary'), '');
  UI.text($('geometry_focus'), '');
  $('search_start').disabled = false;
  $('search_cancel').disabled = true;
  $('search_save').disabled = true;
  $('save').disabled = true;
  $('save_comparison').disabled = true;
  $('export').disabled = false;
  $('load').disabled = false;
  spatial.setOverview({
    nodes: []
  });
  spatial.setFocus(null, null, []);
  spatial.setActivity([], 'baseline');
  UI.text($('geometry_status'), UI.msg("page.activateOverview.message_39cb5d", {}));
  $('geometry_time').disabled = true;
  if ($('nodeDialog').open) $('nodeDialog').close();
  status(UI.msg("page.activateOverview.scope_loaded_ready_to_configure_5060b1", {}));
  document.dispatchEvent(new Event('lab-case'));
}
async function init() {
  try {
    const next = await api('/api/case');
    localToken = next.token;
    workspaceState = next.workspace || null;
    if (next.active_case === false) {
      overview = null;
      $('scope_workspace').hidden = true;
      UI.text($('active_case'), UI.msg("page.init.no_scope_selected_01d49f", {}));
      document.dispatchEvent(new CustomEvent('lab-workspace', {
        detail: workspaceState
      }));
    } else activateOverview(next);
  } catch (e) {
    UI.text($('workspace_status'), UI.join([UI.msg("page.init.workspace_failed_199156", {}), UI.errorText(e)]));
    $('workspace_status').classList.add('error');
  }
}
function refreshSelection() {
  if (!overview) return;
  const reference = $('selection_output').value;
  options('selection_output', cfg().outputs);
  if (cfg().outputs.includes(reference)) $('selection_output').value = reference;
  const group = $('intervention_group').value,
    available = candidateNodes(group).length,
    custom = $('selection_mode').value === 'ids';
  $('selection_controls').hidden = !custom;
  $('selection_count').max = available;
  const selected = custom ? cfg().intervention_ids.length : available;
  UI.text($('selection_size'), UI.msg("page.refreshSelection.compute_candidates_intervention_eaeb60", {
    p0: UI.numeric(overview.manifest.node_count, {}),
    p1: UI.numeric(available, {}),
    p2: UI.numeric(selected, {})
  }));
  spatialSelection();
}
$('intervention_group').addEventListener('change', () => {
  $('selection_mode').value = 'all';
  $('selection_ids').value = '';
  changed();
});
async function chooseNodes(method) {
  if (busy) return;
  const snapshot = JSON.stringify(cfg());
  busy = true;
  $('experiment').classList.add('busy');
  $('experiment').inert = true;
  status(UI.msg("page.chooseNodes.node_e6656c", {}));
  try {
    const c = cfg();
    c.intervention_ids = null;
    validateCondition(c);
    const d = await api('/api/select', {
      experiment: c,
      count: Number($('selection_count').value),
      method,
      output: $('selection_output').value
    });
    if (JSON.stringify(cfg()) !== snapshot) throw UI.error("page.chooseNodes.condition_node_cab498", {});
    $('selection_mode').value = 'ids';
    $('selection_ids').value = d.body_ids.join(', ');
    changed();
    status(UI.msg("page.chooseNodes.node_42c61f", {
      p0: d.body_ids.length
    }));
  } catch (e) {
    status(UI.errorText(e), true);
  } finally {
    busy = false;
    $('save_comparison').disabled = !canSaveComparison();
    $('experiment').classList.remove('busy');
    $('experiment').inert = false;
    spatialSelection();
  }
}
$('select_id').onclick = () => chooseNodes('id');
$('select_signal').onclick = () => chooseNodes('signal');
function renderSignals(result = activeSignalResult()) {
  for (const id of ['signal_stats', 'signal_groups', 'signal_nodes', 'signal_edges']) $(id).replaceChildren();
  if (!result?.signals) return;
  const d = result.signals[$('signal_output').value];
  if (!d) return;
  const share = d.baseline_signal > 0 ? 100 * d.selected_baseline_signal / d.baseline_signal : null;
  $('signal_stats').innerHTML = [[UI.msg("page.renderSignals.node_input_contacts_eb811d", {}), (100 * d.selected_input_fraction).toFixed(2) + '%'], [UI.msg("page.renderSignals.node_baseline_incoming_signal_027adb", {}), share === null ? UI.msg("page.renderSignals.message_553dba", {}) : share.toFixed(2) + '%'], [UI.msg("page.renderSignals.baseline_incoming_signal_057963", {}), fmt(d.baseline_signal)], [UI.msg("page.renderSignals.intervention_incoming_signal_349829", {}), fmt(d.intervention_signal)]].map(([l, v]) => `<div><span>${UI.html(l)}</span><b>${UI.html(v)}</b></div>`).join('');
  $('signal_groups').innerHTML = d.groups.map(g => `<tr><td>${UI.html(g.type)}</td><td>${g.node_count}</td><td>${UI.html(num(g.contacts))}</td><td>${UI.html(fmt(g.baseline_signal))}</td><td>${UI.html(fmt(g.intervention_signal))}</td><td>${UI.html(fmt(g.signal_delta))}</td></tr>`).join('');
  $('signal_nodes').innerHTML = d.nodes.slice(0, 100).map(n => `<tr class="${n.selected ? 'selectedrow' : ''}"><td>${idButton(n.bodyId)}</td><td>${UI.html(n.type)}</td><td>${UI.html(n.selected ? UI.msg("page.controls.message_b5141d", {}) : '—')}</td><td>${UI.html(num(n.contacts))}</td><td>${UI.html(fmt(n.baseline_signal))}</td><td>${UI.html(fmt(n.intervention_signal))}</td><td>${UI.html(fmt(n.signal_delta))}</td></tr>`).join('');
  $('signal_edges').innerHTML = d.edges.slice(0, 100).map(e => `<tr><td>${idButton(e.body_pre)}</td><td>${idButton(e.body_post)}</td><td>${UI.html(num(e.contacts))}</td><td>${UI.html(fmt(e.baseline_signal))}</td><td>${UI.html(fmt(e.intervention_signal))}</td></tr>`).join('');
}
$('signal_output').onchange = () => renderSignals();
const protocolKeys = ['steps', 'alpha', 'rho'];
function validateConditions(items) {
  if (!Array.isArray(items) || !items.length || items.length > 12) throw UI.error("page.validateConditions.comparison_1_12_condition_924ee9", {});
  const names = new Set();
  for (const item of items) {
    if (!item || Object.keys(item).sort().join('|') !== 'experiment|name' || typeof item.name !== 'string' || !item.name.trim() || item.name.length > 80 || names.has(item.name)) throw UI.error("page.validateConditions.condition_names_must_be_unique_and_nonempty_227822", {});
    names.add(item.name);
    validateCondition(item.experiment);
    if (protocolKeys.some(k => JSON.stringify(item.experiment[k]) !== JSON.stringify(items[0].experiment[k])) || JSON.stringify(canonicalObservations(item.experiment)) !== JSON.stringify(canonicalObservations(items[0].experiment))) throw UI.error("page.validateConditions.compare_conditions_model_parameters_observation_sets_043d0d", {});
  }
}
function renderConditions() {
  UI.text($('comparison_draft_hint') || $('comparison_status'), UI.msg("page.renderConditions.12_condition_comparison_1edff0", {
    p0: conditions.length
  }));
  $('condition_list').innerHTML = conditions.map((c, k) => {
    const events = c.experiment.intervention_events,
      nodeIds = Array.isArray(events) ? [...new Set(events.filter(e => e.enabled && e.type === 'node_gain').flatMap(e => e.body_ids))] : c.experiment.intervention_ids || candidateNodes(c.experiment.intervention_group).map(n => n.bodyId),
      edges = Array.isArray(events) ? new Set(events.filter(e => e.enabled && e.type === 'edge_gain').flatMap(e => e.edges.map(p => p.join(' → ')))) : new Set();
    return `<details><summary>${UI.htmlText("page.controls.node_1ed095", {
      p0: c.name,
      p1: UI.list(canonicalObservations(c.experiment).map(o => UI.join([UI.join([UI.join([UI.join([UI.join([esc(o.name), UI.msg("page.controls.message_001d89", {})]), o.evaluation_window.start]), ', ']), o.evaluation_window.stop]), ')'])), ' / '),
      p2: nodeIds.length,
      p3: edges.size
    })}<button class="small" data-remove="${k}">${UI.htmlText("page.controls.remove_6135d4", {})}</button></summary><pre style="white-space:pre-wrap">${UI.html(nodeIds.slice(0, 200).join(', '))}${UI.html(nodeIds.length > 200 ? UI.msg("page.controls.200id_f637b6", {}) : '')}${edges.size ? '\n' + esc([...edges].slice(0, 200).join('\n')) : ''}</pre></details>`;
  }).join('');
}
function loadConditions(items) {
  items = items.map(item => ({
    ...item,
    experiment: {
      intervention_ids: null,
      ...item.experiment
    }
  }));
  validateConditions(items);
  conditions = items;
  renderConditions();
}
function conditionFeedback(message, error = false) {
  const target = $('condition_feedback');
  if (!target) return;
  UI.text(target, message);
  target.classList.toggle('error', error);
}
$('add_condition').onclick = () => {
  if (busy) return;
  conditionFeedback('');
  try {
    const c = cfg();
    validateCondition(c);
    let name = $('condition_name').value.trim();
    if (!name) {
      let number=conditions.length+1;
      do { name=UI.t('editor.conditionName',{number:number++}); } while (conditions.some(c=>c.name===name));
    }
    const next = [...conditions, {
        name,
        experiment: c
      }];
    validateConditions(next);
    conditions = next;
    $('condition_name').value = '';
    renderConditions();
  } catch (e) {
    conditionFeedback(UI.errorText(e), true);
    status(UI.errorText(e), true);
  }
};
document.addEventListener('click', async e => {
  if (e.target.dataset.remove !== undefined && !busy) {
    conditions.splice(Number(e.target.dataset.remove), 1);
    renderConditions();
  }
  if (e.target.dataset.inspect !== undefined && !busy && comparison && !comparison.timing_evaluation) {
    const r = comparison.results[Number(e.target.dataset.inspect)];
    apply(r.config.experiment);
    changed();
    await run();
  }
});
$('clear_conditions').onclick = () => {
  if (!busy) {
    conditions = [];
    renderConditions();
  }
};
$('compare_conditions').onclick = async () => {
  if (busy) return;
  try {
    validateConditions(conditions);
  } catch (e) {
    status(UI.errorText(e), true);
    return;
  }
  busy = true;
  $('experiment').classList.add('busy');
  for (const id of ['run', 'baseline', 'load', 'export', 'save', 'compare_conditions', 'save_comparison']) $(id).disabled = true;
  UI.text($('comparison_status'), UI.msg("page.controls.comparison_24ddfe", {}));
  try {
    const r = await api('/api/compare', {
      conditions
    });
    renderComparison(r);
    const outputs = r.protocol.outputs;
    $('comparison_head').innerHTML = `<tr><th>${UI.htmlText("page.controls.condition_16bb1d", {})}</th><th>${UI.htmlText("page.controls.node_count_2e797c", {})}</th><th>${UI.htmlText("page.controls.retained_gain_915c4f", {})}</th><th>${UI.htmlText("page.controls.update_interval_677bb0", {})}</th>${outputs.map(o => `<th>${UI.htmlText("page.controls.message_3f765a", {
      p0: o
    })}</th>`).join('')}<th>${UI.htmlText("page.controls.details_979a33", {})}</th></tr>`;
    $('comparison_rows').innerHTML = r.rows.map((row, k) => `<tr><td>${UI.html(row.name)}</td><td>${row.intervention_node_count}</td><td>${(100 * row.gain).toFixed(1)}%</td><td>[${row.start}, ${row.stop})</td>${row.outputs.map(o => `<td>${UI.html(o.relative_sum_delta === null ? UI.msg("page.controls.no_baseline_response_dca6a4", {}) : (100 * o.relative_sum_delta).toFixed(2) + '%')}</td>`).join('')}<td><button class="linkbtn" data-inspect="${k}">${UI.htmlText("page.controls.view_signals_and_nodes_ffaad8", {})}</button></td></tr>`).join('');
    UI.text($('comparison_status'), UI.msg("page.controls.condition_9c8068", {
      p0: r.protocol.input_group,
      p1: r.protocol.amplitude,
      p2: r.protocol.input_start,
      p3: r.protocol.input_stop,
      p4: r.rows.length
    }));
    status(UI.msg("page.controls.multi_condition_comparisoncomplete_1ba199", {}));
  } catch (e) {
    status(UI.errorText(e), true);
    UI.text($('comparison_status'), UI.msg("page.controls.comparisonfailed_b295c9", {}));
  } finally {
    busy = false;
    $('experiment').classList.remove('busy');
    for (const id of ['run', 'baseline', 'load', 'export', 'compare_conditions']) $(id).disabled = false;
    $('save').disabled = !latest || dirty;
    $('save_comparison').disabled = !canSaveComparison();
    spatialSelection();
  }
};
$('save_comparison').onclick = async () => {
  if (!canSaveComparison()) return;
  const savingResult = comparison, savingView = comparisonView;
  comparisonSavingId = savingResult.comparison_id;
  $('save_comparison').disabled = true;
  try {
    const d = await api('/api/save-comparison', {
      comparison_id: savingResult.comparison_id
    });
    if (comparison === savingResult && comparisonView === savingView) {
      comparisonView = {origin: 'saved', artifactId: d.artifact_id};
      refreshComparisonStatus();
      renderComparisonUsability(comparison);
    }
    status(UI.join([UI.msg("page.controls.comparison_save_e30816", {}), d.artifact_id]));
    document.dispatchEvent(new Event('lab-saved'));
  } catch (e) {
    if (comparison === savingResult) UI.text($('comparison_status'), UI.errorText(e));
    status(UI.errorText(e), true);
  } finally {
    comparisonSavingId = null;
    $('save_comparison').disabled = !canSaveComparison();
  }
};
const spatial = new SkeletonView($('geometry_canvas'), id => showNode(id));
let geometryData = null,
  focusNode = null,
  focusSequence = 0,
  activitySequence = 0,
  activityRows = [],
  searchJob = null,
  searchResult = null;
function spatialSelection() {
  if (!overview) return;
  const c = cfg(),
    ids = c.intervention_ids ?? candidateNodes(c.intervention_group).map(n => n.bodyId);
  spatial.setSelection(ids);
  $('geometry_add').disabled = !focusNode || !candidateNodes('__all__').some(n => n.bodyId === focusNode.bodyId) || busy;
  UI.text($('geometry_add'), $('selection_mode').value === 'all' ? UI.msg("page.spatialSelection.node_4afe19", {}) : UI.msg("page.spatialSelection.add_to_intervention_set_ce1d68", {}));
}
async function refreshGeometry() {
  const generation = caseGeneration;
  try {
    const data = await api('/api/geometry');
    if (generation !== caseGeneration) return;
    geometryData = data;
    spatial.setOverview(geometryData);
    spatialSelection();
    UI.text($('geometry_status'), UI.msg("page.refreshGeometry.message_242414", {
      p0: geometryData.available_count,
      p1: geometryData.case_node_count,
      p2: geometryData.missing_count,
      p3: geometryData.invalid_count
    }));
    $('geometry_time').disabled = !latest?.run_id || !geometryData.available_count;
    if (geometryData.errors.length) UI.text($('geometry_status'), UI.join([UI.currentText($('geometry_status')), ' · ', UI.apiErrorText(geometryData.errors[0])]));
    if (focusNode) await focusGeometry(focusNode.bodyId);
  } catch (e) {
    UI.text($('geometry_status'), UI.errorText(e));
  }
}
async function focusGeometry(id, detail = null) {
  const seq = ++focusSequence;
  try {
    const d = detail || (await api('/api/node?' + new URLSearchParams({
      id
    })));
    if (seq !== focusSequence) return;
    focusNode = d.node;
    spatial.setFocus(id, null, [...d.incoming, ...d.outgoing].map(e => e.node.bodyId));
    UI.text($('geometry_focus'), `${d.node.group_label} · body ID ${id}`);
    spatialSelection();
    document.querySelectorAll('[data-id]').forEach(b => b.style.outline = b.dataset.id === id ? '1px solid var(--teal)' : '');
    if (geometryData?.nodes.some(n => n.bodyId === id)) {
      const skeleton = await api('/api/skeleton?' + new URLSearchParams({
        id
      }));
      if (seq !== focusSequence) return;
      spatial.setFocus(id, skeleton, [...d.incoming, ...d.outgoing].map(e => e.node.bodyId));
      UI.text($('geometry_focus'), UI.join([UI.currentText($('geometry_focus')), UI.msg("page.focusGeometry.m_19a306", {
        p0: UI.numeric(skeleton.point_count, {})
      })]));
    } else UI.text($('geometry_focus'), UI.join([UI.currentText($('geometry_focus')), UI.msg("page.focusGeometry.message_01ec6c", {})]));
    updateFocusActivity();
  } catch (e) {
    if (seq === focusSequence) UI.text($('geometry_focus'), UI.errorText(e));
  }
}
function updateFocusActivity() {
  if (!focusNode) return;
  const r = activityRows.find(n => n.bodyId === focusNode.bodyId);
  UI.text($('geometry_focus'), UI.join([focusNode.group_label || focusNode.type || '', ' · body ID ', focusNode.bodyId]));
  if (r) UI.text($('geometry_focus'), UI.join([UI.currentText($('geometry_focus')), UI.msg("page.updateFocusActivity.baseline_intervention_difference_731def", {
    p0: UI.numeric(r.baseline, {
      maximumSignificantDigits: 4
    }),
    p1: UI.numeric(r.intervention, {
      maximumSignificantDigits: 4
    }),
    p2: UI.numeric(r.delta, {
      maximumSignificantDigits: 4
    })
  })]));
}
async function refreshActivity() {
  if (!latest?.run_id || !geometryData?.available_count) return;
  const seq = ++activitySequence,
    runId = latest.run_id;
  let t = Number($('geometry_time').value);
  const times = latest.recording_metadata?.time_steps || [];
  if (!times.includes(t)) {
    t = times.reduce((a, b) => Math.abs(b - t) < Math.abs(a - t) ? b : a, times[0]);
    $('geometry_time').value = t;
  }
  UI.text($('geometry_step'), t);
  try {
    const r = await api('/api/activity?' + new URLSearchParams({
      run_id: runId,
      step: t
    }));
    if (seq !== activitySequence || latest?.run_id !== runId) return;
    activityRows = r.nodes;
    spatial.setActivity(r.nodes, $('geometry_mode').value);
    updateFocusActivity();
  } catch (e) {
    if (seq === activitySequence) UI.text($('geometry_focus'), UI.errorText(e));
  }
}
$('geometry_refresh').onclick = refreshGeometry;
$('geometry_reset').onclick = () => spatial.reset();
$('geometry_links').onchange = () => {
  spatial.showLinks = $('geometry_links').checked;
  spatial.draw();
};
$('geometry_mode').onchange = () => spatial.setActivity(activityRows, $('geometry_mode').value);
$('geometry_time').oninput = refreshActivity;
$('geometry_add').onclick = () => {
  if (busy || !focusNode || !candidateNodes('__all__').some(n => n.bodyId === focusNode.bodyId)) return;
  const c = cfg(),
    ids = c.intervention_ids || [];
  if (c.intervention_group !== '__all__' && !candidateNodes(c.intervention_group).some(n => n.bodyId === focusNode.bodyId)) $('intervention_group').value = '__all__';
  $('selection_mode').value = 'ids';
  $('selection_ids').value = [...new Set([...ids, focusNode.bodyId])].join(', ');
  changed();
  spatialSelection();
  status(UI.msg("page.controls.node_set_62ed9d", {}));
};
document.addEventListener('lab-result', () => {
  $('geometry_time').disabled = !latest?.run_id || !geometryData?.available_count;
  $('geometry_time').max = latest.config.experiment.steps;
  $('geometry_time').value = Math.min(Number($('geometry_time').value), latest.config.experiment.steps);
  spatialSelection();
  if (geometryData?.available_count) refreshActivity();
});
function useSearchPlan(p) {
  if (busy || !searchResult) return;
  apply({
    ...searchResult.experiment,
    intervention_ids: p.body_ids
  });
  changed();
  spatialSelection();
  if (p.body_ids.length) focusGeometry(p.body_ids[0]);
  status(UI.msg("page.useSearchPlan.searchplanloaded_pending_9a40ab", {}));
}
function renderSearch(r) {
  searchResult = r;
  const plans = (r.best ? [r.best] : []).concat(r.frontier.filter(p => p !== r.best && JSON.stringify(p.body_ids) !== JSON.stringify(r.best?.body_ids))).slice(0, 30);
  searchResult.displayPlans = plans;
  $('search_head').innerHTML = `<tr><th>${UI.htmlText("page.renderSearch.plan_6f949a", {})}</th><th>${UI.htmlText("page.renderSearch.node_count_2e797c", {})}</th><th>${UI.htmlText("page.renderSearch.message_5154a5", {
    p0: r.target_output
  })}</th><th>${UI.htmlText("page.renderSearch.message_5154a5", {
    p0: r.protected_output
  })}</th><th>${UI.htmlText("page.renderSearch.constraints_ba0934", {})}</th><th>${UI.htmlText("page.renderSearch.actions_ed31fb", {})}</th></tr>`;
  $('search_rows').innerHTML = plans.map((p, k) => `<tr><td>${UI.html(k === 0 ? UI.msg("page.controls.message_1234ab", {}) : UI.join([UI.msg("page.controls.message_3d7752", {}), k]))}</td><td>${p.node_count}</td><td>${(p.target_loss * 100).toFixed(2)}%</td><td>${(p.protected_loss * 100).toFixed(2)}%</td><td>${UI.html(p.feasible ? UI.msg("page.controls.satisfied_4e8156", {}) : UI.list(p.violations.map(v => v === 'minimum_target_loss' ? UI.msg("page.controls.a_target_8db666", {}) : UI.msg("page.controls.b_4f064b", {})), ' / '))}</td><td><button class="linkbtn" data-plan="${k}">${UI.htmlText("page.controls.load_nodes_34138c", {})}</button></td></tr>`).join('');
  $('sensitivity_head').innerHTML = `<tr><th>body ID</th><th>${UI.htmlText("page.renderSearch.type_ba4001", {})}</th><th>${UI.htmlText("page.renderSearch.message_5154a5", {
    p0: r.target_output
  })}</th><th>${UI.htmlText("page.renderSearch.message_5154a5", {
    p0: r.protected_output
  })}</th></tr>`;
  $('sensitivity_rows').innerHTML = r.sensitivity.slice(0, 100).map(n => `<tr><td>${idButton(n.bodyId)}</td><td>${UI.html(n.type)}</td><td>${(n.target_loss * 100).toFixed(3)}%</td><td>${(n.protected_loss * 100).toFixed(3)}%</td></tr>`).join('');
  document.dispatchEvent(new Event('lab-search'));
  const labels = {
    complete: UI.msg("page.renderSearch.searchstop_8728a6", {}),
    budget_exhausted: UI.msg("page.renderSearch.budget_exhausted_d9e9de", {}),
    cancelled: UI.msg("page.renderSearch.cancelled_a37778", {})
  };
  UI.text($('search_status'), UI.msg("page.renderSearch.message_0add7c", {
    p0: labels[r.status] || UI.code(r.status),
    p1: r.experiment.input_group,
    p2: r.target_output,
    p3: r.protected_output,
    p4: r.screened_candidates,
    p5: r.candidate_count,
    p6: r.evaluations,
    p7: r.options.max_evaluations,
    p8: r.best?.feasible ? UI.msg("page.renderSearch.satisfiedconstraints_plan_1998c8", {}) : UI.msg("page.renderSearch.satisfiedconstraints_plan_64f174", {})
  }));
}
async function pollSearch(id) {
  try {
    const d = await api('/api/search?' + new URLSearchParams({
      job_id: id
    }));
    if (searchJob !== id) return;
    if (d.status === 'running') {
      UI.text($('search_status'), UI.msg("page.pollSearch.message_c07f30", {
        p0: UI.code(d.progress.phase || 'baseline') || UI.msg("page.pollSearch.baseline_1bea37", {}),
        p1: d.progress.evaluations || 0,
        p2: d.progress.budget || '—'
      }));
      setTimeout(() => pollSearch(id), 700);
      return;
    }
    if (d.result) renderSearch(d.result);else UI.text($('search_status'), UI.apiErrorText(d));
    $('search_start').disabled = false;
    $('search_cancel').disabled = true;
    $('search_save').disabled = !d.result;
  } catch (e) {
    if (searchJob !== id) return;
    UI.text($('search_status'), UI.errorText(e));
    $('search_start').disabled = false;
    $('search_cancel').disabled = true;
  }
}
$('search_start').onclick = async () => {
  if (busy || $('search_start').disabled) return;
  try {
    const c = cfg();
    validateCondition(c);
    const options = {
      max_nodes: Number($('search_size').value),
      max_evaluations: Number($('search_budget').value),
      max_protected_loss: Number($('search_cap').value) / 100,
      min_target_loss: Number($('search_min').value) / 100
    };
    $('search_start').disabled = true;
    $('search_save').disabled = true;
    const d = await api('/api/search', {
      experiment: c,
      options
    });
    searchJob = d.job_id;
    searchResult = null;
    document.dispatchEvent(new Event('lab-search'));
    $('search_cancel').disabled = false;
    $('search_rows').replaceChildren();
    $('sensitivity_rows').replaceChildren();
    pollSearch(searchJob);
  } catch (e) {
    UI.text($('search_status'), UI.errorText(e));
    $('search_start').disabled = false;
  }
};
$('search_cancel').onclick = async () => {
  const id = searchJob;
  try {
    await api('/api/cancel-search', {
      job_id: id
    });
    if (id === searchJob && $('search_start').disabled) {
      $('search_cancel').disabled = true;
      UI.text($('search_status'), UI.msg("page.controls.cancel_e8e08b", {}));
    }
  } catch (e) {
    if (id === searchJob && $('search_start').disabled) UI.text($('search_status'), UI.errorText(e));
  }
};
$('search_save').onclick = async () => {
  const id = searchJob;
  $('search_save').disabled = true;
  try {
    const d = await api('/api/save-search', {
      job_id: id
    });
    status(UI.join([UI.msg("page.controls.search_save_7ce157", {}), d.folder]));
    document.dispatchEvent(new Event('lab-saved'));
  } catch (e) {
    status(UI.errorText(e), true);
  } finally {
    if (id === searchJob) $('search_save').disabled = !searchResult;
  }
};
document.addEventListener('click', e => {
  if (e.target.dataset.plan !== undefined) useSearchPlan(searchResult.displayPlans[Number(e.target.dataset.plan)]);
});
