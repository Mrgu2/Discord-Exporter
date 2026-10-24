#!/usr/bin/env python3
"""Check installation without reading settings, archives, or credentials."""
import shutil
import subprocess
import sys
from pathlib import Path


def check(root):
    errors = []
    if sys.version_info < (3, 10):
        errors.append('需要 Python 3.10 或更新版本')
    node = shutil.which('node')
    if not node:
        errors.append('缺少 Node.js，请重新运行 Install.command')
    else:
        try:
            version = subprocess.check_output([node, '-p', 'process.versions.node'], text=True, timeout=10)
            if int(version.split('.')[0]) < 20:
                errors.append('需要 Node.js 20 或更新版本')
            else:
                result = subprocess.run([node, str(root / 'scripts/check_browser.mjs')],
                                        capture_output=True, text=True, timeout=60)
                if result.returncode:
                    errors.append(result.stderr.strip()[-1200:] or '浏览器检查失败，请重新运行 Install.command')
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            errors.append('无法完成浏览器检查：' + type(exc).__name__)
    return errors


if __name__ == '__main__':
    issues = check(Path(__file__).resolve().parent.parent)
    for issue in issues:
        print(issue, file=sys.stderr)
    if not issues:
        print('Python、Node.js、项目 Playwright、浏览器启动及绘图检查通过。语音为可选功能。')
    raise SystemExit(bool(issues))
