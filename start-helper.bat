@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY="
if exist "%~dp0python-path.txt" (
  for /f "usebackq delims=" %%L in ("%~dp0python-path.txt") do (
    if not defined PY set "PY=%%L"
  )
)
if not defined PY (
  echo.
  echo   Run setup.bat first.
  echo.
  pause
  exit /b 1
)

rem Start hidden (pythonw has no window). Falls back to python.exe if missing.
set "PYW=%PY:python.exe=pythonw.exe%"
if not exist "%PYW%" set "PYW=%PY%"
start "" /b "%PYW%" "%~dp0helper.py"
echo.
echo   VidFetch helper started in the background. You can close this window.
timeout /t 3 >nul
