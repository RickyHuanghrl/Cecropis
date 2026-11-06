"use strict";

/* One global background, exact shared selections, explicit existing replay only. */
const spatialPanel = document.createElement('section');
spatialPanel.id = 'spatial_panel';
spatialPanel.className = 'panel wide';
spatialPanel.innerHTML = `<div class="rowtitle"><h2>${UI.htmlText("spatial.labels.space_3347e0", {})}</h2><div class="buttons"><button id="space_load">${UI.htmlText("spatial.labels.load_global_positions_ef31eb", {})}</button><button id="space_expand">${UI.htmlText("spatial.labels.expand_00bd39", {})}</button><button id="space_fit">${UI.htmlText("spatial.labels.fit_global_view_116c08", {})}</button><button id="space_focus">${UI.htmlText("spatial.labels.focus_selected_a5f3aa", {})}</button></div></div>
<div id="space_status" role="status"></div><div id="space_coverage"></div><div id="space_context"></div>
<div class="buttons"><label>${UI.htmlText("spatial.labels.actions_762059", {})}<select id="space_tool"><option value="orbit" data-i18n="spatial.labels.orbit_alt_right_drag_to_pan_78d337">${UI.t("spatial.labels.orbit_alt_right_drag_to_pan_78d337")}</option><option value="box" data-i18n="spatial.labels.box_select_all_depths_868bb1">${UI.t("spatial.labels.box_select_all_depths_868bb1")}</option></select></label><label><input type="checkbox" id="space_append" checked>${UI.htmlText("spatial.labels.append_selection_9be944", {})}</label><label><input type="checkbox" id="space_isolate">${UI.htmlText("spatial.labels.isolate_selection_highlight_299a03", {})}</label><button id="space_clear">${UI.htmlText("spatial.labels.clear_selection_a3c974", {})}</button><button id="space_clear_highlight">${UI.htmlText("spatial.labels.clear_highlight_5e2c0f", {})}</button></div>
<div id="space_stage" style="position:relative"><canvas id="space_canvas" style="display:block;width:100%;height:480px;touch-action:none" ${UI.htmlAttribute("aria-label", "spatial.labels.emspace_3d4d8a", {})}></canvas><div id="space_frame_label" style="position:absolute;top:6px;right:8px;pointer-events:none;background:#16202ddd"></div><div id="space_focus_label" style="position:absolute;top:6px;left:8px;pointer-events:none;background:#16202ddd"></div><div id="space_box" style="display:none;position:absolute;border:1px solid #ffdc75;pointer-events:none"></div></div>
<div id="space_legend">${UI.htmlText("spatial.labels.soma_circles_cut_fiber_ends_crosses_selection_outlined_h_a86d53", {})}</div>
<details><summary>${UI.htmlText("spatial.labels.groups_selection_823163", {})}</summary><div class="buttons"><select id="space_field" ${UI.htmlAttribute("aria-label", "spatial.labels.spacefilter_039909", {})}><option value="superclass">superclass</option><option value="class">class</option><option value="type">type</option><option value="somaSide">somaSide</option></select><input id="space_value" type="text" ${UI.htmlAttribute("aria-label", "spatial.labels.space_annotation_value_63f879", {})}><button id="space_filter_highlight">${UI.htmlText("spatial.labels.highlight_annotation_68eafa", {})}</button><button id="space_filter">${UI.htmlText("spatial.labels.show_only_this_value_47d5ff", {})}</button><button id="space_filter_clear">${UI.htmlText("spatial.labels.clear_display_filter_f507e3", {})}</button></div><div class="buttons"><button id="space_group">${UI.htmlText("spatial.labels.highlight_all_group_members_17f9f0", {})}</button><button id="space_query">${UI.htmlText("spatial.labels.highlight_all_query_matches_580bc1", {})}</button><button id="space_select_group">${UI.htmlText("spatial.labels.select_entire_highlighted_set_0324f3", {})}</button><button id="space_scope">${UI.htmlText("spatial.labels.highlight_calculation_scope_c03609", {})}</button></div><div id="space_selection_info"></div><textarea id="space_ids" rows="3" readonly ${UI.htmlAttribute("aria-label", "spatial.labels.selectionbody_id_00a96e", {})}></textarea>
<div class="buttons"><select id="space_handoff" ${UI.htmlAttribute("aria-label", "spatial.labels.spaceselectrole_7e0848", {})}><option value="seeds" data-i18n="spatial.labels.new_scope_seeds_6f5a57">${UI.t("spatial.labels.new_scope_seeds_6f5a57")}</option><option value="path_source" data-i18n="spatial.labels.path_sources_eb8ef8">${UI.t("spatial.labels.path_sources_eb8ef8")}</option><option value="path_a" data-i18n="spatial.labels.path_target_a_a32b57">${UI.t("spatial.labels.path_target_a_a32b57")}</option><option value="path_b" data-i18n="spatial.labels.path_target_b_d99a64">${UI.t("spatial.labels.path_target_b_d99a64")}</option><option value="input" data-i18n="spatial.labels.new_input_event_draft_795a6b">${UI.t("spatial.labels.new_input_event_draft_795a6b")}</option><option value="observation" data-i18n="spatial.labels.new_observation_draft_63fb3b">${UI.t("spatial.labels.new_observation_draft_63fb3b")}</option><option value="intervention" data-i18n="spatial.labels.new_node_intervention_draft_2a1f0f">${UI.t("spatial.labels.new_node_intervention_draft_2a1f0f")}</option></select><button id="space_send">${UI.htmlText("spatial.labels.send_to_editor_904d59", {})}</button></div></details>
<details id="space_detail"><summary>${UI.htmlText("spatial.labels.focused_object_actual_connections_6f68df", {})}</summary><div id="space_node_detail"></div><div class="buttons"><button id="space_add_focus">${UI.htmlText("spatial.labels.add_focused_node_a03520", {})}</button><button id="space_neighbors">${UI.htmlText("spatial.labels.show_actual_neighbors_top_20_per_direction_49cf31", {})}</button><button id="space_event_edges">${UI.htmlText("spatial.labels.show_bound_plan_edges_447b66", {})}</button><button id="space_path_edges">${UI.htmlText("spatial.labels.show_current_path_edges_21d4d2", {})}</button><button id="space_no_edges">${UI.htmlText("spatial.labels.clear_abstract_connections_2604a5", {})}</button></div><div id="space_edge_info"></div><div class="tablewrap" style="max-height:200px"><table><thead><tr><th>${UI.htmlText("spatial.labels.actual_direction_2970a5", {})}</th><th>${UI.htmlText("spatial.labels.connection_count_93e376", {})}</th><th>${UI.htmlText("spatial.labels.base_weight_c4f4f2", {})}</th></tr></thead><tbody id="space_edge_rows"></tbody></table></div><div id="space_edge_detail"></div></details>
<details open><summary>${UI.htmlText("spatial.labels.real_skeletons_d9e414", {})}</summary><div class="buttons"><button id="space_geom_load">${UI.htmlText("spatial.labels.load_processed_skeletons_49dac5", {})}</button><label>${UI.htmlText("spatial.labels.input_budget_mib_df9d4b", {})}<input id="space_geom_input" type="number" min="1" max="8192" value="512" style="width:80px"></label><label>${UI.htmlText("spatial.labels.cache_limit_mib_373b5f", {})}<input id="space_geom_cache" type="number" min="1" max="16384" value="2048" style="width:85px"></label><button id="space_geom_update">${UI.htmlText("spatial.labels.update_geometry_3d88d6", {})}</button><button id="space_geom_cancel" disabled>${UI.htmlText("spatial.labels.cancel_processing_8b69bc", {})}</button><label><input id="space_geom_enabled" type="checkbox" checked>${UI.htmlText("spatial.labels.show_skeletons_438126", {})}</label></div><div id="space_geometry_coverage"></div><div class="buttons"><label>${UI.htmlText("spatial.labels.display_diameter_m_993edb", {})}<input id="space_geom_diameter" type="number" min="0.01" max="10" step="0.05" value="0.3" style="width:70px"></label><label>${UI.htmlText("spatial.labels.radius_scale_5886b0", {})}<input id="space_geom_radius_scale" type="number" min="0.1" max="100" step="0.5" value="1" style="width:60px"></label><label>${UI.htmlText("spatial.labels.background_intensity_f6dd70", {})}<input id="space_geom_background" type="range" min="0" max="1" step="0.01" value="0.15"></label><label>${UI.htmlText("spatial.labels.display_quality_5ad550", {})}<select id="space_geom_quality"><option value="balanced" data-i18n="spatial.labels.balanced_2588b5">${UI.t("spatial.labels.balanced_2588b5")}</option><option value="high" data-i18n="spatial.labels.detailed_c4191d">${UI.t("spatial.labels.detailed_c4191d")}</option><option value="low" data-i18n="spatial.labels.low_cost_ab6c44">${UI.t("spatial.labels.low_cost_ab6c44")}</option></select></label></div><div id="space_geometry_status">${UI.htmlText("spatial.labels.processed_skeletons_not_loaded_be3b61", {})}</div><details><summary>${UI.htmlText("spatial.labels.local_swc_6a0c33", {})}</summary><div class="buttons"><button id="space_skeleton">${UI.htmlText("spatial.labels.load_local_swc_for_focused_object_6f221d", {})}</button><button id="space_skeleton_clear">${UI.htmlText("spatial.labels.clear_swc_layer_001df4", {})}</button></div></details></details>
<div class="buttons"><select id="space_mode" ${UI.htmlAttribute("aria-label", "spatial.labels.space_da439b", {})}><option value="structure" data-i18n="spatial.labels.structure_b9011a">${UI.t("spatial.labels.structure_b9011a")}</option><option value="baseline" data-i18n="spatial.labels.baseline_a7ac58">${UI.t("spatial.labels.baseline_a7ac58")}</option><option value="intervention" data-i18n="spatial.labels.intervention_c74feb">${UI.t("spatial.labels.intervention_c74feb")}</option><option value="delta" data-i18n="spatial.labels.intervention_baseline_565398">${UI.t("spatial.labels.intervention_baseline_565398")}</option></select><button id="space_bind">${UI.htmlText("spatial.labels.use_existing_replay_6cd158", {})}</button><button id="space_play">${UI.htmlText("spatial.labels.play_c33961", {})}</button><button id="space_to_replay">${UI.htmlText("spatial.labels.open_2d_replay_node_curves_96268f", {})}</button></div><label>${UI.htmlText("spatial.labels.recorded_state_step_c72cb8", {})}<output id="space_time_label">—</output><input id="space_time" type="range" min="0" max="0" step="1" value="0" disabled></label><div id="space_activity_info"></div><div class="buttons"><button id="space_save_scene">${UI.htmlText("spatial.labels.save_current_session_bad39e", {})}</button></div>`;
$('scope_workspace').before(spatialPanel);
$('geometry_panel').hidden = true;
let spaceHeader = null,
  spaceLoadPromise = null,
  spaceBytes = 0,
  spaceHighIds = [],
  spaceFilter = null,
  spaceFocusId = null,
  spaceFocusData = null,
  spaceNeighbors = null;
