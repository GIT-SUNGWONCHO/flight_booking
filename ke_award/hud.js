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
 * 클릭은 전부 recorder.js 의 녹화 재생이 담당한다 (라벨 추측 클릭은 제거됨).
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
  /* 입력칸에 손으로 치다 보면 '2026-08-24-09:00:00' 처럼 날짜와 시각 사이가 하이픈이
   * 되거나 공백이 여러 개 들어간다. 그 상태로 형식 오류만 띄우면 정작 9시에 발사가
   * 안 걸린다. 숫자만 뽑아 재조립해서 웬만한 표기는 다 받아준다. */
  function targetMs() {
    if (!S.targetKst) return NaN;
    var n = String(S.targetKst).match(/\d+/g);
    if (!n || n.length < 5) return NaN;
    var p = function (i, d) { return (n[i] === undefined ? d : ('0' + n[i]).slice(-2)); };
    var iso = n[0] + '-' + p(1) + '-' + p(2) + 'T' + p(3) + ':' + p(4) + ':' + p(5, '00');
    return Date.parse(iso + '+09:00');
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
      /* 어디서 온 단계인지 항상 보이게 한다. 브라우저에 남은 옛날 녹화가 도는데
       * 그걸 모르고 실전에 들어가는 게 제일 위험하다. */
      var src = st.source === 'local' ? '직접 녹화' : '내장';
      lab.textContent = st.steps.length + '단계 (' + src + ')'
        + (st.playing ? ' - 재생 중 ' + (st.idx + 1) + '/' + st.steps.length
                      : (st.idx ? ' (' + st.idx + '까지 진행됨)' : ''))
        + (el ? '  ' + el.toFixed(1) + 's' : '');
      lab.style.color = st.source === 'local' ? '#a0f' : '#0b4da2';
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
        /* 건너뜀 여부는 메시지 문구가 아니라 숫자로 판정한다.
         * 문구 매칭에 기대면 '건너뛰었습니다' -> '건너뜀' 처럼 표현만 바뀌어도
         * 조용히 ★완료★ 로 잘못 보고하게 된다. */
        var ok = st.steps.length > 0 && st.idx >= st.steps.length
                 && !st.skipped && !/못 찾|다릅니다/.test(m);
        notify(m, ok);
      }
    }
    wasPlaying = st.playing;
  }

  function render() {
    if (!root) return;
    renderRec();
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
      '<h4>KE 마일리지 예매 보조 <span id="ke-ver"></span>' +
      '<span style="float:right;cursor:pointer" id="ke-min">_</span></h4>' +
      '<div id="ke-body">' +
      '<div id="ke-clock">--</div><div id="ke-cd">--</div>' +
      '<label>오픈시각 (KST)</label><input id="ke-target" placeholder="2026-08-22 10:00:00">' +
      '<label>선발사(ms)</label><input id="ke-lead" type="number">' +
      '<button id="ke-sync" style="background:#666;width:100%">시각 동기</button>' +
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
    var B = W.KE_BUILD || window.KE_BUILD;
    var ver = root.querySelector('#ke-ver');
    /* 어떤 빌드가 로드됐는지 한눈에 보이게 한다. 버전을 안 올려서 이전 스크립트로
     * 계속 테스트한 적이 있다 - 그때 이게 있었으면 바로 알았다. */
    if (ver && B) {
      ver.textContent = 'v' + B.version;
      ver.style.cssText = 'font-size:10px;font-weight:400;color:'
        + (/dirty|nogit/.test(B.version) ? '#c60' : '#888');
      ver.title = 'build ' + B.hash;
    }
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
