"use strict";

/* Saved sparse structural aggregates and exact member hand-off. */
let groupReport = null,
  groupJob = null,
  groupPreview = null,
  groupPreparedDefinition = null;
let groupGeneration = 0,
  groupViewSequence = 0,
  groupPageOffset = 0,
  groupPageRows = [],
  groupMatrix = null;
let groupMemberSelection = null,
  groupPairOffset = 0,
  groupParentStack = [],
  groupRestrictedMembers = null;
let groupFeatureCache = null,
  groupFeatureOffset = 0;
const groupPageSize = 30;
function groupStatus(message, error = false) {
  UI.text($('group_status'), message);
  $('group_status').classList.toggle('error', error);
}
function groupNumber(value) {
  return value == null ? UI.msg("group.groupNumber.definition_2ba10d", {}) : num(value);
}
function groupRatio(value) {
  return value == null ? UI.msg("group.groupRatio.definition_2ba10d", {}) : (100 * value).toPrecision(4) + '%';
}
function groupURL(path, values) {
  return path + '?' + new URLSearchParams(values);
}
function groupDefinition() {
  const mode = $('group_mode').value;
  if (mode === 'case' && !overview) throw UI.error("group.groupDefinition.open_saved_scopes_202515", {});
  const filters = {},
    field = $('group_filter_field').value,
    value = $('group_filter_value').value.trim();
  if (field && value) filters[field] = value;
  const definition = {
    mode,
    field: $('group_field').value,
    filters,
    budgets: {
      max_nodes: 200000,
      max_groups: 20000,
      max_edges: Number($('group_edge_budget').value),
      max_bytes: Number($('group_memory_budget').value) * 1024 ** 2
    }
  };
  if (!definition.field) throw UI.error("group.groupDefinition.select_an_item_d6a96b", {});
  if (groupRestrictedMembers) definition.body_ids = groupRestrictedMembers;
  return definition;
}
function groupDefinitionChanged() {
  groupGeneration++;
  groupViewSequence++;
  groupPreview = null;
  groupPreparedDefinition = null;
  groupMemberSelection = null;
  $('group_start').disabled = true;
  $('group_apply_selection').disabled = true;
  UI.text($('group_member_info'), '');
  $('group_selected_ids').value = '';
  if (groupReport) groupStatus(UI.msg("group.groupDefinitionChanged.definition_complete_analysis_0230a6", {}));
}
function groupLock() {
  const running = !!groupJob;
  $('group_preview').disabled = running;
  $('group_start').disabled = running || !groupPreview?.build_allowed;
  $('group_cancel').disabled = !running;
  for (const id of ['group_mode', 'group_field', 'group_filter_field', 'group_filter_value', 'group_edge_budget', 'group_memory_budget', 'group_back', 'group_drill']) $(id).disabled = running || id === 'group_back' && !groupParentStack.length || id === 'group_drill' && !groupReport;
}
async function groupPreflight() {
  const generation = ++groupGeneration;
  try {
    const definition = groupDefinition();
    groupPreparedDefinition = null;
    groupPreview = null;
    $('group_start').disabled = true;
    groupStatus(UI.msg("group.groupPreflight.check_requestanalysismembers_1355f0", {}));
    const result = await api('/api/group-preview', {
      definition
    });
    if (generation !== groupGeneration) return;
    groupPreview = result;
    groupPreparedDefinition = definition;
    groupStatus(UI.msg("group.groupPreflight.analysis_node_mib_e2a900", {
      p0: UI.numeric(result.node_count, {}),
      p1: UI.numeric(result.group_count, {}),
      p2: UI.numeric(result.scan_edges, {}),
      p3: UI.numeric(result.estimated_bytes / 1024 ** 2, {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1
      }),
      p4: result.reuse_case_path ? UI.msg("group.groupPreflight.scope_aba7ec", {}) : '',
      p5: result.errors?.length ? ' · ' + result.errors.join('；') : ''
    }), !result.build_allowed);
    groupLock();
  } catch (error) {
    if (generation === groupGeneration) groupStatus(UI.errorText(error), true);
  }
}
async function groupStart() {
  try {
    if (!groupPreparedDefinition || !groupPreview?.build_allowed || JSON.stringify(groupDefinition()) !== JSON.stringify(groupPreparedDefinition)) throw UI.error("group.groupStart.check_the_definition_first_analysisdefinition_005e48", {});
    const result = await api('/api/group-start', {
      definition: groupPreparedDefinition
    });
    groupJob = result.job_id;
    groupLock();
    groupStatus(UI.msg("group.groupStart.group_connections_e2d21f", {}));
    await groupPoll();
  } catch (error) {
    groupStatus(UI.errorText(error), true);
    groupJob = null;
    groupLock();
  }
}
async function groupPoll() {
  const id = groupJob;
  if (!id) return;
  try {
    const job = await api(groupURL('/api/group-job', {
      job_id: id
    }));
    if (groupJob !== id) return;
    const progress = job.progress || {};
    groupStatus(progress.total ? UI.msg("group.groupPoll.node_9e730d", {
      p0: progress.phase === 'group_incoming' ? UI.msg("group.groupPoll.direction_d59eb2", {}) : UI.msg("group.groupPoll.direction_18298b", {}),
      p1: UI.numeric(progress.completed, {}),
      p2: UI.numeric(progress.total, {}),
      p3: UI.numeric(progress.scanned_edges, {}),
      p4: UI.numeric(progress.required_edges, {})
    }) : UI.msg("group.groupPoll.status_59143f", {
      p0: UI.code(job.status)
    }));
    if (['complete', 'completed', 'failed', 'cancelled', 'canceled', 'budget_exceeded'].includes(job.status)) {
      groupJob = null;
      groupLock();
      if (['complete', 'completed'].includes(job.status)) {
        const result = await api('/api/group-result', {
          job_id: id
        });
        await renderGroupReport(result.summary || result.result || result);
      } else {
        const message = UI.msg('group.incomplete', {status:UI.code(job.status)});
        message.technical = job.error || job.message || '';
        groupStatus(message, ['failed', 'budget_exceeded'].includes(job.status));
      }
      return;
    }
    setTimeout(() => {
      if (groupJob === id) groupPoll();
    }, 700);
  } catch (error) {
    if (groupJob === id) {
      groupStatus(UI.errorText(error), true);
      groupJob = null;
      groupLock();
    }
  }
}
function groupKnown(id) {
  return (groupReport?.groups || []).find(g => Number(g.group_id) === Number(id)) || groupPageRows.find(g => Number(g.group_id) === Number(id));
}
function groupOptions() {
  const a = $('group_a').value,
    b = $('group_b').value,
    options = new Map(groupPageRows.map(g => [String(g.group_id), g]));
  for (const id of [a, b]) {
    const g = groupKnown(id);
    if (g) options.set(String(g.group_id), g);
  }
  for (const key of ['a', 'b']) {
    const old = $('group_' + key).value;
    $('group_' + key).replaceChildren();
    for (const g of options.values()) $('group_' + key).append(UI.option(UI.msg("group.groupOptions.nodes_871529", {
      p0: g.name,
      p1: UI.numeric(g.node_count, {})
    }), String(g.group_id)));
    if (options.has(old)) $('group_' + key).value = old;
  }
  if (!b && groupPageRows.length > 1) $('group_b').value = String(groupPageRows[1].group_id);
}
function groupSetEndpoint(key, id) {
  const group = groupKnown(id);
  if (!group) throw UI.error("group.groupSetEndpoint.analysis_532631", {});
  const control = $('group_' + key);
  if (![...control.options].some(o => o.value === String(id))) control.append(UI.option(UI.msg("group.groupSetEndpoint.nodes_871529", {
    p0: group.name,
    p1: UI.numeric(group.node_count, {})
  }), String(id)));
  control.value = String(id);
  groupViewSequence++;
  groupMemberSelection = null;
  $('group_apply_selection').disabled = true;
  $('group_selected_ids').value = '';
  UI.text($('group_member_info'), UI.msg("group.groupSetEndpoint.select_get_exact_members_2cda11", {}));
}
async function renderGroupReport(summary) {
  if (!summary.report_id) throw UI.error("group.renderGroupReport.analysis_6d8a8f", {});
  if (summary.status && summary.status !== 'complete') throw UI.error("group.renderGroupReport.complete_363c0f", {});
  groupGeneration++;
  groupViewSequence++;
  groupReport = summary;
  groupPageOffset = 0;
  groupMatrix = null;
  groupMemberSelection = null;
  groupPairOffset = 0;
  const definition = summary.definition;
  groupRestrictedMembers = definition.body_ids ? [...definition.body_ids] : null;
  $('group_mode').value = definition.mode;
  $('group_field').value = definition.field;
  const filters = Object.entries(definition.filters || {});
  $('group_filter_field').value = filters[0]?.[0] || '';
  $('group_filter_value').value = filters[0]?.[1] || '';
  $('group_edge_budget').value = definition.budgets.max_edges;
  $('group_memory_budget').value = definition.budgets.max_bytes / 1024 ** 2;
  groupPreview = null;
  groupPreparedDefinition = null;
  $('group_result').hidden = false;
  $('group_panel').open = true;
  $('group_save').disabled = false;
  $('group_apply_selection').disabled = true;
  $('group_selected_ids').value = '';
  UI.text($('group_member_info'), '');
  $('group_a').replaceChildren();
  $('group_b').replaceChildren();
  for (const id of ['group_feature_head', 'group_feature_rows', 'group_pair_rows']) $(id).replaceChildren();
  groupFeatureCache = null;
  groupFeatureOffset = 0;
  $('group_feature_prev').disabled = true;
  $('group_feature_next').disabled = true;
  UI.text($('group_feature_page'), '');
  UI.text($('group_feature_status'), '');
  UI.text($('group_pair_info'), '');
  $('group_query').value = '';
  const metrics = summary.metrics || {};
  UI.text($('group_context'), UI.msg("group.renderGroupReport.analysis_node_connected_node_pairs_connection_count_0da070", {
    p0: summary.definition.mode === 'global' ? UI.msg("group.renderGroupReport.message_1410cf", {}) : UI.join([UI.msg("group.renderGroupReport.savescope_47ce7a", {}), summary.identity?.case_id || '']),
    p1: summary.definition.field,
    p2: summary.definition.body_ids ? UI.msg("group.renderGroupReport.members_351887", {}) : '',
    p3: UI.numeric(metrics.node_count, {}),
    p4: UI.numeric(metrics.group_count, {}),
    p5: UI.numeric(metrics.internal_edges, {}),
    p6: UI.numeric(metrics.internal_contacts, {}),
    p7: UI.numeric(metrics.elapsed_seconds || 0, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    })
  }));
  groupStatus(UI.msg("group.renderGroupReport.complete_1846e3", {}));
  groupLock();
  await groupLoadPage(0);
  $('group_panel').scrollIntoView({
    block: 'start'
  });
}
async function groupLoadPage(offset = 0) {
  if (!groupReport) return;
  const generation = groupGeneration,
    sequence = ++groupViewSequence,
    id = groupReport.report_id;
  try {
    const page = await api(groupURL('/api/group-page', {
      report_id: id,
      q: $('group_query').value.trim(),
      sort: $('group_sort').value,
      offset,
      limit: groupPageSize
    }));
    if (generation !== groupGeneration || sequence !== groupViewSequence) return;
    groupPageOffset = offset;
    groupPageRows = page.groups;
    groupOptions();
    $('group_rows').innerHTML = page.groups.map(g => `<tr><td>${UI.html(g.name)}</td><td>${UI.html(num(g.node_count))}</td><td>${UI.html(num(g.internal_input))} / ${UI.html(num(g.full_input))}</td><td><button class="small" data-group-endpoint="a" data-group-id="${g.group_id}">A</button> <button class="small" data-group-endpoint="b" data-group-id="${g.group_id}">B</button></td></tr>`).join('');
    UI.text($('group_page_info'), UI.msg("group.groupLoadPage.message_4970ad", {
      p0: page.total ? offset + 1 : 0,
      p1: Math.min(offset + page.groups.length, page.total),
      p2: UI.numeric(page.total, {})
    }));
    $('group_prev').disabled = offset === 0;
    $('group_next').disabled = offset + page.groups.length >= page.total;
    UI.text($('group_matrix_status'), UI.msg("group.groupLoadPage.message_828ab4", {}));
    const ids = page.groups.map(g => g.group_id);
    const matrix = await api('/api/group-matrix', {
      report_id: id,
      source_ids: ids,
      target_ids: ids
    });
    if (generation !== groupGeneration || sequence !== groupViewSequence) return;
    groupMatrix = matrix;
    groupDrawMatrix();
  } catch (error) {
    if (generation === groupGeneration) groupStatus(UI.errorText(error), true);
  }
}
function groupDrawMatrix() {
  if (!groupMatrix) return;
  const metric = $('group_metric').value,
    cells = new Map(groupMatrix.cells.map(c => [`${c.source}:${c.target}`, c])),
    complete = groupMatrix.complete === true;
  const values = groupMatrix.cells.map(c => c[metric]).filter(v => v != null),
    max = Math.max(0, ...values);
  const format = value => metric === 'input_share' ? groupRatio(value) : groupNumber(value);
  $('group_matrix').innerHTML = `<table><thead><tr><th>${UI.htmlText("group.groupDrawMatrix.source_target_79dd73", {})}</th>` + groupPageRows.map(g => `<th title="${esc(g.name)}">${UI.html(g.name)}</th>`).join('') + '</tr></thead><tbody>' + groupPageRows.map(source => `<tr><th>${UI.html(source.name)}</th>` + groupPageRows.map(target => {
    const cell = cells.get(`${source.group_id}:${target.group_id}`),
      value = cell ? cell[metric] : complete ? metric === 'input_share' && target.full_input === 0 ? null : 0 : undefined;
    const text = value === undefined ? UI.msg("group.controls.message_0416bb", {}) : format(value),
      strength = value != null && max > 0 ? Math.sqrt(value / max) : 0;
    const background = UI.heatColor(value, max);
    return `<td><button class="small" data-group-pair-source="${source.group_id}" data-group-pair-target="${target.group_id}" style="background:${background};color:${UI.contrastText(background)}" ${UI.htmlAttribute('title','editor.connectionValue',{source:source.name,target:target.name,value:text})}>${UI.html(text)}</button></td>`;
  }).join('') + '</tr>').join('') + '</tbody></table>';
  UI.text($('group_matrix_status'), UI.msg("group.groupDrawMatrix.target_all_bee14d", {
    p0: groupPageRows.length,
    p1: groupPageRows.length,
    p2: UI.numeric(groupReport.metrics.group_count, {}),
    p3: complete ? UI.msg("group.groupDrawMatrix.complete_95f568", {}) : UI.msg("group.groupDrawMatrix.complete_1a4773", {})
  }));
  UI.text($('group_scale'), UI.msg("group.groupDrawMatrix.0_0_no_connection_definition_c27d43", {
    p0: format(max)
  }));
}
function groupPairIds() {
  if (!groupReport) throw UI.error("group.groupPairIds.complete_open_analysis_6d12ff", {});
  const a = Number($('group_a').value),
    b = Number($('group_b').value);
  if (!$('group_a').value || !$('group_b').value) throw UI.error("group.groupPairIds.select_a_b_db77fc", {});
  return {
    report_id: groupReport.report_id,
    a,
    b,
    direction: $('group_direction').value
  };
}
function groupFeatureRows(rows, renderRow, offset = 0) {
  groupFeatureCache = {
    rows,
    renderRow,
    report_id: groupReport.report_id
  };
  groupFeatureOffset = offset;
  $('group_feature_rows').innerHTML = rows.slice(offset, offset + 50).map(renderRow).join('');
  UI.text($('group_feature_page'), UI.msg("group.groupFeatureRows.back_08361a", {
    p0: rows.length ? offset + 1 : 0,
    p1: Math.min(offset + 50, rows.length),
    p2: UI.numeric(rows.length, {})
  }));
  $('group_feature_prev').disabled = offset === 0;
  $('group_feature_next').disabled = offset + 50 >= rows.length;
}
async function groupFeature(kind) {
  const generation = groupGeneration,
    sequence = ++groupViewSequence;
  try {
    const selection = groupPairIds();
    UI.text($('group_feature_status'), UI.msg("group.groupFeature.connections_af44b1", {}));
    let data;
    if (kind === 'features') {
      data = await api(groupURL('/api/group-features', selection));
      if (generation !== groupGeneration || sequence !== groupViewSequence) return;
      $('group_feature_head').innerHTML = `<tr><th>${UI.htmlText("group.groupFeature.partner_group_cb985a", {})}</th><th>${UI.htmlText("group.groupFeature.membership_1e9b3d", {})}</th><th>${UI.htmlText("group.groupFeature.a_contacts_direction_share_d46f65", {})}</th><th>${UI.htmlText("group.groupFeature.b_contacts_direction_share_df024e", {})}</th><th>${UI.htmlText("group.groupFeature.actions_ed31fb", {})}</th></tr>`;
      groupFeatureRows(data.partners, g => `<tr><td>${UI.html(g.name)}</td><td>${UI.html({
        shared: UI.msg("group.controls.message_690b88", {}),
        a_only: UI.msg("group.controls.a_117aff", {}),
        b_only: UI.msg("group.controls.b_664951", {})
      }[g.relation])}</td><td>${UI.html(num(g.a_contacts))} / ${groupRatio(g.a_share)}</td><td>${UI.html(num(g.b_contacts))} / ${groupRatio(g.b_share)}</td><td><button class="small" data-group-endpoint="b" data-group-id="${g.group_id}">${UI.htmlText("group.controls.set_as_b_5838b7", {})}</button></td></tr>`);
      UI.text($('group_feature_status'), UI.msg("group.groupFeature.a_scope_scope_b_scope_scope_4791dc", {
        p0: selection.direction === 'incoming' ? UI.msg("group.groupFeature.upstream_a9ab29", {}) : UI.msg("group.groupFeature.downstream_fde36e", {}),
        p1: UI.numeric(data.a_totals.internal, {}),
        p2: UI.numeric(data.a_totals.external, {}),
        p3: UI.numeric(data.a_totals.full, {}),
        p4: UI.numeric(data.b_totals.internal, {}),
        p5: UI.numeric(data.b_totals.external, {}),
        p6: UI.numeric(data.b_totals.full, {})
      }));
    } else if (kind === 'similar') {
      data = await api(groupURL('/api/group-similar', {
        report_id: selection.report_id,
        group_id: selection.a,
        direction: selection.direction
      }));
      if (generation !== groupGeneration || sequence !== groupViewSequence) return;
      $('group_feature_head').innerHTML = `<tr><th>${UI.htmlText("group.groupFeature.group_76acfb", {})}</th><th>${UI.htmlText("group.groupFeature.within_scope_structural_cosine_similarity_33a5ef", {})}</th><th>${UI.htmlText("group.groupFeature.members_6e6d6d", {})}</th><th>${UI.htmlText("group.groupFeature.contacts_within_direction_a8e23d", {})}</th><th>${UI.htmlText("group.groupFeature.actions_ed31fb", {})}</th></tr>`;
      groupFeatureRows(data.groups, g => `<tr><td>${UI.html(g.name)}</td><td>${UI.html(g.similarity == null ? UI.msg("group.controls.definition_623996", {}) : g.similarity.toPrecision(6))}</td><td>${UI.htmlNumber(UI.numeric(g.node_count, {}), false)}</td><td>${UI.htmlNumber(UI.numeric(selection.direction === 'incoming' ? g.internal_input : g.internal_output, {}), false)}</td><td><button class="small" data-group-compare="${g.group_id}">${UI.htmlText("group.controls.compare_with_a_eca806", {})}</button></td></tr>`);
      UI.text($('group_feature_status'), UI.msg("group.groupFeature.analysis_all_connections_f32dc7", {
        p0: UI.numeric(groupReport.metrics.group_count, {}),
        p1: selection.direction === 'incoming' ? UI.msg("group.groupFeature.upstream_a9ab29", {}) : UI.msg("group.groupFeature.downstream_fde36e", {}),
        p2: data.groups.length,
        p3: data.total
      }));
    } else {
      data = await api(groupURL('/api/group-relations', {
        report_id: selection.report_id,
        group_id: selection.a,
        direction: selection.direction
      }));
      if (generation !== groupGeneration || sequence !== groupViewSequence) return;
      $('group_feature_head').innerHTML = `<tr><th>${UI.htmlText("group.groupFeature.partner_group_cb985a", {})}</th><th>${UI.htmlText("group.groupFeature.connected_node_pairs_ba2c3a", {})}</th><th>${UI.htmlText("group.groupFeature.connection_count_93e376", {})}</th><th>${UI.htmlText("group.groupFeature.source_target_nodes_15afc4", {})}</th><th>${UI.htmlText("group.groupFeature.share_of_full_target_input_e78ace", {})}</th><th>${UI.htmlText("group.groupFeature.actions_ed31fb", {})}</th></tr>`;
      groupFeatureRows(data.relations, g => `<tr><td>${UI.html(g.name)}</td><td>${UI.htmlNumber(UI.numeric(g.edges, {}), false)}</td><td>${UI.htmlNumber(UI.numeric(g.contacts, {}), false)}</td><td>${UI.html(num(g.senders))} / ${UI.html(num(g.receivers))}</td><td>${groupRatio(g.input_share)}</td><td><button class="small" data-group-endpoint="b" data-group-id="${g.group_id}">${UI.htmlText("group.controls.set_as_b_5838b7", {})}</button></td></tr>`);
      UI.text($('group_feature_status'), UI.msg("group.groupFeature.scope_788bf3", {
        p0: data.group.name,
        p1: selection.direction === 'incoming' ? UI.msg("group.groupFeature.upstream_a9ab29", {}) : UI.msg("group.groupFeature.downstream_fde36e", {}),
        p2: data.relations.length,
        p3: UI.numeric(data.total, {}),
        p4: UI.numeric(data.group.external_input, {}),
        p5: UI.numeric(data.group.external_output, {})
      }));
    }
  } catch (error) {
    if (generation === groupGeneration) UI.text($('group_feature_status'), UI.errorText(error));
  }
}
async function groupLoadPair(offset = 0) {
  const generation = groupGeneration,
    sequence = ++groupViewSequence;
  $('group_real_edges').open = true;
  $('group_real_edges').scrollIntoView({block: 'start'});
  try {
    const pair = groupPairIds();
    UI.text($('group_pair_info'), UI.msg("group.groupLoadPair.search_connections_adddad", {}));
    const [result, matrix] = await Promise.all([api(groupURL('/api/group-pair', {
      report_id: pair.report_id,
      a: pair.a,
      b: pair.b,
      offset,
      limit: 50,
      scan_limit: Number($('group_edge_budget').value)
    })), api('/api/group-matrix', {
      report_id: pair.report_id,
      source_ids: [pair.a],
      target_ids: [pair.b]
    })]);
    if (generation !== groupGeneration || sequence !== groupViewSequence) return;
    const cell = matrix.cells[0];
    UI.text($('group_pair_summary'), UI.msg("group.groupLoadPair.connected_node_pairs_connection_count_node_share_of_full_78785f", {
      p0: groupKnown(pair.a)?.name,
      p1: groupKnown(pair.b)?.name,
      p2: UI.numeric(cell?.edges || 0, {}),
      p3: UI.numeric(cell?.contacts || 0, {}),
      p4: UI.numeric(cell?.senders || 0, {}),
      p5: UI.numeric(cell?.receivers || 0, {}),
      p6: groupRatio(cell ? cell.input_share : groupKnown(pair.b)?.full_input === 0 ? null : 0),
      p7: pair.a === pair.b ? UI.join([UI.join([UI.msg("group.groupLoadPair.connections_5db919", {}), num(cell?.self_edges || 0)]), UI.msg("group.groupLoadPair.nodeconnections_6047ae", {})]) : ''
    }));
    groupPairOffset = offset;
    $('group_pair_rows').innerHTML = result.edges.map(edge => `<tr><td><button class="linkbtn" data-global-node="${esc(edge.source)}">${UI.html(edge.source)}</button></td><td>${UI.html(edge.source_node?.type || edge.source_node?.instance)}</td><td><button class="linkbtn" data-global-node="${esc(edge.target)}">${UI.html(edge.target)}</button></td><td>${UI.html(edge.target_node?.type || edge.target_node?.instance)}</td><td>${UI.html(num(edge.contacts))} <button class="small" data-operation-edge="${esc(JSON.stringify([edge.source, edge.target]))}">${UI.htmlText("group.controls.create_edge_event_f1e789", {})}</button></td></tr>`).join('');
    UI.text($('group_pair_info'), UI.msg("group.groupLoadPair.a_b_0aa0f4", {
      p0: result.total ? offset + 1 : 0,
      p1: offset + result.edges.length,
      p2: groupNumber(result.total),
      p3: UI.numeric(result.scanned_edges, {}),
      p4: UI.numeric(result.required_edges, {}),
      p5: result.scan_complete ? UI.msg("group.groupLoadPair.search_d59afa", {}) : UI.msg("group.groupLoadPair.budget_complete_no_connection_connections_53f0f6", {})
    }));
    $('group_pair_prev').disabled = offset === 0;
    $('group_pair_next').disabled = !result.scan_complete || offset + result.edges.length >= result.total;
  } catch (error) {
    if (generation === groupGeneration && sequence === groupViewSequence) UI.text($('group_pair_info'), UI.errorText(error));
  }
}
async function groupSelectMembers() {
  const generation = groupGeneration,
    sequence = ++groupViewSequence;
  try {
    const selected = groupPairIds(),
      side = $('group_member_side').value,
      groups = side === 'both' ? [selected.a, selected.b] : [side === 'a' ? selected.a : selected.b],
      filters = {},
      field = $('group_member_filter').value,
      value = $('group_member_value').value.trim();
    if (field && value) filters[field] = value;
    const result = await api('/api/group-members', {
      report_id: selected.report_id,
      group_ids: groups,
      filters
    });
    if (generation !== groupGeneration || sequence !== groupViewSequence) return;
    groupMemberSelection = {
      report_id: selected.report_id,
      body_ids: result.body_ids,
      groups,
      filters
    };
    $('group_selected_ids').value = result.body_ids.join(', ');
    UI.text($('group_member_info'), UI.msg("group.groupSelectMembers.node_6f5329", {
      p0: UI.numeric(result.node_count ?? result.body_ids.length, {}),
      p1: value ? UI.join([UI.join([UI.join([UI.join([UI.msg("group.groupSelectMembers.message_ed9d5c", {}), field]), '=']), value]), UI.msg("group.groupSelectMembers.filter_f068ad", {})]) : UI.msg("group.groupSelectMembers.all_members_029ae8", {})
    }));
    $('group_apply_selection').disabled = !result.body_ids.length;
  } catch (error) {
    if (generation === groupGeneration) {
      groupMemberSelection = null;
      $('group_apply_selection').disabled = true;
      UI.text($('group_member_info'), UI.errorText(error));
    }
  }
}
function groupApplyMembers() {
  try {
    if (!groupMemberSelection || groupMemberSelection.report_id !== groupReport?.report_id) throw UI.error("group.groupApplyMembers.analysis_2988fc", {});
    const ids = groupMemberSelection.body_ids,
      action = $('group_selection_action').value;
    if (ids.length > 200000) throw UI.error("group.groupApplyMembers.members_scope_membersfilter_9d8ff2", {});
    if (action.startsWith('path_')) {
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
      groupEnsurePathway();
      $('pathway_panel').scrollIntoView({
        block: 'start'
      });
    } else {
      appendSeeds(ids);
      if (action !== 'seeds') assignRole(action, ids);
      $('scope_ids').closest('details').open = true;
      $('scope_ids').scrollIntoView({
        block: 'center'
      });
    }
    UI.text($('group_member_info'), UI.msg("group.groupApplyMembers.node_run_439e08", {
      p0: action.startsWith('path_') ? UI.msg("group.groupApplyMembers.paths_a79327", {}) : UI.msg("group.groupApplyMembers.scope_role_5dcf44", {}),
      p1: UI.numeric(ids.length, {})
    }));
  } catch (error) {
    UI.text($('group_member_info'), UI.errorText(error));
  }
}
async function groupDrill() {
  const generation = groupGeneration, sequence = ++groupViewSequence;
  try {
    if (groupJob) throw UI.error("group.groupDrill.complete_cancel_23120a", {});
    if (!groupReport) throw UI.error('group.groupPairIds.complete_open_analysis_6d12ff');
    if (!$('group_a').value) throw UI.error('group.selectA');
    const selection = {report_id: groupReport.report_id, a: Number($('group_a').value)},
      result = await api('/api/group-members', {
        report_id: selection.report_id,
        group_ids: [selection.a]
      });
    if (generation !== groupGeneration || sequence !== groupViewSequence) return;
    groupParentStack.push({
      summary: groupReport,
      restricted: groupReport.definition.body_ids || null,
      definition: groupReport.definition
    });
    groupRestrictedMembers = result.body_ids;
    groupDefinitionChanged();
    groupStatus(UI.msg("group.groupDrill.members_select_check_request_e6dab7", {
      p0: UI.numeric(result.body_ids.length, {})
    }));
    groupLock();
    $('group_field').scrollIntoView({block: 'center'});
    $('group_field').focus({preventScroll: true});
  } catch (error) {
    if (generation !== groupGeneration || sequence !== groupViewSequence) return;
    groupStatus(UI.errorText(error), true);
    $('group_status').scrollIntoView({block: 'center'});
  }
}
async function groupBack() {
  if (groupJob) return;
  const parent = groupParentStack.pop();
  if (!parent) return;
  groupRestrictedMembers = parent.restricted;
  $('group_mode').value = parent.definition.mode;
  $('group_field').value = parent.definition.field;
  const entries = Object.entries(parent.definition.filters || {});
  $('group_filter_field').value = entries[0]?.[0] || '';
  $('group_filter_value').value = entries[0]?.[1] || '';
  groupPreview = null;
  groupPreparedDefinition = null;
  await renderGroupReport(parent.summary);
}
function groupEnsurePathway() {
  if (!overview) {
    $('pathway_panel').hidden = false;
    $('path_scope').value = 'global';
    $('path_endpoint_mode').value = 'ids';
    $('path_endpoints').hidden = false;
    $('path_observation_controls').hidden = true;
    $('path_explore').disabled = false;
  }
}
async function initializeGroups() {
  try {
    const fields = await api('/api/group-fields'),
      groupFields = fields.fields || fields.group_fields || fields.annotation_fields,
      annotationFields = fields.annotation_fields || groupFields;
    const names = items => items.map(item => typeof item === 'string' ? item : item.field || item.name);
    $('group_field').replaceChildren();
    for (const field of names(groupFields)) $('group_field').append(UI.option(UI.field(field), field));
    for (const key of ['group_filter_field', 'group_member_filter']) {
      $(key).replaceChildren(UI.option(UI.msg("group.initializeGroups.no_filter_cff884", {}), ''));
      for (const field of names(annotationFields)) $(key).append(UI.option(UI.field(field), field));
    }
    const caseOption = [...$('group_mode').options].find(o => o.value === 'case');
    caseOption.disabled = !overview;
    groupEnsurePathway();
  } catch (error) {
    groupStatus(UI.errorText(error), true);
    $('group_preview').disabled = true;
  }
}
for (const id of ['group_mode', 'group_field', 'group_filter_field', 'group_filter_value', 'group_edge_budget', 'group_memory_budget']) $(id).addEventListener('input', groupDefinitionChanged);
for (const id of ['group_a', 'group_b', 'group_member_side', 'group_member_filter', 'group_member_value']) $(id).addEventListener('input', () => {
  groupViewSequence++;
  groupMemberSelection = null;
  $('group_apply_selection').disabled = true;
  $('group_selected_ids').value = '';
  UI.text($('group_member_info'), UI.msg("group.controls.select_get_exact_members_a3ce9e", {}));
});
$('group_preview').onclick = groupPreflight;
$('group_start').onclick = groupStart;
$('group_cancel').onclick = async () => {
  try {
    if (groupJob) {
      await api('/api/group-cancel', {
        job_id: groupJob
      });
      groupStatus(UI.msg("group.controls.cancel_keeptask_status_c0425b", {}));
    }
  } catch (error) {
    groupStatus(UI.errorText(error), true);
  }
};
$('group_save').onclick = async () => {
  try {
    if (!groupReport) throw UI.error("group.controls.complete_9fab87", {});
    const saved = await api('/api/group-save', {
      report_id: groupReport.report_id
    });
    groupStatus(UI.join([UI.msg("group.controls.analysis_save_a067c9", {}), saved.id || saved.artifact_id || saved.folder]));
    document.dispatchEvent(new Event('lab-saved'));
  } catch (error) {
    groupStatus(UI.errorText(error), true);
  }
};
$('group_page').onclick = () => groupLoadPage(0);
$('group_prev').onclick = () => groupLoadPage(Math.max(0, groupPageOffset - groupPageSize));
$('group_next').onclick = () => groupLoadPage(groupPageOffset + groupPageSize);
$('group_metric').onchange = groupDrawMatrix;
$('group_relations').onclick = () => groupFeature('relations');
$('group_features').onclick = () => groupFeature('features');
$('group_similar').onclick = () => groupFeature('similar');
$('group_pair').onclick = () => groupLoadPair(0);
$('group_pair_prev').onclick = () => groupLoadPair(Math.max(0, groupPairOffset - 50));
$('group_pair_next').onclick = () => groupLoadPair(groupPairOffset + 50);
for (const [id, step] of [['group_feature_prev', -50], ['group_feature_next', 50]]) $(id).onclick = () => {
  if (groupFeatureCache?.report_id === groupReport?.report_id) groupFeatureRows(groupFeatureCache.rows, groupFeatureCache.renderRow, Math.max(0, groupFeatureOffset + step));
};
$('group_select_members').onclick = groupSelectMembers;
$('group_apply_selection').onclick = groupApplyMembers;
$('group_drill').onclick = groupDrill;
$('group_back').onclick = groupBack;
document.addEventListener('click', event => {
  const data = event.target.dataset;
  try {
    if (data.groupEndpoint) groupSetEndpoint(data.groupEndpoint, Number(data.groupId));
    if (data.groupCompare) {
      groupSetEndpoint('b', Number(data.groupCompare));
      groupFeature('features');
    }
    if (data.groupPairSource != null) {
      groupSetEndpoint('a', Number(data.groupPairSource));
      groupSetEndpoint('b', Number(data.groupPairTarget));
      groupLoadPair(0);
    }
  } catch (error) {
    groupStatus(UI.errorText(error), true);
  }
});
document.addEventListener('lab-workspace', () => {
  groupEnsurePathway();
});
document.addEventListener('lab-case', () => {
  groupGeneration++;
  groupViewSequence++;
  groupMemberSelection = null;
  groupPreview = null;
  groupPreparedDefinition = null;
  $('group_apply_selection').disabled = true;
  $('group_start').disabled = true;
  [...$('group_mode').options].find(o => o.value === 'case').disabled = false;
  if ($('group_mode').value === 'case') {
    groupReport = null;
    $('group_result').hidden = true;
    groupRestrictedMembers = null;
    groupParentStack = [];
    groupStatus(UI.msg("group.controls.scope_check_request_678cbe", {}));
  }
});
window.renderGroupReport = renderGroupReport;
// The initial workspace request may finish before this last script is loaded.
if (typeof localToken !== 'undefined' && localToken) initializeGroups();

for(const event of ['ui-language','ui-theme','ui-fonts'])document.addEventListener(event,()=>{groupDrawMatrix();});
