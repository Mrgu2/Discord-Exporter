# 验证方法与证据边界

公开文档仅描述验证方法，不包含私人账号、设备标识、实机运行日志或聊天样本。测试结果以当前版本实际运行的回执为准；历史私人验收记录不随源码分发。

基础回归：

```sh
python3 -m unittest discover -s tests
python3 scripts/verify_workflow.py
node tests/frontend_design_check.mjs
node tests/ui_check.mjs
```

跨模块脚本使用虚构消息和模拟 Discord 响应，在独立目录验证保存、增量、回复关系、稿件及 PNG 下载，不代表真实账号权限已通过验证。

真实部署仍需由使用者单独核对授权频道、两轮增量保存、回复和媒体覆盖、断线恢复。实体设备、长期运行、断电和平台风控不能由单元测试代替。私有回执保存在忽略的 `artifacts/`、`data/` 或 `output/` 中。

[安装验证](INSTALLATION_ACCEPTANCE.md) · [手机验证](PHONE_ACCEPTANCE.md) · [发布检查](GITHUB_PRIVACY.md)
