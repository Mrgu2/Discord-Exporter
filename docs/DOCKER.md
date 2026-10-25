# Ubuntu Docker 安装与使用

适用于 Ubuntu x86_64（amd64）。镜像包含运行环境、浏览器、FFmpeg、中文字体和 small 模型，使用与 Mac 相同的工作台。Mac 继续[原生安装](MAC.md)。

## 1. 准备服务器与文件

服务器需 Docker Engine、Compose v2、Tailscale，建议至少留 12 GiB 空间。检查：

```sh
uname -m
df -h /
sudo docker version
sudo docker compose version
```

架构应为 `x86_64`。缺 Docker 时按 [Docker 官方 Ubuntu 安装说明](https://docs.docker.com/engine/install/ubuntu/)安装 Engine 与 Compose；保留已有容器环境。

从 [Release](https://github.com/Mrgu2/Discord-Exporter/releases/tag/v2026.10.25.2)下载**两个文件**，通过 SFTP / scp 上传到 Ubuntu 的同一个新目录，例如 `~/apps/discordarchive-docker`：

| 文件 | 用途 |
| --- | --- |
| `DiscordArchive-Docker-linux-amd64.zip` | 部署脚本、教程与镜像校验文件 |
| `discordarchive-linux-amd64.tar.gz` | 离线镜像，已含 small 模型，无需手动解压 |

私有仓库需有权限的 GitHub 账号下载，无权限可能返回 404。新部署使用独立数据卷，原生安装不自动迁移或同步。

## 2. 安装并启动

以下在 **Ubuntu SSH 终端**执行，路径换成实际上传目录：

```sh
cd ~/apps/discordarchive-docker
unzip -n DiscordArchive-Docker-linux-amd64.zip
sudo bash Install-Docker.sh
```

缺 `unzip` 时先执行 `sudo apt-get update && sudo apt-get install -y unzip`。安装器导入镜像、实际加载 small CPU INT8 模型并启动应用，看到“**应用已就绪**”后继续。

默认请求 8765 端口，被占用时自动换端口。应用只监听服务器本机，另一台电脑不能直接打开提示中的 `127.0.0.1` 地址，需完成下一节。

## 3. 设置私网访问（只做一次）

服务器和访问设备均安装 [Tailscale](https://tailscale.com/docs/install)，加入自己的私网。服务器尚未授权时执行：

```sh
sudo tailscale up
```

本人打开命令给出的链接完成授权，再回部署目录执行：

```sh
sudo bash Configure-Tailscale.sh
```

首次 Serve 可能还需私网管理员批准 HTTPS。收藏脚本输出的 `https://主机.私网.ts.net` 地址，以后直接打开。已有 Serve 路由时，脚本只打印待核对命令；确认不影响其他服务后再执行。

Tailscale 在宿主机运行，容器无管理权限。工作台仅允许配置的所有者管理；不开放公网、不启用 Funnel。代理阻断浏览器时，使用 [访问客户端](ACCESS.md)。日常使用 HTTPS 域名，Tailscale IP 用于 SSH 维护。

## 4. 首次连接 Discord 与出图

按 [首次连接 Discord](LOGIN_ASSISTANT.md#首次连接-discord)，在自己的 Mac / Windows 日常浏览器确认账号。访问电脑无需项目或模型；连接完成后 Ubuntu 独立运行，已有连接不重复绑定。

再按 [首次采集出图](USAGE.md#第一次采集出图)操作：选小频道 → 保存 → 出稿 → 出图 → 下载。**首次保存读取全部可见历史，稿件日期不限制采集量。** 语音默认启用，推送默认关闭；[推送配置](DELIVERY.md)在此 Ubuntu 工作台完成。

## 日常管理与资料保存

在部署目录执行：

| 操作 | 命令或入口 |
| --- | --- |
| 启动 / 恢复应用 | `sudo bash Start-Docker.sh` |
| 重启应用 | 网页“重启服务”，只重启容器内应用 |
| 停止整个容器 | `sudo bash Stop-Docker.sh` |
| 查看状态 | `sudo docker compose ps` |
| 查看最近日志 | `sudo docker compose logs --tail 80` |

“**容器启动后自动运行**”控制下次是否随容器启动应用，关闭不停止当前应用；手动 Start 始终可启动。Docker 的 `unless-stopped` 策略管理容器恢复，宿主机 Docker 服务须启用。

资料、图片和模型在 `data`、`output`、`models` 命名卷，凭据只在 data 卷。保留同一部署目录和 Compose 项目名。**不要运行 `docker compose down -v`，它会删除资料卷。** 备份先停止容器，再备份三个卷并核对恢复。

更新先备份，取得同版部署包与镜像，按该版本说明操作；仅导入镜像不会切换正在运行的容器。自动另存使用容器内路径；需要宿主机固定目录时，只挂载所需目录。

**Docker 版不控制 Ubuntu 关机或重启。** 不挂载 Docker socket 或电源接口，不使用特权容器。

## 验收范围

[Docker 实测记录](DOCKER_ACCEPTANCE.md)覆盖 Linux amd64 / CPU。NVIDIA、AMD GPU 需另行准备驱动、运行时与镜像，尚未实测；适配方向见 [Linux GPU 说明](LINUX.md#3-语音转写默认-small--cpu)。
