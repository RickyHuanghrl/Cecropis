"use strict";

/* One display router moves existing controls once; it owns no computational state. */
(() => {
  'use strict';

  const el = id => document.getElementById(id),
    make = (tag, cls) => {
      const e = document.createElement(tag);
      if (cls) e.className = cls;
      return e;
    };
  const header = document.querySelector('header');
  header.className = 'app-header';
  header.replaceChildren();
  const title = make('h1');
  title.dataset.i18n = 'nav.workspace';
  // The page owns its title; the top bar contains scope/result/selection context.
  const preferences = make('div', 'preference-controls');
  for (const [id, key, values, current] of [['ui_language', 'preference.language', [['zh-CN', '简体中文'], ['en', 'English'], ['ja', '日本語'], ['fr', 'Français'], ['de', 'Deutsch'], ['es', 'Español']], UI.preferences.language], ['ui_theme', 'preference.theme', [['light', 'theme.menuLight'], ['dark', 'theme.menuDark'], ['system', 'theme.menuSystem']], UI.preferences.theme]]) {
    const label = make('label');
    const text = make('span');
    text.dataset.i18n = key;
    label.append(text);
    const select = make('select');
    select.id = id;
    UI.attr(select, 'aria-label', UI.msg(key));
    for (const [value, caption] of values) {
      const option = make('option');
      option.value = value;
      if (id === 'ui_language') {
        option.lang = value;
        UI.text(option, caption);
        option.dataset.userText = 'true';
      } else {
        option.dataset.i18n = caption;
        UI.text(option, UI.msg(caption));
      }
      select.append(option);
    }
    select.value = current;
    select.onchange = () => id === 'ui_language' ? UI.language(select.value) : UI.setTheme(select.value);
    label.append(select);
    preferences.append(label);
  }
  header.append(preferences);
  const layout = make('div', 'app-layout'),
    nav = make('nav', 'app-nav'),
    content = make('div', 'app-content');
  UI.attr(nav, 'aria-label', UI.msg('nav.navigation'));
  layout.append(nav, content);
  header.after(layout);
  const context = make('div', 'context-bar');
  context.innerHTML = '<div class="context-item"><span data-i18n="context.scope"></span><strong id="shell_scope" data-user-text></strong></div><div class="context-item"><span data-i18n="context.result"></span><strong id="shell_result" data-user-text></strong></div><div class="context-item"><span data-i18n="context.selection"></span><strong id="shell_selection"></strong></div><button id="shell_save" data-i18n="action.saveScene"></button><button id="shell_history" data-i18n="action.openHistory"></button>';
  header.prepend(context);
  nav.id = 'workspace_navigation';
  const brand = make('a', 'brand-wordmark');
  brand.href = '#library';
  brand.textContent = 'Cecropis';
  brand.onclick = event => { event.preventDefault(); navigate('library'); };
  nav.append(brand);
  const toggle = make('button', 'nav-toggle');
  toggle.type = 'button';
  toggle.textContent = '☰';
  UI.attr(toggle, 'aria-controls', nav.id);
  UI.attr(toggle, 'aria-expanded', 'false');
  UI.attr(toggle, 'aria-label', UI.msg('nav.navigation'));
  header.prepend(toggle);
  const backdrop = make('button', 'nav-backdrop');
  backdrop.type = 'button';
  UI.attr(backdrop, 'aria-label', UI.msg('action.back'));
  layout.append(backdrop);
  const drawer = open => {
    document.body.classList.toggle('nav-open', open);
    UI.attr(toggle, 'aria-expanded', String(open));
    nav.inert = matchMedia('(max-width:850px)').matches && !open;
  };
  toggle.onclick = () => drawer(!document.body.classList.contains('nav-open'));
  backdrop.onclick = () => drawer(false);
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && document.body.classList.contains('nav-open')) {
      drawer(false);
      toggle.focus();
    }
  });
  matchMedia('(max-width:850px)').addEventListener('change', () => drawer(false));
  drawer(false);
  const stages = make('div');
  content.append(stages);
  const scope = el('scope_workspace');
  scope.className = 'scope-pages';
  stages.append(scope);
  const pages = new Map(),
    buttons = new Map();
  let current = 'library',
    history = [];
  const definitions = [['browse', 'nav.browse', [['library', 'nav.library'], ['query', 'nav.query'], ['groups', 'nav.groups'], ['space', 'nav.space'], ['scope', 'nav.scope']]], ['compute', 'nav.compute', [['protocol', 'nav.protocol'], ['compare', 'nav.compare'], ['search', 'nav.search'], ['responses', 'nav.responses'], ['tasks', 'nav.tasks']]], ['analyze', 'nav.analyze', [['analysis', 'nav.analysis'], ['signals', 'nav.signals'], ['ranges', 'nav.ranges']]]];
  const scopePages = new Set(['protocol', 'compare', 'search', 'responses', 'analysis', 'signals', 'ranges']);
  for (const [group, key, items] of definitions) {
    const section = make('section', 'nav-group'),
      h = make('h2');
    h.dataset.i18n = key;
    section.append(h);
    const list = make('div');
    section.append(list);
    nav.append(section);
    for (const [id, label] of items) {
      const button = make('button');
      button.type = 'button';
      button.dataset.i18n = label;
      button.onclick = () => navigate(id);
      list.append(button);
      buttons.set(id, button);
      const page = make('section', 'workspace-page');
      page.id = 'page_' + id;
      page.hidden = true;
      const heading = make('div', 'workspace-page-title'),
        h2 = make('h2');
      h2.dataset.i18n = label;
      heading.append(h2);
      const back = make('button');
      back.dataset.i18n = 'action.back';
      back.onclick = () => {
        const previous = history.pop();
        if (previous) navigate(previous, false);
      };
      heading.append(back);
      page.append(heading);
      (scopePages.has(id) ? scope : stages).append(page);
      pages.set(id, page);
    }
  }
  const move = (id, page, unwrap = false) => {
    const node = typeof id === 'string' ? el(id) : id;
    if (!node) return;
    if (unwrap && node.tagName === 'DETAILS') {
      node.open = true;
      node.dataset.shellPrimary = 'true';
    }
    pages.get(page).append(node);
  };
  const global = el('global_panel'),
    query = el('global_q').closest('details'),
    range = el('scope_ids').closest('details');
  move(query, 'query', true);
  move('group_panel', 'groups', true);
  move(range, 'scope', true);
  move('spatial_panel', 'space');
  move('local_tasks_area', 'tasks', true);
  move(global, 'library');
  move('task_definition_controls', 'library', true);
  const path = el('pathway_panel');
  move(path, 'scope', true);
  const workspaceDetails = make('details', 'workspace-context-details');
  const summary = make('summary');
  summary.dataset.i18n = 'action.workspaceDetails';
  workspaceDetails.append(summary, el('workspace_status'));
  const readiness = make('section');readiness.id='workspace_preparation';
  const refreshReadiness = make('button');refreshReadiness.type='button';refreshReadiness.dataset.i18n='prep.check';
  refreshReadiness.onclick=async()=>{
    refreshReadiness.disabled=true;
    try{DataPreparation.render(readiness,await api('/api/preparation'));}
    catch(error){UI.text(readiness,UI.errorText(error));}
    finally{refreshReadiness.disabled=false;}
  };
  workspaceDetails.append(refreshReadiness,readiness);
  const dataSettings=make('button');dataSettings.type='button';dataSettings.dataset.i18n='prep.title';dataSettings.id='workspace_data_settings';
  dataSettings.onclick=()=>{
    if(window.workflowDraftEdited && !confirm(UI.t('binding.unsaved')))return;
    location.assign('/data-settings');
  };
  workspaceDetails.append(dataSettings);
  if(typeof workspaceState!=='undefined' && workspaceState?.preparation)DataPreparation.render(readiness,workspaceState.preparation);
  global.append(workspaceDetails);
  const controls = scope.querySelector('.controls');
  const grid = make('div', 'configure-grid');
  pages.get('protocol').append(grid);
  if (controls) grid.append(controls);
  const editors = make('div');
  grid.append(editors);
  editors.append(el('protocol_panel'));
  editors.append(el('intervention_editor'));
  const sourceDetails = make('details', 'source-details'),
    sourceCaption = make('summary');
  sourceCaption.dataset.i18n = 'analysis.definition';
  const sourceInfo = make('pre');
  sourceInfo.id = 'analysis_source_details';
  sourceDetails.append(sourceCaption, sourceInfo);
  el('analysis_context').after(sourceDetails);
  move('analysis_workspace', 'analysis');
  move('signal_panel', 'signals');
  move('scope_comparison_panel', 'ranges');
  move('analysis_responses', 'responses');
  const oldAnalysisTab = analysisTab;
  analysisTab = function (view) {
    oldAnalysisTab(view);
    navigate(view === 'responses' ? 'responses' : view === 'spatial' ? 'space' : 'analysis');
  };
  // Stable host IDs from older modules remain available after these DOM moves.
  const main = scope.querySelector('main');
  const comparisonPanel = el('condition_name')?.closest('section');
  comparisonPanel?.querySelector('h2')?.remove();
  comparisonPanel?.querySelector('h2')?.remove();
  move(comparisonPanel, 'compare');
  const resultTitle = el('charts')?.previousElementSibling;
  if (resultTitle?.classList.contains('resultshead')) move(resultTitle, 'compare');
  move('charts', 'compare');
  for (const node of [...(main?.children || [])]) {
    if (node.id === 'geometry_panel') {
      node.hidden = true;
      continue;
    }
    if (['search_panel', 'joint_search_panel', 'timing_panel'].includes(node.id)) continue;
    if (node.querySelector('#edges')) {
      el('analysis_connections').append(node);
      continue;
    }
    if (node.querySelector('#flow')) {
      const info = make('details', 'scope-summary');
      const caption = make('summary');
      UI.text(caption, UI.msg("workspace.shell.controls.compute_scope_overview_24d756", {}));
      info.append(caption, node);
      el('analysis_connections').append(info);
      continue;
    }
    move(node, 'analysis');
  }
  const searchTools = make('div');
  searchTools.id = 'shell_search_tools';
  const toolSelect = make('select', 'tool-select');
  toolSelect.id = 'shell_search_select';
  UI.attr(toolSelect, 'aria-label', UI.msg('nav.search'));
  const searchItems = [['operation_search_area', 'tool.operations'], ['search_panel', 'tool.nodes'], ['joint_search_panel', 'tool.joint'], ['timing_panel', 'tool.timing']];
  for (const [id, key] of searchItems) {
    const node = el(id);
    if (!node) continue;
    const option = make('option');
    option.value = id;
    option.dataset.i18n = key;
    UI.text(option, UI.msg(key));
    toolSelect.append(option);
    searchTools.append(node);
    if (node.tagName === 'DETAILS') node.open = true;
  }
  pages.get('search').append(toolSelect, searchTools);
  const chooseTool = () => {
    for (const [id] of searchItems) if (el(id)) el(id).hidden = id !== toolSelect.value;
  };
  toolSelect.onchange = chooseTool;
  chooseTool();
  const openSearchTool = id => {
    if (!searchItems.some(([key]) => key === id)) return;
    toolSelect.value = id;
    toolSelect.dispatchEvent(new Event('change'));
    if (el(id)?.tagName === 'DETAILS') el(id).open = true;
    el(id)?.scrollIntoView({block: 'start'});
  };
  const empty = make('section', 'shell-empty');
  empty.id = 'shell_no_scope';
  empty.innerHTML = '<h3 data-i18n="empty.scope"></h3><div class="buttons"><button data-route="library" data-i18n="action.openScope"></button><button data-route="scope" data-i18n="action.buildScope"></button></div>';
  empty.hidden = true;
  stages.append(empty);
  for (const button of empty.querySelectorAll('[data-route]')) button.onclick = () => navigate(button.dataset.route);
  const libraryEmpty = make('div', 'shell-empty');
  libraryEmpty.id = 'shell_no_results';
  libraryEmpty.innerHTML = '<h3 data-i18n="empty.results"></h3><div class="buttons"><button data-route="query" data-i18n="nav.query"></button><button data-route="space" data-i18n="nav.space"></button><button data-route="scope" data-i18n="action.buildScope"></button></div>';
  global.append(libraryEmpty);
  for (const b of libraryEmpty.querySelectorAll('button')) b.onclick = () => navigate(b.dataset.route);
  el('shell_history').onclick = () => navigate('library');
  el('shell_save').onclick = () => {
    navigate('analysis');
    const details = el('analysis_save_controls');
    if (details) details.open = true;
    const name = el('analysis_name');
    if (name && !name.value.trim()) {
      name.focus();
      return;
    }
    el('analysis_save').click();
  };
  function navigate(id, remember = true) {
    drawer(false);
    if (!pages.has(id)) return;
    if (remember && current !== id) history.push(current);
    current = id;
    for (const [key, page] of pages) {
      page.hidden = key !== id;
      UI.attr(buttons.get(key), 'aria-current', key === id ? 'page' : 'false');
    }
    empty.hidden = !(scopePages.has(id) && !window.shellHasScope);
    title.dataset.i18n = definitions.flatMap(d => d[2]).find(item => item[0] === id)[1];
    document.title = 'Cecropis · ' + UI.t(title.dataset.i18n);
    contextUpdate();
    if (id === 'responses') el('analysis_responses').hidden = false;
    if (id === 'compare' && typeof renderUnifiedCurves === 'function') renderUnifiedCurves();
    try {
      localStorage.setItem('workspace-view-v1', id);
    } catch {}
    if (id === 'space' && typeof globalSpace !== 'undefined') {
      globalSpace.draw?.();
      window.spaceEnter?.();
    }
    if (id !== 'space' && typeof skeletonStreaming !== 'undefined') {
      clearTimeout(skeletonStreaming.timer);
      skeletonStreaming.viewRequest?.abort();
    }
    if (id === 'analysis') {
      window.replayTopology?.resize?.();
      window.pathwayTopology?.resize?.();
    }
    UI.apply();
    window.scrollTo({
      top: 0,
      behavior: 'instant'
    });
  }
  function contextUpdate() {
    window.shellHasScope = typeof overview !== 'undefined' && !!overview;
    const manifest = window.shellHasScope ? overview.manifest : null;
    UI.text(el('shell_scope'), manifest ? manifest.case_name || manifest.case_id : UI.t('empty.scope'));
    const source = typeof analysisCurrent !== 'undefined' ? analysisCurrent : null;
    const artifact = source && savedArtifactCatalog.find(item => item.id === source.source?.artifact_id);
    const label = source ? artifact ? artifact.label === artifact.id ? UI.format(savedKindLabels[artifact.kind] || artifact.kind) : artifact.label : source.label || UI.t('status.loaded') : UI.t('empty.noResult');
    const replaySource = source?.source?.artifact_id && source.source.artifact_id === source.references?.replay?.artifact_id && typeof replayResult !== 'undefined' ? replayResult?.config?.source : null;
    const condition = source?.source?.condition_name || artifact?.config?.source?.condition_name || replaySource?.condition_name;
    UI.text(el('shell_result'), UI.join([label, ...(condition ? [' · ', condition] : [])]));
    if (current === 'compare' && typeof comparison !== 'undefined' && comparison?.rows?.[comparisonFocusIndex]) {
      UI.text(el('shell_result'), UI.join([UI.msg('nav.compare'), ' · ', UI.name(comparison.rows[comparisonFocusIndex])]));
    }
    UI.text(el('shell_selection'), UI.number(window.analysisSelection?.ids().length || 0));
    el('shell_save').disabled = !source;
    empty.hidden = !(scopePages.has(current) && !window.shellHasScope);
    libraryEmpty.hidden = typeof savedArtifactCatalog !== 'undefined' && savedArtifactCatalog.length > 0;
  }
  // Existing entry points request scrolling; reveal their original page first.
  const scroll = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = function (...args) {
    const page = this.closest('.workspace-page');
    if (page) {
      if (this.closest('#shell_search_tools')) {
        const node = this.closest('#operation_search_area,#search_panel,#joint_search_panel,#timing_panel');
        if (node) {
          toolSelect.value = node.id;
          chooseTool();
        }
      }
      navigate(page.id.slice(5));
    }
    return scroll.apply(this, args);
  };
  document.addEventListener('lab-case', contextUpdate);
  document.addEventListener('lab-workspace', contextUpdate);
  document.addEventListener('lab-analysis-selection', contextUpdate);
  document.addEventListener('lab-result', contextUpdate);
  document.addEventListener('ui-language', () => {
    el('ui_language').value = UI.preferences.language;
    contextUpdate();
    UI.attr(nav, 'aria-label', UI.msg('nav.navigation'));
    UI.apply();
    document.title = 'Cecropis · ' + UI.t(title.dataset.i18n);
  });
  document.addEventListener('ui-theme', () => { el('ui_theme').value = UI.preferences.theme; });
  const contextObserver = new MutationObserver(contextUpdate);
  contextObserver.observe(el('analysis_context'), {
    childList: true,
    characterData: true,
    subtree: true
  });
  contextObserver.observe(el('saved_results'), {
    childList: true
  });
  window.workspaceShell = {
    navigate,
    openSearchTool,
    refreshContext: contextUpdate,
    current: () => current
  };
  contextUpdate();
  let previous;
  try {
    previous = localStorage.getItem('workspace-view-v1');
  } catch {}
  navigate(pages.has(previous) ? previous : 'library', false);
})();
