# 分发包验证方法

本页说明验证方法；实测结论以对应版本验收记录为准。样例与日志不得包含私人账号、凭据或聊天。

Mac 本地登录不需要扩展；Ubuntu 首次绑定使用对应访问电脑的连接工具。源码包包含程序与必要依赖声明；客户端包按访问电脑的平台选择，首次连接工具与日常访问入口分别核对。操作入口见 [README](../README.md)。

验证精确文件清单、SHA-256、ZIP CRC、组件协议和平台架构。检查安装后服务健康，以及独立合成资料库从保存到 PNG 的路径。构建机器验证不等于其他系统实机通过。

```sh
python3 -m unittest discover -s tests -p 'test_packaging.py'
python3 -m unittest discover -s tests -p 'test_helper_packages.py'
python3 -m unittest discover -s tests -p 'test_installation.py'
```

只分发经过核对的原始包。工作台专用下载可能附带服务器地址或资料库身份，不直接上传到公开仓库。未完成的平台实测、Developer ID 公证和商店发布不得标为已通过。
