// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 The Shoji Authors
//
// Shoji's scriptlet library: small functions that run inside web pages before the page's own scripts,
// for filter rules written as  example.com##+js(name, arg1, arg2, ...)  (uBlock Origin syntax).
//
// Written independently for Shoji from the documented behaviour of each rule; it contains no code from
// uBlock Origin or AdGuard (both GPL-licensed). Only the most used rules are implemented.
//
// File format (read by shoji/scriptlets.py):
//   "//@ name alias alias…" starts a section; the section body is one function expression.
//   The "_helpers" section is shared and always included when a page uses any scriptlet.

//@ _helpers
{
  fnToString: Function.prototype.toString,
  reEsc(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  },
  // 文字列か /正規表現/ を RegExp に。空なら何にでも一致
  rx(p) {
    p = p === undefined || p === null ? '' : String(p);
    if (p === '' || p === '*') return /^/;
    const m = /^\/(.+)\/([dimsuy]*)$/.exec(p);
    if (m) {
      try { return new RegExp(m[1], m[2]); } catch (e) { return /(?!)/; }
    }
    return new RegExp(this.reEsc(p));
  },
  // 先頭の "!" で否定できる一致判定関数
  pat(p) {
    p = p === undefined || p === null ? '' : String(p);
    let not = false;
    if (p.startsWith('!')) { not = true; p = p.slice(1); }
    const re = this.rx(p);
    return s => re.test(String(s)) !== not;
  },
  // 遅延時間の判定: '' は何でも、'1000' は一致、'!1000' は不一致
  delay(p) {
    p = p === undefined || p === null ? '' : String(p).trim();
    if (p === '' || p === '*') return () => true;
    let not = false;
    if (p.startsWith('!')) { not = true; p = p.slice(1); }
    const n = parseInt(p, 10);
    if (isNaN(n)) return () => false;
    return d => ((parseInt(d, 10) || 0) === n) !== not;
  },
  text(f) {
    try { return typeof f === 'function' ? this.fnToString.call(f) : String(f); } catch (e) { return ''; }
  },
  // set-constant などで使える値
  value(raw) {
    raw = raw === undefined ? '' : String(raw);
    const noop = function () {};
    const table = {
      'undefined': undefined, 'false': false, 'true': true, 'null': null, '': '', 'emptyStr': '',
      'noopFunc': noop, 'trueFunc': function () { return true; }, 'falseFunc': function () { return false; },
      'throwFunc': function () { throw new Error(); }, 'noopCallbackFunc': function () { return noop; },
      'noopPromiseResolve': function () { return Promise.resolve(); },
      'noopPromiseReject': function () { return Promise.reject(); },
      'emptyArr': [], 'emptyObj': {}, 'yes': 'yes', 'no': 'no', 'on': 'on', 'off': 'off',
      'NaN': NaN, 'Infinity': Infinity, '-Infinity': -Infinity,
    };
    if (Object.prototype.hasOwnProperty.call(table, raw)) return { ok: true, v: table[raw] };
    if (/^-?\d{1,5}$/.test(raw) && Math.abs(parseInt(raw, 10)) <= 32767) return { ok: true, v: parseInt(raw, 10) };
    return { ok: false };
  },
  // "a.b.c" の最後のプロパティに leaf(owner, prop) を仕掛ける。途中のオブジェクトが後から作られても追従する
  trap(chain, leaf) {
    chain = String(chain || '').replace(/^window\./, '');
    if (!chain) return;
    const go = (owner, path) => {
      const dot = path.indexOf('.');
      if (dot < 0) { leaf(owner, path); return; }
      const prop = path.slice(0, dot), rest = path.slice(dot + 1);
      let cur;
      try { cur = owner[prop]; } catch (e) { return; }
      if (cur !== null && (typeof cur === 'object' || typeof cur === 'function')) go(cur, rest);
      const d = Object.getOwnPropertyDescriptor(owner, prop);
      if (d && (!d.configurable || d.get || d.set)) return;
      try {
        Object.defineProperty(owner, prop, {
          configurable: true, enumerable: d ? d.enumerable : true,
          get() { return cur; },
          set(v) {
            cur = v;
            if (v !== null && (typeof v === 'object' || typeof v === 'function')) go(v, rest);
          },
        });
      } catch (e) { /* 定義できないプロパティは諦める */ }
    };
    go(window, chain);
  },
  define(owner, prop, desc) {
    const d = Object.getOwnPropertyDescriptor(owner, prop);
    if (d && !d.configurable) return false;
    try {
      Object.defineProperty(owner, prop, Object.assign({ configurable: true, enumerable: true }, desc));
      return true;
    } catch (e) { return false; }
  },
  error() {
    return new ReferenceError('Shoji: blocked');
  },
  wrap(owner, name, handler) {
    const orig = owner[name];
    if (typeof orig !== 'function') return;
    try { owner[name] = new Proxy(orig, { apply: handler }); } catch (e) { /* 読み取り専用 */ }
  },
  ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn, { once: true });
    else fn();
  },
  // ページの変化に合わせて繰り返し実行する（負荷を抑えるためまとめて実行）
  watch(fn) {
    let queued = false;
    const run = () => { queued = false; try { fn(); } catch (e) { /* 無視 */ } };
    const kick = () => { if (!queued) { queued = true; setTimeout(run, 30); } };
    this.ready(() => {
      run();
      try { new MutationObserver(kick).observe(document.documentElement, { childList: true, subtree: true, attributes: true }); } catch (e) { /* 無視 */ }
    });
  },
  // "url:/ads/ method:POST" や "googlesyndication" のような条件を解釈する
  props(spec) {
    const out = [];
    for (const tok of String(spec || '').trim().split(/\s+/)) {
      if (!tok) continue;
      const m = /^(\w+):(.*)$/.exec(tok);
      if (m && m[1] !== 'http' && m[1] !== 'https') out.push([m[1], this.pat(m[2])]);
      else out.push(['url', this.pat(tok)]);
    }
    return out;
  },
  propsMatch(conds, details) {
    if (!conds.length) return false;
    return conds.every(([k, test]) => test(details[k] === undefined ? '' : details[k]));
  },
  storage(getStore, key, value) {
    let store;
    try { store = getStore(); } catch (e) { return; }
    if (!store || !key) return;
    value = value === undefined ? '' : String(value);
    if (value === '$remove$' || value === 'undefined') {
      const re = /^\/.+\/[a-z]*$/.test(key) ? this.rx(key) : null;
      try {
        if (!re) { store.removeItem(key); return; }
        for (const k of Object.keys(store)) if (re.test(k)) store.removeItem(k);
      } catch (e) { /* 無視 */ }
      return;
    }
    const table = { 'false': 'false', 'true': 'true', 'null': 'null', '': '', 'emptyStr': '', 'emptyArr': '[]', 'emptyObj': '{}' };
    let v;
    if (Object.prototype.hasOwnProperty.call(table, value)) v = table[value];
    else if (/^(?:yes|no|on|off|ok|accept|accepted|reject|rejected|allow|allowed|deny|denied|necessary|required|\d{1,9})$/i.test(value)) v = value;
    else return;
    try { store.setItem(key, v); } catch (e) { /* 無視 */ }
  },
  decoyWindow() {
    const noop = function () {};
    let p;
    p = new Proxy(noop, {
      get(t, k) {
        if (k === 'closed') return false;
        if (k === Symbol.toPrimitive) return () => '';
        if (k === 'toString') return () => '[object Window]';
        return p;
      },
      set() { return true; },
      apply() { return p; },
    });
    return p;
  },
}

