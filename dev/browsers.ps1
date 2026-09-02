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

foreach ($t in $targets) {
  $up = Get-NetTCPConnection -State Listen -LocalPort $t.Port -ErrorAction SilentlyContinue
  if ($up) {
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

Start-Sleep -Seconds 8
foreach ($t in $targets) {
  $up = Get-NetTCPConnection -State Listen -LocalPort $t.Port -ErrorAction SilentlyContinue
  Write-Output ("포트 $($t.Port): " + $(if ($up) { "OK" } else { "안 올라옴" }))
}
