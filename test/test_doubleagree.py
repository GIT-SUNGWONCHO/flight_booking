"""녹화에 같은 동의가 두 번 들어간 경우 - 두 번째 클릭이 동의를 꺼지 않는지.

실측 로그:
  재생  7/16: 동의 [15.14s]   #btn-resv-agree-1 을 켬
  재생 12/16: 동의 [17.04s]   같은 버튼을 또 눌러 꺼버림
  재생 중지 - 단계 13 요소를 못 찾음: 확인   (동의가 꺼져 모달이 안 뜸)
화면에는 위아래 동의가 둘 다 꺼진 채로 남았다.

실행:  .venv/Scripts/python.exe test/test_doubleagree.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
FIXTURE = (ROOT / "test" / "fixture" / "doubleagree.html").as_uri()

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(ROOT / ".test-profile-agree"), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            ctx.add_init_script(js)
            pg.goto(FIXTURE)
            pg.wait_for_timeout(300)

            # 실측 녹화와 같은 모양: a1, a3(이미 켜짐), 확인, a1(중복), 결제하기
            pg.evaluate("""() => {
              const R = window.KE_REC;
              R.state.steps = [
                {sel:'#a1',  text:'동의',    tag:'button', url:'/x'},
                {sel:'#a3',  text:'동의',    tag:'button', url:'/x'},
                {sel:'#ok',  text:'확인',    tag:'button', url:'/x'},
                {sel:'#a1',  text:'동의',    tag:'button', url:'/x'},
                {sel:'#pay', text:'결제하기', tag:'button', url:'/x'}
              ];
              R.state.allowPay = true;
              R.state.idx = 0; R.state.startedAt = 0; R.state.problem = false;
              R.state.stepTimeoutMs = 6000;
              R.play();
            }""")
            pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=30000)
            st = pg.evaluate("""() => ({
              a1: document.getElementById('a1').getAttribute('aria-pressed'),
              a3: document.getElementById('a3').getAttribute('aria-pressed'),
              turnedOff: !!window.__turnedOff, a3Off: !!window.__a3TurnedOff,
              pay: window.__payClicks, idx: KE_REC.state.idx,
              total: KE_REC.state.steps.length, msg: KE_REC.state.message})""")

            check(not st["turnedOff"], "중복 동의를 다시 눌러 끄지 않음")
            check(not st["a3Off"], "이미 켜져 있던 동의도 건드리지 않음")
            check(st["a1"] == "true", f"동의 1이 켜진 채로 끝남 (실제 {st['a1']})")
            check(st["a3"] == "true", f"동의 2가 켜진 채로 끝남 (실제 {st['a3']})")
            check(st["pay"] == 1, f"결제하기까지 도달 (실제 {st['pay']}회)")
            check(st["idx"] == st["total"], f"끝까지 재생 ({st['idx']}/{st['total']})")
            print(f"      메시지: {st['msg']}")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "중복 동의 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
