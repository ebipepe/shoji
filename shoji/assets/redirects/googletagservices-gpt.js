/* SPDX-License-Identifier: Apache-2.0 | Copyright 2026 The Shoji Authors */
/* Shoji の代替品: Google Publisher Tag (gpt.js / googletag) — 広告枠の定義は受け付けるが、何も表示しない */
(function () {
  'use strict';
  var noop = function () {};
  function chain(obj, names) {
    names.forEach(function (n) { obj[n] = function () { return obj; }; });
    return obj;
  }
  var listeners = {};
  var slots = [];
  function fire(type, slot) {
    (listeners[type] || []).forEach(function (fn) {
      setTimeout(function () {
        try {
          fn({ type: type, slot: slot, isEmpty: true, size: null, creativeId: null, lineItemId: null,
               advertiserId: null, campaignId: null, serviceName: 'publisher_ads', inViewPercentage: 0 });
        } catch (e) {}
      }, 1);
    });
  }
  function rendered(list) {
    (list || slots).forEach(function (s) { fire('slotRequested', s); fire('slotResponseReceived', s); fire('slotRenderEnded', s); });
  }
  function Slot(path, sizes, id) {
    var targeting = {};
    var s = chain({}, ['addService', 'clearCategoryExclusions', 'defineSizeMapping', 'set', 'setCategoryExclusion',
                       'setClickUrl', 'setCollapseEmptyDiv', 'setConfig', 'setForceSafeFrame', 'setSafeFrameConfig',
                       'updateTargetingFromMap']);
    s.setTargeting = function (k, v) { targeting[k] = [].concat(v); return s; };
    s.clearTargeting = function (k) { if (k === undefined) targeting = {}; else delete targeting[k]; return s; };
    s.getTargeting = function (k) { return targeting[k] || []; };
    s.getTargetingKeys = function () { return Object.keys(targeting); };
    s.getTargetingMap = function () { return targeting; };
    s.get = function () { return null; };
    s.getAdUnitPath = function () { return path || ''; };
    s.getAttributeKeys = function () { return []; };
    s.getCategoryExclusions = function () { return []; };
    s.getConfig = function () { return {}; };
    s.getDomId = s.getSlotElementId = function () { return id || ''; };
    s.getResponseInformation = function () { return null; };
    s.getSizes = function () { return [].concat(sizes || []); };
    s.getSlotId = function () { return { getId: function () { return (path || '') + '_0'; }, getAdUnitPath: s.getAdUnitPath, getDomId: s.getDomId }; };
    s.getServices = function () { return [pubads]; };
    slots.push(s);
    return s;
  }
  var pageTargeting = {};
  var pubads = chain({}, ['clear', 'clearCategoryExclusions', 'clearTagForChildDirectedTreatment', 'collapseEmptyDivs',
                          'disableInitialLoad', 'enableAsyncRendering', 'enableLazyLoad', 'enableSingleRequest',
                          'enableSyncRendering', 'enableVideoAds', 'set', 'setCategoryExclusion', 'setCentering',
                          'setCookieOptions', 'setForceSafeFrame', 'setLocation', 'setPrivacySettings',
                          'setPublisherProvidedId', 'setRequestNonPersonalizedAds', 'setSafeFrameConfig',
                          'setTagForChildDirectedTreatment', 'setVideoContent', 'updateCorrelator', 'setConfig']);
  pubads.addEventListener = function (type, fn) {
    if (typeof fn === 'function') (listeners[type] = listeners[type] || []).push(fn);
    return pubads;
  };
  pubads.removeEventListener = function (type, fn) {
    var l = listeners[type] || [];
    var i = l.indexOf(fn);
    if (i >= 0) l.splice(i, 1);
    return true;
  };
  pubads.setTargeting = function (k, v) { pageTargeting[k] = [].concat(v); return pubads; };
  pubads.clearTargeting = function (k) { if (k === undefined) pageTargeting = {}; else delete pageTargeting[k]; return pubads; };
  pubads.getTargeting = function (k) { return pageTargeting[k] || []; };
  pubads.getTargetingKeys = function () { return Object.keys(pageTargeting); };
  pubads.get = function () { return null; };
  pubads.getAttributeKeys = function () { return []; };
  pubads.getCorrelator = function () { return '0'; };
  pubads.getSlots = function () { return slots.slice(); };
  pubads.isInitialLoadDisabled = function () { return false; };
  pubads.display = function (path, sizes, id) { var s = Slot(path, sizes, id); rendered([s]); return s; };
  pubads.refresh = function (list) { rendered(list); return pubads; };
  pubads.defineOutOfPagePassback = pubads.definePassback = function (path, sizes) {
    var s = Slot(path, sizes);
    s.display = noop;
    return s;
  };

  var sizeBuilder = function () {
    var b = { addSize: function () { return b; }, build: function () { return []; } };
    return b;
  };
  var old = window.googletag || {};
  var cmd = { push: function () {
    for (var i = 0; i < arguments.length; i++) { if (typeof arguments[i] === 'function') { try { arguments[i](); } catch (e) {} } }
    return 0;
  } };
  var gt = {
    apiReady: true, pubadsReady: true, cmd: cmd, evalScripts: noop,
    companionAds: function () { return chain({}, ['setRefreshUnfilledSlots', 'enableSyncLoading', 'setVideoContent', 'addEventListener']); },
    content: function () { return chain({}, ['setContent', 'addEventListener']); },
    defineOutOfPageSlot: function (path, id) { return Slot(path, [], typeof id === 'string' ? id : ''); },
    defineSlot: function (path, sizes, id) { return Slot(path, sizes, id); },
    destroySlots: function (list) {
      (list || slots.slice()).forEach(function (s) { var i = slots.indexOf(s); if (i >= 0) slots.splice(i, 1); });
      return true;
    },
    disablePublisherConsole: noop, openConsole: noop, setAdIframeTitle: noop, setConfig: noop,
    display: function (id) {
      var s = slots.filter(function (x) { return x.getSlotElementId() === (id && id.id ? id.id : id); });
      rendered(s.length ? s : []);
    },
    enableServices: noop,
    getVersion: function () { return '0'; },
    pubads: function () { return pubads; },
    sizeMapping: sizeBuilder,
    enums: { OutOfPageFormat: { BOTTOM_ANCHOR: 3, INTERSTITIAL: 5, REWARDED: 4, TOP_ANCHOR: 2,
                                LEFT_SIDE_RAIL: 6, RIGHT_SIDE_RAIL: 7 },
             TrafficSource: { ORGANIC: 0, PURCHASED: 1 } }
  };
  window.googletag = gt;
  if (old.cmd && typeof old.cmd.forEach === 'function') old.cmd.forEach(function (f) { cmd.push(f); });
})();
