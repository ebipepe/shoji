/* SPDX-License-Identifier: Apache-2.0 | Copyright 2026 The Shoji Authors */
/* Shoji の代替品の小物集。Python 側が「//== 名前」で区切って、1 つずつ返す。 */
//== noop.js
(function () {})();
//== fingerprint2.js
(function () {
  'use strict';
  var hash = (function () {
    var s = '';
    for (var i = 0; i < 32; i++) s += Math.floor(Math.random() * 16).toString(16);
    return s;
  })();
  function later(fn, a, b) { setTimeout(function () { try { fn(a, b); } catch (e) {} }, 1); }
  function F() {}
  F.prototype.get = function (cb) { if (typeof cb === 'function') later(cb, hash, []); return hash; };
  F.get = function (opts, cb) { if (typeof opts === 'function') cb = opts; if (typeof cb === 'function') later(cb, []); };
  F.getPromise = function () { return Promise.resolve([]); };
  F.getV18 = function (opts, cb) { if (typeof opts === 'function') cb = opts; if (typeof cb === 'function') later(cb, hash, []); };
  F.x64hash128 = function () { return hash; };
  F.VERSION = '2.1.0';
  window.Fingerprint2 = F;
})();
//== fingerprint3.js
(function () {
  'use strict';
  var id = (function () {
    var s = '';
    for (var i = 0; i < 32; i++) s += Math.floor(Math.random() * 16).toString(16);
    return s;
  })();
  var agent = { get: function () { return Promise.resolve({ visitorId: id, components: {}, confidence: { score: 0 }, version: '3.0.0' }); } };
  window.FingerprintJS = {
    load: function () { return Promise.resolve(agent); },
    hashComponents: function () { return id; },
    componentsToDebugString: function () { return ''; }
  };
})();
//== fuckadblock.js
(function () {
  'use strict';
  function later(fn) { setTimeout(function () { try { fn(); } catch (e) {} }, 1); }
  function F() { this._ok = []; }
  F.prototype.setOption = function () { return this; };
  F.prototype.check = function () { this._ok.forEach(later); return true; };
  F.prototype.emitEvent = function (detected) { if (!detected) this._ok.forEach(later); return this; };
  F.prototype.clearEvent = function () { this._ok = []; };
  F.prototype.on = function (detected, fn) { if (!detected && typeof fn === 'function') { this._ok.push(fn); later(fn); } return this; };
  F.prototype.onDetected = function () { return this; };
  F.prototype.onNotDetected = function (fn) { return this.on(false, fn); };
  window.FuckAdBlock = window.BlockAdBlock = window.SniffAdBlock = F;
  window.fuckAdBlock = window.blockAdBlock = window.sniffAdBlock = new F();
})();
//== amazon-apstag.js
(function () {
  'use strict';
  var noop = function () {};
  window.apstag = {
    _Q: [],
    init: noop,
    fetchBids: function (cfg, cb) { if (typeof cb === 'function') setTimeout(function () { try { cb([]); } catch (e) {} }, 1); },
    setDisplayBids: noop,
    targetingKeys: function () { return []; },
    renderImp: noop,
    punt: noop,
    dpa: noop,
    rpa: noop,
    upa: noop
  };
})();
//== scorecardresearch-beacon.js
(function () {
  'use strict';
  window.COMSCORE = { beacon: function () {}, purge: function () { return []; } };
})();
//== chartbeat.js
(function () {
  'use strict';
  var noop = function () {};
  window.pSUPERFLY = { virtualPage: noop, activity: noop };
})();
