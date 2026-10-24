#!/usr/bin/env python3
"""Allow only the explicitly selected Tailscale owner through a loopback Serve."""
import argparse,json,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from discord_archive.remote_access import https_origin
from discord_archive.settings import atomic_json
from discord_archive.listener import read_listener

def main():
    p=argparse.ArgumentParser();p.add_argument('--owner');p.add_argument('--root',type=Path,default=ROOT);a=p.parse_args()
    if not sys.platform.startswith('linux'):raise ValueError('请在 Ubuntu 运行')
    s=json.loads(subprocess.check_output(['tailscale','status','--json'],timeout=15))
    if s.get('BackendState')!='Running':raise ValueError('请先通过 tailscale up 的授权链接登录')
    origin=https_origin('https://'+s['Self']['DNSName'].rstrip('.'))
    owner=a.owner or s.get('User',{}).get(str(s['Self'].get('UserID')),{}).get('LoginName')
    if not owner:raise ValueError('无法确认所有者，请显式指定 --owner')
    root=a.root.resolve();target=root/'data/remote-access.json'
    backend=read_listener(root).get('url')
    if not backend: raise ValueError('尚未发现运行端口，请先启动服务，再运行配置器')
    if target.exists():
        backup=root/'data/service-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f');backup.mkdir(parents=True,exist_ok=True);(backup/target.name).write_bytes(target.read_bytes())
    atomic_json(target,{'origin':origin,'owners':[owner]})
    print('访问配置已保存；主服务保持 127.0.0.1 监听。管理员在服务器执行：')
    print('sudo tailscale serve --bg '+backend)
    print('重启本应用后使用 '+origin+'；不启用 Funnel。')
if __name__=='__main__':main()
