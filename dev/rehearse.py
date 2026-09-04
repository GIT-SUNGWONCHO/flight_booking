"""9시에 돌 것을, 9시와 같은 상태에서, 발사까지 통째로 돌려본다.

왜 있나 (2026-09-04 에 09:00 을 통째로 잃고 만들었다)
  그때까지의 '검증' 은 두 군데가 틀려 있었다.
    1) preflight(점검기)만 돌리고, 정작 발사하는 autorun/watch_seats 는
       끝까지 돌려본 적이 없었다. 관측자를 재고 주자를 안 쟀다.
    2) 이미 달궈진 크롬에서 쟀다. 실제 조건은 '부팅 직후 새 크롬' 이고,
       그 상태에서는 첫 셋업이 실패한다(FACTS 에 적혀 있던 사실이다).
  morning.ps1 -NoDaily 로 "18초 완주" 라고 보고했는데, 그 -NoDaily 가
  하필 오늘 실패한 부분을 건너뛰는 스위치였다.

그래서 이 스크립트는 타협하지 않는다
  - 크롬을 죽이고 새로 띄운다 (부팅 직후와 같은 차가운 상태)
  - 09:00 에 도는 것과 **같은 진입점**(daily.py)을 쓴다
  - 발사 시각만 '지금+N분' 으로 바꾼다. --dry 라 주문은 안 생긴다
  - 리포트를 읽어 실제로 발사했는지 확인한다. '오류 없음' 은 통과가 아니다

사용:
  .venv/Scripts/python.exe dev/rehearse.py                 (day.ps1 의 노선을 쓴다)
  .venv/Scripts/python.exe dev/rehearse.py --route ICN --from FCO --minutes 9
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dev-shots"
KST = timezone(timedelta(hours=9))


def log(m):
    print(f"[{datetime.now(KST).strftime('%H:%M:%S')}] {m}", flush=True)


def day_args() -> list[str]:
    """day.ps1 의 $DailyArgs 를 읽는다. 리허설과 실전이 다른 노선이면 의미가 없다."""
    try:
        txt = (ROOT / "dev" / "day.ps1").read_text(encoding="utf-8-sig")
        m = re.search(r"^\$DailyArgs\s*=\s*@\((.*?)\)", txt, re.M)
        return re.findall(r"'([^']*)'", m.group(1)) if m else []
    except Exception:
        return []


ROME_DAYS = {0, 2, 5}      # FACTS: 로마는 양방향 모두 월·수·토


def open_target(args: list[str]):
    """리허설이 쏠 출발일 = '이미 열려 있는' 가장 최신 날짜.

    08:20 에 도는 리허설은 오늘 09:00 에 열릴 날짜를 쓸 수 없다. 아직 없다.
    (09-04 아침에 이걸 놓칠 뻔했다 - 없는 날짜로 쏘면 리허설이 엉뚱하게 실패한다.)

    오픈 규칙: 출발일 = 실행일 + 360. 그러니 09:00 전이면 오늘+359 가 최신이고,
    09:00 이 지났으면 오늘+360 이 최신이다.

    로마(FCO)는 월·수·토만 뜨므로 그 날이 아니면 뒤로 물러선다. 운항 안 하는 날로
    쏘면 매크로가 정상적으로 실패하는데 리허설은 그걸 고장으로 읽는다.
    """
    now = datetime.now(KST)
    d = now.date() + timedelta(days=360 if now.hour >= 9 else 359)
    joined = " ".join(args).upper()
    if "FCO" in joined:
        for _ in range(7):
            if d.weekday() in ROME_DAYS:
                break
            d -= timedelta(days=1)
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=9, help="지금부터 몇 분 뒤에 발사할까")
    ap.add_argument("--route", default="")
    ap.add_argument("--from", dest="origin", default="")
    ap.add_argument("--keep-browsers", action="store_true",
                    help="크롬을 죽이지 않는다. 차가운 상태가 아니게 되므로 권하지 않는다")
    a = ap.parse_args()

    args = ["--route", a.route] + (["--from", a.origin] if a.origin else []) \
        if a.route else day_args()
    log(f"리허설 노선: {' '.join(args) or '(자동)'}")

    # --- 1) 차가운 크롬. 이게 이 스크립트의 존재 이유다 ---
    if a.keep_browsers:
        log("크롬 유지 (차가운 상태 아님 - 실전과 다르다)")
    else:
        log("크롬 죽이고 새로 띄운다 (부팅 직후와 같은 조건)")
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"],
                       capture_output=True, text=True)
        time.sleep(3)
    subprocess.run(["pwsh", "-NoProfile", "-File", str(ROOT / "dev" / "browsers.ps1")],
                   capture_output=True, text=True)

    # --- 2) 9시에 도는 것과 같은 진입점 ---
    for f in ("watch_seats.json", "autorun_report.json"):
        try: (OUT / f).unlink()
        except Exception: pass

    tgt = open_target(args)
    fire = datetime.now(KST) + timedelta(minutes=a.minutes)
    log(f"발사 예정 {fire.strftime('%H:%M:%S')} (지금+{a.minutes}분) / 출발일 {tgt} / dry")
    cmd = [sys.executable, str(ROOT / "dev" / "daily.py")] + args + \
          ["--at", f"+{a.minutes * 60}s", "--setup-at", "+5s",
           "--date", tgt.strftime("%m-%d")]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=(a.minutes + 8) * 60)
    print(r.stdout[-3000:])

    # --- 3) 리포트로 판정한다. 로그에 오류가 없다는 것은 통과가 아니다 ---
    fails, notes = [], []

    w = {}
    try: w = json.loads((OUT / "watch_seats.json").read_text(encoding="utf-8"))
    except Exception: fails.append("계측기 리포트가 없다 - 아예 안 돌았다")
    if w:
        if not w.get("ok") and not w.get("samples"):
            fails.append(f"계측기 실패: {w.get('why')}")
        elif not w.get("samples"):
            fails.append("계측기가 한 건도 측정하지 못했다")
        else:
            notes.append(f"계측기 {w.get('samples')}건 측정")

    m = {}
    try: m = json.loads((OUT / "autorun_report.json").read_text(encoding="utf-8"))
    except Exception: fails.append("매크로 리포트가 없다 - 아예 안 돌았다")
    if m:
        if (m.get("idx") or 0) < 2:
            fails.append(f"매크로가 발사하지 못했다 (idx={m.get('idx')}): {m.get('why')}")
        else:
            notes.append(f"매크로 {m.get('idx')}단계 도달, {m.get('seconds')}초 / {(m.get('why') or '')[:60]}")

    print()
    print("=" * 64)
    if fails:
        print("  리허설 실패 - 이 상태로 9시를 맞으면 진다")
        for f in fails: print("   X " + f)
        for n in notes: print("   . " + n)
        print("=" * 64)
        return 1
    print("  리허설 통과 (차가운 크롬 -> 로그인 -> 발사 -> 조회 화면)")
    for n in notes: print("   O " + n)
    # 통과를 '다 된다' 로 읽지 않게, 무엇을 안 봤는지 매번 같이 찍는다.
    print("  * 여기까지만 봤다. 실전과 다른 점:")
    print("    - 09:00 이 아니라 이미 열린 날짜로 쐈다 - '경쟁' 은 재지 못한다.")
    print("    - 그 날짜는 프레스티지가 늘 매진이라 매크로가 2단계에서 멈춘다.")
    print("      결제까지 가는 길(3~17단계)은 리허설이 보지 않는다. (BACKLOG 10)")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
