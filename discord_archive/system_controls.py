"""OS-backed startup preferences and explicit, permission-gated host power."""
import getpass
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone


def run(command):
    return subprocess.run(command,capture_output=True,text=True,timeout=20)


def require(result, message):
    if result.returncode: raise RuntimeError(message)


class StartupControl:
    def __init__(self,root,host='127.0.0.1',port=8765):
        self.root=Path(root).resolve();self.host=host;self.port=port
        self.lock=threading.RLock()

    def _file(self):
        if sys.platform=='darwin':
            return Path.home()/'Library/LaunchAgents/local.discord.answer-archive.plist'
        return Path.home()/'.config/systemd/user/discordarchive.service'

    def _owned(self,path):
        if not path.exists(): return True
        if sys.platform=='darwin':
            value=plistlib.loads(path.read_bytes())
            arguments=value.get('ProgramArguments',[])
            return len(arguments)>1 and Path(arguments[1]).resolve()==self.root/'app.py'
        for line in path.read_text().splitlines():
            if line.startswith('ExecStart='):
                arguments=shlex.split(line.removeprefix('ExecStart='))
                return len(arguments)>1 and Path(arguments[1]).resolve()==self.root/'app.py'
        return False

    def status(self):
        result={'available':sys.platform=='darwin' or sys.platform.startswith('linux'),
            'enabled':False,'scope':'login','note':''}
        try:
            if not (self.root/'app.py').is_file():
                return {**result,'available':False,'note':'当前目录不含完整源码，不能注册自动启动；请使用完整项目目录。'}
            path=self._file()
            if not self._owned(path):
                return {**result,'available':False,'note':'同名启动服务属于另一份项目，未修改。'}
            if sys.platform=='darwin':
                if path.exists():
                    value=plistlib.loads(path.read_bytes())
                    disabled=run(['/bin/launchctl','print-disabled',f'gui/{os.getuid()}'])
                    require(disabled,'无法读取登录启动状态')
                    blocked=re.search(r'"local\.discord\.answer-archive"\s*=>\s*true',disabled.stdout or '')
                    result['enabled']=bool(value.get('RunAtLoad')) and not blocked
                result['note']='登录 Mac 后自动运行；关闭开关不会停止当前服务。'
            elif sys.platform.startswith('linux'):
                if path.exists():
                    state=run(['systemctl','--user','is-enabled','discordarchive.service'])
                    result['enabled']=state.returncode==0 and state.stdout.strip()=='enabled'
                linger=Path('/var/lib/systemd/linger')/getpass.getuser()
                result['scope']='boot' if linger.exists() else 'login'
                result['note']=('开机后自动运行；关闭开关不会停止当前服务。' if linger.exists()
                    else '当前只在用户登录后运行。开机运行还需管理员启用用户 linger，见部署说明。')
        except (OSError,ValueError,TypeError,RuntimeError,subprocess.SubprocessError):
            return {**result,'available':False,'note':'无法读取系统启动状态，请检查权限和后台服务配置。'}
        return result

    def set_enabled(self,enabled):
        with self.lock:
            return self._set_enabled(enabled)

    def _set_enabled(self,enabled):
        if type(enabled) is not bool: raise ValueError('自动启动开关必须为布尔值')
        if not self.status()['available']: raise ValueError(self.status()['note'])
        path=self._file()
        if not self._owned(path): raise ValueError('同名服务属于另一份项目')
        if not path.exists() and not enabled: return self.status()
        if sys.platform=='darwin':
            from scripts.install_service import build_plist
            value=plistlib.loads(path.read_bytes()) if path.exists() else build_plist(self.root)
            if not path.exists():
                value['ProgramArguments']=[sys.executable,str(self.root/'app.py'),'--root',str(self.root),
                    '--host',self.host,'--port',str(self.port)]
            value['RunAtLoad']=enabled;value['KeepAlive']=enabled
            if path.exists():
                backup=self.root/'data/service-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
                backup.mkdir(parents=True,exist_ok=True);shutil.copy2(path,backup/path.name)
            path.parent.mkdir(parents=True,exist_ok=True)
            pending=path.with_suffix('.pending')
            with pending.open('wb') as output: plistlib.dump(value,output)
            pending.chmod(0o600)
            original=path.read_bytes() if path.exists() else None
            try:
                require(run(['/bin/launchctl','enable' if enabled else 'disable',
                    f'gui/{os.getuid()}/local.discord.answer-archive']),'无法修改登录启动状态')
                os.replace(pending,path)
            except Exception:
                # A failed OS operation must not be presented as a saved toggle.
                if original is not None and path.exists(): path.write_bytes(original)
                raise
        else:
            if not path.exists():
                from scripts.install_linux_service import unit
                if self.host!='127.0.0.1' or self.port!=8765:
                    raise ValueError('当前为自定义监听地址，请先按 Linux 部署说明创建对应服务')
                desktop=bool(os.environ.get('DISCORD_ARCHIVE_LOGIN_DESKTOP'))
                if desktop and not (path.parent/'discordarchive-desktop.service').exists():
                    raise ValueError('请先按 Linux 部署说明安装登录桌面服务')
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(unit(self.root,desktop));path.chmod(0o600)
                require(run(['systemctl','--user','daemon-reload']),'无法载入用户服务')
            require(run(['systemctl','--user','enable' if enabled else 'disable','discordarchive.service']),
                '无法修改自动启动，请检查用户 systemd 权限')
        result=self.status()
        if result['enabled']!=enabled: raise RuntimeError('系统自动启动状态未达到所选值，请重新检查')
        return result


class HostPower:
    METHODS={'host-reboot':'Reboot','host-poweroff':'PowerOff'}

    @staticmethod
    def command(method,*args):
        return ['busctl','call','org.freedesktop.login1','/org/freedesktop/login1',
            'org.freedesktop.login1.Manager',method,*args]

    def status(self):
        result={'supported':sys.platform.startswith('linux'),'reboot':False,'poweroff':False,'note':''}
        if not result['supported']: return result
        try:
            for action,method in self.METHODS.items():
                value=run(self.command('Can'+method))
                result[action.removeprefix('host-')]=value.returncode==0 and value.stdout.strip()=='s "yes"'
            if not all(result[key] for key in ('reboot','poweroff')):
                result['note']='系统尚未授予无交互电源操作权限；请由管理员配置后刷新，应用不保存 sudo 密码。'
        except (OSError,subprocess.SubprocessError):
            result['note']='无法读取系统电源权限，请检查 systemd-logind。'
        return result

    def check(self,action):
        if action not in self.METHODS: raise ValueError('不支持的服务器电源操作')
        state=self.status()
        if not state[action.removeprefix('host-')]: raise ValueError(state['note'] or '服务器电源操作不可用')

    def execute(self,action):
        self.check(action)
        require(run(self.command(self.METHODS[action],'b','false')),
            '系统拒绝电源操作，服务器仍运行；请检查权限或系统阻止条件。')
