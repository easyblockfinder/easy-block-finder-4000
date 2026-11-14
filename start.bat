@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

title Easy Block Finder 4000 — EBF4000 - v1.0
echo ============================================
echo   Easy Block Finder 4000  ^(EBF4000 - v1.0^)
echo   First-run setup — Windows
echo ============================================
echo.

REM Official download helpers ^(opened in browser when setup fails^)
set "URL_PYTHON_PAGE=https://www.python.org/downloads/windows/"
set "URL_NVIDIA=https://www.nvidia.com/Download/index.aspx"
set "URL_PIP=https://pip.pypa.io/en/stable/installation/"

REM Pick Python 3.12 installer for this PC ^(amd64 / arm64 / win32^)
set "PY_ARCH=amd64"
set "PY_ARCH_LABEL=64-bit ^(x86-64^)"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
  set "PY_ARCH=arm64"
  set "PY_ARCH_LABEL=64-bit ^(ARM64^)"
) else if /i "%PROCESSOR_ARCHITECTURE%"=="x86" (
  if /i not "%PROCESSOR_ARCHITEW6432%"=="AMD64" if /i not "%PROCESSOR_ARCHITEW6432%"=="ARM64" (
    set "PY_ARCH=win32"
    set "PY_ARCH_LABEL=32-bit"
  )
)
if /i "%PY_ARCH%"=="win32" (
  set "URL_PYTHON_312=https://www.python.org/ftp/python/3.12.10/python-3.12.10.exe"
) else (
  set "URL_PYTHON_312=https://www.python.org/ftp/python/3.12.10/python-3.12.10-%PY_ARCH%.exe"
)

REM --- Pick a Python ^(prefer 3.12; not free-threaded 3.13t^) ---
set "PYTHON="
set "PICKER=%~dp0scripts\pick_python.py"

where python >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%I in ('python "%PICKER%" 2^>nul') do set "PYTHON=%%I"
)

if not defined PYTHON (
  where py >nul 2>&1
  if not errorlevel 1 (
    for /f "delims=" %%I in ('py -3 "%PICKER%" 2^>nul') do set "PYTHON=%%I"
  )
)

if not defined PYTHON (
  where python >nul 2>&1
  if not errorlevel 1 (
    for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON=%%I"
  )
)

if not defined PYTHON (
  call :guide_python_missing
  exit /b 1
)

echo %PYTHON% | findstr /i "python3.13t t.exe" >nul
if not errorlevel 1 (
  echo [ERROR] Free-threaded Python ^(3.13t^) is not supported: %PYTHON%
  echo PyQt6 has no ready wheel for that build.
  echo.
  call :guide_python_install "Install regular Python 3.12 ^(64-bit^), not 3.13t."
  exit /b 1
)

echo Using Python:
"%PYTHON%" -c "import sys; print(' ', sys.executable); print('  Version:', sys.version.split()[0])"
if errorlevel 1 (
  echo [ERROR] Could not run: %PYTHON%
  call :guide_python_install "Reinstall Python 3.12 and tick 'Add python.exe to PATH'."
  exit /b 1
)

"%PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 1)"
if errorlevel 1 (
  echo [ERROR] Python 3.10+ required ^(3.12 recommended^).
  call :guide_python_install "Your Python is too old."
  exit /b 1
)
echo.

"%PYTHON%" -m pip --version >nul 2>&1
if errorlevel 1 (
  echo [!] pip missing — trying ensurepip...
  "%PYTHON%" -m ensurepip --upgrade
  "%PYTHON%" -m pip --version >nul 2>&1
  if errorlevel 1 (
    echo [ERROR] pip could not be installed automatically.
    echo.
    echo Fix:
    echo   1. Reinstall Python 3.12 from the official installer
    echo   2. Enable "pip" / "Add python.exe to PATH"
    echo   3. Or see: %URL_PIP%
    echo.
    choice /C YN /M "Open pip installation help in your browser"
    if not errorlevel 2 start "" "%URL_PIP%"
    call :guide_python_install ""
    exit /b 1
  )
)

