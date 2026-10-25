"""Container-only preferences; never talks to a host Docker socket or power API."""
import json
import os
from pathlib import Path
from .settings import atomic_json


def active():
    return os.environ.get('DISCORD_ARCHIVE_DOCKER') == '1'


def preference(root):
    path = Path(root)/'data/docker-runtime.json'
    if not path.exists():
        return {'autostart': False}
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or type(value.get('autostart')) is not bool:
        raise ValueError('容器启动偏好无效；原文件已保留')
    return value


def set_autostart(root, enabled):
    if type(enabled) is not bool:
        raise ValueError('自动启动开关必须为布尔值')
    atomic_json(Path(root)/'data/docker-runtime.json', {**preference(root), 'autostart': enabled})


def control_directory():
    return Path(os.environ.get('DISCORD_ARCHIVE_CONTROL_DIR', '/tmp/discordarchive-runtime'))


def mark_stopped():
    directory = control_directory()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory/'manual-stop'
    path.write_text('stop\n'); path.chmod(0o600)


def ensure_identity(root):
    import uuid
    path = Path(root)/'data/docker-identity.json'
    if path.exists():
        value = json.loads(path.read_text()).get('id', '')
        if len(value) != 32 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('容器资料库标识无效；原文件已保留')
        return value
    value = uuid.uuid4().hex
    atomic_json(path, {'id':value})
    return value
