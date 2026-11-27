@echo off
chcp 65001 >nul
title VidFetch - uninstall
cd /d "%~dp0"

echo.
echo   This removes autostart, the self-heal entry and the saved folder setting.
echo   Your downloaded files are NOT touched.
echo.
set /p ok="Continue? (y/n): "
if /i not "%ok%"=="y" goto end

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'VidFetch helper.lnk'; if (Test-Path -LiteralPath $lnk) { Remove-Item -LiteralPath $lnk -Force; Write-Host '  autostart removed' } else { Write-Host '  no autostart entry' }"

powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
echo   helper stopped

powershell -NoProfile -ExecutionPolicy Bypass -Command "foreach ($b in 'HKCU:\Software\Google\Chrome\NativeMessagingHosts','HKCU:\Software\Microsoft\Edge\NativeMessagingHosts','HKCU:\Software\BraveSoftware\Brave-Browser\NativeMessagingHosts') { $k = Join-Path $b 'com.vidfetch.helper'; if (Test-Path $k) { Remove-Item $k -Force } }; Write-Host '  self-heal entry removed'"

if exist "%~dp0config.json" (
  del /q "%~dp0config.json"
  echo   folder setting cleared
)
if exist "%~dp0python-path.txt" del /q "%~dp0python-path.txt"

echo.
echo   Done. You can also remove the extension from chrome://extensions.
echo   Then delete this folder.
echo.

:end
pause
