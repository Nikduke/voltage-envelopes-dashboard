@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\streamlit.exe" (
  echo Voltage Envelopes environment not found.
  echo Create .venv and install the pinned packages from requirements.txt before launching.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$expected = [regex]::Escape('%~dp0app.py'); $listeners = Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue; if (-not $listeners) { exit 1 }; foreach ($listener in $listeners) { $owner = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $listener.OwningProcess); if ($owner.CommandLine -match $expected) { exit 0 } }; exit 2"
if errorlevel 2 goto port_in_use
if errorlevel 1 goto start_app
start "" "http://127.0.0.1:8501/"
exit /b 0

:start_app
"%~dp0.venv\Scripts\streamlit.exe" run "%~dp0app.py" --server.address 127.0.0.1 --server.port 8501 --server.headless false
endlocal
exit /b %errorlevel%

:port_in_use
echo Port 8501 is occupied by another process.
echo Close that process and run this launcher again.
pause
exit /b 2
