"""Stable, trading-day export names without changing renderer cache receipts."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import unicodedata
import uuid
import zlib
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .scheduler import market_day
from .store import parse_time


PREFIX = '答疑存档'
_DAY = re.compile(r'\d{4}-\d{2}-\d{2}\Z')
_PNG = b'\x89PNG\r\n\x1a\n'


def _day(value):
    if not isinstance(value,str) or not _DAY.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _label(start, end=None):
    start = _day(start)
    end = _day(end) if end is not None else start
    if not start or not end or end < start:
        return None
    return start if start == end else f'{start}至{end}'


def _saved_label(value):
    if isinstance(value,str):
        parts = value.split('至')
        if len(parts) in (1,2):
            return _label(parts[0],parts[-1])
    return None


def export_date_label(metadata, *, seeds=None, config=None, evidence=None):
    """Use the selected content's trading dates, never the download/current day."""
    config = config or {}
    evidence = evidence or {}
    selection = metadata.get('selection') or evidence.get('selection') or {}
    chosen = _label(selection.get('start'),selection.get('end'))
    if chosen:
        return chosen
    for value in (metadata.get('export_date'),metadata.get('date')):
        chosen = _saved_label(value)
        if chosen:
            return chosen

    zone = metadata.get('market_timezone') or config.get('market_timezone') or 'America/New_York'
    try:
        ZoneInfo(zone)
    except (TypeError,ValueError,ZoneInfoNotFoundError):
        zone = 'America/New_York'
    try:
        boundary = int(metadata.get('day_boundary_hour',config.get('day_boundary_hour',4)))
        if not 0 <= boundary <= 23:
            boundary = 4
    except (ValueError,TypeError):
        boundary = 4

    def trading_date(value):
        try:
            moment = parse_time(value)
            return market_day(moment,zone,boundary) if moment is not None else None
        except (ValueError,TypeError,OverflowError,OSError):
            return None

    sources = [seeds] if seeds is not None else []
    sources.append([item.get('seed') for item in evidence.get('contexts',[]) if isinstance(item,dict)])
    for source in sources:
        days = sorted({result for item in source or [] if isinstance(item,dict)
            if (result := trading_date(item.get('created_at'))) is not None})
        if days:
            return _label(days[0],days[-1])
    return trading_date(metadata.get('created_at')) or '未标日期'


def _channel_title(value):
    value = unicodedata.normalize('NFC',str(value))
    value = ''.join(character for character in value if not unicodedata.category(character).startswith('C'))
    value = re.sub(r'[/\\:<>"|?*]+','-',value)
    value = re.sub(r'\s+',' ',value).strip(' .-_')
    return value[:40].rstrip(' .-_') or '分栏'


def filename(metadata, sequence, *, render_scale=1, channel_title=None):
    if type(sequence) is not int or not 1 <= sequence <= 999999:
        raise ValueError('图片序号须为 1 到 999999 的整数')
    if type(render_scale) is not int or render_scale not in (1,2):
        raise ValueError('导出清晰度须为标准 1× 或 HiDPI 2×')
    pieces = [PREFIX,export_date_label(metadata)]
    if render_scale == 2:
        pieces.append('HiDPI')
    if channel_title is not None:
        pieces.append(_channel_title(channel_title))
    pieces.append(f'{sequence:02d}')
    return '-'.join(pieces)+'.png'


def _validate_png(path):
    with path.open('rb') as source:
        header = source.read(33)
    if (len(header) != 33 or header[:8] != _PNG or header[8:12] != b'\x00\x00\x00\r'
            or header[12:16] != b'IHDR' or not int.from_bytes(header[16:20],'big')
            or not int.from_bytes(header[20:24],'big')
            or zlib.crc32(header[12:29]) & 0xffffffff != int.from_bytes(header[29:33],'big')):
        raise ValueError('源文件不是有效的 PNG 图片')


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):
            digest.update(block)
    return digest.digest()


def publish_image(source, metadata, sequence, *, render_scale=1, channel_title=None):
    """Publish a byte-identical alias; retain sources and back up replaced names."""
    source = Path(source)
    _validate_png(source)  # A missing source raises; never manufacture an image.
    target = source.parent/filename(metadata,sequence,render_scale=render_scale,channel_title=channel_title)
    if target.exists():
        if source.samefile(target):
            return target
        if target.is_file() and not target.is_symlink() and source.stat().st_size == target.stat().st_size and _hash(source) == _hash(target):
            return target
    if target.exists() or target.is_symlink():
        if target.is_dir() and not target.is_symlink():
            raise IsADirectoryError(str(target))
        backup = source.parent/'export-name-backups'/uuid.uuid4().hex/target.name
        backup.parent.mkdir(parents=True,exist_ok=False)
        if target.is_symlink():
            backup.symlink_to(os.readlink(target))
        else:
            shutil.copy2(target,backup)
    temporary = source.parent/f'.export-name-{uuid.uuid4().hex}.tmp'
    try:
        try:
            os.link(source,temporary)
        except OSError:
            with source.open('rb') as original, temporary.open('xb') as destination:
                shutil.copyfileobj(original,destination,1024*1024)
            shutil.copystat(source,temporary)
        os.replace(temporary,target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
