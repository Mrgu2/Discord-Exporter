#!/usr/bin/env python3
"""Private SSH stdin receiver. Never print input or the server's raw response."""
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import ProxyHandler,Request,build_opener
from urllib.error import HTTPError


def receive(root):
    root=Path(root).expanduser().resolve()
    value=json.loads(sys.stdin.read(16385))
    if not isinstance(value,dict) or set(value)!={'credential','expected_user_id'}:
        raise ValueError('invalid_protocol')
    opener=build_opener(ProxyHandler({}));base='http://127.0.0.1:8765'
    # Root-scoped listener metadata is verified again against live status.
    try:
        listener=json.loads((root/'data/listener.json').read_text())
        port=listener.get('port')
        if listener.get('project_id')==hashlib.sha256(str(root).encode()).hexdigest() and type(port) is int and 1<=port<=65535:
            base=f'http://127.0.0.1:{port}'
    except (OSError, ValueError, TypeError): pass
    status=json.load(opener.open(base+'/api/status',timeout=10))
    expected=hashlib.sha256(str(root).encode()).hexdigest()
    if status.get('platform',{}).get('system')!='linux' or status.get('system',{}).get('project_id')!=expected:
        raise ValueError('wrong_project_or_old_server')
    request=Request(base+'/api/bind-discord',data=json.dumps(value).encode(),method='POST',
        headers={'Content-Type':'application/json','X-Archive-Key':status['archive_key']})
    try:
        result=json.load(opener.open(request,timeout=110))
    except HTTPError as exc:
        print(json.dumps({'ok':False,'code':'server_rejected','http_status':exc.code}));return 1
    if result.get('user_id')!=value.get('expected_user_id') or not result.get('ok'):
        raise ValueError('identity_mismatch')
    print(json.dumps({'ok':True,'same_account':True,'automatic_paused':True}));return 0


if __name__=='__main__':
    try:raise SystemExit(receive(Path(__file__).resolve().parent.parent))
    except Exception:
        print(json.dumps({'ok':False,'code':'receiver_failed'}));raise SystemExit(1)
