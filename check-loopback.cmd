@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [!] .venv python not found - trying system python
  python "dev\_probe_cdp.py" doubleclick
) else (
  ".venv\Scripts\python.exe" "dev\_probe_cdp.py" doubleclick
)
echo.
echo ---------------------------------------------
echo  [2] CONNECT = OK   then automation works when YOU launch it
echo  [2] CONNECT = FAIL then loopback connect is blocked here too
echo ---------------------------------------------
echo.
pause
