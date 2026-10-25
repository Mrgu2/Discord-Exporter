# 访问已有 Ubuntu

服务器已连接 Discord 后，换电脑无需重绑，也不用安装项目或语音模型。

1. 在访问电脑安装 Tailscale，登录服务器获准的账号。
2. 在浏览器打开部署时保存的 HTTPS 工作台地址。
3. 若系统代理阻断访问，改用下面的访问客户端。

## 使用访问客户端

| 电脑 | 文件 | 打开入口 |
| --- | --- | --- |
| Apple Silicon Mac（M 系列 / arm64） | [下载 Mac 登录助手](https://github.com/Mrgu2/Discord-Exporter/releases/download/v0.1.2/login-assistant-mac.zip) | **打开工作台.command** |
| Windows x64 | [下载 Windows 登录助手](https://github.com/Mrgu2/Discord-Exporter/releases/download/v0.1.2/login-assistant-windows.zip) | **Ubuntu Workspace.exe** |

文件见 [下载说明](DOWNLOADS.md)。完整解压，并安装 Chrome 或 Edge。Mac 包不适用于 Intel；Windows 包尚待实机验收，Mac App 尚未公证。

客户端使用专用窗口直连私网，不改全局代理。服务器专用包已填地址；否则尝试发现本人名下唯一的 `discordarchive` 工作台，找不到时输入一次 HTTPS 地址。

修改地址：Mac 打开 **设置工作台.command**，Windows 打开 **设置工作台.cmd**。这些入口应与主 App 保持同目录。客户端只保存地址，不保存 Discord 凭据；关闭窗口不影响服务器任务。TUN 或企业强制代理需另行诊断。

服务器服务已停止时，按 [启动方法](OPERATIONS.md#以后如何打开)恢复；首次账号连接见 [首次连接 Discord](LOGIN_ASSISTANT.md#首次连接-discord)。

## 手机访问与 Tailscale IP

手机安装 Tailscale，登录获准的账号，再用浏览器打开 Ubuntu 的 HTTPS 地址。Ubuntu 默认只监听本机，不能直接用 `http://100.x.x.x:8765` 访问；Tailscale IP 可用于 SSH 维护。

项目在 Mac 上运行且开启局域网监听时，手机也可打开 `http://Mac的Tailscale-IP:实际端口`，按页面完成配对。IP 在 Tailscale 设备列表查看，端口以启动提示为准。不开放公网端口。

## 下一步

- 工作台已显示正确账号：**[下一步：采集并生成图片](USAGE.md#第一次采集出图)**。
- 工作台提示尚未连接 Discord：**[先完成首次连接](LOGIN_ASSISTANT.md#首次连接-discord)**。

以后如何打开、启动和停止，见 [日常使用](OPERATIONS.md#以后如何打开)。
