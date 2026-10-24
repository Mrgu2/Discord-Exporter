"""Per-library listener discovery and atomic port selection; no process killing."""
import errno
import hashlib
import json
from pathlib import Path

from .settings import atomic_json


def project_id(root):
    return hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()


def read_listener(root):
    try:
        value = json.loads((Path(root) / 'data/listener.json').read_text())
        if (value.get('project_id') == project_id(root) and type(value.get('port')) is int
                and 1 <= value['port'] <= 65535):
            return {**value, 'url': f"http://127.0.0.1:{value['port']}"}
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return {}


def bind_server(factory, root, host, requested_port, handler):
    if not 0 <= requested_port <= 65535:
        raise ValueError('端口须为 0 到 65535')
    previous = read_listener(root)
    preferred = previous.get('port') if (previous.get('host') == host and
        previous.get('requested_port') == requested_port) else requested_port
    ports = list(dict.fromkeys([preferred] + list(range(requested_port, min(requested_port + 100, 65536)))))
    for port in ports:
        try:
            server = factory((host, port), handler)
            return server
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
    raise RuntimeError('连续 100 个端口被占用，请使用 --port 指定其他端口；未停止任何进程')


def save_listener(root, host, requested_port, port):
    value = {'project_id': project_id(root), 'host': host,
        'requested_port': requested_port, 'port': port, 'url': f'http://127.0.0.1:{port}'}
    atomic_json(Path(root) / 'data/listener.json', value)
    return value


def sync_private_proxy(origin, backend, previous_backend):
    """Update only this existing Serve root route, without sudo or reset.

    Failure remains visible; never rewrite an unrelated route or enable Funnel.
    """
    import subprocess
    from urllib.parse import urlsplit
    if not origin:
        return None
    address = urlsplit(origin)
    port = address.port or 443
    warning = 'Tailscale 转发尚未同步；请运行 scripts/configure_tailscale.py，执行输出的实际端口命令。'
    try:
        current = subprocess.run(['tailscale', 'serve', 'status', '--json'],
            capture_output=True, text=True, timeout=5)
        if current.returncode:
            return warning
        value = json.loads(current.stdout)
        route = value.get('Web', {}).get(f'{address.hostname}:{port}', {})
        handlers = route.get('Handlers', {})
        proxy = handlers.get('/', {}).get('Proxy')
        if proxy == backend:
            return None
        if set(handlers) != {'/'} or proxy != previous_backend:
            return warning
        # An existing public Funnel must not silently be carried into this flow.
        if any(value.get('AllowFunnel', {}).values()):
            return warning
        changed = subprocess.run(['tailscale', 'serve', '--bg', f'--https={port}', backend],
            capture_output=True, text=True, timeout=10)
        if changed.returncode:
            return warning
        return None
    except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError):
        return warning
