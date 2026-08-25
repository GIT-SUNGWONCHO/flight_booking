"""스크롤 팝업: 버튼이 사라질 때까지 누르는지 + 화면 밖 요소로 단계를 건너뛰지 않는지.

실측에서 난 일:
  재생 9/15: 아래로 스크롤 [15.42s]
  단계 10 건너뜀 (이미 지나간 것으로 보임) -> 11단계로
팝업은 끝까지 안 내려갔는데, 모달 안쪽 아래(화면 밖)에 있던 [확인] 을
"누를 수 있다" 고 오판해 남은 스크롤 단계를 건너뛴 것이다.

실행:  .venv/Scripts/python.exe test/test_scrollmodal.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
FIXTURE = (ROOT / "test" / "fixture" / "scrollmodal.html").as_uri()

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(ROOT / ".test-profile-scroll"), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            ctx.add_init_script(js)
            pg.goto(FIXTURE)
            pg.wait_for_timeout(300)

            # 녹화에는 스크롤이 2번뿐이지만 실제로는 3번 필요하다
            pg.evaluate("""() => {
              const R = window.KE_REC;
              R.state.steps = [
                {sel:'#agree',         text:'동의',        tag:'button', url:'/x'},
                {sel:'#btnScrollDown', text:'아래로 스크롤', tag:'button', url:'/x'},
                {sel:'#btnScrollDown', text:'아래로 스크롤', tag:'button', url:'/x'},
                {sel:'#btnConfirm',    text:'확인',        tag:'button', url:'/x'},
                {sel:'#pay',           text:'결제하기',     tag:'button', url:'/x'}
              ];
              R.state.allowPay = true;
              R.state.idx = 0; R.state.startedAt = 0; R.state.skipped = 0; R.state.skippedList = [];
              R.state.stepTimeoutMs = 6000;
              R.play();
            }""")
            pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=30000)
            st = pg.evaluate("() => ({scrolls: window.__scrollClicks, confirmed: !!window.__confirmed,"
                             " pay: window.__payClicks, veil: document.getElementById('m').className,"
                             " idx: KE_REC.state.idx, total: KE_REC.state.steps.length,"
                             " msg: KE_REC.state.message})")
            check(st["scrolls"] >= 3, f"버튼이 사라질 때까지 스크롤 (실제 {st['scrolls']}회, 녹화는 2회)")
            check(st["confirmed"], "확인까지 눌러 팝업이 닫힘")
            check(st["veil"] != "on", "팝업이 남아 있지 않음")
            check(st["pay"] == 1, f"팝업을 닫은 뒤에 결제하기가 눌림 (실제 {st['pay']}회)")
            check(st["idx"] == st["total"], f"끝까지 재생 ({st['idx']}/{st['total']})")
            print(f"      메시지: {st['msg']}")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "스크롤 팝업 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
