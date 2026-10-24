"""Opt-in Weixin iLink binding, private inbound context and original-file delivery.

Protocol: Tencent/openclaw-weixin/docs/protocol_zh_CN.md (reviewed 2026-10-25).
No message content is archived here and no inbound text is executed.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .settings import atomic_json
from .store import utc_now

API = 'https://ilinkai.weixin.qq.com'
CDN = 'https://novac2c.cdn.weixin.qq.com/c2c'
VERSION = '2.4.10'
HELPER = Path(__file__).resolve().parent.parent / 'scripts/clawbot_crypto.mjs'


class ClawBotError(ValueError):
    pass


class ClawBotNeedsAction(ClawBotError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def official_url(value, *, cdn=False):
    """Only Tencent's documented service namespaces; credentials never redirect."""
    if not isinstance(value, str):
        raise ClawBotError('微信返回了无效的服务地址')
    p = urlsplit(value)
    host = p.hostname or ''
    pattern = r'[a-z0-9-]+\.cdn\.weixin\.qq\.com' if cdn else r'ilink[a-z0-9-]*\.weixin\.qq\.com'
    if (p.scheme != 'https' or not re.fullmatch(pattern, host) or p.netloc != host
            or p.fragment or (not cdn and (p.path not in ('', '/') or p.query))):
        raise ClawBotError('微信返回了未认可的服务地址，请重新扫码')
    return value.rstrip('/') if not cdn else value


def helper(action, data):
    node = shutil.which('node')
    if not node:
        raise ClawBotError('ClawBot 需要 Node.js，请先运行应用安装程序')
    try:
        result = subprocess.run([node, str(HELPER), action], input=data, capture_output=True, timeout=25)
        if result.returncode != 0:
            raise ClawBotError('ClawBot 二维码或加密组件不可用，请重新运行应用安装程序')
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        raise ClawBotError('ClawBot 本地组件未完成，请检查 Node.js 安装') from None


