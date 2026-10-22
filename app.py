#!/usr/bin/env python3
"""Local web workspace. Remote access requires a separate pairing code."""
from __future__ import annotations

import argparse
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
        self.code, self.csrf = access_code(self.root), secrets.token_urlsafe(24)
        self.sessions, self.login_attempts = {}, {}
        self.local_hostname = socket.gethostname().split('.')[0]
        try:
            result = subprocess.run(['/usr/sbin/scutil', '--get', 'LocalHostName'], capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                self.local_hostname = result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass

    def remote_addresses(self):
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
        runs = self.store.list_runs(limit=40)
        for row in runs:
            row['id'], row['created_at'], row['finished_at'] = row['run_id'], row['started_at'], row['completed_at']
        archive = self.store.summary()
        archive['media'] = self.worker.media.stats()
        archive['attachment_failures'] = archive['media'].get('failed', 0)
        return {
            'config': self.settings.read(), 'state': state, 'connectivity': connectivity,
            'runs': runs, 'drafts': self.drafts.list_drafts(), 'archive': archive,
            'credentials': {kind: bool(self.credentials.get(kind)) for kind in ('discord', 'model')},
            'remote': {'urls': self.remote_addresses(), **({'access_code': self.code} if local else {})},
        }


def make_handler(application):
    app = application

    class Handler(BaseHTTPRequestHandler):
        server_version = 'AnswerArchive/1.0'

        def log_message(self, *_args):
            # Request paths, query strings, and bodies can contain private data.
            return

        def local(self):
            hostname = urlsplit('http://' + self.headers.get('Host', '')).hostname
            return self.client_address[0] in ('127.0.0.1', '::1') and hostname in ('127.0.0.1', 'localhost', '::1')

        def valid_host(self):
            hostname = urlsplit('http://' + self.headers.get('Host', '')).hostname or ''
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
            if self.local():
                return True
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get('Cookie', ''))
                session = cookie.get('archive_session')
                return bool(session and app.sessions.get(session.value, 0) > time.time())
            except Exception:
                return False

        def send(self, status, content, mime='application/json; charset=utf-8', extra=None):
            if not isinstance(content, bytes):
                content = json.dumps(content, ensure_ascii=False).encode() if mime.startswith('application/json') else content.encode()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
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
                target = target / 'index.html'
            if not target.is_file():
                return self.send(404, {'error': '文件不存在'})
            mime = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
            return self.send(200, target.read_bytes(), mime)

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
            if not self.authorized():
                return self.send(401, {'error': '请先输入本机显示的手机访问口令'})
            try:
                if url.path == '/api/status':
                    return self.send(200, app.status(local=self.local()))
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
            if not hmac.compare_digest(self.headers.get('X-Archive-Key', ''), app.csrf):
                return self.send(403, {'error': '页面已更新，请刷新后重试'})
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
                if path == '/api/config' and self.command == 'PUT':
                    result = app.settings.update(data)
                    app.worker.reset_attention()
                    return self.send(200, result)
                if path == '/api/credentials':
                    if not self.local():
                        return self.send(403, {'error': '账号凭证请仅在 Mac 本机配置'})
                    backend = app.credentials.set(data['kind'], data['value'])
                    if data['kind'] == 'discord':
                        with app.worker.lock:
                            app.worker.state.update(browser_connected=False, browser_account=None)
                    app.worker.reset_attention()
                    return self.send(200, {'ok': True, 'backend': backend})
                if path == '/api/connect-browser':
                    if not self.local():
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
                    return self.send(202, app.worker.submit('render', data))
                if path == '/api/import':
                    if not self.local():
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
    app.worker.start()
    def stop(*_args):
        app.worker.stop_event.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f'答疑存档已启动：http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    finally:
        app.worker.persist()
        server.server_close()


if __name__ == '__main__':
    main()
