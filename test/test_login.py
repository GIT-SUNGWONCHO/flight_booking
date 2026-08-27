"""
로그인이 풀렸으면 정시가 돼도 쏘지 않는다.

무장은 보통 발사보다 한참 전에 걸어둔다. 그 사이 세션이 풀리면 09:00 에 발사돼도
로그인 화면만 붙잡고 헛돈다. 화면 앞에 없으면 그날 좌석은 그대로 날아간다.
쏘기 전에 확인하고, 아니면 소리로 사람을 부른다.

실행:  .venv/Scripts/python.exe test/test_login.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
BASE = (ROOT / "test" / "fixture" / "login.html").as_uri()

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(ROOT / ".test-profile-daily"), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.set_default_timeout(30000)
            ctx.add_init_script(js)

            # --- 로그인 판정 ---
            pg.goto(BASE, timeout=60000)
            pg.wait_for_timeout(500)
            check(pg.evaluate("KE_UTIL.loggedOut()") is False, "마이페이지가 보이면 로그인 상태")

            pg.goto(BASE + "?out=1", timeout=60000)
            pg.wait_for_timeout(500)
            check(pg.evaluate("KE_UTIL.loggedOut()") is True, "로그인 버튼만 보이면 로그아웃 상태")

            # --- 로그아웃이면 발사하지 않는다 ---
            pg.evaluate("""() => {
              window.KE_REC.state.steps = [{sel:'#date', text:'22 08월 22일 (일)',
                                            tag:'button', url:'/x'}];
              window.KE_REC.save();
              window.KE_HUD.state.armed = true;
              window.KE_HUD.save();
              window.__fired = window.KE_HUD.fire('테스트');
            }""")
            pg.wait_for_timeout(500)
            st = pg.evaluate("""() => ({fired: window.__fired, clicks: window.__clicks,
              armed: KE_HUD.state.armed, title: document.title,
              status: document.getElementById('ke-status').textContent})""")
            check(st["fired"] is False, "로그아웃이면 발사를 취소")
            check(st["clicks"] == 0, f"아무것도 누르지 않음 (실제 {st['clicks']}회)")
            check(st["armed"] is False, "무장을 풀어 헛돌지 않게 함")
            check("로그인" in (st["status"] or ""), "왜 취소했는지 알림", st["status"])
            check(st["title"].startswith("⚠멈춤⚠"), "소리/제목으로 사람을 부름", st["title"][:30])

        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "로그인 확인 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
