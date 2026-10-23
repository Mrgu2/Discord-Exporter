import io
import copy
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import Application, make_handler


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

    def test_draft_page_is_authorized_and_parameters_are_bounded(self):
        self.app.drafts=Mock()
        self.app.drafts.list_draft_page.return_value={'items':[],'total':0}
        handler=self.handler('/api/drafts?limit=20&offset=40&search=%E5%B8%82%E5%9C%BA',method='GET')
        handler.do_GET()
        self.app.drafts.list_draft_page.assert_called_once_with(limit=20,offset=40,search='市场')
        self.assertEqual(handler.send.call_args.args[0],200)
        self.app.drafts.reset_mock()
        for query in ('limit=101','limit=0','offset=-1','limit=oops'):
            handler=self.handler('/api/drafts?'+query,method='GET');handler.do_GET()
            self.assertEqual(handler.send.call_args.args[0],400)
        handler=self.handler('/api/drafts',host='192.168.1.4:8765',client='192.168.1.8',method='GET')
        handler.do_GET()
        self.assertEqual(handler.send.call_args.args[0],401)
        self.app.drafts.list_draft_page.assert_not_called()

    def test_large_download_is_byte_exact_with_bounded_chunks(self):
        folder=self.root/'output';folder.mkdir()
        target=folder/'large.png';chunk=b'png-test-fixture'*20000
        expected=hashlib.sha256()
        with target.open('wb') as output:
            for _ in range(32):output.write(chunk);expected.update(chunk)
        class Sink:
            size=0;largest=0
            def __init__(self):self.digest=hashlib.sha256()
            def write(self,value):
                self.size+=len(value);self.largest=max(self.largest,len(value));self.digest.update(value)
        handler=self.handler('/output/large.png',method='GET')
        handler.response_headers=Mock();handler.wfile=Sink()
        with patch.object(Path,'read_bytes',side_effect=AssertionError('whole-file allocation')):
            handler.file(folder,'large.png')
        self.assertEqual(handler.wfile.size,target.stat().st_size)
        self.assertEqual(handler.wfile.digest.hexdigest(),expected.hexdigest())
        self.assertLessEqual(handler.wfile.largest,256*1024)
        handler.response_headers.assert_called_once_with(200,target.stat().st_size,'image/png')
        handler.send.assert_not_called()

    def test_directory_index_symlink_cannot_escape_and_cancel_is_safe(self):
        folder=self.root/'output';folder.mkdir()
        outside=self.root/'private.html';outside.write_text('private fixture')
        (folder/'index.html').symlink_to(outside)
        handler=self.handler('/output/',method='GET');handler.file(folder,'')
        self.assertEqual(handler.send.call_args.args[0],403)
        (folder/'file.txt').write_text('fixture')
        handler=self.handler('/output/file.txt',method='GET');handler.response_headers=Mock()
        handler.wfile=Mock();handler.wfile.write.side_effect=BrokenPipeError()
        handler.file(folder,'file.txt')
        handler.response_headers.assert_called_once();handler.send.assert_not_called()


class StatusScalingTests(unittest.TestCase):
    def setUp(self):
        self.app=Application.__new__(Application)
        self.app._status_cache={};self.app._status_cache_lock=threading.RLock()

    def test_discovery_cache_is_bounded_and_can_be_invalidated(self):
        compute=Mock(return_value={'discord':True})
        with patch('app.time.monotonic',side_effect=[0,5,31,32]):
            first=self.app._cached_status_value('flags',30,compute);first['discord']=False
            self.assertTrue(self.app._cached_status_value('flags',30,compute)['discord'])
            self.app._cached_status_value('flags',30,compute)
            self.app.invalidate_status_cache()
            self.app._cached_status_value('flags',30,compute)
        self.assertEqual(compute.call_count,3)

    def test_status_returns_recent_page_and_keeps_evidence_out_of_polling(self):
        full={'last_result':{'id':'fixture','scope':'day','evidence_url':'/evidence',
            'render_verification':{'large':'x'*100000},'draft':{'id':'fixture','render_verification':{'large':'x'*100000}},
            'single_columns':[{'title':'栏目','images':['/output/fixture.png'],'render_verification':{'large':'x'*100000}}]}}
        self.app.worker=Mock();self.app.worker.status.return_value=(copy.deepcopy(full),{})
        self.app.worker.media.stats.return_value={}
        self.app.store=Mock();self.app.store.list_runs.return_value=[];self.app.store.summary.return_value={}
        self.app.drafts=Mock();self.app.drafts.list_draft_page.return_value={'items':[{'id':'recent'}],'total':1000,'revision':'changed'}
        self.app.credentials=Mock();self.app.credentials.get.return_value='synthetic'
        self.app.settings=Mock();self.app.settings.read.return_value={};self.app.remote_addresses=Mock(return_value=[])
        self.app.code='synthetic-pairing-code'
        result=self.app.status(local=False)
        self.assertEqual(result['draft_count'],1000)
        self.assertEqual(result['draft_revision'],'changed')
        self.app.drafts.list_draft_page.assert_called_once_with(limit=3)
        self.assertNotIn('access_code',result['remote'])
        self.assertNotIn('render_verification',result['state']['last_result'])
        self.assertEqual(result['state']['last_result']['draft'],{'id':'fixture'})
        self.assertEqual(result['state']['last_result']['single_columns'],[{'title':'栏目','images':['/output/fixture.png']}])
        self.assertLess(len(json.dumps(result)),2000)


if __name__=='__main__':unittest.main()
