extension NativeRuntime {
    /// JavaScript loaded before app/main.js: console, timers, fetch, storage,
    /// fs, require, the `tux` sensor API and the `UI` view builder.
    static let prelude = #"""
    (function () {
    'use strict';
    const g = globalThis;

    // ---- console -------------------------------------------------------
    const fmt = (a) => a.map((x) => {
      if (typeof x === 'string') return x;
      if (x instanceof Error) return x.message + '\n' + (x.stack || '');
      try { return JSON.stringify(x); } catch (e) { return String(x); }
    }).join(' ');
    g.console = {
      log: (...a) => __log(fmt(a)), info: (...a) => __log(fmt(a)), debug: (...a) => __log(fmt(a)),
      warn: (...a) => __log('WARN ' + fmt(a)), error: (...a) => __log('ERROR ' + fmt(a)),
    };

    // ---- timers --------------------------------------------------------
    const timers = new Map();
    let nextTimer = 1;
    const addTimer = (repeat) => (fn, ms, ...args) => {
      const id = nextTimer++;
      timers.set(id, { fn, args, repeat });
      __setTimer(id, Number(ms) || 0, repeat);
      return id;
    };
    g.setTimeout = addTimer(false);
    g.setInterval = addTimer(true);
    g.clearTimeout = g.clearInterval = (id) => { timers.delete(id); __clearTimer(id); };
    g.__timer = (id) => {
      const t = timers.get(id);
      if (!t) return;
      if (!t.repeat) timers.delete(id);
      t.fn(...t.args);
    };
    if (!g.queueMicrotask) g.queueMicrotask = (fn) => Promise.resolve().then(fn);

    // ---- network / storage / files --------------------------------------
    g.fetch = (url, opts = {}) => new Promise((resolve, reject) => {
      const body = opts.body == null ? undefined : typeof opts.body === 'string' ? opts.body : JSON.stringify(opts.body);
      __fetch(String(url), { method: opts.method, headers: opts.headers, body }, (r) => resolve({
        ok: r.status >= 200 && r.status < 300, status: r.status, url: r.url,
        headers: { get: (k) => r.headers[String(k).toLowerCase()] ?? null, all: r.headers },
        text: async () => r.body, json: async () => JSON.parse(r.body), base64: async () => r.base64,
      }), (e) => reject(new Error(e)));
    });
    g.storage = {
      get: (k) => { const v = __storageGet(String(k)); return v == null ? null : JSON.parse(v); },
      set: (k, v) => __storageSet(String(k), JSON.stringify(v)),
      remove: (k) => __storageSet(String(k), null),
    };
    g.fs = {
      read: (p) => __fsRead(String(p)),
      write: (p, text) => __fsWrite(String(p), String(text)),
      list: (p = '') => __fsList(String(p)),
      remove: (p) => __fsRemove(String(p)),
      exists: (p) => __fsRead(String(p)) != null,
    };

    // ---- modules (files inside app/) -------------------------------------
    const modules = {};
    g.require = (name) => {
      let path = String(name).replace(/^\.\//, '');
      if (!/\.(js|json)$/.test(path)) path += '.js';
      if (modules[path]) return modules[path].exports;
      const src = __readApp(path);
      if (src == null) throw new Error('module not found: ' + name);
      const module = { exports: {} };
      modules[path] = module;
      if (path.endsWith('.json')) module.exports = JSON.parse(src);
      else new Function('module', 'exports', 'require', src + '\n//# sourceURL=' + path)(module, module.exports, g.require);
      return module.exports;
    };

    // ---- tux: sensors & device --------------------------------------------
    const listeners = new Map();
    g.__emit = (name, detail) => (listeners.get(name) || []).slice().forEach((fn) => fn(detail));
    const on = (name, fn) => {
      if (!listeners.has(name)) listeners.set(name, []);
      listeners.get(name).push(fn);
      return () => listeners.set(name, listeners.get(name).filter((f) => f !== fn));
    };
    const post = (method, args) => new Promise((resolve, reject) =>
      __tuxCall(method, args || {}, resolve, (e) => reject(new Error(e))));
    g.tux = __tuxAPI(post, on);

    // ---- UI ---------------------------------------------------------------
    const fns = new Map();
    let nextFn = 1;
    const ser = (v) => {
      if (typeof v === 'function') { const id = nextFn++; fns.set(id, v); return { $fn: id }; }
      if (Array.isArray(v)) return v.map(ser);
      if (v instanceof Date) return v.getTime();
      if (v && typeof v === 'object') {
        const out = {};
        for (const k of Object.keys(v)) if (v[k] !== undefined) out[k] = ser(v[k]);
        return out;
      }
      return v;
    };
    const isProps = (x) => x && typeof x === 'object' && !Array.isArray(x) && !x.__node;
    const h = (type, ...a) => {
      let text;
      if (typeof a[0] === 'string' || typeof a[0] === 'number') text = String(a.shift());
      let props = isProps(a[0]) ? { ...a.shift() } : {};
      if (text !== undefined) props.text = text;
      if (typeof a[0] === 'function') props.action = a.shift();   // Button('Go', () => ...)
      const children = a.flat(Infinity)
        .filter((c) => c != null && c !== false && c !== true)
        .map((c) => (typeof c === 'string' || typeof c === 'number') ? h('Text', String(c)) : c);
      return { __node: true, type, props, children };
    };

    const TYPES = ['VStack', 'HStack', 'ZStack', 'Spacer', 'Divider', 'ScrollView', 'List', 'Section', 'Form',
      'Group', 'Grid', 'NavigationStack', 'NavigationLink', 'TabView', 'Tab', 'Text', 'Label', 'Image', 'Button',
      'Menu', 'Toggle', 'Slider', 'Stepper', 'TextField', 'SecureField', 'TextEditor', 'Picker', 'DatePicker',
      'ColorPicker', 'ProgressView', 'Gauge', 'Link', 'ShareLink', 'DisclosureGroup', 'MapView', 'Chart', 'WebView',
      'Camera', 'Rectangle', 'RoundedRectangle', 'Circle', 'Capsule', 'Ellipse', 'Color', 'GlassContainer',
      'ContentUnavailable'];
    const UI = { h };
    for (const t of TYPES) { UI[t] = (...a) => h(t, ...a); if (!(t in g)) g[t] = UI[t]; }

    let viewFn = null, sheetFn = null, alertSpec = null, dirty = false, animation = null;
    const proxies = new WeakMap();
    const reactive = (obj) => {
      if (obj === null || typeof obj !== 'object' || obj.__node) return obj;
      const proto = Object.getPrototypeOf(obj);
      if (proto !== Object.prototype && proto !== Array.prototype && proto !== null) return obj;
      if (proxies.has(obj)) return proxies.get(obj);
      const p = new Proxy(obj, {
        get: (t, k, r) => reactive(Reflect.get(t, k, r)),
        set: (t, k, v) => { t[k] = v; dirty = true; return true; },
        deleteProperty: (t, k) => { delete t[k]; dirty = true; return true; },
      });
      proxies.set(obj, p);
      return p;
    };

    UI.state = (initial) => reactive(initial);
    UI.mount = (fn) => { viewFn = fn; dirty = true; };
    UI.update = () => { dirty = true; };
    UI.animate = (fn, style = 'default') => { animation = style; fn(); dirty = true; };
    UI.sheet = (content) => { sheetFn = content; dirty = true; };
    UI.alert = (title, message, buttons) => {
      alertSpec = { title, message, buttons: buttons || [{ text: 'OK' }] };
      dirty = true;
    };
    g.UI = UI;

    g.__dismissSheet = () => { sheetFn = null; dirty = true; };
    g.__dismissAlert = () => { alertSpec = null; dirty = true; };
    g.__invoke = (id, ...args) => { const fn = fns.get(id); if (fn) fn(...args); };
    g.__flush = () => {
      if (!dirty || !viewFn) return;
      dirty = false;
      fns.clear();
      const sheet = typeof sheetFn === 'function' ? sheetFn() : sheetFn;
      const payload = {
        root: ser(viewFn()), sheet: sheet ? ser(sheet) : null,
        alert: alertSpec ? ser(alertSpec) : null, animation,
      };
      animation = null;
      __render(payload);
    };
    g.__boot = () => { g.require('main.js'); };
    })();
    """#
}
