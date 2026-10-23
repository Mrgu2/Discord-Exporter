import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from app import make_handler


class ServerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.app=SimpleNamespace(root=self.root,local_hostname='archive-mac',csrf='test-csrf',code='test-phone-code',sessions={},login_attempts={},worker=Mock())
        self.app.worker.submit.return_value={'status':'queued'}

    def tearDown(self):
        self.temp.cleanup()

    def handler(self,path,body=None,host='127.0.0.1:8765',client='127.0.0.1',method='POST'):
        handler=make_handler(self.app).__new__(make_handler(self.app))
        raw=json.dumps(body or {}).encode()
        handler.path=path;handler.command=method;handler.client_address=(client,123)
        handler.headers={'Host':host,'X-Archive-Key':'test-csrf','Content-Length':str(len(raw))}
        handler.rfile=io.BytesIO(raw)
        handler.send=Mock()
        return handler

    def test_remote_cannot_read_private_status_without_pairing(self):
        handler=self.handler('/api/status',host='192.168.1.4:8765',client='192.168.1.8',method='GET')
        handler.do_GET()
        self.assertEqual(handler.send.call_args.args[0],401)

    def test_remote_cannot_set_account_credentials_even_with_session(self):
        self.app.sessions['valid']=9999999999
        handler=self.handler('/api/credentials',{'kind':'discord','value':'fictitious'},host='192.168.1.4:8765',client='192.168.1.8')
        handler.headers['Cookie']='archive_session=valid'
        handler.mutation()
        self.assertEqual(handler.send.call_args.args[0],403)

    def test_csrf_and_foreign_origin_rejected(self):
        for name,value in [('X-Archive-Key','wrong'),('Origin','https://elsewhere.invalid')]:
            handler=self.handler('/api/capture')
            handler.headers[name]=value
            handler.mutation()
            self.assertEqual(handler.send.call_args.args[0],403)
        self.app.worker.submit.assert_not_called()

    def test_real_uuid_render_reaches_worker(self):
        identity='274ee8a1-f0de-4d97-8987-536815bd5671'
        handler=self.handler('/api/render',{'draft_id':identity})
        handler.mutation()
        self.assertEqual(handler.send.call_args.args[0],202)
        self.app.worker.submit.assert_called_once_with('render',{'draft_id':identity,'target':'main','render_scale':1})

    def test_render_rejects_invalid_density_before_enqueue(self):
        for value in [0,3,True,'2',1.5]:
            handler=self.handler('/api/render',{'draft_id':'274ee8a1-f0de-4d97-8987-536815bd5671','render_scale':value})
            handler.mutation()
            self.assertEqual(handler.send.call_args.args[0],400)
        self.app.worker.submit.assert_not_called()

    def test_path_traversal_and_dns_rebinding_rejected(self):
        handler=self.handler('/api/status',host='evil.invalid:8765',method='GET')
        handler.do_GET()
        self.assertEqual(handler.send.call_args.args[0],403)
        handler=self.handler('/')
        handler.file(self.root/'output','../../credentials.json')
        self.assertEqual(handler.send.call_args.args[0],403)

    def test_login_sets_http_only_cookie_and_never_returns_secret(self):
        handler=self.handler('/api/login',{'code':'test-phone-code'},host='192.168.1.4:8765',client='192.168.1.8')
        handler.mutation()
        call=handler.send.call_args
        self.assertEqual(call.args[0],200)
        self.assertEqual(call.args[1],{'ok':True})
        self.assertIn('HttpOnly',call.kwargs['extra']['Set-Cookie'])
        self.assertIn('SameSite=Strict',call.kwargs['extra']['Set-Cookie'])


if __name__=='__main__':unittest.main()
