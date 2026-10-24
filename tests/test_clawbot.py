"""Protocol/fault checks with fictional credentials; never contacts Weixin."""
import base64
import copy
import io
import json
import struct
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from discord_archive.clawbot import API, ClawBot, ClawBotError, ClawBotNeedsAction, helper, official_url
from discord_archive.delivery import DeliveryOutbox
from discord_archive.settings import Settings

ACCOUNT = {'token': 'fictional-token', 'user_id': 'fictional-user@im.wechat',
           'bot_id': 'fictional-bot', 'api_url': API}


class MemoryCredentials:
    def __init__(self): self.values = {}
    def get(self, key): return self.values.get(key)
    def set(self, key, value): self.values[key] = value; return 'private_file'


class Response:
    def __init__(self, value, headers=None):
        self.raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.headers = headers or {}; self.status = 200
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, *args): return self.raw


class ClawBotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.credentials = MemoryCredentials()
        self.client = ClawBot(self.root, self.credentials)

    def bind(self):
        self.credentials.set('delivery_clawbot', json.dumps(ACCOUNT))
        self.client = ClawBot(self.root, self.credentials)
        self.client._save(context_token='fresh-context')

    def test_official_domains_and_no_redirects(self):
        self.assertEqual(official_url(API+'/'), API)
        self.assertEqual(official_url('https://ilinkhk.weixin.qq.com'), 'https://ilinkhk.weixin.qq.com')
        for url in ('http://ilinkai.weixin.qq.com', API+'@evil.example', API+':443', API+'/evil',
                    API+'.evil.example', 'https://127.0.0.1', None, 'https://ilinkai.weixin.qq.com#x'):
            with self.subTest(url=url), self.assertRaises(ClawBotError): official_url(url)
        self.assertEqual(official_url('https://novac2c.cdn.weixin.qq.com/c2c/upload?q=x', cdn=True),
                         'https://novac2c.cdn.weixin.qq.com/c2c/upload?q=x')
        with self.assertRaises(ClawBotError): official_url('https://evil.example/upload', cdn=True)

    def test_qr_login_then_private_context_survives_restart_and_hides_secrets(self):
        with patch.object(self.client, '_request', return_value={'qrcode':'secret-qr', 'qrcode_img_content':'https://weixin.qq.com/test'}), \
                patch('discord_archive.clawbot.helper', return_value=b'PNG'), patch.object(self.client, 'start'):
            summary = self.client.begin()
        self.assertEqual(self.client.qr(summary['login_id']), b'PNG')
        with patch.object(self.client, '_request', return_value={'status':'confirmed',
                'bot_token':ACCOUNT['token'], 'ilink_user_id':ACCOUNT['user_id'],
                'ilink_bot_id':ACCOUNT['bot_id'], 'baseurl':API}): self.client._poll_login()
        self.assertEqual(self.client.status()['status'], 'needs_message')
        self.assertIsNone(self.client.status()['qr_url'])
        self.client.pending['started'] -= 400
        self.assertEqual(self.client.status()['login_status'], 'confirmed')
        messages = {'ret':0, 'get_updates_buf':'private-cursor', 'msgs':[
            {'from_user_id':ACCOUNT['user_id'], 'message_type':1, 'context_token':'fresh-context',
             'item_list':[{'text_item':{'text':'private-content-not-archived'}}]}]}
        with patch.object(self.client, '_request', return_value=messages): self.client._poll_messages()
        self.assertTrue(self.client.status()['ready'])
        restarted = ClawBot(self.root, self.credentials)
        self.assertTrue(restarted.ready_for(self.client.binding_id()))
        public = json.dumps(restarted.status())
        for secret in ('fictional-token', ACCOUNT['user_id'], 'private-cursor', 'fresh-context', 'secret-qr'):
            self.assertNotIn(secret, public)
        self.assertNotIn('private-content-not-archived', self.client.path.read_text())
        self.assertEqual(self.client.path.stat().st_mode & 0o777, 0o600)

    def test_stale_login_response_cannot_replace_new_qr_or_existing_credentials(self):
        self.bind()
        self.client.pending = {'id':'old','value':'qr','png':b'PNG','status':'wait',
                              'started':time.monotonic()-301,'base':API,'verify_code':None}
        with patch.object(self.client, '_request') as request:
            self.client._poll_login(); request.assert_not_called()
        self.assertEqual(self.client.status()['login_status'], 'expired')
        with self.assertRaises(ClawBotError): self.client.qr('old')
        self.assertEqual(self.client.account, ACCOUNT)

    def test_verify_code_and_redirect_validation(self):
        self.client.pending = {'id':'login','value':'qr','png':b'PNG','status':'need_verifycode',
                              'started':time.monotonic(),'base':API,'verify_code':None}
        for code in ('abc', '123\n4', None):
            with self.assertRaises(ClawBotError): self.client.verify('login', code)
        self.client.verify('login', '123456')
        with patch.object(self.client, '_request', return_value={'status':'scaned_but_redirect','redirect_host':'evil.example'}):
            with self.assertRaises(ClawBotError): self.client._poll_login()
        with patch.object(self.client, '_request', return_value={'status':'scaned_but_redirect','redirect_host':'ilinkhk.weixin.qq.com'}):
            self.client._poll_login()
        self.assertEqual(self.client.pending['base'], 'https://ilinkhk.weixin.qq.com')

    def test_verification_code_is_submitted_once_even_when_rejected(self):
        self.client.pending = {'id':'login','value':'qr','png':b'PNG','status':'need_verifycode',
                              'started':time.monotonic(),'base':API,'verify_code':'123456'}
        with patch.object(self.client, '_request', return_value={'status':'need_verifycode'}) as request:
            self.client._poll_login()
            self.assertIn('verify_code=123456', request.call_args.args[1])
            self.assertIsNone(self.client.pending['verify_code'])
            self.client._poll_login()
            self.assertNotIn('verify_code=', request.call_args.args[1])

    def test_only_scanner_private_inbound_can_refresh_context(self):
        self.bind(); self.client._save(needs_message=True)
        bad = [{'from_user_id':'other', 'message_type':1, 'context_token':'wrong'},
               {'from_user_id':ACCOUNT['user_id'], 'message_type':2, 'context_token':'wrong'},
               {'from_user_id':ACCOUNT['user_id'], 'message_type':1, 'group_id':'group', 'context_token':'wrong'}]
        with patch.object(self.client, '_request', return_value={'msgs':bad}): self.client._poll_messages()
        self.assertFalse(self.client.status()['ready'])
        self.assertEqual(self.client.state['context_token'], 'fresh-context')

    def test_request_headers_business_errors_and_redaction(self):
        opener = Mock()
        with patch('discord_archive.clawbot.build_opener', return_value=opener):
            opener.open.return_value = Response({'ret':0})
            self.client._request(API, 'ilink/bot/getconfig', {}, token='fictional-token')
            request = opener.open.call_args.args[0]
            self.assertEqual(request.get_header('Authorization'), 'Bearer fictional-token')
            self.assertEqual(json.loads(request.data)['base_info']['bot_agent'], 'DiscordArchive/1.0')
            for code, flag in [(-2,'needs_message'), (-14,'needs_rebind')]:
                opener.open.return_value = Response({'ret':code,'errmsg':'fictional-token'})
                with self.assertRaises(ClawBotNeedsAction) as error:
                    self.client._request(API, 'ilink/bot/sendmessage', {}, token='fictional-token')
                self.assertNotIn('fictional-token', str(error.exception))
                self.assertTrue(self.client.state[flag])
            opener.open.side_effect = HTTPError('fictional-token', 403, 'fictional-token', {}, None)
            with self.assertRaises(ClawBotError) as error: self.client._request(API, 'endpoint')
            self.assertNotIn('fictional-token', str(error.exception))

    def test_file_upload_is_encrypted_and_acknowledged_with_no_token_to_cdn(self):
        self.bind(); path = self.root/'original.png'; path.write_bytes(b'fictional-original-bytes')
        calls=[]
        def request(base, endpoint, body=None, **kwargs):
            calls.append((endpoint, body))
            if endpoint.endswith('getuploadurl'): return {'upload_full_url':'https://novac2c.cdn.weixin.qq.com/c2c/upload?key=fixture'}
            # Actual iLink sendmessage may return {} after successful delivery.
            return {}
        opener=Mock();opener.open.return_value=Response(b'', {'x-encrypted-param':'download-fixture'})
        with patch.object(self.client, '_request', side_effect=request), patch('discord_archive.clawbot.build_opener', return_value=opener):
            self.client.send_file(path, 'title', self.client.binding_id())
        self.assertEqual(calls[0][1]['media_type'], 3)
        upload=opener.open.call_args.args[0]
        self.assertIsNone(upload.get_header('Authorization'))
        self.assertNotEqual(upload.data, path.read_bytes())
        item=calls[1][1]['msg']['item_list'][0]
        self.assertEqual(item['type'], 4)
        self.assertEqual(item['file_item']['file_name'], path.name)
        self.assertEqual(item['file_item']['len'], str(path.stat().st_size))
        self.assertEqual(len(base64.b64decode(item['file_item']['media']['aes_key'])), 32)
        with self.assertRaises(ClawBotNeedsAction): self.client.send_file(path, 'title', 'other-binding')

    def test_crypto_matches_nist_aes_block_and_qr_png_is_real(self):
        key=bytes.fromhex('000102030405060708090a0b0c0d0e0f')
        plaintext=bytes.fromhex('00112233445566778899aabbccddeeff')
        encrypted=helper('encrypt', key+plaintext)
        self.assertEqual(encrypted[:16].hex(), '69c4e0d86a7b0430d8cdb78070b4c55a')
        self.assertEqual(len(encrypted),32)
        png=helper('qr', b'https://weixin.qq.com/fictional')
        self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(struct.unpack('>II', png[16:24]),(320,320))

    def test_session_failure_waits_for_new_message_and_retries_only_after_it(self):
        self.bind(); settings=Settings(self.root)
        outbox=DeliveryOutbox(self.root, settings, self.credentials)
        key=outbox.enqueue_test('clawbot')
        outbox.clawbot._save(needs_message=True)
        self.assertEqual(outbox.send(key)['status'], 'attention')
        self.assertIsNone(outbox.due(manual_only=True))
        # A fresh incoming message makes the durable waiting item eligible again.
        outbox.clawbot._save(needs_message=False, context_token='new-context')
        self.assertEqual(outbox.due(manual_only=True),key)
        with patch.object(outbox.clawbot, 'send_file') as send:
            self.assertEqual(outbox.send(key)['status'], 'sent'); send.assert_called_once()
        self.assertEqual(outbox.send(key)['deduplicated'],True)


if __name__ == '__main__': unittest.main()
