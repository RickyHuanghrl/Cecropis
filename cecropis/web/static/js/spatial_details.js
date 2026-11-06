"use strict";

/* Focus and neighborhood pages are display state, separate from shared selection. */
let spaceNeighborSequence = 0;
let spaceNeighborDirection = 'incoming';
function renderSpaceNodeSummary() {
  if (!spaceFocusData || !workElement('space_node_summary')) return;
  const node = spaceFocusData, point = globalSpace.position(spaceFocusId);
  const index = globalSpace.idIndex.get(spaceFocusId);
  const rawKind = globalSpace.vertexIndex?.[index] >= 0 ? spaceHeader?.coordinate_kinds[globalSpace.kinds[index]] : null;
  const kind = rawKind ? UI.t(rawKind === 'soma' ? 'use.soma' : 'use.cutEnd') : UI.t('spatial.spaceFocus.skeleton_bounding_box_center_navigation_6a1f91');
  workElement('space_node_summary').innerHTML = `<strong data-user-text>${UI.html(node.name || node.instance || node.type || spaceFocusId)}</strong><div class="node-identity"><span class="body-id">body ID ${UI.html(spaceFocusId)}</span><button type="button" class="small" data-copy-body="${esc(spaceFocusId)}">${UI.htmlText('spatial.detail.copy')}</button><span>${UI.html(node.type || '')}</span></div><dl class="node-values"><div><dt>${UI.htmlText('spatial.detail.position')}</dt><dd>${point ? point.map(v => UI.number(v,{maximumFractionDigits:2})).join(', ') + ' µm' : UI.htmlText('spatial.spaceFocus.no_spatial_position_b5530e')}</dd></div><div><dt>${UI.htmlText('spatial.detail.reference')}</dt><dd>${UI.html(kind)}</dd></div></dl>`;
  spaceUpdateFocusValue();
}
function renderSpaceNeighborLists() {
  const host = workElement('space_neighbor_lists');
  if (!host || !spaceNeighbors) return;
  host.innerHTML = '<div class="buttons">' + ['incoming', 'outgoing'].map(direction => '<button type="button" data-neighbor-direction="' + direction + '" aria-pressed="' + (direction === spaceNeighborDirection) + '">' + UI.htmlText(direction === 'incoming' ? 'use.upstream' : 'use.downstream') + ' (' + UI.htmlNumber(UI.numeric(spaceNeighbors[direction].edge_count)) + ')</button>').join('') + '</div>' + [spaceNeighborDirection].map(direction => {
    const page = spaceNeighbors[direction],
      offset = page.offset || 0;
    return `<section class="neighbor-section"><h3>${UI.htmlText(direction === 'incoming' ? 'use.upstream' : 'use.downstream')}</h3><div class="note">${UI.htmlText('use.neighborPage', {
      start: UI.numeric(page.nodes.length ? offset + 1 : 0),
      stop: UI.numeric(offset + page.nodes.length),
      total: UI.numeric(page.edge_count)
    })}</div><div class="tablewrap"><table class="neighbor-table"><thead><tr><th>${UI.htmlText('use.name')}</th><th>body ID</th><th>${UI.htmlText('use.contacts')}</th><th>${UI.htmlText('comparison.actions')}</th></tr></thead><tbody>${page.nodes.map(edge => `<tr><td><button type="button" class="linkbtn" data-neighbor-focus="${esc(edge.node.bodyId)}">${UI.html(edge.node.type || edge.node.name || edge.node.instance || UI.t('spatial.controls.unannotated_8f0a5a'))}</button></td><td class="body-id">${UI.html(edge.node.bodyId)}</td><td class="numeric-cell">${UI.htmlNumber(UI.numeric(edge.weight))}</td><td><button type="button" class="small" data-neighbor-add="${esc(edge.node.bodyId)}" ${UI.htmlAttribute("aria-label", 'use.add')}>+</button></td></tr>`).join('') || '<tr><td colspan="4">' + UI.htmlText('use.emptyNeighbors') + '</td></tr>'}</tbody></table></div><div class="neighbor-pagination"><button type="button" data-neighbor-page="${direction}" data-offset="${Math.max(0, offset - 20)}" ${offset === 0 ? 'disabled' : ''}>${UI.htmlText('use.previous')}</button><button type="button" data-neighbor-page="${direction}" data-offset="${offset + 20}" ${offset + page.nodes.length >= page.edge_count ? 'disabled' : ''}>${UI.htmlText('use.next')}</button></div></section>`;
  }).join('');
}
async function spaceNeighborPage(direction, offset) {
  const focused = spaceFocusId,
    epoch = spaceSequence,
    seq = ++spaceNeighborSequence;
  try {
    const result = await api('/api/global/neighbors?' + new URLSearchParams({
      id: focused,
      direction,
      limit: 20,
      offset
    }));
    if (epoch !== spaceSequence || seq !== spaceNeighborSequence || spaceFocusId !== focused) return;
    spaceNeighbors[direction] = result;
    renderSpaceNeighborLists();
  } catch (error) {
    if (epoch === spaceSequence) spaceStatus(UI.errorText(error), true);
  }
}
document.addEventListener('click', event => {
  const copy=event.target.closest('[data-copy-body]');
  if (copy) {
    navigator.clipboard.writeText(copy.dataset.copyBody).then(()=>UI.text(copy,UI.msg('spatial.detail.copied'))).catch(error=>spaceStatus(UI.errorText(error),true));
    return;
  }
  const target = event.target.closest('[data-neighbor-focus],[data-neighbor-add],[data-neighbor-page],[data-neighbor-direction]');
  if (!target) return;
  if (target.dataset.neighborFocus) spaceFocus(target.dataset.neighborFocus);
  if (target.dataset.neighborAdd) spaceSelect([target.dataset.neighborAdd], true);
  if (target.dataset.neighborPage) spaceNeighborPage(target.dataset.neighborPage, Number(target.dataset.offset));
  if (target.dataset.neighborDirection) {
    spaceNeighborDirection = target.dataset.neighborDirection;
    renderSpaceNeighborLists();
  }
});
(() => {
  const side = document.querySelector('.spatial-sidebar'),
    node = workElement('space_detail');
  const layer = document.createElement('div');
  layer.id = 'space_layers_content';
  for (const child of [...side.children]) if (child !== node) layer.append(child);
  const tabs = document.createElement('div');
  tabs.className = 'space-detail-tabs';
  const nodeTab = workButton('use.nodeDetails', () => pane('node')),
    layerTab = workButton('use.layers', () => pane('layers'));
  nodeTab.id = 'space_node_tab';
  layerTab.id = 'space_layer_tab';
  tabs.append(nodeTab, layerTab);
  side.append(tabs, node, layer);
  node.open = true;
  node.querySelector('summary').hidden = true;
  function pane(name) {
    side.hidden = false;
    side.parentElement.classList.remove('sidebar-closed');
    node.hidden = name !== 'node';
    layer.hidden = name !== 'layers';
    nodeTab.setAttribute('aria-selected', String(name === 'node'));
    layerTab.setAttribute('aria-selected', String(name === 'layers'));
    workElement('space_layers').setAttribute('aria-expanded', 'true');
    globalSpace.draw();
  }
  window.spaceOpenDetails = () => pane('node');
  document.addEventListener('lab-case', () => workElement('space_node_summary')?.replaceChildren());
  workElement('space_layers').onclick = () => {
    if (!side.hidden && !layer.hidden) {
      side.hidden = true;
      side.parentElement.classList.add('sidebar-closed');
      workElement('space_layers').setAttribute('aria-expanded', 'false');
      globalSpace.draw();
    } else pane('layers');
  };
  const originalPick = globalSpace.callbacks.pick;
  globalSpace.callbacks.pick = (...args) => {
    originalPick(...args);
    pane('node');
  };
  workElement('space_append').checked = false;
  UI.text(workElement('space_node_detail'), UI.msg('use.focusHint'));
  const identity = document.createElement('p');
  identity.id = 'space_shared_count';
  identity.className = 'note';
  node.prepend(identity);
  const summary = document.createElement('div');
  summary.id = 'space_node_summary';
  node.insertBefore(summary, workElement('space_node_detail'));
  const actions = document.createElement('div');
  actions.className = 'space-primary-actions';
  actions.append(workElement('space_add_focus'), workButton('use.fromSelection', () => workScopeFromSelection()), workButton('use.toIntervention', async () => {
    if (busy) return;
    const before = JSON.stringify(cfg());
    workElement('space_handoff').value = 'intervention';
    await spaceSend();
    if (JSON.stringify(cfg()) !== before) workConfig();
  }));
  node.insertBefore(actions, workElement('space_node_detail'));
  workElement('space_add_focus').onclick = () => {
    if (!spaceFocusId) return;
    if (analysisSelection.ids().includes(spaceFocusId)) analysisSelection.remove(spaceFocusId);else spaceSelect([spaceFocusId], true);
  };
  workElement('space_neighbors').dataset.i18n = 'use.neighborEdges';
  const settings = workSection('use.layers');
  layer.prepend(settings);
  const geometry = workElement('space_geom_input').closest('details');
  geometry.querySelector('summary').dataset.i18n = 'use.maintenance';
  geometry.open = false;
  const extra = document.createElement('div');
  extra.id = 'space_geometry_extra';
  geometry.append(extra);
  for (const id of ['space_points_layer', 'space_links_layer', 'space_geom_enabled', 'space_geom_diameter', 'space_geom_background', 'space_geom_quality']) settings.append(workElement(id).closest('label'));
  const color = document.createElement('div');
  color.id = 'space_color_scale';
  color.className = 'space-color-scale';
  document.querySelector('.spatial-timeline').append(color);
  document.querySelector('.spatial-view-tools').append(workElement('space_save_scene'));
  workElement('space_save_scene').dataset.i18n = 'action.saveScene';
  const primaryNote = node.querySelector('#space_shape_status');
  if (primaryNote) geometry.append(primaryNote);
  let lastSignature = '';
  let sharedIds = analysisSelection.ids(),
    selectionSignature = '';
  function update(force = false) {
    const ids = sharedIds,
      included = ids.includes(spaceFocusId),
      nextSelection = ids.length + '|' + spaceFocusId + '|' + included;
    if (force || nextSelection !== selectionSignature) {
      selectionSignature = nextSelection;
      UI.text(identity, UI.msg('use.selectedCount', {
        count: UI.numeric(ids.length)
      }));
      workElement('space_add_focus').disabled = !spaceFocusId;
      UI.text(workElement('space_add_focus'), UI.msg(included ? 'use.remove' : 'use.add'));
    }
    workElement('space_focus_label').hidden = !workElement('space_focus_label').textContent.trim();
    const active = !!spaceBoundReplay && replayResult?.ready && replayFrame;
    const summary = typeof responseSpaceSummary !== 'undefined' && responseSpaceSummary;
    const structural = workElement('space_mode').value === 'structure';
    workElement('space_play').hidden = !active || structural;
    workElement('space_time').closest('label').hidden = !active || structural;
    workElement('space_to_replay').hidden = !active;
    workElement('space_bind').hidden = !replayResult?.ready || active;
    workElement('space_frame_label').hidden = !active || structural;
    if (active && !structural) {
      const frameText = UI.t('use.activity') + ' · x(' + replayFrame.state_step + ')';
      if (workElement('space_frame_label').textContent !== frameText) UI.text(workElement('space_frame_label'), frameText);
    }
    color.hidden = structural || !active && !summary;
    const signature = [structural, !!active, !!summary, globalSpace.mode, globalSpace.domain, UI.preferences.language].join('|');
    if (signature !== lastSignature || force) {
      lastSignature = signature;
      const d = globalSpace.domain || 1,
        delta = globalSpace.mode === 'delta';
      const rgb = value => 'rgb(' + spatialActivityColor(value, d, globalSpace.mode).map(v => Math.round(v * 255)).join(',') + ')';
      const gradient = delta ? 'linear-gradient(90deg,' + rgb(-d) + ',' + rgb(-d * 1e-12) + ' 49.8%,' + rgb(0) + ' 50.2%,' + rgb(d) + ')' : 'linear-gradient(90deg,' + rgb(0) + ',' + rgb(d) + ')';
      color.innerHTML = '<div><div class="space-color-ramp" style="background:' + gradient + '"></div><div class="space-color-values"><span>' + UI.htmlNumber(UI.value(delta ? -d : 0)) + '</span><span>' + UI.htmlNumber(UI.value(delta ? 0 : d)) + '</span>' + (delta ? '<span>' + UI.htmlNumber(UI.value(d)) + '</span>' : '') + '</div></div><span><i class="missing-swatch"></i> ' + UI.htmlText('use.missingActivity') + '</span><span>' + UI.htmlText('use.knownZero') + '</span>';
    }
  }
  const oldRender = globalSpace.callbacks.render;
  globalSpace.callbacks.render = () => {
    oldRender?.();
    update();
  };
  for (const event of ['lab-analysis-selection', 'lab-artifact-open', 'ui-language']) document.addEventListener(event, () => {
    if (event === 'lab-analysis-selection') sharedIds = analysisSelection.ids();
    update(true);
      if (event === 'ui-language') { renderSpaceNeighborLists(); renderSpaceNodeSummary(); }
  });
  workElement('space_mode').addEventListener('change', () => update(true));
  node.hidden = false;
  layer.hidden = true;
  update(true);
  UI.apply(side);
})();
