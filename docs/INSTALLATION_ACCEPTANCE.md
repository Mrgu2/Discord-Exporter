# 安装验证方法

公开文档仅描述验证方法，不包含私人账号、设备标识、实机运行日志或聊天样本。测试结果以当前版本实际运行的回执为准；历史私人验收记录不随源码分发。

在独立目录和空 HOME 中解包，验证安装器的依赖下载、浏览器启动、服务健康、虚构数据到 PNG 的完整流程。不得复用真实凭证或访问正在使用的资料库。

```sh
python3 -m unittest discover -s tests -p 'test_installation.py'
python3 -m unittest discover -s tests -p 'test_packaging.py'
```

完整安装验证可按 `scripts/verify_distribution.py` 的参数说明执行。依赖已安装的隔离测试不等于全新实体系统冷安装；未测试的平台和签名限制必须单独说明。

[部署入口](../README.md) · [包核对](FINAL_PACKAGE_ACCEPTANCE.md)
