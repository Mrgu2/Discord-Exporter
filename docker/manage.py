#!/usr/bin/env python3
"""Private, in-container service control. No host daemon access."""
import argparse
import json
import os
import socket
import sys
from pathlib import Path
from urllib.request import ProxyHandler, build_opener
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from discord_archive.container_runtime import control_directory
from discord_archive.listener import project_id


def command(action):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(10);sock.connect(str(control_directory()/'control.sock'))
        sock.sendall(json.dumps({'action':action}).encode()+b'\n')
        value=b''
        while b'\n' not in value:
            chunk=sock.recv(4096)
            if not chunk or len(value)>16384: raise RuntimeError('容器服务未响应')
            value+=chunk
    result=json.loads(value)
    if result.get('error'): raise RuntimeError(result['error'])
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['start','status','health']);args=parser.parse_args()
    result=command('status' if args.action=='health' else args.action)
    if args.action=='health' and result.get('running'):
        opener=build_opener(ProxyHandler({}))
        status=json.load(opener.open(result['url']+'/api/status',timeout=5))
        if status.get('system',{}).get('project_id')!=project_id(os.environ.get('ARCHIVE_ROOT','/app')):
            raise RuntimeError('健康检查指向其他资料库')
    if args.action!='health': print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(str(exc) if isinstance(exc,(ValueError,RuntimeError)) else '容器应用尚未就绪，请查看 docker compose logs',file=sys.stderr);raise SystemExit(1)
