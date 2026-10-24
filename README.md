# Discord 本地归档与答疑整理

保存自己有权访问的 Discord 频道，围绕指定答疑人整理文字稿和长图。支持 Mac 本地运行，也可部署到 Ubuntu 后通过私网访问。

## 主要功能

- **保存消息与附件**：保留原文，后续增量更新。
- **整理答疑**：围绕指定发言人，结合原问题、回复和后续补充生成稿件。
- **生成长图**：支持多种版式、手机分栏和 PNG 下载。
- **本地语音转写**：保存原音频，选装模型后将转写文字加入稿件和图片。
- **自动运行**：可选自动保存、定时出稿和系统启动后运行，也能随时暂停。
- **私网工作台**：Ubuntu 可通过 Tailscale HTTPS 访问，服务器独立处理，不需要访问电脑一直开着。

数据保存在运行项目的机器上，Mac 和 Ubuntu 的资料不自动同步。只使用自己有权查看的频道；账号自动读取仍受 Discord 平台规则约束。

<details>
<summary><strong>安装与使用教程</strong></summary>

选择与你用途对应的一篇即可：

| 我要做什么 | 打开教程 |
| --- | --- |
| 在 Mac 本地安装、直接登录 Discord | [Mac 安装与登录](docs/MAC.md) |
| 第一次部署 Ubuntu 服务器 | [Ubuntu 安装与首次连接](docs/LINUX_SETUP.md) |
| 在新电脑访问已经部署好的 Ubuntu | [访问已有 Ubuntu](docs/ACCESS.md) |
| 已经打开工作台，开始采集和出图 | [使用教程](docs/USAGE.md#第一次采集出图) |
| 配置语音转写 | [语音配置](docs/USAGE.md#语音转写可选) |

**Mac 本地直接登录，不需要扩展。只有 Ubuntu 首次连接或重连时才用扩展；访问已连接的 Ubuntu 不重复绑定。**

<a id="需要拿哪些文件"></a>

### 准备哪些文件

| 用途 | 所需文件 |
| --- | --- |
| Mac 本地完整安装 | `DiscordArchive-source.zip` |
| Ubuntu 服务端安装 | `DiscordArchive-source.zip`，以及访问电脑对应的客户端包 |
| Mac 访问 Ubuntu | `login-assistant-mac.zip` |
| Windows 访问 Ubuntu | `login-assistant-windows.zip` |

仅访问 Ubuntu 的电脑不需要安装完整项目或语音模型。首次采集先选一个已知的小频道；保存会读取该频道完整可见历史，日期筛选只限制稿件范围。

</details>

<details>
<summary><strong>维护、排错与开发说明</strong></summary>

- [日常管理、自启动与定时出稿](docs/OPERATIONS.md)
- [常见问题](docs/TROUBLESHOOTING.md)
- [Linux 维护、备用登录和 GPU 配置](docs/LINUX.md)
- [分发包构建与文件位置](docs/PACKAGING.md)
- [当前版本验证与平台限制](docs/FINAL_PACKAGE_ACCEPTANCE.md)
- [GitHub 上传与隐私检查](docs/GITHUB_PRIVACY.md)

已实测 Apple Silicon Mac 与 Ubuntu 22.04 x86_64。Windows 访问客户端已构建，尚待实机验证；其他平台及登录验证的具体边界见验证记录。

</details>
