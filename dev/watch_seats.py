"""좌석 계측기: 09:00 부터 프레스티지 좌석수(KEBONUSPR)가 1->0 으로 바뀌는 시각을 잰다.

watch_open.py 는 '달력에 날짜가 뜨는 순간'(일반석 기준)만 본다. 프레스티지 매진은
달력에 없고 조회 응답의 commercialFareFamilyList 에만 있다(KEBONUSPR.soldout).
그래서 이 도구는 조회까지 가서 그 응답을 읽는다 - 예매는 하지 않는다(읽기 전용).

전용 탭 하나를 쓴다. 실전 매크로가 도는 탭과 겹치지 않게 --tab 을 다르게 준다.
매 주기: 새로고침 -> 목표 날짜 선택 -> 항공편 검색 -> 조회 응답에서 좌석수 읽기.

사용:
  .venv/bin/python dev/watch_seats.py --route CDG --day 08-27 \
      --setup-at 08:55 --date 2027-08-27 --from 08:59:55 --until 09:02

주의: 실전 09:00 이 와야만 진짜로 검증된다. 그 전까지는 '어제 열린 날짜'로 형태만
확인할 수 있다(그 날짜는 이미 매진이라 seatCount 변화는 안 보일 수 있다).
"""
from __future__ import annotations
import argparse, json, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER = ROOT / "userscript" / "ke-award-macro.user.js"
OUT = ROOT / "dev-shots"
CDP = "http://localhost:9222"
KST = timezone(timedelta(hours=9))


def log(m): print(f"  [{datetime.now(KST).strftime('%H:%M:%S.%f')[:-3]}] {m}", flush=True)


def wait_until(when: datetime) -> None:
    # 한 번의 긴 sleep 은 절전 중 멈춘다. 벽시계를 계속 다시 보며 짧게 나눠 기다린다.
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


# 한 주기: 목표 날짜를 골라 조회하고, 조회 응답에서 그 날 KEBONUSPR/일반석 좌석수를 읽는다.
# 유저스크립트(KE_UTIL/KE_PROBE)가 주입돼 있어야 한다.
READ = """(day) => {
  const P = window.KE_PROBE;
  if (!P || !P.keCabin) return { err: 'no probe' };
  const pr = P.keCabin('프레스티지', day);
  const ey = P.keCabin('일반석', day);
  return {
    answered: P.answered ? P.answered() : false,
    pr: pr, ey: ey,
    // 원본 타임라인의 그날 KEBONUSPR 최신값(시각 포함)
    tl: (P.seatTimeline() || []).filter(r => r.family === 'KEBONUSPR'
          && (!day || r.date.slice(4,8) === day.replace('-',''))).slice(-3)
  };
}"""

# 목표 날짜를 달력/날짜띠에서 찾아 누른 뒤, 항공편 검색을 누른다. 없으면 아직 안 열린 것.
PICK = """(day) => {
  const U = window.KE_UTIL;
  if (!U) return { err: 'no util' };
  let cell = U.findOpenDate ? U.findOpenDate('dep-fare-', day) : null;
  if (!cell && U.findStripDate) cell = U.findStripDate(day);
  if (!cell) return { picked: false, why: 'not-open' };
  U.fireClick(cell);
  return { picked: true };
}"""

