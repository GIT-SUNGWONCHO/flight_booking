# 전날 사전점검. 스케줄러가 매일 16:00 에 이것 하나를 실행한다.
#
# 왜 아침이 아니라 전날 16:00 인가
#   08:45 에 "로그인이 풀렸습니다" 를 알아봐야 고칠 시간이 15분이다. 사람이 자리에
#   없으면 그냥 하루를 잃는다(2026-09-03).
#   16:00 은 사람이 PC 앞에 있는 시간이라 팝업을 실제로 본다. 밤에 걸면 아무도 안 본다.
#
# 무엇을 하나
#   크롬 2개를 띄우고, 내일 노선으로 로그인·달력 화면까지 **실제로 세워본다.**
#   되면 그대로 두고, 안 되면 팝업으로 크게 알린다. 5~8분 걸린다.
#   (아침 08:45 은 크롬이 살아 있나만 20초 보고 바로 측정에 들어간다.)
param(
  # 크롬을 새로 띄우지 않고 이미 떠 있는 것만 점검한다.
  [switch]$NoBrowsers
)
$ErrorActionPreference = 'SilentlyContinue'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
. (Join-Path $PSScriptRoot "day.ps1")      # $DailyArgs
$py = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "dev-shots"
New-Item -ItemType Directory -Force $logDir | Out-Null

function Say([string]$m) {
  $line = "[{0}] {1}" -f (Get-Date -Format "MM-dd HH:mm:ss"), $m
  Write-Output $line
  Add-Content -Path (Join-Path $logDir "precheck.log") -Value $line
}

function Popup([string]$title, [string]$body) {
  try {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($body, $title,
      [System.Windows.Forms.MessageBoxButtons]::OK,
      [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
  } catch {
    try { & msg.exe * $body } catch {}
  }
}

# StartWhenAvailable 때문에 PC 가 꺼져 있었다면 다음날 아침에 뒤늦게 실행될 수 있다.
# 그때 5~8분짜리 셋업이 돌면 08:45 아침 작업과 같은 크롬을 놓고 다툰다. 막는다.
$h = (Get-Date).TimeOfDay
if ($h -ge [TimeSpan]::FromHours(7.5) -and $h -lt [TimeSpan]::FromHours(9.5)) {
  Say "아침 시간대라 저녁 점검을 건너뛴다 (08:45 아침 작업과 크롬을 다툰다)"
  exit 0
}

Say "=== 전날 사전점검 시작 ==="

if (-not $NoBrowsers) {
  & (Join-Path $PSScriptRoot "browsers.ps1") | ForEach-Object { Say "  $_" }
}

Say ("내일 노선으로 실제 세워본다 (" + ($DailyArgs -join ' ') + ")")
$out = & $py (Join-Path $PSScriptRoot "preflight.py") --for-tomorrow @DailyArgs 2>&1
$ok = ($LASTEXITCODE -eq 0)
$out | ForEach-Object { Say "  $_" }

if ($ok) {
  Say "통과 - 내일 아침은 크롬 확인만 하고 바로 측정에 들어간다"
} else {
  $why = ""
  try {
    $j = Get-Content (Join-Path $logDir "preflight.json") -Raw | ConvertFrom-Json
    $why = ($j.problems -join "`n")
  } catch { $why = "preflight.json 을 읽지 못했습니다" }
  Say "!!! 실패 - 팝업으로 알림"
  Popup "내일 9시 준비 안 됨 (오늘 안에 고쳐두세요)" `
        ("내일 09:00 을 위한 사전점검이 실패했습니다.`n지금 고쳐두면 내일 아침은 그냥 돌아갑니다.`n`n" +
         "$why`n`n" +
         "고친 뒤 확인:  pwsh -File dev\precheck.ps1")
}
Say "=== 사전점검 끝 ==="
