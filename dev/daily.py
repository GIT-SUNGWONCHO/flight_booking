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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ke_setup import TARGETS, nearest_future   # 날짜 계산·목표일은 저장소에 한 벌만 둔다

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


def ready_checkpoint(hhmm: str, ports: list, procs: dict = None, want_date: str = ""):
    """약속한 시각에 '정말로 발사할 수 있는 상태인가' 를 확인한다.

    09-04 에 두 크롬이 현금 달력(/booking/calendar-fare)에 서 있었는데 아무도
    몰랐다. 프로세스는 이미 죽어 있었고 로그는 09:01 에야 나왔다.

    **화면만 보면 안 된다.** 매크로가 죽어도 달력은 그대로 남아 있어서 통과한다.
    프로세스가 살아 있는지, 로그인돼 있는지, 목표 달을 그리고 있는지 같이 본다.
    (리뷰 P1, 09-08)
    """
    now = datetime.now(KST)
    h, m = (hhmm.split(":") + ["0"])[:2]
    t = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    if t > now:
        log(f"{t.strftime('%H:%M')} 준비 확인까지 대기")
        time.sleep((t - now).total_seconds())
    bad = []

    # 1) 프로세스가 살아 있나. 죽었으면 화면이 멀쩡해도 9시에 아무 일도 안 일어난다.
    for name, p in (procs or {}).items():
        if p.poll() is not None:
            bad.append(f"{name} 프로세스가 이미 끝났다 (코드 {p.returncode})")
            log(f"  준비확인 {name}: X 죽어 있음 (코드 {p.returncode})")
        else:
            log(f"  준비확인 {name}: 살아 있음")

    # 2) 화면 - 보너스 달력인가 / 로그인돼 있나 / 목표 달을 그리는가
    ym = ""
    if want_date:
        try:
            ym = nearest_future(want_date).strftime("%Y%m")
        except Exception:
            ym = ""
    try:
        from playwright.sync_api import sync_playwright
        USER = ROOT / "userscript" / "ke-award-macro.user.js"
        for port in ports:
            info, url = {}, ""
            try:
                with sync_playwright() as pw:
                    b = sync_cdp(pw, port)
                    pages = b.contexts[0].pages
                    page = pages[-1] if pages else None
                    if page:
                        url = page.url
                        try:
                            page.evaluate(USER.read_text(encoding="utf-8"))
                            info = page.evaluate("""() => {
                              const U = window.KE_UTIL;
                              const lab = U.candidates(document).filter(e => U.visible(e))
                                .map(e => U.label(e)).filter(Boolean);
                              return {
                                loggedIn: lab.some(t => /로그아웃/.test(t)),
                                months: [...document.querySelectorAll('[id^=month]')].map(e => e.id)
                              };
                            }""")
                        except Exception:
                            info = {}
                    b.close()
            except Exception as e:
                url = f"(붙지 못함: {str(e)[:40]})"
            probs = []
            if "calendar-fare-bonus" not in url:
                probs.append(f"마일리지 달력이 아님: {url[:60]}")
            if info and not info.get("loggedIn"):
                probs.append("로그아웃 상태")
            if ym and info.get("months") and f"month{ym}" not in info["months"]:
                probs.append(f"목표 달(month{ym})을 안 그림: {info['months']}")
            log(f"  준비확인 {port}: {'OK' if not probs else 'X ' + ' / '.join(probs)}")
            bad += [f"{port}: {p}" for p in probs]
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


