"""셋업을 '시간이 남는 한 다시 해보는' 방식으로 돌린다.

왜 있나 (2026-09-04 에 하루를 잃고 만들었다)
  FACTS: 크롬을 갓 띄운 직후 첫 셋업은 자주 실패하고 두 번째에 된다.
  이 사실을 알고도 재시도를 preflight.py(점검기)에만 넣었다. 정작 09:00 에
  발사하는 autorun.py 와 watch_seats.py 는 한 번 해보고 그냥 죽었다.
  09-04 아침, PC 재부팅으로 크롬이 새것이 되자 둘 다 08:40 에 포기했다.
  사람이 08:46 에 손으로 고쳐도 프로세스는 이미 없었다.

규칙
  - 한 번 실패했다고 하루를 버리지 않는다. 마감까지 남는 시간을 다 쓴다.
  - 실패 이유가 '로그인' 이면 사람이 필요하다. 더 해봐야 소용없으니 즉시 멈춘다.
  - 마감은 발사 시각보다 앞이어야 한다. 발사 직전까지 붙잡고 있으면 안 된다.
"""
from __future__ import annotations
import json, subprocess, sys
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def run_setup(cmd, deadline: datetime, log=print, gap: float = 3.0, min_tries: int = 2):
    """setup.py 를 마감까지 반복 실행한다. 마지막 결과 dict 를 돌려준다.

    cmd       setup.py 실행 인자 리스트
    deadline  이 시각을 넘기면 더 시도하지 않는다 (보통 발사 90초 전)
    min_tries 마감이 이미 지났어도 최소 이만큼은 해본다 (손으로 늦게 돌릴 때)
    """
    st, n = {}, 0
    while True:
        n += 1
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=420)
            tail = (r.stdout or "").strip().splitlines()
            st = json.loads(tail[-1]) if tail else {}
        except Exception as e:
            st = {"ok": False, "why": f"setup 실행 실패: {e}"[:90]}

        if st.get("ok"):
            if n > 1:
                log(f"  셋업 {n}회째에 성공")
            return st

        why = st.get("why") or "알 수 없음"
        if "로그인" in why:
            log(f"  셋업 실패({why}) - 사람이 로그인해야 한다. 재시도 안 함")
            return st

        left = (deadline - datetime.now(KST)).total_seconds()
        if left <= 0 and n >= min_tries:
            log(f"  셋업 {n}회 모두 실패({why}) - 마감")
            return st
        log(f"  셋업 {n}회 실패({why}) - 다시 (마감까지 {max(left,0):.0f}초)")
        if gap:
            import time
            time.sleep(gap)
