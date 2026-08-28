"""페이지가 넘어가기 전에 다음 단계를 눌러버리지 않는가.

실측(2026-08-28), 달력 모드 실전:

    재생 5/17: 다음   [9.39s]
    재생 6/17: 확인   [9.67s]      <- 0.28초 뒤

조회 화면에서 [다음] 을 눌러 결제 화면으로 넘어가기도 전에, 아직 조회 화면인
상태에서 6단계 [확인] 이 눌렸다. 그 클릭은 곧 이어진 페이지 이동에 씻겨나갔고,
결제 화면에서는 6단계가 안 된 채 7단계를 기다려 영영 멈췄다.

화면이 잠잠해지길 기다리는 시간(maxSettleMs)이 2.5초일 때는 우연히 가려져 있던
구멍이다. 그 대기를 1.2초로 줄이자 드러났다. 시간을 되돌리는 것은 답이 아니다 -
단계마다 녹화된 url 이 있으니, 그 화면이 뜨기 전에는 누르지 않으면 된다.

실행:  .venv/Scripts/python.exe test/test_pagewait.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
FX = ROOT / "test" / "fixture"
HOST = "https://ke.test"
DEP = HOST + "/booking/select-award-flight/slownav"

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


def serve(route):
    path = route.request.url.split("?")[0][len(HOST):]
    f = FX / path.lstrip("/")
    if not f.suffix:
        f = f.with_suffix(".html")
    if not f.exists():
        route.fulfill(status=404, body="not found")
        return
    route.fulfill(status=200, content_type="text/html", body=f.read_bytes())


STEPS = """[
  {sel:'#next', text:'다음', tag:'button',
   url:'/booking/select-award-flight/'},
  {sel:'#submit-passenger-ADT-0', text:'확인', tag:'button',
   url:'/payment/gate/RT/NR'},
  {sel:'#submit-contact', text:'확인', tag:'button',
   url:'/payment/gate/RT/NR'}
]"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")
    profile = ROOT / ".test-profile-pagewait"
    shutil.rmtree(profile, ignore_errors=True)

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(profile), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.set_default_timeout(20000)
            ctx.add_init_script(js)
            ctx.route(HOST + "/**", serve)

            pg.goto(DEP + "?nav=1500")
            pg.wait_for_function("() => !!window.KE_REC", timeout=20000)
            pg.evaluate(f"""() => {{
              const S = window.KE_REC.state;
              S.steps = {STEPS};
              S.allowPay = false; S.expectDate = ''; S.idx = 0;
              S.playing = false; S.playAfterReload = false;
              window.KE_REC.save();
              window.KE_REC.play();
            }}""")

            # [다음] 은 눌러야 한다
            pg.wait_for_function("() => (window.__clicks||[]).includes('next')", timeout=15000)
            # 그런데 이동 전(1.5초 동안) 그 화면의 '확인' 을 눌러선 안 된다
            pg.wait_for_timeout(1200)
            early = pg.evaluate("window.__clicks || []")
            check(early == ["next"],
                  f"페이지가 넘어가기 전에는 다음 단계를 누르지 않는다 (실제 {early})")
            check(pg.evaluate("KE_REC.state.idx") == 1,
                  f"단계 번호도 앞서 가지 않는다 (실제 {pg.evaluate('KE_REC.state.idx')})")

            # 넘어간 뒤에는 이어서 끝까지 간다
            pg.wait_for_url("**/payment/gate/RT/NR", timeout=20000)
            pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=20000)
            after = pg.evaluate("window.__clicks || []")
            check(after == ["submit-passenger-ADT-0", "submit-contact"],
                  f"새 화면에서 남은 단계를 순서대로 누른다 (실제 {after})")
            st = pg.evaluate("() => ({idx: KE_REC.state.idx, problem: KE_REC.state.problem,"
                             " msg: KE_REC.state.message})")
            check(st["idx"] == 3 and st["problem"] is False, "끝까지 문제 없이 갔다", str(st))
            print(f"      {st['msg']}")

            # 엉뚱한 화면에 계속 있으면 영영 기다리지 말고 사람을 부른다
            pg.goto(DEP + "?nav=999999")
            pg.wait_for_function("() => !!window.KE_REC", timeout=20000)
            pg.evaluate(f"""() => {{
              const S = window.KE_REC.state;
              S.steps = {STEPS};
              S.idx = 1;                      // 결제 화면 단계인데 조회 화면에 있다
              S.stepTimeoutMs = 2500;
              S.playing = false; S.playAfterReload = false;
              window.KE_REC.save();
              window.KE_REC.play();
            }}""")
            pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=20000)
            msg = pg.evaluate("KE_REC.state.message")
            check("화면의 단계인데" in (msg or ""),
                  "화면이 안 바뀌면 왜 못 하는지 말하고 멈춘다", msg)
            check("submit-passenger-ADT-0" not in (pg.evaluate("window.__clicks") or []),
                  "그동안 엉뚱한 화면의 같은 이름 버튼을 누르지 않았다",
                  str(pg.evaluate("window.__clicks")))
            print(f"      {msg}")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "페이지 이동 대기 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
