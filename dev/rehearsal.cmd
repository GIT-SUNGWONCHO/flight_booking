@echo off
rem 무인 리허설: 스케줄러가 이걸 실행한다. autorun 을 dry(주문 안 만듦)로 돌린다.
rem 목표 FCO 08-28 은 아직 안 열렸으므로(내일 9시 오픈) 매크로가 '못 찾음' 으로
rem 안전하게 보고한다 - 스케줄러+무인 파이프라인이 도는지 검증하는 것이 목적이다.
cd /d "%~dp0.."
".venv\Scripts\python.exe" "dev\autorun.py" --dry --route FCO --date 08-28 --at 13:14 > "dev-shots\rehearsal_console.log" 2>&1
