"""Restartable automatic capture, manuscript, rendering and verified copies."""
from __future__ import annotations

import copy
import json
import threading
from datetime import date, timedelta
from pathlib import Path

from .collector import AccessDenied, DiscordAPIError
from .export_schedule import latest_export_slot, next_export_at, normalize_auto_export
from .settings import atomic_json
from .store import iso_time, parse_time, utc_now


class ScheduledExporter:
    def __init__(self, root):
        self.path = Path(root)/'data/auto-export-state.json'
        self.lock = threading.RLock()
        saved = json.loads(self.path.read_text()) if self.path.exists() else {}
        if not isinstance(saved,dict):
            raise ValueError('自动导出状态文件须为对象')
        self.state = {'enabled_since':None,'enabled':False,'last_completed_slot_at':None,
            'last_completed_at':None,'last_draft_id':None,'last_status':'idle','last_error':None,
            'retry_at':None,'failures':0,'pending':None,**saved}

    def _save(self, **changes):
        with self.lock:
            candidate = {**self.state,**copy.deepcopy(changes)}
            atomic_json(self.path,candidate)
            self.state = candidate

    @property
    def stage(self):
        with self.lock:
            return (self.state.get('pending') or {}).get('stage')

    def due(self, config, now):
        options = normalize_auto_export(config.get('auto_export'))
        now = parse_time(now)
        if now is None:
            raise ValueError('自动导出检查时间不能为空')
        with self.lock:
            if not options['enabled']:
                if self.state['enabled']:
                    self._save(enabled=False)
                return None
            if not self.state['enabled'] or not self.state.get('enabled_since'):
                self._save(enabled=True,enabled_since=iso_time(now.replace(second=0,microsecond=0)),
                    pending=None,retry_at=None,failures=0,last_error=None)
            slot = latest_export_slot(config,now,not_before=self.state['enabled_since'],
                after=self.state.get('last_completed_slot_at'))
            pending = self.state.get('pending') or {}
            retry = parse_time(self.state.get('retry_at'))
            if slot is None:
                # Capture catch-up is bounded, but already-saved manuscripts
                # must still finish after a weekend or an unavailable drive.
                if pending.get('stage') in ('draft','render') and (retry is None or now >= retry):
                    return copy.deepcopy(pending['slot'])
                return None
            previous = parse_time((pending.get('slot') or {}).get('scheduled_at'))
            newer = previous is not None and parse_time(slot['scheduled_at']) > previous
            if retry is not None and now < retry and not newer:
                return None
            return copy.deepcopy(slot)

    @staticmethod
    def _slot(slot):
        if not isinstance(slot,dict) or not slot.get('key') or parse_time(slot.get('scheduled_at')) is None:
            raise ValueError('自动导出时刻无效')
        try:
            date.fromisoformat(slot['market_date'])
        except (ValueError,TypeError,KeyError) as exc:
            raise ValueError('自动导出交易日无效') from exc
        return copy.deepcopy(slot)

    def _complete(self, slot, status, draft_id=None):
        self._save(last_completed_slot_at=slot['scheduled_at'],last_completed_at=utc_now(),
            last_draft_id=draft_id or self.state.get('last_draft_id'),last_status=status,
            last_error=None,retry_at=None,failures=0,pending=None)

    @staticmethod
    def _safe_error(exc, config):
        text = str(exc) if isinstance(exc,(ValueError,RuntimeError,DiscordAPIError)) else '自动导出未完成，请检查连接或本机导出设置'
        directory = (config.get('export') or {}).get('copy_directory')
        if isinstance(directory,str) and directory:
            try:
                paths = {directory,str(Path(directory).expanduser()),str(Path(directory).expanduser().resolve())}
            except (OSError,ValueError,RuntimeError):
                paths = {directory}
            for path in sorted(paths,key=len,reverse=True):
                text = text.replace(path,'导出目录')
        return text[:500]

    def run(self, worker, slot):
        from .editorial import EmptyDraft
        slot = self._slot(slot)
        config = worker.settings.read()
        options = normalize_auto_export(config.get('auto_export'))
        if not options['enabled']:
            self._save(enabled=False)
            return {'status':'disabled','slot':slot,'deduplicated':True}
        with self.lock:
            saved_state = copy.deepcopy(self.state)
        completed = parse_time(saved_state.get('last_completed_slot_at'))
        if completed is not None and parse_time(slot['scheduled_at']) <= completed:
            return {'status':saved_state.get('last_status'),'slot':slot,'deduplicated':True,'draft_id':saved_state.get('last_draft_id')}
        pending = saved_state.get('pending')
        if not pending or pending['slot']['scheduled_at'] != slot['scheduled_at']:
            pending = {'slot':slot,'options':options,'stage':'capture','draft_id':None,'rendered_scales':[]}
            self._save(pending=pending,failures=0)
        else:
            options = pending['options']
        self._save(last_status='running',last_error=None,retry_at=None)
        result = None
        try:
            if pending['stage'] in ('capture','capture_partial'):
                pending['stage'] = 'capture'
                self._save(pending=pending)
                capture = worker.capture({'trigger':'scheduled_export'})
                if capture.get('status') == 'partial':
                    # Local permission gaps pause this workflow, not the
                    # independent archive collector's network/attention state.
                    pending['stage'] = 'capture_partial'
                    raise AccessDenied(403,'部分频道无法读取，本次自动出稿已暂停；已保存原文仍保留')
                if capture.get('status') != 'success':
                    raise ValueError('本轮保存未完整成功，未生成自动稿件')
                pending['stage'] = 'draft'
                self._save(pending=pending)
            if pending['stage'] == 'draft':
                clock = str(slot['key']).rsplit(':',2)[-2:]
                clock = ':'.join(clock)
                draft = worker.drafts.generate({'scope':'day','date':slot['market_date'],'mode':'evidence',
                    'layout':options['layout'],'presentation':options['presentation'],
                    'title':f'{slot["market_date"]} 定时 {clock}'})
                if not isinstance(draft,dict) or not draft.get('id'):
                    raise ValueError('自动稿件未返回可用编号')
                pending.update(draft_id=draft['id'],stage='render')
                self._save(pending=pending,last_draft_id=draft['id'])
            for scale in options['render_scales']:
                if scale in pending['rendered_scales']:
                    continue
                result = worker.drafts.render(pending['draft_id'],target=options['target'],render_scale=scale)
                if any(row.get('enabled') for row in config.get('delivery', {}).values()):
                    worker.delivery.enqueue_render(result, draft_id=pending['draft_id'], scale=scale, target=options['target'])
                copied = (result.get('draft') or {}).get('export_copy') or {}
                needs_copy = bool((config.get('export') or {}).get('copy_directory'))
                if needs_copy and (not copied.get('enabled') or copied.get('failed',0) != 0 or copied.get('copied',0) <= 0):
                    raise ValueError('自动导出图片未全部另存成功，请检查导出目录后重试')
                pending['rendered_scales'].append(scale)
                self._save(pending=pending)
            draft_id = pending['draft_id']
            self._complete(slot,'success',draft_id)
            return {**(result or {}),'status':'success','slot':slot,'draft_id':draft_id}
        except Exception as exc:
            if isinstance(exc,EmptyDraft) and pending['stage'] == 'draft':
                self._complete(slot,'skipped')
                return {'status':'skipped','slot':slot,'reason':'所选交易日没有可导出的目标发言'}
            with self.lock:
                failures = self.state.get('failures',0)+1
            delay = min(30*2**min(failures-1,6),1800)
            self._save(last_status='failed',last_error=self._safe_error(exc,config),failures=failures,
                retry_at=iso_time(parse_time(utc_now())+timedelta(seconds=delay)),pending=pending)
            raise

    def summary(self, config, now):
        options = normalize_auto_export(config.get('auto_export'))
        with self.lock:
            return {'enabled':options['enabled'],'next_at':next_export_at(config,now),
                'last_status':self.state.get('last_status'),'last_error':self.state.get('last_error'),
                'retry_at':self.state.get('retry_at') if options['enabled'] else None,
                'last_completed_at':self.state.get('last_completed_at'),
                'last_draft_id':self.state.get('last_draft_id'),'stage':self.stage}
