# 交给 Agent 安装与验收

适用于用户已授权你操作的 Mac 或 Ubuntu。先确认目标机器和目录；这是安装说明，不是授予额外权限。已有授权无需重复询问，缺少会改变目标或权限范围的信息才询问。

## 先识别环境与已有安装

1. 读取项目 AGENTS.md、README、目标平台教程和用户约束。区分“Mac 本地运行”与“只访问 Ubuntu”；后者不安装完整项目或模型。
2. 使用 `uname -s`、`uname -m`、`python3 --version`、`node --version` 和 `df -h .` 检查平台、架构、运行环境和空间。缺少命令不代表资料库为空。
3. 检查目标目录是否已有 data/、output/ 和运行服务。存在时按 [保留资料更新](DELIVERY.md#已有安装如何更新)处理，不删除或清空，不用新空目录冒充原安装成功。只读诊断可用 `python3 scripts/desktop_launcher.py --root "$PWD" --check`（Mac）或 `python3 scripts/install_linux_service.py --status`（Ubuntu）。
4. 分发文件见 [获取安装包](DOWNLOADS.md)。验证 CHECKSUMS.sha256，核对源码 ZIP 的 PACKAGE-MANIFEST.json，以及访问客户端平台。Mac 客户端仅 Apple Silicon arm64；Windows x64 尚待实机验收。

## Mac 本地安装

在完整项目或克隆的源码仓库中执行：

```sh
bash Install.command --no-open --no-system-install
export PATH="$PWD/.runtime/bin:$PATH"
python3 scripts/doctor.py
python3 scripts/desktop_launcher.py --root "$PWD" --no-open
python3 scripts/desktop_launcher.py --root "$PWD" --check
```

第一条限制安装器只准备项目依赖，不通过 Homebrew 安装系统组件。缺 Python/Node 时先确认用户已有的系统安装授权；若已授权，按 [Mac 教程](MAC.md)准备依赖后继续，不能以重复执行掩盖同一错误。`--no-open` 保持终端路径可验收；用户需要界面时去掉该参数或打开 --check 返回的实际 URL。

**Mac 本地登录不依赖 helpers/login-assistant-mac.zip。** 有效的可选 Ubuntu 客户端包会被发布；缺少或发布失败不会阻止本地安装。只有访问 Ubuntu 时才需要对应客户端。不要为源码克隆安装额外强制下载助手包。

语音在需要时单独执行 `bash Install-Speech.command`；Intel Mac 的当前语音入口不支持，不能标记通过。不要删除旧模型或已有虚拟环境。

## Ubuntu 首次部署

严格区分访问电脑与服务器终端。按 [Ubuntu 教程](LINUX_SETUP.md)先 SCP 上传并用 ls 检查，再在项目目录执行：

```sh
bash scripts/install_linux.sh
export PATH="$PWD/.runtime/node/bin:$PATH"
python3 scripts/install_linux_service.py --install --no-autostart
```

该基本安装不自动装系统包；若缺 Ubuntu 系统依赖，在用户已有授权范围内使用教程的 `--with-system-deps`，否则报告具体缺项再请求必要授权。安装同名 systemd 服务前检查是否属于另一个目录；遇到现有服务不得覆盖、停止或另建实例抢占原资料库。隔离验收可用 `--print` 核对服务配置，明确它不等于已安装后台服务。

Mac 访问客户端可直接从源码内嵌包发布：

```sh
python3 scripts/install_login_assistants.py --mac-zip helpers/login-assistant-mac.zip
```

Windows 访问时按教程提供 Windows ZIP。接着配置用户自己的 Tailscale 与 HTTPS，沿用本机监听，不开放公网端口、不启用 Funnel。运行 `python3 scripts/configure_tailscale.py` 后按输出的实际端口配置 Serve，不硬编码 8765。

语音执行 `python3 scripts/install_speech.py`，默认 small 多语言、CPU/INT8；客户电脑不装模型。以“模型已实际加载”和实际语音稿件为准，不把下载完成当成转写验收。

## 本人接管与账号边界

- Discord 密码、扫码、验证码及人机验证，Tailscale 账号批准，macOS 系统授权由本人完成；不要让人把密码或 Token 发到聊天中。
- 工作台已连接时不重复登录、不重绑。用户明确允许复用旧连接进行隔离验收时，只从获准凭据存储在进程内读取，既不打印，也不放进命令行、环境回显、截图、分发包或测试配置。不要导出整个浏览器资料。
- 仅有 Ubuntu SSH 权限不能替本人在访问电脑加载扩展。缺少这一步时报告“环境已安装，首次账号连接待本人操作”，不能声称完整可用。

## 第一张图片的验收

在工作台按“首次出图”提示继续：确认保存范围 → 生成首份稿件 → 生成第一张图片 → 查看并下载。先使用最近一轮、本地证据稿和标准 1×，无需先理解纽约交易日。

首次采集会读取所选频道全部可见历史。只选消息少的频道；产品没有“只采十条”的开关。测试脚本若在隔离目录限量取样，必须明确这是脚本限制，不是完整历史采集验收。不要为验收勾选全部频道或启动真实推送。

成功标准：

1. 环境检查和健康检查通过，返回正确目标资料库的实际 URL；端口变化已反映到访问入口。
2. Discord 连接有效；无法完成本人授权时明确标记未完成，不循环弹登录窗口。
3. 保存记录成功，稿件包含预期目标发言；PNG 下载后能打开、文字可读。失败时报告阶段、原因和下一步，不只报“安装命令退出 0”。
4. 已有原文、图片、配置和凭据保留；测试未擅自开启自启动、恢复暂停计划、发送推送、重启机器或修改全局代理。
5. 汇报测试的平台、架构、包版本和未覆盖范围。模拟资料库、旧 Token 复用和全新首次授权必须区分。

## 失败后继续

保留退出码与脱敏日志，先定位缺失依赖、端口、服务归属、网络或授权阶段，再修正并复验。网络下载失败可重跑原安装入口，不能删除 data/、output/、凭据或旧导出。浏览器启动或模型加载失败时继续保留已保存内容；禁止用关闭系统保护、公开端口或复制原库到测试环境来掩盖失败。
