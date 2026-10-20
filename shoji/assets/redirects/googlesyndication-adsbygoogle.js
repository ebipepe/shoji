/* SPDX-License-Identifier: Apache-2.0 | Copyright 2026 The Shoji Authors */
/* Shoji の代替品: Google AdSense (adsbygoogle.js) — 広告は読み込まず、ページ側の push() を受け流す */
(function () {
  'use strict';
  function mark() {
    try {
      document.querySelectorAll('ins.adsbygoogle:not([data-adsbygoogle-status])').forEach(function (ins) {
        ins.setAttribute('data-adsbygoogle-status', 'done');
        ins.setAttribute('data-ad-status', 'unfilled');
      });
    } catch (e) {}
  }
  function run(item) {
    if (item && typeof item === 'object' && item.params && typeof item.params.google_ad_loaded === 'function') {
      try { item.params.google_ad_loaded(); } catch (e) {}
    }
    mark();
  }
  var old = window.adsbygoogle;
  var a = [];
  a.loaded = true;
  a.push = function () { for (var i = 0; i < arguments.length; i++) run(arguments[i]); return 0; };
  window.adsbygoogle = a;
  if (Array.isArray(old)) old.forEach(run);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mark);
  else mark();
})();
