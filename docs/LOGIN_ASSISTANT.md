# 首次连接与访问客户端

## 新电脑访问已有 Ubuntu

日常只需要：登录同一个 Tailscale 账号 → 双击访问客户端 → 进入工作台。服务器已有的 Discord 连接、资料和模型继续使用，换电脑不重新授权 Discord，不安装扩展、不做网页配对。

当前原生客户端约 3 MB，使用 Go 标准库，不需要完整项目、Python、Node、Playwright 或语音模型。客户端用 Chrome / Edge 的独立临时工作台窗口直连私网，不修改系统代理。普通浏览器也可访问固定 HTTPS 地址；TUN / 企业强制代理等环境尚需分别验收。

客户端先使用包内或已保存的公开地址。无地址时，只在本机 Tailscale 状态中寻找在线、名称以 `discordarchive` 开头的候选节点，并验证 HTTPS 与本人管理员权限；只有找到唯一工作台时自动选择，不扫描其他设备。找不到唯一结果时，才提示输入一次服务器 HTTPS 地址。

地址不是写死的。Mac 用包内“设置工作台.app”，Windows 用“设置工作台.cmd”修改。只保存公开地址，不保存 Discord 凭证。默认启动不注册 Native Messaging 组件，也不要求浏览器权限。

## Mac 本地与 Ubuntu 首次连接

Mac 本地见 [Mac 首次连接](../README.md#mac连接账号)，Ubuntu 见 [Linux 首次连接](../README.md#linux连接账号)。新服务器没有账号时，下载服务器专用客户端，运行包内首次连接工具并加载一次 Browser Extension；在日常 Discord 标签页点扩展，识别账号、核对目标后确认。成功后 Ubuntu 保存连接并独立运行；换电脑访问不重复绑定。

v0.4 扩展只在主动识别后短时观察所选 Discord 标签页的指定 API 请求；只接收同站发起的 GET 请求，不读取网页存储或其他网站、聊天正文。识别到候选后立即停止观察，经本人确认才通过 Native Messaging 和本人 Tailscale HTTPS 提交。扩展不持久化连接；取消和超时清空待提交状态。服务器再次校验账号并以 0600 保存，自动任务保持暂停。

扩展只有 discord.com 站点权限；不需要关闭代理。Ubuntu HTTPS 传输由本机组件直连，正常校验证书，不修改系统代理。Mac 本地仅接受精确的 `http://127.0.0.1:端口`，连接包附带资料库身份，组件与服务端均核对；拒绝其他 HTTP 地址或不同资料库。Mac 正常安装继续用系统钥匙串。默认打开访问客户端不注册组件；仅首次连接工具才安装当前用户的组件。服务器下载包的公开地址用于首次连接，避免旧的访问地址把新服务器绑定到错误位置；日常访问仍优先使用用户设置。一次性连接目标单独保存在本机 `binding.json`，日常地址保存在 `server.json`；连接 Mac 不会改掉日常 Ubuntu 访问地址。

这不是官方 OAuth。旧版存储字段识别扩展与专用自动化登录窗口没有通过实测，保留源码但退出推荐路线。新流程已在没有连接和消息的独立 Ubuntu 与 Mac 资料库首次连接成功；验证码仍由人在日常浏览器处理。当前未上架扩展，首次加载仍需本人操作。结果与限制见 [首次连接验收](FIRST_LOGIN_ACCEPTANCE.md)。

## 开发者构建访问客户端

在有 Go 与 macOS 构建工具的开发机执行；用户机器不需要 Go：

```sh
python3 scripts/package_native_client.py --platform darwin-arm64 --destination dist/access-mac-new --with-first-login
python3 scripts/package_native_client.py --platform win32-x64 --destination dist/access-windows-new --with-first-login
```

输出目录须是新的，已有版本保留。Mac 仅本地签名，尚无 Developer ID 公证。Windows x64 可交叉编译、核对 PE 和文件哈希，但尚未完成 Windows 实机验证；Intel Mac 同样未实机验收。

面向新部署的包使用 `--with-first-login`，附带一次性扩展和首次连接入口。省略该参数只生成日常访问客户端；旧参数 `--with-experimental-binding` 作为兼容别名保留。

## 发布访问客户端

将可信 ZIP 上传到 Ubuntu，在项目目录执行：

```sh
python3 scripts/install_login_assistants.py --mac-zip /路径/login-assistant-mac.zip --windows-zip /路径/login-assistant-windows.zip
```

入口文件名保持旧名以兼容已有下载链接，但内容是访问客户端。先核对平台、首次连接组件、连接协议版本 2、精确清单和 SHA-256，再原子发布到 `.local/login-assistants/`；替换旧包时先备份。只对管理员下载开放。

服务器专用下载包在 App 外附加仅含当前 HTTPS 地址的 `server.json`，不改动 App 签名、不加入账号信息。首次收到包时完整解压；地址保存后可按自己习惯放置客户端。设置工具与主 App 应保持同目录。

## 验证

```sh
GOCACHE="$PWD/.runtime/go-cache" go test login_assistant/native_client.go login_assistant/native_client_test.go
python3 -m unittest discover -s tests -q
node tests/first_login_extension_check.mjs
node tests/first_login_network_check.mjs
```

原生测试使用虚构凭证与回环测试服务，覆盖地址限制、本人身份、绑定端点的输入验证与消息协议；不读取真实浏览器会话。访问客户端的 `--check` 是只读的私网检查，不安装组件或传递账号。实际结果与未完成项见 [私网访问验收](REMOTE_ACCESS_ACCEPTANCE.md)。

完整 Mac 源码包由构建器使用 `--mac-helper /路径/login-assistant-mac.zip` 内嵌已验证的连接包；安装器自动发布。未显式传参时只复用源码包内的 `helpers/login-assistant-mac.zip` 或当前安装已发布的包，二者都缺时停止构建，不生成缺首登工具的发布版本。源码开发者先构建对应连接包；使用者无需 Go。
