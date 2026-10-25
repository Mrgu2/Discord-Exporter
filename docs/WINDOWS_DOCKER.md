# Windows Docker 本地完整版（预览）

流程：**安装并打开本机工作台 → [连接 Discord](LOGIN_ASSISTANT.md#首次连接-discord) → [首次出图](USAGE.md#第一次采集出图)**。

在 Windows 上运行同一个 Linux 镜像，采集、small 语音转写和出图均在本机容器完成。它与“Windows 访问 Ubuntu 客户端”是两种用途。

**当前为预览包，没有 Windows Docker Desktop 实机验收。** 脚本会检查本机访问和管理权限，失败就停止；Linux 容器测试不能替代 Windows 实测。Mac 继续使用原生安装。

## 1. 准备 Windows

- x64 Windows，安装符合 [Docker 官方系统要求](https://docs.docker.com/desktop/setup/install/windows-install/)的 Docker Desktop，使用 **WSL 2 / Linux containers**。当前镜像为 amd64，不支持 Windows ARM 或 Windows containers 模式。
- Docker Desktop **4.34+**：按提示登录 Docker 账号，在 **Settings → Resources → Network** 开启 **Enable host networking**，应用设置并重启 Docker Desktop。受管设备不允许此功能时，本包不能直接运行，不要关闭企业安全策略。
- 预留至少 12 GiB 磁盘空间；Docker Desktop 须保持运行，电脑睡眠时任务也会停止。

[host 网络官方说明](https://docs.docker.com/engine/network/drivers/host/)：本包不使用 `-p` 或 `ports:`，端口通过 `ARCHIVE_PORT` 设置。

## 2. 文件放到哪里

只下载一个 [Docker 完整离线包](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.4/DiscordArchive-Docker-complete-preview.zip)，已含镜像和 small 模型，无需另下文件。

按 [校验方法](DOWNLOADS.md#核对文件)核对 SHA-256。若 Windows 标记 ZIP 来自互联网，在 ZIP“属性”中解除锁定，再完整解压到固定目录，例如 `D:\DiscordArchive`。不要全局关闭脚本策略，也不要解压包内的 `.tar.gz` 镜像。

解压后应看到：

```text
D:\DiscordArchive\
  Install-Docker.cmd
  Start-Docker.cmd
  Stop-Docker.cmd
  Doctor-Docker.cmd
  Configure-Tailscale.cmd
  Backup-Docker.ps1
  Archive-Docker.psm1
  compose.yaml
  .env.example
  discordarchive-linux-amd64.tar.gz
  CHECKSUMS.sha256
  examples\
  docs\
```

程序数据默认在 Docker 命名卷，**不是这个文件夹内的 data/**。不要把旧资料库拖进来；新部署不自动迁移原安装。

## 3. 安装并启动

默认直接双击 **Install-Docker.cmd**，无需编辑变量。想先准备配置时，用 [Windows 可复制示例](DOCKER_CONFIG.md#windows)，该段命令也会安装，不必重复执行。也可在 PowerShell 执行：

```powershell
Set-Location D:\DiscordArchive
.\Install-Docker.ps1
```

首次运行会从 `.env.example` 创建 `.env`，校验并导入镜像、测试 host 网络、加载模型，再打开工作台。全程不用在 Windows 安装 Python、Node 或 Whisper。

**通过标志：**输出应用地址，且打开的工作台属于本资料库。若提示无法访问回环地址或身份检查失败，先按下方排错；不要改为监听 `0.0.0.0` 来跳过检查。

安装完成后直接在同一台 Windows 绑定账号，按下一节操作；不需要 Tailscale 或另一台电脑。

端口被 Windows 其他程序占用时，启动器会选择后续空闲端口，更新 `.env` 并保留旧配置副本；显式 shell 环境变量不会被覆盖。

<a id="windows-first-connection"></a>

## 4. 在同一台 Windows 连接 Discord

1. 保持 Docker Desktop 与容器运行。双击 **Start-Docker.cmd** 打开本机工作台，地址以启动提示为准，例如 `http://127.0.0.1:8765`。
2. 在该工作台点击 **首次连接 Discord**，下载 **Windows 连接工具与访问客户端**。使用这里下载的包，它已带上本机地址和当前资料库标识；不要手动改成另一台机器的地址。
3. 解压后运行 **Connect Discord.cmd**，再按 [首次连接教程](LOGIN_ASSISTANT.md#首次连接-discord)加载扩展、识别并确认日常浏览器里的 Discord 账号。
4. 工作台显示正确账号后，点击 **[首次采集出图](USAGE.md#第一次采集出图)**，先测试一个小频道。

同机绑定无需 Tailscale、HTTPS 域名或 SSH 隧道。连接成功后，助手可关闭、扩展可移除，容器独立运行；连接过期时再绑定。浏览器或容器网络无法访问 Discord 时，仍需分别处理网络问题。

<a id="4-tailscale-https首次连接与远程访问"></a>

## 远程访问（可选）

只有要从其他电脑或手机访问时，才在 Windows 和访问设备安装 [Tailscale](https://tailscale.com/docs/install)，登录获准账号。重新打开部署目录的 PowerShell，执行：

```powershell
.\Configure-Tailscale.ps1
```

按提示批准 HTTPS；需要管理员权限时，只在管理员 PowerShell 重跑这一步。脚本输出固定 HTTPS 地址，已有 Serve 路由保留并打印待核对命令。其他设备按 [访问教程](ACCESS.md)打开工作台，已连接账号不重复绑定。

Tailscale 在 Windows 宿主机运行。不开放公网或启用 Funnel，容器不管理 Windows 网络或电源。

<details>
<summary>安装后的管理、配置与排错</summary>

## 5. 日常使用

| 操作 | 入口 |
| --- | --- |
| 启动或恢复 | `Start-Docker.cmd` |
| 停止容器，保留资料 | `Stop-Docker.cmd` |
| 检查配置与本机访问 | `Doctor-Docker.cmd` |
| 重启应用 | 工作台“重启服务”，只重启容器内应用 |
| 不打开浏览器启动 | PowerShell：`.\Start-Docker.ps1 -NoOpen` |

“容器启动后自动运行”控制应用；Docker Desktop 是否随 Windows 登录启动，由 Docker Desktop 设置。两者不是同一个开关，均未由本安装器擅自开启。

## 6. 端口、目录和变量

完整说明见 [Docker 配置指南](DOCKER_CONFIG.md)，包括：

- `.env` 放置位置、变量含义和应用方法。
- host 网络下如何换端口，以及为何不能加 `ports:`。
- 将图片另存到 `D:/DiscordArchive/exports`，不将数据库直接放在 NTFS 共享目录。
- CPU / 内存限制、备份与恢复、更新和迁移边界。

## 排错

| 提示 | 处理 |
| --- | --- |
| 无法运行脚本 | 核对来源与哈希，解除可信 ZIP 的锁定后重新解压；CMD 仅使用当前进程 RemoteSigned，不改全局策略 |
| 不是 Linux / amd64 | 在 Docker Desktop 切换 Linux containers；ARM 主机不在本包范围 |
| 无法访问容器回环地址 | 检查 host networking 已启用、Docker Desktop 已重启，及当前设备是否允许该模式 |
| 资料库身份不符或端口冲突 | 在 `.env` 换 `ARCHIVE_PORT` 后重新 Start；不会停止占用端口的程序 |
| 同名项目属于另一目录 | 回原目录启动；只有明确要新资料库时才换 `COMPOSE_PROJECT_NAME` |
| 账号识别成功但容器校验失败 | 检查容器能否访问 Discord；浏览器能上网不代表容器可达，按 Docker Desktop 网络/代理设置处理 |
| 目录不能写入 | 确认目录存在、Docker Desktop 能访问，并检查另存错误；不要把整个系统盘挂进容器 |

Windows 的 host 网络、NTFS 挂载、扫码扩展和 Tailscale Serve 仍需实机验收；不能因脚本检查通过就宣称全部硬件环境可用。

</details>

## 下一步

确认本机工作台能打开后，点击 **[下一步：连接 Discord](LOGIN_ASSISTANT.md#首次连接-discord)**，在运行 Docker 的这台 Windows 操作。

工作台已经显示已连接账号时，直接进入 **[首次采集出图](USAGE.md#第一次采集出图)**，不用重新绑定。
