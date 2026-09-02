@echo off
rem 매일 09:00 측정. 스케줄러가 08:50 에 이걸 실행한다.
rem  - 요일 보고 노선 자동 결정 (월수토=로마 FCO->ICN, 그 외=파리 SEL->CDG)
rem  - 계측기(2번 크롬 9223) + dry 매크로(1번 크롬 9222) 동시
rem  - dry 라 주문/hold 를 만들지 않는다. 실전(목표일)은 따로 건다.
rem 전제: 1번(dev-browser.cmd)과 2번(dev-browser2.cmd) 크롬이 각각 로그인된 채 떠 있을 것.
cd /d "%~dp0.."
".venv\Scripts\python.exe" "dev\daily.py" > "dev-shots\daily_console.log" 2>&1
