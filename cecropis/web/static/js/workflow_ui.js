"use strict";

/* Context actions over the existing router, draft, shared selection and results. */
const workElement = id => document.getElementById(id);
function workButton(key, action, className = '') {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = className;
  button.dataset.i18n = key;
  UI.text(button, UI.msg(key));
  button.onclick = action;
  return button;
}
function workSection(key, className = '') {
  const section = document.createElement('section');
  section.className = className;
  const heading = document.createElement('h3');
  heading.dataset.i18n = key;
  section.append(heading);
  return section;
}
function workRoute(page) {
  workspaceShell.navigate(page);
}
function workScopeFromSelection(ids = analysisSelection.ids()) {
  try {
    if (busy) return;
    if (!ids.length) throw UI.error('use.selectFirst');
    workElement('scope_seed_mode').value = 'ids';
    workElement('scope_ids').value = ids.join(', ');
    workElement('scope_ids').dispatchEvent(new Event('input', {
      bubbles: true
    }));
    workRoute('scope');
  } catch (error) {
    globalStatus(UI.errorText(error), true);
  }
}
function workConfig() {
  if (!overview) {
    workRoute('scope');
    return;
  }
  workRoute('protocol');
}
function workConditionConfig(index) {
  return comparison?.conditions?.[index]?.experiment || comparison?.results?.[index]?.config?.experiment;
}
function workConstraintRow(name) {
  return comparison?.constraints?.find(c => c.name === name)?.constraints?.condition_results?.[0];
}
function workJudgment(constraint) {
  return UI.htmlText(!constraint ? 'use.notConfigured' : constraint.defined === false ? 'use.undefined' : constraint.satisfied ? 'use.pass' : 'use.fail');
}
function workConstraintDescription(name, constraint, target = false) {
  const limit = target ? constraint.minimum : constraint.limit;
  const value = constraint.metric === 'relative' ? UI.percent(limit, 2) : UI.msg('use.absoluteUnit', {
    value: UI.value(limit)
  });
  return '<li><strong>' + esc(name) + '</strong> · ' + UI.htmlText(target ? 'use.minimumLoss' : 'use.maximumLoss', {
    value
  }) + ' · ' + UI.htmlText('result.actualLoss',{value:constraint.loss == null ? UI.msg('use.undefined') : constraint.metric === 'relative' ? UI.percent(constraint.loss,2) : UI.value(constraint.loss)}) + ' · ' + workJudgment(constraint) + '</li>';
}
function workShowCondition(index, only = true) {
  if (!comparison?.rows?.[index]) return;
  comparisonFocusIndex = index;
  if (only) {
    conditionSelected.clear();
    conditionSelected.add(index);
  }
  renderComparisonUsability(comparison);
  renderUnifiedCurves();
  document.dispatchEvent(new Event('lab-comparison-selection'));
}
function renderComparisonUsability(result) {
  workElement('page_compare').classList.add('has-comparison');
  const draft = document.querySelector('.compare-drafts');
  if (draft && draft.comparisonSource !== result) {
    draft.open = false;
    draft.comparisonSource = result;
  }
  const focus = Math.min(comparisonFocusIndex, Math.max(0, result.rows.length - 1));
  comparisonFocusIndex = focus;
  window.workspaceShell?.refreshContext();
  workElement('comparison_head').innerHTML = '<tr>' + ['comparison.condition', 'use.response', 'use.protection'].map(key => '<th>' + UI.htmlText(key) + '</th>').join('') + '</tr>';
  workElement('comparison_rows').innerHTML = result.rows.map((row, k) => {
    const constraints = workConstraintRow(row.name),
      protectedItems = Object.values(constraints?.protected_constraints || {});
    const target = constraints?.target_constraint?.observation;
    const outputs = target ? row.outputs.filter(o => o.type === target) : row.outputs.slice(0, 3);
    const protection = protectedItems.length ? protectedItems.some(p => p.defined === false) ? 'use.undefined' : protectedItems.every(p => p.satisfied) ? 'use.pass' : 'use.fail' : 'use.notConfigured';
    return `<tr aria-selected="${k === focus}" class="${k === focus ? 'selectedrow' : ''}"><td><button type="button" class="linkbtn condition-focus" data-comparison-focus="${k}">${UI.html(UI.name(row))}</button></td><td>${outputs.map(o => '<div><strong>' + esc(o.type) + '</strong> ' + changeText(o) + '</div>').join('') || UI.htmlText('use.undefined')}</td><td>${UI.htmlText(protection)}</td></tr>`;
  }).join('');
  const row = result.rows[focus],
    config = workConditionConfig(focus),
    constraint = row && workConstraintRow(row.name);
  const host = workElement('comparison_detail');
  if (!host) return;
  host.hidden = !row;
  if (!row) return;
  const requirements = [...(constraint?.target_constraint ? [workConstraintDescription(constraint.target_constraint.observation, constraint.target_constraint, true)] : []), ...Object.entries(constraint?.protected_constraints || {}).map(([name, c]) => workConstraintDescription(name, c))];
  host.innerHTML = `<div class="result-heading"><h3>${UI.html(UI.name(row))}</h3><span class="result-state">${UI.htmlText(comparisonStateKey())}</span></div><ul class="constraint-list">${requirements.join('') || '<li>' + UI.htmlText('use.notConfigured') + '</li>'}</ul><div class="buttons" id="condition_next_actions"></div><details><summary>${UI.htmlText('use.exact')}</summary><pre class="exact-definition" data-user-text>${UI.html(JSON.stringify(config ? {
    input_events: protocolEvents(config),
    observations: protocolObservations(config),
    intervention_events: config.intervention_events,
    intervention_ids: config.intervention_ids,
    gain: config.gain,
    intervention_start: config.intervention_start,
    intervention_stop: config.intervention_stop
  } : {
    status: 'not_recorded'
  }, null, 2))}</pre></details>`;
  const actions = workElement('condition_next_actions');
  const adopt = workButton('use.adopt', () => {
    if (busy || !config) return;
    if (window.workflowDraftEdited && !confirm(UI.t('use.replaceConfirm'))) return;
    apply(replayClone(config));
    changed();
    workConfig();
  });
  adopt.disabled = !config;
  actions.append(workButton('use.analyze', () => workAnalyzeCondition(focus, false)), workButton('use.locate', () => workAnalyzeCondition(focus, true)), adopt);
  workElement('comparison_result_tools').hidden = false;
  UI.apply(host);
}
async function workAnalyzeCondition(index, spatial = false) {
  try {
    if (busy) return;
    const config = workConditionConfig(index);
    if (!config) throw UI.error('use.undefined');
    refreshReplaySources();
    const name = comparison.rows[index].name;
    const choices = replaySources.map((source, k) => ({
      source,
      k
    })).filter(({
      source
    }) => source.source.condition_name === name && JSON.stringify(source.experiment) === JSON.stringify(config));
    const chosen = choices.find(({
      source
    }) => source.source.kind === 'artifact') || choices[0];
    if (!chosen) throw UI.error('use.recordMissing');
    await selectReplaySource(chosen.k);
    if (!spatial) {
      workRoute('analysis');
      return;
    }
    workRoute('space');
    await spaceLoad();
    await skeletonLoadIfNeeded();
    const ids = [...new Set(protocolObservations(config).flatMap(o => o.body_ids))];
    await spaceHighlight(ids, name);
    globalSpace.fit(ids);
    // Available tracks must match this exact condition, never merely its scope.
    if (replayResult?.ready && JSON.stringify(replayExperiment(replayResult)) === JSON.stringify(config)) await spaceBind();else {
      spaceUnbind();
      spaceStatus(UI.msg('use.recordMissing'));
    }
  } catch (error) {
    UI.text(workElement('comparison_status'), UI.errorText(error));
  }
}
async function skeletonLoadIfNeeded() {
  if (!skeletonStreaming.manifest) await skeletonLoad();
}
(() => {
  window.workflowDraftEdited = false;
  const previousChanged = changed;
  changed = function () {
    previousChanged();
    window.workflowDraftEdited = true;
  };
  document.addEventListener('lab-case', () => {
    window.workflowDraftEdited = false;
  });
  const draftChoice = document.createElement('label');
  draftChoice.innerHTML = '<input id="scene_include_draft" type="checkbox" checked>' + UI.htmlText('use.saveDraft');
  workElement('analysis_save_controls').append(draftChoice);
  const saveDialog = document.createElement('dialog');
  saveDialog.id = 'work_save_scene_dialog';
  const saveTitle = document.createElement('h3');
  saveTitle.dataset.i18n = 'action.saveScene';
  const saveLabel = document.createElement('label');
  saveLabel.innerHTML = UI.htmlText('use.sceneName');
  const nameInput = workElement('analysis_name');
  saveLabel.append(nameInput);
  const saveButtons = document.createElement('div');
  saveButtons.className = 'buttons';
  const saveError = document.createElement('div');
  saveError.id = 'work_save_scene_error';
  saveError.className = 'error';
  const commit = workButton('action.saveScene', async () => {
    commit.disabled = true;
    try {
      const result = await saveAnalysisScene();
      if (result?.artifact_id) saveDialog.close();else if (result?.error) UI.text(saveError, UI.errorText(result.error));
    } finally {
      commit.disabled = false;
    }
  }, 'primary');
  commit.id = 'work_save_scene';
  saveButtons.append(commit, workButton('action.back', () => saveDialog.close()));
  saveDialog.append(saveTitle, saveLabel, draftChoice, saveButtons, saveError);
  document.body.append(saveDialog);
  window.workSaveScene = () => {
    if (workspaceShell.current() === 'space') analysisActiveView = 'spatial';
    UI.text(saveError, '');
    saveDialog.showModal();
    nameInput.focus();
  };
  workElement('analysis_save').onclick = window.workSaveScene;
  workElement('space_save_scene').onclick = window.workSaveScene;
  const library = workElement('page_library'),
    globalPanel = workElement('global_panel');
  const start = document.createElement('div');
  start.className = 'workspace-start';
  const resume = workSection('use.continue'),
    fresh = workSection('use.new');
  const resumeActions = document.createElement('div');
  resumeActions.className = 'buttons';
  const recent = workButton('use.openLatest', () => {
    const item = savedArtifactCatalog.find(i => i.kind === 'analysis_session') || savedArtifactCatalog[0];
    if (item) reopenArtifact(item.id);
  });
  recent.id = 'work_open_recent';
  resumeActions.append(recent, workButton('nav.tasks', () => workRoute('tasks')));
  resume.append(resumeActions);
  const freshActions = document.createElement('div');
  freshActions.className = 'buttons';
  for (const [route, key] of [['query', 'nav.query'], ['groups', 'nav.groups'], ['space', 'nav.space']]) freshActions.append(workButton(key, () => workRoute(route)));
  const configure = workButton('use.configure', workConfig);
  configure.id = 'work_configure';
  freshActions.append(configure);
  fresh.append(freshActions);
  const state = document.createElement('div');
  state.id = 'work_start_state';
  state.className = 'note';
  fresh.append(state);
  start.append(resume, fresh);
  library.insertBefore(start, globalPanel);
  workElement('path_selected').after(workButton('use.fromSelection', () => {
    const checked = selectedRows('path_nodes_rows');
    workScopeFromSelection(checked.length ? checked : analysisSelection.ids());
  }));
  for (const page of ['query', 'scope']) {
    const row = document.createElement('div');
    row.className = 'workflow-next buttons';
    row.append(workButton('use.fromSelection', () => {
      let ids = analysisSelection.ids();
      if (page === 'query') {
        const checked = selectedRows('global_nodes');
        if (checked.length) {
          checked.forEach(id => spatialKnownIds.add(id));
          analysisSelection.set(checked);
          ids = checked;
        }
      }
      workScopeFromSelection(ids);
    }), workButton('use.configure', workConfig));
    workElement('page_' + page).querySelector('.workspace-page-title').after(row);
  }
  // One original form keeps the same submit/busy ownership around all editors.
  const form = workElement('experiment'),
    grid = document.querySelector('.configure-grid');
  const oldChildren = [...form.children],
    ancillary = [...form.parentElement.children].filter(e => e !== form),
    editor = workElement('intervention_editor'),
    protocol = workElement('protocol_panel');
  const legacy = workElement('legacy_intervention_controls');
  const advanced = document.createElement('details');
  advanced.className = 'advanced-settings';
  const caption = document.createElement('summary');
  caption.dataset.i18n = 'use.advanced';
  advanced.append(caption);
  for (const child of oldChildren) if (child !== legacy) advanced.append(child);
  advanced.append(...ancillary);
  form.append(protocol, editor, advanced);
  const duration = document.createElement('div');
  duration.className = 'protocol-duration';
  duration.append(document.querySelector('label[for="steps"]'), workElement('steps'));
  protocol.prepend(duration);
  grid.replaceChildren(form);
  editor.querySelector('.buttons').after(legacy);
  form.addEventListener('submit', event => {
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);
  // Enter edits an input; only explicit action buttons start work.
  form.addEventListener('keydown', event => {
    if (event.key === 'Enter' && event.target.tagName === 'INPUT') event.preventDefault();
  }, true);
  for (const button of form.querySelectorAll('button')) button.type = 'button';
  workElement('run').onclick = () => run();
  workElement('run').dataset.i18n = 'use.runDraft';
  workElement('save').dataset.i18n = 'use.saveRun';
  const quick = workElement('replace_single_input').closest('details');
  quick.querySelector('summary').dataset.i18n = 'use.quickInput';
  quick.open = false;
  workElement('replace_single_input').dataset.i18n = 'use.replaceInput';
  const interventionHeading = editor.querySelector('summary');
  interventionHeading.hidden = true;
  editor.open=true;
  const interventionHeader=document.createElement('div');
  interventionHeader.className='rowtitle editor-heading';
  const interventionTitle=document.createElement('h2');
  UI.text(interventionTitle,UI.msg('page.labels.intervention_operations_d8322b'));
  const interventionAdd=document.createElement('div');
  interventionAdd.id='intervention_header_actions';
  interventionAdd.className='buttons';
  interventionAdd.append(workElement('intervention_add_node'),workElement('intervention_add_edge'));
  interventionHeader.append(interventionTitle,interventionAdd);
  interventionHeading.after(interventionHeader);
  const syncInterventionAdd=()=>{interventionAdd.hidden=workElement('intervention_plan_mode').value!=='events';};
  syncInterventionAdd();
  const runControls = document.createElement('div');
  runControls.className = 'run-draft-controls buttons';
  runControls.append(workElement('run'),workElement('baseline'),workElement('save'));
  const observationHeading = workElement('add_observation').closest('.rowtitle');
  observationHeading.classList.add('editor-heading');
  const inputHeading = protocol.querySelector('.rowtitle');
  inputHeading.classList.add('editor-heading');
  const footer = document.createElement('div');
  footer.className = 'workflow-next buttons';
  footer.append(workButton('use.addCompare', () => {
    if (busy) return;
    const previous = conditions.length;
    workElement('add_condition').click();
    if (conditions.length > previous) {
      workRoute('compare');
      UI.text(workElement('comparison_draft_hint'), UI.msg('use.readyCompare'));
    }
  }), workButton('nav.search', () => workRoute('search')));
  form.append(runControls,footer);
  if (workElement('status')) form.append(workElement('status'));
  // Existing condition editors, execution and saved-result actions remain separate.
  const comparePage = workElement('page_compare'),
    name = workElement('condition_name');
  const oldSection = name.closest('section'),
    draft = document.createElement('details');
  draft.className = 'compare-drafts';
  draft.open = true;
  const draftHeading = document.createElement('summary');
  draftHeading.dataset.i18n = 'use.conditions';
  draft.append(draftHeading);
  const editing = document.createElement('div');
  editing.className = 'buttons';
  editing.append(name, workElement('add_condition'), workButton('use.configure', workConfig));
  draft.append(editing);
  const conditionFeedback = document.createElement('div');
  conditionFeedback.id = 'condition_feedback';
  conditionFeedback.setAttribute('role', 'status');
  draft.append(conditionFeedback);
  const hint = document.createElement('p');
  hint.id = 'comparison_draft_hint';
  hint.className = 'note';
  hint.dataset.i18n = 'use.prepareCondition';
  draft.append(hint);
  const draftList = workElement('condition_list').closest('details');
  draftList.open = true;
  draft.append(draftList);
  const execute = document.createElement('div');
  execute.className = 'comparison-run';
  execute.append(workElement('compare_conditions'));
  const cleanup = document.createElement('details');
  const cleanSummary = document.createElement('summary');
  cleanSummary.dataset.i18n = 'comparison.actions';
  workElement('clear_conditions').classList.add('danger');
  UI.text(cleanSummary, UI.msg('comparison.actions'));
  cleanup.append(cleanSummary, workElement('clear_conditions'));
  execute.append(cleanup);
  draft.append(execute);
  const results = workSection('use.resultActions', 'compare-results');
  const resultTools = document.createElement('div');
  resultTools.id = 'comparison_result_tools';
  resultTools.className = 'buttons';
  workElement('save_comparison').dataset.i18n = 'use.savedResult';
  resultTools.append(workElement('save_comparison'), workElement('report_condition_mode'), workElement('report_preview'), workElement('report_export'));
  results.append(workElement('comparison_status'));
  const resultLayout = document.createElement('div');
  resultLayout.className = 'comparison-layout';
  const conditionSidebar = document.createElement('aside');
  conditionSidebar.className = 'comparison-conditions';
  conditionSidebar.append(workElement('comparison_rows').closest('.tablewrap'));
  const currentResult = document.createElement('div');
  currentResult.className = 'comparison-current';
  resultLayout.append(conditionSidebar, currentResult);
  results.append(resultLayout);
  resultTools.append(workButton('use.exportTask', async () => {
    await workAnalyzeCondition(comparisonFocusIndex, false);
    workElement('task_export_mode').value = 'source';
    exportPortableTask();
  }));
  const detail = document.createElement('section');
  detail.id = 'comparison_detail';
  detail.className = 'condition-detail';
  detail.hidden = true;
  currentResult.append(detail);
  results.append(resultTools);
  for (const id of ['report_status', 'report_links']) results.append(workElement(id));
  comparePage.insertBefore(draft, oldSection);
  comparePage.insertBefore(results, oldSection);
  oldSection.remove();
  const curveFilters = document.createElement('details');
  curveFilters.id = 'comparison_curve_filters';
  const curveCaption = document.createElement('summary');
  curveCaption.dataset.i18n = 'use.allCurves';
  curveFilters.append(curveCaption, workElement('curve_conditions'), workElement('curve_observations'));
  const plots = document.createElement('div');
  plots.className='comparison-plots';
  plots.append(curveFilters,workElement('charts'));
  resultLayout.after(plots);
  workElement('comparison_rows').addEventListener('click', event => {
    const button = event.target.closest('[data-comparison-focus]');
    if (button) workShowCondition(Number(button.dataset.comparisonFocus));
  });
  const searchHint = document.createElement('div');
  searchHint.id = 'work_search_help';
  searchHint.className = 'workflow-next';
  searchHint.append(workButton('use.configure', workConfig));
  workElement('shell_search_select').after(searchHint);
  function update() {
    recent.disabled = !savedArtifactCatalog.length;
    configure.hidden = !overview;
    UI.text(state, UI.msg(overview ? 'use.scopeReady' : 'use.selectFirst'));
    const keys = {
      operation_search_area: 'use.searchOperations',
      search_panel: 'use.searchNodes',
      joint_search_panel: 'use.searchJoint',
      timing_panel: 'use.searchTiming'
    };
    let text = searchHint.querySelector('p');
    if (!text) {
      text = document.createElement('p');
      searchHint.prepend(text);
    }
    UI.text(text, UI.join([UI.msg(keys[workElement('shell_search_select').value]), ' · ', UI.msg('use.searchPrerequisite')]));
    resultTools.hidden = !comparison;
  }
  for (const event of ['lab-case', 'lab-workspace', 'lab-saved', 'lab-operation-idle', 'ui-language']) document.addEventListener(event, update);
  workElement('shell_search_select').addEventListener('change', update);
  update();
  UI.apply();
})();
