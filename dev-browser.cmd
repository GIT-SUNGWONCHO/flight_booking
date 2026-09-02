@echo off
rem 개발용 Chrome 을 원격 디버깅 포트와 함께 띄운다 (dev-browser.sh 의 윈도우판).
rem 이 창에서 한 번만 로그인해두면, 이후 테스트 스크립트가 CDP 로 붙어서
rem 스크립트 주입 / 재생 / DOM 확인을 전부 자동으로 한다.
rem
rem   dev-browser.cmd 를 더블클릭 (한 번 실행해두고 그대로 두세요)
rem
rem 주의: 평소 쓰는 Chrome 프로필이 아니라 이 프로젝트 전용 프로필(.debug-profile)을 쓴다.
rem       최신 Chrome 은 기본 프로필에 원격 디버깅을 허용하지 않기 때문.
cd /d "%~dp0"
rem 최소화/가려진 창에서도 타이머가 안 늦춰지게 하는 플래그 3개.
rem 이게 있으면 9시 발사 중에 창을 최소화해도 매크로가 안 느려진다.
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9222 ^
  --user-data-dir="%~dp0.debug-profile" ^
  --no-first-run ^
  --no-default-browser-check ^
  --disable-background-timer-throttling ^
  --disable-backgrounding-occluded-windows ^
  --disable-renderer-backgrounding ^
  "https://www.koreanair.com/kr/ko"
