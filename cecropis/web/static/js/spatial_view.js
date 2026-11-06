"use strict";

// One scale for point markers, skeletons and the displayed legend.
function spatialActivityColor(value, domain, mode) {
  const maximum = domain || 1;
  if (mode === 'delta') {
    const q = Math.min(1, Math.abs(value) / maximum);
    return value < 0 ? [.2, .5 + q * .4, .85] : [.7 + q * .3, .45, .2];
  }
  const q = Math.min(1, Math.max(0, value) / maximum);
  return [.15 + .8 * q, .5 + .3 * q, .8 - .5 * q];
}

/* Batched native WebGL annotation positions. Camera changes never fetch data. */
class GlobalSpatialView {
  constructor(canvas, callbacks = {}) {
    this.canvas = canvas;
    this.callbacks = callbacks;
    this.ids = [];
    this.idIndex = new Map();
    this.points = new Float32Array();
    this.kinds = [];
    this.selected = new Set();
    this.highlight = new Set();
    this.caseIds = new Set();
    this.activity = new Map();
    this.mode = 'structure';
    this.focus = null;
    this.isolate = false;
    this.filterIds = null;
    this.edges = [];
    this.skeletons = [];
    this.activeNodes = new Set();
    this.activeEdges = new Set();
    this.camera = {
      center: [0, 0, 0],
      span: 1,
      yaw: .3,
      pitch: -.2,
      zoom: 1,
      pan: [0, 0]
    };
    this.pending = false;
    this.lost = false;
    this.displayLight = document.documentElement.dataset.theme === 'light';
    this.init();
    document.addEventListener('ui-theme', () => {
      this.displayLight = document.documentElement.dataset.theme === 'light';
      this.styleAll(true);
    });
    canvas.addEventListener('webglcontextlost', e => {
      e.preventDefault();
      this.lost = true;
      callbacks.error?.(UI.msg("spatial.view.controls.webgl_select_keep_de27fb", {}));
    });
    canvas.addEventListener('webglcontextrestored', () => {
      this.lost = false;
      this.init();
      this.upload();
      this.styleAll();
      callbacks.error?.(UI.msg("spatial.view.controls.webgl_b804be", {}));
    });
    let drag = null;
    canvas.addEventListener('contextmenu', e => e.preventDefault());
    canvas.addEventListener('pointerdown', e => {
      this.cameraTouched = true;
      canvas.setPointerCapture(e.pointerId);
      drag = {
        x: e.clientX,
        y: e.clientY,
        startX: e.offsetX,
        startY: e.offsetY,
        moved: false,
        box: callbacks.tool?.() === 'box',
        pan: e.button === 2 || e.altKey
      };
    });
    canvas.addEventListener('pointermove', e => {
      if (!drag) return;
      const dx = e.clientX - drag.x,
        dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 1) drag.moved = true;
      if (drag.box) {
        callbacks.box?.([drag.startX, drag.startY, e.offsetX, e.offsetY]);
      } else if (drag.pan) {
        const r = canvas.getBoundingClientRect();
        this.camera.pan[0] += 2 * dx / r.width;
        this.camera.pan[1] -= 2 * dy / r.height;
        this.draw();
      } else {
        this.camera.yaw += dx * .007;
        this.camera.pitch = Math.max(-Math.PI / 2, Math.min(Math.PI / 2, this.camera.pitch + dy * .007));
        this.draw();
      }
      drag.x = e.clientX;
      drag.y = e.clientY;
    });
    canvas.addEventListener('pointerup', e => {
      if (!drag) return;
      const r = canvas.getBoundingClientRect(),
        x = e.clientX - r.left,
        y = e.clientY - r.top;
      if (drag.box) {
        const rect = [Math.min(x, drag.startX), Math.min(y, drag.startY), Math.max(x, drag.startX), Math.max(y, drag.startY)];
        callbacks.box?.(null);
        callbacks.region?.(this.region(rect));
      } else if (!drag.moved) {
        const id = this.pick(x, y);
        if (id) callbacks.pick?.(id, e.shiftKey || e.ctrlKey);else {
          const edge = this.pickEdge(x, y);
          if (edge) callbacks.edge?.(edge);
        }
      }
      drag = null;
    });
    canvas.addEventListener('pointercancel', () => {
      drag = null;
      callbacks.box?.(null);
    });
    canvas.addEventListener('wheel', e => {
      this.cameraTouched = true;
      e.preventDefault();
      this.camera.zoom = Math.min(200, Math.max(.05, this.camera.zoom * Math.exp(-e.deltaY * .001)));
      this.draw();
    }, {
      passive: false
    });
    this.resize = new ResizeObserver(() => this.draw());
    this.resize.observe(canvas);
  }
  init() {
    try {
      const gl = this.canvas.getContext('webgl', {
        antialias: true,
        preserveDrawingBuffer: true
      });
      if (!gl) throw UI.error("spatial.view.controls.webgl_continue_analysis_4e45ba", {});
      this.gl = gl;
      const vs = `attribute vec3 aPos;attribute vec4 aColor;attribute float aSize;attribute float aKind;uniform vec3 uCenter;uniform float uSpan,uYaw,uPitch,uZoom,uAspect,uDpr;uniform vec2 uPan;varying vec4 vColor;varying float vKind,vSize;void main(){vec3 p=(aPos-uCenter)/uSpan;float x=cos(uYaw)*p.x+sin(uYaw)*p.z;float z=-sin(uYaw)*p.x+cos(uYaw)*p.z;float y=cos(uPitch)*p.y-sin(uPitch)*z;float d=sin(uPitch)*p.y+cos(uPitch)*z;gl_Position=vec4(x*1.7*uZoom/uAspect+uPan.x,y*1.7*uZoom+uPan.y,d*.15,1.);gl_PointSize=aSize*uDpr;vColor=aColor;vKind=aKind;vSize=aSize;}`;
      const fs = `precision mediump float;varying vec4 vColor;varying float vKind,vSize;uniform float uLines;void main(){if(vColor.a==0.)discard;if(uLines<.5){float r=length(gl_PointCoord-vec2(.5));if(vKind<1.5&&r>.5)discard;if(vKind>1.5&&abs(gl_PointCoord.x-.5)>.13&&abs(gl_PointCoord.y-.5)>.13)discard;if(vSize>7.&&r>.34){gl_FragColor=vec4(1.,1.,1.,1.);return;}}gl_FragColor=vColor;}`;
      const compile = (type, text) => {
        const s = gl.createShader(type);
        gl.shaderSource(s, text);
        gl.compileShader(s);
        if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(s));
        return s;
      };
      this.program = gl.createProgram();
      gl.attachShader(this.program, compile(gl.VERTEX_SHADER, vs));
      gl.attachShader(this.program, compile(gl.FRAGMENT_SHADER, fs));
      gl.linkProgram(this.program);
      if (!gl.getProgramParameter(this.program, gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(this.program));
      this.attrs = {};
      for (const a of ['Pos', 'Color', 'Size', 'Kind']) this.attrs[a] = gl.getAttribLocation(this.program, 'a' + a);
      this.uniforms = {};
      for (const u of ['Center', 'Span', 'Yaw', 'Pitch', 'Zoom', 'Aspect', 'Dpr', 'Pan', 'Lines']) this.uniforms[u] = gl.getUniformLocation(this.program, 'u' + u);
      this.positionBuffer = gl.createBuffer();
      this.styleBuffer = gl.createBuffer();
      this.kindBuffer = gl.createBuffer();
      this.lineBuffer = gl.createBuffer();
      this.lineColors = gl.createBuffer();
      this.skeletonBuffer = gl.createBuffer();
      this.skeletonColorBuffer = gl.createBuffer();
      this.uploadSkeletons();
      gl.enable(gl.DEPTH_TEST);
      gl.enable(gl.BLEND);
      // Keep the cleared opaque canvas opaque; alpha-squared blending washes out
      // translucent geometry when the browser composites it over a light page.
      gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    } catch (e) {
      this.gl = null;
      this.callbacks.error?.(UI.errorText(e));
    }
  }
  setData(ids, positions, kinds, bounds) {
    this.ids = ids;
    this.positions = positions;
    this.kinds = kinds;
    this.idIndex = new Map(ids.map((id, i) => [id, i]));
    this.drawIndices = [];
    this.vertexIndex = new Int32Array(ids.length).fill(-1);
    for (let i = 0; i < ids.length; i++) if (kinds[i] === 1 || kinds[i] === 2) {
      this.vertexIndex[i] = this.drawIndices.length;
      this.drawIndices.push(i);
    }
    this.points = new Float32Array(this.drawIndices.length * 3);
    this.kindData = new Float32Array(this.drawIndices.length);
    this.styles = new Float32Array(this.drawIndices.length * 5);
    this.drawIndices.forEach((i, v) => {
      this.points.set(positions.subarray(i * 3, i * 3 + 3), v * 3);
      this.kindData[v] = kinds[i];
    });
    this.bounds = bounds;
    this.upload();
    this.home(false);
    this.styleAll();
  }
  upload() {
    if (!this.gl || !this.points.length) return;
    const gl = this.gl;
    for (const [b, data, usage] of [[this.positionBuffer, this.points, gl.STATIC_DRAW], [this.kindBuffer, this.kindData, gl.STATIC_DRAW], [this.styleBuffer, this.styles, gl.DYNAMIC_DRAW]]) {
      gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.bufferData(gl.ARRAY_BUFFER, data, usage);
    }
  }
  visible(id) {
    return (!this.filterIds || this.filterIds.has(id)) && (!this.isolate || this.selected.has(id) || this.highlight.has(id));
  }
  style(i) {
    const v = this.vertexIndex[i];
    if (v < 0) return;
    const id = this.ids[i];
    let c = this.displayLight ? this.caseIds.has(id) ? [.25, .34, .45, .85] : [.40, .47, .55, .38] : this.caseIds.has(id) ? [.38, .45, .56, .7] : [.17, .24, .32, .48],
      size = 2;
    const a = this.activity.get(id);
    if (this.mode !== 'structure' && a) {
      const value = a[this.mode],
        max = this.domain || 1;
      c = [...spatialActivityColor(value, max, this.mode), 1];
      size = 5;
    }
    if (this.highlight.has(id)) {
      if (this.mode === 'structure' || !a) c = [.24, .75, .7, 1];
      size = 4;
    }
    if (this.activeNodes.has(id) && this.mode !== 'baseline' && this.mode !== 'structure') {
      if (!a) c = [1, .5, .2, 1];
      size = 7;
    }
    if (this.selected.has(id)) {
      if (this.mode === 'structure' || !a) c = [...UI.rgb('selection'), 1];
      size = 8;
    }
    if (id === this.focus) size = 10;
    if (!this.visible(id)) c[3] = 0;
    this.styles.set([...c, size], v * 5);
  }
  styleAll(displayOnly = false) {
    if (!displayOnly) this.visibilityRevision = (this.visibilityRevision || 0) + 1;
    if (!this.styles) return;
    for (const i of this.drawIndices) this.style(i);
    if (this.gl) {
      this.gl.bindBuffer(this.gl.ARRAY_BUFFER, this.styleBuffer);
      this.gl.bufferSubData(this.gl.ARRAY_BUFFER, 0, this.styles);
    }
    this.draw();
  }
  setSelection(ids, focus = this.focus) {
    this.selected = new Set(ids);
    this.focus = focus;
    this.styleAll();
  }
  setHighlight(ids) {
    this.highlight = new Set(ids);
    this.styleAll();
  }
  setScope(ids) {
    this.caseIds = new Set(ids);
    this.activity.clear();
    this.activeNodes.clear();
    this.activeEdges.clear();
    this.styleAll();
  }
  setActivity(frame, mode, domain) {
    const dirty = new Set([...this.activity.keys(), ...this.activeNodes]);
    this.mode = mode;
    this.domain = domain;
    this.activity = new Map((frame?.nodes || []).map(r => [r.body_id, r]));
    this.activeNodes = new Set((frame?.active_events || []).filter(e => e.type === 'node_gain' && e.gain < 1).flatMap(e => e.body_ids));
    this.activeEdges = new Set((frame?.active_events || []).filter(e => e.type === 'edge_gain' && e.gain < 1).flatMap(e => e.edges.map(p => p.join('->'))));
    for (const id of [...this.activity.keys(), ...this.activeNodes]) dirty.add(id);
    if (this.gl) for (const id of dirty) {
      const i = this.idIndex.get(id);
      if (i == null || this.vertexIndex[i] < 0) continue;
      this.style(i);
      const v = this.vertexIndex[i];
      this.gl.bindBuffer(this.gl.ARRAY_BUFFER, this.styleBuffer);
      this.gl.bufferSubData(this.gl.ARRAY_BUFFER, v * 20, this.styles.subarray(v * 5, v * 5 + 5));
    }
    this.draw();
  }
  fit(ids = null, userOperation = true) {
    const points = ids ? ids.flatMap(id => {
      const detail = this.skeletonLayer?.positions(id),
        b = detail?.length ? detail : this.geometryPositions?.get(id);
      return b?.length ? b : [this.position(id)];
    }).filter(Boolean) : [...(this.bounds || []), ...(this.geometryBounds || [])];
    if (!points?.length) return false;
    const low = [Infinity, Infinity, Infinity],
      high = [-Infinity, -Infinity, -Infinity];
    for (const p of points) for (let k = 0; k < 3; k++) {
      low[k] = Math.min(low[k], p[k]);
      high[k] = Math.max(high[k], p[k]);
    }
    this.camera.center = low.map((v, k) => (v + high[k]) / 2);
    this.camera.span = Math.max(...high.map((v, k) => v - low[k]), ids ? 5 : 1);
    const rect = this.canvas.getBoundingClientRect(),
      aspect = Math.max(.001, (rect.width || 1) / (rect.height || 1)),
      c = this.camera;
    let halfX = 0,
      halfY = 0;
    for (let i = 0; i < 8; i++) {
      const p = [0, 1, 2].map(k => (i & 1 << k ? high[k] : low[k]) - c.center[k]);
      const x = Math.cos(c.yaw) * p[0] + Math.sin(c.yaw) * p[2],
        z = -Math.sin(c.yaw) * p[0] + Math.cos(c.yaw) * p[2];
      const y = Math.cos(c.pitch) * p[1] - Math.sin(c.pitch) * z;
      halfX = Math.max(halfX, Math.abs(x));
      halfY = Math.max(halfY, Math.abs(y));
    }
    this.camera.zoom = Math.min(.88 * aspect * c.span / (1.7 * Math.max(halfX, .001)), .88 * c.span / (1.7 * Math.max(halfY, .001)));
    if (this.camera.zoom < .05) {
      this.camera.span *= .05 / this.camera.zoom;
      this.camera.zoom = .05;
    }
    this.camera.zoom = Math.min(200, this.camera.zoom);
    this.camera.pan = [0, 0];
    if (userOperation) this.cameraTouched = true;
    this.draw();
    return true;
  }
  home(userOperation = true) {
    this.camera.yaw = .3;
    this.camera.pitch = -.65;
    return this.fit(null, userOperation);
  }
  standardView(plane) {
    const angles = {
      xy: [0, 0],
      xz: [0, Math.PI / 2],
      yz: [Math.PI / 2, 0]
    };
    if (!angles[plane]) return;
    [this.camera.yaw, this.camera.pitch] = angles[plane];
    this.fit();
  }
  position(id) {
    const i = this.idIndex.get(id);
    if (i != null && this.vertexIndex[i] >= 0) return Array.from(this.positions.subarray(i * 3, i * 3 + 3));
    const detail = this.skeletonLayer?.positions(id),
      b = detail?.length ? detail : this.geometryPositions?.get(id);
    return b?.length ? b[0].map((v, k) => (v + b[b.length - 1][k]) / 2) : null;
  }
  project(point) {
    const r = this.canvas.getBoundingClientRect(),
      c = this.camera,
      p = point.map((v, k) => (v - c.center[k]) / c.span),
      x = Math.cos(c.yaw) * p[0] + Math.sin(c.yaw) * p[2],
      z = -Math.sin(c.yaw) * p[0] + Math.cos(c.yaw) * p[2],
      y = Math.cos(c.pitch) * p[1] - Math.sin(c.pitch) * z,
      d = Math.sin(c.pitch) * p[1] + Math.cos(c.pitch) * z;
    return {
      x: (x * 1.7 * c.zoom / (r.width / r.height) + c.pan[0] + 1) * r.width / 2,
      y: (1 - y * 1.7 * c.zoom - c.pan[1]) * r.height / 2,
      depth: d * .15
    };
  }
  pick(x, y) {
    let hit = null,
      depth = Infinity;
    if (this.showPoints !== false) for (const i of this.drawIndices) {
      const id = this.ids[i];
      if (!this.visible(id)) continue;
      const p = this.project(this.positions.subarray(i * 3, i * 3 + 3)),
        v = this.vertexIndex[i],
        radius = Math.max(5, this.styles[v * 5 + 4] / 2);
      if (p.depth >= -1 && p.depth <= 1 && (p.x - x) ** 2 + (p.y - y) ** 2 <= radius ** 2 && p.depth < depth) {
        hit = id;
        depth = p.depth;
      }
    }
    const skeleton = this.skeletonLayer?.pickHit(x, y);
    if (skeleton && skeleton.depth < depth) return skeleton.body_id;
    return hit;
  }
  region(rect) {
    const out = [];
    if (this.showPoints !== false) for (const i of this.drawIndices) {
      const id = this.ids[i];
      if (!this.visible(id)) continue;
      const p = this.project(this.positions.subarray(i * 3, i * 3 + 3));
      if (p.depth >= -1 && p.depth <= 1 && p.x >= rect[0] && p.x <= rect[2] && p.y >= rect[1] && p.y <= rect[3]) out.push(id);
    }
    return [...new Set([...out, ...(this.skeletonLayer?.region(rect) || [])])];
  }
  pickEdge(x, y) {
    let chosen = null,
      best = 36;
    for (const e of this.edges) {
      if (!e.pre_position || !e.post_position) continue;
      const a = this.project(e.pre_position),
        b = this.project(e.post_position),
        dx = b.x - a.x,
        dy = b.y - a.y,
        t = Math.max(0, Math.min(1, ((x - a.x) * dx + (y - a.y) * dy) / (dx * dx + dy * dy || 1))),
        d = (x - a.x - t * dx) ** 2 + (y - a.y - t * dy) ** 2;
      if (d < best) {
        best = d;
        chosen = e.edge_id;
      }
    }
    return chosen;
  }
  setEdges(edges) {
    this.edges = edges;
    this.draw();
  }
  lineData() {
    const points = [],
      colors = [],
      add = (a, b, c) => {
        points.push(...a, ...b);
        colors.push(...c, ...c);
      };
    for (const e of this.edges) {
      const a = e.pre_position,
        b = e.post_position;
      if (!a || !b || !this.visible(e.pre_id) || !this.visible(e.post_id)) continue;
      const active = this.activeEdges.has(e.edge_id) && !['baseline', 'structure'].includes(this.mode),
        c = active ? [1, .5, .2, 1] : [.36, .6, .66, .8];
      add(a, b, c);
      const d = b.map((v, k) => v - a[k]),
        len = Math.hypot(...d);
      if (!len) {
        const radius = this.camera.span / this.camera.zoom * .012;
        let prev = a;
        for (let j = 1; j <= 24; j++) {
          const angle = j * Math.PI / 12,
            next = [a[0] + radius * Math.sin(angle), a[1] + radius * (1 - Math.cos(angle)), a[2]];
          add(prev, next, c);
          prev = next;
        }
        add(a, [a[0] + radius * .4, a[1] + radius * .5, a[2]], c);
        continue;
      }
      const scale = Math.min(len * .18, this.camera.span / this.camera.zoom * .025),
        u = d.map(v => v / len);
      const side = Math.abs(u[1]) > .95 ? [1, 0, 0] : [u[2], 0, -u[0]],
        sl = Math.hypot(...side) || 1,
        tip = b.map((v, k) => v - u[k] * scale * .3),
        tail = tip.map((v, k) => v - u[k] * scale);
      add(tip, tail.map((v, k) => v + side[k] / sl * scale * .4), c);
      add(tip, tail.map((v, k) => v - side[k] / sl * scale * .4), c);
    }
    return {
      points: new Float32Array(points),
      colors: new Float32Array(colors)
    };
  }
  setSkeletons(objects) {
    this.skeletons = objects;
    const points = [];
    for (const s of objects) for (const [a, b] of s.edges) points.push(...s.points[a], ...s.points[b]);
    this.skeletonPoints = new Float32Array(points);
    const colors = new Float32Array(points.length / 3 * 4);
    for (let i = 0; i < points.length / 3; i++) colors.set([.8, .75, .9, .85], i * 4);
    this.skeletonColors = colors;
    this.uploadSkeletons();
    this.draw();
  }
  uploadSkeletons() {
    if (!this.gl || !this.skeletonPoints) return;
    const g = this.gl;
    for (const [b, data] of [[this.skeletonBuffer, this.skeletonPoints], [this.skeletonColorBuffer, this.skeletonColors]]) {
      g.bindBuffer(g.ARRAY_BUFFER, b);
      g.bufferData(g.ARRAY_BUFFER, data, g.STATIC_DRAW);
    }
  }
  draw() {
    if (this.pending) return;
    this.pending = true;
    requestAnimationFrame(() => {
      this.pending = false;
      this.render();
    });
  }
  render() {
    const gl = this.gl;
    if (!gl || this.lost) return;
    const r = this.canvas.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const dpr = Math.min(2, devicePixelRatio || 1),
      w = Math.round(r.width * dpr),
      h = Math.round(r.height * dpr);
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    gl.viewport(0, 0, w, h);
    gl.clearColor(...UI.rgb('canvas'), 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.useProgram(this.program);
    const c = this.camera,
      u = this.uniforms;
    gl.uniform3fv(u.Center, c.center);
    gl.uniform1f(u.Span, c.span);
    gl.uniform1f(u.Yaw, c.yaw);
    gl.uniform1f(u.Pitch, c.pitch);
    gl.uniform1f(u.Zoom, c.zoom);
    gl.uniform1f(u.Aspect, r.width / r.height);
    gl.uniform1f(u.Dpr, dpr);
    gl.uniform2fv(u.Pan, c.pan);
    const attr = (key, buffer, n, stride = 0, offset = 0) => {
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.enableVertexAttribArray(this.attrs[key]);
      gl.vertexAttribPointer(this.attrs[key], n, gl.FLOAT, false, stride, offset);
    };
    const lines = this.lineData();
    if (lines.points.length && this.showConnections !== false) {
      gl.uniform1f(u.Lines, 1);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.lineBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, lines.points, gl.DYNAMIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.lineColors);
      gl.bufferData(gl.ARRAY_BUFFER, lines.colors, gl.DYNAMIC_DRAW);
      attr('Pos', this.lineBuffer, 3);
      attr('Color', this.lineColors, 4);
      for (const key of ['Size', 'Kind']) {
        gl.disableVertexAttribArray(this.attrs[key]);
        gl.vertexAttrib1f(this.attrs[key], 1);
      }
      gl.drawArrays(gl.LINES, 0, lines.points.length / 3);
    }
    if (this.skeletonPoints?.length) {
      gl.uniform1f(u.Lines, 1);
      attr('Pos', this.skeletonBuffer, 3);
      attr('Color', this.skeletonColorBuffer, 4);
      for (const key of ['Size', 'Kind']) {
        gl.disableVertexAttribArray(this.attrs[key]);
        gl.vertexAttrib1f(this.attrs[key], 1);
      }
      gl.drawArrays(gl.LINES, 0, this.skeletonPoints.length / 3);
    }
    if (this.points.length && this.showPoints !== false) {
      gl.uniform1f(u.Lines, 0);
      attr('Pos', this.positionBuffer, 3);
      attr('Color', this.styleBuffer, 4, 20, 0);
      attr('Size', this.styleBuffer, 1, 20, 16);
      attr('Kind', this.kindBuffer, 1);
      gl.drawArrays(gl.POINTS, 0, this.drawIndices.length);
    }
    this.skeletonLayer?.render();
    this.geometrySchedule?.();
    this.callbacks.render?.();
  }
  exportState() {
    return JSON.parse(JSON.stringify(this.camera));
  }
  importState(camera) {
    this.cameraTouched = true;
    this.camera = JSON.parse(JSON.stringify(camera));
    this.draw();
  }
}
