@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

title Easy Block Finder 4000 — EBF4000
echo ============================================
echo   Easy Block Finder 4000  ^(EBF4000^)
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

set "PICKER=%~dp0scripts\pick_python.py"
set "PATH_FIX_PS1=%~dp0scripts\add_python_user_path.ps1"
set "PYTHON="
set "PYTHON_FROM_PATH=0"

call :discover_python
if not defined PYTHON (
  echo [!] Python not found on PATH or in common install folders.
  echo.
  call :offer_python_auto_install
  call :discover_python
)
if not defined PYTHON (
  call :guide_python_missing
  call :discover_python
)
if not defined PYTHON (
  echo [ERROR] Still no usable Python. Close this window and try again after installing.
  pause
  exit /b 1
)

REM Prefer pick_python ranking when we have a working interpreter
if exist "%PICKER%" (
  for /f "delims=" %%I in ('"%PYTHON%" "%PICKER%" 2^>nul') do set "PYTHON=%%I"
)

echo %PYTHON% | findstr /i "python3.13t t.exe" >nul
if not errorlevel 1 (
  echo [ERROR] Free-threaded Python ^(3.13t^) is not supported: %PYTHON%
  echo PyQt6 has no ready wheel for that build.
  echo.
  call :guide_python_install "Install regular Python 3.12 ^(64-bit^), not 3.13t."
  exit /b 1
)

call :ensure_python_on_path

echo Using Python:
"%PYTHON%" -c "import sys; print(' ', sys.executable); print('  Version:', sys.version.split()[0])"
if errorlevel 1 (
  echo [ERROR] Could not run: %PYTHON%
  call :guide_python_install "Reinstall Python 3.12 ^(PATH is added automatically if you use start.bat auto-install^)."
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
    echo   2. Or run start.bat again and choose auto-install ^(adds PATH for you^)
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


REM ========== Python discovery / PATH / install ==========

:discover_python
set "PYTHON="
set "PYTHON_FROM_PATH=0"

REM 1) Already on PATH
where python >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%I in ('where python 2^>nul') do (
    if not defined PYTHON (
      echo %%I | findstr /i "WindowsApps\\python.exe WindowsApps\\Python.exe" >nul
      if errorlevel 1 (
        set "PYTHON=%%I"
        set "PYTHON_FROM_PATH=1"
      )
    )
  )
)

REM 2) py launcher ^(works even when python.exe is not on PATH^)
if not defined PYTHON (
  where py >nul 2>&1
  if not errorlevel 1 (
    for /f "delims=" %%I in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON=%%I"
    if not defined PYTHON (
      for /f "delims=" %%I in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON=%%I"
    )
  )
)

REM 3) Common install folders — even if "Add to PATH" was unticked
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PYTHON if exist "%ProgramFiles%\Python312\python.exe" set "PYTHON=%ProgramFiles%\Python312\python.exe"
if not defined PYTHON if exist "%ProgramFiles%\Python311\python.exe" set "PYTHON=%ProgramFiles%\Python311\python.exe"
if not defined PYTHON if exist "C:\Python312\python.exe" set "PYTHON=C:\Python312\python.exe"
if not defined PYTHON if exist "C:\Python311\python.exe" set "PYTHON=C:\Python311\python.exe"
if not defined PYTHON if exist "C:\Python310\python.exe" set "PYTHON=C:\Python310\python.exe"

if defined PYTHON (
  if not exist "%PYTHON%" set "PYTHON="
)
exit /b 0


:ensure_python_on_path
REM Make this session + optionally permanent User PATH see python.exe
for %%I in ("%PYTHON%") do set "PY_DIR=%%~dpI"
set "PY_DIR=%PY_DIR:~0,-1%"

where python >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%I in ('where python 2^>nul') do (
    if /i "%%~fI"=="%PYTHON%" (
      echo Python is on PATH for this session.
      exit /b 0
    )
  )
)

echo.
echo [!] Python was found, but it is NOT on PATH:
echo     %PYTHON%
echo     ^(Installer checkbox "Add python.exe to PATH" was probably skipped.^)
echo.
REM Fix this CMD session immediately
set "PATH=%PY_DIR%;%PY_DIR%\Scripts;%PATH%"
echo [OK] Added to PATH for THIS window so setup can continue.
echo.

