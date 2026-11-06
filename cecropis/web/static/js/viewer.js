"use strict";

/* Project local SWC geometry with a rotatable orthographic camera. No generated positions. */
class SkeletonView {
  constructor(canvas, onPick) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.onPick = onPick;
    this.nodes = [];
    this.selected = new Set();
    this.focusId = null;
    this.skeleton = null;
    this.activity = new Map();
    this.mode = 'baseline';
    this.yaw = .35;
    this.pitch = -.3;
    this.zoom = 1;
    this.links = [];
    this.showLinks = false;
    this.center = [0, 0, 0];
    this.span = 1;
    this.hits = [];
    let drag = null;
    canvas.onpointerdown = e => {
      drag = {
        x: e.clientX,
        y: e.clientY,
        moved: false
      };
      canvas.setPointerCapture(e.pointerId);
    };
    canvas.onpointermove = e => {
      if (!drag) return;
      const dx = e.clientX - drag.x,
        dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
      this.yaw += dx * .008;
      this.pitch += dy * .008;
      drag.x = e.clientX;
      drag.y = e.clientY;
      this.draw();
    };
    canvas.onpointerup = e => {
      if (drag && !drag.moved) {
        const rect = canvas.getBoundingClientRect(),
          x = e.clientX - rect.left,
          y = e.clientY - rect.top;
        const pick = this.hits.map(h => ({
          ...h,
          d: (h.x - x) ** 2 + (h.y - y) ** 2
        })).sort((a, b) => a.d - b.d)[0];
        if (pick && pick.d < 225) this.onPick(pick.id);
      }
      drag = null;
    };
    canvas.onpointercancel = () => {
      drag = null;
    };
    canvas.onwheel = e => {
      e.preventDefault();
      this.zoom = Math.min(30, Math.max(.2, this.zoom * Math.exp(-e.deltaY * .001)));
      this.draw();
    };
    new ResizeObserver(() => this.draw()).observe(canvas);
  }
  setOverview(data) {
    this.nodes = data.nodes;
    this.reset();
  }
  reset() {
    if (this.nodes.length) {
      const low = [Infinity, Infinity, Infinity],
        high = [-Infinity, -Infinity, -Infinity];
      for (const n of this.nodes) for (let k = 0; k < 3; k++) {
        low[k] = Math.min(low[k], n.bounds[0][k]);
        high[k] = Math.max(high[k], n.bounds[1][k]);
      }
      this.center = low.map((v, k) => (v + high[k]) / 2);
      this.span = Math.max(...low.map((v, k) => high[k] - v), 1);
    }
    this.zoom = 1;
    this.draw();
  }
  setSelection(ids) {
    this.selected = new Set(ids);
    this.draw();
  }
  setFocus(id, skeleton = null, links = []) {
    this.focusId = id;
    this.skeleton = skeleton;
    this.links = links;
    this.draw();
  }
  setActivity(rows, mode) {
    this.activity = new Map(rows.map(r => [r.bodyId, r]));
    this.mode = mode;
    this.draw();
  }
  project(point, w, h) {
    const [x, y, z] = point.map((v, k) => v - this.center[k]);
    const a = Math.cos(this.yaw) * x + Math.sin(this.yaw) * z,
      b = -Math.sin(this.yaw) * x + Math.cos(this.yaw) * z;
    const c = Math.cos(this.pitch) * y - Math.sin(this.pitch) * b,
      depth = Math.sin(this.pitch) * y + Math.cos(this.pitch) * b;
    const scale = Math.min(w, h) * .8 / this.span * this.zoom;
    return {
      x: w / 2 + a * scale,
      y: h / 2 + c * scale,
      depth
    };
  }
  color(id, max) {
    const r = this.activity.get(id);
    if (!r) return '#71889f';
    const q = Math.min(1, Math.abs(r[this.mode]) / max);
    if (this.mode === 'delta') return `rgb(${Math.round(80 + 175 * q)},${Math.round(115 + 60 * q)},${Math.round(145 - 60 * q)})`;
    return `rgb(${Math.round(45 + 200 * q)},${Math.round(100 + 95 * q)},${Math.round(135 - 40 * q)})`;
  }
  draw() {
    const rect = this.canvas.getBoundingClientRect(),
      w = rect.width,
      h = rect.height;
    if (!w || !h) return;
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = w * dpr;
    this.canvas.height = h * dpr;
    const c = this.ctx;
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.fillStyle = '#0b131d';
    c.fillRect(0, 0, w, h);
    this.hits = [];
    if (!this.nodes.length) {
      c.fillStyle = '#96a9be';
      c.font = UI.canvasFont(14);
      c.textAlign = 'center';
      c.fillText(UI.msg("viewer.controls.message_082fac", {}), w / 2, h / 2);
      return;
    }
    let max = 0;
    for (const r of this.activity.values()) max = Math.max(max, Math.abs(r.baseline), Math.abs(r.intervention));
    if (this.mode === 'delta') {
      max = 0;
      for (const r of this.activity.values()) max = Math.max(max, Math.abs(r.delta));
    }
    max = max || 1;
    const projected = this.nodes.map(n => ({
      ...this.project(n.position, w, h),
      node: n
    }));
    if (this.showLinks) {
      const focal = projected.find(p => p.node.bodyId === this.focusId);
      if (focal) {
        c.strokeStyle = '#617383';
        c.setLineDash([4, 5]);
        for (const id of this.links) {
          const p = projected.find(p => p.node.bodyId === id);
          if (p) {
            c.beginPath();
            c.moveTo(focal.x, focal.y);
            c.lineTo(p.x, p.y);
            c.stroke();
          }
        }
        c.setLineDash([]);
      }
    }
    if (this.skeleton) {
      c.strokeStyle = this.color(this.skeleton.bodyId, max);
      c.lineWidth = 1;
      const points = this.skeleton.points.map(p => this.project(p, w, h));
      c.beginPath();
      for (const [a, b] of this.skeleton.edges) {
        c.moveTo(points[a].x, points[a].y);
        c.lineTo(points[b].x, points[b].y);
      }
      c.stroke();
      // Picking the displayed full skeleton maps back to the same body ID.
      const stride = Math.max(1, Math.ceil(points.length / 10000));
      for (let k = 0; k < points.length; k += stride) this.hits.push({
        ...points[k],
        id: this.skeleton.bodyId
      });
    }
    for (const p of projected.sort((a, b) => a.depth - b.depth)) {
      const id = p.node.bodyId,
        selected = this.selected.has(id),
        focused = id === this.focusId;
      c.beginPath();
      c.arc(p.x, p.y, focused ? 6 : selected ? 4 : 2.5, 0, 2 * Math.PI);
      c.fillStyle = this.color(id, max);
      c.fill();
      if (selected || focused) {
        c.strokeStyle = focused ? '#ffffff' : '#63d4c5';
        c.lineWidth = 1.5;
        c.stroke();
      }
      this.hits.push({
        ...p,
        id
      });
    }
    c.textAlign = 'left';
    c.font = UI.canvasFont(12);
    c.fillStyle = '#96a9be';
    c.fillText('MaleCNS EM · μm', 12, h - 12);
    c.textAlign = 'right';
    c.fillText(UI.join([this.mode === 'delta' ? UI.msg("viewer.controls.0_9c4fe2", {}) : UI.msg("viewer.controls.0_d548ad", {}), max.toPrecision(3)]), w - 12, h - 12);
    // Axis triad is tied to the camera, not an assumed brain orientation.
    const o = this.project(this.center, w, h);
    for (const [k, label, color] of [[0, 'X', '#ff9595'], [1, 'Y', '#63d4c5'], [2, 'Z', '#87b6ed']]) {
      const p = [...this.center];
      p[k] += this.span * .08 / this.zoom;
      const q = this.project(p, w, h);
      c.strokeStyle = color;
      c.beginPath();
      c.moveTo(35, 35);
      c.lineTo(35 + q.x - o.x, 35 + q.y - o.y);
      c.stroke();
      c.fillStyle = color;
      c.textAlign = 'center';
      c.fillText(label, 35 + q.x - o.x, 30 + q.y - o.y);
    }
  }
}
