"""좌석 계측기: 09:00 에 새로 열리는 날짜의 프레스티지 좌석이 몇 석이고
언제 0 이 되는지 잰다. 읽기 전용 - 예약은 절대 하지 않는다.

왜 필요한가 (2026-09-02 실전):
  09:00:03 프레스티지 1석 → 09:00:10 우리가 잠그려니 이미 사라짐.
  "몇 초에 채이는가" 를 모르면 얼마나 더 빨라져야 하는지 알 수 없다.

어떻게 재는가:
  좌석 수는 7단계까지 안 가도 **조회 응답**에 있다
  (awardAvailability → commercialFareFamilyList → KEBONUSPR.seatCount/soldout).
  그래서 매크로의 1~2단계(날짜 클릭 + 검색)만 재생해 조회 화면에 도달한 뒤,
  날짜 띠를 다시 눌러 재조회하며 좌석 수 변화를 기록한다.

  첫 측정은 빨라야 09:00:03 쯤이다 - 새 날짜는 09:00:00 에야 고를 수 있고
  조회 응답까지 3초쯤 걸린다. 그 이전은 구조적으로 못 본다.

전제: dev-browser2.cmd (포트 9223, 별도 프로필) 가 떠 있고 계측용 계정으로 로그인됨.
사용:
  .venv/Scripts/python.exe dev/watch_seats.py --route FCO --date 08-28 --at 09:00
"""
from __future__ import annotations
import argparse, json, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER = ROOT / "userscript" / "ke-award-macro.user.js"
OUT = ROOT / "dev-shots"
KST = timezone(timedelta(hours=9))


def log(m):
    print(f"  [{datetime.now(KST).strftime('%H:%M:%S.%f')[:-3]}] {m}", flush=True)


def wait_until(when: datetime) -> None:
    # 한 번의 긴 sleep 은 절전 중 멈춘다. 벽시계를 다시 보며 짧게 나눠 기다린다.
    while True:
        left = (when - datetime.now(KST)).total_seconds()
        if left <= 0.02:
            return
        time.sleep(min(5, max(0.02, left)))


def at(spec: str) -> datetime:
    now = datetime.now(KST)
    if spec.startswith("+"):
        return now + timedelta(seconds=int(spec[1:].rstrip("s")))
    p = (spec.split(":") + ["0", "0"])[:3]
    t = now.replace(hour=int(p[0]), minute=int(p[1]), second=int(p[2]), microsecond=0)
    return t if t > now else t + timedelta(days=1)


# 조회 화면에서 목표 날짜를 다시 눌러 재조회시킨다(페이지 이동 없이 그 자리에서).
REPRESS = """(mmdd) => {
  const U = window.KE_UTIL;
  if (!U || !U.findStripDate) return 'no-util';
  const c = U.findStripDate(mmdd);
  if (!c) return 'no-strip';
  U.fireClick(c);
  return 'ok';
}"""

