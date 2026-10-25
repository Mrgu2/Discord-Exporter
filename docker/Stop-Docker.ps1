Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot 'Archive-Docker.psm1') -Force
try {
    $null = Assert-ArchiveWindows
    $null = Invoke-ArchiveDocker @('compose','stop','app')
    Write-Host '本容器已停止，资料卷保留。'
} catch { Write-Host $_.Exception.Message; exit 1 }
