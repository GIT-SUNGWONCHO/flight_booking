"""좌석이 이미 나갔을 때 - 헛클릭을 반복하지 않고 즉시 멈추는지.

실측(2026-08-29 09:00, 프레스티지 1석):
  재생 7/17: 확인 [17.1s]
  ... 단계 8 이 안 나타나 직전 단계를 다시 누름 (16회째)
  재생 중지 - 단계 8 요소를 못 찾음: 동의  [총 38.74s]

그 사이 화면에는 "운임 및 좌석 상황이 변하여 예약을 완료할 수 없습니다" 팝업이
떠 있었다. 좌석은 이미 남의 것이 됐는데 도구는 그걸 못 알아보고 21.6초를 버렸고,
그나마 누른 '확인' 은 그 에러 팝업의 확인 버튼이었다.

이 경우 빨리 멈추는 것 자체가 기능이다 - 사람이 다음 수를 둘 시간을 벌어준다.

실행:  .venv/bin/python test/test_seatgone.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
FIXTURE = (ROOT / "test" / "fixture" / "seatgone.html").as_uri()

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


STEPS = """[
  {sel:'#a', text:'확인', tag:'button', url:'/x'},
  {sel:'#nope', text:'동의', tag:'button', url:'/x'}
]"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(ROOT / ".test-profile-gone"), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.set_default_timeout(30000)
            ctx.add_init_script(js)
            pg.goto(FIXTURE)
            pg.wait_for_function("() => !!window.KE_REC", timeout=20000)

            pg.evaluate(f"""() => {{
              const R = window.KE_REC;
              R.state.steps = {STEPS};
              R.state.idx = 0; R.state.startedAt = 0; R.state.problem = false;
              R.state.times = [];
              // 제한시간은 넉넉히 둔다 - 여기서 검증할 것은 "그 전에 스스로 멈추는가" 다
              R.state.stepTimeoutMs = 20000;
              R.play();
            }}""")

            t0 = time.time()
            pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=25000)
            took = time.time() - t0

            st = pg.evaluate("() => ({msg: KE_REC.state.message, problem: KE_REC.state.problem,"
                             " idx: KE_REC.state.idx})")

            # 20초 제한시간을 다 채우지 않고 훨씬 일찍 끊어야 한다
            check(took < 8, f"제한시간(20s)을 채우지 않고 일찍 멈춘다 (실제 {took:.1f}s)")
            check("운임 및 좌석 상황이 변하여" in (st["msg"] or ""),
                  "사이트가 띄운 안내를 그대로 알려준다", str(st["msg"])[:90])
            check(st["problem"] is True, "문제 있음으로 표시한다 (완료 소리가 나면 안 된다)")

            # 에러 팝업의 확인을 계속 눌러대지 않아야 한다
            clicks = pg.evaluate("() => document.querySelectorAll('#err').length")
            check(clicks == 1, f"에러 팝업을 다시 띄우지 않는다 (실제 {clicks})")
            print(f"      {took:.1f}s 에 멈춤: {st['msg'][:80]}")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "좌석 소진 감지 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
