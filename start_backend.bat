@echo off
setlocal

set "ENV_NAME=%APP_CONDA_ENV%"
if "%ENV_NAME%"=="" set "ENV_NAME=any-auto-register"
set "HOST=%HOST%"
if "%HOST%"=="" set "HOST=0.0.0.0"
set "PORT=%PORT%"
if "%PORT%"=="" set "PORT=8000"
set "RESTART_EXISTING=%RESTART_EXISTING%"
if "%RESTART_EXISTING%"=="" set "RESTART_EXISTING=1"

where conda >nul 2>nul
if errorlevel 1 (
  echo [ERROR] not found conda Order. Please install first Miniconda/Anaconda, and ensure conda Available in Terminal.
  exit /b 1
)

cd /d "%~dp0"
echo [INFO] Project directory: %CD%
echo [INFO] use conda environment: %ENV_NAME%
echo [INFO] Start backend: http://localhost:%PORT%
echo [INFO] according to Ctrl+C Can stop service

if "%RESTART_EXISTING%"=="1" (
  echo [INFO] Clean old backend before launching / Solver process
  powershell -ExecutionPolicy Bypass -File "%~dp0stop_backend.ps1" -BackendPort %PORT% -SolverPort 8889 -FullStop 0
)

for /f "usebackq delims=" %%i in (`conda run --no-capture-output -n %ENV_NAME% python -c "import sys; print(sys.executable)"`) do set "PYTHON_EXE=%%i"

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Unable to parse conda environment "%ENV_NAME%" Corresponding python path.
  exit /b 1
)

set "HOST=%HOST%"
set "PORT=%PORT%"
set "PYTHONIOENCODING=utf-8"
echo [INFO] Python: %PYTHON_EXE%
"%PYTHON_EXE%" main.py
