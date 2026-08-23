// ==UserScript==
// @name         대한항공 마일리지 예매 보조 (KE Award Macro)
// @namespace    local.ke.award
// @version      1.3.0
// @description  예매 단계 녹화/재생 + 오픈시각 정시 발사 + 안내사항 모달 즉시 통과
// @author       local
// @match        *://*.koreanair.com/*
// @match        *://koreanair.com/*
// @run-at       document-start
// @grant        unsafeWindow
// @noframes     false
// ==/UserScript==
/* 주의: 본인 계정으로 본인 여정을 예매하는 용도로만 사용하세요.
 *       재조회 간격은 800ms 미만으로 낮추지 마세요 (봇 탐지 / 서버 부담).  */


// ---------- util ----------
try {
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
   * 화면 밖이라 판정이 불가능하면 통과시킨다 - fireClick 이 스크롤해서 누른다. */
  function hittable(el) {
    var r;
    try { r = el.getBoundingClientRect(); } catch (e) { return true; }
    var x = r.left + r.width / 2, y = r.top + r.height / 2;
    var W2 = window.innerWidth || 0, H2 = window.innerHeight || 0;
    if (x < 0 || y < 0 || x > W2 || y > H2) return true;   // 화면 밖 -> 판정 보류
    var top;
    try { top = document.elementFromPoint(x, y); } catch (e) { return true; }
    if (!top) return true;
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

} catch (e) {
  console.error('[KE] util 로드 실패:', e);
}


// ---------- autoconfirm ----------
try {
/* ============================================================
 * autoconfirm.js  --  안내사항 모달 즉시 통과 엔진
 *
 * 동작 원리
 *  1) MutationObserver 로 DOM 변화를 감시 -> 모달이 그려지는 즉시 반응
 *  2) rAF 루프를 보조로 돌려 CSS transition 으로 뒤늦게 보이는 버튼도 포착
 *  3) 버튼 라벨을 "정규화 후 정확히" 매칭 (부분일치 X)
 *     - 결제/발권 화면에서 엉뚱한 버튼을 누르는 사고를 막기 위함
 *  4) 클릭 금지 목록(never)이 항상 우선
 *
 * 콘솔 튜닝
 *  KE_AUTO.scan()              현재 화면의 버튼 후보 미리보기 (클릭 안 함)
 *  KE_AUTO.click.push("라벨")  라벨 추가
 *  KE_AUTO.off() / .on()       토글
 *  KE_AUTO.dump()              클릭 로그
 * ============================================================ */
(function () {
  'use strict';

  /* Tampermonkey 는 @grant 가 걸리면 샌드박스에서 실행된다. 그 경우 window 에 붙인
   * 값은 페이지(=F12 콘솔)에서 안 보이므로 unsafeWindow 에도 같이 노출해야 한다.
   * Playwright 주입 시에는 unsafeWindow 가 없으니 window 로 폴백. */
  var W = window;
  try { if (typeof unsafeWindow !== 'undefined' && unsafeWindow) W = unsafeWindow; } catch (e) {}
  function expose(k, v) {
    try { W[k] = v; } catch (e) {}
    if (W !== window) { try { window[k] = v; } catch (e) {} }
  }

  if (W.KE_AUTO || window.KE_AUTO) return;

  // util.js 가 없는 환경(Playwright 는 이 파일만 단독 주입)에서도 동작해야 하므로 없으면 무시.
  var U = W.KE_UTIL || window.KE_UTIL;

  var CFG = {
    enabled: true,

    // 정규화(소문자/공백·기호 제거) 후 "정확히" 일치하면 클릭
    click: [
      '확인', '확인하였습니다', '동의', '동의함', '동의합니다',
      '전체동의', '모두동의', '전체선택', '위내용을확인하였습니다',
      '다음', '다음단계', '계속', '계속하기', '진행',
      '아래로스크롤', '아래로', '스크롤',   // 위험품 안내 팝업: 끝까지 내려야 확인이 열림
      '예', 'ok', 'confirm', 'agree', 'iagree', 'continue', 'next', 'accept', 'yes'
    ],

    /* 토글성 버튼: 이미 켜져 있으면 누르면 안 된다.
     * (확인 및 동의 2개 중 하나가 이미 동의된 상태로 나오는 화면이 있는데,
     *  거기서 다시 누르면 동의가 풀려 결제로 못 넘어간다) */
    toggleLabels: ['동의', '동의함', '동의합니다', '전체동의', '모두동의', '전체선택'],

    // 이 문자열이 "포함"되면 무조건 스킵 (click 목록보다 우선)
    never: [
      '취소', '닫기', '이전', '뒤로', '아니오', '아니요', '거부', '동의하지',
      '삭제', '로그아웃', '재검색', '다시검색', '변경', '초기화', '홈으로',
      'cancel', 'close', 'back', 'no', 'decline', 'reject', 'logout', 'reset'
    ],

    // 최종 발권/결제 버튼은 기본 OFF. 마지막 한 번은 사람이 누르는 게 안전.
    // 켜려면 콘솔에서  KE_AUTO.autoFinal = true
    autoFinal: false,
    finalLabels: ['발권', '결제', '구매', '예약완료', '마일리지공제', 'purchase', 'issueticket'],

    checkboxes: true,   // 필수 동의 체크박스 자동 체크
    cooldownMs: 350,    // 같은 라벨 재클릭 최소 간격 (무한루프 방지)
    maxClicks: 60,      // 세션당 총 클릭 상한 (폭주 안전장치)
    log: []
  };

  // 아래 설치 과정에서 예외가 나도 API 는 남도록 먼저 노출한다
  expose('KE_AUTO', CFG);

  var clicks = 0;
  var lastByLabel = Object.create(null);
  var seen = new WeakSet();

  // 기호를 하나씩 블랙리스트로 지우면  »  ›  →  같은 글리프를 놓친다.
  // 한글 음절 / 영문 / 숫자만 남기는 화이트리스트가 안전.
  var KEEP = /[^0-9a-z가-힣]/g;

  function norm(s) {
    return (s || '').toLowerCase().replace(KEEP, '');
  }

  function labelOf(el) {
    var t = el.innerText || el.textContent || '';
    if (!t.trim()) t = el.value || el.getAttribute('aria-label') || el.title || '';
    return norm(t).slice(0, 40);
  }

  function visible(el) {
    if (!el.isConnected) return false;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
    var r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    var st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none') return false;
    if (parseFloat(st.opacity || '1') < 0.05) return false;
    if (st.pointerEvents === 'none') return false;
    return true;
  }

  var SEL = 'button, a[role="button"], a[href="#"], a[href^="javascript"], ' +
            '[role="button"], input[type="button"], input[type="submit"], ' +
            '.btn, .button, [class*="btn-confirm"], [class*="btnConfirm"]';

  function candidates(root) {
    var out = [];
    try { out = Array.prototype.slice.call(root.querySelectorAll(SEL)); } catch (e) { return out; }
    // open shadow root 내부까지 훑는다 (일부 위젯이 웹컴포넌트)
    try {
      root.querySelectorAll('*').forEach(function (n) {
        if (n.shadowRoot) out = out.concat(candidates(n.shadowRoot));
      });
    } catch (e) {}
    return out;
  }

  /** 이미 선택/동의된 상태인가. 토글 버튼을 다시 눌러 끄는 사고를 막기 위한 판정. */
  function alreadyOn(el) {
    var a = el.getAttribute('aria-pressed') || el.getAttribute('aria-checked')
         || el.getAttribute('aria-selected');
    if (a === 'true') return true;
    if (a === 'false') return false;
    var node = el;
    for (var d = 0; d < 2 && node; d++) {          // 자신 + 부모까지만
      var cl = node.classList;
      if (cl) {
        for (var i = 0; i < cl.length; i++) {
          if (/^(active|selected|checked|on|agreed|is-active|is-selected|is-checked)$/i.test(cl[i])) {
            return true;
          }
        }
      }
      node = node.parentElement;
    }
    var inp = el.querySelector && el.querySelector('input[type="checkbox"],input[type="radio"]');
    return !!(inp && inp.checked);
  }

  function decide(el) {
    var L = labelOf(el);
    if (!L) return null;
    for (var i = 0; i < CFG.never.length; i++) {
      if (L.indexOf(norm(CFG.never[i])) !== -1) return null;
    }
    for (var t = 0; t < CFG.toggleLabels.length; t++) {
      if (L === norm(CFG.toggleLabels[t]) && alreadyOn(el)) return null;   // 이미 켜짐 -> 건드리지 않음
    }
    for (var j = 0; j < CFG.click.length; j++) {
      if (L === norm(CFG.click[j])) return L;
    }
    if (CFG.autoFinal) {
      for (var k = 0; k < CFG.finalLabels.length; k++) {
        if (L.indexOf(norm(CFG.finalLabels[k])) !== -1) return L;
      }
    }
    return null;
  }

  function fire(el, label) {
    var now = performance.now();
    if (lastByLabel[label] && now - lastByLabel[label] < CFG.cooldownMs) return false;
    if (clicks >= CFG.maxClicks) return false;
    lastByLabel[label] = now;
    seen.add(el);
    clicks++;
    if (U) {
      U.fireClick(el);
    } else {
      try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
      try {
        el.click();
      } catch (e) {
        try {
          el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
        } catch (e2) { return false; }
      }
    }
    var rec = { t: new Date().toISOString().slice(11, 23), label: label, n: clicks };
    CFG.log.push(rec);
    var report = window.__keReport || W.__keReport;   // Playwright 바인딩 (있을 때만)
    if (report) { try { report(JSON.stringify(rec)); } catch (e) {} }
    console.log('%c[KE_AUTO] click #' + clicks + ' -> ' + label, 'color:#0a0;font-weight:bold');
    return true;
  }

  var SKIP_BOX = /동의하지|수신거부|선택안함|아니오|아니요/;

  function doCheckboxes(root) {
    if (!CFG.checkboxes) return;
    var boxes;
    try { boxes = root.querySelectorAll('input[type="checkbox"]:not(:checked)'); } catch (e) { return; }
    boxes.forEach(function (cb) {
      if (seen.has(cb) || !visible(cb)) return;
      var scope = cb.closest('label, li, dd, div, tr') || cb.parentElement;
      var txt = scope ? (scope.innerText || '') : '';
      if (SKIP_BOX.test(txt)) return;      // 거부/미동의 항목은 건드리지 않음
      seen.add(cb);
      try { cb.click(); } catch (e) {}
      console.log('%c[KE_AUTO] check -> ' + txt.replace(/\s+/g, ' ').slice(0, 30), 'color:#08a');
    });
  }

  /* recorder.js 가 재생 중이면 그쪽이 이미 같은 확인/동의/스크롤 버튼을 정해진
   * 순서로 누르고 있다. autoconfirm 이 동시에 끼어들면 recorder 보다 먼저 눌러
   * 버려서 recorder 가 자기 단계의 요소를 못 찾고 20초씩 멈추는 경합이 생긴다.
   * 재생 중엔 손을 떼고, 재생이 끝나면(완료/일시정지/결제대기) 다시 넘겨받는다. */
  var REPLAY_GRACE_MS = 4000;   // 이보다 오래 같은 단계에서 막히면 예상 밖 모달로 보고 다시 끼어든다
  function replaying() {
    var R = W.KE_REC || window.KE_REC;
    if (!R || !R.state || !R.state.playing) return false;
    var stalled = (R.stalledMs && R.stalledMs()) || 0;
    return stalled < REPLAY_GRACE_MS;
  }

  function sweep() {
    if (!CFG.enabled || replaying()) return;
    var roots = [document];
    // same-origin iframe (약관/결제 위젯이 iframe 인 경우)
    try {
      document.querySelectorAll('iframe').forEach(function (f) {
        try { if (f.contentDocument) roots.push(f.contentDocument); } catch (e) {}
      });
    } catch (e) {}

    for (var r = 0; r < roots.length; r++) {
      doCheckboxes(roots[r]);
      var els = candidates(roots[r]);
      for (var i = 0; i < els.length; i++) {
        var el = els[i];
        if (seen.has(el) || !visible(el)) continue;
        var label = decide(el);
        if (label) { fire(el, label); return; }   // 한 번에 하나만 -> 화면 전환 후 재평가
      }
    }
  }

  // document-start 주입 시점에는 document.documentElement 가 아직 null 이라
  // 그것을 observe 하면 TypeError 로 스크립트 전체가 죽는다. document 는 항상 존재한다.
  try {
    new MutationObserver(sweep).observe(document, {
      childList: true, subtree: true, attributes: true,
      attributeFilter: ['class', 'style', 'hidden', 'aria-hidden', 'disabled']
    });
  } catch (e) {
    console.warn('[KE_AUTO] MutationObserver 설치 실패', e);
  }

  // 보조 1: transition 으로 늦게 나타나는 버튼 포착 (~16ms 반응)
  (function raf() { sweep(); requestAnimationFrame(raf); })();
  // 보조 2: 탭이 백그라운드면 rAF 가 멈춘다. 저빈도 인터벌로 최소한의 동작을 보장.
  setInterval(sweep, 250);

  // "이 페이지를 나가시겠습니까?" 억제 - 리트라이 중 흐름이 막히지 않도록
  window.addEventListener('beforeunload', function (e) { delete e.returnValue; }, true);

  CFG.on    = function () { CFG.enabled = true;  console.log('[KE_AUTO] ON'); };
  CFG.off   = function () { CFG.enabled = false; console.log('[KE_AUTO] OFF'); };
  CFG.dump  = function () { console.table(CFG.log); return CFG.log; };
  CFG.reset = function () { clicks = 0; lastByLabel = Object.create(null); seen = new WeakSet(); };
  CFG.scan  = function () {
    var out = [];
    candidates(document).forEach(function (el) {
      if (visible(el)) {
        out.push({
          normalized: labelOf(el),
          wouldClick: !!decide(el),
          text: (el.innerText || el.value || '').replace(/\s+/g, ' ').trim().slice(0, 30)
        });
      }
    });
    console.table(out);
    return out;
  };

  console.log('%c[KE_AUTO] armed. KE_AUTO.scan() 으로 후보 확인, KE_AUTO.off() 로 정지.',
              'color:#c60;font-weight:bold');
})();

} catch (e) {
  console.error('[KE] autoconfirm 로드 실패:', e);
}


// ---------- steps ----------
try {
(function () {
  var S = [{"dynamicDate":true,"idPrefix":"dep-fare-","sel":"#dep-fare-5-1","text":"(날짜: 매번 최신 오픈일 자동 감지 - 16 08월 16일 (월) , 성수기 일반석 은 녹화 당시 예시)","tag":"td","url":"/booking/calendar-fare-bonus","selectorOnly":false},{"sel":"#ac0e9a2f7f9ead9dbd368853f47deb65CalendarFareBonusMain > div.payment-widget.bottom-fixed-area:nth-of-type(4) > kds-sticky.ang-sticky > kds-sticky_1.--wds-ui.ui-sticky__host > kds-button.--wds-ui.ui-button__host > kds-button_1.--wds-ui.ui-button__host","text":"검색","tag":"kds-button_1","url":"/booking/calendar-fare-bonus","selectorOnly":false},{"dynamicCabin":true,"sel":"","text":"(좌석: 패널에서 고른 등급을 매번 다시 찾음 - 녹화 당시는 '항공편명 KE901 일반석 52,500 마일')","tag":"label","url":"/booking/select-award-flight/departure","selectorOnly":false},{"sel":"#payment-widget > kds-sticky_1.--wds-ui.ui-sticky__host > kds-button > kds-button_1.--wds-ui.ui-button__host","text":"다음","tag":"kds-button_1","url":"/booking/select-award-flight/departure","selectorOnly":false},{"sel":"#submit-passenger-ADT-0","text":"확인","tag":"button","url":"/payment/gate/RT/NR","selectorOnly":false},{"sel":"#submit-contact","text":"확인","tag":"button","url":"/payment/gate/RT/NR","selectorOnly":false},{"sel":"#btn-resv-agree-1","text":"동의","tag":"button","url":"/payment/gate/RT/NR","selectorOnly":false},{"sel":"#btn-resv-agree-3","text":"동의","tag":"button","url":"/payment/gate/RT/NR","selectorOnly":false},{"sel":"#btnScrollDown > kds-button_1.--wds-ui.ui-button__host","text":"아래로 스크롤","tag":"kds-button_1","url":"/payment/gate/RT/NR","selectorOnly":false},{"sel":"#btnScrollDown > kds-button_1.--wds-ui.ui-button__host","text":"아래로 스크롤","tag":"kds-button_1","url":"/payment/gate/RT/NR","selectorOnly":false},{"sel":"#btnConfirm > kds-button_1.--wds-ui.ui-button__host","text":"확인","tag":"kds-button_1","url":"/payment/gate/RT/NR","selectorOnly":false},{"sel":"#btn-resv-agree-1","text":"동의","tag":"button","url":"/payment/gate/RT/NR","selectorOnly":false},{"sel":"#btnConfirm","text":"확인","tag":"button","url":"/payment/gate/RT/NR","selectorOnly":false},{"sel":"#btnAwardUseMileageApply","text":"적용","tag":"button","url":"/payment/gate/RT/NR","selectorOnly":false},{"sel":"ke-payment-interface-cont._folders.ng-star-inserted > ke-payment-interface-pres.ng-star-inserted > div.bundles.-bordered > div.-lined.ng-star-inserted:nth-of-type(2) > div.payment-method.ng-star-inserted:nth-of-type(1) > div.payment-method__item.ng-star-inserted:nth-of-type(3) > label.ng-star-inserted","text":"Npay","tag":"label","url":"/payment/gate/RT/NR","selectorOnly":false},{"sel":"#btn-payment","text":"결제하기 새 창 열림","tag":"button","url":"/payment/gate/RT/NR","selectorOnly":false}];
  var W = window;
  try { if (typeof unsafeWindow !== 'undefined' && unsafeWindow) W = unsafeWindow; } catch (e) {}
  try { W.KE_STEPS_BAKED = S; } catch (e) {}
  if (W !== window) { try { window.KE_STEPS_BAKED = S; } catch (e) {} }
  if (S.length) console.log('[KE] 내장 단계 ' + S.length + '개 (2026-08-21 08:57:27)');
})();
} catch (e) {
  console.error('[KE] steps 로드 실패:', e);
}


// ---------- recorder ----------
try {
/* ============================================================
 * recorder.js  --  예매 단계 녹화 / 재생
 *
 * 왜 필요한가
 *   실제 예매는 "확인 버튼 아무거나 누르기" 가 아니라 정해진 순서다:
 *     새로고침 -> 새 날짜 클릭 -> 검색 -> 좌석 -> 다음 -> 승객확인
 *     -> 위험품 팝업 아래로스크롤 x2 -> 확인 -> 동의(안 켜진 것만) -> 결제수단
 *   라벨 추측으로는 (a) 날짜처럼 매일 바뀌는 것 (b) 이미 켜진 동의를 다시 눌러
 *   꺼버리는 사고 를 막을 수 없다. 손으로 한 번 한 걸 그대로 재생하는 게 정확하다.
 *
 * 페이지 이동
 *   단계 중간에 페이지가 바뀌면 JS 상태가 날아간다. 진행 위치를 localStorage 에
 *   두고 새 문서에서 자동으로 이어서 재생한다.
 *
 * 콘솔
 *   KE_REC.record()  녹화 시작 / KE_REC.stop() 중지
 *   KE_REC.play()    재생      / KE_REC.pause() 중지
 *   KE_REC.list()    단계 목록 / KE_REC.clear() 삭제
 * ============================================================ */
(function () {
  'use strict';
  var W = window;
  try { if (typeof unsafeWindow !== 'undefined' && unsafeWindow) W = unsafeWindow; } catch (e) {}
  if (W.KE_REC || window.KE_REC) return;

  var U = W.KE_UTIL || window.KE_UTIL;
  var LS = 'ke_award_steps_v1';

  /* 이 라벨이 걸리면 재생을 멈추고 사람에게 넘긴다.
   * 마일리지와 현금이 실제로 빠져나가는 지점이라 자동으로 넘기지 않는다. */
  var PAY = /결제하기|결제및발권|발권하기|구매하기|purchase|paynow/;

  // "아래로 스크롤" 계열 단계. 클릭만으로는 불안해서 스크롤을 직접 한 번 더 밀어준다.
  var SCROLLY = /아래로|스크롤|scroll/i;

  var S = {
    steps: [],
    recording: false,
    playing: false,
    idx: 0,
    playAfterReload: false, // 새로고침이 끝난 뒤에 재생을 시작하라는 예약 (armForReload)
    startedAt: 0,         // 발사 시각(ms). 단계별/총 소요시간 표시용
    skipped: 0,           // resync 로 건너뛴 단계 수. 완료 보고를 정직하게 하기 위함
    expectDate: '',       // 목표 날짜(예: "08월 17일"). 넣으면 자동 감지한 최신 오픈일이
                          // 이것과 다를 때 클릭하지 않고 멈춘다 (엉뚱한 날 예매 방지)
    cabin: '일반석',       // 좌석 등급. 연습은 '일반석', 실전은 '프레스티지'
    /* 결제하기까지 자동으로 눌러 결제창(네이버페이 등)을 띄운다.
     * 결제창에서 다시 본인 인증이 필요하므로 여기서 바로 돈이 빠지지는 않는다.
     * 패널의 [결제하기까지 자동] 체크박스로 끌 수 있다. */
    allowPay: true,
    stepTimeoutMs: 20000, // 한 단계에서 요소를 못 찾고 버티는 한계
    resyncAfterMs: 700,   // 이만큼 막히면 "이미 지나간 단계인가?" 하고 뒤를 넘겨본다.
                          // 자동클릭 엔진이 같은 버튼을 먼저 눌러버리는 일이 잦아서
                          // 길게 잡으면 그만큼 그냥 버려진다
    lookahead: 3,         // 몇 단계 앞까지 넘겨볼지
    gapMs: 80             // 클릭 사이 최소 간격
  };

  function load() {
    try {
      var raw = localStorage.getItem(LS);
      if (raw) {
        var d = JSON.parse(raw);
        for (var k in d) if (k in S) S[k] = d[k];
      }
    } catch (e) {}
  }
  function save() {
    try { localStorage.setItem(LS, JSON.stringify(S)); } catch (e) {}
  }
  load();

  /* 빌드 시 steps.json 에서 구워 넣은 기본 단계.
   * 이 브라우저에 녹화본이 없을 때만 쓴다 (직접 녹화한 게 항상 우선). */
  function baked() { return (W.KE_STEPS_BAKED || window.KE_STEPS_BAKED || []); }
  if (!S.steps.length && baked().length) {
    S.steps = JSON.parse(JSON.stringify(baked()));
    S.idx = 0;
    save();
  }

  /* armForReload() 로 예약해둔 재생을 여기서 시작한다.
   * 이 코드는 새 문서가 뜰 때마다 한 번 실행되므로, "새로고침이 끝난 뒤" 라는
   * 시점이 정확히 보장된다. 낡은 화면에서 1단계를 눌러버리고 그 결과가 새로고침에
   * 날아가는 사고를 막기 위한 것이다. */
  if (S.playAfterReload) {
    S.playAfterReload = false;
    S.playing = true;
    S.idx = 0;
    save();
  }

  var listeners = [];
  function emit() {
    for (var i = 0; i < listeners.length; i++) {
      try { listeners[i](S); } catch (e) {}
    }
  }
  function log(msg) {
    console.log('%c[KE_REC] ' + msg, 'color:#a0f;font-weight:bold');
    S.message = msg;
    emit();
  }

  // ---- 녹화 --------------------------------------------------------------
  function onClick(ev) {
    if (!S.recording) return;
    var el = ev.target;
    if (el.closest && el.closest('#ke-hud, #ke-editor, #ke-export')) return;  // 우리 UI 는 기록 안 함
    var t = el.closest ? (el.closest(U.CLICKABLE) || el) : el;

    var step = {
      sel: U.cssPath(t),
      text: U.label(t),
      tag: t.tagName.toLowerCase(),
      url: location.pathname + location.search,
      // 날짜처럼 매일 바뀌는 라벨은 텍스트 폴백이 오히려 해롭다 -> 사용자가 끌 수 있게
      selectorOnly: false
    };
    S.steps.push(step);
    save();
    log('녹화 ' + S.steps.length + ': ' + (step.text || step.sel).slice(0, 30));
  }
  document.addEventListener('click', onClick, true);

  function record() {
    S.steps = [];
    S.recording = true;
    S.playing = false;
    S.idx = 0;
    save();
    log('녹화 시작 - 평소처럼 끝까지 진행하세요 (결제 직전까지)');
  }
  function stopRec() {
    S.recording = false;
    save();
    log('녹화 종료 - ' + S.steps.length + '단계');
  }

  // ---- 재생 --------------------------------------------------------------
  var waitingSince = 0;
  var lastClickAt = 0;

  function isPay(step) {
    return PAY.test((step.text || '').replace(/[^0-9a-z가-힣]/gi, '').toLowerCase());
  }

  /** 발사(재생 시작)부터 지금까지 몇 초. 새로고침을 건너도 이어지도록 저장해둔다. */
  function elapsed() {
    return S.startedAt ? (Date.now() - S.startedAt) / 1000 : 0;
  }
  function secs(v) { return v.toFixed(2) + 's'; }

  function play() {
    if (!S.steps.length) { log('녹화된 단계가 없습니다'); return; }
    S.recording = false;
    S.playing = true;
    if (!S.startedAt || S.idx === 0) { S.startedAt = Date.now(); S.skipped = 0; }
    waitingSince = 0;
    save();
    log('재생 시작 (' + (S.idx + 1) + '/' + S.steps.length + ')');
  }
  function pause(why) {
    S.playing = false;
    S.playAfterReload = false;
    var took = elapsed();
    save();
    log('재생 중지' + (why ? ' - ' + why : '') + (took ? '  [총 ' + secs(took) + ']' : ''));
  }

  /* "새로고침한 다음 처음부터 재생" 예약. 지금 당장은 재생하지 않는다.
   * play() 를 먼저 부르면 tick 이 낡은 화면에서 1단계를 눌러버리고, 이어지는
   * 새로고침이 그 결과를 통째로 날린다 (정시 발사 때 날짜 선택이 사라지는 사고). */
  function armForReload() {
    if (!S.steps.length) { log('녹화된 단계가 없습니다'); return false; }
    S.recording = false;
    S.playing = false;
    S.idx = 0;
    S.playAfterReload = true;
    S.startedAt = Date.now();   // 소요시간은 "발사 시점" 부터 센다 (새로고침 포함)
    S.skipped = 0;
    save();
    log('새로고침 후 처음부터 재생 예약됨');
    return true;
  }
  function reset() { S.idx = 0; save(); log('처음 단계로'); }
  function clear() { S.steps = []; S.idx = 0; S.playing = false; S.recording = false; save(); log('삭제됨'); }

  /* 한 단계가 가리키는 요소를 찾는다.
   * dynamicDate: 특정 날짜 텍스트/셀렉터 대신 "지금 예약 가능한 것 중 가장 나중 날짜".
   *   마일리지는 매일 09:00 KST 에 하루치씩 새로 열려서, 녹화한 날짜는 다음날 못 쓴다.
   * dynamicCabin: 패널에서 고른 좌석 등급의 항공편 카드 (연습=일반석 / 실전=프레스티지). */
  function locate(step) {
    if (step.dynamicDate) return U.findLatestOpenDate(step.idPrefix);
    if (step.dynamicCabin) return U.findCabin(S.cabin);
    return U.findEl(step.sel, step.text, { selectorOnly: step.selectorOnly });
  }

  /* 막혔을 때 "이미 지나간 단계"인지 확인한다.
   * 자동클릭 엔진이 같은 확인 버튼을 먼저 눌러버리거나, 사이트가 화면 하나를 건너뛰면
   * 녹화한 요소는 영영 안 나타난다. 그때 20초를 버리는 대신, 뒤쪽 단계의 요소가 이미
   * 보이면 거기로 따라잡는다. 녹화는 정답 스크립트가 아니라 안내로 취급하는 쪽이 맞다.
   * 단, 결제 단계로는 절대 건너뛰지 않는다 (순서대로 도달했을 때만 누른다). */
  function resync() {
    /* 모달이 떠 있으면 그 뒤 화면의 버튼들이 "보이기" 때문에, 그것만 보고 건너뛰면
     * 팝업이 열린 채로 끝까지 달려가 "완료" 라고 거짓 보고를 한다(소리는 나는데
     * 화면은 위험품 팝업에서 멈춰 있는 증상). 실제로 그 좌표에서 잡히는지(hittable)
     * 까지 확인해야 한다. */
    var end = Math.min(S.idx + 1 + S.lookahead, S.steps.length);
    for (var k = S.idx + 1; k < end; k++) {
      var nx = S.steps[k];
      if (isPay(nx)) return false;
      var nel = locate(nx);
      if (nel && U.hittable(nel)) {
        log('단계 ' + (S.idx + 1) + ' 건너뜀 (이미 지나간 것으로 보임) -> ' + (k + 1) + '단계로');
        S.skipped = (S.skipped || 0) + (k - S.idx);
        S.idx = k;
        waitingSince = 0;
        save();
        return true;
      }
    }
    return false;
  }

  function tick() {
    if (!S.playing) return;
    /* 문서가 아직 파싱 중이면 요소는 이미 DOM 에 있어도 그 페이지의 스크립트가
     * 클릭 핸들러를 아직 안 붙였을 수 있다. 그 틈에 누르면 예외도 없이 아무 일도
     * 안 일어난다. DOMContentLoaded 이후(interactive/complete)에만 진행한다. */
    if (document.readyState === 'loading') return;
    var now = Date.now();
    if (now - lastClickAt < S.gapMs) return;

    var step = S.steps[S.idx];
    if (!step) { pause('전체 단계 완료'); return; }

    if (isPay(step) && !S.allowPay) {
      pause('결제 단계입니다 - 직접 확인하고 누르세요');
      return;
    }

    var el = locate(step);

    /* 목표 날짜를 지정해뒀으면, 자동 감지한 최신 오픈일이 그 날짜가 맞는지 확인한다.
     * 안 맞으면 누르지 않고 멈춘다 - 엉뚱한 날짜로 마일리지가 빠지는 게 최악이다. */
    if (step.dynamicDate && el && S.expectDate) {
      var got = U.label(el);
      if (got.indexOf(S.expectDate) === -1) {
        pause('목표 날짜(' + S.expectDate + ')와 다릅니다 - 감지된 최신 오픈일: ' + got.slice(0, 30));
        return;
      }
    }
    if (!el) {
      if (!waitingSince) waitingSince = now;
      /* 스크롤 단계인데 버튼을 못 찾는 경우: 버튼이 스크롤에 밀려 사라졌거나 라벨이
       * 바뀐 것일 수 있다. 그래도 팝업은 끝까지 내려야 [확인] 이 열리므로, 버튼과
       * 무관하게 스크롤 자체는 계속 밀어준다. */
      if (SCROLLY.test(step.text || '')) U.scrollToBottom();
      if (now - waitingSince > S.resyncAfterMs && resync()) return;
      if (now - waitingSince > S.stepTimeoutMs) {
        // 스크린샷 한 장으로 원인 파악이 되도록 패널 상태줄에 진단 요약을 그대로 붙인다.
        var diag = step.dynamicDate
          ? '최신 오픈일 셀을 못 찾음 (id 접두어: ' + (step.idPrefix || 'dep-fare-') + ')'
          : step.dynamicCabin
            ? '"' + S.cabin + '" 좌석이 이 화면에 없습니다 (그날 그 등급이 안 열렸을 수 있음)'
            : U.diagnoseText(step.sel, step.selectorOnly ? '' : step.text);
        pause('단계 ' + (S.idx + 1) + ' 요소를 못 찾음: ' + (step.text || step.sel || '').slice(0, 30) + ' [' + diag + ']');
      }
      return;
    }

    waitingSince = 0;
    lastClickAt = now;
    U.fireClick(el);

    /* "아래로 스크롤" 은 버튼을 누르는 것만으로는 불안하다. 스크롤이 진행되면 버튼
     * 자체가 위로 밀리거나 화면 밖으로 나가서 클릭이 빗나가고, 팝업이 끝까지 안 내려가
     * [확인] 이 안 열린 채 멈춘다. 스크롤 영역을 직접 바닥까지 내려 확실히 한다. */
    if (SCROLLY.test(step.text || '')) U.scrollToBottom();

    S.idx++;
    save();
    log('재생 ' + S.idx + '/' + S.steps.length + ': ' + (step.text || step.sel).slice(0, 30)
        + '  [' + secs(elapsed()) + ']');
    if (S.idx >= S.steps.length) {
      /* 건너뛴 단계가 있으면 "완료" 라고만 하면 안 된다. 자동클릭 엔진이 대신 눌러서
       * 정상인 경우도 있지만, 화면이 실제로는 안 넘어갔을 수도 있다. 반드시 눈으로
       * 확인하라고 알린다. */
      pause(S.skipped
        ? '단계 끝까지 진행 - 다만 ' + S.skipped + '단계를 건너뛰었습니다. 화면을 확인하세요'
        : '전체 단계 완료');
    }
  }

  // 페이지가 바뀌어도 localStorage 의 idx 에서 이어서 재생된다
  setInterval(tick, 60);
  new MutationObserver(tick).observe(document, { childList: true, subtree: true });

  /** ke_award/steps.json 에 그대로 붙여넣을 수 있는 형태로 뽑는다. */
  function exportJson() {
    return JSON.stringify({
      note: '패널 [내보내기] 로 뽑은 예매 단계. ke_award/steps.json 에 덮어쓰고 node build.mjs 하면 스크립트에 내장된다.',
      recordedAt: new Date().toISOString().slice(0, 19).replace('T', ' '),
      steps: S.steps
    }, null, 2);
  }

  /** 화면에 텍스트박스를 띄워 복사시킨다. 클립보드 API 가 막힌 환경도 있어서 폴백이 필요. */
  function showExport() {
    var json = exportJson();
    try { navigator.clipboard.writeText(json); } catch (e) {}
    var old = document.getElementById('ke-export');
    if (old) old.remove();
    var box = document.createElement('div');
    box.id = 'ke-export';
    box.style.cssText = 'position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,.6);' +
                        'display:flex;align-items:center;justify-content:center';
    box.innerHTML =
      '<div style="background:#fff;padding:16px;border-radius:8px;width:min(680px,90vw)">' +
      '<b style="font:13px sans-serif">ke_award/steps.json 에 덮어쓰고 <code>node build.mjs</code></b>' +
      '<textarea id="ke-export-ta" style="width:100%;height:50vh;margin-top:8px;font:11px Consolas,monospace"></textarea>' +
      '<button id="ke-export-close" style="margin-top:8px;padding:6px 12px">닫기</button></div>';
    document.documentElement.appendChild(box);
    var ta = box.querySelector('#ke-export-ta');
    ta.value = json;
    ta.select();
    box.querySelector('#ke-export-close').onclick = function () { box.remove(); };
    console.log(json);
    log('내보내기 - 클립보드에 복사했습니다 (' + S.steps.length + '단계)');
  }

  // ---- 단계 편집 ----------------------------------------------------------
  function removeStep(i) {
    if (i < 0 || i >= S.steps.length) return;
    var gone = S.steps.splice(i, 1)[0];
    if (S.idx > i) S.idx--;
    save(); log('삭제: ' + (gone.text || gone.sel).slice(0, 24));
  }
  function moveStep(i, dir) {
    var j = i + dir;
    if (i < 0 || i >= S.steps.length || j < 0 || j >= S.steps.length) return;
    var t = S.steps[i]; S.steps[i] = S.steps[j]; S.steps[j] = t;
    save(); emit();
  }
  function insertAt(i, step) {
    i = Math.max(0, Math.min(i, S.steps.length));
    S.steps.splice(i, 0, step);
    if (S.idx > i) S.idx++;
    save(); log('추가: ' + (step.text || step.sel).slice(0, 24) + ' (' + (i + 1) + '번째)');
  }
  function setStep(i, patch) {
    if (!S.steps[i]) return;
    for (var k in patch) S.steps[i][k] = patch[k];
    save(); emit();
  }
  function importJson(text) {
    var d = JSON.parse(text);
    var arr = Array.isArray(d) ? d : d.steps;
    if (!Array.isArray(arr)) throw new Error('steps 배열이 없습니다');
    for (var i = 0; i < arr.length; i++) {
      if (!arr[i] || (!arr[i].sel && !arr[i].text)) throw new Error((i + 1) + '번째에 sel/text 가 없습니다');
    }
    S.steps = arr; S.idx = 0; save();
    log('불러오기 ' + arr.length + '단계');
  }

  /* 재생 중 같은 단계에서 이만큼(ms) 막히면 예상 밖 모달일 가능성이 높다고 보고
   * autoconfirm.js 가 다시 끼어들도록 풀어준다 (정상 진행 중엔 계속 손을 떼서
   * 같은 버튼을 두 엔진이 동시에 누르는 경합을 피한다). */
  function stalledMs() { return waitingSince ? (Date.now() - waitingSince) : 0; }

  var API = {
    record: record, stop: stopRec, play: play, pause: pause,
    armForReload: armForReload,
    reset: reset, clear: clear, state: S, save: save,
    exportJson: exportJson, showExport: showExport, importJson: importJson,
    removeStep: removeStep, moveStep: moveStep, insertAt: insertAt, setStep: setStep,
    stalledMs: stalledMs, elapsed: elapsed,
    loadBaked: function () {
      S.steps = JSON.parse(JSON.stringify(baked()));
      S.idx = 0; save();
      log('내장 단계 ' + S.steps.length + '개를 불러왔습니다');
    },
    list: function () { console.table(S.steps); return S.steps; },
    onChange: function (fn) { listeners.push(fn); }
  };
  try { W.KE_REC = API; } catch (e) {}
  if (W !== window) { try { window.KE_REC = API; } catch (e) {} }
  if (S.playing) log('이전 재생을 이어서 진행합니다 (' + (S.idx + 1) + '/' + S.steps.length + ')');
})();

} catch (e) {
  console.error('[KE] recorder 로드 실패:', e);
}


// ---------- editor ----------
try {
/* ============================================================
 * editor.js  --  녹화한 단계 편집 UI
 *
 * 녹화는 한 번에 깔끔하게 되지 않는다. 실제로 이런 일이 생긴다:
 *   - 스크롤을 괜히 두 번 눌러서 불필요한 단계가 끼었다  -> 삭제
 *   - 마일리지 적용을 안 누르고 넘어갔다               -> 그 자리에 끼워넣기
 *   - 날짜 버튼은 라벨이 매일 바뀐다                    -> 셀렉터만 쓰도록 전환
 * 다시 처음부터 녹화하지 않고 고칠 수 있어야 한다.
 * ============================================================ */
(function () {
  'use strict';
  var W = window;
  try { if (typeof unsafeWindow !== 'undefined' && unsafeWindow) W = unsafeWindow; } catch (e) {}
  if (W.KE_EDIT || window.KE_EDIT) return;

  var U = W.KE_UTIL || window.KE_UTIL;

  function REC() { return W.KE_REC || window.KE_REC; }

  // ---- 엘리먼트 피커 -------------------------------------------------------
  var picking = null;

  function pick(cb) {
    stopPick();
    picking = cb;
    document.body.style.cursor = 'crosshair';
  }
  function stopPick() {
    picking = null;
    try { document.body.style.cursor = ''; } catch (e) {}
  }

  document.addEventListener('click', function (ev) {
    if (!picking) return;
    if (ev.target.closest && ev.target.closest('#ke-editor, #ke-hud')) return;
    ev.preventDefault();
    ev.stopPropagation();
    var el = ev.target.closest(U.CLICKABLE) || ev.target;
    var cb = picking;
    stopPick();
    cb({
      sel: U.cssPath(el),
      text: U.label(el),
      tag: el.tagName.toLowerCase(),
      url: location.pathname + location.search,
      selectorOnly: false
    });
  }, true);

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && picking) { stopPick(); render(); }
  }, true);

  // ---- UI ------------------------------------------------------------------
  var box = null;

  function close() { if (box) { box.remove(); box = null; } stopPick(); }

  function open() {
    if (box) { render(); return; }
    box = document.createElement('div');
    box.id = 'ke-editor';
    box.innerHTML =
      '<style>' +
      '#ke-editor{position:fixed;inset:0;z-index:2147483646;background:rgba(0,0,0,.55);' +
      'display:flex;align-items:center;justify-content:center;font:12px/1.5 -apple-system,"Malgun Gothic",sans-serif}' +
      '#ke-editor .w{background:#fff;border-radius:8px;width:min(620px,94vw);max-height:86vh;' +
      'display:flex;flex-direction:column;padding:14px;color:#222}' +
      '#ke-editor h4{margin:0 0 8px;font-size:14px;color:#0b4da2}' +
      '#ke-editor .rows{overflow:auto;flex:1;border:1px solid #eee;border-radius:4px}' +
      '#ke-editor .r{display:flex;align-items:center;gap:6px;padding:5px 7px;border-bottom:1px solid #f0f0f0}' +
      '#ke-editor .r:nth-child(odd){background:#fafafa}' +
      '#ke-editor .n{width:22px;color:#888;text-align:right;flex:none}' +
      '#ke-editor .t{flex:1;min-width:0}' +
      '#ke-editor .t b{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#ke-editor .t code{font-size:10px;color:#888;display:block;overflow:hidden;' +
      'text-overflow:ellipsis;white-space:nowrap}' +
      '#ke-editor button{cursor:pointer;border:1px solid #ccc;background:#fff;border-radius:3px;' +
      'padding:2px 6px;font:inherit;flex:none}' +
      '#ke-editor .ins{width:100%;border:1px dashed #bbb;color:#06c;background:#fff;margin:0;' +
      'border-radius:0;padding:1px;font-size:11px}' +
      '#ke-editor .foot{display:flex;gap:6px;margin-top:10px}' +
      '#ke-editor .foot button{padding:6px 10px}' +
      '#ke-editor .hint{font-size:11px;color:#666;margin-bottom:6px}' +
      '#ke-editor .so{font-size:10px;padding:1px 4px}' +
      '#ke-editor .so.on{background:#06c;color:#fff;border-color:#06c}' +
      '</style>' +
      '<div class="w"><h4>예매 단계 편집</h4>' +
      '<div class="hint">✕ 삭제 · ↑↓ 순서 · <b>＋</b> 그 자리에 빠진 단계 끼워넣기 · ' +
      '<b>고정</b> 은 라벨이 매일 바뀌는 버튼(날짜)에 사용</div>' +
      '<div class="rows" id="ke-ed-rows"></div>' +
      '<div class="foot">' +
      '<button id="ke-ed-add" style="flex:1">맨 끝에 추가</button>' +
      '<button id="ke-ed-json" style="flex:1">JSON</button>' +
      '<button id="ke-ed-close" style="flex:1">닫기</button>' +
      '</div></div>';
    document.documentElement.appendChild(box);
    box.querySelector('#ke-ed-close').onclick = close;
    box.querySelector('#ke-ed-add').onclick = function () { startInsert(REC().state.steps.length); };
    box.querySelector('#ke-ed-json').onclick = function () { close(); REC().showExport(); };
    box.addEventListener('click', function (e) { if (e.target === box) close(); });
    render();
  }

  function startInsert(at) {
    var r = REC();
    close();
    pick(function (step) {
      r.insertAt(at, step);
      open();
    });
    // 피커 안내는 HUD 토스트 대신 콘솔+커서로 (패널이 가려질 수 있어서)
    console.log('%c[KE_EDIT] 추가할 버튼을 클릭하세요 (ESC 취소)', 'color:#06c;font-weight:bold');
  }

  function render() {
    if (!box) return;
    var r = REC();
    if (!r) return;
    var steps = r.state.steps;
    var rows = box.querySelector('#ke-ed-rows');
    rows.innerHTML = '';

    function insertBar(at) {
      var b = document.createElement('button');
      b.className = 'ins';
      b.textContent = '＋ 여기에 추가';
      b.onclick = function () { startInsert(at); };
      rows.appendChild(b);
    }

    insertBar(0);
    steps.forEach(function (s, i) {
      var row = document.createElement('div');
      row.className = 'r';
      row.innerHTML =
        '<span class="n">' + (i + 1) + '</span>' +
        '<span class="t"><b></b><code></code></span>' +
        '<button class="so" title="셀렉터만 사용 (라벨 무시)">고정</button>' +
        '<button title="위로">↑</button><button title="아래로">↓</button>' +
        '<button title="삭제">✕</button>';
      row.querySelector('b').textContent = s.text || '(라벨 없음)';
      row.querySelector('code').textContent = s.sel || '';
      var so = row.querySelector('.so');
      if (s.selectorOnly) so.classList.add('on');
      so.onclick = function () { r.setStep(i, { selectorOnly: !s.selectorOnly }); render(); };
      var btns = row.querySelectorAll('button');
      btns[1].onclick = function () { r.moveStep(i, -1); render(); };
      btns[2].onclick = function () { r.moveStep(i, 1); render(); };
      btns[3].onclick = function () { r.removeStep(i); render(); };
      rows.appendChild(row);
      insertBar(i + 1);
    });

    if (!steps.length) {
      var empty = document.createElement('div');
      empty.style.cssText = 'padding:14px;color:#888;text-align:center';
      empty.textContent = '단계가 없습니다. 패널에서 ● 녹화 를 먼저 하세요.';
      rows.appendChild(empty);
    }
  }

  var API = { open: open, close: close, render: render, pick: pick };
  try { W.KE_EDIT = API; } catch (e) {}
  if (W !== window) { try { window.KE_EDIT = API; } catch (e) {} }
})();

} catch (e) {
  console.error('[KE] editor 로드 실패:', e);
}


