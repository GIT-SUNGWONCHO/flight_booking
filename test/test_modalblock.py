"""모달에 가린 버튼을 누르지 않는지 확인.

실측에서 난 사고: '운임 규정 상세 보기' 모달이 열린 채였는데 재생은 그 뒤의
버튼들을 계속 눌러 11~15단계를 전부 "성공" 으로 찍고 결제까지 눌렀다고 보고했다.
요소가 보이는지(visible)와 지금 누를 수 있는지(hittable)는 다르다.

실행:  .venv/Scripts/python.exe test/test_modalblock.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
FIXTURE = (ROOT / "test" / "fixture" / "modalblock.html").as_uri()

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(ROOT / ".test-profile-modal"), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            ctx.add_init_script(js)
            pg.goto(FIXTURE)
            pg.wait_for_timeout(300)

            # 동의 -> 모달이 뜬다. 다음 단계는 모달 뒤의 결제하기 (녹화에 확인이 빠진 상황)
            pg.evaluate("""() => {
              const R = window.KE_REC;
              R.state.steps = [
                {sel:'#open',   text:'동의', tag:'button', url:'/x'},
                {sel:'#behind', text:'결제하기', tag:'button', url:'/x'}
              ];
              R.state.allowPay = true;
              R.state.idx = 0; R.state.startedAt = 0; R.state.problem = false;
              R.state.stepTimeoutMs = 3500;
              R.play();
            }""")
            pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=20000)
            st = pg.evaluate("() => ({behind: window.__behindClicks,"
                             " veil: document.getElementById('veil').className,"
                             " idx: KE_REC.state.idx, msg: KE_REC.state.message})")
            check(st["behind"] == 0, f"모달 뒤 결제하기를 누르지 않음 (실제 {st['behind']}회)")
            check(st["veil"] == "on", "모달은 그대로 열려 있음 (사람이 봐야 함)")
            check(st["idx"] == 1, f"막힌 단계에서 멈춤 (idx={st['idx']})")
            check("가려" in (st["msg"] or ""), "가려서 못 눌렀다고 알림", st["msg"])
            print(f"      메시지: {st['msg']}")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "모달 가림 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
