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
