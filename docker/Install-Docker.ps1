param([switch]$NoOpen)
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot 'Archive-Docker.psm1') -Force
try {
    if (-not (Test-Path -LiteralPath '.env')) {
        $template = if (Test-Path -LiteralPath '.env.example') { '.env.example' } else { 'env.example' }
        Copy-Item -LiteralPath $template -Destination '.env'
    }
    $config = Assert-ArchiveWindows
    Install-ArchiveImage $config.services.app.image
    Test-ArchiveHostNetwork $config.services.app.image
    $null = Invoke-ArchiveDocker @('compose','run','--rm','--no-deps','--entrypoint','python','app','docker/initialize.py')
    Start-ArchiveApp -NoOpen:$NoOpen
} catch { Write-Host $_.Exception.Message; exit 1 }
