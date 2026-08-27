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
 * 단계를 건너뛰지 않는다
 *   예전에는 "현재 단계를 못 찾으면 뒤쪽 단계가 눌릴 만한지 보고 건너뛰는" 기능이
 *   있었다. 라벨 추측 클릭 엔진이 같은 버튼을 먼저 눌러버리던 시절의 보정책이었는데,
 *   그 엔진을 걷어낸 뒤로는 오판만 낳았다: #btnConfirm 처럼 모달이 닫혀 있어도 DOM 에
 *   남아 있는 요소를 보고 "동의는 이미 지나갔다" 고 판단해 동의 두 개를 통째로
 *   건너뛰었다(실측). 못 찾으면 기다렸다가 직전 단계를 다시 누르고, 그래도 안 되면
 *   멈춰서 사람을 부른다. 조용히 건너뛰는 것보다 멈추는 게 낫다.
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
    /* 재생이 끝났지만 사람이 봐야 하는 상태인가.
     * 예전에는 skipped/skippedList 로 "건너뛴 단계"를 셌는데, 건너뛰기 기능을
     * 없애면서 아무도 값을 올리지 않는 죽은 장치가 됐다. 그런데 hud 의 완료 판정은
     * 그 값을 계속 보고 있어서 "안전장치가 있는 것처럼 보이는" 상태였다.
     * 실제로 문제가 생긴 지점에서만 켜는 플래그로 바꾼다. */
    problem: false,
    lastOpen: null,       // 사이트가 window.open 을 부른 결과 {at, ok}. 결제창이
                          // 실제로 떴는지 확인하는 유일한 방법이다
    message: '',          // 패널 상태줄. 여기 선언이 없으면 load() 가 걸러내서
                          // 마지막 단계가 페이지를 이동시킨 경우 왜 멈췄는지가 사라진다
    expectDate: '',       // 목표 날짜(예: "08-27"). 넣으면 자동 감지한 최신 오픈일이
                          // 이것과 다를 때 클릭하지 않고 멈춘다 (엉뚱한 날 예매 방지)
    cabin: '일반석',       // 좌석 등급. 연습은 '일반석', 실전은 '프레스티지'
    /* 결제하기까지 자동으로 누른다 (사용자 요청으로 기본 켜짐).
     * 결제창에서 다시 본인 인증이 필요하므로 여기서 바로 돈이 빠지지는 않는다.
     * 패널 체크박스로 끌 수 있다.
     *
     * 주의: 실측에서 이 단계가 실행됐는데도 결제창이 뜨지 않은 적이 있다.
     * 브라우저가 스크립트로 만든 클릭(isTrusted=false)에는 사용자 조작 권한을
     * 주지 않아 새 창을 막는 경우가 있는데, 그러면 "눌렀다" 는 로그만 남는다.
     * 그래서 재생이 끝나면 결제창이 실제로 떴는지 확인하라고 알린다. */
    allowPay: true,
    times: [],            // 단계별 소요시간 [{n, label, ms}]. 어디서 시간을 쓰는지
                          // 추측하지 않고 재기 위한 것 - 페이지 이동을 넘어 유지된다
    stepStartedAt: 0,     // 지금 단계를 시작한 시각
    openWaitSince: 0,     // 목표 날짜가 열리기를 기다리기 시작한 시각(페이지 이동을 넘어 유지)
    openRetryMs: 1200,    // 목표 날짜가 없을 때 새로고침 간격 (서버 부담 하한)
    openWaitMaxMs: 180000,// 이만큼 기다려도 안 열리면 사람을 부른다
    stepTimeoutMs: 20000, // 한 단계에서 요소를 못 찾고 버티는 한계
    optionalMs: 400,      // optional 단계 대기 (주 수단은 onlyIfPrev - 대기가 없다)
    gapMs: 80,            // 클릭 사이 최소 간격
    settleMs: 250,        // 이만큼 화면이 잠잠해야 다음 단계를 누른다
    maxSettleMs: 2500,    // 계속 바뀌기만 하면 이 시간 뒤에는 그냥 누른다
    retryClickMs: 1200,   // 막혔을 때 직전 단계를 다시 눌러보는 간격
    source: 'baked',      // 지금 단계가 어디서 왔는지: 'baked'(steps.json) | 'local'(직접 녹화)
    bakedSig: ''          // 적용한 내장본의 지문. 바뀌면 내장본으로 덮는다
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

  /* 사이트는 결제창을 window.open 으로 띄운다. 스크립트가 만든 클릭에는 브라우저가
   * 사용자 조작 권한을 주지 않아 팝업이 차단될 수 있는데, 그러면 "눌렀다" 는 기록만
   * 남고 창은 안 뜬다. 열렸는지 알 방법이 없으므로 open 을 감싸서 결과를 남긴다. */
  (function wrapOpen() {
    try {
      var orig = W.open;
      if (typeof orig !== 'function' || orig.__keWrapped) return;
      var wrapped = function () {
        var w = orig.apply(this, arguments);
        try { S.lastOpen = { at: Date.now(), ok: !!w }; save(); } catch (e) {}
        return w;
      };
      wrapped.__keWrapped = true;
      W.open = wrapped;
    } catch (e) {}
  })();

  /* 빌드 시 steps.json 에서 구워 넣은 기본 단계.
   *
   * 우선순위: 검토를 거쳐 git 에 올린 steps.json 이 브라우저에 남은 녹화보다 세다.
   * 예전에는 반대였는데, 새 스크립트를 붙여넣어도 브라우저에 남아있던 옛날 녹화가
   * 계속 이겨서 정리 전 단계로 돌아가는 사고가 났다.
   *
   * 그렇다고 매번 덮으면 방금 녹화한 게 새로고침마다 날아간다. 그래서 내장본의
   * 지문을 같이 저장해두고, 지문이 바뀔 때(=새 빌드를 붙여넣었을 때)만 덮는다.
   * 지문이 같으면 이 브라우저에서 녹화/편집한 내용을 그대로 둔다. */
  function baked() { return (W.KE_STEPS_BAKED || window.KE_STEPS_BAKED || []); }

  function sigOf(steps) {
    var s = JSON.stringify(steps || []);
    var h = 5381;
    for (var i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
    return (steps || []).length + ':' + (h >>> 0).toString(36);
  }

  function adoptBaked(why) {
    S.steps = JSON.parse(JSON.stringify(baked()));
    S.bakedSig = sigOf(baked());
    S.source = 'baked';
    S.idx = 0;
    save();
    if (why) console.log('%c[KE_REC] 내장 단계 ' + S.steps.length + '개 적용 (' + why + ')',
                         'color:#a0f;font-weight:bold');
  }

  if (baked().length && S.bakedSig !== sigOf(baked())) {
    adoptBaked(S.steps.length ? '스크립트가 갱신되어 이전 녹화를 대체함' : '최초 적용');
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
  /* 단계가 넘어갈 때마다 얼마나 걸렸는지 남긴다.
   * "30초 걸리는데 줄일 수 있나" 는 어디서 쓰는지 알아야 답할 수 있다. */
  function markStep(n, label) {
    var t = Date.now();
    if (S.stepStartedAt) {
      if (!S.times) S.times = [];
      S.times.push({ n: n, label: String(label || '').slice(0, 22), ms: t - S.stepStartedAt });
    }
    S.stepStartedAt = t;
  }

  function timeReport() {
    var a = (S.times || []).slice();
    if (!a.length) return '';
    a.sort(function (x, y) { return y.ms - x.ms; });
    return '  느린 단계: ' + a.slice(0, 3).map(function (x) {
      return x.n + '.' + x.label + ' ' + (x.ms / 1000).toFixed(1) + 's';
    }).join(', ');
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
    S.source = 'local';       // 이제부터는 이 브라우저에서 만든 것
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

  /* 앞 단계의 결과가 화면에 반영되기 전에 다음 단계를 누르면 클릭이 그냥 무시된다.
   * 실측에서 승객정보 확인(6.12s) 0.2초 뒤에 연락처 확인(6.32s)을 눌렀고, 그 클릭이
   * 먹지 않아 이후 단계가 전부 막혔다. 사람이 녹화할 때는 이 사이가 몇 초였다.
   * 그래서 "화면이 잠잠해질 때까지" 기다렸다가 다음을 누른다.
   * 우리 패널은 시계를 50ms 마다 다시 그리므로 그 변화는 세지 않는다. */
  var lastMutAt = 0;
  var retries = 0;
  var blockedEl = null;   // 찾았지만 무언가에 가려 못 누르는 요소
  var lastLabel = '';     // 직전 단계에서 실제로 누른 요소의 라벨 (onlyIfPrev 판단용)
  var lastOpenReloadAt = 0;  // 목표 날짜를 기다리며 마지막으로 새로고침한 시각
  var scrollClicks = 0;   // 이번 스크롤 단계에서 몇 번 눌렀는지
  var ensurePhase = 0;    // ensure 진행 단계: 0 시작 / 1 목록 열림 / 2 적용 대기
  var OURS = '#ke-hud, #ke-editor, #ke-export';
  new MutationObserver(function (muts) {
    for (var i = 0; i < muts.length; i++) {
      var t = muts[i].target;
      var el = t && t.nodeType === 1 ? t : (t && t.parentElement);
      if (el && el.closest && el.closest(OURS)) continue;
      lastMutAt = Date.now();
      return;
    }
  }).observe(document, { childList: true, subtree: true, attributes: true });

  /* 다시 눌러도 되는 단계인가.
   * 확인/다음/검색 같은 제출 버튼은 두 번 눌러도 결과가 같지만, 동의/체크는 토글이라
   * 다시 누르면 꺼진다. steps.json 에서 단계별로 noRetry 로 못박을 수도 있다. */
  var TOGGLEY = /동의|체크|선택|agree|check/i;
  function retryable(step) {
    if (!step || step.noRetry || isPay(step)) return false;
    return !TOGGLEY.test(step.text || '');
  }

  /* 막혀 있으면 직전 단계를 다시 눌러본다.
   * 사이트가 앞 단계를 처리하는 중에 눌러 클릭이 그냥 무시되는 일이 실제로 있었다
   * (연락처 확인을 눌렀는데 화면이 그대로였고 다음 단계가 나타나지 않음).
   * 왜 무시됐는지는 밖에서 알 수 없으므로, 원인을 따지지 않고 다시 누른다. */
  function retryPrevClick(now) {
    // 횟수로 끊지 않는다. 단계 제한시간(stepTimeoutMs)까지 계속 눌러보고,
    // 그래도 안 되면 아래에서 멈추면서 사람을 부른다.
    if (S.idx === 0) return false;
    if (blockedEl) return false;   // 가려서 못 누르는 거면 다시 눌러봤자다
    if (now - lastClickAt < S.retryClickMs) return false;
    var prev = S.steps[S.idx - 1];
    if (!retryable(prev)) return false;
    var el = locate(prev);
    if (!el) return false;
    retries++;
    lastClickAt = now;
    U.fireClick(el);
    log('단계 ' + (S.idx + 1) + ' 가 안 나타나 직전 단계를 다시 누름 (' + retries + '회째): '
        + String(prev.text || prev.sel).slice(0, 24));
    return true;
  }

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
    if (!S.startedAt || S.idx === 0) { S.startedAt = Date.now(); S.problem = false; }
    scrollClicks = 0;   // 중간에 멈췄다 다시 재생할 때 스크롤 상태가 남으면 안 된다
    lastLabel = '';
    S.openWaitSince = 0;
    S.times = []; S.stepStartedAt = Date.now();
    ensurePhase = 0;
    retries = 0;
    waitingSince = 0;
    save();
    log('재생 시작 (' + (S.idx + 1) + '/' + S.steps.length + ')');
  }
  /* 재생을 끝내며 결과를 알린다. 문제가 있으면 message 에 그 사실이 남아
   * hud 의 알림 판정이 ★완료★ 대신 ⚠멈춤⚠ 을 내도록 한다. */
  function finish(why, problem) {
    S.problem = !!problem;
    pause(why + timeReport());
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
    S.problem = false;
    scrollClicks = 0;
    save();
    log('새로고침 후 처음부터 재생 예약됨');
    return true;
  }
  function reset() { S.idx = 0; save(); log('처음 단계로'); }
  /* '삭제' 는 빈 상태로 두는 것보다 내장본으로 되돌리는 게 쓸모 있다.
   * 녹화가 꼬였을 때 되돌아갈 기준점이 생긴다. */
  function clear() {
    S.playing = false; S.recording = false; S.idx = 0;
    if (baked().length) { adoptBaked('삭제 -> 내장본 복원'); log('내장 단계 ' + S.steps.length + '개로 되돌렸습니다'); }
    else { S.steps = []; S.source = 'local'; save(); log('삭제됨'); }
  }

  /* 한 단계가 가리키는 요소를 찾는다.
   * dynamicDate: 특정 날짜 텍스트/셀렉터 대신 "지금 예약 가능한 것 중 가장 나중 날짜".
   *   마일리지는 매일 09:00 KST 에 하루치씩 새로 열려서, 녹화한 날짜는 다음날 못 쓴다.
   * dynamicCabin: 패널에서 고른 좌석 등급의 항공편 카드 (연습=일반석 / 실전=프레스티지). */
  function locate(step) {
    if (step.dynamicDate) return U.findLatestOpenDate(step.idPrefix);
    if (step.dynamicCabin) return U.findCabin(S.cabin);
    var el = U.findEl(step.sel, step.text, { selectorOnly: step.selectorOnly });
    if (el) return el;
    /* alt: 화면에 따라 있을 수도 없을 수도 있는 선택지. 앞에서부터 찾아지는 것 하나만
     * 누른다. 결제수단이 그렇다 - 가는 편에는 네이버페이가 있는데 오는 편에는 없어서
     * 신용카드로 가야 한다. 둘 다 누르면 마지막 것으로 바뀌므로 하나만 골라야 한다. */
    if (step.alt) {
      for (var i = 0; i < step.alt.length; i++) {
        var a = step.alt[i];
        el = U.findEl(a.sel, a.text, { selectorOnly: a.selectorOnly });
        if (el) return el;
      }
    }
    return null;
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

    /* 앞 단계 결과가 반영되기 전에 누르면 클릭이 무시된다. 화면이 잠잠해질 때까지
     * 기다린다. 계속 바뀌기만 하는 화면도 있으므로 상한을 둔다. */
    if (S.idx > 0 && lastClickAt) {
      var quiet = now - Math.max(lastMutAt, lastClickAt);
      if (quiet < S.settleMs && now - lastClickAt < S.maxSettleMs) return;
    }

    /* ensure 단계: "지금 값이 want 면 그대로 두고, 아니면 골라서 맞춘다".
     * 통화(KRW/USD)처럼 화면 상태에 따라 눌러야 할 수도 아닐 수도 있는 것에 쓴다.
     * 좌석 등급을 바꿀 때마다 통화가 되돌아가는 경우가 있어서, 매번 확인해야 한다.
     *   1) 컨트롤 라벨에 want 가 이미 있으면 -> 통과
     *   2) 없으면 컨트롤을 눌러 목록을 연다
     *   3) 목록에서 want 가 든 항목을 눌러 맞춘다 */
    /* ensure 단계: "지금 값이 want 면 그대로 두고, 아니면 골라서 맞춘다".
     * 통화(KRW/USD)나 카드 종류처럼 화면 상태에 따라 손대야 할 수도 아닐 수도 있는 것.
     *
     * 실제 대한항공 통화 선택은 3단계다: #currencyBtn 을 눌러 모달을 열고 -> KRW 라디오
     * 라벨을 고르고 -> [적용] 을 눌러야 반영된다. 적용을 빠뜨리면 모달만 열렸다 닫히고
     * 통화는 그대로다. 그래서 optionSel/applySel 을 단계에 적어둔다.
     * 네이티브 <select> 면 클릭으로는 목록이 안 열리므로 value 를 직접 바꾼다. */
    /* onlyIfPrev: 직전 단계에서 이걸 눌렀을 때만 진행한다.
     * 카드 종류는 카드 결제를 골랐을 때만 나타난다. 예전엔 "없으면 2.5초 기다렸다
     * 넘어감" 이었는데, 09:00 경쟁에서 의미 없이 2.5초를 버리는 짓이다.
     * 앞에서 무엇을 눌렀는지는 이미 알고 있으니 기다릴 이유가 없다. */
    if (step.onlyIfPrev && lastLabel.indexOf(step.onlyIfPrev) === -1) {
      S.idx++; retries = 0; waitingSince = 0; save();
      log('재생 ' + S.idx + '/' + S.steps.length + ': 해당 없어 건너뜀 ('
          + step.onlyIfPrev + ' 을 안 골랐음)');
      return;
    }

    if (step.ensure) {
      var ctrl = (step.sel ? U.findEl(step.sel, '', { selectorOnly: true }) : null)
                 || U.findContaining(step.text);

    /* changed=true 는 실제로 값을 바꿨다는 뜻이다.
     * 통화를 바꾸면 사이트가 화면을 다시 그리면서 처음 페이지로 돌아간다. 그대로
     * 다음 단계로 가면 그 요소가 있을 리 없어 통째로 막힌다(실측). restartFrom 이
     * 있으면 그 단계부터 다시 밟는다 - 두 번째에는 이미 KRW 라 통과하므로 반복되지
     * 않는다. 이미 맞아서 아무것도 안 바꿨으면 되돌아갈 이유가 없다. */
      var doneEnsure = function (how, changed) {
        ensurePhase = 0;
        retries = 0; waitingSince = 0; lastClickAt = now;
        if (changed && typeof step.restartFrom === 'number') {
          S.idx = step.restartFrom;
          save();
          log(how + ' - 화면이 되돌아가므로 ' + (step.restartFrom + 1) + '단계부터 다시 진행합니다');
          return;
        }
        markStep(S.idx + 1, step.ensure || step.text);
        S.idx++; save();
        log('재생 ' + S.idx + '/' + S.steps.length + ': ' + how + '  [' + secs(elapsed()) + ']');
      };

      // --- 네이티브 select ---
      var nsel = ctrl && (ctrl.tagName === 'SELECT'
                          ? ctrl : (ctrl.querySelector && ctrl.querySelector('select')));
      if (nsel) {
        var cur = nsel.options[nsel.selectedIndex];
        if (cur && cur.text.indexOf(step.ensure) !== -1) { doneEnsure('이미 ' + step.ensure); return; }
        for (var k2 = 0; k2 < nsel.options.length; k2++) {
          if (nsel.options[k2].text.indexOf(step.ensure) === -1) continue;
          nsel.selectedIndex = k2;
          try {
            nsel.dispatchEvent(new Event('input', { bubbles: true }));
            nsel.dispatchEvent(new Event('change', { bubbles: true }));
          } catch (e) {}
          doneEnsure(step.ensure + ' 로 맞춤 (select)', true);
          return;
        }
        if (now - waitingSince > S.stepTimeoutMs) {
          finish('목록에 ' + step.ensure + ' 가 없습니다 - 직접 선택하세요', true);
        }
        return;
      }

      // --- 0) 이미 맞는가 / 컨트롤 열기 ---
      if (ensurePhase === 0) {
        if (ctrl && U.label(ctrl).indexOf(step.ensure) !== -1) {
          doneEnsure('이미 ' + step.ensure + ' 이라 그대로 둠');
          return;
        }
        if (!ctrl) {
          if (!waitingSince) waitingSince = now;
          /* optional: 이 화면에 아예 없을 수 있는 단계 (네이버페이로 결제하면
           * 카드 종류 드롭다운이 나타나지 않는다). 잠깐 기다려보고 없으면 넘어간다. */
          if (step.optional && now - waitingSince > (S.optionalMs || 400)) {
            S.idx++; retries = 0; waitingSince = 0; save();
            log('재생 ' + S.idx + '/' + S.steps.length + ': 이 화면에 없어 건너뜀 - '
                + (step.text || step.sel).slice(0, 20));
            return;
          }
          if (now - waitingSince > S.stepTimeoutMs) {
            finish('단계 ' + (S.idx + 1) + ' 컨트롤을 못 찾음: ' + (step.text || step.sel), true);
          }
          return;
        }
        if (!U.hittable(ctrl)) return;
        lastClickAt = now;
        U.fireClick(ctrl);
        ensurePhase = 1;
        waitingSince = now;
        log(step.ensure + ' 로 바꾸기 위해 목록을 엽니다');
        return;
      }

      // --- 1) 원하는 항목 고르기 ---
      if (ensurePhase === 1) {
        var opt = (step.optionSel ? U.findEl(step.optionSel, '', { selectorOnly: true }) : null)
                  || U.findContaining(step.ensure, ctrl);
        if (!opt) {
          if (now - waitingSince > S.stepTimeoutMs) {
            finish('목록에서 ' + step.ensure + ' 를 못 찾았습니다 - 직접 선택하세요', true);
          }
          return;
        }
        lastClickAt = now;
        U.fireClick(opt);
        if (step.applySel || step.applyText) { ensurePhase = 2; waitingSince = now; return; }
        doneEnsure(step.ensure + ' 로 맞춤', true);
        return;
      }

      // --- 2) [적용] 눌러 반영 ---
      var ap = (step.applySel ? U.findEl(step.applySel, '', { selectorOnly: true }) : null)
               || U.findContaining(step.applyText || '적용');
      if (!ap) {
        if (now - waitingSince > S.stepTimeoutMs) {
          finish('[적용] 을 못 찾았습니다 - 직접 눌러주세요', true);
        }
        return;
      }
      lastClickAt = now;
      U.fireClick(ap);
      doneEnsure(step.ensure + ' 로 맞추고 적용', true);
      return;
    }

    var el = locate(step);

    /* 찾았어도 "지금 누를 수 있는" 상태여야 한다.
     * 모달이 떠 있으면 그 뒤 버튼도 크기·visibility 상으로는 멀쩡히 보이지만 실제
     * 클릭은 모달이 먹는다. 그대로 진행하면 화면은 모달에서 멈춰 있는데 단계만
     * 줄줄이 "성공" 으로 찍히고 결제까지 눌렀다고 보고한다(실측에서 그랬다).
     * 여기서 막아두면 최소한 거짓 완료는 없다. */
    /* "아래로 스크롤" 은 몇 번 눌러야 하는지 화면 길이에 따라 다르다. 녹화한 횟수
     * (2번)로 고정하면 모자랄 때 팝업이 안 내려가고, 남으면 다음 단계를 건너뛰게 된다.
     * 버튼이 사라질 때까지 누르는 게 사이트가 의도한 방식이다. */
    /* 스크롤이 끝났다는 신호는 사이트마다 다르다:
     *  - 대한항공: #btnScrollDown 이 숨고 #btnConfirm 이 나타난다 (요소가 사라짐)
     *  - 같은 버튼의 라벨만 '확인' 으로 바뀌는 형태도 있다
     * 둘 다 "더 이상 스크롤 버튼이 아니다" 로 판정한다. */
    /* 이미 동의된 항목을 다시 누르면 꺼진다. 녹화에 같은 동의가 두 번 들어 있어서
     * 실제로 그렇게 꺼졌고, 이후 모달이 안 떠 흐름이 통째로 막혔다. 켜져 있으면 넘어간다. */
    if (el && TOGGLEY.test(step.text || '') && U.alreadyOn(el)) {
      S.idx++;
      waitingSince = 0;   // 다음 단계는 제한시간을 새로 받아야 한다
      retries = 0;
      save();
      log('재생 ' + S.idx + '/' + S.steps.length + ': 이미 켜져 있어 누르지 않음 - '
          + String(step.text || step.sel).slice(0, 20) + '  [' + secs(elapsed()) + ']');
      return;
    }

    var scrollDone = SCROLLY.test(step.text || '') && scrollClicks > 0
                     && (!el || !SCROLLY.test(U.label(el)));
    if (scrollDone) {
      scrollClicks = 0;
      waitingSince = 0;   // 다음 단계는 제한시간을 새로 받아야 한다
      S.idx++;
      /* 녹화에는 스크롤이 여러 번 찍혀 있지만 위에서 버튼이 사라질 때까지 눌렀으므로
       * 뒤따르는 같은 스크롤 단계는 이미 소화된 것이다. 건너뜀으로 세면 멀쩡한 재생이
       * "확인 필요" 로 보고되므로, 조용히 함께 넘긴다. */
      var merged = 0;
      while (S.idx < S.steps.length && SCROLLY.test(S.steps[S.idx].text || '')
             && S.steps[S.idx].sel === step.sel) {
        S.idx++;
        merged++;
      }
      retries = 0;
      save();
      log('재생 ' + S.idx + '/' + S.steps.length + ': 스크롤 완료'
          + (merged ? ' (연속 스크롤 ' + (merged + 1) + '단계를 한 번에 처리)' : '')
          + '  [' + secs(elapsed()) + ']');
      return;
    }

    /* hittable 은 화면 밖이면 판정을 보류하고 통과시킨다. 그런데 fireClick 은 요소에
     * 이벤트를 직접 쏘므로, 그대로 두면 모달이 떠 있어도 화면 밖 버튼은 그냥 눌린다
     * (모달 가드가 통째로 우회된다). 스크롤해서 화면에 넣은 뒤 다시 판정한다. */
    if (el && !U.hittable(el, true)) {
      try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
    }
    if (el && !U.hittable(el)) {
      blockedEl = el;
      el = null;
    } else {
      blockedEl = null;
    }

    /* 목표 날짜를 지정해뒀으면, 자동 감지한 최신 오픈일이 그 날짜가 맞는지 확인한다.
     * 안 맞으면 누르지 않고 멈춘다 - 엉뚱한 날짜로 마일리지가 빠지는 게 최악이다. */
    if (step.dynamicDate && el && S.expectDate) {
      var got = U.label(el);
      /* "08-27", "8/27", "08월 27일" 을 모두 같은 날로 본다. 예전에는 입력 문자열이
       * 라벨에 그대로 들어있는지만 봐서, 형식이 조금만 달라도 무조건 멈췄다. */
      var same = U.sameDate(S.expectDate, got);
      if (same === null) {
        pause('목표 날짜를 해석하지 못했습니다 (예: 08-27) - 입력: ' + S.expectDate
              + ' / 감지: ' + got.slice(0, 30));
        return;
      }
      if (!same) {
        /* 목표 날짜가 화면에 없다 = 아직 안 열렸거나 화면이 낡았다는 뜻이다.
         * 멈춰서 기다리는 건 09:00 경쟁에서 최악이다 - 새로고침해서 다시 본다.
         * 서버를 두드리는 일이라 간격에 하한을 두고, 오래 안 열리면 사람을 부른다. */
        if (!S.openWaitSince) S.openWaitSince = now;
        if (now - S.openWaitSince > S.openWaitMaxMs) {
          finish('목표 날짜(' + S.expectDate + ')가 ' + Math.round(S.openWaitMaxMs / 1000)
                 + '초 동안 안 열렸습니다 - 화면을 확인하세요 (마지막 감지: '
                 + got.slice(0, 24) + ')', true);
          return;
        }
        if (now - lastOpenReloadAt < S.openRetryMs) return;
        lastOpenReloadAt = now;
        S.idx = 0;
        save();
        log('목표 날짜(' + S.expectDate + ')가 아직 없습니다 (감지: ' + got.slice(0, 20)
            + ') - 새로고침하고 다시 봅니다');
        setTimeout(function () { location.reload(); }, 0);
        return;
      }
      S.openWaitSince = 0;
    S.times = []; S.stepStartedAt = Date.now();
    }
    if (!el) {
      if (!waitingSince) waitingSince = now;
      /* optional: 이 화면에 아예 없을 수 있는 단계. 기다려보고 없으면 조용히 넘어간다. */
      if (step.optional && !blockedEl && now - waitingSince > (S.optionalMs || 400)) {
        markStep(S.idx + 1, step.text || step.sel);
        S.idx++; retries = 0; waitingSince = 0; save();
        log('재생 ' + S.idx + '/' + S.steps.length + ': 이 화면에 없어 건너뜀 - '
            + (step.text || step.sel).slice(0, 20) + '  [' + secs(elapsed()) + ']');
        return;
      }
      /* 스크롤 단계인데 버튼을 못 찾는 경우: 버튼이 스크롤에 밀려 사라졌거나 라벨이
       * 바뀐 것일 수 있다. 그래도 팝업은 끝까지 내려야 [확인] 이 열리므로, 버튼과
       * 무관하게 스크롤 자체는 계속 밀어준다. */
      if (SCROLLY.test(step.text || '')) U.scrollToBottom();
      if (now - waitingSince > S.retryClickMs && retryPrevClick(now)) return;
      if (now - waitingSince > S.stepTimeoutMs) {
        // 스크린샷 한 장으로 원인 파악이 되도록 패널 상태줄에 진단 요약을 그대로 붙인다.
        var diag = blockedEl
          ? '무언가에 가려 누를 수 없습니다 (모달이 떠 있는지 확인하세요): '
            + String(U.label(blockedEl)).slice(0, 20)
          : step.dynamicDate
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

    /* 결제 단계는 눌렀다고 끝난 게 아니다. 팝업이 차단되면 로그만 남고 창은 안 뜬다.
     * 누르기 직전의 open 기록을 잡아두고, 잠시 뒤 새 기록이 생겼는지로 판정한다. */
    var payBefore = isPay(step) ? ((S.lastOpen && S.lastOpen.at) || 0) : null;

    lastLabel = U.label(el);   // 다음 단계의 onlyIfPrev 판단에 쓴다
    U.fireClick(el);


    /* "아래로 스크롤" 은 버튼을 누르는 것만으로는 불안하다. 스크롤이 진행되면 버튼
     * 자체가 위로 밀리거나 화면 밖으로 나가서 클릭이 빗나가고, 팝업이 끝까지 안 내려가
     * [확인] 이 안 열린 채 멈춘다. 스크롤 영역을 직접 바닥까지 내려 확실히 한다. */
    if (SCROLLY.test(step.text || '')) {
      U.scrollToBottom();
      scrollClicks++;
      if (scrollClicks < 20) { save(); return; }   // 버튼이 사라질 때까지 같은 단계를 반복
      /* 20번을 눌렀는데도 버튼이 그대로면 끝까지 내려갔는지 확인하지 못한 것이다.
       * 그냥 넘어가되 완료로 보고하지는 않는다. */
      scrollClicks = 0;
      S.problem = true;
      log('스크롤을 20번 눌렀는데도 버튼이 남아 있습니다 - 팝업을 확인하세요');
    }

    markStep(S.idx + 1, step.text || step.sel);
    S.idx++;
    retries = 0;
    save();
    log('재생 ' + S.idx + '/' + S.steps.length + ': ' + (step.text || step.sel).slice(0, 30)
        + '  [' + secs(elapsed()) + ']');
    if (S.idx >= S.steps.length) {
      /* 결제 단계였다면 "눌렀다" 와 "결제창이 떴다" 는 전혀 다르다. 팝업이 차단되면
       * 로그만 남고 창은 안 뜬다. 여기서 바로 완료를 알리면 성공음이 울리고 제목이
       * ★완료★ 로 바뀌어, 정작 결제창이 없는데 사용자가 자리를 뜬다.
       * 창이 떴는지 확인한 뒤에 알린다. */
      if (payBefore !== null) {
        S.playing = false;      // 더 이상 tick 이 돌지 않게 하되, 알림은 판정 후에
        save();
        setTimeout(function () {
          var o = S.lastOpen;
          if (o && o.ok && o.at > payBefore) finish('전체 단계 완료 - 결제창이 열렸습니다');
          else finish('결제하기를 눌렀지만 결제창이 열리지 않았습니다. '
                      + '팝업 차단일 수 있으니 결제 버튼을 직접 눌러주세요', true);
        }, 1500);
        return;
      }
      finish('전체 단계 완료');
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
    S.source = 'local';
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
    S.source = 'local';
    S.steps.splice(i, 0, step);
    if (S.idx > i) S.idx++;
    save(); log('추가: ' + (step.text || step.sel).slice(0, 24) + ' (' + (i + 1) + '번째)');
  }
  function setStep(i, patch) {
    if (!S.steps[i]) return;
    S.source = 'local';
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
    S.steps = arr; S.idx = 0; S.source = 'local'; save();
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
      adoptBaked('수동 요청');
      log('내장 단계 ' + S.steps.length + '개를 불러왔습니다');
    },
    bakedCount: function () { return baked().length; },
    list: function () { console.table(S.steps); return S.steps; },
    onChange: function (fn) { listeners.push(fn); }
  };
  try { W.KE_REC = API; } catch (e) {}
  if (W !== window) { try { window.KE_REC = API; } catch (e) {} }
  if (S.playing) log('이전 재생을 이어서 진행합니다 (' + (S.idx + 1) + '/' + S.steps.length + ')');
})();
