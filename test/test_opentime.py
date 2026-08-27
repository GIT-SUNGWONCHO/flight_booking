"""오픈시각 입력 해석 + 너무 먼 예약 경고.

사용자 보고(2026-08-27): "시간 지정해서 시작하는게 안됨". 확인해보니 오픈시각에
2027-08-27 이 들어가 있었다(여행 날짜 연도가 그대로 들어감). 무장은 정상이었고
1년 뒤를 기다리는 중이었다. 카운트다운이 "T-8759:59:52" 라 눈에 안 들어왔다.

- 시각만 쳐도 되게 한다("09:00" -> 오늘 09시, 지났으면 내일). 매일 09:00 에 열리는
  도구라 연도를 칠 일이 애초에 없다.
- 하루가 넘으면 카운트다운을 "⚠ N일 뒤" 로 크게 띄운다.

실행:  .venv/Scripts/python.exe test/test_opentime.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
FIXTURE = (ROOT / "test" / "fixture" / "booking.html").as_uri() + "?p=cal"

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(ROOT / ".test-profile-open"), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.set_default_timeout(30000)
            ctx.add_init_script(js)
            pg.goto(FIXTURE, timeout=60000)
            pg.wait_for_timeout(600)

            # 시각만 입력 -> 24시간 안으로 잡혀야 한다
            for raw in ("09:00", "23:59:00", "00:01"):
                d = pg.evaluate("""(raw) => {
                  window.KE_HUD.state.targetKst = raw;
                  const t = window.KE_HUD.targetMs ? window.KE_HUD.targetMs() : null;
                  return t ? t - Date.now() : null;
                }""", raw)
                check(d is not None and 0 < d <= 86400000 + 60000,
                      f"시각만 입력 {raw!r} -> 24시간 안 (실제 {None if d is None else round(d/3600000,2)}h)")

            # 1년 뒤로 잡히면 카운트다운이 눈에 띄게 경고해야 한다
            pg.evaluate("""() => {
              const d = new Date(Date.now() + 365*86400e3);
              window.KE_HUD.state.targetKst =
                d.getFullYear() + '-01-01 09:00:00';
              window.KE_HUD.save();
            }""")
            pg.wait_for_timeout(300)
            cd = pg.evaluate("document.getElementById('ke-cd').textContent")
            check("일 뒤" in cd, f"하루 넘으면 '⚠ N일 뒤' 로 표시 (실제 {cd!r})")

            # 가까운 시각이면 평소대로 T-HH:MM:SS
            pg.evaluate("""() => {
              window.KE_HUD.state.targetKst = '09:00';
              window.KE_HUD.save();
            }""")
            pg.wait_for_timeout(300)
            cd2 = pg.evaluate("document.getElementById('ke-cd').textContent")
            check(cd2.startswith("T-"), f"24시간 안이면 T-HH:MM:SS (실제 {cd2!r})")

            # 두 입력칸이 서로 다른 것을 가리킨다는 게 라벨만 봐도 드러나야 한다.
            # 여행 연도(2027)를 발사 시각에 넣어 1년 뒤로 예약된 사고의 근본 원인이다.
            html = pg.evaluate("document.getElementById('ke-hud').innerHTML")
            check("발사 시각" in html and "매크로가 움직일" in html, "발사 시각 라벨이 용도를 밝힘")
            check("달력에서 고를 여행일" in html, "목표 날짜 라벨이 용도를 밝힘")
            check("오픈시각" not in html, "헷갈리던 '오픈시각' 표현이 남아있지 않음")

            # 연월일이 눈에 보여야 헷갈리지 않는다는 요청 - 비어 있으면 채워 넣는다
            v = pg.evaluate("document.getElementById('ke-target').value")
            import re as _re
            check(bool(_re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", v)),
                  f"발사 시각이 연월일까지 채워져 있음 (실제 {v!r})")
            yr = pg.evaluate("new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul'}).format(new Date()).slice(0,4)")
            check(v.startswith(yr), f"연도가 올해로 채워짐 (실제 {v[:4]}, 올해 {yr})")

            # 기본값이 오늘 09:00 이면 이미 지난 시각이라 무장이 바로 풀린다.
            # 다음 09시로 잡아야 "왜 안 되지" 가 없다.
            pg.evaluate("() => { window.KE_HUD.state.targetKst=''; window.KE_HUD.save(); }")
            pg.reload()
            pg.wait_for_timeout(800)
            pg.evaluate("document.getElementById('ke-arm').click()")
            pg.wait_for_timeout(400)
            check(pg.evaluate("window.KE_HUD.state.armed") is True,
                  "기본 발사 시각으로 바로 무장됨 (다음 09시)",
                  pg.evaluate("document.getElementById('ke-status').textContent"))

            # 무장 중에는 소리로 백그라운드 스로틀링을 막는다
            check(pg.evaluate("!!(window.KE_HUD.state.armed)") , "무장 유지")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "오픈시각 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
