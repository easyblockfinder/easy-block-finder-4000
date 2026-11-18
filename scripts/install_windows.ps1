# Portable/first-run installer when Inno Setup.exe is unavailable.
# Extracts/copies the app into %LOCALAPPDATA%\EasyBlockFinder4000\app,
# adds bundled Python to user PATH, creates Start Menu + Desktop shortcuts, launches.
param(
    [string]$SourceDir = "",
    [switch]$NoLaunch,
    [switch]$NoDesktop
)

$ErrorActionPreference = "Stop"
if (-not $SourceDir) {
    $SourceDir = Split-Path -Parent $PSScriptRoot
}
$SourceDir = [System.IO.Path]::GetFullPath($SourceDir)
$Bundled = Join-Path $SourceDir "runtime\python.exe"
if (-not (Test-Path -LiteralPath $Bundled)) {
    throw "Bundled runtime missing: $Bundled — use the official release package."
}

$Dest = Join-Path $env:LOCALAPPDATA "EasyBlockFinder4000\app"
Write-Host "Installing Easy Block Finder 4000 -> $Dest"

New-Item -ItemType Directory -Force -Path $Dest | Out-Null
# Robocopy mirrors payload (runtime included)
$rc = Start-Process -FilePath "robocopy.exe" -ArgumentList @(
    "`"$SourceDir`"", "`"$Dest`"", "/E", "/XD", "__pycache__", ".git",
    "/XF", "*.pyc", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"
) -Wait -PassThru
# robocopy exit 0-7 = success
if ($rc.ExitCode -ge 8) { throw "robocopy failed with code $($rc.ExitCode)" }

$PathScript = Join-Path $Dest "scripts\add_python_user_path.ps1"
$Py = Join-Path $Dest "runtime\python.exe"
if (Test-Path -LiteralPath $PathScript) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $PathScript -PythonExe $Py -Quiet
}

$Wsh = New-Object -ComObject WScript.Shell
$StartBat = Join-Path $Dest "start.bat"
$Programs = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Easy Block Finder 4000"
New-Item -ItemType Directory -Force -Path $Programs | Out-Null
$lnk = $Wsh.CreateShortcut((Join-Path $Programs "Easy Block Finder 4000.lnk"))
$lnk.TargetPath = $StartBat
$lnk.WorkingDirectory = $Dest
$ico = Join-Path $Dest "assets\ebf4000_icon.ico"
if (Test-Path -LiteralPath $ico) { $lnk.IconLocation = $ico }
$lnk.Save()

if (-not $NoDesktop) {
    $desk = [Environment]::GetFolderPath("Desktop")
    $dlnk = $Wsh.CreateShortcut((Join-Path $desk "Easy Block Finder 4000.lnk"))
    $dlnk.TargetPath = $StartBat
    $dlnk.WorkingDirectory = $Dest
    if (Test-Path -LiteralPath $ico) { $dlnk.IconLocation = $ico }
    $dlnk.Save()
}

Write-Host "Install complete."
if (-not $NoLaunch) {
    Start-Process -FilePath $StartBat -WorkingDirectory $Dest
}
exit 0
