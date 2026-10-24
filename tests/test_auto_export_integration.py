import copy
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import make_handler
from discord_archive.collector import DiscordAPIError
from discord_archive.settings import Settings, atomic_json
from discord_archive.store import ArchiveStore
from discord_archive.worker import Worker


class TimedExportSettingsTests(unittest.TestCase):
    def test_legacy_defaults_and_partial_updates_do_not_create_files(self):
        with tempfile.TemporaryDirectory() as directory:
            settings=Settings(directory)
            value=json.loads(settings.path.read_text());value.pop('auto_export')
            atomic_json(settings.path,value);before=settings.path.read_bytes()
            self.assertFalse(settings.read()['auto_export']['enabled'])
            self.assertEqual(before,settings.path.read_bytes())
            destination=Path(directory)/'chosen'
            settings.update({'export':{'copy_directory':str(destination)},
                'auto_export':{'enabled':True,'times':['16:15','10:30','16:15']}})
            updated=settings.update({'auto_export':{'render_scales':[1,2]}})
            self.assertEqual(updated['auto_export']['times'],['10:30','16:15'])
            self.assertTrue(updated['auto_export']['enabled'])
            self.assertEqual(updated['export']['copy_directory'],str(destination))
            self.assertFalse(destination.exists())

    def test_enable_requires_copy_directory_and_bad_options_never_save(self):
        with tempfile.TemporaryDirectory() as directory:
            settings=Settings(directory);before=settings.path.read_bytes()
            for value in ({'enabled':True},{'enabled':'true'},{'times':['25:00']},{'render_scales':[3]}):
                with self.subTest(value=value),self.assertRaises(ValueError):
                    settings.update({'auto_export':value})
                self.assertEqual(before,settings.path.read_bytes())

    def test_phone_can_set_schedule_without_changing_directory_or_resetting_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            settings=Settings(directory)
            settings.update({'export':{'copy_directory':str(Path(directory)/'chosen')}})
            app=SimpleNamespace(settings=settings,worker=Mock(),csrf='fictional',
                sessions={'test':9999999999},local_hostname='test-mac')
            cls=make_handler(app);handler=cls.__new__(cls)
            body=json.dumps({'auto_export':{'enabled':True,'times':['10:30','16:15']}}).encode()
            handler.path='/api/config';handler.command='PUT';handler.client_address=('192.168.1.10',0)
            handler.headers={'Host':'192.168.1.2:8765','X-Archive-Key':'fictional',
                'Cookie':'archive_session=test','Content-Length':str(len(body))}
            handler.rfile=io.BytesIO(body);handler.send=Mock();handler.mutation()
            self.assertEqual(handler.send.call_args.args[0],200)
            self.assertTrue(settings.read()['auto_export']['enabled'])
            app.worker.reset_attention.assert_not_called()
            app.worker.configure_auto_export.assert_called_once()


class TimedExportWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.settings=Settings(self.root)
        self.settings.update({'channels':[{'id':'100','kind':'qa'}],'target_author_id':'9001',
            'schedule':{'enabled':False},'export':{'copy_directory':str(self.root/'chosen')},
            'auto_export':{'enabled':True,'times':['16:15']}})
        self.store=ArchiveStore(self.root/'data/archive.sqlite3')
        self.credentials=Mock();self.credentials.get.return_value='fictional'
        self.drafts=Mock();self.drafts.generate.return_value={'id':'draft-fixture'}
        self.worker=Worker(self.store,self.root,self.settings,self.credentials,self.drafts)
        self.clock=datetime(2026,10,23,20,15,3,tzinfo=timezone.utc)

    def tearDown(self):
        self.store.close();self.temp.cleanup()

    def run_loop(self,capture_error=None,render_error=None):
        def capture(payload):
            if capture_error:
                self.worker.stop_event.set();raise capture_error
            return {'status':'success'}
        def render(*args,**kwargs):
            self.worker.stop_event.set()
            if render_error:raise render_error
            return {'images':['/output/fixture.png'],'draft':{'export_copy':{
                'enabled':True,'copied':1,'failed':0,'error':None}}}
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return self.clock.astimezone(tz) if tz else self.clock.replace(tzinfo=None)
        self.drafts.render.side_effect=render
        # Construction now records activation immediately. Set a known
        # activation checkpoint for the controlled historical scheduler clock.
        self.worker.auto_export._save(enabled=True,enabled_since='2026-10-23T20:15:00Z')
        with patch('discord_archive.worker.datetime',Clock),patch.object(self.worker,'capture',side_effect=capture) as capturing:
            self.worker.loop()
        return capturing

    def test_enabling_records_activation_without_waiting_for_busy_worker(self):
        self.worker.state['active_job']={'type':'capture','id':'fixture'}
        self.worker.configure_auto_export(self.settings.read())
        saved=json.loads((self.root/'data/auto-export-state.json').read_text())
        self.assertTrue(saved['enabled'])
        self.assertIsNotNone(saved['enabled_since'])
        self.assertEqual(self.worker.jobs.qsize(),0)

    def test_real_worker_selects_timed_export_when_archive_schedule_is_disabled(self):
        capturing=self.run_loop()
        self.assertEqual(capturing.call_args.args[0]['trigger'],'scheduled_export')
        self.assertEqual(self.drafts.generate.call_args.args[0]['date'],'2026-10-23')
        self.assertEqual(self.drafts.generate.call_args.args[0]['scope'],'day')
        self.assertEqual(self.worker.state['last_job_status'],'success')
        self.assertFalse(self.worker._queued_auto_export)
        restarted=Worker(self.store,self.root,self.settings,self.credentials,self.drafts)
        self.assertIsNone(restarted.auto_export.due(self.settings.read(),self.clock))
        self.assertEqual(restarted.status()[0]['auto_export']['last_status'],'success')

    def test_network_failure_uses_existing_persistent_backoff(self):
        self.run_loop(capture_error=DiscordAPIError(0,'fictional offline'))
        self.assertEqual(self.worker.auto_export.stage,'capture')
        self.assertIsNotNone(self.worker.state['retry_at'])
        self.assertIsNotNone(self.worker.state['offline_since'])
        self.assertFalse(self.worker.state['requires_attention'])
        self.drafts.generate.assert_not_called()

    def test_local_export_failure_does_not_mark_network_offline(self):
        self.run_loop(render_error=ValueError('fictional disk full'))
        self.assertIsNone(self.worker.state['offline_since'])
        self.assertIsNone(self.worker.state['retry_at'])
        self.assertEqual(self.worker.state['last_job_status'],'failed')
        self.assertEqual(self.worker.auto_export.stage,'render')
        self.assertIsNotNone(self.worker.auto_export.summary(self.settings.read(),self.clock)['retry_at'])


if __name__=='__main__':unittest.main()
