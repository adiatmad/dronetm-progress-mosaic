@echo off
setlocal
set "ROOT=%~dp0"
set "PS1=%ROOT%rebuild_cog.ps1"
set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS1%" (
  echo ERROR: rebuild_cog.ps1 was not found beside this file.
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
  echo Mosaic build did not complete successfully. Review the errors above.
  pause
)
exit /b %RESULT%
