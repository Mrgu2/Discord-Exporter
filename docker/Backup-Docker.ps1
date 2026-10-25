param([Parameter(Mandatory=$true)][string]$Destination, [switch]$IncludeModels)
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot 'Archive-Docker.psm1') -Force
try {
    $config = Assert-ArchiveWindows
    $target = [IO.Path]::GetFullPath($Destination)
    if (Test-Path -LiteralPath $target) { throw '备份目标已存在，请使用新的目录，不覆盖旧备份。' }
    $null = New-Item -ItemType Directory -Path $target
    $null = Invoke-ArchiveDocker @('compose','stop','app')
    foreach ($folder in @('data','output')) {
        $path = Join-Path $target $folder
        $null = New-Item -ItemType Directory -Path $path
        $null = Invoke-ArchiveDocker @('compose','cp',('app:/app/'+$folder+'/.'),$path)
    }
    if ($IncludeModels) {
        $path = Join-Path $target 'models'; $null = New-Item -ItemType Directory -Path $path
        $null = Invoke-ArchiveDocker @('compose','cp','app:/app/.runtime/models/.',$path)
    }
    foreach ($name in @('.env','compose.yaml','compose.exports.yaml','compose.resources.yaml')) {
        if (Test-Path -LiteralPath $name) { Copy-Item -LiteralPath $name -Destination (Join-Path $target $name) }
    }
    $files = @(Get-ChildItem -LiteralPath $target -File -Recurse -Force | ForEach-Object {
        @{path=$_.FullName.Substring($target.Length+1); sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
    })
    $manifest = @{format=1;project=$config.name;image=$config.services.app.image;models_included=[bool]$IncludeModels;files=$files}
    [IO.File]::WriteAllText((Join-Path $target 'BACKUP-MANIFEST.json'),($manifest | ConvertTo-Json -Depth 6),(New-Object Text.UTF8Encoding($false)))
    Write-Host ('备份完成：'+$target)
    Write-Host '备份含账号凭据，请私下保管。容器保持停止；运行 Start-Docker.ps1 恢复。'
} catch { Write-Host $_.Exception.Message; exit 1 }
