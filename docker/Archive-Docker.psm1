# Host tools only. No Docker socket or host power API is mounted into the application.
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'

function Invoke-ArchiveDocker {
    param([Parameter(Mandatory=$true)][string[]]$Arguments)
    $result = & docker @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw ('Docker 命令失败：' + $Arguments[0] + '。请确认 Docker Desktop 已启动，再运行 Doctor-Docker.ps1。') }
    return (($result | ForEach-Object { $_.ToString() }) -join "`n")
}
function Get-ArchiveValue {
    param([string]$Name, [string]$Default)
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ($null -ne $value) { return $value }
    if (Test-Path -LiteralPath '.env') {
        foreach ($line in [IO.File]::ReadAllLines((Join-Path (Get-Location) '.env'))) {
            if ($line -match ('^\s*' + [regex]::Escape($Name) + '\s*=\s*(.*?)\s*$')) {
                $value = $Matches[1]
                if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) { return $value.Substring(1,$value.Length-2) }
                return ($value -replace '\s+#.*$', '').Trim()
            }
        }
    }
    return $Default
}
function Get-ArchiveConfig {
    return (Invoke-ArchiveDocker @('compose','config','--format','json') | ConvertFrom-Json)
}
function Assert-ArchiveWindows {
    if ($env:OS -ne 'Windows_NT') { throw '此入口用于 Windows。Linux 请使用 .sh 脚本。' }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw '未找到 Docker，请先安装并启动 Docker Desktop。' }
    $endpoint = Invoke-ArchiveDocker @('context','inspect','--format','{{json .Endpoints.docker.Host}}') | ConvertFrom-Json
    if (-not $endpoint.StartsWith('npipe://')) { throw '请切换到本机 Docker Desktop context；此入口不操作远端 Docker。' }
    $info = Invoke-ArchiveDocker @('info','--format','{{json .}}') | ConvertFrom-Json
    if ($info.OSType -ne 'linux' -or $info.Architecture -notin @('amd64','x86_64')) { throw '需要 Docker Desktop 的 Linux containers / amd64 模式。' }
    $null = Invoke-ArchiveDocker @('compose','version')
    $config = Get-ArchiveConfig
    if ($config.services.app.network_mode -ne 'host') { throw '当前镜像要求 host 网络，不能直接改成 bridge 或添加 ports。' }
    $ids = Invoke-ArchiveDocker @('ps','-a','--filter',('label=com.docker.compose.project='+$config.name),'--filter','label=com.docker.compose.service=app','--format','{{.ID}}')
    foreach ($id in ($ids -split "`n" | Where-Object { $_ })) {
        $existing = Invoke-ArchiveDocker @('inspect','--format','{{index .Config.Labels "com.docker.compose.project.working_dir"}}',$id)
        if ($existing -and [IO.Path]::GetFullPath($existing).TrimEnd('\','/') -ne [IO.Path]::GetFullPath((Get-Location).Path).TrimEnd('\','/')) { throw '同名 Compose 项目属于另一目录；请回原目录操作，或为新资料库设置不同 COMPOSE_PROJECT_NAME。' }
    }
    return $config
}
function Get-ArchiveHttp {
    param([string]$Url)
    if ($Url -notmatch '^http://127\.0\.0\.1:[0-9]+(?:/[^\s]*)?$') { throw '不是已核对的本机地址。' }
    $request = [Net.HttpWebRequest]::Create($Url)
    $request.Proxy = $null
    $request.Timeout = 2000
    $response = $null; $reader = $null
    try {
        $response = $request.GetResponse(); $reader = New-Object IO.StreamReader($response.GetResponseStream())
        return ($reader.ReadToEnd() | ConvertFrom-Json)
    } finally {
        if ($reader) { $reader.Dispose() }; if ($response) { $response.Dispose() }
    }
}
function Test-ArchiveHostNetwork {
    param([string]$Image)
    $listener = New-Object Net.Sockets.TcpListener -ArgumentList @([Net.IPAddress]::Loopback,0)
    $listener.Start(); $port = $listener.LocalEndpoint.Port; $listener.Stop()
    $marker = [Guid]::NewGuid().ToString('N'); $name = 'discordarchive-probe-'+$marker
    $code = @'
import sys,json
from http.server import BaseHTTPRequestHandler,HTTPServer
marker=sys.argv[1]
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  value=json.dumps(dict(probe=marker)).encode();self.send_response(200);self.end_headers();self.wfile.write(value)
HTTPServer(('127.0.0.1',int(sys.argv[2])),Handler).serve_forever()
'@
    try {
        $null = Invoke-ArchiveDocker @('run','--detach','--rm','--name',$name,'--network','host','--read-only','--cap-drop','ALL','--entrypoint','python',$Image,'-c',$code,$marker,[string]$port)
        for ($attempt=0; $attempt -lt 15; $attempt++) {
            try { $value = Get-ArchiveHttp ('http://127.0.0.1:'+$port); if ($value.probe -eq $marker) { return } } catch { }
            Start-Sleep -Milliseconds 500
        }
        throw '无法从 Windows 访问容器回环地址。启用 Docker Desktop Settings → Resources → Network → Enable host networking 后重试；不要改为监听公网。'
    } finally {
        # This unique, short-lived probe has no volumes. Never remove application containers or data here.
        try { $null = Invoke-ArchiveDocker @('rm','--force',$name) } catch { }
    }
}
function Get-ArchiveRuntime {
    return (Invoke-ArchiveDocker @('compose','exec','-T','app','python','docker/manage.py','status') | ConvertFrom-Json)
}
function Wait-ArchiveReady {
    $expected = Invoke-ArchiveDocker @('compose','exec','-T','app','python','-c',"from discord_archive.listener import project_id; print(project_id('/app'))")
    for ($attempt=0; $attempt -lt 60; $attempt++) {
        try {
            $runtime = Get-ArchiveRuntime
            if ($runtime.running) {
                $null = Invoke-ArchiveDocker @('compose','exec','-T','app','python','docker/manage.py','health')
                $status = Get-ArchiveHttp ($runtime.url+'/api/status')
                if ($status.remote.administrator -and $status.system.project_id -eq $expected) { return $runtime }
            }
        } catch { }
        Start-Sleep -Seconds 1
    }
    throw '容器尚未通过 Windows 本机访问与资料库身份检查。请检查 host networking、端口和 Doctor-Docker.ps1；未放宽管理权限。'
}
function Select-ArchiveHostPort {
    $configuration = Get-ArchiveConfig
    $requested = [int]$configuration.services.app.environment.ARCHIVE_PORT
    if ($requested -lt 1 -or $requested -gt 65535) { throw 'ARCHIVE_PORT 必须为 1 到 65535。' }
    try {
        $runtime = Get-ArchiveRuntime
        if ($runtime.running) {
            $web = Get-ArchiveHttp ($runtime.url+'/api/status')
            $expected = Invoke-ArchiveDocker @('compose','exec','-T','app','python','-c',"from discord_archive.listener import project_id; print(project_id('/app'))")
            if ($web.remote.administrator -and $web.system.project_id -eq $expected -and $web.remote.requested_port -eq $requested) { return }
        }
    } catch { }
    $selected = 0
    for ($candidate=$requested; $candidate -le [Math]::Min(65535,$requested+99); $candidate++) {
        $listener = New-Object Net.Sockets.TcpListener -ArgumentList @([Net.IPAddress]::Loopback,$candidate)
        try { $listener.Start(); $selected=$candidate } catch { } finally { $listener.Stop() }
        if ($selected) { break }
    }
    if (-not $selected) { throw '连续 100 个端口不可用，请另设 ARCHIVE_PORT；没有停止任何进程。' }
    if ($selected -eq $requested) { return }
    if ([Environment]::GetEnvironmentVariable('ARCHIVE_PORT')) { throw '显式环境变量 ARCHIVE_PORT 已占用，请修改该变量后重试；未覆盖它。' }
    $envFile = Join-Path (Get-Location) '.env'
    $backup = $envFile+'.port-backup-'+[Guid]::NewGuid().ToString('N')
    Copy-Item -LiteralPath $envFile -Destination $backup
    $content = [IO.File]::ReadAllText($envFile)
    if ($content -match '(?m)^\s*ARCHIVE_PORT\s*=') { $content = [regex]::Replace($content,'(?m)^\s*ARCHIVE_PORT\s*=.*$',('ARCHIVE_PORT='+$selected)) }
    else { $content += "`nARCHIVE_PORT=$selected`n" }
    [IO.File]::WriteAllText($envFile,$content,(New-Object Text.UTF8Encoding($false)))
    Write-Host ('端口 '+$requested+' 已占用，已将 .env 改为 '+$selected+'；旧配置保留为 '+[IO.Path]::GetFileName($backup))
}
function Start-ArchiveApp {
    param([switch]$NoOpen)
    Select-ArchiveHostPort
    $null = Invoke-ArchiveDocker @('compose','up','-d','--no-build')
    $started=$false
    for ($attempt=0; $attempt -lt 60; $attempt++) {
        try { $null = Invoke-ArchiveDocker @('compose','exec','-T','app','python','docker/manage.py','start');$started=$true;break } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $started) { throw '容器管理进程未就绪，请运行 Doctor-Docker.ps1。' }
    $runtime = Wait-ArchiveReady
    Write-Host ('应用地址：'+$runtime.url)
    if (-not $NoOpen) { Start-Process $runtime.url }
}
function Install-ArchiveImage {
    param([string]$Image)
    $archive = Join-Path (Get-Location) 'discordarchive-linux-amd64.tar.gz'
    if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) { throw '缺少离线镜像，请把 discordarchive-linux-amd64.tar.gz 放到部署目录。' }
    $lines = Get-Content -LiteralPath 'CHECKSUMS.sha256'
    $entry = @($lines | Where-Object { $_ -match '^[0-9a-fA-F]{64}\s+\*?discordarchive-linux-amd64\.tar\.gz$' })
    if ($entry.Count -ne 1) { throw '镜像校验文件无效。' }
    $expected = ($entry[0] -split '\s+')[0]
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expected) { throw '镜像 SHA-256 不一致，请重新下载。' }
    $present = & docker image inspect $Image --format '{{.Id}}' 2>$null
    if ($LASTEXITCODE -ne 0) { $null = Invoke-ArchiveDocker @('load','--input',$archive) }
    $null = Invoke-ArchiveDocker @('image','inspect',$Image)
}
function Invoke-ArchiveTailscale {
    $command = Get-Command tailscale.exe -ErrorAction SilentlyContinue
    if (-not $command) { throw '请先在 Windows 安装并登录 Tailscale，并重新打开 PowerShell。' }
    $port = Get-ArchiveValue 'ARCHIVE_HTTPS_PORT' '443'
    if ($port -notin @('443','8443')) { throw 'ARCHIVE_HTTPS_PORT 仅支持 443 或 8443。' }
    $status = & $command.Source status --json
    if ($LASTEXITCODE -ne 0) { throw 'Tailscale 未就绪，请先完成账号授权。' }
    $previousEncoding = $OutputEncoding
    try {
        $OutputEncoding = New-Object Text.UTF8Encoding($false)
        $result = ($status -join "`n") | & docker compose exec -T app python docker/configure_tailscale.py --https-port $port 2>&1
        if ($LASTEXITCODE -ne 0) { throw '访问配置未完成；请确认 Tailscale 已授权，且没有另一套所有者配置。' }
        Write-Host ($result -join "`n")
    } finally { $OutputEncoding = $previousEncoding }
    $runtime = Get-ArchiveRuntime
    if ($runtime.url -notmatch '^http://127\.0\.0\.1:[0-9]+$') { throw '未确认本应用实际端口，未修改转发。' }
    $existing = & $command.Source serve status --json
    if ($LASTEXITCODE -ne 0) { throw '无法读取 Tailscale Serve 配置，未修改转发。' }
    if ((($existing -join '') -replace '\s','') -in @('{}','null')) {
        & $command.Source serve --bg ('--https='+$port) $runtime.url
        if ($LASTEXITCODE -ne 0) { throw 'Serve 未完成；按 Tailscale 提示批准 HTTPS，必要时在管理员终端重试此脚本。' }
    } else { Write-Host ('已有 Serve 路由，未覆盖。核对后执行：tailscale serve --bg --https='+$port+' '+$runtime.url) }
    $null = Invoke-ArchiveDocker @('compose','exec','-T','app','python','docker/restart.py')
    $null = Wait-ArchiveReady
}
Export-ModuleMember -Function *-Archive*
