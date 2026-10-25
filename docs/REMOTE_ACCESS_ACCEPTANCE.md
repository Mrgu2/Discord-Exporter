# 私网访问验证方法

本页说明验证方法；实测结论以对应版本验收记录为准。样例与日志不得包含私人账号、凭据或聊天。

只接受配置允许的目标、端口和身份；验证拒绝错误 Origin、所有者、端口、过期请求和非预期 HTTP 地址。访问客户端与首次连接工具分开核对。

```sh
python3 -m unittest discover -s tests -p 'test_remote_access.py'
node tests/remote_workspace_check.mjs
node tests/login_assistant_check.mjs
```

模拟测试不能证明跨网络连通性。真实测试使用获准管理的私网，不开放公网或绕过证书校验；公开回执不得保存 tailnet 域名、真实所有者、客户端配置或私网机器清单。
