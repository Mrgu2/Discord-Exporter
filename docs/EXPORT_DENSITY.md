# 导出倍率与大图显示

公开文档仅描述验证方法，不包含私人账号、设备标识、实机运行日志或聊天样本。测试结果以当前版本实际运行的回执为准；历史私人验收记录不随源码分发。

默认标准 1×，可选 HiDPI 2×。两档独立保存与缓存，2× 的像素数为相同排版 1× 的四倍。预览缩放与导出清晰度分开；原始像素模式按屏幕 DPR 对齐来源像素。

```sh
python3 -m unittest discover -s tests -p 'test_render_targets.py'
node tests/render_hidpi_check.mjs
node tests/ui_check.mjs
```

遇到模糊或黑屏时分别核对原始尺寸、完整解码、色彩标签、浏览器显示和系统查看器，不能仅根据截图判断原图损坏。超大图在不同设备上的限制需实测。
