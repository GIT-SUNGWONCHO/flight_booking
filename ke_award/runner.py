"""Playwright 풀오토 러너.

흐름:
  1) 실제 Chrome 을 영구 프로필로 띄운다 (로그인 세션 재사용)
  2) 모든 프레임에 autoconfirm.js 를 주입 -> 안내사항 모달을 ~16ms 안에 통과
  3) NTP 로 보정한 시각에 정시 발사 -> 조회
  4) 매진/세션끊김이면 간격을 두고 재조회, 성공 텍스트가 뜨면 정지 + 알림
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from . import clock

ROOT = Path(__file__).resolve().parent
AUTOCONFIRM = ROOT / "autoconfirm.js"

# 재조회 간격 하한. 이보다 빠르게 두드리면 봇 탐지 대상이 되고,
# 실제로도 조회가 아니라 확인 모달 구간이 병목이라 이득이 없다.
MIN_RETRY_MS = 800


class Outcome(Enum):
    SUCCESS = "예약 완료 감지"
    SOLDOUT = "좌석 없음"
    NO_RESULT = "결과 파싱 실패"
    CLICKED = "좌석 클릭 후 진행 중"
    ERROR = "오류"


@dataclass
class Config:
    profile_dir: str = "profile"
    browser_channel: str = "chrome"
    headless: bool = False   # 예매 본 실행은 항상 False. 테스트에서만 True.
    search_url: str = ""
    login_url: str = "https://www.koreanair.com/kr/ko"
    logged_in_text: list[str] = field(default_factory=lambda: ["로그아웃", "마이페이지"])

    open_at: str = ""
    lead_ms: int = 150
    retry_ms: list[int] = field(default_factory=lambda: [1100, 1800])
    max_minutes: int = 25
    settle_ms: int = 2500          # 조회 후 결과가 그려질 때까지 기다리는 시간
    confirm_timeout_s: int = 35    # 좌석 클릭 후 성공 판정까지 대기

    seat_selector: str = ""
    seat_text: str = "프레스티지|Prestige"
    soldout_text: list[str] = field(default_factory=lambda: [
        "매진", "좌석이 없", "잔여 좌석 없", "조회된 여정이 없", "해당 조건",
    ])
    success_text: list[str] = field(default_factory=lambda: [
        "예약번호", "예약이 완료", "발권 완료", "여정 확인",
    ])
    session_text: list[str] = field(default_factory=lambda: [
        "세션이 종료", "세션이 만료", "시간이 초과", "처음부터 다시",
    ])
    auto_final: bool = False       # 최종 발권 버튼까지 자동으로 누를지

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        import yaml
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise SystemExit(f"config 에 알 수 없는 키: {sorted(unknown)}")
        cfg = cls(**data)
        lo, hi = cfg.retry_ms
        if lo < MIN_RETRY_MS:
            print(f"  [cfg] retry_ms 하한 적용: {lo} -> {MIN_RETRY_MS}ms")
            cfg.retry_ms = [MIN_RETRY_MS, max(hi, MIN_RETRY_MS + 300)]
        return cfg


def launch_with_retry(pw, attempts: int = 5, **kwargs):
    """Windows 는 브라우저 종료 직후에도 실행 파일/프로필을 잠시 잠근다.
    그 상태에서 다시 띄우면 spawn EBUSY 나 기동 타임아웃이 난다 -> 짧게 재시도."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return pw.chromium.launch_persistent_context(**kwargs)
        except Exception as exc:
            msg = str(exc)
            # "Target page, context or browser has been closed" 도 같은 증상이다.
            # 잠긴 프로필을 붙잡은 크롬이 기동 도중 죽으면 이 문구로 나온다.
            # 실측(2026-08-27)에서 이것 때문에 스위트가 통째로 EXIT=1 로 끝났다.
            if not any(k in msg for k in ("EBUSY", "ETXTBSY", "Timeout",
                                          "has been closed", "Target closed")):
                raise
            last = exc
            delay = 0.5 * (i + 1)
            print(f"  [browser] 기동 실패(잠금 추정) - {delay:.1f}s 후 재시도 {i + 1}/{attempts}")
            time.sleep(delay)
    raise last  # type: ignore[misc]


