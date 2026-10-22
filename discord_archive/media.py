"""Download Discord attachments without forwarding the account credential."""
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

from .assets import allowed_media_url, iter_message_assets

from .settings import atomic_json


class _CDNRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_media_url(newurl):
            raise ValueError('unsupported asset host')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class MediaArchive:
    def __init__(self, root):
        self.root = Path(root)
        self.directory = self.root / 'data' / 'media'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'manifest.json'
        self.manifest = json.loads(self.path.read_text()) if self.path.exists() else {}

    def archive_page(self, channel_id, run_id, messages, download=True):
        failures = 0
        visited = set()
        def save(message, channel):
            nonlocal failures
            raw = message.get('raw') if isinstance(message.get('raw'), dict) else message
            channel = str(message.get('channel_id') or raw.get('channel_id') or channel)
            identity = str(message.get('message_id') or raw.get('id', ''))
            if (channel, identity) in visited:
                return
            visited.add((channel, identity))
            for attachment in iter_message_assets(message):
                key = f"{channel}/{identity}/{attachment['id']}"
                existing = self.manifest.get(key, {})
                if existing.get('status') == 'saved' and (self.directory / existing['file']).is_file():
                    continue
                entry = {'channel_id': channel, 'message_id': identity, 'filename': attachment.get('filename', ''), 'run_id': run_id,
                         'content_type': attachment.get('content_type'), 'is_image': attachment.get('is_image'), 'source_type': attachment.get('source_type')}
                try:
                    if not download:
                        entry['status'] = 'not_requested'
                    else:
                        url = attachment.get('download_url', '')
                        if not allowed_media_url(url):
                            raise ValueError('unsupported asset host')
                        if int(attachment.get('size', 0)) > 50 * 1024 * 1024:
                            raise ValueError('asset exceeds 50MB limit')
                        suffix = Path(attachment.get('filename', 'asset')).suffix[:12]
                        if attachment.get('is_image') and not suffix:
                            suffix = {'image/jpeg':'.jpg','image/gif':'.gif','image/webp':'.webp','image/avif':'.avif','image/bmp':'.bmp'}.get(attachment.get('content_type'), '.png')
                        filename = hashlib.sha256(key.encode()).hexdigest() + suffix
                        target = self.directory / filename
                        with build_opener(_CDNRedirect()).open(Request(url, headers={'User-Agent': 'DiscordArchiveLocal/1.0'}), timeout=20) as response:
                            payload = response.read(50 * 1024 * 1024 + 1)
                        if len(payload) > 50 * 1024 * 1024:
                            raise ValueError('asset exceeds 50MB limit')
                        temp = target.with_suffix(target.suffix + '.part')
                        with open(temp, 'wb') as handle:
                            handle.write(payload)
                        os.replace(temp, target)
                        entry.update(status='saved', file=filename, sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))
                except Exception:
                    entry['status'] = 'failed'
                    entry['error'] = '附件未能保存，相关条件需核对'
                    failures += 1
                self.manifest[key] = entry
            nested = raw.get('referenced_message') or raw.get('referencedMessage')
            if isinstance(nested, dict):
                reference = raw.get('message_reference') or {}
                save(nested, reference.get('channel_id') or channel)
        for message in messages:
            save(message, channel_id)
        atomic_json(self.path, self.manifest)
        return failures

    def stats(self):
        counts = {'saved': 0, 'failed': 0, 'not_requested': 0}
        for value in self.manifest.values():
            counts[value['status']] = counts.get(value['status'], 0) + 1
        return counts
