"""달력에서 가장 나중 날짜를 고르는지 + 목표 날짜 형식.

사용자 보고(2026-08-27): 22일이 최신인데 20일이 선택됐다. 요금등급 마커(E/P)가
화면이 다 그려진 뒤에야 붙는데, 그 전에 훑으면 마커가 붙은 마지막 셀을 골랐다.
마커와 무관하게 "날짜 숫자가 있는 마지막 셀" 을 고르고, 엉뚱한 날은 목표 날짜가 막는다.
목표 날짜는 "08-27" 형식으로 넣는다 (예전에는 라벨에 그대로 들어있어야 했다).

실행:  .venv/Scripts/python.exe test/test_calendar.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
FIXTURE = (ROOT / "test" / "fixture" / "calendar.html").as_uri()

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(ROOT / ".test-profile-cal"), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.set_default_timeout(30000)
            ctx.add_init_script(js)
            pg.goto(FIXTURE, timeout=60000)

            # 마커가 붙기 전 - 예전 방식이면 20일을 골랐다
            early = pg.evaluate("() => { var e = KE_UTIL.findLatestOpenDate(); return e ? e.id : null; }")
            check(early == "dep-fare-3-4", f"마커가 없어도 가장 나중 날짜 (실제 {early})")

            pg.wait_for_timeout(900)
            late = pg.evaluate("() => { var e = KE_UTIL.findLatestOpenDate(); return e ? e.id : null; }")
            check(late == "dep-fare-3-4", f"마커가 붙은 뒤에도 같은 날짜 (실제 {late})")
            lab = pg.evaluate("() => KE_UTIL.label(KE_UTIL.findLatestOpenDate())")
            check(lab.startswith("22"), f"22일이 선택됨 (실제 {lab[:20]})")

            # 매진/운항없음 셀은 후보에서 빠진다
            check("23" not in lab, "aria-disabled 인 23일은 고르지 않음", lab[:20])

            for expect, want in (("08-22", True), ("8/22", True), ("08월 22일", True),
                                 ("2027-08-22", True), ("08-20", False)):
                got = pg.evaluate("(e) => KE_UTIL.sameDate(e, KE_UTIL.label(KE_UTIL.findLatestOpenDate()))",
                                  expect)
                check(got is want, f"목표 날짜 {expect!r} -> {want} (실제 {got})")
            # ---- 목표 날짜가 '가장 나중 날짜' 가 아니어도 그 날을 고른다 ----
            # 실측(2026-08-28): 목표 08-18 인데 늘 최신일(08-22)만 찾아놓고
            # "목표 날짜가 아직 없습니다" 하며 달력만 무한 새로고침했다.
            pg.goto(FIXTURE)
            pg.wait_for_timeout(900)
            got = pg.evaluate("() => KE_UTIL.label(KE_UTIL.findOpenDate('dep-fare-', '08-20'))")
            check("08월 20일" in (got or ""),
                  "목표가 최신일이 아니어도 그 날짜 칸을 집는다", str(got))
            got = pg.evaluate("() => KE_UTIL.label(KE_UTIL.findOpenDate('dep-fare-', ''))")
            check("08월 22일" in (got or ""),
                  "목표를 안 정하면 가장 나중 날짜를 집는다 (지금까지 하던 대로)", str(got))
            got = pg.evaluate("() => KE_UTIL.findOpenDate('dep-fare-', '08-23')")
            check(got is None,
                  "매진/비활성 날짜는 집지 않는다", str(got))
            got = pg.evaluate("() => KE_UTIL.findOpenDate('dep-fare-', '12-25')")
            check(got is None, "달력에 없는 날은 집지 않는다", str(got))
            seen = pg.evaluate("() => KE_UTIL.openDateCells('dep-fare-')"
                               ".map(c => KE_UTIL.monthDay(KE_UTIL.label(c)))")
            check(seen == ["08-19", "08-20", "08-21", "08-22"],
                  f"고를 수 있는 날 목록을 그대로 알려준다 (실제 {seen})")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "달력/목표날짜 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
