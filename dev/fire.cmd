@echo off
rem 내일 9시 실전 무인 발사. 스케줄러가 이걸 실행한다.
rem  - 로마 FCO / 프레스티지(autorun 기본값) / 08-28
rem  - --dry 없음 -> allowPay=true -> 좌석 잡고 결제창(네이버페이)까지 연다
rem  - --at 09:00 -> autorun 이 선발사 2500ms 빼서 08:59:57.5 에 발사
rem 로그인된 디버그 크롬이 떠 있어야 한다(사람이 미리 로그인).
cd /d "%~dp0.."
".venv\Scripts\python.exe" "dev\autorun.py" --route FCO --date 08-28 --at 09:00 > "dev-shots\fire_console.log" 2>&1
