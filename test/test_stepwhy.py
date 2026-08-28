"""한 단계가 왜 오래 걸렸는지 나누어 재기.

실측(2026-08-27) 27.7초 중 8단계(동의) 하나가 6.9초였는데, 그게 대한항공 페이지가
느린 것인지 우리가 헛기다린 것인지 구분할 수가 없었다. 둘은 대응이 정반대다:

  - 페이지가 느리다  -> 재시도 간격을 줄여도 소용없다. 손대면 중복 클릭만 는다
  - 우리가 헛기다렸다 -> settleMs/retryClickMs 를 줄이면 그만큼 그대로 벌린다

그래서 매 tick 마다 지금 무엇 때문에 못 누르는지를 적어 시간을 나눠 담는다.
이 테스트는 그 분류가 실제로 맞는지 본다 - 틀린 계기는 없느니만 못하다.

실행:  .venv/Scripts/python.exe test/test_stepwhy.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
FIXTURE = (ROOT / "test" / "fixture" / "slowstep.html").as_uri()

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


STEPS = """[
  {sel:'#a', text:'확인', tag:'button', url:'/x'},
  {sel:'#b', text:'동의', tag:'button', url:'/x'}
]"""


def run(pg, query: str):
    pg.goto(FIXTURE + query, timeout=60000)
    pg.wait_for_function("() => !!window.KE_REC", timeout=20000)
    pg.evaluate(f"""() => {{
      const R = window.KE_REC;
      R.state.steps = {STEPS};
      R.state.idx = 0; R.state.startedAt = 0; R.state.problem = false;
      R.state.times = [];
      R.play();
    }}""")
    pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=30000)
    return pg.evaluate("() => window.KE_REC.state.times")


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")
    profile = ROOT / ".test-profile-why"
    shutil.rmtree(profile, ignore_errors=True)

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(profile), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.set_default_timeout(30000)
            ctx.add_init_script(js)

            # ---- 1) 버튼이 늦게 나타난다 = 페이지가 느린 쪽 ----
            times = run(pg, "?late=1500")
            two = next((t for t in times if t["n"] == 2), None)
            check(two is not None, f"2단계 시간이 기록됐다 (실제 {times})")
            check(two and two["ms"] >= 1400, f"실제로 오래 걸렸다 ({two and two['ms']}ms)")
            check(two and "요소 없음" in (two.get("why") or ""),
                  "원인을 '요소 없음' 으로 짚는다 (페이지가 느린 쪽)", str(two))
            # 원인은 큰 것부터 적는다. 여기서 '화면 안정' 이 조금 섞이는 것은 사실이다
            # - 앞 단계를 누른 뒤 화면이 잠잠해지길 기다리는 시간은 실제로 존재한다.
            # 중요한 것은 무엇이 지배적이냐다. 순서가 뒤집히면 엉뚱한 곳을 손대게 된다.
            check(two and (two.get("why") or "").startswith("요소 없음"),
                  "가장 큰 원인을 맨 앞에 적는다", str(two))
            print(f"      {two['n']}단계 {two['ms']}ms ({two['why']})")

            # ---- 2) 버튼은 곧바로 있는데 화면이 계속 바뀐다 = 우리가 기다린 쪽 ----
            times = run(pg, "?churn=1&late=99999")
            two = next((t for t in times if t["n"] == 2), None)
            check(two is not None and (two.get("why") or "").startswith("화면 안정"),
                  "이번엔 '화면 안정' 이 지배적이라고 짚는다 (우리가 기다린 쪽)", str(two))
            check(two and "요소 없음" not in (two.get("why") or ""),
                  "페이지 탓으로 잘못 적지 않는다", str(two))
            print(f"      {two['n']}단계 {two['ms']}ms ({two['why']})")

            # ---- 시계는 끝나면 멈춰야 한다 ----
            # 실측(2026-08-28): 33초에 끝난 실행이 한 시간 뒤 6346초로 보였다.
            # 계속 올라가는 숫자는 "이번에 몇 초 걸렸나" 를 못 알려준다.
            times = run(pg, "?late=600")
            t1 = pg.evaluate("() => KE_REC.elapsed()")
            pg.wait_for_timeout(1500)
            t2 = pg.evaluate("() => KE_REC.elapsed()")
            check(abs(t2 - t1) < 0.05,
                  f"재생이 끝나면 소요시간이 멈춘다 (1.5초 뒤에도 {t1:.2f}s -> {t2:.2f}s)")
            check(t2 > 0.4, f"그래도 실제로 걸린 시간은 남아 있다 ({t2:.2f}s)")

            # 카운트다운도 끝난 뒤엔 숫자를 올리지 않는다
            pg.evaluate("""() => {
              KE_HUD.state.targetKst = '2020-01-01 09:00:00';
              KE_HUD.state.armed = false; KE_HUD.save();
            }""")
            pg.wait_for_timeout(300)
            cd = pg.evaluate("document.getElementById('ke-cd')?.textContent || ''")
            check("T+" not in cd,
                  "대기 중이 아니면 T+ 를 올리지 않는다", cd)
            print(f"      카운트다운: {cd!r}")

            # ---- 3) 빠른 단계에는 군더더기를 붙이지 않는다 ----
            times = run(pg, "?late=1")
            one = next((t for t in times if t["n"] == 1), None)
            check(one is not None and not (one.get("why") or ""),
                  "금방 끝난 단계에는 원인을 적지 않는다 (읽을 것만 남긴다)", str(one))

            # 완료 메시지에 원인까지 실려야 사람이 로그를 뒤지지 않는다
            times = run(pg, "?late=1200")
            msg = pg.evaluate("() => window.KE_REC.state.message")
            check("요소 없음" in (msg or ""),
                  "완료 메시지만 봐도 어디서 샜는지 안다", msg)
            print(f"      완료 메시지: {msg}")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "단계 원인 분류 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
