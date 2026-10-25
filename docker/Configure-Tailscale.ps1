Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot 'Archive-Docker.psm1') -Force
try {
    $null = Assert-ArchiveWindows
    $null = Wait-ArchiveReady
    Invoke-ArchiveTailscale
} catch { Write-Host $_.Exception.Message; exit 1 }
