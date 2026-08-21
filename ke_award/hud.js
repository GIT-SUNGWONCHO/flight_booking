/* ============================================================
 * hud.js  --  화면 우상단 컨트롤 패널
 *   - KST 서버시각 동기화 (Date 헤더 edge detection)
 *   - 오픈시각 카운트다운 + 자동 발사
 *   - 조회 버튼 지정(엘리먼트 피커) / 매진 감지 후 재조회
 *   - 성공 감지 시 소리 알림
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
    retryMs: 1200,        // 재조회 간격 하한 (서버 부담/봇탐지 방지)
    fireSel: '',          // 조회 버튼 CSS 경로
    fireText: '',         // 조회 버튼 라벨 (셀렉터 실패 시 폴백)
    onOpen: 'replay',     // 정시 동작: 'replay'(새로고침+녹화재생) | 'search'(조회버튼 클릭)
    seatSel: '',          // 좌석 버튼 CSS 경로 (선택)
    seatText: '',         // 좌석 버튼 라벨 (선택)
    armed: false
  };
  try { Object.assign(S, JSON.parse(localStorage.getItem(LS) || '{}')); } catch (e) {}
  function save() { try { localStorage.setItem(LS, JSON.stringify(S)); } catch (e) {} }

  var offsetMs = 0;        // 서버시각 - 로컬시각
  var syncQuality = '미동기화';
  var timer = null;
  var retryTimer = null;

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
  function cssPath(el) {
    if (el.id) return '#' + CSS.escape(el.id);
    var parts = [];
    while (el && el.nodeType === 1 && parts.length < 6) {
      if (el.id) { parts.unshift('#' + CSS.escape(el.id)); break; }
      var s = el.tagName.toLowerCase();
      var cls = Array.prototype.filter.call(el.classList, function (c) {
        return !/^(ng-|is-|active|selected|hover|focus)/.test(c);
      }).slice(0, 2);
      if (cls.length) s += '.' + cls.map(function (c) { return CSS.escape(c); }).join('.');
      var p = el.parentElement;
      if (p) {
        var same = Array.prototype.filter.call(p.children, function (n) { return n.tagName === el.tagName; });
        if (same.length > 1) s += ':nth-of-type(' + (same.indexOf(el) + 1) + ')';
      }
      parts.unshift(s);
      el = p;
    }
    return parts.join(' > ');
  }

  function visible(el) {
    if (!el || !el.isConnected || el.disabled) return false;
    var r = el.getBoundingClientRect();
    return r.width > 2 && r.height > 2;
  }

  /** 셀렉터 우선, 실패하면 라벨 텍스트로 폴백. 화면이 리렌더돼도 다시 찾을 수 있게. */
  function findEl(sel, text) {
    if (sel) {
      try {
        var e = document.querySelector(sel);
        if (visible(e)) return e;
      } catch (err) {}
    }
    if (text) {
      var all = document.querySelectorAll('button, a, input[type="submit"], [role="button"]');
      for (var i = 0; i < all.length; i++) {
        var t = (all[i].innerText || all[i].value || '').replace(/\s+/g, '').trim();
        if (t === text && visible(all[i])) return all[i];
      }
    }
    return null;
  }

  function fire(reason) {
    var REC = W.KE_REC || window.KE_REC;

    /* 녹화된 단계가 있으면 정시 동작은 "새로고침 -> 재생" 이다.
     * playing=true 가 localStorage 에 저장되므로, 새로고침 뒤 recorder 가 이어받아
     * 1단계(새로 열린 날짜)부터 밟는다. */
    if (S.onOpen === 'replay' && REC && REC.state.steps.length) {
      REC.reset();
      REC.play();
      // 재생은 recorder 가 몰기 때문에 HUD 의 매진 재조회 루프와 겹치면 안 된다
      S.armed = false;
      save();
      toast('발사 (' + reason + ') - 새로고침 후 재생 @ ' + fmtKst(nowSrv()));
      setTimeout(function () { location.reload(); }, 0);
      return true;
    }

    var el = findEl(S.fireSel, S.fireText);
    if (!el) { toast('조회 버튼을 못 찾음 - [조회 지정] 다시 하세요', true); return false; }
    el.scrollIntoView({ block: 'center' });
    el.click();
    hunting = !!(S.seatSel || S.seatText);   // 조회했으니 이제 좌석 등장을 노린다
    toast('발사 (' + reason + ') @ ' + fmtKst(nowSrv()));
    return true;
  }

  /* 좌석은 조회 결과가 그려진 뒤에야 나타난다. armed 상태에서 tick 마다 훑어
   * 등장 즉시 클릭한다. 이후 안내사항 모달은 autoconfirm.js 가 이어받는다. */
  var hunting = false;
  function huntSeat() {
    if (!hunting || !S.armed) return;
    var el = findEl(S.seatSel, S.seatText);
    if (!el) return;
    hunting = false;
    el.scrollIntoView({ block: 'center' });
    el.click();
    toast('좌석 클릭 @ ' + fmtKst(nowSrv()));
  }

  var picking = null;      // null | 'fire' | 'seat'
  function startPick(kind) {
    picking = kind;
    toast((kind === 'fire' ? '조회' : '좌석') + ' 버튼을 클릭하세요 (ESC 취소)');
    document.body.style.cursor = 'crosshair';
  }
  function stopPick() { picking = null; document.body.style.cursor = ''; }

  document.addEventListener('click', function (ev) {
    if (!picking) return;
    ev.preventDefault(); ev.stopPropagation();
    var el = ev.target.closest('button, a, input, [role="button"]') || ev.target;
    var sel = cssPath(el);
    var text = (el.innerText || el.value || '').replace(/\s+/g, '').trim().slice(0, 30);
    if (picking === 'fire') { S.fireSel = sel; S.fireText = text; }
    else { S.seatSel = sel; S.seatText = text; }
    save(); stopPick(); render();
    toast('지정됨: ' + (text || sel));
  }, true);

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && picking) { stopPick(); toast('지정 취소'); }
  }, true);

  // ---- 매진 감지 / 재조회 -------------------------------------------------
  var SOLDOUT = /매진|좌석이\s*없|잔여\s*좌석\s*없|조회된\s*(여정|항공편)이\s*없|해당\s*조건.*없|不可|no\s+(seats|availability)/i;
  var SUCCESS = /예약(번호|이\s*완료)|발권\s*완료|여정\s*확인|예약이\s*정상|booking\s+reference|reservation\s+complete/i;
  var SESSION = /세션.*(종료|만료)|시간이\s*초과|다시\s*시도|처음부터/i;

  function pageText() { return (document.body.innerText || '').slice(0, 20000); }

  function watch() {
    if (!S.armed) return;
    var t = pageText();
    if (SUCCESS.test(t)) { succeed(); return; }
    if (SOLDOUT.test(t) || SESSION.test(t)) {
      if (!retryTimer) {
        retryTimer = setTimeout(function () {
          retryTimer = null;
          if (S.armed) fire('재조회');
        }, S.retryMs);
        setStatus('매진/세션끊김 감지 - ' + S.retryMs + 'ms 후 재조회');
      }
    }
  }

  var beeped = false;
  function succeed() {
    if (beeped) return;
    beeped = true;
    S.armed = false; save(); render();
    setStatus('예약 성공 화면 감지! 자동화 정지됨');
    try {
      var ac = new (window.AudioContext || window.webkitAudioContext)();
      [0, 0.25, 0.5].forEach(function (d) {
        var o = ac.createOscillator(), g = ac.createGain();
        o.connect(g); g.connect(ac.destination);
        o.frequency.value = 880; g.gain.value = 0.2;
        o.start(ac.currentTime + d); o.stop(ac.currentTime + d + 0.18);
      });
    } catch (e) {}
    document.title = '★예약성공★ ' + document.title;
  }

  // ---- UI ----------------------------------------------------------------
  var root, statusEl, clockEl, cdEl, toastEl;

  function toast(msg, warn) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.style.color = warn ? '#c00' : '#060';
    console.log('[KE_HUD] ' + msg);
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
    huntSeat();
    watch();
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
   * 카운트다운 -> 정시 발사 -> 좌석 탐색까지 실제와 같은 경로를 탄다. */
  function rehearse(sec) {
    // 재생 모드에서는 조회 버튼 지정이 필요 없다 (녹화 1단계가 그 역할을 한다)
    var REC = W.KE_REC || window.KE_REC;
    var canReplay = S.onOpen === 'replay' && REC && REC.state.steps.length;
    if (!canReplay && !S.fireSel && !S.fireText) {
      toast('먼저 [조회 지정] 을 하거나 단계를 녹화하세요', true);
      return;
    }
    // 입력칸은 초 단위라 그냥 넣으면 밀리초가 잘려 최대 1초 일찍 발사된다. 초 경계로 올림.
    S.targetKst = kstInput(Math.ceil((nowSrv() + sec * 1000) / 1000) * 1000);
    S.armed = true;
    beeped = false;
    save(); render(); schedule();
    toast('연습: ' + sec + '초 뒤 발사합니다');
  }

  /** 지금 화면에서 자동클릭이 누를 후보를 미리 본다 (실제로 누르지는 않음) */
  function preview() {
    var A = W.KE_AUTO || window.KE_AUTO;
    if (!A) { toast('자동클릭 엔진이 없습니다', true); return; }
    var rows = A.scan();
    var hit = rows.filter(function (r) { return r.wouldClick; }).map(function (r) { return r.text; });
    setStatus(hit.length
      ? '누를 후보 ' + hit.length + '개: ' + hit.join(', ')
      : '누를 후보 없음 (버튼 ' + rows.length + '개 검사)');
    toast('전체 목록은 F12 콘솔의 표를 보세요');
  }

  /** 녹화/재생 상태를 패널에 반영 */
  function renderRec() {
    if (!root) return;
    var REC = W.KE_REC || window.KE_REC;
    if (!REC) return;
    var st = REC.state;
    var lab = root.querySelector('#ke-step-label');
    var rec = root.querySelector('#ke-rec');
    var play = root.querySelector('#ke-play');
    var msg = root.querySelector('#ke-rec-msg');
    if (lab) {
      lab.textContent = st.steps.length + '단계'
        + (st.playing ? ' - 재생 중 ' + (st.idx + 1) + '/' + st.steps.length
                      : (st.idx ? ' (' + st.idx + '까지 진행됨)' : ''));
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
    root.querySelector('#ke-retry').value = S.retryMs;
    var ml = root.querySelector('#ke-mode-label');
    if (ml) {
      ml.textContent = S.onOpen === 'replay' ? '새로고침 + 녹화 재생' : '조회 버튼 클릭';
      ml.style.color = S.onOpen === 'replay' ? '#06c' : '#444';
    }
    root.querySelector('#ke-btn-label').textContent = S.fireText || S.fireSel || '(미지정)';
    root.querySelector('#ke-seat-label').textContent = S.seatText || S.seatSel || '(미지정 - 직접 클릭)';
    var arm = root.querySelector('#ke-arm');
    arm.textContent = S.armed ? '■ 정지' : '▶ 대기 시작';
    arm.style.background = S.armed ? '#c33' : '#2a7';
  }

  function build() {
    root = document.createElement('div');
    root.id = 'ke-hud';
    root.innerHTML =
      '<style>' +
      '#ke-hud{position:fixed;top:10px;right:10px;z-index:2147483647;width:290px;' +
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
      '<div class="row"><div><label>선발사(ms)</label><input id="ke-lead" type="number"></div>' +
      '<div><label>재조회(ms)</label><input id="ke-retry" type="number"></div></div>' +
      '<label>조회 버튼: <b id="ke-btn-label">(미지정)</b></label>' +
      '<label>좌석 버튼: <b id="ke-seat-label">(미지정)</b></label>' +
      '<div class="row">' +
      '<button id="ke-pick" style="background:#666">조회 지정</button>' +
      '<button id="ke-pick-seat" style="background:#666">좌석 지정</button></div>' +
      '<div class="row">' +
      '<button id="ke-sync" style="background:#666">시각 동기</button>' +
      '<button id="ke-test" style="background:#666">발사 테스트</button></div>' +
      '<div class="row">' +
      '<button id="ke-auto" style="background:#2a7">자동클릭 ON</button>' +
      '<button id="ke-scan" style="background:#666">버튼 확인</button></div>' +
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
      '<label>정시 동작: <b id="ke-mode-label"></b></label>' +
      '<button id="ke-mode" style="background:#666;width:100%">동작 전환</button>' +
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
    root.querySelector('#ke-pick').onclick = function () { startPick('fire'); };
    root.querySelector('#ke-pick-seat').onclick = function () { startPick('seat'); };
    root.querySelector('#ke-sync').onclick = function () { sync(true); };
    root.querySelector('#ke-test').onclick = function () { fire('수동테스트'); };
    root.querySelector('#ke-rehearse').onclick = function () { rehearse(10); };

    root.querySelector('#ke-mode').onclick = function () {
      S.onOpen = S.onOpen === 'replay' ? 'search' : 'replay';
      save(); render();
    };

    var REC = W.KE_REC || window.KE_REC;
    if (REC) {
      root.querySelector('#ke-rec').onclick = function () {
        REC.state.recording ? REC.stop() : REC.record();
        renderRec();
      };
      root.querySelector('#ke-play').onclick = function () {
        if (REC.state.playing) { REC.pause('사용자 중지'); }
        else {
          // 처음부터 다시 할지, 끊긴 데서 이어갈지
          if (REC.state.idx > 0 && REC.state.idx < REC.state.steps.length) {
            if (confirm(REC.state.idx + '단계까지 진행돼 있습니다.\n확인=이어서, 취소=처음부터')) {
              /* 이어서 */
            } else { REC.reset(); }
          } else { REC.reset(); }
          REC.play();
        }
        renderRec();
      };
      root.querySelector('#ke-edit').onclick = function () {
        var E = W.KE_EDIT || window.KE_EDIT;
        if (E) E.open(); else toast('편집기를 불러오지 못했습니다', true);
      };
      root.querySelector('#ke-export').onclick = function () { REC.showExport(); };
      root.querySelector('#ke-clear').onclick = function () {
        if (confirm('녹화된 단계를 모두 지울까요?')) { REC.clear(); renderRec(); }
      };
      REC.onChange(renderRec);
      renderRec();
    }
    root.querySelector('#ke-scan').onclick = preview;
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
    root.querySelector('#ke-retry').onchange = function (e) {
      // 하한 800ms: 그 이하로 두드리면 봇 탐지 + 서버 부담
      S.retryMs = Math.max(800, +e.target.value || 1200);
      e.target.value = S.retryMs; save();
    };
    root.querySelector('#ke-arm').onclick = function () {
      S.armed = !S.armed; save(); render();
      if (S.armed) { beeped = false; schedule(); }
      else { if (timer) clearTimeout(timer); if (retryTimer) clearTimeout(retryTimer);
             timer = retryTimer = null; hunting = false; setStatus('정지됨'); }
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
                     rehearse: rehearse, preview: preview,
                     offset: function () { return offsetMs; } });
  console.log('%c[KE_HUD] v1.0.0 loaded', 'color:#0b4da2;font-weight:bold');
})();
