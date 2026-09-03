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
    # 붙을 크롬. 계측기는 2번 크롬(9223)을 쓴다 - 실전 예약(9222)과 프로필을 나눠야
    # 쿠키·localStorage 가 안 섞이고 9시에 둘을 동시에 돌릴 수 있다.
    cdp = CDP
    if "--port" in args:
        i = args.index("--port")
        cdp = f"http://localhost:{int(args[i + 1])}"
        del args[i:i + 2]
    # 출발지. 유럽발(로마->인천 등) 목표가 생겨서 필요해졌다 - 지금까지는 늘 SEL 이었다.
    want_from = ""
    if "--from" in args:
        i = args.index("--from")
        want_from = args[i + 1].upper()
        del args[i:i + 2]
    departure = "--departure" in args
    if departure:
        args.remove("--departure")
    want = (args[0].upper() if args else "")

    with sync_playwright() as pw:
        try:
            b = pw.chromium.connect_over_cdp(cdp)
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

        # 로그인 확인. 헤더가 shadow DOM 안이고 늦게 그려져서, 한 번만 보고 판단하면
        # 멀쩡히 로그인돼 있는데도 '로그인 필요' 로 읽는다 (실측 2026-08-30 01:25:
        # 같은 세션을 두 번 봤는데 한 번은 로그아웃, 한 번은 로그인으로 나왔다).
        # 09:00 에 이걸로 중단되면 전부 헛일이므로, 나타날 때까지 기다렸다 판단한다.
        logged = False
        for _ in range(25):
            st = page.evaluate("""() => {
              const U = window.KE_UTIL;
              const c = U.candidates(document).filter(e => U.visible(e));
              return {out: c.some(e => /로그아웃/.test(U.label(e))),
                      inb: c.some(e => /^로그인$/.test(U.label(e)))};
            }""")
            if st["out"]:
                logged = True
                break
            page.wait_for_timeout(1000)
            inject()
        if not logged:
            # 세션이 만료됐으면 네이버 연동으로 다시 들어간다. 네이버 쪽 세션이 살아
            # 있으면 버튼 두 번으로 끝난다 - 비밀번호를 치는 게 아니다.
            # 비밀번호 입력칸이 뜨면 거기서 멈춘다. 그건 사람이 해야 한다.
            log("로그아웃 상태 - 네이버 연동으로 다시 로그인 시도")
            page.evaluate("""() => {
              const U = window.KE_UTIL;
              const b = U.candidates(document).find(e => U.visible(e) && /^로그인$/.test(U.label(e)));
              if (b) U.fireClick(b);
            }""")
            page.wait_for_timeout(6000)
            inject()
            page.evaluate("""() => {
              const U = window.KE_UTIL;
              const b = U.candidates(document).find(e => U.visible(e) && /네이버|NAVER/i.test(U.label(e)));
              if (b) U.fireClick(b);
            }""")
            for _ in range(16):
                page.wait_for_timeout(2500)
                try:
                    # 대한항공 /login 페이지에도 자체 아이디·비밀번호 칸이 있다.
                    # 그걸 보고 멈추면 네이버로 넘어가기도 전에 포기한다 (실측:
                    # 그래서 자동 로그인이 실패했다). 네이버 화면에서 물을 때만 멈춘다.
                    if "naver" in page.url and page.evaluate("""() => {
                      const es = document.querySelectorAll('input[type=password]');
                      for (const e of es) { const r = e.getBoundingClientRect();
                        if (r.width > 1 && r.height > 1) return true; }
                      return false;
                    }"""):
                        log("네이버가 비밀번호를 요구합니다 - 사람이 로그인해야 함")
                        break
                    if "koreanair" in page.url:
                        inject()
                        if page.evaluate("""() => {
                          const U = window.KE_UTIL;
                          return U.candidates(document).some(e => U.visible(e) && /로그아웃/.test(U.label(e)));
                        }"""):
                            logged = True
                            log("네이버 연동 로그인 성공")
                            break
                except Exception:
                    pass
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

        # 출발지/도착지 공용. 유럽발 목표(로마->인천)가 생겨 출발지도 바꿔야 한다.
        # order1 = 출발지, order3 = 도착지. 값이 있으면 "도착지 CDG 파리", 비어 있으면
        # "To 도착지" 로 라벨이 바뀌므로 라벨이 아니라 order 클래스로 잡는다.
        def set_fromto(order, code, name):
            log(f"{name} {code} 로 변경 시도")
            page.evaluate("""(o) => {
              const U = window.KE_UTIL;
              const btn = U.candidates(document).find(e => U.visible(e)
                && /ui-fromto__button/.test((e.className||'').toString())
                && new RegExp('-order' + o + '(\\\\s|$)').test((e.className||'').toString()));
              if (btn) U.fireClick(btn);
            }""", order)
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
            }""", code)
            if typed:
                log("  검색칸에 코드 입력")
                page.wait_for_timeout(2500)

            # 후보 고르기. 자동완성 항목을 '먼저' 본다.
            #   실측(2026-09-02): 코드가 든 아무 요소나 고르면 "여정 1 출발지 SEL -
            #   도착지 FCO 로마" 같은 여정 요약을 눌러버려 출발지가 안 바뀌었다.
            #   자동완성 항목은 도시명과 코드가 다른 요소로 쪼개져 있어(예: <em>FCO</em>)
            #   항목 행까지 올라가 행 전체 글자로 맞춘다.
            #   자동완성이 없으면 최근검색 목록으로 떨어진다 - 둘 다 없으면 아래에서 멈춘다.
            ok = page.evaluate("""(code) => {
              const U = window.KE_UTIL;
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
              if (row) { U.fireClick(row); return (row.innerText||'').replace(/\\s+/g,' ').slice(0,34); }

              const hit = U.candidates(document).find(e => U.visible(e)
                && U.label(e).indexOf(code) !== -1
                && !/ui-fromto__button/.test((e.className||'').toString())
                && !/여정/.test(U.label(e)));
              if (hit) { U.fireClick(hit); return U.label(hit).replace(/\\s+/g,' ').slice(0,34); }
              return null;
            }""", code)
            page.wait_for_timeout(2500)
            now = page.evaluate("""(o) => {
              const U = window.KE_UTIL;
              const b = U.candidates(document).find(e => U.visible(e)
                && /ui-fromto__button/.test((e.className||'').toString())
                && new RegExp('-order' + o + '(\\\\s|$)').test((e.className||'').toString()));
              return b ? U.label(b).replace(/\\s+/g,' ').slice(0,30) : null;
            }""", order)
            log(f"  {name} 선택: {ok or '후보 못 찾음'} -> 현재 {now}")
            # 진짜 안전장치: 눌렀다고 믿지 않고 칸이 실제로 바뀌었는지 본다.
            return (bool(now) and code in now), now

        def read_fromto(order):
            return page.evaluate("""(o) => {
              const U = window.KE_UTIL;
              const b = U.candidates(document).find(e => U.visible(e)
                && /ui-fromto__button/.test((e.className||'').toString())
                && new RegExp('-order' + o + '(\\\\s|$)').test((e.className||'').toString()));
              return b ? U.label(b).replace(/\\s+/g,' ').slice(0,30) : null;
            }""", order)

        # 출발지를 먼저 바꾼다 (도착지보다 먼저여야 목록이 노선에 맞게 나온다).
        #
        # --from 이 없으면 SEL 이 기본이다. 그냥 두면 안 된다 - 유럽발(로마->인천)을 한 번
        # 쓰고 나면 위젯에 FCO 가 남아, 다음 실행이 조용히 'FCO -> CDG' 같은 엉뚱한 노선으로
        # 돈다. 지금 값이 이미 맞으면 건드리지 않는다(불필요한 8초를 아낀다).
        target_from = want_from or "SEL"
        cur_from = read_fromto(1)
        if not cur_from or target_from not in cur_from:
            log(f"출발지 정정 필요: 현재 '{cur_from}' -> {target_from}")
            good, now = set_fromto(1, target_from, "출발지")
            if not good:
                print(json.dumps({"ok": False, "url": page.url,
                                  "why": f"출발지를 {target_from} 로 못 바꿈 (현재: {now})"},
                                 ensure_ascii=False))
                return 6
        else:
            log(f"출발지 그대로: {cur_from}")

        if want:
            good, now = set_fromto(3, want, "도착지")
            if not good:
                print(json.dumps({"ok": False, "url": page.url,
                                  "why": f"도착지를 {want} 로 못 바꿈 (현재: {now})"},
                                 ensure_ascii=False))
                return 6

        # 출발일. 아무 날짜나 고르면 안 된다 - 달력 화면은 고른 날 언저리를 보여주므로,
        # 2026년 9월을 고르면 2027년 8월 달력이 아니라 2026년 9월 달력이 뜬다.
        # 목표일이 있으면 그 달까지 이동해서 그 날을 고른다.
        # 날짜 버튼 클래스에 -small / -large 가 창 크기에 따라 다르게 붙는다.
        # 크기에 기대면 어떤 창에서는 아예 못 찾는다 (실측: -small 로만 찾다가
        # -large 로 렌더된 창에서 날짜를 못 골라 준비가 통째로 실패했다).
        # 크기 표시는 무시하고 '출발일' 이라고 쓰인 버튼을 찾는다.
        DATEBTN = """() => {
          const U = window.KE_UTIL;
          const d = U.candidates(document).find(e => U.visible(e)
            && /ui-booking-tool__button/.test((e.className||'').toString())
            && /^출발일/.test(U.label(e)));
          return d ? U.label(d).replace(/\\s+/g,' ').slice(0,34) : null;
        }"""
        cur = page.evaluate(DATEBTN)
        need_date = bool(want_date) or (cur and "가는 날" in cur)
        if need_date:
            log(f"출발일 설정: 목표 {want_date or '(아무 날짜)'} / 현재 '{cur}'")
            page.evaluate("""() => {
              const U = window.KE_UTIL;
              const d = U.candidates(document).find(e => U.visible(e)
                && /ui-booking-tool__button/.test((e.className||'').toString())
                && /^출발일/.test(U.label(e)));
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

                # 달력은 두 달을 나란히 그린다. 보이는 날짜 전체에서 일자만 맞춰 첫 일치를
                # 고르면 '왼쪽(이른 달)' 의 같은 일자를 집는다 - 2027-08-28(토) 을 달라고 했는데
                # 2027-07-28(수) 을 골랐다(실측 2026-09-03). 그러면 그 날짜로 조회가 나가
                # 운항일이 아니면 "정상적으로 처리되지 않았습니다" 로 끝난다.
                # util.findPickerDate 는 #month{YYYYMM} 안에서만 찾으므로 달을 안 넘는다.
                got = page.evaluate("""({mmdd, year}) => {
                  const U = window.KE_UTIL;
                  const r = U.findPickerDate ? U.findPickerDate(mmdd, year) : null;
                  if (!r || !r.el || !r.available) return null;
                  U.fireClick(r.el);
                  return U.label(r.el).replace(/\\s+/g,' ').slice(0,30);
                }""", {"mmdd": f"{int(mo):02d}-{int(dy):02d}", "year": int(y)})
                # 그 날이 아직 안 열렸을 수 있다 (09:00 에 열리는 날을 08:50 에 세울 때가
                # 그렇다). 여기서 필요한 것은 "달력이 그 달을 보여주는 것" 뿐이므로,
                # 같은 달의 고를 수 있는 마지막 날로 대신한다.
                if not got:
                    # 폴백도 '그 달 안' 에서 고른다. 전체에서 마지막을 집으면 오른쪽 달의
                    # 엉뚱한 날로 새거나, 운항하지 않는 요일을 골라 조회가 실패한다.
                    got = page.evaluate("""({year, mo}) => {
                      const U = window.KE_UTIL;
                      const box = document.getElementById('month' + year + mo);
                      if (!box) return null;
                      let tds; try { tds = box.querySelectorAll('td'); } catch (e) { return null; }
                      const ok = [...tds].filter(t => U.visible(t)
                        && (t.className||'').toString().indexOf('-available') !== -1);
                      if (!ok.length) return null;
                      const t = ok[ok.length - 1];
                      U.fireClick(t);
                      return U.label(t).replace(/\\s+/g,' ').slice(0,30);
                    }""", {"year": int(y), "mo": f"{int(mo):02d}"})
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
        # 마일리지 예매는 검색하면 '항상' 달력으로 간다. 조회 화면은 달력에서 날짜를
        # 눌러야 도달한다 (실측 2026-09-03: '가까운 날짜 함께 조회' 를 꺼도 달력으로 갔다.
        # 그 체크박스는 달력/조회를 가르는 스위치가 아니었다).
        # 그래서 조회 화면이 목표면, 달력에 도착한 뒤 목표 날짜를 눌러 한 걸음 더 간다.
        for _ in range(60):
            time.sleep(0.5)
            if CAL in page.url or DEP in page.url: break
        page.wait_for_timeout(6000)
        inject()

        if departure and DEP not in page.url and CAL in page.url:
            log("조회 화면으로: 달력에서 날짜를 누른다")
            # 목표일이 달력 창에 없으면 '가장 최신 오픈일' 로 대신 들어간다.
            # 조회 화면은 선택일 ±3일 날짜 띠를 들고 있으므로, 목표 근처에만 서면
            # 띠에서 목표일을 집을 수 있다. 못 들어가는 것보다 훨씬 낫다.
            picked = page.evaluate("""(want) => {
              const U = window.KE_UTIL;
              let cell = want ? U.findOpenDate('dep-fare-', want) : null;
              let how = 'want';
              if (!cell) { cell = U.findOpenDate('dep-fare-', ''); how = 'latest'; }
              if (!cell) return null;
              const lb = U.label(cell).replace(/\\s+/g, ' ').slice(0, 30);
              U.fireClick(cell);
              return how + ': ' + lb;
            }""", want_date[5:] if want_date else "")
            log(f"  누른 날짜: {picked or '못 찾음'}")
            page.wait_for_timeout(2500)
            # 날짜만 눌러서는 화면이 안 넘어간다. 달력 아래쪽 [검색] 을 눌러야 조회 화면으로
            # 간다. 위젯의 [항공편 검색] 과 다른 버튼이다 - 달력에는 그 라벨이 없어서
            # 그걸 찾다가 계속 실패했다(실측). 녹화된 2단계도 라벨이 '검색' 이다.
            inject()
            clicked = page.evaluate("""() => {
              const U = window.KE_UTIL;
              const pick = (lb) => U.candidates(document)
                .filter(e => U.visible(e) && U.label(e).replace(/\\s+/g,' ').trim() === lb);
              let b = pick('검색');
              if (!b.length) b = pick('항공편 검색');
              if (!b.length) return null;
              U.fireClick(b[b.length - 1]);
              return U.label(b[b.length - 1]).slice(0, 20);
            }""")
            log(f"  검색 버튼: {clicked or '못 찾음'}")
            for _ in range(40):
                time.sleep(0.5)
                if DEP in page.url: break
            page.wait_for_timeout(4000)
            inject()

        goal = DEP if departure else CAL
        ok = goal in page.url
        log((("조회" if departure else "달력") + (" 도착: " if ok else " 실패: ")) + page.url[:70])
        print(json.dumps({"ok": ok, "url": page.url,
                          "why": "" if ok else f"검색이 {'조회' if departure else '달력'} 화면으로 가지 않음"},
                         ensure_ascii=False))
        return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
