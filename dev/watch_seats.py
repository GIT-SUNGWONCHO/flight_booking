"""좌석 계측기: 09:00 에 새로 열리는 날짜의 프레스티지 좌석이 몇 석이고
언제 0 이 되는지 잰다. 읽기 전용 - 예약은 절대 하지 않는다.

설계 (2026-09-03 리뷰로 전면 수정)
  좌석 수는 7단계까지 안 가도 조회 응답에 있다
  (awardAvailability -> commercialFareFamilyList -> KEBONUSPR.seatCount/soldout).

  목표일 D 는 09:00:00 에야 고를 수 있다. 그런데 **화면은 저절로 바뀌지 않는다** -
  08:5x 에 그려진 날짜 띠는 D 가 없던 시절의 응답으로 만들어진 것이고, 가만히
  들여다봐도 영원히 D 가 안 나타난다(실측). 그래서 이 저장소에서 이미 검증된 방식,
  즉 **새로고침으로 다시 그리기**를 쓴다 (recorder.js 가 목표 날짜를 기다릴 때 하는 것과 같다).

  한 주기: 새로고침 -> 띠에 D 가 고를 수 있게 나타났나 -> 누른다 -> D 응답 확인
  그 뒤에야 1초 간격 되쏘기(reAsk)로 촘촘히 잰다.

  되쏘기를 D 응답 확인 전에 시작하면 안 된다. reAsk 는 '가장 최근 조회 요청' 을
  되쏘는데 그게 아직 D-1 요청이면, 그 응답이 또 최신이 되어 D-1 을 영원히 되쏘는
  고리에 빠진다. 그러면 콘솔엔 좌석이 살아있는 것처럼 예쁘게 찍히는데 값은 전부
  D-1 것이다 - 비어 있는 것보다 나쁘다.

안전
  조회만 한다. 예약 단계는 밟지 않고 HUD 무장도 꺼둔다.

사용:
  .venv/Scripts/python.exe dev/watch_seats.py --route FCO --date 08-30 --at 09:00 --port 9223
"""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys, time, traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ke_setup import nearest_future, run_setup

ROOT = Path(__file__).resolve().parent.parent
USER = ROOT / "userscript" / "ke-award-macro.user.js"
OUT = ROOT / "dev-shots"
KST = timezone(timedelta(hours=9))
STRIP_SPAN = 3          # 조회 화면 날짜 띠가 품는 범위 (선택일 ±3일)


def log(m):
    print(f"  [{datetime.now(KST).strftime('%H:%M:%S.%f')[:-3]}] {m}", flush=True)


def wait_until(when: datetime) -> None:
    while True:
        left = (when - datetime.now(KST)).total_seconds()
        if left <= 0.02:
            return
        time.sleep(min(5, max(0.02, left)))


def browser_alive(port: int) -> bool:
    """CDP 가 실제로 답하는지 본다. 포트가 LISTEN 이라고 살아 있는 게 아니다 -
    방금 죽은 크롬의 소켓이 잠시 남아 거짓으로 읽힌다(09-08 실측)."""
    import urllib.request
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3).read()
        return True
    except Exception:
        return False


def at(spec: str) -> datetime:
    now = datetime.now(KST)
    if spec.startswith("+"):
        return now + timedelta(seconds=int(spec[1:].rstrip("s")))
    p = (spec.split(":") + ["0", "0"])[:3]
    t = now.replace(hour=int(p[0]), minute=int(p[1]), second=int(p[2]), microsecond=0)
    return t if t > now else t + timedelta(days=1)


# nearest_future 는 ke_setup 에 있다. 여기 복사본을 두었다가 autorun 만 옛 규칙으로
# 남아 09-07 에 세 번 죽었다. 날짜 계산은 저장소에 한 벌만 둔다.


