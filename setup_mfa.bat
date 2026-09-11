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
conda run -n moracutter-mfa python -m pip install --upgrade "joblib==1.3.2" "setuptools==68.2.2" "soundfile==0.12.1"
if errorlevel 1 (
  echo MFA compatibility dependency installation failed.
  pause
  exit /b 1
)
conda install -y -n moracutter-mfa -c conda-forge spacy sudachipy sudachidict-core
if errorlevel 1 (
  echo Japanese tokenizer installation failed.
  pause
  exit /b 1
)
REM MFA 3.0.0 passes pathlib.Path to SudachiPy. SudachiPy 0.6.11 requires str.
conda run -n moracutter-mfa python -c "from pathlib import Path; import montreal_forced_aligner as m; p=Path(m.__file__).parent/'tokenization'/'japanese.py'; p.write_text(p.read_text(encoding='utf-8').replace('config_path=config_path', 'config_path=str(config_path)'), encoding='utf-8')"
if errorlevel 1 (
  echo MFA Japanese compatibility update failed.
  pause
  exit /b 1
)
echo MFA setup completed. Restart Mora Cutter before using MFA Japanese.
pause
