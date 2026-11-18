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

# Ensure Inno has an .ico (generated from PNG when missing)
$PngIcon = Join-Path $Root "assets\ebf4000_icon.png"
$IcoIcon = Join-Path $Root "assets\ebf4000_icon.ico"
if ((Test-Path -LiteralPath $PngIcon) -and -not (Test-Path -LiteralPath $IcoIcon)) {
    Write-Host "Generating assets\ebf4000_icon.ico from PNG..."
    Add-Type -AssemblyName System.Drawing
    $bmp = [System.Drawing.Bitmap]::FromFile($PngIcon)
    try {
        $hIcon = $bmp.GetHicon()
        $icon = [System.Drawing.Icon]::FromHandle($hIcon)
        $fs = [System.IO.File]::Create($IcoIcon)
        try { $icon.Save($fs) } finally { $fs.Dispose() }
        $icon.Dispose()
    } finally {
        $bmp.Dispose()
    }
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

Write-Host "Creating ZIP: $ZipPath"
if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
# Zip contents = payload folder name as root entry
Push-Location $Dist
Compress-Archive -Path (Split-Path -Leaf $Payload) -DestinationPath (Split-Path -Leaf $ZipPath) -Force
Pop-Location

function Find-ISCC {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe",
        (Join-Path $Root "build\tools\InnoSetup6\ISCC.exe")
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c)) { return $c }
    }
    $nodeIscc = Join-Path $env:LOCALAPPDATA "Programs\Antigravity IDE\resources\app\node_modules\innosetup\bin\ISCC.exe"
    if (Test-Path -LiteralPath $nodeIscc) { return $nodeIscc }
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
