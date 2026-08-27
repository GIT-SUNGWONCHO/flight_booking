"""건너뛴 단계 보고 테스트 + 추측 클릭 엔진이 되살아나지 않았는지 확인.

실사이트 로그에서 자동클릭(라벨 추측) 엔진이 재생을 방해하는 게 드러나 유저스크립트에서
제거했다. 되살아나면 같은 사고가 재발하므로 빌드 산출물에 없는지 확인한다.
그리고 건너뛴 단계는 개수만이 아니라 어느 단계였는지 알려줘야 판단할 수 있다.

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

            # 2번은 일부러 못 찾게 해서 resync 로 건너뛰게 만든다.
            # 마지막 단계가 페이지를 이동시키지 않도록 구성해야 완료 메시지를 볼 수 있다.
            pg.evaluate("""() => {
              const R = window.KE_REC;
              R.state.steps = [
                {sel:"button.date[data-i='5']", text:'15(일)', tag:'button', url:'/x'},
                {sel:'#존재하지않음', text:'있을리없는라벨입니다', tag:'button', url:'/x', selectorOnly:true},
                {sel:"button.date[data-i='6']", text:'16(월)', tag:'button', url:'/x'}
              ];
              R.state.stepTimeoutMs = 2500; R.state.idx = 0; R.state.startedAt = 0;
              R.state.problem = false;
              R.play();
            }""")

            pg.wait_for_function("() => !window.KE_REC.state.playing", timeout=20000)
            st = pg.evaluate("() => ({msg: KE_REC.state.message, problem: KE_REC.state.problem,"
                             " idx: KE_REC.state.idx})")
            # 못 찾는 단계는 건너뛰지 않고 멈춘다. 조용히 건너뛰면 동의 같은 필수
            # 단계가 통째로 빠진 채 "완료" 로 보고된다(실측 사고).
            check(st["problem"] is False, f"막힌 건 problem 이 아니라 정지로 다룬다 (problem={st['problem']})")
            check(st["idx"] == 1, f"못 찾은 단계에서 멈춤 (idx={st['idx']})")
            check("못 찾음" in (st["msg"] or ""),
                  "어느 단계를 왜 못 찾았는지 알림", st["msg"])

            # 제목 표시는 페이지 이동 전에 봐야 한다 (이동하면 원래 제목으로 돌아감).
            # 판정이 메시지 문구 매칭이면 표현만 바꿔도 조용히 거짓 완료가 된다.
            title = pg.title()
            check(title.startswith("⚠멈춤⚠"), "막히면 제목이 ⚠멈춤⚠", title[:40])
            print(f"      제목  : {title[:40]}")
            print(f"      메시지: {st['msg']}")
        finally:
            ctx.close()

    # 추측 클릭 엔진이 유저스크립트에 다시 섞여들지 않았는지 (회귀 방지)
    src = USERSCRIPT.read_text(encoding="utf-8")
    check("KE_AUTO" not in src, "유저스크립트에 추측 클릭 엔진이 없음")
    check("KE_REC" in src and "KE_HUD" in src, "녹화 재생과 패널은 그대로 있음")

    # 버전이 커밋마다 자동으로 올라가는지 (손으로 올리면 반드시 까먹는다).
    # 붙여넣은 스크립트가 최신인지 확인할 유일한 수단이라 회귀로 고정한다.
    import re
    hdr = re.search(r"@version\s+(\S+)", src)
    check(bool(hdr), "헤더에 @version 이 있음")
    if hdr:
        v = hdr.group(1)
        check(v != "1.3.0" and re.match(r"^1\.\d+\.\d+", v) is not None,
              f"버전이 git 에서 자동 생성됨 ({v})")
        check(f"version: '{v}'" in src, "스크립트 안의 KE_BUILD 와 헤더 버전이 일치")

    print()
    print("FAILED: " + ", ".join(fails) if fails else "건너뜀 보고 테스트 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
