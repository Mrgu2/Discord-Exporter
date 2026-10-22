"""Read-only Discord capture. Network failures never advance a successful cursor."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .store import parse_time


class DiscordAPIError(Exception):
    def __init__(self, status, message, retry_after=None):
        super().__init__(message)
        self.status, self.retry_after = status, retry_after


class AuthRequired(DiscordAPIError):
    pass


class AccessDenied(DiscordAPIError):
    pass


class CaptureBusy(Exception):
    pass


def http_transport(method, url, headers):
    request = Request(url, headers=headers, method=method)
    try:
        with urlopen(request, timeout=25) as response:
            return response.status, dict(response.headers), json.load(response)
    except HTTPError as exc:
        try:
            body = json.loads(exc.read(1048576))
        except (ValueError, OSError):
            body = {}
        return exc.code, dict(exc.headers), body


class DiscordClient:
    def __init__(self, token, transport=None, sleep=time.sleep):
        self._token = token
        self.transport, self.sleep = transport or http_transport, sleep
        self._channel_cache = {}

    def get(self, path, params=None):
        if not path.startswith('/') or '://' in path:
            raise ValueError('Only Discord API paths are accepted')
        url = 'https://discord.com/api/v10' + path
        if params:
            url += '?' + urlencode({k: v for k, v in params.items() if v is not None})
        for attempt in range(3):
            try:
                status, headers, body = self.transport('GET', url, {
                    'Authorization': self._token, 'Accept': 'application/json',
                    'User-Agent': 'DiscordArchiveLocal/1.0 (read-only archive)',
                })
            except (URLError, OSError, TimeoutError):
                if attempt == 2:
                    raise DiscordAPIError(0, '网络连接失败，等待自动重连') from None
                self.sleep(2 ** attempt)
                continue
            if 200 <= status < 300:
                return body
            if status == 401:
                raise AuthRequired(401, 'Discord 登录凭证失效，请在本机重新设置')
            if status == 403:
                raise AccessDenied(403, '没有读取此频道的权限，请核对频道设置')
            if status == 429:
                lowered = {k.lower(): v for k, v in headers.items()}
                raw_delay = body.get('retry_after', lowered.get('retry-after', 1)) if isinstance(body, dict) else lowered.get('retry-after', 1)
                try:
                    delay = max(0.05, float(raw_delay))
                except (ValueError, TypeError):
                    delay = 1
                if attempt == 2 or delay > 30:
                    raise DiscordAPIError(429, 'Discord 限流，按服务端等待时间重试', retry_after=delay)
                self.sleep(delay)
                continue
            if status >= 500 and attempt < 2:
                self.sleep(2 ** attempt)
                continue
            raise DiscordAPIError(status, f'Discord 读取失败（HTTP {status}）')
        raise DiscordAPIError(0, '读取未完成')

    def list_messages(self, channel_id, before=None, after=None, limit=100):
        if not str(channel_id).isdigit():
            raise ValueError('Invalid channel id')
        return self.get(f'/channels/{channel_id}/messages', {'limit': limit, 'before': before, 'after': after})

    def get_channel(self, channel_id):
        channel_id = str(channel_id)
        if not channel_id.isdigit():
            raise ValueError('Invalid channel id')
        if channel_id not in self._channel_cache:
            channel = self.get(f'/channels/{channel_id}')
            if not isinstance(channel, dict) or str(channel.get('id', '')) != channel_id:
                raise DiscordAPIError(0, '频道元数据响应异常，未推进保存位置')
            self._channel_cache[channel_id] = dict(channel)
        return dict(self._channel_cache[channel_id])


_capture_lock = threading.Lock()


class CaptureService:
    def __init__(self, store, client, channels, clock=None, on_page=None):
        self.store, self.client, self.channels = store, client, channels
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.on_page = on_page

    def capture(self, trigger='manual'):
        if not _capture_lock.acquire(blocking=False):
            raise CaptureBusy('已有保存任务在运行')
        summary = {'channels': [], 'status': 'success', 'message_count': 0, 'inserted': 0, 'permission_denied_channels': []}
        try:
            for channel in self.channels:
                channel_id = str(channel['id'] if isinstance(channel, dict) else channel)
                self.store.ensure_channel(channel_id, name=channel.get('label') if isinstance(channel, dict) else None)
                now = self.clock()
                state = self.store.channel_status(channel_id)
                previous = parse_time(state.get('last_success_at'))
                # Read backwards, including edits and old visible replies. First
                # run reads all still-visible history; later runs overlap 48h.
                cutoff = min(now - timedelta(hours=48), previous - timedelta(hours=1)) if previous else None
                run_id = self.store.start_run(channel_id, trigger=trigger, started_at=now)
                before, newest = None, state.get('cursor')
                details = {'channel_id': channel_id, 'run_id': run_id, 'message_count': 0, 'inserted': 0, 'status': 'running'}
                try:
                    # REST message objects usually omit guild_id. Persist the
                    # configured channel's metadata so offline source links do
                    # not incorrectly point at the direct-message (@me) route.
                    # Simple historical fixtures implement list_messages only.
                    get_channel = getattr(self.client, 'get_channel', None)
                    if not state.get('guild_id') and callable(get_channel):
                        metadata = get_channel(channel_id)
                        if not isinstance(metadata, dict) or str(metadata.get('id', '')) != channel_id:
                            raise DiscordAPIError(0, '频道元数据响应异常，未推进保存位置')
                        guild_id = metadata.get('guild_id')
                        if guild_id is not None and not str(guild_id).isdigit():
                            raise DiscordAPIError(0, '频道服务器 ID 无效，未推进保存位置')
                        if guild_id is None and metadata.get('type') not in (1, 3):
                            raise DiscordAPIError(0, '频道元数据缺少服务器信息，未推进保存位置')
                        self.store.ensure_channel(channel_id, guild_id=str(guild_id) if guild_id is not None else None,
                            name=(channel.get('label') if isinstance(channel, dict) else None) or metadata.get('name'))
                    for _page in range(10000):
                        messages = self.client.list_messages(channel_id, before=before)
                        if not isinstance(messages, list):
                            raise DiscordAPIError(0, '消息响应格式异常，未推进保存位置')
                        if not messages:
                            break
                        valid = [m for m in messages if isinstance(m, dict) and str(m.get('id', '')).isdigit()]
                        if len(valid) != len(messages):
                            raise DiscordAPIError(0, '消息缺少有效 ID，未推进保存位置')
                        oldest = min((str(m['id']) for m in valid), key=int)
                        if before and int(oldest) >= int(before):
                            raise DiscordAPIError(0, '分页位置未前进，未推进保存位置')
                        newest = max([x for x in [newest] + [str(m['id']) for m in valid] if x], key=int)
                        stats = self.store.ingest_messages(channel_id, valid, run_id=run_id, observed_at=self.clock())
                        details['message_count'] += len(valid)
                        details['inserted'] += stats['inserted']
                        if self.on_page:
                            self.on_page(channel_id, run_id, valid)
                        times = [parse_time(m.get('timestamp')) for m in valid]
                        if len(messages) < 100 or (cutoff and any(t and t < cutoff for t in times)):
                            break
                        before = oldest
                    else:
                        raise DiscordAPIError(0, '分页达到上限，保留已保存页并等待检查')
                    self.store.finish_run(run_id, True, cursor=newest, ended_at=self.clock())
                    details['status'] = 'success'
                except Exception as exc:
                    safe = str(exc) if isinstance(exc, DiscordAPIError) else '本轮保存中断，已保存的页面会保留'
                    self.store.finish_run(run_id, False, error=safe, ended_at=self.clock())
                    details.update(status='failed', error=safe)
                    summary['channels'].append(details)
                    if isinstance(exc, DiscordAPIError) and exc.status == 403:
                        # A channel permission change must not sacrifice the
                        # remaining readable channels during their retention
                        # window. This failed run still keeps its old cursor.
                        summary['permission_denied_channels'].append(channel_id)
                        summary['message_count'] += details['message_count']
                        summary['inserted'] += details['inserted']
                        continue
                    # Authentication and network errors propagate for the worker's
                    # attention/backoff state, while runs retain their diagnostics.
                    raise
                summary['channels'].append(details)
                summary['message_count'] += details['message_count']
                summary['inserted'] += details['inserted']
            if summary['permission_denied_channels']:
                if not any(channel['status'] == 'success' for channel in summary['channels']):
                    raise AccessDenied(403, '所有已配置频道均无读取权限，请核对频道设置')
                summary['status'] = 'partial'
                summary['warning'] = '以下频道无读取权限：' + '、'.join(summary['permission_denied_channels']) + '；其他频道已保存。'
            return summary
        finally:
            _capture_lock.release()
