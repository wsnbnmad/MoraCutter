@echo off
setlocal
where conda >nul 2>nul
if errorlevel 1 (
  echo MFA requires Miniforge or Conda on Windows.
  echo Install Miniforge, reopen this window, then run this file again.
  echo https://github.com/conda-forge/miniforge
  pause
  exit /b 1
)
echo Creating the dedicated MFA 3.0.0 environment. This can take several minutes.
conda create -y -n moracutter-mfa -c conda-forge montreal-forced-aligner=3.0.0
if errorlevel 1 (
  echo MFA installation failed. See the message above.
  pause
  exit /b 1
)
conda run -n moracutter-mfa mfa --help
echo MFA setup completed. Restart Mora Cutter before using MFA Japanese.
pause
