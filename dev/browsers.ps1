# 실전용(9222)·계측용(9223) 크롬을 띄운다. 이미 떠 있으면 건드리지 않는다.
#
# cmd 의 `start ""` 로 띄우면 스케줄러/도구가 실행할 때 크롬이 붙어 있지 못하고
# 사라진다(2026-09-02 실측: 9222 가 안 올라옴). Start-Process 로 직접 띄우면 붙는다.
#
# 최소화/가려짐에서도 타이머가 안 늦춰지는 플래그를 함께 준다.
$ErrorActionPreference = 'SilentlyContinue'
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$root = Split-Path -Parent $PSScriptRoot

$targets = @(
  @{ Port = 9222; Profile = ".debug-profile";  Name = "실전용" },
  @{ Port = 9223; Profile = ".debug-profile2"; Name = "계측용" }
)

# 포트가 LISTEN 으로 보여도 크롬이 살아 있다는 뜻이 아니다. 방금 죽인 크롬의
# 소켓이 잠시 남아 "이미 떠 있음" 으로 읽히고, 그러면 새로 띄우지 않아 아무것도
# 없는 상태가 된다. 09-07 리허설에서 9223 이 끝내 안 올라와 계측기가 69번
# 재시도하다 죽은 것이 이것이다. **CDP 가 실제로 답하는지**로 판정한다. (09-08)
function Alive([int]$port) {
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/json/version" `
         -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
    return $r.StatusCode -eq 200
  } catch { return $false }
}

foreach ($t in $targets) {
  if (Alive $t.Port) {
    Write-Output "$($t.Name) 크롬 이미 떠 있음 (포트 $($t.Port))"
    continue
  }
  $dir = Join-Path $root $t.Profile
  Start-Process -FilePath $chrome -ArgumentList `
    "--remote-debugging-port=$($t.Port)", `
    "--user-data-dir=$dir", `
    "--no-first-run", `
    "--no-default-browser-check", `
    "--disable-background-timer-throttling", `
    "--disable-backgrounding-occluded-windows", `
    "--disable-renderer-backgrounding", `
    "https://www.koreanair.com/kr/ko"
  Write-Output "$($t.Name) 크롬 띄움 (포트 $($t.Port))"
}

# 8초 고정 대기로는 부족할 때가 있다. 실제로 답할 때까지 최대 30초 기다린다.
foreach ($t in $targets) {
  $ok = $false
  for ($i = 0; $i -lt 30; $i++) {
    if (Alive $t.Port) { $ok = $true; break }
    Start-Sleep -Seconds 1
  }
  Write-Output ("포트 $($t.Port): " + $(if ($ok) { "OK" } else { "안 올라옴 (30초 기다림)" }))
}