def _beep(times: int = 3) -> None:
    try:
        import winsound
        for _ in range(times):
            winsound.Beep(880, 180)
            time.sleep(0.06)
    except Exception:
        print("\a", end="", flush=True)


class Runner:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.offset = 0.0
        self._pw = None
        self.ctx = None
        self.page = None
        self.shots = Path("shots")
        self.shots.mkdir(exist_ok=True)

    # ---- 브라우저 ------------------------------------------------------
    def _spawn(self, attempts: int = 5, **kwargs):
        return launch_with_retry(self._pw, attempts=attempts, **kwargs)

    def launch(self) -> None:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        profile = Path(self.cfg.profile_dir).resolve()
        profile.mkdir(parents=True, exist_ok=True)

        kwargs = dict(
            user_data_dir=str(profile),
            headless=self.cfg.headless,   # 예매 본 실행은 반드시 눈으로 보면서
            viewport=None,
            # --start-maximized 는 headless 에서 무의미하고, Chrome 이 즉시 종료되는 원인이 된다
            args=[] if self.cfg.headless else ["--start-maximized"],
        )
        if self.cfg.browser_channel:
            try:
                # 채널 실행은 재시도를 짧게 - 실패하면 번들로 넘어가는 게 빠르다
                self.ctx = self._spawn(attempts=2, channel=self.cfg.browser_channel, **kwargs)
            except Exception as exc:
                head = str(exc).split("\n")[0]
                print(f"  [browser] '{self.cfg.browser_channel}' 실행 실패: {head}")
                print("            번들 Chromium 으로 대체합니다. "
                      "(계속 실패하면 config 의 browser_channel 을 \"\" 로 두세요)")
                self.ctx = self._spawn(**kwargs)
        else:
            self.ctx = self._spawn(**kwargs)

        # 모달 자동 통과 엔진을 모든 문서/프레임에 주입
        js = AUTOCONFIRM.read_text(encoding="utf-8")
        if self.cfg.auto_final:
            js += "\ntry{window.KE_AUTO.autoFinal=true;}catch(e){}\n"
        self.ctx.add_init_script(js)

        try:
            self.ctx.expose_function(
                "__keReport",
                lambda payload: print(f"    [auto] {payload}", flush=True),
            )
        except Exception:
            pass  # 이미 노출된 경우

        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.on("dialog", lambda d: d.accept())
        self.page.set_default_timeout(15000)

    def close(self) -> None:
        try:
            if self.ctx:
                self.ctx.close()
        finally:
            if self._pw:
                self._pw.stop()

    # ---- 상태 판정 -----------------------------------------------------
    def _text(self) -> str:
        try:
            return self.page.inner_text("body", timeout=3000)[:20000]
        except Exception:
            return ""

    @staticmethod
    def _hit(text: str, needles: list[str]) -> str | None:
        for n in needles:
            if n and n in text:
                return n
        return None

    def is_logged_in(self) -> bool:
        return self._hit(self._text(), self.cfg.logged_in_text) is not None

    def _find_seat(self):
        """예약 가능한 프레스티지 좌석 요소. 없으면 None."""
        if self.cfg.seat_selector:
            try:
                loc = self.page.locator(self.cfg.seat_selector).first
                if loc.count() and loc.is_visible():
                    return loc
            except Exception:
                pass
        if self.cfg.seat_text:
            try:
                loc = self.page.get_by_text(
                    re.compile(self.cfg.seat_text), exact=False
                ).locator(
                    "xpath=ancestor-or-self::*[self::button or @role='button'][1]"
                ).first
                if loc.count() and loc.is_visible():
                    return loc
            except Exception:
                pass
        return None

    # ---- 1회 시도 ------------------------------------------------------
    def attempt(self, n: int) -> Outcome:
        t0 = time.time()
        try:
            self.page.goto(self.cfg.search_url, wait_until="domcontentloaded", timeout=20000)
        except Exception as exc:
            print(f"  #{n} 이동 실패: {exc}")
            return Outcome.ERROR

        # 결과가 그려질 때까지 짧게 폴링 (고정 sleep 보다 빠르다)
        deadline = time.time() + self.cfg.settle_ms / 1000
        seat = None
        while time.time() < deadline:
            seat = self._find_seat()
            if seat:
                break
            txt = self._text()
            if self._hit(txt, self.cfg.soldout_text):
                break
            time.sleep(0.08)

        elapsed = (time.time() - t0) * 1000
        if not seat:
            txt = self._text()
            hit = self._hit(txt, self.cfg.soldout_text)
            print(f"  #{n} {elapsed:6.0f}ms  {'매진: ' + hit if hit else '좌석 없음/미파싱'}")
            return Outcome.SOLDOUT if hit else Outcome.NO_RESULT

        print(f"  #{n} {elapsed:6.0f}ms  좌석 발견 -> 클릭. 이후 모달은 자동 통과.")
        try:
            seat.click(timeout=5000)
        except Exception as exc:
            print(f"       클릭 실패: {exc}")
            return Outcome.ERROR

        # autoconfirm.js 가 모달을 처리하는 동안 결과만 지켜본다
        end = time.time() + self.cfg.confirm_timeout_s
        while time.time() < end:
            txt = self._text()
            if self._hit(txt, self.cfg.success_text):
                return Outcome.SUCCESS
            if self._hit(txt, self.cfg.session_text) or self._hit(txt, self.cfg.soldout_text):
                print("       세션 끊김/매진 - 재시도")
                return Outcome.SOLDOUT
            time.sleep(0.15)

        print("       판정 시간 초과 - 화면을 직접 확인하세요")
        self.page.screenshot(path=str(self.shots / f"timeout_{n}.png"))
        return Outcome.CLICKED

    # ---- 메인 ----------------------------------------------------------
    def run(self) -> Outcome:
        cfg = self.cfg
        if not cfg.search_url:
            raise SystemExit("config 의 search_url 이 비어 있습니다. 먼저 `probe` 로 URL 을 확보하세요.")

        self.offset = clock.sync()
        print(f"  현재 보정시각: {clock.now_kst(self.offset)}")

        if not self.is_logged_in():
            print("\n  로그인이 필요합니다. 브라우저에서 직접 로그인한 뒤 Enter.")
            self.page.goto(cfg.login_url)
            input("  로그인 완료 후 Enter > ")

        if cfg.open_at:
            target = clock.parse_kst(cfg.open_at) - cfg.lead_ms / 1000
            print(f"  발사 예정: {clock.fmt_kst(target)}  (오픈 {cfg.open_at} - 선발사 {cfg.lead_ms}ms)")
            # 예열: 미리 페이지를 한 번 띄워 DNS/TLS/JS 캐시를 데워둔다
            try:
                self.page.goto(cfg.search_url, wait_until="domcontentloaded", timeout=20000)
                print("  예열 완료")
            except Exception:
                pass
            clock.sleep_until(target, self.offset)
            print(f"\n  ★ 발사 {clock.now_kst(self.offset)}\n")

        stop = time.time() + cfg.max_minutes * 60
        n = 0
        while time.time() < stop:
            n += 1
            out = self.attempt(n)
            if out is Outcome.SUCCESS:
                shot = self.shots / f"success_{int(time.time())}.png"
                self.page.screenshot(path=str(shot), full_page=True)
                print(f"\n  ★★★ 예약 완료 화면 감지. 스크린샷: {shot}")
                print("  브라우저에서 예약번호를 직접 확인하세요. 자동화는 정지합니다.")
                _beep()
                return out
            if out is Outcome.CLICKED:
                print("  진행 중 상태로 판단 - 자동화를 멈춥니다. 직접 이어서 진행하세요.")
                _beep(2)
                return out
            time.sleep(random.uniform(cfg.retry_ms[0], cfg.retry_ms[1]) / 1000)

        print(f"\n  제한시간 {cfg.max_minutes}분 종료. 시도 {n}회.")
        return Outcome.SOLDOUT
