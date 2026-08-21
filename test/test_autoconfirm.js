/* 최소 DOM 스텁 위에 실제 autoconfirm.js 를 로드해 클릭 판정을 검증한다.
 * 예매 페이지에서 오클릭은 곧 마일리지 사고이므로 회귀 테스트를 붙여둔다.
 *   실행:  node test/test_autoconfirm.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'ke_award', 'autoconfirm.js'), 'utf8');

function makeEl(text, opts = {}) {
  const el = {
    innerText: text,
    textContent: text,
    value: opts.value || '',
    title: '',
    disabled: !!opts.disabled,
    isConnected: opts.connected !== false,
    shadowRoot: null,
    _clicked: 0,
    getAttribute: (k) => (k === 'aria-disabled' ? (opts.ariaDisabled ? 'true' : null) : null),
    getBoundingClientRect: () => opts.rect || { width: 100, height: 40 },
    closest: () => null,
    scrollIntoView() {},
    click() { this._clicked++; },
    dispatchEvent() { return true; },
  };
  return el;
}

// ---- 스텁 환경 ----------------------------------------------------------
let RAF_RUNS = 0;
const sandbox = {
  console: { log() {}, table() {} },
  performance: { now: () => Date.now() },
  Date, WeakSet, Object, Array, JSON, parseFloat, MouseEvent: function () {},
  // rAF 는 즉시 한 번만 돌리고 멈춘다 (무한루프 방지)
  requestAnimationFrame: (fn) => { if (RAF_RUNS++ < 1) fn(); },
  setInterval: () => 0,   // 보조 폴링은 이 테스트에서 불필요
  clearInterval: () => {},
  getComputedStyle: (el) => ({
    visibility: el._hidden ? 'hidden' : 'visible',
    display: 'block',
    opacity: '1',
    pointerEvents: 'auto',
  }),
  MutationObserver: function () { this.observe = () => {}; },
};
sandbox.window = sandbox;
sandbox.window.addEventListener = () => {};

let POOL = [];        // candidates() 가 돌려줄 버튼들
sandbox.document = {
  documentElement: {},
  querySelectorAll(sel) {
    if (sel.includes('checkbox')) return Object.assign([], { forEach: Array.prototype.forEach });
    if (sel === '*' || sel === 'iframe') return Object.assign([], { forEach: Array.prototype.forEach });
    return POOL;
  },
};

vm.createContext(sandbox);
vm.runInContext(SRC, sandbox);
const KE = sandbox.window.KE_AUTO;
if (!KE) { console.error('KE_AUTO 가 초기화되지 않음'); process.exit(1); }

// ---- 검증 ---------------------------------------------------------------
// sweep() 은 한 번에 하나만 누르므로, 라벨 하나씩 POOL 에 올려 판정을 본다.
function wouldClick(text, opts) {
  KE.reset();
  const el = makeEl(text, opts);
  POOL = [el];
  const found = KE.scan();
  return found.length ? found[0].wouldClick : false;
}

const CASES = [
  // [라벨, 클릭해야 하는가, 설명]
  ['확인',              true,  '기본'],
  ['확 인',             true,  '공백 삽입'],
  ['[확인]',            true,  '대괄호'],
  ['확인 »',            true,  '화살표 글리프 (이전 회귀)'],
  ['확인 ›',            true,  '홑화살표'],
  ['확인 →',            true,  '유니코드 화살표'],
  ['다음 단계',          true,  '띄어쓰기 합성'],
  ['전체 동의',          true,  '전체동의'],
  ['동의합니다',         true,  '경어체'],
  ['OK',               true,  '영문 대문자'],
  ['Confirm',          true,  '영문'],
  ['계속하기',           true,  '계속하기'],

  ['취소',              false, '취소 금지'],
  ['닫기',              false, '닫기 금지'],
  ['이전으로',           false, '이전 포함'],
  ['동의하지 않음',       false, '부정 동의'],
  ['확인 취소',          false, 'never 가 click 보다 우선'],
  ['예약 취소',          false, '취소 포함'],
  ['결제하기',           false, 'autoFinal=false 이면 결제 금지'],
  ['발권하기',           false, 'autoFinal=false 이면 발권 금지'],
  ['좌석 선택',          false, '무관한 버튼'],
  ['다시 검색',          false, '재검색 금지'],
  ['로그아웃',           false, '로그아웃 금지'],
  ['',                 false, '빈 라벨'],
];

let fail = 0;
for (const [text, expect, why] of CASES) {
  const got = wouldClick(text);
  const ok = got === expect;
  if (!ok) fail++;
  console.log(
    `${ok ? 'ok  ' : 'FAIL'}  ${JSON.stringify(text).padEnd(16)} -> ${String(got).padEnd(5)} (${why})`
  );
}

// 가시성/비활성 필터
const guards = [
  ['disabled 버튼은 무시', wouldClick('확인', { disabled: true }) === false],
  ['aria-disabled 무시',   wouldClick('확인', { ariaDisabled: true }) === false],
  ['0px 버튼 무시',        wouldClick('확인', { rect: { width: 0, height: 0 } }) === false],
  ['detached 무시',        wouldClick('확인', { connected: false }) === false],
];
for (const [why, ok] of guards) {
  if (!ok) fail++;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${why}`);
}

// autoFinal 켜면 발권 버튼이 열려야 한다
KE.autoFinal = true;
const finalOn = wouldClick('발권하기') === true;
if (!finalOn) fail++;
console.log(`${finalOn ? 'ok  ' : 'FAIL'}  autoFinal=true 이면 발권 허용`);
KE.autoFinal = false;

console.log(fail ? `\n${fail} FAILED` : `\n전체 ${CASES.length + guards.length + 1}건 통과`);
process.exit(fail ? 1 : 0);
