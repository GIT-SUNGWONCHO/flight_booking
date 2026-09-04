"""매일 09:00 측정: 계측기(2번 크롬)와 dry 매크로(1번 크롬)를 동시에 돌린다.

왜 둘을 같이 돌리나
  계측기 = "좌석이 몇 석이고 언제 0 이 되나"
  dry 매크로 = "우리가 언제 잠글 수 있었나"
  두 숫자를 겹쳐야 "몇 초 부족한가" 가 나온다. 하나만으론 답이 안 나온다.

안전
  연습일에는 dry(7단계 앞 정지)라 주문·hold 를 만들지 않는다.
  계측기는 읽기 전용. 실전(목표일)에만 따로 전체 발사를 건다.

노선 자동 결정
  9시에 열리는 출발일 = 오늘 + 360일 (실측). 그 날이 월·수·토면 로마가 뜨고,
  아니면 파리만 뜬다. 로마 없는 날 로마로 돌리면 하루를 버린다.

사용:
  .venv/Scripts/python.exe dev/daily.py                  (자동 판단)
  .venv/Scripts/python.exe dev/daily.py --route CDG      (강제 지정)
"""
from __future__ import annotations
import argparse, json, subprocess, sys, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dev-shots"
KST = timezone(timedelta(hours=9))
OFFSET = 360                 # FACTS: 오픈일 = 실행일 + 360일
ROME_DAYS = {0, 2, 5}        # FACTS: 로마는 양방향 모두 월·수·토
WD = ['월', '화', '수', '목', '금', '토', '일']


def log(m):
    print(f"[{datetime.now(KST).strftime('%H:%M:%S')}] {m}", flush=True)


def popup(title: str, body: str):
    """스케줄러는 창을 숨기고 돌린다. 문제가 생기면 이렇게라도 눈에 띄게 한다."""
    import ctypes, threading
    threading.Thread(target=lambda: ctypes.windll.user32.MessageBoxW(
        0, body, title, 0x30), daemon=True).start()


def ready_checkpoint(hhmm: str, ports: list):
    """약속한 시각에 '정말로 발사할 수 있는 상태인가' 를 눈으로 확인한다.

    09-04 에 두 크롬이 현금 달력(/booking/calendar-fare)에 서 있었는데 아무도
    몰랐다. 프로세스는 이미 죽어 있었고 로그는 09:01 에야 나왔다.
    보너스 달력(calendar-fare-bonus)이 아니면 그 자리에서 사람을 부른다.
    """
    now = datetime.now(KST)
    h, m = (hhmm.split(":") + ["0"])[:2]
    t = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    if t > now:
        log(f"{t.strftime('%H:%M')} 준비 확인까지 대기")
        time.sleep((t - now).total_seconds())
    bad = []
    try:
        from playwright.sync_api import sync_playwright
        for port in ports:
            try:
                with sync_playwright() as pw:
                    b = sync_cdp(pw, port)
                    url = b.contexts[0].pages[-1].url if b.contexts[0].pages else ""
                    b.close()
            except Exception as e:
                url = f"(붙지 못함: {str(e)[:40]})"
            ok = "calendar-fare-bonus" in url
            log(f"  준비확인 {port}: {'OK' if ok else 'X'}  {url[:70]}")
            if not ok:
                bad.append(f"{port}: {url[:70]}")
    except Exception as e:
        bad.append(f"확인 자체가 실패: {str(e)[:60]}")
    if bad:
        log("!!! 준비 안 됨 - 팝업")
        popup("9시 준비 안 됨 (지금 손봐야 합니다)",
              "마일리지 달력에 서 있지 않습니다:\n\n"
              + "\n".join(bad)
              + "\n\n9시까지 시간이 있습니다."
                "\n그 창에서 마일리지 예매로 들어가 주세요.")
    else:
        log("준비 확인 통과 - 두 크롬 모두 마일리지 달력")


