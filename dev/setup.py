"""개발/실전 준비: 어떤 상태에서든 '마일리지 예매 달력 화면' 까지 알아서 데려간다.

사용:  .venv/bin/python dev/setup.py [도착지코드] [--tab N] [--date YYYY-MM-DD]
        예) dev/setup.py CDG --date 2027-08-25
            dev/setup.py FCO --tab 1 --date 2027-08-25   (두 번째 탭을 그 노선으로)

--date 는 달력이 그 달을 보여주게 하려는 것이다. 달력은 고른 날 언저리를 보여주므로
목표일과 먼 날을 고르면 엉뚱한 달의 달력이 뜬다.

노선마다 탭을 따로 두면 한 브라우저로 여러 노선을 동시에 준비할 수 있다.

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


def goal_now(url: str, departure: bool) -> bool:
    return ("/booking/select-award-flight" in url) if departure else (CAL in url)


def main() -> int:
    from playwright.sync_api import sync_playwright
    args = sys.argv[1:]
    tab = 0
    if "--tab" in args:
        i = args.index("--tab")
        tab = int(args[i + 1])
        del args[i:i + 2]
    want_date = ""
    if "--date" in args:
        i = args.index("--date")
        want_date = args[i + 1]
        del args[i:i + 2]
    departure = "--departure" in args
    if departure:
        args.remove("--departure")
    want = (args[0].upper() if args else "")

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
        while len(pages) <= tab:            # 원하는 번째 탭이 없으면 만든다
            pages.append(ctx.new_page())
        page = pages[tab]
        try: page.bring_to_front()          # 뒤에 있으면 브라우저가 타이머를 늦춘다
        except Exception: pass

        def inject():
            try: page.evaluate(js)
            except Exception: pass

        # 이미 달력이면 끝 (도착지를 바꿔야 하면 그대로 진행한다)
        if goal_now(page.url, departure) and not want:
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

        # 위젯의 토글들은 클릭 가능 목록에 안 걸리는 SPAN/LABEL 이라 직접 훑는다.
        CLICK_TEXT = """(txt) => {
          const U = window.KE_UTIL;
          let hit = null;
          const walk = (root, d) => {
            if (d > 12 || hit) return;
            let els; try { els = root.querySelectorAll('*'); } catch (e) { return; }
            for (const e of els) {
              if (hit) return;
              const t = (e.innerText||e.textContent||'').replace(/\\s+/g,' ').trim();
              if (t === txt && e.children.length === 0 && U.visible(e)) { hit = e; return; }
              if (e.shadowRoot) walk(e.shadowRoot, d+1);
            }
          };
          walk(document, 0);
          if (!hit) return null;
          U.fireClick(hit);
          return true;
        }"""

        def click_text(txt):
            return page.evaluate(CLICK_TEXT, txt)

        log(f"마일리지 예매 전환: {'성공' if click_text('마일리지 예매') else '못 찾음'}")
        page.wait_for_timeout(2500)

        # 편도. 왕복이면 오는 날까지 넣어야 검색이 넘어가지 않는다
        # (실측: 왕복 상태에서 가는 날만 고르면 검색이 날짜 선택기만 다시 연다).
        log(f"편도 전환: {'성공' if click_text('편도') else '못 찾음'}")
        page.wait_for_timeout(2000)

        # 가까운 날짜 함께 조회 - 이게 달력 화면과 조회 화면을 가르는 스위치다.
        # 켜면 검색이 달력(calendar-fare-bonus)으로, 끄면 조회(select-award-flight)로 간다.
        # 우리는 달력에서 그날 새로 열린 날짜를 찾아야 하므로 켜야 한다.
        # 토글이라 이미 켜져 있는데 또 누르면 꺼진다 - 실측에서 그 바람에 조회 화면으로
        # 튕겼다. 상태를 보고 꺼져 있을 때만 누른다.
        # 조회 모드는 이 체크박스를 꺼야 검색이 조회 화면으로 간다 (켜면 달력으로 감).
        flex = page.evaluate("""(wantOn) => {
          const U = window.KE_UTIL;
          /* 체크박스 자체에는 글자가 없다. '가까운 날짜 함께 조회' 라고 쓰인 라벨을 먼저
           * 찾고, 거기서 for=/조상 순으로 실제 input 을 찾아간다. */
          let lab = null;
          const walk = (root, d) => {
            if (d > 12 || lab) return;
            let els; try { els = root.querySelectorAll('*'); } catch (e) { return; }
            for (const e of els) {
              if (lab) return;
              const t = (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim();
              if (t === '가까운 날짜 함께 조회' && e.children.length === 0 && U.visible(e)) { lab = e; return; }
              if (e.shadowRoot) walk(e.shadowRoot, d + 1);
            }
          };
          walk(document, 0);
          if (!lab) return 'notfound';

          /* 진짜 input 은 <kds-checkbox> 의 shadow root 안에 있다. 라이트 DOM 만 뒤지면
           * 못 찾아서 상태를 모른 채 누르게 되고, 이미 켜져 있으면 꺼버린다
           * (실측: 그 바람에 달력 대신 조회 화면으로 갔다). 조상들의 shadow 까지 본다. */
          let box = null, n = lab;
          for (let i = 0; i < 6 && !box && n; i++) {
            if (n.shadowRoot) {
              try { box = n.shadowRoot.querySelector('input[type=checkbox]'); } catch (e) {}
            }
            if (!box && n.querySelector) {
              try { box = n.querySelector('input[type=checkbox]'); } catch (e) {}
            }
            n = n.parentElement;
          }
          if (!box) return 'input못찾음';
          if (!!box.checked === !!wantOn) return 'already';
          U.fireClick(box);
          return box.checked ? 'on' : 'off';
        }""", not departure)
        log(f"가까운 날짜 함께 조회: {flex}")
        page.wait_for_timeout(1500)

        if want:
            log(f"도착지 {want} 로 변경 시도")
            # 도착지 버튼은 값이 있으면 "도착지 CDG 파리", 비어 있으면 "To 도착지" 로
            # 라벨이 바뀐다 (새 프로필은 늘 비어 있다). 라벨로 찾으면 빈 상태에서
            # 못 잡으므로, 상태와 무관한 클래스(-order3 = 도착지 칸)로 잡는다.
            page.evaluate("""(code) => {
              const U = window.KE_UTIL;
              const btn = U.candidates(document).find(e => U.visible(e)
                && /ui-fromto__button/.test((e.className||'').toString())
                && /-order3/.test((e.className||'').toString()));
              if (btn) U.fireClick(btn);
            }""", want)
            page.wait_for_timeout(2500)

            # 선택기는 '최근 검색' 만 보여준다. 처음 가는 도시는 목록에 없으므로
            # '도시, 공항' 검색칸에 코드를 쳐 넣어야 후보가 나온다.
            typed = page.evaluate("""(code) => {
              const U = window.KE_UTIL;
              let box = null;
              const walk = (root, d) => {
                if (d > 10 || box) return;
                let els; try { els = root.querySelectorAll('input[type=text]'); } catch (e) { els = []; }
                for (const e of els) {
                  if (U.visible(e) && /도시|공항/.test(e.placeholder || '')) { box = e; return; }
                }
                let all; try { all = root.querySelectorAll('*'); } catch (e) { return; }
                for (const e of all) { if (box) return; if (e.shadowRoot) walk(e.shadowRoot, d + 1); }
              };
              walk(document, 0);
              if (!box) return false;
              box.focus();
              box.value = code;
              box.dispatchEvent(new Event('input', { bubbles: true }));
              box.dispatchEvent(new Event('change', { bubbles: true }));
              return true;
            }""", want)
            if typed:
                log("  검색칸에 코드 입력")
                page.wait_for_timeout(2500)

            # 후보 고르기. 두 갈래를 다 본다.
            #  1) '최근 검색' 목록 - 클릭 가능한 요소라 candidates 로 잡힌다
            #  2) 검색 자동완성 - 항목이 ui-autocomplete__option-* 안의 SPAN/MARK/EM 이라
            #     클릭 가능 목록에 안 걸린다. 도시명과 코드가 서로 다른 요소로 쪼개져 있어
            #     (예: "밀라노/말펜사, 이탈리아" 와 <em>MXP</em>) 한 요소만 봐서는 못 찾는다.
            #     실측(2026-08-29): 이걸 안 봐서 밀라노가 "없다" 고 잘못 판단했다.
            #     -> 항목 행까지 올라가 행 전체 글자로 맞춘다.
            ok = page.evaluate("""(code) => {
              const U = window.KE_UTIL;
              const hit = U.candidates(document).find(e => U.visible(e) && U.label(e).indexOf(code) !== -1
                          && !/ui-fromto__button/.test((e.className||'').toString()));
              if (hit) { U.fireClick(hit); return U.label(hit).replace(/\\s+/g,' ').slice(0,34); }

              let row = null;
              const walk = (root, d) => {
                if (d > 12 || row) return;
                let els; try { els = root.querySelectorAll('*'); } catch (e) { return; }
                for (const e of els) {
                  if (row) return;
                  if (/ui-autocomplete__option/.test((e.className||'').toString())) {
                    let n = e;
                    for (let i = 0; i < 4 && n; i++) {
                      const t = (n.innerText || n.textContent || '').replace(/\\s+/g,' ');
                      if (t.indexOf(code) !== -1 && U.visible(n)) { row = n; return; }
                      n = n.parentElement;
                    }
                  }
                  if (e.shadowRoot) walk(e.shadowRoot, d + 1);
                }
              };
              walk(document, 0);
              if (!row) return null;
              U.fireClick(row);
              return (row.innerText||'').replace(/\\s+/g,' ').slice(0,34);
            }""", want)
            page.wait_for_timeout(2500)
            now = page.evaluate("""() => {
              const U = window.KE_UTIL;
              const b = U.candidates(document).find(e => U.visible(e)
                && /ui-fromto__button/.test((e.className||'').toString())
                && /-order3/.test((e.className||'').toString()));
              return b ? U.label(b).replace(/\\s+/g,' ').slice(0,30) : null;
            }""")
            log(f"  도착지 선택: {ok or '후보 못 찾음'} -> 현재 {now}")
            if not now or want not in now:
                # 엉뚱한 노선으로 조회하면 그때부터 전부 헛일이다. 여기서 끊는다.
                print(json.dumps({"ok": False, "url": page.url,
                                  "why": f"도착지를 {want} 로 못 바꿈 (현재: {now})"},
                                 ensure_ascii=False))
                return 6

        # 출발일. 아무 날짜나 고르면 안 된다 - 달력 화면은 고른 날 언저리를 보여주므로,
        # 2026년 9월을 고르면 2027년 8월 달력이 아니라 2026년 9월 달력이 뜬다.
        # 목표일이 있으면 그 달까지 이동해서 그 날을 고른다.
        DATEBTN = """() => {
          const U = window.KE_UTIL;
          const d = U.candidates(document).find(e => U.visible(e)
            && /ui-booking-tool__button -small/.test((e.className||'').toString()));
          return d ? U.label(d).replace(/\\s+/g,' ').slice(0,34) : null;
        }"""
        cur = page.evaluate(DATEBTN)
        need_date = bool(want_date) or (cur and "가는 날" in cur)
        if need_date:
            log(f"출발일 설정: 목표 {want_date or '(아무 날짜)'} / 현재 '{cur}'")
            page.evaluate("""() => {
              const U = window.KE_UTIL;
              const d = U.candidates(document).find(e => U.visible(e)
                && /ui-booking-tool__button -small/.test((e.className||'').toString()));
              if (d) U.fireClick(d);
            }""")
            page.wait_for_timeout(2500)

            if want_date:
                y, mo, dy = want_date.split("-")
                head = f"{int(y)}년 {int(mo)}월"
                # 화면에 보이는 달은 ui-datepicker__calendar-month-text 에 적혀 있다
                # (본문 전체에서 정규식으로 긁으면 다른 글자에 걸려 엉뚱한 달로 읽는다).
                MONTHS = """() => {
                  const U = window.KE_UTIL;
                  const out = [];
                  const walk = (root, d) => {
                    if (d > 10) return;
                    let els; try { els = root.querySelectorAll('*'); } catch (e) { return; }
                    for (const e of els) {
                      if (/ui-datepicker__calendar-month-text/.test((e.className||'').toString())
                          && U.visible(e)) out.push((e.innerText||'').replace(/\\s+/g,' ').trim());
                      if (e.shadowRoot) walk(e.shadowRoot, d + 1);
                    }
                  };
                  walk(document, 0);
                  return out;
                }"""
                moved, seen = 0, []
                for _ in range(24):          # 한 번에 한 달씩. 1년 반이면 18번이면 닿는다
                    seen = page.evaluate(MONTHS)
                    if head in seen:
                        break
                    if not page.evaluate("""() => {
                      const U = window.KE_UTIL;
                      const n = U.candidates(document).find(e => U.visible(e)
                        && /ui-datepicker__calendar-button/.test((e.className||'').toString())
                        && /-next/.test((e.className||'').toString()));
                      if (!n) return false;
                      U.fireClick(n); return true;
                    }"""):
                        break
                    moved += 1
                    page.wait_for_timeout(320)
                log(f"  달 이동 {moved}회 -> 보이는 달 {seen} (목표 {head})")

                got = page.evaluate("""({dy, head}) => {
                  const U = window.KE_UTIL;
                  const tds = U.candidates(document).filter(e => U.visible(e)
                    && /ui-datepicker__td/.test((e.className||'').toString())
                    && /-available/.test((e.className||'').toString()));
                  // 라벨이 "25 25일, 수요일" 처럼 시작하므로 앞 숫자로 그 날을 고른다
                  const hit = tds.find(e => new RegExp('^' + dy + '\\\\D').test(U.label(e).trim()));
                  if (!hit) return null;
                  U.fireClick(hit);
                  return U.label(hit).replace(/\\s+/g,' ').slice(0,30);
                }""", {"dy": str(int(dy)), "head": head})
                # 그 날이 아직 안 열렸을 수 있다 (09:00 에 열리는 날을 08:50 에 세울 때가
                # 그렇다). 여기서 필요한 것은 "달력이 그 달을 보여주는 것" 뿐이므로,
                # 같은 달의 고를 수 있는 마지막 날로 대신한다.
                if not got:
                    got = page.evaluate("""() => {
                      const U = window.KE_UTIL;
                      const tds = U.candidates(document).filter(e => U.visible(e)
                        && /ui-datepicker__td/.test((e.className||'').toString())
                        && /-available/.test((e.className||'').toString()));
                      if (!tds.length) return null;
                      const t = tds[tds.length - 1];
                      U.fireClick(t);
                      return U.label(t).replace(/\\s+/g,' ').slice(0,30);
                    }""")
                    log(f"  목표일이 아직 없어 그 달 마지막 날로 대신: {got or '가능한 날 없음'}")
                else:
                    log(f"  목표일 선택: {got}")
                if not got:
                    print(json.dumps({"ok": False, "url": page.url,
                                      "why": f"달력에서 {want_date} 달의 날짜를 못 고름"},
                                     ensure_ascii=False))
                    return 7
            else:
                got = page.evaluate("""() => {
                  const U = window.KE_UTIL;
                  const tds = U.candidates(document).filter(e => U.visible(e)
                    && /ui-datepicker__td/.test((e.className||'').toString())
                    && /-available/.test((e.className||'').toString()));
                  if (!tds.length) return null;
                  const t = tds[Math.min(5, tds.length - 1)];
                  U.fireClick(t);
                  return U.label(t).replace(/\\s+/g,' ').slice(0,26);
                }""")
                log(f"  날짜 선택: {got or '가능한 날짜 없음'}")
            page.wait_for_timeout(2500)

        log("항공편 검색")
        page.evaluate("""() => {
          const U = window.KE_UTIL;
          const b = U.candidates(document).filter(e => U.visible(e) && U.label(e) === '항공편 검색');
          if (b.length) U.fireClick(b[b.length-1]);
        }""")
        DEP = "/booking/select-award-flight"
        goal = DEP if departure else CAL
        for _ in range(60):
            time.sleep(0.5)
            if goal in page.url: break
        page.wait_for_timeout(6000)
        inject()

        ok = goal in page.url
        log((("조회" if departure else "달력") + (" 도착: " if ok else " 실패: ")) + page.url[:70])
        print(json.dumps({"ok": ok, "url": page.url,
                          "why": "" if ok else f"검색이 {'조회' if departure else '달력'} 화면으로 가지 않음"},
                         ensure_ascii=False))
        return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
