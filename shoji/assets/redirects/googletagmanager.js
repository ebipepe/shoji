/* SPDX-License-Identifier: Apache-2.0 | Copyright 2026 The Shoji Authors */
/* Shoji の代替品: Google タグマネージャー / gtag.js — 何も送らず、イベント後のコールバックだけ呼ぶ */
(function () {
  'use strict';
  var noop = function () {};
  function later(fn) { setTimeout(function () { try { fn(); } catch (e) {} }, 1); }
  function handle(item) {
    if (!item || typeof item !== 'object') return;
    if (typeof item.eventCallback === 'function') later(item.eventCallback);
    // gtag('event', 名前, { event_callback: fn }) は arguments オブジェクトとして積まれる
    var p = item[2];
    if (item[0] === 'event' && p && typeof p === 'object' && typeof p.event_callback === 'function') later(p.event_callback);
  }
  var dl = window.dataLayer;
  if (dl && typeof dl === 'object') {
    if (dl.hide && typeof dl.hide.end === 'function') { try { dl.hide.end(); } catch (e) {} dl.hide.end = noop; }
    if (typeof dl.push === 'function' && !dl.__shoji) {
      try { Array.prototype.forEach.call(dl, handle); } catch (e) {}
      var push = dl.push;
      dl.push = function () {
        for (var i = 0; i < arguments.length; i++) handle(arguments[i]);
        return push.apply(this, arguments);
      };
      dl.__shoji = true;
    }
  }
  if (typeof window.ga !== 'function') {
    var ga = function () {
      for (var i = 0; i < arguments.length; i++) {
        var a = arguments[i];
        if (typeof a === 'function') { later(a); return; }
        if (a && typeof a === 'object' && typeof a.hitCallback === 'function') { later(a.hitCallback); return; }
      }
    };
    ga.create = ga.getByName = function () { return { get: noop, set: noop, send: noop }; };
    ga.getAll = function () { return []; };
    ga.remove = noop; ga.loaded = true;
    window.ga = ga;
  }
  window.google_tag_manager = window.google_tag_manager || { dataLayer: { gtmDom: true, gtmLoad: true } };
})();
