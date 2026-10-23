"""Media actually present in a message, including Discord forwarding snapshots."""
from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

CDN_HOSTS = {'cdn.discordapp.com', 'media.discordapp.net', 'cdn.discordapp.net',
             'images-ext-1.discordapp.net', 'images-ext-2.discordapp.net'}
RASTER_TYPES = {'image/png', 'image/apng', 'image/jpeg', 'image/gif', 'image/webp', 'image/avif', 'image/bmp'}
RASTER_SUFFIXES = {'.png', '.apng', '.jpg', '.jpeg', '.gif', '.webp', '.avif', '.bmp'}
AUDIO_SUFFIXES = {'.ogg', '.opus', '.mp3', '.wav', '.m4a', '.aac', '.flac', '.webm'}


def is_audio_asset(asset):
    kind = str(asset.get('content_type') or '').lower().split(';')[0]
    return kind.startswith('audio/') or (not kind.startswith(('image/', 'video/'))
        and PurePosixPath(asset.get('filename') or asset.get('file') or '').suffix.lower() in AUDIO_SUFFIXES)


def allowed_media_url(value):
    try:
        parts = urlsplit(value)
        return parts.scheme == 'https' and parts.hostname in CDN_HOSTS and parts.port in (None, 443) and not parts.username and not parts.password
    except (ValueError, TypeError):
        return False


def _stable_url(value):
    parts = urlsplit(value)
    query = urlencode([(key, item) for key, item in parse_qsl(parts.query, keep_blank_values=True) if key not in {'ex', 'is', 'hm'}])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ''))


def forwarded_texts(message):
    raw = message.get('raw') if isinstance(message.get('raw'), dict) else message
    result, seen = [], set()
    def visit(current, depth=0):
        if depth > 5:
            return
        for snapshot in current.get('message_snapshots') or []:
            inner = snapshot.get('message') if isinstance(snapshot, dict) else None
            if not isinstance(inner, dict):
                continue
            text = str(inner.get('content') or '').strip()
            if text and text not in seen:
                result.append(text); seen.add(text)
            visit(inner, depth+1)
    visit(raw)
    return result


def iter_message_assets(message):
    raw = message.get('raw') if isinstance(message.get('raw'), dict) else message
    assets, seen = [], set()
    def add(asset, identity, kind, label):
        urls = [asset.get('url'), asset.get('proxy_url'), asset.get('proxyUrl')]
        url = next((value for value in urls if isinstance(value, str) and allowed_media_url(value)), None)
        source_url = next((value for value in urls if isinstance(value, str)), '')
        canonical = _stable_url(url) if url else source_url
        if canonical and canonical in seen:
            return
        seen.add(canonical)
        filename = asset.get('filename') or asset.get('fileName') or PurePosixPath(urlsplit(source_url).path).name or 'image.png'
        content_type = str(asset.get('content_type') or asset.get('contentType') or '').lower().split(';')[0]
        is_image = content_type in RASTER_TYPES or PurePosixPath(filename).suffix.lower() in RASTER_SUFFIXES
        if kind in {'embed', 'sticker'} and not content_type:
            is_image = True
        if content_type == 'image/svg+xml' or PurePosixPath(filename).suffix.lower() in {'.svg', '.json'}:
            is_image = False
        assets.append({**asset, 'id': str(identity), 'filename': filename, 'url': source_url,
                       'download_url': url or '', 'content_type': content_type,
                       'is_image': is_image, 'is_audio': is_audio_asset({'content_type':content_type,'filename':filename}),
                       'source_type': kind, 'source_label': label})
    def visit(current, prefix='', depth=0):
        if depth > 5:
            return
        for index, attachment in enumerate(current.get('attachments') or []):
            if isinstance(attachment, dict):
                identity = attachment.get('id') or attachment.get('filename') or f'asset-{index}'
                add(attachment, prefix+str(identity), 'attachment', '转发图片' if prefix else '原图')
        for index, embed in enumerate(current.get('embeds') or []):
            if not isinstance(embed, dict):
                continue
            image = embed.get('image') or embed.get('thumbnail')
            if isinstance(image, dict):
                candidate = image.get('proxy_url') or image.get('url') or ''
                digest = hashlib.sha256(_stable_url(candidate).encode()).hexdigest()[:16] if candidate else str(index)
                add(image, f'{prefix}embed-{index}-{digest}', 'embed', '转发图片' if prefix else '图片')
        for sticker in current.get('sticker_items') or current.get('stickers') or []:
            if not isinstance(sticker, dict) or not str(sticker.get('id', '')).isdigit():
                continue
            format_type = sticker.get('format_type', sticker.get('formatType', 1))
            if format_type not in (1, 2, 4):
                continue
            suffix = 'gif' if format_type == 4 else 'png'
            identity = str(sticker['id'])
            add({'url': f'https://cdn.discordapp.com/stickers/{identity}.{suffix}', 'filename': f'sticker.{suffix}'},
                f'{prefix}sticker-{identity}', 'sticker', '贴纸')
        for index, snapshot in enumerate(current.get('message_snapshots') or []):
            inner = snapshot.get('message') if isinstance(snapshot, dict) else None
            if isinstance(inner, dict):
                visit(inner, f'{prefix}snapshot-{index}-', depth+1)
    visit(raw)
    return assets
