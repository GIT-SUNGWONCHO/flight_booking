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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", default="09:00")
    ap.add_argument("--setup-at", default="08:52")
    ap.add_argument("--route", default="", help="비우면 요일로 자동 (월수토=FCO, 그 외=CDG)")
    ap.add_argument("--from", dest="origin", default="", help="유럽발이면 FCO/CDG")
    ap.add_argument("--port2", type=int, default=9223)
    ap.add_argument("--no-macro", action="store_true", help="계측기만 돌린다")
    ap.add_argument("--no-watch", action="store_true", help="매크로만 돌린다")
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

    mmdd = opens.strftime("%m-%d")
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
