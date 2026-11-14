#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Adds the Easy Block Finder 4000 miner folder to Windows Defender exclusions.
  Used for XMRig (XMR) CoinMiner false positives.
#>
$ErrorActionPreference = "Stop"
$root = Join-Path $env:LOCALAPPDATA "EasyBlockFinder4000"
$legacy = Join-Path $env:LOCALAPPDATA "SoloBlockStrike"
if (-not (Test-Path -LiteralPath $root)) {
    New-Item -ItemType Directory -Path $root -Force | Out-Null
}

try {
    Add-MpPreference -ExclusionPath $root
    if (Test-Path -LiteralPath $legacy) {
        Add-MpPreference -ExclusionPath $legacy
    }
    Write-Host "OK: Defender ExclusionPath added:"
    Write-Host "  $root"
    Write-Host "Restore quarantined xmrig.exe from Protection history,"
    Write-Host "then restart the XMR session in Easy Block Finder 4000."
} catch {
    Write-Host "ERROR: $_"
    Write-Host "Manually: Windows Security -> Virus & threat protection ->"
    Write-Host "  Manage settings -> Exclusions -> Add folder ->"
    Write-Host "  $root"
    exit 1
}
