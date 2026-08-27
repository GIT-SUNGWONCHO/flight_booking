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

  var MAX = 12;            // 최근 몇 건까지 들고 있을지
  var CAP = 200000;        // 한 건당 글자 수 상한 (localStorage 가 아니라 메모리다)
  var hits = [];

  /* 좌석/운임 조회로 보이는 응답만 남긴다. 전부 남기면 로그인 토큰 같은 것까지
   * 딸려 들어와 내보내기가 위험해진다. */
  var WANTED = /(availab|award|bonus|flight|fare|segment|seat)/i;
  var SEATY = /"(remain\w*|avail\w*Seat\w*|seat\w*Count|numberOfSeats?|bookableSeats?)"\s*:/i;

  function note(kind, url, status, body) {
    try {
      if (!WANTED.test(String(url))) return;
      var text = String(body == null ? '' : body);
      if (text.length > CAP) text = text.slice(0, CAP) + '…(잘림)';
      hits.push({ at: Date.now(), kind: kind, url: String(url).slice(0, 300),
                  status: status, seaty: SEATY.test(text), body: text });
      if (hits.length > MAX) hits.shift();
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

  /** 사람이 읽을 한 줄 요약. 잔여석 필드를 가진 응답이 몇 건인지가 핵심이다. */
  function summary() {
    if (!hits.length) return '기록된 조회 응답 없음';
    var seaty = hits.filter(function (h) { return h.seaty; }).length;
    return hits.length + '건 기록 (좌석 수 필드 있음: ' + seaty + '건)';
  }

  W.KE_PROBE = {
    hits: function () { return hits; },
    summary: summary,
    dump: function () {
      return hits.map(function (h) {
        return '### ' + new Date(h.at).toISOString() + '  [' + h.kind + ' ' + h.status + ']'
             + (h.seaty ? '  <- 좌석 수 필드 있음' : '') + '\n' + h.url + '\n' + h.body;
      }).join('\n\n');
    },
    clear: function () { hits = []; }
  };
  if (W !== window) { try { window.KE_PROBE = W.KE_PROBE; } catch (e) {} }
})();
