# 访问已经部署好的 Ubuntu

服务器已连接 Discord 时，换电脑不用重新绑定，也不需要安装完整项目。

先按 [获取安装包](DOWNLOADS.md)准备文件：Apple Silicon（M 系列，arm64）Mac 用 `login-assistant-mac.zip`；该客户端不适用于 Intel Mac。Windows x64 用 `login-assistant-windows.zip`（尚待实机验收）。

1. 在新电脑安装并登录自己的 Tailscale，使用服务器获准的同一身份。
2. 完整解压对应访问客户端，Mac 双击 **Ubuntu Workspace.app**，Windows 双击 **Ubuntu Workspace.exe**。需要已安装 Chrome 或 Edge。
3. 客户端直接打开私网工作台，不弹配对页或 Discord 登录页。同私网中名称以 `discordarchive` 开头且属于本人管理的工作台可自动发现；只有找不到唯一服务器时才提示输入一次 HTTPS 地址。

**地址可以修改：**Mac 打开包内 **设置工作台.app**，Windows 打开 **设置工作台.cmd**，填写服务器实际 HTTPS 地址并保存。服务器专用下载包已预填地址。客户端只记住这个公开地址，不保存 Discord 登录连接，也不注册浏览器桥接组件。

工作台地址也可收藏在普通浏览器；系统代理有冲突时用轻客户端的专用直连窗口，不修改全局代理。约 3 MB 的客户端不需要项目运行环境或模型。当前 Mac 包为 Apple Silicon，Windows x64 尚待实机验收；Mac 仅本地签名，未 Developer ID 公证，首次只对可信包按系统提示允许打开。

需要恢复已停止的服务器服务，见 [日常管理](OPERATIONS.md#以后如何打开)。

## 手机访问与 Tailscale IP

手机安装 Tailscale，登录获准的账号并保持连接，然后在浏览器打开 Ubuntu 的 HTTPS 工作台地址，无需安装项目或模型。Ubuntu 默认只监听本机，请使用 HTTPS 域名；Tailscale IP 可以用于 SSH，但直接打开 `http://100.x.x.x:8765` 不适用于该部署。

如果项目运行在 Mac，且开启局域网监听，手机连接同一 Tailscale 私网后，也可以打开 `http://Mac的Tailscale-IP:实际端口`。IP 可在 Tailscale 设备列表查看，端口以工作台启动提示为准；首次访问按页面完成配对，不开放公网端口。
