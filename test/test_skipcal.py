"""달력 건너뛰고 조회 페이지로 바로 들어가기 (백로그 1).

실측 27.7초 중 절반 이상이 대한항공 페이지가 그려지기를 기다린 시간이었다. 폴링을
조여봐야 몇 밀리초라, 남은 방법은 페이지를 덜 거치는 것뿐이다.

여기서 확인하는 것은 "빨라졌나" 가 아니라 "안전한가" 다:
  - 주소는 추측하지 않고 실제로 지나간 것을 붙잡아 쓰는가
  - 목표 날짜가 없으면 건너뛰지 않는가 (건너뛰면 날짜를 확인할 방법이 없다)
  - 조건이 안 맞으면 조용히가 아니라 이유를 알리고 달력으로 되돌아가는가
  - 바로 들어갔는데 엉뚱한 데 떨어지면 달력으로 복구하는가

실행:  .venv/Scripts/python.exe test/test_skipcal.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
FX = ROOT / "test" / "fixture" / "booking"
CAL = FX / "calendar-fare-bonus.html"
DEP = FX / "select-award-flight" / "departure.html"
BOUNCE = FX / "bounced.html"

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


STEPS = """[
  {sel:'#dep-fare-22', text:'22 08월 22일 (일)', tag:'div',
   url:'/booking/calendar-fare-bonus', dynamicDate:true},
  {sel:'#search', text:'검색', tag:'button', url:'/booking/calendar-fare-bonus'},
  {sel:'#seat', text:'프레스티지', tag:'button',
   url:'/booking/select-award-flight/departure'},
  {sel:'#next', text:'다음', tag:'button',
   url:'/booking/select-award-flight/departure'}
]"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")

    # 재생은 페이지 이동을 넘어 살아남도록 만들어져 있다 (그게 이 도구의 핵심이다).
    # 그래서 지난 실행이 playing=true 로 끝나 있으면 새 실행이 첫 페이지에서 곧바로
    # 단계를 이어 눌러 화면이 넘어가버린다. 프로필을 비우고 시작한다.
    profile = ROOT / ".test-profile-skip"
    shutil.rmtree(profile, ignore_errors=True)

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(profile), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.set_default_timeout(30000)
            ctx.add_init_script(js)

            def stop() -> None:
                """돌고 있는 재생을 멈춘다. 안 멈추면 다음 페이지에서 이어 눌러버린다."""
                pg.evaluate("() => { if (window.KE_REC) { KE_REC.state.playing = false;"
                            " KE_REC.state.playAfterReload = false; KE_REC.save(); } }")

            def land(url: str) -> None:
                """페이지가 뜨고 스크립트가 붙을 때까지 기다린다.

                지난 실행이 남긴 예약 상태가 있으면 스크립트가 뜨자마자 다른 데로
                이동시킬 수 있다. 고정된 시간만 기다리면 그 순간을 밟는다."""
                pg.goto(url, timeout=60000)
                pg.wait_for_function("() => !!window.KE_REC && !!window.KE_HUD", timeout=20000)

            land(CAL.as_uri())
            pg.evaluate("() => { localStorage.clear(); }")   # 지난 실행 흔적 제거

            # ---------- 1) 주소를 붙잡는다 ----------
            land(CAL.as_uri())
            pg.evaluate(f"() => {{ KE_REC.state.steps = {STEPS}; KE_REC.save(); }}")
            pg.reload()
            pg.wait_for_function("() => !!window.KE_REC", timeout=20000)
            base = pg.evaluate("KE_REC.state.baseLink")
            check(bool(base) and "calendar-fare-bonus" in (base or ""),
                  "달력 주소를 붙잡아둔다 (되돌아갈 곳)", str(base))

            # 달력에서 날짜를 고르고 검색 -> 조회 페이지
            pg.evaluate("() => { KE_REC.state.idx = 0; KE_REC.state.expectDate=''; KE_REC.play(); }")
            pg.wait_for_url("**/departure.html*", timeout=20000)
            pg.wait_for_timeout(600)
            deep = pg.evaluate("KE_REC.state.deepLink")
            dd = pg.evaluate("KE_REC.state.deepLinkDate")
            check(bool(deep) and "departure.html" in (deep or ""),
                  "지나간 조회 주소를 붙잡아둔다", str(deep))
            check("depDate=20270822" in (deep or ""), "고른 날짜가 그 주소에 들어 있다", str(deep))
            check(dd == "08-22", f"그때의 '가는 날' 을 함께 기억한다 (실제 {dd})")

            # ---------- 2) 목표 날짜가 없으면 건너뛰지 않는다 ----------
            pg.evaluate("() => { KE_HUD.state.skipCalendar = true; KE_HUD.save(); }")
            pg.fill("#ke-expect", "")          # 사용자가 하듯 입력해서 안내가 따라오는지 본다
            pg.dispatch_event("#ke-expect", "change")
            pg.wait_for_timeout(200)
            why = pg.evaluate("document.getElementById('ke-skipcal-why')?.textContent || ''")
            check("목표 날짜" in why, "목표 날짜가 없으면 이유를 보여준다", why)

            # ---------- 3) 조건이 맞으면 조회 페이지로 바로 간다 ----------
            stop()
            land(CAL.as_uri())                        # 달력에 서 있는 상태에서 발사
            pg.evaluate("() => { KE_REC.state.allowPay = false; KE_REC.save();"
                        " KE_HUD.state.skipCalendar = true; KE_HUD.save(); }")
            pg.fill("#ke-expect", "08-23")     # 붙잡을 때와 다른 날 -> 주소를 고쳐야 한다
            pg.dispatch_event("#ke-expect", "change")
            pg.wait_for_timeout(200)
            why = pg.evaluate("document.getElementById('ke-skipcal-why')?.textContent || ''")
            check("준비됨" in why, "준비되면 몇 단계부터 시작할지 알려준다", why)

            pg.evaluate("() => KE_HUD.fire('테스트')")
            pg.wait_for_url("**/departure.html*", timeout=20000)
            pg.wait_for_timeout(700)
            url = pg.url
            check("depDate=20270823" in url, "가는 날을 목표 날짜로 바꿔 들어간다", url)
            check("retDate=20270905" in url, "오는 날은 건드리지 않는다 (왕복 안전)", url)
            clicked = pg.evaluate("window.__clicks || []")
            check("search" not in clicked, f"달력의 검색을 누르지 않았다 (실제 {clicked})")
            idx = pg.evaluate("KE_REC.state.idx")
            check(idx >= 2, f"조회 페이지 단계(3번)부터 시작했다 (실제 idx={idx})")

            # ---------- 4) 엉뚱한 데 떨어지면 달력으로 되돌아간다 ----------
            stop()
            land(CAL.as_uri())
            pg.evaluate("""() => {
              KE_REC.state.playing = false;
              KE_REC.state.deepLink = 'BOUNCE';
              KE_REC.state.deepLinkDate = '08-22';
              KE_REC.state.expectDate = '08-22';   // 달력에 실제로 있는 날 - 되돌아가서 끝까지 가야 한다
              KE_REC.save();
            }""".replace("BOUNCE", BOUNCE.as_uri()))
            pg.evaluate("() => KE_HUD.fire('튕김 테스트')")
            pg.wait_for_url("**/bounced.html*", timeout=20000)
            check(True, "바로 시작이 엉뚱한 곳으로 떨어졌다 (상황 재현)")
            # 여기서 멈추면 그날 좌석을 놓친다. 달력으로 돌아가 처음부터 끝까지 가야 한다.
            pg.wait_for_url("**/departure.html*", timeout=30000)
            pg.wait_for_function("() => !!window.KE_REC", timeout=20000)
            clicked = pg.evaluate("window.__clicks || []")
            check("depDate=20270822" in pg.url,
                  "달력으로 돌아가 날짜를 골라 다시 조회까지 갔다", pg.url)
            check("seat" in clicked, f"멈추지 않고 이어서 진행했다 (실제 {clicked})")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "달력 건너뛰기 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
