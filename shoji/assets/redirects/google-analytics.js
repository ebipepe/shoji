/* SPDX-License-Identifier: Apache-2.0 | Copyright 2026 The Shoji Authors */
/* Shoji の代替品: Google Analytics (analytics.js) — 何も送らず、ページが待っているコールバックだけ呼ぶ */
(function () {
  'use strict';
  var noop = function () {};
  var tracker = { get: noop, set: noop, send: noop, get_: noop };
  var name = window.GoogleAnalyticsObject || 'ga';
  var old = window[name];
  function later(fn, arg) { setTimeout(function () { try { fn(arg); } catch (e) {} }, 1); }
  function ga() {
    var args = Array.prototype.slice.call(arguments);
    if (!args.length) return;
    if (typeof args[0] === 'function') { later(args[0], tracker); return; }
    for (var i = 0; i < args.length; i++) {
      var a = args[i];
      if (a && typeof a === 'object' && typeof a.hitCallback === 'function') { later(a.hitCallback); return; }
    }
    if (args[0] === 'set' && args[1] === 'hitCallback' && typeof args[2] === 'function') later(args[2]);
  }
  ga.create = function () { return tracker; };
  ga.getByName = function () { return tracker; };
  ga.getAll = function () { return [tracker]; };
  ga.remove = noop;
  ga.loaded = true;
  ga.l = Date.now();
  window[name] = ga;
  if (old && Array.isArray(old.q)) old.q.forEach(function (a) { try { ga.apply(null, a); } catch (e) {} });
  // ページを一時的に隠す仕組み（Google Optimize の anti-flicker）を解除する
  var dl = window.dataLayer;
  if (dl && dl.hide && typeof dl.hide.end === 'function') { try { dl.hide.end(); } catch (e) {} dl.hide.end = noop; }
})();
