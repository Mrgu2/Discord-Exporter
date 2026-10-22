import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

from discord_archive.browser_login import BrowserLogin
from discord_archive.collector import AuthRequired,DiscordAPIError


TOKEN="synthetic_local_test_token_never_a_real_secret"


class BrowserLoginTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.root=Path(self.temporary.name)
        self.credentials=Mock()
        self.credentials.set.return_value="keychain"
        self.client=Mock()
        self.client.get.return_value={"id":"123456789","username":"test_user","global_name":"测试用户","email":"not-returned@example.invalid"}
        self.factory=Mock(return_value=self.client)
        self.runner=Mock(return_value=subprocess.CompletedProcess([],0,json.dumps({"status":"candidate","token":TOKEN}),""))
        self.login=BrowserLogin(self.root,self.credentials,client_factory=self.factory,runner=self.runner)

    def tearDown(self):
        self.temporary.cleanup()

    def connect(self):
        with patch.object(BrowserLogin,"_node",return_value="/test/node"):
            return self.login.connect()

    def test_validates_identity_before_saving_and_never_returns_token(self):
        events=[]
        self.client.get.side_effect=lambda path:(events.append("verify") or {"id":"123","username":"verified"})
        self.credentials.set.side_effect=lambda kind,value:(events.append("save") or "keychain")
        result=self.connect()
        self.assertEqual(events,["verify","save"])
        self.client.get.assert_called_once_with("/users/@me")
        self.credentials.set.assert_called_once_with("discord",TOKEN)
        self.assertEqual(result["status"],"connected")
        self.assertEqual(result["id"],"123")
        self.assertNotIn(TOKEN,repr(result))
        self.assertNotIn("email",result)
        command=self.runner.call_args.args[0]
        self.assertEqual(command[2],str(self.root/"data"/"browser-profile"))
        self.assertEqual((self.root/"data"/"browser-profile").stat().st_mode&0o777,0o700)
        self.assertTrue(self.runner.call_args.kwargs["capture_output"])
        self.assertEqual(self.runner.call_args.kwargs["timeout"],570)
        self.assertEqual(command[3],"565000")

    def test_cancelled_and_timeout_preserve_existing_credentials(self):
        for status in ("cancelled","timeout"):
            self.runner.return_value=subprocess.CompletedProcess([],0,json.dumps({"status":status}),"")
            result=self.connect()
            self.assertEqual(result["status"],status)
            self.credentials.set.assert_not_called()
            self.factory.assert_not_called()

    def test_process_timeout_is_safe_even_when_exception_contains_token(self):
        self.runner.side_effect=subprocess.TimeoutExpired("browser",150,output=TOKEN,stderr=TOKEN)
        result=self.connect()
        self.assertEqual(result["status"],"timeout")
        self.assertNotIn(TOKEN,repr(result))
        self.credentials.set.assert_not_called()

    def test_invalid_or_missing_candidate_never_calls_api(self):
        for token in (None,"",123,"short","unsafe value with spaces"):
            self.runner.return_value=subprocess.CompletedProcess([],0,json.dumps({"status":"candidate","token":token}),TOKEN)
            result=self.connect()
            self.assertEqual(result["status"],"error")
            self.credentials.set.assert_not_called()
            self.factory.assert_not_called()
            self.assertNotIn(TOKEN,repr(result))

    def test_api_failure_does_not_save_or_expose_raw_error(self):
        for error in (AuthRequired(401,TOKEN),DiscordAPIError(0,TOKEN),DiscordAPIError(429,TOKEN),OSError(TOKEN),RuntimeError(TOKEN)):
            self.runner.return_value=subprocess.CompletedProcess([],0,json.dumps({"status":"candidate","token":TOKEN}),"")
            self.client.get.side_effect=error
            result=self.connect()
            self.assertEqual(result["status"],"error")
            self.assertNotIn(TOKEN,repr(result))
            self.credentials.set.assert_not_called()

    def test_invalid_identity_and_save_failure_are_safe(self):
        self.client.get.return_value={"id":"bad", "username":TOKEN}
        result=self.connect()
        self.assertEqual(result["code"],"invalid_identity")
        self.credentials.set.assert_not_called()
        self.client.get.return_value={"id":"123","username":"user"}
        self.runner.return_value=subprocess.CompletedProcess([],0,json.dumps({"status":"candidate","token":TOKEN}),"")
        self.credentials.set.side_effect=RuntimeError(TOKEN)
        result=self.connect()
        self.assertEqual(result["code"],"credential_save_failed")
        self.assertNotIn(TOKEN,repr(result))

    def test_private_file_backend_is_reported_honestly(self):
        self.credentials.set.return_value="private_file"
        result=self.connect()
        self.assertEqual(result["credential_backend"],"private_file")

    def test_malformed_output_and_missing_runtime_are_safe(self):
        self.runner.return_value=subprocess.CompletedProcess([],1,TOKEN,TOKEN)
        result=self.connect()
        self.assertEqual(result["status"],"error")
        self.assertNotIn(TOKEN,repr(result))
        self.credentials.set.assert_not_called()
        with patch.object(BrowserLogin,"_node",return_value=None):
            result=self.login.connect()
        self.assertEqual(result["code"],"node_missing")


if __name__=="__main__":unittest.main()