//@ set-constant set
function (chain, raw) {
  const val = S.value(raw);
  if (!val.ok) return;
  S.trap(chain, (owner, prop) => {
    S.define(owner, prop, { get() { return val.v; }, set() {} });
  });
}

//@ abort-on-property-read aopr
function (chain) {
  S.trap(chain, (owner, prop) => {
    S.define(owner, prop, { get() { throw S.error(); }, set() {} });
  });
}

//@ abort-on-property-write aopw
function (chain) {
  S.trap(chain, (owner, prop) => {
    let v;
    try { v = owner[prop]; } catch (e) { /* 無視 */ }
    S.define(owner, prop, { get() { return v; }, set() { throw S.error(); } });
  });
}

//@ abort-current-script acs abort-current-inline-script acis
function (chain, needle) {
  const test = S.pat(needle);
  const check = () => {
    const s = document.currentScript;
    if (!(s instanceof HTMLScriptElement)) return;
    const text = s.src ? s.src : s.textContent;
    if (test(text)) throw S.error();
  };
  S.trap(chain, (owner, prop) => {
    let v;
    try { v = owner[prop]; } catch (e) { /* 無視 */ }
    S.define(owner, prop, {
      get() { check(); return v; },
      set(x) { check(); v = x; },
    });
  });
}

