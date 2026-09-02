"""무인 실행: 정해진 시각에 알아서 준비하고, 발사하고, 결과를 남긴다.

사용:
  .venv/bin/python dev/autorun.py --at 09:00 --route CDG --cabin 프레스티지 --date 08-24
  .venv/bin/python dev/autorun.py --at +90s --route CDG --cabin 일반석 --dry   (리허설)

--dry 는 7단계(첫 주문) 앞에서 멈춘다. 주문을 만들지 않으므로 반복해도 안전하다.

사람이 없어도 되게 하는 것이 목적이라, 막히면 '왜' 를 파일에 남기고 끝낸다.
고칠 수 없는 것(로그인 없음, 브라우저 없음)은 그대로 보고한다 - 추측해서 진행하지 않는다.
"""
from __future__ import annotations
import argparse, json, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER = ROOT / "userscript" / "ke-award-macro.user.js"
OUT = ROOT / "dev-shots"
CDP = "http://localhost:9222"
CAL = "/booking/calendar-fare-bonus"
KST = timezone(timedelta(hours=9))

report: dict = {}


def log(m):
    print(f"  [{datetime.now(KST).strftime('%H:%M:%S')}] {m}", flush=True)


def finish(ok: bool, why: str, code: int) -> int:
    report.update(ok=ok, why=why, endedAt=datetime.now(KST).isoformat())
    OUT.mkdir(exist_ok=True)
    (OUT / "autorun_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    log(("성공: " if ok else "실패: ") + why)
    print(json.dumps({"ok": ok, "why": why}, ensure_ascii=False))
    return code


def target_time(spec: str) -> datetime:
    now = datetime.now(KST)
    if spec.startswith("+"):
        return now + timedelta(seconds=int(spec[1:].rstrip("s")))
    h, m = (spec.split(":") + ["0"])[:2]
    t = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    return t if t > now else t + timedelta(days=1)


def ensure_browser() -> bool:
    """브라우저가 없으면 띄운다. 뜨는 데 시간이 걸리므로 넉넉히 기다린다."""
    import urllib.request
    for attempt in range(2):
        try:
            urllib.request.urlopen(CDP + "/json/version", timeout=4).read()
            return True
        except Exception:
            pass
        if attempt == 0:
            log("브라우저가 없어 새로 띄운다")
            try:
                if sys.platform == "win32":
                    subprocess.Popen(["cmd", "/c", str(ROOT / "dev-browser.cmd")],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.Popen(["bash", str(ROOT / "dev-browser.sh")],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
            except Exception as e:
                log(f"띄우기 실패: {e}")
                return False
            time.sleep(18)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", default="+60s", help="발사 시각 (09:00 또는 +90s)")
    ap.add_argument("--route", default="", help="도착지 코드 (CDG/FCO/ZRH/ICN). 생략하면 현재 설정")
    # 유럽발(로마->인천 등). 9/9 목표가 FCO->ICN 이라 필요하다. setup 으로 넘긴다.
    ap.add_argument("--from", dest="origin", default="", help="출발지 코드 (유럽발이면 FCO/CDG)")
    ap.add_argument("--cabin", default="프레스티지")
    ap.add_argument("--date", default="", help="목표 날짜 MM-DD (비우면 검사 안 함)")
    ap.add_argument("--dry", action="store_true", help="7단계(첫 주문) 앞에서 멈춘다")
    ap.add_argument("--lead", type=int, default=2500,
                    help="선발사(ms). 오픈시각보다 이만큼 일찍 새로고침해 조회가 09:00 직후 도착하게 한다")
    a = ap.parse_args()

    fire_at = target_time(a.at)
    report.update(startedAt=datetime.now(KST).isoformat(), fireAt=fire_at.isoformat(),
                  route=a.route, cabin=a.cabin, date=a.date, dry=a.dry)
    log(f"발사 예정 {fire_at.strftime('%H:%M:%S')} / 노선 {a.route or '(현재)'} / {a.cabin} / dry={a.dry}")

    if not ensure_browser():
        return finish(False, "브라우저를 띄우지 못함 (PC 가 켜져 있는지 확인)", 1)

    # --- 준비: 달력까지 ---
    # 목표 날짜의 '월' 로 달력을 옮겨야 그 날짜가 보인다. setup 은 YYYY-MM-DD 를 받는다.
    # 마일리지는 ~1년 뒤를 열므로, 목표 월이 이번 달보다 이르면 내년으로 본다.
    setup_cmd = [sys.executable, str(ROOT / "dev" / "setup.py")] + ([a.route] if a.route else [])
    if a.origin:
        setup_cmd += ["--from", a.origin]
    if a.date:
        mm, dd = a.date.split("-")
        yr = datetime.now(KST).year + (1 if int(mm) < datetime.now(KST).month else 0)
        setup_cmd += ["--date", f"{yr}-{mm}-{dd}"]
    r = subprocess.run(setup_cmd, capture_output=True, text=True, timeout=420)
    tail = (r.stdout or "").strip().splitlines()
    try:
        st = json.loads(tail[-1]) if tail else {}
    except Exception:
        st = {}
    if not st.get("ok"):
        return finish(False, f"달력 준비 실패: {st.get('why') or (r.stderr or '')[:80]}", 2)
    log("달력 준비됨")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.connect_over_cdp(CDP)
        ctx = b.contexts[0]
        js = USER.read_text(encoding="utf-8")
        ctx.add_init_script(js)
        page = [p for p in ctx.pages if "koreanair" in p.url][0]
        try: page.bring_to_front()      # 뒤에 있으면 브라우저가 타이머를 늦춘다
        except Exception: pass
        page.evaluate(js)

        page.evaluate("""({cabin, date, dry}) => {
          const R = window.KE_REC, H = window.KE_HUD;
          R.pause('autorun'); R.state.playAfterReload = false;
          R.loadBaked();
          if (dry) R.state.steps = R.state.steps.slice(0, 6);   // 7단계(첫 주문) 전까지
          R.state.cabin = cabin;
          R.state.expectDate = date || '';
          R.state.allowPay = !dry;
          R.state.byCause = {}; R.state.problem = false;
          R.reset(); R.save();
          H.state.startAt = 'calendar';
          H.state.armed = false;
        }""", {"cabin": a.cabin, "date": a.date, "dry": a.dry})

        # 선발사: 오픈시각보다 lead 만큼 일찍 새로고침한다. 페이지가 뜨는 데 ~2.5초가
        # 걸려서, 08:59:57.5 에 쏘면 조회가 09:00:01 경 (오픈 직후) 도착해 재고침을 피한다.
        lead_at = fire_at - timedelta(milliseconds=a.lead)
        report["leadMs"] = a.lead
        report["leadFireAt"] = lead_at.isoformat()
        wait = (lead_at - datetime.now(KST)).total_seconds()
        if wait > 0:
            log(f"{wait:.0f}초 대기 (발사 {lead_at.strftime('%H:%M:%S.%f')[:-3]}, 오픈 {fire_at.strftime('%H:%M:%S')} - 선발사 {a.lead}ms)")
            shown = False
            while True:
                left = (lead_at - datetime.now(KST)).total_seconds()
                if left <= 0:
                    break
                # 발사 30초 전에 창을 앞으로 가져온다 - 사람이 눈으로 지켜볼 수 있게
                # (겸사겸사 탭이 뒤에 있어 크롬이 타이머를 늦추는 것도 막는다)
                if not shown and left <= 30:
                    shown = True
                    try:
                        page.bring_to_front()
                        log("창을 앞으로 (발사 30초 전)")
                    except Exception:
                        pass
                time.sleep(min(5, max(0.02, left)))

        log("발사")
        t0 = time.time()
        try: page.bring_to_front()      # 발사 순간에도 한 번 더 (그새 뒤로 갔을 수 있다)
        except Exception: pass
        page.evaluate("() => window.KE_HUD.fire('autorun')")

        last, popup = -1, False
        ctx.on("page", lambda p: None)
        while time.time() - t0 < 180:
            time.sleep(0.2)
            # 페이지가 넘어가면 스크립트가 사라질 수 있다 (Tampermonkey 없이 붙여 쓰는 구조).
            # 없으면 그 자리에서 다시 넣는다 - 재생 위치는 localStorage 에 있어 이어진다.
            try:
                if not page.evaluate("() => !!window.KE_REC"):
                    page.evaluate(js)
                    log("스크립트 재주입")
            except Exception:
                continue
            try:
                s = page.evaluate("""() => ({idx: KE_REC.state.idx, n: KE_REC.state.steps.length,
                  playing: KE_REC.state.playing, msg: (KE_REC.state.message||'').slice(0,220),
                  cause: KE_REC.state.byCause, problem: KE_REC.state.problem,
                  times: KE_REC.state.times, url: location.pathname})""")
            except Exception:
                continue
            if s["idx"] != last:
                log(f"{s['idx']}/{s['n']} [{s['url']}]")
                last = s["idx"]
            if not s["playing"] and s["idx"] > 0:
                popup = any("pay.naver" in p.url or "payment-loading" in p.url for p in ctx.pages)
                report.update(idx=s["idx"], total=s["n"], msg=s["msg"], problem=s["problem"],
                              byCause=s["cause"], times=s["times"], payWindow=popup,
                              seconds=round(time.time() - t0, 2))
                break
        else:
            return finish(False, "180초 안에 끝나지 않음", 4)

        OUT.mkdir(exist_ok=True)
        try: page.screenshot(path=str(OUT / "autorun_end.png"))
        except Exception: pass

        try:
            report["seats"] = page.evaluate("() => window.KE_PROBE ? KE_PROBE.seatTimeline() : []")
        except Exception: pass

        done = report.get("idx", 0) >= report.get("total", 99)
        why = report.get("msg", "")
        return finish(done and not report.get("problem"), why, 0 if done else 5)


if __name__ == "__main__":
    sys.exit(main())
