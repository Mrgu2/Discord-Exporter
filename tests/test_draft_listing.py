import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from discord_archive.editorial import DraftService


class DraftListingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = DraftService(None, self.temp.name, None, None)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, identity, **extra):
        folder = self.service.output / str(identity)
        folder.mkdir(exist_ok=True)
        value = {'id':str(identity),'title':f'稿件 {identity}','status':'ready',
            'created_at':f'2026-10-{int(identity)%28+1:02d}T10:00:00Z',**extra}
        path = folder/'metadata.json'
        path.write_text(json.dumps(value, ensure_ascii=False))
        return path, value

    def test_all_pages_and_search_include_older_drafts(self):
        for index in range(103):
            self.write(index, title='目标 older' if index == 0 else f'稿件 {index}')
        full = self.service.list_drafts()
        expected = sorted(full, key=lambda row:(row['created_at'],row['id']), reverse=True)
        pages = [self.service.list_draft_page(limit=20,offset=offset) for offset in range(0,103,20)]
        self.assertEqual([row['id'] for page in pages for row in page['items']], [row['id'] for row in expected])
        self.assertEqual([page['total'] for page in pages],[103]*6)
        self.assertTrue(all(page['has_more'] for page in pages[:-1]))
        self.assertFalse(pages[-1]['has_more'])
        found = self.service.list_draft_page(search='OLDER')
        self.assertEqual([row['id'] for row in found['items']],['0'])
        self.assertEqual(found['total'],1)
        self.assertEqual(self.service.list_draft_page(offset=103)['items'],[])

    def test_light_projection_retains_density_links_without_verification(self):
        columns = [{'title':'答疑','channel_id':'100','file':'qa.html','images':['mobile.png'],
            'render_scale':2,'render_verification':{'huge':['x']*100}}]
        self.write(1,warnings=['one','two'],audio={'complete':7,'private':'unneeded'},
            render_scale=2,images=['main.png'],single_columns=columns,
            image_variants={'1':{'images':[],'single_columns':columns,'render_verification':{'unneeded':True}},
                '2':{'images':['two.png'],'render_scale':2,'single_columns':columns}},
            render_verification={'huge':['x']*100},selection={'private':'unneeded'})
        row = self.service.list_draft_page()['items'][0]
        self.assertNotIn('render_verification',row)
        self.assertNotIn('selection',row)
        self.assertNotIn('warnings',row)
        self.assertEqual(row['warning_count'],2)
        self.assertEqual(row['audio'],{'complete':7})
        self.assertEqual(row['single_columns'][0]['render_scale'],2)
        self.assertEqual(row['image_variants']['2']['images'],['two.png'])
        self.assertNotIn('render_verification',row['image_variants']['1'])
        self.assertNotIn('render_verification',row['single_columns'][0])
        self.assertIn('render_verification',self.service.list_drafts()[0])

    def test_cached_reads_notice_external_edit_add_and_atomic_replace(self):
        path, original = self.write(1)
        first = self.service.list_draft_page()
        with patch.object(Path,'read_text',side_effect=AssertionError('Unchanged metadata was decoded again')):
            second = self.service.list_draft_page()
        self.assertEqual(first,second)
        # A caller cannot mutate the retained projection.
        second['items'][0]['images'].append('caller.png')
        self.assertEqual(self.service.list_draft_page()['items'][0]['images'],[])
        old_stat = path.stat()
        replacement = {**original,'title':'稿件 Z'}
        path.write_text(json.dumps(replacement,ensure_ascii=False))
        os.utime(path,ns=(old_stat.st_atime_ns,old_stat.st_mtime_ns))
        changed = self.service.list_draft_page()
        self.assertEqual(changed['items'][0]['title'],'稿件 Z')
        self.assertNotEqual(first['revision'],changed['revision'])
        atomic = path.with_name('metadata-new.json')
        atomic.write_text(json.dumps({**original,'title':'replacement'},ensure_ascii=False))
        os.replace(atomic,path)
        self.assertEqual(self.service.list_draft_page()['items'][0]['title'],'replacement')
        self.write(2)
        self.assertEqual(self.service.list_draft_page()['total'],2)

    def test_bad_json_is_not_cached_and_recovery_is_visible(self):
        path,_ = self.write(1)
        self.service.list_draft_page()
        path.write_text('{unfinished')
        self.assertEqual(self.service.list_draft_page()['total'],0)
        with patch.object(Path,'read_text',wraps=Path.read_text,autospec=True) as read:
            self.service.list_draft_page()
            self.assertTrue(read.called)
        self.write(1,title='recovered')
        self.assertEqual(self.service.list_draft_page()['items'][0]['title'],'recovered')
        path.write_text('[]')
        self.assertEqual(self.service.list_draft_page()['items'],[])

    def test_missing_or_null_timestamp_does_not_break_other_drafts(self):
        self.write(1,created_at=None)
        self.write(2)
        self.assertEqual([row['id'] for row in self.service.list_draft_page()['items']],['2','1'])

    def test_validates_pagination_without_surprising_coercion(self):
        for options in ({'limit':0},{'limit':101},{'limit':True},{'offset':-1},{'offset':'0'},{'search':[]}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.service.list_draft_page(**options)


if __name__ == '__main__':
    unittest.main()
