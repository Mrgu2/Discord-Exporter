# 双击打开与源码迁移包

运行 `python3 scripts/package_app.py`，会在新的 `dist/<版本时间>/` 中生成：

- **Discord Archive.app**：双击打开本机工作台。首次启动只会检查健康、按需启动服务并打开浏览器。
- **DiscordArchive-source.zip**：源码和原生快捷入口，适合移到另一台 Mac。
- **BUILD.json**：包大小、文件数和 SHA-256 校验结果。

已有服务正常时，快捷入口直接打开页面。服务尚未就绪时等待健康检查；匹配的 LaunchAgent 未运行时尝试启动，不执行重启或停止。没有匹配的后台服务时，用本机 Python 启动独立后台进程；退出 App 和浏览器不关闭采集服务。这个备用启动不自动安装开机服务，需要登录后自启动时再按 README 的 LaunchAgent 步骤安装。

已有进程占用端口、资料库仍被服务锁定或启动超过 30 秒时，会显示错误并保留原进程。检查 `data/service.log` 或备用启动的 `data/launcher.log`。快捷入口不会改写后台服务配置、终止正在采集或出图的任务，也不修改睡眠设置。

## 在另一台 Mac 使用

1. 解压 `DiscordArchive-source.zip`，在得到的 **DiscordArchive** 文件夹里打开 **Discord Archive.app**。不要单独移动迁移包中的 App；它靠相邻源码定位工具。
2. 这是一份源码包和原生启动入口，**不是包含全部依赖的独立安装包**。需要 Python 3.10+；导图另需 Node.js、Playwright 和本机 Chrome 或 Chromium。依赖安装命令见 README，打包和启动都不会自动联网下载依赖。
3. 首次在新 Mac 连接 Discord。语音需要另行准备 FFmpeg、MLX Whisper 运行环境与完整本地模型；原 Mac 的虚拟环境与模型不在包中。
4. 需要迁移历史时，按 README 先等任务结束并停止源机服务，再私下复制完整 `data/` 和 `output/`；不要在线单独复制 SQLite 主文件，不要让两台机器同时写同一个资料库。源码包没有带出这些内容，macOS 钥匙串也不会迁移。

App 使用本地临时签名，没有 Developer ID 公证；另一台 Mac 可能要求在“隐私与安全性”确认打开。只对自己构建且核对过 SHA-256 的包操作，不关闭 Gatekeeper 或系统保护。迁移包内的 App 与本机快捷 App 分别签名，迁移版不携带原 Mac 的项目路径。

## 打包检查

源码逐文件白名单涵盖应用代码、网页、已知脚本、文档与回归检查。`data/`、`output/`、`.git/`、`.venv/`、`artifacts/`、`node_modules/`、模型和凭证均不打包。未知文件不会因位于项目目录而被自动带入；白名单源码也不接受符号链接。

每个包包含 `PACKAGE-MANIFEST.json`，逐项记录路径、大小和 SHA-256。构建后重读 ZIP 校验精确文件清单、每个文件的哈希与 CRC；本地 App 同时经过 `codesign --verify --strict` 检查。运行 `python3 -m unittest discover -s tests -p 'test_packaging.py' -v` 可验证启动不打断已有服务、目录定位和源码白名单边界。

重新打包会生成新版本目录；同一目录或同名 ZIP 已存在时拒绝覆盖，不删除已有 App、归档或数据。更改了源码后重新运行打包命令，旧源码包保持原样。
