@echo off
REM One-click install from an extracted release folder (Python already bundled in runtime\).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_windows.ps1" -SourceDir "%~dp0"
exit /b %ERRORLEVEL%
