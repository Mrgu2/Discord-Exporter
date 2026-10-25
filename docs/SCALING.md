# 归档规模与性能验证

本页说明验证方法；实测结论以对应版本验收记录为准。样例与日志不得包含私人账号、凭据或聊天。

历史版本索引、上下文索引和稿件列表摘要用于减少重复读取。稿件列表分页加载，不预加载原图；搜索仍覆盖已保存稿件。

```sh
python3 scripts/benchmark_scaling.py
python3 scripts/benchmark_draft_listing.py
python3 scripts/benchmark_history.py
node tests/draft_library_check.mjs
```

基准采用合成数据，记录输入规模、预热、重复次数和中位数，核对优化前后的历史语义与分页结果。冷缓存、并发负载、首次索引、语音和绘图应分别测量。公开回执不能包含真实资料库计数、私人文件哈希或稿件标识。
