import io,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from app import make_handler
from discord_archive.remote_access import RemoteAccess,LoginPairings,DeviceAuthorizations,https_origin

ORIGIN='https://archive.example.ts.net'
class RemoteAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'data').mkdir()
        (self.root/'data/remote-access.json').write_text(json.dumps({'origin':ORIGIN,'owners':['owner@example.com']}))
        self.remote=RemoteAccess(self.root)
    def tearDown(self):self.temp.cleanup()
    def test_exact_origin_and_owner_proxy_only(self):
        headers={'Host':'archive.example.ts.net','X-Forwarded-Proto':'https','Tailscale-User-Login':'owner@example.com'}
        self.assertTrue(self.remote.trusted('127.0.0.1',headers))
        for address,changed in [('192.168.1.3',{}),('127.0.0.1',{'Tailscale-User-Login':'other@example.com'}),('127.0.0.1',{'Host':'evil.example.ts.net'}),('127.0.0.1',{'X-Forwarded-Proto':'http'})]:
            self.assertFalse(self.remote.trusted(address,{**headers,**changed}))
        for url in ['http://archive.example.ts.net','https://example.com','https://archive.example.ts.net/path','https://evil@archive.example.ts.net','https://archive.example.ts.net?secret=x','https://archive.example.ts.net:9999']:
            with self.assertRaises(ValueError):https_origin(url)
    def test_isolated_https_port_must_match_configured_authority(self):
        self.assertEqual(https_origin(ORIGIN+':8443'),ORIGIN+':8443')
        headers={'Host':'archive.example.ts.net:8443','X-Forwarded-Proto':'https','Tailscale-User-Login':'owner@example.com'}
        self.assertFalse(self.remote.trusted('127.0.0.1',headers))
        (self.root/'data/remote-access.json').write_text(json.dumps({'origin':ORIGIN+':8443','owners':['owner@example.com']}))
        isolated=RemoteAccess(self.root)
        self.assertTrue(isolated.trusted('127.0.0.1',headers))
        self.assertFalse(isolated.trusted('127.0.0.1',{**headers,'Host':'archive.example.ts.net'}))
    def test_device_link_requires_confirmation_poll_secret_and_single_use(self):
        now=[100];pairings=LoginPairings(lambda:now[0]);devices=DeviceAuthorizations(pairings,lambda:now[0]);r=devices.request(ORIGIN,'Fixture Windows')
        self.assertFalse(devices.poll(r['request_id'],r['poll_secret'])['approved'])
        self.assertNotIn('secret',devices.info(r['request_id']))
        with self.assertRaises(ValueError):devices.poll(r['request_id'],'wrong')
        devices.approve(r['request_id']);code=devices.poll(r['request_id'],r['poll_secret'])['pairing_code'];pairings.check(code,True)
        with self.assertRaises(ValueError):pairings.check(code)
        now[0]=401
        with self.assertRaises(ValueError):devices.info(r['request_id'])
    def handler(self,path,body,owner='owner@example.com',client='127.0.0.1',csrf='fixture'):
        h=make_handler(self.app).__new__(make_handler(self.app));raw=json.dumps(body).encode();h.path=path;h.command='POST';h.client_address=(client,1)
        h.headers={'Host':'archive.example.ts.net','Origin':ORIGIN,'Tailscale-User-Login':owner,'X-Forwarded-Proto':'https','Content-Length':str(len(raw)),'X-Archive-Key':csrf};h.rfile=io.BytesIO(raw);h.send=Mock();return h
    def test_proxy_cannot_claim_local_privileges_with_forged_host(self):
        self.app=SimpleNamespace(remote_access=self.remote,local_hostname='fixture',csrf='fixture',sessions={})
        h=self.handler('/api/helper/request',{'device':'Fixture'},owner='other@example.com')
        h.headers['Host']='127.0.0.1:8765';h.headers.pop('Origin')
        self.assertFalse(h.local());h.mutation();self.assertEqual(h.send.call_args.args[0],403)

    def test_https_admin_and_device_flow_server_boundary(self):
        pairings=LoginPairings();devices=DeviceAuthorizations(pairings)
        self.app=SimpleNamespace(remote_access=self.remote,login_pairings=pairings,device_authorizations=devices,local_hostname='fixture',csrf='fixture',worker=Mock(),credentials=Mock(),invalidate_status_cache=Mock(),sessions={})
        h=self.handler('/api/helper/request',{'device':'Fixture Mac'},csrf='');h.mutation();self.assertEqual(h.send.call_args.args[0],200);r=h.send.call_args.args[1]
        h=self.handler('/api/helper/approve',{'request_id':r['request_id']},csrf='bad');h.mutation();self.assertEqual(h.send.call_args.args[0],403)
        h=self.handler('/api/helper/approve',{'request_id':r['request_id']});h.mutation();self.assertEqual(h.send.call_args.args[0],200)
        code=devices.poll(r['request_id'],r['poll_secret'])['pairing_code']
        with patch('app.bind_connection',return_value={'ok':True}) as bind:
            h=self.handler('/api/helper/bind',{'pairing_code':code,'credential':'fixture_never_real','expected_user_id':'9001'},owner='other@example.com');h.mutation();self.assertEqual(h.send.call_args.args[0],403);bind.assert_not_called()
            h=self.handler('/api/helper/bind',{'pairing_code':code,'credential':'fixture_never_real','expected_user_id':'9001'},client='192.168.1.8');h.mutation();self.assertEqual(h.send.call_args.args[0],403);bind.assert_not_called()
            h=self.handler('/api/helper/bind',{'pairing_code':code,'credential':'fixture_never_real','expected_user_id':'9001'},csrf='');h.mutation();self.assertEqual(h.send.call_args.args[0],200);self.assertNotIn('fixture_never_real',json.dumps(h.send.call_args.args[1]))
            h=self.handler('/api/helper/bind',{'pairing_code':code,'credential':'fixture_never_real','expected_user_id':'9001'},csrf='');h.mutation();self.assertEqual(h.send.call_args.args[0],400);self.assertEqual(bind.call_count,1)
