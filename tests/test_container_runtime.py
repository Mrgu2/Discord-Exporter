import hashlib,json,os,signal,socket,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from discord_archive import container_runtime as runtime
from discord_archive.system_controls import StartupControl,HostPower
from discord_archive.listener import project_id
ROOT=Path(__file__).resolve().parent.parent

class ContainerPreferencesTests(unittest.TestCase):
    def test_native_identity_unchanged_and_volume_identity_persistent(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.dict(os.environ,{'DISCORD_ARCHIVE_DOCKER':'0'}):
                self.assertEqual(project_id(root),hashlib.sha256(str(root.resolve()).encode()).hexdigest())
            with patch.dict(os.environ,{'DISCORD_ARCHIVE_DOCKER':'1'}):
                runtime.ensure_identity(root);first=project_id(root)
                self.assertEqual(project_id(root),first)
                self.assertEqual((root/'data/docker-identity.json').stat().st_mode&0o777,0o600)
                (root/'data/docker-identity.json').write_text(json.dumps({'id':'a'*32}))
                self.assertNotEqual(project_id(root),first)

    def test_startup_toggle_is_persistent_without_host_calls(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'DISCORD_ARCHIVE_DOCKER':'1'}),patch('discord_archive.system_controls.run') as run:
            control=StartupControl(folder)
            self.assertFalse(control.status()['enabled'])
            self.assertEqual(control.status()['scope'],'container')
            self.assertTrue(control.set_enabled(True)['enabled']);self.assertTrue(StartupControl(folder).status()['enabled'])
            self.assertFalse(control.set_enabled(False)['enabled']);run.assert_not_called()
            with self.assertRaises(ValueError):control.set_enabled('yes')

    def test_host_power_is_unavailable_even_on_linux(self):
        with patch.dict(os.environ,{'DISCORD_ARCHIVE_DOCKER':'1'}),patch('discord_archive.system_controls.run') as run:
            self.assertFalse(HostPower().status()['supported'])
            with self.assertRaises(ValueError):HostPower().execute('host-reboot')
            run.assert_not_called()

    def test_bad_preference_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'DISCORD_ARCHIVE_DOCKER':'1'}):
            file=Path(folder)/'data/docker-runtime.json';file.parent.mkdir();file.write_text('bad')
            self.assertFalse(StartupControl(folder).status()['available']);self.assertEqual(file.read_text(),'bad')

@unittest.skipUnless(hasattr(socket,'AF_UNIX') and os.name=='posix','Linux/Mac IPC integration')
class SupervisorTests(unittest.TestCase):
    def test_manual_stop_start_and_reboot_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'app.py').write_text('import time\ntime.sleep(300)\n')
            env={**os.environ,'DISCORD_ARCHIVE_DOCKER':'1','ARCHIVE_ROOT':str(root),'DISCORD_ARCHIVE_CONTROL_DIR':str(root/'ipc')}
            def spawn():return subprocess.Popen([sys.executable,str(ROOT/'docker/supervisor.py')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            def command(action='status'):
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
                    sock.settimeout(2);sock.connect(str(root/'ipc/control.sock'));sock.sendall(json.dumps({'action':action}).encode()+b'\n');return json.loads(sock.recv(4096))
            def wait(predicate):
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    try:
                        value=command()
                        if predicate(value):return value
                    except OSError:pass
                    time.sleep(.1)
                self.fail('Supervisor did not reach expected state')
            proc=spawn()
            try:
                state=wait(lambda s:s['running']);self.assertFalse(state['autostart'])
                self.assertIn('error',command('host-reboot'))
                with patch.dict(os.environ,env):runtime.mark_stopped()
                os.kill(state['pid'],signal.SIGTERM);wait(lambda s:not s['running']);time.sleep(2.2);self.assertFalse(command()['running'])
                command('start');wait(lambda s:s['running'])
                proc.terminate();proc.wait(timeout=5);proc=spawn();wait(lambda s:not s['running'])
                with patch.dict(os.environ,env):runtime.set_autostart(root,True)
                proc.terminate();proc.wait(timeout=5);proc=spawn();wait(lambda s:s['running'])
            finally:
                proc.terminate();proc.wait(timeout=5)

    def test_shutdown_during_child_exec_restart_does_not_hang(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'app.py').write_text("import signal,time,os,sys\nfrom pathlib import Path\nrestart=False\ndef term(*_):\n global restart\n restart=True\nsignal.signal(signal.SIGTERM,term)\nPath('"+str(root/'ready')+"').write_text('ready')\nwhile not restart:time.sleep(.01)\ntime.sleep(1)\nos.execv(sys.executable,[sys.executable,'-c','import time;time.sleep(60)'])\n")
            env={**os.environ,'DISCORD_ARCHIVE_DOCKER':'1','ARCHIVE_ROOT':str(root),'DISCORD_ARCHIVE_CONTROL_DIR':str(root/'ipc')}
            proc=subprocess.Popen([sys.executable,str(ROOT/'docker/supervisor.py')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            child=None
            try:
                deadline=time.monotonic()+5
                while not (root/'ready').exists() and time.monotonic()<deadline:time.sleep(.02)
                self.assertTrue((root/'ready').exists())
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
                    sock.connect(str(root/'ipc/control.sock'));sock.sendall(b'{"action":"status"}\n');child=json.loads(sock.recv(4096))['pid']
                proc.terminate()
                try:proc.wait(timeout=4)
                except subprocess.TimeoutExpired:self.fail('Supervisor hangs when SIGTERM overlaps child exec restart')
            finally:
                if proc.poll() is None and child:
                    try:os.kill(child,signal.SIGTERM)
                    except ProcessLookupError:pass
                    proc.wait(timeout=5)
