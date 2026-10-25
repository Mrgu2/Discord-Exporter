param([switch]$NoOpen)
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot 'Archive-Docker.psm1') -Force
try {
    if (-not (Test-Path -LiteralPath '.env')) { throw '请先运行 Install-Docker.ps1。' }
    $null = Assert-ArchiveWindows
    Start-ArchiveApp -NoOpen:$NoOpen
} catch { Write-Host $_.Exception.Message; exit 1 }
