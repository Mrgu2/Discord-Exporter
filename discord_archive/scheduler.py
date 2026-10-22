"""UTC persistence, IANA market schedules, independent browser display zones."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def as_utc(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('Timestamp must include a timezone')
    return value.astimezone(timezone.utc)


def market_day(now, market_timezone='America/New_York', boundary_hour=4):
    local = as_utc(now).astimezone(ZoneInfo(market_timezone))
    return (local - timedelta(hours=boundary_hour)).date().isoformat()


def day_bounds(date, market_timezone='America/New_York', boundary_hour=4):
    local = datetime.fromisoformat(date).replace(hour=boundary_hour, tzinfo=ZoneInfo(market_timezone))
    return local.astimezone(timezone.utc), (local + timedelta(days=1)).astimezone(timezone.utc)


def _minute(value):
    hour, minute = map(int, value.split(':'))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError('Invalid time')
    return hour * 60 + minute


def due(config, now_utc, last_capture_at=None, last_slot=None):
    schedule = config.get('schedule', {})
    if not schedule.get('enabled', False):
        return None
    now = as_utc(now_utc)
    local = now.astimezone(ZoneInfo(schedule.get('timezone') or config.get('market_timezone', 'America/New_York')))
    minute = local.hour * 60 + local.minute
    window = schedule.get('window', {})
    if window.get('enabled', False) and local.weekday() in window.get('weekdays', [0, 1, 2, 3, 4]):
        start, end = _minute(window.get('start', '15:50')), _minute(window.get('end', '16:10'))
        in_window = start <= minute <= end if end >= start else (minute >= start or minute <= end)
        step = max(1, int(window.get('every_minutes', 5)))
        if in_window:
            elapsed = (minute - start) % 1440
            slot_start = now - timedelta(minutes=elapsed % step, seconds=local.second, microseconds=local.microsecond)
            key = 'window:' + slot_start.isoformat()
            if key != last_slot and (not last_capture_at or as_utc(last_capture_at) < slot_start):
                return key
    for clock_time in schedule.get('times', []):
        if _minute(clock_time) == minute:
            key = f'fixed:{local.date()}:{clock_time}:{local.utcoffset()}'
            if key != last_slot and (not last_capture_at or (now - as_utc(last_capture_at)).total_seconds() > 60):
                return key
    interval = max(1, int(schedule.get('interval_minutes', 360)))
    if not last_capture_at or (now - as_utc(last_capture_at)).total_seconds() >= interval * 60:
        return 'interval:' + now.isoformat()
    return None
