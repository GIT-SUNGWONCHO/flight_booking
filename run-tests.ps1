# 전체 테스트.  실행:  ./run-tests.ps1
$ErrorActionPreference = 'Stop'

# Windows 는 브라우저 종료 직후에도 실행 파일/프로필을 잠시 잠근다.
# 브라우저를 쓰는 단계 사이마다 잔류 프로세스를 치우고 잠깐 쉬어 흔들림을 줄인다.
function Reset-Browsers {
  Get-CimInstance Win32_Process -Filter "Name='chrome.exe' OR Name='chrome-headless-shell.exe'" |
    Where-Object { $_.CommandLine -like '*test-profile*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Milliseconds 700
  Remove-Item -Recurse -Force .test-profile* -ErrorAction SilentlyContinue
}

function Invoke-Stage([string]$Title, [scriptblock]$Body, [string]$OnFail) {
  Write-Host "`n$Title" -ForegroundColor Cyan
  & $Body
  if ($LASTEXITCODE -ne 0) { throw $OnFail }
}

Invoke-Stage "[1/6] 라벨 판정 유닛테스트" { node test/test_autoconfirm.js } "유닛테스트 실패"

Invoke-Stage "[2/6] 유저스크립트 빌드" {
  node build.mjs
  node --check userscript/ke-award-macro.user.js
} "빌드 실패"

Reset-Browsers
Invoke-Stage "[3/6] 브라우저 통합테스트" {
  & ./.venv/Scripts/python.exe test/test_integration.py
} "통합테스트 실패"

Reset-Browsers
Invoke-Stage "[4/6] 유저스크립트(HUD) 테스트" {
  & ./.venv/Scripts/python.exe test/test_hud.py
} "HUD 테스트 실패"

Reset-Browsers
Invoke-Stage "[5/6] 녹화/재생 테스트" {
  & ./.venv/Scripts/python.exe test/test_recorder.py
} "녹화/재생 테스트 실패"

Reset-Browsers
Invoke-Stage "[6/6] 단계 편집 테스트" {
  & ./.venv/Scripts/python.exe test/test_editor.py
} "편집 테스트 실패"

Reset-Browsers
Write-Host "`n전체 통과" -ForegroundColor Green
