"""유저스크립트(HUD) 경로 통합 테스트.

HUD 가 담당하는 것은 "정시가 되면 재생을 걸고 새로고침한다" 하나뿐이다:
  연습 발사 예약 -> 카운트다운 -> T-0 에 발사 -> 새로고침 -> recorder 가 재생
  -> autoconfirm 이 모달 체인 통과 -> 재생이 멈추면 소리/제목으로 알림

실행:  .venv/bin/python test/test_hud.py
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

            # 남아 있어야 하는 컨트롤
            for el, name in (("ke-auto", "자동클릭 토글"), ("ke-sync", "시각 동기"),
                             ("ke-rec", "녹화"), ("ke-play", "재생"), ("ke-edit", "단계 편집"),
                             ("ke-export", "내보내기"), ("ke-rehearse", "연습 발사"),
                             ("ke-arm", "대기 시작")):
                check(pg.evaluate(f"!!document.getElementById('{el}')"), f"{name} 버튼 존재")

            # 걷어낸 컨트롤이 되살아나지 않았는지 (죽은 경로 재도입 방지)
            for el, name in (("ke-pick", "조회 지정"), ("ke-pick-seat", "좌석 지정"),
                             ("ke-test", "발사 테스트"), ("ke-scan", "버튼 확인"),
                             ("ke-mode", "동작 전환"), ("ke-retry", "재조회 입력")):
                check(not pg.evaluate(f"!!document.getElementById('{el}')"), f"{name} 제거됨")

            # 자동클릭 토글이 실제로 엔진을 끄고 켜는지
            pg.click("#ke-auto")
            check(pg.evaluate("window.KE_AUTO.enabled") is False, "토글로 자동클릭 OFF")
            check(pg.inner_text("#ke-auto").strip() == "자동클릭 OFF", "버튼 라벨이 OFF 로 바뀜")
            pg.click("#ke-auto")
            check(pg.evaluate("window.KE_AUTO.enabled") is True, "토글로 다시 ON")

            # 녹화가 없으면 발사하지 않고 안내만 한다
            pg.evaluate("() => { window.KE_REC.clear(); window.KE_HUD.rehearse(2); }")
            check(pg.evaluate("window.KE_HUD.state.armed") is False,
                  "녹화가 없으면 무장하지 않음")

            # armForReload 는 "예약"만 해야 한다. 여기서 바로 재생이 돌면 낡은 화면에서
            # 1단계(날짜)를 눌러버리고, 이어지는 새로고침이 그 선택을 날린다.
            pg.evaluate("""() => {
              window.__seatClicked = 0;
              window.KE_REC.state.steps = [
                {sel: '#seat', text: '프레스티지 PR 1석 · KE927 ICN→FCO', tag: 'button',
                 url: location.pathname, selectorOnly: false}
              ];
              window.KE_REC.save();
              window.KE_REC.armForReload();
            }""")
            pg.wait_for_timeout(700)
            arm = pg.evaluate("() => ({playing: KE_REC.state.playing,"
                              " pending: KE_REC.state.playAfterReload,"
                              " seat: !!window.__seatClicked})")
            check(arm["pending"] is True, "새로고침 후 재생이 예약됨")
            check(arm["playing"] is False, "예약 시점에는 아직 재생하지 않음")
            check(arm["seat"] is False, "새로고침 전에 1단계를 눌러버리지 않음")

            # 연습 발사: 2초 뒤 -> 새로고침 -> 좌석 클릭 재생 -> 모달 체인
            pg.evaluate("""() => {
              window.KE_REC.reset();
              window.KE_REC.save();
              window.KE_HUD.rehearse(2);
            }""")
            check(pg.evaluate("window.KE_HUD.state.armed") is True, "녹화가 있으면 무장함")

            t0 = time.time()
            # playing=true 는 재생이 순식간에 끝나면 놓칠 수 있다. 새로고침 뒤 실제로
            # 좌석이 눌린 흔적(픽스처가 남김)을 발사 시점의 관측 지점으로 쓴다.
            pg.wait_for_function("() => !!window.__seatClicked", timeout=15000)
            elapsed = time.time() - t0
            # 의미 있는 쪽은 하한이다: 초 단위 절삭 때문에 T-0 보다 일찍 쏘는 회귀를 잡는다.
            check(elapsed > 1.9, f"T-0 이전에 미리 쏘지 않음 (실제 {elapsed:.2f}s)")

            pg.wait_for_function("() => !!window.__done", timeout=20000)
            st = pg.evaluate("() => ({done: window.__done, aborted: window.__aborted || null,"
                             " unchecked: window.__unchecked || null,"
                             " armed: window.KE_HUD.state.armed})")
            check(st["done"] == EXPECTED, "연습 발사로 모달 체인까지 통과", f"실제: {st['done']}")
            check(st["aborted"] is None, "오클릭 없음", f"눌림: {st['aborted']}")
            check(st["unchecked"] is None, "체크박스 먼저 체크")
            check(st["armed"] is False, "재생으로 넘어가며 HUD 무장은 해제됨")

            # 재생이 멈추면 사람을 부른다 (소리는 못 보지만 제목은 확인 가능)
            pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=10000)
            pg.wait_for_timeout(300)
            # 끝까지 간 경우와 막힌 경우를 제목으로 구분해야 한다
            # (같게 알리면 막혀서 멈춘 걸 완료로 오해한다)
            check(pg.title().startswith("★완료★"),
                  "끝까지 갔으면 '완료' 로 알림", f"title={pg.title()!r}")

            pg.evaluate("""() => {
              const R = window.KE_REC;
              R.state.steps = [{sel: '#nope-does-not-exist', text: '있을 리 없는 버튼',
                                tag: 'button', url: location.pathname, selectorOnly: true}];
              R.state.stepTimeoutMs = 600;
              R.reset(); R.save(); R.play();
            }""")
            pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=8000)
            pg.wait_for_timeout(300)
            check(pg.title().startswith("⚠멈춤⚠"),
                  "막혀서 멈추면 '멈춤' 으로 다르게 알림", f"title={pg.title()!r}")

            check(not errors, "콘솔 에러 없음", str(errors[:2]))
        finally:
            ctx.close()

    print()
    print("FAILED: " + ", ".join(fails) if fails else "HUD 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
