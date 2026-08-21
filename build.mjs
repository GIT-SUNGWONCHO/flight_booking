/* autoconfirm.js + hud.js  ->  userscript/ke-award-macro.user.js
 * 엔진을 한 곳에서만 관리하기 위한 스티처.  실행:  node build.mjs
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';

/* @grant 를 none 으로 두면 Tampermonkey 가 페이지 컨텍스트에 <script> 로 밀어넣는데,
 * CSP 가 강한 사이트(항공사 등)에서는 그게 차단되어 스크립트가 조용히 죽는다.
 * unsafeWindow 를 grant 하면 샌드박스에서 실행되어 CSP 를 타지 않는다.
 * (그래서 각 모듈이 KE_AUTO/KE_HUD 를 unsafeWindow 에도 노출한다 - 콘솔 접근용) */
const HEADER = `// ==UserScript==
// @name         대한항공 마일리지 예매 보조 (KE Award Macro)
// @namespace    local.ke.award
// @version      1.3.0
// @description  예매 단계 녹화/재생 + 오픈시각 정시 발사 + 안내사항 모달 즉시 통과
// @author       local
// @match        *://*.koreanair.com/*
// @match        *://koreanair.com/*
// @run-at       document-start
// @grant        unsafeWindow
// @noframes     false
// ==/UserScript==
/* 주의: 본인 계정으로 본인 여정을 예매하는 용도로만 사용하세요.
 *       재조회 간격은 800ms 미만으로 낮추지 마세요 (봇 탐지 / 서버 부담).  */
`;

/* 두 모듈은 한 파일로 합쳐지므로, 앞 모듈에서 예외가 top-level 로 새면
 * 뒤 모듈이 아예 실행되지 않는다. 각각 격리한다. */
function isolate(name, src) {
  return `
// ---------- ${name} ----------
try {
${src}
} catch (e) {
  console.error('[KE] ${name} 로드 실패:', e);
}
`;
}

// util 이 가장 먼저 로드되어야 recorder/hud 가 KE_UTIL 을 쓸 수 있다
const MODULES = ['util', 'autoconfirm', 'recorder', 'hud'];
const out = [HEADER]
  .concat(MODULES.map((m) => isolate(m, readFileSync(`ke_award/${m}.js`, 'utf8'))))
  .join('\n');

mkdirSync('userscript', { recursive: true });
writeFileSync('userscript/ke-award-macro.user.js', out, 'utf8');
console.log(`built userscript/ke-award-macro.user.js  (${out.split('\n').length} lines, ${out.length} bytes)`);
