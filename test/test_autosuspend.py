"""재생 중 자동클릭 정지 + 건너뛴 단계 보고 테스트.

실사이트 로그에서 드러난 문제:
  6단계(5.86s) 직후 자동클릭이 확인/동의를 먼저 눌러 위험물 팝업을 띄웠고,
  재생은 7단계 버튼이 팝업에 가려 10초를 기다렸다(7단계가 16.65s 에 실행).
  재생이 끝난 뒤에도 자동클릭이 팝업을 눌러 사람이 보기 전에 치워버렸다.
  게다가 페이지가 바뀌면 엔진이 기본값(ON)으로 되살아나 다시 충돌했다.

실행:  .venv/Scripts/python.exe test/test_autosuspend.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
BASE = (ROOT / "test" / "fixture" / "booking.html").as_uri()

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(ROOT / ".test-profile-auto"), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            ctx.add_init_script(js)
            pg.goto(BASE + "?p=cal")
            pg.wait_for_timeout(400)
            check(pg.evaluate("window.KE_AUTO.enabled") is True, "재생 전에는 자동클릭 ON")

            # 2번은 일부러 못 찾게 해서 resync 로 건너뛰게 만든다.
            # 마지막 단계가 페이지를 이동시키지 않도록 구성해야 완료 메시지를 볼 수 있다.
            pg.evaluate("""() => {
              const R = window.KE_REC;
              R.state.steps = [
                {sel:"button.date[data-i='5']", text:'15(일)', tag:'button', url:'/x'},
                {sel:'#존재하지않음', text:'있을리없는라벨입니다', tag:'button', url:'/x', selectorOnly:true},
                {sel:"button.date[data-i='6']", text:'16(월)', tag:'button', url:'/x'}
              ];
              R.state.resyncAfterMs = 250; R.state.idx = 0; R.state.startedAt = 0;
              R.state.skipped = 0; R.state.skippedList = [];
              R.play();
            }""")
            check(pg.evaluate("window.KE_AUTO.enabled") is False, "재생 시작하면 자동클릭 OFF")

            pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=20000)
            st = pg.evaluate("() => ({msg: KE_REC.state.message, list: KE_REC.state.skippedList})")
            check(bool(st["list"]) and "2번" in st["list"][0],
                  "건너뛴 단계를 이름까지 기록", str(st["list"]))
            check("2번" in (st["msg"] or ""),
                  "완료 메시지가 어느 단계를 건너뛰었는지 밝힘", st["msg"])

            # 제목 표시는 페이지 이동 전에 봐야 한다 (이동하면 원래 제목으로 돌아감).
            # 판정이 메시지 문구 매칭이면 표현만 바꿔도 조용히 거짓 완료가 된다.
            title = pg.title()
            check(title.startswith("⚠멈춤⚠"), "건너뜀이 있으면 제목이 ⚠멈춤⚠", title[:40])
            print(f"      제목  : {title[:40]}")

            # 페이지가 바뀌면 엔진이 새로 초기화된다. 그래도 꺼진 상태여야 한다.
            pg.goto(BASE + "?p=result")
            pg.wait_for_timeout(500)
            check(pg.evaluate("window.KE_AUTO.enabled") is False, "페이지 이동 후에도 OFF 유지")

            # 사용자가 다시 켜면 그 상태도 이동을 넘어 유지된다
            pg.evaluate("window.KE_REC.resumeAuto()")
            pg.goto(BASE + "?p=cal")
            pg.wait_for_timeout(500)
            check(pg.evaluate("window.KE_AUTO.enabled") is True, "사용자가 켜면 이동 후에도 ON 유지")
            print(f"      메시지: {st['msg']}")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "자동클릭 정지 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
