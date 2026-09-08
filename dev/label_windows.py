"""크롬 창 제목에 말머리를 붙인다 - `[Claude · 9223] 가는 편 항공편 선택 ...`

왜 있나
  이 PC 에는 크롬이 여럿 떠 있다 - 사용자 개인 창, 다른 작업자의 워크트리(9232/9233),
  그리고 우리 둘(9222/9223). 창만 봐서는 어느 것이 무엇인지 모른다.
  프로필 칩(툴바 아바타)에도 이름을 넣어 뒀지만 눌러야 보인다. 제목이 제일 잘 보인다.

왜 이렇게 하나
  크롬 창 제목은 **탭 제목**이라 밖에서 못 고친다. 페이지 안에서 document.title 을
  바꿔야 하고, KE 는 화면을 옮길 때마다 제목을 다시 쓰므로 한 번 바꾸면 지워진다.
  add_init_script 로 모든 문서에 심고, 1초마다 말머리가 남아 있는지만 본다.
  MutationObserver 대신 1초 간격을 쓴 이유는 09:00 경주 중에 도는 코드라
  '언제 얼마나 도는지' 가 예측 가능해야 하기 때문이다. 1초에 한 번은 무시할 만하다.

    .venv/Scripts/python.exe dev/label_windows.py            (9222, 9223)
    .venv/Scripts/python.exe dev/label_windows.py --ports 9223
"""
from __future__ import annotations
import argparse

NAMES = {9222: "실전", 9223: "계측"}

JS = """(() => {
  const TAG = %s;
  const fix = () => {
    try {
      const t = document.title || '';
      if (t.indexOf(TAG) !== 0) document.title = TAG + ' ' + t;
    } catch (e) {}
  };
  fix();
  try { setInterval(fix, 1000); } catch (e) {}
})();"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ports", default="9222,9223")
    a = ap.parse_args()

    from playwright.sync_api import sync_playwright
    for port in [int(p) for p in a.ports.split(",")]:
        tag = f"[Claude · {port} {NAMES.get(port, '')}]".replace(" ]", "]")
        js = JS % repr(tag).replace("'", '"')
        try:
            with sync_playwright() as pw:
                b = pw.chromium.connect_over_cdp(f"http://localhost:{port}")
                ctx = b.contexts[0]
                # 앞으로 열리는 모든 문서에 심는다 (화면을 옮겨도 말머리가 남는다)
                ctx.add_init_script(js)
                # 지금 떠 있는 탭에도 바로 적용
                for p in ctx.pages:
                    try:
                        p.evaluate(js)
                    except Exception:
                        pass
                titles = [(p.title() or "")[:60] for p in ctx.pages]
                b.close()
            print(f"  {port}: {tag}  ->  {titles}")
        except Exception as e:
            print(f"  {port}: 붙지 못함 - {str(e)[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
