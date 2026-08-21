"""유저스크립트(HUD) 경로 통합 테스트.

Playwright 러너와 달리 유저스크립트는 HUD 가 흐름을 몰기 때문에 별도로 검증한다:
  연습 발사 예약 -> 카운트다운 -> 정시에 조회 버튼 클릭 -> 좌석 등장 즉시 클릭
  -> autoconfirm 이 모달 체인 통과 -> 성공 감지로 자동 정지

실행:  .venv/Scripts/python.exe test/test_hud.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
FIXTURE = (ROOT / "test" / "fixture" / "gauntlet.html").as_uri()
EXPECTED = ["확인", "다음 »", "전체 동의", "계속하기"]

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")
    profile = ROOT / ".test-profile-hud"

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(profile), headless=True)
        errors: list[str] = []
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            ctx.add_init_script(js)
            pg.goto(FIXTURE)
            pg.wait_for_timeout(600)

            check(pg.evaluate("typeof window.KE_AUTO") == "object", "autoconfirm 로드")
            check(pg.evaluate("typeof window.KE_HUD") == "object", "HUD 로드")
            check(pg.evaluate("!!document.getElementById('ke-hud')"), "패널 렌더")

            # 패널의 새 컨트롤들이 실제로 존재하는지
            for el, name in (("ke-auto", "자동클릭 토글"), ("ke-scan", "버튼 확인"),
                             ("ke-rehearse", "연습 발사"), ("ke-pick-seat", "좌석 지정")):
                check(pg.evaluate(f"!!document.getElementById('{el}')"), f"{name} 버튼 존재")

            # 자동클릭 토글이 실제로 엔진을 끄고 켜는지
            pg.click("#ke-auto")
            off = pg.evaluate("window.KE_AUTO.enabled") is False
            check(off, "토글로 자동클릭 OFF")
            check(pg.inner_text("#ke-auto").strip() == "자동클릭 OFF", "버튼 라벨이 OFF 로 바뀜")
            pg.click("#ke-auto")
            check(pg.evaluate("window.KE_AUTO.enabled") is True, "토글로 다시 ON")

            # 버튼 미리보기: 클릭하지 않고 후보만 센다
            pg.evaluate("window.__seatClicked = 0")
            pg.click("#ke-scan")
            check(pg.evaluate("window.__seatClicked") == 0, "미리보기는 실제로 누르지 않음")

            # 연습 발사: 2초 뒤 조회 -> 좌석 -> 모달 체인
            pg.evaluate("""() => {
              const S = window.KE_HUD.state;
              S.fireSel = '#seat'; S.seatSel = '#seat';
              window.KE_HUD.rehearse(2);
            }""")
            t0 = time.time()
            pg.wait_for_function("() => !!window.__done", timeout=15000)
            elapsed = time.time() - t0

            st = pg.evaluate("() => ({done: window.__done, aborted: window.__aborted || null,"
                             " unchecked: window.__unchecked || null,"
                             " armed: window.KE_HUD.state.armed})")
            check(st["done"] == EXPECTED, "연습 발사로 모달 체인까지 통과", f"실제: {st['done']}")
            check(st["aborted"] is None, "오클릭 없음", f"눌림: {st['aborted']}")
            check(st["unchecked"] is None, "체크박스 먼저 체크")
            # 의미 있는 쪽은 하한이다: 초 단위 절삭 때문에 T-0 보다 일찍 쏘는 회귀를 잡는다.
            # 상한은 부하를 타므로 느슨하게 둔다 (안 쏘는 경우는 위 wait_for_function 이 잡음).
            check(elapsed > 1.9, f"T-0 이전에 미리 쏘지 않음 (실제 {elapsed:.2f}s)")

            # 성공 화면을 감지하면 스스로 무장 해제해야 한다
            pg.wait_for_timeout(400)
            check(pg.evaluate("window.KE_HUD.state.armed") is False,
                  "성공 감지 후 자동 정지", f"armed={pg.evaluate('window.KE_HUD.state.armed')}")

            check(not errors, "콘솔 에러 없음", str(errors[:2]))
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "HUD 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
