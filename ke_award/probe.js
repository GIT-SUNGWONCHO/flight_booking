/* 좌석이 언제 "매진" 이 되는지 알아내기 위한 계측.
 *
 * 사용자 관찰: 달력에서 검색하고 좌석 등급 화면으로 넘어가면 5초 만에 프레스티지가
 * 이미 매진인 날이 있다. 5초 안에 결제까지 끝낸 사람이 있을 리는 없으므로, 남는
 * 설명은 둘 중 하나다.
 *
 *   (가) 좌석을 고르고 넘어가는 순간 서버가 좌석을 잠근다(hold). 그러면 결승선은
 *        '결제하기' 가 아니라 '다음' 이고, 그 뒤 14.8초는 경쟁이 아니다.
 *   (나) 화면에 보인 잔여석이 애초에 캐시된 옛날 값이었다.
 *
 * 어느 쪽인지는 서버만 알지만, 우리가 볼 수 있는 것이 하나 있다: 조회 화면이 좌석
 * 수를 그릴 때 쓰는 API 응답이다. 잔여석 필드가 어떻게 생겼고 언제 0이 되는지를
 * 09:00 에 사람이 지켜볼 수는 없으므로 자동으로 남긴다.
 *
 * 아무것도 바꾸지 않는다 - 오가는 응답을 엿보고 기록만 한다. */
