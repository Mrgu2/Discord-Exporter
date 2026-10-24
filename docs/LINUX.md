# Linux 部署与使用

Linux 与 Mac 共用工作台、采集、原文归档、稿件、长图、定时出稿和语音转写流程。已实测 Ubuntu 22.04 x86_64；其他发行版与 ARM64 尚未实机验收。Linux 语音使用 faster-whisper，Mac 保留 MLX；相同模型级别也不保证识别结果逐字相同。

## 已经部署：以后怎么打开

不必重装或手工建隧道。使用代理时先打开随包提供的访问客户端，不以普通浏览器能先打开 HTTPS 为下载客户端的前提。客户端 Tailscale 在线后，也可打开部署时输出的固定 `https://主机.私网.ts.net` 地址；使用代理时，双击访问客户端，专用窗口直接访问私网；默认不处理 Discord 登录。客户端不运行采集或模型，关闭客户端不影响服务器任务。

默认步骤见 [README Linux 部署](LINUX_SETUP.md)。Ubuntu 只装一份完整项目；新电脑只需同一 Tailscale 身份和访问客户端，不重新绑定服务器已保存的账号。首次新服务器按 [Ubuntu 首次部署](LINUX_SETUP.md) 做一次日常浏览器连接；已有连接时跳过。

Tailscale Serve 提供私网 HTTPS，代理到服务器 `127.0.0.1:8765`。服务端只信任回环来源、配置的准确域名、HTTPS 转发标记，以及指定所有者的 Tailscale 身份头；其他身份不获得管理权限。[Serve 官方说明](https://tailscale.com/docs/features/tailscale-serve)

不做公网端口映射，不启用 Tailscale Funnel。服务器局域网 / Tailscale IP 用于 SSH 维护，不是让用户直接打开 `IP:8765` 的入口。服务器地址变化可用 `ip -4 address`、`tailscale ip -4` 核对；固定域名以 `tailscale status` 与部署输出为准。

旧版 `http://127.0.0.1:18765` 是客户端建立 SSH 隧道后的备用入口，6080 是手工启用 VNC 的备用桌面。它们不属于新默认流程；具体见第 2 节。原有数据和连接不因启用 HTTPS 迁移或删除。

## 首次部署前

以下安装命令都在 **Ubuntu 服务器的 SSH 终端**执行，助手和访问操作在 **你自己的 Mac / Windows**进行。需要普通用户、可用的 sudo 权限、Python 3.10+、联网下载依赖的能力，以及约数 GiB 的可用磁盘空间；实际聊天和附件会继续占用磁盘。先用 `df -h /` 检查系统盘。

先从可信来源取得完整源码（或解压 `DiscordArchive-source.zip`），通过 SSH/SFTP 上传到服务器的固定目录。目录中应能看到 `app.py`、`scripts/`、`web/`、`package-lock.json`；不要只上传 Mac App，也不要上传自己的 SSH 配置或已有聊天数据。从 ZIP 首次上传与解压的完整命令见 [README Linux 部署](LINUX_SETUP.md)。下面示例统一使用 `~/apps/DiscordArchive`；已有安装继续用原目录，不另建实例。

## 1. 默认部署：Tailscale HTTPS 与独立助手

把源码放到固定、可写的用户目录，例如 `~/apps/DiscordArchive`。不要复制其他电脑的 `.runtime`、`node_modules` 或 `.venv`。安装过程需要联网。

```sh
cd ~/apps/DiscordArchive
bash scripts/install_linux.sh --with-system-deps
```

需要 Python 3.10+ 和 sudo 权限。安装入口优先使用已有 Node.js 20+；缺少时从 Node 官方站下载 Node 22，并核对 SHA-256，仅安装到项目的 `.runtime`。npm 和 Playwright 使用项目锁定版本。`--with-system-deps` 另安装 Chromium 系统依赖、中文字体、FFmpeg 和 Python venv，不替换系统 Python。

看到“Linux 环境检查通过”才算完成。重新检查：

```sh
bash scripts/install_linux.sh --check
```

基础部署顺序为：基础环境 → 用户后台服务 / linger → small 语音（按需）→ Tailscale 授权 → `configure_tailscale.py` 配置所有者 → Serve 私网 HTTPS → 发布访问客户端。首次账号连接使用包内首次连接工具和日常浏览器扩展；空资料库首次连接已实测。逐条命令与成功标志见 [README](LINUX_SETUP.md)。访问已有服务器的 Mac / Windows 不需要执行本项目安装器。

助手构建、发布、代理处理和 Windows 的验证边界见 [独立助手说明](LOGIN_ASSISTANT.md)。新安装默认不自启动，由工作台设置选择；升级现有安装保留原服务偏好，切勿另建第二份资料库。

## 2. 备用：SSH 绑定与登录桌面

本节仅保留旧版维护 / 回退路线，会要求 Mac 也安装完整项目；访问已有服务器优先使用第 1 节客户端；新账号优先按 [Ubuntu 首次部署](LINUX_SETUP.md) 的首次连接流程处理。旧路线同样不需要显示器、DISPLAY、Xvfb 或 VNC。先在 Mac 完整项目中登录，再经核对身份的 SSH 绑定。 绑定后，Ubuntu 自己连接 Discord、保存附件、转写和出图；关闭 Mac 或 SSH 隧道不影响服务器已提交的任务和已开启的自动计划。

### 在 Ubuntu 安装后台服务

```sh
cd ~/apps/DiscordArchive
sudo loginctl enable-linger "$USER"
python3 scripts/install_linux_service.py --install --no-autostart
```

`discordarchive.service` 使用当前普通用户运行，默认只监听 `127.0.0.1:8765`，不依赖登录桌面。linger 让用户服务在退出 SSH 后继续运行；`--no-autostart` 只启动这次服务。以后在“高级设置 → 自动启动”选择是否开机运行。已有安装升级时省略 `--no-autostart` 可保留原自启动偏好。已有独立归档进程时，先从工作台停止它，再安装，避免争用资料库。

### 在自己的 Mac 建立隧道

替换用户名和服务器私有地址；跨网络先连 Tailscale 等私网。首次 SSH 须通过可信途径核对服务器主机指纹，不能关闭主机身份检查。SSH 端口不是 22 时补 `-p 实际端口`。

```sh
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18765:127.0.0.1:8765 用户名@服务器地址
```

保持终端打开，在浏览器进入 [Ubuntu 工作台](http://127.0.0.1:18765)。它与 Mac 自己的 `http://127.0.0.1:8765` 是两个独立安装，不要配错频道。点击“本机登录后绑定”可查看当前服务器的绑定命令。

### 在 Mac 绑定一次

1. 打开 **Mac 自己的工作台**，点击“连接 Discord”，本人在专用浏览器正常登录。已连接且可用时跳过此步。不要在 Ubuntu 的验证码页反复尝试。
2. 在 **Mac 的项目目录**新建私有 `.env.ssh.local`，填写 SSH 资料，或使用已有文件：

   ```dotenv
   SSH_HOST='服务器的私有地址'
   SSH_PORT='22'
   SSH_USER='部署用户名'
   SSH_KEY_PATH='/Users/你的名字/.ssh/私钥文件'
   ```

   已解锁的 SSH agent 可省略 `SSH_KEY_PATH`。密码认证则省略密钥路径，填写 `SSH_PASSWORD='SSH密码'`，并先在 Mac 安装 `sshpass`（例如 `brew install sshpass`）；SSH 密钥有口令时，先用 `ssh-add /私钥路径` 解锁到 agent。此文件只填写 SSH 信息，**不填写 Discord 密码或凭证**，不要 `source` 它。密钥路径与密码同时存在时优先使用密钥。
3. 在同一个 Mac 终端、Mac 项目目录执行，远端目录替换为服务器实际路径；引号中的 `~` 在 Ubuntu 展开：

   ```sh
   chmod 600 .env.ssh.local
   PATH="$PWD/.runtime/bin:/opt/homebrew/bin:/usr/local/bin:$PATH" python3 scripts/bind_linux.py --ssh-file .env.ssh.local --remote-root '~/apps/DiscordArchive'
   ```

   默认读取 `~/.ssh/known_hosts`；使用独立主机记录时加 `--known-hosts /绝对路径/known_hosts`。未核对主机、远端项目不匹配、仍有采集或备用登录任务、已有另一账号时，绑定会拒绝。
4. 看到“**绑定成功：两端账号一致**”，刷新 Ubuntu 工作台，确认进入“添加频道与答疑人”。绑定会暂停自动任务，先只配置一个小频道，完成 [首次保存、出稿和下载](USAGE.md#第一次采集出图)，再按需恢复自动任务。频道与发言人设置需要在 Ubuntu 单独配置，不会从 Mac 自动复制。

绑定传递的是本项目已有连接，经 SSH 加密 stdin 发送；不会复制日常浏览器资料，不在命令参数或输出中显示凭证。Ubuntu 会独立向 Discord 验证同一账号，保存到项目的 `data/credentials.json`（权限 `0600`）。Ubuntu 的 SSH 账号和备份应按可访问 Discord 账号连接的敏感资料保护；不要将 `.env.ssh.local`、`data/` 或浏览器资料发给别人。源码分发不包含它们。

这是复用已有登录连接，并非新的 OAuth 授权，也不能保证连接永不过期。退出账号、撤销连接或风控使连接失效时，在 Mac 正常重新登录后再运行绑定；绑定不会绕过验证码。服务器网络仍需能够访问 Discord。

### VNC 仅作备用

只有需要在服务器浏览器本人操作时才安装备用桌面。服务器机房网络上的验证码仍可能失败，启用 VNC 不保证登录成功。默认绑定和采集无需此步骤。

先在工作台停止服务并等待任务结束，再在 Ubuntu 执行：

```sh
sudo apt-get install -y xvfb x11vnc novnc websockify xauth x11-utils
python3 scripts/install_linux_service.py --install --desktop
```

这会另启动 `discordarchive-desktop.service`，并让归档服务在备用模式下使用它。只在需要时给上面的 SSH 隧道再加 `-L 127.0.0.1:6080:127.0.0.1:6080`。打开 [备用登录桌面](http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale)，在工作台“高级设置”点击“备用登录（VNC）”，由本人登录。不要公开 6080/5900 端口。

恢复默认无桌面方式：先从工作台停止归档服务，再执行：

```sh
systemctl --user stop discordarchive-desktop.service
python3 scripts/install_linux_service.py --install
```

以上保留账号连接与自启动偏好，不删除资料。Linux 的“自动另存目录”填写**服务器上的绝对路径**；下载图片保存在当前浏览器的下载目录。

## 3. 语音转写：默认 small / CPU

先完成基础安装，再运行：

```sh
python3 scripts/install_speech.py
```

不带参数即使用 **small 多语言模型、CPU / INT8**，不自动探测或切换 GPU。等价命令为 `python3 scripts/install_speech.py --model small --device cpu`。独立环境位于 `.venv/whisper-linux`，完整模型位于 `.runtime/models/faster-whisper-small`。安装器实际加载模型通过后，才启用转写；之后推理只读取本地模型与音频，不联网下载或上传语音。下一次保存或生成稿件会读取配置，无需重启。旧稿件不自动改写。

性能较弱时可把 `small` 换成 `tiny` 或 `base`；更大模型可选 `medium`、`large-v3`。CPU 默认 INT8，最多使用 4 个线程；可在 `data/config.json` 的 `speech.cpu_threads` 设置线程数。切换模型会创建独立缓存，已有模型和转写不删除。

### 备选：NVIDIA GPU

当前项目已提供 faster-whisper 的 CUDA 配置入口，尚未做 GPU 实机验收。有受支持的 **NVIDIA CUDA GPU** 及匹配运行库时，可配置：

```sh
python3 scripts/install_speech.py --model small --device cuda --compute-type float16
```

CUDA 安装会先尝试实际加载，失败时不覆盖原有语音配置。当前服务器的 CPU 路径已实测，CUDA 路径未实测；Intel/AMD 核显不走此 CUDA 路径。相关运行库要求见 [faster-whisper 官方说明](https://github.com/SYSTRAN/faster-whisper#gpu)。

适配前确认 GPU 型号、显存、驱动以及 CTranslate2 对 CUDA/cuDNN 的当前版本要求。`nvidia-smi` 能看到显卡只证明驱动可见；还需确认运行进程实际使用 GPU，并用同一音频比较准确度、耗时、显存与 CPU 内存。安装失败时继续使用原 CPU 配置，不自动改装驱动或覆盖原模型。

### 备选：AMD GPU（后续适配方案）

**当前项目没有接入 AMD GPU 后端。** 不能把 `--device cuda` 改成 `amd`、`rocm` 或 `vulkan` 就使用现有安装器。AMD 可考虑另接 whisper.cpp 的 Vulkan 或 ROCm 后端；上游提供这些方向，但具体 GPU、驱动和构建支持仍需核对。[whisper.cpp 官方说明](https://github.com/ggml-org/whisper.cpp)

建议先验证 Vulkan 路线是否适合目标显卡；已有兼容 ROCm 环境时也可评估 ROCm。需要单独准备 whisper.cpp 对应的模型格式，不能直接复用本项目 CTranslate2 的 `model.bin`。不要仅因电脑有 AMD 显卡，就认定其后端可用或一定比 CPU 快。

### 给后续 AI / 开发者的适配任务

目标是在不改变工作台和稿件流程的前提下增加可选 GPU 后端，保留 small / CPU 的可用配置。先读取以下代码，再按真实硬件选择路径：

| 位置 | 适配职责 |
| --- | --- |
| `scripts/install_speech.py` | 隔离环境和模型安装；实际加载通过后才更新设置，失败保留原 CPU 配置 |
| `discord_archive/speech.py` 的 `configuration()` | 注册引擎与设备、验证本地模型；将后端、设备、精度、模型及运行器版本纳入缓存指纹 |
| `scripts/transcribe_local.py` | 读取批次请求、离线解码和推理、发布统一转写回执；增加 AMD 时在这里接入独立适配器 |
| `scripts/verify_speech.py`、`tests/test_speech.py`、`tests/test_linux.py` | 验证实际音频、缓存隔离、失败恢复及稿件/PNG 输出 |

AMD 需要新增引擎标识（例如未来的 `whisper-cpp`）、对应权重验证和子进程适配；此名称仅为设计建议，当前配置校验不会接受它。NVIDIA 可先沿现有 faster-whisper / CUDA 路径完成实机验收，无需更换上层接口。

接入时保持以下合同：

- 批次请求仍带本地音频路径、音频 SHA-256、模型指纹、语言和输出目录；不向外部服务传输音频，也不在推理时临时下载模型。
- 转写回执保留 `status`、`text`、`segments`（起止时间与原文）、`language`、`audio_sha256`、`model_fingerprint`、`model`、`engine`、`duration_seconds`、`elapsed_seconds`。缺少的置信度字段可以为空，不编造数值。
- 保留现有超过 30 分钟不交付截断文字的边界、子进程超时、原音频留存、缓存复用和原子写入；后端失败必须可见且可重试，不破坏已保存内容。
- 使用同一段中英文音频与 CPU 基线对比；证明 GPU 实际参与运算，转写进入文字稿和标准/HiDPI 图片；测试切换后端后不会错误命中旧缓存。保留 CPU 回退方法，失败时不静默改变用户所选设备。
- 验收报告写清硬件、驱动、后端与模型版本、精度、耗时、内存/显存和识别错误。没有目标 GPU 实测，就标记“适配方案”或“配置入口”，不能写“已兼容”。

可直接给另一位 AI 的任务描述：

> 请先读取 docs/LINUX.md、docs/LINUX_ACCEPTANCE.md 和语音相关代码，检查本机 GPU 型号与驱动。在保留 small/CPU 可用配置和现有 UI、稿件、图片流程的前提下，验证 NVIDIA CUDA 路径或增加 AMD whisper.cpp 适配。不要假定 AMD 能使用 CUDA，不自动覆盖模型或升级系统驱动；按文中的请求/回执合同完成真实音频、缓存、失败恢复和出图验收，明确记录未验证项。

验证自己的测试音频及出图链路：

```sh
PATH="$PWD/.runtime/node/bin:$PATH" python3 scripts/verify_speech.py /绝对路径/测试音频.wav
```

该命令仅处理指定的本地音频，在新的 `artifacts/speech-verify-*` 目录保留转写、虚构消息、稿件、图片与 `acceptance.json`，不会读取 Discord 凭证。实际聊天与交易术语仍需人工核对。

## 4. 常见访问问题

| 现象 | 下一步 |
| --- | --- |
| 私有 IP 能看到，但浏览器打不开服务器 IP:8765 | 默认只监听回环地址；按第 2 节建立 SSH 隧道，打开本机 18765 |
| 在外面 SSH 连不上 | 先确认两端 Tailscale 在线、地址正确、访问策略允许 SSH；不要改为开放公网端口 |
| 本机 18765 显示连接被拒绝 | 检查隧道终端是否还开着；重新建立隧道。仍失败时在服务器检查服务状态 |
| SSH 提示绑定端口失败 | 检查是否已有同用途隧道；命令应停止而不是继续让用户打开错误页面 |
| 工作台能打开，但 Discord 登录窗口看不到 | 已有连接无需重新登录；首次授权见账号配置边界，备用模式检查 6080 隧道与桌面服务 |
| 服务器重启后打不开 | 先确认服务器已上线，再检查用户 linger 和归档服务；备用模式另查桌面服务；重新建立本机隧道 |

## 5. 日常管理与验收

工作台中的暂停、恢复、重启、停止沿用同一流程。服务使用 `Restart=on-failure`：从工作台主动停止后不会立即自动拉起，重启操作会等待任务结束并恢复页面。

```sh
python3 scripts/install_linux_service.py --status
systemctl --user start discordarchive.service
systemctl --user restart discordarchive.service
journalctl --user -u discordarchive.service -n 50 --no-pager
```

需要停用自启动并停止本安装（保留服务文件、凭证、归档和模型）：

```sh
python3 scripts/install_linux_service.py --uninstall
```

运行状态应显示 `ActiveState=active`、非零 `MainPID`；自动启动开关对应 `UnitFileState=enabled/disabled`，disabled 时当前服务仍可以运行。仅 enabled 不能证明可用，还需打开页面、完成真实保存和图片下载。模拟全链路检查不使用真实账号：

```sh
PATH="$PWD/.runtime/node/bin:$PATH" python3 -m unittest discover -s tests -q
PATH="$PWD/.runtime/node/bin:$PATH" python3 scripts/verify_workflow.py
```

换机前先停止服务，再复制完整 `data/`、`output/`；不要复制正在写入的单个 SQLite 文件，也不要让两台机器写同一数据库。语音环境与模型在新机器重新安装。

## 6. 服务器电源

“高级设置 → 服务器电源”提供**重启服务器 / 关闭服务器**，只在服务器本机、获准所有者的 Tailscale HTTPS 或 SSH 隧道页面可用。它们影响整台机器和其他程序，不是“重启服务”的别名；需要输入对应操作文字确认，先等待本应用任务结束。

本应用通过 systemd-logind 查询和请求操作。只有系统明确返回无需进一步认证的授权时，按钮才可用；`challenge`、被系统阻止或读取失败都不会被当成已授权。执行时再次检查权限，不强制跳过系统阻止条件，也不保存 sudo 密码。[systemd-logind 官方接口](https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.login1.html)

### 管理员一次性授权（按需）

这一步**不会自动执行**。若只需要应用运行，无需配置。若确实希望从工作台控制整台服务器，管理员可按组织策略授予运行应用的账号相应 logind 权限。以下规则只允许两个基本电源动作，但该账号的其他进程也将拥有这些权限；不要授权不可信或共享账号。

先确认实际服务账号，在服务器由管理员创建独立规则文件（已有同名文件先检查和备份）：

```sh
sudoedit /etc/polkit-1/rules.d/49-discordarchive-power.rules
```

规则示例，必须把 `实际服务用户名` 替换为部署账号：

```javascript
polkit.addRule(function(action, subject) {
    if (subject.user === "实际服务用户名" &&
        (action.id === "org.freedesktop.login1.reboot" ||
         action.id === "org.freedesktop.login1.power-off")) {
        return polkit.Result.YES;
    }
});
```

规则只涉及基本关机与重启；多用户会话或系统阻止条件仍可能导致不可用，不追加绕过这些限制的授权。撤销时由管理员禁用这份独立规则并重新检查权限，不改其他应用的规则。

配置后等待状态缓存刷新（最多约 30 秒）再刷新工作台，确认权限状态。可先只读检查，**以下两条不会重启或关机**：

```sh
busctl call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager CanReboot
busctl call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager CanPowerOff
```

真实整机操作需由使用者挑选维护时间在页面确认；部署测试不得为了验证按钮而自动重启、关闭服务器。重启后等待服务器和私网连接恢复，再重建 SSH 隧道；若关闭了自动启动，需要登录服务器手动启动本应用。关机后需通过物理主机、虚拟机管理工具或另外配置的远程开机方案启动，工作台本身不能给已关机的机器开机。

[本次 Linux 验收结果](LINUX_ACCEPTANCE.md) · [详细功能说明](REFERENCE.md)
