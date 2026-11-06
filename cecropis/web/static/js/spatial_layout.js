"use strict";

/* Display-only assembly over existing controls, selection and replay APIs. */
(() => {
  const panel = document.getElementById('spatial_panel'),
    el = id => document.getElementById(id),
    loadButton = el('space_load');
  if (!panel) return;
  panel.querySelector('.rowtitle h2')?.remove();
  const shell = document.createElement('div');
  shell.className = 'spatial-workspace sidebar-closed';
  const main = document.createElement('div');
  main.className = 'spatial-main';
  const toolbar = document.createElement('div');
  toolbar.className = 'spatial-toolbar';
  const side = document.createElement('aside');
  side.className = 'spatial-sidebar';
  side.hidden = true;
  const button = (id, key) => {
    const e = document.createElement('button');
    e.type = 'button';
    e.id = id;
    e.dataset.i18n = key;
    e.textContent = UI.t(key);
    return e;
  };
  const fitButton = el('space_fit');
  fitButton.dataset.i18n = 'space.fitView';
  UI.text(fitButton, UI.msg('space.fitView'));
  const cameraTools=document.createElement('div');
  cameraTools.className='spatial-camera-tools';
  cameraTools.append(button('space_home', 'space.home'),fitButton,el('space_focus'));
  toolbar.append(cameraTools);
  const views = document.createElement('select');
  views.id = 'space_standard_view';
  UI.attr(views, 'aria-label', UI.msg('space.standardView'));
  for (const [value, label] of [['', 'XYZ'], ['xy', 'XY'], ['xz', 'XZ'], ['yz', 'YZ']]) views.append(new Option(label, value));
  views.onchange = () => {
    if (views.value) globalSpace.standardView(views.value);
  };
  const layers = button('space_layers', 'space.layers');
  layers.setAttribute('aria-expanded', 'false');
  cameraTools.append(views);
  const viewTools=document.createElement('div');
  viewTools.className='spatial-view-tools';
  viewTools.append(layers,el('space_expand'));
  toolbar.append(viewTools);
  layers.onclick = () => {
    side.hidden = !side.hidden;
    shell.classList.toggle('sidebar-closed', side.hidden);
    layers.setAttribute('aria-expanded', String(!side.hidden));
    globalSpace.draw();
  };
  const stage = el('space_stage');
  for (const e of [stage, el('space_canvas'), el('space_frame_label'), el('space_focus_label'), el('space_box')]) e.removeAttribute('style');
  const axes = document.createElement('div');
  axes.id = 'space_axes';
  axes.innerHTML = '<svg width="72" height="72" viewBox="0 0 72 72" aria-label="XYZ"><g id="space_axis_lines"></g></svg>';
  stage.append(axes);
  const redrawAxes = () => {
    const c = globalSpace.camera;
    const xyz = [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
      colors = ['#cf6262', '#3b9670', '#558fbd'];
    el('space_axis_lines').innerHTML = xyz.map((p, i) => {
      const x = Math.cos(c.yaw) * p[0] + Math.sin(c.yaw) * p[2],
        z = -Math.sin(c.yaw) * p[0] + Math.cos(c.yaw) * p[2],
        y = Math.cos(c.pitch) * p[1] - Math.sin(c.pitch) * z;
      return `<line x1="32" y1="40" x2="${32 + x * 24}" y2="${40 - y * 24}" stroke="${colors[i]}"/><text x="${32 + x * 29}" y="${40 - y * 29}" fill="${colors[i]}">${'XYZ'[i]}</text>`;
    }).join('');
  };
  const oldRender = globalSpace.callbacks.render;
  globalSpace.callbacks.render = () => {
    oldRender?.();
    redrawAxes();
  };
  const timeline = document.createElement('div');
  timeline.className = 'spatial-timeline';
  const replayControls = el('space_mode').closest('.buttons'),
    timeLabel = el('space_time').closest('label');
  timeline.append(replayControls, timeLabel);
  main.append(toolbar, stage, timeline);
  shell.append(main, side);
  const remaining = [...panel.children];
  panel.append(shell);
  for (const e of remaining) {
    if (e.contains(stage) || e.classList.contains('rowtitle')) continue;
    side.append(e);
  }
  const status = el('space_status');
  status.className = 'spatial-status';
  main.append(status);
  panel.replaceChildren(shell);
  // Controls extracted from old toolbar remain available in the layers panel.
  const loadRow = document.createElement('div');
  loadRow.className = 'buttons';
  loadRow.append(loadButton, el('space_tool').closest('.buttons'));
  side.prepend(loadRow);
  el('space_load').hidden = !!spaceHeader;
  const coverage = document.createElement('details'),
    caption = document.createElement('summary');
  caption.dataset.i18n = 'space.coverage';
  caption.textContent = UI.t('space.coverage');
  coverage.append(caption);
  for (const id of ['space_coverage', 'space_context', 'space_geometry_coverage', 'space_geometry_status', 'space_activity_info']) if (el(id)) coverage.append(el(id));
  side.append(coverage);
  el('space_geom_radius_scale').closest('label').hidden = true;
  const points = document.createElement('label');
  points.innerHTML = '<input id="space_points_layer" type="checkbox"><span data-i18n="space.points"></span>';
  side.prepend(points);
  el('space_points_layer').onchange = () => {
    globalSpace.showPoints = el('space_points_layer').checked;
    spaceCountRevision = -1;
    globalSpace.draw();
  };
  globalSpace.showPoints = false;
  const links = document.createElement('label');
  links.innerHTML = '<input id="space_links_layer" type="checkbox"><span data-i18n="space.links"></span>';
  side.prepend(links);
  el('space_links_layer').onchange = () => {
    globalSpace.showConnections = el('space_links_layer').checked;
    globalSpace.draw();
  };
  globalSpace.showConnections = false;
  el('space_home').onclick = () => globalSpace.home();
  el('space_expand').onclick = () => {
    const on = panel.classList.toggle('space-expanded');
    UI.text(el('space_expand'), UI.msg(on ? 'action.back' : 'space.expand'));
    globalSpace.draw();
  };
  window.spaceEnter = async () => {
    try {
      await spaceLoad();
      el('space_load').hidden = true;
      if (!skeletonStreaming.manifest) await skeletonLoad();
      else {
        // Navigation cancels a pending view query. Re-enter even at the same
        // camera must resume it, rather than keeping a stale camera key.
        skeletonStreaming.cameraKey = '';
        skeletonStreaming.cameraChanged();
      }
    } catch (e) {
      spaceStatus(UI.errorText(e), true);
    }
  };
  const beforeSnapshot = spaceSnapshot;
  spaceSnapshot = () => {
    const state = beforeSnapshot();
    if (state) state.display_layers = {
      points: globalSpace.showPoints,
      connections: globalSpace.showConnections,
      sidebar: !side.hidden
    };
    return state;
  };
  const beforeRestore = spaceRestore;
  spaceRestore = async state => {
    await beforeRestore(state);
    if (state?.display_layers) {
      globalSpace.showPoints = !!state.display_layers.points;
      globalSpace.showConnections = state.display_layers.connections !== false;
      el('space_points_layer').checked = globalSpace.showPoints;
      el('space_links_layer').checked = globalSpace.showConnections;
      side.hidden = !state.display_layers.sidebar;
      shell.classList.toggle('sidebar-closed', side.hidden);
      layers.setAttribute('aria-expanded', String(!side.hidden));
      globalSpace.draw();
    }
  };
  UI.apply(side);
  const beforePick = globalSpace.callbacks.pick;
  globalSpace.callbacks.pick = (...args) => {
    beforePick?.(...args);
    side.hidden = false;
    shell.classList.remove('sidebar-closed');
    layers.setAttribute('aria-expanded', 'true');
    globalSpace.draw();
  };
  for (const option of el('local_tasks_filter').options) if (localLabels[option.value]) UI.text(option, localLabels[option.value]);
  for (const id of ['search_cancel', 'operation_cancel', 'local_cancel', 'space_geom_cancel']) el(id)?.classList.add('danger');
  if (window.workspaceShell?.current() === 'space') window.spaceEnter();
})();
