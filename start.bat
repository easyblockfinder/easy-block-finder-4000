@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

title Easy Block Finder 4000 — EBF4000
echo ============================================
echo   Easy Block Finder 4000  ^(EBF4000^)
echo   Windows launcher
echo ============================================
echo.

set "URL_NVIDIA=https://www.nvidia.com/Download/index.aspx"
set "PICKER=%~dp0scripts\pick_python.py"
set "PATH_FIX_PS1=%~dp0scripts\add_python_user_path.ps1"
set "BUNDLED=%~dp0runtime\python.exe"
set "PYTHON="
set "USING_BUNDLE=0"

REM ========== Prefer shipped runtime (no Python download) ==========
if exist "%BUNDLED%" goto :use_bundle
goto :use_system

:use_bundle
set "PYTHON=%BUNDLED%"
set "USING_BUNDLE=1"
REM Smoke test — use delayed !PYTHON! (%% inside parentheses is empty at parse time)
"!PYTHON!" -c "import sys; print(sys.version.split()[0])" >nul 2>&1
if errorlevel 1 (
  echo [!] Bundled runtime failed smoke test — falling back to system Python.
  set "PYTHON="
  set "USING_BUNDLE=0"
  goto :use_system
)
echo Using bundled Python:
"!PYTHON!" -c "import sys; print(' ', sys.executable); print('  Version:', sys.version.split()[0])"
set "PATH=%~dp0runtime;%~dp0runtime\Scripts;%PATH%"
if not exist "%~dp0runtime\.path_ok" (
  if exist "%PATH_FIX_PS1%" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PATH_FIX_PS1%" -PythonExe "!PYTHON!" -Quiet >nul 2>&1
    if not errorlevel 1 (
      echo.>"%~dp0runtime\.path_ok"
      echo [OK] Bundled Python added to your user PATH.
    )
  )
)
goto :after_python

:use_system
echo [!] No usable bundled runtime\ — looking for a system Python.
echo     Prefer the official Setup / ZIP that ships runtime\.
echo.
call :discover_python
if not defined PYTHON (
  echo [ERROR] Python not found.
  echo.
  echo Install the official Windows Setup from:
  echo   https://github.com/easyblockfinder/easy-block-finder-4000/releases/latest
  echo.
  pause
  exit /b 1
)

if exist "%PICKER%" (
  for /f "delims=" %%I in ('"!PYTHON!" "%PICKER%" 2^>nul') do set "PYTHON=%%I"
)

echo !PYTHON! | findstr /i "python3.13t t.exe" >nul
if not errorlevel 1 (
  echo [ERROR] Free-threaded Python ^(3.13t^) is not supported: !PYTHON!
  pause
  exit /b 1
)

"!PYTHON!" -c "import sys; print('Using system Python:'); print(' ', sys.executable); print('  Version:', sys.version.split()[0])"
if errorlevel 1 (
  echo [ERROR] Could not run: !PYTHON!
  pause
  exit /b 1
)
"!PYTHON!" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 1)"
if errorlevel 1 (
  echo [ERROR] Python 3.10+ required ^(3.12 recommended^).
  pause
  exit /b 1
)

:after_python
echo.

"!PYTHON!" -m pip --version >nul 2>&1
if errorlevel 1 (
  if "!USING_BUNDLE!"=="1" (
    echo [ERROR] Bundled pip missing — reinstall the Setup package.
    pause
    exit /b 1
  )
  echo [!] pip missing — trying ensurepip...
  "!PYTHON!" -m ensurepip --upgrade
  "!PYTHON!" -m pip --version >nul 2>&1
  if errorlevel 1 (
    echo [ERROR] pip could not be installed automatically.
    pause
    exit /b 1
  )
)

echo Checking / installing requirements...
echo.
set "DEPS_MODE="
if /i "%~1"=="force" set "DEPS_MODE=--force"
if /i "%~1"=="cpu" set "DEPS_MODE=--cpu-only"
if /i "%~1"=="cpu-only" set "DEPS_MODE=--cpu-only"

if "!USING_BUNDLE!"=="1" if exist "%~dp0runtime\.deps_ok" if not defined DEPS_MODE (
  echo [OK] Bundled dependencies already prepared.
  goto :launch
)
if "!USING_BUNDLE!"=="1" if exist "%~dp0.deps_ok" if not defined DEPS_MODE (
  echo [OK] Bundled dependencies already prepared.
  goto :launch
)

if defined DEPS_MODE (
  "!PYTHON!" "%~dp0scripts\ensure_deps.py" --quiet !DEPS_MODE!
) else (
  "!PYTHON!" "%~dp0scripts\ensure_deps.py" --quiet
)
if errorlevel 1 (
  echo.
  echo [!] Full GPU check failed — trying CPU-only ^(XMR^)...
  "!PYTHON!" "%~dp0scripts\ensure_deps.py" --quiet --cpu-only
  if errorlevel 1 (
    echo.
    echo [ERROR] Automatic dependency setup failed.
    echo If you extracted a ZIP inside WinRAR/temp, extract to Desktop/Documents first.
    echo GPU driver: %URL_NVIDIA%
    pause
    exit /b 1
  )
  echo.
  echo [!] No usable NVIDIA OpenCL/GPU stack detected.
  echo     BTC/BCH/RVN/ERG may be unavailable; XMR ^(CPU^) can still work.
)

:launch
echo.
echo Starting application...
echo ^(XMRig/Rigel are not bundled — downloaded later only after in-app consent.^)
set "PYTHONPATH=%~dp0src"

set "PYTHONW=!PYTHON!"
if /i "!PYTHON:~-10!"=="python.exe" (
  set "PYTHONW=!PYTHON:~0,-10!pythonw.exe"
)
if not exist "!PYTHONW!" set "PYTHONW=!PYTHON!"

if /i "%~1"=="console" (
  "!PYTHON!" "%~dp0src\main.py"
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

start "" "!PYTHONW!" "%~dp0src\main.py"
endlocal
exit 0


:discover_python
set "PYTHON="
where python >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%I in ('where python 2^>nul') do (
    if not defined PYTHON (
      echo %%I | findstr /i "WindowsApps\\python.exe WindowsApps\\Python.exe" >nul
      if errorlevel 1 set "PYTHON=%%I"
    )
  )
)
if not defined PYTHON (
  where py >nul 2>&1
  if not errorlevel 1 (
    for /f "delims=" %%I in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON=%%I"
    if not defined PYTHON (
      for /f "delims=" %%I in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON=%%I"
    )
  )
)
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PYTHON if exist "%ProgramFiles%\Python312\python.exe" set "PYTHON=%ProgramFiles%\Python312\python.exe"
if defined PYTHON if not exist "%PYTHON%" set "PYTHON="
exit /b 0
