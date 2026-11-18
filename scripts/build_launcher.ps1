# Compile EBF4000.exe GUI launcher (no console) with .NET Framework csc.
param(
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) { $OutDir = $Root }

$src = Join-Path $PSScriptRoot "launcher\EBF4000Launcher.cs"
$out = Join-Path $OutDir "EBF4000.exe"
$csc = Get-ChildItem "C:\Windows\Microsoft.NET\Framework64\v4*\csc.exe" |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $csc) {
    $csc = Get-ChildItem "C:\Windows\Microsoft.NET\Framework\v4*\csc.exe" |
        Sort-Object FullName -Descending | Select-Object -First 1
}
if (-not $csc) { throw "csc.exe not found (need .NET Framework 4.x)" }

# Icon embedding skipped: assets\ebf4000_icon.ico from System.Drawing is not a valid Win32 ICO for csc.
$args = @(
    "/nologo", "/target:winexe", "/optimize+",
    "/r:System.Windows.Forms.dll", "/r:System.dll",
    "/out:$out", $src
)

Write-Host "Compiling $out with $($csc.FullName)"
& $csc.FullName @args
if ($LASTEXITCODE -ne 0) { throw "csc failed ($LASTEXITCODE)" }
if (-not (Test-Path -LiteralPath $out)) { throw "EBF4000.exe not produced" }
Write-Host "OK: $out ($([math]::Round((Get-Item $out).Length/1KB,1)) KB)"
exit 0
