"""08:47 사전 점검: 9시에 바로 쏠 수 있는 상태인지 미리 확인하고 화면까지 세워둔다.

왜 따로 있나
  예전엔 08:50 에 측정이 시작되면서 그때 셋업을 했다. 로그인이 풀려 있으면
  08:54 에나 알게 되고 9시까지 6분이 남는다. 실제로 2026-09-03 에 그렇게 하루를 잃었다.
  그래서 미리 점검해 '사람이 손봐야 하는 것' 을 일찍 크게 알린다.

무엇을 하나
  - 크롬 두 개(9222 실전 / 9223 계측)가 떠 있나
  - 각각 로그인돼 있나 (풀렸으면 네이버 연동 자동 로그인을 시도한다)
  - 오늘 노선의 달력 화면까지 세워둔다 (그래야 08:50 에 바로 시작한다)
  - 결과를 dev-shots/preflight.json 과 화면에 남긴다

사용:
  .venv/Scripts/python.exe dev/preflight.py            (요일로 노선 자동 판단)
  .venv/Scripts/python.exe dev/preflight.py --route FCO
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER = ROOT / "userscript" / "ke-award-macro.user.js"
OUT = ROOT / "dev-shots"
KST = timezone(timedelta(hours=9))
OFFSET = 360
ROME_DAYS = {0, 2, 5}
WD = ['월', '화', '수', '목', '금', '토', '일']


def log(m):
    print(f"[{datetime.now(KST).strftime('%H:%M:%S')}] {m}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", default="")
    ap.add_argument("--from", dest="origin", default="")
    ap.add_argument("--ports", default="9222,9223")
    a = ap.parse_args()

    today = datetime.now(KST).date()
    opens = today + timedelta(days=OFFSET)
    rome_ok = opens.weekday() in ROME_DAYS
    route = a.route.upper() if a.route else ("FCO" if rome_ok else "CDG")
    origin = a.origin.upper()
    # 9시에 열리는 날은 아직 못 고른다. 하루 전 날짜로 화면을 세워두면 그 언저리
    # 달력이 떠서, 9시에 열리자마자 매크로가 바로 찾는다.
    stand = opens - timedelta(days=1)

    log(f"오늘 {today}({WD[today.weekday()]}) 9시에 열리는 날: "
        f"{opens}({WD[opens.weekday()]})  로마운항={'O' if rome_ok else 'X'}")
    log(f"노선 {origin or 'SEL'} -> {route} / 화면은 {stand} 로 세워둔다")

    result = {"at": datetime.now(KST).isoformat(), "today": str(today),
              "opens": str(opens), "route": route, "origin": origin or "SEL",
              "ports": {}}
    problems: list = []

    from playwright.sync_api import sync_playwright
    for port in [int(p) for p in a.ports.split(",")]:
        tag = "실전" if port == 9222 else "계측"
        info = {"chrome": False, "loggedIn": False, "ready": False, "why": ""}
        result["ports"][str(port)] = info

        # 1) 크롬이 떠 있나 + 로그인돼 있나
        try:
            with sync_playwright() as pw:
                b = pw.chromium.connect_over_cdp(f"http://localhost:{port}")
                info["chrome"] = True
                ctx = b.contexts[0]
                pages = [p for p in ctx.pages if "koreanair" in p.url] or ctx.pages
                if not pages:
                    page = ctx.new_page()
                    page.goto("https://www.koreanair.com/kr/ko",
                              wait_until="domcontentloaded", timeout=60000)
                else:
                    page = pages[-1]
                page.evaluate(USER.read_text(encoding="utf-8"))
                # 헤더가 shadow DOM 이라 한 번만 보면 로그인돼 있어도 로그아웃으로 읽힌다.
                # 나타날 때까지 몇 번 본다.
                st = {}
                for _ in range(8):
                    st = page.evaluate("""() => {
                      const U = window.KE_UTIL;
                      const c = U.candidates(document).filter(e => U.visible(e));
                      return {out: c.some(e => /로그아웃/.test(U.label(e))),
                              inb: c.some(e => /^로그인$/.test(U.label(e)))};
                    }""")
                    if st.get("out"):
                        break
                    page.wait_for_timeout(700)
                info["loggedIn"] = bool(st.get("out"))
                b.close()
        except Exception as e:
            info["why"] = f"연결 실패: {str(e)[:70]}"
            problems.append(f"{tag}({port}) 크롬이 없습니다 - dev/browsers.ps1 로 띄우세요")
            log(f"  {tag}({port}): 크롬 없음")
            continue

        # 갓 띄운 크롬은 헤더(shadow DOM)가 아직 안 그려져 로그인돼 있어도 false 로 읽힌다.
        # 그래서 여기서는 단정하지 않는다. 진짜 판정은 아래 setup 이 한다.
        log(f"  {tag}({port}): 크롬 OK / 로그인 "
            f"{'OK' if info['loggedIn'] else '아직 확인 안 됨 (셋업에서 다시 본다)'}")

        # 2) 달력까지 세운다. setup 은 로그아웃이면 네이버 연동을 스스로 시도한다.
        cmd = [sys.executable, str(ROOT / "dev" / "setup.py"), route,
               "--port", str(port), "--date", stand.isoformat()]
        if origin:
            cmd += ["--from", origin]
        # 크롬을 갓 띄운 직후에는 첫 시도가 자주 실패하고 두 번째에 된다(2026-09-03 에
        # 두 번 그랬다 - 위젯이 아직 덜 자리잡은 듯). 그래서 한 번 더 해본다.
        # 08:47 에 도는 점검이라 재시도할 시간이 있다.
        st2 = {}
        for attempt in (1, 2):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                tail = (r.stdout or "").strip().splitlines()
                st2 = json.loads(tail[-1]) if tail else {}
            except Exception as e:
                st2 = {"ok": False, "why": f"setup 실패: {e}"[:80]}
            if st2.get("ok") or "로그인" in (st2.get("why") or ""):
                break
            if attempt == 1:
                log(f"  {tag}({port}): 1차 실패({st2.get('why')}) - 다시 시도")
        info["ready"] = bool(st2.get("ok"))
        info["why"] = st2.get("why", "")
        info["url"] = st2.get("url", "")
        if info["ready"]:
            # setup 이 로그인까지 해결했을 수 있다
            info["loggedIn"] = True
            log(f"  {tag}({port}): 화면 준비됨")
        else:
            why = info["why"] or "알 수 없음"
            log(f"  {tag}({port}): 화면 준비 실패 - {why}")
            if "로그인" in why:
                problems.append(f"★ {tag}({port}) 로그인이 필요합니다 - 그 창에서 직접 로그인해 주세요")
            else:
                problems.append(f"{tag}({port}) 준비 실패: {why}")

    result["problems"] = problems
    result["ok"] = not problems
    OUT.mkdir(exist_ok=True)
    (OUT / "preflight.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                        encoding="utf-8")

    print()
    if problems:
        print("=" * 60)
        print("  9시 준비 안 됨 - 사람이 손봐야 합니다")
        for p in problems:
            print("   - " + p)
        print("=" * 60)
        return 1
    print("=" * 60)
    print(f"  9시 준비 완료 - {origin or 'SEL'} -> {route}, {opens} 를 노린다")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
