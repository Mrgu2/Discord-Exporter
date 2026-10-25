# Discord 归档与答疑

保存有权访问的 Discord 频道，按指定答疑人整理文字稿和长图。支持 Mac 本地运行、Ubuntu Docker 部署。

[下载发布包](https://github.com/Mrgu2/Discord-Exporter/releases/tag/v2026.10.25.2) · [Mac 安装](docs/MAC.md) · [Ubuntu Docker 安装](docs/DOCKER.md)

## 主要功能

- **保存消息与附件**：保留原文，后续增量更新。
- **整理答疑**：连接原问题、回答和补充，保留出处。
- **生成长图**：多种版式、手机分栏、标准与 HiDPI PNG。
- **本地语音转写**：转写加入稿件和图片；Mac 可选安装，Docker 已含 small 模型。
- **定时出稿与推送**：自动生成图片，可另存目录，或发到邮箱、Telegram、Discord、微信 ClawBot。
- **后台与私网访问**：支持自启动、暂停和任务恢复；Ubuntu 可独立运行。

资料保存在运行应用的机器上，Mac 与 Ubuntu 不自动同步。推送默认关闭，启用后图片发给指定收件人。使用时遵守 Discord 平台规则。

<details>
<summary>安装与使用教程（Mac / Ubuntu / 手机）</summary>

## 选择使用方式

<a id="需要拿哪些文件"></a>

| 使用场景 | 下载文件 | 教程 |
| --- | --- | --- |
| Mac 本地运行 | [DiscordArchive-source.zip](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.2/DiscordArchive-source.zip) | [安装与登录](docs/MAC.md) |
| Ubuntu Docker（x86_64） | [部署 ZIP](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.2/DiscordArchive-Docker-linux-amd64.zip) + [离线镜像，含 small](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.2/discordarchive-linux-amd64.tar.gz) | [安装与首次连接](docs/DOCKER.md) |
| Mac 访问已有 Ubuntu | [login-assistant-mac.zip](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.2/login-assistant-mac.zip)（仅 M 系列 / arm64） | [日常访问](docs/ACCESS.md) |
| Windows 访问已有 Ubuntu | [login-assistant-windows.zip](https://github.com/Mrgu2/Discord-Exporter/releases/download/v2026.10.25.2/login-assistant-windows.zip)（x64，待实机验收） | [日常访问](docs/ACCESS.md) |
| 手机访问已有工作台 | 安装 Tailscale，无需项目或模型 | [手机访问](docs/ACCESS.md#手机访问与-tailscale-ip) |

Mac 本地直接登录；Ubuntu 首次连接使用浏览器扩展，换电脑访问不重复绑定。客户端架构与文件校验见 [选包说明](docs/DOWNLOADS.md)。

**第一次请选消息少的频道。** 首次保存读取完整可见历史，稿件日期不限制采集量。安装并连接后，按 [首次采集出图](docs/USAGE.md#第一次采集出图)操作。

按需配置：[语音](docs/USAGE.md#语音转写可选) · [自动推送](docs/DELIVERY.md) · [自启动与日常管理](docs/OPERATIONS.md) · [Agent 安装](docs/AGENT_INSTALL.md)。

</details>

## 效果预览

以下为虚构消息。点击图片查看原图。

**工作台**

[![工作台：选择频道、保存消息、生成稿件](docs/images/workspace.png)](docs/images/workspace.png)

**导出长图**

[![导出长图：主题栏目与答疑分区](docs/images/export-example.png)](docs/images/export-example.png)

<details>
<summary>维护、排错与验收</summary>

- [常见问题](docs/TROUBLESHOOTING.md)
- [更新与数据保留](docs/DELIVERY.md#已有安装如何更新)
- [Ubuntu 原生安装（替代方案）](docs/LINUX_SETUP.md)
- [Linux 维护、备用登录与 GPU](docs/LINUX.md)
- [分发包构建](docs/PACKAGING.md) · [发布隐私检查](docs/GITHUB_PRIVACY.md)
- [Docker 实测结果](docs/DOCKER_ACCEPTANCE.md) · [推送实测范围](docs/DELIVERY.md#当前验收范围) · [验证方法](docs/ACCEPTANCE.md)

Mac 与 Ubuntu 的基础采集、语音和出图已有实测。四个推送渠道的真实收件验收完成于 Mac；Ubuntu 需在自己的部署上测试。Windows 客户端尚待实机验收。

</details>