def sync_cdp(pw, port: int):
    return pw.chromium.connect_over_cdp(f"http://localhost:{port}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", default="09:00")
    # 셋업이 실패하면 다시 해봐야 한다. 08:52 면 재시도 시간이 없다. (09-04)
    ap.add_argument("--setup-at", default="08:40")
    ap.add_argument("--route", default="", help="비우면 요일로 자동 (월수토=FCO, 그 외=CDG)")
    ap.add_argument("--from", dest="origin", default="", help="유럽발이면 FCO/CDG")
    ap.add_argument("--port2", type=int, default=9223)
    ap.add_argument("--no-macro", action="store_true", help="계측기만 돌린다")
    ap.add_argument("--no-watch", action="store_true", help="매크로만 돌린다")
    # 리허설용. 08:20 에는 오늘 열릴 날짜가 아직 없어 그 날짜로는 못 쏜다.
    # 이미 열린 최신일을 넣어 파이프라인만 확인한다.
    ap.add_argument("--date", default="", help="MM-DD 강제 (비우면 오늘+360)")
    ap.add_argument("--ready-by", default="", help="이 시각에 두 크롬이 보너스 달력에 서 있는지 확인 (HH:MM)")
    a = ap.parse_args()

    today = datetime.now(KST).date()
    opens = today + timedelta(days=OFFSET)
    rome_ok = opens.weekday() in ROME_DAYS

    # 노선/방향 자동: 로마 날이면 9/9 목표와 같은 방향(로마->인천)으로 연습하고,
    # 아니면 9/14 목표와 같은 방향(인천->파리)으로 연습한다.
    if a.route:
        route, origin = a.route.upper(), a.origin.upper()
    elif rome_ok:
        route, origin = "ICN", "FCO"      # 로마 -> 인천 (9/9 목표 방향)
    else:
        route, origin = "CDG", ""         # 인천 -> 파리 (9/14 목표 방향)

    mmdd = a.date or opens.strftime("%m-%d")
    log(f"오늘 {today}({WD[today.weekday()]}) 9시에 열리는 날: "
        f"{opens}({WD[opens.weekday()]})  로마운항={'O' if rome_ok else 'X'}")
    log(f"측정 노선: {origin or 'SEL'} -> {route}  (출발일 {mmdd})")

    procs = {}
    if not a.no_watch:
        cmd = [sys.executable, str(ROOT / "dev" / "watch_seats.py"),
               "--route", route, "--date", mmdd, "--at", a.at,
               "--port", str(a.port2), "--setup-at", a.setup_at]
        if origin:
            cmd += ["--from", origin]
        procs["watch"] = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT, text=True)
        log("계측기 시작 (2번 크롬)")
    if not a.no_macro:
        cmd = [sys.executable, str(ROOT / "dev" / "autorun.py"),
               "--route", route, "--date", mmdd, "--at", a.at, "--dry"]
        if origin:
            cmd += ["--from", origin]
        procs["macro"] = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT, text=True)
        log("dry 매크로 시작 (1번 크롬, 주문 안 만듦)")

    if a.ready_by:
        ready_checkpoint(a.ready_by, [9222, a.port2])

    outs = {}
    for name, p in procs.items():
        outs[name] = (p.communicate()[0] or "")[-1500:]
        log(f"{name} 종료 (코드 {p.returncode})")

    # 두 결과를 한 줄로 합쳐 쌓는다
    summary = {"day": str(today), "opens": str(opens), "weekday": WD[opens.weekday()],
               "route": route, "origin": origin or "SEL"}
    try:
        w = json.loads((OUT / "watch_seats.json").read_text(encoding="utf-8"))
        summary["prestigeSeats"] = w.get("maxPrestigeSeats")
        summary["goneSinceOpen"] = w.get("goneSinceOpen")
        summary["samples"] = w.get("samples")
    except Exception:
        pass
    try:
        m = json.loads((OUT / "autorun_report.json").read_text(encoding="utf-8"))
        summary["macroIdx"] = m.get("idx")
        summary["macroSeconds"] = m.get("seconds")
        summary["macroWhy"] = (m.get("why") or "")[:120]
    except Exception:
        pass

    (OUT).mkdir(exist_ok=True)
    with (OUT / "daily_history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    log("요약: " + json.dumps(summary, ensure_ascii=False))
    for name, o in outs.items():
        print(f"--- {name} ---\n{o}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
