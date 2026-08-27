"""달력을 건너뛰고 조회 화면에서 그대로 시작하기 (백로그 1).

처음에는 조회 주소에 날짜를 박아 밖에서 뛰어들려고 했다. 실측에서 막혔다 - 그 주소는
/booking/select-award-flight/departure 뿐이고 물음표 뒤가 비어 있으며, 응답에
jsessionId 와 pageTicket 이 있다. 서버가 흐름 순서를 강제한다는 뜻이라 중간 페이지로
뛰어드는 것 자체를 막는다.

방법을 바꿨다: 이미 조회 화면에 서 있다가 그 자리에서 새로고침한다. 세션 안에 있으니
티켓도 살아 있고, 주소에 날짜가 없어도 상관없다. 조회 화면은 자기 화면에 7일치 날짜
띠를 들고 있어서 새로 열린 날도 거기 있다. 달력 한 장과 그 전환이 통째로 빠진다.

여기서 확인하는 것은 "빨라졌나" 가 아니라 "엉뚱한 날을 누르지 않는가" 다. 3초 벌자고
잘못된 날짜로 마일리지를 태우는 건 말이 안 되므로, 조금이라도 확신이 없으면 건너뛰지
않고 달력으로 가야 한다.

실행:  .venv/Scripts/python.exe test/test_skipcal.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
FX = ROOT / "test" / "fixture" / "booking"

# 픽스처를 file:// 로 열면 페이지가 자기 API 를 XHR 로 못 부른다(크롬이 file 간
# 요청을 막는다). 그런데 이 기능의 판정 근거가 바로 그 API 응답이라 그러면 아무것도
# 확인할 수 없다. 가짜 호스트를 가로채 파일로 응답한다 - 덤으로 주소 경로가 실제와
# 같아져서 "조회 페이지인가" 판정도 진짜와 동일하게 검사된다.
HOST = "https://ke.test"
CAL = HOST + "/booking/calendar-fare-bonus"
DEP = HOST + "/booking/select-award-flight/departure"

MIME = {".html": "text/html", ".json": "application/json"}


def availability(day: str, seats: bool) -> str:
    """조회 화면이 좌석을 그릴 때 쓰는 응답. 실측(2026-08-27) 모양 그대로.

    좌석이 아직 안 열린 날이면 availFlightList 가 비어 서버 응답에서 날짜를 알 수
    없다 - 그때는 검색 위젯만이 근거가 된다. 그 상황을 그대로 재현해야 의미가 있다."""
    strip = [f"202708{d:02d}" for d in range(18, 25)]
    flights = [{
        "flightId": "0", "departureDate": day + "132000",
        "flightInfoList": [{"carrierCode": "KE", "flightNumber": "931"}],
        "commercialFareFamilyList": [
            {"fareFamily": "KEBONUSPR", "seatCount": "1", "soldout": False,
             "totalMileage": "62500"}],
    }] if seats else []
    return json.dumps({"upsellBoundAvailList": [{
        "boundId": "0",
        "upsellCalendarFareList": [{"date": d} for d in strip],
        "availFlightList": flights,
    }]}, ensure_ascii=False)


def serve(route):
    url = route.request.url
    path = url.split("?")[0][len(HOST):]
    q = dict(pair.split("=", 1) for pair in url.split("?")[1].split("&")) if "?" in url else {}
    if path.endswith("awardAvailability.json"):
        # 날짜와 좌석 유무는 요청에 따라 만들어 준다. 고정 파일로 두면 화면이 보는
        # 날짜와 응답의 날짜가 어긋나 매크로가(옳게) 거부해버린다.
        route.fulfill(status=200, content_type="application/json",
                      body=availability(q.get("d", "20270821"), q.get("seats") == "1"))
        return
    f = FX.parent / path.lstrip("/")
    if f.is_dir() or not f.suffix:
        f = f.with_suffix(".html")
    if not f.exists():
        route.fulfill(status=404, body="not found")
        return
    route.fulfill(status=200, content_type=MIME.get(f.suffix, "text/plain"),
                  body=f.read_bytes())

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


STEPS = """[
  {sel:'#dep-fare-22', text:'22 08월 22일 (일)', tag:'div',
   url:'/booking/calendar-fare-bonus', dynamicDate:true},
  {sel:'#search', text:'검색', tag:'button', url:'/booking/calendar-fare-bonus'},
  /* 실제 steps.json 과 같이 좌석 단계는 dynamicCabin 이다 - 고정 셀렉터가 아니라
     그날 화면에서 등급으로 찾는다. 좌석이 아직 안 열렸을 때 다시 불러오는 것도
     이 단계에 걸려 있다. */
  {sel:'#seat', text:'프레스티지', tag:'button', dynamicCabin:true,
   url:'/booking/select-award-flight/departure'},
  {sel:'#next', text:'다음', tag:'button',
   url:'/booking/select-award-flight/departure'}
]"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")
    profile = ROOT / ".test-profile-skip"
    shutil.rmtree(profile, ignore_errors=True)

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(profile), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.set_default_timeout(30000)
            ctx.add_init_script(js)
            ctx.route(HOST + "/**", serve)

            def land(url: str, fresh_loads: bool = False) -> None:
                pg.goto(url, timeout=60000)
                pg.wait_for_function("() => !!window.KE_REC && !!window.KE_HUD", timeout=20000)
                if fresh_loads:
                    # 픽스처의 로드 횟수는 sessionStorage 에 쌓인다. 앞 케이스가
                    # 올려둔 값을 그대로 두면 "아직 좌석 없음" 상황이 재현되지 않는다.
                    pg.evaluate("() => { sessionStorage.removeItem('loads'); }")
                    pg.reload()
                    pg.wait_for_function("() => !!window.KE_HUD", timeout=20000)

            def setup(expect: str, skip: bool = True) -> None:
                pg.evaluate(f"""() => {{
                  KE_REC.state.steps = {STEPS};
                  KE_REC.state.playing = false; KE_REC.state.playAfterReload = false;
                  KE_REC.state.allowPay = false;
                  KE_REC.state.expectDate = {expect!r};
                  KE_REC.state.cabin = '프레스티지';
                  KE_REC.save();
                  KE_HUD.state.startAt = {'departure' if skip else 'calendar'!r};
                  KE_HUD.save();
                  KE_HUD.render();
                }}""")

            def why() -> str:
                return pg.evaluate("document.getElementById('ke-skipcal-why')?.textContent || ''")

            # ---------- 거절해야 하는 경우들 ----------
            land(CAL)
            setup("08-21")
            check("조회 페이지가 아닙니다" in why(),
                  "조회 모드인데 달력에 서 있으면 그렇다고 말한다", why())

            land(DEP)
            pg.wait_for_timeout(400)
            setup("")
            check("목표 날짜" in why(), "목표 날짜가 없으면 건너뛰지 않는다", why())

            setup("08-23")
            check("이 화면은 08-21" in why() and "08-23" in why(),
                  "보고 있는 날과 목표가 다르면 건너뛰지 않는다 (엉뚱한 날 방지)", why())
            check("맞춰두고 대기" in why(), "무엇을 해야 하는지 알려준다", why())

            # ---------- 되는 경우 ----------
            setup("08-21")
            check("준비됨" in why() and "08-21" in why(),
                  "보고 있는 날 = 목표면 준비됐다고 한다", why())

            before = pg.evaluate("window.__loads")
            pg.evaluate("() => KE_HUD.fire('테스트')")
            pg.wait_for_function(f"() => window.__loads > {before}", timeout=20000)
            pg.wait_for_function("() => !!window.KE_REC", timeout=20000)
            check("departure" in pg.url, "같은 화면에 그대로 있다 (달력으로 안 감)", pg.url)

            pg.wait_for_function("() => (window.__clicks||[]).includes('next')", timeout=20000)
            clicked = pg.evaluate("window.__clicks || []")
            check(clicked[:2] == ["seat", "next"],
                  f"조회 페이지 단계(3·4번)부터 눌렀다 (실제 {clicked})")
            check(pg.evaluate("KE_REC.state.idx") == 4, "끝까지 갔다")

            # ---------- 좌석이 아직 없어도 날짜를 안다 ----------
            # 09:00 직전에 목표 날짜로 맞춰두고 기다리는 상황. 그날 좌석이 아직
            # 없으므로 서버 응답에는 날짜가 없다. 검색 위젯만 보고 알아내야 한다.
            land(DEP + "?depDate=20270822&empty=1")
            pg.wait_for_timeout(400)
            setup("08-22")
            check(pg.evaluate("KE_UTIL.searchedDate()") == "08-22",
                  "좌석이 없어도 검색 위젯에서 조회 날짜를 읽는다",
                  str(pg.evaluate("KE_UTIL.searchedDate()")))
            check("준비됨" in why(),
                  "좌석이 아직 없어도 '이 날짜로 대기 중' 이면 준비된 것이다", why())

            # ---------- 손으로 ▶ 재생 을 눌러도 같은 곳에서 시작한다 ----------
            # 실측(2026-08-27): 조회 화면 모드로 해놓고 ▶ 재생 을 눌렀더니 1단계
            # (달력 날짜 클릭)부터 돌아, 조회 화면에 있지도 않은 dep-fare- 셀을
            # 20초 동안 찾다 멈췄다. 사람이 시험해보는 가장 자연스러운 경로가 그것이다.
            land(DEP + "?depDate=20270821", fresh_loads=True)
            setup("08-21")
            pg.evaluate("() => { KE_REC.state.stepTimeoutMs = 3000; KE_REC.save(); }")
            pg.click("#ke-play")
            pg.wait_for_function("() => (window.__clicks||[]).includes('next')", timeout=20000)
            clicked = pg.evaluate("window.__clicks || []")
            check(clicked[:2] == ["seat", "next"],
                  f"▶ 재생 도 3단계부터 시작한다 (실제 {clicked})")
            check(pg.evaluate("KE_REC.state.problem") is False,
                  "1단계를 찾다 멈추지 않는다",
                  str(pg.evaluate("KE_REC.state.message")))

            # 조건이 안 맞으면 헛돌리지 말고 이유를 말한다
            land(CAL)
            pg.evaluate("() => { KE_HUD.state.startAt = 'departure'; KE_HUD.save();"
                        " KE_REC.state.idx = 0; KE_REC.save(); }")
            pg.click("#ke-play")
            pg.wait_for_timeout(600)
            check(pg.evaluate("KE_REC.state.playing") is False,
                  "조회 화면이 아니면 ▶ 재생 이 헛돌지 않는다")
            toast = pg.evaluate("document.getElementById('ke-toast')?.textContent || ''")
            check("조회 화면에서 시작할 수 없습니다" in toast, "왜 안 되는지 말해준다", toast)

            # ---------- 09:00 정각: 좌석이 조금 늦게 열린다 ----------
            # 정각에 새로고침해도 서버가 좌석을 몇 백 밀리초 늦게 푸는 경우가 있다.
            # 여기서 20초를 기다리다 포기하면 그날 좌석은 그대로 날아간다.
            # 달력에서 목표 날짜를 기다릴 때처럼 다시 불러와서 봐야 한다.
            land(DEP + "?depDate=20270822&opensAfter=3", fresh_loads=True)
            setup("08-22")
            pg.evaluate("() => { KE_REC.state.stepTimeoutMs = 4000; KE_REC.save(); }")
            check(pg.evaluate("!document.getElementById('seat')"),
                  "첫 화면에는 좌석이 아직 없다 (상황 재현)")

            pg.evaluate("() => KE_HUD.fire('정각 테스트')")
            pg.wait_for_function("() => (window.__clicks||[]).includes('next')", timeout=30000)
            loads = pg.evaluate("window.__loads")
            check(loads >= 3, f"좌석이 나올 때까지 다시 불러왔다 (로드 {loads}회)")
            check("departure" in pg.url, "그 사이에도 달력으로 새지 않는다", pg.url)
            check(pg.evaluate("KE_REC.state.problem") is False,
                  "포기하지 않고 끝까지 갔다",
                  str(pg.evaluate("KE_REC.state.message")))

            # ---------- 끝내 안 나오면 사람을 부른다 ----------
            land(DEP + "?depDate=20270822&opensAfter=999", fresh_loads=True)
            setup("08-22")
            pg.evaluate("""() => {
              KE_REC.state.openWaitMaxMs = 2500;   // 실제로는 180초
              KE_REC.state.openWaitSince = 0;
              KE_REC.save();
            }""")
            pg.evaluate("() => KE_HUD.fire('안 열리는 경우')")
            pg.wait_for_function("() => window.KE_REC && !window.KE_REC.state.playing"
                                 " && window.KE_REC.state.problem", timeout=40000)
            msg = pg.evaluate("KE_REC.state.message")
            check("안 나왔습니다" in (msg or ""),
                  "무한히 새로고침하지 않고 사람을 부른다", msg)
            print(f"      {msg}")
            pg.evaluate("() => { KE_REC.state.openWaitMaxMs = 180000; KE_REC.save(); }")

            # ---------- 꺼두면 원래대로 ----------
            land(DEP)
            pg.wait_for_timeout(400)
            setup("08-21", skip=False)
            check("달력 화면이 아닙니다" in why(),
                  "달력 모드로 되돌리면 '여기는 달력이 아니다' 라고 말한다", why())
            land(CAL)
            setup("08-21", skip=False)
            check("준비됨" in why() and "1단계" in why(),
                  "달력 모드로 달력에 서 있으면 준비됨", why())
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "달력 건너뛰기 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
