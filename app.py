#!/usr/bin/env python3
"""Local web workspace. Remote access requires a separate pairing code."""
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import hmac
import ipaddress
import json
import mimetypes
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from discord_archive.settings import Credentials, Settings, access_code
from discord_archive.store import ArchiveStore
from discord_archive.worker import Worker
from discord_archive.service_control import ServiceControl
from discord_archive.access import linux_access
from discord_archive.system_controls import StartupControl, HostPower
from discord_archive.connection_binding import bind_connection
from discord_archive.phone_sessions import PhoneSessions
from discord_archive.remote_access import RemoteAccess, LoginPairings, DeviceAuthorizations


def choose_export_directory():
    if sys.platform != 'darwin':
        raise ValueError('文件夹选择仅支持 Mac，请填写本机绝对路径')
    try:
        result = subprocess.run(['/usr/bin/osascript', '-e',
            'POSIX path of (choose folder with prompt "选择自动另存目录")'],
            capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise ValueError('文件夹选择已超时，请重试或填写路径') from None
    if result.returncode:
        if '(-128)' in result.stderr:
            return {'cancelled': True}
        raise ValueError('无法打开文件夹选择器，请填写本机绝对路径')
    path = result.stdout.strip()
    if not path or not Path(path).is_absolute():
        raise ValueError('未取得有效的文件夹路径，请重试')
    return {'path': path}


class Application:
    def __init__(self, root, host='0.0.0.0', port=8765):
        self.root, self.host, self.port = Path(root).resolve(), host, port
        os.umask(0o077)
        for name in ('data', 'output'):
            directory = self.root / name
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o700)
        self.process_lock = open(self.root / 'data' / 'server.lock', 'a')
        try:
            fcntl.flock(self.process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('同一资料库已有服务在运行，请打开现有页面') from None
        self.settings, self.credentials = Settings(self.root), Credentials(self.root)
        self.store = ArchiveStore(self.root / 'data' / 'archive.sqlite3')
        from discord_archive.editorial import DraftService
        self.drafts = DraftService(self.store, self.root, self.settings, self.credentials)
        self.worker = Worker(self.store, self.root, self.settings, self.credentials, self.drafts)
        self.service = ServiceControl(self.worker)
        self.startup = StartupControl(self.root,self.host,self.port)
        self.remote_access, self.login_pairings = RemoteAccess(self.root), LoginPairings()
        self.device_authorizations=DeviceAuthorizations(self.login_pairings)
        self.code, self.csrf = access_code(self.root), secrets.token_urlsafe(24)
        self.sessions, self.login_attempts = PhoneSessions(self.root, self.code), {}
        self._status_cache, self._status_cache_lock = {}, threading.RLock()
        self.local_hostname = socket.gethostname().split('.')[0]
        try:
            result = subprocess.run(['/usr/sbin/scutil', '--get', 'LocalHostName'], capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                self.local_hostname = result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass

    def remote_addresses(self):
        return self._cached_status_value('addresses', 30, self._discover_addresses)

    def _cached_status_value(self, key, lifetime, compute):
        # Cache only discovery/boolean flags, never an account credential.
        with self._status_cache_lock:
            now = time.monotonic()
            cached = self._status_cache.get(key)
            if cached is None or now - cached[0] >= lifetime:
                cached = (now, compute())
                self._status_cache[key] = cached
            return copy.deepcopy(cached[1])

    def invalidate_status_cache(self):
        with self._status_cache_lock:
            self._status_cache.clear()

    def _discover_addresses(self):
        if sys.platform.startswith('linux'):
            # The systemd deployment is loopback-only; an interface IP is not
            # an HTTP entry point. Explain the tunnel separately in status.
            return [self.remote_access.origin] if self.remote_access.origin else []
        addresses = [f'http://{self.local_hostname}.local:{self.port}']
        for interface in ('en0', 'en1'):
            try:
                value = subprocess.run(['/usr/sbin/ipconfig', 'getifaddr', interface], capture_output=True, text=True, timeout=2).stdout.strip()
                if value:
                    addresses.append(f'http://{value}:{self.port}')
            except (OSError, subprocess.SubprocessError):
                pass
        return addresses

    def status(self, local=False):
        state, connectivity = self.worker.status()
        # Full job evidence stays on disk; polling needs only the result links.
        result = state.get('last_result')
        if isinstance(result, dict):
            state['last_result'] = {key: value for key, value in result.items()
                if key in {'id', 'title', 'status', 'scope', 'evidence_url', 'manuscript_url',
                           'images', 'channels', 'message_count', 'error', 'path', 'url',
                           'layout_mode', 'render_scale', 'single_columns'}}
            if isinstance(result.get('draft'), dict):
                state['last_result']['draft'] = {key: result['draft'][key]
                    for key in ('id', 'title', 'status') if key in result['draft']}
            if isinstance(result.get('single_columns'), list):
                state['last_result']['single_columns'] = [{key: column[key] for key in
                    ('title', 'channel_id', 'file', 'url', 'images', 'render_scale') if key in column}
                    for column in result['single_columns'] if isinstance(column, dict)]
        runs = self.store.list_runs(limit=40)
        for row in runs:
            row['id'], row['created_at'], row['finished_at'] = row['run_id'], row['started_at'], row['completed_at']
        archive = self.store.summary()
        archive['media'] = self.worker.media.stats()
        archive['attachment_failures'] = archive['media'].get('failed', 0)
        page = self.drafts.list_draft_page(limit=3)
        credential_revision = (state.get('browser_connected'), (state.get('browser_account') or {}).get('id'))
        credential_flags = self._cached_status_value(('credentials', credential_revision), 30,
            lambda: {kind: bool(self.credentials.get(kind)) for kind in ('discord', 'model')})
        return {
            'platform': {'system': sys.platform, 'login_desktop': bool(os.environ.get('DISCORD_ARCHIVE_LOGIN_DESKTOP')) if local else False},
            'system': self._cached_status_value('system_controls',30,
                lambda:{'hostname':self.local_hostname,'binding_root':str(self.root.resolve()),'project_id':hashlib.sha256(str(self.root.resolve()).encode()).hexdigest(),
                    'startup':self.startup.status(),'power':self.service.power.status()})
                if local and hasattr(self,'startup') else {},
            'archive_key': self.csrf, 'service': self.service.status(), 'config': self.settings.read(), 'state': state, 'connectivity': connectivity,
            'runs': runs, 'drafts': page['items'], 'draft_count': page['total'],
            'draft_revision': page['revision'], 'archive': archive,
            'credentials': credential_flags,
            'connection_helper': {'available': bool(local and sys.platform=='darwin' and (self.root/'.local/login-assistants/login-assistant-mac.zip').is_file())},
            'remote': {'urls': self.remote_addresses(),'administrator':local,
                'https_url':getattr(getattr(self,'remote_access',None),'origin',''),
                **({'access':self._cached_status_value('linux_access',30,
                    lambda:linux_access(getattr(self,'host','127.0.0.1'),getattr(self,'port',8765)))} if sys.platform.startswith('linux') else {}),
                **({'access_code': self.code} if local else {})},
        }


def make_handler(application):
    app = application

    class Handler(BaseHTTPRequestHandler):
        server_version = 'AnswerArchive/1.0'

        def log_message(self, *_args):
            # Request paths, query strings, and bodies can contain private data.
            return

        def local(self):
            if any(key in self.headers for key in ('X-Forwarded-For','X-Forwarded-Proto','Forwarded','Tailscale-User-Login')):
                return False
            hostname = urlsplit('http://' + self.headers.get('Host', '')).hostname
            return self.client_address[0] in ('127.0.0.1', '::1') and hostname in ('127.0.0.1', 'localhost', '::1')

        def administrator(self):
            remote=getattr(app,'remote_access',None)
            return self.local() or bool(remote and remote.trusted(self.client_address[0],self.headers))

        def valid_host(self):
            hostname = urlsplit('http://' + self.headers.get('Host', '')).hostname or ''
            remote=getattr(app,'remote_access',None)
            if remote and (hostname==remote.hostname or any(key in self.headers for key in ('X-Forwarded-For','X-Forwarded-Proto','Forwarded','Tailscale-User-Login'))):
                return remote.trusted(self.client_address[0],self.headers)
            if hostname in ('localhost', app.local_hostname.lower() + '.local'):
                return True
            if hostname in os.environ.get('ARCHIVE_ALLOWED_HOSTS', '').split(','):
                return True
            try:
                identity = ipaddress.ip_address(hostname)
                return identity.is_loopback or identity.is_private or identity in ipaddress.ip_network('100.64.0.0/10')
            except ValueError:
                return False

        def authorized(self):
            if self.administrator():
                return True
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get('Cookie', ''))
                session = cookie.get('archive_session')
                return bool(session and app.sessions.get(session.value, 0) > time.time())
            except Exception:
                return False

        def response_headers(self, status, length, mime, extra=None):
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(length))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()

        def send(self, status, content, mime='application/json; charset=utf-8', extra=None):
            if not isinstance(content, bytes):
                content = json.dumps(content, ensure_ascii=False).encode() if mime.startswith('application/json') else content.encode()
            self.response_headers(status, len(content), mime, extra)
            self.wfile.write(content)

        def body(self):
            length = int(self.headers.get('Content-Length', 0))
            if length > 4 * 1024 * 1024:
                raise ValueError('请求内容过大')
            return json.loads(self.rfile.read(length) or b'{}')

        def file(self, base, relative):
            base = Path(base).resolve()
            target = (base / unquote(relative)).resolve()
            if not target.is_relative_to(base):
                return self.send(403, {'error': '无效路径'})
            if target.is_dir():
                target = (target / 'index.html').resolve()
                if not target.is_relative_to(base):
                    return self.send(403, {'error': '无效路径'})
            if not target.is_file():
                return self.send(404, {'error': '文件不存在'})
            mime = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
            try:
                source = target.open('rb')
            except FileNotFoundError:
                return self.send(404, {'error': '文件不存在'})
            with source:
                remaining = os.fstat(source.fileno()).st_size
                try:
                    self.response_headers(200, remaining, mime)
                    while remaining:
                        chunk = source.read(min(256 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return  # A cancelled phone download must not trigger another response.

        def do_GET(self):
            if not self.valid_host():
                return self.send(403, {'error': '访问地址未授权'})
            url = urlsplit(self.path)
            if url.path == '/api/health':
                return self.send(200, {'ok': True, 'service': 'answer-archive'})
            if url.path in ('/', '/index.html'):
                content = (app.root / 'web' / 'index.html').read_text().replace('__ARCHIVE_KEY__', app.csrf)
                return self.send(200, content, 'text/html; charset=utf-8')
            if url.path.startswith('/web/'):
                return self.file(app.root / 'web', url.path.removeprefix('/web/'))
            if url.path in ('/download/login-assistant-mac.zip','/download/login-assistant-windows.zip'):
                if not self.administrator():return self.send(403,{'error':'仅管理员可下载登录助手'})
                source=app.root/'.local/login-assistants'/url.path.rsplit('/',1)[-1]
                if not source.is_file():return self.send(404,{'error':'此平台助手尚未部署，请联系管理员'})
                import io,zipfile
                output=io.BytesIO()
                with zipfile.ZipFile(source) as original,zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                    for member in original.infolist():
                        if member.filename!='server.json':archive.writestr(member,original.read(member.filename))
                    target={'server_url':app.remote_access.origin}
                    if self.local() and sys.platform=='darwin':
                        target={'server_url':f'http://127.0.0.1:{app.port}','project_id':hashlib.sha256(str(app.root).encode()).hexdigest()}
                    archive.writestr('server.json',json.dumps(target))
                return self.send(200,output.getvalue(),'application/zip',{'Content-Disposition':'attachment; filename="'+source.name+'"'})
            if not self.authorized():
                return self.send(401, {'error': '请先输入本机显示的手机访问口令'})
            try:
                if url.path == '/api/status':
                    return self.send(200, app.status(local=self.administrator()))
                if url.path == '/api/drafts':
                    query = parse_qs(url.query)
                    try:
                        limit = int(query.get('limit', ['20'])[0])
                        offset = int(query.get('offset', ['0'])[0])
                        if not 1 <= limit <= 100 or offset < 0:
                            raise ValueError()
                    except ValueError:
                        return self.send(400, {'error': '分页参数无效'})
                    return self.send(200, app.drafts.list_draft_page(
                        limit=limit, offset=offset, search=query.get('search', [''])[0]))
                if url.path == '/api/helper/authorization':
                    if not self.administrator():return self.send(403,{'error':'仅管理员可确认授权'})
                    try:return self.send(200,app.device_authorizations.info(parse_qs(url.query).get('id',[''])[0]))
                    except ValueError as exc:return self.send(400,{'error':str(exc)})
                if url.path == '/api/config':
                    return self.send(200, app.settings.read())
                if url.path == '/api/source':
                    query = parse_qs(url.query)
                    message = app.store.get_message(query['channel_id'][0], query['message_id'][0])
                    return self.send(200 if message else 404, {'message': message, 'versions': app.store.get_versions(query['channel_id'][0], query['message_id'][0])})
                if url.path.startswith('/drafts/'):
                    return self.file(app.root / 'output', url.path.removeprefix('/drafts/'))
                if url.path.startswith('/output/'):
                    return self.file(app.root / 'output', url.path.removeprefix('/output/'))
                if url.path.startswith('/media/'):
                    return self.file(app.root / 'data' / 'media', url.path.removeprefix('/media/'))
                return self.send(404, {'error': '页面不存在'})
            except Exception:
                return self.send(500, {'error': '页面读取失败，请检查本机服务'})

        def mutation(self):
            if not self.valid_host():
                return self.send(403, {'error': '访问地址未授权'})
            origin = self.headers.get('Origin')
            if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                return self.send(403, {'error': '只接受本页操作'})
            helper_path=urlsplit(self.path).path
            if helper_path in ('/api/helper/request','/api/helper/poll','/api/helper/inspect','/api/helper/bind'):
                remote=getattr(app,'remote_access',None)
                if not remote or not remote.trusted(self.client_address[0],self.headers):
                    return self.send(403,{'error':'登录助手仅接受本人 Tailscale HTTPS 连接'})
                try:
                    if int(self.headers.get('Content-Length',0))>16384:raise ValueError('绑定请求过大')
                    data=self.body()
                    if helper_path.endswith('/request'):
                        return self.send(200,app.device_authorizations.request(remote.origin,data.get('device')))
                    if helper_path.endswith('/poll'):
                        return self.send(200,app.device_authorizations.poll(data.get('request_id'),data.get('poll_secret')))
                    app.login_pairings.check(data.get('pairing_code'),consume=helper_path.endswith('/bind'))
                    if helper_path.endswith('/inspect'):
                        return self.send(200,{'ok':True,'server_url':remote.origin,'server_name':app.local_hostname,
                            'existing_account':(app.worker.state.get('browser_account') or {}).get('name')})
                    result=bind_connection(app.credentials,app.worker,data.get('credential'),data.get('expected_user_id'))
                    app.invalidate_status_cache()
                    return self.send(200,{'ok':result['ok'],'automatic_paused':True})
                except (ValueError,KeyError) as exc:return self.send(400,{'error':str(exc)})
                except Exception:return self.send(500,{'error':'绑定未完成；请重新生成配对码后重试'})
            if not hmac.compare_digest(self.headers.get('X-Archive-Key', ''), app.csrf):
                return self.send(403, {'error': '页面已更新，请刷新后重试', 'code': 'csrf_expired'})
            path = urlsplit(self.path).path
            try:
                data = self.body()
                if path == '/api/login':
                    address = self.client_address[0]
                    attempts = [stamp for stamp in app.login_attempts.get(address, []) if stamp > time.time() - 60]
                    if len(attempts) >= 8:
                        return self.send(429, {'error': '尝试过于频繁，请稍后重试'})
                    if not hmac.compare_digest(str(data.get('code', '')), app.code):
                        attempts.append(time.time())
                        app.login_attempts[address] = attempts
                        return self.send(401, {'error': '访问口令不正确'})
                    session = secrets.token_urlsafe(32)
                    app.sessions[session] = time.time() + 30 * 86400
                    return self.send(200, {'ok': True}, extra={'Set-Cookie': f'archive_session={session}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000'})
                if not self.authorized():
                    return self.send(401, {'error': '请先登录手机界面'})
                if path == '/api/helper/approve' and self.command == 'POST':
                    if not self.administrator():return self.send(403,{'error':'仅管理员可确认授权'})
                    return self.send(200,app.device_authorizations.approve(data.get('request_id')))
                if path == '/api/helper/pair' and self.command == 'POST':
                    if not self.administrator():return self.send(403,{'error':'仅管理员可生成配对码'})
                    remote=getattr(app,'remote_access',None)
                    if not remote or not remote.origin:raise ValueError('请先配置 Tailscale HTTPS 访问')
                    return self.send(200,{**app.login_pairings.issue(),'server_url':remote.origin})
                if path == '/api/bind-discord' and self.command == 'POST':
                    if not self.administrator():
                        return self.send(403,{'error':'绑定连接仅允许本机或 SSH 隧道操作'})
                    if sys.platform=='darwin' and data.get('expected_project_id')!=hashlib.sha256(str(app.root).encode()).hexdigest():
                        raise ValueError('本机资料库已变化，请从当前工作台重新下载首次连接包')
                    result=bind_connection(app.credentials,app.worker,data.get('credential'),data.get('expected_user_id'))
                    app.invalidate_status_cache()
                    return self.send(200,result)
                if path == '/api/autostart' and self.command == 'POST':
                    if not self.administrator():
                        return self.send(403, {'error':'自动启动设置仅允许本机或 SSH 隧道操作'})
                    if app.service.action:
                        raise ValueError('服务操作正在进行，请稍后修改自动启动')
                    try:
                        result=app.startup.set_enabled(data.get('enabled'))
                    except RuntimeError as exc:
                        raise ValueError(str(exc)) from None
                    app.invalidate_status_cache()
                    return self.send(200,result)
                if path == '/api/host-power' and self.command == 'POST':
                    if not self.administrator():
                        return self.send(403, {'error':'服务器电源操作仅允许本机或 SSH 隧道操作'})
                    confirmations={'reboot':'重启服务器','poweroff':'关闭服务器'}
                    action=data.get('action')
                    if action not in confirmations or data.get('confirmation')!=confirmations[action]:
                        raise ValueError('请输入对应的服务器电源操作确认文字')
                    result=app.service.request('host-'+action)
                    try:
                        return self.send(202,result)
                    finally:
                        app.service.start()
                if path == '/api/service' and self.command == 'POST':
                    action = data.get('action')
                    if action in {'pause', 'resume'}:
                        return self.send(200, app.worker.set_automatic_paused(action == 'pause'))
                    if action not in {'restart','stop'}:
                        raise ValueError('不支持的服务操作')
                    if not self.administrator():
                        return self.send(403, {'error': '重启或停止服务请在 Mac 本机操作'})
                    result = app.service.request(action)
                    try:
                        return self.send(202, result)
                    finally:
                        app.service.start()
                if path == '/api/config' and self.command == 'PUT':
                    old = app.settings.read()
                    exports = data.get('export', {})
                    if (not self.administrator() and isinstance(exports, dict) and 'copy_directory' in exports
                            and exports['copy_directory'] != old.get('export', {}).get('copy_directory', '')):
                        return self.send(403, {'error': '自动另存目录请在 Mac 本机修改'})
                    result = app.settings.update(data)
                    if 'auto_export' in data:
                        app.worker.configure_auto_export(result)
                    if {key:value for key,value in old.items() if key not in {'export','auto_export'}} != {
                            key:value for key,value in result.items() if key not in {'export','auto_export'}}:
                        app.worker.reset_attention()
                    return self.send(200, result)
                if path == '/api/export-directory' and self.command == 'POST':
                    if not self.administrator():
                        return self.send(403, {'error': '文件夹选择请在 Mac 本机操作'})
                    if data.get('action') != 'choose':
                        raise ValueError('请选择文件夹或填写本机路径')
                    return self.send(200, choose_export_directory())
                if path == '/api/credentials':
                    if not self.administrator():
                        return self.send(403, {'error': '账号凭证请仅在 Mac 本机配置'})
                    backend = app.credentials.set(data['kind'], data['value'])
                    app.invalidate_status_cache()
                    if data['kind'] == 'discord':
                        with app.worker.lock:
                            app.worker.state.update(browser_connected=False, browser_account=None)
                    app.worker.reset_attention()
                    return self.send(200, {'ok': True, 'backend': backend})
                if path == '/api/connect-browser':
                    if not self.administrator():
                        return self.send(403, {'error': '首次连接请在常开 Mac 上操作，之后手机可遥控'})
                    return self.send(202, app.worker.submit('connect_browser'))
                if path == '/api/capture':
                    return self.send(202, app.worker.submit('capture', {'trigger': 'manual'}))
                if path == '/api/drafts':
                    return self.send(202, app.worker.submit('draft', data))
                if path == '/api/render':
                    try:
                        data['draft_id'] = str(uuid.UUID(str(data.get('draft_id', ''))))
                    except ValueError:
                        raise ValueError('稿件 ID 无效') from None
                    data.setdefault('target','main')
                    data.setdefault('render_scale',1)
                    if type(data['render_scale']) is not int or data['render_scale'] not in (1,2):
                        raise ValueError('导出清晰度须为标准 1× 或 HiDPI 2×')
                    if data['target'] not in {'main','mobile','all'}:
                        raise ValueError('图片类型须为 main、mobile 或 all')
                    if 'force' in data and not isinstance(data['force'],bool):
                        raise ValueError('force 须为布尔值')
                    return self.send(202, app.worker.submit('render', data))
                if path == '/api/import':
                    if not self.administrator():
                        return self.send(403, {'error': '导入只能在 Mac 本机操作'})
                    source = Path(data['path']).resolve()
                    if not source.is_file() or source.suffix.lower() != '.json':
                        raise ValueError('请提供本机 JSON 导出文件路径')
                    return self.send(202, app.worker.submit('import', {'path': str(source)}))
                return self.send(404, {'error': '操作不存在'})
            except (ValueError, KeyError) as exc:
                return self.send(400, {'error': str(exc)})
            except Exception:
                return self.send(500, {'error': '操作未完成，请检查本机服务'})

        def do_POST(self):
            self.mutation()

        def do_PUT(self):
            self.mutation()

    return Handler


def main():
    parser = argparse.ArgumentParser(description='Discord 本地答疑归档')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--root', default=str(Path(__file__).parent))
    args = parser.parse_args()
    app = Application(args.root, args.host, args.port)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    server.daemon_threads = True
    app.service.server = server
    app.worker.start()
    def stop(*_args):
        with app.worker.lock:
            app.worker.draining = True
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f'答疑存档已启动：http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    finally:
        # Finish every accepted job, including queued work, before releasing data.
        with app.worker.lock:
            app.worker.draining = True
        app.worker.jobs.join()
        app.worker.stop_event.set()
        app.worker.thread.join()
        app.worker.persist()
        server.server_close()
        app.process_lock.close()
    if app.service.action == 'restart':
        os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()),
            '--root', str(app.root), '--host', args.host, '--port', str(args.port)])


if __name__ == '__main__':
    main()
