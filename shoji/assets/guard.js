/* SPDX-License-Identifier: Apache-2.0 | Copyright 2026 The Shoji Authors */
/* Shoji 詐欺ページ対策
 * 1. ブラウザロッカー / サポート詐欺
 *    「ウイルスに感染しました。今すぐお電話ください」と表示し、警告ダイアログの連発・全画面表示・
 *    キーボードの乗っ取り・「戻る」の無効化などで画面を固めるページを検出し、その動きを止めて警告を出す。
 *    誤検出を避けるため、詐欺に特有の「文言」と「画面を固める動き」の両方がそろったときだけ反応する。
 * 2. ClickFix（偽の「ロボットではありません」確認など）
 *    ページが危険なコマンド（powershell・mshta など）をクリップボードに書き込み、
 *    「Win+R を押して貼り付けてください」と実行させる手口。ページ自身による書き込みだけを見て、
 *    コマンドがページに表示されていない（隠されている）か、誘い文句があるときだけ止める。
 *    止めたときは、貼り付けても何も起きない注意書きをクリップボードに入れる。
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
      report: 'サポート詐欺の疑い（画面を固める動きを停止）',
      cf_title: '危険なコマンドのコピーを止めました',
      cf_body: 'このページは、パソコンで実行すると危険なコマンドを、こっそりクリップボードにコピーしようとしていました。「ロボットではないことの確認」などと称して、Windows キー＋R を押して貼り付けさせる詐欺の手口です。',
      cf_warn: 'ページの指示に従って、ファイル名を指定して実行・ターミナル・PowerShell に貼り付けないでください。',
      cf_close: 'このページを閉じる', cf_stay: '閉じて表示を続ける',
      cf_clip: 'Shoji: 危険なコマンドのため、コピーを止めました。この文字は実行しないでください。',
      cf_report: 'ClickFix の疑い（危険なコマンドのコピーを停止）' },
    en: { title: 'This page looks like a tech-support scam',
      body: 'It showed fake warnings such as "your computer is infected" while trying to lock your screen with endless dialogs and full screen. Shoji has stopped that.',
      phone: 'Do not call any phone number shown on the page. Your PC is fine — just close this page.',
      close: 'Close this page', stay: 'Dismiss and keep viewing', footer: 'Shoji — scam page protection',
      report: 'Suspected tech-support scam (screen locking stopped)',
      cf_title: 'A dangerous command was not copied',
      cf_body: 'This page tried to secretly copy a command to your clipboard that would be dangerous to run on your PC. Pages that pretend to "verify you are human" and ask you to press Windows + R and paste are a common scam.',
      cf_warn: 'Do not paste anything from this page into the Run box, a terminal or PowerShell.',
      cf_close: 'Close this page', cf_stay: 'Dismiss and keep viewing',
      cf_clip: 'Shoji: a dangerous command was not copied. Do not run this text.',
      cf_report: 'Suspected ClickFix (dangerous command not copied)' }
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
  function report(what) {
    try {
      var body = JSON.stringify({ host: location.hostname, counts: { security: 1, _d: ['security:' + (what || T.report)] } });
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
  function showWarning(kind) {
    if (shown || !document.documentElement) return;
    shown = true;
    var cf = kind === 'clickfix';
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
    c.appendChild(el('h1', {}, cf ? T.cf_title : T.title));
    c.appendChild(el('p', {}, cf ? T.cf_body : T.body));
    c.appendChild(el('p', { 'class': 's' }, cf ? T.cf_warn : T.phone));
    var row = el('div', { 'class': 'b' });
    var close = el('button', { 'class': 'p' }, cf ? T.cf_close : T.close);
    var stay = el('button', {}, cf ? T.cf_stay : T.stay);
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

  /* ---------- ClickFix ---------- */
  // 実行すると危険なコマンドの特徴（Windows の実行ダイアログ・ターミナル・macOS のターミナル）
  var DANGER = [
    /\b(powershell|pwsh)(\.exe)?\b/i, /\bmshta(\.exe)?\b/i, /\bcmd(\.exe)?\b[^\n]{0,40}\/[ckr]\b/i,
    /\b(rundll32|regsvr32|certutil|bitsadmin|wscript|cscript|msiexec|conhost|forfiles|finger)(\.exe)?\s+\S/i,
    /\b(iex|invoke-expression|iwr|irm|invoke-webrequest|invoke-restmethod|start-process|downloadstring|downloadfile|frombase64string)\b/i,
    /\b(curl|wget)\b[^\n|]*\|\s*(sh|bash|zsh)\b/i, /\bosascript\b|\bbase64\s+(-d|--decode)\b[^\n]*\|/i
  ];
  // 誘い文句（「Win+R を押して」「ロボットではありません」など）
  var LURE = /(win(dows)?\s*(key)?\s*\+\s*r|⊞\s*\+\s*r|ctrl\s*\+\s*v|run dialog|verify you are (a )?human|i am not a robot|i'm not a robot|captcha|verification (step|id)|cloudflare|ファイル名を指定して実行|ロボットではありません|人間であることを確認|認証(手順|ステップ)|貼り付け(て|る))/i;
  function looksDangerous(text) {
    if (typeof text !== 'string' || text.length < 6 || text.length > 20000) return false;
    for (var i = 0; i < DANGER.length; i++) if (DANGER[i].test(text)) return true;
    return false;
  }
  function visibleOnPage(text) {
    try {
      var pageText = document.body ? document.body.innerText : '';
      var t = text.replace(/\s+/g, ' ').trim().slice(0, 200);
      return t.length > 0 && pageText.replace(/\s+/g, ' ').indexOf(t) >= 0;
    } catch (e) { return false; }
  }
  function isClickFix(text) {
    if (!looksDangerous(text)) return false;
    var page = '';
    try { page = (document.title || '') + ' ' + (document.body ? document.body.innerText : '').slice(0, 20000); } catch (e) {}
    return !visibleOnPage(text) || LURE.test(page) || LURE.test(text);
  }
  var cfDone = false;
  function stopClickFix() {
    if (!cfDone) { cfDone = true; report(T.cf_report); }
    showWarning('clickfix');
  }
  var clip = navigator.clipboard;
  var origWrite = clip && clip.writeText && clip.writeText.bind(clip);
  function safeText() { return origWrite ? origWrite(T.cf_clip).catch(function () {}) : Promise.resolve(); }
  if (clip && clip.writeText) {
    wrap(clip, 'writeText', function (args) {
      if (isClickFix(args[0])) { stopClickFix(); return { skip: true, value: safeText() }; }
    });
  }
  if (clip && clip.write && window.ClipboardItem) {
    var origClipWrite = clip.write.bind(clip);
    try {
      clip.write = function (items) {
        var item = items && items[0];
        if (!item || !item.types || item.types.indexOf('text/plain') < 0) return origClipWrite(items);
        return Promise.resolve(item.getType('text/plain')).then(function (blob) { return blob.text(); }).then(function (text) {
          if (isClickFix(text)) { stopClickFix(); return safeText(); }
          return origClipWrite(items);
        });
      };
    } catch (e) {}
  }
  // コピーのイベントの中でページが書き込む内容（clipboardData.setData）
  if (window.DataTransfer) {
    wrap(DataTransfer.prototype, 'setData', function (args) {
      if (/^text(\/plain)?$/i.test(String(args[0])) && isClickFix(args[1])) {
        stopClickFix();
        args[1] = T.cf_clip;   // 危険なコマンドの代わりに、注意書きを書き込ませる
      }
    });
  }
  // 隠した入力欄を選択して document.execCommand('copy') でコピーする方法
  wrap(document, 'execCommand', function (args) {
    if (String(args[0]).toLowerCase() !== 'copy') return;
    var text = '';
    try {
      var a = document.activeElement;
      if (a && typeof a.value === 'string' && typeof a.selectionStart === 'number') text = a.value.slice(a.selectionStart, a.selectionEnd);
      if (!text) text = String(window.getSelection ? window.getSelection() : '');
    } catch (e) {}
    if (isClickFix(text)) {
      stopClickFix();
      safeText();
      return { skip: true, value: false };
    }
  });

  // ページの文言が出そろってから一度だけ確認（動きが無ければ何もしない）
  window.addEventListener('load', function () { setTimeout(evaluate, 1500); });
})(window.__SHOJI_CFG__);