(function () {
  var W = (typeof unsafeWindow !== 'undefined') ? unsafeWindow : window;
  if (W.KE_PROBE) return;

  var MAX = 40;            // 최근 몇 건까지 들고 있을지
  var CAP = 200000;        // 한 건당 글자 수 상한 (localStorage 가 아니라 메모리다)
  var hits = [];
  var stamp = 0;         // 기록이 늘 때마다 증가. 화면 갱신 여부를 값싸게 판단한다

  /* 좌석/운임 조회로 보이는 응답만 남긴다. 전부 남기면 로그인 토큰 같은 것까지
   * 딸려 들어와 내보내기가 위험해진다. */
  var WANTED = /(availab|award|bonus|flight|fare|segment|seat|payment)/i;
  /* 실측에서 걸러야 했던 것들. 구글 애널리틱스는 현재 주소를 파라미터로 실어 보내서
   * 'select-award-flight' 가 그 안에 들어가 WANTED 에 걸렸고, 화면 문구 사전은
   * '좌석' 이라는 낱말이 수백 번 나와 기록을 통째로 밀어냈다. */
  var NOISE = /(analytics|googletagmanager|doubleclick|\/collect\?|languageInfo|loading_)/i;
  var SEATY = /"(seatCount|cabinSeatCount|bookingClassSeatCount|remain\w*|avail\w*Seat\w*|numberOfSeats?|bookableSeats?)"\s*:/i;

  function note(kind, url, status, body) {
    try {
      if (!WANTED.test(String(url)) || NOISE.test(String(url))) return;
      var text = String(body == null ? '' : body);
      if (text.length > CAP) text = text.slice(0, CAP) + '…(잘림)';
      hits.push({ at: Date.now(), kind: kind, url: String(url).slice(0, 300),
                  status: status, seaty: SEATY.test(text), body: text });
      if (hits.length > MAX) hits.shift();
      stamp++;
    } catch (e) {}
  }

  // ---- fetch ----
  try {
    var of = W.fetch;
    if (typeof of === 'function' && !of.__keProbe) {
      var nf = function (input, init) {
        var url = (input && input.url) || input;
        return of.apply(this, arguments).then(function (res) {
          try {
            if (WANTED.test(String(url))) {
              res.clone().text().then(function (t) { note('fetch', url, res.status, t); },
                                      function () {});
            }
          } catch (e) {}
          return res;
        });
      };
      nf.__keProbe = true;
      W.fetch = nf;
    }
  } catch (e) {}

  // ---- XMLHttpRequest ----
  try {
    var XP = W.XMLHttpRequest && W.XMLHttpRequest.prototype;
    if (XP && !XP.__keProbe) {
      var oo = XP.open, os = XP.send;
      XP.open = function (m, u) { try { this.__keUrl = u; } catch (e) {} return oo.apply(this, arguments); };
      XP.send = function () {
        var self = this;
        try {
          self.addEventListener('load', function () {
            var t = '';
            try { t = (self.responseType === '' || self.responseType === 'text') ? self.responseText : ''; } catch (e) {}
            note('xhr', self.__keUrl, self.status, t);
          });
        } catch (e) {}
        return os.apply(this, arguments);
      };
      XP.__keProbe = true;
    }
  } catch (e) {}

  /* ---- 실측으로 확인된 응답 모양 (2026-08-27) --------------------------
   *
   * api/ap/booking/avail/awardAvailability 안:
   *   commercialFareFamilyList: [
   *     {fareFamily:"KEBONUSEY", seatCount:"9", soldout:false, totalMileage:"35000"},
   *     {fareFamily:"KEBONUSPR", seatCount:"0", soldout:true,  totalMileage:"62500"}
   *   ]
   * KEBONUSPR 이 프레스티지다. 이게 매진 판정의 출처다 - 화면에는 없다.
   *
   * seatCount "9" 는 실제 9석이 아니라 "9석 이상" 이라는 항공사 표준 상한값이다.
   * 반대로 "0" 은 진짜 0이다. 우리가 알고 싶은 것은 09:00 직후에 1~2였다가 0이
   * 되는지(누가 채간 것), 아니면 처음부터 0인지(그날 그 등급이 아예 없던 것)다.
   * 둘은 대응이 전혀 다르다. */
  var FAMILY = { KEBONUSPR: '프레스티지', KEBONUSEY: '일반석',
                 KEBONUSPE: '프리미엄', KEBONUSFR: '일등석' };

  /** 기록에서 등급별 좌석 수 변화를 뽑아낸다. [{at, family, seatCount, soldout}] */
  function seatTimeline() {
    var out = [];
    hits.forEach(function (h) {
      var d;
      try { d = JSON.parse(h.body); } catch (e) { return; }
      var bounds = (d && d.upsellBoundAvailList) || [];
      bounds.forEach(function (b) {
        ((b && b.availFlightList) || []).forEach(function (f) {
          ((f && f.commercialFareFamilyList) || []).forEach(function (c) {
            out.push({
              at: h.at,
              flight: (f.flightInfoList && f.flightInfoList[0]
                       && (f.flightInfoList[0].carrierCode + f.flightInfoList[0].flightNumber)) || '',
              date: String(f.departureDate || '').slice(0, 8),
              family: c.fareFamily || '',
              name: FAMILY[c.fareFamily] || c.fareFamily || '',
              seatCount: c.seatCount,
              soldout: !!c.soldout,
              mileage: c.totalMileage
            });
          });
        });
      });
    });
    return out;
  }

  /** 지금 조회 화면이 어느 날을 보고 있는가. "MM-DD" 또는 null.
   *
   * 조회 페이지 주소에는 날짜가 없다(/departure 뿐). 그래서 화면만 보고는 지금
   * 몇 일자를 조회 중인지 확신할 수 없는데, 서버 응답에는 있다. 달력을 건너뛰고
   * 이 페이지에서 시작할 때 "엉뚱한 날 좌석을 누르는" 사고를 막는 유일한 근거다. */
  function shownDate(since) {
    /* since 를 주면 그 시각 이후에 온 응답만 본다.
     *
     * 이게 없으면 낡은 응답이 진실을 가린다: 날짜를 바꿔 눌렀는데 재조회가 안 되면
     * 예전 응답이 그대로 남아, 마치 그 날짜를 조회 중인 것처럼 보인다.
     * 실측(2026-08-27)에서 정확히 그랬다 - 머리말은 08-18 인데 목록은 08-21 이었다. */
    var tl = seatTimeline();
    for (var i = tl.length - 1; i >= 0; i--) {
      if (since && tl[i].at < since) continue;
      var d = tl[i].date;                       // YYYYMMDD
      if (d && d.length === 8) return d.slice(4, 6) + '-' + d.slice(6, 8);
    }
    return null;
  }

  /** 이 화면의 날짜 띠에 있는 날들. ["08-16", ...] - 목표 날짜가 여기 있어야 고를 수 있다. */
  function stripDates() {
    var out = [];
    hits.forEach(function (h) {
      var d;
      try { d = JSON.parse(h.body); } catch (e) { return; }
      ((d && d.upsellBoundAvailList) || []).forEach(function (b) {
        ((b && b.upsellCalendarFareList) || []).forEach(function (c) {
          var s2 = String(c.date || '');
          if (s2.length !== 8) return;
          var mmdd = s2.slice(4, 6) + '-' + s2.slice(6, 8);
          if (out.indexOf(mmdd) < 0) out.push(mmdd);
        });
      });
    });
    return out;
  }

  /* 결제 수단은 화면에서 눈으로 찾을 필요가 없다. 서버가 목록으로 준다.
   * 돌아오는 편에 네이버페이가 없다는 것도 여기서 미리 알 수 있다. */
  function payTypes() {
    for (var i = hits.length - 1; i >= 0; i--) {
      if (!/GetAvailablePaymentType/i.test(hits[i].url)) continue;
      try {
        var d = JSON.parse(hits[i].body);
        return (d.paymentTypeList || []).map(function (t) { return t.paymentTypeCode; });
      } catch (e) { return null; }
    }
    return null;
  }

  /* ---- 조회 조건이 어디에 사는가 -----------------------------------------
   *
   * 실측(2026-08-27): 조회 페이지 주소는 그냥 /booking/select-award-flight/departure
   * 다. 물음표 뒤가 비어 있다. 그런데 이 화면은 노선·날짜·인원·등급을 알고 있고
   * awardAvailability 를 그 조건으로 부른다. 그 조건이 주소가 아니라면 어딘가에는
   * 있다 - sessionStorage, localStorage, 아니면 서버 세션이다.
   *
   * 앞의 둘이면 목표 날짜를 그 자리에 써넣고 조회 페이지로 바로 들어갈 수 있다.
   * 서버 세션이면 못 한다. 추측하지 말고 실제로 무엇이 들어 있는지 본다.
   *
   * 값은 그대로 두고 읽기만 한다. 다만 사람 정보나 토큰이 섞여 있을 수 있으므로
   * 내보낼 때는 날짜처럼 보이는 것만 남기고 나머지는 길이만 적는다. */
  var DATEISH = /(20\d{2})[-.\/]?(\d{2})[-.\/]?(\d{2})/;

  function scanStore(store, name) {
    var out = [];
    try {
      for (var i = 0; i < store.length; i++) {
        var k = store.key(i), v = '';
        try { v = String(store.getItem(k)); } catch (e) { continue; }
        if (k.indexOf('ke_award') === 0) continue;      // 우리 것은 뺀다
        var m = v.match(DATEISH);
        out.push({ store: name, key: k, len: v.length,
                   date: m ? m[0] : '', sample: m ? v.slice(Math.max(0, m.index - 60),
                                                             m.index + 60) : '' });
      }
    } catch (e) {}
    return out;
  }

  /** 지금 화면의 저장소에서 '날짜를 들고 있는 항목' 을 찾는다. */
  function storeHints() {
    var all = [];
    try { all = all.concat(scanStore(W.sessionStorage, 'session')); } catch (e) {}
    try { all = all.concat(scanStore(W.localStorage, 'local')); } catch (e) {}
    return all;
  }

  /** 사람이 읽을 한 줄 요약. 목표 등급이 몇 석인지가 핵심이다. */
  function summary() {
    if (!hits.length) return '조회 응답 기록 없음';
    var tl = seatTimeline();
    if (!tl.length) return hits.length + '건 기록 (좌석 수는 아직 못 봄)';
    var last = {};
    tl.forEach(function (r) { last[r.name] = r; });
    return Object.keys(last).map(function (k) {
      return k + ' ' + (last[k].soldout ? '매진' : last[k].seatCount + '석');
    }).join(' · ');
  }

  W.KE_PROBE = {
    hits: function () { return hits; },
    stamp: function () { return stamp; },
    /* 좌석 조회 응답이 한 번이라도 왔는가.
     *
     * "고른 등급이 없다" 와 "페이지가 아직 안 떴다" 를 가르는 근거다. 화면만 보면
     * 둘 다 '없음' 으로 보여서, 안 떴는데 새로고침 -> 또 안 뜸 -> 무한반복이 된다
     * (실측 2026-08-28). 서버가 답을 준 뒤라면 목록이 비어 있어도 그건 사실이므로
     * 그때는 새로고침해서 다시 보는 것이 맞다. */
    answered: function () {
      for (var i = 0; i < hits.length; i++) {
        if (/availab/i.test(hits[i].url)) return true;
      }
      return false;
    },
    summary: summary,
    seatTimeline: seatTimeline,
    storeHints: storeHints,
    shownDate: shownDate, stripDates: stripDates,
    payTypes: payTypes,
    dump: function () {
      /* 원본 JSON 은 길어서 사람이 읽기 어렵다. 알고 싶은 것(등급별 좌석 수가
       * 언제 어떻게 바뀌었나)을 맨 위에 표로 뽑아두고 원본은 그 아래 붙인다. */
      var tl = seatTimeline();
      var head = tl.length
        ? ('== 등급별 좌석 수 ==' + '\n'
           + tl.map(function (r) {
               return new Date(r.at).toISOString().slice(11, 23) + '  ' + r.date + ' ' + r.flight
                    + '  ' + (r.name || r.family) + '  ' + r.seatCount + '석'
                    + (r.soldout ? ' (매진)' : '') + '  ' + r.mileage + '마일';
             }).join('\n'))
        : '== 등급별 좌석 수: 아직 못 봄 ==';
      var pt = payTypes();
      /* 달력 건너뛰기가 가능한지는 조회 조건이 어디 사는가에 달렸다.
       * 저장소에 날짜가 있으면 고쳐 넣고 바로 들어갈 수 있고, 없으면 못 한다. */
      var hints = storeHints();
      var dated = hints.filter(function (h) { return h.date; });
      head += '\n\n== 조회 조건이 어디 있나 (달력 건너뛰기용) ==\n'
            + (hints.length
               ? (dated.length
                  ? dated.map(function (h) {
                      return h.store + '  ' + h.key + '  (' + h.len + '자)  날짜=' + h.date
                           + '\n    …' + h.sample.replace(/[\s]+/g, ' ') + '…';
                    }).join('\n')
                  : '저장소에 ' + hints.length + '개 있지만 날짜를 든 것은 없음'
                    + ' -> 조회 조건은 서버 세션에 있을 가능성이 큼\n  ('
                    + hints.map(function (h) { return h.key; }).slice(0, 30).join(', ') + ')')
               : '저장소가 비어 있음 -> 조회 조건은 서버 세션에 있을 가능성이 큼');
      head += '\n\n== 쓸 수 있는 결제 수단 ==\n'
            + (pt ? pt.join(', ') + (pt.indexOf('NAVERPAY') < 0 ? '  <- 네이버페이 없음' : '')
                  : '아직 못 봄');
      return head + '\n\n== 원본 ==\n\n' + hits.map(function (h) {
        return '### ' + new Date(h.at).toISOString() + '  [' + h.kind + ' ' + h.status + ']'
             + (h.seaty ? '  <- 좌석 수 필드 있음' : '') + '\n' + h.url + '\n' + h.body;
      }).join('\n\n');
    },
    clear: function () { hits = []; stamp++; }
  };
  if (W !== window) { try { window.KE_PROBE = W.KE_PROBE; } catch (e) {} }
})();
