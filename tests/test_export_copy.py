import concurrent.futures
import errno
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from discord_archive.export_copy import copy_export


PNG = b'\x89PNG\r\n\x1a\n'


class ExportCopyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / 'output' / 'draft' / 'scale-1' / '答疑存档-2026-10-23-01.png'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(PNG + b'original PNG bytes')
        self.directory = self.root / 'chosen' / 'exports'

    def tearDown(self):
        self.temporary.cleanup()

    def copy(self, directory=None, source=None):
        return copy_export(source or self.source, self.directory if directory is None else directory,
            draft_id='draft', render_scale=1, sequence=1)

    def test_empty_directory_disables_copy_even_without_a_source(self):
        for directory in (None, '', '  '):
            self.assertIsNone(copy_export(self.root / 'missing.png', directory, draft_id='draft'))
        self.assertFalse(self.directory.exists())

    def test_creates_missing_directory_and_preserves_source_bytes(self):
        before = self.source.read_bytes()
        target = self.copy()
        self.assertEqual(target, self.directory / self.source.name)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse(target.samefile(self.source))
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(list(self.directory.iterdir()), [target])

    def test_tilde_expands_and_relative_paths_are_rejected(self):
        with patch.dict(os.environ, {'HOME': str(self.root)}):
            target = self.copy('~/local-exports')
        self.assertEqual(target.parent, self.root / 'local-exports')
        for directory in ('exports', '../exports', 12, '/tmp/invalid\x00path'):
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                self.copy(directory)

    def test_identical_content_reuses_existing_file_without_changing_inode(self):
        target = self.copy()
        inode = target.stat().st_ino
        self.assertEqual(self.copy(), target)
        self.assertEqual(target.stat().st_ino, inode)
        self.assertEqual(list(self.directory.iterdir()), [target])

    def test_different_content_gets_a_version_without_overwriting_old_files(self):
        target = self.copy()
        before = target.read_bytes()
        self.source.write_bytes(PNG + b'new PNG bytes')
        second = self.copy()
        self.assertEqual(second.name, self.source.stem + '-版本02.png')
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(second.read_bytes(), self.source.read_bytes())
        self.assertEqual(self.copy(), second)
        self.assertEqual(len(list(self.directory.iterdir())), 2)

    def test_directory_symlink_is_resolved_and_existing_file_symlinks_are_skipped(self):
        self.directory.mkdir(parents=True)
        alias = self.root / 'folder-alias'
        alias.symlink_to(self.directory, target_is_directory=True)
        outside = self.root / 'private-file.png'
        outside.write_bytes(self.source.read_bytes())
        candidate = self.directory / self.source.name
        candidate.symlink_to(outside)
        target = self.copy(alias)
        self.assertEqual(target, self.directory / (self.source.stem + '-版本02.png'))
        self.assertTrue(candidate.is_symlink())
        self.assertEqual(outside.read_bytes(), self.source.read_bytes())

    def test_broken_symlink_and_directory_name_collisions_are_preserved(self):
        self.directory.mkdir(parents=True)
        first = self.directory / self.source.name
        first.symlink_to(self.root / 'missing-file')
        second = self.directory / (self.source.stem + '-版本02.png')
        second.mkdir()
        target = self.copy()
        self.assertEqual(target.name, self.source.stem + '-版本03.png')
        self.assertTrue(first.is_symlink())
        self.assertTrue(second.is_dir())

    def test_system_and_internal_archive_paths_are_rejected_before_writing(self):
        for directory in ('/', '/System/exports', '/Library/exports', '/Applications/exports',
                          self.root / 'output' / 'new', self.root / 'data' / 'new'):
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                self.copy(directory)
        alias = self.root / 'archive-alias'
        alias.symlink_to(self.root / 'output', target_is_directory=True)
        with self.assertRaises(ValueError):
            self.copy(alias / 'new')
        self.assertFalse((self.root / 'data').exists())
        self.assertFalse((self.root / 'output' / 'new').exists())

    def test_existing_file_cannot_be_used_as_directory(self):
        path = self.root / 'not-a-folder'
        path.write_bytes(b'preserve')
        with self.assertRaises(ValueError):
            self.copy(path)
        self.assertEqual(path.read_bytes(), b'preserve')

    def test_publication_failure_keeps_user_files_and_cleans_only_own_temp(self):
        self.directory.mkdir(parents=True)
        unrelated = self.directory / '.discord-export-unrelated.tmp'
        unrelated.write_bytes(b'preserve this user file')
        with (patch('discord_archive.export_copy.os.link', side_effect=PermissionError(errno.EACCES, 'denied')),
                self.assertRaisesRegex(ValueError, '目录权限')):
            self.copy()
        self.assertEqual(list(self.directory.iterdir()), [unrelated])
        self.assertEqual(unrelated.read_bytes(), b'preserve this user file')
        self.assertEqual(self.source.read_bytes(), PNG + b'original PNG bytes')

    def test_copy_failure_does_not_publish_partial_file(self):
        self.directory.mkdir(parents=True)
        with (patch('discord_archive.export_copy.os.fsync', side_effect=OSError(errno.ENOSPC, 'full')),
                self.assertRaisesRegex(ValueError, '可用空间')):
            self.copy()
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_source_is_read_in_bounded_chunks(self):
        content = PNG + b'x' * (3 * 1024 * 1024 + 37)
        self.source.write_bytes(content)
        original_open = Path.open
        reads = []

        class Reader:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *args): return self.stream.__exit__(*args)
            def fileno(self): return self.stream.fileno()
            def read(self, size=-1):
                reads.append(size)
                self_size.assertGreater(size, 0)
                self_size.assertLessEqual(size, 1024 * 1024)
                return self.stream.read(size)

        self_size = self

        def tracked_open(path, *args, **kwargs):
            stream = original_open(path, *args, **kwargs)
            return Reader(stream) if path == self.source else stream

        with patch.object(Path, 'open', tracked_open):
            target = self.copy()
        self.assertEqual(target.read_bytes(), content)
        self.assertGreater(len(reads), 3)

    def test_concurrent_identical_exports_converge_to_one_complete_file(self):
        self.directory.mkdir(parents=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            targets = list(executor.map(lambda _: self.copy(), range(16)))
        self.assertEqual(len(set(targets)), 1)
        self.assertEqual(targets[0].read_bytes(), self.source.read_bytes())
        self.assertEqual(list(self.directory.iterdir()), [targets[0]])

    def test_concurrent_different_content_preserves_both_complete_versions(self):
        other = self.root / 'another-source' / self.source.name
        other.parent.mkdir()
        other.write_bytes(PNG + b'another PNG')
        self.directory.mkdir(parents=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            targets = list(executor.map(lambda source: self.copy(source=source), (self.source, other)))
        self.assertEqual(len(set(targets)), 2)
        self.assertEqual({target.read_bytes() for target in targets},
            {self.source.read_bytes(), other.read_bytes()})
        self.assertEqual(len(list(self.directory.iterdir())), 2)

    def test_versions_are_bounded_without_overwriting_existing_files(self):
        self.directory.mkdir(parents=True)
        original = self.directory / self.source.name
        original.write_bytes(b'old user file')
        with patch('discord_archive.export_copy._MAX_VERSION', 1), self.assertRaisesRegex(ValueError, '版本过多'):
            self.copy()
        self.assertEqual(original.read_bytes(), b'old user file')
        self.assertEqual(list(self.directory.iterdir()), [original])

    def test_invalid_source_is_not_copied(self):
        self.source.write_bytes(b'not a PNG')
        with self.assertRaisesRegex(ValueError, 'PNG'):
            self.copy()
        self.assertEqual(list(self.directory.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
