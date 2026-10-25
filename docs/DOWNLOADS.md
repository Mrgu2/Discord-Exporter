# 获取安装包

当前交付版本：**v2026.10.25.1（预览版）**。

## 从哪里取得

打开 [GitHub Releases](https://github.com/Mrgu2/Discord-Exporter/releases/tag/v2026.10.25.1)，在 **Assets** 中选择对应 ZIP。仓库目前为私有，需要登录拥有访问权限的 GitHub 账号；无权限时下载链接可能显示 404。

| 用途 | 下载 |
| --- | --- |
| Mac 本地完整安装 / Ubuntu 服务端 | [DiscordArchive-source.zip](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.1/DiscordArchive-source.zip) |
| Apple Silicon Mac 访问 Ubuntu | [login-assistant-mac.zip](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.1/login-assistant-mac.zip) |
| Windows x64 访问 Ubuntu | [login-assistant-windows.zip](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.1/login-assistant-windows.zip) |
| 校验上述三个 ZIP | [CHECKSUMS.sha256](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.1/CHECKSUMS.sha256) |

不要将 GitHub 自动生成的 **Source code (zip)** 当作 `DiscordArchive-source.zip`：自动源码快照没有构建好的原生入口和内嵌客户端。需要本地重新构建时，见 [打包说明](PACKAGING.md)。本版构建产物位于项目的 `dist/releases/v2026.10.25.1/`，这一路径仅供维护者使用。

**如果已解压源码 ZIP，并能看到 Install.command、app.py 和 docs/，你已经拿到完整项目，无需再次下载源码包。** 直接进入 [Mac 安装](MAC.md) 或 [Ubuntu 安装](LINUX_SETUP.md)。

## 完整项目

文件：`DiscordArchive-source.zip`。用于 Mac 本地运行或 Ubuntu 服务端部署，解压后得到 `DiscordArchive/` 文件夹；依赖在安装时准备，不包含私人消息、凭据或模型。Ubuntu 的 Mac 首次连接包同时内嵌于源码包 `helpers/` 中。

## Mac 访问客户端

文件：`login-assistant-mac.zip`。当前架构为 **darwin-arm64，只适用于 Apple Silicon（M1 / M2 / M3 / M4 等 M 系列）**；不是 Intel Mac（x86_64）客户端。可在“苹果菜单 → 关于本机”查看芯片；Intel 用户不要误装该包。

这是访问 Ubuntu 的客户端和首次连接工具，不需要在 Mac 安装完整项目或模型。使用见 [访问已有 Ubuntu](ACCESS.md)，首次连接见 [Ubuntu 教程](LINUX_SETUP.md#连接-discord)。Mac 本地运行完整项目不使用这个客户端包。

## Windows 访问客户端

文件：`login-assistant-windows.zip`，架构 **Windows x64**。已构建并校验组件，尚未完成 Windows 实机验收；不要把它当成已验证的 Windows ARM 原生包。

## 核对文件

分发目录还包含 `FILES.txt` 和 `CHECKSUMS.sha256`。先根据 FILES.txt 选择文件，再在该目录执行：

```sh
# Mac
shasum -a 256 -c CHECKSUMS.sha256
# Ubuntu
sha256sum -c CHECKSUMS.sha256
```

Windows PowerShell 可分别执行 `Get-FileHash .\DiscordArchive-source.zip -Algorithm SHA256`（客户端文件同理），对照 CHECKSUMS.sha256 的对应行。未通过校验时重新取得文件，不覆盖已有资料。
