# Download official CPython embeddable 3.12, enable site-packages, install runtime deps.
# Output: <Repo>\runtime\python.exe  (gitignored)
param(
    [string]$PythonVersion = "3.12.10",
    [string]$OutDir = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path $Root "runtime" }

$Arch = "amd64"
if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { $Arch = "arm64" }
elseif ($env:PROCESSOR_ARCHITECTURE -eq "x86" -and -not $env:PROCESSOR_ARCHITEW6432) {
    throw "32-bit Windows is not supported for the bundled runtime."
}

$Tag = "python-$PythonVersion-embed-$Arch"
$ZipName = "$Tag.zip"
$Url = "https://www.python.org/ftp/python/$PythonVersion/$ZipName"
$CacheDir = Join-Path $Root "build\cache"
$ZipPath = Join-Path $CacheDir $ZipName
$GetPip = Join-Path $CacheDir "get-pip.py"
$Req = Join-Path $Root "requirements-runtime.txt"

New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null

if ((Test-Path -LiteralPath (Join-Path $OutDir "python.exe")) -and -not $Force) {
    Write-Host "Bundled runtime already exists: $OutDir"
    Write-Host "Pass -Force to rebuild."
    exit 0
}

if (Test-Path -LiteralPath $OutDir) {
    Write-Host "Removing old runtime: $OutDir"
    Remove-Item -LiteralPath $OutDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if (-not (Test-Path -LiteralPath $ZipPath)) {
    Write-Host "Downloading $Url"
    Invoke-WebRequest -Uri $Url -OutFile $ZipPath -UseBasicParsing
}

Write-Host "Extracting embeddable Python -> $OutDir"
Expand-Archive -LiteralPath $ZipPath -DestinationPath $OutDir -Force

# Enable pip / site-packages on embeddable build
$Pth = Get-ChildItem -LiteralPath $OutDir -Filter "python*._pth" | Select-Object -First 1
if (-not $Pth) { throw "python*._pth not found in embeddable package" }
$pthLines = @(
    "python312.zip"
    "."
    "Lib\\site-packages"
    "import site"
)
# Keep zip name matching whatever embed package shipped
$zipLib = Get-ChildItem -LiteralPath $OutDir -Filter "python*.zip" | Select-Object -First 1
if ($zipLib) {
    $pthLines[0] = $zipLib.Name
}
Set-Content -LiteralPath $Pth.FullName -Value ($pthLines -join "`r`n") -Encoding ascii

if (-not (Test-Path -LiteralPath $GetPip)) {
    Write-Host "Downloading get-pip.py"
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPip -UseBasicParsing
}

$Py = Join-Path $OutDir "python.exe"
$env:PYTHONNOUSERSITE = "1"
Write-Host "Installing pip into embeddable runtime..."
& $Py $GetPip --no-warn-script-location --no-user
if ($LASTEXITCODE -ne 0) { throw "get-pip failed ($LASTEXITCODE)" }

Write-Host "Installing requirements-runtime.txt ..."
& $Py -m pip install --no-warn-script-location --no-user -r $Req
if ($LASTEXITCODE -ne 0) { throw "pip install failed ($LASTEXITCODE)" }

# Marker so start.bat can skip ensure_deps on first launch
$marker = Join-Path $Root ".deps_ok"
"runtime-bundled $(Get-Date -Format o)" | Set-Content -LiteralPath (Join-Path $OutDir ".deps_ok") -Encoding utf8

& $Py -c "import PyQt6, numpy, pyopencl; print('runtime-ok', __import__('sys').version)"
if ($LASTEXITCODE -ne 0) { throw "Runtime import smoke test failed" }

Write-Host "Bundled Python ready: $Py"
exit 0
