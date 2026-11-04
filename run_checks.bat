@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Voltage Envelopes environment not found. Create .venv and install requirements.txt first.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -m pytest -q
endlocal
