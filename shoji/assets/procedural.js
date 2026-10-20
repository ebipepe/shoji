/* SPDX-License-Identifier: Apache-2.0 | Copyright 2026 The Shoji Authors */
/* Shoji 拡張 CSS（手続き型の要素非表示）
 * ブラウザの CSS では書けないルール（文字列で探す・親をたどる・XPath・計算後のスタイルで絞るなど）を、
 * Python 側（shoji/procedural.py）が作った「手順」に従って実行する。
 * ページの変化（MutationObserver）に合わせて間引きながら再実行する。
 */
(function (CFG) {
  'use strict';
  var TASKS = CFG && CFG.proc;
  if (!TASKS || !TASKS.length || window.__shojiProc) return;
  window.__shojiProc = true;

  var MAGIC = CFG.magic;
  var where = location.pathname + location.search;
  var watchAttrs = {};
  var hasWatch = false;
  var done = new WeakSet();
  var count = 0, pendingReport = 0, reportTimer = null;

  function report(n) {
    pendingReport += n;
    if (reportTimer) return;
    reportTimer = setTimeout(function () {
      reportTimer = null;
      var body = JSON.stringify({ host: location.hostname, counts: { cosmetic: pendingReport, _d: ['cosmetic:extended css'] } });
      pendingReport = 0;
      try {
        if (!navigator.sendBeacon || !navigator.sendBeacon(MAGIC + '/report', body)) {
          fetch(MAGIC + '/report', { method: 'POST', body: body, mode: 'no-cors', keepalive: true });
        }
      } catch (e) {}
    }, 3000);
  }

  /* ---------- 手順の準備（正規表現を作っておく。作れない手順は使わない） ---------- */
  function rx(p) { return p ? new RegExp(p[0], p[1]) : null; }
  function compile(task) {
    var t = { s: task.s, o: [], a: task.a ? task.a.slice() : null, p: task.p ? rx(task.p) : null };
    for (var i = 0; i < task.o.length; i++) {
      var op = task.o[i], k = op[0];
      if (k === 'text') t.o.push([k, rx(op[1])]);
      else if (k === 'has' || k === 'not') t.o.push([k, compile(op[1])]);
      else if (k === 'css') t.o.push([k, op[1], rx(op[2]), op[3] || null]);
      else if (k === 'attr') t.o.push([k, rx(op[1]), rx(op[2])]);
      else if (k === 'watch') {
        hasWatch = true;
        op[1].forEach(function (n) { watchAttrs[n] = 1; });
        if (!op[1].length) watchAttrs['*'] = 1;
      } else t.o.push(op);
    }
    if (t.a && (t.a[0] === 'rmattr' || t.a[0] === 'rmclass')) t.a = [t.a[0], rx(t.a[1])];
    if (t.s) document.createDocumentFragment().querySelector(t.s);  // 不正なセレクタならここで例外
    return t;
  }
  var tasks = [];
  TASKS.forEach(function (task) {
    try {
      var t = compile(task);
      if (!t.p || t.p.test(where)) tasks.push(t);
    } catch (e) {}
  });
  if (!tasks.length) return;

  /* ---------- 実行 ---------- */
  function toArray(list) { return Array.prototype.slice.call(list); }
  function unique(arr) {
    var seen = new Set(), out = [];
    for (var i = 0; i < arr.length; i++) if (arr[i] && !seen.has(arr[i])) { seen.add(arr[i]); out.push(arr[i]); }
    return out;
  }
  // 起点の要素から見た相対セレクタ（"> .a" / " .a" / "+ .a" / "~ .a"）
  function relative(el, sel) {
    var c = sel.trim().charAt(0);
    if (c === '+' || c === '~') {
      var p = el.parentElement;
      if (!p) return [];
      var idx = Array.prototype.indexOf.call(p.children, el) + 1;
      return toArray(p.querySelectorAll(':scope > :nth-child(' + idx + ')' + sel));
    }
    if (el.nodeType === 9) return toArray(el.querySelectorAll(sel.replace(/^\s*>/, ':root >')));
    return toArray(el.querySelectorAll(':scope' + (/^\s/.test(sel) ? sel : ' ' + sel)));
  }
  function xpath(ctx, expr) {
    var out = [];
    var r = document.evaluate(expr, ctx, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
    for (var i = 0; i < r.snapshotLength; i++) {
      var n = r.snapshotItem(i);
      if (n && n.nodeType === 1) out.push(n);
    }
    return out;
  }
  function textOf(el) { return el.textContent || ''; }

  function step(els, op) {
    var k = op[0], out = [], i;
    switch (k) {
      case 'text':
        return els.filter(function (e) { return op[1].test(textOf(e)); });
      case 'has':
        return els.filter(function (e) { return run(op[1], e).length > 0; });
      case 'not':
        return els.filter(function (e) { return run(op[1], e).length === 0; });
      case 'up':
        for (i = 0; i < els.length; i++) {
          var e = els[i];
          if (typeof op[1] === 'number') {
            for (var n = op[1]; e && n > 0; n--) e = e.parentElement;
            out.push(e);
          } else if (e.parentElement) {
            out.push(e.parentElement.closest(op[1]));
          }
        }
        return unique(out);
      case 'xpath':
        for (i = 0; i < els.length; i++) out = out.concat(xpath(els[i], op[1]));
        return unique(out);
      case 'css':
        return els.filter(function (e) {
          var v = getComputedStyle(e, op[3])[op[1]];
          if (v === undefined) v = getComputedStyle(e, op[3]).getPropertyValue(op[1]);
          return op[2].test(String(v));
        });
      case 'minlen':
        return els.filter(function (e) { return textOf(e).length >= op[1]; });
      case 'attr':
        return els.filter(function (e) {
          for (var j = 0; j < e.attributes.length; j++) {
            var a = e.attributes[j];
            if (op[1].test(a.name) && (!op[2] || op[2].test(a.value))) return true;
          }
          return false;
        });
      case 'spath':
        for (i = 0; i < els.length; i++) out = out.concat(relative(els[i], op[1]));
        return unique(out);
      case 'match':
        return els.filter(function (e) { return e.matches(op[1]); });
    }
    return els;
  }
  // root が無ければ文書全体、あれば root を起点にする（:has などの中身）
  function run(t, root) {
    var els;
    if (t.s) els = root ? relative(root, ' ' + t.s) : toArray(document.querySelectorAll(t.s));
    else els = [root || document];
    for (var i = 0; i < t.o.length && els.length; i++) els = step(els, t.o[i]);
    return els.filter(function (e) { return e && e.nodeType === 1; });
  }

  function apply(t, el) {
    var a = t.a ? t.a[0] : 'hide';
    if (a === 'remove') { if (el.parentNode) { el.remove(); return true; } return false; }
    if (a === 'style') {
      // 同じ値を書き直すと属性の変化として通知され、無駄な再実行が続くため、違うときだけ書く
      t.a[1].forEach(function (d) {
        if (el.style.getPropertyValue(d[0]) !== d[1] || el.style.getPropertyPriority(d[0]) !== 'important') {
          el.style.setProperty(d[0], d[1], 'important');
        }
      });
      return false;
    }
    if (a === 'rmattr') {
      toArray(el.attributes).forEach(function (at) { if (t.a[1].test(at.name)) el.removeAttribute(at.name); });
      return false;
    }
    if (a === 'rmclass') {
      toArray(el.classList).forEach(function (c) { if (t.a[1].test(c)) el.classList.remove(c); });
      return false;
    }
    if (el.style.getPropertyValue('display') === 'none' && el.style.getPropertyPriority('display') === 'important') return false;
    el.style.setProperty('display', 'none', 'important');
    el.setAttribute('data-shoji', 'hidden');
    return !done.has(el);
  }

  var busy = false;
  function scan() {
    if (busy || !document.documentElement) return;
    busy = true;
    var n = 0;
    try {
      for (var i = 0; i < tasks.length; i++) {
        var els;
        try { els = run(tasks[i], null); } catch (e) { tasks.splice(i--, 1); continue; }
        for (var j = 0; j < els.length; j++) {
          var el = els[j];
          if (el === document.documentElement || el === document.body && (!tasks[i].a || tasks[i].a[0] === 'remove')) continue;
          if (apply(tasks[i], el)) n++;
          done.add(el);
        }
      }
    } finally {
      busy = false;
    }
    if (n) { count += n; report(n); }
  }

  /* ---------- ページの変化に合わせて再実行（間引きつき） ---------- */
  var timer = null, last = 0;
  function schedule() {
    if (timer) return;
    var wait = Math.max(0, 120 - (Date.now() - last));
    timer = setTimeout(function () { timer = null; last = Date.now(); scan(); }, wait);
  }
  function start() {
    scan();
    var opts = { childList: true, subtree: true };
    if (hasWatch) {
      opts.attributes = true;
      if (!watchAttrs['*']) opts.attributeFilter = Object.keys(watchAttrs);
    }
    try {
      new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
          var m = muts[i];
          if (m.type === 'attributes' || m.addedNodes.length) { schedule(); return; }
        }
      }).observe(document.documentElement, opts);
    } catch (e) {}
    window.addEventListener('load', schedule);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
    // 早く出てくる広告のために、読み込み途中でも何度か実行する
    var early = setInterval(function () { if (document.readyState !== 'loading') clearInterval(early); else scan(); }, 250);
  } else {
    start();
  }
})(window.__SHOJI_CFG__);
