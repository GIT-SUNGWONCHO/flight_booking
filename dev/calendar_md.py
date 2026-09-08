"""실전·연습 달력을 CALENDAR.md 로 뽑는다.

손으로 적으면 틀린다. 규칙 두 개(FACTS)에서 매번 계산한다.
  - 09:00 에 열리는 출발일 = 실행일 + 360
  - 로마(FCO)는 양방향 모두 월·수·토. 파리(CDG)는 매일.

    .venv/Scripts/python.exe dev/calendar_md.py          (CALENDAR.md 를 다시 쓴다)
    .venv/Scripts/python.exe dev/calendar_md.py --days 30
"""
from __future__ import annotations
import argparse, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OFFSET = 360
ROME_DAYS = {0, 2, 5}          # 월·수·토
WD = "월화수목금토일"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ke_setup import TARGETS      # 실전 목표는 ke_setup 한 곳에만 둔다


def where(run_day: date) -> str:
    """그날 누가 돌리나.

    이 윈도우 PC 는 평일에만 켜 둔다. 토·일은 사용자가 맥으로 들어가야 하고,
    못 들어가면 그날은 못 잰다. (09-08 사용자 확인)
    """
    return "이 PC (자동)" if run_day.weekday() < 5 else "**맥 (사람이 켜야 함)**"


def next_target(run_day: date):
    """그날 기준으로 **다음에 올 실전**. 연습은 그 노선을 밟는다."""
    for d in sorted(TARGETS):
        if d >= run_day:
            return d, TARGETS[d]
    return None, None


def plan(run_day: date):
    """그날 09:00 에 무엇을 할지. (열리는날, 로마여부, 노선표기, 비고)

    연습은 **다음 실전과 같은 노선**으로 한다. 로마가 뜨는 날이라고 로마를 잡으면,
    09-14 인천→파리 실전을 앞두고 엉뚱한 노선을 연습하게 된다. (09-08 사용자 지적)
    """
    opens = run_day + timedelta(days=OFFSET)
    rome = opens.weekday() in ROME_DAYS

    if run_day in TARGETS:
        o, r, label = TARGETS[run_day]
        ok = rome if "FCO" in (o, r) else True
        note = "**실전**" if ok else "**실전인데 그날 로마가 안 뜬다 - 확인 필요**"
        return opens, rome, label, note

    tgt_day, tgt = next_target(run_day)
    if not tgt:
        return opens, rome, "파리 → 인천", "연습 (목표 없음 - 유럽발 유지)"

    o, r, label = tgt
    # 로마 노선인데 그날 로마가 안 뜨면 그 노선을 못 밟는다.
    # 방향(유럽발)이라도 같게 파리로 대신한다.
    if "FCO" in (o, r) and not rome:
        return opens, rome, "파리 → 인천", f"연습 (대체 - {tgt_day.strftime('%m/%d')} 로마 실전 대비, 그날 로마 없음)"
    return opens, rome, label, f"연습 ({tgt_day.strftime('%m/%d')} 실전과 같은 노선)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=24)
    ap.add_argument("--from", dest="start", default="", help="YYYY-MM-DD (기본: 오늘)")
    a = ap.parse_args()

    today = (date.fromisoformat(a.start) if a.start else datetime.now(KST).date())

    rows = []
    for i in range(a.days):
        d = today + timedelta(days=i)
        opens, rome, label, note = plan(d)
        rows.append((d, opens, rome, label, note))

    out = []
    out.append("# 실전·연습 달력")
    out.append("")
    out.append(f"뽑은 날: {today}  ·  `dev/calendar_md.py` 로 다시 뽑는다. 손으로 고치지 말 것.")
    out.append("")
    out.append("규칙 두 개에서 계산한다 (FACTS.md):")
    out.append("- **09:00 에 열리는 출발일 = 실행일 + 360일**")
    out.append("- **로마(FCO)는 양방향 모두 월·수·토.** 파리(CDG)는 매일.")
    out.append("")
    out.append("'로마' 칸은 **그날 열리는 출발일에 로마 노선이 뜨는가**다. 파리는 매일 뜨므로")
    out.append("파리 연습일에는 이 칸이 X 여도 상관없다.")
    out.append("")
    out.append("**마지막 실전(09-25)까지는 매일 돌린다.** 토·일은 이 PC 가 꺼져 있어")
    out.append("사용자가 맥으로 들어가야 하고, 못 들어가면 그날은 못 잰다.")
    out.append("")
    out.append("| 실행일 | 09:00 에 열리는 출발일 | 로마 | 그날 할 것 | 어디서 | 비고 |")
    out.append("|---|---|---|---|---|---|")
    for d, opens, rome, label, note in rows:
        dd = f"{d}({WD[d.weekday()]})"
        oo = f"{opens}({WD[opens.weekday()]})"
        if d in TARGETS:
            dd = f"**{dd}**"
        out.append(f"| {dd} | {oo} | {'O' if rome else 'X'} | {label} | {where(d)} | {note} |")

    out.append("")
    out.append("## 실전 목표 세 개")
    out.append("")
    for d in sorted(TARGETS):
        o, r, label = TARGETS[d]
        opens = d + timedelta(days=OFFSET)
        rome = opens.weekday() in ROME_DAYS
        left = (d - today).days
        when = "지남" if left < 0 else ("오늘" if left == 0 else f"{left}일 뒤")
        out.append(f"- **{d}({WD[d.weekday()]}) {label}** — 출발일 "
                   f"{opens}({WD[opens.weekday()]}), 로마운항 {'O' if rome else 'X'} · {when}")
    out.append("")
    out.append("## 그날 무엇으로 도는가")
    out.append("")
    out.append("노선은 `dev/day.ps1` 의 `$DailyArgs` 한 줄에서만 정한다. 이 표대로 자동으로")
    out.append("바뀌지 **않는다** — 실전 전날 손으로 맞춰야 한다.")
    out.append("")
    out.append("    연습:  daily.py --mode dry    7단계 앞에서 정지. 주문·hold 안 생김")
    out.append("    실전:  daily.py --mode hold   7단계까지. 좌석을 잡고 멈춤 (결제는 사람이)")
    out.append("")
    out.append("스케줄: `ke_morning` 08:20 (리허설 → 실전셋팅 → 08:50 확인 → 09:00 발사),")
    out.append("`ke_precheck` 전날 16:00 (리허설).")
    out.append("")

    p = ROOT / "CALENDAR.md"
    p.write_text("\n".join(out), encoding="utf-8")
    print(f"{p} 에 {len(rows)}일치 저장")
    for d, opens, rome, label, note in rows[:8]:
        print(f"  {d}({WD[d.weekday()]}) -> {opens}({WD[opens.weekday()]}) "
              f"로마{'O' if rome else 'X'}  {label}  {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