SEARCH = """() => {
  const b = document.querySelector('#flight-widget__btn');
  if (b) { b.click(); return true; }
  const U = window.KE_UTIL;
  const c = U && U.candidates(document).find(e => U.visible(e) && /항공편\\s*검색/.test(U.label(e)));
  if (c) { U.fireClick(c); return true; }
  return false;
}"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", default="CDG")
    ap.add_argument("--day", required=True, help="지켜볼 날짜 MM-DD (예: 08-27)")
    ap.add_argument("--tab", type=int, default=5, help="쓸 탭 번호 (실전 탭과 겹치지 않게)")
    ap.add_argument("--setup-at", default="")
    ap.add_argument("--date", default="", help="셋업용 날짜 YYYY-MM-DD")
    ap.add_argument("--from", dest="start", default="+0s")
    ap.add_argument("--until", default="+180s")
    ap.add_argument("--gap", type=float, default=1.2, help="조회 사이 최소 간격(초, 서버 부담 하한)")
    a = ap.parse_args()

    t_start, t_end = at(a.start), at(a.until)
    rows = []

    if a.setup_at:
        wait_until(at(a.setup_at))
        cmd = [sys.executable, str(ROOT / "dev" / "setup.py"), a.route, "--tab", str(a.tab)]
        if a.date:
            cmd += ["--date", a.date]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        tail = (p.stdout or "").strip().splitlines()
        try: st = json.loads(tail[-1]) if tail else {}
        except Exception: st = {}
        log(f"감시탭 셋업: {'OK' if st.get('ok') else st.get('why')}")
        if not st.get("ok"):
            return 2

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.connect_over_cdp(CDP)
        ctx = b.contexts[0]
        js = USER.read_text(encoding="utf-8")
        cals = [p for p in ctx.pages if "koreanair" in p.url]
        if not cals:
            log("감시할 대한항공 탭이 없다"); return 3
        page = cals[-1]
        log(f"감시 탭: {page.url[:70]}")

        w = (t_start - datetime.now(KST)).total_seconds()
        if w > 0:
            log(f"감시 시작까지 {w:.0f}초 대기 ({t_start:%H:%M:%S})")
            wait_until(t_start)

        log(f"감시 시작 - {a.day} 프레스티지 좌석수를 {t_end:%H:%M:%S} 까지 지켜본다")
        gone_at = None
        seen_open = False
        while datetime.now(KST) < t_end:
            cyc = datetime.now(KST)
            try:
                page.reload(wait_until="domcontentloaded", timeout=40000)
            except Exception:
                pass
            try: page.evaluate(js)
            except Exception: pass
            # 목표 날짜 선택 -> 검색
            try:
                pk = page.evaluate(PICK, a.day)
                if pk.get("picked"):
                    page.wait_for_timeout(300)
                    page.evaluate(SEARCH)
            except Exception:
                pk = {"picked": False, "why": "err"}
            # 조회 응답을 기다렸다가 읽는다
            r = None
            for _ in range(50):
                page.wait_for_timeout(200)
                try: r = page.evaluate(READ, a.day)
                except Exception: continue
                if r and r.get("answered") and (r.get("pr") or r.get("ey")):
                    break
            r = r or {}
            stamp = datetime.now(KST)
            pr = r.get("pr") or {}
            ey = r.get("ey") or {}
            row = {"at": stamp.isoformat(),
                   "picked": pk.get("picked"), "why": pk.get("why"),
                   "prSeats": pr.get("seats"), "prSoldout": pr.get("soldout"),
                   "prListed": pr.get("listed"), "eySeats": ey.get("seats"),
                   "keFlights": pr.get("keFlights")}
            rows.append(row)
            if pr.get("listed") and not pr.get("soldout"):
                seen_open = True
                log(f"{a.day} 프레스티지 {pr.get('seats')}석  (일반석 {ey.get('seats')})  ★열려있음")
            elif pr.get("soldout"):
                log(f"{a.day} 프레스티지 매진  (일반석 {ey.get('seats')})"
                    + ("  <- 방금 닫힘" if seen_open and not gone_at else ""))
                if seen_open and not gone_at:
                    gone_at = stamp
                    log(f"★ 프레스티지가 {stamp:%H:%M:%S.%f} 에 0 이 됐다"[:60])
            else:
                log(f"{a.day} 아직 조회 안됨 (picked={pk.get('picked')}, why={pk.get('why')})")
            slept = (datetime.now(KST) - cyc).total_seconds()
            if slept < a.gap:
                time.sleep(a.gap - slept)

        OUT.mkdir(exist_ok=True)
        (OUT / "watch_seats.json").write_text(json.dumps(
            {"day": a.day, "route": a.route,
             "goneAt": gone_at.isoformat() if gone_at else None,
             "sawOpen": seen_open, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"기록 {len(rows)}건 -> dev-shots/watch_seats.json"
            + (f" / 프레스티지 0 전환 {gone_at:%H:%M:%S.%f}"[:40] if gone_at else ""))
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
