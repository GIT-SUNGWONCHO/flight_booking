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
  sleep 0.7
  rm -rf .test-profile* 2>/dev/null || true
}

stage() { printf '\n\033[36m%s\033[0m\n' "$1"; }

stage "[1/6] 라벨 판정 유닛테스트"
node test/test_autoconfirm.js

stage "[2/6] 유저스크립트 빌드"
node build.mjs
node --check userscript/ke-award-macro.user.js

reset_browsers
stage "[3/6] 브라우저 통합테스트"
"$PY" test/test_integration.py

reset_browsers
stage "[4/6] 유저스크립트(HUD) 테스트"
"$PY" test/test_hud.py

reset_browsers
stage "[5/6] 녹화/재생 테스트"
"$PY" test/test_recorder.py

reset_browsers
stage "[6/6] 단계 편집 테스트"
"$PY" test/test_editor.py

reset_browsers
printf '\n\033[32m전체 통과\033[0m\n'
