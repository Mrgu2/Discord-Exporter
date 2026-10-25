"""Drain jobs before controlling this process; never signal unrelated services."""
import os
import re
import subprocess
import sys
import threading
import uuid
from .system_controls import HostPower
from . import container_runtime

LABEL = 'local.discord.answer-archive'


def launchctl(*arguments):
    return subprocess.run(['/bin/launchctl', *arguments], capture_output=True, text=True, timeout=20)


def own_agent():
    if sys.platform != 'darwin':
        return None
    target = f'gui/{os.getuid()}/{LABEL}'
    result = launchctl('print', target)
    pid = re.search(r'^\s*pid = (\d+)\s*$', result.stdout or '', re.MULTILINE)
    return target if result.returncode == 0 and pid and int(pid.group(1)) == os.getpid() else None


class ServiceControl:
    def __init__(self, worker):
        self.worker = worker
        self.instance = uuid.uuid4().hex
        self.action = None
        self.error = None
        self.server = None
        self.power = HostPower()

    def status(self):
        with self.worker.lock:
            return {'instance': self.instance, 'action': self.action, 'error': self.error,
                    'available': self.server is not None}

    def request(self, action):
        if action not in {'restart', 'stop', 'host-reboot', 'host-poweroff'}:
            raise ValueError('请选择重启服务或停止服务')
        with self.worker.lock:
            if self.server is None:
                raise ValueError('当前运行方式不支持服务控制')
            if self.action:
                raise ValueError('服务操作正在进行，请等待完成')
            if action.startswith('host-'):
                self.power.check(action)
            # Inspect ownership before accepting; failures leave the service running.
            agent = own_agent() if action == 'stop' else None
            if action == 'stop' and container_runtime.active():
                container_runtime.mark_stopped()
            self.worker.draining = True
            self.action, self.error = action, None
            self.agent = agent
            return self.status()

    def start(self):
        threading.Thread(target=self._finish, args=(self.agent,), daemon=True).start()

    def _finish(self, agent):
        try:
            self.worker.jobs.join()
            # The worker cannot schedule or accept new work while draining.
            self.worker.persist()
            if self.action.startswith('host-'):
                self.power.execute(self.action)
            if agent:
                result = launchctl('disable', agent)
                if result.returncode:
                    raise RuntimeError('无法停用自动拉起，服务仍在运行，请重试')
                try:
                    result = launchctl('bootout', agent)
                    if result.returncode:
                        raise RuntimeError('无法停止登录服务，服务仍在运行，请重试')
                except Exception:
                    launchctl('enable', agent)
                    raise
            self.server.shutdown()
        except Exception as exc:
            with self.worker.lock:
                self.worker.draining = False
                self.action = None
                self.error = str(exc) if isinstance(exc, RuntimeError) else '服务操作未完成，服务仍在运行，请重试'
