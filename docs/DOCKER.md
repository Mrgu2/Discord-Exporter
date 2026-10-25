# Ubuntu Docker 安装与使用

适用于 Ubuntu x86_64（amd64）。Mac 保留[原生安装](MAC.md)。Docker 版使用同一工作台，保留频道保存、附件、答疑稿、标准与 HiDPI 图片、small 语音转写、定时出稿和四种推送渠道。语音默认 small 多语言 / CPU INT8，不要求独立显卡。

## 1. 准备服务器与文件

服务器需要 Docker Engine、Compose v2、Tailscale 和足够的空间。镜像包含 Chromium、FFmpeg、中文字体、Python、Node 和 small 模型；无需逐项安装。先用 `uname -m` 确认是 `x86_64`，用 `df -h /` 检查空间，建议至少留 12 GiB。其他架构尚未验收。

Docker 未安装时按 [Ubuntu 官方安装说明](https://docs.docker.com/engine/install/ubuntu/)安装 Engine 与 Compose 插件，不要覆盖已有容器环境。用以下命令检查：

```sh
sudo docker version
sudo docker compose version
```

从[本版 Release](https://github.com/Mrgu2/Discord-Exporter/releases/tag/v2026.10.25.2)下载两个文件，上传到 Ubuntu 的同一个**新目录**：

- `DiscordArchive-Docker-linux-amd64.zip`：部署脚本、Compose、教程与校验文件。
- `discordarchive-linux-amd64.tar.gz`：离线镜像，已包含 small 模型；无需解压它。

私有仓库需要有权限的 GitHub 账号下载；不能用匿名 wget 的 404 当作包不存在。可先在访问电脑下载，再用 SFTP 或 scp 上传。不要将原安装的 data/、output/ 或凭据移入镜像目录。已有原生版可继续运行，新 Docker 部署是另一套独立资料库，不会自动迁移或同步旧资料。

## 2. 安装并启动

以下在 **Ubuntu SSH 终端**执行，将路径换成实际上传目录。需要 `unzip` 解压部署包；若提示命令不存在，先执行 `sudo apt-get update && sudo apt-get install -y unzip`：

```sh
cd ~/apps/discordarchive-docker
unzip -n DiscordArchive-Docker-linux-amd64.zip
sudo bash Install-Docker.sh
```

命令使用 sudo 访问 Docker；不用为此把普通用户加入 docker 用户组。安装器检查镜像校验、导入镜像、实际加载模型、启动应用并等待健康检查。看到“应用已就绪”后继续。重复执行会保留资料，不要运行 `docker compose down -v`。

默认请求本机 8765 端口；被占用时应用自动选择空闲端口，脚本输出实际 URL，不停止占用者。默认只监听 `127.0.0.1`，不开放公网。不要直接在另一台电脑浏览器照抄这个 localhost 地址。

## 3. 设置私网访问（只做一次）

服务器、访问电脑或手机都安装 [Tailscale](https://tailscale.com/docs/install)并加入自己的私网。尚未授权的服务器在 Ubuntu 执行：

```sh
sudo tailscale up
```

本人打开命令给出的授权链接，完成后回到部署目录执行：

```sh
sudo bash Configure-Tailscale.sh
```

首次启用 Serve 可能另需私网管理员批准 HTTPS。脚本输出自己的 `https://主机.私网.ts.net` 地址；将它收藏，以后直接打开。已存在 Serve 路由时脚本会保留配置、打印待核对命令；确认不会覆盖其他服务后再执行。端口发生变化时重新运行本脚本，核对输出的实际转发目标。不启用 Funnel，不把应用直接发布到公网。

Tailscale 由宿主机管理，容器没有其管理权限。工作台默认只允许服务器所属的 Tailscale 账号管理；访问电脑只需 Tailscale 与浏览器，首次连接 Discord 时才需要对应客户端。系统代理影响访问时，使用访问客户端的专用工作台窗口，见[访问教程](ACCESS.md)。Tailscale IP 可用于网络诊断；日常使用本节的 HTTPS 域名，避免证书与授权地址不一致。

## 4. 首次连接 Discord 与出图

在 HTTPS 工作台选择“连接 Discord”，下载适合访问电脑的客户端：Apple Silicon Mac 用 arm64，Windows 用 x64（尚待 Windows 实机验收）。按[首次连接流程](LINUX_SETUP.md#连接-discord)在日常 Chrome / Edge 已正常登录的 Discord 页面确认账号与目标服务器；不要求在无头 Ubuntu 上完成验证码，VNC 仅作备用。

已连接的工作台不重复登录。Mac 本地完整版仍可直接登录，不因 Docker 版而要求安装扩展。

连接后按[首次采集出图](USAGE.md#第一次采集出图)继续：选一个消息少的频道 → 确认保存范围 → 生成首份稿件 → 生成第一张图片 → 查看并下载。首次保存读取整个频道可见历史，稿件日期不会限制采集量。语音已默认启用；转写在 Ubuntu 容器内完成，访问电脑不用装模型。推送仍默认关闭，在此 Docker 工作台配置收件渠道后才能推送。

## 日常管理与资料保存

- 网页“重启应用”只重启容器内应用；“停止服务”保留容器管理进程，重新启动请在部署目录执行 `sudo bash Start-Docker.sh`。
- 设置中的“容器启动后自动运行”控制下次容器启动是否同时启动应用。关闭不影响当前运行；手动 Start 始终可启动。容器自身由 Docker 的 `unless-stopped` 策略恢复，宿主机 Docker 服务也须启用。
- 停止整个容器：`sudo bash Stop-Docker.sh`；重新启动：`sudo bash Start-Docker.sh`。不会删除资料。
- 查看状态与日志：`sudo docker compose ps`、`sudo docker compose logs --tail 80`。日志有大小和轮转上限。
- **没有 Ubuntu 关机或重启功能。** 不挂载 Docker socket、宿主机电源接口、整个家目录，不使用特权容器。

资料分别在 Compose 的 `data`、`output`、`models` 命名卷内；凭据也在本部署 data 卷，不在镜像里。保持同一部署目录及 Compose 项目名，避免误建空资料库。备份时先停止容器，再备份这三个卷并核对能恢复；`docker compose down -v` 会删除卷，禁止用于更新或排错。

本次不自动迁移原生安装。更新先备份，再取得对应版本的部署包和镜像，在原目录按新版本教程操作；不要只导入镜像后以为已切换应用版本。自动另存目录指容器内路径，默认输出保存在 output 卷；如需宿主机固定目录，部署者应只为所需目录配置明确的读写挂载。

## 验收范围

实际验证和限制见 [Docker 验收记录](DOCKER_ACCEPTANCE.md)。GPU 属于可选适配：本版镜像验收的是 CPU INT8；NVIDIA / AMD 需要匹配驱动、运行时和推理依赖，见 [Linux GPU 说明](LINUX.md)，不要仅传入显卡设备就视为已完成适配。
