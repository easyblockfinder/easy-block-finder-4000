# Assemble Windows payload (app + bundled runtime), ZIP, and optional Inno Setup installer.
param(
    [string]$Version = "",
    [switch]$SkipRuntimePrepare,
    [switch]$SkipInstaller,
    [switch]$ForceRuntime
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

if (-not $Version) {
    $meta = Get-Content (Join-Path $Root "src\app_meta.py") -Raw
    if ($meta -match 'APP_VERSION\s*=\s*"([^"]+)"') { $Version = $Matches[1] }
    else { throw "Could not read APP_VERSION from src/app_meta.py" }
}

$Runtime = Join-Path $Root "runtime"
$Dist = Join-Path $Root "dist"
$Payload = Join-Path $Dist "EBF4000-v$Version-windows"
$ZipPath = Join-Path $Dist "EBF4000-v$Version-windows.zip"
$SetupOut = Join-Path $Dist "EBF4000-v$Version-windows-setup.exe"

Write-Host "=== EBF4000 Windows release build v$Version ==="

# GUI launcher exe (preferred entry point for end users)
$launchBuild = Join-Path $PSScriptRoot "build_launcher.ps1"
& $launchBuild -OutDir $Root
if ($LASTEXITCODE -ne 0) { throw "build_launcher failed" }

# Inno Setup needs assets\ebf4000_icon.ico — build_launcher.ps1 already writes a
# csc-compatible multi-size ICO from PNG. Keep a soft check for installer builds.
$IcoIcon = Join-Path $Root "assets\ebf4000_icon.ico"
if (-not (Test-Path -LiteralPath $IcoIcon)) {
    Write-Warning "assets\ebf4000_icon.ico missing after launcher build; Inno may lack SetupIcon"
}

if (-not $SkipRuntimePrepare) {
    $prep = Join-Path $PSScriptRoot "prepare_embedded_python.ps1"
    if ($ForceRuntime) {
        & $prep -Force
    } else {
        & $prep
    }
    if ($LASTEXITCODE -ne 0) { throw "prepare_embedded_python failed" }
}

if (-not (Test-Path -LiteralPath (Join-Path $Runtime "python.exe"))) {
    throw "Missing bundled runtime at $Runtime — run prepare_embedded_python.ps1 first"
}

if (Test-Path -LiteralPath $Payload) { Remove-Item -LiteralPath $Payload -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Payload | Out-Null

$copyDirs = @("src", "scripts", "assets", "runtime")
foreach ($d in $copyDirs) {
    $src = Join-Path $Root $d
    if (-not (Test-Path -LiteralPath $src)) { throw "Missing: $src" }
    Write-Host "Copy $d ..."
    Copy-Item -LiteralPath $src -Destination (Join-Path $Payload $d) -Recurse -Force
}

# Official miner pin file (XMR/RVN/ERG downloads). Required next to src/ for fetch_miner.
$lockSrc = Join-Path $Root "third_party\miners.lock.json"
$lockDstDir = Join-Path $Payload "third_party"
if (-not (Test-Path -LiteralPath $lockSrc)) {
    throw "Missing third_party\miners.lock.json — external miner catalog required"
}
New-Item -ItemType Directory -Force -Path $lockDstDir | Out-Null
Copy-Item -LiteralPath $lockSrc -Destination (Join-Path $lockDstDir "miners.lock.json") -Force
Write-Host "Copy third_party\miners.lock.json ..."

$rootFiles = @(
    "EBF4000.exe", "start.bat", "Install.bat", "requirements.txt", "requirements-runtime.txt",
    "LICENSE", "README.md", "DISCLAIMER.md", "SECURITY.md", "DONATE.md",
    "TRADEMARKS.md", "THIRD_PARTY_NOTICES.md", "RELEASE_SIGNING.md"
)
if (-not (Test-Path -LiteralPath (Join-Path $Root "EBF4000.exe"))) {
    throw "EBF4000.exe missing — build_launcher.ps1 must succeed first"
}
foreach ($f in $rootFiles) {
    $p = Join-Path $Root $f
    if (Test-Path -LiteralPath $p) {
        Copy-Item -LiteralPath $p -Destination (Join-Path $Payload $f) -Force
    }
}

# Drop caches from payload
Get-ChildItem -LiteralPath $Payload -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
Get-ChildItem -LiteralPath $Payload -Recurse -File -Filter "*.pyc" -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue }

# Bundle marker at payload root (start.bat also checks runtime\.deps_ok)
Copy-Item -LiteralPath (Join-Path $Runtime ".deps_ok") -Destination (Join-Path $Payload ".deps_ok") -Force -ErrorAction SilentlyContinue

# Drop non-runtime junk that blows past MAX_PATH and bloats the ZIP
Get-ChildItem -LiteralPath (Join-Path $Payload "runtime") -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Extension -match '\.(c|h|f|f90|pyx|pxd)$' -or
        $_.Name -match '(^|\.)(test_|_test\.|tests\.|\.pyc$)' -or
        $_.FullName -match '\\(tests|testing|__pycache__|examples|benchmarks)\\'
    } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue }

Write-Host "Creating ZIP: $ZipPath"
$ZipTmp = "$ZipPath.tmp"
if (Test-Path -LiteralPath $ZipTmp) { Remove-Item -LiteralPath $ZipTmp -Force -ErrorAction SilentlyContinue }
# Compress-Archive fails on long numpy paths — use Python zipfile instead
$zipPy = @"
import os, zipfile, sys
from pathlib import Path
payload = Path(r'$Payload')
zip_tmp = Path(r'$ZipTmp')
zip_path = Path(r'$ZipPath')
root = payload.parent
files = []
for dirpath, dirnames, filenames in os.walk(payload):
    dirnames[:] = [d for d in dirnames if d != '__pycache__']
    for fn in filenames:
        full = Path(dirpath) / fn
        if full.is_file():
            files.append(full)
