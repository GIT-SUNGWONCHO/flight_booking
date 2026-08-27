"""헛클릭(클릭했는데 아무 일도 안 일어남) 감지·재시도 테스트.

실측에서 난 상황:
  재생 5/15: 확인 [8.01s]   <- 승객정보
  재생 6/15: 확인 [8.22s]   <- 연락처. 눌렸다는 로그는 남았는데 화면은 그대로였다
  재생 중지 - 단계 7 요소를 못 찾음: 동의 [셀렉터 0개, 텍스트 0개]
사이트가 섹션을 다시 그리는 중에 눌러서 예외도 없이 무시된 것이다.

핵심은 "다시 눌러도 되는 클릭" 과 "다시 누르면 안 되는 클릭(토글)" 을 가르는 것:
클릭 뒤 DOM 이 전혀 안 움직였을 때만 재시도한다. 토글이 먹었다면 DOM 이 바뀌므로
여기 걸리지 않는다.

실행:  .venv/Scripts/python.exe test/test_deadclick.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
FIXTURE = (ROOT / "test" / "fixture" / "deadclick.html").as_uri()

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(ROOT / ".test-profile-dead"), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            ctx.add_init_script(js)

            # --- 1) 헛클릭이면 다시 눌러서 진행한다 ---
            pg.goto(FIXTURE)
            pg.wait_for_timeout(300)
            pg.evaluate("""() => {
              const R = window.KE_REC;
              R.state.steps = [
                {sel:'#contact', text:'확인', tag:'button', url:'/x'},
                {sel:'#next',    text:'다음', tag:'button', url:'/x'}
              ];
              R.state.idx = 0; R.state.startedAt = 0; R.state.problem = false;
              R.state.stepTimeoutMs = 8000;
              R.play();
            }""")
            pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=20000)
            st = pg.evaluate("() => ({tries: window.__contactTries, advanced: !!window.__advanced,"
                             " ignored: window.__ignored, idx: KE_REC.state.idx, total: KE_REC.state.steps.length,"
                             " msg: KE_REC.state.message})")
            check(st["tries"] >= 2, f"무시된 클릭을 다시 눌렀다 (총 {st['tries']}회)")
            check(st["advanced"], "결국 화면이 넘어감")
            check(st["ignored"] >= 1, f"첫 클릭은 실제로 무시됐다 (무시 {st['ignored']}회)")
            check(st["idx"] == st["total"], f"끝까지 재생 ({st['idx']}/{st['total']})")

            # --- 2) 토글은 재시도 대상이 아니다 ---
            # 동의를 누르면 DOM 이 바뀌므로 헛클릭이 아니다. 다음 단계를 못 찾아
            # 멈추더라도 동의를 다시 눌러 꺼서는 안 된다.
            pg.goto(FIXTURE)
            pg.wait_for_timeout(300)
            pg.evaluate("""() => {
              const R = window.KE_REC;
              R.state.steps = [
                {sel:'#agree',        text:'동의', tag:'button', url:'/x'},
                {sel:'#절대없는버튼',   text:'있을리없는라벨', tag:'button', url:'/x', selectorOnly:true}
              ];
              R.state.idx = 0; R.state.startedAt = 0; R.state.problem = false;
              R.state.stepTimeoutMs = 3000;
              R.play();
            }""")
            pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=20000)
            st = pg.evaluate("() => ({clicks: window.__agreeClicks,"
                             " off: !!window.__agreeTurnedOff,"
                             " pressed: document.getElementById('agree').getAttribute('aria-pressed')})")
            check(st["clicks"] == 1, f"토글은 딱 한 번만 눌림 (실제 {st['clicks']}회)")
            check(not st["off"], "동의를 다시 눌러 꺼버리지 않음")
            check(st["pressed"] == "true", f"동의가 켜진 채로 끝남 (실제 {st['pressed']})")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "헛클릭 재시도 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
