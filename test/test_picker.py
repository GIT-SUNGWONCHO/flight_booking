"""모달이 열린 상태에서 셀렉터를 집을 수 있는지 + 패널을 옮길 수 있는지.

사용자 보고(2026-08-25):
  "콘솔은 원래 복붙이 안돼? 너무 불편한데"
  "패널은 모달열리면 안되고 지금 자리도 틀린거같애서 안쓰게되네"
모달이 뜨면 패널을 만질 수 없어 셀렉터를 알아낼 수단이 없었다. 키보드는 모달과
무관하게 먹으므로 Alt+P 로 집는다. 패널은 끌어서 옮기고 자리를 기억한다.

실행:  .venv/Scripts/python.exe test/test_picker.py
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
        ctx = launch_with_retry(p, user_data_dir=str(ROOT / ".test-profile-pick"), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.set_default_timeout(30000)
            ctx.add_init_script(js)
            pg.goto(FIXTURE, timeout=60000)
            pg.wait_for_timeout(600)

            # 모달을 띄운다 - 이 상태에서 패널은 만질 수 없다
            pg.evaluate("document.getElementById('a1').click()")
            pg.wait_for_timeout(300)
            check(pg.evaluate("document.getElementById('m').className") == "on",
                  "모달이 열린 상태")

            pg.keyboard.press("Alt+p")
            pg.wait_for_timeout(250)
            check(pg.evaluate("document.body.style.cursor") == "crosshair",
                  "Alt+P 로 집기 모드 진입")

            # 모달 안 버튼을 집는다
            pg.evaluate("""() => document.getElementById('btnScrollDown')
              .dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}))""")
            pg.wait_for_timeout(500)

            check(pg.evaluate("!!document.getElementById('ke-picked')"), "집기 결과창이 뜸")
            val = pg.evaluate(
                "() => { var t = document.querySelector('#ke-picked textarea');"
                " return t ? t.value : ''; }")
            check("#btnScrollDown" in val, "모달 안 버튼의 셀렉터를 집음", val[:60])
            check(pg.evaluate("window.__confirmed.length") == 0,
                  "집기만 하고 실제로 누르지는 않음")
            print("      집은 값: " + val.replace(chr(10), "  |  ")[:70])

            # 패널을 끌어 옮기고 위치를 기억하는지
            pg.evaluate("document.getElementById('ke-picked').remove()")
            head = pg.evaluate(
                "() => { const r = document.getElementById('ke-hud')"
                ".querySelector('h4').getBoundingClientRect();"
                " return {x: Math.round(r.left + 40), y: Math.round(r.top + 8)}; }")
            pg.mouse.move(head["x"], head["y"])
            pg.mouse.down()
            pg.mouse.move(300, 400, steps=6)
            pg.mouse.up()
            pg.wait_for_timeout(300)
            pos = pg.evaluate("window.KE_HUD.state.pos")
            check(pos is not None and pos["top"] > 250,
                  f"패널을 끌어 옮기고 자리를 기억 ({pos})")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "집기/드래그 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
