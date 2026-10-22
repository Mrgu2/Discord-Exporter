"""Connect via an explicitly launched, dedicated browser profile.

This module never opens the user's everyday Chrome profile. Browser output is
an internal credential-bearing pipe: callers receive only a verified identity.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .collector import AccessDenied, AuthRequired, DiscordAPIError, DiscordClient


_connect_lock = threading.Lock()


class BrowserLogin:
    def __init__(self, root, credentials, *, client_factory=None, runner=None, timeout=600):
        self.root,self.credentials = Path(root),credentials
        self.client_factory,self.runner = client_factory,runner
        self.timeout = max(1,min(600,float(timeout)))

    @staticmethod
    def _result(status,message,**extra):
        return {"status":status,"name":None,"id":None,"message":message,**extra}

    @staticmethod
    def _node():
        discovered = shutil.which("node")
        if discovered:
            return discovered
        for candidate in ("/opt/homebrew/bin/node","/usr/local/bin/node"):
            if Path(candidate).is_file():
                return candidate
        return None

    def _client(self,token,deadline):
        if self.client_factory:
            return self.client_factory(token)
        def transport(method,url,headers):
            # The existing client supplies only Discord API URLs. A short,
            # bounded identity check leaves time to save to the OS keychain.
            remaining = deadline-time.monotonic()-13
            if remaining <= 0:
                raise TimeoutError
            request = Request(url,headers=headers,method=method)
            try:
                with urlopen(request,timeout=max(0.1,min(5,remaining/3))) as response:
                    return response.status,dict(response.headers),json.load(response)
            except HTTPError as exc:
                return exc.code,dict(exc.headers),{}
        def bounded_sleep(seconds):
            remaining = deadline-time.monotonic()-13
            if remaining <= seconds:
                raise TimeoutError
            time.sleep(seconds)
        return DiscordClient(token,transport=transport,sleep=bounded_sleep)

    def connect(self):
        if not _connect_lock.acquire(blocking=False):
            return self._result("busy","已有登录窗口正在等待操作，请完成或关闭那个窗口。")
        candidate = None
        try:
            deadline = time.monotonic()+self.timeout
            node = self._node()
            if not node:
                return self._result("error","连接需要 Node.js，请先安装后重试。",code="node_missing")
            profile = self.root/"data"/"browser-profile"
            profile.mkdir(parents=True,exist_ok=True,mode=0o700)
            os.chmod(profile,0o700)
            script = Path(__file__).resolve().parent.parent/"scripts"/"connect_browser.mjs"
            process_budget = min(570,max(1,self.timeout-30))
            browser_wait_ms = max(250,int((process_budget-5)*1000))
            try:
                # This stdout may contain the candidate credential. It is never
                # returned, logged, or included in an exception message.
                completed = (self.runner or subprocess.run)([
                    node,str(script),str(profile),str(browser_wait_ms)
                ],capture_output=True,text=True,timeout=process_budget,start_new_session=True)
            except subprocess.TimeoutExpired:
                return self._result("timeout","登录等待已超时。请再次点击连接，在专用窗口中完成登录。")
            except (OSError,ValueError):
                return self._result("error","无法打开专用登录窗口，请确认 Chrome 与 Node.js 已安装。",code="launch_failed")
            try:
                if len(completed.stdout or "") > 16384:
                    raise ValueError
                payload = json.loads(completed.stdout or "{}")
                if not isinstance(payload,dict):
                    raise ValueError
            except (ValueError,TypeError):
                return self._result("error","登录窗口返回异常，请重试；未保存凭证。",code="invalid_browser_result")
            status = payload.get("status")
            if status == "cancelled":
                return self._result("cancelled","已关闭登录窗口；未更改已保存的连接。")
            if status == "timeout":
                return self._result("timeout","登录等待已超时。请再次点击连接，在专用窗口中完成登录。")
            if completed.returncode or status != "candidate":
                return self._result("error","无法连接专用登录窗口，请确认 Chrome 可正常打开后重试。",code="browser_unavailable")
            candidate = payload.get("token")
            # Discard the credential-bearing subprocess strings as soon as the
            # candidate has been copied into the narrow verification path.
            completed.stdout = ""
            completed.stderr = ""
            payload.clear()
            if not isinstance(candidate,str) or not 16 <= len(candidate) <= 4096 or any(character.isspace() for character in candidate):
                return self._result("error","尚未识别到有效登录，请在专用窗口中完成 Discord 登录后重试。",code="no_candidate")
            if time.monotonic() >= deadline:
                return self._result("timeout","连接验证超时，请稍后重试；未保存凭证。")
            try:
                identity = self._client(candidate,deadline).get("/users/@me")
            except AuthRequired:
                return self._result("error","这次登录未通过 Discord 验证，请重新连接并登录。",code="authentication_failed")
            except AccessDenied:
                return self._result("error","Discord 拒绝了身份验证，请检查账号状态后重试。",code="access_denied")
            except DiscordAPIError as exc:
                if exc.status == 429:
                    return self._result("error","Discord 暂时限流，请稍后重新连接。",code="rate_limited")
                return self._result("error","身份验证暂时失败，请检查网络后重试；未保存凭证。",code="verification_failed")
            except (URLError,OSError,TimeoutError,ValueError,TypeError):
                return self._result("error","身份验证暂时失败，请检查网络后重试；未保存凭证。",code="verification_failed")
            except Exception:
                return self._result("error","身份验证未完成，请重新连接；未保存凭证。",code="verification_failed")
            if not isinstance(identity,dict) or not str(identity.get("id","")).isdigit():
                return self._result("error","Discord 身份响应异常；未保存凭证。",code="invalid_identity")
            if time.monotonic() >= deadline:
                return self._result("timeout","连接验证超时，请稍后重试；未保存凭证。")
            try:
                backend = self.credentials.set("discord",candidate)
            except Exception:
                return self._result("error","登录已验证，但本机凭证保存失败，请重新连接。",code="credential_save_failed")
            name = identity.get("global_name") or identity.get("username") or "Discord 用户"
            return {"status":"connected","id":str(identity["id"]),"name":str(name)[:100],
                "credential_backend":backend,"message":"已验证并保存连接；以后可直接自动保存。"}
        finally:
            candidate = None
            _connect_lock.release()
