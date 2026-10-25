# Mac 本地安装与登录

流程：**安装与登录 → [首次出图](USAGE.md#第一次采集出图) → [日常使用](OPERATIONS.md)**。

下载 [DiscordArchive-source.zip](DOWNLOADS.md#完整项目)。Apple Silicon 与 Intel Mac 的基础安装使用同一包；当前语音安装仅支持 Apple Silicon。

## 安装

1. 解压 ZIP，把完整 **DiscordArchive** 文件夹放到固定、可写的位置，如 `~/Applications/DiscordArchive`。不要单独移动 App。
2. 双击 **Install.command**，保留终端窗口，等待依赖和浏览器安装完成。
3. 看到“**安装检查通过**”且工作台打开后，继续登录。失败时按 [常见问题](TROUBLESHOOTING.md)处理。

macOS 阻止打开时，到“系统设置 → 隐私与安全性”允许这份可信程序，再重新打开。App 尚未公证，不要关闭系统保护。

<details>
<summary>缺少 Homebrew / 从源码安装</summary>

缺少 Python 或 Node 且没有 Homebrew 时：

1. 打开“终端”，按 [Homebrew 官网](https://brew.sh/)安装。
2. 执行安装末尾“Next steps”给出的环境配置命令。
3. 新开终端，确认 `brew --version` 可用，再双击 **Install.command**。输入系统密码时可能不显示字符。

从 Git 仓库安装：在固定、可写的仓库目录执行 `bash Install.command`，无需 Ubuntu 助手包。已有服务运行时不要移动项目目录。

</details>

## 登录 Discord

1. 在工作台点击 **连接 Discord**。
2. 在专用登录窗口使用 **账号和密码登录**，完成验证码；Mac 本地无需扩展。
3. 工作台显示 **添加频道与答疑人** 后，关闭登录窗口，按 [首次采集出图](USAGE.md#第一次采集出图)继续。

**建议优先使用账号和密码。** 作者多次尝试扫码登录，均卡在人机验证；这属于作者的使用经历，不代表所有人都会遇到。账号密码登录也可能需要验证。

已有有效连接不必重登。日常浏览器已登录，不等于本项目的专用窗口已连接；验证码失败时保留原资料，按 [登录排错](TROUBLESHOOTING.md)处理。

以后双击 **Start.command** 或 **Discord Archive.app**。默认端口 8765，被占用时自动换用空闲端口，以启动提示为准。

按需配置：[语音转写](USAGE.md#语音转写可选) · [定时推送](DELIVERY.md) · [自动启动](OPERATIONS.md#自动启动可选)。只访问已有 Ubuntu 时，按 [访问教程](ACCESS.md)操作。

## 下一步

工作台已显示账号或“添加频道与答疑人”后，点击 **[下一步：首次采集出图](USAGE.md#第一次采集出图)**。
