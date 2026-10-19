/* SPDX-License-Identifier: Apache-2.0 | Copyright 2026 The Shoji Authors */
/* Shoji 要素の選択ブロック
 * Alt+Shift+H で起動し、隠したい部分をクリックすると「このサイトだけで隠す」ルールを作って保存する。
 * 画面の部品は閉じた Shadow DOM に入れ、ページの CSS の影響を受けないようにする。
 */
(function (OPT) {
  'use strict';
  var MAGIC = OPT.magic;
  var TEXT = {
    ja: { title: 'Shoji: 隠す部分を選ぶ', click: '隠したい部分をクリックしてください（Esc で終了）', ph: 'クリックするとここにセレクタが入ります',
      up: '広げる', upTip: 'ひとつ外側の要素を選ぶ', down: '狭める', downTip: 'ひとつ内側に戻す', pick: '選び直す',
      cancel: 'キャンセル', save: 'このサイトで隠す', badSel: 'セレクタが正しくありません', count: '{n} 個の要素',
      chosen: 'この範囲を隠します。広すぎる・狭すぎるときは「広げる」「狭める」かセレクタを直接編集できます。',
      none: '一致する要素がありません。セレクタを確認してください。', failed: '保存できませんでした: ',
      saved: '保存しました（{rule}）。ダッシュボードの「ユーザールール」で取り消せます。', exists: '同じルールが既にあります。',
      offline: 'Shoji に接続できませんでした。' },
    en: { title: 'Shoji: choose what to hide', click: 'Click the part you want to hide (Esc to quit)', ph: 'The selector appears here after you click',
      up: 'Wider', upTip: 'Select the enclosing element', down: 'Narrower', downTip: 'Go back one level in', pick: 'Pick again',
      cancel: 'Cancel', save: 'Hide on this site', badSel: 'Invalid selector', count: '{n} element(s)',
      chosen: 'This area will be hidden. Use Wider / Narrower or edit the selector if it is too big or too small.',
      none: 'Nothing matches. Check the selector.', failed: 'Could not save: ',
      saved: 'Saved ({rule}). You can undo it under "User rules" in the dashboard.', exists: 'That rule already exists.',
      offline: 'Could not reach Shoji.' }
  };
  var T = TEXT[OPT.lang] || TEXT.en;
  function tr(k, v) { return T[k].replace(/\{(\w+)\}/g, function (m, x) { return v && v[x] !== undefined ? v[x] : m; }); }
  if (window !== window.top || window.__shojiPicker) return;
  window.__shojiPicker = true;

  var SITE = location.hostname.replace(/^www\./, '');
  var host = null, root = null, box = null, panel = null;
  var current = null, chosen = null, history = [], previewStyle = null;

  /* ---------- セレクタの生成 ---------- */
  function goodId(id) { return id && id.length <= 60 && !/\d{4,}/.test(id) && !/^[0-9]/.test(id) && !/^(shoji|ember|react-|__next)/.test(id); }
  function goodClass(c) {
    return c.length >= 2 && c.length <= 40 && !/\d{4,}/.test(c) && !/^(css|sc|jsx|svelte|emotion|tw)-/i.test(c)
      && !/^[a-z]{1,3}[A-Z0-9][A-Za-z0-9]{4,}$/.test(c) && !/^shoji/.test(c) && !/(hover|active|focus|open|show|visible|selected)$/i.test(c);
  }
  function part(el, nth) {
    var s = el.tagName.toLowerCase();
    if (goodId(el.id)) return { s: '#' + CSS.escape(el.id), unique: true };
    var cls = Array.prototype.filter.call(el.classList, goodClass).slice(0, 3);
    if (cls.length) s += cls.map(function (c) { return '.' + CSS.escape(c); }).join('');
    if (nth && el.parentElement) {
      var same = Array.prototype.filter.call(el.parentElement.children, function (x) { return x.tagName === el.tagName; });
      if (same.length > 1) s += ':nth-of-type(' + (same.indexOf(el) + 1) + ')';
    }
    return { s: s, unique: false };
  }
  function uniqueFor(sel, el) {
    try { var m = document.querySelectorAll(sel); return m.length === 1 && m[0] === el; } catch (e) { return false; }
  }
  function selectorFor(el) {
    var rounds = [false, true];
    for (var r = 0; r < rounds.length; r++) {
      var parts = [], cur = el;
      while (cur && cur.nodeType === 1 && cur !== document.documentElement && cur !== document.body) {
        var p = part(cur, rounds[r]);
        parts.unshift(p.s);
        var sel = parts.join(' > ');
        // タグ名だけのセレクタ（span 等）はページが変わると別の要素に当たりやすいので、クラスか ID を含むまで外側へ広げる
        if (uniqueFor(sel, el) && /[.#]/.test(sel)) return sel;
        if (p.unique || parts.length >= 6) break;
        cur = cur.parentElement;
      }
    }
    return part(el, true).s;
  }
  function count(sel) { try { return document.querySelectorAll(sel).length; } catch (e) { return -1; } }

  /* ---------- 画面の部品 ---------- */
  var CSS_TEXT = [
    ':host{all:initial}',
    '.box{position:fixed;pointer-events:none;z-index:2147483646;border:2px solid #e8590c;background:rgba(232,89,12,.15);border-radius:3px;transition:all .05s}',
    '.box.multi{border-style:dashed}',
    '.panel{position:fixed;right:16px;bottom:16px;z-index:2147483647;width:min(460px,calc(100vw - 32px));font:13px/1.5 system-ui,"Segoe UI","Yu Gothic UI","Hiragino Sans",sans-serif;',
    'color:#1b1b1a;background:#fcfcfb;border:1px solid #d9d8d3;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,.25);padding:12px 14px}',
    '@media (prefers-color-scheme:dark){.panel{color:#f0efec;background:#1d1d1b;border-color:#3a3a37}.sel{background:#262624!important;color:#f0efec!important;border-color:#3a3a37!important}.btn{background:#262624!important;color:#f0efec!important;border-color:#3a3a37!important}}',
    '.t{font-weight:700;margin:0 0 4px}.m{color:#7a7974;font-size:12px;margin:0 0 8px}',
    '.sel{width:100%;box-sizing:border-box;font:12px ui-monospace,Consolas,monospace;padding:6px 8px;border:1px solid #d9d8d3;border-radius:7px;background:#fff;color:#111}',
    '.row{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;align-items:center}',
    '.btn{font:inherit;font-size:12.5px;padding:5px 11px;border-radius:7px;border:1px solid #d9d8d3;background:#fff;color:#111;cursor:pointer}',
    '.btn.pri{background:#2a78d6!important;border-color:#2a78d6!important;color:#fff!important}',
    '.sp{flex:1}.n{font-size:12px;color:#7a7974}'
  ].join('');

  function el(tag, attrs, text) {
    var e = document.createElement(tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (text) e.textContent = text;
    return e;
  }
  // CSP（style-src）の制限を受けないよう、<style> ではなく CSSOM のスタイルシートを使う
  function sheet(css) {
    try { var sh = new CSSStyleSheet(); sh.replaceSync(css); return sh; } catch (e) { return null; }
  }
  function adopt(target, sh) {
    if (sh) try { target.adoptedStyleSheets = Array.prototype.concat.call([], target.adoptedStyleSheets || [], [sh]); } catch (e) {}
  }
  function build() {
    host = document.createElement('shoji-picker');
    root = host.attachShadow({ mode: 'closed' });
    adopt(root, sheet(CSS_TEXT));
    box = el('div', { 'class': 'box' }); root.appendChild(box);
    panel = el('div', { 'class': 'panel' });
    panel.appendChild(el('p', { 'class': 't' }, T.title));
    panel.appendChild(el('p', { 'class': 'm', 'data-k': 'msg' }, T.click));
    panel.appendChild(el('input', { 'class': 'sel', 'data-k': 'sel', spellcheck: 'false', placeholder: T.ph }));
    var row = el('div', { 'class': 'row' });
    row.appendChild(el('button', { 'class': 'btn', 'data-k': 'up', title: T.upTip }, T.up));
    row.appendChild(el('button', { 'class': 'btn', 'data-k': 'down', title: T.downTip }, T.down));
    row.appendChild(el('button', { 'class': 'btn', 'data-k': 'pick', title: T.pick }, T.pick));
    row.appendChild(el('span', { 'class': 'n', 'data-k': 'n' }));
    panel.appendChild(row);
    var row2 = el('div', { 'class': 'row' });
    row2.appendChild(el('span', { 'class': 'sp' }));
    row2.appendChild(el('button', { 'class': 'btn', 'data-k': 'cancel' }, T.cancel));
    row2.appendChild(el('button', { 'class': 'btn pri', 'data-k': 'save' }, T.save));
    panel.appendChild(row2);
    root.appendChild(panel);
    (document.documentElement || document.body).appendChild(host);
    q('up').onclick = function () { if (chosen && chosen.parentElement && chosen.parentElement !== document.body) { history.push(chosen); choose(chosen.parentElement); } };
    q('down').onclick = function () { if (history.length) choose(history.pop()); };
    q('pick').onclick = function () { chosen = null; history = []; setPreview(''); q('sel').value = ''; q('n').textContent = ''; msg(T.click); picking = true; };
    q('cancel').onclick = stop;
    q('save').onclick = save;
    q('sel').oninput = function () { setPreview(q('sel').value.trim()); updateCount(); };
  }
  function q(k) { return root.querySelector('[data-k="' + k + '"]'); }
  function msg(t) { q('msg').textContent = t; }
  function updateCount() {
    var n = count(q('sel').value.trim());
    q('n').textContent = n < 0 ? T.badSel : (n ? tr('count', { n: n }) : '');
  }
  function place(el) {
    if (!el) { box.style.display = 'none'; return; }
    var r = el.getBoundingClientRect();
    box.style.display = 'block';
    box.style.left = r.left + 'px'; box.style.top = r.top + 'px';
    box.style.width = r.width + 'px'; box.style.height = r.height + 'px';
  }
  // 選んだセレクタに一致する要素を半透明にして、隠れる範囲を見せる
  function setPreview(sel) {
    if (!previewStyle) { previewStyle = sheet(''); adopt(document, previewStyle); }
    if (!previewStyle) return;
    var css = '';
    if (sel && count(sel) > 0) css = sel + '{outline:2px dashed #e8590c!important;opacity:.35!important}';
    try { previewStyle.replaceSync(css); } catch (e) {}
  }

  /* ---------- 操作 ---------- */
  var picking = false;
  function isOurs(el) { return el === host; }
  function onMove(e) {
    if (!picking) return;
    var el = document.elementFromPoint(e.clientX, e.clientY);
    if (!el || isOurs(el)) return;
    current = el; place(el);
  }
  function choose(el) {
    chosen = el; place(el);
    var sel = selectorFor(el);
    q('sel').value = sel; setPreview(sel); updateCount();
    msg(T.chosen);
  }
  function onClick(e) {
    if (!host || isOurs(e.target) || e.composedPath().indexOf(host) >= 0) return;
    e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
    if (!picking) return;
    picking = false; history = [];
    choose(current || e.target);
  }
  function swallow(e) {
    if (!host || e.composedPath().indexOf(host) >= 0) return;
    e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
  }
  function onKey(e) { if (e.key === 'Escape') { e.preventDefault(); stop(); } }
  function onScroll() { if (chosen) place(chosen); }

  function start() {
    if (host) return;
    build(); picking = true;
    document.addEventListener('mousemove', onMove, true);
    document.addEventListener('click', onClick, true);
    ['mousedown', 'mouseup', 'pointerdown', 'pointerup', 'auxclick', 'dblclick', 'contextmenu'].forEach(function (t) { document.addEventListener(t, swallow, true); });
    document.addEventListener('keydown', onKey, true);
    window.addEventListener('scroll', onScroll, true);
  }
  function stop() {
    if (!host) return;
    document.removeEventListener('mousemove', onMove, true);
    document.removeEventListener('click', onClick, true);
    ['mousedown', 'mouseup', 'pointerdown', 'pointerup', 'auxclick', 'dblclick', 'contextmenu'].forEach(function (t) { document.removeEventListener(t, swallow, true); });
    document.removeEventListener('keydown', onKey, true);
    window.removeEventListener('scroll', onScroll, true);
    setPreview('');
    host.remove(); host = root = box = panel = null; current = chosen = null; picking = false;
  }
  function save() {
    var sel = q('sel').value.trim();
    if (!sel || count(sel) < 1) { msg(T.none); return; }
    var rule = SITE + '##' + sel;
    q('save').disabled = true;
    fetch(MAGIC + '/user-rule', { method: 'POST', mode: 'cors', body: JSON.stringify({ rule: rule }), headers: { 'Content-Type': 'text/plain' } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { msg(T.failed + (d.error || '')); q('save').disabled = false; return; }
        // 保存したルールをすぐにこのページにも適用する
        adopt(document, sheet(sel + '{display:none!important}'));
        setPreview(''); place(null);
        msg(d.added ? tr('saved', { rule: rule }) : T.exists);
        setTimeout(stop, 1800);
      })
      .catch(function () { msg(T.offline); q('save').disabled = false; });
  }

  // Alt+Shift+H で起動 / 終了
  document.addEventListener('keydown', function (e) {
    if (e.altKey && e.shiftKey && !e.ctrlKey && !e.metaKey && (e.code === 'KeyH' || e.key === 'H' || e.key === 'h')) {
      e.preventDefault(); e.stopPropagation();
      if (host) stop(); else start();
    }
  }, true);
})(window.__SHOJI_MAGIC__);
