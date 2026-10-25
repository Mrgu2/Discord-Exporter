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

GitHub 发布版见 [Releases](https://github.com/Mrgu2/Discord-Exporter/releases/tag/v2026.10.25.1)。当前维护者构建目录为 `dist/releases/v2026.10.25.1/`；接收方直接下载 Release 中的三个 ZIP，按平台选用。获取方式与客户端架构见 [获取安装包](DOWNLOADS.md)。

当前修正版及验收边界见 [当前修正版验收](FINAL_PACKAGE_ACCEPTANCE.md)，不同使用方式拿哪些 ZIP 见 [README 文件选择](../README.md#需要拿哪些文件)。

本项目生成文件统一留在工作目录内：构建中间文件放 `dist/builds/`，干净的交付文件放 `dist/releases/`，验收截图、JSON、样例和报告放 `artifacts/`，可复用说明放 `docs/`。不额外向下载目录导出源码包、客户端包或测试目录。只有本人需要手动加载/更新浏览器扩展时，才导出对应 `Browser Extension` 到下载目录的固定文件夹；不移动浏览器仍在加载的扩展目录。

交付目录提供：

- `DiscordArchive-source.zip`：Mac 本地完整安装或 Ubuntu 服务端安装；内含 Mac 连接包。
- `login-assistant-mac.zip`：Apple Silicon Mac 访问 Ubuntu 时单独使用。
- `login-assistant-windows.zip`：Windows x64 访问 Ubuntu 时单独使用，尚待实机验收。
- `CHECKSUMS.sha256`：上面三个原始 ZIP 的哈希。
- `FILES.txt`：简明的平台与文件对应关系。
- `START-HERE.html`：离线可打开的选包页面，含三个 ZIP 的直接链接。
- `ACCEPTANCE.md`：该版本的验收范围与限制。

下载接收方核对方式：Mac 在交付目录执行 `shasum -a 256 -c CHECKSUMS.sha256`；Ubuntu 执行 `sha256sum -c CHECKSUMS.sha256`。工作台下载包附加当前地址信息，字节与交付原始包不同，不用这个清单校验工作台专用包，也不要把专用包拿回服务器发布。

文档同步版保持应用、安装与首次连接代码和已验收修正版一致；公开验收记录进入源码白名单，私有 `artifacts/` 机器记录不进入交付包。旧构建和测试文件保留，不覆盖、不删除。

## 分享与隐私

**不要直接压缩自己的项目文件夹。** Mac 本地模式分享重新构建的 `DiscordArchive-source.zip`；Ubuntu 部署另提供访问电脑对应的连接包 ZIP；两种访问电脑都用时才提供两个。普通访问端只拿对应客户端包。

在 Mac 的项目目录执行：

```sh
PATH="$PWD/.runtime/bin:$PATH" python3 scripts/package_app.py
```

新版本生成在 `dist/` 下的新版本目录，不会覆盖旧包。独立助手的构建与校验见 [助手说明](LOGIN_ASSISTANT.md)。分发包不含 `data/`、`output/`、登录浏览器资料、凭证、聊天、模型或本机依赖。接收完整项目的新部署需要安装依赖、连接自己的账号并添加频道；只访问已有 Ubuntu 的人不重装项目、不重复授权。迁移自己的历史数据请另看[迁移说明](REFERENCE.md#换到另一台-mac)。

只使用本人已有的频道访问权限。普通成员账号自动读取存在 Discord 账号处罚风险；此工具不负责自动发布，也不向外部模型发送群聊。
