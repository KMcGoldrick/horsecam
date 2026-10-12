@echo off
REM One-time setup: creates a private Python environment next to this file.
cd /d "%~dp0"
where py >nul 2>nul || (echo Python is not installed. Get Python 3.11 or 3.12 from https://www.python.org/downloads/ and tick "Add python.exe to PATH". & pause & exit /b 1)
py -3 -m venv .venv || (pause & exit /b 1)
.venv\Scripts\python -m pip install --upgrade pip
echo.
echo Do you have an NVIDIA graphics card? GPU makes horse detection 10-30x faster.
choice /c YN /m "Install GPU (CUDA) version of PyTorch"
if errorlevel 2 goto cpu
.venv\Scripts\python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
goto rest
:cpu
.venv\Scripts\python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
:rest
.venv\Scripts\python -m pip install -r requirements.txt || (pause & exit /b 1)
echo.
echo Setup complete. Double-click HorseCam.bat to start.
pause