let spaceSequence = 0,
  spaceLoadGeneration = 0,
  spaceCountRevision = -1,
  spaceGeometrySequence = 0,
  spaceEdgesSequence = 0,
  spaceSelectionSequence = 0,
  spaceRestoreSequence = 0,
  spaceBoundReplay = null,
  spaceEdgeId = null,
  spacePlaying = null,
  spaceSkeletonIds = [];
window.spatialKnownIds = new Set();
function spaceStatus(text, error = false) {
  UI.text($('space_status'), text);
  $('space_status').classList.toggle('error', error);
}
const globalSpace = new GlobalSpatialView($('space_canvas'), {
  tool: () => $('space_tool').value,
  error: spaceStatus,
  pick: (id, append) => {
    spaceFocus(id);
    if (append || $('space_append').checked) spaceSelect([id], true);
  },
  region: ids => spaceSelect(ids, $('space_append').checked),
  edge: id => spaceSelectEdge(id),
  box: rect => {
    const b = $('space_box');
    b.style.display = rect ? 'block' : 'none';
    if (rect) {
      b.style.left = Math.min(rect[0], rect[2]) + 'px';
      b.style.top = Math.min(rect[1], rect[3]) + 'px';
      b.style.width = Math.abs(rect[2] - rect[0]) + 'px';
      b.style.height = Math.abs(rect[3] - rect[1]) + 'px';
    }
  },
  render: () => spaceViewCounts()
});
async function spaceLoad() {
  if (spaceHeader) return spaceHeader;
  if (spaceLoadPromise) return spaceLoadPromise;
  spaceLoadPromise = (async () => {
    const seq = ++spaceLoadGeneration;
    spaceStatus(UI.msg("spatial.controls.traced_249201", {}));
    $('space_load').disabled = true;
    try {
      const h = await api('/api/spatial/overview'),
        ids = [],
        xyz = new Float32Array(h.traced_count * 3),
        kinds = new Uint8Array(h.traced_count);
      let offset = 0,
        bytes = 0;
      while (offset < h.traced_count) {
        const response = await fetch('/api/spatial/chunk?' + new URLSearchParams({
          cache_id: h.cache_id,
          offset,
          limit: 20000
        }));
        if (!response.ok) throw Error((await response.json()).error);
        const body = await response.arrayBuffer();
        if (seq !== spaceLoadGeneration) return null;
        if (body.byteLength % 24) throw UI.error("spatial.controls.space_1ff8f1", {});
        const data = new DataView(body);
        let count = body.byteLength / 24;
        if (!count || offset + count > h.traced_count) throw UI.error("spatial.controls.space_count_aa63ab", {});
        for (let i = 0; i < count; i++) {
          const start = i * 24;
          ids.push(data.getBigUint64(start, true).toString());
          for (let k = 0; k < 3; k++) xyz[(offset + i) * 3 + k] = data.getFloat32(start + 8 + k * 4, true);
          kinds[offset + i] = data.getUint8(start + 20);
        }
        offset += count;
        bytes += body.byteLength;
        spaceStatus(UI.join([UI.join([UI.join([UI.join([UI.msg("spatial.controls.message_a0dd64", {}), num(offset)]), ' / ']), num(h.traced_count)]), UI.msg("spatial.controls.message_953350", {})]));
      }
      spaceHeader = h;
      spaceBytes = bytes;
      window.spatialKnownIds = new Set(ids);
      globalSpace.setData(ids, xyz, kinds, h.bounds);
      globalSpace.setScope((overview?.scope_nodes || []).map(n => String(n.bodyId)));
      globalSpace.setSelection(window.analysisSelection.ids(), spaceFocusId);
      UI.text($('space_load'), UI.msg("spatial.controls.global_positions_loaded_c2abcc", {}));
      $('space_load').disabled = true;
      spaceStatus(UI.msg("spatial.controls.loaded_emspace_m_ca8c86", {}));
      spaceViewCounts();
      return h;
    } catch (e) {
      spaceStatus(UI.errorText(e), true);
      $('space_load').disabled = false;
      throw e;
    } finally {
      spaceLoadPromise = null;
    }
  })();
  return spaceLoadPromise;
}
function spaceViewCounts() {
  if (!spaceHeader) return;
  if (spaceCountRevision !== globalSpace.visibilityRevision) {
    spaceCountRevision = globalSpace.visibilityRevision;
    let visible = 0,
      missing = 0;
    for (let i = 0; i < globalSpace.ids.length; i++) if (globalSpace.visible(globalSpace.ids[i])) {
      if (globalSpace.kinds[i] === 1 || globalSpace.kinds[i] === 2) visible++;else missing++;
    }
    UI.text($('space_coverage'), UI.msg("spatial.spaceViewCounts.traced_soma_fiber_ends_missing_invalid_displayed_points__bc6245", {
      p0: UI.numeric(spaceHeader.traced_count, {}),
      p1: UI.numeric(spaceHeader.soma_count, {}),
      p2: UI.numeric(spaceHeader.other_position_count, {}),
      p3: UI.numeric(spaceHeader.missing_count, {}),
      p4: UI.numeric(spaceHeader.invalid_count, {}),
      p5: UI.numeric(globalSpace.showPoints ? visible : 0, {}),
      p6: UI.numeric(missing, {}),
      p7: UI.fixed(spaceBytes / 1024 ** 2, 2)
    }));
  }
  UI.text($('space_context'), UI.msg("spatial.spaceViewCounts.global_traced_positions_and_skeletons_compute_nodes_sele_fda40a", {
    p0: overview ? num(overview.manifest.node_count) : '—',
    p1: window.analysisSelection.ids().length
  }));
}
async function spaceSelect(ids, append = false) {
  const seq = ++spaceSelectionSequence;
  try {
    await spaceLoad();
    const exact = [...new Set(ids.map(String))];
    if (!exact.length && !append) {
      analysisSelection.clear();
      return;
    }
    const r = await api('/api/spatial/locate', {
      source_index_id: spaceHeader.identity.source_index_id,
      body_ids: exact
    });
    if (seq !== spaceSelectionSequence) return;
    for (const n of r.nodes) spatialKnownIds.add(n.bodyId);
    analysisSelection.set(append ? [...new Set([...analysisSelection.ids(), ...exact])] : exact);
    spaceStatus(UI.msg("spatial.spaceSelect.selection_members_space_c604c9", {
      p0: append ? UI.msg("spatial.spaceSelect.message_d91017", {}) : UI.msg("spatial.spaceSelect.message_131b13", {}),
      p1: UI.numeric(exact.length, {}),
      p2: UI.numeric(r.selection_count - r.located_count, {})
    }));
  } catch (e) {
    spaceStatus(UI.errorText(e), true);
  }
}
function spaceSelectionDisplay() {
  const ids = analysisSelection.ids();
  $('space_ids').value = ids.join(', ');
  let located = 0;
  for (const id of ids) if (globalSpace.position(id)) located++;
  UI.text($('space_selection_info'), UI.msg("spatial.spaceSelectionDisplay.full_selection_positioned_missing_81077b", {
    p0: UI.numeric(ids.length, {}),
    p1: UI.numeric(located, {}),
    p2: UI.numeric(ids.length - located, {})
  }));
  globalSpace.setSelection(ids, spaceFocusId);
}
async function spaceHighlight(ids, label) {
  window.workspaceShell?.navigate('space');
  const seq = ++spaceSelectionSequence;
  await spaceLoad();
  const exact = [...new Set(ids.map(String))];
  const r = await api('/api/spatial/locate', {
    source_index_id: spaceHeader.identity.source_index_id,
    body_ids: exact
  });
  if (seq !== spaceSelectionSequence) return;
  spaceHighIds = exact;
  globalSpace.setHighlight(exact);
  spaceStatus(UI.msg("spatial.spaceHighlight.members_555f62", {
    p0: label,
    p1: UI.numeric(exact.length, {}),
    p2: UI.numeric(r.located_count, {}),
    p3: UI.numeric(exact.length - r.located_count, {})
  }));
  globalSpace.fit(exact);
}
async function spaceFocus(id) {
  const seq = ++spaceSequence;
  ++spaceGeometrySequence;
  spaceFocusId = id;
  spaceFocusData = null;
  spaceNeighbors = null;
  analysisSelection.focus(id);
  globalSpace.setSelection(analysisSelection.ids(), id);
  $('space_detail').open = true;
  window.spaceOpenDetails?.();
  if($('space_node_summary'))$('space_node_summary').replaceChildren();
  UI.text($('space_node_detail'), UI.join([UI.join([UI.msg("spatial.spaceFocus.message_8107a8", {}), id]), '…']));
  try {
    const [data, incoming, outgoing, geometry] = await Promise.all([api('/api/global/node?' + new URLSearchParams({
      id
    })), api('/api/global/neighbors?' + new URLSearchParams({
      id,
      direction: 'incoming',
      limit: 20
    })), api('/api/global/neighbors?' + new URLSearchParams({
      id,
      direction: 'outgoing',
      limit: 20
    })), api('/api/skeleton-cache/locate', {
      body_ids: [id]
    })]);
    if (seq !== spaceSequence || spaceFocusId !== id) return;
    spaceFocusData = data.node;
    spaceNeighbors = {
      incoming,
      outgoing
    };
    renderSpaceNodeSummary();
    $('space_node_detail').innerHTML='<div id="space_neighbor_lists"></div>';
    renderSpaceNeighborLists();
    const shape = geometry.nodes?.[0],
      line = document.createElement('div');
    line.id = 'space_shape_status';
    const statuses = {
      available: UI.msg("spatial.spaceFocus.real_skeleton_processed_665eef", {}),
      downloaded_unprocessed: UI.msg("spatial.spaceFocus.downloaded_not_processed_4dcb49", {}),
      not_downloaded: UI.msg("spatial.spaceFocus.not_downloaded_7176bc", {}),
      missing: UI.msg("spatial.spaceFocus.message_6a305f", {}),
      unprepared: UI.msg("spatial.spaceFocus.message_342100", {}),
      invalid: UI.msg("spatial.spaceFocus.message_056922", {})
    };
    UI.text(line, shape ? UI.join([statuses[shape.status] || shape.status, shape.status === 'available' ? UI.join([UI.join([UI.join([UI.join([' · ' + shape.vertices, UI.msg("spatial.spaceFocus.message_122631", {})]), shape.edges]), UI.msg("spatial.spaceFocus.message_d671e5", {})]), shape.radius ? UI.msg("spatial.spaceFocus.message_1209bc", {}) : UI.msg("spatial.spaceFocus.display_diameter_no_radius_attribute_752fbb", {})]) : shape.error ? ' · ' + shape.error : '']) : UI.msg("spatial.spaceFocus.statusnot_recorded_0d5011", {}));
    (document.getElementById('space_geometry_extra')||$('space_node_detail')).append(line);
    UI.text($('space_focus_label'), UI.join([UI.join([data.node.type || data.node.instance || UI.msg("spatial.spaceFocus.unclassified_54b89f", {}), ' · ']), id]));
    spaceUpdateFocusValue();
  } catch (e) {
    if (seq === spaceSequence) UI.text($('space_node_detail'), UI.errorText(e));
  }
}
function spaceUpdateFocusValue() {
  if (!spaceFocusData) return;
  let element = $('space_focus_value');
  if (!element) {
    element = document.createElement('div');
    element.id = 'space_focus_value';
    ($('space_node_summary')||$('space_node_detail')).append(element);
  }
  const row = globalSpace.activity.get(spaceFocusId);
  const summary = typeof responseSpaceSummary !== 'undefined' && responseSpaceSummary;
  if (row) {
    const mode = $('space_mode').value === 'structure' ? 'baseline' : $('space_mode').value;
    UI.text($('space_focus_label'), UI.join([UI.join([UI.join([UI.join([spaceFocusData.type || spaceFocusData.instance || UI.msg("spatial.spaceUpdateFocusValue.node_2410d8", {}), ' · ']), spaceFocusId]), ' · ']), contextNumber(row[mode])]));
    const fields = [
      [summary ? 'spatial.detail.window' : 'spatial.detail.state', summary ? UI.msg('spatial.spaceUpdateFocusValue.window_690210') : replayFrame?.state_step],
      ['spatial.detail.baseline',row.baseline],['spatial.detail.intervention',row.intervention],['spatial.detail.delta',row.delta]
    ];
    if (!summary) fields.push(['spatial.detail.update',replayFrame?.node_update_step],['spatial.detail.gain',row.effective_gain]);
    element.innerHTML='<dl class="node-values">'+fields.map(([key,value])=>'<div><dt>'+UI.htmlText(key)+'</dt><dd>'+UI.html(value == null ? UI.msg('use.missingActivity') : typeof value === 'number' && !['spatial.detail.state','spatial.detail.update'].includes(key) ? UI.numeric(value,{notation:'scientific',minimumFractionDigits:4,maximumFractionDigits:4}) : value)+'</dd></div>').join('')+'</dl>';

  } else UI.text(element, globalSpace.caseIds.has(spaceFocusId) ? UI.msg("spatial.spaceUpdateFocusValue.scopemembers_not_recorded_97f5b3", {
    p0: globalSpace.activeNodes.has(spaceFocusId) ? UI.join([UI.msg("spatial.spaceUpdateFocusValue.message_556171", {}), contextNumber(spaceEventGain('node_gain', spaceFocusId))]) : ''
  }) : UI.msg("spatial.spaceUpdateFocusValue.outside_this_calculation_c5d1ba", {}));
}
async function spaceShowEdges(pairs) {
  const seq = ++spaceEdgesSequence;
  await spaceLoad();
  const r = await api('/api/spatial/edges', {
    source_index_id: spaceHeader.identity.source_index_id,
    edges: pairs,
    max_edges: 2000
  });
  if (seq !== spaceEdgesSequence) return null;
  globalSpace.setEdges(r.edges);
  $('space_edge_rows').innerHTML = r.edges.map(e => `<tr><td><button class="linkbtn" data-space-edge="${esc(e.edge_id)}">${UI.html(e.pre_id)} → ${UI.html(e.post_id)}</button></td><td>${UI.html(num(e.count))}</td><td>${UI.html(contextNumber(e.weight))}</td></tr>`).join('');
  UI.text($('space_edge_info'), UI.msg("spatial.spaceShowEdges.actual_edges_drawable_missing_endpoints_straight_lines_i_1fa22a", {
    p0: UI.numeric(r.edge_count, {}),
    p1: UI.numeric(r.drawable_count, {}),
    p2: UI.numeric(r.edge_count - r.drawable_count, {})
  }));
  return r;
}
function spaceEventGain(type, id) {
  return (replayFrame?.active_events || []).filter(e => e.type === type && e.gain < 1 && (type === 'node_gain' ? e.body_ids.includes(id) : e.edges.some(p => p.join('->') === id))).reduce((g, e) => g * e.gain, 1);
}
function spaceSelectEdge(id) {
  spaceEdgeId = id;
  const base = globalSpace.edges.find(e => e.edge_id === id),
    r = spaceBoundReplay === replayResult?.replay_id ? replayFrame?.edges.find(e => e.edge_id === id) : null;
  if (!base) return;
  $('space_detail').open = true;
  UI.text($('space_edge_detail'), UI.msg("spatial.spaceSelectEdge.connection_count_base_weight_34ebdd", {
    p0: base.pre_id,
    p1: base.post_id,
    p2: base.count,
    p3: UI.numeric(base.weight, {
      notation: "scientific",
      minimumFractionDigits: 4,
      maximumFractionDigits: 4
    }),
    p4: r ? r.connection_defined ? UI.msg("spatial.spaceSelectEdge.message_d1e93f", {
      p0: replayFrame.state_step,
      p1: UI.numeric(r.effective_gain, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      }),
      p2: UI.numeric(r.intervention, {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      })
    }) : UI.msg("spatial.spaceSelectEdge.message_121153", {}) : UI.msg("spatial.spaceSelectEdge.not_recorded_4b5bcb", {
      p0: UI.numeric(spaceEventGain('edge_gain', id), {
        notation: "scientific",
        minimumFractionDigits: 4,
        maximumFractionDigits: 4
      })
    })
  }));
}
function spaceUnbind() {
  spaceEdgesSequence++;
  spaceSelectionSequence++;
  spacePause();
  spaceBoundReplay = null;
  globalSpace.setActivity(null, 'structure', 1);
  $('space_time').disabled = true;
  UI.text($('space_time_label'), '—');
  UI.text($('space_activity_info'), UI.msg("spatial.spaceUnbind.no_result_bound_f04856", {}));
  UI.text($('space_frame_label'), '');
  UI.text($('space_edge_detail'), '');
  if (spaceFocusData) UI.text($('space_focus_label'), UI.join([UI.join([spaceFocusData.type || spaceFocusData.instance || UI.msg("spatial.spaceUnbind.node_2410d8", {}), ' · ']), spaceFocusId]));
  if ($('space_focus_value')) UI.text($('space_focus_value'), UI.msg("spatial.spaceUnbind.no_activity_record_bound_6bc37d", {}));
}
function spacePause() {
  if (spacePlaying) clearInterval(spacePlaying);
  spacePlaying = null;
  UI.text($('space_play'), UI.msg("spatial.spacePause.play_c33961", {}));
}
function spaceSyncReplay() {
  if (spaceBoundReplay && spaceBoundReplay !== replayResult?.replay_id) {
    spaceUnbind();
    return;
  }
  if (!spaceHeader || !replayResult?.ready || !spaceBoundReplay || !replayFrame) return;
  if (replayResult.config.source_index_id !== spaceHeader.identity.source_index_id || replayResult.config.case_id !== overview?.manifest.case_id) {
    spaceUnbind();
    spaceStatus(UI.msg("spatial.spaceSyncReplay.replayscope_8837ff", {}), true);
    return;
  }
  const mode = $('space_mode').value,
    domain = mode === 'delta' ? replayResult.color_domain?.delta_abs_max ?? 1 : replayResult.color_domain?.activity_max ?? 1;
  globalSpace.setActivity(replayFrame, mode, domain);
  $('space_time').max = replayResult.time_steps.length - 1;
  $('space_time').disabled = false;
  $('space_time').value = Math.max(0, replayResult.time_steps.indexOf(replayFrame.state_step));
  UI.text($('space_time_label'), 'x(' + replayFrame.state_step + ')');
  UI.text($('space_frame_label'), UI.join([UI.join([UI.join([UI.join([UI.join([UI.join(['x(', replayFrame.state_step]), ') · ']), {
    structure: UI.msg("spatial.spaceSyncReplay.message_3b15fa", {}),
    baseline: UI.msg("spatial.spaceSyncReplay.baseline_a7ac58", {}),
    intervention: UI.msg('use.intervention'),
    delta: UI.msg("spatial.spaceSyncReplay.intervention_baseline_565398", {})
  }[mode]]), UI.msg("spatial.spaceSyncReplay.message_242179", {})]), mode === 'delta' ? '±' : '0…']), contextNumber(domain)]));
  const inSpace = replayFrame.nodes.filter(n => globalSpace.position(n.body_id)).length,
    zero = replayFrame.nodes.filter(n => n[mode === 'structure' ? 'baseline' : mode] === 0).length;
  UI.text($('space_activity_info'), UI.msg("spatial.spaceSyncReplay.x_recorded_positioned_missing_recorded_zeros_color_domai_d31149", {
    p0: replayFrame.state_step,
    p1: replayFrame.nodes.length,
    p2: inSpace,
    p3: replayFrame.nodes.length - inSpace,
    p4: zero,
    p5: mode === 'delta' ? '±' : '0…',
    p6: UI.numeric(globalSpace.domain, {
      notation: "scientific",
      minimumFractionDigits: 4,
      maximumFractionDigits: 4
    }),
    p7: globalSpace.activeNodes.size,
    p8: globalSpace.activeEdges.size
  }));
  spaceUpdateFocusValue();
  if (spaceEdgeId) spaceSelectEdge(spaceEdgeId);
}
async function spaceBind() {
  const epoch = analysisOpenSequence;
  try {
    await spaceLoad();
    if (epoch !== analysisOpenSequence) return;
    if (!replayResult?.ready) throw UI.error("spatial.spaceBind.open_replay_82befb", {});
    if (replayResult.config.source_index_id !== spaceHeader.identity.source_index_id) throw UI.error("spatial.spaceBind.replay_b51c59", {});
    const origin = replayResult;
    spaceBoundReplay = origin.replay_id;
    if ($('space_mode').value === 'structure') $('space_mode').value = 'delta';
    const edges = await spaceShowEdges(origin.edges.map(e => [e.pre_id, e.post_id]));
    if (!edges || epoch !== analysisOpenSequence || origin !== replayResult || spaceBoundReplay !== origin.replay_id) return;
    spaceSyncReplay();
    spaceStatus(UI.msg("spatial.spaceBind.existing_records_bound_c90dc7", {}));
  } catch (e) {
    if (epoch === analysisOpenSequence) spaceStatus(UI.errorText(e), true);
  }
}
async function spaceGeometry(ids) {
  const seq = ++spaceGeometrySequence;
  try {
    await spaceLoad();
    const r = await api('/api/spatial/geometry', {
      source_index_id: spaceHeader.identity.source_index_id,
      body_ids: ids,
      load: true
    });
    if (seq !== spaceGeometrySequence) return;
    spaceSkeletonIds = ids;
    globalSpace.setSkeletons(r.objects.filter(o => o.status === 'loaded').map(o => o.skeleton));
    UI.text($('space_geometry_status'), UI.join([UI.list(r.objects.map(o => UI.join([o.bodyId, " · ", o.status === 'loaded' ? UI.join([o.skeleton.point_count, UI.msg("spatial.controls.swc_b4538e", {})]) : o.status === 'missing' ? UI.msg("spatial.controls.message_8eadf2", {}) : UI.apiErrorText(o)])), ' / '), UI.msg("spatial.spaceGeometry.8_32mib_6cc93a", {
      p0: globalSpace.skeletons.length,
      p1: ids.length
    })]));
  } catch (e) {
    if (seq === spaceGeometrySequence) UI.text($('space_geometry_status'), UI.errorText(e));
  }
}
function spaceSend() {
  try {
    const ids = analysisSelection.ids();
    if (!ids.length) throw UI.error("spatial.spaceSend.select_nodes_first_24135a", {});
    if (ids.length > 200000) throw UI.error("spatial.spaceSend.select_scope_budget_45d8e3", {});
    const action = $('space_handoff').value;
    if (action === 'seeds') {
      appendSeeds(ids);
      $('scope_ids').closest('details').open = true;
      $('scope_ids').scrollIntoView({
        block: 'center'
      });
    } else if (action.startsWith('path_')) {
      const key = action.slice(5);
      $({
        source: 'path_source_ids',
        a: 'path_a_ids',
        b: 'path_b_ids'
      }[key]).value = ids.join(', ');
      $('path_scope').value = 'global';
      $('path_endpoint_mode').value = 'ids';
      $('path_endpoints').hidden = false;
      $('path_observation_controls').hidden = true;
      $('path_explore').disabled = false;
      if (typeof groupEnsurePathway === 'function') groupEnsurePathway();
      $('pathway_panel').scrollIntoView({
        block: 'center'
      });
    } else {
      const allowed = new Set((overview?.scope_nodes || []).map(n => String(n.bodyId))),
        missing = ids.filter(id => !allowed.has(id));
      if (missing.length) throw UI.errorValue(UI.join([UI.msg("spatial.spaceSend.members_scope_scope_79c7ce", {}), missing.join(', ')]));
      if (action === 'intervention') {
        interventionUI.addNodes(ids);
      } else {
        const c = cfg();
        if (action === 'input') {
          const events = protocolEvents(c);
          events.push({
            body_ids: ids,
            start: 0,
            stop: Math.min(8, c.steps),
            amplitude: 1
          });
          c.input_events = events;
        } else {
          const observations = protocolObservations(c);
          if (observations.length >= 32) throw UI.error("spatial.spaceSend.observation_sets_32_160b4e", {});
          let name = UI.t("spatial.spaceSend.spaceselect_9508e8");
          while (observations.some(o => o.name === name)) name += ' +';
          observations.push({
            name,
            body_ids: ids,
            evaluation_window: {
              start: 0,
              stop: c.steps
            }
          });
          c.observations = observations;
          c.outputs = observations.map(o => o.name);
        }
        apply(c);
        changed();
      }
    }
    spaceStatus(UI.msg("spatial.spaceSend.select_edit_run_679644", {}));
  } catch (e) {
    spaceStatus(UI.errorText(e), true);
  }
}
function spaceSnapshot() {
  if (!spaceHeader) return null;
  return {
    source_index_id: spaceHeader.identity.source_index_id,
    coordinate_rule: spaceHeader.coordinate_rule,
    camera: globalSpace.exportState(),
    filter: spaceFilter,
    highlight_ids: spaceHighIds.slice(),
    selected_nodes: analysisSelection.ids(),
    focus_node: spaceFocusId,
    isolate: globalSpace.isolate,
    mode: $('space_mode').value,
    replay_id: spaceBoundReplay,
    state_step: spaceBoundReplay ? replayFrame?.state_step || 0 : 0,
    show_edges: globalSpace.edges.length > 0,
    edge_pairs: globalSpace.edges.map(e => [e.pre_id, e.post_id]),
    selected_edge: globalSpace.edges.some(e => e.edge_id === spaceEdgeId) ? spaceEdgeId : null,
    skeleton_ids: spaceSkeletonIds.slice(),
    geometry: window.skeletonStreaming?.snapshot() || undefined
  };
}
async function spaceRestore(state) {
  if (!state) return;
  const epoch = analysisOpenSequence,
    seq = ++spaceRestoreSequence,
    current = () => epoch === analysisOpenSequence && seq === spaceRestoreSequence;
  await spaceLoad();
  if (!current()) return;
  if (state.source_index_id !== spaceHeader.identity.source_index_id || JSON.stringify(state.coordinate_rule) !== JSON.stringify(spaceHeader.coordinate_rule)) throw UI.error("spatial.spaceRestore.space_9d5e1c", {});
  const filtered = state.filter ? await api('/api/spatial/filter', {
    source_index_id: state.source_index_id,
    ...state.filter
  }) : null;
  if (!current()) return;
  spaceFilter = state.filter;
  globalSpace.filterIds = filtered ? new Set(filtered.body_ids) : null;
  spaceHighIds = state.highlight_ids || [];
  globalSpace.setHighlight(spaceHighIds);
  await spaceSelect(state.selected_nodes || []);
  if (!current()) return;
  globalSpace.isolate = state.isolate;
  $('space_isolate').checked = state.isolate;
  globalSpace.importState(state.camera);
  $('space_mode').value = state.mode;
  if (state.focus_node) await spaceFocus(state.focus_node);else {
    spaceFocusId = null;
    spaceFocusData = null;
    globalSpace.setSelection(analysisSelection.ids(), null);
    UI.text($('space_focus_label'), '');
    UI.text($('space_node_detail'), '');
    $('space_node_summary')?.replaceChildren();
  }
  if (!current()) return;
  if (state.replay_id && replayResult?.ready) {
    await spaceBind();
    if (!current()) return;
    $('space_mode').value = state.mode;
    const step = replayResult.time_steps.indexOf(state.state_step);
    if (step < 0) throw UI.error("spatial.spaceRestore.savestate_stepnot_recorded_fb7b18", {});
    await readReplayFrame(step);
    if (!current()) return;
    globalSpace.importState(state.camera);
  } else spaceUnbind();
  if (state.show_edges && state.edge_pairs?.length) {
    await spaceShowEdges(state.edge_pairs);
    if (!current()) return;
    if (state.selected_edge) spaceSelectEdge(state.selected_edge);
  }
  if (!state.show_edges) {
    globalSpace.setEdges([]);
    spaceEdgeId = null;
    $('space_edge_rows').replaceChildren();
    UI.text($('space_edge_info'), '');
    UI.text($('space_edge_detail'), '');
  }
  if (state.skeleton_ids?.length) await spaceGeometry(state.skeleton_ids);else {
    spaceGeometrySequence++;
    spaceSkeletonIds = [];
    globalSpace.setSkeletons([]);
    UI.text($('space_geometry_status'), UI.msg("spatial.spaceRestore.message_106e68", {}));
  }
  if (!current()) return;
  if (state.geometry && window.skeletonStreaming) {
    await skeletonStreaming.restore(state.geometry);
    if (!current()) return;
  }
  globalSpace.styleAll();
  spaceSyncReplay();
  spaceStatus(state.replay_id && !spaceBoundReplay ? UI.msg("spatial.spaceRestore.space_replay_b9bb16", {}) : UI.msg("spatial.spaceRestore.spatial_session_restored_0628fa", {}));
}
window.spaceSnapshot = spaceSnapshot;
window.spaceRestore = spaceRestore;
const snapshotBeforeSpace = analysisSnapshot;
analysisSnapshot = () => {
  const state = snapshotBeforeSpace(),
    local = new Set((overview?.scope_nodes || []).map(n => String(n.bodyId)));
  state.selected_nodes = state.selected_nodes.filter(id => local.has(id));
  if (state.focus_node && !local.has(state.focus_node)) state.focus_node = null;
  const s = spaceSnapshot();
  if (s) state.spatial = s;
  return state;
};
const restoreBeforeSpace = analysisRestore;
analysisRestore = async (state, available) => {
  const epoch = analysisOpenSequence;
  await restoreBeforeSpace(state, available);
  if (epoch === analysisOpenSequence && state.spatial) await spaceRestore(state.spatial);
};
const graphBeforeSpace = renderReplayGraph;
renderReplayGraph = (...args) => {
  graphBeforeSpace(...args);
  spaceSyncReplay();
};
const oldAnalysisTabSpace = analysisTab;
analysisTab = view => {
  oldAnalysisTabSpace(view);
  if (view === 'spatial') {
    $('space_stage').scrollIntoView({
      block: 'center'
    });
    globalSpace.draw();
  }
};
const tab = document.createElement('button');
UI.text(tab, UI.msg("spatial.labels.space_3347e0", {}));
tab.dataset.analysisTab = 'spatial';
UI.attr(tab, 'role', 'tab');
tab.onclick = () => analysisTab('spatial');
$('analysis_workspace').querySelector('[role=tablist]').append(tab);
$('space_load').onclick = () => spaceLoad().catch(() => {});
$('space_fit').onclick = () => globalSpace.fit();
$('space_focus').onclick = () => {
  if (!globalSpace.fit(analysisSelection.ids().length ? analysisSelection.ids() : spaceFocusId ? [spaceFocusId] : spaceHighIds)) spaceStatus(UI.msg("spatial.controls.spatial_position_662a1e", {}), true);
};
$('space_expand').onclick = () => {
  const on = spatialPanel.classList.toggle('space-expanded');
  spatialPanel.style.cssText = on ? 'position:fixed;inset:12px;z-index:35;overflow:auto;background:var(--panel)' : '';
  $('space_canvas').style.height = on ? '65vh' : '480px';
  UI.text($('space_expand'), on ? UI.msg("spatial.controls.back_572cf4", {}) : UI.msg("spatial.controls.expand_00bd39", {}));
  globalSpace.draw();
};
$('space_clear').onclick = () => analysisSelection.clear();
$('space_clear_highlight').onclick = () => {
  spaceHighIds = [];
  globalSpace.setHighlight([]);
};
$('space_isolate').onchange = () => {
  globalSpace.isolate = $('space_isolate').checked;
  globalSpace.styleAll();
};
for (const [id, filter] of [['space_filter_highlight', false], ['space_filter', true]]) $(id).onclick = async () => {
  try {
    await spaceLoad();
    const def = {
      field: $('space_field').value,
      value: $('space_value').value
    };
    const r = await api('/api/spatial/filter', {
      source_index_id: spaceHeader.identity.source_index_id,
      ...def
    });
    if (filter) {
      spaceFilter = def;
      globalSpace.filterIds = new Set(r.body_ids);
      globalSpace.styleAll();
      spaceStatus(UI.msg("spatial.controls.filtered_members_positioned_e196e4", {
        p0: UI.numeric(r.member_count, {}),
        p1: UI.numeric(r.position_count, {})
      }));
    } else await spaceHighlight(r.body_ids, UI.msg("spatial.controls.highlight_annotation_68eafa", {}));
  } catch (e) {
    spaceStatus(UI.errorText(e), true);
  }
};
$('space_filter_clear').onclick = () => {
  spaceFilter = null;
  globalSpace.filterIds = null;
  globalSpace.styleAll();
};
$('space_group').onclick = async () => {
  try {
    await groupSelectMembers();
    if (!groupMemberSelection || groupMemberSelection.report_id !== groupReport?.report_id) throw UI.error("spatial.controls.select_memberscondition_07981b", {});
    await spaceHighlight(groupMemberSelection.body_ids, UI.msg("spatial.controls.highlight_all_group_members_17f9f0", {}));
  } catch (e) {
    spaceStatus(UI.errorText(e), true);
  }
};
$('space_query').onclick = async () => {
  try {
    await spaceLoad();
    const r = await api('/api/spatial/query', {
      source_index_id: spaceHeader.identity.source_index_id,
      filters: globalFilters()
    });
    await spaceHighlight(r.body_ids, UI.msg("spatial.controls.search_members_900124", {}));
  } catch (e) {
    spaceStatus(UI.errorText(e), true);
  }
};
$('space_select_group').onclick = () => spaceSelect(spaceHighIds, false);
$('space_scope').onclick = () => spaceHighlight((overview?.scope_nodes || []).map(n => String(n.bodyId)), UI.msg("spatial.controls.current_scope_35ba27", {}));
$('space_add_focus').onclick = () => {
  if (spaceFocusId) spaceSelect([spaceFocusId], true);
};
$('space_send').onclick = spaceSend;
$('space_neighbors').onclick = () => {
  if (!spaceFocusId || !spaceNeighbors) {
    spaceStatus(UI.msg("spatial.controls.node_11214f", {}), true);
    return;
  }
  spaceShowEdges([...spaceNeighbors.incoming.nodes.map(e => [e.node.bodyId, spaceFocusId]), ...spaceNeighbors.outgoing.nodes.map(e => [spaceFocusId, e.node.bodyId])]).catch(e => spaceStatus(UI.errorText(e), true));
};
$('space_path_edges').onclick = () => {
  if (!pathwayResult) {
    spaceStatus(UI.msg("spatial.controls.open_paths_f1de8d", {}), true);
    return;
  }
  spaceShowEdges(pathwayResult.edges.map(e => [e.body_pre, e.body_post])).catch(e => spaceStatus(UI.errorText(e), true));
};
$('space_no_edges').onclick = () => {
  spaceEdgesSequence++;
  globalSpace.setEdges([]);
  $('space_edge_rows').replaceChildren();
  UI.text($('space_edge_info'), '');
};
$('space_skeleton').onclick = () => {
  if (!spaceFocusId) {
    spaceStatus(UI.msg("spatial.controls.node_7ede4a", {}), true);
    return;
  }
  const ids = [...new Set([...spaceSkeletonIds, spaceFocusId])];
  if (ids.length > 8) {
    spaceStatus(UI.msg("spatial.controls.8_zoom_outselect_29c56b", {}), true);
    return;
  }
  spaceGeometry(ids);
};
$('space_skeleton_clear').onclick = () => {
  spaceGeometrySequence++;
  spaceSkeletonIds = [];
  globalSpace.setSkeletons([]);
  UI.text($('space_geometry_status'), UI.msg("spatial.controls.message_7ccbfb", {}));
};
$('space_bind').onclick = spaceBind;
$('space_mode').onchange = () => {
  if (spaceBoundReplay) spaceSyncReplay();else globalSpace.setActivity(null, 'structure', 1);
};
$('space_time').oninput = () => {
  spacePause();
  if (spaceBoundReplay === replayResult?.replay_id) readReplayFrame(Number($('space_time').value));
};
$('space_play').onclick = () => {
  if (spacePlaying) {
    spacePause();
    return;
  }
  if (spaceBoundReplay !== replayResult?.replay_id || !replayResult?.ready) {
    spaceStatus(UI.msg("spatial.controls.replay_88b628", {}), true);
    return;
  }
  UI.text($('space_play'), UI.msg("spatial.controls.pause_8d12fc", {}));
  spacePlaying = setInterval(() => {
    const next = Number($('space_time').value) + 1;
    if (next >= replayResult.time_steps.length) {
      spacePause();
      return;
    }
    readReplayFrame(next);
  }, 450);
};
$('space_to_replay').onclick = () => {
  analysisTab('replay');
  $('analysis_workspace').scrollIntoView({
    block: 'start'
  });
  if (spaceFocusId && replayResult?.nodes.some(n => n.body_id === spaceFocusId)) selectReplayNode(spaceFocusId, false, false);
};
$('space_save_scene').onclick = () => {
  analysisTab('spatial');
  saveAnalysisScene();
};
document.addEventListener('lab-analysis-selection', e => {
  if (e.detail.focus) spaceFocusId = e.detail.focus;
  spaceSelectionDisplay();
});
document.addEventListener('lab-case', () => {
  spaceRestoreSequence++;
  spaceSequence++;
  spaceGeometrySequence++;
  spaceUnbind();
  spaceFocusId = null;
  spaceFocusData = null;
  spaceNeighbors = null;
  spaceEdgeId = null;
  UI.text($('space_focus_label'), '');
  UI.text($('space_node_detail'), '');
  globalSpace.setScope((overview?.scope_nodes || []).map(n => String(n.bodyId)));
  globalSpace.setEdges([]);
  $('space_edge_rows').replaceChildren();
  UI.text($('space_edge_info'), '');
  spaceViewCounts();
});
document.addEventListener('click', e => {
  if (e.target.dataset.spaceNode) spaceFocus(e.target.dataset.spaceNode);
  if (e.target.dataset.spaceEdge) spaceSelectEdge(e.target.dataset.spaceEdge);
});
const groupSpaceButton = document.createElement('button');
UI.text(groupSpaceButton, UI.msg("spatial.labels.space_09c8c0", {}));
groupSpaceButton.onclick = () => {
  $('space_group').click();
  spatialPanel.scrollIntoView({
    block: 'start'
  });
};
$('group_apply_selection').parentElement.append(groupSpaceButton);
document.addEventListener('lab-replay-source', spaceUnbind);
document.addEventListener('lab-analysis-focus', e => {
  if (spaceHeader && e.detail.id && e.detail.id !== spaceFocusId) spaceFocus(e.detail.id);
});
document.addEventListener('lab-analysis-source-changing', () => {
  spaceRestoreSequence++;
  spaceSequence++;
  spaceGeometrySequence++;
  spaceUnbind();
});
$('space_event_edges').onclick = () => {
  if (!spaceBoundReplay || spaceBoundReplay !== replayResult?.replay_id) {
    spaceStatus(UI.msg("spatial.controls.message_50c2ad", {}), true);
    return;
  }
  const pairs = [...new Map((replayResult.config.experiment.intervention_events || []).filter(e => e.type === 'edge_gain' && e.enabled).flatMap(e => e.edges).map(p => [p.join('->'), p])).values()];
  spaceShowEdges(pairs).catch(e => spaceStatus(UI.errorText(e), true));
};
