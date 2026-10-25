# 首次连接与访问客户端

流程：**打开 HTTPS 工作台 → 确认 Discord 账号 → [首次出图](USAGE.md#第一次采集出图)**。

Mac 本地使用 [登录窗口](MAC.md#登录-discord)。本页用于 Docker 或原生 Ubuntu 的首次连接；服务器已连接时，直接按 [日常访问](ACCESS.md)操作。

## 首次连接 Discord

在访问电脑操作，只做一次。需要 Chrome 或 Edge、Tailscale，以及能正常登录 Discord 的日常浏览器。

1. 完整解压对应 [访问客户端](DOWNLOADS.md)。用 **Ubuntu Workspace.app / Ubuntu Workspace.exe** 打开工作台；没有预填地址时，输入部署时得到的 HTTPS 地址。系统代理有冲突时使用此专用窗口。
2. 可从工作台下载带服务器地址的首次连接包。Mac 打开包内 **首次连接 Discord.app**，Windows 打开 **Connect Discord.cmd**，安装当前用户的连接组件。
3. 在 Chrome 打开 `chrome://extensions/`（Edge 用 `edge://extensions/`），开启 **开发者模式 → 加载已解压的扩展**，选择包内 **Browser Extension**。扩展未上架，此步需手动完成；更新同目录扩展时点刷新。
4. 在日常浏览器本人登录 [Discord](https://discord.com/channels/@me)，停在 Discord 标签页，点扩展图标，再点 **识别当前 Discord 账号**。标签页刷新并识别后，核对账号和服务器，点 **确认连接此账号**。
5. 看到 **连接成功**，且目标工作台显示账号后，按 [首次采集出图](USAGE.md#第一次采集出图)验证一个小频道。自动任务保持暂停，按需恢复。

完成后可关闭客户端或移除扩展，部署机器独立运行。换电脑访问不重复绑定；连接过期时再执行本节。

密码和验证码只在 Discord 页面输入。浏览器本身无法登录时，先处理登录问题；工具不绕过人机验证。这是本人确认的连接迁移，**不是 Discord 官方 OAuth**。取消、超时、验证失败或服务器已有另一账号时，不直接覆盖原连接。

<details>
<summary>连接权限与保存位置</summary>

扩展 v0.4 仅在主动识别后，短时观察所选 Discord 标签页的指定同站 GET 请求；不读取网页存储、聊天正文或其他网站。识别后停止观察，待本人确认后经 Native Messaging 和 Tailscale HTTPS 提交。

扩展不持久保存连接，取消或超时即清空。服务器再次验证账号，凭据文件权限为 `0600`；Mac 本地登录使用系统钥匙串。扩展不关闭代理、不跳过证书检查。

客户端只保存公开地址。日常地址在 `server.json`，一次性连接目标在 `binding.json`，互不覆盖。只有首次连接工具注册当前用户的本机组件，日常访问入口不注册。

</details>

## 新电脑访问已有 Ubuntu

按 [访问教程](ACCESS.md)登录 Tailscale 并打开工作台，无需项目、模型或扩展。客户端约 3 MB，使用已安装的 Chrome / Edge；TUN 和企业强制代理需单独诊断。

<details>
<summary>开发者：构建、发布与测试客户端</summary>

## 开发者构建访问客户端

开发机需 Go；Mac 打包另需 macOS 构建工具。用户机器无需 Go：

```sh
python3 scripts/package_native_client.py --platform darwin-arm64 --destination dist/access-mac-new --with-first-login
python3 scripts/package_native_client.py --platform win32-x64 --destination dist/access-windows-new --with-first-login
```

输出目录必须是新的。`--with-first-login` 包含首次连接工具；省略时仅生成访问客户端，旧参数 `--with-experimental-binding` 仍兼容。Mac 包仅支持 Apple Silicon，尚未公证；Windows x64 尚待实机验收。

## 发布访问客户端

Docker 镜像已内置两种客户端。以下命令用于**原生 Ubuntu**，在项目目录发布可信 ZIP：

```sh
python3 scripts/install_login_assistants.py --mac-zip /路径/login-assistant-mac.zip --windows-zip /路径/login-assistant-windows.zip
```

发布器核对平台、首次连接组件、协议版本 2、文件清单与 SHA-256，再原子写入 `.local/login-assistants/`；替换前保留备份。下载仅对管理员开放，专用包附加 HTTPS 地址，不改 App 签名或加入账号。

完整源码包的助手内嵌规则见 [打包说明](PACKAGING.md)。Mac 本地安装不强制依赖该助手包。

## 验证

```sh
GOCACHE="$PWD/.runtime/go-cache" go test login_assistant/native_client.go login_assistant/native_client_test.go
python3 -m unittest discover -s tests -q
node tests/first_login_extension_check.mjs
node tests/first_login_network_check.mjs
```

测试使用虚构凭据和回环服务，覆盖地址、身份与连接协议；不读取真实浏览器会话。客户端 `--check` 只检查私网连接，不注册组件或提交账号。实机与模拟测试须分别记录，见 [首次连接验证](FIRST_LOGIN_ACCEPTANCE.md)。

</details>

## 下一步

看到“连接成功”，且目标工作台显示正确账号后，点击 **[下一步：首次采集出图](USAGE.md#第一次采集出图)**。不必继续阅读开发者说明。
