"""Durable per-file outbox. No transport response or credential is persisted."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import smtplib
import ssl
import threading
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .clawbot import ClawBot, ClawBotError, ClawBotNeedsAction
from .delivery_config import CHANNELS, SECRET_KINDS, normalize_delivery, validate_destination
from .settings import atomic_json
from .store import parse_time, utc_now


class DeliveryError(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def multipart(fields, path):
    boundary = 'archive-' + uuid.uuid4().hex
    chunks = []
    for key, value in fields.items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    # Fixed ASCII wire name avoids header injection; captions retain the title.
    key = 'document' if 'chat_id' in fields else 'files[0]'
    chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="archive.png"\r\nContent-Type: image/png\r\n\r\n'.encode())
    chunks.extend([path.read_bytes(), f'\r\n--{boundary}--\r\n'.encode()])
    return b''.join(chunks), f'multipart/form-data; boundary={boundary}'


def send_file(channel, options, secret, path, title):
    """Return only a safe receipt. Remote error bodies must never escape."""
    if not secret:
        raise DeliveryError('尚未配置此渠道的发送凭据')
    try:
        if channel == 'email':
            if path.stat().st_size > 18 * 1024 * 1024:
                raise DeliveryError('单张图片超过邮箱保守附件上限 18 MiB，请降低导出清晰度')
            message = EmailMessage()
            message['Subject'] = title
            message['From'] = options['sender']
            message['To'] = ', '.join(options['recipients'])
            message.set_content('答疑存档图片见附件。')
            message.add_attachment(path.read_bytes(), maintype='image', subtype='png', filename=path.name)
            context = ssl.create_default_context()
            smtp_class = smtplib.SMTP_SSL if options['security'] == 'ssl' else smtplib.SMTP
            kwargs = {'timeout': 30}
            if options['security'] == 'ssl':
                kwargs['context'] = context
            with smtp_class(options['host'], options['port'], **kwargs) as smtp:
                if options['security'] == 'starttls':
                    smtp.ehlo()
                    smtp.starttls(context=context)
                    smtp.ehlo()
                smtp.login(options['username'] or options['sender'], secret)
                refused = smtp.send_message(message)
                if refused:
                    raise DeliveryError('部分收件人被拒绝，请检查收件人；重试可能重复投递已接收的收件人')
            return
        if channel == 'telegram':
            if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+', secret):
                raise DeliveryError('Telegram Bot Token 格式无效')
            url = f'https://api.telegram.org/bot{secret}/sendDocument'
            fields = {'chat_id': options['chat_id'], 'caption': title[:1000]}
            limit = 50 * 1024 * 1024
        elif channel == 'discord':
            parsed = urlsplit(secret)
            if (parsed.scheme != 'https' or parsed.netloc != 'discord.com'
                    or not re.fullmatch(r'/api(?:/v\d+)?/webhooks/\d+/[A-Za-z0-9_-]+', parsed.path)
                    or parsed.query or parsed.fragment):
                raise DeliveryError('请使用 https://discord.com/api/webhooks/… 地址')
            url = secret + '?wait=true'
            fields = {'payload_json': json.dumps({'content': title[:1900], 'allowed_mentions': {'parse': []}}, ensure_ascii=False)}
            limit = 10 * 1024 * 1024
        else:
            raise DeliveryError('推送渠道无效')
        if path.stat().st_size > limit:
            raise DeliveryError('图片超过此渠道的附件上限，请降低导出清晰度')
        body, content_type = multipart(fields, path)
        request = Request(url, data=body, headers={'Content-Type': content_type, 'User-Agent': 'DiscordArchive/1.0'})
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            result = json.loads(response.read(65536))
        if not isinstance(result, dict) or (channel == 'telegram' and result.get('ok') is not True) or (channel == 'discord' and not result.get('id')):
            raise DeliveryError('平台未确认发送成功，请检查渠道配置')
    except DeliveryError:
        raise
    except HTTPError as exc:
        exc.close()
        if exc.code == 429:
            raise DeliveryError('平台限流，稍后自动重试') from None
        raise DeliveryError(f'平台拒绝发送（HTTP {exc.code}），请检查凭据、权限和附件大小') from None
    except smtplib.SMTPAuthenticationError:
        raise DeliveryError('邮箱认证失败，请检查账号与 SMTP 授权凭据') from None
    except Exception:
        raise DeliveryError('发送未确认成功，请检查服务器网络、渠道配置和附件限制；重试可能重复投递') from None


class DeliveryOutbox:
    def __init__(self, root, settings, credentials, stop_event=None):
        self.root, self.settings, self.credentials = Path(root).resolve(), settings, credentials
        self.path = self.root / 'data/delivery-state.json'
        self.lock = threading.RLock()
        self.clawbot = ClawBot(root, credentials, stop_event)
        self.items = json.loads(self.path.read_text()) if self.path.exists() else {}

    def _save(self, items):
        # Bound disposable history only. Pending/failed real deliveries and
        # source PNGs are never removed by history maintenance.
        items = dict(items)
        for test, limit in ((True, 100), (False, 1000)):
            completed = [key for key, item in items.items()
                         if bool(item.get('test')) == test and
                         (item.get('status') == 'sent' or (test and item.get('status') == 'failed'))]
            for key in completed[:-limit]:
                items.pop(key)
        atomic_json(self.path, items)
        self.items = items

    def _image(self, relative):
        path = (self.root / relative).resolve()
        output = (self.root / 'output').resolve()
        if output not in path.parents or path.suffix.lower() != '.png' or not path.is_file():
            raise DeliveryError('推送图片不存在或不在导出目录中')
        with path.open('rb') as handle:
            header = handle.read(8)
        if header != b'\x89PNG\r\n\x1a\n':
            raise DeliveryError('推送源文件不是 PNG 图片')
        return path

    def enqueue_render(self, result, *, draft_id, scale, target):
        preferences = normalize_delivery(self.settings.read().get('delivery'))
        if not any(row['enabled'] for row in preferences.values()):
            return
        draft = result.get('draft') or {}
        variant = (draft.get('image_variants') or {}).get(str(scale)) or draft
        urls = list(variant.get('images') or result.get('images') or [])
        if target == 'all':
            for column in variant.get('single_columns') or result.get('single_columns') or []:
                urls.extend(column.get('images') or [])
        if not urls:
            raise DeliveryError('未找到可推送的导出图片')
        for index, url in enumerate(dict.fromkeys(urls), 1):
            if not isinstance(url, str) or not url.startswith('/output/') or urlsplit(url).query:
                raise DeliveryError('导出图片路径无效')
            path = self._image(unquote(url.lstrip('/')))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            for channel, row in preferences.items():
                if row['enabled']:
                    self._enqueue(channel, row, path, f'{draft.get("title") or draft_id} · {scale}× · 第 {index} 张',
                                  f'{draft_id}:{scale}:{path.relative_to(self.root)}:{digest}', False)

    def _enqueue(self, channel, options, path, title, identity, test):
        # Destination is captured so queued private exports cannot silently move
        # to a newly configured recipient. Secrets are always read at send time.
        if channel == 'clawbot':
            options = {**options, 'binding_id': self.clawbot.binding_id()}
        key = hashlib.sha256(json.dumps([channel, identity], sort_keys=True).encode()).hexdigest()
        with self.lock:
            items = copy.deepcopy(self.items)
            if key in items:
                return key
            if sum(item.get('status') not in ('sent', 'failed') or
                   (item.get('status') == 'failed' and not item.get('test')) for item in items.values()) >= 1000:
                raise DeliveryError('待处理推送已达 1000 条，请先处理失败记录；未清理原图或未完成任务')
            items[key] = {'id': key, 'channel': channel, 'options': options,
                'path': str(path.relative_to(self.root)), 'title': title[:180], 'test': test,
                'status': 'pending', 'attempts': 0, 'retry_at': utc_now(), 'error': None,
                'created_at': utc_now(), 'sent_at': None}
            self._save(items)
        return key

    def enqueue_test(self, channel):
        if channel not in CHANNELS:
            raise ValueError('推送渠道无效')
        row = normalize_delivery(self.settings.read().get('delivery'))[channel]
        validate_destination(channel, row)
        if not self.credentials.get(SECRET_KINDS[channel]):
            raise ValueError('请先保存此渠道的发送凭据')
        folder = self.root / 'output/delivery-test'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / 'test.png'
        # A valid tiny PNG, with a descriptive caption; never sends archive data.
        path.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII='))
        return self._enqueue(channel, row, path, '答疑存档 · 测试发送', uuid.uuid4().hex, True)

    def due(self, now=None, *, manual_only=False):
        now = now or datetime.now(timezone.utc)
        preferences = normalize_delivery(self.settings.read().get('delivery'))
        with self.lock:
            for key, item in self.items.items():
                if manual_only and not (item['test'] or item.get('manual')):
                    continue
                ready = item['status'] in ('pending', 'retrying')
                if item['status'] == 'attention' and item['channel'] == 'clawbot':
                    ready = self.clawbot.ready_for(item['options'].get('binding_id'))
                if (ready and item['attempts'] < 8
                        and (item['test'] or item.get('manual') or preferences[item['channel']]['enabled'])
                        and (item['retry_at'] is None or parse_time(item['retry_at']) <= now)):
                    return key
        return None

    def is_manual(self, key):
        with self.lock:
            item = self.items[key]
            return bool(item['test'] or item.get('manual'))

    def send(self, key):
        with self.lock:
            item = copy.deepcopy(self.items[key])
        if item['status'] == 'sent':
            return {'status': 'sent', 'deduplicated': True}
        preferences = normalize_delivery(self.settings.read().get('delivery'))
        if not (item['test'] or item.get('manual')) and not preferences[item['channel']]['enabled']:
            return {'status': 'disabled'}
        try:
            path = self._image(item['path'])
            if item['channel'] == 'clawbot':
                self.clawbot.send_file(path, item['title'], item['options'].get('binding_id'))
            else:
                send_file(item['channel'], item['options'], self.credentials.get(SECRET_KINDS[item['channel']]), path, item['title'])
            item.update(status='sent', sent_at=utc_now(), error=None, retry_at=None)
        except Exception as exc:
            item['attempts'] += 1
            delay = min(30 * 2 ** min(item['attempts'] - 1, 6), 1800)
            item.update(status='failed' if item['attempts'] >= 8 else 'retrying',
                        error=str(exc) if isinstance(exc, (DeliveryError, ClawBotError)) else '发送失败，请检查渠道设置',
                        retry_at=(datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat())
            if isinstance(exc, ClawBotNeedsAction):
                item.update(status='attention', retry_at=None)
        with self.lock:
            self._save({**self.items, key: item})
        return {'status': item['status']}

    def retry(self, key):
        with self.lock:
            item = copy.deepcopy(self.items.get(key))
            if not item or item['status'] not in ('retrying', 'failed', 'attention'):
                raise ValueError('请选择发送失败的记录')
            # Manual retry uses freshly saved destination settings, allowing a
            # mistyped chat ID or mailbox to be corrected deliberately.
            item['options'] = normalize_delivery(self.settings.read().get('delivery'))[item['channel']]
            validate_destination(item['channel'], item['options'])
            if item['channel'] == 'clawbot':
                item['options']['binding_id'] = self.clawbot.binding_id()
            item.update(status='pending', attempts=0, retry_at=utc_now(), error=None, manual=True)
            self._save({**self.items, key: item})
        return {'status': 'pending'}

    def summary(self):
        with self.lock:
            return [{key: item.get(key) for key in ('id', 'channel', 'title', 'test', 'status', 'attempts', 'retry_at', 'error', 'created_at', 'sent_at')}
                    for item in list(self.items.values())[-30:][::-1]]