if exist "%PATH_FIX_PS1%" (
  choice /C YN /M "Also add Python to your user PATH permanently so future windows find it"
  if not errorlevel 2 (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PATH_FIX_PS1%" -PythonExe "%PYTHON%"
    if errorlevel 1 (
      echo [!] Could not update user PATH automatically. This start.bat window will still work.
    ) else (
      echo [OK] User PATH updated. New terminals will find python without re-checking.
    )
  ) else (
    echo Skipped permanent PATH fix. You can re-run start.bat later to add it.
  )
)
echo.
exit /b 0


:offer_python_auto_install
echo Easy Block Finder 4000 needs Python 3.10–3.12 ^(%PY_ARCH_LABEL% recommended^).
echo.
echo You can let start.bat download and install official Python 3.12
echo WITH PATH enabled automatically ^(no need to tick the checkbox^).
echo.
choice /C YN /M "Download and install Python 3.12 now with PATH enabled"
if errorlevel 2 (
  echo.
  echo Skipping auto-install.
  exit /b 1
)

set "PY_SETUP=%TEMP%\EBF4000-python-3.12.10-setup.exe"
echo.
echo Downloading:
echo   %URL_PYTHON_312%
echo.

where curl >nul 2>&1
if not errorlevel 1 (
  curl -L --retry 3 --retry-delay 2 -o "%PY_SETUP%" "%URL_PYTHON_312%"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri '%URL_PYTHON_312%' -OutFile '%PY_SETUP%'"
)
if not exist "%PY_SETUP%" (
  echo [ERROR] Download failed.
  exit /b 1
)

echo.
echo Installing Python 3.12 ^(per-user, PrependPath=1, Include launcher + pip^)...
echo Please wait — a progress window may appear.
echo.
"%PY_SETUP%" /passive InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1 Include_test=0 SimpleInstall=1
set "INST_ERR=!ERRORLEVEL!"
echo Installer exit code: !INST_ERR!
echo.

REM Refresh PATH from registry for this session
for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')"`) do set "PATH=%%A"

call :discover_python
if defined PYTHON (
  echo [OK] Python installed and detected:
  echo     %PYTHON%
  call :ensure_python_on_path
  exit /b 0
)

echo [!] Install finished but Python still not detected in this window.
echo     Close this CMD, open a NEW one, and run start.bat again.
exit /b 1


REM ========== Guides ==========

:guide_python_missing
echo [ERROR] No suitable Python found on this PC.
echo.
echo Easy Block Finder 4000 needs Python 3.10–3.12.
echo Recommended: Python 3.12 %PY_ARCH_LABEL% for this PC.
echo.
echo Easiest fix: run start.bat again and choose YES when asked to
echo auto-install Python 3.12 — PATH is enabled for you ^(PrependPath=1^).
echo.
echo Manual install:
echo   1. Download: %URL_PYTHON_312%
echo   2. On the FIRST screen tick [x] Add python.exe to PATH
echo      OR just re-run start.bat auto-install so you do not need that checkbox.
echo   3. Open a NEW terminal and run start.bat again
echo.
echo Avoid: Python 3.13t / free-threaded builds ^(PyQt6 wheels missing^).
echo.
choice /C YN /M "Try auto-install Python 3.12 with PATH now"
if not errorlevel 2 (
  call :offer_python_auto_install
  call :discover_python
  if defined PYTHON exit /b 0
)
choice /C YN /M "Open Python download page in browser instead"
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
echo Recommended: run start.bat and accept auto-install ^(PATH is set for you^).
echo Or download: %URL_PYTHON_312%
echo If installing manually, tick "Add python.exe to PATH" on the first screen.
echo.
choice /C YN /M "Auto-install Python 3.12 with PATH now"
if not errorlevel 2 (
  call :offer_python_auto_install
  exit /b 0
)
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
echo     Or re-run start.bat and use Python auto-install ^(PATH included^):
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