//@ abort-on-stack-trace aost
function (chain, needle) {
  if (!needle) return;
  const test = S.pat(needle);
  const check = () => {
    let stack = '';
    try { stack = new Error().stack || ''; } catch (e) { /* 無視 */ }
    if (test(stack)) throw S.error();
  };
  S.trap(chain, (owner, prop) => {
    let v;
    try { v = owner[prop]; } catch (e) { /* 無視 */ }
    S.define(owner, prop, { get() { check(); return v; }, set(x) { check(); v = x; } });
  });
}

//@ addEventListener-defuser aeld prevent-addEventListener
function (type, needle, opt, sel) {
  if (!type && !needle) return;
  const tt = S.pat(type), tn = S.pat(needle);
  // 第 3・4 引数 "elements", "<セレクタ>" で対象の要素を絞れる（window / document も指定可）
  const only = opt === 'elements' && sel ? String(sel) : '';
  const isTarget = self => {
    if (!only) return true;
    try {
      if (self === window) return /(^|,)\s*window\s*(,|$)/.test(only);
      if (self === document) return /(^|,)\s*document\s*(,|$)/.test(only);
      return self instanceof Element && self.matches(only);
    } catch (e) { return false; }
  };
  S.wrap(EventTarget.prototype, 'addEventListener', (target, self, args) => {
    const h = args[1];
    let text = '';
    if (typeof h === 'function') text = S.text(h);
    else if (h && typeof h.handleEvent === 'function') text = S.text(h.handleEvent);
    if (tt(args[0]) && tn(text) && isTarget(self)) return undefined;
    return Reflect.apply(target, self, args);
  });
}

//@ no-setTimeout-if nostif setTimeout-defuser
function (needle, delay) {
  if (!needle && !delay) return;
  const tn = S.pat(needle), td = S.delay(delay);
  S.wrap(window, 'setTimeout', (target, self, args) => {
    if (tn(S.text(args[0])) && td(args[1])) return Reflect.apply(target, self, [function () {}, args[1]]);
    return Reflect.apply(target, self, args);
  });
}

//@ no-setInterval-if nosiif setInterval-defuser
function (needle, delay) {
  if (!needle && !delay) return;
  const tn = S.pat(needle), td = S.delay(delay);
  S.wrap(window, 'setInterval', (target, self, args) => {
    if (tn(S.text(args[0])) && td(args[1])) return Reflect.apply(target, self, [function () {}, args[1]]);
    return Reflect.apply(target, self, args);
  });
}

//@ no-requestAnimationFrame-if norafif
function (needle) {
  if (!needle) return;
  const tn = S.pat(needle);
  S.wrap(window, 'requestAnimationFrame', (target, self, args) => {
    if (tn(S.text(args[0]))) return Reflect.apply(target, self, [function () {}]);
    return Reflect.apply(target, self, args);
  });
}

