#!/usr/bin/env bash
# 전체 테스트 (macOS / Linux / Git Bash).  실행:  ./run-tests.sh
# Windows PowerShell 에서는 ./run-tests.ps1 을 쓰세요.
set -euo pipefail
cd "$(dirname "$0")"

# venv 레이아웃이 OS 마다 다르다
if   [ -x .venv/bin/python ];         then PY=.venv/bin/python
elif [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe
else
  echo "venv 가 없습니다:  python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi

# 브라우저 종료 직후에도 프로필/실행파일이 잠시 잠긴다. 단계 사이에 정리한다.
reset_browsers() {
  case "$(uname -s)" in
    Darwin|Linux) pkill -f 'test-profile' 2>/dev/null || true ;;
    *)            taskkill //F //IM chrome-headless-shell.exe 2>/dev/null || true ;;
  esac
  sleep 2.5
  rm -rf .test-profile* 2>/dev/null || true
}

stage() { printf '\n\033[36m%s\033[0m\n' "$1"; }

stage "[1/27] 라벨 판정 유닛테스트"
node test/test_autoconfirm.js

stage "[2/27] 유틸(날짜 자동감지/접두어 매칭) 유닛테스트"
node test/test_util.js

stage "[3/27] 유저스크립트 빌드"
node build.mjs
node --check userscript/ke-award-macro.user.js

reset_browsers
stage "[4/27] 브라우저 통합테스트"
"$PY" test/test_integration.py

reset_browsers
stage "[5/27] 유저스크립트(HUD) 테스트"
"$PY" test/test_hud.py

reset_browsers
stage "[6/27] 녹화/재생 테스트"
"$PY" test/test_recorder.py

reset_browsers
stage "[7/27] 단계 편집 테스트"
"$PY" test/test_editor.py

reset_browsers
stage "[8/27] 단계 우선순위 테스트"
"$PY" test/test_precedence.py

reset_browsers
stage "[9/27] 건너뜀 보고 / 추측클릭 제거 확인"
"$PY" test/test_skipreport.py

reset_browsers
stage "[10/27] 헛클릭 감지·재시도 테스트"
"$PY" test/test_deadclick.py

reset_browsers
stage "[11/27] 모달 가림 테스트"
"$PY" test/test_modalblock.py

reset_browsers
stage "[12/27] 스크롤 팝업 테스트"
"$PY" test/test_scrollmodal.py

reset_browsers
stage "[13/27] 중복 동의 테스트"
"$PY" test/test_doubleagree.py

reset_browsers
stage "[14/27] 동의 2개 모달 테스트"
"$PY" test/test_twoagree.py

reset_browsers
stage "[15/27] 셀렉터 집기 / 패널 드래그 테스트"
"$PY" test/test_picker.py

reset_browsers
stage "[16/27] 건너뛰기 금지 테스트"
"$PY" test/test_noskip.py

reset_browsers
stage "[17/27] 무장 유지 / 결제창 판정 테스트"
"$PY" test/test_armpersist.py

reset_browsers
stage "[18/27] 달력 최신날짜 / 목표날짜 형식 테스트"
"$PY" test/test_calendar.py

reset_browsers
stage "[19/27] 통화 KRW / 결제수단 대체 테스트"
"$PY" test/test_currency.py

reset_browsers
stage "[20/27] 통화 변경 후 화면 되돌아감 테스트"
"$PY" test/test_currestart.py

reset_browsers
stage "[21/27] 발사 시각 입력 테스트"
"$PY" test/test_opentime.py

reset_browsers
stage "[22/27] 목표 날짜 오픈 대기 테스트"
"$PY" test/test_openwait.py

reset_browsers
stage "[23/27] 로그인 확인 테스트"
"$PY" test/test_login.py

stage "[24/27] 바로 시작 주소 테스트"
node test/test_deeplink.js

stage "[25/27] 조회 응답 계측 테스트"
node test/test_probe.js

reset_browsers
stage "[26/27] 달력 건너뛰기 테스트"
"$PY" test/test_skipcal.py

reset_browsers
stage "[27/27] 단계 원인 분류 테스트"
"$PY" test/test_stepwhy.py

reset_browsers
printf '\n\033[32m전체 통과\033[0m\n'
