import hashlib,json,tempfile,unittest,zipfile
from pathlib import Path
from scripts.install_login_assistants import verify
class HelperPackageTests(unittest.TestCase):
    def archive(self,root,*,first=True,protocol=2,missing=False):
        files={'Browser Extension/manifest.json':b'{}','Browser Extension/popup.mjs':b'fixture','Browser Extension/launch.mjs':b'fixture','Browser Extension/session.mjs':b'fixture','首次连接 Discord.app/Contents/MacOS/applet':b'fixture'}
        if missing:files.pop('Browser Extension/session.mjs')
        manifest={'platform':'darwin-arm64','first_login_included':first,'connection_protocol':protocol,'files':{k:hashlib.sha256(v).hexdigest() for k,v in files.items()}}
        path=Path(root)/'helper.zip'
        with zipfile.ZipFile(path,'w') as z:
            for k,v in files.items():z.writestr(k,v)
            z.writestr('ASSISTANT-MANIFEST.json',json.dumps(manifest))
        return path
    def test_first_connection_capability_checked_before_publish(self):
        for values in [{'first':False},{'protocol':1},{'missing':True}]:
            with self.subTest(values=values),tempfile.TemporaryDirectory() as root:
                with self.assertRaisesRegex(ValueError,'首次连接'):verify(self.archive(root,**values),{'darwin-arm64'})
        with tempfile.TemporaryDirectory() as root:self.assertEqual(verify(self.archive(root),{'darwin-arm64'}),'darwin-arm64')
