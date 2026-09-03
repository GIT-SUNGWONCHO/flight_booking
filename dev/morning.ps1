# 아침 한 방. 08:45 에 스케줄러가 이것 하나만 실행한다.
#
#   1) 크롬 2개(9222 실전 / 9223 계측) 띄우기
#   2) 사전 점검 - 로그인 확인 + 오늘 노선의 달력 화면까지 세워보기
#      실패하면 화면에 팝업을 띄운다. 로그로만 남기면 사람이 못 본다.
#   3) 측정 프로세스 시작 - 스스로 셋업하고 08:59:57.5 까지 대기했다가 발사
#
# 예전엔 08:45/08:47/08:50 세 개로 나눠 걸었는데 나눌 이유가 없었다.
# 09:00 까지 15분이라 순서대로 해도 넉넉하다.
param(
  # 시험용. 측정 프로세스(09:00 까지 기다리는 부분)를 건너뛰고 준비까지만 본다.
  [switch]$NoDaily
)
$ErrorActionPreference = 'SilentlyContinue'

# ─────────────────────────────────────────────────────────────
#  오늘 무엇을 잴 것인가 — 여기 한 줄만 고친다.
#
#  비워두면 요일로 자동 판단한다 (열리는 날이 월·수·토면 로마, 아니면 파리).
#  두 군데에 각각 적으면 사전점검과 측정이 서로 다른 화면을 잡는다. 그래서 한 곳이다.
#
#  2026-09-04 (금, 열리는 날 2027-08-30 월 = 로마 운항일):
#    인천→로마(SEL→FCO)로 계측기 + dry 매크로 동시.
$DailyArgs = @('--route', 'FCO')
# ─────────────────────────────────────────────────────────────

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "dev-shots"
New-Item -ItemType Directory -Force $logDir | Out-Null

function Say([string]$m) {
  $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $m
  Write-Output $line
  Add-Content -Path (Join-Path $logDir "morning.log") -Value $line
}

function Popup([string]$title, [string]$body) {
  # 스케줄러는 창을 숨긴 채 돌리므로, 문제가 생기면 이렇게라도 눈에 띄게 한다.
  try {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($body, $title,
      [System.Windows.Forms.MessageBoxButtons]::OK,
      [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
  } catch {
    try { & msg.exe * $body } catch {}
  }
}

Say "=== 아침 준비 시작 ==="

# --- 1) 크롬 ---
& (Join-Path $PSScriptRoot "browsers.ps1") | ForEach-Object { Say "  $_" }

# --- 2) 사전 점검 ---
Say "사전 점검 (로그인 + 화면 세팅)"
# 측정과 같은 노선으로 점검해야 의미가 있다. 그래서 $DailyArgs 를 그대로 넘긴다.
$pre = & $py (Join-Path $PSScriptRoot "preflight.py") @DailyArgs 2>&1
$preOk = ($LASTEXITCODE -eq 0)
$pre | ForEach-Object { Say "  $_" }

if (-not $preOk) {
  $why = ""
  try {
    $j = Get-Content (Join-Path $logDir "preflight.json") -Raw | ConvertFrom-Json
    $why = ($j.problems -join "`n")
  } catch { $why = "preflight.json 을 읽지 못했습니다" }
  Say "!!! 사전 점검 실패 - 팝업으로 알림"
  Popup "9시 준비 안 됨 (지금 손봐야 합니다)" `
        ("9시까지 시간이 있습니다. 아래를 해결해 주세요:`n`n$why`n`n" +
         "해결하면 08:50 경 자동 셋업이 다시 시도합니다.")
} else {
  Say "사전 점검 통과 - 9시 준비됨"
}

# --- 3) 측정 (점검이 실패했어도 돌린다. 사람이 로그인만 고치면 자체 셋업이 살린다) ---
if ($NoDaily) {
  Say "(-NoDaily) 측정은 건너뜀 - 준비까지만 확인"
} else {
  Say ("측정 프로세스 시작 (" + ($DailyArgs -join ' ') + ") - 스스로 셋업 후 08:59:57.5 발사")
  & $py (Join-Path $PSScriptRoot "daily.py") @DailyArgs 2>&1 |
    ForEach-Object { Say "  $_" }
}
Say "=== 아침 끝 (결과는 dev-shots 참고) ==="
