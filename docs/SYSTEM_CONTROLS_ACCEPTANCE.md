# 系统控制验证方法

本页说明验证方法；实测结论以对应版本验收记录为准。样例与日志不得包含私人账号、凭据或聊天。

自动启动偏好与当前进程状态分别核对；关闭自动启动不应退出正在运行的服务。Linux linger 与本应用服务开关分开处理。

```sh
python3 -m unittest discover -s tests -p 'test_system_controls.py'
node tests/system_controls_check.mjs
```

电源接口测试使用模拟对象，覆盖权限、来源、确认文字、等待任务、失败恢复。真实重启或关机需由拥有者明确授权，在隔离环境核对恢复；公开记录不保存 boot ID、精确时间线、主机身份或个人操作经历。
