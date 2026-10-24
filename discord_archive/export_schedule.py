"""Market-time automatic export slots with bounded restart catch-up."""
from __future__ import annotations

import copy
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .scheduler import as_utc, market_day


AUTO_EXPORT_DEFAULTS = {
    'enabled': False,
    'times': ['16:15'],
    'weekdays': [0, 1, 2, 3, 4],
    'render_scales': [1],
    'layout': 'horizontal',
    'presentation': 'reading',
    'target': 'main',
}
_CLOCK = re.compile(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z')


def normalize_auto_export(value=None):
    """Return independent defaults plus validated, canonical export settings."""
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError('自动导出设置须为对象')
    result = copy.deepcopy(AUTO_EXPORT_DEFAULTS)
    result.update(copy.deepcopy(value))
    if type(result['enabled']) is not bool:
        raise ValueError('自动导出开关须为布尔值')
    clocks = result['times']
    if (not isinstance(clocks, list) or not 1 <= len(clocks) <= 24
            or any(not isinstance(clock, str) or not _CLOCK.fullmatch(clock) for clock in clocks)):
        raise ValueError('自动导出时间须为 1 到 24 个 HH:MM 格式的时间')
    result['times'] = sorted(set(clocks))
    weekdays = result['weekdays']
    if (not isinstance(weekdays, list) or not weekdays
            or any(type(day) is not int or not 0 <= day <= 6 for day in weekdays)):
        raise ValueError('自动导出星期须为 0 到 6 的非空列表')
    result['weekdays'] = sorted(set(weekdays))
    scales = result['render_scales']
    if (not isinstance(scales, list) or not scales
            or any(type(scale) is not int or scale not in (1, 2) for scale in scales)):
        raise ValueError('自动导出清晰度须选择标准、HiDPI 或两者')
    result['render_scales'] = sorted(set(scales))
    if result['layout'] not in ('horizontal', 'stacked', 'collage', 'qa', 'board'):
        raise ValueError('自动导出版式无效')
    if result['presentation'] not in ('reading', 'full'):
        raise ValueError('自动导出内容须为阅读稿或完整稿')
    if result['target'] not in ('main', 'all'):
        raise ValueError('自动导出范围须为主图或全部图片')
    return result


def _utc(value):
    try:
        result = as_utc(value)
    except (ValueError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError('计划时间须包含有效时区') from exc
    if result is None:
        raise ValueError('计划时间不能为空')
    return result


def _zone(config):
    try:
        return ZoneInfo(config.get('market_timezone') or 'America/New_York')
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError('市场时区无效') from exc


def _slots(schedule, zone, start_date, end_date):
    day = start_date
    while day <= end_date:
        if day.weekday() in schedule['weekdays']:
            for clock in schedule['times']:
                hour, minute = map(int, clock.split(':'))
                local = datetime.combine(day, time(hour, minute)).replace(tzinfo=zone, fold=0)
                instant = local.astimezone(timezone.utc)
                roundtrip = instant.astimezone(zone)
                # A nonexistent wall time is shifted by UTC round-tripping.
                # Ambiguous times always select fold=0, once per local date.
                if roundtrip.replace(tzinfo=None) == local.replace(tzinfo=None) and roundtrip.fold == 0:
                    yield instant, day, clock
        day += timedelta(days=1)


def _slot_result(config, zone, instant, day, clock):
    boundary = config.get('day_boundary_hour', 4)
    if type(boundary) is not int or not 0 <= boundary <= 23:
        raise ValueError('交易日分界小时须为 0 到 23 的整数')
    return {
        'key': f'auto-export:{day.isoformat()}:{clock}',
        'scheduled_at': instant.isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'market_date': market_day(instant, zone.key, boundary),
    }


def latest_export_slot(config, now, not_before=None, after=None):
    """Return only the latest due slot within the preceding eight actual days.

    ``not_before`` includes its exact instant, while ``after`` excludes it.
    Callers persist ``scheduled_at`` as the completion/deduplication cursor.
    """
    schedule = normalize_auto_export(config.get('auto_export'))
    if not schedule['enabled']:
        return None
    now = _utc(now)
    earliest = now - timedelta(days=8)
    if not_before is not None:
        earliest = max(earliest, _utc(not_before))
    completed = _utc(after) if after is not None else None
    if earliest > now or (completed is not None and completed >= now):
        return None
    zone = _zone(config)
    candidates = [slot for slot in _slots(schedule, zone,
        earliest.astimezone(zone).date(), now.astimezone(zone).date())
        if earliest <= slot[0] <= now and (completed is None or slot[0] > completed)]
    if not candidates:
        return None
    return _slot_result(config, zone, *max(candidates, key=lambda slot: slot[0]))


def next_export_at(config, now):
    """Return the next UTC slot within eight days, including an exact ``now``."""
    schedule = normalize_auto_export(config.get('auto_export'))
    if not schedule['enabled']:
        return None
    now = _utc(now)
    zone = _zone(config)
    end = now + timedelta(days=8)
    candidates = [instant for instant, _, _ in _slots(schedule, zone,
        now.astimezone(zone).date(), end.astimezone(zone).date()) if now <= instant <= end]
    if not candidates:
        return None
    return min(candidates).isoformat(timespec='seconds').replace('+00:00', 'Z')
