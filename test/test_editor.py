"""단계 편집 테스트.

실제로 겪은 두 가지를 그대로 재현한다:
  - 스크롤을 괜히 두 번 더 눌러 불필요한 단계가 낀 경우  -> 삭제
  - 눌렀어야 할 버튼(마일리지 적용)을 빼먹은 경우        -> 그 자리에 끼워넣기
그리고 고친 단계로 재생이 실제로 되는지까지 확인한다.

실행:  .venv/Scripts/python.exe test/test_editor.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
START = (ROOT / "test" / "fixture" / "booking.html").as_uri() + "?p=cal"

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(ROOT / ".test-profile-edit"), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            ctx.add_init_script(js)
            ctx.add_init_script("try{setTimeout(()=>{window.KE_AUTO.enabled=false},0)}catch(e){}")

            # ---------- 실수가 섞인 녹화 ----------
            pg.goto(START)
            pg.evaluate("window.KE_REC.clear(); window.KE_REC.record()")
            pg.click("button.date[data-i='6']")
            pg.click("#search")
            pg.wait_for_selector("#seat")
            # 여기서 '일반석' 을 눌러야 하는데 빼먹었다고 치고 #next 로 직행
            pg.click("#next")
            pg.wait_for_selector("#pax")
            pg.click("#pax")
            pg.click("#scroll")
            pg.click("#scroll")
            pg.click("#scroll")
            pg.click("#ag1")
            pg.click("#ag1")     # 괜히 한 번 더 눌러 동의를 꺼버린 실수
            pg.evaluate("window.KE_REC.stop()")

            before = pg.evaluate("window.KE_REC.state.steps.map(s => s.text)")
            check(len(before) == 9, f"실수 포함 9단계 녹화 (실제 {len(before)})", str(before))

            # ---------- 편집 1: 잘못 눌린 마지막 동의 삭제 ----------
            pg.evaluate("window.KE_REC.removeStep(8)")
            after_del = pg.evaluate("window.KE_REC.state.steps.map(s => s.text)")
            check(len(after_del) == 8, f"중복 동의 삭제 -> 8단계 (실제 {len(after_del)})")
            check(after_del.count("✓ 동의") == 1, "동의는 1개만 남음")

            # ---------- 편집 2: 빠뜨린 좌석 선택을 3번째 자리에 끼워넣기 ----------
            pg.goto((ROOT / "test" / "fixture" / "booking.html").as_uri() + "?p=result")
            pg.wait_for_selector("#seat")
            pg.evaluate("""() => {
              const el = document.querySelector('#seat');
              window.KE_EDIT.pick(step => { window.KE_REC.insertAt(2, step); window.__inserted = step; });
              el.click();
            }""")
            pg.wait_for_function("() => !!window.__inserted", timeout=5000)
            steps = pg.evaluate("window.KE_REC.state.steps.map(s => s.text)")
            check(len(steps) == 9, f"좌석 단계 삽입 -> 9단계 (실제 {len(steps)})")
            check(steps[2] == "일반석 E · KE927", f"3번째에 좌석이 들어감 (실제 {steps[2]!r})")
            # booking.html 은 좌석 클릭 시 __seatPicked 를 세운다.
            # 피커가 capture 단계에서 가로챘다면 이게 안 서 있어야 한다.
            check(pg.evaluate("!!window.__seatPicked") is False,
                  "피커로 지정만 하고 실제로 누르지는 않음")

            # ---------- 편집 3: 날짜 단계를 셀렉터 고정 ----------
            pg.evaluate("window.KE_REC.setStep(0, {selectorOnly: true})")
            check(pg.evaluate("window.KE_REC.state.steps[0].selectorOnly") is True,
                  "날짜 단계를 셀렉터 고정으로 전환")

            # ---------- 고친 단계로 재생 ----------
            pg.goto(START)
            pg.evaluate("() => { sessionStorage.clear(); window.KE_REC.reset(); window.KE_REC.play(); }")
            pg.wait_for_function("() => !!window.__ag1", timeout=25000)
            pg.wait_for_timeout(600)

            st = pg.evaluate(
                "() => ({seat: sessionStorage.getItem('seatPicked') === '1', ag1: window.__ag1,"
                " broke: !!window.__brokeAgreement, scrolls: window.__scrolls || 0,"
                " paid: !!window.__paid, idx: window.KE_REC.state.idx,"
                " total: window.KE_REC.state.steps.length})"
            )
            check(st["seat"], "고친 단계로 재생하니 좌석이 선택됨")
            check(st["ag1"] == "true", f"동의가 켜진 채로 끝남 (실제 {st['ag1']})")
            check(not st["broke"], "동의를 꺼버리지 않음")
            check(st["scrolls"] == 2, f"스크롤 2회 (실제 {st['scrolls']})")
            check(not st["paid"], "결제하기는 안 눌림")
            check(st["idx"] == st["total"], f"전 단계 완료 ({st['idx']}/{st['total']})")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "편집 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