def spawn(name: str, cmd: list):
    """자식을 띄우고 출력을 파일로 받는다.

    PIPE 로 받아 두고 communicate 를 늦게 부르면 파이프 버퍼가 차서 자식이 멈춘다.
    ready_checkpoint 가 08:50 까지 기다리는 동안 그럴 수 있었다. (리뷰 P1, 09-08)
    """
    OUT.mkdir(exist_ok=True)
    f = (OUT / f"{name}.out").open("w", encoding="utf-8", errors="replace")
    return subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)


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
    # 매크로를 어디까지 돌릴지. 기본은 dry - 실전은 사람이 명시해야만 온다.
    #   dry  7단계 앞에서 정지. 주문도 hold 도 안 생긴다 (연습 기본값)
    #   hold 7단계까지. 좌석을 실제로 잡고 멈춘다. 결제는 사람이 (09-09 실전)
    #   full 17단계 전부. 결제까지 한다
    ap.add_argument("--mode", default="dry", choices=["dry", "hold", "full"])
    # 실전 모드를 오늘이 목표일이 아닐 때 쓰려면 이걸 같이 줘야 한다.
    # day.ps1 에 hold 를 적어 두고 다음날 지우는 것을 잊으면 **연습일에 주문이 생긴다.**
    ap.add_argument("--force-live", action="store_true",
                    help="목표일이 아닌 날에도 hold/full 을 허용한다")
    a = ap.parse_args()

    started = datetime.now(KST)
    today = started.date()

    # 실전 모드는 목표일에만. day.ps1 에 hold 를 적어 두고 다음날 지우는 것을 잊으면
    # 연습일에 실제 주문이 생긴다 - 마일리지가 실제로 빠져나간다. 날짜로 잠근다.
    if a.mode != "dry" and today not in TARGETS and not a.force_live:
        log(f"오늘({today})은 실전 목표일이 아닌데 --mode {a.mode} 다. dry 로 내린다.")
        log(f"  목표일: {', '.join(str(d) for d in sorted(TARGETS))}")
        log("  정말 실전으로 쏘려면 --force-live 를 같이 준다.")
        a.mode = "dry"
    elif a.mode != "dry":
        why = "목표일" if today in TARGETS else "--force-live 로 강제"
        log(f"*** 실전 모드 {a.mode} ({why}) - 좌석을 실제로 잡는다 ***")
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

    # 결과 파일 이름이 고정이라 옛 실행 것이 남아 있다. 지우고 시작해 '이번 실행에
    # 결과가 없다' 와 '어제 결과가 남아 있다' 를 구별한다. (리뷰 P1, 09-08)
    OUT.mkdir(exist_ok=True)
    for f in ("watch_seats.json", "autorun_report.json"):
        try:
            (OUT / f).unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass

    procs = {}
    if not a.no_watch:
        cmd = [sys.executable, str(ROOT / "dev" / "watch_seats.py"),
               "--route", route, "--date", mmdd, "--at", a.at,
               "--port", str(a.port2), "--setup-at", a.setup_at]
        if origin:
            cmd += ["--from", origin]
        procs["watch"] = spawn("watch", cmd)
        log("계측기 시작 (2번 크롬)")
    if not a.no_macro:
        cmd = [sys.executable, str(ROOT / "dev" / "autorun.py"),
               "--route", route, "--date", mmdd, "--at", a.at]
        if a.mode == "dry":
            cmd += ["--dry"]
        elif a.mode == "hold":
            cmd += ["--hold"]
        # mode == "full" 이면 아무것도 안 붙인다 (결제까지). 사람이 명시해야만 온다.
        if origin:
            cmd += ["--from", origin]
        procs["macro"] = spawn("macro", cmd)
        log(f"매크로 시작 (1번 크롬, 모드 {a.mode})")

    if a.ready_by:
        watched = [p for p, use in ((9222, not a.no_macro), (a.port2, not a.no_watch)) if use]
        ready_checkpoint(a.ready_by, watched, procs, mmdd)

    # 자식 출력은 파일로 받는다. PIPE 로 받고 communicate 를 늦게 부르면 버퍼가
    # 차서 **자식이 멈춘다**. ready_checkpoint 가 08:50 까지 기다리는 동안 그럴 수
    # 있었다. (리뷰 P1, 09-08)
    outs, failed = {}, []
    for name, p in procs.items():
        p.wait()
        f = OUT / f"{name}.out"
        try:
            outs[name] = f.read_text(encoding="utf-8", errors="replace")[-1500:]
        except Exception:
            outs[name] = ""
        log(f"{name} 종료 (코드 {p.returncode})  로그: {f}")
        if p.returncode != 0:
            failed.append(f"{name}({p.returncode})")

    # 두 결과를 한 줄로 합쳐 쌓는다
    summary = {"day": str(today), "opens": str(opens), "weekday": WD[opens.weekday()],
               "route": route, "origin": origin or "SEL", "mode": a.mode,
               "runStartedAt": started.isoformat()}

    # 결과 파일 이름이 고정이라 **이번 실행에서 안 쓴 옛 파일을 읽을 수 있다.**
    # 시작 시각을 대조해 이번 실행 것이 아니면 안 쓴다. (리뷰 P1, 09-08)
    def fresh(fn: str):
        try:
            d = json.loads((OUT / fn).read_text(encoding="utf-8"))
        except Exception:
            return None
        try:
            if datetime.fromisoformat(d.get("startedAt", "")) < started:
                summary.setdefault("stale", []).append(fn)
                return None
        except Exception:
            return None
        return d

    w = fresh("watch_seats.json")
    if w:
        summary["prestigeSeats"] = w.get("maxPrestigeSeats")
        summary["goneSinceOpen"] = w.get("goneSinceOpen")
        summary["samples"] = w.get("samples")
    m = fresh("autorun_report.json")
    if m:
        summary["macroIdx"] = m.get("idx")
        summary["macroSeconds"] = m.get("seconds")
        summary["macroWhy"] = (m.get("why") or "")[:120]
    if failed:
        summary["failed"] = failed

    (OUT).mkdir(exist_ok=True)
    with (OUT / "daily_history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    log("요약: " + json.dumps(summary, ensure_ascii=False))
    for name, o in outs.items():
        print(f"--- {name} ---\n{o}")
    # 자식이 실패했으면 그대로 알린다. 예전엔 무조건 0 을 돌려줘서 스케줄러가
    # 성공으로 기록했다. (리뷰 P1, 09-08)
    if failed:
        log("실패한 자식: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
