@echo off
setlocal
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or later first.
  pause
  exit /b 1
)
where nvidia-smi >nul 2>nul
if errorlevel 1 (
  echo NVIDIA GPU driver was not found. GPU acceleration cannot be installed.
  pause
  exit /b 1
)
echo Installing the CUDA 12.8 build of PyTorch for NVIDIA GPUs...
python -m pip install --upgrade torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 (
  echo Installation failed. See the message above.
  pause
  exit /b 1
)
python -c "import torch; print('CUDA available:', torch.cuda.is_available()); print('CUDA build:', torch.version.cuda)"
pause