missing = 0
with zipfile.ZipFile(zip_tmp, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for full in files:
        if not full.is_file():
            missing += 1
            continue
        arc = full.relative_to(root).as_posix()
        try:
            zf.write(full, arc)
        except FileNotFoundError:
            missing += 1
if zip_path.exists():
    try:
        zip_path.unlink()
    except OSError:
        bak = zip_path.with_suffix(zip_path.suffix + '.bak')
        if bak.exists():
            try: bak.unlink()
            except OSError: pass
        try:
            zip_path.rename(bak)
        except OSError as exc:
            print('ZIP_REPLACE_FAIL', exc)
            sys.exit(2)
zip_tmp.replace(zip_path)
print('ZIP_OK', zip_path, 'bytes', zip_path.stat().st_size, 'missing_skipped', missing)
"@
$zipPyPath = Join-Path $Dist "_zip_payload.py"
# UTF8NoBOM — a UTF-8 BOM breaks the leading import when py runs the temp script
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($zipPyPath, $zipPy, $utf8NoBom)
& py -3 $zipPyPath
$zipExit = $LASTEXITCODE
Remove-Item -LiteralPath $zipPyPath -Force -ErrorAction SilentlyContinue
if ($zipExit -ne 0 -or -not (Test-Path -LiteralPath $ZipPath)) {
    throw "Python ZIP creation failed (exit=$zipExit)"
}

function Find-ISCC {
    # Prefer a full Inno install; skip IDE-bundled ISCC (often fails on large payloads).
    $candidates = @(
        (Join-Path $Root "build\tools\InnoSetup6\ISCC.exe"),
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe"
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c)) { return $c }
    }
    return $null
}

function Install-InnoSetup {
    $cache = Join-Path $Root "build\cache"
    $tools = Join-Path $Root "build\tools\InnoSetup6"
    New-Item -ItemType Directory -Force -Path $cache | Out-Null
    $setup = Join-Path $cache "innosetup-6.7.4.exe"
    $url = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_4/innosetup-6.7.4.exe"
    if (-not (Test-Path -LiteralPath $setup) -or ((Get-Item $setup).Length -lt 1MB)) {
        Write-Host "Downloading Inno Setup 6.7.4 ..."
        try {
            Invoke-WebRequest -Uri $url -OutFile $setup -UseBasicParsing
        } catch {
            Write-Warning "Could not download Inno Setup: $_"
            return $null
        }
    }
    Write-Host "Installing Inno Setup into build\tools\InnoSetup6 (no admin)..."
    New-Item -ItemType Directory -Force -Path $tools | Out-Null
    $p = Start-Process -FilePath $setup -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
        "/DIR=`"$tools`""
    ) -Wait -PassThru
    Write-Host "Inno installer exit: $($p.ExitCode)"
    $found = Join-Path $tools "ISCC.exe"
    if (Test-Path -LiteralPath $found) { return $found }
    return (Find-ISCC)
}

if (-not $SkipInstaller) {
    $iss = Join-Path $Root "installer\ebf4000.iss"
    if (-not (Test-Path -LiteralPath $iss)) { throw "Missing $iss" }

    $iscc = Find-ISCC
    if (-not $iscc) {
        $wg = Get-Command winget -ErrorAction SilentlyContinue
        if ($wg) {
            Write-Host "Inno Setup 6 not found — trying winget..."
            try {
                & winget install --id JRSoftware.InnoSetup -e --accept-package-agreements --accept-source-agreements
            } catch {
                Write-Warning "winget install failed: $_"
            }
            $iscc = Find-ISCC
        }
    }
    if (-not $iscc) {
        $iscc = Install-InnoSetup
    }

    if ($iscc) {
        Write-Host "Compiling installer with $iscc"
        & $iscc "/DMyAppVersion=$Version" "/DPayloadDir=$Payload" "/DDistDir=$Dist" $iss
        if ($LASTEXITCODE -ne 0) { throw "ISCC failed ($LASTEXITCODE)" }
        if (-not (Test-Path -LiteralPath $SetupOut)) {
            throw "Setup.exe not produced at $SetupOut"
        }
        Write-Host "Setup ready: $SetupOut"
    } else {
        Write-Warning "ISCC.exe not available — writing PowerShell bootstrap setup next to ZIP."
        $boot = Join-Path $Dist "EBF4000-v$Version-windows-setup.cmd"
        @"
@echo off
setlocal
cd /d "%~dp0"
echo Easy Block Finder 4000 — bootstrap setup
echo Extract/open the matching ZIP folder first if needed, then this script installs it.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0EBF4000-v$Version-windows\scripts\install_windows.ps1" -SourceDir "%~dp0EBF4000-v$Version-windows"
exit /b %ERRORLEVEL%
"@ | Set-Content -LiteralPath $boot -Encoding ASCII
        Write-Host "Bootstrap: $boot (run after extracting the ZIP, or from dist after build)"
        Write-Host "Also: payload includes scripts\install_windows.ps1 for one-click install."
    }
}

Write-Host ""
Write-Host "Done."
Write-Host "  Payload: $Payload"
Write-Host "  ZIP:     $ZipPath"
if (Test-Path -LiteralPath $SetupOut) { Write-Host "  Setup:   $SetupOut" }
exit 0
