"""Lifecycle fault injection and pause semantics; never touch the user's agent."""
import copy
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch, call

from discord_archive.service_control import ServiceControl, own_agent
from discord_archive.settings import Settings
from discord_archive.store import ArchiveStore
from discord_archive.worker import Worker


class PauseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = Settings(self.root)
        self.store = ArchiveStore(self.root/'data/archive.sqlite3')
        self.credentials = Mock(); self.credentials.get.return_value = 'synthetic'
        self.worker = Worker(self.store, self.root, self.settings, self.credentials, Mock())

    def tearDown(self):
        if hasattr(self.worker, 'thread'):
            self.worker.stop_event.set(); self.worker.thread.join(3)
            self.assertFalse(self.worker.thread.is_alive())
        self.store.close(); self.temp.cleanup()

    def test_pause_is_durable_preserves_configuration_and_manual_work(self):
        before = self.settings.read()
        self.worker.submit('capture', {'trigger':'scheduled'})
        self.worker.submit('auto_export', {'slot':'synthetic'})
        self.worker.set_automatic_paused(True)
        self.assertEqual(self.settings.read(), before)
        reloaded = Worker(self.store, self.root, self.settings, self.credentials, Mock())
        self.assertTrue(reloaded.state['automatic_paused'])
        state, _ = self.worker.status()
        self.assertIsNone(state['next_capture_at']); self.assertIsNone(state['auto_export']['next_at'])
        for kind,payload in [('capture',{'trigger':'scheduled'}),('capture',{'trigger':'reconnect'}),('auto_export',{})]:
            with self.assertRaisesRegex(ValueError,'暂停'): self.worker.submit(kind,payload)
        with patch.object(self.worker, 'capture') as capture, patch.object(self.worker.auto_export,'run') as export, patch.object(self.worker.auto_export,'due') as due:
            self.worker.drafts.generate.side_effect = lambda _: self.worker.stop_event.set() or {'id':'manual'}
            self.worker.submit('draft', {})
            self.worker.loop()
            self.worker.jobs.join()
            capture.assert_not_called(); export.assert_not_called(); due.assert_not_called()
            self.worker.drafts.generate.assert_called_once()
        self.assertFalse(self.worker._queued_capture); self.assertFalse(self.worker._queued_auto_export)
        self.worker.set_automatic_paused(False)
        self.assertFalse(Worker(self.store,self.root,self.settings,self.credentials,Mock()).state['automatic_paused'])
        self.assertEqual(self.settings.read(), before)

    def test_pause_allows_current_task_to_finish_and_manual_capture_afterward(self):
        entered, finish, second = threading.Event(), threading.Event(), threading.Event()
        def capture(payload):
            if not entered.is_set():
                entered.set(); self.assertTrue(finish.wait(4))
            else: second.set()
            return {'status':'success'}
        with patch.object(self.worker,'capture',side_effect=capture):
            self.worker.submit('capture',{'trigger':'scheduled'}); self.worker.start()
            self.assertTrue(entered.wait(3)); self.worker.set_automatic_paused(True)
            self.assertIsNotNone(self.worker.state['active_job'])
            finish.set(); self.worker.jobs.join()
            self.worker.submit('capture',{'trigger':'manual'}); self.assertTrue(second.wait(3))
            self.worker.jobs.join()
            self.assertEqual(self.worker.state['last_job_status'],'success')

    def test_pause_write_failure_keeps_previous_state(self):
        with patch.object(self.worker,'persist',side_effect=OSError('synthetic disk full')):
            with self.assertRaises(OSError): self.worker.set_automatic_paused(True)
        self.assertFalse(self.worker.state['automatic_paused'])

    def test_drain_finishes_queue_and_rejects_new_jobs_then_shutdown(self):
        control = ServiceControl(self.worker); control.server = Mock()
        self.worker.submit('draft',{}); self.worker.submit('draft',{})
        gate = threading.Event(); entered = threading.Event()
        def generate(_):
            entered.set(); self.assertTrue(gate.wait(4)); return {'id':'synthetic'}
        self.worker.drafts.generate.side_effect = generate
        self.worker.start(); self.assertTrue(entered.wait(3))
        control.request('restart'); control.start()
        control.server.shutdown.assert_not_called()
        with self.assertRaisesRegex(ValueError,'重启'): self.worker.submit('draft',{})
        with self.assertRaisesRegex(ValueError,'重启'): self.worker.set_automatic_paused(True)
        with self.assertRaises(ValueError): control.request('stop')
        gate.set(); self.worker.jobs.join()
        # Deterministic callback arrival, with no arbitrary delay.
        for _ in range(100):
            if control.server.shutdown.called: break
            threading.Event().wait(.01)
        control.server.shutdown.assert_called_once()
        self.assertEqual(self.worker.drafts.generate.call_count,2)


class ManagedServiceTests(unittest.TestCase):
    def worker(self):
        return SimpleNamespace(lock=threading.RLock(),jobs=Mock(),persist=Mock(),draining=False)

    def test_agent_detection_matches_own_pid_only(self):
        with patch('discord_archive.service_control.sys.platform','darwin'), patch('discord_archive.service_control.os.getpid',return_value=42), patch('discord_archive.service_control.launchctl') as command:
            for pid,code,expected in ((42,0,True),(43,0,False),(42,1,False)):
                command.return_value=subprocess.CompletedProcess([],code,f' pid = {pid}\n')
                self.assertEqual(bool(own_agent()),expected)

    def test_managed_stop_disables_then_boots_out_and_preserves_files(self):
        control=ServiceControl(self.worker());control.server=Mock()
        control.action='stop'
        with patch('discord_archive.service_control.launchctl',return_value=subprocess.CompletedProcess([],0)) as command:
            control._finish('gui/123/test-only')
        self.assertEqual(command.call_args_list,[call('disable','gui/123/test-only'),call('bootout','gui/123/test-only')])
        control.server.shutdown.assert_called_once()

    def test_failed_stop_restores_running_state_and_reports_error(self):
        for codes in ((1,), (0,1,0)):
            control=ServiceControl(self.worker());control.server=Mock();control.action='stop';control.worker.draining=True
            with patch('discord_archive.service_control.launchctl',side_effect=[subprocess.CompletedProcess([],code) for code in codes]) as command:
                control._finish('gui/123/test-only')
            self.assertIsNone(control.action);self.assertFalse(control.worker.draining)
            self.assertIsNotNone(control.error);control.server.shutdown.assert_not_called()
            if len(codes)>1: self.assertEqual(command.call_args_list[-1],call('enable','gui/123/test-only'))

    def test_invalid_or_unavailable_actions_do_not_drain(self):
        control=ServiceControl(self.worker())
        for action in ('restart','stop','invalid',None):
            with self.assertRaises(ValueError): control.request(action)
        self.assertFalse(control.worker.draining)


if __name__=='__main__': unittest.main()
