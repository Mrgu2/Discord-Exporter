import io,json,tempfile,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from app import make_handler,supports_local_connection
from discord_archive.listener import project_id

class LocalDockerConnectionTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.app=SimpleNamespace(root=self.root,port=29876,csrf='fixture',local_hostname='fixture',remote_access=SimpleNamespace(origin='https://fixture.ts.net',hostname='fixture.ts.net',trusted=lambda *_:False),credentials=Mock(),worker=Mock(),invalidate_status_cache=Mock())
        self.cls=make_handler(self.app)

    def handler(self,path,body=None):
        h=self.cls.__new__(self.cls);h.path=path;h.command='GET' if body is None else 'POST';h.client_address=('127.0.0.1',1)
        raw=json.dumps(body or {}).encode();h.headers={'Host':'127.0.0.1:29876','Origin':'http://127.0.0.1:29876','Content-Length':str(len(raw)),'X-Archive-Key':'fixture'};h.rfile=io.BytesIO(raw);h.send=Mock();return h

    def test_download_pins_local_url_project_and_current_port_for_both_clients(self):
        folder=self.root/'.local/login-assistants';folder.mkdir(parents=True)
        for platform in ('mac','windows'):
            name=f'login-assistant-{platform}.zip'
            with zipfile.ZipFile(folder/name,'w') as z:z.writestr('client','fixture');z.writestr('server.json','{"server_url":"https://old.ts.net"}')
            h=self.handler('/download/'+name)
            with patch('app.sys.platform','linux'),patch.dict('os.environ',{'DISCORD_ARCHIVE_DOCKER':'1'}):h.do_GET()
            self.assertEqual(h.send.call_args.args[0],200)
            with zipfile.ZipFile(io.BytesIO(h.send.call_args.args[1])) as z:
                self.assertEqual(z.namelist().count('server.json'),1)
                self.assertEqual(json.loads(z.read('server.json')),{'server_url':'http://127.0.0.1:29876','project_id':project_id(self.root)})
            # Download personalization must not change the installed template.
            with zipfile.ZipFile(folder/name) as z:self.assertEqual(json.loads(z.read('server.json'))['server_url'],'https://old.ts.net')

    def test_local_docker_rejects_wrong_database_before_committing(self):
        with patch('app.sys.platform','linux'),patch.dict('os.environ',{'DISCORD_ARCHIVE_DOCKER':'1'}):
            for project,code in [(None,400),('wrong',400),(project_id(self.root),200)]:
                with self.subTest(project=project):
                    h=self.handler('/api/bind-discord',{'credential':'synthetic_never_real','expected_user_id':'9001','expected_project_id':project})
                    with patch('app.bind_connection',return_value={'ok':True}) as bind:h.mutation()
                    self.assertEqual(h.send.call_args.args[0],code);self.assertEqual(bind.call_count,int(code==200))

    def test_forwarded_and_wrong_origin_cannot_use_local_binding(self):
        for changes in [{'Origin':'http://evil.invalid'},{'X-Forwarded-For':'127.0.0.1'},{'Host':'evil.invalid:29876'}]:
            h=self.handler('/api/bind-discord',{'credential':'synthetic_never_real','expected_user_id':'9001','expected_project_id':project_id(self.root)});h.headers.update(changes)
            with patch('app.sys.platform','linux'),patch.dict('os.environ',{'DISCORD_ARCHIVE_DOCKER':'1'}),patch('app.bind_connection') as bind:h.mutation()
            self.assertIn(h.send.call_args.args[0],(401,403));bind.assert_not_called()

    def test_native_linux_does_not_advertise_local_docker_binding(self):
        with patch('app.sys.platform','linux'),patch.dict('os.environ',{'DISCORD_ARCHIVE_DOCKER':''}):self.assertFalse(supports_local_connection())
