@echo off
setlocal
set "ROOT=%~dp0"
set "PS1=%ROOT%prepare_oam_cog.ps1"
set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS1%" (
  echo ERROR: prepare_oam_cog.ps1 was not found beside this file.
  pause
  exit /b 1
)
if not exist "%POWERSHELL%" (
  echo ERROR: Windows PowerShell was not found.
  pause
  exit /b 1
)
"%POWERSHELL%" -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo OAM COG preparation did not complete successfully. No upload was attempted.
  pause
)
exit /b %RESULT%