# 날짜 띠에서 목표일을 누른다. findStripDate 는 {el, selectable, why} 를 돌려준다.
PRESS = """(mmdd) => {
  const U = window.KE_UTIL;
  if (!U || !U.findStripDate) return 'no-util';
  const c = U.findStripDate(mmdd);
  if (!c) return 'no-strip';
  if (!c.el) return 'none:' + (c.why || '');
  if (!c.selectable) return 'locked:' + (c.why || '');
  U.fireClick(c.el);
  return 'ok';
}"""

# 지금 화면이 보고 있는 날짜(MM-DD). 엉뚱한 날짜에 서 있는지 확인하는 근거.
SCREEN = """() => {
  const U = window.KE_UTIL;
  return U && U.searchedDate ? U.searchedDate() : null;
}"""

# 목표 날짜의 좌석. lastAt 은 '그 날짜를 담은 응답' 의 도착 시각이라야 한다.
# 아무 응답의 시각을 쓰면 D-1 되쏘기가 새 표본으로 둔갑한다(리뷰 지적).
"""브라우저에 **이미 쌓인** 응답을 읽는다. 서버에 새로 묻는 것은 reAsk 뿐이다.

이 구분이 중요하다. 이 함수를 0.2초마다 부른다고 0.2초마다 재는 것이 아니다 -
같은 응답을 다시 읽을 뿐이다. 표본이 새로워지는 것은 **새 응답이 도착했을 때**고,
그건 reAsk 가 보낸 요청이 돌아왔을 때다. (09-08 사용자 지적)

그래서 srcId 를 같이 돌려준다. 이 값이 바뀌어야 새 응답이다.
"""
READ = """(cab) => {
  const P = window.KE_PROBE;
  if (!P || !P.keCabin) return null;
  const pr = P.keCabin('프레스티지', cab);
  const ey = P.keCabin('일반석', cab);
  const src = pr || ey || null;
  return {
    pr: pr, ey: ey,
    srcId:     src ? (src.srcId || 0) : 0,
    srcAt:     src ? (src.srcAt || 0) : 0,
    srcSentAt: src ? (src.srcSentAt || 0) : 0,
    srcStatus: src ? (src.srcStatus || 0) : 0,
    lastAt:    src ? (src.srcAt || 0) : 0,
    now: Date.now()
  };
}"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", required=True)
    ap.add_argument("--from", dest="origin", default="")
    ap.add_argument("--date", required=True, help="지켜볼 출발일 MM-DD (그날 새로 열리는 날)")
    ap.add_argument("--at", default="09:00")
    ap.add_argument("--lead", type=int, default=2500)
    ap.add_argument("--until", type=int, default=90)
    ap.add_argument("--gap", type=float, default=6.0)
    ap.add_argument("--fast-gap", type=float, default=1.0)
    ap.add_argument("--fast-window", type=float, default=20.0)
    ap.add_argument("--reload-gap", type=float, default=1.5, help="D 를 기다리며 새로고침하는 간격")
    ap.add_argument("--port", type=int, default=9223)
    ap.add_argument("--setup-at", default="")
    a = ap.parse_args()

    tgt = nearest_future(a.date)
    stand = tgt - timedelta(days=1)
    open_at = at(a.at)
    fire_at = open_at - timedelta(milliseconds=a.lead)
    end_at = open_at + timedelta(seconds=a.until)

    rows: list = []
    asks: list = []          # reAsk 를 언제 보냈나. 표본과 대조해 왕복 시간을 본다
    # 실행마다 다른 이름으로도 남긴다. 고정 이름 하나면 오후 리허설이 09:00 을 덮는다.
    run_id = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    report = {"runId": run_id,
              "startedAt": datetime.now(KST).isoformat(), "route": a.route,
              "origin": a.origin or "SEL", "date": a.date, "target": tgt.isoformat(),
              "openAt": open_at.isoformat(), "ok": False, "why": "시작 전"}

    def save_report():
        # 예외로 죽어도 리포트는 남긴다. 안 남기면 daily 가 '어제 파일' 을 오늘로 읽는다.
        try:
            ever = any(r.get("prListed") for r in rows)
            report["rows"] = rows
            report["samples"] = len(rows)
            report["asks"] = asks           # 서버에 실제로 새로 물은 횟수·시각
            report["asksSent"] = sum(1 for x in asks if x.get("ok"))
            report["prestigeEverListed"] = ever

            # --- 소진 시각을 함부로 말하지 않는다 -------------------------------
            # 첫 표본부터 0 이면 '6초 안에 팔렸다' 고 말할 수 없다. 애초에 공급이
            # 없었는지, 우리가 늦어서 못 봤는지 구별이 안 된다. (09-08 사용자 지적)
            # 양수 -> 0 을 실제로 본 경우에만 그 사이를 소진 구간이라 부른다.
            pos = [r for r in rows if r.get("prListed") and not r.get("prSoldout")
                   and (r.get("prSeats") or 0) > 0]
            if not rows:
                verdict, window = "표본 없음", None
            elif not pos:
                first = rows[0]
                verdict = ("소진 시각 미확인 - 첫 표본(오픈+"
                           f"{first.get('sinceOpen')}s)부터 0석. "
                           "그 전에 팔렸는지, 애초에 안 열렸는지 구별 못 함")
                window = None
            elif report.get("goneSinceOpen") is not None:
                last_pos = pos[-1]
                verdict = "소진 관측됨"
                window = {"lastPositiveSinceOpen": last_pos.get("sinceOpen"),
                          "lastPositiveSeats": last_pos.get("prSeats"),
                          "firstZeroSinceOpen": report.get("goneSinceOpen")}
            else:
                verdict = f"관측 끝까지 남아 있었다 (최대 {report.get('maxPrestigeSeats')}석)"
                window = None
            report["depletion"] = verdict
            report["depletionWindow"] = window

            OUT.mkdir(exist_ok=True)
            (OUT / "watch_seats.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
            # 실행별로도 남긴다. 고정 이름 하나면 오후 리허설이 09:00 결과를 덮어쓴다.
            # (09-08 사용자 지적) 09:00 결과는 되돌릴 수 없는 자료다.
            runs = OUT / "runs"
            runs.mkdir(exist_ok=True)
            (runs / f"watch_{run_id}.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
            with (OUT / "seat_history.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "day": datetime.now(KST).strftime("%Y-%m-%d"),
                    "route": a.route, "origin": a.origin or "SEL",
                    "target": tgt.isoformat(), "screen": report.get("screen"),
                    "ok": report.get("ok"), "why": report.get("why"),
                    "maxPrestigeSeats": report.get("maxPrestigeSeats"),
                    "prestigeEverListed": ever,
                    "goneSinceOpen": report.get("goneSinceOpen"),
                    "samples": len(rows), "pressAt": report.get("pressSinceOpen"),
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # --- 준비: 목표 근처(가급적 D-1)의 조회 화면에 선다 ---
    if a.setup_at:
        wait_until(at(a.setup_at))
    # 브라우저가 없으면 띄운다. autorun 에는 이 장치가 있는데 계측기에는 없어서,
    # 크롬이 안 뜬 채로 셋업을 수십 번 되풀이하다 마감을 맞았다 (09-07: 69회, 09-08: 10회).
    # 없는 브라우저에 다시 붙어봐야 소용없다 - 띄우는 게 먼저다.
    if not browser_alive(a.port):
        log(f"포트 {a.port} 크롬이 없다 - 띄운다")
        shell = shutil.which("pwsh") or shutil.which("powershell") or (
            str(Path(os.environ.get("SystemRoot", r"C:\Windows"))
                / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"))
        try:
            subprocess.run([shell, "-NoProfile", "-File",
                            str(ROOT / "dev" / "browsers.ps1")],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
        except Exception as e:
            log(f"  띄우기 실패: {str(e)[:60]}")
        log(f"  포트 {a.port}: {'OK' if browser_alive(a.port) else '여전히 없음'}")

    # 달력에 선다.
    #
    # 조회 화면에 서서 날짜 띠를 누르는 방식은 못 쓴다: 조회 페이지를 새로고침하면
    # 세션(pageTicket)이 깨져 "정상적으로 처리되지 않았습니다" 로 뜨고 띠가 사라진다
    # (실측 2026-09-03). 새로고침 없이는 띠가 D 를 알 방법이 없다.
    #
    # 달력은 새로고침을 견딘다. 그리고 09:00 에 열리는 D 는 '가장 최신 오픈일' 이라
    # 달력 창 끝에 있어 찾을 수 있다 - 어제 9시 실전에서 이 경로로 08-28 을 정확히
    # 찾아냈다. (오늘 실패들은 최신일이 아닌 중간 날짜를 목표로 시험한 탓이었다.)
    cmd = [sys.executable, str(ROOT / "dev" / "setup.py"), a.route,
           "--port", str(a.port), "--date", stand.isoformat()]
    if a.origin:
        cmd += ["--from", a.origin]
    log(f"달력 준비 ({a.origin or 'SEL'} -> {a.route}, 목표 {tgt})")
    # 한 번 실패했다고 하루를 버리지 않는다. 발사 90초 전까지 다시 해본다.
    # (09-04: 새 크롬에서 1차 실패하고 그대로 죽어 09:00 을 통째로 놓쳤다)
    st = run_setup(cmd, open_at - timedelta(seconds=90), log)
    if not st.get("ok"):
        report["why"] = f"조회 화면 준비 실패: {st.get('why')}"
        log(report["why"]); save_report(); return 2
    log("조회 화면 준비됨")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.connect_over_cdp(f"http://localhost:{a.port}")
        ctx = b.contexts[0]
        js = USER.read_text(encoding="utf-8")
        ctx.add_init_script(js)
        pages = [p for p in ctx.pages if "koreanair" in p.url]
        if not pages:
            report["why"] = "대한항공 탭이 없다"; log(report["why"]); save_report(); return 3
        page = pages[-1]
        try: page.bring_to_front()
        except Exception: pass
        page.evaluate(js)

        # 예약 쪽이 끼어들지 않게 확실히 재운다. HUD 무장이 남아 있으면 새 문서마다
        # 스스로 발사해 예약 단계를 밟는다 - 읽기 전용 보장이 깨진다.
        page.evaluate("""() => {
          const R = window.KE_REC, H = window.KE_HUD;
          if (R) { R.pause('watch'); R.state.playing = false;
                   R.state.playAfterReload = false; R.state.allowPay = false; R.save(); }
          if (H) { H.state.armed = false; H.save(); }
        }""")

        # 달력에 서 있는지, 그리고 목표 근처인지 남겨둔다 (엉뚱한 달에 서 있어도
        # URL 만 보면 통과하므로, 나중에 결과를 의심할 근거를 기록해둔다).
        screen = None
        try: screen = page.evaluate(SCREEN)
        except Exception: pass
        report["screen"] = screen
        log(f"화면이 보고 있는 날짜: {screen}")

        # 매크로의 1~2단계(달력에서 D 클릭 -> 검색)만 재생한다. 예약 단계는 싣지 않는다.
        # D 를 못 찾으면 recorder 가 스스로 새로고침하며 기다린다(검증된 동작).
        page.evaluate("""({date}) => {
          const R = window.KE_REC, H = window.KE_HUD;
          R.loadBaked();
          R.state.steps = R.state.steps.slice(0, 2);
          R.state.expectDate = date;
          R.state.allowPay = false;
          R.state.byCause = {}; R.state.problem = false; R.state.openReloads = 0;
          R.reset(); R.save();
          H.state.startAt = 'calendar'; H.state.armed = false; H.save();
        }""", {"date": a.date})

        w = (fire_at - datetime.now(KST)).total_seconds()
        if w > 0:
            log(f"{w:.0f}초 대기 (발사 {fire_at.strftime('%H:%M:%S.%f')[:-3]})")
            wait_until(fire_at)

        # --- 1) 발사: 매크로가 달력에서 D 를 찾아 누르고 검색까지 간다 ---
        log(f"발사 - 달력에서 {a.date} 를 찾아 조회 화면으로")
        page.evaluate("() => window.KE_HUD.fire('watch')")
        reached = False
        while datetime.now(KST) < end_at and not reached:
            try:
                if not page.evaluate("() => !!window.KE_REC"):
                    page.evaluate(js)
                s = page.evaluate("""() => ({idx: KE_REC.state.idx,
                  playing: KE_REC.state.playing, msg: (KE_REC.state.message||'').slice(0,90),
                  reloads: KE_REC.state.openReloads})""")
            except Exception:
                time.sleep(0.2); continue
            if s["idx"] >= 2:
                reached = True
                secs = round((datetime.now(KST) - open_at).total_seconds(), 2)
                report["pressSinceOpen"] = secs
                report["openReloads"] = s.get("reloads")
                log(f"조회 화면 도달 (오픈+{secs:.2f}s, 재고침 {s.get('reloads')}회)")
                break
            if not s["playing"] and s["idx"] > 0:
                report["why"] = f"매크로가 멈춤: {s['msg']}"
                log(report["why"]); save_report(); b.close(); return 5
            time.sleep(0.2)
        if not reached:
            report["why"] = f"{a.date} 조회 화면에 도달하지 못함"
            log(report["why"]); save_report(); b.close(); return 5

        # --- 2) D 응답이 올 때까지 기다린다 (되쏘기는 그 뒤에) ---
        #
        # 여기서 도는 0.2초 반복은 **브라우저에 쌓인 응답을 읽는 것**이지 서버에
        # 새로 묻는 것이 아니다. 서버에 묻는 것은 화면 자신의 조회와 reAsk 뿐이다.
        # 그래서 '보낸 시각 / 도착 시각 / 우리가 읽은 시각' 을 나눠 남긴다 -
        # 첫 표본이 늦은 구간이 우리 쪽인지 서버 쪽인지 가르려면 이 셋이 필요하다.
        seen_id = 0
        got_d = False
        while datetime.now(KST) < end_at and not got_d:
            try:
                d = page.evaluate(READ, a.date)
            except Exception:
                d = None
            if d and (d.get("srcId") or 0) > 0 and (d.get("pr") or d.get("ey")):
                read_at = datetime.now(KST)
                sent_ms, arr_ms = d.get("srcSentAt") or 0, d.get("srcAt") or 0
                # 브라우저 시계(ms) 를 오픈 기준 초로 옮긴다. now 로 맞춘다.
                base = d.get("now") or arr_ms
                off = (read_at - open_at).total_seconds() - (base / 1000.0)
                report["first"] = {
                    "srcId": d.get("srcId"),
                    "status": d.get("srcStatus"),
                    "sentSinceOpen": round(sent_ms / 1000.0 + off, 2) if sent_ms else None,
                    "arrivedSinceOpen": round(arr_ms / 1000.0 + off, 2) if arr_ms else None,
                    "readSinceOpen": round((read_at - open_at).total_seconds(), 2),
                }
                f = report["first"]
                log(f"첫 목표일 응답:  보냄 오픈+{f['sentSinceOpen']}s"
                    f" -> 도착 오픈+{f['arrivedSinceOpen']}s"
                    f" -> 읽음 오픈+{f['readSinceOpen']}s  (응답 #{f['srcId']})")
                got_d = True
                break
            time.sleep(0.2)
        if not got_d:
            report["why"] = f"{a.date} 조회 응답이 오지 않았다"
            log(report["why"]); save_report(); b.close(); return 6

        # --- 3) 촘촘히 재기 ---
        gone_at = None
        best = None
        last_ask = 0.0
        while datetime.now(KST) < end_at:
            d = None
            try:
                if not page.evaluate("() => !!window.KE_PROBE"):
                    page.evaluate(js)
                d = page.evaluate(READ, a.date)
            except Exception:
                d = None
            # **새 응답일 때만** 표본으로 센다. 같은 응답을 다시 읽은 것은 표본이 아니다.
            # 예전엔 도착 시각(lastAt)으로 걸렀는데, 그것만으로는 '새 응답을 읽었다' 를
            # 보증하지 못한다. 응답마다 붙는 id 로 가른다. (09-08 사용자 지적)
            if d and (d.get("srcId") or 0) > seen_id and (d.get("pr") or d.get("ey")):
                seen_id = d["srcId"]
                pr, ey = d.get("pr") or {}, d.get("ey") or {}
                now = datetime.now(KST)
                secs = round((now - open_at).total_seconds(), 2)
                sent_ms, arr_ms = d.get("srcSentAt") or 0, d.get("srcAt") or 0
                base = d.get("now") or arr_ms
                off = secs - (base / 1000.0)
                rows.append({"at": now.isoformat(), "sinceOpen": secs,
                             "prSeats": pr.get("seats"), "prSoldout": pr.get("soldout"),
                             "prListed": pr.get("listed"), "eySeats": ey.get("seats"),
                             "keFlights": pr.get("keFlights"),
                             # 이 표본이 어느 응답에서 나왔는지. 눈으로 검증할 수 있게.
                             "srcId": d.get("srcId"), "srcStatus": d.get("srcStatus"),
                             "sentSinceOpen": round(sent_ms / 1000.0 + off, 2) if sent_ms else None,
                             "arrivedSinceOpen": round(arr_ms / 1000.0 + off, 2) if arr_ms else None,
                             "target": tgt.isoformat(),
                             "route": f"{a.origin or 'SEL'}->{a.route}",
                             # 편명·등급·좌석수 원본 (인증정보 없음)
                             "flights": pr.get("flights")})
                mark = ""
                if pr.get("listed") and not pr.get("soldout"):
                    # 0 도 유효한 값이다. truthiness 로 보면 0 이 falsy 라 1->0 을 놓친다.
                    s = pr.get("seats") or 0
                    best = s if best is None else max(best, s)
                    mark = "  ★있음"
                elif pr.get("soldout") and best is not None and not gone_at:
                    gone_at = now
                    mark = "  <- 방금 0 이 됨"
                log(f"오픈+{secs:6.2f}s  프레스티지 "
                    f"{'매진' if pr.get('soldout') else str(pr.get('seats')) + '석'}"
                    f"  (일반석 {ey.get('seats')}){mark}")
                if gone_at:
                    break
            since_open = (datetime.now(KST) - open_at).total_seconds()
            gap = a.fast_gap if since_open < a.fast_window else a.gap
            if (time.time() - last_ask) >= gap:
                last_ask = time.time()
                # 서버에 실제로 새로 묻는 곳은 여기뿐이다. 위의 읽기 반복은 이미 온
                # 응답을 볼 뿐이다. 언제 보냈는지 남겨 표본과 대조할 수 있게 한다.
                try:
                    r = page.evaluate("() => window.KE_PROBE && KE_PROBE.reAsk()")
                    asks.append({"sinceOpen": round(
                        (datetime.now(KST) - open_at).total_seconds(), 2),
                        "ok": bool(r and r.get("ok")), "why": (r or {}).get("why")})
                except Exception:
                    asks.append({"sinceOpen": round(
                        (datetime.now(KST) - open_at).total_seconds(), 2),
                        "ok": False, "why": "evaluate 실패"})
            time.sleep(0.15)

        report.update(ok=True, why="", maxPrestigeSeats=best,
                      goneAt=gone_at.isoformat() if gone_at else None,
                      goneSinceOpen=round((gone_at - open_at).total_seconds(), 2) if gone_at else None)
        save_report()
        ever = any(r.get("prListed") for r in rows)
        note = (f"프레스티지 최대 {best}석" if best else
                ("프레스티지 처음부터 매진(0석)" if ever else "프레스티지 정보 없음"))
        log(f"기록 {len(rows)}건 / {note}"
            + (f" / 오픈+{report['goneSinceOpen']}초에 0" if gone_at else ""))
        b.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(9)
