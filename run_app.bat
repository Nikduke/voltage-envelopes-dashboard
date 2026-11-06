@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\streamlit.exe" (
  echo Voltage Envelopes environment not found.
  echo Create .venv and install the pinned packages from requirements.txt before launching.
  pause
  exit /b 1
)

set "APP_PORT="
for /f "delims=" %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue); foreach ($port in 8501..8510) { if ($listeners.LocalPort -notcontains $port) { Write-Output $port; exit 0 } }" 2^>nul') do set "APP_PORT=%%A"

if not defined APP_PORT (
  echo No free Voltage Envelopes port found in the range 8501-8510.
  pause
  exit /b 2
)

echo Starting Voltage Envelopes at http://127.0.0.1:%APP_PORT%/
echo This window shows Streamlit logs. Press Ctrl+C or close this window to stop the server.
"%~dp0.venv\Scripts\streamlit.exe" run "%~dp0app.py" --server.address 127.0.0.1 --server.port %APP_PORT% --server.headless false
set "APP_EXIT_CODE=%errorlevel%"
if not "%APP_EXIT_CODE%"=="0" pause
endlocal & exit /b %APP_EXIT_CODE%
