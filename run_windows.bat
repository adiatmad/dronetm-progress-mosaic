@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher (py) was not found.
  echo Install 64-bit Python 3.11 or 3.12 from https://www.python.org/downloads/windows/
  echo Make sure "Add Python to PATH" is enabled.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating local virtual environment...
  py -3.11 -m venv .venv
  if errorlevel 1 (
    if exist ".venv" rmdir /s /q ".venv"
    py -3.12 -m venv .venv
  )
  if errorlevel 1 (
    echo Could not create a Python 3.11 or 3.12 environment.
    echo Install 64-bit Python from https://www.python.org/downloads/windows/
    pause
    exit /b 1
  )
)

echo Installing or updating dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo Starting DroneTM Progress Mosaic...
".venv\Scripts\python.exe" -m streamlit run app.py
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo Startup failed. Check the error above, your internet connection, and Python installation.
pause
exit /b 1
