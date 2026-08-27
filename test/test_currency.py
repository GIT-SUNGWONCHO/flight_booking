"""통화 KRW 확인 + 결제수단 대체(네이버페이 없으면 신용카드).

사용자 요청(2026-08-27):
  - 항공편 화면의 통화가 KRW 가 아니면 KRW 로 바꿔야 한다. 좌석 등급을 바꿀 때마다
    되돌아가는 경우가 있어 매번 확인이 필요하다.
  - 오는 편에는 네이버페이가 없다. 그때는 한국발행 신용/체크카드로 가야 한다.

실행:  .venv/Scripts/python.exe test/test_currency.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
BASE = (ROOT / "test" / "fixture" / "currency.html").as_uri()

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


STEPS = """() => {
  const R = window.KE_REC;
  R.state.steps = [
    {ensure:'KRW', sel:'#currencyBtn', text:'통화', tag:'button', url:'/x',
     optionSel:'#filter-currency .filter__list .filter__item:nth-of-type(2) > label',
     applySel:'#filter-currency .filter__apply', applyText:'적용'},
    {sel:'', text:'Npay', tag:'button', url:'/x',
     alt:[{sel:'', text:'한국발행 신용/체크카드'}]},
    {ensure:'현대카드', onlyIfPrev:'한국발행', sel:'#sel-korCardCompany',
     text:'한국발행 신용/체크카드 종류', tag:'select', url:'/x', selectorOnly:true}
  ];
  R.state.optionalMs = 700;
  R.state.idx = 0; R.state.startedAt = 0; R.state.problem = false;
  R.state.stepTimeoutMs = 6000;
  R.play();
}"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(ROOT / ".test-profile-cur"), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.set_default_timeout(30000)
            ctx.add_init_script(js)

            for query, cur_label, want_cur, want_pick, want_clicks, want_ct in (
                ("?cur=KRW", "이미 KRW", "KRW", "npay", 0, None),
                ("?cur=USD", "USD 로 시작", "KRW", "npay", 1, None),
                ("?cur=USD&npay=0", "네이버페이 없음(오는 편)", "KRW", "card", 1, "현대카드"),
            ):
                pg.goto(BASE + query, timeout=60000)
                pg.wait_for_timeout(400)
                t0 = time.time()
                pg.evaluate(STEPS)
                pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=20000)
                took = time.time() - t0
                st = pg.evaluate("""() => ({
                  cur: document.getElementById('curval').textContent,
                  clicks: window.__curClicks, picked: window.__picked,
                  applied: window.__applied || 0,
                  ct: (function(){ var e=document.getElementById('sel-korCardCompany');
                        return e ? e.options[e.selectedIndex].text : null; })(),
                  ctClicks: window.__ctClicks || 0,
                  idx: KE_REC.state.idx, total: KE_REC.state.steps.length,
                  problem: KE_REC.state.problem})""")
                check(st["cur"] == want_cur, f"{cur_label}: 통화가 {want_cur} (실제 {st['cur']})")
                check(st["applied"] == want_clicks,
                      f"{cur_label}: [적용] 을 {want_clicks}회 눌렀다 (실제 {st['applied']})")
                check(st["clicks"] == want_clicks,
                      f"{cur_label}: 필요할 때만 통화를 건드림 (클릭 {st['clicks']}회, 기대 {want_clicks})")
                check(st["picked"] == want_pick,
                      f"{cur_label}: 결제수단 {want_pick} 선택 (실제 {st['picked']})")
                if want_ct:
                    check(st["ct"] == want_ct,
                          f"{cur_label}: 카드 종류가 {want_ct} (실제 {st['ct']})")
                else:
                    check(st["ctClicks"] == 0,
                          f"{cur_label}: 카드 종류 단계를 건너뜀 (클릭 {st['ctClicks']}회)")
                    # 예전엔 "없으면 2.5초 기다렸다 넘어감" 이었다. 09:00 경쟁에서
                    # 의미 없이 버리는 시간이라, 앞에서 무엇을 눌렀는지로 즉시 판단한다.
                    check(took < 1.5, f"{cur_label}: 대기 없이 끝남 (실제 {took:.2f}s)")
                check(st["idx"] == st["total"] and not st["problem"],
                      f"{cur_label}: 끝까지 진행 ({st['idx']}/{st['total']}, problem={st['problem']})")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "통화/결제수단 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
