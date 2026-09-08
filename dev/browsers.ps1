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
  # Pos/Size: 자동화가 띄운 창을 눈으로 바로 가려낼 수 있게 자리를 고정한다.
  # 창 폭은 1400 이상이어야 한다 - 그 아래는 모바일 레이아웃이라 셀렉터가 달라진다(FACTS).
  @{ Port = 9222; Profile = ".debug-profile";  Name = "실전용"; Pos = "0,0";   Size = "1500,980" },
  @{ Port = 9223; Profile = ".debug-profile2"; Name = "계측용"; Pos = "120,80"; Size = "1500,980" }
)

# 창에 누구 것인지 써 둔다. 다른 작업자(9232/9233)와 사용자 개인 창이 같이 떠 있어서
# 어느 크롬이 이 자동화의 것인지 눈으로 구별돼야 한다. (09-08 사용자 요청)
#
# 크롬 창 제목은 탭 제목이라 우리가 못 고친다. 대신 프로필 이름을 박는다 -
# 툴바 프로필 칩과 프로필 메뉴에 그대로 보인다. 크롬이 꺼져 있을 때 써야 한다.
function Set-ProfileName([string]$dir, [string]$label) {
  $pref = Join-Path $dir "Default\Preferences"
  try {
    if (-not (Test-Path $pref)) { return }   # 첫 실행이면 아직 없다. 다음 번에 붙는다.
    $j = Get-Content $pref -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $j.profile) { return }
    if ($j.profile.name -eq $label) { return }
    $j.profile | Add-Member -NotePropertyName name -NotePropertyValue $label -Force
    ($j | ConvertTo-Json -Depth 100 -Compress) | Set-Content $pref -Encoding UTF8 -NoNewline
  } catch { }
}

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

function Launch($t) {
  $dir = Join-Path $root $t.Profile
  # 말머리를 'Claude:' 로 둔다. 브라우저를 봤을 때 이 자동화가 띄운 창인지
  # 사람이 띄운 창인지, 다른 작업자 것인지 바로 갈리게. (09-08 사용자 요청)
  $label = "Claude:$($t.Port) $($t.Name)"   # 예: "Claude:9223 계측용"
  Set-ProfileName $dir $label
  Start-Process -FilePath $chrome -ArgumentList `
    "--remote-debugging-port=$($t.Port)", `
    "--user-data-dir=$dir", `
    "--no-first-run", `
    "--no-default-browser-check", `
    "--disable-background-timer-throttling", `
    "--disable-backgrounding-occluded-windows", `
    "--disable-renderer-backgrounding", `
    "--window-position=$($t.Pos)", `
    "--window-size=$($t.Size)", `
    "https://www.koreanair.com/kr/ko"
  Write-Output "$($t.Name) 크롬 띄움 (포트 $($t.Port), 프로필이름 '$label', 창 $($t.Pos))"
}

# 죽인 직후에는 프로필이 아직 안 풀려 크롬이 **조용히 죽는다**. 로그에는
# '띄움' 이라고 찍히고 포트는 끝내 안 열린다. 09-08 에 실제로 그랬다.
# 한 번 더 띄워 본다 - 두 번째는 됐다.
foreach ($t in $targets) {
  if (Alive $t.Port) {
    Write-Output "$($t.Name) 크롬 이미 떠 있음 (포트 $($t.Port))"
    continue
  }
  $ok = $false
  for ($try = 1; $try -le 3 -and -not $ok; $try++) {
    if ($try -gt 1) { Write-Output "  ($($t.Port)) $try 번째 시도"; Start-Sleep -Seconds 4 }
    Launch $t
    for ($i = 0; $i -lt 25; $i++) {
      if (Alive $t.Port) { $ok = $true; break }
      Start-Sleep -Seconds 1
    }
  }
  Write-Output ("포트 $($t.Port): " + $(if ($ok) { "OK" } else { "안 올라옴 (3번 시도)" }))
}
