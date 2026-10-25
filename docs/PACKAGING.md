# 双击打开与源码迁移包

运行 `python3 scripts/package_app.py --mac-helper /路径/login-assistant-mac.zip`，会在新的 `dist/<版本时间>/` 中生成：

- **Discord Archive.app**：双击打开本机工作台。首次启动只会检查健康、按需启动服务并打开浏览器。
- **DiscordArchive-source.zip**：源码和原生快捷入口，适合移到另一台 Mac。
- **BUILD.json**：包大小、文件数和 SHA-256 校验结果。

已有服务正常时，快捷入口直接打开页面。服务尚未就绪时等待健康检查；匹配的 LaunchAgent 未运行时尝试启动，不执行重启或停止。没有匹配的后台服务时，用本机 Python 启动独立后台进程；退出 App 和浏览器不关闭采集服务。这个备用启动不自动安装开机服务，需要登录后自启动时再按 README 的 LaunchAgent 步骤安装。

其他程序占用请求端口时会自动尝试空闲端口，并使用实际地址；同一资料库已被服务锁定时等待现有服务就绪，不另开实例。超过等待时限会显示错误并保留原进程。检查 `data/service.log` 或备用启动的 `data/launcher.log`。快捷入口不会改写后台服务配置、终止正在采集或出图的任务，也不修改睡眠设置。

## 在另一台 Mac 使用

1. 解压 `DiscordArchive-source.zip`，在得到的 **DiscordArchive** 文件夹里先双击 **Install.command**，检查通过后自动打开工作台。以后使用 **Start.command** 或 **Discord Archive.app**。不要单独移动迁移包中的 App；它靠相邻源码定位工具。
2. 这是一份源码包和原生启动入口，**不是包含全部依赖的独立安装包**。需要 Python 3.10+；登录与导图均需 Node.js 20+、锁定版本的 Playwright 和 Chromium。Install.command 会联网安装缺失依赖并验证浏览器；App 和 Start.command 不自动下载依赖。无 Homebrew 且缺少 Python/Node 时，安装入口提供安装链接后停止。
3. 首次在新 Mac 连接 Discord。语音默认关闭；Apple Silicon Mac 可双击 Install-Speech.command 单独安装 FFmpeg、MLX Whisper 与完整本地模型；原 Mac 的虚拟环境与模型不在包中。
4. 需要迁移历史时，按 README 先等任务结束并停止源机服务，再私下复制完整 `data/` 和 `output/`；不要在线单独复制 SQLite 主文件，不要让两台机器同时写同一个资料库。源码包没有带出这些内容，macOS 钥匙串也不会迁移。

App 使用本地临时签名，没有 Developer ID 公证；另一台 Mac 可能要求在“隐私与安全性”确认打开。只对自己构建且核对过 SHA-256 的包操作，不关闭 Gatekeeper 或系统保护。迁移包内的 App 与本机快捷 App 分别签名，迁移版不携带原 Mac 的项目路径。

## 打包检查

源码逐文件白名单涵盖应用代码、网页、已知脚本、文档与回归检查。`data/`、`output/`、`.git/`、`.venv/`、`.runtime/`、`artifacts/`、`node_modules/`、模型和凭证均不打包。未知文件不会因位于项目目录而被自动带入；白名单源码也不接受符号链接。

每个包包含 `PACKAGE-MANIFEST.json`，逐项记录路径、大小和 SHA-256。构建后重读 ZIP 校验精确文件清单、每个文件的哈希与 CRC；本地 App 同时经过 `codesign --verify --strict` 检查。运行 `python3 -m unittest discover -s tests -p 'test_packaging.py' -v` 可验证启动不打断已有服务、目录定位和源码白名单边界。

重新打包会生成新版本目录；同一目录或同名 ZIP 已存在时拒绝覆盖，不删除已有 App、归档或数据。更改了源码后重新运行打包命令，旧源码包保持原样。

首次分发前先运行 `python3 scripts/package_native_client.py --platform darwin-arm64 --destination dist/新目录 --with-first-login`，再将输出 ZIP 交给上述 `--mac-helper`。构建器核对首次连接协议和组件，并将 ZIP 内嵌到源码包的 `helpers/`，Mac 安装器自动发布；已安装的完整包通常可自动找到该 ZIP。不要使用只有访问能力的旧包。

## 修正版交付目录与文件位置

当前分发见 [Release](https://github.com/Mrgu2/Discord-Exporter/releases/tag/v0.1.2)，文件选择见 [下载说明](DOWNLOADS.md)。本版完整分发目录为 `dist/releases/v0.1.2/`，含源码包、客户端、Docker 配置、离线镜像和完整离线 ZIP。旧版本保留。

构建中间文件放 `dist/builds/`，交付物放 `dist/releases/`，测试记录放 `artifacts/`。只有需要本人加载浏览器扩展时，才把对应扩展导出到下载目录；不移动浏览器正在加载的目录。

工作台专用下载会附加服务器地址，字节与 Release 原包不同，不能用原包哈希核对，也不能拿回服务器作为通用包发布。旧构建和原数据保留。

## 分享与隐私

**不要直接压缩自己的项目文件夹。** Mac 分享源码分发 ZIP；Ubuntu Docker 分享部署 ZIP 与离线镜像；仅访问服务器的人按平台拿客户端。

在 Mac 的项目目录执行：

```sh
PATH="$PWD/.runtime/bin:$PATH" python3 scripts/package_app.py
```

新版本生成在 `dist/` 下的新版本目录，不会覆盖旧包。独立助手的构建与校验见 [助手说明](LOGIN_ASSISTANT.md)。源码与客户端包不含 `data/`、`output/`、浏览器资料、凭证、聊天、模型或本机依赖；Docker 镜像含公共模型和依赖，不含私人资料。接收完整项目的新部署需要安装依赖、连接自己的账号并添加频道；只访问已有 Ubuntu 的人不重装项目、不重复授权。迁移自己的历史数据请另看[迁移说明](REFERENCE.md#换到另一台-mac)。

只使用本人已有的频道访问权限。普通成员账号自动读取存在 Discord 账号处罚风险；此工具不负责自动发布，也不向外部模型发送群聊。

## Linux Docker 分发

Docker 版单独交付 `DiscordArchive-Docker-linux-amd64.zip` 与 `discordarchive-linux-amd64.tar.gz`。前者是脚本和教程，后者是带 Chromium、FFmpeg、中文字体与 small 模型的离线镜像；源码 ZIP 仍不包含模型。镜像只从白名单公共源文件、已校验客户端与公共模型构建，不包含任何命名卷、账号或聊天。

维护者先用 `scripts/package_docker.py` 生成干净构建上下文，再在 Linux amd64 上执行 `docker build -f docker/Dockerfile -t discordarchive-linux:版本号 构建目录`，实际验收后 `docker save` 导出并压缩。不要使用 `docker commit` 将登录后的容器变成镜像，不要打包 data/output 卷。保持 Compose 默认镜像版本与分发镜像一致。

安装与功能边界见 [Docker 教程](DOCKER.md)，当前验证结果见 [Docker 验收记录](DOCKER_ACCEPTANCE.md)。
