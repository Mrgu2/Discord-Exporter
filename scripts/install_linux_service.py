#!/usr/bin/env python3
"""Manage an unprivileged systemd service without replacing other installations."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

NAME = 'discordarchive.service'
DESKTOP = 'discordarchive-desktop.service'


def quoted(value):
    value = str(value)
    if any(character in value for character in '\n\r\0"\\%$'):
        raise ValueError('部署路径含 systemd 不支持的特殊字符，请使用普通目录路径')
    return '"' + value + '"'


def unit(root, desktop=False):
    root = Path(root).resolve()
    python = Path(sys.executable).absolute()
    path = os.pathsep.join([str(root/'.runtime/node/bin'),str(python.parent),'/usr/local/bin','/usr/bin','/bin'])
    return ('[Unit]\nDescription=Discord local archive\n' +
        (f'Requires={DESKTOP}\nAfter={DESKTOP}\n' if desktop else '') +
        '[Service]\nType=exec\n' +
        f'WorkingDirectory={root}\n' +
        f'ExecStart={quoted(python)} {quoted(root/"app.py")} --root {quoted(root)} --host 127.0.0.1\n' +
        f'Environment={quoted("PATH="+path)}\n' +
        (f'Environment=DISPLAY=:99\nEnvironment={quoted("XAUTHORITY="+str(root/"data/linux-xauthority"))}\nEnvironment=DISCORD_ARCHIVE_LOGIN_DESKTOP=1\n' if desktop else '') +
        ('' if desktop else 'UnsetEnvironment=DISPLAY XAUTHORITY DISCORD_ARCHIVE_LOGIN_DESKTOP\n') +
        'Environment=PYTHONUNBUFFERED=1\nUMask=0077\nRestart=on-failure\nRestartSec=10\n' +
        'TimeoutStopSec=infinity\nKillMode=mixed\n[Install]\nWantedBy=default.target\n')


def desktop_unit(root):
    return ('[Unit]\nDescription=Discord private login display\n[Service]\nType=exec\n' +
        f'ExecStart=/bin/bash {quoted(Path(root)/"scripts/linux_desktop.sh")}\n' +
        'UMask=0077\nRestart=on-failure\nRestartSec=10\n[Install]\nWantedBy=default.target\n')


def systemctl(*args):
    return subprocess.run(['systemctl','--user',*args],check=True,text=True,capture_output=True,timeout=120)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    for flag in ['print','install','status','uninstall']:
        mode.add_argument('--'+flag,action='store_true')
    parser.add_argument('--desktop',action='store_true',help='同时启动仅本机可访问的登录桌面')
    parser.add_argument('--no-autostart',action='store_true',help='安装并启动服务，但不启用下次自动启动；可在工作台设置')
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent)
    args=parser.parse_args()
    root=args.root.resolve()
    if args.print:
        print(unit(root,args.desktop));return
    if not sys.platform.startswith('linux'):
        raise ValueError('此入口仅支持 Linux systemd')
    folder=Path.home()/'.config/systemd/user'
    if args.install:
        if not (root/'app.py').is_file(): raise ValueError('缺少 app.py')
        if args.desktop:
            for command in ['Xvfb','xdpyinfo','xauth','x11vnc','websockify']:
                if not shutil.which(command): raise ValueError('缺少桌面组件：'+command)
        (root/'data').mkdir(mode=0o700,parents=True,exist_ok=True)
        # Refuse to compete with an existing independent archive process.
        import fcntl
        with (root/'data/server.lock').open('a') as lock:
            try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError('已有归档进程，请先从工作台停止服务，再安装') from None
        files={NAME:unit(root,args.desktop)}
        if args.desktop: files[DESKTOP]=desktop_unit(root)
        for name in files:
            target=folder/name
            if target.exists() and str(root) not in target.read_text():
                raise ValueError('同名服务属于另一目录，未覆盖：'+str(target))
        existing_install=(folder/NAME).exists()
        enabled_before=(subprocess.run(['systemctl','--user','is-enabled','--quiet',NAME],capture_output=True,timeout=15).returncode==0) if existing_install else False
        folder.mkdir(parents=True,exist_ok=True)
        for name,content in files.items():
            target=folder/name
            if target.exists():
                backup=root/'data/service-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
                backup.mkdir(parents=True,exist_ok=True);shutil.copy2(target,backup/name)
            target.write_text(content);target.chmod(0o600)
        systemctl('daemon-reload')
        if args.no_autostart:
            systemctl('disable',NAME)
            systemctl('start',NAME)
        elif not existing_install or enabled_before:
            systemctl('enable','--now',NAME)
        else:
            systemctl('start',NAME)
    elif args.uninstall:
        # Keep unit files and all data; stop only this named installation.
        target=folder/NAME
        if not target.exists() or str(root) not in target.read_text():
            raise ValueError('未找到属于当前目录的服务，未停止其他安装')
        systemctl('disable','--now',NAME)
        desktop=folder/DESKTOP
        if desktop.exists() and str(root) in desktop.read_text(): systemctl('stop',DESKTOP)
    print(systemctl('show',NAME,'--property=ActiveState,SubState,MainPID,Result,UnitFileState').stdout)
    if not args.uninstall:
        sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
        from discord_archive.access import linux_access
        access=linux_access()
        print('服务器私有 IP（用于 SSH）：'+('、'.join(access['server_addresses']) or '未检测到，请执行 ip -4 address 核对'))
        print('工作台仅监听 127.0.0.1:8765；不能直接用服务器 IP:8765 打开。')
        print('下一步：按 README 配置 Tailscale HTTPS；以后打开固定私网 HTTPS 地址，使用代理时先打开随包访问客户端。')
        print('SSH 隧道 http://127.0.0.1:18765 只作备用，不是默认日常步骤。')
        print('访问步骤见 docs/LINUX.md；不开放公网端口，不使用 Tailscale Funnel。')


if __name__=='__main__':
    try: main()
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        print('Linux 服务操作未完成：'+str(exc),file=sys.stderr);raise SystemExit(1)
