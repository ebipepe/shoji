/* SPDX-License-Identifier: Apache-2.0 | Copyright 2026 The Shoji Authors */
/* Shoji の代替品: 旧 Google Analytics (ga.js / _gaq) — 何も送らない */
(function () {
  'use strict';
  var noop = function () {};
  function Tracker() {}
  ['_addIgnoredOrganic', '_addIgnoredRef', '_addItem', '_addOrganic', '_addTrans', '_clearIgnoredOrganic',
   '_clearIgnoredRef', '_clearOrganic', '_cookiePathCopy', '_deleteCustomVar', '_initData', '_setAccount',
   '_setAllowAnchor', '_setAllowHash', '_setAllowLinker', '_setCampaignTrack', '_setCampaignCookieTimeout',
   '_setClientInfo', '_setCookiePath', '_setCustomVar', '_setDetectFlash', '_setDetectTitle', '_setDomainName',
   '_setLocalRemoteServerMode', '_setNamespace', '_setReferrerOverride', '_setSampleRate', '_setSessionCookieTimeout',
   '_setSiteSpeedSampleRate', '_setVar', '_setVisitorCookieTimeout', '_trackEvent', '_trackPageLoadTime',
   '_trackPageview', '_trackSocial', '_trackTiming', '_trackTrans', '_visitCode'].forEach(function (m) {
    Tracker.prototype[m] = noop;
  });
  Tracker.prototype._getLinkerUrl = function (u) { return u; };
  Tracker.prototype._link = function (u) { if (u) { try { location.href = u; } catch (e) {} } };
  Tracker.prototype._linkByPost = noop;
  Tracker.prototype._getAccount = function () { return ''; };
  Tracker.prototype._getVersion = function () { return '5'; };
  var tracker = new Tracker();
  var gat = { _anonymizeIp: noop, _createTracker: function () { return tracker; }, _forceSSL: noop,
              _getPlugin: noop, _getTracker: function () { return tracker; }, _getTrackerByName: function () { return tracker; },
              _getTrackers: function () { return [tracker]; } };
  function run(cmd) {
    if (typeof cmd === 'function') { try { cmd(); } catch (e) {} return; }
    if (!Array.isArray(cmd)) return;
    var m = String(cmd[0] || '').replace(/^.*\./, '');
    if (m === '_link' && typeof cmd[1] === 'string') { tracker._link(cmd[1]); return; }
    if (m === '_set' && cmd[1] === 'hitCallback' && typeof cmd[2] === 'function') { setTimeout(cmd[2], 1); }
  }
  var old = window._gaq;
  var gaq = { push: function () { for (var i = 0; i < arguments.length; i++) run(arguments[i]); return 0; } };
  window._gat = gat;
  window._gaq = gaq;
  if (Array.isArray(old)) old.forEach(run);
})();
