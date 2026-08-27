"""늦게 나타나는 단계를 건너뛰지 않고 기다리는지.

실측 사고:
  단계 7 건너뜀 (이미 지나간 것으로 보임) -> 9단계로
  단계 10 건너뜀 (이미 지나간 것으로 보임) -> 12단계로
  건너뜀 5개: ... 7번 "동의", 8번 "아래로 스크롤", 10번 "동의", 11번 "아래로 스크롤"
동의를 둘 다 건너뛰어 아무것도 동의되지 않았다. #btnConfirm 이 모달이 닫혀 있어도
DOM 에 남아 있어서 "동의는 이미 지나갔다" 고 오판한 것이다.

이제 건너뛰기 기능 자체가 없다. 못 찾으면 기다린다.

실행:  .venv/Scripts/python.exe test/test_noskip.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
FIXTURE = (ROOT / "test" / "fixture" / "noskip.html").as_uri()

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(ROOT / ".test-profile-noskip"), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.set_default_timeout(30000)
            ctx.add_init_script(js)
            pg.goto(FIXTURE, timeout=60000)

            # 동의는 1.2초 뒤에 나타난다. 그동안 #btnConfirm 은 이미 DOM 에 있다.
            pg.evaluate("""() => {
              const R = window.KE_REC;
              R.state.steps = [
                {sel:'#agree',      text:'동의', tag:'button', url:'/x'},
                {sel:'#btnConfirm', text:'확인', tag:'button', url:'/x'}
              ];
              R.state.idx = 0; R.state.startedAt = 0;
              R.state.problem = false;
              R.state.stepTimeoutMs = 10000;
              R.play();
            }""")
            pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=30000)
            st = pg.evaluate("""() => ({
              agree: window.__agreeClicks, confirm: window.__confirmClicks,
              pressed: (document.getElementById('agree')||{}).getAttribute
                       ? document.getElementById('agree').getAttribute('aria-pressed') : null,
              problem: KE_REC.state.problem,
              idx: KE_REC.state.idx, total: KE_REC.state.steps.length,
              msg: KE_REC.state.message})""")

            check(st["agree"] == 1, f"늦게 나타난 동의를 기다렸다 누름 (실제 {st['agree']}회)")
            check(st["pressed"] == "true", f"동의가 켜짐 (실제 {st['pressed']})")
            check(st["problem"] is False, f"문제 없이 진행 (problem={st['problem']})")
            check(st["confirm"] == 1, f"확인은 순서대로 한 번만 (실제 {st['confirm']}회)")
            check(st["idx"] == st["total"], f"끝까지 재생 ({st['idx']}/{st['total']})")
            print(f"      메시지: {st['msg']}")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "건너뛰기 금지 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
