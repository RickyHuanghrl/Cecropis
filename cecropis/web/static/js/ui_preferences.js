"use strict";

/* Explicit typed display bindings. No text matching, body walker or DOM number parsing. */
(() => {
  'use strict';

  const languages = ['zh-CN', 'en', 'ja', 'fr', 'de', 'es'];
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem('display-preferences-v1') || '{}') || {};
  } catch {}
  const preferences = {
    version: 1,
    language: languages.includes(saved.language) ? saved.language : 'en',
    theme: ['light', 'dark', 'system'].includes(saved.theme) ? saved.theme : 'system'
  };
  const media = matchMedia('(prefers-color-scheme: dark)'),
    bindings = new Map(),
    attributes = new Map();
  const escape = v => String(v ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[c]);
  const number = (value, options = {}) => value == null || !Number.isFinite(Number(value)) ? '—' : new Intl.NumberFormat(preferences.language, options).format(value);
  class Message {
    constructor(key, params = {}, parts = null) {
      this.key = key;
      this.params = params;
      this.parts = parts;
      if (parts) this.technical = parts.map(part => part?.technical).filter(Boolean).join('\n');
    }
    toString() {
      return this.parts ? this.parts.map(format).join('') : t(this.key, this.params);
    }
    [Symbol.toPrimitive]() {
      return this.toString();
    }
    toJSON() {
      return this.toString();
    }
  }
  class Numeric {
    constructor(value, options = {}) {
      this.value = value;
      this.options = options;
    }
    toString() {
      return number(this.value, this.options);
    }
    [Symbol.toPrimitive]() {
      return this.toString();
    }
    toJSON() {
      return this.value;
    }
  }
  class Plural extends Message {
    constructor(key, count, params = {}) {
      super(key, params);
      this.count = count;
    }
    toString() {
      const category = new Intl.PluralRules(preferences.language).select(this.count);
      const key = window.UI_MESSAGES[this.key + '.' + category] ? this.key + '.' + category : this.key + '.other';
      return t(key, {
        ...this.params,
        count: new Numeric(this.count)
      });
    }
  }
  function format(value) {
    if (value instanceof Message || value instanceof Numeric) return value.toString();
    if (value?.$message) return t(value.$message, value.params);
    if (value?.$number) return number(value.value, value.options);
    return String(value ?? '—');
  }
  function t(key, params = {}) {
    const row = window.UI_MESSAGES[key];
    if (!row) {
      console.warn('Missing UI key:', key);
      return key;
    }
    return (row[preferences.language] ?? row.en).replace(/\{(\w+)\}/g, (_, name) => format(params[name]));
  }
  function serialize(value) {
    if (value instanceof Plural) return {
      $plural: value.key,
      count: value.count,
      params: serialize(value.params)
    };
    if (value instanceof Message) return value.parts ? {
      $parts: value.parts.map(serialize)
    } : {
      $message: value.key,
      params: serialize(value.params)
    };
    if (value instanceof Numeric) return {
      $number: true,
      value: value.value,
      options: value.options
    };
    if (Array.isArray(value)) return value.map(serialize);
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, serialize(v)]));
    return value;
  }
  function hydrate(value) {
    if (value?.$plural) return new Plural(value.$plural, value.count, Object.fromEntries(Object.entries(value.params || {}).map(([k, v]) => [k, hydrate(v)])));
    if (value?.$message) return new Message(value.$message, Object.fromEntries(Object.entries(value.params || {}).map(([k, v]) => [k, hydrate(v)])));
    if (value?.$number) return new Numeric(value.value, value.options);
    if (value?.$parts) return new Message(null, {}, value.$parts.map(hydrate));
    return value;
  }
  function msg(key, params = {}) {
    return new Message(key, params);
  }
  function list(values, separator = ' / ') {
    return new Message(null, {}, values.flatMap((value, i) => i ? [separator, value] : [value]));
  }
  const codeKeys = {
    running: 'local.tasks.labels.running_1f0eb9',
    pause_requested: 'local.tasks.labels.pause_requested_3e246f',
    paused: 'local.tasks.labels.paused_eb0c32',
    interrupted: 'local.tasks.labels.interrupted_88cf2d',
    failed: 'local.tasks.labels.failed_28384d',
    complete: 'local.tasks.labels.complete_c0b3fb',
    completed: 'local.tasks.labels.complete_c0b3fb',
    cancelled: 'local.tasks.labels.cancelled_a37778',
    canceled: 'local.tasks.labels.cancelled_a37778',
    budget_exhausted: 'local.tasks.labels.budget_exhausted_d9e9de',
    budget_exceeded: 'local.tasks.labels.budget_exhausted_d9e9de',
    evaluation_budget_reached: 'operation.search.operationState.combination_evaluation_budget_13e1d8',
    bounded_layers_completed: 'operation.search.operationState.complete_99eb38',
    no_intervention_needed: 'operation.search.operationState.no_intervention_satisfied_e3a627',
    no_effective_candidates: 'operation.search.operationState.message_c81472',
    execution_failed: 'operation.search.operationState.failed_934459',
    evaluated: 'operation.search.operationState.message_df49f2',
    retained_for_next_layer: 'operation.search.operationState.message_60f374',
    beam_width: 'operation.search.operationState.beam_width_683d20',
    incomplete: 'operation.search.operationState.complete_6707de',
    not_ranked: 'operation.search.operationState.sort_6407a6',
    empty_plan_satisfies_constraints: 'operation.search.operationState.satisfiedconstraints_326996',
    response_exploration: 'global.labels.input_response_exploration_3cb1e0',
    operation_search: 'global.labels.operation_search_469176',
    baselines: 'code.baseline',
    singles: 'code.screening',
    sets: 'code.evaluation',
    done: 'local.tasks.labels.complete_c0b3fb',
    local_irreducible: 'reduction.renderReduction.condition_remove_members_constraints_92bb3a',
    empty_set_reached: 'reduction.renderReduction.message_1ed77c',
    withdrawals_completed: 'reduction.renderReduction.plan_complete_aaba47',
    baseline_failed: 'reduction.renderReduction.baseline_failed_14773f',
    evaluation_failed: 'reduction.renderReduction.plan_failed_52f140',
    original_infeasible: 'reduction.renderReduction.plannot_satisfied_3ff535'
  };
  function code(value) {
    if (value == null || value === '') return '—';
    const [kind, ...tail] = String(value).split(':');
    const key = codeKeys[kind] || 'code.' + kind;
    const result = msg(window.UI_MESSAGES[key] ? key : 'code.unknown', {name: tail.join(':')});
    if (!window.UI_MESSAGES[key]) result.technical = String(value);
    return result;
  }
  function text(element, value) {
    if (!element) return;
    const localized = value instanceof Message || value instanceof Numeric;
    const rendered = format(value);
    if (localized) bindings.set(element, {
      value,
      rendered
    });else bindings.delete(element);
    element.textContent = rendered;
    if (element.nextElementSibling?.classList.contains('error-details')) element.nextElementSibling.remove();
    if (value?.technical) {
      const detail = document.createElement('details');
      detail.className = 'error-details';
      const summary = document.createElement('summary');
      summary.dataset.i18n = 'error.details';
      summary.textContent = t('error.details');
      const pre = document.createElement('pre');
      pre.textContent = value.technical;
      detail.append(summary, pre);
      element.after(detail);
    }
  }
  function attr(element, name, value) {
    if (value instanceof Message || value instanceof Numeric) {
      let fields = attributes.get(element);
      if (!fields) attributes.set(element, fields = new Map());
      fields.set(name, value);
    } else attributes.get(element)?.delete(name);
    element.setAttribute(name, format(value));
  }
  // Bind the authored value, never infer a translation from rendered text. User
  // strings remain strings; messages and numbers retain their original types.
  function html(value, svg = false) {
    if (!(value instanceof Message || value instanceof Numeric)) return escape(value);
    const tag = svg ? 'tspan' : 'span';
    const content = `<${tag} ${displayAttribute(value)}>${escape(format(value))}</${tag}>`;
    return !svg && value.technical ? content + `<details class="error-details"><summary>${htmlText('error.details')}</summary><pre>${escape(value.technical)}</pre></details>` : content;
  }
  function htmlList(values, separator = '<br>') {
    return values.map(value => html(value)).join(separator);
  }
  function displayAttribute(value) {
    return `data-ui-display="${escape(JSON.stringify(serialize(value)))}"`;
  }
  function htmlAttribute(name, key, params = {}) {
    const field = {'aria-label': 'label', title: 'title', placeholder: 'placeholder'}[name];
    if (!field) throw Error('Unsupported display attribute');
    return `${name}="${escape(t(key, params))}" data-i18n-${field}="${escape(key)}" data-i18n-${field}-params="${escape(JSON.stringify(serialize(params)))}"`;
  }
  function currentText(element) {
    const binding = bindings.get(element);
    return binding && element.textContent === binding.rendered ? binding.value : element.textContent;
  }
  function htmlText(key, params = {}, svg = false) {
    const encoded = escape(JSON.stringify(serialize(params)));
    return `<${svg ? 'tspan' : 'span'} data-i18n="${escape(key)}" data-i18n-params="${encoded}">${escape(t(key, params))}</${svg ? 'tspan' : 'span'}>`;
  }
  function htmlNumber(value, svg = false) {
    return `<${svg ? 'tspan' : 'span'} data-ui-number="${escape(JSON.stringify(serialize(value)))}">${escape(format(value))}</${svg ? 'tspan' : 'span'}>`;
  }
  function apply(root = document.body) {
    if (!root) return;
    const targets = [...(root.matches?.('[data-i18n]') ? [root] : []), ...root.querySelectorAll('[data-i18n]')];
    for (const e of targets) {
      let params = {};
      try {
        params = JSON.parse(e.dataset.i18nParams || '{}');
      } catch {}
      e.textContent = t(e.dataset.i18n, Object.fromEntries(Object.entries(params).map(([k, v]) => [k, hydrate(v)])));
    }
    for (const e of root.querySelectorAll('[data-i18n-title],[data-i18n-label],[data-i18n-placeholder]')) for (const [name, attribute] of [['title', 'title'], ['label', 'aria-label'], ['placeholder', 'placeholder']]) {
      const key = e.getAttribute('data-i18n-' + name);
      if (key) {
        let params = {};
        try { params = JSON.parse(e.getAttribute('data-i18n-' + name + '-params') || '{}'); } catch {}
        e.setAttribute(attribute, t(key, Object.fromEntries(Object.entries(params).map(([k, v]) => [k, hydrate(v)]))));
      }
    }
    for (const [e, binding] of bindings) {
      if (!e.isConnected || e.children?.length || e.textContent !== binding.rendered) {
        bindings.delete(e);
        continue;
      }
      e.textContent = format(binding.value);
      binding.rendered = e.textContent;
    }
    for (const [e, fields] of attributes) {
      if (!e.isConnected) {
        attributes.delete(e);
        continue;
      }
      for (const [name, value] of fields) e.setAttribute(name, format(value));
    }
    for (const e of root.querySelectorAll('[data-ui-number]')) {
      try {
        e.textContent = format(hydrate(JSON.parse(e.dataset.uiNumber)));
      } catch {}
    }
    for (const e of root.querySelectorAll('[data-ui-display]')) {
      try { e.textContent = format(hydrate(JSON.parse(e.dataset.uiDisplay))); } catch {}
    }
  }
  function error(key, params = {}, technical = '') {
    const e = new Error(t(key, params));
    e.uiKey = key;
    e.params = params;
    e.technical = technical;
    e.code = key;
    return e;
  }
  function errorValue(value) {
    const e = new Error(format(value));
    e.displayBinding = value;
    e.code = value.key || value.parts?.find(p => p?.key)?.key || 'request';
    return e;
  }
  function errorText(e) {
    if (e?.displayBinding) return e.displayBinding;
    if (e?.uiKey) {
      const value = msg(e.uiKey, e.params);
      value.technical = e.technical;
      return value;
    }
    const value = msg('error.request');
    value.technical = e?.message || String(e);
    return value;
  }
  function apiError(body) {
    const key = 'error.' + (body.error_code || 'request');
    return error(window.UI_MESSAGES[key] ? key : 'error.request', body.error_params || {}, body.error || body.error_code || '');
  }
  function store() {
    try {
      localStorage.setItem('display-preferences-v1', JSON.stringify(preferences));
    } catch {}
  }
  function theme() {
    document.documentElement.dataset.theme = preferences.theme === 'system' ? media.matches ? 'dark' : 'light' : preferences.theme;
    document.documentElement.dataset.themePreference = preferences.theme;
    document.dispatchEvent(new CustomEvent('ui-theme'));
  }
  function language(value) {
    if (!languages.includes(value)) throw Error('Unknown interface language');
    preferences.language = value;
    document.documentElement.lang = value;
    store();
    apply();
    document.dispatchEvent(new CustomEvent('ui-language'));
  }
  function setTheme(value) {
    if (!['light', 'dark', 'system'].includes(value)) throw Error('Unknown theme');
    preferences.theme = value;
    store();
    theme();
  }
  function option(value, code, defaultSelected, selected) {
    const e = new Option(format(value), code ?? format(value), defaultSelected, selected);
    text(e, value);
    return e;
  }
  const palettes = {
    light: ['#176c97', '#974b06', '#267247', '#784cb0', '#a53553', '#47720f', '#a2448b', '#2b6872', '#69523e', '#3658a7'],
    dark: ['#65c3ee', '#f3b565', '#8bd0a4', '#bd9aec', '#ef95ac', '#c1cf7e', '#e394ce', '#8cd0da', '#d7b69b', '#91acef']
  };
  function observationColor(label) {
    let hash = 0;
    for (const c of String(label)) hash = hash * 31 + c.charCodeAt(0) >>> 0;
    return palettes[document.documentElement.dataset.theme || 'light'][hash % 10];
  }
  function heatColor(value, maximum, mode = 'response') {
    if (value == null) return UI.color('line');
    if (value === 0) return UI.color('raised');
    const base = UI.rgb('panel');
    const target = UI.rgb(mode === 'delta' ? value < 0 ? 'negative' : 'positive' : 'teal');
    const strength = .15 + .75 * Math.sqrt(Math.min(1, Math.abs(value) / Math.max(maximum, 1e-30)));
    return '#' + base.map((v,k) => Math.round(255*(v*(1-strength)+target[k]*strength)).toString(16).padStart(2,'0')).join('');
  }
  function contrastText(color) {
    const rgb=[1,3,5].map(k=>parseInt(color.slice(k,k+2),16));
    return .299*rgb[0]+.587*rgb[1]+.114*rgb[2]>145 ? '#172b40' : '#f4f7fb';
  }
  window.UI = {
    t,
    msg,
    list,
    code,
    field: field => window.UI_MESSAGES['field.' + field] ? msg('field.' + field) : field,
    name: item => item?.name_display ? msg(item.name_display.key, item.name_display.params) : item?.name,
    format,
    text,
    attr,
    html,
    htmlList,
    htmlAttribute,
    displayAttribute,
    currentText,
    htmlText,
    htmlNumber,
    svgText: (k, p) => htmlText(k, p, true),
    numeric: (v, o) => new Numeric(v, o),
    join: p => new Message(null, {}, p),
    option,
    error,
    errorValue,
    errorText,
    apiError,
    apiErrorText: body => errorText(apiError(body)),
    jobText: (snapshot,fallback) => {
      if (snapshot.error_code) return errorText(apiError(snapshot));
      const message=fallback || (snapshot.status ? code(snapshot.status) : msg('error.request'));
      if (snapshot.error) message.technical=String(snapshot.error);
      return message;
    },
    apply,
    schedule: apply,
    preferences,
    languages,
    language,
    setTheme,
    escape,
    number,
    observationColor,
    heatColor,
    contrastText,
    fixed: (v, d) => new Numeric(v, {
      minimumFractionDigits: d,
      maximumFractionDigits: d
    }),
    percent: (v, d = 3) => new Numeric(v, {
      style: 'percent',
      minimumFractionDigits: d,
      maximumFractionDigits: d
    }),
    value: v => new Numeric(v, {
      maximumSignificantDigits: 4,
      notation: Math.abs(v) > 0 && Math.abs(v) < .001 ? 'scientific' : 'standard'
    }),
    date: (v, o = {}) => new Intl.DateTimeFormat(preferences.language, {
      dateStyle: 'medium',
      timeStyle: 'short',
      ...o
    }).format(new Date(v)),
    plural: (k, n, p = {}) => new Plural(k, n, p),
    message: (code, p = {}, technical = '') => error('error.' + code, p, technical),
    color: key => getComputedStyle(document.documentElement).getPropertyValue('--' + key).trim(),
    rgb: key => {
      const h = UI.color(key);
      return [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255);
    },
    canvasFont: (size = 14) => `${size}px ${getComputedStyle(document.documentElement).getPropertyValue('--font-ui').trim()}`
  };
  document.documentElement.lang = preferences.language;
  theme();
  media.addEventListener('change', () => {
    if (preferences.theme === 'system') theme();
  });
  document.addEventListener('DOMContentLoaded', () => apply());
  document.fonts?.ready.then(() => document.dispatchEvent(new CustomEvent('ui-fonts')));
  document.fonts?.addEventListener('loadingdone', () => document.dispatchEvent(new CustomEvent('ui-fonts')));
})();
