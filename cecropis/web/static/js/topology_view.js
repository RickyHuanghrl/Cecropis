"use strict";

/* Display-only SVG topology. Node positions and camera never enter experiments. */
(function (global) {
  'use strict';

  const NS = 'http://www.w3.org/2000/svg';
  let serial = 0;
  const element = (name, attributes = {}) => {
    const value = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attributes)) UI.attr(value, k, String(v));
    return value;
  };
  const identifier = value => String(value);
  const number = value => value == null ? UI.msg("topology.view.number.not_recorded_7450cc", {}) : Number(value).toPrecision(5);
  const label = node => UI.join([node.type || node.annotation?.type || node.annotation?.instance || UI.msg("topology.view.label.type_fb8761", {}), " · ", node.body_id]);
  class TopologyView {
    constructor(container, options = {}) {
      this.container = container;
      this.options = options;
      this.nodes = new Map();
      this.edges = new Map();
      this.positions = new Map();
      this.fixed = new Set();
      this.selection = new Set();
      this.focus = null;
      this.edgeFocus = null;
      this.hover = null;
      this.transform = {
        x: 0,
        y: 0,
        k: 1
      };
      this.labelMode = 'auto';
      this.drag = null;
      this.expanded = false;
      this.graphKey = null;
      this.root = document.createElement('div');
      this.root.className = 'topology-view';
      this.root.style.cssText = 'position:relative;min-width:0;background:var(--canvas);border:1px solid var(--line);border-radius:6px';
      this.toolbar = document.createElement('div');
      this.toolbar.style.cssText = 'display:flex;gap:5px;flex-wrap:wrap;padding:7px';
      const buttons = [['−', () => this.zoom(.8)], ['＋', () => this.zoom(1.25)], [UI.msg("topology.view.controls.fit_72891f", {}), () => this.fit()], [UI.msg("topology.view.controls.focus_selection_6302c3", {}), () => this.focusSelection()], [UI.msg("topology.view.controls.pin_d4b3f4", {}), () => this.pin(true)], [UI.msg("topology.view.controls.unpin_fa7dd2", {}), () => this.pin(false)], [UI.msg("topology.view.controls.reset_layout_b74829", {}), () => this.resetLayout()], [UI.msg("topology.view.controls.expand_00bd39", {}), () => this.expand(), 'expand']];
      for (const [text, action, kind] of buttons) {
        const button = document.createElement('button');
        button.type = 'button';
        UI.text(button, text);
        UI.attr(button, 'aria-label', text === '−' ? UI.msg("topology.view.controls.zoom_out_290f68", {}) : text === '＋' ? UI.msg("topology.view.controls.zoom_in_80f8fb", {}) : text);
        button.onclick = action;
        this.toolbar.appendChild(button);
        if (kind === 'expand') this.expandButton = button;
      }
      this.labelControl = document.createElement('select');
      UI.attr(this.labelControl, 'aria-label', UI.msg("topology.view.controls.message_aa1be3", {}));
      for (const [value, text] of [['auto', UI.msg("topology.view.controls.labels_auto_9d5dbe", {})], ['all', UI.msg("topology.view.controls.labels_all_098dfc", {})], ['selected', UI.msg("topology.view.controls.labels_selected_28aab5", {})]]) {
        const option = document.createElement('option');
        option.value = value;
        UI.text(option, text);
        this.labelControl.appendChild(option);
      }
      this.labelControl.onchange = () => {
        this.labelMode = this.labelControl.value;
        this.refreshLabels();
        this.changed();
      };
      this.toolbar.appendChild(this.labelControl);
      this.membershipLegend = document.createElement('span');
      this.membershipLegend.style.cssText = 'font-size:12px';
      this.toolbar.appendChild(this.membershipLegend);
      this.svg = element('svg', {
        viewBox: '0 0 640 420',
        role: 'group',
        'aria-label': options.label || UI.msg("topology.view.controls.actual_directed_connection_topology_c75589", {})
      });
      this.svg.style.cssText = 'display:block;width:100%;height:420px;touch-action:none;user-select:none';
      const defs = element('defs'),
        marker = element('marker', {
          id: 'topology-arrow-' + ++serial,
          viewBox: '0 0 10 10',
          refX: 9,
          refY: 5,
          markerWidth: 5,
          markerHeight: 5,
          orient: 'auto',
          markerUnits: 'strokeWidth'
        });
      marker.appendChild(element('path', {
        d: 'M0 0L10 5L0 10Z',
        fill: 'var(--canvas-node)'
      }));
      defs.appendChild(marker);
      this.marker = marker.getAttribute('id');
      this.svg.appendChild(defs);
      this.layer = element('g');
      this.edgeLayer = element('g');
      this.nodeLayer = element('g');
      this.layer.appendChild(this.edgeLayer);
      this.layer.appendChild(this.nodeLayer);
      this.svg.appendChild(this.layer);
      this.root.appendChild(this.toolbar);
      this.root.appendChild(this.svg);
      container.replaceChildren(this.root);
      this.handlers = {
        pointerdown: e => this.pointerDown(e),
        pointermove: e => this.pointerMove(e),
        pointerup: e => this.pointerUp(e),
        pointercancel: e => this.pointerUp(e),
        wheel: e => {
          e.preventDefault();
          this.zoom(e.deltaY < 0 ? 1.15 : 1 / 1.15, this.point(e));
        }
      };
      for (const [name, handler] of Object.entries(this.handlers)) this.svg.addEventListener(name, handler, name === 'wheel' ? {
        passive: false
      } : undefined);
      if (global.ResizeObserver) {
        this.observer = new ResizeObserver(() => this.refreshLabels());
        this.observer.observe(container);
      }
    }
    changed() {
      this.options.onState?.(this.exportState());
    }
    point(event) {
      const box = this.svg.getBoundingClientRect();
      const scale = Math.min((box.width || 640) / 640, (box.height || 420) / 420);
      return {
        x: (event.clientX - box.left - ((box.width || 640) - 640 * scale) / 2) / scale,
        y: (event.clientY - box.top - ((box.height || 420) - 420 * scale) / 2) / scale
      };
    }
    world(point) {
      return {
        x: (point.x - this.transform.x) / this.transform.k,
        y: (point.y - this.transform.y) / this.transform.k
      };
    }
    applyTransform() {
      const t = this.transform;
      UI.attr(this.layer, 'transform', `translate(${t.x} ${t.y}) scale(${t.k})`);
      this.refreshLabels();
    }
    zoom(factor, center = {
      x: 320,
      y: 210
    }) {
      const old = this.transform.k,
        next = Math.max(.035, Math.min(12, old * factor));
      this.transform = {
        x: center.x - (center.x - this.transform.x) * next / old,
        y: center.y - (center.y - this.transform.y) * next / old,
        k: next
      };
      this.applyTransform();
      this.changed();
    }
    pointerDown(event) {
      if (event.button !== 0) return;
      const node = event.target.closest('[data-topology-node]');
      if (event.target.closest('[data-topology-edge]')) return;
      const point = this.point(event);
      this.drag = {
        id: node?.dataset.topologyNode || null,
        start: point,
        previous: point,
        moved: false,
        pointer: event.pointerId
      };
      if (!node) this.svg.setPointerCapture?.(event.pointerId);
    }
    pointerMove(event) {
      if (!this.drag || event.pointerId !== this.drag.pointer) return;
      const point = this.point(event),
        d = this.drag;
      if (Math.hypot(point.x - d.start.x, point.y - d.start.y) > 3) d.moved = true;
      if (!d.moved) return;
      this.svg.setPointerCapture?.(event.pointerId);
      if (d.id) {
        const p = this.world(point);
        this.positions.set(d.id, p);
        this.fixed.add(d.id);
        this.updateGeometry();
      } else {
        this.transform.x += point.x - d.previous.x;
        this.transform.y += point.y - d.previous.y;
        this.applyTransform();
      }
      d.previous = point;
    }
    pointerUp(event) {
      if (!this.drag || event.pointerId !== this.drag.pointer) return;
      this.suppressClick = this.drag.moved;
      this.drag = null;
      this.svg.releasePointerCapture?.(event.pointerId);
      this.changed();
      setTimeout(() => {
        this.suppressClick = false;
      }, 0);
    }
    setGraph(graph) {
      this.nodes.clear();
      this.edges.clear();
      this.edgeLayer.replaceChildren();
      this.nodeLayer.replaceChildren();
      this.positions.clear();
      this.fixed.clear();
      for (const original of graph.nodes || []) {
        const node = {
          ...original,
          body_id: identifier(original.body_id ?? original.bodyId)
        };
        this.nodes.set(node.body_id, {
          data: node
        });
      }
      for (const original of graph.edges || []) {
        const edge = {
          ...original,
          pre_id: identifier(original.pre_id ?? original.body_pre),
          post_id: identifier(original.post_id ?? original.body_post)
        };
        edge.edge_id = identifier(edge.edge_id ?? `${edge.pre_id}->${edge.post_id}`);
        if (!this.nodes.has(edge.pre_id) || !this.nodes.has(edge.post_id)) continue;
        const group = element('g', {
            'data-topology-edge': edge.edge_id,
            tabindex: 0,
            role: 'button',
            'aria-label': UI.msg("topology.view.controls.message_a6d0b0", {
              p0: edge.pre_id,
              p1: edge.post_id,
              p2: edge.count ?? edge.contacts ?? UI.msg("topology.view.controls.not_recorded_7450cc", {})
            })
          }),
          hit = element('path', {
            fill: 'none',
            stroke: 'transparent',
            'stroke-width': 13
          }),
          path = element('path', {
            fill: 'none',
            stroke: 'var(--canvas-node)',
            'stroke-width': 1.5,
            'marker-end': `url(#${this.marker})`
          }),
          title = element('title');
        group.style.cursor = 'pointer';
        group.appendChild(hit);
        group.appendChild(path);
        group.appendChild(title);
        this.edgeLayer.appendChild(group);
        const activate = e => {
          e.stopPropagation();
          this.edgeFocus = edge.edge_id;
          this.focus = null;
          this.applyHighlight();
          this.options.onEdge?.(edge.edge_id, e);
          this.changed();
        };
        group.addEventListener('click', activate);
        group.addEventListener('keydown', e => {
          if (['Enter', ' '].includes(e.key)) {
            e.preventDefault();
            activate(e);
          }
        });
        this.edges.set(edge.edge_id, {
          data: edge,
          group,
          hit,
          path,
          title
        });
      }
      for (const [id, node] of this.nodes) {
        const group = element('g', {
            'data-topology-node': id,
            tabindex: 0,
            role: 'button',
            'aria-label': label(node.data)
          }),
          circle = element('circle', {
            r: node.data.input || node.data.intervention || node.data.observation_names?.length ? 11 : 9,
            fill: node.data.color || 'var(--baseline)',
            stroke: 'var(--canvas-node)',
            'stroke-width': 1.3
          }),
          text = element('text', {
            x: 0,
            y: 27,
            'text-anchor': 'middle',
            fill: 'var(--text)',
            'font-size': 12,
            stroke: 'none'
          }),
          title = element('title');
        UI.text(text, label(node.data));
        UI.text(title, label(node.data));
        group.style.cursor = 'grab';
        group.appendChild(circle);
        group.appendChild(text);
        group.appendChild(title);
        this.nodeLayer.appendChild(group);
        Object.assign(node, {
          group,
          circle,
          text,
          title
        });
        const activate = e => {
          e.stopPropagation();
          if (this.suppressClick) return;
          this.focus = id;
          this.edgeFocus = null;
          this.applyHighlight();
          this.options.onNode?.(id, e);
          this.changed();
        };
        group.addEventListener('click', activate);
        group.addEventListener('keydown', e => {
          if (['Enter', ' '].includes(e.key)) {
            e.preventDefault();
            activate(e);
          }
        });
        group.addEventListener('pointerenter', () => {
          this.hover = id;
          this.applyHighlight();
        });
        group.addEventListener('pointerleave', () => {
          this.hover = null;
          this.applyHighlight();
        });
      }
      this.edgePairs = new Set([...this.edges.values()].map(e => e.data.pre_id + '->' + e.data.post_id));
      this.layout();
      this.updateGeometry();
      this.fit();
      this.applyHighlight();
    }
    layout() {
      const levels = new Map(),
        links = new Map();
      for (const e of this.edges.values()) {
        if (!links.has(e.data.pre_id)) links.set(e.data.pre_id, []);
        links.get(e.data.pre_id).push(e.data.post_id);
      }
      const ordered = [...this.nodes.keys()].sort((a, b) => BigInt(a) < BigInt(b) ? -1 : 1);
      let roots = ordered.filter(id => this.nodes.get(id).data.input || this.nodes.get(id).data.source_hops === 0);
      if (!roots.length && ordered.length) roots = [ordered[0]];
      const queue = roots.slice();
      for (const id of roots) levels.set(id, 0);
      for (let k = 0; k < queue.length; k++) for (const next of links.get(queue[k]) || []) if (!levels.has(next)) {
        levels.set(next, Math.min(8, levels.get(queue[k]) + 1));
        queue.push(next);
      }
      const bands = new Map();
      for (const id of ordered) {
        const level = this.nodes.get(id).data.source_hops ?? levels.get(id) ?? 9;
        if (!bands.has(level)) bands.set(level, []);
        bands.get(level).push(id);
      }
      for (const [level, ids] of bands) ids.forEach((id, k) => {
        if (!this.fixed.has(id)) this.positions.set(id, {
          x: 70 + Number(level) * 215,
          y: 55 + k * 70
        });
      });
    }
    edgePath(edge) {
      const a = this.positions.get(edge.pre_id),
        b = this.positions.get(edge.post_id);
      if (!a || !b) return '';
      if (edge.pre_id === edge.post_id) return `M ${a.x + 7} ${a.y - 8} C ${a.x + 62} ${a.y - 71} ${a.x - 62} ${a.y - 71} ${a.x - 8} ${a.y - 9}`;
      const dx = b.x - a.x,
        dy = b.y - a.y,
        d = Math.max(1, Math.hypot(dx, dy)),
        nx = -dy / d,
        ny = dx / d,
        reverse = this.edgePairs.has(edge.post_id + '->' + edge.pre_id),
        bend = reverse ? Math.min(55, d * .18) : Math.min(24, d * .08),
        cx = (a.x + b.x) / 2 + nx * bend,
        cy = (a.y + b.y) / 2 + ny * bend,
        ad = Math.max(1, Math.hypot(cx - a.x, cy - a.y)),
        bd = Math.max(1, Math.hypot(b.x - cx, b.y - cy)),
        r1 = Number(this.nodes.get(edge.pre_id).circle.getAttribute('r')) + 1,
        r2 = Number(this.nodes.get(edge.post_id).circle.getAttribute('r')) + 3;
      return `M ${a.x + (cx - a.x) / ad * r1} ${a.y + (cy - a.y) / ad * r1} Q ${cx} ${cy} ${b.x - (b.x - cx) / bd * r2} ${b.y - (b.y - cy) / bd * r2}`;
    }
    updateGeometry() {
      for (const [id, n] of this.nodes) {
        const p = this.positions.get(id);
        UI.attr(n.group, 'transform', `translate(${p.x} ${p.y})`);
        UI.attr(n.group, 'data-fixed', String(this.fixed.has(id)));
      }
      for (const e of this.edges.values()) {
        const d = this.edgePath(e.data);
        UI.attr(e.path, 'd', d);
        UI.attr(e.hit, 'd', d);
      }
      this.applyHighlight();
    }
    fit(ids = null) {
      const points = (ids || [...this.nodes.keys()]).map(id => this.positions.get(String(id))).filter(Boolean);
      if (!points.length) return;
      const xs = points.map(p => p.x),
        ys = points.map(p => p.y),
        left = Math.min(...xs) - 85,
        right = Math.max(...xs) + 85,
        top = Math.min(...ys) - 70,
        bottom = Math.max(...ys) + 48,
        k = Math.min(580 / Math.max(170, right - left), 355 / Math.max(120, bottom - top), 2);
      this.transform = {
        k,
        x: 320 - (left + right) / 2 * k,
        y: 210 - (top + bottom) / 2 * k
      };
      this.applyTransform();
      this.changed();
    }
    focusSelection() {
      const ids = [...this.selection];
      if (this.focus && !ids.includes(this.focus)) ids.push(this.focus);
      this.fit(ids);
    }
    pin(fixed) {
      const ids = this.selection.size ? [...this.selection] : this.focus ? [this.focus] : [];
      for (const id of ids) if (this.nodes.has(id)) {
        if (fixed) this.fixed.add(id);else this.fixed.delete(id);
      }
      this.updateGeometry();
      this.changed();
    }
    resetLayout() {
      this.fixed.clear();
      this.layout();
      this.updateGeometry();
      this.fit();
    }
    setSelection(ids, focus = null) {
      this.selection = new Set((ids || []).map(String));
      this.focus = focus == null ? null : String(focus);
      this.applyHighlight();
    }
    setEdgeSelection(id) {
      this.edgeFocus = id == null ? null : String(id);
      this.applyHighlight();
    }
    setInterventionMembership(retained, withdrawn) {
      UI.text(this.membershipLegend, retained?.length || withdrawn?.length ? UI.msg("topology.view.controls.keepintervention_intervention_8dc5a0", {}) : String());
      this.interventionRetained = new Set((retained || []).map(String));
      this.interventionWithdrawn = new Set((withdrawn || []).map(String));
      for (const [id, n] of this.nodes) {
        const state = this.interventionRetained.has(id) ? UI.msg("topology.view.controls.keepintervention_311d6f", {}) : this.interventionWithdrawn.has(id) ? UI.msg("topology.view.controls.intervention_node_connectionskeep_24a23a", {}) : null;
        UI.attr(n.group, 'data-intervention-membership', state || '');
        if (!n.interventionRing) {
          n.interventionRing = element('circle', {
            r: 15,
            fill: 'none',
            'pointer-events': 'none',
            'stroke-width': 2
          });
          n.group.insertBefore(n.interventionRing, n.circle);
        }
        UI.attr(n.interventionRing, 'display', state ? '' : 'none');
        UI.attr(n.interventionRing, 'stroke', this.interventionRetained.has(id) ? 'var(--intervention)' : 'var(--highlight)');
        UI.attr(n.interventionRing, 'stroke-dasharray', this.interventionWithdrawn.has(id) ? '2 3' : '');
        UI.attr(n.group, 'aria-label', label(n.data) + (state ? ' · ' + state : ''));
      }
    }
    applyHighlight() {
      const anchors = new Set([...this.selection].filter(id => this.nodes.has(id)));
      if (this.nodes.has(this.focus)) anchors.add(this.focus);
      if (this.nodes.has(this.hover)) anchors.add(this.hover);
      const nearby = new Set(anchors);
      for (const e of this.edges.values()) if (anchors.has(e.data.pre_id) || anchors.has(e.data.post_id)) {
        nearby.add(e.data.pre_id);
        nearby.add(e.data.post_id);
      }
      for (const [id, n] of this.nodes) {
        const active = anchors.has(id),
          chosen = this.selection.has(id);
        UI.attr(n.group, 'opacity', anchors.size && !nearby.has(id) ? .32 : 1);
        UI.attr(n.circle, 'stroke', active ? 'var(--selection)' : 'var(--canvas-node)');
        UI.attr(n.circle, 'stroke-width', active ? 3.5 : 1.3);
        UI.attr(n.circle, 'stroke-dasharray', this.fixed.has(id) ? '3 2' : '');
        UI.attr(n.group, 'aria-pressed', String(chosen));
        UI.attr(n.group, 'data-selected', String(chosen));
      }
      for (const e of this.edges.values()) {
        const selected = e.data.edge_id === this.edgeFocus,
          adjacent = anchors.has(e.data.pre_id) || anchors.has(e.data.post_id);
        UI.attr(e.group, 'opacity', selected ? 1 : anchors.size && !adjacent ? .15 : .75);
        UI.attr(e.path, 'stroke-width', selected ? 3.7 : adjacent ? 2.4 : 1.5);
        UI.attr(e.group, 'aria-pressed', String(selected));
      }
      this.refreshLabels();
    }
    refreshLabels() {
      const box = this.svg.getBoundingClientRect(),
        scale = Math.min((box.width || 640) / 640, (box.height || 420) / 420);
      for (const [id, n] of this.nodes) {
        const special = this.selection.has(id) || this.focus === id || this.hover === id;
        const show = special || this.labelMode === 'all' || this.labelMode === 'auto' && (this.nodes.size <= 20 || this.transform.k >= .85);
        UI.attr(n.text, 'display', show ? '' : 'none');
        UI.attr(n.text, 'font-size', Math.max(12, 12 / (this.transform.k * scale)));
      }
    }
    updateActivity(frame, mode, colorFn) {
      const nodes = new Map((frame?.nodes || []).map(n => [String(n.body_id), n])),
        edges = new Map((frame?.edges || []).map(e => [String(e.edge_id), e]));
      for (const [id, n] of this.nodes) {
        const value = nodes.get(id)?.[mode];
        UI.attr(n.circle, 'fill', colorFn ? colorFn(value, mode, false) : n.data.color || 'var(--baseline)');
        UI.text(n.title, `${label(n.data)}${frame ? ' · ' + mode + ' ' + number(value) : ''}`);
      }
      for (const [id, e] of this.edges) {
        const value = edges.get(id)?.[mode];
        UI.attr(e.path, 'stroke', colorFn ? colorFn(value, mode, true) : '#8299b2');
        UI.text(e.title, UI.msg("topology.view.controls.message_c39acf", {
          p0: e.data.pre_id,
          p1: e.data.post_id,
          p2: e.data.count ?? e.data.contacts ?? UI.msg("topology.view.controls.not_recorded_7450cc", {}),
          p3: number(e.data.weight),
          p4: frame ? ' · ' + mode + ' ' + number(value) : ''
        }));
      }
    }
    exportState() {
      return {
        positions: Object.fromEntries([...this.positions].map(([id, p]) => [id, {
          ...p
        }])),
        fixed_nodes: [...this.fixed],
        transform: {
          ...this.transform
        },
        label_mode: this.labelMode,
        selected_node: this.focus,
        selected_edge: this.edgeFocus
      };
    }
    importState(state) {
      if (!state) return;
      for (const [id, p] of Object.entries(state.positions || {})) if (this.nodes.has(id) && Number.isFinite(p.x) && Number.isFinite(p.y)) this.positions.set(id, {
        x: p.x,
        y: p.y
      });
      this.fixed = new Set((state.fixed_nodes || []).map(String).filter(id => this.nodes.has(id)));
      const t = state.transform;
      if (t && Number.isFinite(t.x) && Number.isFinite(t.y) && Number.isFinite(t.k) && t.k >= .035 && t.k <= 12) this.transform = {
        ...t
      };
      if (['auto', 'all', 'selected'].includes(state.label_mode)) this.labelMode = state.label_mode;
      this.labelControl.value = this.labelMode;
      this.focus = this.nodes.has(String(state.selected_node)) ? String(state.selected_node) : null;
      this.edgeFocus = this.edges.has(String(state.selected_edge)) ? String(state.selected_edge) : null;
      this.updateGeometry();
      this.applyTransform();
    }
    expand() {
      this.expanded = !this.expanded;
      this.root.style.cssText = this.expanded ? 'position:fixed;inset:16px;z-index:1200;background:var(--canvas);border:1px solid var(--line);border-radius:6px;overflow:auto' : 'position:relative;min-width:0;background:var(--canvas);border:1px solid var(--line);border-radius:6px';
      this.svg.style.height = this.expanded ? 'calc(100% - 65px)' : '420px';
      UI.text(this.expandButton, this.expanded ? UI.msg("topology.view.controls.back_572cf4", {}) : UI.msg("topology.view.controls.expand_00bd39", {}));
      this.refreshLabels();
    }
    destroy() {
      this.observer?.disconnect();
      for (const [name, handler] of Object.entries(this.handlers)) this.svg.removeEventListener(name, handler);
      this.root.remove();
      this.nodes.clear();
      this.edges.clear();
    }
  }
  global.TopologyView = TopologyView;
})(window);