//@ nano-setInterval-booster nano-sib adjust-setInterval
function (needle, delay, boost) {
  const tn = S.pat(needle);
  const d = delay === undefined || delay === '' ? 1000 : (delay === '*' ? -1 : parseInt(delay, 10));
  let b = parseFloat(boost);
  if (isNaN(b)) b = 0.05;
  b = Math.min(50, Math.max(0.001, b));
  S.wrap(window, 'setInterval', (target, self, args) => {
    if (tn(S.text(args[0])) && (d < 0 || (parseInt(args[1], 10) || 0) === d)) {
      args = Array.from(args);
      args[1] = (parseInt(args[1], 10) || 0) * b;
    }
    return Reflect.apply(target, self, args);
  });
}

//@ nano-setTimeout-booster nano-stb adjust-setTimeout
function (needle, delay, boost) {
  const tn = S.pat(needle);
  const d = delay === undefined || delay === '' ? 1000 : (delay === '*' ? -1 : parseInt(delay, 10));
  let b = parseFloat(boost);
  if (isNaN(b)) b = 0.05;
  b = Math.min(50, Math.max(0.001, b));
  S.wrap(window, 'setTimeout', (target, self, args) => {
    if (tn(S.text(args[0])) && (d < 0 || (parseInt(args[1], 10) || 0) === d)) {
      args = Array.from(args);
      args[1] = (parseInt(args[1], 10) || 0) * b;
    }
    return Reflect.apply(target, self, args);
  });
}

//@ no-window-open-if nowoif window.open-defuser
function (needle) {
  const tn = S.pat(needle);
  S.wrap(window, 'open', (target, self, args) => {
    if (tn(args[0] === undefined ? '' : args[0])) return S.decoyWindow();
    return Reflect.apply(target, self, args);
  });
}

//@ noeval
function () {
  S.wrap(window, 'eval', () => undefined);
}

//@ noeval-if
function (needle) {
  const tn = S.pat(needle);
  S.wrap(window, 'eval', (target, self, args) => {
    if (tn(args[0])) return undefined;
    return Reflect.apply(target, self, args);
  });
}

//@ nowebrtc
function () {
  const Dummy = function () {};
  const resolved = function () { return Promise.resolve(); };
  Dummy.prototype = {
    close() {}, createDataChannel() { return { close() {}, send() {} }; },
    createOffer: resolved, createAnswer: resolved, setLocalDescription: resolved,
    setRemoteDescription: resolved, addIceCandidate: resolved,
    addEventListener() {}, removeEventListener() {}, getStats: resolved,
  };
  for (const name of ['RTCPeerConnection', 'webkitRTCPeerConnection', 'mozRTCPeerConnection']) {
    if (name in window) S.define(window, name, { value: Dummy, writable: true });
  }
}

//@ json-prune
function (prunePaths, needlePaths) {
  if (!prunePaths) return;
  const prune = String(prunePaths).trim().split(/\s+/);
  const needles = needlePaths ? String(needlePaths).trim().split(/\s+/) : [];
  const walk = (o, parts, i, del) => {
    if (o === null || typeof o !== 'object') return false;
    const k = parts[i];
    const last = i === parts.length - 1;
    if (k === '[-]') {
      // 配列の要素のうち、続きのパスを持つものを要素ごと取り除く
      if (!Array.isArray(o)) return false;
      let found = false;
      for (let j = o.length - 1; j >= 0; j--) {
        if (last || walk(o[j], parts, i + 1, false)) {
          found = true;
          if (del) o.splice(j, 1);
        }
      }
      return found;
    }
    if (k === '[]' || k === '*') {
      let found = false;
      for (const key of Object.keys(o)) {
        if (last) { found = true; if (del) delete o[key]; }
        else if (walk(o[key], parts, i + 1, del)) found = true;
      }
      return found;
    }
    if (!Object.prototype.hasOwnProperty.call(o, k)) return false;
    if (last) { if (del) delete o[k]; return true; }
    return walk(o[k], parts, i + 1, del);
  };
  const apply = obj => {
    try {
      if (obj === null || typeof obj !== 'object') return obj;
      if (needles.length && !needles.every(n => walk(obj, n.split('.'), 0, false))) return obj;
      for (const p of prune) walk(obj, p.split('.'), 0, true);
    } catch (e) { /* 無視 */ }
    return obj;
  };
  S.wrap(JSON, 'parse', (target, self, args) => apply(Reflect.apply(target, self, args)));
  if (window.Response) {
    S.wrap(Response.prototype, 'json', (target, self, args) => Reflect.apply(target, self, args).then(apply));
  }
}

