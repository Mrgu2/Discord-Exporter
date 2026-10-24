import errno
import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from discord_archive.export_names import export_date_label, filename, publish_image


def png(red=0):
    def chunk(kind,body):
        return struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body)&0xffffffff)
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))
        +chunk(b'IDAT',zlib.compress(bytes((0,red,30,90))))+chunk(b'IEND',b''))


class ExportDateTests(unittest.TestCase):
    def test_selection_date_wins_over_generation_download_and_other_dates(self):
        metadata={'selection':{'start':'2026-10-23','end':'2026-10-23'},
            'date':'2026-10-24','export_date':'2026-10-25','created_at':'2026-10-26T14:00:00Z'}
        self.assertEqual(export_date_label(metadata),'2026-10-23')
        self.assertEqual(export_date_label({'selection':{'start':'2026-10-21','end':'2026-10-23'}}),
            '2026-10-21至2026-10-23')

    def test_saved_and_legacy_dates_are_validated_without_reading_current_day(self):
        self.assertEqual(export_date_label({'export_date':'2026-10-23','date':'2026-10-24'}),'2026-10-23')
        self.assertEqual(export_date_label({'export_date':'2026-10-22至2026-10-23'}),'2026-10-22至2026-10-23')
        self.assertEqual(export_date_label({'export_date':'../invalid','date':'2026-10-23'}),'2026-10-23')
        for value in ({},{'date':'2026-02-30'},{'created_at':'not a date'},
                      {'export_date':'2026-10-24至2026-10-23'}):
            with self.subTest(value=value):
                self.assertEqual(export_date_label(value),'未标日期')

    def test_latest_uses_selected_seeds_and_ranges_across_source_days(self):
        metadata={'scope':'latest','created_at':'2026-10-24T14:00:00Z'}
        self.assertEqual(export_date_label(metadata,seeds=[{'created_at':'2026-10-24T06:00:00Z'}]),'2026-10-23')
        self.assertEqual(export_date_label(metadata,seeds=[{'created_at':'2026-10-23T08:00:00Z'},
            {'created_at':'2026-10-24T08:00:00Z'}]),'2026-10-23至2026-10-24')

    def test_evidence_fallback_ignores_ancestors_followups_and_invalid_seed_dates(self):
        evidence={'contexts':[{'seed':{'created_at':'2026-10-24T06:00:00Z'},
            'reply_chain':[{'created_at':'2020-01-01T12:00:00Z'}],
            'followups':[{'created_at':'2027-01-01T12:00:00Z'}]},
            {'seed':{'created_at':'invalid'}}]}
        self.assertEqual(export_date_label({},evidence=evidence),'2026-10-23')
        self.assertEqual(export_date_label({},evidence={'selection':{'start':'2026-10-22','end':'2026-10-23'}}),
            '2026-10-22至2026-10-23')

    def test_new_york_boundary_tracks_both_dst_transitions(self):
        for stamp,expected in (('2026-03-08T07:59:59Z','2026-03-07'),
                               ('2026-03-08T08:00:00Z','2026-03-08'),
                               ('2026-11-01T08:59:59Z','2026-10-31'),
                               ('2026-11-01T09:00:00Z','2026-11-01')):
            with self.subTest(stamp=stamp):
                self.assertEqual(export_date_label({'created_at':stamp}),expected)

    def test_saved_timezone_and_boundary_take_precedence_over_current_settings(self):
        metadata={'created_at':'2026-10-23T07:30:00Z','market_timezone':'America/New_York','day_boundary_hour':4}
        self.assertEqual(export_date_label(metadata,config={'market_timezone':'Asia/Shanghai','day_boundary_hour':0}),
            '2026-10-22')
        self.assertEqual(export_date_label({'created_at':'2026-10-23T07:30:00Z'},config={'day_boundary_hour':0}),
            '2026-10-23')
        self.assertEqual(export_date_label({'created_at':'2026-10-24T06:00:00Z',
            'market_timezone':'invalid','day_boundary_hour':'invalid'}),'2026-10-23')


class FilenameTests(unittest.TestCase):
    def test_main_hidpi_and_channel_names_are_distinct(self):
        metadata={'export_date':'2026-10-23'}
        self.assertEqual(filename(metadata,1),'答疑存档-2026-10-23-01.png')
        self.assertEqual(filename(metadata,2,render_scale=2),'答疑存档-2026-10-23-HiDPI-02.png')
        self.assertEqual(filename(metadata,1,channel_title='示例分栏'),'答疑存档-2026-10-23-示例分栏-01.png')
        self.assertEqual(filename(metadata,1,render_scale=2,channel_title='示例讨论'),
            '答疑存档-2026-10-23-HiDPI-示例讨论-01.png')

    def test_untrusted_title_never_creates_a_path_or_unbounded_filename(self):
        name=filename({'date':'2026-10-23'},1,channel_title='../\x00/恶意\\路径:\n\u202e'+'中'*1000)
        self.assertEqual(Path(name).name,name)
        self.assertNotIn('/',name);self.assertNotIn('\\',name);self.assertNotIn('\x00',name)
        self.assertNotIn('\n',name);self.assertNotIn('\u202e',name);self.assertNotIn(':',name)
        self.assertLess(len(name.encode()),255)
        self.assertIn('分栏',filename({},1,channel_title='\x00/../'))

    def test_invalid_sequence_or_density_is_rejected(self):
        for sequence in (0,-1,True,'1',1000000):
            with self.subTest(sequence=sequence),self.assertRaises(ValueError):filename({},sequence)
        for scale in (True,0,3,'2'):
            with self.subTest(scale=scale),self.assertRaises(ValueError):filename({},1,render_scale=scale)


class PublishImageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.source=self.root/'long-01.png'
        self.source.write_bytes(png())
        self.metadata={'export_date':'2026-10-23'}

    def tearDown(self):self.temp.cleanup()

    def test_alias_preserves_source_and_same_inode_is_reused_without_hash_or_link(self):
        before=self.source.read_bytes()
        target=publish_image(self.source,self.metadata,1)
        self.assertEqual(target.parent,self.source.parent)
        self.assertEqual(target.read_bytes(),before)
        self.assertEqual(self.source.read_bytes(),before)
        self.assertTrue(self.source.samefile(target))
        with (patch('discord_archive.export_names._hash',side_effect=AssertionError('unnecessary hash')),
                patch('discord_archive.export_names.os.link',side_effect=AssertionError('unnecessary link'))):
            self.assertEqual(publish_image(self.source,self.metadata,1),target)

    def test_existing_identical_copy_is_kept_and_needs_no_backup(self):
        target=self.root/filename(self.metadata,1);target.write_bytes(self.source.read_bytes())
        inode=target.stat().st_ino
        self.assertEqual(publish_image(self.source,self.metadata,1),target)
        self.assertEqual(target.stat().st_ino,inode)
        self.assertFalse((self.root/'export-name-backups').exists())

    def test_new_renderer_inode_updates_alias_and_backs_up_previous_bytes(self):
        target=publish_image(self.source,self.metadata,1);old=target.read_bytes()
        replacement=self.root/'replacement.png';replacement.write_bytes(png(200));os.replace(replacement,self.source)
        publish_image(self.source,self.metadata,1)
        self.assertEqual(target.read_bytes(),png(200));self.assertEqual(self.source.read_bytes(),png(200))
        backups=list((self.root/'export-name-backups').glob('*/*.png'))
        self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),old)

    def test_existing_user_file_is_backed_up_and_cross_device_link_uses_copy(self):
        target=self.root/filename(self.metadata,1);target.write_bytes(b'existing user file')
        with patch('discord_archive.export_names.os.link',side_effect=OSError(errno.EXDEV,'synthetic other device')):
            self.assertEqual(publish_image(self.source,self.metadata,1),target)
        self.assertEqual(target.read_bytes(),self.source.read_bytes())
        self.assertFalse(target.samefile(self.source))
        self.assertEqual(next((self.root/'export-name-backups').glob('*/*.png')).read_bytes(),b'existing user file')

    def test_atomic_replace_failure_keeps_existing_file_and_source(self):
        target=self.root/filename(self.metadata,1);target.write_bytes(b'preserve original target')
        before=self.source.read_bytes()
        with (patch('discord_archive.export_names.os.replace',side_effect=PermissionError('synthetic replace failure')),
                self.assertRaises(PermissionError)):
            publish_image(self.source,self.metadata,1)
        self.assertEqual(target.read_bytes(),b'preserve original target');self.assertEqual(self.source.read_bytes(),before)
        self.assertFalse(list(self.root.glob('.export-name-*.tmp')))
        self.assertEqual(next((self.root/'export-name-backups').glob('*/*.png')).read_bytes(),target.read_bytes())

    def test_failed_copy_cleans_only_its_own_temporary_and_keeps_existing_files(self):
        target=self.root/filename(self.metadata,1);target.write_bytes(b'keep me')
        with (patch('discord_archive.export_names.os.link',side_effect=OSError(errno.EXDEV,'synthetic')),
                patch('discord_archive.export_names.shutil.copyfileobj',side_effect=OSError('synthetic copy failure')),
                self.assertRaises(OSError)):
            publish_image(self.source,self.metadata,1)
        self.assertEqual(target.read_bytes(),b'keep me');self.assertEqual(self.source.read_bytes(),png())
        self.assertFalse(list(self.root.glob('.export-name-*.tmp')))

    def test_missing_source_and_non_png_never_create_placeholder(self):
        with self.assertRaises(FileNotFoundError):publish_image(self.root/'missing.png',self.metadata,1)
        for payload in (b'plain text',png()[:24],png()[:29]+b'bad!'+png()[33:]):
            self.source.write_bytes(payload)
            with self.subTest(payload=payload[:10]),self.assertRaises(ValueError):
                publish_image(self.source,self.metadata,1)
        self.assertFalse((self.root/filename(self.metadata,1)).exists())


if __name__=='__main__':unittest.main()
