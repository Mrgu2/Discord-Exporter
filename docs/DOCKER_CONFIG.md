# Docker 配置指南

首次安装只看自己的系统示例，**默认值可直接使用，无需改端口或数据目录**。已有安装请保留 `.env` 和项目名，不用示例覆盖。

配置文件与 `compose.yaml` 放在同一部署目录。账号、频道和推送仍在工作台设置，不填进 `.env`。

<a id="windows"></a>

## Windows：复制后安装

先按 [Windows 准备步骤](WINDOWS_DOCKER.md#1-准备-windows)安装 Docker Desktop 并开启 host networking。完整解压离线包，在解压目录打开 PowerShell，整段复制：

```powershell
if (-not (Test-Path -LiteralPath 'compose.yaml')) {
    throw '请先进入解压后的部署目录。'
} elseif (Test-Path -LiteralPath '.env') {
    throw '.env 已存在，请保留原配置，按日常启动入口操作。'
} else {
    Copy-Item -LiteralPath 'examples/windows.env.example' -Destination '.env' -ErrorAction Stop
    .\Install-Docker.ps1
}
```

示例文件 `examples/windows.env.example` 的完整配置如下，不含需要替换的路径：

```dotenv
COMPOSE_PROJECT_NAME=discordarchive
ARCHIVE_IMAGE=discordarchive-linux:v2026.10.25.3
ARCHIVE_PORT=8765
ARCHIVE_HTTPS_PORT=443
COMPOSE_FILE=compose.yaml
```

安装通过后，继续 [Tailscale HTTPS 与首次连接](WINDOWS_DOCKER.md#4-tailscale-https首次连接与远程访问)。Windows Docker Desktop 尚待实机验收。

<a id="linux"></a>

## Linux：复制后安装

先确认 Docker Engine 和 Compose v2 可用。完整解压离线包，在部署目录的普通用户终端整段复制：

```sh
if [ ! -f compose.yaml ]; then
  echo '请先进入解压后的部署目录。'
elif [ -e .env ]; then
  echo '.env 已存在，请保留原配置，按日常启动入口操作。'
else
  cp -n examples/linux.env.example .env && sudo bash Install-Docker.sh
fi
```

示例文件 `examples/linux.env.example` 的完整配置如下，同样无需替换用户名或路径：

```dotenv
COMPOSE_PROJECT_NAME=discordarchive
ARCHIVE_IMAGE=discordarchive-linux:v2026.10.25.3
ARCHIVE_PORT=8765
ARCHIVE_HTTPS_PORT=443
COMPOSE_FILE=compose.yaml
```

看到“应用已就绪”后，继续 [Tailscale HTTPS 与首次连接](DOCKER.md#3-设置私网访问只做一次)。

## 默认文件保存在哪里

消息、配置、图片和模型在 Docker 命名卷中，重新启动不会丢失。手动下载的 PNG 在浏览器下载目录。

需要把图片额外存到自己的文件夹、换端口或限制资源时，再展开下面的高级选项。不要执行 `docker compose down -v`，它会删除资料卷。

## 高级选项

<details>
<summary>数据卷、文件位置与备份范围</summary>

## 文件与数据位置

| 位置 | 放什么 | 更新时怎么办 |
| --- | --- | --- |
| 部署目录 | Compose、启动脚本、`.env`、教程 | 保留自己的 `.env` 与本地覆盖文件 |
| `data` 命名卷 → `/app/data` | 原文、配置、连接、任务状态 | 先停容器再备份，含敏感凭据 |
| `output` 命名卷 → `/app/output` | 稿件与图片 | 保留，不删除旧输出 |
| `models` 命名卷 → `/app/.runtime/models` | 本地 small 模型 | 镜像首次创建卷时提供模型，可另备份 |
| 可选宿主机目录 → `/exports` | 自动另存的图片副本 | 宿主机直接查看；不取代原始归档 |

命名卷由 Docker 管理。Windows 下位于 Docker Desktop 的 Linux 虚拟机，不要手工改其内部文件或把数据库放进 OneDrive。查看实际卷名：

```sh
docker volume ls
```

按 Compose 项目前缀查找。不要为了“找回文件”创建另一个空项目或执行 `down -v`。

</details>

<details>
<summary>变量含义与配置生效</summary>

## `.env` 放在哪里

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `COMPOSE_PROJECT_NAME` | `discordarchive` | 决定容器和卷的名称；改名会得到另一套资料库 |
| `ARCHIVE_IMAGE` | 当前已验收镜像标签 | 选择镜像；离线文件与标签须配套 |
| `ARCHIVE_PORT` | `8765` | 请求的本机监听端口，冲突时应用尝试后续端口 |
| `ARCHIVE_HTTPS_PORT` | `443` | 宿主机 Tailscale Serve 端口，仅支持 443 / 8443 |
| `COMPOSE_FILE` | `compose.yaml` | 选择可选覆盖文件，见下节 |
| `ARCHIVE_EXPORT_DIR` | 无 | 仅导出目录覆盖文件启用时有效 |
| `ARCHIVE_CPUS` / `ARCHIVE_MEMORY` | 无限制；启用资源模板时为 2 / 4g | 限制本容器 CPU 与内存，不修改宿主机设置 |

修改 `.env` 后运行平台的 **Start-Docker**。Compose 会按需重建容器，保留命名卷；不是仅刷新网页。Linux Docker 用 `sudo bash Start-Docker.sh`，Windows 用 `Start-Docker.cmd`。

同名 shell 环境变量会优先于 `.env`。排错时检查自己设置的变量；不要把 Token、密码或整个环境输出贴到日志。单引号可保留值中的 `$`，复杂格式按 [Compose 官方语法](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)处理。

</details>

<details>
<summary>更换端口与 Tailscale 转发</summary>

## 端口与“映射”

本包使用 `network_mode: host`，应用只绑定 `127.0.0.1`。**宿主机与容器共用该监听端口，不使用 `ports:` 或 `-p`。** 这些参数在 host 模式下无效，不能照搬常见的 `18765:8765` 写法。[Docker 官方说明](https://docs.docker.com/engine/network/drivers/host/)

例如改为：

```dotenv
ARCHIVE_PORT=18765
```

重新 Start 后，以脚本输出的实际地址为准，如 `http://127.0.0.1:18765`。普通桥接映射尚未适配本项目的本机身份与 Tailscale 校验，不直接改成 bridge 或开放 `0.0.0.0`。

端口变化后重跑 **Configure-Tailscale**，核对其输出命令，再确认 HTTPS 可用。HTTPS 域名的 443 与后端应用端口是两件事。

</details>

<details>
<summary>图片另存：Windows / Linux 直接复制示例</summary>

## 图片另存到自己的目录

只额外挂载 `exports` 图片目录，数据库和模型继续用命名卷。以下命令在部署目录执行，不会修改现有 `.env`。

### Windows 示例

```powershell
New-Item -ItemType Directory -Path 'exports' -Force | Out-Null
if (-not (Test-Path -LiteralPath 'compose.exports.yaml')) {
    Copy-Item -LiteralPath 'examples/compose.exports.example.yaml' -Destination 'compose.exports.yaml' -ErrorAction Stop
}
```

按 `examples/windows.exports.env.example` 修改 `.env` 中这两项，其他行保留：

```dotenv
ARCHIVE_EXPORT_DIR=./exports
COMPOSE_FILE=compose.yaml;compose.exports.yaml
```

### Linux 示例

```sh
mkdir -p exports
cp -n examples/compose.exports.example.yaml compose.exports.yaml
```

按 `examples/linux.exports.env.example` 修改 `.env` 中这两项，其他行保留：

```dotenv
ARCHIVE_EXPORT_DIR=./exports
COMPOSE_FILE=compose.yaml:compose.exports.yaml
```

两平台都将图片副本放到部署目录下的 `exports/`。如需另选目录，再将 `./exports` 换成自己已创建的绝对路径；Windows 用正斜线，如 `D:/DiscordArchive/exports`。Linux 目录需对容器 UID 1000 可写，不递归改旧资料权限。

修改后运行 **Start-Docker**，在工作台“导出设置 → 自动另存目录”填写 **`/exports`** 并保存。生成一张图片，确认宿主机目录收到副本。不要在网页填 Windows 盘符路径；失败时原图仍保留在 output 卷。

</details>

<details>
<summary>CPU / 内存限制</summary>

## 可选 CPU / 内存上限

将 `examples/compose.resources.example.yaml` 复制为 `compose.resources.yaml`，保留 `.env` 的其他行，按自己的系统修改 `COMPOSE_FILE`：

| 使用方式 | Windows | Linux |
| --- | --- | --- |
| 仅限制资源 | `compose.yaml;compose.resources.yaml` | `compose.yaml:compose.resources.yaml` |
| 资源限制 + 图片另存 | `compose.yaml;compose.exports.yaml;compose.resources.yaml` | `compose.yaml:compose.exports.yaml:compose.resources.yaml` |

再设置上限，重新 Start：

```dotenv
ARCHIVE_CPUS=2
ARCHIVE_MEMORY=4g
```

默认不启用这些限制；4g 是上限，不是所有任务的最低需求。限制过低可能使语音或大图中断。GPU 需另行适配。

</details>

<details>
<summary>检查配置与变量优先级</summary>

## 检查配置

在部署目录运行：

```sh
docker compose config --quiet
docker compose ps
```

Linux 可执行 `sudo bash Doctor-Docker.sh`；Windows 用 `Doctor-Docker.cmd`。健康检查还会核对资料库身份，不能只看容器显示 running。

`.env` 变量不会自动全部传入应用；只有 Compose 中声明的变量生效。不要在里面加入未支持的 `PUID`、`PGID` 或账号 Token，并假定程序会使用它们。

同名 shell 环境变量优先于 `.env`。语法见 [Compose 变量说明](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)。

</details>

<details>
<summary>备份、恢复与更新</summary>

## 备份

备份会停止当前容器。选择一个新的目标目录，避免覆盖旧备份；备份包含 Discord 与推送凭据，须私下保管。

**Windows：**

```powershell
.\Backup-Docker.ps1 -Destination D:\DiscordArchiveBackups\backup-01
# 连公共模型一起备份时加 -IncludeModels
```

脚本生成 `BACKUP-MANIFEST.json`，记录文件 SHA-256；完成后容器保持停止，按需运行 Start-Docker 恢复。

**Linux：**先创建新的空备份目录，在部署目录执行；把 `/备份目录` 替换为实际路径：

```sh
sudo bash Stop-Docker.sh
mkdir -p /备份目录/data /备份目录/output
sudo docker compose cp app:/app/data/. /备份目录/data
sudo docker compose cp app:/app/output/. /备份目录/output
```

另存 `.env`、Compose 与覆盖文件，并核对文件能读取；需要模型时另备份 `/app/.runtime/models`。命名卷不是备份，镜像也不包含自己的资料。

## 恢复与更新

恢复先在**新项目名的空卷**演练，不覆盖正在使用的资料库：初始化同版容器 → 停止应用 → 将 data/output 备份复制进对应卷 → 核对容器 UID 1000 可读写 → 启动并检查消息、稿件和连接。不要合并两个账号的凭据文件。恢复工具与跨 Windows/Linux 的权限差异尚未实机验收，遇到权限问题先保留备份再求助。

更新先备份，核对新镜像与部署文件配套，在原目录保留 `.env` 和项目名后运行安装入口。保持同一卷，禁止 `docker compose down -v` 或清空旧 data。仅导入新镜像不会替换正在运行的容器。

本次配置预览包使用 v2026.10.25.3 镜像，包含容器停止竞态修复；Linux、Windows 预览入口与测试边界见 [配置包验收](DOCKER_CONFIG_ACCEPTANCE.md)。

</details>
