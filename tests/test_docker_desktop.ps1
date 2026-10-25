param([string]$ModulePath = (Join-Path $PSScriptRoot '../docker/Archive-Docker.psm1'))
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
$ModulePath = (Resolve-Path -LiteralPath $ModulePath).Path
$source = Split-Path -Parent $ModulePath
$cases = New-Object Collections.Generic.List[string]
function Check([bool]$Condition,[string]$Name) { if (-not $Condition) { throw ('FAIL: '+$Name) }; $cases.Add($Name) }
function Must-Fail([scriptblock]$Action,[string]$Name) {
    $failed=$false; try { & $Action | Out-Null } catch { $failed=$true }; Check $failed $Name
}
foreach ($file in Get-ChildItem -LiteralPath $source -File | Where-Object { $_.Extension -in @('.ps1','.psm1') }) {
    $tokens=$null; $errors=$null
    $null=[Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$tokens,[ref]$errors)
    Check ($errors.Count -eq 0) ('parse '+$file.Name)
    $bytes=[IO.File]::ReadAllBytes($file.FullName)
    Check ($bytes[0] -eq 239 -and $bytes[1] -eq 187 -and $bytes[2] -eq 191) ('UTF8 BOM '+$file.Name)
}
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('archive-ps-test-'+[Guid]::NewGuid().ToString('N'))
$null=New-Item -ItemType Directory -Path $temporary
$oldDirectory=(Get-Location).Path; $oldOS=$env:OS; $oldPort=$env:ARCHIVE_PORT
try {
    Set-Location $temporary
    [IO.File]::WriteAllText((Join-Path $temporary '.env'),"ARCHIVE_PORT=18765`nARCHIVE_HTTPS_PORT=8443`nARCHIVE_EXPORT_DIR='D:/folder with spaces'`n",(New-Object Text.UTF8Encoding($false)))
    Import-Module $ModulePath -Force
    $env:ARCHIVE_PORT=$null
    Check ((Get-ArchiveValue 'ARCHIVE_PORT' '8765') -eq '18765') 'dotenv port'
    Check ((Get-ArchiveValue 'ARCHIVE_EXPORT_DIR' '') -eq 'D:/folder with spaces') 'quoted folder'
    $env:ARCHIVE_PORT='28865'; Check ((Get-ArchiveValue 'ARCHIVE_PORT' '8765') -eq '28865') 'shell precedence'
    Must-Fail { Get-ArchiveHttp 'https://example.com/' } 'reject non-loopback HTTP target'
    $env:OS='Linux'; Must-Fail { Assert-ArchiveWindows } 'reject non-Windows entry'
    $env:OS='Windows_NT'
    function global:docker { $global:LASTEXITCODE=0; return 'fixture-image' }
    $module=Get-Module Archive-Docker
    & $module {
        $script:Endpoint='npipe:////./pipe/dockerDesktopLinuxEngine';$script:Kind='linux';$script:Arch='amd64';$script:Mode='host';$script:DifferentDirectory=$false;$script:HasExisting=$false
        function script:Invoke-ArchiveDocker {
            param([string[]]$Arguments)
            switch ($Arguments[0]) {
                'context' { return ('"'+$script:Endpoint+'"') }
                'info' { return (@{OSType=$script:Kind;Architecture=$script:Arch}|ConvertTo-Json -Compress) }
                'ps' { if ($script:HasExisting) { return 'fictional-container' }; return '' }
                'inspect' { if ($script:DifferentDirectory) { return 'another-directory' };return (Get-Location).Path }
                'compose' { return (@{name='fixture';services=@{app=@{network_mode=$script:Mode}}}|ConvertTo-Json -Depth 5 -Compress) }
            }
            return ''
        }
    }
    Check ((Assert-ArchiveWindows).name -eq 'fixture') 'local Linux container mode accepted'
    & $module { $script:HasExisting=$true };Check ((Assert-ArchiveWindows).name -eq 'fixture') 'own existing project accepted'
    & $module { $script:Endpoint='ssh://remote' }; Must-Fail { Assert-ArchiveWindows } 'reject remote Docker context'
    & $module { $script:Endpoint='npipe:////./pipe/dockerDesktopLinuxEngine';$script:Kind='windows' }; Must-Fail { Assert-ArchiveWindows } 'reject Windows containers'
    & $module { $script:Kind='linux';$script:Arch='arm64' }; Must-Fail { Assert-ArchiveWindows } 'reject ARM image mismatch'
    & $module { $script:Arch='amd64';$script:Mode='bridge' }; Must-Fail { Assert-ArchiveWindows } 'reject unadapted bridge networking'
    & $module { $script:Mode='host';$script:DifferentDirectory=$true }; Must-Fail { Assert-ArchiveWindows } 'preserve another project directory'
    # Probe exercises cleanup and marker checking without requiring Docker Desktop.
    & $module {
        $script:Runs=@();$script:Marker='';$script:HttpMatches=$true
        function script:Invoke-ArchiveDocker {
            param([string[]]$Arguments)
            $script:Runs += ,$Arguments
            if ($Arguments[0] -eq 'run') { $script:Marker=$Arguments[$Arguments.Count-2] }
            return ''
        }
        function script:Get-ArchiveHttp { param([string]$Url); if ($script:HttpMatches) { return @{probe=$script:Marker} }; return @{probe='wrong'} }
        function script:Start-Sleep { param([int]$Milliseconds,[int]$Seconds) }
    }
    Test-ArchiveHostNetwork 'fixture-image'
    $runs=& $module { $script:Runs }
    Check ($runs[0] -contains 'host' -and $runs[0] -contains '--cap-drop') 'probe uses host mode without host privileges'
    Check ($runs[$runs.Count-1][0] -eq 'rm' -and $runs[$runs.Count-1][2] -like 'discordarchive-probe-*') 'probe cleanup limited to its own temporary container'
    & $module { $script:HttpMatches=$false }; Must-Fail { Test-ArchiveHostNetwork 'fixture-image' } 'fail closed when Windows cannot reach container'
    & $module {
        $script:IdentityMatches=$true
        function script:Invoke-ArchiveDocker { param([string[]]$Arguments); return 'expected-project' }
        function script:Get-ArchiveRuntime { return @{running=$true;url='http://127.0.0.1:8765'} }
        function script:Get-ArchiveHttp { param([string]$Url);return @{remote=@{administrator=$true};system=@{project_id=$(if($script:IdentityMatches){'expected-project'}else{'other-project'})}} }
    }
    Check ((Wait-ArchiveReady).url -eq 'http://127.0.0.1:8765') 'host identity matches own project'
    & $module { $script:IdentityMatches=$false }; Must-Fail { Wait-ArchiveReady } 'reject another application on the same port'
    # Exercise host-port collision with real local sockets, while Docker calls remain mocked.
    $env:ARCHIVE_PORT=$null
    $busy=New-Object Net.Sockets.TcpListener -ArgumentList @([Net.IPAddress]::Loopback,0)
    $busy.Start();$busyPort=$busy.LocalEndpoint.Port
    try {
        & $module { param($port);$script:BusyPort=$port
            function script:Get-ArchiveConfig { return @{services=@{app=@{environment=@{ARCHIVE_PORT=$script:BusyPort}}}} }
            function script:Get-ArchiveRuntime { throw 'fixture has no application yet' }
        } $busyPort
        Select-ArchiveHostPort
        $selected=[int](Get-ArchiveValue 'ARCHIVE_PORT' '0')
        Check ($selected -gt $busyPort -and $selected -le $busyPort+99) 'host occupied port selects another port'
        Check (@(Get-ChildItem -Force '.env.port-backup-*').Count -eq 1) 'host port update preserves previous dotenv'
        Check ((Get-ArchiveValue 'ARCHIVE_EXPORT_DIR' '') -eq 'D:/folder with spaces') 'port update preserves other settings'
        $env:ARCHIVE_PORT=[string]$busyPort
        Must-Fail { Select-ArchiveHostPort } 'explicit shell port is not silently overridden'
        $env:ARCHIVE_PORT=$null
    } finally { $busy.Stop() }
    # Image integrity is checked before image import. No real image or credential is needed.
    [IO.File]::WriteAllText((Join-Path $temporary 'discordarchive-linux-amd64.tar.gz'),'public fixture')
    [IO.File]::WriteAllText((Join-Path $temporary 'CHECKSUMS.sha256'),(('0'*64)+'  discordarchive-linux-amd64.tar.gz'))
    Must-Fail { Install-ArchiveImage 'fixture-image' } 'reject mismatched offline image checksum'
    & $module {
        $script:StartAttempts=0
        function script:Select-ArchiveHostPort { }
        function script:Invoke-ArchiveDocker {
            param([string[]]$Arguments)
            if ($Arguments[$Arguments.Count-1] -eq 'start') { $script:StartAttempts++;if ($script:StartAttempts -lt 3) { throw 'fixture IPC not ready' } }
            return ''
        }
        function script:Wait-ArchiveReady { return @{url='http://127.0.0.1:8765'} }
    }
    Start-ArchiveApp -NoOpen
    Check ((& $module { $script:StartAttempts }) -eq 3) 'startup waits for supervisor IPC'
    # Run the real backup script with a fake native Docker CLI and real files.
    $global:ArchiveBackupStops=0
    function global:docker {
        param([Parameter(ValueFromRemainingArguments=$true)][object[]]$Arguments)
        $global:LASTEXITCODE=0
        if ($Arguments[0] -eq 'context') { return '"npipe:////./pipe/dockerDesktopLinuxEngine"' }
        if ($Arguments[0] -eq 'info') { return '{"OSType":"linux","Architecture":"amd64"}' }
        if ($Arguments[0] -eq 'ps') { return '' }
        if ($Arguments[0] -eq 'compose' -and $Arguments[1] -eq 'version') { return 'Docker Compose fixture' }
        if ($Arguments[0] -eq 'compose' -and $Arguments[1] -eq 'config') { return '{"name":"fixture","services":{"app":{"network_mode":"host","image":"fixture-image"}}}' }
        if ($Arguments[0] -eq 'compose' -and $Arguments[1] -eq 'stop') { $global:ArchiveBackupStops++;return '' }
        if ($Arguments[0] -eq 'compose' -and $Arguments[1] -eq 'cp') { [IO.File]::WriteAllText((Join-Path $Arguments[$Arguments.Count-1] 'fixture.txt'),'public backup fixture');return '' }
        throw 'Unexpected fixture Docker command'
    }
    $backup=Join-Path $temporary 'backup'
    & (Join-Path $source 'Backup-Docker.ps1') -Destination $backup
    Check ((Test-Path (Join-Path $backup 'data/fixture.txt')) -and (Test-Path (Join-Path $backup 'output/fixture.txt'))) 'backup copies data and output'
    $manifest=Get-Content (Join-Path $backup 'BACKUP-MANIFEST.json') -Raw | ConvertFrom-Json
    foreach ($item in $manifest.files) { Check ((Get-FileHash (Join-Path $backup $item.path) -Algorithm SHA256).Hash -eq $item.sha256) ('backup hash '+$item.path) }
    Check ($global:ArchiveBackupStops -eq 1 -and -not $manifest.models_included) 'backup stops own service and keeps it stopped'
    Write-Output (@{passed=$true;checks=$cases.Count;cases=@($cases);scope='PowerShell parser and mocked host-tool contracts; not Windows Docker Desktop acceptance'}|ConvertTo-Json -Depth 4)
} finally {
    Set-Location $oldDirectory; $env:OS=$oldOS; $env:ARCHIVE_PORT=$oldPort
    # Keep generated test fixtures for inspection. No user project or volume is removed.
}
