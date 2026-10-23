# 归档规模与性能验证

公开文档仅描述验证方法，不包含私人账号、设备标识、实机运行日志或聊天样本。测试结果以当前版本实际运行的回执为准；历史私人验收记录不随源码分发。

历史版本索引、上下文索引和稿件列表摘要用于减少重复读取。稿件列表分页加载，不预加载原图；搜索仍覆盖已保存稿件。

```sh
python3 scripts/benchmark_scaling.py
python3 scripts/benchmark_draft_listing.py
python3 scripts/benchmark_history.py
node tests/draft_library_check.mjs
```

基准采用合成数据，记录输入规模、预热、重复次数和中位数，核对优化前后的历史语义与分页结果。冷缓存、并发负载、首次索引、语音和绘图应分别测量。公开回执不能包含真实资料库计数、私人文件哈希或稿件标识。
