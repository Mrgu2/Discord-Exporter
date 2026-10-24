"""Persist only digests of paired-device cookies, with the original 30-day expiry."""
import hashlib
import json
import math
import re
import threading
import time
from pathlib import Path

from .settings import atomic_json


class PhoneSessions:
    def __init__(self, root, access_code):
        self.path = Path(root) / 'data' / 'phone-sessions.json'
        self.lock = threading.RLock()
        self.code_digest = self.digest(access_code)
        self.sessions = {}
        try:
            saved = json.loads(self.path.read_text())
            if saved.get('code_digest') == self.code_digest:
                self.sessions = {key: expiry for key, expiry in saved.get('sessions', {}).items()
                    if re.fullmatch(r'[0-9a-f]{64}', key) and type(expiry) in (int, float)
                    and math.isfinite(expiry) and expiry > time.time()}
        except (OSError, ValueError, AttributeError, TypeError):
            # Missing/corrupt session data never grants access.
            self.sessions = {}

    @staticmethod
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def get(self, token, default=None):
        with self.lock:
            expiry = self.sessions.get(self.digest(token), 0)
            return expiry if expiry > time.time() else default

    def __setitem__(self, token, expiry):
        with self.lock:
            saved = {key: value for key, value in self.sessions.items() if value > time.time()}
            # Keep storage bounded; oldest pairings expire first if full.
            while len(saved) >= 256:
                saved.pop(min(saved, key=saved.get))
            saved[self.digest(token)] = expiry
            atomic_json(self.path, {'code_digest': self.code_digest, 'sessions': saved})
            self.sessions = saved
