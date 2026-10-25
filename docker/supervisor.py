#!/usr/bin/env python3
"""Keep manual stop/autostart semantics without host Docker permissions."""
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from discord_archive.container_runtime import control_directory,preference,set_autostart,ensure_identity
from discord_archive.listener import read_listener


def main():
    os.umask(0o077)
    root=Path(os.environ.get('ARCHIVE_ROOT','/app')).resolve()
    directory=control_directory();directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=directory/'control.sock';marker=directory/'manual-stop'
    # Only ephemeral IPC entries created by this supervisor are refreshed.
    if path.exists(): path.unlink()
    if marker.exists(): marker.unlink()
    ensure_identity(root)
    first=not (root/'data/docker-runtime.json').exists()
    if first:set_autostart(root,False)
    child=None;lock=threading.RLock();stopping=threading.Event();run_requested=first or preference(root)['autostart']
    def spawn():
        nonlocal child
        if child and child.poll() is None:return
        if marker.exists():marker.unlink()
        child=subprocess.Popen([sys.executable,str(root/'app.py'),'--root',str(root),'--host','127.0.0.1','--port',os.environ.get('ARCHIVE_PORT','8765')])
    def status():
        current=read_listener(root)
        return {'pid':child.pid if child and child.poll() is None else None,'running':bool(child and child.poll() is None),'autostart':preference(root)['autostart'],
            'url':current.get('url',f"http://127.0.0.1:{os.environ.get('ARCHIVE_PORT','8765')}")}
    def signal_stop(*_):
        stopping.set()
        with lock:
            if child and child.poll() is None:child.terminate()
    signal.signal(signal.SIGTERM,signal_stop);signal.signal(signal.SIGINT,signal_stop)
    server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.bind(str(path));path.chmod(0o600);server.listen(4);server.settimeout(.5)
    last_spawn=0
    try:
        while not stopping.is_set():
            with lock:
                if child and child.poll() is not None:
                    run_requested=not marker.exists();child=None
                if run_requested and child is None and time.monotonic()-last_spawn>=2:
                    spawn();last_spawn=time.monotonic()
            try:connection,_=server.accept()
            except socket.timeout:continue
            with connection:
                connection.settimeout(2)
                try:
                    raw=b''
                    while b'\n' not in raw:
                        chunk=connection.recv(4096)
                        if not chunk or len(raw)>4096:raise ValueError()
                        raw+=chunk
                    request=json.loads(raw)
                    if not isinstance(request,dict) or set(request)!={'action'} or request['action'] not in ('start','status'):raise ValueError()
                    with lock:
                        if request['action']=='start':run_requested=True;spawn()
                        result=status()
                except Exception:result={'error':'只支持本容器的 start/status 操作'}
                connection.sendall(json.dumps(result).encode()+b'\n')
    finally:
        stopping.set();server.close()
        while child and child.poll() is None:
            # A child may exec a restart after the first signal. Signal again
            # after each grace interval until this same child actually exits.
            child.terminate()
            try:child.wait(timeout=1)
            except subprocess.TimeoutExpired:pass
if __name__=='__main__':main()
