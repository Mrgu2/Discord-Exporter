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
from .speech import SpeechArchive
from .scheduler import due, market_day
from .settings import atomic_json, message_location
from .store import parse_time, utc_now
from .auto_export import ScheduledExporter
from .delivery import DeliveryOutbox


class Worker:
    def __init__(self, store, root, settings, credentials, drafts):
        self.store, self.root, self.settings, self.credentials, self.drafts = store, Path(root), settings, credentials, drafts
        self.path = self.root / 'data' / 'worker-state.json'
        self.lock = threading.RLock()
        self.jobs, self.stop_event = queue.Queue(), threading.Event()
        previous = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.state = {
            'automatic_paused': previous.get('automatic_paused', False),
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
        self.speech = SpeechArchive(root,self.settings.read().get('speech'))
        if self.drafts is not None:
            self.drafts.media = self.media
            self.drafts.speech = self.speech
        interrupted = self.store.recover_interrupted_runs('服务中断后自动恢复；上次成功位置保持不变')
        if interrupted or previous.get('active_job'):
            self.state.update(offline_since=previous.get('last_heartbeat') or utc_now(), retry_at=utc_now(), last_error='上次任务被中断，准备补采')
        elif previous.get('last_success_at') and not previous.get('requires_attention'):
            self.state['retry_at'] = utc_now()
        deadline = parse_time(self.state.get('rate_limit_until'))
        if deadline and deadline > datetime.now(timezone.utc):
            self.state['retry_at'] = deadline.isoformat()
        self.draining = False
        self._queued_capture = False
        self._queued_auto_export = False
        self.auto_export = ScheduledExporter(root)
        self.delivery = DeliveryOutbox(root, settings, credentials, self.stop_event)
        self._queued_delivery = False
        self._render_jobs = {}
        self._last_schedule_slot = None
        self.configure_auto_export(self.settings.read())

    def configure_auto_export(self, config):
        # Activation must be durable even while the serialized worker is busy
        # capturing. This only records schedule state; it does not run a job.
        self.auto_export.due(config,datetime.now(timezone.utc))

    def persist(self):
        with self.lock:
            self.state['last_heartbeat'] = utc_now()
            atomic_json(self.path, self.state)

    def start(self):
        if self.delivery.clawbot.account:
            self.delivery.clawbot.start()
        self.thread = threading.Thread(target=self.loop, name='archive-worker', daemon=True)
        self.thread.start()

    def set_automatic_paused(self, paused):
        if type(paused) is not bool:
            raise ValueError('暂停状态须为布尔值')
        with self.lock:
            if self.draining:
                raise ValueError('服务正在重启或停止，请稍后操作')
            previous = self.state.get('automatic_paused', False)
            self.state['automatic_paused'] = paused
            try:
                self.persist()
            except Exception:
                self.state['automatic_paused'] = previous
                raise
        return {'automatic_paused': paused}

    @staticmethod
    def automatic_job(job):
        if job['type'] == 'delivery':
            return not job['payload'].get('manual', False)
        return job['type'] == 'auto_export' or (job['type'] == 'capture' and
            job['payload'].get('trigger') in {'scheduled', 'reconnect'})

    def submit(self, kind, payload=None):
        with self.lock:
            if self.draining:
                raise ValueError('服务正在重启或停止，请稍后操作')
            if self.state.get('automatic_paused') and self.automatic_job({'type': kind, 'payload': payload or {}}):
                raise ValueError('自动任务已暂停')
            if kind == 'delivery' and self._queued_delivery:
                raise ValueError('已有发送任务在进行或等待')
            if kind == 'auto_export' and self._queued_auto_export:
                raise ValueError('已有定时出稿任务在进行或等待')
            if kind == 'render':
                payload = {**(payload or {})}
                payload.setdefault('target','main')
                payload.setdefault('render_scale',1)
                if type(payload['render_scale']) is not int or payload['render_scale'] not in (1,2):
                    raise ValueError('导出清晰度须为标准 1× 或 HiDPI 2×')
                if payload['target'] not in {'main','mobile','all'}:
                    raise ValueError('图片类型须为 main、mobile 或 all')
                active = self.state.get('active_job') or {}
                for (draft,target,scale),identifier in self._render_jobs.items():
                    if draft == payload.get('draft_id') and target in {payload['target'],'all'} and scale == payload['render_scale']:
                        return {'id':identifier,'status':'running' if active.get('id') == identifier else 'queued','type':'render','deduplicated':True}
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
            if kind == 'render':
                self._render_jobs[(payload.get('draft_id'),payload['target'],payload['render_scale'])] = identifier
            if kind == 'auto_export':
                self._queued_auto_export = True
            if kind == 'delivery':
                self._queued_delivery = True
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
        self.state['target_resolution_warning'] = None
        if not config.get('target_author_id') and location:
            try:
                # The single-message endpoint rejects ordinary member accounts
                # (Discord code 20002). Locate the exact example through the
                # same history endpoint used for the user's visible messages.
                messages = client.get(f'/channels/{location[1]}/messages', {'around': location[2], 'limit': 1})
                if not isinstance(messages, list):
                    raise DiscordAPIError(0, '示例消息响应异常，未更改答疑人')
                message = next((row for row in messages if isinstance(row, dict) and str(row.get('id')) == location[2]), None)
                author_id = str((message.get('author') or {}).get('id', '')) if message else ''
                if author_id.isdigit():
                    config = self.settings.update({'target_author_id': author_id})
                    self.store.ensure_channel(location[1], guild_id=location[0])
                else:
                    self.state['target_resolution_warning'] = '未找到示例消息，请更新群主的一条发言链接；当前仍会保存频道内容。'
            except DiscordAPIError as exc:
                if exc.status not in (403, 404):
                    raise
                # A deleted example must not stop saving messages still visible.
                self.state['target_resolution_warning'] = '示例消息当前无法读取，请更新群主的一条发言链接；其他可读频道仍会保存。'
        snapshot_dir = self.root / 'data' / 'snapshots'
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        page_counts = {}
        channel_labels = {row['id']: row.get('label') or '频道' for row in channels}
        def archive_page(channel_id, run_id, messages):
            page_counts[channel_id] = page_counts.get(channel_id, 0) + len(messages)
            with self.lock:
                active = self.state.get('active_job')
                if active and active.get('type') == 'capture':
                    active['message'] = f'正在保存{channel_labels.get(channel_id, "频道")} · 已读取 {page_counts[channel_id]} 条，正在保存附件'
                self.persist()
            with open(snapshot_dir / f'{run_id}-{channel_id}.ndjson', 'a') as handle:
                for message in messages:
                    handle.write(json.dumps(message, ensure_ascii=False) + '\n')
                handle.flush()
            self.media.archive_page(channel_id, run_id, messages, download=config.get('download_media', True))
        result = CaptureService(self.store, client, channels, on_page=archive_page).capture(payload.get('trigger', 'manual'))
        with self.lock:
            self.state.update(last_success_at=utc_now(), last_online_at=utc_now(), offline_since=None, retry_at=None, rate_limit_until=None, failures=0, requires_attention=False, last_error=None)
            warnings = [value for value in (self.state.get('target_resolution_warning'), result.get('warning')) if value]
            self.state.update(permission_denied_channels=result.get('permission_denied_channels', []), last_warning=' '.join(warnings) or None)
        def speech_progress(message):
            with self.lock:
                if self.state.get('active_job'):
                    self.state['active_job']['message'] = message
                self.persist()
        # All network pages and attachments are durable before any inference.
        # An ASR failure never turns a successful capture into a network retry.
        self.speech.options = config.get('speech') or {}
        try:
            result['audio'] = self.speech.process_saved(self.media,progress=speech_progress)
        except Exception:
            result['audio'] = {'failed':True,'error':'语音转写未完成，已保存的消息和音频不受影响；重新出稿会重试'}
        return result

    def loop(self):
        next_schedule_check = 0
        while not self.stop_event.is_set():
            now = datetime.now(timezone.utc)
            if time.monotonic() >= next_schedule_check:
                next_schedule_check = time.monotonic() + 10
                try:
                    with self.lock:
                        if not self.draining:
                            paused = bool(self.state.get('automatic_paused'))
                            # Tests and explicit retries are user actions, like
                            # manual captures, and must work while automation is paused.
                            delivery_id = self.delivery.due(now, manual_only=paused)
                            if delivery_id and not self._queued_delivery and not self.state.get('active_job'):
                                self.submit('delivery', {'id': delivery_id, 'manual': self.delivery.is_manual(delivery_id)})
                            if not paused:
                                config = self.settings.read()
                                export_slot = self.auto_export.due(config,now)
                                if self.credentials.get('discord') and any(row.get('enabled', True) for row in config.get('channels', [])) and not self.state.get('requires_attention'):
                                    retry = parse_time(self.state.get('retry_at'))
                                    slot = due(config, now, self.state.get('last_success_at'), self.state.get('last_slot'))
                                    ready_retry = retry and now >= retry
                                    allowed_schedule = slot and (not retry or now >= retry)
                                    if not self._queued_capture and not self._queued_auto_export and not self.state.get('active_job'):
                                        if export_slot and (not retry or now >= retry):
                                            self.submit('auto_export',{'slot':export_slot})
                                        elif ready_retry or allowed_schedule:
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
                if self.state.get('automatic_paused') and self.automatic_job(job):
                    if job['type'] == 'capture':
                        self._queued_capture = False
                    elif job['type'] == 'delivery':
                        self._queued_delivery = False
                    else:
                        self._queued_auto_export = False
                    self.jobs.task_done()
                    continue
                self.state.update(status='running', active_job={'type': job['type'], 'id': job['id'],
                    **({key:job['payload'].get(key) for key in ('draft_id','target','render_scale')} if job['type'] == 'render' else {}),
                    'message': {'delivery': '正在发送图片', 'capture': '正在保存频道与回复上下文', 'auto_export': '正在保存并导出交易日稿件', 'draft': '正在生成稿件', 'render': '正在生成分栏图' if job['payload'].get('target') == 'mobile' else '正在生成高清主图', 'import': '正在导入存档', 'connect_browser': '请在新打开的 Discord 窗口中登录'}.get(job['type'], '处理中')})
                self.persist()
            try:
                if job['type'] == 'capture':
                    result = self.capture(job['payload'])
                    self.state['last_slot'] = job['payload'].get('slot') or self.state.get('last_slot')
                elif job['type'] == 'auto_export':
                    result = self.auto_export.run(self,job['payload']['slot'])
                elif job['type'] == 'delivery':
                    result = self.delivery.send(job['payload']['id'])
                elif job['type'] == 'draft':
                    result = self.drafts.generate(job['payload'])
                elif job['type'] == 'render':
                    result = self.drafts.render(job['payload']['draft_id'],target=job['payload'].get('target','main'),force=job['payload'].get('force',False),render_scale=job['payload'].get('render_scale',1))
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
                    self.state.update(last_result=result, last_job_id=job['id'], last_job_status='partial' if partial else 'success', last_job_error=None)
            except Exception as exc:
                with self.lock:
                    safe = str(exc) if isinstance(exc, (DiscordAPIError, ValueError, RuntimeError)) else '任务未完成，请查看本机日志或配置'
                    self.state.update(last_job_id=job['id'], last_job_status='failed', last_job_error=safe)
                    if job['type'] == 'capture' or (job['type'] == 'auto_export' and self.auto_export.stage == 'capture'):
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
                    if job['type'] == 'auto_export':
                        self._queued_auto_export = False
                    if job['type'] == 'delivery':
                        self._queued_delivery = False
                    if job['type'] == 'render':
                        self._render_jobs.pop((job['payload'].get('draft_id'),job['payload'].get('target','main'),job['payload'].get('render_scale',1)),None)
                    self.persist()
                self.jobs.task_done()

    def status(self):
        with self.lock:
            state = json.loads(json.dumps(self.state))
        now = datetime.now(timezone.utc)
        offline = parse_time(state.get('offline_since'))
        state['queue_length'] = self.jobs.qsize()
        with self.jobs.mutex:
            queued = list(self.jobs.queue)
        state['render_jobs'] = [{key:job.get(key) for key in ('id','type','draft_id','target','render_scale')}
            for job in [state.get('active_job') or {}, *[{**job,**job['payload']} for job in queued]] if job.get('type') == 'render']
        config = self.settings.read()
        state['auto_export'] = self.auto_export.summary(config,now)
        state['delivery'] = self.delivery.summary()
        state['clawbot'] = self.delivery.clawbot.status()
        state['market_day'] = market_day(now, config['market_timezone'], config.get('day_boundary_hour', 4))
        # Search the next day's minute slots in UTC, including DST transitions.
        next_time = None
        for offset in range(0, 24 * 60 + 1):
            candidate = now + timedelta(minutes=offset)
            if due(config, candidate, state.get('last_success_at'), state.get('last_slot')):
                next_time = candidate.isoformat()
                break
        state['next_capture_at'] = None if state.get('automatic_paused') else state.get('retry_at') or next_time
        if state.get('automatic_paused'):
            state['auto_export']['next_at'] = None
        connectivity = {'online': None if not state.get('last_success_at') and not offline else not bool(offline), 'offline_since': state.get('offline_since'), 'last_online_at': state.get('last_online_at'), 'retry_at': state.get('retry_at'), 'gap_hours': round((now - offline).total_seconds() / 3600, 2) if offline else 0, 'last_error': state.get('last_error'), 'requires_attention': state.get('requires_attention')}
        return state, connectivity
