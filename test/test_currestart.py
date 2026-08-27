"""통화를 바꾸면 화면이 처음으로 돌아간다 - 그 뒤를 이어가는지.

사용자 보고(2026-08-27): "USD일때 바꾸고 적용까지 되는데 다시 처음페이지로 돌아가서
아무것도 안되는 버그", "KRW일땐 잘됨".
[적용] 이 화면을 다시 그리면서 처음으로 돌려보내는데, 재생은 통화 단계를 완료로 치고
다음 단계를 찾으니 있을 리가 없다. 통화를 실제로 바꾼 경우에만 날짜부터 다시 밟는다
(restartFrom). 두 번째에는 이미 KRW 라 통과하므로 무한 반복되지 않는다.

실행:  .venv/Scripts/python.exe test/test_currestart.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
BASE = (ROOT / "test" / "fixture" / "currestart.html").as_uri()

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


STEPS = """() => {
  const R = window.KE_REC;
  R.state.steps = [
    {sel:'#date',   text:'22 08월 22일 (일)', tag:'button', url:'/x'},
    {sel:'#search', text:'검색', tag:'button', url:'/x'},
    {sel:'#seat',   text:'일반석 35,000 마일', tag:'button', url:'/x'},
    {ensure:'KRW', sel:'#currencyBtn', text:'통화', tag:'button', url:'/x',
     optionSel:'#filter-currency .filter__item:nth-of-type(2) > label',
     applySel:'#filter-currency .filter__apply', applyText:'적용',
     restartFrom:0},
    {sel:'#next',   text:'다음', tag:'button', url:'/x'}
  ];
  R.state.idx = 0; R.state.startedAt = 0; R.state.problem = false;
  R.state.stepTimeoutMs = 8000;
  R.play();
}"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(ROOT / ".test-profile-crst"), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.set_default_timeout(30000)
            ctx.add_init_script(js)

            for start_cur, label, want_searches in (("USD", "USD 로 시작", 2), ("KRW", "이미 KRW", 1)):
                pg.goto(BASE + "?cur=" + start_cur, timeout=60000)
                pg.evaluate("sessionStorage.setItem('log','[]')")
                pg.wait_for_timeout(300)
                pg.evaluate(STEPS)
                pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=40000)
                st = pg.evaluate("""() => ({
                  log: JSON.parse(sessionStorage.getItem('log') || '[]'),
                  cur: document.getElementById('curval').textContent,
                  idx: KE_REC.state.idx, total: KE_REC.state.steps.length,
                  problem: KE_REC.state.problem, msg: KE_REC.state.message})""")
                log = st["log"]
                check(st["cur"] == "KRW", f"{label}: 통화가 KRW (실제 {st['cur']})")
                check(log.count("search") == want_searches,
                      f"{label}: 검색 {want_searches}회 (실제 {log.count('search')}) - "
                      f"바꿨을 때만 다시 밟는다", str(log))
                check(log and log[-1] == "next",
                      f"{label}: 마지막에 '다음' 까지 도달 (실제 {log[-1] if log else None})", str(log))
                check(st["idx"] == st["total"] and not st["problem"],
                      f"{label}: 끝까지 재생 ({st['idx']}/{st['total']}, problem={st['problem']})",
                      st["msg"])
                print(f"      {label} 진행: {' -> '.join(log)}")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "통화 재시작 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
