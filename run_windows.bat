@echo off
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or later.
  pause
  exit /b 1
)
python -c "import numpy" >nul 2>nul
if errorlevel 1 python -m pip install numpy
python "%~dp0main.py"

