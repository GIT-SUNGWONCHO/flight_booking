# 아침 한 방. 08:45 에 스케줄러가 이것 하나만 실행한다.
#
#   1) 크롬 2개(9222 실전 / 9223 계측) 띄우기
#   2) 크롬이 살아 있나만 20초 확인 (--quick)
#   3) 측정 시작 - 스스로 셋업하고 08:59:57.5 까지 대기했다가 발사
#
# 무거운 점검은 여기 없다. 전날 16:00 precheck.ps1 이 한다.
# 08:45 에 "로그인이 풀렸습니다" 를 알아봐야 고칠 시간이 15분뿐이고, 그 점검이
# 6분 53초를 잡아먹으면(09-03 리허설) 측정 셋업에 3분밖에 안 남는다.
# 아침에 할 일은 '문제 찾기' 가 아니라 '9시에 대기 상태로 서 있기' 다.
param(
  # 시험용. 측정 프로세스(09:00 까지 기다리는 부분)를 건너뛰고 준비까지만 본다.
  [switch]$NoDaily
)
$ErrorActionPreference = 'SilentlyContinue'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
. (Join-Path $PSScriptRoot "day.ps1")      # $DailyArgs - 저녁 점검과 같은 파일을 읽는다
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

# 어젯밤 점검이 실제로 통과했는지 확인만 한다. 여기서 다시 점검하지는 않는다.
$evWarn = ""
try {
  $j = Get-Content (Join-Path $logDir "preflight.json") -Raw | ConvertFrom-Json
  $age = ((Get-Date) - [datetime]$j.at).TotalHours
  if (-not $j.ok)      { $evWarn = "어젯밤 점검이 실패로 끝났습니다: " + ($j.problems -join '; ') }
  elseif ($age -gt 20) { $evWarn = ("어젯밤 점검이 없습니다 (마지막 {0:N0}시간 전)" -f $age) }
  else { Say ("어젯밤 점검 통과 확인 ({0} / {1} -> {2})" -f $j.at, $j.origin, $j.route) }
} catch { $evWarn = "어젯밤 점검 기록을 읽지 못했습니다" }
if ($evWarn) { Say ("주의: " + $evWarn) }

# --- 1) 크롬 ---
& (Join-Path $PSScriptRoot "browsers.ps1") | ForEach-Object { Say "  $_" }

# --- 2) 살아 있나 (20초) ---
# 혹시 이것마저 멈추면 측정을 못 시작한다. 2분 넘기면 잘라내고 그냥 간다.
Say "크롬 확인 (--quick)"
$qOut = Join-Path $logDir "preflight_quick.out"
$proc = Start-Process -FilePath $py -PassThru -NoNewWindow `
        -ArgumentList @((Join-Path $PSScriptRoot "preflight.py"), "--quick") `
        -RedirectStandardOutput $qOut -RedirectStandardError (Join-Path $logDir "preflight_quick.err")
if ($proc.WaitForExit(120000)) {
  $qOk = ($proc.ExitCode -eq 0)
} else {
  & taskkill /T /F /PID $proc.Id 2>&1 | Out-Null
  $qOk = $false
}
Get-Content $qOut -ErrorAction SilentlyContinue | ForEach-Object { Say "  $_" }

if (-not $qOk) {
  $why = ""
  try {
    $j = Get-Content (Join-Path $logDir "preflight_quick.json") -Raw | ConvertFrom-Json
    $why = ($j.problems -join "`n")
  } catch { $why = "크롬 확인이 끝나지 않았습니다" }
  Say "!!! 크롬 확인 실패 - 팝업으로 알림"
  Popup "9시 준비 - 크롬을 봐주세요" `
        ("9시까지 시간이 있습니다.`n`n$why`n" + $(if($evWarn){"`n($evWarn)`n"}else{""}) + "`n" +
         "측정은 그대로 시작하며 스스로 셋업을 다시 시도합니다.")
} else {
  Say "크롬 OK"
}

# --- 3) 측정 (확인이 실패했어도 돌린다. 측정은 스스로 셋업한다) ---
if ($NoDaily) {
  Say "(-NoDaily) 측정은 건너뜀 - 준비까지만 확인"
} else {
  Say ("측정 프로세스 시작 (" + ($DailyArgs -join ' ') + ") - 스스로 셋업 후 08:59:57.5 발사")
  & $py (Join-Path $PSScriptRoot "daily.py") @DailyArgs 2>&1 |
    ForEach-Object { Say "  $_" }
}
Say "=== 아침 끝 (결과는 dev-shots 참고) ==="