# '새 응답인가' 는 조회 응답의 도착 시각(epoch ms)으로 판단한다.
# stamp 는 문서마다 0 부터 다시 세서, 새로고침하면 값이 같아져 새 응답을 놓친다(실측:
# 표본이 2건에서 멈췄다). 시각은 문서를 넘어 단조증가하므로 안전하다.
READ = """(cab) => {
  const P = window.KE_PROBE;
  if (!P || !P.keCabin) return null;
  var last = 0;
  try {
    var hs = P.hits();
    for (var i = hs.length - 1; i >= 0; i--) {
      if (/availab/i.test(hs[i].url)) { last = hs[i].at; break; }
    }
  } catch (e) {}
  return { pr: P.keCabin('프레스티지', cab), ey: P.keCabin('일반석', cab),
           lastAt: last };
}"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", required=True, help="도착지 코드 (FCO/CDG)")
    ap.add_argument("--from", dest="origin", default="", help="출발지 코드 (유럽발이면 FCO 등)")
    ap.add_argument("--date", required=True, help="지켜볼 출발일 MM-DD (그날 새로 열리는 날)")
    ap.add_argument("--at", default="09:00", help="오픈 시각")
    ap.add_argument("--lead", type=int, default=2500, help="선발사(ms)")
    ap.add_argument("--until", type=int, default=90, help="오픈 후 몇 초까지 지켜볼지")
    ap.add_argument("--gap", type=float, default=6.0, help="느슨한 구간의 재조회 간격(초)")
    # 승부는 오픈 직후 20초 안에 난다(2026-09-02 실전: 1석이 10초 안에 사라짐).
    # 그 구간만 촘촘히 보고, 이후엔 요청 수를 줄인다.
    ap.add_argument("--fast-gap", type=float, default=1.0, help="초반 촘촘히 볼 때 간격(초)")
    ap.add_argument("--fast-window", type=float, default=20.0, help="촘촘히 볼 구간(오픈 후 초)")
    ap.add_argument("--port", type=int, default=9223, help="2번 크롬 포트")
    ap.add_argument("--setup-at", default="", help="이 시각에 달력까지 준비 (예: 08:50)")
    a = ap.parse_args()

    open_at = at(a.at)
    fire_at = open_at - timedelta(milliseconds=a.lead)
    end_at = open_at + timedelta(seconds=a.until)
    rows: list = []
    report = {"startedAt": datetime.now(KST).isoformat(), "route": a.route,
              "origin": a.origin or "SEL", "date": a.date, "openAt": open_at.isoformat()}

    # --- 준비: 달력까지 (계측용 크롬에서) ---
    if a.setup_at:
        wait_until(at(a.setup_at))
    yr = datetime.now(KST).year + (1 if int(a.date.split("-")[0]) < datetime.now(KST).month else 0)
    cmd = [sys.executable, str(ROOT / "dev" / "setup.py"), a.route,
           "--port", str(a.port), "--date", f"{yr}-{a.date}"]
    if a.origin:
        cmd += ["--from", a.origin]
    log(f"달력 준비 ({a.origin or 'SEL'} -> {a.route}, {yr}-{a.date})")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    tail = (r.stdout or "").strip().splitlines()
    try: st = json.loads(tail[-1]) if tail else {}
    except Exception: st = {}
    if not st.get("ok"):
        log(f"준비 실패: {st.get('why') or (r.stderr or '')[:100]}")
        report["ok"] = False; report["why"] = st.get("why") or "달력 준비 실패"
        OUT.mkdir(exist_ok=True)
        (OUT / "watch_seats.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
        return 2
    log("달력 준비됨")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.connect_over_cdp(f"http://localhost:{a.port}")
        ctx = b.contexts[0]
        js = USER.read_text(encoding="utf-8")
        # 새 문서가 뜰 때마다 스크립트를 '페이지 스크립트보다 먼저' 넣는다.
        # 이게 없으면 (a) 발사 후 새로고침에서 매크로가 사라져 재생이 멈추고
        # (b) 조회 XHR 이 우리가 주입하기 전에 끝나 프로브가 놓친다.
        # 실측(2026-09-02): 이것 없이 돌렸다가 기록 0건 - 달력에서 한 발도 못 나갔다.
        ctx.add_init_script(js)
        page = [p for p in ctx.pages if "koreanair" in p.url][-1]
        try: page.bring_to_front()
        except Exception: pass
        page.evaluate(js)

        # 매크로의 1~2단계(날짜 클릭 + 검색)만 재생한다. 예약 단계는 아예 싣지 않는다.
        page.evaluate("""({date}) => {
          const R = window.KE_REC, H = window.KE_HUD;
          R.pause('watch'); R.state.playAfterReload = false;
          R.loadBaked();
          R.state.steps = R.state.steps.slice(0, 2);   // 날짜 + 검색 까지만
          R.state.expectDate = date;
          R.state.allowPay = false;
          R.state.byCause = {}; R.state.problem = false; R.state.openReloads = 0;
          R.reset(); R.save();
          H.state.startAt = 'calendar'; H.state.armed = false; H.save();
        }""", {"date": a.date})

        wait = (fire_at - datetime.now(KST)).total_seconds()
        if wait > 0:
            log(f"{wait:.0f}초 대기 (발사 {fire_at.strftime('%H:%M:%S.%f')[:-3]})")
            wait_until(fire_at)
        log("발사 - 조회 화면으로")
        t0 = time.time()
        page.evaluate("() => window.KE_HUD.fire('watch')")

        # 조회 화면에 도착할 때까지 (매크로가 날짜 클릭 + 검색을 한다)
        seen_stamp = 0          # 마지막으로 본 조회 응답의 도착 시각(epoch ms)
        gone_at = None
        best_seats = None
        last_new = time.time()   # 마지막으로 '새 응답' 을 본 시각 (재조회 강제 판단용)
        # 한 주기 = [새 응답을 기다렸다 기록] -> [곧바로 다음 재조회]
        #
        # 예전엔 '6초 동안 새 응답이 없으면' 새로고침해서 주기가 11초까지 늘어졌다(실측).
        # 1->0 전환을 좁히려면 응답이 오는 즉시 다음 재조회를 걸어야 한다.
        # 날짜 띠 다시 누르기는 이미 선택된 날짜면 아무 일도 안 하므로(실측) 새로고침으로 건다.
        # 조회 페이지 새로고침은 세션의 날짜를 유지한 채 다시 조회한다(실측 확인).
        last_ask = 0.0
        asks = 0
        while datetime.now(KST) < end_at:
            d = None
            try:
                if not page.evaluate("() => !!window.KE_REC"):
                    page.evaluate(js)
                d = page.evaluate(READ, a.date)
            except Exception:
                time.sleep(0.2)
                d = None
            if d and not ((d.get("lastAt") or 0) > seen_stamp and (d.get("pr") or d.get("ey"))):
                d = None

            if d:
                seen_stamp = d["lastAt"]
                last_new = time.time()
                pr, ey = d.get("pr") or {}, d.get("ey") or {}
                now = datetime.now(KST)
                secs = round((now - open_at).total_seconds(), 2)
                row = {"at": now.isoformat(), "sinceOpen": secs,
                       "prSeats": pr.get("seats"), "prSoldout": pr.get("soldout"),
                       "prListed": pr.get("listed"), "eySeats": ey.get("seats"),
                       "keFlights": pr.get("keFlights")}
                rows.append(row)
                mark = ""
                if pr.get("listed") and not pr.get("soldout"):
                    best_seats = max(best_seats or 0, pr.get("seats") or 0)
                    mark = "  ★있음"
                elif pr.get("soldout") and best_seats and not gone_at:
                    gone_at = now
                    mark = "  ← 방금 0 이 됨"
                log(f"오픈+{secs:6.2f}s  프레스티지 "
                    f"{'매진' if pr.get('soldout') else str(pr.get('seats')) + '석'}"
                    f"  (일반석 {ey.get('seats')}){mark}")
                if gone_at:
                    break

            # 재조회를 '겹쳐서' 쏜다. 응답을 기다리지 않고 간격마다 발사하므로,
            # API 가 1.7초 걸려도 표본 간격은 발사 간격(초반 1초)에 수렴한다.
            # 페이지가 자기 세션으로 같은 조회를 한 번 더 하는 것이라 상태를 안 바꾼다.
            since_open = (datetime.now(KST) - open_at).total_seconds()
            gap = a.fast_gap if since_open < a.fast_window else a.gap
            if (time.time() - last_ask) >= gap:
                try:
                    r = page.evaluate("() => window.KE_PROBE ? KE_PROBE.reAsk() : 'no-probe'")
                except Exception:
                    r = "err"
                last_ask = time.time()
                asks += 1
                # 되쏠 요청을 아직 못 잡았으면(조회 전) 새로고침으로 대신한다.
                if r in ("no-request", "no-probe") and since_open > 8:
                    try:
                        page.reload(wait_until="domcontentloaded", timeout=20000)
                    except Exception:
                        pass
            time.sleep(0.15)

        report.update(ok=True, rows=rows, maxPrestigeSeats=best_seats,
                      goneAt=gone_at.isoformat() if gone_at else None,
                      goneSinceOpen=round((gone_at - open_at).total_seconds(), 2) if gone_at else None,
                      samples=len(rows))
        OUT.mkdir(exist_ok=True)
        (OUT / "watch_seats.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
        # 날짜별로 쌓아 패턴이 보이게 한다
        hist = OUT / "seat_history.jsonl"
        with hist.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"day": datetime.now(KST).strftime("%Y-%m-%d"),
                                "route": a.route, "origin": a.origin or "SEL",
                                "date": a.date, "maxPrestigeSeats": best_seats,
                                "goneSinceOpen": report.get("goneSinceOpen"),
                                "samples": len(rows)}, ensure_ascii=False) + "\n")
        # '읽었는데 매진' 과 '아예 못 읽음' 은 전혀 다른 결과다. 뭉뚱그리면 다음날
        # 기록을 볼 때 계측이 실패한 건지 좌석이 없던 건지 구분이 안 된다.
        ever = any(r.get("prListed") for r in rows)
        if best_seats:
            note = f" / 프레스티지 최대 {best_seats}석"
        elif ever:
            note = " / 프레스티지 처음부터 매진(0석)"
        else:
            note = " / 프레스티지 정보 없음(계측 실패 가능)"
        report["prestigeEverListed"] = ever
        log(f"기록 {len(rows)}건 -> dev-shots/watch_seats.json" + note
            + (f" / 오픈+{report['goneSinceOpen']}초에 0" if gone_at else ""))
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
