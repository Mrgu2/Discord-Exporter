# HiDPI 验证方法

本页说明验证方法；实测结论以对应版本验收记录为准。样例与日志不得包含私人账号、凭据或聊天。

HiDPI 从 HTML 以原生 2× 设备像素绘制；与标准 1× 比较时，排版一致，宽高各翻倍。核对来源、文字、图片、完整话题和跨片段接缝。

```sh
node tests/render_hidpi_check.mjs
node tests/render_collage_check.mjs
node tests/png_check.mjs
```

验证超限拒绝、解码、sRGB 标签及失败不覆盖旧输出。原附件的低分辨率不能由正文倍率恢复；网页检查不能代替实体设备检查。
