"""Linux-specific contracts; no SSH, real credentials, or model downloads."""
import contextlib
import io
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from discord_archive.browser_login import BrowserLogin
from discord_archive.speech import SpeechArchive
from discord_archive.access import private_addresses, linux_access

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('linux_service',ROOT/'scripts/install_linux_service.py')
service=importlib.util.module_from_spec(spec);spec.loader.exec_module(service)


class LinuxTests(unittest.TestCase):
    def test_access_report_does_not_advertise_public_proxy_or_loopback_ips(self):
        rows=[{'addr_info':[{'local':value} for value in
            ['127.0.0.1','192.0.2.66','100.64.1.2','198.18.0.1','8.8.8.8','bad','::1']]}]
        self.assertEqual(private_addresses(rows),['192.0.2.66','100.64.1.2'])
        with patch('discord_archive.access.subprocess.run',return_value=Mock(returncode=0,stdout=json.dumps(rows))), patch('discord_archive.access.shutil.which',return_value=None):
            report=linux_access()
        self.assertTrue(report['loopback_only'])
        self.assertFalse(report['tailscale_installed'])
        self.assertEqual(report['tunnel_workbench'],'http://127.0.0.1:18765')

    def test_access_report_survives_missing_ip_command(self):
        with patch('discord_archive.access.subprocess.run',side_effect=FileNotFoundError), patch('discord_archive.access.shutil.which',return_value=None):
            report=linux_access('server-name')
        self.assertEqual(report['server_addresses'],[])
        self.assertFalse(report['loopback_only'])

    def test_headless_login_explains_missing_display_without_touching_credentials(self):
        with tempfile.TemporaryDirectory() as folder, patch('discord_archive.browser_login.sys.platform','linux'), patch.dict(os.environ,{},clear=True):
            credentials=Mock()
            result=BrowserLogin(folder,credentials).connect()
            self.assertEqual(result['code'],'display_missing')
            credentials.set.assert_not_called()

    def test_ct2_model_validation_and_device_specific_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);model=root/'tiny';model.mkdir()
            (model/'config.json').write_text(json.dumps({'lang_ids':[50259,50260]}))
            (model/'model.bin').write_bytes(b'fixture')
            speech=SpeechArchive(root,{'python':os.sys.executable,'model_path':str(model),'device':'cpu'})
            cpu=speech.configuration()
            self.assertEqual(cpu['engine'],'faster-whisper')
            self.assertEqual(cpu['compute_type'],'int8')
            speech.options['device']='cuda'
            cuda=speech.configuration()
            self.assertEqual(cuda['compute_type'],'float16')
            self.assertNotEqual(cpu['fingerprint'],cuda['fingerprint'])
            (model/'config.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'英文专用'): speech.configuration()
            (model/'config.json').write_text(json.dumps({'lang_ids':[50259,50260]}))
            (model/'model.bin').unlink()
            speech.options['engine']='faster-whisper'
            with self.assertRaisesRegex(ValueError,'权重不完整'): speech.configuration()

    def test_reinstall_preserves_startup_preference(self):
        for existing,enabled,no_autostart,expected in [
                (True,False,False,'start'),(True,True,False,'enable'),
                (False,False,False,'enable'),(True,True,True,'disable')]:
            with self.subTest(existing=existing,enabled=enabled,no_autostart=no_autostart),tempfile.TemporaryDirectory() as folder:
                home=Path(folder);root=home/'project';root.mkdir();(root/'app.py').touch()
                unit_folder=home/'.config/systemd/user';unit_folder.mkdir(parents=True)
                if existing:(unit_folder/service.NAME).write_text(service.unit(root))
                args=['install_linux_service.py','--install','--root',str(root)]+(['--no-autostart'] if no_autostart else [])
                with patch.object(service.Path,'home',return_value=home),patch.object(service.sys,'platform','linux'),patch.object(service.sys,'argv',args),patch.object(service.subprocess,'run',return_value=Mock(returncode=0 if enabled else 1)),patch.object(service,'systemctl',return_value=Mock(stdout='')) as calls,patch('discord_archive.access.linux_access',return_value={'server_addresses':[]}),contextlib.redirect_stdout(io.StringIO()):
                    service.main()
                actions=[call.args[0] for call in calls.call_args_list]
                self.assertIn(expected,actions)
                if expected=='start':self.assertNotIn('enable',actions);self.assertNotIn('disable',actions)
                self.assertIn('UnsetEnvironment=DISPLAY', (unit_folder/service.NAME).read_text())

    def test_systemd_loopback_stop_and_desktop_contract(self):
        root=Path('/home/example/Archive Folder').resolve()
        output=service.unit(root,True)
        self.assertIn(f'WorkingDirectory={root}\n',output)
        self.assertIn('--host 127.0.0.1',output)
        self.assertIn('Restart=on-failure',output)
        self.assertIn('TimeoutStopSec=infinity',output)
        self.assertIn('Requires=discordarchive-desktop.service',output)
        headless=service.unit(root)
        self.assertNotIn('Requires=discordarchive-desktop.service',headless)
        self.assertIn('UnsetEnvironment=DISPLAY XAUTHORITY DISCORD_ARCHIVE_LOGIN_DESKTOP',headless)
        self.assertNotIn('Token',output)
        self.assertNotIn('Password',output)
        with self.assertRaises(ValueError): service.unit(Path('/tmp/unsafe%path'))


if __name__=='__main__': unittest.main()
