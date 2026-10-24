import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from discord_archive.editorial import DraftService


class RenderDiagnosticsTests(unittest.TestCase):
    def test_playwright_error_keeps_cause_instead_of_anonymous_stack_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);service=DraftService(None,root,None,None)
            identity=str(uuid.uuid4());folder=root/'output'/identity;folder.mkdir()
            (folder/'index.html').write_text('<main id="manuscript">fixture</main>')
            (folder/'metadata.json').write_text(json.dumps({'id':identity,'images':[],'single_columns':[]}))
            stderr=('page.evaluate: Error: 横向长图超过单图尺寸限制\n'
                '    at eval (<anonymous>:110:28)\n    at UtilityScript.<anonymous> (<anonymous>:1:44)\n')
            with patch('discord_archive.editorial.shutil.which',return_value='/fixture/node'), \
                    patch('discord_archive.editorial.subprocess.run',return_value=SimpleNamespace(returncode=1,stderr=stderr)), \
                    self.assertRaisesRegex(ValueError,'横向长图超过单图尺寸限制') as failure:
                service.render(identity,target='main')
            self.assertNotIn('UtilityScript',str(failure.exception))
            self.assertEqual(json.loads((folder/'metadata.json').read_text())['images'],[])


if __name__=='__main__':unittest.main()
