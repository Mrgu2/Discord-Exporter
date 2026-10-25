# 获取安装包

当前版本：**v2026.10.25.3（预览版）**。[打开 Release](https://github.com/Mrgu2/Discord-Exporter/releases/tag/v2026.10.25.3)，在 **Assets** 中下载。私有仓库需有权限的 GitHub 账号；无权限可能返回 404。

## 首次安装：只选一个包

| 安装在哪台电脑 | 下载文件 | 教程 |
| --- | --- | --- |
| Mac | [DiscordArchive-source.zip](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.3/DiscordArchive-source.zip) | [Mac 安装](MAC.md) |
| Ubuntu / Windows x64 | [DiscordArchive-Docker-complete-preview.zip](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.3/DiscordArchive-Docker-complete-preview.zip)（约 1.31 GB） | [Ubuntu](DOCKER.md) · [Windows（预览）](WINDOWS_DOCKER.md) |

**Ubuntu 和 Windows 用同一个 Docker 完整包**，已含镜像、运行环境和 small 模型。解压后按自己的系统教程安装，不用再下载其他包。宿主机仍需安装 Docker；首次连接和私网访问需要网络。Windows Docker 尚未实机验收。

<a id="完整项目"></a>

Mac 包解压后是 `DiscordArchive/`，双击 `Install.command`；依赖在安装时下载。已看到 `Install.command` 和 `app.py` 时，无需重复下载。

不要选 GitHub 自动生成的 **Source code (zip)**，它没有构建好的 App 和内嵌客户端。

## 登录助手：访问已有 Ubuntu

按 [访问教程](ACCESS.md)操作，不用安装完整项目或模型。浏览器能直接访问时，无需下载客户端；代理冲突时可用专用窗口。

| 访问电脑 | 可选客户端 |
| --- | --- |
| M 系列 Mac（arm64） | [login-assistant-mac.zip](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.3/login-assistant-mac.zip)，不适用于 Intel Mac |
| Windows x64 | [login-assistant-windows.zip](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.3/login-assistant-windows.zip)，待实机验收 |

手机按 [手机访问](ACCESS.md#手机访问与-tailscale-ip)操作。上述客户端不是本机完整版；Mac App 尚未公证，仅对核对过的可信包按系统提示允许打开。

<details>
<summary>高级：已有同版镜像，只下载配置包</summary>

**首次安装不用看这里。** 以下是完整 Docker 包的拆分下载方式，功能相同，用于复用已有镜像或分次下载。

| 系统 | 配置包 |
| --- | --- |
| Ubuntu | [DiscordArchive-Docker-linux-amd64.zip](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.3/DiscordArchive-Docker-linux-amd64.zip) |
| Windows x64（预览） | [DiscordArchive-Docker-desktop-preview.zip](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.3/DiscordArchive-Docker-desktop-preview.zip) |

解压配置包，将[同版镜像 discordarchive-linux-amd64.tar.gz](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.3/discordarchive-linux-amd64.tar.gz)放在 `Install-Docker.sh` / `Install-Docker.cmd` 旁。镜像不要手动解压。已有完整 ZIP 时，无需这些文件。

Ubuntu 原生安装是替代方案，使用 Mac 同名的源码包，见 [原生教程](LINUX_SETUP.md)。

</details>

## 核对文件

下载 [CHECKSUMS.sha256](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.3/CHECKSUMS.sha256)，对照所选文件的 SHA-256：

```sh
# Mac；文件名换成自己下载的文件
shasum -a 256 DiscordArchive-source.zip
# Ubuntu
sha256sum DiscordArchive-Docker-complete-preview.zip
```

Windows PowerShell：`Get-FileHash .\DiscordArchive-Docker-complete-preview.zip -Algorithm SHA256`。

只有下载了清单内全部文件，才用 `shasum -a 256 -c CHECKSUMS.sha256` 或 `sha256sum -c CHECKSUMS.sha256` 批量检查；否则会提示其他文件缺失。Docker 部署 ZIP 内另有仅核对镜像的校验文件，供安装器使用。校验不一致时重新下载。

维护者构建说明见 [打包](PACKAGING.md)。
