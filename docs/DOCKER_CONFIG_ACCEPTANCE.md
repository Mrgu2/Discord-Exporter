# Docker 配置包验收

本次为 Linux 配置增强及 Windows Docker Desktop 预览，使用新的 v2026.10.25.3 镜像。旧 v2026.10.25.2 Release、原工作台和原数据保留；本版发布至 [v2026.10.25.3 Release](https://github.com/Mrgu2/Discord-Exporter/releases/tag/v2026.10.25.3)。

## 本次结果

- Python 回归 358 项通过，含停止竞态最小复现与回归。
- 新镜像连续三次“重启应用后立即停容器”约 2.5–3.4 秒完成。
- CPU small INT8 的隔离样本已验证转写、缓存复用、入稿及 HiDPI 出图。单个测试环境的结果不代表所有设备或语音的准确率、速度。

## 验证范围

- PowerShell 解析、UTF-8 BOM、变量优先级、端口冲突、配置备份、拒绝远端 context、Windows containers、ARM 和错误资料库的检查已在官方 PowerShell Linux 容器验证。
- Ubuntu 在独立 Compose 项目、空卷和独立端口上检查模型加载、目录含空格挂载、UID 1000 写出相同图片副本、资源上限、`.env` HTTPS 端口和停止后备份。
- 最小复现确认旧管理进程存在“子应用 exec 重启与停止信号重叠时等待不退出”的竞态。新管理进程持续检查同一子进程是否退出，保留任务排空时间，不强制杀死任务。
- 以上不等于 Windows Docker Desktop 实机验收；Windows host networking、NTFS 权限、浏览器扩展和 Tailscale Serve 仍需目标电脑验证。

最终次数、镜像与包校验记录保留在本地 `artifacts/docker-config-20261025/`。本轮没有重新登录、读取生产资料库或发送真实推送；语音仅只读复用了此前保留的验收样本。CPU small 沿用原模型，GPU 不在本次验收范围。

## 分平台配置示例复核

基础配置已分为 Windows / Linux 两份，可直接复制；图片另存片段也按平台分开。两平台默认与另存共四种 Compose 配置解析通过，Windows 分隔符在 Linux 上模拟。Linux 教程命令已在新项目和空卷执行，small 加载及重复执行不覆盖配置通过；测试仅将项目名改为隔离名称。Windows 复制步骤在 PowerShell 容器中用假安装器验证，覆盖空格目录、已有配置保护与错误目录，仍不代表 Windows Desktop 实测。高级选项默认折叠。

## 同机 Docker 首次连接修正

修复分支支持同机 Windows 从本机工作台下载带实际端口与资料库标识的连接包，无需 Tailscale HTTPS。连接器提交前校验目标，服务端也独立拒绝错误资料库标识；跨电脑仍使用 Tailscale。

[GitHub Actions 验证](https://github.com/Mrgu2/Discord-Exporter/actions/runs/40203012273)：Windows Server 2022 和 Ubuntu 的原生连接器测试、真实 Linux 容器中的回环 HTTP 绑定均通过。容器测试使用虚构账号，覆盖保存连接、暂停自动任务和错误资料库拒绝提交。本机 362 项 Python 回归、Mac 助手构建签名及 390/1360 连接界面检查通过。

这不等于 Windows Docker Desktop/WSL 与真实浏览器账号的完整实机验收。修复尚未进入上方旧版 Release，不能用旧包验证新流程。
