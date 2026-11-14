#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Adds ONLY the Easy Block Finder 4000 miners folder to Windows Defender exclusions.
  Does not disable Defender. Used for XMRig/Rigel CoinMiner false positives.
#>
$ErrorActionPreference = "Stop"
$root = Join-Path $env:LOCALAPPDATA "EasyBlockFinder4000\miners"
if (-not (Test-Path -LiteralPath $root)) {
    New-Item -ItemType Directory -Path $root -Force | Out-Null
}

try {
    Add-MpPreference -ExclusionPath $root
    Write-Host "OK: Defender ExclusionPath added (miners only):"
    Write-Host "  $root"
    Write-Host ""
    Write-Host "Next: Windows Security → Protection history → Restore quarantined file,"
    Write-Host "then Start the network again in Easy Block Finder 4000."
    Write-Host "Press Enter to close."
    Read-Host | Out-Null
} catch {
    Write-Host "ERROR: $_"
    Write-Host "Manual: Windows Security → Virus & threat protection →"
    Write-Host "  Manage settings → Exclusions → Add folder →"
    Write-Host "  $root"
    Write-Host "Press Enter to close."
    Read-Host | Out-Null
    exit 1
}
