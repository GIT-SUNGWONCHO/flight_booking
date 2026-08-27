/* 달력 건너뛰기(바로 시작)의 주소 수술 검증.
 *
 * 여기가 이 기능에서 유일하게 위험한 곳이다. 왕복이면 주소에 가는 날과 오는 날이
 * 둘 다 들어 있어서, 아무 날짜나 바꾸면 오는 날을 망가뜨린다. 3초 벌자고 엉뚱한
 * 날짜로 마일리지를 태우는 건 말이 안 되므로, 조금이라도 모호하면 바꾸지 않고
 * 달력 경로로 되돌아가는 것이 옳다. 그 "안 바꾼다" 를 여기서 못 박는다.
 *
 * 실행:  node test/test_deeplink.js
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
global.window = global;
new Function(fs.readFileSync(path.join(ROOT, 'ke_award', 'util.js'), 'utf8'))();
const U = global.KE_UTIL;

let fails = [];
const check = (ok, label, detail = '') => {
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${!ok && detail ? '  <- ' + detail : ''}`);
  if (!ok) fails.push(label);
};

// ---- 어디가 조회 페이지인가 ----
check(U.onDeparture('https://www.koreanair.com/booking/select-award-flight/departure'),
      '조회 페이지를 알아본다');
check(U.onDeparture('/booking/select-award-wait-flight/departure'),
      '대기 예약 조회 페이지도 알아본다');
check(!U.onDeparture('https://www.koreanair.com/booking/calendar-fare-bonus'),
      '달력은 조회 페이지가 아니다');
check(!U.onDeparture('/payment/gate/RT/NR'), '결제 페이지도 아니다');

// ---- 주소에서 날짜 찾기 ----
const RT = 'https://www.koreanair.com/booking/select-award-flight/departure'
         + '?tripType=RT&dep=ICN&arr=FCO&depDate=20270821&retDate=20270905&adult=1&cabin=PR';
const ds = U.urlDates(RT);
check(ds.length === 2, `왕복 주소에서 날짜 둘을 찾는다 (실제 ${ds.length})`);
check(ds[0].mmdd === '08-21' && ds[1].mmdd === '09-05',
      '가는 날/오는 날을 순서대로', JSON.stringify(ds.map(d => d.mmdd)));
check(U.urlDates('?adult=1&infant=0&x=12345678').length === 0,
      '날짜가 아닌 숫자를 날짜로 오해하지 않는다');

// ---- 재조준: 가는 날만 바꾼다 ----
let r = U.retarget(RT, '08-21', '08-22');
check(r.url && r.url.includes('depDate=20270822'), '가는 날을 목표 날짜로 바꾼다', r.why);
check(r.url && r.url.includes('retDate=20270905'), '오는 날은 그대로 둔다 (왕복 안전)', r.url);

r = U.retarget(RT, '08-21', '08-21');
check(r.url === RT, '같은 날이면 주소를 손대지 않는다', r.why);

// 붙잡을 당시의 가는 날을 모르면 어느 자리가 가는 날인지 고를 수 없다
r = U.retarget(RT, '', '08-22');
check(!r.url, '기준 날짜가 없으면 바꾸지 않는다', r.url || '');
r = U.retarget(RT, '07-01', '08-22');
check(!r.url, '기준 날짜가 주소에 없으면 바꾸지 않는다', r.url || '');
check(!U.retarget('', '08-21', '08-22').url, '저장된 주소가 없으면 바꾸지 않는다');
check(!U.retarget('/departure?x=1', '08-21', '08-22').url, '주소에 날짜가 없으면 바꾸지 않는다');
check(!U.retarget(RT, '08-21', '').url, '목표 날짜가 없으면 바꾸지 않는다');

// 구분자가 있는 형식도
const DASH = '/departure?depDate=2027-08-21&retDate=2027-09-05';
r = U.retarget(DASH, '08-21', '08-22');
check(r.url === '/departure?depDate=2027-08-22&retDate=2027-09-05',
      '구분자(-)를 유지한 채 바꾼다', r.url || r.why);

// ---- 연도: 마일리지 예매는 360일쯤 앞을 본다 ----
const now = Date.parse('2026-08-27T00:00:00+09:00');
check(U.nextYearFor('08-21', now) === 2027, '오늘보다 이른 월일은 내년',
      String(U.nextYearFor('08-21', now)));
check(U.nextYearFor('12-31', now) === 2026, '오늘보다 늦은 월일은 올해',
      String(U.nextYearFor('12-31', now)));
check(U.nextYearFor('08-27', now) === 2027, '오늘과 같은 월일은 내년 (오늘 출발은 없다)',
      String(U.nextYearFor('08-27', now)));

// 실제 재조준에도 연도가 반영되는가 (연말을 넘어가는 경우)
r = U.retarget('/d?depDate=20260901&retDate=20260915', '09-01', '01-05');
check(r.url && /depDate=20270105/.test(r.url), '해를 넘기면 연도가 올라간다', r.url || r.why);

console.log();
console.log(fails.length ? 'FAILED: ' + fails.join(', ') : '바로 시작 주소 테스트 통과');
process.exit(fails.length ? 1 : 0);
