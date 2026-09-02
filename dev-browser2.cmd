@echo off
rem 계측기 전용 2번 크롬 (포트 9223 / 별도 프로필 / 다른 계정).
rem 1번 크롬(9222, 실전 예약용)과 프로필이 완전히 분리돼 쿠키·세션·localStorage 가
rem 섞이지 않는다. 그래서 9시에 예약과 계측을 동시에 돌려도 서로 방해하지 않는다.
rem
rem   dev-browser2.cmd 더블클릭 -> 뜨면 '계측용 계정' 으로 로그인해두세요.
rem
rem 최소화/가려짐에서도 타이머가 안 늦춰지게 하는 플래그를 함께 준다.
cd /d "%~dp0"
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9223 ^
  --user-data-dir="%~dp0.debug-profile2" ^
  --no-first-run ^
  --no-default-browser-check ^
  --disable-background-timer-throttling ^
  --disable-backgrounding-occluded-windows ^
  --disable-renderer-backgrounding ^
  "https://www.koreanair.com/kr/ko"
