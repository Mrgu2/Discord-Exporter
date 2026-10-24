# Ubuntu 安装与首次连接

以下用于 **Ubuntu 22.04 首次安装**；已有安装沿用原目录和资料，不另建实例。示例新目录为 `~/apps/DiscordArchive`。准备普通 SSH 账号、sudo、Python 3.10+、数 GiB 可用空间，以及收到的可信文件：

- `DiscordArchive-source.zip`：完整源码，只在 Ubuntu 安装。
- `login-assistant-mac.zip`：Apple Silicon Mac 连接工具与访问客户端，包含首次连接组件。
- `login-assistant-windows.zip`：Windows x64 连接工具与访问客户端（尚待实机验收）。只需准备实际使用的平台包；两平台都用时才准备两个。

可先通过 SSH/SFTP 上传源码 ZIP 和对应平台的连接包 ZIP 到服务器用户主目录；不需要在客户端安装完整项目。SSH 只用于服务器首次部署和维护，日常不用建立隧道。命令中的用户名、地址、端口和本地路径须替换；`scp` 的端口参数是大写 `-P`，`ssh` 为小写 `-p`。

## 安装环境与后台服务

**在 Ubuntu 的 SSH 终端执行：**首次连接先通过可信途径核对服务器主机指纹。

```sh
python3 --version
df -h /
sudo apt-get update
sudo apt-get install -y unzip python3-venv
mkdir -p ~/apps
unzip -n ~/DiscordArchive-source.zip -d ~/apps
cd ~/apps/DiscordArchive
bash scripts/install_linux.sh --with-system-deps
```

Python 应为 3.10+。看到“**Linux 环境检查通过**”后继续：

```sh
sudo loginctl enable-linger "$USER"
python3 scripts/install_linux_service.py --install --no-autostart
python3 scripts/install_login_assistants.py --mac-zip ~/login-assistant-mac.zip
```

Mac 包已经内嵌在源码 ZIP 中：只上传源码时，可改用 `--mac-zip helpers/login-assistant-mac.zip` 发布；访问电脑仍拿单独 Mac ZIP，先由客户端打开工作台。上例发布 Mac 包；只用 Windows 时改为 `--windows-zip ~/login-assistant-windows.zip`，两者都用时同时传两个参数。发布器会拒绝缺少首次连接组件或协议版本不匹配的旧访问包。

确认 `ActiveState=active`、非零 `MainPID`。linger 让服务退出 SSH 后继续运行；`--no-autostart` 不开启下次开机自启动，以后在设置中自行选择。助手包先校验再发布，替换旧包时保留备份；不包含任何账号或模型。

需要语音时，仍在 **Ubuntu 项目目录**执行：

```sh
python3 scripts/install_speech.py
```

默认 **small 多语言模型、CPU / INT8**，无需独立 GPU。看到“**语音环境和模型已实际加载**”才继续；客户端不用安装模型。暂时跳过可在以后补装，详见 [语音配置](USAGE.md#语音转写可选)。

## 启用 Tailscale HTTPS

服务器与访问电脑都按 [Tailscale 官方说明](https://tailscale.com/docs/install)安装客户端，并加入自己的私网。Ubuntu 安装方式见 [官方 Linux 安装说明](https://tailscale.com/docs/install/linux)。Tailscale 不由本项目自动注册账号。

**在 Ubuntu 执行：**

```sh
sudo tailscale up --hostname discordarchive-ubuntu
```

按终端给出的链接本人登录并批准这台服务器；保持命令等待到成功，已登录的服务器不必重复操作。然后在 **Ubuntu 项目目录**执行：

```sh
python3 scripts/configure_tailscale.py
sudo tailscale serve --bg http://127.0.0.1:8765
systemctl --user restart discordarchive.service
```

第一次使用 Serve 若出现启用 HTTPS 的网页链接，按提示由私网管理员确认，回终端等待完成；这可能是加入设备后另一轮确认，不要以为刚才登录失败。成功后执行 `tailscale serve status`，应显示实际 HTTPS 地址和 `127.0.0.1:8765` 转发目标；此时才继续。

配置器默认只允许该服务器注册时所属的 Tailscale 用户管理工作台；需要显式指定所有者时用 `--owner Tailscale登录名`。它会输出类似 `https://主机.私网.ts.net` 的固定地址，收藏自己的实际地址，别照抄别人的域名。

应用仍只监听 `127.0.0.1:8765`，由 Serve 提供私网 HTTPS；不开放公网，不启用 Funnel。工作台通过可信的 Serve 身份头识别获准管理员，不必再填工作台访问口令。其他用户、缺少身份头或公网转发均不获得管理权限。

## 连接 Discord

**已有部署且工作台显示“已连接”时跳过此节。换电脑不会要求服务器重新登录 Discord。**

首次部署只做一次，使用 **Chrome / Edge 日常浏览器**，不在服务器上开 VNC，不在自动化窗口反复登录：

1. **先在访问电脑解压随部署包收到的对应客户端**，双击 **Ubuntu Workspace.app / Ubuntu Workspace.exe**，由专用直连窗口打开工作台；无预填地址时输入服务器配置器输出的 HTTPS 地址。不要先依赖普通浏览器打开 HTTPS 才去下载客户端，系统代理可能阻断这一步。进入工作台后也可用 **首次连接 Discord** 下载服务器专用包。Mac 双击包内 **首次连接 Discord.app**，Windows 双击 **Connect Discord.cmd**；它只安装当前用户的本机连接组件，不需要完整项目或模型。
2. 在 Chrome 打开 `chrome://extensions/`（Edge：`edge://extensions/`），开启 **开发者模式 → 加载已解压的扩展**，选择包内 **Browser Extension** 文件夹。当前扩展未上架，这个手动加载步骤只做一次。升级已加载的同目录扩展时点刷新，并按浏览器提示确认新增权限。
3. 在日常浏览器本人正常登录 [Discord](https://discord.com/channels/@me)，停在 Discord 标签页，点击扩展图标。新页显示目标服务器，点 **识别当前 Discord 账号**；它会刷新所选 Discord 标签页，识别后显示账号。核对服务器和账号，再点 **确认连接此账号**。
4. 只有页面提示 **连接成功**，并且 Ubuntu 工作台识别到账号，才算完成。自动任务保持暂停，先按 [首次出稿](USAGE.md#第一次采集出图)验证一个小频道。连接完成后，可关闭本机客户端或移除扩展，Ubuntu 独立采集；以后换电脑只需访问，不重复本节。

取消、超时和验证失败不会提交连接；服务器已有另一账号时不会直接覆盖。密码、验证码由本人在日常浏览器处理，不粘贴到工作台、终端或聊天里；工具不绕过 Discord 人机验证。浏览器无法正常登录 Discord 时，先处理浏览器的登录问题。

这是一条经本人确认的账号连接迁移流程，**不是 Discord 官方 OAuth**。普通 OAuth 的身份授权不等于频道历史读取权限；连接仍可能过期，届时重复本节即可。Mac 到空 Ubuntu 的首次连接与独立采集已实测；Windows 包已构建，尚待实机验收。详见 [首次连接验收与限制](FIRST_LOGIN_ACCEPTANCE.md)。

连接成功后按 [第一次采集出图](USAGE.md#第一次采集出图)验证一个小频道。以后的访问见 [访问已有 Ubuntu](ACCESS.md)。
