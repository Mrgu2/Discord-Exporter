import hashlib,json,tempfile,unittest,zipfile
from pathlib import Path
from scripts.install_login_assistants import verify
class HelperPackageTests(unittest.TestCase):
    def archive(self,root,*,first=True,protocol=2,missing=False,entry="首次连接 Discord.app/Contents/MacOS/applet"):
        files={'Browser Extension/manifest.json':b'{}','Browser Extension/popup.mjs':b'fixture','Browser Extension/launch.mjs':b'fixture','Browser Extension/session.mjs':b'fixture',entry:b'fixture'}
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

    def test_command_entry_and_legacy_app_are_both_verified(self):
        for entry in ['首次连接 Discord.command','首次连接 Discord.app/Contents/MacOS/applet']:
            with self.subTest(entry=entry),tempfile.TemporaryDirectory() as root:
                self.assertEqual(verify(self.archive(root,entry=entry),{'darwin-arm64'}),'darwin-arm64')

    def test_mac_command_uses_real_package_directory_not_current_or_translocated_app(self):
        import os,subprocess
        from scripts.package_native_client import write_mac_command
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'新电脑 download folder';root.mkdir()
            binary=root/'Ubuntu Workspace.app/Contents/MacOS/client';binary.parent.mkdir(parents=True)
            binary.write_text('#!/bin/bash\nprintf \'%s\\n\' "$PWD" "$@" > "$PROBE_FILE"\n');binary.chmod(0o755)
            probe=Path(temp)/'probe'
            for name,arg in [('首次连接 Discord.command','--install-only'),('设置工作台.command','--configure'),('打开工作台.command','')]:
                write_mac_command(root,name,arg,"It's ready.")
                script=root/name
                subprocess.run(['bash','-n',str(script)],check=True)
                result=subprocess.run(['bash',str(script)],cwd=temp,env={**os.environ,'PROBE_FILE':str(probe)},capture_output=True,text=True,check=True)
                self.assertEqual(probe.read_text().splitlines(),[str(root)]+([arg] if arg else []))
                self.assertIn("It's ready.",result.stdout)
            binary.rename(binary.with_name('retained-fixture'))
            failure=subprocess.run(['bash',str(root/'首次连接 Discord.command')],capture_output=True,text=True)
            self.assertEqual(failure.returncode,1);self.assertIn('连接包不完整',failure.stderr)
