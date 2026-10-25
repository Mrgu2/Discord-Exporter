#!/usr/bin/env python3
"""Accept only public Tailscale status, never a Tailscale key or account secret."""
import argparse,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from discord_archive.remote_access import https_origin
from discord_archive.settings import atomic_json
parser=argparse.ArgumentParser();parser.add_argument('--https-port',type=int,choices=[443,8443],default=443);args=parser.parse_args()
value=json.loads(sys.stdin.read(1024*1024))
if value.get('BackendState')!='Running':raise ValueError('请先在宿主机完成 Tailscale 授权')
identity=value['Self'];origin=https_origin('https://'+identity['DNSName'].rstrip('.')+('' if args.https_port==443 else ':8443'))
owner=value.get('User',{}).get(str(identity.get('UserID')),{}).get('LoginName')
if not owner:raise ValueError('未确认服务器所属账号，配置未保存')
path=Path(os.environ.get('ARCHIVE_ROOT','/app'))/'data/remote-access.json'
config={'origin':origin,'owners':[owner]}
if path.exists() and json.loads(path.read_text())!=config:raise ValueError('已有另一套访问设置，未覆盖；请先核对')
atomic_json(path,config);print('访问地址：'+origin)
