"""Exercise the background recovery state machine without a real connection."""

import copy
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from discord_archive.collector import AccessDenied, AuthRequired, DiscordAPIError
from discord_archive.settings import DEFAULT_CONFIG
from discord_archive.store import ArchiveStore, parse_time
from discord_archive.worker import Worker


class FakeSettings:
    def read(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["schedule"]["enabled"] = False
        return config


class NoCredentials:
    def get(self, kind):
        return None


class WorkerRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = ArchiveStore(self.root / "archive.sqlite3")
        self.worker = self.new_worker()

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def new_worker(self):
        return Worker(self.store, self.root, FakeSettings(), NoCredentials(), None)

    def test_render_deduplicates_queued_active_and_dequeued_transition(self):
        first=self.worker.submit('render',{'draft_id':'fixture','target':'main'})
        self.assertEqual(self.worker.submit('render',{'draft_id':'fixture','target':'main'})['id'],first['id'])
        removed=self.worker.jobs.get_nowait()
        # Covers the brief handoff between queue.get and active_job assignment.
        self.assertTrue(self.worker.submit('render',{'draft_id':'fixture','target':'main'})['deduplicated'])
        self.worker.state['active_job']={'id':removed['id'],'type':'render','draft_id':'fixture','target':'main'}
        active=self.worker.submit('render',{'draft_id':'fixture','target':'main'})
        self.assertEqual(active['status'],'running')
        mobile=self.worker.submit('render',{'draft_id':'fixture','target':'mobile'})
        self.assertNotEqual(mobile['id'],first['id'])
        self.assertEqual(len(self.worker.status()[0]['render_jobs']),2)

    def test_speech_failure_does_not_reclassify_durable_capture_as_offline(self):
        config=FakeSettings().read();config['channels']=[{'id':'100'}]
        self.worker.settings=Mock();self.worker.settings.read.return_value=config
        self.worker.credentials=Mock();self.worker.credentials.get.return_value='synthetic'
        with patch('discord_archive.worker.DiscordClient'),patch('discord_archive.worker.CaptureService') as capture, \
                patch.object(self.worker.speech,'process_saved',side_effect=RuntimeError('synthetic ASR fault')):
            capture.return_value.capture.return_value={'status':'success'}
            result=self.worker.capture({'trigger':'manual'})
        self.assertEqual(result['status'],'success')
        self.assertTrue(result['audio']['failed'])
        self.assertIsNotNone(self.worker.state['last_success_at'])
        self.assertIsNone(self.worker.state['offline_since'])
        self.assertIsNone(self.worker.state['retry_at'])

    def run_one_failure(self, error):
        self.worker.stop_event.clear()
        self.worker.submit("capture", {"trigger": "manual"})

        def capture(payload):
            self.worker.stop_event.set()
            raise error

        with patch.object(self.worker, "capture", side_effect=capture):
            self.worker.loop()

    def test_invalid_credentials_pause_automatic_retries(self):
        self.run_one_failure(AuthRequired(401, "Fictitious credential expired"))
        self.assertTrue(self.worker.state["requires_attention"])
        self.assertIsNone(self.worker.state["retry_at"])
        self.assertEqual(self.worker.state["last_job_status"], "failed")
        restarted = self.new_worker()
        self.assertTrue(restarted.state["requires_attention"])

    def test_missing_permissions_pause_automatic_retries(self):
        self.run_one_failure(AccessDenied(403, "Fictitious permission denied"))
        self.assertTrue(self.worker.state["requires_attention"])
        self.assertIsNone(self.worker.state["retry_at"])

    def test_partial_permissions_keep_worker_online_and_automatic_capture_available(self):
        config = FakeSettings().read()
        config["channels"] = [{"id":"100"},{"id":"200"}]
        self.worker.settings = Mock()
        self.worker.settings.read.return_value = config
        self.worker.credentials = Mock()
        self.worker.credentials.get.return_value = "synthetic-test-credential"

        class PartlyReadableClient:
            def list_messages(inner_self, channel_id, before=None):
                if channel_id == "100":
                    raise AccessDenied(403,"Fictitious missing access")
                return [{"id":"300","channel_id":"200","author":{"id":"400"},"content":"Fictitious preserved message","timestamp":"2026-10-22T14:00:00Z"}]

        capture = self.worker.capture
        def one_capture(payload):
            try:
                return capture(payload)
            finally:
                self.worker.stop_event.set()
        self.worker.submit("capture", {"trigger":"manual"})
        with patch("discord_archive.worker.DiscordClient",return_value=PartlyReadableClient()),patch.object(self.worker,"capture",side_effect=one_capture):
            self.worker.loop()
        self.assertEqual(self.worker.state["last_job_status"],"partial")
        self.assertEqual(self.worker.state["permission_denied_channels"],["100"])
        self.assertIsNotNone(self.worker.state["last_warning"])
        self.assertFalse(self.worker.state["requires_attention"])
        self.assertIsNone(self.worker.state["offline_since"])
        self.assertIsNone(self.worker.state["retry_at"])
        self.assertIsNone(self.worker.state["last_error"])
        self.assertIsNotNone(self.worker.state["last_success_at"])
        self.assertEqual(self.store.list_runs("100")[0]["status"],"failed")
        self.assertEqual(self.store.list_runs("200")[0]["status"],"success")
        restarted = self.new_worker()
        self.assertFalse(restarted.state["requires_attention"])
        self.assertEqual(restarted.state["permission_denied_channels"],["100"])

    def test_member_example_is_resolved_through_history_exact_match(self):
        config = FakeSettings().read()
        config.update(channels=[{'id':'100','label':'测试频道'}], target_author_id='',
                      target_message_url='https://discord.com/channels/10/100/300')
        self.worker.settings = Mock()
        self.worker.settings.read.side_effect = lambda: copy.deepcopy(config)
        self.worker.settings.update.side_effect = lambda change: (config.update(change) or copy.deepcopy(config))
        self.worker.credentials = Mock()
        self.worker.credentials.get.return_value = 'fictitious-local-credential'
        self.worker.state['active_job'] = {'type':'capture','id':'fictitious-job'}
        example = {'id':'300','channel_id':'100','author':{'id':'400'},
                   'timestamp':'2026-10-22T14:00:00Z','content':'虚构的群主示例'}

        class MemberClient:
            def get(inner_self, path, params=None):
                self.assertEqual(path, '/channels/100/messages')
                self.assertEqual(params, {'around':'300','limit':1})
                return [example]

            def list_messages(inner_self, channel_id, before=None):
                return [example]

        with patch('discord_archive.worker.DiscordClient', return_value=MemberClient()):
            result = self.worker.capture({'trigger':'manual'})
        self.assertEqual(result['status'], 'success')
        self.assertEqual(config['target_author_id'], '400')
        self.assertEqual(self.store.channel_status('100')['guild_id'], '10')
        self.assertIsNone(self.worker.state['target_resolution_warning'])
        self.assertIn('测试频道', self.worker.state['active_job']['message'])
        self.assertIn('1 条', self.worker.state['active_job']['message'])

    def test_missing_or_forbidden_example_does_not_guess_author_or_stop_archive(self):
        for forbidden in (False, True):
            with self.subTest(forbidden=forbidden):
                config = FakeSettings().read()
                config.update(channels=[{'id':'100'}],target_author_id='',
                              target_message_url='https://discord.com/channels/10/100/300')
                self.worker.settings = Mock()
                self.worker.settings.read.return_value = config
                self.worker.credentials = Mock()
                self.worker.credentials.get.return_value = 'fictitious-local-credential'
                neighbor = {'id':'301','channel_id':'100','author':{'id':'999'},
                            'timestamp':'2026-10-22T14:00:00Z','content':'虚构邻近消息，不是示例作者'}

                class MemberClient:
                    def get(inner_self, path, params=None):
                        if forbidden:
                            raise AccessDenied(403, 'Fictitious unreadable example')
                        return [neighbor]

                    def list_messages(inner_self, channel_id, before=None):
                        return [neighbor]

                with patch('discord_archive.worker.DiscordClient', return_value=MemberClient()):
                    result = self.worker.capture({'trigger':'manual'})
                self.assertEqual(result['status'], 'success')
                self.worker.settings.update.assert_not_called()
                self.assertEqual(config['target_author_id'], '')
                self.assertIsNotNone(self.worker.state['target_resolution_warning'])
                self.assertIn('示例消息', self.worker.state['last_warning'])

    def test_network_failures_continue_with_bounded_backoff(self):
        first_delay = None
        for attempt in range(8):
            before = datetime.now(timezone.utc)
            self.run_one_failure(DiscordAPIError(0, "Fictitious outage"))
            delay = (parse_time(self.worker.state["retry_at"]) - before).total_seconds()
            if first_delay is None:
                first_delay = delay
            self.assertGreaterEqual(delay, 29)
            self.assertLessEqual(delay, 1802)
            self.assertFalse(self.worker.state["requires_attention"])
            self.assertEqual(self.worker.state["failures"], attempt + 1)
        self.assertGreater(delay, first_delay)
        restarted = self.new_worker()
        self.assertEqual(restarted.state["failures"], 8)
        self.assertIsNotNone(restarted.state["offline_since"])

    def test_long_rate_limit_survives_restart_without_early_request(self):
        before = datetime.now(timezone.utc)
        self.run_one_failure(DiscordAPIError(429, "Fictitious limit", retry_after=600))
        retry_at = parse_time(self.worker.state["retry_at"])
        self.assertGreaterEqual(retry_at, before + timedelta(seconds=600))
        restarted = self.new_worker()
        self.assertGreaterEqual(parse_time(restarted.state["retry_at"]), retry_at)
        self.assertFalse(restarted.state["requires_attention"])

    def test_reset_after_local_reconfiguration_clears_attention(self):
        self.run_one_failure(AuthRequired(401, "Fictitious credential expired"))
        self.worker.reset_attention()
        self.assertFalse(self.worker.state["requires_attention"])
        self.assertEqual(self.worker.state["failures"], 0)
        self.assertIsNone(self.worker.state["last_error"])
        self.assertIsNotNone(self.worker.state["retry_at"])


if __name__ == "__main__":
    unittest.main()
