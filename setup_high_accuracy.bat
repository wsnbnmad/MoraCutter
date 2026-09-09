@echo off
setlocal
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or later first.
  pause
  exit /b 1
)
echo Installing optional high-accuracy recognition dependencies...
python -m pip install -r "%~dp0requirements-high-accuracy.txt"
if errorlevel 1 (
  echo Installation failed. See the message above.
  pause
  exit /b 1
)
echo Installation completed. Start Mora Cutter with run_windows.bat.
pause
