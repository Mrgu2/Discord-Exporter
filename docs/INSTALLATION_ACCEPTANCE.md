# 安装验证方法

本页说明验证方法；实测结论以对应版本验收记录为准。样例与日志不得包含私人账号、凭据或聊天。

Mac 本地安装后直接打开登录窗口，不要求扩展或连接包。在独立目录和空 HOME 中解包，验证安装器的依赖下载、浏览器启动、服务健康、虚构数据到 PNG 的完整流程。模拟流程不使用真实凭证或运行中的资料库；真实账号验收须获得用户授权并另行记录。

```sh
python3 -m unittest discover -s tests -p 'test_installation.py'
python3 -m unittest discover -s tests -p 'test_packaging.py'
```

完整安装验证可按 `scripts/verify_distribution.py` 的参数说明执行。依赖已安装的隔离测试不等于全新实体系统冷安装；未测试的平台和签名限制必须单独说明。

[部署入口](../README.md) · [包核对](FINAL_PACKAGE_ACCEPTANCE.md)
