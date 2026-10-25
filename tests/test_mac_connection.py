import hashlib,io,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from app import make_handler
from discord_archive.listener import project_id
class MacConnectionBoundaryTests(unittest.TestCase):
    def test_local_bind_requires_exact_project_before_any_credential_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=SimpleNamespace(root=root,csrf='fixture',local_hostname='fixture',remote_access=None,credentials=Mock(),worker=Mock(),invalidate_status_cache=Mock())
            cls=make_handler(app)
            for project,expected in [(None,400),('wrong',400),(project_id(root),200)]:
                h=cls.__new__(cls);body=json.dumps({'credential':'synthetic_never_real','expected_user_id':'9001','expected_project_id':project}).encode();h.path='/api/bind-discord';h.command='POST';h.client_address=('127.0.0.1',1);h.headers={'Host':'127.0.0.1:8765','Origin':'http://127.0.0.1:8765','Content-Length':str(len(body)),'X-Archive-Key':'fixture'};h.rfile=io.BytesIO(body);h.send=Mock()
                with patch('app.sys.platform','darwin'),patch('app.bind_connection',return_value={'ok':True}) as bind:h.mutation()
                self.assertEqual(h.send.call_args.args[0],expected)
                self.assertEqual(bind.call_count,1 if expected==200 else 0)
