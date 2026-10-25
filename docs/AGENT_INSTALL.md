# 交给 Agent 安装与验收

适用于已获授权的 Mac / Ubuntu。确认目标机器、目录和已有服务；只为目标或权限缺口提问，不重复请求已有授权。

## 先识别环境与已有安装

1. 读取项目 AGENTS.md、README、目标平台教程和用户约束。区分“Mac 本地运行”与“只访问 Ubuntu”；后者不安装完整项目或模型。
2. 用 `uname -s`、`uname -m`、`df -h .` 检查平台与空间。原生版另查 Python / Node；Docker 查 Engine / Compose，无需在宿主机安装项目依赖。
3. 检查原生 data/output、Docker 卷与已有服务。更新按 [保留资料](DELIVERY.md#已有安装如何更新)处理；隔离测试另设目录或卷，不覆盖原安装。Mac 用 launcher `--check`，原生 Ubuntu 用服务脚本 `--status`，Docker 用 `sudo docker compose ps` 查看状态。
4. 按 [下载说明](DOWNLOADS.md)选择文件并核对对应哈希、源码清单和客户端架构。Mac 客户端为 arm64；Windows x64 待实机验收。

## Mac 本地安装

在完整项目或克隆的源码仓库中执行：

```sh
bash Install.command --no-open --no-system-install
export PATH="$PWD/.runtime/bin:$PATH"
python3 scripts/doctor.py
python3 scripts/desktop_launcher.py --root "$PWD" --no-open
python3 scripts/desktop_launcher.py --root "$PWD" --check
```

`--no-system-install` 禁止安装系统组件。缺 Python/Node 时，在用户已有授权范围内按 [Mac 教程](MAC.md)准备。`--no-open` 不打开浏览器；需要界面时打开 `--check` 返回的实际 URL。

**Mac 本地安装不依赖 helpers/login-assistant-mac.zip**，无需为克隆的源码另下 Ubuntu 助手。

语音在需要时单独执行 `bash Install-Speech.command`；Intel Mac 的当前语音入口不支持，不能标记通过。不要删除旧模型或已有虚拟环境。

## Ubuntu Docker 首次部署（推荐）

按 [Docker 教程](DOCKER.md)检查 Linux amd64、Docker / Compose 与空间。下载一个完整离线 ZIP，解压到新目录，执行 `sudo bash Install-Docker.sh`，再执行 `sudo bash Configure-Tailscale.sh`。保留已有 Serve 路由；模型已在镜像内。

隔离验收要设置不同 `COMPOSE_PROJECT_NAME` 和 `ARCHIVE_PORT`，不得挂载原 data/output 卷。复用凭证必须得到用户授权，私密数据仅传入新卷。检查实际出图、语音进入稿件、容器重启后资料仍在，以及停止/自动启动设置生效。不得挂载 Docker socket 或电源接口；Docker 版只能控制容器内应用，不控制 Ubuntu 关机/重启。

## Ubuntu 原生首次部署（替代方案）

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

保留退出码和脱敏日志，定位依赖、端口、服务归属、网络或授权问题，修正后复验。重试安装不清空资料、凭据或模型；不以关闭系统保护、开放公网或替换资料库解决失败。
