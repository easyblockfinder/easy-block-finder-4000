@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

title Easy Block Finder 4000 — EBF4000 - v1.0
echo ============================================
echo   Easy Block Finder 4000  (EBF4000 - v1.0)
echo   Solo mining — no CUDA Toolkit
echo ============================================
echo.

REM --- Pick a Python with deps (prefer 3.12; not 3.13t) ---
set "PYTHON="
set "PICKER=%~dp0scripts\pick_python.py"

REM Try PATH python first
where python >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%I in ('python "%PICKER%" 2^>nul') do set "PYTHON=%%I"
)

REM py launcher fallback
if not defined PYTHON (
  where py >nul 2>&1
  if not errorlevel 1 (
    for /f "delims=" %%I in ('py -3 "%PICKER%" 2^>nul') do set "PYTHON=%%I"
  )
)

REM Last resort: raw python / py path
if not defined PYTHON (
  where python >nul 2>&1
  if not errorlevel 1 (
    for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON=%%I"
  )
)

if not defined PYTHON (
  echo [ERROR] No suitable Python found.
  echo.
  echo Packages may be installed under C:\Python312 on this machine.
  echo Put Python 3.10-3.12 on PATH; do not use free-threaded 3.13t.
  echo https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

REM Reject 3.13t free-threaded builds
echo %PYTHON% | findstr /i "python3.13t t.exe" >nul
if not errorlevel 1 (
  echo [ERROR] Selected interpreter is free-threaded ^(3.13t^): %PYTHON%
  echo PyQt6 has no ready wheel on this build. Use C:\Python312\python.exe.
  echo.
  pause
  exit /b 1
)

echo Using Python:
"%PYTHON%" -c "import sys; print(' ', sys.executable); print('  Version:', sys.version.split()[0])"
if errorlevel 1 (
  echo [ERROR] Could not run Python: %PYTHON%
  pause
  exit /b 1
)
echo.

"%PYTHON%" -m pip --version >nul 2>&1
if errorlevel 1 (
  echo [!] pip missing; trying ensurepip...
  "%PYTHON%" -m ensurepip --upgrade
  "%PYTHON%" -m pip --version >nul 2>&1
  if errorlevel 1 (
    echo [ERROR] pip install failed.
    pause
    exit /b 1
  )
)

echo Checking requirements...
echo.
set "DEPS_MODE="
if /i "%~1"=="force" set "DEPS_MODE=--force"
if /i "%~1"=="cpu" set "DEPS_MODE=--cpu-only"
if /i "%~1"=="cpu-only" set "DEPS_MODE=--cpu-only"

if defined DEPS_MODE (
  "%PYTHON%" "%~dp0scripts\ensure_deps.py" --quiet %DEPS_MODE%
) else (
  "%PYTHON%" "%~dp0scripts\ensure_deps.py" --quiet
)
if errorlevel 1 (
  echo.
  echo [!] Full GPU check failed — trying CPU-only ^(XMR^)...
  "%PYTHON%" "%~dp0scripts\ensure_deps.py" --quiet --cpu-only
  if errorlevel 1 (
    echo.
    echo [ERROR] Requirements could not be completed.
    echo Full check: start.bat force
    echo CPU-only: start.bat cpu
    echo Wrong Python path? Try:
    echo   C:\Python312\python.exe scripts\ensure_deps.py --force
    pause
    exit /b 1
  )
  echo [!] No GPU / OpenCL — BTC/BCH/RVN/ERG unavailable; XMR can be selected.
)

REM Miners are NOT bundled and NOT auto-downloaded here.
REM After UI consent, only the engine for the network you Start is fetched.
echo.
echo Starting application...
set "PYTHONPATH=%~dp0src"

REM Prefer pythonw.exe so no black console sticks next to the GUI.
set "PYTHONW=%PYTHON%"
if /i "%PYTHON:~-10%"=="python.exe" (
  set "PYTHONW=%PYTHON:~0,-10%pythonw.exe"
)
if not exist "%PYTHONW%" set "PYTHONW=%PYTHON%"

REM Detach GUI and close this CMD window (use: start.bat console to keep it).
if /i "%~1"=="console" (
  "%PYTHON%" "%~dp0src\main.py"
  set "ERR=!ERRORLEVEL!"
  if not "!ERR!"=="0" (
    echo.
    echo [ERROR] Application exit code: !ERR!
    pause
    exit /b !ERR!
  )
  endlocal
  exit /b 0
)

start "" "%PYTHONW%" "%~dp0src\main.py"
endlocal
exit /b 0