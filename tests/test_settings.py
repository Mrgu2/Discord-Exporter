"""Credential storage checks with fake secrets and a mocked macOS keychain."""

import json
import os
import tempfile
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from discord_archive.settings import Credentials, Settings, atomic_json


class CredentialRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.credentials = Credentials(self.root)
        real_exists = Path.exists
        self.exists_patch = patch(
            "discord_archive.settings.Path.exists",
            autospec=True,
            side_effect=lambda path: str(path) == "/usr/bin/security" or real_exists(path),
        )
        self.exists_patch.start()
        self.environment_patch = patch.dict(os.environ, {}, clear=True)
        self.environment_patch.start()

    def tearDown(self):
        self.environment_patch.stop()
        self.exists_patch.stop()
        self.temporary.cleanup()

    def test_keychain_update_retires_only_that_stale_fallback(self):
        atomic_json(self.credentials.path, {"discord": "fictitious-old", "model": "fictitious-model"})
        fake_process = SimpleNamespace(returncode=0, stdout="fictitious-new\n")
        with patch("discord_archive.settings.subprocess.run", return_value=fake_process) as run:
            self.assertEqual(self.credentials.set("discord", "fictitious-new"), "keychain")
            self.assertEqual(self.credentials.get("discord"), "fictitious-new")
            self.assertEqual(self.credentials.get("model"), "fictitious-model")
        self.assertEqual(json.loads(self.credentials.path.read_text()), {"model": "fictitious-model"})
        self.assertEqual(self.credentials.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(run.call_count, 2)

    def test_failed_keychain_write_keeps_new_private_fallback_usable(self):
        atomic_json(self.credentials.path, {"discord": "fictitious-old", "model": "fictitious-model"})
        fake_process = SimpleNamespace(returncode=1, stdout="")
        with patch("discord_archive.settings.subprocess.run", return_value=fake_process):
            self.assertEqual(self.credentials.set("discord", "fictitious-new"), "private_file")
            self.assertEqual(self.credentials.get("discord"), "fictitious-new")
            self.assertEqual(self.credentials.get("model"), "fictitious-model")
        self.assertEqual(self.credentials.path.stat().st_mode & 0o777, 0o600)

    def test_environment_override_is_explicit_and_never_rewritten(self):
        atomic_json(self.credentials.path, {"discord": "fictitious-local"})
        with patch.dict(os.environ, {"DISCORD_ARCHIVE_TOKEN": "fictitious-environment"}):
            self.assertEqual(self.credentials.get("discord"), "fictitious-environment")
        self.assertEqual(json.loads(self.credentials.path.read_text())["discord"], "fictitious-local")

    def test_keychain_read_timeout_does_not_break_status(self):
        with patch('discord_archive.settings.subprocess.run', side_effect=subprocess.TimeoutExpired('security', 2)):
            self.assertIsNone(self.credentials.get('discord'))

    def test_keychain_write_timeout_uses_private_fallback(self):
        with patch('discord_archive.settings.subprocess.run', side_effect=subprocess.TimeoutExpired('security', 12)):
            self.assertEqual(self.credentials.set('discord', 'fictitious-new'), 'private_file')
        self.assertEqual(self.credentials.get('discord'), 'fictitious-new')
        self.assertEqual(self.credentials.path.stat().st_mode & 0o777, 0o600)

    def test_new_speaker_link_invalidates_cached_author_but_keeps_explicit_override(self):
        settings=Settings(self.root)
        settings.update({'target_message_url':'https://discord.com/channels/1/2/3','target_author_id':'100'})
        settings.update({'target_message_url':'https://discord.com/channels/1/2/4','target_author_id':'100'})
        self.assertEqual(settings.read()['target_author_id'], '')
        settings.update({'target_message_url':'https://discord.com/channels/1/2/5','target_author_id':'200'})
        self.assertEqual(settings.read()['target_author_id'], '200')

    def test_deselected_channels_remain_available_after_config_roundtrip(self):
        settings=Settings(self.root)
        settings.update({'channels':[{'id':'100','label':'答疑','kind':'qa','enabled':False}]})
        row=settings.read()['channels'][0]
        self.assertFalse(row['enabled'])
        self.assertEqual(row['kind'], 'qa')
        settings.update({'channels':[{**row,'enabled':True}]})
        self.assertTrue(settings.read()['channels'][0]['enabled'])


if __name__ == "__main__":
    unittest.main()
