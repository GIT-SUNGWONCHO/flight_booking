#!/usr/bin/env bash
# 고친 것만 빨리 검사한다.
#
# run-tests.sh 는 29단계 전부를 돌리느라 브라우저를 22번 새로 띄운다 - 15~20분이다.
# 한 줄 고칠 때마다 그걸 기다릴 이유가 없다. 푸시 직전에 한 번만 전체를 돌리고,
# 그전까지는 이걸 쓴다.
#
#   ./t.sh                    브라우저 없는 검사 전부 (빌드/문법/유닛)   ~10초
#   ./t.sh parity skipcal     이름이 맞는 것만                          ~1분
#   ./t.sh --list             무엇을 고르면 되는지 보여준다
#   ./t.sh --gate             푸시 직전 검사 (09:00 결과에 직결되는 것만)  ~3분
#   ./t.sh --all              run-tests.sh 로 전체                        ~15분
set -uo pipefail
cd "$(dirname "$0")"
PY=./.venv/Scripts/python.exe
[ -x "$PY" ] || PY=./.venv/bin/python
R=0
say() { printf '\033[36m%s\033[0m\n' "$*"; }
bad() { printf '\033[31m%s\033[0m\n' "$*"; R=1; }

# 브라우저가 남아 있으면 프로필이 잠겨 다음 실행이 죽는다
reset_browsers() {
  taskkill //F //IM chrome-headless-shell.exe >/dev/null 2>&1 || true
  sleep 1.5
}

if [ "${1:-}" = "--all" ]; then exec ./run-tests.sh; fi

# 푸시 직전 검사. 29단계 전부는 15분이라 매번 돌 수 없다.
#
# 고른 기준은 "이게 깨지면 09:00 에 좌석을 잃는가" 하나다:
#   hud        무장 -> 정시 발사 -> 새로고침 -> 재생. 이게 안 되면 아무것도 안 된다
#   parity     재생/연습/대기시작이 갈라지는가. 같은 사고가 세 번 났다
#   skipcal    조회 화면 모드 전체 + 세 경로 동치
#   calendar   목표 날짜 고르기. 틀리면 엉뚱한 날에 마일리지가 나간다
#   deadclick  클릭이 씹혔을 때 되살리기. 대기 시간을 줄일수록 여기에 기댄다
#   twoagree   동의 2개 + 스크롤. 실전에서 가장 자주 막히던 구간
#
# 나머지는 편집기 UI, 셀렉터 집기, 유저스크립트에 없는 코드 같은 것들이라
# 푸시를 막을 이유가 없다. 그것들은 ./t.sh --all 로 가끔 돌린다.
if [ "${1:-}" = "--gate" ]; then
  set -- hud parity skipcal calendar deadclick twoagree
fi

if [ "${1:-}" = "--list" ]; then
  echo "고칠 파일 -> 돌릴 것"
  echo "  ke_award/util.js       util calendar deeplink probe"
  echo "  ke_award/recorder.js   recorder deadclick twoagree scrollmodal parity stepwhy currestart"
  echo "  ke_award/hud.js        hud armpersist opentime parity skipcal narrow"
  echo "  ke_award/probe.js      probe skipcal"
  echo "  ke_award/steps.json    precedence skipreport"
  echo
  echo "있는 것:"
  ls test/test_*.py test/test_*.js | sed 's|test/test_||; s|\.[a-z]*$||' | tr '\n' ' '
  echo
  exit 0
fi

# --- 어떤 경우에도 하는 것: 문법 + 빌드 (몇 초, 붕괴를 여기서 잡는다) ---
say "[빠름] 문법 검사"
for f in ke_award/*.js; do node --check "$f" || bad "문법 오류: $f"; done
say "[빠름] 빌드"
node build.mjs >/dev/null || bad "빌드 실패"
node --check userscript/ke-award-macro.user.js || bad "빌드 산출물 문법 오류"

if [ $# -eq 0 ]; then
  # 브라우저 없는 검사 전부
  for f in test/test_*.js; do
    say "[빠름] $(basename "$f")"
    node "$f" >/dev/null || bad "$(basename "$f") 실패"
  done
  [ $R -eq 0 ] && printf '\033[32m빠른 검사 통과 (브라우저 없는 것만)\033[0m\n'
  exit $R
fi

# --- 이름이 맞는 것만 ---
for want in "$@"; do
  hit=0
  for f in test/test_*.py test/test_*.js; do
    case "$f" in *"$want"*) hit=1
      say "[검사] $(basename "$f")"
      case "$f" in
        *.js) node "$f" || bad "$(basename "$f") 실패" ;;
        *)    reset_browsers; "$PY" "$f" || bad "$(basename "$f") 실패" ;;
      esac ;;
    esac
  done
  [ $hit -eq 0 ] && bad "'$want' 에 맞는 테스트가 없습니다 (./t.sh --list)"
done
reset_browsers
[ $R -eq 0 ] && printf '\033[32m통과\033[0m\n'
exit $R
