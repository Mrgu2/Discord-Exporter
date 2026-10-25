# Ubuntu 原生安装与首次连接

新部署推荐 [Docker 版](DOCKER.md)，镜像已包含浏览器、small 模型和运行环境。本页保留原生安装流程；已有原生安装不自动迁移。

以下用于 **Ubuntu 22.04 首次安装**；已有安装沿用原目录和资料，不另建实例。示例新目录为 `~/apps/DiscordArchive`。准备普通 SSH 账号、sudo、Python 3.10+、数 GiB 可用空间，以及收到的可信文件：

- `DiscordArchive-source.zip`：完整源码，只在 Ubuntu 安装。
- `login-assistant-mac.zip`：Apple Silicon Mac 连接工具与访问客户端，包含首次连接组件。
- `login-assistant-windows.zip`：Windows x64 连接工具与访问客户端（尚待实机验收）。只需准备实际使用的平台包；两平台都用时才准备两个。

## 先从访问电脑上传文件

先按 [获取安装包](DOWNLOADS.md)取得完整分发目录。下面前三条命令在**访问电脑**的终端执行（Mac 终端或 Windows PowerShell），不是在服务器执行。

将路径、`ubuntu_user`、`server_host` 和端口 `22` 换成自己的实际值；用户名是普通 Ubuntu SSH 账号。首次连接先通过可信途径核对服务器主机指纹。密码由 SSH 本人输入，不写进命令：

```sh
cd "分发文件夹的实际路径"
scp -P 22 "./DiscordArchive-source.zip" "ubuntu_user@server_host:~/"
ssh -p 22 ubuntu_user@server_host
```

`scp` 的端口参数是大写 `-P`，`ssh` 是小写 `-p`。Mac 客户端 ZIP 已内嵌在源码中，不必另外上传；**本地仍保留单独客户端 ZIP**，后面解压并连接工作台。只有使用 Windows 访问时，还需在访问电脑另开终端，从同一分发目录上传：

```sh
scp -P 22 "./login-assistant-windows.zip" "ubuntu_user@server_host:~/"
```

支持 SFTP 的 SSH 工具也可以将相同文件上传到服务器用户主目录。日常访问不需要手动建 SSH 隧道，SSH 留作首次部署和维护。

## 安装环境与后台服务

**以下命令均在已经登录 Ubuntu 的 SSH 终端执行。** 先检查上传文件存在；若 ls 提示不存在，回到上节核对上传目标，不继续解压。

```sh
ls -lh ~/DiscordArchive-source.zip
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
python3 scripts/install_login_assistants.py --mac-zip helpers/login-assistant-mac.zip
```

上例直接发布源码内嵌的 Apple Silicon Mac 包；只用 Windows 时改为 `--windows-zip ~/login-assistant-windows.zip`，两者都用时同时传两个参数。发布器会拒绝缺少首次连接组件或协议版本不匹配的旧访问包。

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
```

复制配置器刚输出的 `sudo tailscale serve --bg http://127.0.0.1:实际端口` 命令并执行，再执行 `systemctl --user restart discordarchive.service`。不要固定照抄 8765；端口占用时应用会自动换端口。

第一次使用 Serve 若出现启用 HTTPS 的网页链接，按提示由私网管理员确认，回终端等待完成；这可能是加入设备后另一轮确认，不要以为刚才登录失败。成功后执行 `tailscale serve status`，应显示实际 HTTPS 地址和配置器输出的实际转发目标；此时才继续。

配置器默认只允许该服务器注册时所属的 Tailscale 用户管理工作台；需要显式指定所有者时用 `--owner Tailscale登录名`。它会输出类似 `https://主机.私网.ts.net` 的固定地址，收藏自己的实际地址，别照抄别人的域名。

应用仍只监听 `127.0.0.1:实际端口`，由 Serve 提供私网 HTTPS；不开放公网，不启用 Funnel。工作台通过可信的 Serve 身份头识别获准管理员，不必再填工作台访问口令。其他用户、缺少身份头或公网转发均不获得管理权限。

## 连接 Discord

按 [首次连接 Discord](LOGIN_ASSISTANT.md#首次连接-discord)，在访问电脑完成一次账号确认。已连接时跳过，换电脑不重绑。完成后按 [首次采集出图](USAGE.md#第一次采集出图)验证小频道。

## 配置定时图片推送（可选）

先完成手动出图，再按 [推送教程](DELIVERY.md)配置。用 Ubuntu 出图，就在 Ubuntu 工作台设置收件渠道并测试；Mac 的配置不会同步到服务器。

## 下一步

HTTPS 工作台已能打开时，点击 **[下一步：连接 Discord](LOGIN_ASSISTANT.md#首次连接-discord)**。已连接账号时，直接进入 [首次采集出图](USAGE.md#第一次采集出图)。
