"use strict";

/* Published geometry scheduling. Raw directories are read only by explicit update. */
class SkeletonStreaming {
  constructor(view) {
    this.view = view;
    this.layer = new SkeletonLayer(view, {
      status: message => this.status(message),
      evicted: id => this.loaded?.delete(id)
    });
    view.skeletonLayer = this.layer;
    view.geometrySchedule = () => this.cameraChanged();
    this.catalog = new Map();
    this.loaded = new Map();
    this.pending = new Map();
    this.epoch = 0;
    this.manifest = null;
    this.timer = null;
    this.cameraKey = '';
    this.worker = new Worker('/skeleton_worker.js');
    this.decodePending = new Map();
    this.token = 0;
    this.worker.onmessage = ({
      data
    }) => {
      const pending = this.decodePending.get(data.token);
      if (!pending) return;
      this.decodePending.delete(data.token);
      data.error ? pending.reject(UI.error('geometry.error.' + (data.error_code || 'decode'), {}, data.error_code === 'decode' ? data.error : '')) : pending.resolve(data);
    };
    this.worker.onerror = () => {
      for (const p of this.decodePending.values()) p.reject(UI.error("skeleton.controls.failed_569fca", {}));
      this.decodePending.clear();
    };
    this.settings = {
      enabled: true,
      diameter: .3,
      radius_scale: 1,
      background: .15,
      quality: 'balanced'
    };
    this.maxObjects = 32;
    this.maxBytes = 64 * 1024 ** 2;
    this.maxEdges = 240000;
    this.viewRequest = null;
    this.viewRevision = 0;
    this.baseBackground = null;
  }
  status(message, error = false) {
    UI.text($('space_geometry_status'), message);
    $('space_geometry_status').classList.toggle('error', error);
  }
  async decode(kind, buffer) {
    const token = ++this.token;
    return new Promise((resolve, reject) => {
      this.decodePending.set(token, {
        resolve,
        reject
      });
      this.worker.postMessage({
        token,
        kind,
        buffer
      }, [buffer]);
    });
  }
  async bytes(path, signal) {
    const response = await fetch(path, {
      signal
    });
    if (!response.ok) throw UI.apiError(await response.json());
    return response.arrayBuffer();
  }
  async load() {
    const epoch = ++this.epoch;
    for (const p of this.pending.values()) p.abort();
    this.pending.clear();
    clearTimeout(this.timer);
    this.viewRequest?.abort();
    this.backgroundRequest?.abort();
    const header = await api('/api/skeleton-cache/overview?offset=0&limit=0');
    if (epoch !== this.epoch) return;
    let background = {
      points: new Float32Array(),
      ids: []
    };
    if (header.coverage?.valid) {
      const buffer = await this.bytes('/api/skeleton-cache/background?' + new URLSearchParams({
        cache_id: header.cache_id,
        max_edges: this.settings.quality === 'high' ? 300000 : 64000
      }));
      background = await this.decode('background', buffer);
      if (epoch !== this.epoch) return;
    }
    if (epoch !== this.epoch) return;
    // Header + bounded global overview only; no full object directory in browser.
    this.manifest = header;
    this.backgroundLimit = this.settings.quality === 'high' ? 300000 : 64000;
    this.catalog = new Map();
    this.baseBackground = background;
    for (const id of background.ids) spatialKnownIds.add(id);
    this.layer.clear();
    this.loaded.clear();
    this.view.geometryPositions = new Map();
    this.view.geometryBounds = header.bounds;
    this.layer.setBackground(background);
    this.layer.setSettings(this.settings);
    if (!this.view.geometryInitialized) {
      this.view.geometryInitialized = true;
      if (!this.view.cameraTouched) this.view.home(false);
    }
    this.showCoverage();
    this.schedule();
    this.view.draw();
    return header;
  }
  showCoverage() {
    const h = this.manifest,
      c = h?.coverage || {};
    UI.text($('space_geometry_coverage'), h ? UI.msg("skeleton.controls.skeletons_annotated_unannotated_invalid_over_limit_mib_b_6e5145", {
      p0: c.valid ?? 0,
      p1: c.expected ?? '—',
      p2: c.annotated ?? 0,
      p3: c.unannotated ?? 0,
      p4: c.invalid ?? 0,
      p5: c.over_limit ?? 0,
      p6: UI.fixed(c.cache_bytes / 1024 ** 2, 1),
      p7: new Set(this.layer.background?.ids || []).size
    }) : UI.msg("skeleton.controls.message_615506", {}));
    this.status(UI.msg("skeleton.controls.geometry_loaded_awaiting_processing_1bcade", {
      p0: c.downloaded_unprocessed ?? 0
    }));
  }
  cameraChanged() {
    const key = JSON.stringify(this.view.camera) + this.view.focus + this.view.visibilityRevision;
    if (key === this.cameraKey) return;
    this.cameraKey = key;
    clearTimeout(this.timer);
    this.layer.moving = true;
    this.viewRequest?.abort();
    this.timer = setTimeout(() => {
      this.layer.moving = false;
      this.schedule();
      this.view.draw();
    }, 220);
  }
  queryBounds() {
    const c = this.view.camera,
      r = this.view.canvas.getBoundingClientRect(),
      global = this.manifest.bounds;
    if (!global) return null;
    const corners = [];
    for (let i = 0; i < 8; i++) corners.push([global[i >> 0 & 1][0], global[i >> 1 & 1][1], global[i >> 2 & 1][2]]);
    const depth = corners.map(p => this.view.project(p).depth * c.span / .15);
    const low = [Infinity, Infinity, Infinity],
      high = [-Infinity, -Infinity, -Infinity];
    for (const px of [-1, 1]) for (const py of [-1, 1]) for (const d of [Math.min(...depth), Math.max(...depth)]) {
      const x = (px - c.pan[0]) * (r.width / r.height) * c.span / (1.7 * c.zoom),
        y = (py - c.pan[1]) * c.span / (1.7 * c.zoom);
      const originalY = Math.cos(c.pitch) * y + Math.sin(c.pitch) * d,
        z = -Math.sin(c.pitch) * y + Math.cos(c.pitch) * d;
      const p = [Math.cos(c.yaw) * x - Math.sin(c.yaw) * z, originalY, Math.sin(c.yaw) * x + Math.cos(c.yaw) * z];
      for (let k = 0; k < 3; k++) {
        p[k] += c.center[k];
        low[k] = Math.min(low[k], p[k]);
        high[k] = Math.max(high[k], p[k]);
      }
    }
    return [low, high];
  }
  mergeBackground(local) {
    const base = this.baseBackground,
      replace = new Set(local.ids),
      keep = [];
    for (let i = 0; i < base.ids.length; i++) if (!replace.has(base.ids[i])) keep.push(i);
    const points = new Float32Array((keep.length + local.ids.length) * 6),
      ids = [];
    keep.forEach((i, j) => {
      points.set(base.points.subarray(i * 6, i * 6 + 6), j * 6);
      ids.push(base.ids[i]);
    });
    points.set(local.points, keep.length * 6);
    ids.push(...local.ids);
    this.layer.setBackground({
      points,
      ids
    });
  }
  queryPlanes() {
    const c = this.view.camera,
      r = this.view.canvas.getBoundingClientRect();
    const x = [Math.cos(c.yaw), 0, Math.sin(c.yaw)],
      y = [Math.sin(c.pitch) * Math.sin(c.yaw), Math.cos(c.pitch), -Math.sin(c.pitch) * Math.cos(c.yaw)];
    const planes = [];
    for (const [axis, pan, scale] of [[x, c.pan[0], r.width / r.height], [y, c.pan[1], 1]]) {
      const offset = axis.reduce((sum, v, k) => sum + v * c.center[k], 0);
      const low = (-1 - pan) * scale * c.span / (1.7 * c.zoom),
        high = (1 - pan) * scale * c.span / (1.7 * c.zoom);
      planes.push([...axis, -offset - low], [...axis.map(v => -v), offset + high]);
    }
    return planes;
  }
  priority(entry) {
    const id = String(entry.body_id),
      bounds = entry.bounds;
    if (!bounds || !this.view.visible(id)) return null;
    const selected = this.view.selected.has(id) || id === this.view.focus;
    const projected = bounds.map(p => this.view.project(p));
    // A bounding sphere conservatively covers long bodies even across tiles.
    const center = bounds[0].map((v, k) => (v + bounds[1][k]) / 2),
      p = this.view.project(center);
    const r = this.view.canvas.getBoundingClientRect();
    const size = Math.hypot(...bounds[1].map((v, k) => v - bounds[0][k])) / this.view.camera.span * this.view.camera.zoom * r.height * .85;
    if (!selected && (p.x + size < 0 || p.x - size > r.width || p.y + size < 0 || p.y - size > r.height || Math.abs(p.depth) > 1 + size / r.height)) return null;
    if (!selected && size < 70) return null;
    const lods = Array.isArray(entry.lods) ? entry.lods : Object.entries(entry.lods || {}).map(([level, v]) => ({
      ...v,
      level: Number(level)
    }));
    lods.sort((a, b) => Number(a.level) - Number(b.level));
    if (!lods.length) return null;
    const desired = selected || size > 500 ? 0 : size > 180 ? 1 : 2;
    let lod = lods.find(v => Number(v.level) === desired) || lods[lods.length - 1];
    if (selected && (lod.edges > this.layer.maxTubeSegments || lod.bytes > this.maxBytes / 3)) {
      lod = lods.find(v => v.edges <= this.layer.maxTubeSegments && v.bytes <= this.maxBytes / 3) || lods[lods.length - 1];
      if (lod.estimated) lod = {
        ...lod,
        reserve_bytes: 16 * 1024 ** 2,
        reserve_edges: this.layer.maxTubeSegments
      };
    }
    const previous = this.loaded.get(id);
    // Small hysteresis band keeps camera jitter from changing levels.
    if (previous && !selected && previous.level === 1 && size > 150 && size < 550) lod = lods.find(v => Number(v.level) === 1) || lod;
    return {
      id,
      entry,
      lod,
      priority: (id === this.view.focus ? 1e12 : selected ? 1e10 : 0) + size
    };
  }
  async schedule() {
    if (!this.manifest || !this.settings.enabled) return;
    const viewport = this.view.canvas.getBoundingClientRect();
    if (!viewport.width || !viewport.height) return;
    const epoch = this.epoch,
      revision = ++this.viewRevision,
      abortView = new AbortController();
    this.viewRequest?.abort();
    this.viewRequest = abortView;
    try {
      const bounds = this.queryBounds(),
        planes = this.queryPlanes();
      if (!bounds) return;
      const response = await fetch('/api/skeleton-cache/view', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Local-Token': localToken || overview?.token || ''
        },
        body: JSON.stringify({
          bounds,
          planes,
          limit: 512,
          cache_id: this.manifest.cache_id
        }),
        signal: abortView.signal
      });
      if (!response.ok) throw UI.apiError(await response.json());
      const page = await response.json();
      const ids = [...new Set([this.view.focus, ...this.view.selected].filter(Boolean))].slice(0, 64);
      const focused = ids.length ? await api('/api/skeleton-cache/locate', {
        body_ids: ids
      }) : {
        nodes: []
      };
      const buffer = await this.bytes('/api/skeleton-cache/background?' + new URLSearchParams({
        cache_id: this.manifest.cache_id,
        max_edges: this.settings.quality === 'high' ? 48000 : this.settings.quality === 'low' ? 16000 : 32000,
        bounds: JSON.stringify(bounds),
        planes: JSON.stringify(planes)
      }), abortView.signal);
      const background = await this.decode('background', buffer);
      if (epoch !== this.epoch || revision !== this.viewRevision || abortView.signal.aborted) return;
      this.catalog = new Map([...page.entries, ...focused.nodes].filter(e => e.status === 'available').map(e => [String(e.body_id), e]));
      this.view.geometryPositions = new Map([...this.catalog].map(([id, e]) => [id, e.bounds]));
      for (const id of this.catalog.keys()) spatialKnownIds.add(id);
      this.mergeBackground(background);
      this.showCoverage();
      this.viewMatchCount = page.matched_count;
    } catch (error) {
      if (error.name !== 'AbortError' && epoch === this.epoch) this.status(UI.errorText(error), true);
      return;
    }
    const items = [];
    for (const entry of this.catalog.values()) {
      const item = this.priority(entry);
      if (item) items.push(item);
    }
    items.sort((a, b) => b.priority - a.priority || a.id.localeCompare(b.id, undefined, {
      numeric: true
    }));
    const desired = new Map();
    let bytes = 0,
      edges = 0;
    for (const item of items) {
      const n = item.lod.reserve_edges ?? item.lod.edges ?? item.lod.edge_count ?? 0,
        b = item.lod.reserve_bytes ?? item.lod.bytes ?? 0;
      if (desired.size >= this.maxObjects || bytes + b > this.maxBytes || edges + n > this.maxEdges) continue;
      desired.set(item.id, item);
      bytes += b;
      edges += n;
    }
    this.currentDesired = desired;
    for (const [id, p] of this.pending) if (!desired.has(id)) {
      p.abort();
      this.pending.delete(id);
    }
    for (const id of this.loaded.keys()) if (!desired.has(id)) {
      this.layer.remove(id);
      this.loaded.delete(id);
    }
    // Only two outstanding geometry requests, never all selections at once.
    const work = [...desired.values()].filter(item => !this.pending.has(item.id) && this.loaded.get(item.id)?.level !== Number(item.lod.level));
    const worker = async () => {
      while (work.length && epoch === this.epoch && revision === this.viewRevision) {
        if (this.pending.size >= 2) return;
        const item = work.shift(),
          abort = new AbortController();
        this.pending.set(item.id, abort);
        try {
          const buffer = await this.bytes('/api/skeleton-cache/detail?' + new URLSearchParams({
            id: item.id,
            level: item.lod.level,
            cache_id: this.manifest.cache_id
          }), abort.signal);
          const data = await this.decode('detail', buffer);
          if (epoch !== this.epoch || abort.signal.aborted || this.pending.get(item.id) !== abort || this.currentDesired?.get(item.id)?.lod.level !== item.lod.level) continue;
          data.level = Number(item.lod.level);
          data.bounds = item.entry.bounds;
          if (this.layer.put(item.id, data)) this.loaded.set(item.id, {
            level: data.level,
            bytes: data.points.byteLength + data.radii.byteLength + data.edges.byteLength
          });
        } catch (error) {
          if (error.name !== 'AbortError' && epoch === this.epoch) this.status(UI.join([item.id, "：", UI.errorText(error)]), true);
        } finally {
          if (this.pending.get(item.id) === abort) this.pending.delete(item.id);
        }
      }
    };
    await Promise.all([worker(), worker()]);
    if (epoch === this.epoch) {
      const s = this.layer.stats();
      this.status(UI.msg("skeleton.controls.view_matches_directory_576_local_objects_segments_mib_fu_1b2629", {
        p0: this.viewMatchCount,
        p1: this.catalog.size,
        p2: this.loaded.size,
        p3: s.segments ?? s.detail_segments ?? '—',
        p4: UI.fixed(Number(s.bytes ?? 0) / 1024 ** 2, 1),
        p5: this.view.selected.size
      }));
      this.view.draw();
    }
  }
  setSettings(settings) {
    const previousQuality = this.settings.quality;
    const next = this.layer.setSettings({
      ...this.settings,
      ...settings
    });
    this.settings = {
      ...next
    };
    if (!this.settings.enabled) {
      this.viewRequest?.abort();
      for (const p of this.pending.values()) p.abort();
      this.pending.clear();
    } else if (previousQuality !== this.settings.quality && this.manifest) this.refreshBackground();else this.schedule();
    this.view.draw();
  }
  async refreshBackground() {
    const limit = this.settings.quality === 'high' ? 300000 : 64000;
    if (limit === this.backgroundLimit) {
      this.schedule();
      return;
    }
    this.backgroundRequest?.abort();
    const abort = new AbortController();
    this.backgroundRequest = abort;
    const epoch = this.epoch;
    this.status(UI.msg('space.loadingOverview', {
      segments: UI.numeric(limit)
    }));
    try {
      const bytes = await this.bytes('/api/skeleton-cache/background?' + new URLSearchParams({
        cache_id: this.manifest.cache_id,
        max_edges: limit
      }), abort.signal);
      const background = await this.decode('background', bytes);
      if (abort.signal.aborted || epoch !== this.epoch || this.backgroundRequest !== abort) return;
      this.baseBackground = background;
      this.backgroundLimit = limit;
      this.layer.setBackground(background);
      this.showCoverage();
      this.view.draw();
      this.schedule();
    } catch (e) {
      if (e.name !== 'AbortError') this.status(UI.errorText(e), true);
    }
  }
  snapshot() {
    return this.manifest?.cache_id ? {
      cache_id: this.manifest.cache_id,
      coordinate_space: 'male-cns-em',
      settings: {
        ...this.settings
      }
    } : null;
  }
  async restore(state) {
    try {
      await this.load();
    } catch (error) {
      this.status(UI.msg("skeleton.controls.keep_e356b3", {
        p0: UI.errorText(error)
      }), true);
      return;
    }
    if (state.coordinate_space !== 'male-cns-em' || state.cache_id !== this.manifest?.cache_id) {
      this.status(UI.msg("skeleton.controls.space_keep_select_fbb2c5", {}), true);
      return;
    }
    this.setSettings(state.settings);
    this.controls();
  }
  controls() {
    $('space_geom_enabled').checked = this.settings.enabled;
    for (const key of ['diameter', 'radius_scale', 'background', 'quality']) $('space_geom_' + key).value = this.settings[key];
  }
}
const skeletonStreaming = new SkeletonStreaming(globalSpace);
window.skeletonStreaming = skeletonStreaming;
async function skeletonLoad() {
  try {
    await spaceLoad();
    await skeletonStreaming.load();
    spaceSelectionDisplay();
  } catch (error) {
    skeletonStreaming.status(UI.errorText(error), true);
  }
}
let skeletonJob = null;
async function skeletonUpdate() {
  try {
    $('space_geom_update').disabled = true;
    const request = {
      max_input_mib: Number($('space_geom_input').value),
      max_cache_mib: Number($('space_geom_cache').value),
      max_files: null
    };
    const task = await api('/api/skeleton-cache/update', request);
    skeletonJob = task.job_id;
    $('space_geom_cancel').disabled = false;
    const poll = async () => {
      try {
        const status = await api('/api/skeleton-cache/job?' + new URLSearchParams({
          job_id: skeletonJob
        }));
        if (status.status === 'running') {
          const p = status.progress || {};
          skeletonStreaming.status(UI.msg("skeleton.poll.message_3099d5", {
            p0: p.completed ?? p.processed ?? 0,
            p1: p.total ?? p.snapshot_count ?? '—',
            p2: p.phase || UI.msg("skeleton.poll.message_ee8626", {})
          }));
          setTimeout(poll, 700);
          return;
        }
        $('space_geom_update').disabled = false;
        $('space_geom_cancel').disabled = true;
        if (status.error) throw UI.error('geometry.error.decode', {}, status.error);
        await skeletonLoad();
        skeletonStreaming.status(UI.msg("skeleton.poll.message_8fed5c", {
          p0: status.status
        }));
      } catch (error) {
        $('space_geom_update').disabled = false;
        $('space_geom_cancel').disabled = true;
        skeletonStreaming.status(UI.errorText(error), true);
      }
    };
    poll();
  } catch (error) {
    $('space_geom_update').disabled = false;
    skeletonStreaming.status(UI.errorText(error), true);
  }
}
$('space_geom_load').onclick = skeletonLoad;
$('space_geom_update').onclick = skeletonUpdate;
$('space_geom_cancel').onclick = async () => {
  try {
    await api('/api/skeleton-cache/cancel', {
      job_id: skeletonJob
    });
    skeletonStreaming.status(UI.msg("skeleton.controls.cancel_complete_keep_097285", {}));
  } catch (e) {
    skeletonStreaming.status(UI.errorText(e), true);
  }
};
for (const key of ['enabled', 'diameter', 'radius_scale', 'background', 'quality']) {
  $('space_geom_' + key).addEventListener('change', () => {
    const settings = {
      enabled: $('space_geom_enabled').checked,
      quality: $('space_geom_quality').value
    };
    for (const k of ['diameter', 'radius_scale', 'background']) settings[k] = Number($('space_geom_' + k).value);
    try {
      skeletonStreaming.setSettings(settings);
    } catch (error) {
      skeletonStreaming.controls();
      skeletonStreaming.status(UI.errorText(error), true);
    }
  });
}
document.addEventListener('lab-analysis-selection', () => skeletonStreaming.schedule());
document.addEventListener('lab-analysis-focus', () => skeletonStreaming.schedule());
