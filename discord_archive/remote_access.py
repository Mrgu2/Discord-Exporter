"""Owner-only HTTPS access behind a loopback Tailscale Serve proxy."""
import hashlib
import hmac
import json
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit


def https_origin(value):
    try:
        p=urlsplit(value)
        if (p.scheme!='https' or not p.hostname or not p.hostname.endswith('.ts.net')
                or p.username or p.password or p.port not in (None,443,8443)
                or p.path not in ('','/') or p.query or p.fragment):
            raise ValueError()
        return 'https://'+p.hostname.lower()+(':8443' if p.port==8443 else '')
    except (ValueError,TypeError,AttributeError):
        raise ValueError('需要 Tailscale 的 HTTPS 根地址，例如 https://主机.私网.ts.net') from None


class RemoteAccess:
    def __init__(self,root):
        self.origin,self.owners='',set()
        path=Path(root)/'data/remote-access.json'
        if path.exists():
            value=json.loads(path.read_text())
            self.origin=https_origin(value['origin'])
            self.owners={x for x in value['owners'] if isinstance(x,str) and x.strip()}
            if not self.owners:raise ValueError('远程管理必须指定 Tailscale 账号')

    @property
    def hostname(self):return urlsplit(self.origin).hostname if self.origin else None

    def trusted(self,address,headers):
        if not self.origin or address not in ('127.0.0.1','::1'):return False
        try:
            host=urlsplit('https://'+headers.get('Host',''))
            if host.hostname!=self.hostname or (host.port or 443)!=(urlsplit(self.origin).port or 443):return False
        except ValueError:return False
        return (headers.get('X-Forwarded-Proto','').lower()=='https'
            and headers.get('Tailscale-User-Login','') in self.owners)


class LoginPairings:
    """Memory-only 5-minute codes; issue revokes old codes, consume is atomic."""
    def __init__(self,clock=time.time):
        self.clock=clock;self.lock=threading.Lock();self.digest=None;self.deadline=0

    def issue(self):
        code=secrets.token_urlsafe(24)
        with self.lock:
            self.digest=hashlib.sha256(code.encode()).digest();self.deadline=self.clock()+300
            return {'pairing_code':code,'expires_at':self.deadline}

    def check(self,code,consume=False):
        if not isinstance(code,str) or not 20<=len(code)<=100:raise ValueError('配对码无效或已过期，请在工作台重新生成')
        with self.lock:
            if self.digest is None or self.clock()>=self.deadline or not hmac.compare_digest(self.digest,hashlib.sha256(code.encode()).digest()):
                raise ValueError('配对码无效或已过期，请在工作台重新生成')
            if consume:self.digest=None

class DeviceAuthorizations:
    """Device-link approval: the browser never receives the helper's polling secret."""
    def __init__(self,pairings,clock=time.time):
        self.pairings=pairings;self.clock=clock;self.lock=threading.RLock();self.current=None

    def request(self,origin,device):
        if not isinstance(device,str) or not 1<=len(device)<=100:raise ValueError('设备名称无效')
        identity=secrets.token_urlsafe(24);secret=secrets.token_urlsafe(32)
        with self.lock:
            self.current={'id':identity,'secret':hashlib.sha256(secret.encode()).digest(),
                'device':device,'expires_at':self.clock()+300,'approved':False,'binding':None}
        return {'request_id':identity,'poll_secret':secret,'authorization_url':origin+'/?authorize='+identity,'expires_in':300}

    def _get(self,identity):
        item=self.current
        if not item or item['id']!=identity or self.clock()>=item['expires_at']:raise ValueError('授权请求已过期，请回到助手重新连接')
        return item

    def info(self,identity):
        with self.lock:
            item=self._get(identity);return {k:item[k] for k in ('device','expires_at','approved')}

    def approve(self,identity):
        with self.lock:
            item=self._get(identity)
            if not item['approved']:
                item['binding']=self.pairings.issue();item['approved']=True
            return {'approved':True}

    def poll(self,identity,secret):
        with self.lock:
            item=self._get(identity)
            if not isinstance(secret,str) or not hmac.compare_digest(item['secret'],hashlib.sha256(secret.encode()).digest()):raise ValueError('助手身份不匹配')
            return {'approved':item['approved'],**(item['binding'] or {})}
