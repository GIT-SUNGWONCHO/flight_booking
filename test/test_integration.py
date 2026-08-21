"""실제 브라우저에 autoconfirm.js 를 주입해 모달 체인을 통과시키는 통합 테스트.

fixture/gauntlet.html 은 예매 흐름을 흉내낸다:
  좌석 클릭 -> [확인] -> [다음 »] -> [체크박스 + 전체 동의] -> [계속하기] -> 예약번호

검증 포인트:
  - 취소/닫기/이전/다시 검색 을 단 한 번도 누르지 않았는가 (오클릭 = 마일리지 사고)
  - 필수 체크박스를 누르기 전에 체크했는가
  - 끝까지 통과했는가, 그리고 얼마나 빨랐는가
  - 매진 화면에서는 아무것도 누르지 않는가

브라우저는 한 번만 띄운다. Windows 는 프로필/실행파일 잠금 때문에 연속 기동이
불안정해서, 시나리오마다 cfg 만 갈아끼운다.

실행:  .venv/Scripts/python.exe test/test_integration.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import Config, Runner  # noqa: E402

FIXTURE = (ROOT / "test" / "fixture" / "gauntlet.html").as_uri()
SOLDOUT = (ROOT / "test" / "fixture" / "soldout.html").as_uri()
EXPECTED = ["확인", "다음 »", "전체 동의", "계속하기"]

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


def main() -> int:
    cfg = Config(
        profile_dir=str(ROOT / ".test-profile"),
        headless=True,
        browser_channel="",   # 테스트는 번들 Chromium 고정 (실 Chrome 은 정책 변수가 많다)
        search_url=FIXTURE,
        seat_selector="#seat",
        success_text=["예약번호"],
        soldout_text=["매진", "좌석이 없"],
        settle_ms=3000,
        confirm_timeout_s=15,
    )
    r = Runner(cfg)
    r.launch()
    try:
        # --- 1) CSS 셀렉터로 좌석 지목 ----------------------------------
        print("[1] seat_selector 경로")
        t0 = time.time()
        outcome = r.attempt(1)
        elapsed = (time.time() - t0) * 1000
        st = r.page.evaluate(
            "() => ({done: window.__done || null, aborted: window.__aborted || null,"
            " unchecked: window.__unchecked || null, seat: window.__seatClicked || 0,"
            " loaded: typeof window.KE_AUTO,"
            " log: (window.KE_AUTO && window.KE_AUTO.log) || []})"
        )
        check(st["loaded"] == "object", "autoconfirm.js 가 주입됨", f"typeof={st['loaded']}")
        check(st["seat"] == 1, "좌석 버튼이 클릭됨")
        check(st["aborted"] is None, "취소/닫기/이전 계열을 누르지 않음", f"눌림: {st['aborted']}")
        check(st["unchecked"] is None, "동의 체크박스를 먼저 체크함")
        check(st["done"] == EXPECTED, "모달 체인을 순서대로 통과",
              f"실제: {st['done']}  기대: {EXPECTED}")
        check(outcome.name == "SUCCESS", f"SUCCESS 반환 (실제 {outcome.name})")
        check(elapsed < 8000, f"전체 {elapsed:.0f}ms < 8000ms")
        print(f"      자동 클릭 {len(st['log'])}회 {[c['label'] for c in st['log']]}, "
              f"좌석클릭→예약번호 {elapsed:.0f}ms")

        # --- 2) 텍스트로 좌석 찾기 (셀렉터를 모를 때의 기본 경로) ---------
        print("\n[2] seat_text 경로 (xpath 조상 탐색)")
        r.cfg.seat_selector = ""
        r.cfg.seat_text = "프레스티지|Prestige"
        outcome = r.attempt(1)
        st = r.page.evaluate("() => ({seat: window.__seatClicked || 0, done: window.__done || null,"
                             " aborted: window.__aborted || null})")
        check(st["seat"] == 1, "텍스트만으로 좌석 버튼을 찾아 클릭")
        check(outcome.name == "SUCCESS", f"SUCCESS 반환 (실제 {outcome.name})")
        check(st["done"] == EXPECTED, "모달 체인 통과", f"실제: {st['done']}")
        check(st["aborted"] is None, "오클릭 없음", f"눌림: {st['aborted']}")

        # --- 3) 매진 화면에서 오클릭 없이 SOLDOUT 판정 -------------------
        print("\n[3] 매진 분기")
        r.cfg.search_url = SOLDOUT
        outcome = r.attempt(1)
        n = r.page.evaluate("() => ((window.KE_AUTO && window.KE_AUTO.log) || []).length")
        check(outcome.name == "SOLDOUT", f"SOLDOUT 반환 (실제 {outcome.name})")
        check(n == 0, f"매진 화면에서는 아무것도 클릭하지 않음 (클릭 {n}회)")
    finally:
        r.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "통합 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