echo Checking / installing requirements...
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
    echo [ERROR] Automatic dependency setup failed.
    call :guide_deps_failed
    exit /b 1
  )
  echo.
  echo [!] No usable NVIDIA OpenCL/GPU stack detected.
  echo     BTC/BCH/RVN/ERG may be unavailable; XMR ^(CPU^) can still work.
  echo     GPU driver: %URL_NVIDIA%
  choice /C YN /M "Open NVIDIA driver download page"
  if not errorlevel 2 start "" "%URL_NVIDIA%"
  echo.
)

echo.
echo Starting application...
echo ^(XMRig/Rigel are not bundled — downloaded later only after in-app consent.^)
set "PYTHONPATH=%~dp0src"

set "PYTHONW=%PYTHON%"
if /i "%PYTHON:~-10%"=="python.exe" (
  set "PYTHONW=%PYTHON:~0,-10%pythonw.exe"
)
if not exist "%PYTHONW%" set "PYTHONW=%PYTHON%"

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

REM Launch GUI detached, then close this console (do not leave a stuck CMD)
start "" "%PYTHONW%" "%~dp0src\main.py"
endlocal
exit 0


REM ========== Guides ==========

:guide_python_missing
echo [ERROR] No suitable Python found on this PC.
echo.
echo Easy Block Finder 4000 needs Python 3.10–3.12.
echo Recommended: Python 3.12 %PY_ARCH_LABEL% for this PC.
echo Auto-install is not available from this script.
echo.
echo Do this:
echo   1. Download the installer matched to this PC ^(link below^)
echo   2. *** IMPORTANT *** On the FIRST installer screen, tick:
echo        [x] Add python.exe to PATH
echo      ^(Without this, start.bat will not find Python after install.^)
echo   3. Close this window, open a NEW terminal, run start.bat again
echo.
echo Avoid: Python 3.13t / free-threaded builds ^(PyQt6 wheels missing^).
echo.
echo Download page:     %URL_PYTHON_PAGE%
echo Direct 3.12 %PY_ARCH%: %URL_PYTHON_312%
echo.
choice /C YN /M "Open Python 3.12 download for this PC now"
if not errorlevel 2 (
  start "" "%URL_PYTHON_PAGE%"
  start "" "%URL_PYTHON_312%"
)
echo.
pause
exit /b 0

:guide_python_install
if not "%~1"=="" echo %~1
echo.
echo Download page:     %URL_PYTHON_PAGE%
echo Direct 3.12 %PY_ARCH%: %URL_PYTHON_312%
echo.
echo *** IMPORTANT *** Reinstall and tick "Add python.exe to PATH"
echo on the first installer screen, then reopen start.bat in a NEW window.
echo.
choice /C YN /M "Open Python download for this PC now"
if not errorlevel 2 (
  start "" "%URL_PYTHON_PAGE%"
  start "" "%URL_PYTHON_312%"
)
echo.
pause
exit /b 0

:guide_deps_failed
echo.
echo What to try next:
echo.
echo  1^) Python / pip packages
echo     "%PYTHON%" -m pip install -r "%~dp0requirements.txt"
echo     If that fails, reinstall Python 3.12 with PATH enabled:
echo     %URL_PYTHON_312%
echo.
echo  2^) NVIDIA GPU networks ^(BTC/BCH/RVN/ERG^)
echo     Install a current Game Ready / Studio driver ^(includes OpenCL^):
echo     %URL_NVIDIA%
echo     Then run:  start.bat force
echo.
echo  3^) CPU-only Monero
echo     start.bat cpu
echo.
choice /C 123N /M "Open [1] Python  [2] NVIDIA  [3] both  [N] nothing"
if errorlevel 4 goto :guide_deps_end
if errorlevel 3 (
  start "" "%URL_PYTHON_PAGE%"
  start "" "%URL_PYTHON_312%"
  start "" "%URL_NVIDIA%"
  goto :guide_deps_end
)
if errorlevel 2 (
  start "" "%URL_NVIDIA%"
  goto :guide_deps_end
)
if errorlevel 1 (
  start "" "%URL_PYTHON_PAGE%"
  start "" "%URL_PYTHON_312%"
  goto :guide_deps_end
)
:guide_deps_end
echo.
pause
exit /b 0
