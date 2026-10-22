"""Download Discord attachments without forwarding the account credential."""
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .settings import atomic_json


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
        def save(message):
            nonlocal failures
            identity = str(message.get('id', ''))
            if identity in visited:
                return
            visited.add(identity)
            for attachment in message.get('attachments', []):
                key = f"{channel_id}/{identity}/{attachment.get('id', attachment.get('filename', 'asset'))}"
                existing = self.manifest.get(key, {})
                if existing.get('status') == 'saved' and (self.directory / existing['file']).is_file():
                    continue
                entry = {'channel_id': channel_id, 'message_id': identity, 'filename': attachment.get('filename', ''), 'run_id': run_id}
                try:
                    if not download:
                        entry['status'] = 'not_requested'
                    else:
                        url = attachment.get('url', '')
                        parts = urlsplit(url)
                        if parts.scheme != 'https' or parts.hostname not in ('cdn.discordapp.com', 'media.discordapp.net', 'cdn.discordapp.net'):
                            raise ValueError('unsupported asset host')
                        if int(attachment.get('size', 0)) > 50 * 1024 * 1024:
                            raise ValueError('asset exceeds 50MB limit')
                        suffix = Path(attachment.get('filename', 'asset')).suffix[:12]
                        filename = hashlib.sha256(key.encode()).hexdigest() + suffix
                        target = self.directory / filename
                        with urlopen(Request(url, headers={'User-Agent': 'DiscordArchiveLocal/1.0'}), timeout=20) as response:
                            raw = response.read(50 * 1024 * 1024 + 1)
                        if len(raw) > 50 * 1024 * 1024:
                            raise ValueError('asset exceeds 50MB limit')
                        temp = target.with_suffix(target.suffix + '.part')
                        with open(temp, 'wb') as handle:
                            handle.write(raw)
                        os.replace(temp, target)
                        entry.update(status='saved', file=filename, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
                except Exception:
                    entry['status'] = 'failed'
                    entry['error'] = '附件未能保存，相关条件需核对'
                    failures += 1
                self.manifest[key] = entry
            nested = message.get('referenced_message')
            if isinstance(nested, dict):
                save(nested)
        for message in messages:
            save(message)
        atomic_json(self.path, self.manifest)
        return failures

    def stats(self):
        counts = {'saved': 0, 'failed': 0, 'not_requested': 0}
        for value in self.manifest.values():
            counts[value['status']] = counts.get(value['status'], 0) + 1
        return counts