class ClawBot:
    def __init__(self, root, credentials, stop_event=None):
        self.path = Path(root) / 'data/clawbot-state.json'
        self.credentials = credentials
        self.stop = stop_event or threading.Event()
        self.lock = threading.RLock()
        self.thread = None
        self.pending = None
        saved = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.state = {'cursor': '', 'context_token': '', 'context_updated_at': None,
            'needs_message': False, 'needs_rebind': False, 'error': None, **saved}
        self.account = self._load_account()

    def _load_account(self):
        try:
            account = json.loads(self.credentials.get('delivery_clawbot') or 'null')
            if not isinstance(account, dict) or not all(isinstance(account.get(k), str) and account[k]
                    for k in ('token', 'user_id', 'bot_id', 'api_url')):
                return None
            official_url(account['api_url'])
            return account
        except (ValueError, TypeError):
            return None

    def _save(self, **changes):
        with self.lock:
            state = {**self.state, **changes}
            atomic_json(self.path, state)
            self.state = state

    def binding_id(self):
        with self.lock:
            if not self.account:
                raise ClawBotNeedsAction('请先扫码绑定微信 ClawBot')
            return hashlib.sha256(json.dumps([self.account['bot_id'], self.account['user_id']]).encode()).hexdigest()

    def ready_for(self, binding):
        with self.lock:
            return bool(self.account and binding == self.binding_id() and self.state['context_token']
                        and not self.state['needs_message'] and not self.state['needs_rebind'])

    def status(self):
        with self.lock:
            pending = self.pending
            login = pending['status'] if pending else None
            if pending and pending['status'] != 'confirmed' and time.monotonic() - pending['started'] > 300:
                login = 'expired'
            bound = bool(self.account)
            ready = bound and bool(self.state['context_token']) and not (self.state['needs_message'] or self.state['needs_rebind'])
            return {'connected': bound, 'ready': ready, 'needs_rebind': self.state['needs_rebind'],
                'status': 'ready' if ready else 'needs_rebind' if self.state['needs_rebind'] else 'needs_message' if bound else 'unbound',
                'login_status': login, 'login_id': pending['id'] if pending else None,
                'qr_url': '/api/clawbot/qr?id=' + pending['id'] if pending and login not in ('expired', 'confirmed', 'verify_code_blocked') else None,
                'context_updated_at': self.state['context_updated_at'], 'error': self.state['error']}

    def _request(self, base, endpoint, body=None, *, token=None, timeout=40, qr_poll=False):
        base = official_url(base)
        headers = {'iLink-App-Id': 'bot', 'iLink-App-ClientVersion': str((2 << 16) | (4 << 8) | 10),
                   'User-Agent': 'DiscordArchive/1.0'}
        if not qr_poll:
            headers.update({'Content-Type': 'application/json', 'AuthorizationType': 'ilink_bot_token',
                'X-WECHAT-UIN': base64.b64encode(str(secrets.randbits(32)).encode()).decode()})
            if token:
                headers['Authorization'] = 'Bearer ' + token
                body = {**(body or {}), 'base_info': {'channel_version': VERSION, 'bot_agent': 'DiscordArchive/1.0'}}
        request = Request(base + '/' + endpoint, data=None if qr_poll else json.dumps(body or {}).encode(), headers=headers)
        try:
            with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ClawBotError('微信响应过大，请稍后重试')
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ClawBotError('微信返回了无效响应')
            if result.get('ret', 0) != 0 or result.get('errcode', 0) != 0:
                if -14 in (result.get('ret'), result.get('errcode')):
                    self._save(needs_rebind=True, error='微信登录已失效，请重新扫码绑定')
                    raise ClawBotNeedsAction('微信登录已失效，请重新扫码绑定')
                if -2 in (result.get('ret'), result.get('errcode')):
                    self._save(needs_message=True, error='微信未接受当前会话，请向 ClawBot 发一条消息后重试')
                    raise ClawBotNeedsAction('微信未接受当前会话，请向 ClawBot 发一条消息后重试')
                raise ClawBotError('微信拒绝请求，请检查连接或稍后重试')
            return result
        except ClawBotError:
            raise
        except HTTPError as exc:
            code = exc.code
            exc.close()
            raise ClawBotError(f'微信连接失败（HTTP {code}），请稍后重试') from None
        except Exception:
            raise ClawBotError('微信连接未完成，请检查服务器网络后重试') from None

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._loop, name='clawbot-receiver', daemon=True)
            self.thread.start()

    def begin(self):
        result = self._request(API, 'ilink/bot/get_bot_qrcode?bot_type=3', {'local_token_list': []})
        value, content = result.get('qrcode'), result.get('qrcode_img_content')
        if not isinstance(value, str) or not value or not isinstance(content, str) or not content or len(content) > 4096:
            raise ClawBotError('微信未返回可用二维码，请重试')
        png = helper('qr', content.encode())
        with self.lock:
            self.pending = {'id': uuid.uuid4().hex, 'value': value, 'png': png, 'status': 'wait',
                'started': time.monotonic(), 'base': API, 'verify_code': None}
        self._save(error=None)
        self.start()
        return self.status()

    def qr(self, identity):
        with self.lock:
            if (not self.pending or self.pending['id'] != identity
                    or time.monotonic() - self.pending['started'] > 300
                    or self.pending['status'] in ('confirmed', 'expired', 'verify_code_blocked')):
                raise ClawBotError('二维码已过期，请重新生成')
            return self.pending['png']

    def verify(self, identity, code):
        if not isinstance(code, str) or not re.fullmatch(r'[0-9]{4,12}', code):
            raise ClawBotError('请输入微信手机端显示的验证码')
        with self.lock:
            if not self.pending or self.pending['id'] != identity or self.pending['status'] != 'need_verifycode':
                raise ClawBotError('当前不需要验证码，请刷新连接状态')
            self.pending['verify_code'] = code
        return {'ok': True}

    def _poll_login(self):
        with self.lock:
            login = copy.deepcopy(self.pending)
        if time.monotonic() - login['started'] > 300:
            with self.lock:
                if self.pending and self.pending['id'] == login['id']:
                    self.pending['status'] = 'expired'
            return
        query = {'qrcode': login['value']}
        if login['verify_code']:
            query['verify_code'] = login['verify_code']
        result = self._request(login['base'], 'ilink/bot/get_qrcode_status?' + urlencode(query), qr_poll=True)
        status = result.get('status')
        allowed = {'wait', 'scaned', 'confirmed', 'expired', 'need_verifycode', 'verify_code_blocked', 'scaned_but_redirect', 'binded_redirect'}
        if status not in allowed:
            raise ClawBotError('微信二维码状态异常，请刷新二维码')
        with self.lock:
            if not self.pending or self.pending['id'] != login['id'] or time.monotonic() - login['started'] > 300:
                return
            if status == 'scaned_but_redirect':
                host = result.get('redirect_host', '')
                self.pending['base'] = official_url(host if host.startswith('https://') else 'https://' + host)
            elif status == 'confirmed':
                account = {'token': result.get('bot_token'), 'user_id': result.get('ilink_user_id'),
                    'bot_id': result.get('ilink_bot_id'), 'api_url': official_url(result.get('baseurl') or login['base'])}
                if not all(isinstance(v, str) and v for v in account.values()):
                    raise ClawBotError('微信绑定信息不完整，请重新扫码')
                self.credentials.set('delivery_clawbot', json.dumps(account, separators=(',', ':')))
                self.account = account
                self._save(cursor='', context_token='', context_updated_at=None, needs_message=True, needs_rebind=False, error=None)
            elif status == 'binded_redirect':
                if not self.account:
                    raise ClawBotError('微信提示已绑定，但本机没有凭据，请先在微信解除旧绑定后重新扫码')
                status = 'confirmed'
            # Never resubmit a phone verification code automatically after a
            # rejected attempt; the user must explicitly enter a fresh code.
            if status == 'scaned' or (login['verify_code'] and self.pending['verify_code'] == login['verify_code']):
                self.pending['verify_code'] = None
            self.pending['status'] = status

    def _poll_messages(self):
        with self.lock:
            account, cursor = copy.deepcopy(self.account), self.state['cursor']
        result = self._request(account['api_url'], 'ilink/bot/getupdates', {'get_updates_buf': cursor}, token=account['token'])
        context = None
        for message in result.get('msgs') or []:
            # Only the person who scanned the QR can refresh this private target.
            if (isinstance(message, dict) and not message.get('group_id') and message.get('from_user_id') == account['user_id']
                    and message.get('message_type') == 1 and isinstance(message.get('context_token'), str)
                    and message['context_token']):
                context = message['context_token']
        with self.lock:
            if self.account != account:
                return
            changes = {}
            if isinstance(result.get('get_updates_buf'), str) and result['get_updates_buf']:
                changes['cursor'] = result['get_updates_buf']
            if context:
                changes.update(context_token=context, context_updated_at=utc_now(), needs_message=False, error=None)
            if changes:
                self._save(**changes)

    def _loop(self):
        while not self.stop.is_set():
            try:
                with self.lock:
                    login = self.pending and self.pending['status'] not in ('confirmed', 'expired', 'verify_code_blocked')
                    receive = self.account and not self.state['needs_rebind']
                if login:
                    self._poll_login()
                elif receive:
                    self._poll_messages()
                else:
                    self.stop.wait(1)
                    continue
                self.stop.wait(1)
            except Exception as exc:
                self._save(error=str(exc) if isinstance(exc, ClawBotError) else '微信连接未完成，请稍后重试')
                self.stop.wait(10)

    def send_file(self, path, title, binding):
        with self.lock:
            if not self.ready_for(binding):
                if self.account and binding != self.binding_id():
                    raise ClawBotNeedsAction('微信绑定对象已改变，请确认收件人后手动重试')
                raise ClawBotNeedsAction('请先绑定微信，并向 ClawBot 发一条消息后重试')
            account, context = copy.deepcopy(self.account), self.state['context_token']
        if path.stat().st_size > 18 * 1024 * 1024:
            raise ClawBotError('ClawBot 单张图片保守上限为 18 MiB，请降低清晰度')
        raw = path.read_bytes()
        key, filekey = secrets.token_bytes(16), secrets.token_hex(16)
        encrypted = helper('encrypt', key + raw)
        response = self._request(account['api_url'], 'ilink/bot/getuploadurl', {
            'filekey': filekey, 'media_type': 3, 'to_user_id': account['user_id'], 'rawsize': len(raw),
            'rawfilemd5': hashlib.md5(raw).hexdigest(), 'filesize': len(encrypted), 'no_need_thumb': True,
            'aeskey': key.hex()}, token=account['token'])
        url = response.get('upload_full_url')
        if not url and response.get('upload_param'):
            url = CDN + '/upload?' + urlencode({'encrypted_query_param': response['upload_param'], 'filekey': filekey})
        url = official_url(url, cdn=True)
        try:
            request = Request(url, data=encrypted, headers={'Content-Type': 'application/octet-stream'})
            with build_opener(NoRedirect()).open(request, timeout=45) as response:
                download = response.headers.get('x-encrypted-param')
                if response.status != 200 or not download:
                    raise ClawBotError('微信文件上传未得到确认，请重试')
        except ClawBotError:
            raise
        except Exception:
            raise ClawBotError('微信文件上传未完成，请检查网络后重试') from None
        result = self._request(account['api_url'], 'ilink/bot/sendmessage', {'msg': {
            'from_user_id': '', 'to_user_id': account['user_id'], 'client_id': 'archive-' + uuid.uuid4().hex,
            'message_type': 2, 'message_state': 2, 'context_token': context, 'item_list': [{
                'type': 4, 'file_item': {'file_name': path.name, 'len': str(len(raw)), 'media': {
                    'encrypt_query_param': download, 'aes_key': base64.b64encode(key.hex().encode()).decode(),
                    'encrypt_type': 1}}}]}}, token=account['token'])
        # Tencent's client treats an absent ret as success. Some live iLink
        # responses are {}, after HTTP 200; _request has already rejected any
        # explicit nonzero ret/errcode. Requiring the field here causes duplicates.
        if result.get('ret', 0) != 0:
            raise ClawBotError('微信没有确认发送成功，请检查收件情况')
