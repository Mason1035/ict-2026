@echo off
setlocal
chcp 65001 >nul
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo 未找到项目虚拟环境，请按 LOCAL_WORK_GUIDE.md 选择 Python 3.11+。
  pause
  exit /b 2
)
"%~dp0.venv\Scripts\python.exe" -B -X utf8 "%~dp0run_independent.py"
set "B_RUN_EXIT=%ERRORLEVEL%"
pause
exit /b %B_RUN_EXIT%
