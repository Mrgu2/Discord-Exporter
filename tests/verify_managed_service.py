"""Opt-in macOS acceptance using a unique LaunchAgent and temporary archive."""
import importlib.util
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


def verify():
    label = 'local.discord.archive-test.' + uuid.uuid4().hex
    target = f'gui/{os.getuid()}/{label}'
    domain = f'gui/{os.getuid()}'
    def ctl(*args):
        return subprocess.run(['/bin/launchctl',*args], capture_output=True, text=True, timeout=25)
    def require(result):
        if result.returncode: raise RuntimeError(f'launchctl failed: {result.returncode}: {result.stderr}')
    def until(fn, timeout=20):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            try:
                result=fn()
                if result: return result
            except (OSError,ValueError): pass
            time.sleep(.15)
        raise AssertionError('Timed out waiting for isolated managed service')
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def read(path='/api/status'):
        with opener.open(base+path,timeout=2) as response: return response.read()
    def status(): return json.loads(read())
    def post(action):
        csrf=re.search(r'name="archive-key" content="([^"]+)"',read('/').decode()).group(1)
        request=urllib.request.Request(base+'/api/service',data=json.dumps({'action':action}).encode(),
            headers={'Content-Type':'application/json','X-Archive-Key':csrf})
        with opener.open(request,timeout=3) as response: return json.load(response)
    with tempfile.TemporaryDirectory(prefix='archive-managed-') as temporary:
        root=Path(temporary).resolve()
        (root/'web').symlink_to(ROOT/'web',target_is_directory=True)
        runner=root/'app.py'
        runner.write_text(f'''import sys
sys.path.insert(0, {str(ROOT)!r})
import app
import discord_archive.service_control as control
control.LABEL = {label!r}
real_exec = app.os.execv
def fixture_exec(executable, arguments):
    arguments[1] = {str(runner)!r}
    real_exec(executable, arguments)
app.os.execv = fixture_exec
app.main()
''')
        plist=root/'Library/LaunchAgents'/f'{label}.plist';plist.parent.mkdir(parents=True)
        plist.write_bytes(plistlib.dumps({'Label':label,'ProgramArguments':[sys.executable,str(runner),'--root',str(root),'--host','127.0.0.1','--port',str(port)],
            'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':1,
            'EnvironmentVariables':{'DISCORD_ARCHIVE_TOKEN':'fictional-managed-test','ARCHIVE_MODEL_KEY':'fictional-managed-test'},
            'StandardOutPath':str(root/'fixture.log'),'StandardErrorPath':str(root/'fixture.log')}))
        try:
            require(ctl('bootstrap',domain,str(plist)))
            first=until(status)
            post('pause');post('restart')
            until(lambda: status()['service']['instance'] != first['service']['instance'])
            assert status()['state']['automatic_paused']
            # Pause never mutates planned task settings.
            assert status()['config']['schedule']['enabled']
            post('stop')
            until(lambda: ctl('print',target).returncode != 0)
            disabled=ctl('print-disabled',domain)
            assert re.search('"'+re.escape(label)+r'"\s*=>\s*(?:true|disabled)',disabled.stdout), (disabled.returncode, [line for line in disabled.stdout.splitlines() if label in line], disabled.stderr)
            time.sleep(2)
            assert ctl('print',target).returncode != 0, 'Stopped agent was relaunched'
            # Exercise the actual desktop start branch with its home/port isolated.
            spec=importlib.util.spec_from_file_location('fixture_launcher',ROOT/'scripts/desktop_launcher.py')
            launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
            launcher.LABEL=label
            def health():
                try: return 'healthy' if json.loads(read('/api/health'))['ok'] else 'occupied'
                except OSError: return 'offline'
            with patch.object(launcher.Path,'home',return_value=root),patch.object(launcher,'health',side_effect=health),patch.object(launcher,'wait_healthy',side_effect=lambda:until(status)):
                assert launcher.ensure_service(root)=='agent'
            assert status()['state']['automatic_paused']
            post('resume');assert not status()['state']['automatic_paused']
            assert (root/'data/archive.sqlite3').exists()
            post('stop');until(lambda:ctl('print',target).returncode != 0)
            print('PASS: real LaunchAgent restart, pause durability, disable + bootout, no KeepAlive relaunch, App launcher re-enable + bootstrap, resume, data preserved.')
        except Exception:
            if (root/'fixture.log').exists(): print((root/'fixture.log').read_text(),file=sys.stderr)
            raise
        finally:
            ctl('bootout',target)
            ctl('enable',target)  # Remove the test label's disabled state.


if __name__=='__main__': verify()
