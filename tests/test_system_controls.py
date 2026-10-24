"""Never execute real host power or alter the user's startup services."""
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
import io
from unittest.mock import Mock,patch

from discord_archive.system_controls import StartupControl,HostPower
from discord_archive.service_control import ServiceControl


class SystemControlsTests(unittest.TestCase):
    def test_linux_first_install_can_start_without_enabling_boot(self):
        from scripts import install_linux_service as installer
        with tempfile.TemporaryDirectory() as folder,patch('pathlib.Path.home',return_value=Path(folder)),patch('sys.platform','linux'):
            root=Path(folder)/'archive';root.mkdir();(root/'app.py').write_text('# fixture')
            with patch('sys.argv',['installer','--install','--root',str(root),'--no-autostart']),patch.object(installer,'systemctl',return_value=Mock(stdout='active')) as command,patch('discord_archive.access.linux_access',return_value={'server_addresses':[]}),patch('sys.stdout',new=io.StringIO()):
                installer.main()
            calls=[call.args for call in command.call_args_list]
            self.assertIn(('disable',installer.NAME),calls)
            self.assertIn(('start',installer.NAME),calls)
            self.assertFalse(any('enable' in args for args in calls))

    def test_mac_toggle_writes_verified_preference_without_start_or_stop(self):
        with tempfile.TemporaryDirectory() as folder,patch('discord_archive.system_controls.sys.platform','darwin'),patch('pathlib.Path.home',return_value=Path(folder)):
            root=Path(folder)/'archive';root.mkdir();(root/'app.py').write_text('# fixture')
            control=StartupControl(root);blocked=False;commands=[]
            def command(args):
                nonlocal blocked
                commands.append(args)
                if args[1] in ('enable','disable'): blocked=args[1]=='disable'
                return Mock(returncode=0,stdout='"local.discord.answer-archive" => '+str(blocked).lower())
            with patch('discord_archive.system_controls.run',side_effect=command):
                self.assertTrue(control.set_enabled(True)['enabled'])
                self.assertFalse(control.set_enabled(False)['enabled'])
                with self.assertRaises(ValueError):control.set_enabled('false')
            value=plistlib.loads(control._file().read_bytes())
            self.assertFalse(value['RunAtLoad']);self.assertFalse(value['KeepAlive'])
            self.assertFalse(any(command[1] in ['bootstrap','bootout','kickstart'] for command in commands))

    def test_linux_toggle_does_not_stop_running_service(self):
        with tempfile.TemporaryDirectory() as folder,patch('discord_archive.system_controls.sys.platform','linux'),patch('pathlib.Path.home',return_value=Path(folder)):
            root=Path(folder)/'archive';root.mkdir();(root/'app.py').write_text('# fixture');control=StartupControl(root)
            path=control._file();path.parent.mkdir(parents=True);path.write_text('ExecStart=/usr/bin/python3 '+str((root/'app.py').resolve()))
            enabled=True;commands=[]
            def command(args):
                nonlocal enabled
                commands.append(args)
                if args[2] in ('enable','disable'):enabled=args[2]=='enable'
                return Mock(returncode=0 if enabled else 1,stdout='enabled' if enabled else 'disabled')
            # disable/enable return success, while is-enabled reports the state.
            def operating(args):
                result=command(args)
                if args[2] in ('enable','disable'):result.returncode=0
                return result
            with patch('discord_archive.system_controls.run',side_effect=operating):
                self.assertFalse(control.set_enabled(False)['enabled'])
                self.assertTrue(control.set_enabled(True)['enabled'])
            self.assertFalse(any(value in command for command in commands for value in ['--now','stop','restart']))

    def test_other_installation_is_never_modified(self):
        with tempfile.TemporaryDirectory() as folder,patch('discord_archive.system_controls.sys.platform','linux'),patch('pathlib.Path.home',return_value=Path(folder)):
            control=StartupControl(Path(folder)/'archive');path=control._file();path.parent.mkdir(parents=True);path.write_text('ExecStart=/another/app.py')
            with patch('discord_archive.system_controls.run') as run:
                with self.assertRaises(ValueError):control.set_enabled(True)
                run.assert_not_called()
            self.assertEqual(path.read_text(),'ExecStart=/another/app.py')

    def test_power_challenge_never_attempts_execution(self):
        with patch('discord_archive.system_controls.sys.platform','linux'),patch('discord_archive.system_controls.run',return_value=Mock(returncode=0,stdout='s "challenge"')) as run:
            power=HostPower();self.assertFalse(power.status()['reboot'])
            with self.assertRaises(ValueError):power.execute('host-reboot')
            self.assertTrue(all(command.args[0][5].startswith('Can') for command in run.call_args_list))

    def test_authorized_power_uses_noninteractive_logind_only_mocked(self):
        power=HostPower()
        with patch.object(power,'check'),patch('discord_archive.system_controls.run',return_value=Mock(returncode=0)) as run:
            power.execute('host-poweroff')
        self.assertEqual(run.call_args.args[0][-3:],['PowerOff','b','false'])

    def test_power_drains_before_execution_and_failure_restores_service(self):
        worker=Mock();worker.lock=__import__('threading').RLock();worker.draining=False
        control=ServiceControl(worker);control.server=Mock();control.power=Mock()
        control.request('host-reboot')
        events=[]
        worker.jobs.join.side_effect=lambda:events.append('drain')
        worker.persist.side_effect=lambda:events.append('persist')
        def fail(_):events.append('power');raise RuntimeError('授权已撤销')
        control.power.execute.side_effect=fail
        control._finish(None)
        self.assertEqual(events,['drain','persist','power'])
        self.assertFalse(worker.draining);self.assertIsNone(control.action)
        control.server.shutdown.assert_not_called()


if __name__=='__main__':unittest.main()
