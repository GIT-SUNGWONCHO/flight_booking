"""녹화 -> 재생 통합 테스트.

fixture/booking.html 은 실제 예매 흐름을 흉내낸다 (페이지 이동 포함):
  캘린더에서 날짜 -> 항공편 검색 -> [이동] -> 좌석 -> 다음 -> [이동]
  -> 승객정보 확인 -> 위험품 팝업(아래로 스크롤 x2 -> 확인) -> 동의 -> 네이버페이 -> 결제하기

검증 포인트:
  - 손으로 한 번 밟은 순서를 그대로 재생하는가
  - 페이지가 바뀌어도 이어서 재생하는가 (localStorage 재개)
  - 이미 동의된 버튼을 다시 눌러 동의를 풀지 않는가
  - 결제하기 앞에서 반드시 멈추는가

실행:  .venv/Scripts/python.exe test/test_recorder.py
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
        ctx = launch_with_retry(p, user_data_dir=str(ROOT / ".test-profile-rec"), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            ctx.add_init_script(js)
            # 녹화 중 자동클릭이 끼어들면 순서가 오염된다
            ctx.add_init_script("try{setTimeout(()=>{window.KE_AUTO.enabled=false},0)}catch(e){}")

            # ---------- 1) 손으로 한 번 밟으며 녹화 ----------
            pg.goto(START)
            pg.evaluate("window.KE_REC.record()")

            pg.click("button.date[data-i='6']")     # 새로 열린 마지막 날짜
            pg.click("#search")                      # -> result 로 이동
            pg.wait_for_selector("#seat")
            pg.click("#seat")
            pg.click("#next")                        # -> info 로 이동
            pg.wait_for_selector("#pax")
            pg.click("#pax")
            pg.click("#scroll")
            pg.click("#scroll")
            pg.click("#scroll")   # 라벨이 확인 으로 바뀐 같은 버튼
            pg.click("#ag1")                         # 안 켜진 동의만
            pg.click("#npay")
            pg.evaluate("window.KE_REC.stop()")

            steps = pg.evaluate("window.KE_REC.state.steps")
            labels = [s["text"] for s in steps]
            # 날짜, 검색, 좌석, 다음, 확인, 스크롤x2, 확인, 동의, 네이버페이 = 10
            check(len(steps) == 10, f"10단계 녹화됨 (실제 {len(steps)})", str(labels))
            check(labels[0] == "16(월)" and labels[1] == "항공편 검색",
                  "날짜 -> 검색 순서가 그대로 기록됨", str(labels[:2]))
            check("아래로 스크롤" in labels, "위험품 팝업의 '아래로 스크롤' 이 녹화됨")
            check(labels.count("✓ 동의") == 1, "동의는 1개만 녹화됨 (이미 켜진 건 안 누름)")
            check(pg.evaluate("!!window.__brokeAgreement") is False, "녹화 중 동의 해제 없음")

            # ---------- 2) 처음으로 돌아가 재생 ----------
            pg.evaluate("window.KE_REC.reset()")
            pg.goto(START)
            pg.evaluate("() => { sessionStorage.clear(); window.KE_REC.play(); }")

            # 결제 직전에서 멈춰야 한다 -> 네이버페이까지 진행되면 완료
            pg.wait_for_function("() => !!window.__npay", timeout=25000)
            pg.wait_for_timeout(700)

            st = pg.evaluate(
                "() => ({paid: !!window.__paid, npay: !!window.__npay,"
                " ag1: window.__ag1, broke: !!window.__brokeAgreement,"
                " scrolls: window.__scrolls || 0, okEarly: !!window.__okBeforeScroll,"
                " closed: !!window.__closedDanger,"
                " playing: window.KE_REC.state.playing, idx: window.KE_REC.state.idx,"
                " total: window.KE_REC.state.steps.length, msg: window.KE_REC.state.message})"
            )
            check(st["npay"], "재생이 네이버페이 선택까지 도달")
            check(st["scrolls"] == 2, f"'아래로 스크롤' 2회 재생 (실제 {st['scrolls']})")
            check(not st["okEarly"], "스크롤 전에 확인을 누르지 않음")
            check(not st["closed"], "위험품 팝업의 '닫기' 를 누르지 않음")
            check(st["ag1"] == "true", f"동의 1번이 켜짐 (실제 {st['ag1']})")
            check(not st["broke"], "이미 켜진 동의를 끄지 않음")
            check(not st["paid"], "결제하기는 자동으로 누르지 않음")
            check(st["idx"] == st["total"], f"모든 단계 재생 완료 ({st['idx']}/{st['total']})")
            print(f"      마지막 상태: {st['msg']}")

            # ---------- 3) 정시 발사 -> 새로고침 -> 재생 (실전 경로) ----------
            pg.goto(START)
            pg.evaluate("""() => {
              sessionStorage.clear();
              const H = window.KE_HUD.state;
              H.onOpen = 'replay';
              window.KE_REC.reset();
              window.KE_HUD.rehearse(2);   // 2초 뒤 정시 발사
            }""")
            pg.wait_for_function("() => !!window.__npay", timeout=30000)
            st2 = pg.evaluate(
                "() => ({npay: !!window.__npay, paid: !!window.__paid,"
                " broke: !!window.__brokeAgreement, scrolls: window.__scrolls || 0,"
                " armed: window.KE_HUD.state.armed,"
                " idx: window.KE_REC.state.idx, total: window.KE_REC.state.steps.length})"
            )
            check(st2['npay'], '정시 발사 -> 새로고침 -> 재생이 끝까지 진행')
            check(st2['scrolls'] == 2, f"스크롤 2회 (실제 {st2['scrolls']})")
            check(not st2['broke'], '동의 해제 없음')
            check(not st2['paid'], '결제하기는 안 눌림')
            check(not st2['armed'], '재생으로 넘어가며 HUD 재조회 루프는 해제됨')
            check(st2['idx'] == st2['total'], f"전 단계 완료 ({st2['idx']}/{st2['total']})")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "녹화/재생 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