// ---------- hud ----------
try {
/* ============================================================
 * hud.js  --  화면 우상단 컨트롤 패널
 *   - KST 서버시각 동기화 (Date 헤더 edge detection)
 *   - 오픈시각 카운트다운 -> 정시에 "새로고침 + 녹화 재생" 발사
 *   - 녹화/재생/편집 컨트롤
 *   - 재생이 멈추는 순간(결제 직전 / 전체 완료) 소리 알림
 *
 * 실제 발사 동작은 recorder.js 의 녹화 재생 하나뿐이다.
 * (예전엔 "조회 버튼 지정 + 좌석 헌팅" 경로도 있었지만, 녹화 재생이 그 일을
 *  전부 대신하므로 걷어냈다. 관련 컨트롤/상태도 같이 제거됨)
 * autoconfirm.js 가 먼저 로드되어 window.KE_AUTO 가 있어야 한다.
 * ============================================================ */
(function () {
  'use strict';

  var W = window;
  try { if (typeof unsafeWindow !== 'undefined' && unsafeWindow) W = unsafeWindow; } catch (e) {}
  function expose(k, v) {
    try { W[k] = v; } catch (e) {}
    if (W !== window) { try { window[k] = v; } catch (e) {} }
  }

  if (W.KE_HUD || window.KE_HUD) return;

  var LS = 'ke_award_hud_v1';
  var S = {
    targetKst: '',        // "2026-08-22 10:00:00"
    leadMs: 150,          // 네트워크 지연 보정: 이만큼 먼저 발사
    armed: false
  };
  try { Object.assign(S, JSON.parse(localStorage.getItem(LS) || '{}')); } catch (e) {}
  function save() { try { localStorage.setItem(LS, JSON.stringify(S)); } catch (e) {} }

  var offsetMs = 0;        // 서버시각 - 로컬시각
  var syncQuality = '미동기화';
  var timer = null;

  function REC() { return W.KE_REC || window.KE_REC; }

  // ---- 시각 --------------------------------------------------------------
  function nowSrv() { return Date.now() + offsetMs; }

  function fmtKst(ms) {
    return new Intl.DateTimeFormat('ko-KR', {
      timeZone: 'Asia/Seoul', hour12: false,
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit'
    }).format(new Date(ms)) + '.' + String(ms % 1000).padStart(3, '0');
  }

  // 한국은 서머타임이 없으므로 KST = UTC+9 고정
  function targetMs() {
    if (!S.targetKst) return NaN;
    var s = S.targetKst.trim().replace(' ', 'T');
    if (s.length === 16) s += ':00';
    return Date.parse(s + '+09:00');
  }

  /* Date 헤더는 1초 해상도라 그대로 쓰면 ±500ms 오차가 난다.
   * 짧은 간격으로 두드려 "초가 바뀌는 순간"을 잡으면 오차를 ~50ms 로 줄일 수 있다. */
  async function sync(log) {
    if (!/^https?:$/.test(location.protocol)) {
      syncQuality = '로컬 파일 - 로컬시각 사용';
      if (log) toast(syncQuality);
      return;                       // file:// 등에서는 fetch 가 무의미
    }
    var probes = 14, gap = 120, prevSec = null, edge = null, bestRtt = 1e9, coarse = 0;
    for (var i = 0; i < probes; i++) {
      var t0 = Date.now();
      var hdr;
      try {
        var res = await fetch(location.origin + '/favicon.ico?_t=' + t0,
                             { method: 'HEAD', cache: 'no-store' });
        hdr = res.headers.get('date');
      } catch (e) { hdr = null; }
      var t1 = Date.now();
      if (!hdr) continue;
      var srv = Date.parse(hdr), rtt = t1 - t0, mid = t0 + rtt / 2;
      if (rtt < bestRtt) { bestRtt = rtt; coarse = srv + 500 - mid; }
      if (prevSec !== null && srv !== prevSec) { edge = { srv: srv, at: mid }; break; }
      prevSec = srv;
      await new Promise(function (r) { setTimeout(r, gap); });
    }
    if (edge) {
      // edge.srv 초가 시작된 시점이 edge.at 직전(<=gap) 이다
      offsetMs = Math.round(edge.srv - (edge.at - gap / 2));
      syncQuality = '정밀 (오차 ~' + Math.round(gap / 2 + bestRtt / 2) + 'ms)';
    } else if (bestRtt < 1e9) {
      offsetMs = Math.round(coarse);
      syncQuality = '개략 (오차 ~500ms)';
    } else {
      syncQuality = '동기화 실패 - 로컬시각 사용';
    }
    if (log) toast('시각 동기화: ' + syncQuality + ' / offset ' + offsetMs + 'ms');
    save();
  }

  // ---- 발사 --------------------------------------------------------------
  /* 정시 동작: "새로고침이 끝난 뒤에 처음부터 재생" 을 예약하고 새로고침한다.
   * 여기서 바로 play() 를 부르면 안 된다 - recorder 의 tick 이 낡은 화면에서 1단계
   * (그날 새로 열린 날짜)를 눌러버리고, 이어지는 새로고침이 그 선택을 통째로 날린다.
   * 예약은 localStorage 에 남아 새 문서가 뜰 때 recorder 가 스스로 집어간다. */
  function fire(reason) {
    var R = REC();
    if (!R || !R.state.steps.length) {
      toast('녹화된 단계가 없습니다 - 먼저 ● 녹화 하세요', true);
      return false;
    }
    if (!R.armForReload()) return false;
    // 이후 흐름은 recorder 가 몬다. HUD 는 무장을 풀어 카운트다운을 멈춘다.
    S.armed = false;
    save();
    toast('발사 (' + reason + ') - 새로고침 후 재생 @ ' + fmtKst(nowSrv()));
    setTimeout(function () { location.reload(); }, 0);
    return true;
  }

  // ---- 알림 --------------------------------------------------------------
  /* 재생이 멈추는 순간 = 사람이 개입해야 하는 순간.
   * 끝까지 간 것과 중간에 막힌 것은 대응이 전혀 다르므로 소리와 제목을 다르게 낸다.
   * (같은 소리를 내면 막혀서 멈춘 걸 "완료" 로 오해하게 된다) */
  function beep(freqs, dur) {
    try {
      var ac = new (window.AudioContext || window.webkitAudioContext)();
      freqs.forEach(function (f, i) {
        var o = ac.createOscillator(), g = ac.createGain();
        o.connect(g); g.connect(ac.destination);
        o.frequency.value = f; g.gain.value = 0.2;
        o.start(ac.currentTime + i * dur); o.stop(ac.currentTime + i * dur + dur * 0.8);
      });
    } catch (e) {}
  }

  function notify(msg, ok) {
    setStatus(msg || '재생이 멈췄습니다');
    if (ok) beep([880, 1175, 1568], 0.16);        // 올라가는 3음 = 끝까지 갔음
    else    beep([440, 330, 247, 196], 0.22);     // 내려가는 4음 = 막혔으니 봐야 함
    var tag = ok ? '★완료★ ' : '⚠멈춤⚠ ';
    document.title = tag + document.title.replace(/^(★완료★|⚠멈춤⚠)\s*/, '');
  }

  // ---- UI ----------------------------------------------------------------
  var root, statusEl, clockEl, cdEl, toastEl;

  // 패널에는 항상 표시. 콘솔은 경고/오류만 (평상시 로그로 콘솔을 채우지 않는다)
  function toast(msg, warn) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.style.color = warn ? '#c00' : '#060';
    if (warn) console.warn('[KE_HUD] ' + msg);
  }
  function setStatus(msg) { if (statusEl) statusEl.textContent = msg; }

  function tick() {
    if (!clockEl) return;
    var n = nowSrv();
    clockEl.textContent = fmtKst(n) + '  (' + syncQuality + ')';
    var T = targetMs();
    if (!isNaN(T)) {
      var d = T - S.leadMs - n;
      if (d > 0) {
        var s = Math.floor(d / 1000);
        cdEl.textContent = 'T-' + String(Math.floor(s / 3600)).padStart(2, '0') + ':' +
          String(Math.floor(s / 60) % 60).padStart(2, '0') + ':' +
          String(s % 60).padStart(2, '0') + '.' + String(d % 1000).padStart(3, '0');
        cdEl.style.color = d < 10000 ? '#c00' : '#333';
      } else {
        cdEl.textContent = 'T+' + Math.floor(-d / 1000) + 's';
        cdEl.style.color = '#c00';
      }
    } else {
      cdEl.textContent = '오픈시각 미설정';
    }
  }

  function schedule() {
    if (timer) { clearTimeout(timer); timer = null; }
    var T = targetMs();
    if (isNaN(T)) { toast('오픈시각 형식 오류 (예: 2026-08-22 10:00:00)', true); return; }
    var wait = T - S.leadMs - nowSrv();
    if (wait < 0) { toast('이미 지난 시각입니다', true); return; }
    // 남은 시간이 길면 쪼개서 재계산 (setTimeout 드리프트 보정)
    (function step() {
      var left = targetMs() - S.leadMs - nowSrv();
      if (left <= 0) { fire('정시'); return; }
      timer = setTimeout(step, left > 5000 ? Math.min(left - 3000, 60000) : Math.max(left - 20, 1));
    })();
    setStatus('예약 대기 중 - ' + fmtKst(T - S.leadMs) + ' 발사 예정');
  }

  /** targetKst 입력칸이 쓰는 "YYYY-MM-DD HH:MM:SS" (KST) 형식으로 변환 */
  function kstInput(ms) {
    var p = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Seoul', hourCycle: 'h23',
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit'
    }).formatToParts(new Date(ms)).reduce(function (a, x) { a[x.type] = x.value; return a; }, {});
    return p.year + '-' + p.month + '-' + p.day + ' ' + p.hour + ':' + p.minute + ':' + p.second;
  }

  /* 연습: 오픈시각을 몇 초 뒤로 잡고 그대로 무장한다.
   * 카운트다운 -> 정시 발사 -> 새로고침 -> 재생까지 실전과 같은 경로를 탄다. */
  function rehearse(sec) {
    var R = REC();
    if (!R || !R.state.steps.length) {
      toast('녹화된 단계가 없습니다 - 먼저 ● 녹화 하세요', true);
      return;
    }
    // 입력칸은 초 단위라 그냥 넣으면 밀리초가 잘려 최대 1초 일찍 발사된다. 초 경계로 올림.
    S.targetKst = kstInput(Math.ceil((nowSrv() + sec * 1000) / 1000) * 1000);
    S.armed = true;
    save(); render(); schedule();
    toast('연습: ' + sec + '초 뒤 발사합니다');
  }

  /** 녹화/재생 상태를 패널에 반영 + 재생이 멈추는 순간 알림 */
  var wasPlaying = false;
  function renderRec() {
    if (!root) return;
    var R = REC();
    if (!R) return;
    var st = R.state;
    var lab = root.querySelector('#ke-step-label');
    var rec = root.querySelector('#ke-rec');
    var play = root.querySelector('#ke-play');
    var msg = root.querySelector('#ke-rec-msg');
    if (lab) {
      var el = R.elapsed ? R.elapsed() : 0;
      lab.textContent = st.steps.length + '단계'
        + (st.playing ? ' - 재생 중 ' + (st.idx + 1) + '/' + st.steps.length
                      : (st.idx ? ' (' + st.idx + '까지 진행됨)' : ''))
        + (el ? '  ' + el.toFixed(1) + 's' : '');
    }
    if (rec) {
      rec.textContent = st.recording ? '■ 녹화중지' : '● 녹화';
      rec.style.background = st.recording ? '#c33' : '#a0f';
    }
    if (play) {
      play.textContent = st.playing ? '■ 정지' : '▶ 재생';
      play.style.background = st.playing ? '#c33' : '#06c';
    }
    if (msg) msg.textContent = st.message || '';

    /* 재생 중이다가 멈췄으면 사람을 부른다.
     * "끝까지 감"(결제 단계 도달 / 전 단계 완료) 과 "중간에 막힘"(요소 못 찾음 /
     * 건너뜀 / 목표 날짜 불일치) 을 구분해서 알린다. */
    if (wasPlaying && !st.playing) {
      var m = st.message || '';
      // 사용자가 직접 정지한 건 알릴 필요 없다
      if (!/사용자 중지/.test(m)) {
        var ok = st.steps.length > 0 && st.idx >= st.steps.length
                 && !/건너뛰|못 찾|다릅니다/.test(m);
        notify(m, ok);
      }
    }
    wasPlaying = st.playing;
  }

  function render() {
    if (!root) return;
    renderRec();
    var A = W.KE_AUTO || window.KE_AUTO;
    var ab = root.querySelector('#ke-auto');
    if (ab && A) {
      ab.textContent = A.enabled ? '자동클릭 ON' : '자동클릭 OFF';
      ab.style.background = A.enabled ? '#2a7' : '#888';
    }
    root.querySelector('#ke-target').value = S.targetKst;
    root.querySelector('#ke-lead').value = S.leadMs;
    var R2 = REC();
    if (R2) {
      root.querySelector('#ke-cabin').value = R2.state.cabin || '일반석';
      root.querySelector('#ke-expect').value = R2.state.expectDate || '';
      root.querySelector('#ke-allowpay').checked = !!R2.state.allowPay;
    }
    var arm = root.querySelector('#ke-arm');
    arm.textContent = S.armed ? '■ 정지' : '▶ 대기 시작';
    arm.style.background = S.armed ? '#c33' : '#2a7';
  }

  function build() {
    root = document.createElement('div');
    root.id = 'ke-hud';
    root.innerHTML =
      '<style>' +
      '#ke-hud{position:fixed;top:10px;right:10px;z-index:2147483647;width:270px;' +
      'font:12px/1.5 -apple-system,"Malgun Gothic",sans-serif;background:#fff;color:#222;' +
      'border:2px solid #0b4da2;border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.25);padding:10px}' +
      '#ke-hud h4{margin:0 0 6px;font-size:13px;color:#0b4da2}' +
      '#ke-hud label{display:block;margin:5px 0 1px;font-size:11px;color:#666}' +
      '#ke-hud input{width:100%;box-sizing:border-box;padding:3px 5px;border:1px solid #bbb;border-radius:3px;font:inherit}' +
      '#ke-hud button{cursor:pointer;border:0;border-radius:4px;color:#fff;padding:5px 8px;font:inherit;margin-top:6px}' +
      '#ke-clock{font-family:Consolas,monospace;font-size:11px;color:#0b4da2}' +
      '#ke-cd{font-family:Consolas,monospace;font-size:19px;font-weight:700;text-align:center;margin:4px 0}' +
      '#ke-status{font-size:11px;color:#444;min-height:15px;margin-top:4px}' +
      '#ke-toast{font-size:11px;min-height:15px}' +
      '#ke-hud .row{display:flex;gap:5px}#ke-hud .row>*{flex:1}' +
      '</style>' +
      '<h4>KE 마일리지 예매 보조 <span style="float:right;cursor:pointer" id="ke-min">_</span></h4>' +
      '<div id="ke-body">' +
      '<div id="ke-clock">--</div><div id="ke-cd">--</div>' +
      '<label>오픈시각 (KST)</label><input id="ke-target" placeholder="2026-08-22 10:00:00">' +
      '<label>선발사(ms)</label><input id="ke-lead" type="number">' +
      '<div class="row">' +
      '<button id="ke-sync" style="background:#666">시각 동기</button>' +
      '<button id="ke-auto" style="background:#2a7">자동클릭 ON</button></div>' +
      '<hr style="border:0;border-top:1px solid #ddd;margin:8px 0">' +
      '<label>좌석 등급</label>' +
      '<select id="ke-cabin" style="width:100%;box-sizing:border-box;padding:3px 5px;' +
      'border:1px solid #bbb;border-radius:3px;font:inherit">' +
      '<option value="일반석">일반석 (연습용)</option>' +
      '<option value="프레스티지">프레스티지 (실전)</option>' +
      '<option value="프리미엄">프리미엄</option>' +
      '<option value="일등석">일등석</option>' +
      '</select>' +
      '<label>목표 날짜 <span style="color:#999">(비우면 검사 안 함)</span></label>' +
      '<input id="ke-expect" placeholder="08월 17일">' +
      '<label style="display:flex;align-items:center;gap:5px;margin-top:6px;color:#c00">' +
      '<input type="checkbox" id="ke-allowpay" style="width:auto">' +
      '결제하기까지 자동 (결제창 열림)</label>' +
      '<hr style="border:0;border-top:1px solid #ddd;margin:8px 0">' +
      '<label>예매 단계: <b id="ke-step-label">0단계</b></label>' +
      '<div class="row">' +
      '<button id="ke-rec" style="background:#a0f">● 녹화</button>' +
      '<button id="ke-play" style="background:#06c">▶ 재생</button>' +
      '<button id="ke-clear" style="background:#888">삭제</button></div>' +
      '<button id="ke-edit" style="background:#06c;width:100%">단계 편집</button>' +
      '<button id="ke-export" style="background:#555;width:100%">내보내기 (steps.json 용)</button>' +
      '<div id="ke-rec-msg" style="font-size:11px;color:#606"></div>' +
      '<hr style="border:0;border-top:1px solid #ddd;margin:8px 0">' +
      '<button id="ke-rehearse" style="background:#c80;width:100%">연습 (10초 뒤 발사)</button>' +
      '<button id="ke-arm" style="background:#2a7;width:100%">▶ 대기 시작</button>' +
      '<div id="ke-status"></div><div id="ke-toast"></div>' +
      '</div>';
    document.documentElement.appendChild(root);

    statusEl = root.querySelector('#ke-status');
    clockEl = root.querySelector('#ke-clock');
    cdEl = root.querySelector('#ke-cd');
    toastEl = root.querySelector('#ke-toast');

    root.querySelector('#ke-min').onclick = function () {
      var b = root.querySelector('#ke-body');
      b.style.display = b.style.display === 'none' ? '' : 'none';
    };
    root.querySelector('#ke-sync').onclick = function () { sync(true); };
    root.querySelector('#ke-rehearse').onclick = function () { rehearse(10); };

    var R = REC();
    if (R) {
      root.querySelector('#ke-rec').onclick = function () {
        R.state.recording ? R.stop() : R.record();
        renderRec();
      };
      root.querySelector('#ke-play').onclick = function () {
        if (R.state.playing) { R.pause('사용자 중지'); }
        else {
          // 처음부터 다시 할지, 끊긴 데서 이어갈지
          if (R.state.idx > 0 && R.state.idx < R.state.steps.length) {
            if (confirm(R.state.idx + '단계까지 진행돼 있습니다.\n확인=이어서, 취소=처음부터')) {
              /* 이어서 */
            } else { R.reset(); }
          } else { R.reset(); }
          R.play();
        }
        renderRec();
      };
      root.querySelector('#ke-edit').onclick = function () {
        var E = W.KE_EDIT || window.KE_EDIT;
        if (E) E.open(); else toast('편집기를 불러오지 못했습니다', true);
      };
      root.querySelector('#ke-export').onclick = function () { R.showExport(); };
      root.querySelector('#ke-clear').onclick = function () {
        if (confirm('녹화된 단계를 모두 지울까요?')) { R.clear(); renderRec(); }
      };
      root.querySelector('#ke-cabin').onchange = function (e) {
        R.state.cabin = e.target.value; R.save();
        toast('좌석 등급: ' + e.target.value);
      };
      root.querySelector('#ke-expect').onchange = function (e) {
        R.state.expectDate = e.target.value.trim(); R.save();
        toast(R.state.expectDate
          ? '목표 날짜 ' + R.state.expectDate + ' - 다르면 멈춥니다'
          : '목표 날짜 검사 끔');
      };
      /* 기본은 꺼짐. 켜면 결제하기까지 눌러 결제창(네이버페이 등)을 띄운다.
       * 결제창에서 다시 본인 인증이 필요하므로 여기서 바로 돈이 빠지지는 않지만,
       * 되돌리기 어려운 지점이라 매번 눈에 보이게 체크하도록 둔다. */
      root.querySelector('#ke-allowpay').onchange = function (e) {
        R.state.allowPay = !!e.target.checked; R.save();
        toast(R.state.allowPay
          ? '결제하기까지 자동 - 결제창이 열립니다'
          : '결제 직전에서 멈춥니다 (기본)', R.state.allowPay);
      };
      R.onChange(renderRec);
      renderRec();
    }
    root.querySelector('#ke-auto').onclick = function () {
      var A = W.KE_AUTO || window.KE_AUTO;
      if (!A) { toast('자동클릭 엔진이 없습니다', true); return; }
      A.enabled ? A.off() : A.on();
      render();
      toast('자동클릭 ' + (A.enabled ? 'ON - 확인/동의 모달을 자동 통과합니다'
                                    : 'OFF - 아무것도 누르지 않습니다'));
    };
    root.querySelector('#ke-target').onchange = function (e) { S.targetKst = e.target.value; save(); };
    root.querySelector('#ke-lead').onchange = function (e) { S.leadMs = +e.target.value || 0; save(); };
    root.querySelector('#ke-arm').onclick = function () {
      S.armed = !S.armed; save(); render();
      if (S.armed) { schedule(); }
      else { if (timer) clearTimeout(timer); timer = null; setStatus('정지됨'); }
    };

    render();
    setInterval(tick, 50);
    sync(false);
  }

  /* document-start 에 주입되면 body 가 아직 없다. 게다가 SPA 가 화면을 갈아끼우면서
   * 패널을 통째로 걷어낼 수 있으므로, 사라졌으면 다시 붙인다. */
  function mount() {
    if (!document.documentElement) return;
    if (root && root.isConnected) return;
    if (root) { document.documentElement.appendChild(root); return; }  // 떨어져 나간 것 복구
    try {
      build();
    } catch (e) {
      console.error('[KE_HUD] 패널 생성 실패', e);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  }
  mount();
  setInterval(mount, 1000);   // 사라지면 1초 안에 복구

  expose('KE_HUD', { sync: sync, fire: fire, state: S, mount: mount,
                     rehearse: rehearse,
                     offset: function () { return offsetMs; } });
  console.log('%c[KE_HUD] v1.1.0 loaded', 'color:#0b4da2;font-weight:bold');
})();

} catch (e) {
  console.error('[KE] hud 로드 실패:', e);
}
