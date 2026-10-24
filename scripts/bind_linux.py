#!/usr/bin/env python3
"""Bind this app's existing local Discord login to one verified SSH destination."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from discord_archive.collector import DiscordClient
from discord_archive.settings import Credentials


def read_config(path):
    path=Path(path).expanduser()
    if path.stat().st_mode & 0o077:
        raise ValueError('SSH 配置权限过宽，请先执行 chmod 600 '+str(path))
    result={}
    for line in path.read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        key,separator,value=line.removeprefix('export ').partition('=')
        if separator:result[key.strip()]=' '.join(shlex.split(value,comments=True))
    return result


def ssh_command(config,known_hosts,remote_root):
    host=config.get('SSH_HOST','');user=config.get('SSH_USER','');port=config.get('SSH_PORT') or '22'
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]*',host) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',user):
        raise ValueError('SSH 主机或用户名无效')
    if not port.isdigit() or not 1<=int(port)<=65535:raise ValueError('SSH 端口无效')
    if not Path(known_hosts).expanduser().is_file():raise ValueError('请先通过 SSH 核对服务器指纹，建立 known_hosts 后再绑定')
    args=['ssh','-p',port,'-o','ConnectTimeout=15','-o','StrictHostKeyChecking=yes',
        '-o','UserKnownHostsFile='+str(Path(known_hosts).expanduser()),'-o','SendEnv=-*','-o','NumberOfPasswordPrompts=1']
    env={key:value for key,value in os.environ.items() if key in {'PATH','HOME','SSH_AUTH_SOCK','USER','LOGNAME','LANG','LC_ALL','TMPDIR'}}
    key=config.get('SSH_KEY_PATH')
    if key:
        args+=['-i',str(Path(key).expanduser()),'-o','IdentitiesOnly=yes','-o','BatchMode=yes']
    elif config.get('SSH_PASSWORD'):
        if not shutil.which('sshpass'):raise ValueError('密码方式需要 sshpass；也可改用 SSH 密钥或已解锁的 agent')
        env['SSHPASS']=config['SSH_PASSWORD'];args=['sshpass','-e',*args]
    else:args+=['-o','BatchMode=yes']
    jump=config.get('SSH_JUMP_HOST')
    if jump:
        if not re.fullmatch(r'[A-Za-z0-9_.@:\[\]-]+',jump):raise ValueError('SSH 跳板地址无效')
        args+=['-J',jump]
    bootstrap='from pathlib import Path; import sys; root=Path(sys.argv[1]).expanduser().resolve(); sys.path.insert(0,str(root)); from scripts.receive_connection import receive; raise SystemExit(receive(root))'
    args+=[user+'@'+host,shlex.join(['python3','-c',bootstrap,remote_root])]
    return args,env


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-file',type=Path,required=True)
    parser.add_argument('--remote-root',required=True)
    parser.add_argument('--known-hosts',default=str(Path.home()/'.ssh/known_hosts'))
    args=parser.parse_args()
    command,env=ssh_command(read_config(args.ssh_file),args.known_hosts,args.remote_root)
    token=Credentials(ROOT).get('discord')
    if not token:raise ValueError('本机尚未连接 Discord，请先在本机工作台完成正常登录')
    identity=DiscordClient(token).get('/users/@me')
    user_id=str(identity.get('id','')) if isinstance(identity,dict) else ''
    if not user_id.isdigit():raise ValueError('本机连接身份验证失败')
    payload=json.dumps({'credential':token,'expected_user_id':user_id});token=None
    completed=subprocess.run(command,input=payload,capture_output=True,text=True,env=env,timeout=150)
    payload=None
    try:result=json.loads(completed.stdout) if len(completed.stdout)<16384 else {}
    except ValueError:result={}
    if completed.returncode or not result.get('ok') or not result.get('same_account'):
        raise ValueError('SSH 绑定未确认成功；请检查主机指纹、项目路径、服务器版本或未结束的登录任务。未显示任何原始响应。')
    print('绑定成功：两端账号一致。Ubuntu 已保存连接，可独立采集；自动任务保持暂停，请先配置一个小频道验收。')


if __name__=='__main__':
    try:main()
    except ValueError as exc:
        print('绑定未完成：'+str(exc),file=sys.stderr);raise SystemExit(1)
    except Exception:
        # Do not let exceptions from a credential-bearing pipe print its payload.
        print('绑定未完成：请检查本机连接、SSH 配置及服务器状态；凭证未输出。',file=sys.stderr)
        raise SystemExit(1)
