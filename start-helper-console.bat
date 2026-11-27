@echo off
rem Debug mode: runs the helper in a visible window so you can watch the log.
chcp 65001 >nul
title VidFetch - helper (console)
cd /d "%~dp0"
set "PY="
if exist "%~dp0python-path.txt" (
  for /f "usebackq delims=" %%L in ("%~dp0python-path.txt") do (
    if not defined PY set "PY=%%L"
  )
)
if not defined PY ( echo Run setup.bat first. & pause & exit /b 1 )
"%PY%" helper.py
pause
