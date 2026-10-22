# HiDPI 验证方法

公开文档仅描述验证方法，不包含私人账号、设备标识、实机运行日志或聊天样本。测试结果以当前版本实际运行的回执为准；历史私人验收记录不随源码分发。

HiDPI 从 HTML 以原生 2× 设备像素绘制；与标准 1× 比较时，排版一致，宽高各翻倍。核对来源、文字、图片、完整话题和跨片段接缝。

```sh
node tests/render_hidpi_check.mjs
node tests/render_collage_check.mjs
node tests/png_check.mjs
```

验证超限拒绝、解码、sRGB 标签及失败不覆盖旧输出。原附件的低分辨率不能由正文倍率恢复；网页检查不能代替实体设备检查。
