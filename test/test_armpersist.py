"""무장 상태가 페이지가 다시 떠도 살아남는지 + 결제창 판정 후에 완료를 알리는지.

코드 리뷰에서 나온 두 가지:

1) schedule() 이 "대기 시작" 버튼 클릭에서만 불렸다. 08시에 무장해두고 09시 전에
   페이지가 한 번이라도 다시 뜨면(수동 새로고침/세션 갱신/SPA 풀 로드) 타이머만
   조용히 사라진다. 버튼은 '■ 정지', 카운트다운도 계속 도는 채로 정시에 아무 일도
   일어나지 않는다. 09:00 한 번에 승부가 나는 도구에서 가장 치명적인 경로다.

2) 결제 단계를 누른 직후 곧바로 '전체 단계 완료' 를 알렸다. 팝업 차단으로 결제창이
   안 떴는지는 1.5초 뒤에야 알 수 있는데, 그때는 이미 성공음이 울리고 제목이
   ★완료★ 로 바뀐 뒤였다. 이 도구가 막으려던 바로 그 사고다.

실행:  .venv/Scripts/python.exe test/test_armpersist.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ke_award.runner import launch_with_retry  # noqa: E402

USERSCRIPT = ROOT / "userscript" / "ke-award-macro.user.js"
FIXTURE = (ROOT / "test" / "fixture" / "booking.html").as_uri() + "?p=cal"
PAYPOPUP = (ROOT / "test" / "fixture" / "paypopup.html").as_uri()

fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}{('  <- ' + detail) if detail and not ok else ''}")
    if not ok:
        fails.append(label)


def main() -> int:
    from playwright.sync_api import sync_playwright

    js = USERSCRIPT.read_text(encoding="utf-8")

    with sync_playwright() as p:
        ctx = launch_with_retry(p, user_data_dir=str(ROOT / ".test-profile-arm"), headless=True)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.set_default_timeout(30000)
            ctx.add_init_script(js)

            # ---------- 1) 무장은 새 문서에서도 다시 예약돼야 한다 ----------
            pg.goto(FIXTURE, timeout=60000)
            pg.wait_for_timeout(600)
            pg.evaluate("""() => {
              const H = window.KE_HUD.state;
              // toISOString 은 UTC 라 그대로 쓰면 KST 로 해석돼 과거가 된다. KST 로 만든다.
              const p = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Seoul', hourCycle:'h23',
                year:'numeric',month:'2-digit',day:'2-digit',
                hour:'2-digit',minute:'2-digit',second:'2-digit'})
                .formatToParts(new Date(Date.now() + 3600e3))
                .reduce((a,x)=>(a[x.type]=x.value,a),{});
              H.targetKst = `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`;
              H.armed = false;
              window.KE_HUD.save();
              document.getElementById('ke-arm').click();   // 무장
            }""")
            pg.wait_for_timeout(300)
            check(pg.evaluate("window.KE_HUD.state.armed") is True, "무장됨")
            before = pg.evaluate("document.getElementById('ke-status').textContent")
            check("예약 대기" in (before or ""), "예약 대기 상태 표시", before)

            # 페이지를 다시 띄운다 = 09시 전에 새로고침이 한 번 일어난 상황
            pg.reload()
            pg.wait_for_timeout(900)
            check(pg.evaluate("window.KE_HUD.state.armed") is True, "새 문서에서도 무장 유지")
            after = pg.evaluate("document.getElementById('ke-status').textContent")
            check("예약 대기" in (after or ""),
                  "새 문서에서 타이머가 다시 예약됨 (이게 없으면 정시에 안 쏜다)", after)

            # 이미 지난 시각으로 무장하면 조용히 두지 않고 무장을 푼다
            pg.evaluate("""() => {
              const H = window.KE_HUD.state;
              H.targetKst = '2020-01-01 09:00:00';
              document.getElementById('ke-arm').click();   // 정지
              document.getElementById('ke-arm').click();   // 다시 무장 시도
            }""")
            pg.wait_for_timeout(300)
            check(pg.evaluate("window.KE_HUD.state.armed") is False,
                  "지난 시각이면 무장을 풀어 '무장했는데 타이머 없음' 을 없앤다")

            # ---------- 2) 결제창이 안 뜨면 완료로 알리지 않는다 ----------
            for blocked, label in ((True, "차단된 경우"), (False, "열린 경우")):
                pg.goto(PAYPOPUP + ("?block=1" if blocked else ""), timeout=60000)
                pg.wait_for_timeout(400)
                pg.evaluate("""() => {
                  const R = window.KE_REC;
                  R.state.steps = [{sel:'#pay', text:'결제하기 새 창 열림', tag:'button', url:'/x'}];
                  R.state.allowPay = true;
                  R.state.idx = 0; R.state.startedAt = 0; R.state.problem = false;
                  R.state.lastOpen = null;
                  R.play();
                }""")
                pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=15000)
                # 판정은 1.5초 뒤에 온다. 그 전에 완료로 알리면 안 된다.
                pg.wait_for_timeout(2200)
                st = pg.evaluate("() => ({problem: KE_REC.state.problem,"
                                 " msg: KE_REC.state.message, title: document.title})")
                if blocked:
                    check(st["problem"] is True, f"{label}: 문제로 표시", str(st))
                    check(st["title"].startswith("⚠멈춤⚠"),
                          f"{label}: 제목이 ⚠멈춤⚠ (성공음/★완료★ 가 아니어야)", st["title"][:40])
                    check("열리지 않았습니다" in (st["msg"] or ""), f"{label}: 이유를 알림", st["msg"])
                else:
                    check(st["problem"] is False, f"{label}: 문제 없음", str(st))
                    check(st["title"].startswith("★완료★"), f"{label}: 제목이 ★완료★", st["title"][:40])
                print(f"      {label}: {st['msg']}")
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "무장 유지 / 결제창 판정 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
