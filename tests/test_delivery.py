"""Fictional destinations only; no external messages or real credentials."""
import copy
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from discord_archive.delivery import DeliveryError, DeliveryOutbox, send_file
from discord_archive.delivery_config import normalize_delivery
from discord_archive.settings import Credentials, Settings


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = Settings(self.root)
        self.credentials = Mock()
        self.credentials.get.return_value = 'fake-secret'
        self.outbox = DeliveryOutbox(self.root, self.settings, self.credentials)

    def configure(self, **overrides):
        self.settings.update({'delivery': {'email': {'host': 'smtp.example.com', 'sender': 'from@example.com',
            'recipients': ['to@example.com']}, 'telegram': {'chat_id': '123456'}, **overrides}})

    def test_terminal_history_is_bounded_without_deleting_images_or_pending_work(self):
        self.configure()
        key = self.outbox.enqueue_test('telegram')
        image = self.root / self.outbox.items[key]['path']
        rows = {}
        for test, count in ((True, 140), (False, 1040)):
            for index in range(count):
                identity = f'{test}-{index}'
                rows[identity] = {**self.outbox.items[key], 'id': identity, 'test': test, 'status': 'sent'}
        rows['unsent'] = {**self.outbox.items[key], 'id': 'unsent', 'test': False}
        self.outbox._save(rows)
        restarted = DeliveryOutbox(self.root, self.settings, self.credentials)
        self.assertEqual(len(restarted.items), 1101)
        self.assertIn('unsent', restarted.items)
        self.assertEqual(restarted.due(), None)  # formal channel is disabled
        self.assertTrue(image.exists())
        self.assertNotIn('True-0', restarted.items)
        self.assertIn('False-1039', restarted.items)

    def test_pending_queue_limit_preserves_existing_tasks(self):
        self.configure()
        key = self.outbox.enqueue_test('telegram')
        self.outbox._save({str(i): {**self.outbox.items[key], 'id': str(i)} for i in range(1000)})
        with self.assertRaisesRegex(DeliveryError, '1000'):
            self.outbox.enqueue_test('telegram')
        self.assertEqual(len(self.outbox.items), 1000)

    def test_defaults_validation_partial_update_and_separate_secrets(self):
        self.assertFalse(any(x['enabled'] for x in self.settings.read()['delivery'].values()))
        self.configure(telegram={'enabled': True, 'chat_id': '123456'})
        self.settings.update({'delivery': {'discord': {'enabled': True}}})
        self.assertTrue(self.settings.read()['delivery']['telegram']['enabled'])
        for value in ([], {'telegram': {'enabled': 'yes'}}, {'email': {'security': 'plain'}},
                {'email': {'host': 42}}, {'email': {'recipients': ['a@b.com\r\nBcc:x@y.com']}},
                {'email': {'recipients': ['']}}, {'discord': {'webhook': 'secret'}}, {'unknown': {}},
                {'telegram': {'enabled': True, 'chat_id': ''}}, {'email': []}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.settings.update({'delivery': value})
        self.assertNotIn('fake-secret', self.settings.path.read_text())
        self.assertEqual(self.outbox.summary(), [])

    def test_channel_can_be_disabled_without_a_copy_directory(self):
        self.configure(discord={'enabled': True})
        self.settings.update({'auto_export': {'enabled': True}})
        value = self.settings.update({'delivery': {'discord': {'enabled': False}}})
        self.assertFalse(value['delivery']['discord']['enabled'])

    def test_new_credential_kinds_do_not_fall_back_to_model_key(self):
        with patch.dict(os.environ, {'ARCHIVE_MODEL_KEY': 'model-secret', 'DISCORD_ARCHIVE_CREDENTIAL_STORE': 'file'}, clear=True):
            credentials = Credentials(self.root)
            self.assertIsNone(credentials.get('delivery_email'))
            credentials.set('delivery_email', 'mail-secret')
            credentials.set('delivery_discord', 'webhook-secret')
            self.assertEqual(credentials.get('delivery_email'), 'mail-secret')
            self.assertEqual(credentials.get('delivery_discord'), 'webhook-secret')
            self.assertEqual(credentials.path.stat().st_mode & 0o777, 0o600)

    def test_test_send_works_when_disabled_and_is_durable(self):
        self.configure()
        key = self.outbox.enqueue_test('telegram')
        restarted = DeliveryOutbox(self.root, self.settings, self.credentials)
        self.assertEqual(restarted.due(), key)
        with patch('discord_archive.delivery.send_file') as send:
            self.assertEqual(restarted.send(key)['status'], 'sent')
            send.assert_called_once()
            self.assertEqual(restarted.send(key)['deduplicated'], True)
            send.assert_called_once()
        self.assertIsNone(restarted.due())
        serialized = json.dumps(restarted.summary())
        self.assertNotIn('fake-secret', serialized)
        self.assertNotIn('options', serialized)
        self.assertNotIn('chat_id', serialized)

    def test_retry_persists_and_manual_retry_uses_corrected_destination(self):
        self.configure()
        key = self.outbox.enqueue_test('telegram')
        with patch('discord_archive.delivery.send_file', side_effect=DeliveryError('发送失败')):
            self.assertEqual(self.outbox.send(key)['status'], 'retrying')
        restarted = DeliveryOutbox(self.root, self.settings, self.credentials)
        self.assertIsNone(restarted.due())
        self.assertEqual(restarted.due(datetime.now(timezone.utc) + timedelta(minutes=1)), key)
        self.settings.update({'delivery': {'telegram': {'chat_id': '654321'}}})
        restarted.retry(key)
        with patch('discord_archive.delivery.send_file') as send:
            restarted.send(key)
            self.assertEqual(send.call_args.args[1]['chat_id'], '654321')
        with self.assertRaises(ValueError): restarted.retry(key)

    def test_retry_limit_then_explicit_retry(self):
        self.configure()
        key = self.outbox.enqueue_test('telegram')
        with patch('discord_archive.delivery.send_file', side_effect=RuntimeError('fake-secret')):
            for _ in range(8): self.outbox.send(key)
        self.assertEqual(self.outbox.summary()[0]['status'], 'failed')
        self.assertIsNone(self.outbox.due(datetime.now(timezone.utc) + timedelta(days=1)))
        self.assertNotIn('fake-secret', json.dumps(self.outbox.summary()))
        self.outbox.retry(key)
        self.assertEqual(self.outbox.due(), key)

    def test_auto_images_deduplicated_per_channel_page_and_scale(self):
        self.configure(telegram={'enabled': True, 'chat_id': '123456'}, discord={'enabled': True})
        test = self.outbox.enqueue_test('email')
        path = self.outbox.items[test]['path']
        result = {'images': ['/' + path], 'draft': {'title': '虚构稿件'},
            'single_columns': [{'images': ['/' + path]}]}
        for _ in range(2):
            self.outbox.enqueue_render(result, draft_id='fake-draft', scale=1, target='all')
        self.assertEqual(len(self.outbox.items), 3)
        # A retry of the same render keeps its captured destination even after configuration edits.
        self.settings.update({'delivery': {'telegram': {'chat_id': '654321'}}})
        self.outbox.enqueue_render(result, draft_id='fake-draft', scale=1, target='all')
        self.assertEqual(len(self.outbox.items), 3)
        automatic = [x for x in self.outbox.items.values() if not x['test'] and x['channel'] == 'telegram'][0]
        self.assertEqual(automatic['options']['chat_id'], '123456')
        # Disabling auto pushes suspends existing pending automatic entries.
        self.settings.update({'delivery': {'telegram': {'enabled': False}, 'discord': {'enabled': False}}})
        with patch('discord_archive.delivery.send_file'): self.outbox.send(test)
        self.assertIsNone(self.outbox.due())
        self.settings.update({'delivery': {'telegram': {'enabled': True}}})
        self.assertIsNotNone(self.outbox.due())

    def test_all_pages_and_columns_from_each_density_are_queued_independently(self):
        self.configure(telegram={'enabled': True, 'chat_id': '123456'}, discord={'enabled': True})
        test_id = self.outbox.enqueue_test('telegram')
        source = self.root / self.outbox.items[test_id]['path']
        urls = []
        for name in ('scale-1/page-1.png', 'scale-1/page-2.png', 'scale-1/column.png', 'scale-2/page-1.png'):
            target = self.root / 'output' / name
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(source.read_bytes())
            urls.append('/output/' + name)
        metadata = {'image_variants': {
            '1': {'images': urls[:2], 'single_columns': [{'images': [urls[2]]}]},
            '2': {'images': [urls[3]], 'single_columns': []}}}
        for scale in (1, 2):
            self.outbox.enqueue_render({'draft': metadata}, draft_id='fake', scale=scale, target='all')
        self.assertEqual(len(self.outbox.items), 9)
        automatic = [x for x in self.outbox.items.values() if not x['test']]
        with patch('discord_archive.delivery.send_file') as send:
            for item in automatic: self.outbox.send(item['id'])
            self.assertEqual(send.call_count, 8)
        self.assertEqual(len({x['path'] for x in automatic}), 4)
        self.assertTrue(all(x['status'] == 'sent' for x in self.outbox.items.values() if not x['test']))

    def test_paused_queue_skips_automatic_but_allows_explicit_retry(self):
        self.configure(telegram={'enabled': True, 'chat_id': '123'})
        test = self.outbox.enqueue_test('telegram')
        result = {'images': ['/' + self.outbox.items[test]['path']]}
        self.outbox.enqueue_render(result, draft_id='fake', scale=1, target='main')
        auto = [key for key in self.outbox.items if key != test][0]
        with patch('discord_archive.delivery.send_file'):
            self.outbox.send(test)
        self.assertEqual(self.outbox.due(), auto)
        self.assertIsNone(self.outbox.due(manual_only=True))
        self.assertFalse(self.outbox.is_manual(auto))
        with patch('discord_archive.delivery.send_file', side_effect=DeliveryError('虚构网络错误')):
            self.outbox.send(auto)
        self.outbox.retry(auto)
        self.assertEqual(self.outbox.due(manual_only=True), auto)
        self.assertTrue(self.outbox.is_manual(auto))

    def test_paths_cannot_escape_output_or_follow_external_symlink(self):
        self.configure(discord={'enabled': True})
        outside = self.root / 'private.png'; outside.write_bytes(b'\x89PNG\r\n\x1a\n')
        folder = self.root / 'output'; folder.mkdir(exist_ok=True)
        (folder / 'link.png').symlink_to(outside)
        for url in ('/output/../private.png', '/output/link.png', 'https://example.com/a.png'):
            with self.subTest(url=url), self.assertRaises(DeliveryError):
                self.outbox.enqueue_render({'images': [url]}, draft_id='fake', scale=1, target='main')

    def test_platform_upload_receipts_and_payload(self):
        self.configure()
        key = self.outbox.enqueue_test('telegram')
        path = self.root / self.outbox.items[key]['path']
        for channel, secret, receipt in [('telegram', '123:FAKE_token', {'ok': True, 'result': {}}),
                ('discord', 'https://discord.com/api/webhooks/123/FAKE_token', {'id': '123'})]:
            response = Mock(); response.__enter__ = Mock(return_value=io.BytesIO(json.dumps(receipt).encode())); response.__exit__ = Mock()
            opener = Mock(); opener.open.return_value = response
            with patch('discord_archive.delivery.build_opener', return_value=opener):
                send_file(channel, {'chat_id': '123'}, secret, path, '测试标题')
                request = opener.open.call_args.args[0]
                self.assertIn(path.read_bytes(), request.data)
                self.assertIn('测试标题'.encode(), request.data)
                if channel == 'discord': self.assertIn(b'allowed_mentions', request.data)
            with patch('discord_archive.delivery.build_opener') as factory:
                factory.return_value.open.side_effect = HTTPError('url/' + secret, 429, secret, {}, None)
                with self.assertRaisesRegex(DeliveryError, '限流') as error:
                    send_file(channel, {'chat_id': '123'}, secret, path, '测试')
                self.assertNotIn(secret, str(error.exception))
        for secret in ('http://discord.com/api/webhooks/123/x', 'https://evil.example/api/webhooks/123/x',
                       'https://discord.com/api/webhooks/123/x?foo=1'):
            with self.assertRaises(DeliveryError): send_file('discord', {}, secret, path, '测试')

    def test_transport_rejects_bad_receipts_and_oversize_images_without_leaking_secrets(self):
        self.configure()
        key = self.outbox.enqueue_test('telegram'); path = self.root / self.outbox.items[key]['path']
        for channel, secret in [('telegram', '123:FAKE_token'),
                ('discord', 'https://discord.com/api/webhooks/123/FAKE_token')]:
            response = Mock(); response.__enter__ = Mock(return_value=io.BytesIO(b'{"ok": false}')); response.__exit__ = Mock()
            with patch('discord_archive.delivery.build_opener') as factory:
                factory.return_value.open.return_value = response
                with self.assertRaises(DeliveryError) as raised:
                    send_file(channel, {'chat_id': '123'}, secret, path, '测试')
                self.assertNotIn(secret, str(raised.exception))
            with patch('discord_archive.delivery.build_opener') as factory:
                factory.return_value.open.side_effect = OSError(secret)
                with self.assertRaises(DeliveryError) as raised:
                    send_file(channel, {'chat_id': '123'}, secret, path, '测试')
                self.assertNotIn(secret, str(raised.exception))
        fake_path = Mock(); fake_path.stat.return_value.st_size = 60 * 1024 * 1024
        for channel, secret in [('telegram', '123:FAKE_token'),
                ('discord', 'https://discord.com/api/webhooks/123/FAKE_token')]:
            with self.assertRaisesRegex(DeliveryError, '上限'):
                send_file(channel, {'chat_id': '123'}, secret, fake_path, '测试')
            fake_path.read_bytes.assert_not_called()

    def test_email_attachment_and_tls_modes(self):
        self.configure()
        key = self.outbox.enqueue_test('email'); path = self.root / self.outbox.items[key]['path']
        options = self.settings.read()['delivery']['email']
        for security, smtp_name in [('ssl', 'SMTP_SSL'), ('starttls', 'SMTP')]:
            smtp = Mock(); smtp.send_message.return_value = {}
            with patch('discord_archive.delivery.smtplib.' + smtp_name) as factory:
                factory.return_value.__enter__.return_value = smtp
                send_file('email', {**options, 'security': security}, 'mail-secret', path, '测试')
                message = smtp.send_message.call_args.args[0]
                self.assertEqual(next(message.iter_attachments()).get_payload(decode=True), path.read_bytes())
                smtp.login.assert_called_once_with('from@example.com', 'mail-secret')
                self.assertEqual(smtp.starttls.call_count, int(security == 'starttls'))

class DeliveryWorkflowTests(unittest.TestCase):
    def test_scheduled_render_enqueues_without_copy_and_copy_failure_does_not_block_push(self):
        from discord_archive.auto_export import ScheduledExporter
        from discord_archive.export_schedule import normalize_auto_export
        slot = {'key': 'auto-export:2026-10-23:16:15', 'scheduled_at': '2026-10-23T20:15:00Z', 'market_date': '2026-10-23'}
        for copy_failure in (False, True):
            with self.subTest(copy_failure=copy_failure), tempfile.TemporaryDirectory() as directory:
                settings = Settings(directory); credentials = Mock(); credentials.get.return_value = 'fake'
                settings.update({'delivery': {'discord': {'enabled': True}},
                    'auto_export': {'enabled': True}, 'export': {'copy_directory': directory + '/copies' if copy_failure else ''}})
                outbox = DeliveryOutbox(directory, settings, credentials)
                test_id = outbox.enqueue_test('discord')
                url = '/' + outbox.items[test_id]['path']
                worker = Mock(); worker.delivery = outbox; worker.settings = settings
                worker.capture.return_value = {'status': 'success'}
                worker.drafts.generate.return_value = {'id': 'fake-draft'}
                worker.drafts.render.return_value = {'images': [url], 'draft': {'id': 'fake-draft', 'export_copy': {
                    'enabled': copy_failure, 'copied': 0, 'failed': int(copy_failure)}}}
                exporter = ScheduledExporter(directory)
                if copy_failure:
                    with self.assertRaisesRegex(ValueError, '另存'): exporter.run(worker, slot)
                else:
                    self.assertEqual(exporter.run(worker, slot)['status'], 'success')
                queued = [row for row in outbox.items.values() if not row['test']]
                self.assertEqual(len(queued), 1)
                with patch('discord_archive.delivery.send_file') as send:
                    self.assertEqual(outbox.send(queued[0]['id'])['status'], 'sent')
                    send.assert_called_once()
                if copy_failure:
                    worker.drafts.render.return_value['draft']['export_copy'].update(copied=1, failed=0)
                    exporter.run(worker, slot)
                    self.assertEqual(len(outbox.items), 2)
                    worker.capture.assert_called_once()

    def test_paused_worker_still_sends_explicit_test_without_resuming_automatic_tasks(self):
        import threading
        from discord_archive.store import ArchiveStore
        from discord_archive.worker import Worker
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(directory)
            settings.update({'delivery': {'telegram': {'chat_id': '123'}}})
            credentials = Mock(); credentials.get.return_value = 'fake'
            store = ArchiveStore(Path(directory) / 'data/archive.sqlite3')
            try:
                worker = Worker(store, directory, settings, credentials, Mock())
                worker.set_automatic_paused(True)
                key = worker.delivery.enqueue_test('telegram')
                timer = threading.Timer(0.1, worker.stop_event.set)
                timer.start()
                try:
                    with patch('discord_archive.delivery.send_file') as send, patch.object(worker, 'capture') as capture:
                        send.side_effect = lambda *args: worker.stop_event.set()
                        worker.loop()
                        self.assertEqual(worker.delivery.items[key]['status'], 'sent')
                        send.assert_called_once(); capture.assert_not_called()
                        self.assertTrue(worker.state['automatic_paused'])
                finally:
                    timer.cancel()
            finally: store.close()

    def test_worker_sends_durable_outbox_without_discord_capture_credentials(self):
        from discord_archive.store import ArchiveStore
        from discord_archive.worker import Worker
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(directory)
            settings.update({'delivery': {'telegram': {'chat_id': '123'}}})
            credentials = Mock(); credentials.get.side_effect = lambda kind: 'fake' if kind == 'delivery_telegram' else None
            store = ArchiveStore(Path(directory) / 'data/archive.sqlite3')
            try:
                worker = Worker(store, directory, settings, credentials, Mock())
                key = worker.delivery.enqueue_test('telegram')
                def sent(*args): worker.stop_event.set()
                with patch('discord_archive.delivery.send_file', side_effect=sent): worker.loop()
                self.assertEqual(worker.delivery.items[key]['status'], 'sent')
                self.assertFalse(worker._queued_delivery)
                self.assertEqual(worker.status()[0]['delivery'][0]['status'], 'sent')
            finally: store.close()


if __name__ == '__main__': unittest.main()
