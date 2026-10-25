Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot 'Archive-Docker.psm1') -Force
try {
    $config = Assert-ArchiveWindows
    Test-ArchiveHostNetwork $config.services.app.image
    $runtime = Get-ArchiveRuntime
    if (-not $runtime.running) { throw '应用已停止。运行 Start-Docker.ps1 恢复，未自动更改启动偏好。' }
    $null = Wait-ArchiveReady
    Write-Host ('Windows 本机访问检查通过：'+$runtime.url)
} catch { Write-Host $_.Exception.Message; exit 1 }