//@ no-fetch-if prevent-fetch
function (spec, body) {
  const conds = S.props(spec);
  if (!conds.length || typeof window.fetch !== 'function') return;
  const bodies = { '': '', 'emptyStr': '', 'emptyObj': '{}', 'emptyArr': '[]', 'true': 'true', 'false': 'false' };
  const text = Object.prototype.hasOwnProperty.call(bodies, body || '') ? bodies[body || ''] : '';
  S.wrap(window, 'fetch', (target, self, args) => {
    let details = { url: '', method: 'GET' };
    try {
      const input = args[0], init = args[1] || {};
      if (input instanceof Request) details = { url: input.url, method: input.method, mode: input.mode, credentials: input.credentials };
      else details.url = String(input);
      for (const k of ['method', 'mode', 'credentials', 'body', 'cache', 'redirect', 'referrer']) {
        if (init[k] !== undefined) details[k] = String(init[k]);
      }
    } catch (e) { /* 無視 */ }
    if (S.propsMatch(conds, details)) {
      const r = new Response(text, { status: 200, statusText: 'OK', headers: { 'Content-Type': 'text/plain' } });
      try { Object.defineProperty(r, 'url', { value: details.url }); } catch (e) { /* 無視 */ }
      return Promise.resolve(r);
    }
    return Reflect.apply(target, self, args);
  });
}

//@ no-xhr-if prevent-xhr
function (spec) {
  const conds = S.props(spec);
  if (!conds.length || !window.XMLHttpRequest) return;
  const info = new WeakMap();
  const P = XMLHttpRequest.prototype;
  S.wrap(P, 'open', (target, self, args) => {
    info.set(self, { method: String(args[0] || 'GET'), url: String(args[1] || '') });
    return Reflect.apply(target, self, args);
  });
  S.wrap(P, 'send', (target, self, args) => {
    const d = info.get(self);
    if (!d || !S.propsMatch(conds, d)) return Reflect.apply(target, self, args);
    const set = (k, v) => { try { Object.defineProperty(self, k, { value: v, configurable: true }); } catch (e) { /* 無視 */ } };
    setTimeout(() => {
      const rt = self.responseType;
      set('readyState', 4);
      set('status', 200);
      set('statusText', 'OK');
      set('responseURL', d.url);
      set('responseText', '');
      set('response', rt === 'json' ? null : (rt === 'arraybuffer' ? new ArrayBuffer(0) : (rt === 'blob' ? new Blob([]) : '')));
      for (const t of ['readystatechange', 'load', 'loadend']) {
        try { self.dispatchEvent(new Event(t)); } catch (e) { /* 無視 */ }
      }
    }, 1);
    return undefined;
  });
}

