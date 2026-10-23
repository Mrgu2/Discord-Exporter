import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from discord_archive.editorial import DraftService
from discord_archive import render_cache
from discord_archive.settings import atomic_json


class RenderTargetTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.service=DraftService(None,self.root,None,None)
        self.identity=str(uuid.uuid4());self.folder=self.root/'output'/self.identity;self.folder.mkdir()
        (self.folder/'index.html').write_text('<main id="manuscript">main</main>')
        (self.folder/'single-100.html').write_text('<main id="manuscript">column</main>')
        atomic_json(self.folder/'metadata.json',{'id':self.identity,'images':[],
            'single_columns':[{'channel_id':'100','title':'QA','file':'single-100.html','images':[]}]})

    def tearDown(self):
        self.temporary.cleanup()

    def render(self,command,**options):
        output=Path(command[3]);output.mkdir(exist_ok=True)
        target=output/'long-01.png'
        # A deterministic PNG header suffices for cache transport tests; actual
        # PNG decode/CRC coverage lives in png_check and renderer acceptance.
        target.write_bytes(b'\x89PNG\r\n\x1a\n'+b'\0\0\0\rIHDR'+b'\0\0\0\2\0\0\0\2'+b'fixture')
        return type('Result',(),{'returncode':0,'stdout':json.dumps({'images':[str(target)],
            'render_scale':2,'dimensions':[{'width':2,'height':2}],'css_dimensions':[{'width':1,'height':1}]})})()

    def test_main_only_then_mobile_preserves_main_and_warm_run_starts_no_browser(self):
        with patch('discord_archive.editorial.shutil.which',return_value='/fixture/node'), \
                patch('discord_archive.editorial.subprocess.run',side_effect=self.render) as runner:
            main=self.service.render(self.identity,target='main')
            self.assertEqual(runner.call_count,1)
            self.assertEqual(main['single_columns'][0]['images'],[])
            mobile=self.service.render(self.identity,target='mobile')
            self.assertEqual(runner.call_count,2)
            self.assertEqual(mobile['images'],main['images'])
            self.assertTrue(mobile['single_columns'][0]['images'])
            warm=self.service.render(self.identity)
            self.assertEqual(runner.call_count,2)
            self.assertEqual(set(warm['cache_hits']),{'main','mobile:100'})
            self.service.render(self.identity,target='main',force=True)
            self.assertEqual(runner.call_count,3)

    def test_missing_changed_png_or_html_invalidate_cache(self):
        with patch('discord_archive.editorial.shutil.which',return_value='/fixture/node'), \
                patch('discord_archive.editorial.subprocess.run',side_effect=self.render) as runner:
            self.service.render(self.identity,target='main')
            (self.folder/'long-01.png').write_bytes(b'corrupted')
            self.service.render(self.identity,target='main')
            (self.folder/'index.html').write_text('changed HTML')
            self.service.render(self.identity,target='main')
            self.assertEqual(runner.call_count,3)

    def test_local_image_bytes_change_input_fingerprint(self):
        media=self.root/'data/media';media.mkdir(parents=True);(media/'a.png').write_bytes(b'old')
        (self.folder/'index.html').write_text('<img src="/media/a.png" data-local-src="../../data/media/a.png">')
        before=render_cache.fingerprint(self.folder/'index.html',self.root)
        (media/'a.png').write_bytes(b'new')
        self.assertNotEqual(before,render_cache.fingerprint(self.folder/'index.html',self.root))

    def test_main_is_published_even_if_later_phone_column_fails(self):
        def failure(command,**options):
            if 'single-' in command[2]:
                raise ValueError('synthetic mobile failure')
            return self.render(command,**options)
        with patch('discord_archive.editorial.shutil.which',return_value='/fixture/node'), \
                patch('discord_archive.editorial.subprocess.run',side_effect=failure), \
                self.assertRaisesRegex(ValueError,'mobile failure'):
            self.service.render(self.identity)
        saved=json.loads((self.folder/'metadata.json').read_text())
        self.assertTrue(saved['images'])
        self.assertEqual(saved['render_scale'],2)


if __name__ == '__main__':
    unittest.main()
