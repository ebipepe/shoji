/* SPDX-License-Identifier: Apache-2.0 | Copyright 2026 The Shoji Authors */
/* Shoji の代替品: Google IMA SDK (ima3.js) — 動画広告の要求に「広告なし」のエラーを返し、
 * 動画プレイヤーがすぐ本編に進めるようにする */
(function () {
  'use strict';
  if (window.google && window.google.ima && window.google.ima.__shoji) return;
  var noop = function () {};

  function Emitter() { this._l = {}; }
  Emitter.prototype.addEventListener = function (types, fn) {
    var self = this;
    [].concat(types).forEach(function (t) { (self._l[t] = self._l[t] || []).push(fn); });
  };
  Emitter.prototype.removeEventListener = function (types, fn) {
    var self = this;
    [].concat(types).forEach(function (t) {
      var l = self._l[t] || [];
      var i = l.indexOf(fn);
      if (i >= 0) l.splice(i, 1);
    });
  };
  Emitter.prototype._emit = function (t, ev) {
    (this._l[t] || []).slice().forEach(function (fn) {
      try { if (typeof fn === 'function') fn(ev); else if (fn && fn.handleEvent) fn.handleEvent(ev); } catch (e) {}
    });
  };

  function AdError(message, code, type) { this.message = message; this.errorCode = code; this.type = type; }
  AdError.prototype.getMessage = function () { return this.message; };
  AdError.prototype.getErrorCode = function () { return this.errorCode; };
  AdError.prototype.getVastErrorCode = function () { return 303; };
  AdError.prototype.getType = function () { return this.type; };
  AdError.prototype.getInnerError = function () { return null; };
  AdError.prototype.toString = function () { return 'AdError ' + this.errorCode + ': ' + this.message; };
  AdError.ErrorCode = { VAST_EMPTY_RESPONSE: 1009, VAST_NO_ADS_AFTER_WRAPPER: 303, UNKNOWN_ERROR: 900,
                        VAST_LOAD_TIMEOUT: 301, VAST_MEDIA_LOAD_TIMEOUT: 402, FAILED_TO_REQUEST_ADS: 1005,
                        INVALID_ARGUMENTS: 1101, AUTOPLAY_DISALLOWED: 1205 };
  AdError.Type = { AD_LOAD: 'adLoadError', AD_PLAY: 'adPlayError' };

  function AdErrorEvent(err, ctx) { this.type = 'adError'; this._err = err; this._ctx = ctx; }
  AdErrorEvent.prototype.getError = function () { return this._err; };
  AdErrorEvent.prototype.getUserRequestContext = function () { return this._ctx || {}; };
  AdErrorEvent.Type = { AD_ERROR: 'adError' };

  function AdEvent(type) { this.type = type; }
  AdEvent.prototype.getAd = function () { return null; };
  AdEvent.prototype.getAdData = function () { return {}; };
  AdEvent.Type = {};
  ['AD_BREAK_READY', 'AD_BREAK_FETCH_ERROR', 'AD_BUFFERING', 'AD_CAN_PLAY', 'AD_METADATA', 'AD_PROGRESS', 'ALL_ADS_COMPLETED',
   'CLICK', 'COMPLETE', 'CONTENT_PAUSE_REQUESTED', 'CONTENT_RESUME_REQUESTED', 'DURATION_CHANGE', 'FIRST_QUARTILE',
   'IMPRESSION', 'INTERACTION', 'LINEAR_CHANGED', 'LOADED', 'LOG', 'MIDPOINT', 'PAUSED', 'RESUMED', 'SKIPPABLE_STATE_CHANGED',
   'SKIPPED', 'STARTED', 'THIRD_QUARTILE', 'USER_CLOSE', 'VIDEO_CLICKED', 'VIDEO_ICON_CLICKED', 'VOLUME_CHANGED',
   'VOLUME_MUTED', 'AD_MUTED', 'IMAGE_CLICKED'].forEach(function (k) {
    AdEvent.Type[k] = k.toLowerCase().replace(/_([a-z])/g, function (_, c) { return c.toUpperCase(); });
  });

  function AdsManagerLoadedEvent() { this.type = 'adsManagerLoaded'; }
  AdsManagerLoadedEvent.Type = { ADS_MANAGER_LOADED: 'adsManagerLoaded' };

  function AdDisplayContainer() {}
  AdDisplayContainer.prototype.initialize = noop;
  AdDisplayContainer.prototype.destroy = noop;

  var settings = {
    _locale: 'en', _vpaid: 0,
    getLocale: function () { return this._locale; }, setLocale: function (l) { this._locale = l; },
    getVpaidMode: function () { return this._vpaid; }, setVpaidMode: function (m) { this._vpaid = m; },
    getNumRedirects: function () { return 4; }, getPlayerType: function () { return ''; },
    getPlayerVersion: function () { return ''; }, getPpid: function () { return ''; },
    getDisableCustomPlaybackForIOS10Plus: function () { return false; }, getFeatureFlags: function () { return {}; },
    isCookiesEnabled: function () { return false; }, isVpaidAdapter: function () { return false; },
    getCompanionBackfill: function () { return 'off'; }
  };
  ['setAutoPlayAdBreaks', 'setCompanionBackfill', 'setCookiesEnabled', 'setDisableCustomPlaybackForIOS10Plus',
   'setFeatureFlags', 'setIsVpaidAdapter', 'setNumRedirects', 'setPlayerType', 'setPlayerVersion', 'setPpid',
   'setSessionId', 'setSurveyEnabled', 'setDisableFlashAds', 'setStreamCorrelator'].forEach(function (k) { settings[k] = noop; });

  function AdsLoader() { Emitter.call(this); }
  AdsLoader.prototype = Object.create(Emitter.prototype);
  AdsLoader.prototype.constructor = AdsLoader;
  AdsLoader.prototype.getSettings = function () { return settings; };
  AdsLoader.prototype.contentComplete = noop;
  AdsLoader.prototype.destroy = noop;
  AdsLoader.prototype.getVersion = function () { return ima.VERSION; };
  AdsLoader.prototype.requestAds = function (req, ctx) {
    var self = this;
    setTimeout(function () {
      self._emit('adError', new AdErrorEvent(new AdError('No ads (blocked by Shoji)', 1009, 'adLoadError'), ctx));
    }, 1);
  };

  function AdsRequest() {
    this.adTagUrl = ''; this.adsResponse = null; this.linearAdSlotWidth = 0; this.linearAdSlotHeight = 0;
    this.nonLinearAdSlotWidth = 0; this.nonLinearAdSlotHeight = 0; this.vastLoadTimeout = 5000;
  }
  ['setAdWillAutoPlay', 'setAdWillPlayMuted', 'setContinuousPlayback', 'setContentDuration', 'setContentKeywords',
   'setContentTitle', 'setLiveStreamPrefetchSeconds'].forEach(function (k) { AdsRequest.prototype[k] = noop; });

  function AdsRenderingSettings() {
    this.autoAlign = true; this.bitrate = -1; this.enablePreloading = false; this.loadVideoTimeout = 8000;
    this.mimeTypes = null; this.restoreCustomPlaybackStateOnAdBreakComplete = false; this.uiElements = null;
    this.useStyledLinearAds = false; this.useStyledNonLinearAds = false;
  }

  function CompanionAdSelectionSettings() {}
  CompanionAdSelectionSettings.CreativeType = { ALL: 'All', FLASH: 'Flash', IMAGE: 'Image' };
  CompanionAdSelectionSettings.ResourceType = { ALL: 'All', HTML: 'Html', IFRAME: 'IFrame', STATIC: 'Static' };
  CompanionAdSelectionSettings.SizeCriteria = { IGNORE: 'IgnoreSize', SELECT_EXACT_MATCH: 'SelectExactMatch',
                                                SELECT_NEAR_MATCH: 'SelectNearMatch' };

  var ima = {
    __shoji: true,
    VERSION: '3.0.0',
    AdDisplayContainer: AdDisplayContainer,
    AdError: AdError,
    AdErrorEvent: AdErrorEvent,
    AdEvent: AdEvent,
    AdsLoader: AdsLoader,
    AdsManagerLoadedEvent: AdsManagerLoadedEvent,
    AdsRenderingSettings: AdsRenderingSettings,
    AdsRequest: AdsRequest,
    CompanionAdSelectionSettings: CompanionAdSelectionSettings,
    ImaSdkSettings: { VpaidMode: { DISABLED: 0, ENABLED: 1, INSECURE: 2 },
                      CompanionBackfillMode: { ALWAYS: 'always', ON_MASTER_AD: 'on_master_ad' } },
    OmidAccessMode: { DOMAIN: 'domain', FULL: 'full', LIMITED: 'limited' },
    OmidVerificationVendor: {},
    UiElements: { AD_ATTRIBUTION: 'adAttribution', COUNTDOWN: 'countdown' },
    ViewMode: { FULLSCREEN: 'fullscreen', NORMAL: 'normal' },
    settings: settings
  };
  window.google = window.google || {};
  window.google.ima = ima;
})();
