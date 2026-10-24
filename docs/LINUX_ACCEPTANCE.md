# Linux 验证方法

公开文档仅描述验证方法，不包含私人账号、设备标识、实机运行日志或聊天样本。测试结果以当前版本实际运行的回执为准；历史私人验收记录不随源码分发。

安装与操作见 [Linux 部署](LINUX.md)。在隔离资料库中验证无桌面采集、用户服务、自启动、浏览器渲染和本地语音；CPU 与 GPU 后端分别核对。

```sh
python3 -m unittest discover -s tests -p 'test_linux.py'
python3 -m unittest discover -s tests -p 'test_system_controls.py'
python3 scripts/verify_workflow.py
```

模拟响应不证明账号绑定和频道权限。整机重启、自启动与网络恢复仅在拥有者授权的测试环境中执行，不能把一次正常重启推广为断电和长期运行可靠性。服务器地址、启动标识、资源快照和凭证不写入公开回执。
