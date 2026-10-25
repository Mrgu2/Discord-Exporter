# 服务控制验证方法

本页说明验证方法；实测结论以对应版本验收记录为准。样例与日志不得包含私人账号、凭据或聊天。

暂停状态独立持久化；重启和停止等待已接受任务完成并保存状态。检查认证、来源、CSRF、未保存设置提示、页面重连与已配对会话。

```sh
python3 -m unittest discover -s tests -p 'test_service_control.py'
node tests/service_controls_check.mjs
```

`tests/verify_managed_service.py` 会操作独立测试服务，执行前按其参数说明选择测试环境。不得操作正常使用的服务来证明模拟测试通过。测试结果不包含生产实例 ID、进程号、实际任务记录或访问口令。
