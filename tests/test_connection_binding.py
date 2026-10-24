import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch

from discord_archive.connection_binding import bind_connection
from discord_archive.collector import DiscordAPIError
from scripts.bind_linux import ssh_command

TOKEN='fixture_private_credential_never_real'


class BindingTests(unittest.TestCase):
    def worker(self):
        worker=Mock();worker.lock=threading.RLock();worker.state={};worker.jobs=queue.Queue();worker.draining=False
        return worker

    def test_same_account_verifies_before_pausing_and_saving(self):
        worker=self.worker();credentials=Mock();credentials.get.return_value=None
        events=[]
        def client(_):events.append('verify');return Mock(get=Mock(return_value={'id':'9001','username':'fixture'}))
        worker.set_automatic_paused.side_effect=lambda paused:events.append('pause')
        credentials.set.side_effect=lambda *args:events.append('save') or 'file'
        worker.persist.side_effect=lambda:events.append('persist')
        with patch.dict(os.environ,{},clear=True):result=bind_connection(credentials,worker,TOKEN,'9001',client)
        self.assertEqual(events,['verify','pause','save','persist'])
        self.assertTrue(result['automatic_paused']);self.assertNotIn(TOKEN,json.dumps(result))

    def test_failed_or_wrong_identity_never_saves_or_pauses(self):
        for identity in [{'id':'other'},None]:
            worker=self.worker();credentials=Mock()
            client=Mock(return_value=Mock(get=Mock(return_value=identity)))
            with patch.dict(os.environ,{},clear=True),self.assertRaises(ValueError):bind_connection(credentials,worker,TOKEN,'9001',client)
            credentials.set.assert_not_called();worker.set_automatic_paused.assert_not_called()
        worker=self.worker();credentials=Mock()
        client=Mock(return_value=Mock(get=Mock(side_effect=DiscordAPIError(403,'denied'))))
        with patch.dict(os.environ,{},clear=True),self.assertRaisesRegex(ValueError,'未保存'):bind_connection(credentials,worker,TOKEN,'9001',client)
        credentials.set.assert_not_called()

    def test_other_server_account_and_busy_login_are_not_overwritten(self):
        worker=self.worker();credentials=Mock();credentials.get.return_value='old_fixture_credential'
        factory=lambda token:Mock(get=Mock(return_value={'id':'9001' if token==TOKEN else '9002'}))
        with patch.dict(os.environ,{},clear=True),self.assertRaisesRegex(ValueError,'另一账号'):bind_connection(credentials,worker,TOKEN,'9001',factory)
        credentials.set.assert_not_called()
        credentials.get.return_value=None;worker.state['active_job']={'type':'connect_browser'}
        with patch.dict(os.environ,{},clear=True),self.assertRaisesRegex(ValueError,'等待'):bind_connection(credentials,worker,TOKEN,'9001',factory)
        credentials.set.assert_not_called()

    def test_concurrent_binding_cannot_replace_newly_saved_account(self):
        worker=self.worker();credentials=Mock();credentials.get.side_effect=[None,'newly_saved_other_account']
        client=Mock(return_value=Mock(get=Mock(return_value={'id':'9001'})))
        with patch.dict(os.environ,{},clear=True),self.assertRaisesRegex(ValueError,'刚刚发生变化'):
            bind_connection(credentials,worker,TOKEN,'9001',client)
        credentials.set.assert_not_called();worker.set_automatic_paused.assert_not_called()

    def test_ssh_verifies_host_and_secrets_are_not_command_arguments(self):
        with tempfile.NamedTemporaryFile() as known,patch('scripts.bind_linux.shutil.which',return_value='/sshpass'),patch.dict(os.environ,{'OPENAI_API_KEY':'never_forward'},clear=False):
            args,env=ssh_command({'SSH_HOST':'server.example','SSH_USER':'example','SSH_PASSWORD':'fixture_ssh_password'},known.name,'~/archive path')
        self.assertIn('StrictHostKeyChecking=yes',args)
        self.assertNotIn('fixture_ssh_password',' '.join(args));self.assertNotIn(TOKEN,' '.join(args))
        self.assertNotIn('OPENAI_API_KEY',env);self.assertEqual(env['SSHPASS'],'fixture_ssh_password')

    def test_receiver_rejects_wrong_project_before_any_post(self):
        from scripts.receive_connection import receive
        opener=Mock();opener.open.return_value=io.StringIO(json.dumps({'platform':{'system':'linux'},'system':{'project_id':'wrong'}}))
        with tempfile.TemporaryDirectory() as root,patch('scripts.receive_connection.build_opener',return_value=opener),patch('sys.stdin',new=io.StringIO(json.dumps({'credential':TOKEN,'expected_user_id':'9001'}))),self.assertRaises(ValueError):
            receive(root)
        self.assertEqual(opener.open.call_count,1)


if __name__=='__main__':unittest.main()
