"use strict";

/* Cached skeletons in EM micrometres. Rendering never reads raw files or runs a model. */
class SkeletonLayer {
  constructor(view, options = {}) {
    this.view = view;
    this.options = options;
    this.objects = new Map();
    this.settings = {
      enabled: true,
      diameter: .3,
      radius_scale: 1,
      background: .15,
      quality: 'balanced',
      ...options.settings
    };
    this.maxBytes = options.maxBytes || 64 * 1024 * 1024;
    this.maxSegments = options.maxSegments || 240000;
    this.maxBackgroundSegments = options.maxBackgroundSegments || 350000;
    this.maxTubeSegments = options.maxTubeSegments || 90000;
    this.bytes = 0;
    this.segments = 0;
    this.clock = 0;
    this.lost = false;
    this.disposed = false;
    this.meshes = new Map();
    this.background = null;
    this.objectRevision = 0;
    this.onLost = () => {
      this.lost = true;
      for (const object of this.objects.values()) object.gpu = null;
      if (this.background) this.background.gpu = null;
      this.meshes.clear();
      this.program = null;
    };
    this.onRestored = () => {
      this.lost = false;
      this.initialize();
      for (const object of this.objects.values()) this.upload(object);
      this.uploadBackground();
      this.view.draw();
    };
    view.canvas.addEventListener('webglcontextlost', this.onLost);
    view.canvas.addEventListener('webglcontextrestored', this.onRestored);
    this.initialize();
  }
  initialize() {
    const gl = this.view.gl;
    if (!gl || this.disposed || this.lost) return;
    this.gl = gl;
    this.instancing = gl.getExtension('ANGLE_instanced_arrays');
    if (!this.instancing) {
      this.options.status?.(UI.msg("skeleton.view.controls.gpu_d4d033", {}));
    }
    const vertex = `
      attribute vec3 aVertex;
      attribute vec3 aNormal;
      attribute vec3 aStart;
      attribute vec3 aEnd;
      attribute vec2 aRadii;
      uniform vec3 uCenter;
      uniform float uSpan, uYaw, uPitch, uZoom, uAspect;
      uniform vec2 uPan;
      uniform float uSphere, uFallback, uRadiusScale;
      varying vec3 vNormal;
      vec3 turn(vec3 p) {
        float x = cos(uYaw)*p.x + sin(uYaw)*p.z;
        float z = -sin(uYaw)*p.x + cos(uYaw)*p.z;
        return vec3(x, cos(uPitch)*p.y - sin(uPitch)*z,
                    sin(uPitch)*p.y + cos(uPitch)*z);
      }
      void main() {
        float ra = aRadii.x > 0. ? aRadii.x*uRadiusScale : uFallback;
        float rb = aRadii.y > 0. ? aRadii.y*uRadiusScale : uFallback;
        ra = clamp(ra, .001, 40.);
        rb = clamp(rb, .001, 40.);
        vec3 p;
        vec3 normal;
        if (uSphere > .5) {
          p = aStart + aVertex*ra;
          normal = aNormal;
        } else {
          vec3 direction = aEnd-aStart;
          float distance = max(length(direction), .000001);
          vec3 axis = direction/distance;
          vec3 helper = abs(axis.z) < .9 ? vec3(0.,0.,1.) : vec3(0.,1.,0.);
          vec3 side = normalize(cross(axis, helper));
          vec3 up = cross(axis, side);
          float radius = mix(ra, rb, aVertex.z);
          p = mix(aStart, aEnd, aVertex.z) +
              (side*aVertex.x + up*aVertex.y)*radius;
          normal = normalize(side*aNormal.x + up*aNormal.y +
                             axis*((ra-rb)/distance));
        }
        vec3 eye = turn((p-uCenter)/uSpan);
        gl_Position = vec4(eye.x*1.7*uZoom/uAspect+uPan.x,
                           eye.y*1.7*uZoom+uPan.y, eye.z*.15, 1.);
        vNormal = turn(normal);
      }`;
    const fragment = `
      precision mediump float;
      uniform vec4 uColor;
      uniform float uLit;
      varying vec3 vNormal;
      void main() {
        vec3 n = normalize(vNormal);
        vec3 light = normalize(vec3(-.35,.65,-1.));
        float diffuse = max(dot(n, light), 0.);
        float rim = pow(1.-abs(n.z), 3.);
        float brightness = mix(1., .52+.42*diffuse+.06*rim, uLit);
        gl_FragColor = vec4(uColor.rgb*brightness, uColor.a);
      }`;
    const lineVertex = `
      attribute vec3 aVertex;
      attribute vec4 aColor;
      uniform vec3 uCenter;
      uniform float uSpan, uYaw, uPitch, uZoom, uAspect;
      uniform vec2 uPan;
      varying vec4 vColor;
      void main() {
        vec3 p = (aVertex-uCenter)/uSpan;
        float x = cos(uYaw)*p.x+sin(uYaw)*p.z;
        float z = -sin(uYaw)*p.x+cos(uYaw)*p.z;
        float y = cos(uPitch)*p.y-sin(uPitch)*z;
        float d = sin(uPitch)*p.y+cos(uPitch)*z;
        gl_Position = vec4(x*1.7*uZoom/uAspect+uPan.x,
                           y*1.7*uZoom+uPan.y,d*.15,1.);
        vColor = aColor;
      }`;
    const lineFragment = `
      precision mediump float;
      uniform vec4 uColor;
      uniform float uUseVertexColor;
      varying vec4 vColor;
      void main() {
        vec4 color = uUseVertexColor > .5 ? vColor : uColor;
        if (color.a <= 0.) discard;
        gl_FragColor = color;
      }`;
    this.program = this.makeProgram(vertex, fragment);
    this.lineProgram = this.makeProgram(lineVertex, lineFragment);
    this.locations = this.getLocations(this.program, true);
    this.lineLocations = this.getLocations(this.lineProgram, false);
  }
  makeProgram(vertex, fragment) {
    const gl = this.gl;
    const program = gl.createProgram();
    const shaders = [];
    try {
      for (const [type, source] of [[gl.VERTEX_SHADER, vertex], [gl.FRAGMENT_SHADER, fragment]]) {
        const shader = gl.createShader(type);
        shaders.push(shader);
        gl.shaderSource(shader, source);
        gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
          throw UI.errorValue(UI.join([UI.msg("skeleton.view.controls.message_6f8676", {}), gl.getShaderInfoLog(shader)]));
        }
        gl.attachShader(program, shader);
      }
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        throw UI.errorValue(UI.join([UI.msg("skeleton.view.controls.message_6f8676", {}), gl.getProgramInfoLog(program)]));
      }
      return program;
    } catch (error) {
      gl.deleteProgram(program);
      throw error;
    } finally {
      for (const shader of shaders) gl.deleteShader(shader);
    }
  }
  getLocations(program, tubes) {
    const gl = this.gl;
    const attributes = {};
    const uniforms = {};
    for (const name of tubes ? ['Vertex', 'Normal', 'Start', 'End', 'Radii'] : ['Vertex', 'Color']) {
      attributes[name] = gl.getAttribLocation(program, 'a' + name);
    }
    const names = ['Center', 'Span', 'Yaw', 'Pitch', 'Zoom', 'Aspect', 'Pan', 'Color'];
    if (tubes) names.push('Sphere', 'Fallback', 'RadiusScale', 'Lit');else names.push('UseVertexColor');
    for (const name of names) uniforms[name] = gl.getUniformLocation(program, 'u' + name);
    return {
      attributes,
      uniforms
    };
  }
  setSettings(settings) {
    const next = {
      ...this.settings,
      ...settings
    };
    if (typeof next.enabled !== 'boolean') throw UI.error("skeleton.view.controls.message_4824be", {});
    for (const name of ['diameter', 'radius_scale', 'background']) {
      if (!Number.isFinite(Number(next[name]))) throw UI.errorValue(UI.join([UI.msg("skeleton.view.controls.message_458aee", {}), name]));
      next[name] = Number(next[name]);
    }
    if (next.diameter <= 0 || next.diameter > 80 || next.radius_scale <= 0 || next.radius_scale > 100) {
      throw UI.error("skeleton.view.controls.0_80_m_zoom_in_0_100_2b9535", {});
    }
    if (next.background < 0 || next.background > 1) throw UI.error("skeleton.view.controls.background_intensity_0_1_dcb78f", {});
    if (!['low', 'balanced', 'high'].includes(next.quality)) throw UI.error("skeleton.view.controls.display_quality_f7cf7b", {});
    this.settings = next;
    if (this.background) this.background.styleSignature = null;
    this.view.draw();
    return {
      ...this.settings
    };
  }
  put(id, data) {
    id = String(id);
    if (!/^\d+$/.test(id)) throw UI.error("skeleton.view.controls.body_id_ef0768", {});
    const points = data.points;
    const edges = data.edges;
    if (!(points instanceof Float32Array) || points.length % 3 || !(edges instanceof Uint32Array) || edges.length % 2) {
      throw UI.errorValue(UI.join([UI.msg("skeleton.view.controls.message_abb399", {}), id]));
    }
    const count = points.length / 3;
    if (!count) throw UI.errorValue(UI.join([UI.msg("skeleton.view.controls.message_27406b", {}), id]));
    const radii = data.radii || new Float32Array(count);
    if (!(radii instanceof Float32Array) || radii.length !== count) throw UI.errorValue(UI.join([UI.msg("skeleton.view.controls.count_3485b4", {}), id]));
    const low = [Infinity, Infinity, Infinity];
    const high = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < points.length; i++) {
      const value = points[i];
      if (!Number.isFinite(value)) throw UI.errorValue(UI.join([UI.msg("skeleton.view.controls.message_dd822b", {}), id]));
      const k = i % 3;
      low[k] = Math.min(low[k], value);
      high[k] = Math.max(high[k], value);
    }
    const usable = [];
    const connected = new Set();
    for (let i = 0; i < edges.length; i += 2) {
      const a = edges[i],
        b = edges[i + 1];
      if (a >= count || b >= count) throw UI.errorValue(UI.join([UI.msg("skeleton.view.controls.connections_972d3c", {}), id]));
      connected.add(a);
      connected.add(b);
      const distance = Math.hypot(points[a * 3] - points[b * 3], points[a * 3 + 1] - points[b * 3 + 1], points[a * 3 + 2] - points[b * 3 + 2]);
      if (distance > .000001) usable.push(a, b);
    }
    for (const value of radii) if (!Number.isFinite(value) || value < 0) throw UI.errorValue(UI.join([UI.msg("skeleton.view.controls.message_9bcfef", {}), id]));
    const validEdges = new Uint32Array(usable);
    const jointIndices = new Uint32Array(connected.size ? connected : Array.from({
      length: count
    }, (_, i) => i));
    const segmentCount = validEdges.length / 2;
    // Lines, tapered-cylinder instances, joint instances, plus retained packed input.
    const bytes = points.byteLength + edges.byteLength + radii.byteLength + validEdges.byteLength + segmentCount * 56 + jointIndices.byteLength + jointIndices.length * 32;
    if (bytes > this.maxBytes || segmentCount > this.maxSegments) {
      throw UI.errorValue(UI.join([UI.msg("skeleton.view.controls.budget_702864", {}), id]));
    }
    const previous = this.objects.get(id);
    const extraBytes = bytes - (previous?.bytes || 0);
    const extraSegments = segmentCount - (previous?.segmentCount || 0);
    if (!this.makeRoom(extraBytes, extraSegments, id)) return false;
    if (previous) this.remove(id);
    const object = {
      id,
      points,
      radii,
      edges: validEdges,
      jointIndices,
      bounds: [low, high],
      level: Number(data.level || 0),
      bytes,
      segmentCount,
      touched: ++this.clock,
      gpu: null,
      projected: null
    };
    this.objects.set(id, object);
    this.objectRevision++;
    this.bytes += bytes;
    this.segments += segmentCount;
    this.upload(object);
    this.view.draw();
    return true;
  }
  makeRoom(bytes, segments, incoming) {
    const candidates = [...this.objects.values()].filter(object => object.id !== incoming);
    candidates.sort((a, b) => Number(this.important(a.id)) - Number(this.important(b.id)) || a.touched - b.touched);
    while (this.bytes + bytes > this.maxBytes || this.segments + segments > this.maxSegments) {
      const object = candidates.shift();
      if (!object || this.important(object.id) && !this.important(incoming)) return false;
      this.remove(object.id);
      this.options.evicted?.(object.id);
    }
    return true;
  }
  important(id) {
    return id === this.view.focus || this.view.selected.has(id) || this.view.highlight.has(id);
  }
  createBuffer(data) {
    const gl = this.gl;
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    return buffer;
  }
  upload(object) {
    if (!this.gl || this.lost || this.disposed) return;
    const lines = new Float32Array(object.segmentCount * 6);
    const instances = new Float32Array(object.segmentCount * 8);
    for (let i = 0; i < object.segmentCount; i++) {
      const a = object.edges[i * 2],
        b = object.edges[i * 2 + 1];
      lines.set(object.points.subarray(a * 3, a * 3 + 3), i * 6);
      lines.set(object.points.subarray(b * 3, b * 3 + 3), i * 6 + 3);
      instances.set(lines.subarray(i * 6, i * 6 + 6), i * 8);
      instances[i * 8 + 6] = object.radii[a];
      instances[i * 8 + 7] = object.radii[b];
    }
    const joints = new Float32Array(object.jointIndices.length * 8);
    for (let i = 0; i < object.jointIndices.length; i++) {
      const index = object.jointIndices[i];
      joints.set(object.points.subarray(index * 3, index * 3 + 3), i * 8);
      joints.set(object.points.subarray(index * 3, index * 3 + 3), i * 8 + 3);
      joints[i * 8 + 6] = object.radii[index];
      joints[i * 8 + 7] = object.radii[index];
    }
    object.gpu = {
      lines: this.createBuffer(lines),
      segments: this.createBuffer(instances),
      joints: this.createBuffer(joints)
    };
  }
  remove(id) {
    id = String(id);
    const object = this.objects.get(id);
    if (!object) return false;
    if (object.gpu && this.gl && !this.lost) {
      for (const buffer of Object.values(object.gpu)) this.gl.deleteBuffer(buffer);
    }
    this.bytes -= object.bytes;
    this.segments -= object.segmentCount;
    this.objects.delete(id);
    this.objectRevision++;
    return true;
  }
  clear() {
    for (const id of [...this.objects.keys()]) this.remove(id);
    this.clearBackground();
    this.view.draw();
  }
  setBackground(data) {
    const points = data.points;
    const ids = data.ids;
    if (!(points instanceof Float32Array) || points.length % 6 || !Array.isArray(ids) || ids.length !== points.length / 6) {
      throw UI.error("skeleton.view.controls.message_31e6b4", {});
    }
    const exactIds = ids.map(String);
    for (const id of exactIds) if (!/^\d+$/.test(id)) throw UI.error("skeleton.view.controls.id_7adef3", {});
    for (const value of points) if (!Number.isFinite(value)) throw UI.error("skeleton.view.controls.message_cb6bbb", {});
    if (ids.length > this.maxBackgroundSegments) throw UI.error("skeleton.view.controls.budget_3fc1b1", {});
    // Resident packed CPU/GPU buffers and a conservative string-ID allowance.
    const bytes = points.byteLength * 2 + ids.length * 64 + exactIds.reduce((total, id) => total + id.length * 2 + 16, 0);
    const previousBytes = this.background?.bytes || 0;
    if (!this.makeRoom(bytes - previousBytes, 0, '__background__')) throw UI.error("skeleton.view.controls.budget_21323d", {});
    this.clearBackground();
    this.background = {
      points,
      ids: exactIds,
      colors: new Float32Array(ids.length * 8),
      bodyCount: new Set(exactIds).size,
      bytes,
      gpu: null,
      projected: null,
      styleSignature: null
    };
    this.bytes += bytes;
    this.uploadBackground();
    this.view.draw();
    return this.stats();
  }
  uploadBackground() {
    const background = this.background;
    if (!background || !this.gl || this.lost || this.disposed) return;
    background.gpu = {
      points: this.createBuffer(background.points),
      colors: this.createBuffer(background.colors)
    };
    background.styleSignature = null;
  }
  clearBackground() {
    if (!this.background) return;
    if (this.background.gpu && this.gl && !this.lost) {
      for (const buffer of Object.values(this.background.gpu)) this.gl.deleteBuffer(buffer);
    }
    this.bytes -= this.background.bytes;
    this.background = null;
  }
  backgroundStyle() {
    const background = this.background;
    if (!background?.gpu) return;
    const view = this.view;
    const signature = [view.activity, view.mode, view.domain, view.selected, view.highlight, view.focus, view.caseIds, view.activeNodes, view.filterIds, view.isolate, this.settings.background, this.objectRevision, view.displayLight];
    if (background.styleSignature && signature.every((value, i) => value === background.styleSignature[i])) return;
    const cached = new Map();
    for (let i = 0; i < background.ids.length; i++) {
      const id = background.ids[i];
      if (!cached.has(id)) {
        const color = this.color(id, false);
        if (!view.visible(id) || this.objects.has(id)) color[3] = 0;
        cached.set(id, color);
      }
      const color = cached.get(id);
      background.colors.set(color, i * 8);
      background.colors.set(color, i * 8 + 4);
    }
    this.gl.bindBuffer(this.gl.ARRAY_BUFFER, background.gpu.colors);
    this.gl.bufferSubData(this.gl.ARRAY_BUFFER, 0, background.colors);
    background.styleSignature = signature;
  }
  drawBackground() {
    const background = this.background;
    if (!background?.gpu || !background.ids.length) return;
    this.backgroundStyle();
    const gl = this.gl;
    const locations = this.lineLocations;
    gl.useProgram(this.lineProgram);
    this.cameraUniforms(locations);
    gl.uniform1f(locations.uniforms.UseVertexColor, 1);
    this.bindAttribute(locations.attributes.Vertex, background.gpu.points, 3);
    this.bindAttribute(locations.attributes.Color, background.gpu.colors, 4);
    gl.drawArrays(gl.LINES, 0, background.ids.length * 2);
    for (const location of Object.values(locations.attributes)) gl.disableVertexAttribArray(location);
  }
  mesh(kind, sides) {
    const key = kind + sides;
    if (this.meshes.has(key)) return this.meshes.get(key);
    const vertices = [];
    const normals = [];
    const add = (p, n) => {
      vertices.push(...p);
      normals.push(...n);
    };
    if (kind === 'cylinder') {
      for (let i = 0; i < sides; i++) {
        const a = i * 2 * Math.PI / sides,
          b = (i + 1) * 2 * Math.PI / sides;
        const n0 = [Math.cos(a), Math.sin(a), 0];
        const n1 = [Math.cos(b), Math.sin(b), 0];
        const p0 = [n0[0], n0[1], 0],
          p1 = [n1[0], n1[1], 0];
        const p2 = [n1[0], n1[1], 1],
          p3 = [n0[0], n0[1], 1];
        add(p0, n0);
        add(p1, n1);
        add(p2, n1);
        add(p0, n0);
        add(p2, n1);
        add(p3, n0);
      }
    } else {
      const rings = Math.max(4, Math.floor(sides / 2));
      const point = (a, b) => [Math.sin(a) * Math.cos(b), Math.sin(a) * Math.sin(b), Math.cos(a)];
      for (let i = 0; i < rings; i++) for (let j = 0; j < sides; j++) {
        const a = i * Math.PI / rings,
          b = (i + 1) * Math.PI / rings;
        const c = j * 2 * Math.PI / sides,
          d = (j + 1) * 2 * Math.PI / sides;
        const p0 = point(a, c),
          p1 = point(a, d),
          p2 = point(b, d),
          p3 = point(b, c);
        add(p0, p0);
        add(p1, p1);
        add(p2, p2);
        add(p0, p0);
        add(p2, p2);
        add(p3, p3);
      }
    }
    const mesh = {
      position: this.createBuffer(new Float32Array(vertices)),
      normal: this.createBuffer(new Float32Array(normals)),
      count: vertices.length / 3
    };
    this.meshes.set(key, mesh);
    return mesh;
  }
  color(id, detailed) {
    const view = this.view;
    let rgb = view.displayLight ? view.caseIds.has(id) ? [.26,.39,.33] : [.43,.48,.45] : view.caseIds.has(id) ? [.64,.75,.68] : [.40,.47,.43];
    const row = view.activity.get(id);
    const value = row?.[view.mode];
    const known = view.mode !== 'structure' && Number.isFinite(value);
    if (known) {
      rgb = spatialActivityColor(value, view.domain, view.mode);
    }
    if (view.highlight.has(id) && !known) rgb = [.24, .75, .70];
    if (view.selected.has(id) && !known) rgb = UI.rgb('selection');
    if (!known && view.activeNodes.has(id) && !['structure', 'baseline'].includes(view.mode)) rgb = [1, .5, .2];
    const important = this.important(id);
    if (important || detailed && !view.selected.size && !view.focus) return [...rgb, 1];
    return [...rgb, this.settings.background * (view.displayLight ? 1.8 : .7) * (view.selected.size || view.focus ? .35 : 1)];
  }
  cameraUniforms(locations) {
    const gl = this.gl;
    const c = this.view.camera;
    const r = this.view.canvas.getBoundingClientRect();
    const u = locations.uniforms;
    gl.uniform3fv(u.Center, c.center);
    gl.uniform1f(u.Span, c.span);
    gl.uniform1f(u.Yaw, c.yaw);
    gl.uniform1f(u.Pitch, c.pitch);
    gl.uniform1f(u.Zoom, c.zoom);
    gl.uniform1f(u.Aspect, r.width / r.height);
    gl.uniform2fv(u.Pan, c.pan);
  }
  screenBounds(object) {
    let left = Infinity,
      top = Infinity,
      right = -Infinity,
      bottom = -Infinity;
    for (const point of this.corners(object.bounds)) {
      const p = this.view.project(point);
      left = Math.min(left, p.x);
      right = Math.max(right, p.x);
      top = Math.min(top, p.y);
      bottom = Math.max(bottom, p.y);
    }
    return {
      left,
      top,
      right,
      bottom,
      size: Math.max(right - left, bottom - top)
    };
  }
  wantedTube(object, screen) {
    if (!this.instancing) return false;
    if (this.important(object.id)) return true;
    if (this.view.focus || this.view.selected.size) return false;
    if (this.moving || this.options.moving?.()) return false;
    if (this.settings.quality === 'low') return false;
    // Hysteresis avoids style thrashing at a stationary LOD boundary.
    const threshold = object.tubular ? 80 : 120;
    return object.level <= 1 && screen.size > threshold;
  }
  bindAttribute(location, buffer, size, stride = 0, offset = 0, divisor = 0) {
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.enableVertexAttribArray(location);
    gl.vertexAttribPointer(location, size, gl.FLOAT, false, stride, offset);
    this.instancing?.vertexAttribDivisorANGLE(location, divisor);
  }
  drawTube(object, sides) {
    const gl = this.gl;
    const attrs = this.locations.attributes;
    const u = this.locations.uniforms;
    gl.useProgram(this.program);
    this.cameraUniforms(this.locations);
    gl.uniform4fv(u.Color, this.color(object.id, true));
    gl.uniform1f(u.Fallback, this.settings.diameter / 2);
    gl.uniform1f(u.RadiusScale, this.settings.radius_scale);
    gl.uniform1f(u.Lit, this.view.mode === 'structure' ? 1 : 0);
    const draw = (kind, buffer, count, sphere) => {
      if (!count) return;
      const mesh = this.mesh(kind, sides);
      this.bindAttribute(attrs.Vertex, mesh.position, 3);
      this.bindAttribute(attrs.Normal, mesh.normal, 3);
      this.bindAttribute(attrs.Start, buffer, 3, 32, 0, 1);
      this.bindAttribute(attrs.End, buffer, 3, 32, 12, 1);
      this.bindAttribute(attrs.Radii, buffer, 2, 32, 24, 1);
      gl.uniform1f(u.Sphere, sphere);
      this.instancing.drawArraysInstancedANGLE(gl.TRIANGLES, 0, mesh.count, count);
    };
    if (this.view.selected.has(object.id) || this.view.focus === object.id) {
      // Back-face silhouette is display-only and leaves the recorded fill color intact.
      gl.enable(gl.CULL_FACE);
      gl.cullFace(gl.FRONT);
      gl.depthMask(false);
      gl.uniform4fv(u.Color, [...UI.rgb('selection'), 1]);
      gl.uniform1f(u.Lit, 0);
      gl.uniform1f(u.Fallback, this.settings.diameter * .8);
      gl.uniform1f(u.RadiusScale, this.settings.radius_scale * 1.6);
      draw('cylinder', object.gpu.segments, object.segmentCount, 0);
      gl.disable(gl.CULL_FACE);
      gl.depthMask(true);
      gl.uniform4fv(u.Color, this.color(object.id, true));
      gl.uniform1f(u.Lit, this.view.mode === 'structure' ? 1 : 0);
      gl.uniform1f(u.Fallback, this.settings.diameter / 2);
      gl.uniform1f(u.RadiusScale, this.settings.radius_scale);
    }
    draw('cylinder', object.gpu.segments, object.segmentCount, 0);
    // Active-event markers do not replace the recorded response color of branches.
    if (this.view.activeNodes.has(object.id) && !['structure', 'baseline'].includes(this.view.mode)) {
      gl.uniform4fv(u.Color, [1, .5, .2, 1]);
    }
    draw('sphere', object.gpu.joints, object.jointIndices.length, 1);
    for (const location of Object.values(attrs)) {
      this.instancing.vertexAttribDivisorANGLE(location, 0);
      gl.disableVertexAttribArray(location);
    }
  }
  drawLine(object) {
    const gl = this.gl;
    const attrs = this.lineLocations.attributes;
    gl.useProgram(this.lineProgram);
    this.cameraUniforms(this.lineLocations);
    gl.uniform4fv(this.lineLocations.uniforms.Color, this.color(object.id, false));
    gl.uniform1f(this.lineLocations.uniforms.UseVertexColor, 0);
    gl.disableVertexAttribArray(attrs.Color);
    gl.vertexAttrib4f(attrs.Color, 1, 1, 1, 1);
    this.bindAttribute(attrs.Vertex, object.gpu.lines, 3);
    gl.drawArrays(gl.LINES, 0, object.segmentCount * 2);
    gl.disableVertexAttribArray(attrs.Vertex);
  }
  render() {
    if (!this.settings.enabled) {
      this.lastRender = {
        visible_objects: 0,
        tube_objects: 0,
        tube_segments: 0,
        line_objects: 0
      };
      return;
    }
    if (!this.gl || this.lost || this.disposed || !this.program) return;
    const gl = this.gl;
    const r = this.view.canvas.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const objects = [];
    for (const object of this.objects.values()) {
      if (!object.gpu || !this.view.visible(object.id)) continue;
      const screen = this.screenBounds(object);
      if (screen.right < 0 || screen.bottom < 0 || screen.left > r.width || screen.top > r.height) continue;
      objects.push({
        object,
        screen
      });
    }
    objects.sort((a, b) => Number(this.important(b.object.id)) - Number(this.important(a.object.id)) || b.screen.size - a.screen.size || a.object.id.localeCompare(b.object.id));
    let tubeSegments = 0,
      tubeObjects = 0;
    const lines = [];
    const sides = this.settings.quality === 'high' ? 12 : this.settings.quality === 'low' ? 6 : 8;
    gl.enable(gl.DEPTH_TEST);
    gl.depthFunc(gl.LEQUAL);
    gl.depthMask(true);
    gl.disable(gl.CULL_FACE);
    gl.disable(gl.BLEND);
    for (const {
      object,
      screen
    } of objects) {
      const tube = this.wantedTube(object, screen) && tubeSegments + object.segmentCount <= this.maxTubeSegments;
      object.tubular = tube;
      if (tube) {
        this.drawTube(object, sides);
        tubeSegments += object.segmentCount;
        tubeObjects++;
      } else lines.push(object);
    }
    gl.enable(gl.BLEND);
    gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.depthMask(false);
    for (const object of lines) this.drawLine(object);
    gl.depthMask(true);
    this.drawBackground();
    gl.depthMask(true);
    gl.depthFunc(gl.LESS);
    this.lastRender = {
      visible_objects: objects.length,
      tube_objects: tubeObjects,
      tube_segments: tubeSegments,
      line_objects: lines.length
    };
  }
  corners(bounds) {
    const [low, high] = bounds;
    const out = [];
    for (let i = 0; i < 8; i++) out.push([i & 1 ? high[0] : low[0], i & 2 ? high[1] : low[1], i & 4 ? high[2] : low[2]]);
    return out;
  }
  positions(id) {
    const object = this.objects.get(String(id));
    return object ? this.corners(object.bounds) : [];
  }
  projected(object) {
    const c = this.view.camera;
    const r = this.view.canvas.getBoundingClientRect();
    const key = JSON.stringify([c, r.width, r.height]);
    if (object.projected?.key === key) return object.projected.values;
    const values = new Float32Array(object.points.length);
    const yawCos = Math.cos(c.yaw),
      yawSin = Math.sin(c.yaw),
      pitchCos = Math.cos(c.pitch),
      pitchSin = Math.sin(c.pitch);
    const scale = r.height * .85 * c.zoom / c.span;
    for (let i = 0; i < object.points.length; i += 3) {
      const x = object.points[i] - c.center[0],
        y = object.points[i + 1] - c.center[1],
        z = object.points[i + 2] - c.center[2];
      const rx = yawCos * x + yawSin * z,
        rz = -yawSin * x + yawCos * z;
      values[i] = (1 + c.pan[0]) * r.width / 2 + rx * scale;
      values[i + 1] = (1 - c.pan[1]) * r.height / 2 - (pitchCos * y - pitchSin * rz) * scale;
      values[i + 2] = (pitchSin * y + pitchCos * rz) * .15 / c.span;
    }
    object.projected = {
      key,
      values
    };
    return values;
  }
  pickHit(x, y) {
    if (!this.settings.enabled || this.lost || this.disposed) return null;
    let best = null;
    const r = this.view.canvas.getBoundingClientRect();
    const pixels = r.height * .85 * this.view.camera.zoom / this.view.camera.span;
    for (const object of this.objects.values()) {
      if (!object.gpu || !this.view.visible(object.id)) continue;
      const screen = this.screenBounds(object);
      if (x < screen.left - 8 || x > screen.right + 8 || y < screen.top - 8 || y > screen.bottom + 8) continue;
      const points = this.projected(object);
      for (let i = 0; i < object.edges.length; i += 2) {
        const ia = object.edges[i],
          ib = object.edges[i + 1],
          a = ia * 3,
          b = ib * 3;
        const dx = points[b] - points[a],
          dy = points[b + 1] - points[a + 1];
        const t = Math.max(0, Math.min(1, ((x - points[a]) * dx + (y - points[a + 1]) * dy) / (dx * dx + dy * dy || 1)));
        const depth = points[a + 2] + t * (points[b + 2] - points[a + 2]);
        if (depth < -1 || depth > 1) continue;
        const distance = Math.hypot(x - points[a] - t * dx, y - points[a + 1] - t * dy);
        const radiusA = object.radii[ia] > 0 ? object.radii[ia] * this.settings.radius_scale : this.settings.diameter / 2;
        const radiusB = object.radii[ib] > 0 ? object.radii[ib] * this.settings.radius_scale : this.settings.diameter / 2;
        const radius = object.tubular ? Math.min(40, radiusA * (1 - t) + radiusB * t) * pixels : 1;
        if (distance > Math.max(4, radius + 2)) continue;
        if (!best || depth < best.depth - .00001 || Math.abs(depth - best.depth) < .00001 && distance < best.distance) {
          best = {
            body_id: object.id,
            depth,
            distance
          };
        }
      }
      if (!object.edges.length) for (let i = 0; i < points.length; i += 3) {
        const distance = Math.hypot(x - points[i], y - points[i + 1]);
        if (distance <= 5 && (!best || points[i + 2] < best.depth)) best = {
          body_id: object.id,
          depth: points[i + 2],
          distance
        };
      }
    }
    const background = this.background;
    if (background?.gpu) {
      const points = this.projected(background);
      for (let i = 0; i < background.ids.length; i++) {
        const id = background.ids[i],
          a = i * 6,
          b = a + 3;
        if (this.objects.has(id) || !this.view.visible(id)) continue;
        const dx = points[b] - points[a],
          dy = points[b + 1] - points[a + 1];
        const t = Math.max(0, Math.min(1, ((x - points[a]) * dx + (y - points[a + 1]) * dy) / (dx * dx + dy * dy || 1)));
        const depth = points[a + 2] + t * (points[b + 2] - points[a + 2]);
        if (depth < -1 || depth > 1) continue;
        const distance = Math.hypot(x - points[a] - t * dx, y - points[a + 1] - t * dy);
        if (distance > 4) continue;
        if (!best || depth < best.depth - .00001 || Math.abs(depth - best.depth) < .00001 && distance < best.distance) {
          best = {
            body_id: id,
            depth,
            distance
          };
        }
      }
    }
    if (best && this.objects.has(best.body_id)) this.objects.get(best.body_id).touched = ++this.clock;
    return best;
  }
  pick(x, y) {
    return this.pickHit(x, y)?.body_id || null;
  }
  region(rect) {
    if (!this.settings.enabled || this.lost || this.disposed) return [];
    const [left, top, right, bottom] = rect;
    const ids = [];
    const within = (x, y) => x >= left && x <= right && y >= top && y <= bottom;
    const crosses = (points, a, b) => {
      if (Math.max(points[a + 2], points[b + 2]) < -1 || Math.min(points[a + 2], points[b + 2]) > 1) return false;
      const dx = points[b] - points[a],
        dy = points[b + 1] - points[a + 1];
      const p = [-dx, dx, -dy, dy],
        q = [points[a] - left, right - points[a], points[a + 1] - top, bottom - points[a + 1]];
      let low = 0,
        high = 1;
      for (let k = 0; k < 4; k++) {
        if (!p[k]) {
          if (q[k] < 0) return false;
        } else {
          const ratio = q[k] / p[k];
          if (p[k] < 0) low = Math.max(low, ratio);else high = Math.min(high, ratio);
        }
      }
      return low <= high;
    };
    for (const object of this.objects.values()) {
      if (!object.gpu || !this.view.visible(object.id)) continue;
      const points = this.projected(object);
      let hit = false;
      for (let i = 0; i < points.length; i += 3) {
        if (points[i + 2] >= -1 && points[i + 2] <= 1 && within(points[i], points[i + 1])) {
          hit = true;
          break;
        }
      }
      if (!hit) for (let i = 0; i < object.edges.length; i += 2) {
        const a = object.edges[i] * 3,
          b = object.edges[i + 1] * 3;
        if (Math.max(points[a + 2], points[b + 2]) < -1 || Math.min(points[a + 2], points[b + 2]) > 1) continue;
        // Liang-Barsky clipping includes a branch crossing a box whose endpoints lie outside.
        const dx = points[b] - points[a],
          dy = points[b + 1] - points[a + 1];
        const p = [-dx, dx, -dy, dy];
        const q = [points[a] - left, right - points[a], points[a + 1] - top, bottom - points[a + 1]];
        let low = 0,
          high = 1,
          valid = true;
        for (let k = 0; k < 4; k++) {
          if (!p[k]) {
            if (q[k] < 0) valid = false;
          } else {
            const ratio = q[k] / p[k];
            if (p[k] < 0) low = Math.max(low, ratio);else high = Math.min(high, ratio);
          }
        }
        if (valid && low <= high) {
          hit = true;
          break;
        }
      }
      if (hit) ids.push(object.id);
    }
    if (this.background?.gpu) {
      const background = this.background,
        points = this.projected(background),
        seen = new Set(ids);
      for (let i = 0; i < background.ids.length; i++) {
        const id = background.ids[i];
        if (seen.has(id) || this.objects.has(id) || !this.view.visible(id)) continue;
        if (crosses(points, i * 6, i * 6 + 3)) {
          ids.push(id);
          seen.add(id);
        }
      }
    }
    return ids;
  }
  stats() {
    return {
      objects: this.objects.size,
      segments: this.segments,
      bytes: this.bytes,
      background_count: this.background?.ids.length || 0,
      background_body_count: this.background?.bodyCount || 0,
      instancing: !!this.instancing,
      max_bytes: this.maxBytes,
      max_segments: this.maxSegments,
      max_background_segments: this.maxBackgroundSegments,
      max_tube_segments: this.maxTubeSegments,
      ...this.lastRender
    };
  }
  dispose() {
    this.clear();
    if (this.gl && !this.lost) {
      for (const mesh of this.meshes.values()) {
        this.gl.deleteBuffer(mesh.position);
        this.gl.deleteBuffer(mesh.normal);
      }
      if (this.program) this.gl.deleteProgram(this.program);
      if (this.lineProgram) this.gl.deleteProgram(this.lineProgram);
    }
    this.meshes.clear();
    this.view.canvas.removeEventListener('webglcontextlost', this.onLost);
    this.view.canvas.removeEventListener('webglcontextrestored', this.onRestored);
    this.disposed = true;
  }
}
