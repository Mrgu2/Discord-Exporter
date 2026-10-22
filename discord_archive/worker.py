"""Persistent schedule, automatic retry, and serialized on-demand jobs."""
import json
import queue
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .collector import AccessDenied, AuthRequired, CaptureService, DiscordAPIError, DiscordClient
from .media import MediaArchive
from .scheduler import due, market_day
from .settings import atomic_json, message_location
from .store import parse_time, utc_now


class Worker:
    def __init__(self, store, root, settings, credentials, drafts):
        self.store, self.root, self.settings, self.credentials, self.drafts = store, Path(root), settings, credentials, drafts
        self.path = self.root / 'data' / 'worker-state.json'
        self.lock = threading.RLock()
        self.jobs, self.stop_event = queue.Queue(), threading.Event()
        previous = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.state = {
            'status': 'idle', 'active_job': None, 'last_success_at': previous.get('last_success_at'),
            'last_heartbeat': utc_now(), 'last_slot': previous.get('last_slot'),
            'offline_since': previous.get('offline_since'), 'last_online_at': previous.get('last_online_at'),
            'retry_at': previous.get('retry_at'), 'last_error': previous.get('last_error'),
            'rate_limit_until': previous.get('rate_limit_until'),
            'failures': previous.get('failures', 0), 'requires_attention': previous.get('requires_attention', False),
            'last_result': previous.get('last_result'), 'resumed_at': utc_now(),
            'browser_connected': previous.get('browser_connected', False), 'browser_account': previous.get('browser_account'),
            'permission_denied_channels': previous.get('permission_denied_channels', []), 'last_warning': previous.get('last_warning'),
        }
        self.media = MediaArchive(root)
        interrupted = self.store.recover_interrupted_runs('服务中断后自动恢复；上次成功位置保持不变')
        if interrupted or previous.get('active_job'):
            self.state.update(offline_since=previous.get('last_heartbeat') or utc_now(), retry_at=utc_now(), last_error='上次任务被中断，准备补采')
        elif previous.get('last_success_at') and not previous.get('requires_attention'):
            self.state['retry_at'] = utc_now()
        deadline = parse_time(self.state.get('rate_limit_until'))
        if deadline and deadline > datetime.now(timezone.utc):
            self.state['retry_at'] = deadline.isoformat()
        self._queued_capture = False
        self._last_schedule_slot = None

    def persist(self):
        with self.lock:
            self.state['last_heartbeat'] = utc_now()
            atomic_json(self.path, self.state)

    def start(self):
        self.thread = threading.Thread(target=self.loop, name='archive-worker', daemon=True)
        self.thread.start()

    def submit(self, kind, payload=None):
        with self.lock:
            if self.jobs.qsize() >= 20:
                raise ValueError('等待任务过多，请稍后重试')
            if kind == 'connect_browser' and ((self.state.get('active_job') or {}).get('type') == 'connect_browser' or any(job['type'] == 'connect_browser' for job in list(self.jobs.queue))):
                raise ValueError('已有登录窗口正在等待操作')
            if kind == 'capture':
                deadline = parse_time(self.state.get('rate_limit_until'))
                if deadline and deadline > datetime.now(timezone.utc):
                    raise ValueError('当前处于 Discord 限流等待期，稍后会自动补采')
                if self._queued_capture or (self.state.get('active_job') or {}).get('type') == 'capture':
                    raise ValueError('已有保存任务在进行或等待')
                self._queued_capture = True
            identifier = uuid.uuid4().hex
            self.jobs.put({'id': identifier, 'type': kind, 'payload': payload or {}})
            return {'id': identifier, 'status': 'queued', 'type': kind}

    def reset_attention(self):
        with self.lock:
            self.state.update(requires_attention=False, retry_at=utc_now(), failures=0, last_error=None)
            deadline = parse_time(self.state.get('rate_limit_until'))
            if deadline and deadline > datetime.now(timezone.utc):
                self.state['retry_at'] = deadline.isoformat()
            self._last_schedule_slot = None
            self.persist()

    def capture(self, payload):
        config = self.settings.read()
        token = self.credentials.get('discord')
        if not token:
            raise AuthRequired(401, '请先在本机设置页配置 Discord 凭证')
        channels = [row for row in config['channels'] if row.get('enabled', True)]
        if not channels:
            raise ValueError('请先设置需要保存的频道')
        client = DiscordClient(token)
        location = message_location(config.get('target_message_url', ''))
        if not config.get('target_author_id') and location:
            try:
                message = client.get(f'/channels/{location[1]}/messages/{location[2]}')
                config = self.settings.update({'target_author_id': str(message['author']['id'])})
                self.store.ensure_channel(location[1], guild_id=location[0])
            except DiscordAPIError as exc:
                if exc.status != 404:
                    raise
                # A deleted example must not stop saving messages still visible.
                self.state['target_resolution_warning'] = '示例消息已删除，请从仍可见的群主发言填写作者 ID'
        snapshot_dir = self.root / 'data' / 'snapshots'
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        def archive_page(channel_id, run_id, messages):
            with open(snapshot_dir / f'{run_id}-{channel_id}.ndjson', 'a') as handle:
                for message in messages:
                    handle.write(json.dumps(message, ensure_ascii=False) + '\n')
                handle.flush()
            self.media.archive_page(channel_id, run_id, messages, download=config.get('download_media', True))
        result = CaptureService(self.store, client, channels, on_page=archive_page).capture(payload.get('trigger', 'manual'))
        with self.lock:
            self.state.update(last_success_at=utc_now(), last_online_at=utc_now(), offline_since=None, retry_at=None, rate_limit_until=None, failures=0, requires_attention=False, last_error=None)
            self.state.update(permission_denied_channels=result.get('permission_denied_channels', []), last_warning=result.get('warning'))
        return result

    def loop(self):
        next_schedule_check = 0
        while not self.stop_event.is_set():
            now = datetime.now(timezone.utc)
            if time.monotonic() >= next_schedule_check:
                next_schedule_check = time.monotonic() + 10
                try:
                    config = self.settings.read()
                    if self.credentials.get('discord') and any(row.get('enabled', True) for row in config.get('channels', [])) and not self.state.get('requires_attention'):
                        retry = parse_time(self.state.get('retry_at'))
                        slot = due(config, now, self.state.get('last_success_at'), self.state.get('last_slot'))
                        ready_retry = retry and now >= retry
                        allowed_schedule = slot and (not retry or now >= retry)
                        if (ready_retry or allowed_schedule) and not self._queued_capture and not self.state.get('active_job'):
                            self.submit('capture', {'trigger': 'reconnect' if ready_retry else 'scheduled', 'slot': slot})
                    self.persist()
                except Exception:
                    with self.lock:
                        self.state['last_error'] = '自动计划检查失败，请检查设置'
            try:
                job = self.jobs.get(timeout=1)
            except queue.Empty:
                continue
            with self.lock:
                self.state.update(status='running', active_job={'type': job['type'], 'id': job['id'], 'message': {'capture': '正在保存频道与回复上下文', 'draft': '正在生成稿件', 'render': '正在生成长图', 'import': '正在导入存档', 'connect_browser': '请在新打开的 Discord 窗口中登录'}.get(job['type'], '处理中')})
                self.persist()
            try:
                if job['type'] == 'capture':
                    result = self.capture(job['payload'])
                    self.state['last_slot'] = job['payload'].get('slot') or self.state.get('last_slot')
                elif job['type'] == 'draft':
                    result = self.drafts.generate(job['payload'])
                elif job['type'] == 'render':
                    result = self.drafts.render(job['payload']['draft_id'])
                elif job['type'] == 'import':
                    result = self.store.import_dce(job['payload']['path'])
                elif job['type'] == 'connect_browser':
                    from .browser_login import BrowserLogin
                    result = BrowserLogin(self.root, self.credentials).connect()
                    if result.get('status') != 'connected':
                        raise ValueError(result.get('message', '连接尚未完成'))
                    self.state.update(browser_connected=True, browser_account={key: result.get(key) for key in ('name', 'id', 'credential_backend')})
                    self.reset_attention()
                else:
                    raise ValueError('未知任务')
                with self.lock:
                    partial = job['type'] == 'capture' and result.get('status') == 'partial'
                    self.state.update(last_result=result, last_job_status='partial' if partial else 'success', last_job_error=None)
            except Exception as exc:
                with self.lock:
                    safe = str(exc) if isinstance(exc, (DiscordAPIError, ValueError, RuntimeError)) else '任务未完成，请查看本机日志或配置'
                    self.state.update(last_job_status='failed', last_job_error=safe)
                    if job['type'] == 'capture':
                        failures = self.state.get('failures', 0) + 1
                        if isinstance(exc, (AuthRequired, AccessDenied)):
                            self.state.update(requires_attention=True, retry_at=None)
                            if isinstance(exc, AuthRequired):
                                self.state['browser_connected'] = False
                        else:
                            delay = max(min(30 * 2 ** min(failures - 1, 6), 1800), getattr(exc, 'retry_after', 0) or 0)
                            self.state['retry_at'] = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
                            if isinstance(exc, DiscordAPIError) and exc.status == 429:
                                self.state['rate_limit_until'] = self.state['retry_at']
                        self.state.update(failures=failures, last_error=safe, offline_since=self.state.get('offline_since') or utc_now())
            finally:
                with self.lock:
                    self.state.update(active_job=None, status='idle')
                    if job['type'] == 'capture':
                        self._queued_capture = False
                    self.persist()
                self.jobs.task_done()

    def status(self):
        with self.lock:
            state = json.loads(json.dumps(self.state))
        now = datetime.now(timezone.utc)
        offline = parse_time(state.get('offline_since'))
        state['queue_length'] = self.jobs.qsize()
        config = self.settings.read()
        state['market_day'] = market_day(now, config['market_timezone'], config.get('day_boundary_hour', 4))
        # Search the next day's minute slots in UTC, including DST transitions.
        next_time = None
        for offset in range(0, 24 * 60 + 1):
            candidate = now + timedelta(minutes=offset)
            if due(config, candidate, state.get('last_success_at'), state.get('last_slot')):
                next_time = candidate.isoformat()
                break
        state['next_capture_at'] = state.get('retry_at') or next_time
        connectivity = {'online': None if not state.get('last_success_at') and not offline else not bool(offline), 'offline_since': state.get('offline_since'), 'last_online_at': state.get('last_online_at'), 'retry_at': state.get('retry_at'), 'gap_hours': round((now - offline).total_seconds() / 3600, 2) if offline else 0, 'last_error': state.get('last_error'), 'requires_attention': state.get('requires_attention')}
        return state, connectivity
