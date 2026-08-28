"""창이 좁으면 사이트가 모바일 화면으로 바뀐다 - 그때 멈추지 말고 짚어준다.

실측(2026-08-28): 창을 줄여놓고 돌렸더니 12단계(아래로 스크롤)에서 멈췄고,
최대화하면 잘 됐다. 좁은 화면에서는 그 모달에 [아래로 스크롤] 버튼이 아예 없다 -
그냥 스크롤하는 모바일 레이아웃이기 때문이다.

녹화한 단계는 넓은 화면 기준이므로, 좁은 창에서는 셀렉터도 라벨도 안 맞는다.
"요소를 못 찾음" 만 보면 원인을 알 수 없으니 그 자리에서 창 너비를 짚어준다.

여기에 더해, 창이 가려져 있던 시간은 인내심에서 뺀다. 가려진 창은 우리 tick 만
늦춰지는 게 아니라 그 페이지 자신이 늦춰져서, 벽시계로 재면 멀쩡한 화면을 두고
먼저 포기한다.

실행:  .venv/Scripts/python.exe test/test_narrow.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
FIXTURE = (ROOT / "test" / "fixture" / "gauntlet.html").as_uri()

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")
    profile = ROOT / ".test-profile-narrow"
    shutil.rmtree(profile, ignore_errors=True)

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(profile), headless=True,
                                viewport={"width": 1400, "height": 900})
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.set_default_timeout(20000)
            ctx.add_init_script(js)
            pg.goto(FIXTURE)
            pg.wait_for_function("() => !!window.KE_HUD", timeout=20000)

            def warn() -> str:
                return pg.evaluate("document.getElementById('ke-width')?.textContent || ''")

            # 녹화하면 그때의 창 너비가 남는다
            pg.evaluate("() => { KE_REC.record(); KE_REC.stop(); }")
            w = pg.evaluate("KE_REC.state.recordedWidth")
            check(w and w > 1000, f"녹화할 때의 창 너비를 남긴다 (실제 {w})")

            pg.evaluate("() => KE_HUD.render()")
            check(warn() == "", "넓은 창에서는 아무 말도 하지 않는다", warn())

            # 좁히면 미리 알린다 - 09:00 에 알면 늦다
            pg.set_viewport_size({"width": 700, "height": 900})
            pg.evaluate("() => KE_HUD.render()")
            check("창이 좁습니다" in warn(), "좁히면 미리 알린다", warn())
            check("700px" in warn() and str(w) in warn(),
                  "지금 너비와 필요한 너비를 같이 알려준다", warn())
            print(f"      {warn()}")

            # 못 찾고 멈출 때도 그 이유를 짚어준다
            pg.evaluate("""() => {
              const R = window.KE_REC;
              R.state.steps = [{sel:'#nope-not-here', text:'있을 리 없는 버튼',
                                tag:'button', url: location.pathname, selectorOnly:true}];
              R.state.stepTimeoutMs = 800;
              R.reset(); R.save(); R.play();
            }""")
            pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=15000)
            msg = pg.evaluate("KE_REC.state.message")
            check("창이 좁습니다" in (msg or ""),
                  "멈춤 메시지에도 창 너비를 짚어준다 (원인을 못 찾고 헤매지 않게)", msg)
            print(f"      {msg}")

            # ---- 이 크롬이 가려진 창을 늦추는지 직접 잰다 ----
            # 말로만 "최소화하지 마세요" 라고 하면 확인할 방법이 없다. 재서 보여준다.
            # 참고: Playwright 는 스로틀링을 끄는 플래그로 크롬을 띄운다. 그래서
            # 테스트에서는 이 문제가 아예 재현되지 않는다 - 실제 크롬과 다른 지점이다.
            th = pg.evaluate("() => KE_REC.throttle()")
            check(isinstance(th, dict) and "gapMs" in th and "samples" in th,
                  "가려진 동안의 tick 간격을 재고 있다", str(th))
            pg.evaluate("() => KE_HUD.render()")
            note = pg.evaluate("document.getElementById('ke-throttle')?.textContent || ''")
            check(note == "" or "늦" in note,
                  "잰 결과를 사람이 읽을 말로 보여준다 (표본이 없으면 조용히)", note)
            print(f"      throttle={th} note={note!r}")

            # 넓히면 그 말은 사라진다 (엉뚱한 경고로 헷갈리지 않게)
            pg.set_viewport_size({"width": 1400, "height": 900})
            pg.evaluate("""() => {
              KE_REC.reset(); KE_REC.save(); KE_REC.play();
            }""")
            pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=15000)
            msg = pg.evaluate("KE_REC.state.message")
            check("창이 좁습니다" not in (msg or ""),
                  "넓은 창에서는 그 말을 붙이지 않는다", msg)
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "좁은 창 안내 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
