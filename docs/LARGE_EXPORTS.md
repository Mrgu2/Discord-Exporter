# 大范围导出验证

本页说明验证方法；实测结论以对应版本验收记录为准。样例与日志不得包含私人账号、凭据或聊天。

大范围稿件按完整话题分页，尽量避免将可在单页容纳的问答拆开。核对所有分页的来源、正文、图片、顺序与边界；超限应明确拒绝，不能静默遗漏内容。

```sh
node tests/render_large_flow_check.mjs
node tests/render_collage_check.mjs
python3 -m unittest discover -s tests -p 'test_render_targets.py'
```

使用合成话题覆盖单页、多页、超长话题、空输入和图片边界。实际资源占用取决于消息量、媒体和设备，不承诺任意规模都能即时完成。
