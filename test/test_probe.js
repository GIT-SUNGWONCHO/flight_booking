/* 조회 응답 계측(probe) 검증.
 *
 * 목적은 "프레스티지가 5초 만에 매진되는 기준이 무엇인가" 를 추측이 아니라 기록으로
 * 답하는 것이다. 09:00 에 사람이 개발자도구를 붙잡고 있을 수는 없으니 자동으로 남긴다.
 *
 * 여기서 못 박는 것:
 *   - 오가는 응답을 바꾸지 않는다 (페이지가 받는 값이 그대로여야 한다)
 *   - 좌석/운임 조회로 보이는 것만 남긴다 (로그인 토큰 같은 것까지 쓸어담지 않는다)
 *   - 잔여석 필드가 있는 응답을 표시한다 (그게 매진 판정의 출처 후보다)
 *
 * 실행:  node test/test_probe.js
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
global.window = global;

// 가짜 fetch/XHR 을 먼저 깔아두고 probe 가 그것을 감싸게 한다
const served = new Map();
global.fetch = function (url) {
  const body = served.get(String(url)) || '{}';
  return Promise.resolve({
    status: 200,
    clone() { return { text: () => Promise.resolve(body) }; },
    text: () => Promise.resolve(body),
    __body: body,
  });
};
new Function(fs.readFileSync(path.join(ROOT, 'ke_award', 'probe.js'), 'utf8'))();
const P = global.KE_PROBE;

let fails = [];
const check = (ok, label, detail = '') => {
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${!ok && detail ? '  <- ' + detail : ''}`);
  if (!ok) fails.push(label);
};

const AVAIL = '/api/booking/award/availability?dep=ICN&arr=FCO';
const LOGIN = '/api/member/login';
served.set(AVAIL, JSON.stringify({
  flights: [{ no: 'KE927', cabins: [{ code: 'PR', remainingSeats: 2 }, { code: 'EY', remainingSeats: 9 }] }],
}));
served.set(LOGIN, JSON.stringify({ token: 'SECRET-DO-NOT-KEEP', name: 'CHO' }));

(async () => {
  check(typeof global.fetch === 'function' && global.fetch.__keProbe === true,
        'fetch 를 감쌌다');

  const res = await global.fetch(AVAIL);
  const text = await res.text();
  check(JSON.parse(text).flights[0].cabins[0].remainingSeats === 2,
        '페이지가 받는 응답을 바꾸지 않는다 (엿보기만 한다)');

  await global.fetch(LOGIN);
  await new Promise((r) => setTimeout(r, 30));   // clone().text() 는 비동기다

  const hits = P.hits();
  check(hits.length === 1, `좌석 조회만 남긴다 (실제 ${hits.length}건)`,
        JSON.stringify(hits.map((h) => h.url)));
  check(!P.dump().includes('SECRET-DO-NOT-KEEP'),
        '로그인 응답 같은 것은 남기지 않는다');
  check(hits[0] && hits[0].seaty === true,
        '잔여석 필드가 있는 응답을 표시한다 (매진 판정의 출처 후보)');
  check(P.summary().includes('좌석 수 필드 있음: 1건'), '요약이 그 사실을 알려준다',
        P.summary());
  check(P.dump().includes('remainingSeats'), '내보내면 실제 값이 보인다');

  P.clear();
  check(P.hits().length === 0, '지울 수 있다');

  console.log();
  console.log(fails.length ? 'FAILED: ' + fails.join(', ') : '조회 응답 계측 테스트 통과');
  process.exit(fails.length ? 1 : 0);
})();
