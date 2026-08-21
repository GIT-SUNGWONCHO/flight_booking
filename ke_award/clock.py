"""NTP 기반 시각 동기화.

Windows 로컬 시계는 기본적으로 수 초까지 틀어질 수 있다. 좌석 오픈 시각을
±50ms 로 맞추려면 서버 시각과의 오프셋을 직접 재야 한다.
외부 패키지 없이 socket 으로 SNTP 를 구현한다.
"""
from __future__ import annotations

import socket
import statistics
import struct
import time
from datetime import datetime, timedelta, timezone

NTP_EPOCH = 2208988800  # 1900-01-01 ~ 1970-01-01 (초)
KST = timezone(timedelta(hours=9))  # 한국은 서머타임 없음 -> 고정 +09:00

DEFAULT_SERVERS = (
    "time.bora.net",      # LG U+ (국내, 지연 낮음)
    "kr.pool.ntp.org",
    "time.google.com",
    "time.windows.com",
)


def _query(host: str, timeout: float = 2.0) -> tuple[float, float]:
    """(offset, round-trip delay) 를 초 단위로 반환."""
    pkt = b"\x1b" + 47 * b"\0"          # LI=0, VN=3, Mode=3(client)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        t1 = time.time()
        sock.sendto(pkt, (host, 123))
        data, _ = sock.recvfrom(1024)
        t4 = time.time()
    finally:
        sock.close()

    if len(data) < 48:
        raise ValueError(f"{host}: 응답이 짧음 ({len(data)}B)")

    def ts(off: int) -> float:
        sec, frac = struct.unpack("!II", data[off:off + 8])
        return (sec - NTP_EPOCH) + frac / 2 ** 32

    t2, t3 = ts(32), ts(40)             # 서버 수신 / 서버 송신
    offset = ((t2 - t1) + (t3 - t4)) / 2
    delay = (t4 - t1) - (t3 - t2)
    return offset, delay


def sync(servers=DEFAULT_SERVERS, samples: int = 3, verbose: bool = True) -> float:
    """서버시각 - 로컬시각 오프셋(초). 실패하면 0.0 (로컬 시계 사용)."""
    results: list[tuple[float, float, str]] = []
    for host in servers:
        for _ in range(samples):
            try:
                off, delay = _query(host)
                if delay >= 0:
                    results.append((delay, off, host))
            except Exception:
                break                   # 이 서버는 접근 불가 -> 다음 서버
            time.sleep(0.05)

    if not results:
        if verbose:
            print("  [clock] NTP 실패 - 로컬 시계를 그대로 사용합니다.")
            print("          PowerShell 관리자 권한으로 'w32tm /resync' 를 먼저 돌려보세요.")
        return 0.0

    results.sort()                      # 왕복지연이 짧은 표본일수록 정확
    best = results[: max(3, len(results) // 3)]
    offset = statistics.median(o for _, o, _ in best)
    if verbose:
        d, _, host = results[0]
        print(f"  [clock] offset {offset * 1000:+.1f}ms  (기준 {host}, 최소 RTT {d * 1000:.1f}ms, 표본 {len(results)})")
    return offset


def parse_kst(text: str) -> float:
    """'2026-08-22 10:00:00' (KST) -> epoch 초."""
    text = text.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=KST).timestamp()
        except ValueError:
            continue
    raise ValueError(f"시각 형식을 해석할 수 없음: {text!r} (예: 2026-08-22 10:00:00)")


def fmt_kst(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, KST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " KST"


def sleep_until(target_epoch: float, offset: float = 0.0, verbose: bool = True) -> None:
    """보정시각 기준으로 target 까지 대기. 마지막 구간은 busy-wait 로 정밀도 확보."""
    last_report = 0.0
    while True:
        remain = target_epoch - (time.time() + offset)
        if remain <= 0:
            return
        if remain > 0.3:
            if verbose and time.time() - last_report > 10:
                last_report = time.time()
                print(f"  [clock] T-{remain:,.1f}s", flush=True)
            time.sleep(min(remain - 0.15, 5.0))
        else:
            time.sleep(0.0002)          # 마지막 300ms: 스핀에 가깝게


def now_kst(offset: float = 0.0) -> str:
    return fmt_kst(time.time() + offset)
