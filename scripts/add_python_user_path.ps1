# Add a Python install dir (+ Scripts) to the current user's PATH permanently.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File add_python_user_path.ps1 -PythonExe "C:\...\python.exe" [-Quiet]
param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExe,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$exe = [System.IO.Path]::GetFullPath($PythonExe)
if (-not (Test-Path -LiteralPath $exe)) {
    Write-Error "Python exe not found: $exe"
    exit 2
}

$dir = [System.IO.Path]::GetDirectoryName($exe)
$scripts = Join-Path $dir "Scripts"
$add = @($dir)
if (Test-Path -LiteralPath $scripts) { $add += $scripts }

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($null -eq $userPath) { $userPath = "" }
$parts = @()
foreach ($p in ($userPath -split ";")) {
    $t = $p.Trim()
    if ($t) { $parts += $t }
}
$lower = @{ }
foreach ($p in $parts) { $lower[$p.ToLowerInvariant()] = $true }

$changed = $false
foreach ($p in $add) {
    $key = $p.ToLowerInvariant()
    if (-not $lower.ContainsKey($key)) {
        $parts += $p
        $lower[$key] = $true
        $changed = $true
        Write-Host "Will add to User PATH: $p"
    } else {
        Write-Host "Already on User PATH: $p"
    }
}

if (-not $changed) {
    Write-Host "User PATH already contains this Python. Nothing to change."
    exit 0
}

$newPath = ($parts -join ";")
[Environment]::SetEnvironmentVariable("Path", $newPath, "User")
# Also update this process so callers see it immediately
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + $newPath
Write-Host "User PATH updated. New CMD / start.bat windows will see python."
exit 0
