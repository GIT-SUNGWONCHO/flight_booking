@echo off
rem 매일 09:00 측정. 스케줄러가 08:50 에 실행한다.
rem
rem 이 파일은 '그날 무엇을 잴지' 에 따라 손으로 조정한다. 날마다 목적이 다르기 때문이다.
rem   - 계측만: --no-macro  (매크로는 안 돌린다)
rem   - 유럽발: --from CDG --route ICN  (파리->인천) / --from FCO --route ICN (로마->인천)
rem   - 자동판단: 인자 없이 (열리는 날이 월수토면 로마, 아니면 파리)
rem
rem 2026-09-03 (목, 열리는 날 08-29 일요일 - 로마 없음):
rem   계측만 진행하고, 유럽발 경로를 9시 조건에서 처음 검증한다 (파리->인천 = 9/25 목표 방향).
cd /d "%~dp0.."
".venv\Scripts\python.exe" "dev\daily.py" --route ICN --from CDG --no-macro > "dev-shots\daily_console.log" 2>&1
