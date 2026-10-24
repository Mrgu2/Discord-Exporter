# GitHub 发布与隐私检查

公开文档仅描述验证方法，不包含私人账号、设备标识、实机运行日志或聊天样本。测试结果以当前版本实际运行的回执为准；历史私人验收记录不随源码分发。

源码只收录程序、合成测试与通用文档。聊天、凭证、运行配置、导出、私人验收日志、历史备份和生成包均留在忽略的目录。

```sh
python3 scripts/check_repository_privacy.py
gitleaks git --log-opts=--all --redact
gitleaks dir --redact
```

提交前核对 `git status --short` 与 `git diff --cached`，使用 GitHub 提供的 noreply 邮箱，不以 `git add -f` 绕过忽略规则。密钥检测只精确排除用于扩展 ID 的公开 RSA 公钥。

隐私检查必须覆盖历史版本、提交元数据、文件名与内容。`.gitignore` 不能清除已经提交的文件；补一个删除提交也不能清除旧版本。清理时保留私有备份，在独立仓库验证改写结果，再核对远端引用与全新克隆。旧仓库和备份不能通过 `--mirror` 或附加分支重新发布。

自动检测不能识别所有自然语言隐私。不得把真实频道名称、设备型号与个人使用记录、私人稿件 UUID、系统启动标识或内容哈希写入公开验收。公开前还应检查 Releases、Actions 附件、Pages、Wiki 和讨论记录。
