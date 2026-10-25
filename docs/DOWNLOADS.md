# 获取安装包

当前版本：**v2026.10.25.3（预览版）**。[打开 Release](https://github.com/Mrgu2/Discord-Exporter/releases/tag/v2026.10.25.3)，在 **Assets** 中下载。私有仓库需有权限的 GitHub 账号；无权限可能返回 404。

| 用途 | 文件 | 教程 |
| --- | --- | --- |
| Mac 本地完整安装 | [DiscordArchive-source.zip](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.3/DiscordArchive-source.zip) | [Mac](MAC.md) |
| Ubuntu Docker（x86_64） | [部署 ZIP](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.3/DiscordArchive-Docker-linux-amd64.zip) + [离线镜像，含 small](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.3/discordarchive-linux-amd64.tar.gz) | [Docker](DOCKER.md) |
| Windows 本机 Docker（x64，预览） | [完整离线 ZIP](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.3/DiscordArchive-Docker-complete-preview.zip) | [Windows Docker](WINDOWS_DOCKER.md)，未实机验收 |
| Mac 访问 Ubuntu | [login-assistant-mac.zip](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.3/login-assistant-mac.zip)（仅 M 系列 / arm64） | [访问](ACCESS.md) |
| Windows 访问 Ubuntu | [login-assistant-windows.zip](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.3/login-assistant-windows.zip)（x64，待实机验收） | [访问](ACCESS.md) |

Linux 也可下载同一个[完整离线 ZIP](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.3/DiscordArchive-Docker-complete-preview.zip)，其中已含镜像；不要同时重复下载独立镜像。仅需小配置包时，可选 [Windows 配置 ZIP](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.3/DiscordArchive-Docker-desktop-preview.zip)并配套同版镜像。

**不要选 GitHub 自动生成的 Source code (zip)**：它没有构建好的 App 和内嵌客户端。仅访问 Ubuntu 的电脑不用安装完整项目或模型。

## 完整项目

`DiscordArchive-source.zip` 解压得到 **DiscordArchive/**，Mac 依赖在安装时准备。Ubuntu 原生替代安装也使用此包，见 [原生教程](LINUX_SETUP.md)。包内没有私人资料或模型，`helpers/` 内含 Mac 首次连接包。

已看到 `Install.command`、`app.py` 和 `docs/` 时，无需再次下载源码包。

## Mac 访问客户端

`login-assistant-mac.zip` 适用于 **Apple Silicon（M 系列 / arm64）**，不适用于 Intel。它用于 Ubuntu 首次连接和日常访问，Mac 本地完整版不需要此包。App 尚未公证，仅对核对过的可信包按系统提示允许打开。

## Windows 访问客户端

`login-assistant-windows.zip` 适用于 **Windows x64**，尚待 Windows 实机验收；不是 Windows 本地完整版或 ARM 客户端。

## 核对文件

下载 [CHECKSUMS.sha256](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.3/CHECKSUMS.sha256)，对照所选文件的 SHA-256：

```sh
# Mac；文件名换成自己下载的文件
shasum -a 256 DiscordArchive-source.zip
# Ubuntu
sha256sum DiscordArchive-Docker-linux-amd64.zip
```

Windows PowerShell：`Get-FileHash .\login-assistant-windows.zip -Algorithm SHA256`。

只有下载了清单内全部文件，才用 `shasum -a 256 -c CHECKSUMS.sha256` 或 `sha256sum -c CHECKSUMS.sha256` 批量检查；否则会提示其他文件缺失。Docker 部署 ZIP 内另有仅核对镜像的校验文件，供安装器使用。校验不一致时重新下载。

维护者构建说明见 [打包](PACKAGING.md)。