//@ remove-node-text rmnt
function (nodeName, needle) {
  if (!nodeName || !needle) return;
  const tn = S.pat(needle);
  const nameRe = S.rx(String(nodeName).startsWith('/') ? nodeName : '/^' + S.reEsc(String(nodeName)) + '$/i');
  const check = node => {
    if (!nameRe.test(node.nodeName.toLowerCase()) && !nameRe.test(node.nodeName)) return;
    const t = node.textContent;
    if (t && tn(t)) node.textContent = '';
  };
  const scan = root => {
    if (root.nodeType === 1 || root.nodeType === 3) check(root);
    if (root.nodeType !== 1) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) check(walker.currentNode);
  };
  try {
    new MutationObserver(records => {
      for (const r of records) for (const n of r.addedNodes) scan(n);
    }).observe(document, { childList: true, subtree: true });
  } catch (e) { /* 無視 */ }
  if (document.documentElement) scan(document.documentElement);
}

//@ remove-attr ra
function (attrs, selector) {
  const names = String(attrs || '').split('|').map(s => s.trim()).filter(Boolean);
  if (!names.length) return;
  const sel = selector || names.map(n => '[' + n + ']').join(',');
  S.watch(() => {
    for (const el of document.querySelectorAll(sel)) {
      for (const n of names) if (el.hasAttribute(n)) el.removeAttribute(n);
    }
  });
}

//@ remove-class rc
function (classes, selector) {
  const names = String(classes || '').split('|').map(s => s.trim()).filter(Boolean);
  if (!names.length) return;
  const sel = selector || names.map(n => '.' + CSS.escape(n)).join(',');
  S.watch(() => {
    for (const el of document.querySelectorAll(sel)) el.classList.remove(...names);
  });
}

//@ href-sanitizer
function (selector, source) {
  if (!selector) return;
  source = source || 'text';
  const pick = el => {
    if (source === 'text') return (el.textContent || '').trim();
    let m = /^\[(.+)\]$/.exec(source);
    if (m) return el.getAttribute(m[1]) || '';
    m = /^\?(.+)$/.exec(source);
    if (m) { try { return new URL(el.href).searchParams.get(m[1]) || ''; } catch (e) { return ''; } }
    return '';
  };
  S.watch(() => {
    for (const el of document.querySelectorAll(selector)) {
      if (el.dataset && el.dataset.shojiHref) continue;
      const cand = pick(el);
      try {
        const u = new URL(cand, location.href);
        if (u.protocol === 'http:' || u.protocol === 'https:') {
          el.setAttribute('href', u.href);
          if (el.dataset) el.dataset.shojiHref = '1';
        }
      } catch (e) { /* 無視 */ }
    }
  });
}

//@ remove-cookie cookie-remover
function (needle) {
  const tn = S.pat(needle);
  const remove = () => {
    const host = location.hostname;
    const parts = host.split('.');
    const domains = [''];
    for (let i = 0; i < parts.length - 1; i++) {
      const d = parts.slice(i).join('.');
      domains.push('; domain=' + d, '; domain=.' + d);
    }
    for (const c of document.cookie.split(';')) {
      const name = c.split('=')[0].trim();
      if (!name || !tn(name)) continue;
      for (const d of domains) {
        document.cookie = name + '=; max-age=0; path=/' + d;
        document.cookie = name + '=; max-age=0' + d;
      }
    }
  };
  remove();
  S.ready(remove);
  window.addEventListener('beforeunload', remove);
}

//@ set-cookie
function (name, value, path) {
  if (!name) return;
  const ok = /^(?:true|false|yes|no|y|n|ok|on|off|accept|accepted|reject|rejected|allow|allowed|deny|denied|necessary|required|hide|hidden|essential|nonessential|checked|unchecked|forbidden|forever|\d{1,9}|)$/i;
  value = value === undefined ? '' : String(value);
  if (!ok.test(value)) return;
  const enc = encodeURIComponent(name);
  if (document.cookie.split(';').some(c => c.trim() === enc + '=' + value)) return;
  document.cookie = enc + '=' + value + '; path=' + (path === 'none' ? location.pathname : (path || '/'));
}

//@ set-local-storage-item
function (key, value) {
  S.storage(() => window.localStorage, key, value);
}

//@ set-session-storage-item
function (key, value) {
  S.storage(() => window.sessionStorage, key, value);
}
