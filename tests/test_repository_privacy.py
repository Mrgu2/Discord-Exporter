import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('repository_privacy', Path(__file__).parents[1] / 'scripts/check_repository_privacy.py')
privacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(privacy)


class RepositoryPrivacyTests(unittest.TestCase):
    def test_prose_fingerprints_and_private_file_names(self):
        self.assertTrue(privacy.inspect_file('docs/report.md', b'output/12345678-1234-1234-1234-123456789abc/'))
        self.assertTrue(privacy.inspect_file('docs/report.md', b'a' * 64))
        for path in ['credentials.json', 'archive.sqlite3-wal', 'private.bundle', '.ssh/id_ed25519']:
            self.assertTrue(privacy.inspect_file(path, b'example'))
        self.assertFalse(privacy.inspect_file('tests/example.py', b"owner = 'owner@example.com'"))

    def test_public_images_require_exact_reviewed_bytes(self):
        root = Path(__file__).parents[1]
        for path in privacy.PUBLIC_BINARY_SHA256:
            content = (root / path).read_bytes()
            self.assertFalse(privacy.inspect_file(path, content))
            self.assertIn(('binary file requires privacy review', path), privacy.inspect_file(path, content + b'changed'))

    def test_deleted_history_reused_blob_and_staged_only_data_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)
            git('init', '-q')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@users.noreply.github.com')
            (root / 'public.txt').write_text('fixture content\n')
            git('add', '.')
            git('commit', '-qm', 'fixture')
            (root / 'credentials.json').write_text('fixture content\n')
            git('add', '.')
            git('commit', '-qm', 'reuse identical content under private name')
            git('rm', 'credentials.json')
            git('commit', '-qm', 'remove private file from head')
            (root / 'pending.md').write_text('fixture ' + 'b' * 64)
            git('add', 'pending.md')
            (root / 'pending.md').write_text('clean working tree copy\n')
            findings, commits, blobs = privacy.inspect_repository(root)
            self.assertIn(('private/generated file', 'credentials.json'), findings)
            self.assertIn(('content fingerprint in prose', 'pending.md'), findings)
            self.assertEqual(commits, 3)


if __name__ == '__main__':
    unittest.main()
