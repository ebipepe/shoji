/* SPDX-License-Identifier: Apache-2.0 | Copyright 2026 The Shoji Authors */
/* Shoji 詐欺ページ対策（ブラウザロッカー / サポート詐欺）
 * 「ウイルスに感染しました。今すぐお電話ください」と表示し、警告ダイアログの連発・全画面表示・
 * キーボードの乗っ取り・「戻る」の無効化などで画面を固めるページを検出し、その動きを止めて警告を出す。
 * 誤検出を避けるため、詐欺に特有の「文言」と「画面を固める動き」の両方がそろったときだけ反応する。
 */
(function (CFG) {
  'use strict';
  if (!CFG || !CFG.f || CFG.f.block_malware === false || window.__shojiGuard) return;
  window.__shojiGuard = true;

  var MAGIC = CFG.magic;
  var TEXT = {
    ja: { title: 'サポート詐欺の可能性があるページです',
      body: 'このページは「ウイルスに感染した」などの警告を出しながら、ダイアログの連発や全画面表示で画面を固めようとしていました。Shoji がその動きを止めました。',
      phone: '表示されている電話番号には絶対に電話しないでください。お使いの PC は、このページを閉じれば元どおり使えます。',
      close: 'このページを閉じる', stay: '警告を消して表示を続ける', footer: 'Shoji — 詐欺ページ対策',
      report: 'サポート詐欺の疑い（画面を固める動きを停止）' },
    en: { title: 'This page looks like a tech-support scam',
      body: 'It showed fake warnings such as "your computer is infected" while trying to lock your screen with endless dialogs and full screen. Shoji has stopped that.',
      phone: 'Do not call any phone number shown on the page. Your PC is fine — just close this page.',
      close: 'Close this page', stay: 'Dismiss and keep viewing', footer: 'Shoji — scam page protection',
      report: 'Suspected tech-support scam (screen locking stopped)' }
  };
  var T = TEXT[CFG.lang] || TEXT.en;
  var isTop = window === window.top;
  var tripped = false, shown = false;
  var b = { dialogs: [], fullscreen: 0, keylock: 0, pointerlock: 0, history: [], unload: 0 };

  function now() { return Date.now(); }
  function recent(list, ms) { var t = now(); while (list.length && t - list[0] > ms) list.shift(); return list.length; }

  /* ---------- 文言の判定 ---------- */
  var PHRASES = [
    /ウイルス|ウィルス|マルウェア|トロイの木馬|スパイウェア/, /感染|ハッキング|不正アクセス|個人情報.{0,6}(流出|盗|危険)/,
    /Microsoft|マイクロソフト|Windows ?(Defender|セキュリティ|サポート)|Apple ?サポート/i,
    /(サポート|テクニカル|ヘルプ).{0,4}(センター|窓口|デスク)|(お|ご)電話ください|すぐに電話|電話番号/,
    /(コンピューター|パソコン|PC|ブラウザ).{0,8}(ロック|ブロック|停止|削除)/,
    /virus|malware|trojan|spyware|infected|hacked|pornographic spyware/i,
    /(call|contact).{0,20}(support|technician|microsoft|helpline|toll.?free)/i,
    /(computer|pc|browser|device).{0,20}(locked|blocked|disabled|compromised)/i,
    /do not (close|restart|shut ?down)|閉じないで|再起動しないで|電源を切らないで/i
  ];
  var PHONE = /0120[-\s‐－]?\d{2,3}[-\s‐－]?\d{3,4}|050[-\s‐－]?\d{4}[-\s‐－]?\d{4}|0800[-\s‐－]?\d{3}[-\s‐－]?\d{4}|\+?1?[\s(.-]*8(00|33|44|55|66|77|88)[\s).-]*\d{3}[\s.-]?\d{4}/;
  function textScore() {
    var t = '';
    try { t = ((document.title || '') + ' ' + (document.body ? document.body.innerText : '')).slice(0, 30000); } catch (e) {}
    var hits = 0;
    for (var i = 0; i < PHRASES.length; i++) if (PHRASES[i].test(t)) hits++;
    return { phrases: hits, phone: PHONE.test(t) };
  }
  function behaviorScore() {
    var s = 0;
    if (recent(b.dialogs, 30000) >= 3) s += 2;
    if (b.fullscreen) s += 1;
    if (b.keylock) s += 2;
    if (b.pointerlock) s += 1;
    if (recent(b.history, 5000) >= 20) s += 2;
    if (b.unload) s += 1;
    return s;
  }
  function evaluate() {
    if (tripped) return;
    var bs = behaviorScore();
    if (!bs) return;
    var ts = textScore();
    var scam = (ts.phrases >= 2 && (ts.phone || ts.phrases >= 3) && bs >= 2) || bs >= 5;
    if (scam) trip(ts, bs);
  }

  /* ---------- 画面を固める動きの記録 ---------- */
  function wrap(owner, name, before) {
    var orig = owner && owner[name];
    if (typeof orig !== 'function') return;
    try {
      owner[name] = new Proxy(orig, {
        apply: function (target, self, args) {
          var r = before(args);
          if (r && r.skip) return r.value;
          return Reflect.apply(target, self, args);
        }
      });
    } catch (e) {}
  }
  ['alert', 'confirm', 'prompt'].forEach(function (name) {
    wrap(window, name, function () {
      b.dialogs.push(now());
      // 30 秒に 5 回以上の警告ダイアログは、どんなページでも止める
      if (tripped || recent(b.dialogs, 30000) > 5) return { skip: true, value: name === 'confirm' ? false : (name === 'prompt' ? null : undefined) };
      setTimeout(evaluate, 0);
    });
  });
  if (window.Element) {
    ['requestFullscreen', 'webkitRequestFullscreen', 'requestPointerLock'].forEach(function (name) {
      wrap(Element.prototype, name, function () {
        if (name === 'requestPointerLock') b.pointerlock++; else b.fullscreen++;
        setTimeout(evaluate, 0);
        if (tripped) return { skip: true, value: Promise.resolve() };
      });
    });
  }
  if (navigator.keyboard && navigator.keyboard.lock) {
    wrap(navigator.keyboard, 'lock', function () {
      b.keylock++; setTimeout(evaluate, 0);
      if (tripped) return { skip: true, value: Promise.resolve() };
    });
  }
  ['pushState', 'replaceState'].forEach(function (name) {
    wrap(history, name, function () {
      b.history.push(now());
      if (b.history.length > 200) b.history.splice(0, 100);
      if (b.history.length % 10 === 0) setTimeout(evaluate, 0);
      if (tripped) return { skip: true, value: undefined };
    });
  });
  wrap(EventTarget.prototype, 'addEventListener', function (args) {
    if (args[0] === 'beforeunload') {
      b.unload++;
      if (tripped) return { skip: true, value: undefined };
    }
  });

  /* ---------- 検出したとき ---------- */
  function neutralize() {
    try { if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen(); } catch (e) {}
    try { if (document.exitPointerLock) document.exitPointerLock(); } catch (e) {}
    try { if (navigator.keyboard && navigator.keyboard.unlock) navigator.keyboard.unlock(); } catch (e) {}
    try { window.onbeforeunload = null; } catch (e) {}
    try {
      document.querySelectorAll('audio,video').forEach(function (m) { try { m.muted = true; m.pause(); } catch (e) {} });
    } catch (e) {}
  }
  function report() {
    try {
      var body = JSON.stringify({ host: location.hostname, counts: { security: 1, _d: ['security:' + T.report] } });
      if (!navigator.sendBeacon || !navigator.sendBeacon(MAGIC + '/report', body)) fetch(MAGIC + '/report', { method: 'POST', body: body, mode: 'no-cors' });
    } catch (e) {}
  }
  function trip() {
    tripped = true;
    neutralize();
    setInterval(neutralize, 1000);
    report();
    if (isTop) showWarning();
  }
  function el(tag, attrs, text) {
    var e = document.createElement(tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (text) e.textContent = text;
    return e;
  }
  function showWarning() {
    if (shown || !document.documentElement) return;
    shown = true;
    var host = document.createElement('shoji-guard');
    var root = host.attachShadow({ mode: 'closed' });
    try {
      var sh = new CSSStyleSheet();
      sh.replaceSync(':host{all:initial}.o{position:fixed;inset:0;z-index:2147483647;background:rgba(10,10,10,.82);display:grid;place-items:center;'
        + 'font:15px/1.7 system-ui,"Segoe UI","Yu Gothic UI","Hiragino Sans",sans-serif}'
        + '.c{background:#fff;color:#1b1b1a;max-width:560px;margin:16px;border-radius:14px;border-top:5px solid #c43c3b;padding:26px 30px;box-shadow:0 12px 48px rgba(0,0,0,.4)}'
        + 'h1{font-size:20px;margin:0 0 10px}p{margin:8px 0;color:#444}.s{font-weight:700;color:#1b1b1a}'
        + '.b{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}button{font:inherit;padding:8px 16px;border-radius:8px;border:1px solid #ccc;background:#fff;cursor:pointer}'
        + 'button.p{background:#c43c3b;border-color:#c43c3b;color:#fff}.f{font-size:12px;color:#888;margin-top:14px}');
      root.adoptedStyleSheets = [sh];
    } catch (e) {}
    var o = el('div', { 'class': 'o' }), c = el('div', { 'class': 'c' });
    c.appendChild(el('h1', {}, T.title));
    c.appendChild(el('p', {}, T.body));
    c.appendChild(el('p', { 'class': 's' }, T.phone));
    var row = el('div', { 'class': 'b' });
    var close = el('button', { 'class': 'p' }, T.close);
    var stay = el('button', {}, T.stay);
    row.appendChild(close); row.appendChild(stay); c.appendChild(row);
    c.appendChild(el('p', { 'class': 'f' }, T.footer));
    o.appendChild(c); root.appendChild(o);
    close.onclick = function () {
      try { window.close(); } catch (e) {}
      setTimeout(function () { location.replace('about:blank'); }, 150);
    };
    stay.onclick = function () { host.remove(); };
    document.documentElement.appendChild(host);
  }

  // ページの文言が出そろってから一度だけ確認（動きが無ければ何もしない）
  window.addEventListener('load', function () { setTimeout(evaluate, 1500); });
})(window.__SHOJI_CFG__);
