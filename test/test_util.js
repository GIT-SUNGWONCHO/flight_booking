/* 최소 DOM 스텁 위에 실제 util.js 를 로드해 findLatestOpenDate / findEl 접두어
 * 폴백을 검증한다. 둘 다 스크린샷으로만 확인했던 로직이라 회귀 테스트를 붙여둔다.
 *   실행:  node test/test_util.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'ke_award', 'util.js'), 'utf8');

function makeEl(id, text, opts = {}) {
  const cls = opts.className || '';
  return {
    id: id || '',
    className: cls,
    classList: { length: 0 },
    innerText: text,
    textContent: text,
    value: '',
    title: '',
    disabled: !!opts.disabled,
    isConnected: opts.connected !== false,
    shadowRoot: null,
    parentElement: opts.parent || null,
    nodeType: 1,
    tagName: opts.tag || 'TD',
    getAttribute: (k) => (k === 'aria-disabled' ? (opts.ariaDisabled ? 'true' : null) : null),
    getBoundingClientRect: () => opts.rect || { width: 100, height: 40, left: 0, top: 0 },
    scrollIntoView() {},
    click() {},
    dispatchEvent() { return true; },
  };
}

// 헤더/네비게이션처럼 조상만 있으면 되는 더미 컨테이너 (자기 자신은 후보 목록에 안 올림)
function makeChrome(tag) {
  return { tagName: tag, parentElement: null, getAttribute: () => null };
}

let POOL = [];

const sandbox = {
  console: { log() {}, warn() {} },
  Date, Object, Array, JSON, parseFloat, RegExp, String,
  CSS: { escape: (s) => s },
  MouseEvent: function () {}, PointerEvent: undefined,
  getComputedStyle: (el) => ({
    visibility: el._hidden ? 'hidden' : 'visible',
    display: 'block',
    opacity: '1',
  }),
};
sandbox.window = sandbox;

sandbox.document = {
  documentElement: {},
  querySelectorAll(sel) {
    const arr = [];
    if (sel === '*') return Object.assign(arr, { forEach: Array.prototype.forEach });
    const m = /^\[id\^="([^"]+)"\]$/.exec(sel);
    if (m) {
      const out = POOL.filter((el) => el.id && el.id.indexOf(m[1]) === 0);
      return Object.assign(out, { forEach: Array.prototype.forEach });
    }
    if (sel.indexOf('#') === 0) {
      const id = sel.slice(1);
      const out = POOL.filter((el) => el.id === id);
      return Object.assign(out, { forEach: Array.prototype.forEach });
    }
    // CLICKABLE 등 나머지는 전체 POOL 을 후보로 돌려준다 (candidates() 용)
    return Object.assign(POOL.slice(), { forEach: Array.prototype.forEach });
  },
};

vm.createContext(sandbox);
vm.runInContext(SRC, sandbox);
const U = sandbox.window.KE_UTIL;
if (!U) { console.error('KE_UTIL 이 초기화되지 않음'); process.exit(1); }

let fail = 0;
function check(name, cond) {
  if (!cond) fail++;
  console.log(`${cond ? 'ok  ' : 'FAIL'}  ${name}`);
}

// ---- findLatestOpenDate ---------------------------------------------------
{
  POOL = [
    makeEl('dep-fare-4-6', '13 08월 13일 (금) , 성수기 일반석'),          // 예약 가능, 더 이른 날짜
    makeEl('dep-fare-5-0', '15 08월 15일 (일)'),                          // 요금등급 글자 없음 -> 그 요일 운항 없음/미오픈
    makeEl('dep-fare-5-1', '16 08월 16일 (월) , 성수기 일반석'),          // 예약 가능, 마지막이어야 함
    makeEl('dep-fare-5-2', '17 08월 17일 (화)', { ariaDisabled: true }),  // 아직 안 열림
    makeEl('other-9-9', '99 09월 09일 (수) , 성수기 일반석'),             // id 접두어가 달라 후보에서 제외돼야 함
  ];
  const el = U.findLatestOpenDate('dep-fare-');
  check('요금등급 없는/막힌 셀은 건너뛰고 마지막 예약 가능 날짜를 고름', el && el.id === 'dep-fare-5-1');

  POOL = [makeEl('dep-fare-1-1', '01 08월 01일 (토)')];
  check('예약 가능한 날짜가 하나도 없으면 null', U.findLatestOpenDate('dep-fare-') === null);

  POOL = [makeEl('dep-fare-1-1', '01 08월 01일 (토) , 일반석', { rect: { width: 0, height: 0 } })];
  check('0px(안 보이는) 날짜 셀은 제외', U.findLatestOpenDate('dep-fare-') === null);
}

// ---- findEl 접두어 폴백 -----------------------------------------------------
{
  const target = makeEl('dep-fare-5-1', '16 08월 16일 (월) , 성수기 일반석 , 선택됨');
  POOL = [
    makeEl('other', '아무 상관 없는 버튼'),
    target,
  ];
  // 녹화 당시 텍스트는 클릭 후 상태("선택됨")까지 포함하지만, 재생 시점(클릭 전)의
  // 실제 라벨에는 그게 없다 -> 정확 일치는 실패하고 접두어 일치로 찾아야 한다.
  const found = U.findEl('', '16 08월 16일 (월) , 성수기 일반석 , 선택됨');
  check('정확히 안 맞아도 앞부분이 같으면 접두어로 찾음', found === target);

  const noMatch = U.findEl('', '17 08월 17일 (화) , 성수기 일반석 , 선택됨');
  check('접두어까지 다르면 못 찾음(오매칭 방지)', noMatch === null);

  const short = U.findEl('', '확인');
  check('짧은 라벨은 접두어 폴백 대상이 아님(정확히 없으면 null)', short === null);
}

// ---- 헤더/네비 영역 후보 제외 (사이트 전체검색 아이콘 오매칭 방지) -----------------
{
  const header = makeChrome('HEADER');
  const decoy = makeEl('site-search', '검색', { parent: header });   // 헤더 안의 전체 검색 아이콘
  const real = makeEl('booking-search', '검색');                     // 예매 화면의 진짜 검색 버튼
  POOL = [decoy, real];
  check('헤더 안의 동명 버튼은 건너뛰고 진짜 버튼을 찾음', U.findEl('', '검색') === real);

  POOL = [decoy];
  check('헤더 안에만 있으면 못 찾음(오클릭 방지)', U.findEl('', '검색') === null);
}

// ---- realTarget: shadow DOM 안쪽 진짜 버튼까지 파고들기 ------------------------
{
  // kds-button(껍데기) > kds-button_1(shadow 보유) >> shadowRoot > button(진짜)
  const realBtn = makeEl('kds-button-id-x', '', { tag: 'BUTTON' });
  const inner = makeEl('', '검색', { tag: 'KDS-BUTTON_1' });
  inner.shadowRoot = { querySelector: (sel) => (/button/.test(sel) ? realBtn : null) };
  inner.children = [];
  const host = makeEl('', '검색', { tag: 'KDS-BUTTON' });
  host.children = [inner];

  check('껍데기 -> shadow 안쪽 네이티브 button 까지 내려감', U.realTarget(host) === realBtn);
  check('shadow 보유 요소에서 시작해도 안쪽 button 을 찾음', U.realTarget(inner) === realBtn);

  const plain = makeEl('plain', '확인', { tag: 'BUTTON' });
  plain.children = [];
  check('평범한 버튼은 그대로 반환', U.realTarget(plain) === plain);
}

// ---- findCabin: 좌석 등급으로 항공편 카드 고르기 -------------------------------
{
  const eco = makeEl('', '항공편명 KE901 일반석 52,500 마일', { tag: 'LABEL' });
  const pres = makeEl('', '항공편명 KE901 프레스티지 90,000 마일', { tag: 'LABEL' });
  // 카드 전체를 감싸는 컨테이너: 같은 글자를 품지만 라벨이 더 길다 -> 골라선 안 된다
  const wrap = makeEl('', '항공편명 KE901 일반석 52,500 마일 상세 보기 좌석 선택', { tag: 'DIV' });
  POOL = [wrap, eco, pres];

  check('연습용 일반석 카드를 고름', U.findCabin('일반석') === eco);
  check('실전 프레스티지 카드를 고름', U.findCabin('프레스티지') === pres);
  check('그날 안 열린 등급은 null (엉뚱한 등급 클릭 방지)', U.findCabin('일등석') === null);
  check('등급을 안 정하면 null', U.findCabin('') === null);
}

// ---- hittable: 모달에 가려진 요소를 "누를 수 있다"고 하면 안 된다 ------------------
{
  const covered = makeEl('behind', '확인', { tag: 'BUTTON' });
  const overlay = makeEl('overlay', '', { tag: 'DIV' });
  covered.contains = () => false;
  overlay.contains = () => false;
  sandbox.window.innerWidth = 1000;
  sandbox.window.innerHeight = 800;

  sandbox.document.elementFromPoint = () => overlay;      // 모달이 위를 덮고 있음
  check('모달에 가려진 버튼은 누를 수 없다고 판정', U.hittable(covered) === false);

  sandbox.document.elementFromPoint = () => covered;      // 아무것도 안 가림
  check('안 가려진 버튼은 누를 수 있다고 판정', U.hittable(covered) === true);

  sandbox.document.elementFromPoint = () => null;         // 판정 불가
  check('판정 불가면 통과시킴(스크롤해서 누르면 되므로)', U.hittable(covered) === true);
}

console.log(fail ? `\n${fail} FAILED` : '\n전체 통과');
process.exit(fail ? 1 : 0);
