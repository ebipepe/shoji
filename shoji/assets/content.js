/* SPDX-License-Identifier: Apache-2.0 | Copyright 2026 The Shoji Authors */
/* Shoji ページ内スクリプト
 * プロキシが HTML に埋め込み、ページのスクリプトより先に実行される。
 *   - ポップアップ / ポップアンダーのブロック
 *   - 再挿入された広告の除去（MutationObserver）
 *   - 広告削除後のスペース調整（空になった広告枠を畳む）
 *   - YouTube 動画広告の除去・自動スキップ
 *   - AMP リンクの書き換え
 *   - ステルスモード（追跡パラメーター除去・ping 属性除去・WebRTC/フィンガープリント対策）
 */
(function (CFG) {
  'use strict';
  if (window.__shojiLoaded) return;
  window.__shojiLoaded = true;

  var F = CFG.f || {}, S = CFG.s || {};
  var MAGIC = CFG.magic;
  var HOST = location.hostname;
  var isTop = window === window.top;

  /* ---------------- 統計の報告 ---------------- */
  var pending = {}, pendingTimer = null;
  function report(kind, n, detail) {
    pending[kind] = (pending[kind] || 0) + (n || 1);
    if (detail) { pending._d = pending._d || []; if (pending._d.length < 20) pending._d.push(kind + ':' + detail); }
    if (!pendingTimer) pendingTimer = setTimeout(flush, 2500);
  }
  function flush() {
    pendingTimer = null;
    var body = JSON.stringify({ host: HOST, counts: pending });
    pending = {};
    try {
      if (!navigator.sendBeacon || !navigator.sendBeacon(MAGIC + '/report', body)) {
        fetch(MAGIC + '/report', { method: 'POST', body: body, mode: 'no-cors', keepalive: true });
      }
    } catch (e) {}
  }
  window.addEventListener('pagehide', function () { if (pendingTimer) { clearTimeout(pendingTimer); flush(); } });

  function regDomain(h) {
    var p = (h || '').split('.');
    if (p.length >= 3 && /^(co|ne|or|ac|go|ad|ed|gr|lg|com|net|org|gov)$/.test(p[p.length - 2])) return p.slice(-3).join('.');
    return p.slice(-2).join('.');
  }
  function sameSite(url) {
    try { return regDomain(new URL(url, location.href).hostname) === regDomain(HOST); } catch (e) { return true; }
  }

  /* ---------------- ポップアップのブロック ---------------- */
  if (F.block_popups) {
    var lastDown = null;
    document.addEventListener('pointerdown', function (e) { lastDown = { t: e.target, at: Date.now() }; }, true);

    var isRealControl = function (el) {
      for (var i = 0; el && i < 6; i++, el = el.parentElement) {
        var tag = el.tagName;
        if (tag === 'A' || tag === 'BUTTON' || tag === 'INPUT' || tag === 'SELECT' || tag === 'LABEL' ||
            tag === 'SUMMARY' || tag === 'VIDEO' || (el.getAttribute && /button|link|menuitem|tab/.test(el.getAttribute('role') || ''))) return true;
      }
      return false;
    };
    // 画面全体を覆う透明なオーバーレイ（クリックを横取りする罠）
    var isOverlayTrap = function (el) {
      if (!el || el === document.body || el === document.documentElement) return false;
      try {
        var r = el.getBoundingClientRect(), cs = getComputedStyle(el);
        var big = r.width * r.height > innerWidth * innerHeight * 0.6;
        var pos = cs.position === 'fixed' || cs.position === 'absolute';
        var invisible = parseFloat(cs.opacity) < 0.15 || (cs.backgroundColor === 'rgba(0, 0, 0, 0)' && !el.textContent.trim() && !el.querySelector('img,video,canvas,svg'));
        return big && pos && invisible && (parseInt(cs.zIndex, 10) || 0) > 100;
      } catch (e) { return false; }
    };

    var origOpen = window.open;
    var blockedOpen = function (url) {
      report('popup', 1, String(url || '').slice(0, 120));
      return null;
    };
    window.open = function (url) {
      var active = navigator.userActivation ? navigator.userActivation.isActive : true;
      var recent = lastDown && Date.now() - lastDown.at < 1500;
      if (!active) return blockedOpen(url);                       // ユーザー操作なしで開こうとした
      if (url && !sameSite(url) && recent && !isRealControl(lastDown.t)) return blockedOpen(url); // ポップアンダー
      if (recent && isOverlayTrap(lastDown.t)) return blockedOpen(url);
      return origOpen.apply(this, arguments);
    };

    // スクリプトで生成したリンクをクリックさせて新しいタブを開く手口
    document.addEventListener('click', function (e) {
      var a = e.target && e.target.closest ? e.target.closest('a[target]') : null;
      if (!a || !a.href || a.target === '_self' || a.target === '_top' || a.target === '_parent') return;
      if (!/^https?:/.test(a.href) || a.hasAttribute('download')) return;
      if ((!e.isTrusted || !a.isConnected) && !sameSite(a.href)) {
        e.preventDefault(); e.stopImmediatePropagation(); report('popup', 1, a.href.slice(0, 120));
      }
    }, true);
    var origClick = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () {
      if (this.target && this.target !== '_self' && !this.isConnected && /^https?:/.test(this.href) && !this.hasAttribute('download') && !sameSite(this.href)) {
        report('popup', 1, String(this.href).slice(0, 120)); return;
      }
      return origClick.apply(this, arguments);
    };
    // 透明オーバーレイの罠は押した瞬間に取り除く
    document.addEventListener('pointerdown', function (e) {
      if (isOverlayTrap(e.target) && e.target.querySelector && !e.target.querySelector('input,textarea,button,video')) {
        var link = e.target.closest('a[href]');
        if (link && /^https?:/.test(link.href) && !sameSite(link.href)) {
          e.preventDefault(); e.stopImmediatePropagation();
          e.target.remove(); report('popup', 1, 'overlay');
        }
      }
    }, true);
  }

  /* ---------------- ステルス: ブラウザ情報・フィンガープリント ---------------- */
  if (S.enabled && S.block_webrtc_leak && window.RTCPeerConnection) {
    var Orig = window.RTCPeerConnection;
    var priv = /(^|\s)(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|169\.254\.|fe80:|fd[0-9a-f]{2}:)/i;
    var Wrapped = function (cfg, opt) {
      var pc = new Orig(cfg, opt);
      var filt = function (ev) { return !(ev && ev.candidate && ev.candidate.candidate && / typ host/.test(ev.candidate.candidate) && priv.test(ev.candidate.candidate.split(' ')[4] || '')); };
      var origAdd = pc.addEventListener;
      pc.addEventListener = function (type, fn, o) {
        if (type === 'icecandidate' && typeof fn === 'function') {
          var f = fn; fn = function (ev) { if (filt(ev)) return f.call(this, ev); };
        }
        return origAdd.call(this, type, fn, o);
      };
      var handler = null;
      Object.defineProperty(pc, 'onicecandidate', {
        get: function () { return handler; },
        set: function (fn) { handler = fn; origAdd.call(pc, 'icecandidate', function (ev) { if (handler && filt(ev)) handler.call(pc, ev); }); }
      });
      return pc;
    };
    Wrapped.prototype = Orig.prototype;
    try { Object.setPrototypeOf(Wrapped, Orig); } catch (e) {}
    window.RTCPeerConnection = Wrapped;
    if (window.webkitRTCPeerConnection) window.webkitRTCPeerConnection = Wrapped;
  }

  if (S.enabled && S.fingerprint_protection) {
    var def = function (obj, prop, val) {
      try { Object.defineProperty(obj, prop, { get: function () { return typeof val === 'function' ? val() : val; }, configurable: true }); } catch (e) {}
    };
    var NP = Navigator.prototype;
    def(NP, 'hardwareConcurrency', 4);
    def(NP, 'deviceMemory', 8);
    if (window.Screen) {
      var SP = Screen.prototype;
      // 実際の解像度・タスクバー位置を隠し、最も一般的な値を返す
      def(SP, 'width', 1920); def(SP, 'height', 1080);
      def(SP, 'availWidth', 1920); def(SP, 'availHeight', 1040);
      def(SP, 'colorDepth', 24); def(SP, 'pixelDepth', 24);
    }
    // Canvas フィンガープリント対策: 読み出し時にごく僅かなノイズを加える（見た目は変わらない）
    var seed = (Math.random() * 1e9) | 0;
    var noisify = function (canvas) {
      try {
        var ctx = canvas.getContext('2d');
        if (!ctx || canvas.width * canvas.height > 4e6 || canvas.width === 0) return;
        var x = seed % canvas.width, y = (seed >> 8) % canvas.height;
        var d = origGet.call(ctx, x, y, 1, 1);
        d.data[0] = d.data[0] ^ 1;
        ctx.putImageData(d, x, y);
      } catch (e) {}
    };
    var CRC = window.CanvasRenderingContext2D && CanvasRenderingContext2D.prototype;
    var origGet = CRC && CRC.getImageData;
    if (CRC) {
      var origToData = HTMLCanvasElement.prototype.toDataURL;
      HTMLCanvasElement.prototype.toDataURL = function () { noisify(this); return origToData.apply(this, arguments); };
      var origToBlob = HTMLCanvasElement.prototype.toBlob;
      HTMLCanvasElement.prototype.toBlob = function () { noisify(this); return origToBlob.apply(this, arguments); };
      CRC.getImageData = function () { var r = origGet.apply(this, arguments); if (r && r.data && r.data.length > 64) r.data[(seed % (r.data.length / 4)) * 4] ^= 1; return r; };
    }
  }

  /* ---------------- YouTube ---------------- */
  var isYT = /(^|\.)youtube(-nocookie|kids)?\.com$/.test(HOST);
  if (isYT && F.youtube_ads) {
    var AD_KEYS = ['adPlacements', 'playerAds', 'adSlots', 'adBreakHeartbeatParams'];
    var isPlayer = function (o) { return o && typeof o === 'object' && ('videoDetails' in o || 'playabilityStatus' in o || 'streamingData' in o); };
    var pruneObj = function (o) {
      var n = 0;
      if (!o || typeof o !== 'object') return 0;
      if (o.playerResponse) n += pruneObj(o.playerResponse);
      if (!isPlayer(o)) return n;
      for (var i = 0; i < AD_KEYS.length; i++) { if (o[AD_KEYS[i]]) { delete o[AD_KEYS[i]]; n++; } }
      return n;
    };
    // ページ内で組み立てられるプレイヤー設定にも適用（プロキシ処理の取りこぼし対策）
    // 同じ動画のプレイヤー設定は何度も解析されるので、動画ごとに 1 回だけ数える
    var countedVideos = Object.create(null);
    var reportVideo = function (o, n, how) {
      var vid = (o && o.videoDetails && o.videoDetails.videoId) || (o && o.playerResponse && o.playerResponse.videoDetails && o.playerResponse.videoDetails.videoId) || how;
      if (n && !countedVideos[vid]) { countedVideos[vid] = 1; report('youtube', 1, how); }
    };
    var origParse = JSON.parse;
    JSON.parse = function () {
      var r = origParse.apply(this, arguments);
      try { if (r && typeof r === 'object' && ((isPlayer(r) && (r.adPlacements || r.playerAds || r.adSlots)) || (r.playerResponse && r.playerResponse.adPlacements))) { var n = pruneObj(r); reportVideo(r, n, 'json'); } } catch (e) {}
      return r;
    };
    var trap = function (name) {
      var val;
      try {
        Object.defineProperty(window, name, {
          configurable: true,
          get: function () { return val; },
          set: function (v) { var n = pruneObj(v); reportVideo(v, n, name); val = v; }
        });
      } catch (e) {}
    };
    trap('ytInitialPlayerResponse');

    // それでも広告が再生された場合（サーバー挿入型など）は即スキップする
    var skipAd = function () {
      var player = document.querySelector('.html5-video-player');
      if (!player || !player.classList.contains('ad-showing')) return;
      var v = player.querySelector('video');
      var btn = document.querySelector('.ytp-ad-skip-button, .ytp-ad-skip-button-modern, .ytp-skip-ad-button, button[id^="skip-button"]');
      if (btn) { btn.click(); }
      if (v && isFinite(v.duration) && v.duration > 0) {
        v.muted = true;
        try { v.currentTime = v.duration - 0.05; } catch (e) {}
        v.playbackRate = 16;
      }
      if (!player.__kkCounted) { player.__kkCounted = true; report('youtube', 1, 'skip'); setTimeout(function () { player.__kkCounted = false; }, 4000); }
    };
    setInterval(skipAd, 300);
    document.addEventListener('yt-navigate-finish', skipAd);
  }

  /* ---------------- 要素非表示・再挿入対策・スペース調整 ---------------- */
  var hideSelectors = (CFG.sel || []).slice();
  var excSelector = (CFG.exc || []).join(',');
  var isException = function (el) { if (!excSelector) return false; try { return el.matches(excSelector); } catch (e) { excSelector = ''; return false; } };
  var hiddenSet = new WeakSet();
  var seenSigs = Object.create(null);
  var startAt = Date.now();

  // 汎用ルール（数万個）を毎回 querySelectorAll すると重いので、
  // 単純な .class / #id / tag.class セレクタを辞書にして要素側から引く（uBlock Origin と同じ考え方）
  var genClass = null, genId = null, genComplex = null, genLoading = false, genHas = [], lastHas = 0;
  var injected = Object.create(null);
  (CFG.exc || []).forEach(function (x) { injected[x] = 1; });   // 例外セレクタは追加しない
  var styleEl = document.getElementById('shoji-css');
  function buildGenericIndex() {
    if (genClass) return true;
    if (!CFG.gen) return false;
    if (!genLoading) {
      genLoading = true;
      // 単純セレクタの辞書（ブラウザにキャッシュされる）。読み込めたら全体を照合し直す
      fetch(MAGIC + '/generic-simple.json?v=' + CFG.v, { credentials: 'omit' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          genClass = d.c || {}; genId = d.i || {};
          // 不正なセレクタを除いてから 1 つにまとめる
          genHas = (d.h || []).filter(function (x) { try { document.querySelector(x); return true; } catch (e) { return false; } });
          genHas = genHas.length ? [genHas.join(',')] : [];
          fullScan = true; queueScan();
        })
        .catch(function () {});
    }
    if (genComplex === null) {
      try {
        for (var i = 0; i < document.styleSheets.length; i++) {
          var sh = document.styleSheets[i];
          if (!sh.href || sh.href.indexOf(MAGIC) !== 0) continue;
          var rules = sh.cssRules, out = [];
          for (var j = 0; j < rules.length; j++) if (rules[j].selectorText) out.push(rules[j].selectorText);
          genComplex = out;
        }
      } catch (e) {}
    }
    return !!genClass;
  }
  // 一致したセレクタをページの <style> に CSSOM で追加する（CSP の影響を受けない）
  function injectSel(sel) {
    if (injected[sel]) return;
    injected[sel] = 1;
    try {
      if (!styleEl || !styleEl.isConnected) {
        styleEl = document.createElement('style');
        (document.head || document.documentElement).appendChild(styleEl);
      }
      styleEl.sheet.insertRule(sel + '{display:none!important}', styleEl.sheet.cssRules.length);
    } catch (e) {}
  }
  function genericMatch(el) {
    var t, hit = false, i, tag = el.tagName.toLowerCase();
    if (el.id && (t = genId[el.id])) {
      for (i = 0; i < t.length; i++) if (t[i] === '' || t[i] === tag) { injectSel(t[i] + '#' + el.id); hit = true; }
    }
    var cl = el.classList;
    if (cl) for (var k = 0; k < cl.length; k++) {
      if ((t = genClass[cl[k]])) for (i = 0; i < t.length; i++) if (t[i] === '' || t[i] === tag) { injectSel(t[i] + '.' + cl[k]); hit = true; }
    }
    return hit;
  }
  var specificSel = function () { return hideSelectors.join(','); };
  function matchesHide(el) {
    try { if (hideSelectors.length && el.matches(specificSel())) return true; } catch (e) {}
    if (genClass && genericMatch(el)) return true;
    if (genComplex) for (var i = 0; i < genComplex.length; i++) { try { if (el.matches(genComplex[i])) return true; } catch (e) {} }
    return false;
  }
  var pendingRoots = [], fullScan = true;

  function sig(el) {
    return el.tagName + '#' + (el.id || '') + '.' + (typeof el.className === 'string' ? el.className : '') + '@' + (el.getAttribute('src') || el.getAttribute('data-ad-slot') || '');
  }
  function isVisible(el) {
    var cs = getComputedStyle(el);
    return cs.display !== 'none' && cs.visibility !== 'hidden';
  }
  function hideEl(el) {
    el.style.setProperty('display', 'none', 'important');
    el.setAttribute('data-shoji', 'hidden');
  }
  var LABEL_RE = /^(広告|スポンサー(リンク)?|PR|AD|Ads?|Advertisement|Sponsored|プロモーション|Promoted|スポンサードリンク|[\s　・:：|]*)$/i;
  // 広告を消した後、空っぽになった親要素（枠・余白）も畳む
  function collapseUp(el) {
    if (!F.collapse_space) return;
    var p = el.parentElement;
    for (var depth = 0; p && depth < 4 && p !== document.body && p !== document.documentElement; depth++) {
      var kids = p.children, visible = 0;
      for (var i = 0; i < kids.length && visible === 0; i++) {
        var k = kids[i];
        if (k.tagName === 'SCRIPT' || k.tagName === 'STYLE' || k.tagName === 'NOSCRIPT' || k.tagName === 'LINK') continue;
        if (k.getAttribute('data-shoji') === 'hidden') continue;
        if (!isVisible(k)) continue;
        if (k.children.length === 0 && LABEL_RE.test((k.textContent || '').trim()) && !/IMG|VIDEO|CANVAS|IFRAME|SVG/.test(k.tagName)) continue;
        visible++;
      }
      var ownText = '';
      for (var c = p.firstChild; c; c = c.nextSibling) if (c.nodeType === 3) ownText += c.nodeValue;
      if (visible > 0 || !LABEL_RE.test(ownText.trim())) break;
      hideEl(p);
      p = p.parentElement;
    }
  }

  function handleMatch(el, isScanAfterLoad) {
    if (isException(el)) return;
    if (hiddenSet.has(el)) {
      if (isVisible(el)) { el.remove(); report('reinserted', 1, sig(el).slice(0, 80)); }
      return;
    }
    hiddenSet.add(el);
    var s = sig(el);
    var visible = isVisible(el);
    if (visible) {
      // CSS で隠したはずなのに表示されている = インライン !important 等で無理やり再表示されている
      el.remove();
      if (F.anti_reinsertion) report('reinserted', 1, s.slice(0, 80));
      return;
    }
    if (F.anti_reinsertion && isScanAfterLoad && seenSigs[s]) report('reinserted', 1, s.slice(0, 80));
    seenSigs[s] = 1;
    report('cosmetic', 1);
    collapseUp(el);
  }

  // サイトが自分で貼ったアフィリエイトのバナー画像（画像はサイト内にあり、リンクだけが広告）。
  // rel="sponsored"（宣伝リンクの目印）や、Amazon・楽天・A8 等のアフィリエイトリンクで囲まれた
  // ある程度の大きさの画像だけを隠す。文字のリンクや記事中の商品紹介ボックスは対象にしない。
  var AFF_LINK = 'a[rel~="sponsored"], a[href*="amzn.to/"], a[href*="link.amazon/"], a[href*="amzn.asia/"],' +
    ' a[href*="amazon.co.jp/"][href*="tag="], a[href*="hb.afl.rakuten.co.jp"], a[href*="px.a8.net"],' +
    ' a[href*="ck.jp.ap.valuecommerce.com"], a[href*="h.accesstrade.net"], a[href*="af.moshimo.com"]';
  var BOX_EXCLUDE = '.pochipp-box, .yyi-rinker-contents, .kaerebalink-box, .booklink-box, .product-item-box, article .entry-content table';
  function scanAffiliate() {
    if (!F.hide_affiliate_banners) return;
    var links;
    try { links = document.querySelectorAll(AFF_LINK); } catch (e) { return; }
    for (var i = 0; i < links.length; i++) {
      var a = links[i];
      if (hiddenSet.has(a) || isException(a) || a.closest(BOX_EXCLUDE)) continue;
      var img = a.querySelector('img, picture, video');
      if (!img) continue;
      var r = img.getBoundingClientRect();
      var w = r.width || img.naturalWidth || +img.getAttribute('width') || 0;
      var h = r.height || img.naturalHeight || +img.getAttribute('height') || 0;
      if (w < 120 || h < 60) continue;          // アイコン等の小さな画像は対象外
      hiddenSet.add(a); hideEl(a); report('cosmetic', 1, 'affiliate'); collapseUp(a);
    }
  }

  // 標準的な広告サイズの外部 iframe（ランダムなクラス名で再挿入される広告への対策）
  var AD_SIZES = ['300x250', '336x280', '728x90', '970x90', '970x250', '320x50', '320x100', '160x600', '300x600', '468x60', '234x60', '120x600', '250x250', '200x200', '300x50'];
  var AD_HINT = /ad[sx]?[\W_]|doubleclick|googlesyndication|adservice|banner|sponsor|criteo|taboola|outbrain|amazon-adsystem|adnxs|i-mobile|microad|adingo|fluct|nend|zucks|logly|popin|gssprt|socdm|impact-ad|ladsp/i;
  function scanIframes(root) {
    if (!F.anti_reinsertion) return;
    var frames = (root.querySelectorAll ? root.querySelectorAll('iframe') : []);
    for (var i = 0; i < frames.length; i++) {
      var f = frames[i];
      if (hiddenSet.has(f)) continue;
      var size = (f.getAttribute('width') || f.offsetWidth) + 'x' + (f.getAttribute('height') || f.offsetHeight);
      var src = f.getAttribute('src') || '';
      if (AD_SIZES.indexOf(size) >= 0 && (AD_HINT.test(src) || AD_HINT.test(f.id + ' ' + f.name)) && !sameSite(src || location.href)) {
        hiddenSet.add(f); hideEl(f); report('cosmetic', 1, 'iframe ' + size); collapseUp(f);
      }
    }
  }

  var scanQueued = false, lastScan = 0, scanCost = 0;
  function scan() {
    scanQueued = false;
    var t0 = performance.now();
    try { scanInner(); } finally { scanCost = performance.now() - t0; lastScan = Date.now(); }
  }
  function scanInner() {
    if (!F.cosmetic) return;
    var afterLoad = Date.now() - startAt > 3000;
    var i, list;
    // サイト別ルール（少数）は毎回まとめて照合
    if (hideSelectors.length) {
      try { list = document.querySelectorAll(specificSel()); } catch (e) {
        // 1 つの不正セレクタで全体が無効にならないよう個別に試す
        hideSelectors = hideSelectors.filter(function (s) { try { document.querySelector(s); return true; } catch (x) { return false; } });
        list = [];
      }
      for (i = 0; i < list.length; i++) handleMatch(list[i], afterLoad);
    }
    // 汎用ルール: 初回は全要素、以降は追加された要素だけを辞書で照合
    var roots = pendingRoots; pendingRoots = [];
    if (buildGenericIndex()) {
      var els = [];
      if (fullScan) { els = document.querySelectorAll('[id],[class]'); fullScan = false; }
      else {
        for (var r = 0; r < roots.length && els.length < 8000; r++) {
          var root = roots[r];
          if (!root.isConnected) continue;
          els.push(root);
          var sub = root.querySelectorAll ? root.querySelectorAll('[id],[class]') : [];
          for (var q = 0; q < sub.length && els.length < 8000; q++) els.push(sub[q]);
        }
      }
      for (i = 0; i < els.length; i++) if (!hiddenSet.has(els[i]) && genericMatch(els[i])) handleMatch(els[i], afterLoad);
      // :has() を含む汎用ルールは 2 秒に 1 回まで
      if (genHas.length && Date.now() - lastHas > 2000) {
        lastHas = Date.now();
        list = document.querySelectorAll(genHas[0]);
        for (i = 0; i < list.length; i++) if (!hiddenSet.has(list[i]) && !isException(list[i])) { hideEl(list[i]); handleMatch(list[i], afterLoad); }
      }
    }
    // !important のインラインスタイルで無理やり表示し直された広告（再挿入対策）
    if (F.anti_reinsertion) {
      list = document.querySelectorAll('[style*="important"]:not([data-shoji])');
      for (i = 0; i < list.length && i < 200; i++) if (!hiddenSet.has(list[i]) && matchesHide(list[i])) handleMatch(list[i], afterLoad);
    }
    scanAffiliate();
    if (fullScan || roots.length > 50) scanIframes(document);
    else for (i = 0; i < roots.length; i++) if (roots[i].isConnected) scanIframes(roots[i].parentNode || roots[i]);
  }
  function queueScan() {
    if (scanQueued) return;
    scanQueued = true;
    // 重いページでは走査間隔を自動的に広げる（体感速度を落とさない）
    var wait = Math.max(0, Math.max(600, scanCost * 15) - (Date.now() - lastScan));
    setTimeout(function () { (window.requestIdleCallback || setTimeout)(scan, { timeout: 800 }); }, wait);
  }

  // ブロックされた iframe（プロキシがメッセージを送る）と読み込みに失敗した広告画像を畳む
  window.addEventListener('message', function (e) {
    if (!e.data || e.data.shoji !== 'collapse') return;
    var frames = document.getElementsByTagName('iframe');
    for (var i = 0; i < frames.length; i++) {
      if (frames[i].contentWindow === e.source) { hideEl(frames[i]); hiddenSet.add(frames[i]); collapseUp(frames[i]); break; }
    }
  });
  if (F.collapse_space) {
    document.addEventListener('error', function (e) {
      var t = e.target;
      if (!t || !/^(IMG|IFRAME|EMBED|OBJECT)$/.test(t.tagName)) return;
      var src = t.currentSrc || t.src || '';
      if (src && !sameSite(src)) { hideEl(t); collapseUp(t); }
    }, true);
  }

  /* ---------------- AMP リンク・追跡パラメーター・ping ---------------- */
  var TRACK = /^(utm_[a-z_]+|fbclid|gclid|gclsrc|dclid|gbraid|wbraid|msclkid|yclid|ysclid|twclid|ttclid|igshid|igsh|mc_cid|mc_eid|_ga|_gl|_hsenc|_hsmi|mkt_tok|srsltid|li_fat_id|pk_[a-z_]+|mtm_[a-z_]+|hsa_[a-z_]+|ldtag_cl|spm|scm)$/i;
  var isGoogle = /(^|\.)google\.[a-z.]+$/.test(HOST);
  var linkRoots = [], linkQueued = false;
  function queueLinks() {
    if (linkQueued) return;
    linkQueued = true;
    setTimeout(function () {
      linkQueued = false;
      var roots = linkRoots; linkRoots = [];
      for (var i = 0; i < roots.length; i++) if (roots[i].isConnected) cleanLinks(roots[i]);
    }, 300);
  }
  function cleanLinks(root) {
    var links = root.querySelectorAll ? Array.prototype.slice.call(root.querySelectorAll('a[href]')) : [];
    if (root.tagName === 'A' && root.href) links.push(root);
    for (var i = 0; i < links.length; i++) {
      var a = links[i];
      if (a.__kk) continue;
      a.__kk = true;
      if (S.enabled && a.hasAttribute('ping')) a.removeAttribute('ping');
      if (F.disable_amp) {
        if (a.hasAttribute('data-amp') || a.hasAttribute('data-amp-cur')) {
          var cur = a.getAttribute('data-amp-cur') || a.getAttribute('data-cur');
          ['data-amp', 'data-amp-cur', 'data-amp-title', 'data-amp-vgi'].forEach(function (x) { a.removeAttribute(x); });
          if (cur) a.href = cur;
          report('amp', 1, a.href.slice(0, 100));
        }
        var m = /^https?:\/\/(?:www\.)?google\.[a-z.]+\/amp\/(?:s\/)?(.+)$/.exec(a.href);
        if (m) { a.href = (m[1].indexOf('http') === 0 ? '' : 'https://') + decodeURIComponent(m[1]); report('amp', 1); }
      }
      if (S.enabled && S.strip_tracking_params && a.href.indexOf('?') > 0) {
        try {
          var u = new URL(a.href), changed = false;
          if (isGoogle && u.pathname === '/url' && (u.searchParams.get('q') || u.searchParams.get('url'))) {
            var dest = u.searchParams.get('q') || u.searchParams.get('url');
            if (/^https?:/.test(dest)) { a.href = dest; u = new URL(dest); changed = true; }
          }
          var keys = []; u.searchParams.forEach(function (v, k) { if (TRACK.test(k)) keys.push(k); });
          keys.forEach(function (k) { u.searchParams.delete(k); });
          if (keys.length || changed) { a.href = u.toString(); if (keys.length) report('stealth_param', keys.length); }
        } catch (e) {}
      }
    }
    if (isGoogle && S.enabled) {
      var tracked = root.querySelectorAll ? root.querySelectorAll('a[onmousedown], a[jsaction*="mousedown"], a[data-jsarwt]') : [];
      for (var j = 0; j < tracked.length; j++) { tracked[j].removeAttribute('onmousedown'); tracked[j].removeAttribute('data-jsarwt'); }
    }
  }

  /* ---------------- 起動 ---------------- */
  function onMutations(muts) {
    var added = false;
    for (var i = 0; i < muts.length; i++) {
      var m = muts[i];
      if (m.addedNodes && m.addedNodes.length) {
        added = true;
        for (var j = 0; j < m.addedNodes.length; j++) {
          var n = m.addedNodes[j];
          if (n.nodeType === 1) { linkRoots.push(n); if (pendingRoots.length < 2000) pendingRoots.push(n); }
        }
      } else if (m.type === 'attributes' && hiddenSet.has(m.target) && m.target.isConnected && isVisible(m.target)) {
        // CSS で隠した広告を style/class の書き換えで再表示させる手口
        m.target.remove(); if (F.anti_reinsertion) report('reinserted', 1, 'restyle');
      } else if (m.type === 'attributes' && m.target.getAttribute && m.target.getAttribute('data-shoji') === 'hidden') {
        // 隠した要素の style を書き換えて再表示させる手口
        if (isVisible(m.target)) { hideEl(m.target); if (F.anti_reinsertion) report('reinserted', 1, 'style'); }
      }
    }
    if (added) { queueScan(); queueLinks(); }
  }
  function start() {
    scan();
    cleanLinks(document);
    var mo = new MutationObserver(onMutations);
    mo.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class', 'hidden'] });
    window.addEventListener('load', function () { setTimeout(scan, 300); setTimeout(scan, 2500); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})(window.__SHOJI_CFG__);
