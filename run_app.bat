@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\streamlit.exe" (
  echo Voltage Envelopes environment not found.
  echo Create .venv and install the pinned packages from requirements.txt before launching.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\streamlit.exe" run "%~dp0app.py" --server.address 127.0.0.1 --server.port 8501
endlocal
