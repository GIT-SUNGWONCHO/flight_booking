#!/usr/bin/env bash
# 달력모드 / 조회모드를 같은 조건으로 연달아 돌려 속도를 비교한다.
# 첫 주문(7단계) 앞에서 멈추는 --dry 를 쓴다:
#   - 경쟁 결승선이 7단계이므로 거기까지의 시간이 곧 비교 대상이다
#   - 미결제 주문을 8건(4노선 x 2모드) 만들지 않는다
set -u
cd "$(dirname "$0")/.."
SC="${1:-.dev-shots}"
mkdir -p "$SC"
ROUTES=ZRH,CDG,FCO,MXP
DATE=2027-08-25
CABIN=일반석

echo "===== $(date '+%F %T') 달력모드 ====="
.venv/bin/python dev/autorun_multi.py --at +25s --mode calendar --tag calendar \
  --routes $ROUTES --date $DATE --cabin $CABIN --dry

echo
echo "===== $(date '+%F %T') 조회모드 ====="
.venv/bin/python dev/autorun_multi.py --at +25s --mode departure --tag departure \
  --routes $ROUTES --date $DATE --cabin $CABIN --dry

echo
echo "===== $(date '+%F %T') 끝 ====="
