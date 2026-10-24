import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from discord_archive.phone_sessions import PhoneSessions


class PhoneSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.sessions = PhoneSessions(self.root, 'fictional-pairing-code')

    def tearDown(self): self.temp.cleanup()

    def test_pairing_survives_restart_without_saving_cookie_or_code(self):
        with patch('discord_archive.phone_sessions.time.time', return_value=100):
            self.sessions['fictional-cookie'] = 200
            reloaded = PhoneSessions(self.root, 'fictional-pairing-code')
            self.assertEqual(reloaded.get('fictional-cookie',0),200)
            self.assertEqual(reloaded.get('unpaired',0),0)
            contents = self.sessions.path.read_text()
            self.assertNotIn('fictional-cookie',contents);self.assertNotIn('fictional-pairing-code',contents)
            self.assertEqual(stat.S_IMODE(self.sessions.path.stat().st_mode),0o600)

    def test_expired_sessions_are_rejected_and_not_extended_by_reads(self):
        with patch('discord_archive.phone_sessions.time.time',return_value=100): self.sessions['cookie']=200
        with patch('discord_archive.phone_sessions.time.time',return_value=150): self.assertEqual(self.sessions.get('cookie',0),200)
        with patch('discord_archive.phone_sessions.time.time',return_value=200):
            self.assertEqual(self.sessions.get('cookie',0),0)
            self.assertEqual(PhoneSessions(self.root,'fictional-pairing-code').get('cookie',0),0)

    def test_code_rotation_and_corrupt_files_require_pairing(self):
        self.sessions['cookie']=9999999999
        self.assertEqual(PhoneSessions(self.root,'changed-code').get('cookie',0),0)
        for content in ('invalid', '[]', '{"sessions": []}'):
            self.sessions.path.write_text(content)
            self.assertEqual(PhoneSessions(self.root,'fictional-pairing-code').get('cookie',0),0)

    def test_storage_failure_does_not_issue_an_unpersisted_session(self):
        with patch('discord_archive.phone_sessions.atomic_json',side_effect=OSError('synthetic disk full')):
            with self.assertRaises(OSError): self.sessions['cookie']=9999999999
        self.assertEqual(self.sessions.get('cookie',0),0)

    def test_persisted_session_count_is_bounded_and_expired_entries_pruned(self):
        with patch('discord_archive.phone_sessions.time.time',return_value=100):
            for index in range(258): self.sessions[str(index)]=200+index
            self.assertEqual(len(json.loads(self.sessions.path.read_text())['sessions']),256)
            self.assertEqual(self.sessions.get('0',0),0)
        with patch('discord_archive.phone_sessions.time.time',return_value=1000):
            self.sessions['new']=2000
            self.assertEqual(len(json.loads(self.sessions.path.read_text())['sessions']),1)


if __name__=='__main__': unittest.main()
