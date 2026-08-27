"""동의가 두 개고 각각 모달을 띄우는 흐름.

사용자 확인(2026-08-25): 두 번째 동의(리튬 보조배터리/위험품)도 아래로 스크롤 후
확인이 필요하다. 녹화는 '동의1 -> 동의2 -> 스크롤 -> 확인 -> 동의1(중복) -> 확인'
이라 두 번째 모달이 처리되지 않고 막혔다.

실행:  .venv/Scripts/python.exe test/test_twoagree.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
FIXTURE = (ROOT / "test" / "fixture" / "twoagree.html").as_uri()

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(ROOT / ".test-profile-two"), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            ctx.add_init_script(js)
            pg.goto(FIXTURE)
            pg.wait_for_timeout(300)

            # steps.json 과 같은 모양: 동의 -> 스크롤 -> 확인 을 두 번
            pg.evaluate("""() => {
              const R = window.KE_REC;
              R.state.steps = [
                {sel:'#a1',            text:'동의',        tag:'button', url:'/x'},
                {sel:'#btnScrollDown', text:'아래로 스크롤', tag:'button', url:'/x'},
                {sel:'#btnConfirm',    text:'확인',        tag:'button', url:'/x'},
                {sel:'#a3',            text:'동의',        tag:'button', url:'/x'},
                {sel:'#btnScrollDown', text:'아래로 스크롤', tag:'button', url:'/x'},
                {sel:'#btnConfirm',    text:'확인',        tag:'button', url:'/x'},
                {sel:'#pay',           text:'결제하기',     tag:'button', url:'/x'}
              ];
              R.state.allowPay = true;
              R.state.idx = 0; R.state.startedAt = 0; R.state.problem = false;
              R.state.stepTimeoutMs = 8000;
              R.play();
            }""")
            pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=40000)
            st = pg.evaluate("""() => ({
              a1: document.getElementById('a1').getAttribute('aria-pressed'),
              a3: document.getElementById('a3').getAttribute('aria-pressed'),
              confirmed: window.__confirmed, off: !!window.__off,
              veil: document.getElementById('m').className,
              pay: window.__payClicks, idx: KE_REC.state.idx,
              total: KE_REC.state.steps.length, msg: KE_REC.state.message})""")

            check(st["confirmed"] == ["a1", "a3"],
                  f"두 모달을 순서대로 확인 (실제 {st['confirmed']})")
            check(st["a1"] == "true" and st["a3"] == "true",
                  f"동의 둘 다 켜진 채로 끝남 (a1={st['a1']}, a3={st['a3']})")
            check(not st["off"], "동의를 다시 눌러 끄지 않음")
            check(st["veil"] != "on", "모달이 남아 있지 않음")
            check(st["pay"] == 1, f"결제하기까지 도달 (실제 {st['pay']}회)")
            check(st["idx"] == st["total"], f"끝까지 재생 ({st['idx']}/{st['total']})")
            print(f"      메시지: {st['msg']}")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "동의 2개 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
