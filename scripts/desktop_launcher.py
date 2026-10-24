#!/usr/bin/env python3
"""Open the local workspace, starting an idle service without interrupting jobs."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import plistlib
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


LABEL = "local.discord.answer-archive"
URL = "http://127.0.0.1:8765"


def project_root(app_path: Path | None = None, root: Path | None = None) -> Path:
    candidates = [root] if root else []
    if app_path:
        app_path = app_path.resolve()
        # An extracted migration package keeps the app beside its source.
        candidates.append(app_path.parent)
        config = app_path / "Contents" / "Resources" / "project.json"
        try:
            candidates.append(Path(json.loads(config.read_text())["root"]))
        except (OSError, ValueError, KeyError, TypeError):
            pass
    candidates.append(Path(__file__).resolve().parent.parent)
    for candidate in candidates:
        if candidate and all((candidate / name).is_file() for name in
                             ("app.py", "discord_archive/__init__.py", "web/index.html")):
            return candidate.resolve()
    raise RuntimeError("找不到完整工具目录。请将 App 放在解压后的源码目录中，再次打开。")


def health() -> str:
    """Return healthy/offline/occupied; never follow environment HTTP proxies."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(URL + "/api/health", timeout=1) as response:
            payload = json.loads(response.read(4096))
        return "healthy" if payload == {"ok": True, "service": "answer-archive"} else "occupied"
    except (urllib.error.HTTPError, ValueError):
        return "occupied"
    except (urllib.error.URLError, TimeoutError, OSError):
        # A bound but stalled process must not be mistaken for a free port.
        try:
            with socket.create_connection(("127.0.0.1", 8765), timeout=0.3):
                return "occupied"
        except OSError:
            return "offline"


def archive_locked(root: Path) -> bool:
    lock = root / "data" / "server.lock"
    if not lock.exists():
        return False
    with lock.open("r") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        finally:
            # LOCK_UN is harmless if this descriptor never obtained the lock.
            fcntl.flock(handle, fcntl.LOCK_UN)
    return False


def launchctl(*arguments: str):
    return subprocess.run(["/bin/launchctl", *arguments], capture_output=True,
                          text=True, timeout=8)


def matching_agent(root: Path, plist_path: Path) -> bool:
    try:
        config = plistlib.loads(plist_path.read_bytes())
        arguments = config.get("ProgramArguments", [])
        return (config.get("Label") == LABEL and len(arguments) >= 2
                and Path(arguments[1]).resolve() == root / "app.py")
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
        return False


def agent_autostart(plist_path: Path) -> bool:
    try:
        return plistlib.loads(plist_path.read_bytes()).get('RunAtLoad',True) is not False
    except (OSError,ValueError,TypeError):
        return True


def wait_healthy(timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if health() == "healthy":
            return
        time.sleep(0.5)
    raise RuntimeError("服务未能在 30 秒内就绪。现有任务未被重启；请检查 data/service.log 或 data/launcher.log。")


def ensure_service(root: Path) -> str:
    initial = health()
    if initial == "healthy":
        return "reused"
    if initial == "occupied":
        # This includes a slow/hung existing instance. Do not spawn or kill it.
        wait_healthy()
        return "waited"
    if archive_locked(root):
        wait_healthy()
        return "waited"
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{LABEL}"
    plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    if sys.platform == "darwin" and matching_agent(root, plist) and agent_autostart(plist):
        state = launchctl("print", target)
        loaded = state.returncode == 0
        if loaded:
            if re.search(r"^\s*pid = \d+\s*$", state.stdout or "", re.MULTILINE):
                wait_healthy()
                return "waited"
            # No -k: a running service and its in-flight jobs remain untouched.
            result = launchctl("kickstart", target)
        else:
            # A deliberate stop disables login relaunch until the App is opened.
            enabled = launchctl("enable", target)
            if enabled.returncode != 0:
                raise RuntimeError("无法恢复后台服务；未改写或重装服务，请查看当前用户的后台服务权限。")
            result = launchctl("bootstrap", domain, str(plist))
        if result.returncode != 0:
            raise RuntimeError("现有后台服务未能启动；未改写或重装服务。请查看后台服务状态。")
        wait_healthy()
        return "agent"
    data = root / "data"
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    env = os.environ.copy()
    node = shutil.which("node")
    directories = [str(root / ".runtime" / "bin")] + ([str(Path(node).parent)] if node else []) + [
        str(Path(sys.executable).parent), "/opt/homebrew/bin", "/usr/local/bin",
        "/usr/bin", "/bin", "/usr/sbin", "/sbin",
    ]
    env["PATH"] = ":".join(dict.fromkeys(directories))
    env["PYTHONUNBUFFERED"] = "1"
    log_path = data / "launcher.log"
    descriptor = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "ab") as log:
        subprocess.Popen([sys.executable, str(root / "app.py"), "--root", str(root)],
                         cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log,
                         stderr=log, start_new_session=True, close_fds=True)
    wait_healthy()
    return "started"


def main() -> None:
    parser = argparse.ArgumentParser(description="打开 Discord 本地归档工作台")
    parser.add_argument("--app-path", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--no-open", action="store_true", help="只确认服务就绪，不打开浏览器")
    parser.add_argument("--check", action="store_true", help="只读检查目录和健康状态")
    args = parser.parse_args()
    root = project_root(args.app_path, args.root)
    if args.check:
        print(json.dumps({"root": str(root), "health": health(), "url": URL}, ensure_ascii=False))
        return
    outcome = ensure_service(root)
    if not args.no_open:
        subprocess.run(["/usr/bin/open", URL], check=True, timeout=10)
    print(json.dumps({"result": outcome, "url": URL}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
