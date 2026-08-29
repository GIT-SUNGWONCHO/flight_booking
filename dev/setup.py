"""개발/실전 준비: 어떤 상태에서든 '마일리지 예매 달력 화면' 까지 알아서 데려간다.

사용:  .venv/bin/python dev/setup.py [도착지코드]
        예) dev/setup.py CDG      (생략하면 지금 설정된 도착지 그대로)

돌아오는 값(마지막 줄 JSON): {"ok":bool, "url":..., "why":...}
  ok=false 이고 why="로그인 필요" 면 사람이 로그인해야 한다 (비밀번호는 다루지 않는다).
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER = ROOT / "userscript" / "ke-award-macro.user.js"
CDP = "http://localhost:9222"
CAL = "/booking/calendar-fare-bonus"


def log(m): print(f"  {m}", flush=True)


def main() -> int:
    from playwright.sync_api import sync_playwright
    want = (sys.argv[1].upper() if len(sys.argv) > 1 else "")

    with sync_playwright() as pw:
        try:
            b = pw.chromium.connect_over_cdp(CDP)
        except Exception as e:
            print(json.dumps({"ok": False, "why": f"브라우저 없음 ({e})"[:80]}, ensure_ascii=False))
            return 1
        ctx = b.contexts[0]
        js = USER.read_text(encoding="utf-8")
        ctx.add_init_script(js)
        pages = [p for p in ctx.pages if "koreanair" in p.url]
        page = pages[0] if pages else ctx.new_page()

        def inject():
            try: page.evaluate(js)
            except Exception: pass

        # 이미 달력이면 끝 (도착지를 바꿔야 하면 그대로 진행한다)
        if CAL in page.url and not want:
            inject()
            log(f"이미 달력 화면: {page.url[:60]}")
            print(json.dumps({"ok": True, "url": page.url, "why": "이미 달력"}, ensure_ascii=False))
            return 0

        log("홈으로 이동")
        page.goto("https://www.koreanair.com/kr/ko", wait_until="load", timeout=60000)
        page.wait_for_timeout(11000)
        inject()

        # 로그인 확인 (헤더가 shadow DOM 안이라 candidates 로 봐야 한다)
        logged = page.evaluate("""() => {
          const U = window.KE_UTIL;
          return U.candidates(document).some(e => U.visible(e) && /로그아웃/.test(U.label(e)));
        }""")
        if not logged:
            log("로그인 안 됨")
            print(json.dumps({"ok": False, "url": page.url, "why": "로그인 필요"}, ensure_ascii=False))
            return 2
        log("로그인 확인됨")

        # 마일리지 예매로 전환 (span 이라 candidates 로 못 잡힌다 - 직접 훑는다)
        picked = page.evaluate("""() => {
          const U = window.KE_UTIL;
          let hit = null;
          const walk = (root, d) => {
            if (d > 12 || hit) return;
            let els; try { els = root.querySelectorAll('*'); } catch (e) { return; }
            for (const e of els) {
              if (hit) return;
              const t = (e.innerText||e.textContent||'').replace(/\\s+/g,' ').trim();
              if (t === '마일리지 예매' && e.children.length === 0 && U.visible(e)) { hit = e; return; }
              if (e.shadowRoot) walk(e.shadowRoot, d+1);
            }
          };
          walk(document, 0);
          if (!hit) return null;
          U.fireClick(hit);
          return true;
        }""")
        log(f"마일리지 예매 전환: {'성공' if picked else '못 찾음'}")
        page.wait_for_timeout(2500)

        if want:
            log(f"도착지 {want} 로 변경 시도")
            page.evaluate("""(code) => {
              const U = window.KE_UTIL;
              const btn = U.candidates(document).find(e => U.visible(e) && /^도착지/.test(U.label(e)));
              if (btn) U.fireClick(btn);
            }""", want)
            page.wait_for_timeout(2500)
            ok = page.evaluate("""(code) => {
              const U = window.KE_UTIL;
              const hit = U.candidates(document).find(e => U.visible(e) && U.label(e).indexOf(code) !== -1
                                                          && !/^도착지/.test(U.label(e)));
              if (hit) { U.fireClick(hit); return U.label(hit).slice(0,30); }
              return null;
            }""", want)
            log(f"  도착지 선택: {ok or '실패(수동 확인 필요)'}")
            page.wait_for_timeout(2000)

        log("항공편 검색")
        page.evaluate("""() => {
          const U = window.KE_UTIL;
          const b = U.candidates(document).filter(e => U.visible(e) && U.label(e) === '항공편 검색');
          if (b.length) U.fireClick(b[b.length-1]);
        }""")
        for _ in range(60):
            time.sleep(0.5)
            if CAL in page.url: break
        page.wait_for_timeout(6000)
        inject()

        ok = CAL in page.url
        log(("달력 도착: " if ok else "달력 실패: ") + page.url[:70])
        print(json.dumps({"ok": ok, "url": page.url,
                          "why": "" if ok else "검색이 달력으로 가지 않음"}, ensure_ascii=False))
        return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
