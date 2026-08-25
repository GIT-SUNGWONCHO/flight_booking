/* 공용 유틸. autoconfirm / hud / recorder 가 함께 쓴다. */
(function () {
  'use strict';
  var W = window;
  try { if (typeof unsafeWindow !== 'undefined' && unsafeWindow) W = unsafeWindow; } catch (e) {}
  if (W.KE_UTIL || window.KE_UTIL) return;

  function visible(el) {
    if (!el || el.nodeType !== 1 || !el.isConnected) return false;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
    var r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    var st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none') return false;
    if (parseFloat(st.opacity || '1') < 0.05) return false;
    return true;
  }

  /* 화면에 "보인다"(visible)와 "지금 누를 수 있다"(hittable)는 다르다.
   * 모달이 떠 있으면 그 뒤의 버튼도 getBoundingClientRect/opacity 상으로는 멀쩡히
   * 보이지만, 실제로 클릭하면 모달이 먹는다. 그 좌표에서 실제로 잡히는 요소가
   * 자기 자신(또는 조상/자손)인지로 판정한다.
   * 화면 밖이라 판정이 불가능하면 기본은 통과시킨다 - fireClick 이 스크롤해서 누른다.
   *
   * strict=true 는 "단계를 건너뛸지" 판단할 때 쓴다. 거기서는 판정 보류를 통과로
   * 처리하면 안 된다: 모달 안쪽 아래에 숨어 있어 화면 밖인 [확인] 버튼을 "누를 수
   * 있다" 고 오판해서, 아직 끝나지 않은 스크롤 단계를 건너뛰어 버렸다(실측).
   * 건너뛰기는 확실한 근거가 있을 때만 해야 한다. */
  function hittable(el, strict) {
    var r;
    try { r = el.getBoundingClientRect(); } catch (e) { return !strict; }
    var x = r.left + r.width / 2, y = r.top + r.height / 2;
    var W2 = window.innerWidth || 0, H2 = window.innerHeight || 0;
    if (x < 0 || y < 0 || x > W2 || y > H2) return !strict;   // 화면 밖
    var top;
    try { top = document.elementFromPoint(x, y); } catch (e) { return !strict; }
    if (!top) return !strict;
    return top === el || el.contains(top) || top.contains(el);
  }

  function label(el) {
    var t = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
    if (!t) t = el.value || el.getAttribute('aria-label') || el.title || '';
    return t.slice(0, 40);
  }

  /* 안정적인 CSS 경로. 자동 생성 클래스(ng-*, css-해시 등)와 상태 클래스는
   * 리렌더마다 바뀌므로 빼고, 구조(nth-of-type)에 기대는 쪽이 오래 간다. */
  var VOLATILE = /^(ng-|v-|is-|has-|css-|sc-|jsx-|active|selected|hover|focus|open|show|current|on)$/i;

  // 16자 이상 이어지는 16진수는 렌더/세션마다 새로 발급되는 컴포넌트 인스턴스 id일 확률이
  // 높다(예: ac0e9a2f7f9ead9dbd368853f47deb65CalendarFareBonusMain). 앵커로 쓰면 다음 로드 때
  // 100% 매칭 실패하므로 건너뛰고 더 위 조상의 안정적인 id 를 찾는다.
  function looksHashy(id) { return /[0-9a-f]{16,}/i.test(id); }
  function stableId(el) { return el.id && !/^\d/.test(el.id) && !looksHashy(el.id); }

  function cssPath(el) {
    if (!el || el.nodeType !== 1) return '';
    if (stableId(el)) {
      try { if (document.querySelectorAll('#' + CSS.escape(el.id)).length === 1) return '#' + CSS.escape(el.id); }
      catch (e) {}
    }
    var parts = [];
    while (el && el.nodeType === 1 && parts.length < 7) {
      if (stableId(el)) { parts.unshift('#' + CSS.escape(el.id)); break; }
      var s = el.tagName.toLowerCase();
      var cls = [];
      for (var i = 0; i < el.classList.length && cls.length < 2; i++) {
        if (!VOLATILE.test(el.classList[i])) cls.push(el.classList[i]);
      }
      if (cls.length) {
        try { s += '.' + cls.map(function (c) { return CSS.escape(c); }).join('.'); } catch (e) {}
      }
      var p = el.parentElement;
      if (p) {
        var same = [];
        for (var j = 0; j < p.children.length; j++) {
          if (p.children[j].tagName === el.tagName) same.push(p.children[j]);
        }
        if (same.length > 1) s += ':nth-of-type(' + (same.indexOf(el) + 1) + ')';
      }
      parts.unshift(s);
      el = p;
    }
    return parts.join(' > ');
  }

  // 대한항공 사이트는 <kds-button_1> 같은 커스텀 엘리먼트를 많이 쓰는데 button/role=button
  // 이 아닌 경우가 있어 원래 목록으로는 안 잡혔다. class 에 btn/button 이 들어간 것까지 넓힌다.
  var CLICKABLE = 'button, a, input[type="button"], input[type="submit"], input[type="checkbox"], ' +
                  '[role="button"], [role="tab"], [role="checkbox"], label, ' +
                  '.btn, .button, [class*="btn" i], [class*="button" i]';

  /** open shadow root 내부까지 훑는다 (일부 위젯이 웹컴포넌트). autoconfirm.js 와 동일 전략. */
  function candidates(root) {
    var out = [];
    try { out = Array.prototype.slice.call(root.querySelectorAll(CLICKABLE)); } catch (e) { return out; }
    try {
      root.querySelectorAll('*').forEach(function (n) {
        if (n.shadowRoot) out = out.concat(candidates(n.shadowRoot));
      });
    } catch (e) {}
    return out;
  }

  var PREFIX_LEN = 10;

  /* "검색"/"확인" 같은 흔한 라벨은 예매 화면 말고도 사이트 공통 헤더(전체 검색
   * 아이콘 등)에도 있을 수 있다. 그러면 엉뚱한 걸 눌러버리고도 클릭 자체는
   * 성공한 것처럼 보여서 화면이 안 넘어가는데 recorder 는 다음 단계로 넘어가버린다.
   * header/nav/banner 영역은 텍스트 폴백 후보에서 아예 제외한다. */
  function inChrome(el) {
    var n = el;
    for (var d = 0; d < 8 && n; d++) {
      var tag = n.tagName;
      if (tag === 'HEADER' || tag === 'NAV') return true;
      var role = n.getAttribute && n.getAttribute('role');
      if (role === 'banner' || role === 'navigation') return true;
      n = n.parentElement;
    }
    return false;
  }

  /** 셀렉터 우선, 없으면 라벨 텍스트로 폴백해서 화면에 보이는 요소를 찾는다.
   * 날짜 셀처럼 클릭 후에만 "선택됨" 같은 상태 문구가 뒤에 붙는 라벨은 정확히 일치가
   * 안 되므로, 정확 일치가 실패하면 앞부분(날짜/편명 등 실제 내용)이 같은 요소로
   * 한 번 더 찾는다. 너무 짧은 라벨(확인/동의 등)은 접두어만으로 오매칭 위험이 있어
   * 제외한다. */
  function findEl(sel, text, opts) {
    opts = opts || {};
    if (sel) {
      try {
        var list = document.querySelectorAll(sel);
        for (var i = 0; i < list.length; i++) if (visible(list[i])) return list[i];
      } catch (e) {}
    }
    if (text && !opts.selectorOnly) {
      var all = candidates(document);
      for (var k = 0; k < all.length; k++) {
        if (visible(all[k]) && !inChrome(all[k]) && label(all[k]) === text) return all[k];
      }
      if (text.length > PREFIX_LEN) {
        var prefix = text.slice(0, PREFIX_LEN);
        for (var j = 0; j < all.length; j++) {
          if (visible(all[j]) && !inChrome(all[j]) && label(all[j]).indexOf(prefix) === 0) return all[j];
        }
      }
    }
    return null;
  }

  /** 재생이 단계를 못 찾고 멈췄을 때 왜 못 찾았는지 - 셀렉터가 몇 개 매치됐는지,
   * 텍스트가 일치하는 후보가 있는지 - 를 요약한다. 스크린샷 한 장으로 원인 파악이
   * 되도록 패널 상태줄에 그대로 얹는 용도. */
  function diagnose(sel, text) {
    var out = { selMatches: 0, selVisible: 0, selError: null, textMatches: 0, textVisible: 0, prefixMatches: 0 };
    if (sel) {
      try {
        var list = document.querySelectorAll(sel);
        out.selMatches = list.length;
        for (var i = 0; i < list.length; i++) if (visible(list[i])) out.selVisible++;
      } catch (e) { out.selError = String(e.message || e).slice(0, 60); }
    }
    if (text) {
      var all = candidates(document);
      for (var k = 0; k < all.length; k++) {
        if (inChrome(all[k])) continue;
        if (label(all[k]) === text) {
          out.textMatches++;
          if (visible(all[k])) out.textVisible++;
        }
      }
      if (text.length > PREFIX_LEN) {
        var prefix = text.slice(0, PREFIX_LEN);
        for (var j = 0; j < all.length; j++) {
          if (visible(all[j]) && !inChrome(all[j]) && label(all[j]).indexOf(prefix) === 0) out.prefixMatches++;
        }
      }
    }
    return out;
  }

  function diagnoseText(sel, text) {
    var d = diagnose(sel, text);
    if (d.selError) return '셀렉터 오류: ' + d.selError;
    var parts = [];
    parts.push('셀렉터 매치 ' + d.selMatches + '개(보임 ' + d.selVisible + ')');
    if (d.prefixMatches) parts.push('접두어일치(보임) ' + d.prefixMatches + '개');
    parts.push('텍스트일치 ' + d.textMatches + '개(보임 ' + d.textVisible + ')');
    return parts.join(', ');
  }

  /* el.click() 은 'click' 이벤트 하나만 던진다. 최신 디자인시스템 커스텀 엘리먼트
   * (kds-button_1 류) 는 내부적으로 pointerdown/pointerup 이나 mousedown/mouseup 을
   * 듣고 반응하는 경우가 있어서, click 만 던지면 예외 없이 "성공"으로 보이지만 실제
   * 사이트는 아무 반응을 안 하는 사고가 난다(요소는 찾았는데 화면이 안 넘어감).
   * 실제 마우스 클릭과 같은 이벤트 시퀀스를 순서대로 던져서 이 클래스의 컴포넌트도
   * 커버한다. */
  /* 커스텀 엘리먼트(kds-button 계열)는 껍데기만 DOM 에 보이고, 실제 클릭 핸들러는
   * shadow root 안쪽 네이티브 <button> 에 붙어 있다. 이벤트는 위로만 올라가지 shadow
   * 안쪽으로 내려가지 않으므로, 껍데기에 클릭을 쏘면 예외도 안 나면서 아무 반응이
   * 없다(요소는 찾았는데 화면이 안 넘어가는 증상). 안쪽 진짜 버튼까지 파고든다.
   * 감싸기만 하는 래퍼(자식 하나)도 같이 통과한다. */
  function realTarget(el) {
    var best = el, n = el;
    for (var d = 0; n && d < 6; d++) {
      var next = null;
      if (n.shadowRoot) {
        try { next = n.shadowRoot.querySelector('button, a[href], input, [role="button"]'); } catch (e) {}
      }
      if (!next && n.children && n.children.length === 1) next = n.children[0];
      if (!next) break;
      n = next;
      if (/^(BUTTON|A|INPUT)$/.test(n.tagName)) best = n;
    }
    return best;
  }

  function fireClick(el) {
    el = realTarget(el);
    try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
    var r;
    try { r = el.getBoundingClientRect(); } catch (e) { r = { left: 0, top: 0, width: 0, height: 0 }; }
    var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    var base = { bubbles: true, cancelable: true, composed: true, view: window, clientX: cx, clientY: cy };
    function dispatch(Ctor, type, extra) {
      try { el.dispatchEvent(new Ctor(type, Object.assign({}, base, extra || {}))); } catch (e) {}
    }
    if (window.PointerEvent) {
      dispatch(PointerEvent, 'pointerdown', { pointerId: 1, pointerType: 'mouse', isPrimary: true });
    }
    dispatch(MouseEvent, 'mousedown', { button: 0 });
    if (window.PointerEvent) {
      dispatch(PointerEvent, 'pointerup', { pointerId: 1, pointerType: 'mouse', isPrimary: true });
    }
    dispatch(MouseEvent, 'mouseup', { button: 0 });
    try { el.click(); } catch (e) { dispatch(MouseEvent, 'click', { button: 0 }); }
  }

  var FARE_WORDS = /(일반석|프리미엄|프레스티지|일등석)/;

  /** 특정 날짜를 하드코딩하지 않고, 달력에서 "예약 가능한 것 중 가장 나중(=제일 늦게
   * 열린) 날짜" 를 찾는다. 마일리지 좌석은 매일 09:00 KST 에 하루치씩 새로 열리므로,
   * 이 방식이면 스텝을 매일 다시 지정할 필요가 없다.
   * idPrefix 로 시작하는 id 를 가진 셀들을 훑어서, 요금등급 글자(일반석/프레스티지 등)
   * 가 붙어있는(=예약 가능한) 것들 중 DOM 순서상 마지막(=달력에서 가장 나중 날짜)을
   * 반환한다. 요일만 있고 요금 정보가 없는 셀(아직 안 열렸거나 그 요일 운항이 없는
   * 날)은 자동으로 제외된다. */
  function findLatestOpenDate(idPrefix) {
    idPrefix = idPrefix || 'dep-fare-';
    var list;
    try { list = document.querySelectorAll('[id^="' + idPrefix + '"]'); } catch (e) { return null; }
    var best = null;
    for (var i = 0; i < list.length; i++) {
      var el = list[i];
      if (!visible(el)) continue;
      if (el.getAttribute('aria-disabled') === 'true' || el.disabled) continue;
      if (/disable|unavail|soldout/i.test(el.className || '')) continue;
      if (FARE_WORDS.test(label(el))) best = el;
    }
    return best;
  }

  /* 좌석 등급으로 항공편 카드를 찾는다.
   * 라벨이 "항공편명 KE901 일반석 52,500 마일" 형태라, 등급 이름 + '마일' 로 고르면
   * 편명이나 필요 마일리지가 바뀌어도, id/클래스(#classEconomyList0 등)가 등급마다
   * 달라도 그대로 동작한다. 같은 등급 카드가 여러 개면 라벨이 가장 짧은 것(=가장
   * 구체적인 요소)을 고른다. */
  function findCabin(cabin) {
    if (!cabin) return null;
    var all = candidates(document), best = null, bestLen = 1e9;
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      if (!visible(el) || inChrome(el)) continue;
      var t = label(el);
      if (t.indexOf(cabin) === -1 || t.indexOf('마일') === -1) continue;
      if (t.length < bestLen) { best = el; bestLen = t.length; }
    }
    return best;
  }

  /* 위험품 안내 팝업은 끝까지 내려야 [확인] 이 열린다. "아래로 스크롤" 버튼이
   * 스크롤에 따라 움직이거나 화면 밖으로 밀리면 클릭이 빗나가 거기서 멈춘다.
   * 버튼을 누르는 것과 별개로, 스크롤 가능한 영역을 직접 바닥까지 내려 확실히 한다.
   * (사이트가 스크롤 이벤트로 판정하는 경우도 있어 버튼 클릭도 그대로 유지한다) */
  function scrollToBottom() {
    var n = 0;
    var all;
    try { all = document.querySelectorAll('div,section,article,main,ul,ol'); } catch (e) { return 0; }
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      if (el.scrollHeight - el.clientHeight < 24) continue;   // 스크롤할 게 없음
      if (!visible(el)) continue;
      var oy;
      try { oy = getComputedStyle(el).overflowY; } catch (e) { continue; }
      if (oy !== 'auto' && oy !== 'scroll') continue;
      try {
        el.scrollTop = el.scrollHeight;
        el.dispatchEvent(new Event('scroll', { bubbles: true }));
        n++;
      } catch (e) {}
    }
    try {
      var d = document.scrollingElement || document.documentElement;
      if (d && d.scrollHeight - d.clientHeight > 24) { d.scrollTop = d.scrollHeight; n++; }
    } catch (e) {}
    return n;
  }

  var U = {
    visible: visible, label: label, cssPath: cssPath, findEl: findEl, CLICKABLE: CLICKABLE,
    candidates: candidates, diagnose: diagnose, diagnoseText: diagnoseText, fireClick: fireClick,
    findLatestOpenDate: findLatestOpenDate, inChrome: inChrome, realTarget: realTarget,
    findCabin: findCabin, scrollToBottom: scrollToBottom, hittable: hittable
  };
  try { W.KE_UTIL = U; } catch (e) {}
  if (W !== window) { try { window.KE_UTIL = U; } catch (e) {} }
})();
