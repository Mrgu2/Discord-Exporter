#!/usr/bin/env python3
"""Install this user's LaunchAgent, preserving existing files and all archives."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


LABEL = "local.discord.answer-archive"
LAUNCHCTL = "/bin/launchctl"


def build_plist(root: Path, executable: str | None = None) -> dict:
    root = Path(root).resolve()
    python = str(Path(executable or sys.executable).absolute())
    node = shutil.which("node")
    # A LaunchAgent does not inherit the interactive shell's PATH. Include only
    # executable directories needed for rendering, never the shell's secrets.
    directories = ([str(Path(node).parent)] if node else []) + [
        str(Path(python).parent), "/opt/homebrew/bin", "/usr/local/bin",
        "/usr/bin", "/bin", "/usr/sbin", "/sbin",
    ]
    runtime_path = ":".join(dict.fromkeys(directories))
    return {
        "Label": LABEL,
        "ProgramArguments": [
            # Keep Homebrew's stable opt/bin symlink rather than pinning a
            # Cellar patch-version directory that an upgrade may remove.
            python,
            str(root / "app.py"),
            "--host", "0.0.0.0", "--root", str(root),
        ],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "ProcessType": "Background",
        "Umask": 0o077,
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1", "PATH": runtime_path},
        "StandardOutPath": str(root / "data" / "service.log"),
        "StandardErrorPath": str(root / "data" / "service.log"),
    }


def launchctl(*arguments):
    return subprocess.run(
        [LAUNCHCTL, *arguments], capture_output=True, text=True, timeout=20
    )


def service_status(plist_path: Path, domain: str) -> dict:
    target = f"{domain}/{LABEL}"
    result = launchctl("print", target)
    status = {"label": LABEL, "plist": str(plist_path), "plist_exists": plist_path.exists(), "loaded": result.returncode == 0}
    # launchctl print can include environment variables. Return only operational
    # fields; do not echo its complete output into logs or the browser.
    if result.returncode == 0:
        for field, pattern in (
            ("state", r"^\s*state = (.+)$"),
            ("pid", r"^\s*pid = (\d+)$"),
            ("last_exit_code", r"^\s*last exit code = (\d+)$"),
        ):
            found = re.search(pattern, result.stdout, re.MULTILINE)
            if found:
                status[field] = int(found.group(1)) if field != "state" else found.group(1).strip()
    disabled = launchctl("print-disabled", domain)
    match = re.search(r'"' + re.escape(LABEL) + r'"\s*=>\s*(true|false)', disabled.stdout)
    status["disabled"] = match.group(1) == "true" if match else None
    return status


def require_success(result, operation: str) -> None:
    if result.returncode != 0:
        raise RuntimeError(f"{operation}失败（launchctl {result.returncode}）；未删除原文件，请检查当前用户登录状态与系统权限")


def install(root: Path, plist_path: Path, domain: str) -> dict:
    if not (root / "app.py").is_file():
        raise ValueError("工具目录缺少 app.py，请使用 --root 指定完整项目目录")
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    data.chmod(0o700)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if plist_path.exists():
        backup_directory = data / "service-backups"
        backup_directory.mkdir(parents=True, exist_ok=True)
        backup_directory.chmod(0o700)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = backup_directory / f"{LABEL}-{stamp}.plist"
        shutil.copy2(plist_path, backup)
        backup.chmod(0o600)
    raw = plistlib.dumps(build_plist(root), sort_keys=False)
    pending = plist_path.with_name(plist_path.name + f".pending-{os.getpid()}")
    descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(pending, plist_path)
    plist_path.chmod(0o600)
    target = f"{domain}/{LABEL}"
    loaded = launchctl("print", target).returncode == 0
    if loaded:
        require_success(launchctl("bootout", target), "停止旧后台服务")
    require_success(launchctl("enable", target), "启用后台服务")
    require_success(launchctl("bootstrap", domain, str(plist_path)), "注册后台服务")
    result = service_status(plist_path, domain)
    result["backup"] = str(backup) if backup else None
    result["message"] = "已注册当前用户的登录后自启动；仍需核对服务健康与真实采集"
    return result


def deactivate(plist_path: Path, domain: str) -> dict:
    target = f"{domain}/{LABEL}"
    require_success(launchctl("disable", target), "停用后台服务")
    if launchctl("print", target).returncode == 0:
        require_success(launchctl("bootout", target), "停止后台服务")
    result = service_status(plist_path, domain)
    result["message"] = "已停用后台服务；plist、备份、日志、凭证和归档数据均保留。再次 --install 可恢复"
    return result


def main():
    parser = argparse.ArgumentParser(description="安装或停用当前用户的 Discord 归档后台服务")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--print", action="store_true", help="只输出 LaunchAgent plist，不修改系统")
    mode.add_argument("--install", action="store_true", help="备份原 plist 并安装当前用户的后台服务")
    mode.add_argument("--status", action="store_true", help="读取后台运行状态，不显示完整环境变量")
    mode.add_argument("--uninstall", action="store_true", help="停用并停止服务，保留所有文件")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.print:
        sys.stdout.buffer.write(plistlib.dumps(build_plist(root), sort_keys=False))
        return
    if sys.platform != "darwin":
        raise ValueError("后台服务安装仅支持 macOS；其他平台可直接运行 app.py")
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    domain = f"gui/{os.getuid()}"
    if args.install:
        result = install(root, plist_path, domain)
    elif args.uninstall:
        result = deactivate(plist_path, domain)
    else:
        result = service_status(plist_path, domain)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"后台服务操作未完成：{exc}", file=sys.stderr)
        raise SystemExit(1)
