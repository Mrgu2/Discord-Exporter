# 首次连接验证方法

本页说明验证方法；实测结论以对应版本验收记录为准。样例与日志不得包含私人账号、凭据或聊天。

Mac 本地使用登录窗口；Ubuntu 首次连接使用访问电脑上的扩展工具。使用独立空资料库，检查连接前无凭证、取消和超时不提交、目标资料库匹配、本人确认后只提交一次，以及服务重启后的连接保留。日常访问地址与一次性连接目标应互不覆盖。

```sh
python3 -m unittest discover -s tests -p 'test_mac_connection.py'
python3 -m unittest discover -s tests -p 'test_connection_binding.py'
node tests/first_login_extension_check.mjs
node tests/first_login_network_check.mjs
node tests/unified_login_check.mjs
```

模拟网络事件不证明所有浏览器或代理环境兼容。密码和验证码由本人处理。此连接迁移不是 Discord 官方 OAuth，平台权限与风控仍需单独确认。不要将真实请求头、账号或服务器标识加入样例。
