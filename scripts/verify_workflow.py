#!/usr/bin/env python3
"""Opt-in HTTP → archive → manuscript → browser-render acceptance check.

Run explicitly, not as a default unit test. Every account, message, credential,
and image is synthetic. Only loopback HTTP is used; the Discord transport is
replaced in memory. Artifacts remain in a new temporary directory for review.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import struct
import sys
import tempfile
import threading
import time
import zlib
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(SOURCE))

from app import Application, make_handler  # noqa: E402
from discord_archive.collector import DiscordClient  # noqa: E402
from discord_archive.settings import atomic_json  # noqa: E402


OWNER = "9001"
CHANNELS = [
    {"id":"101","label":"示例栏目甲","kind":"feed"},
    {"id":"102","label":"示例栏目乙","kind":"feed"},
    {"id":"103","label":"示例栏目丙","kind":"feed"},
    {"id":"104","label":"示例栏目丁","kind":"feed"},
    {"id":"105","label":"示例问答","kind":"qa"},
]
QUESTION = "【虚构提问】观察位置到了，还要等待什么条件？"
ANSWER = "【虚构原话】等走势和量能确认，条件未满足时先观察。"
FOLLOWUP = "【虚构追问】如果尾盘还没确认呢？"
SUPPLEMENT = "【虚构补充】此前条件仍然有效，尾盘没有确认就继续观察。"


def require(condition,message):
    if not condition:
        raise AssertionError(message)


class FakeCredentials:
    """Intentionally has no implementation that can touch a real keychain."""
    def __init__(self,_root):
        pass

    def get(self,kind):
        return "synthetic-workflow-only-credential" if kind == "discord" else None

    def set(self,*_args):
        raise AssertionError("This verification must not write credentials")


def message(channel,identity,content,*,author=OWNER,reference=None,edited=False,attachment=False):
    value = {"id":str(identity),"channel_id":str(channel),"author":{"id":author,"username":"虚构群主" if author == OWNER else "虚构提问者"},
        "timestamp":"2026-10-21T14:00:00Z","content":content}
    if reference:
        value["message_reference"] = {"message_id":str(reference),"channel_id":str(channel)}
    if edited:
        value["edited_timestamp"] = "2026-10-21T14:40:00Z"
    if attachment:
        value["attachments"] = [{"id":"7002","filename":"synthetic.png","url":"https://example.invalid/never-requested.png"}]
    return value


class FakeDiscordTransport:
    def __init__(self):
        self.round = 1
        self.calls = 0
        self.metadata_calls = 0
        self.offline = False
        self.failed_calls = 0

    def __call__(self,method,url,headers):
        location = urlsplit(url)
        match = re.fullmatch(r"/api/v10/channels/(10[1-5])/messages",location.path)
        metadata_match = re.fullmatch(r"/api/v10/channels/(10[1-5])",location.path)
        require(method == "GET" and location.hostname == "discord.com" and (match is not None or metadata_match is not None),"Unexpected synthetic transport request")
        require(headers.get("Authorization") == "synthetic-workflow-only-credential","Unexpected verification credential")
        self.calls += 1
        if self.offline:
            self.failed_calls += 1
            raise URLError('Synthetic transport outage; no network request was made')
        if metadata_match:
            self.metadata_calls += 1
            channel = metadata_match.group(1)
            return 200,{}, {"id":channel,"guild_id":"8000","name":next(row["label"] for row in CHANNELS if row["id"] == channel)}
        channel = match.group(1)
        if channel != "105":
            label = next(row["label"] for row in CHANNELS if row["id"] == channel)
            content = f"【虚构{label}】保留原文、时间和条件。"
            if channel == "101" and self.round == 2:
                content = "【虚构示例栏目甲】原话经过编辑，补充了确认条件。"
            values = [message(channel,int(channel)*100+1,content,edited=channel == "101" and self.round == 2,attachment=channel == "102")]
        else:
            question = message(channel,10501,QUESTION,author="9002")
            answer = message(channel,10502,ANSWER,reference=10501)
            answer["referenced_message"] = copy.deepcopy(question)
            values = [question,answer]
            if self.round == 2:
                values += [message(channel,10503,FOLLOWUP,author="9002",reference=10502),
                    message(channel,10504,SUPPLEMENT,reference=10503),
                    message(channel,10505,"【虚构连续补充】保留条件，不改写成确定判断。")]
        return 200,{},copy.deepcopy(values)


def fixture_png():
    def chunk(kind,data):
        return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
    width,height = 480,240
    raw = b"".join(b"\x00"+bytes((50,80+row%120,140))*width for row in range(height))
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",width,height,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(raw))+chunk(b"IEND",b"")


def verify():
    began = time.monotonic()
    root = Path(tempfile.mkdtemp(prefix="discord-workflow-verify-")).resolve()
    root.chmod(0o700)
    shutil.copytree(SOURCE/"web",root/"web")
    transport = FakeDiscordTransport()
    app = server = server_thread = None
    # Patches surround the complete server lifetime, including its worker. No
    # default credential provider or real Discord client can be reached.
    with patch("app.Credentials",FakeCredentials),patch("discord_archive.worker.DiscordClient",side_effect=lambda token:DiscordClient(token,transport=transport,sleep=lambda _seconds:None)):
        try:
            app = Application(root,host="127.0.0.1",port=0)
            server = ThreadingHTTPServer(("127.0.0.1",0),make_handler(app))
            server.daemon_threads = True
            app.port = server.server_address[1]
            base = f"http://127.0.0.1:{app.port}"
            phone_host = f"192.168.50.20:{app.port}"
            opener = build_opener(ProxyHandler({}))
            server_thread = threading.Thread(target=server.serve_forever,daemon=True)
            server_thread.start()

            def request(path,method="GET",data=None,*,phone=False,cookie=None,expected=200):
                require(path.startswith("/") and not path.startswith("//"),"Only local verification paths are allowed")
                headers = {}
                if phone:
                    headers["Host"] = phone_host
                if cookie:
                    headers["Cookie"] = cookie
                if method != "GET":
                    headers.update({"Content-Type":"application/json","X-Archive-Key":app.csrf})
                body = json.dumps(data,ensure_ascii=False).encode() if data is not None else None
                try:
                    response = opener.open(Request(base+path,data=body,headers=headers,method=method),timeout=5)
                except HTTPError as exc:
                    response = exc
                with response:
                    status,payload,response_headers = response.status,response.read(),dict(response.headers)
                require(status == expected,f"HTTP verification failed for {method} {path}: expected {expected}, got {status}")
                return payload,response_headers

            def json_request(path,method="GET",data=None,**options):
                raw,headers = request(path,method,data,**options)
                return json.loads(raw),headers

            def wait_for_job(predicate,deadline_seconds=40):
                deadline = min(began+100,time.monotonic()+deadline_seconds)
                while time.monotonic() < deadline:
                    status,_ = json_request("/api/status")
                    state = status["state"]
                    idle = not state.get("active_job") and not state.get("queue_length")
                    if idle and state.get("last_job_status") == "failed":
                        raise AssertionError("HTTP-submitted worker job failed: "+str(state.get("last_job_error","unknown error")))
                    if idle and predicate(state.get("last_result") or {}):
                        return state["last_result"]
                    time.sleep(1)
                raise AssertionError("HTTP-submitted worker job exceeded the verification time budget")

            def wait_for_state(predicate,deadline_seconds=50):
                deadline=min(began+100,time.monotonic()+deadline_seconds)
                while time.monotonic()<deadline:
                    status,_=json_request('/api/status')
                    if predicate(status):
                        return status
                    time.sleep(.25)
                raise AssertionError('Scheduled recovery exceeded the verification time budget')

            page,_ = request("/")
            require(b'archive-key' in page and b'connect-browser-button' in page,"Copied web UI or connection entry did not load")
            json_request("/api/config","PUT",{
                "channels":CHANNELS,"target_author_id":OWNER,"target_message_url":"",
                "download_media":False,"schedule":{"enabled":True,"interval_minutes":360,"times":[],"timezone":"America/New_York","window":{"enabled":False,"start":"15:50","end":"16:10","every_minutes":5,"weekdays":[0,1,2,3,4]}}})
            # Exercise the real clock -> due -> queue -> capture path on first
            # startup, without changing the system clock or the user's config.
            # The config route's catch-up slot is unrelated to this assertion.
            app.worker.state["retry_at"] = None
            raw_png = fixture_png()
            media_path = root/"data"/"media"/"synthetic.png"
            media_path.write_bytes(raw_png)
            app.worker.media.manifest["102/10201/7002"] = {"status":"saved","file":"synthetic.png","filename":"synthetic.png","sha256":hashlib.sha256(raw_png).hexdigest(),"bytes":len(raw_png)}
            atomic_json(app.worker.media.path,app.worker.media.manifest)
            app.worker.start()

            first = wait_for_job(lambda result:len(result.get("channels",[])) == 5)
            require(first["status"] == "success","First synthetic capture did not succeed")
            require(all(app.store.get_run(row['run_id'])['trigger']=='scheduled' for row in first['channels']),"The enabled schedule did not drive the real worker queue")
            require(str(app.worker.state.get('last_slot','')).startswith('interval:'),"The scheduled slot was not persisted")
            first_max = max(row["run_id"] for row in first["channels"])
            transport.round = 2
            json_request("/api/capture","POST",{},expected=202)
            second = wait_for_job(lambda result:len(result.get("channels",[])) == 5 and min(row["run_id"] for row in result["channels"]) > first_max)
            require(second["status"] == "success","Second synthetic capture did not succeed")
            source,_ = json_request("/api/source?channel_id=101&message_id=10101")
            require(len(source["versions"]) == 2,"An edited message did not retain both versions")
            counts = app.store.summary()
            require(counts["message_count"] == 9 and counts["version_count"] == 10,"Repeated HTTP captures did not deduplicate or retain edits correctly")

            json_request("/api/drafts","POST",{"scope":"latest","layout":"stacked","mode":"evidence","title":"五频道两轮 · 虚构增量验收"},expected=202)
            incremental = wait_for_job(lambda result:result.get("scope") == "latest" and bool(result.get("evidence_url")))
            delta_evidence,_ = json_request(incremental["evidence_url"])
            delta_ids = {message["message_id"] for panel in delta_evidence["panels"] for message in panel["messages"]}
            require(incremental["message_count"] == 3 and delta_ids == {"10101","10504","10505"},"Latest-round draft repeated unchanged messages or lost an edit/new contribution")
            require(len(delta_evidence["panels"]) == 2,"Unchanged channels were not omitted from the incremental draft")
            json_request("/api/drafts","POST",{"scope":"day","date":"2026-10-21","layout":"stacked","mode":"evidence","title":"五频道两轮 · 虚构交易日验收"},expected=202)
            draft = wait_for_job(lambda result:result.get("scope") == "day" and bool(result.get("evidence_url")))
            require(Path(draft["path"]).is_relative_to(root),"Draft output escaped the isolated root")
            document,_ = request(draft["url"])
            manuscript,_ = request(draft["manuscript_url"])
            evidence,_ = json_request(draft["evidence_url"])
            for quote in (QUESTION,ANSWER,FOLLOWUP,SUPPLEMENT):
                require(quote in document.decode() and quote in manuscript.decode(),"An original question or answer was missing from HTML/Markdown")
            require(len(evidence["panels"]) == 5 and draft["message_count"] == 7,"The five-channel draft lost target-author messages")
            sources = [source for context in evidence["contexts"] for source in context["sources"]]
            require(sources and all(source["url"].startswith("https://discord.com/channels/8000/") for source in sources),"A guild source link incorrectly used the direct-message route")
            require(transport.metadata_calls == 5,"Channel guild metadata was not cached across capture rounds")
            require(b'/media/synthetic.png' in document,"Saved original image was not included in the draft")
            downloaded_media,_ = request("/media/synthetic.png")
            require(downloaded_media == raw_png,"Local media download changed the saved original")

            json_request("/api/render","POST",{"draft_id":draft["id"],"target":"all","render_scale":2},expected=202)
            rendered = wait_for_job(lambda result:bool(result.get("images")) and result.get("draft",{}).get("id") == draft["id"])
            # Status polling carries a summary; full evidence is loaded only
            # when needed for the export acceptance checks.
            rendered['draft'],_ = json_request(f'/drafts/{draft["id"]}/metadata.json')
            require(rendered.get('layout_mode')=='stacked' and len(rendered['images'])==1,'The section strips were not combined into one image')
            require(rendered.get('render_scale')==2,'The workflow did not produce a 2x HiDPI export')
            bands=rendered['draft']['render_verification']['bands']
            require([band['kind'] for band in bands]==['feed','qa'] and bands[0]['width']==bands[1]['width'] and bands[1]['y']>=bands[0]['y']+bands[0]['height'],'The feed and Q&A strips did not stack at equal width')
            all_images = rendered["images"]+[image for column in rendered["single_columns"] for image in column["images"]]
            require(len(rendered["single_columns"]) == 5 and all_images,"Theme mobile exports were not produced")
            dimensions = []
            for image in all_images:
                png,_ = request(image)
                require(png.startswith(b"\x89PNG\r\n\x1a\n"),"Rendered PNG could not be downloaded")
                width,height = struct.unpack(">II",png[16:24])
                require((image in rendered['images'] and width==8472 and height<=64000 and width*height<=320_000_000)
                    or (image not in rendered['images'] and width==2160 and height<=7200),"Rendered image exceeded the output dimensions")
                dimensions.append({"width":width,"height":height})

            json_request("/api/status",phone=True,expected=401)
            request(rendered["images"][0],phone=True,expected=401)
            _,login_headers = json_request("/api/login","POST",{"code":app.code},phone=True)
            cookie = login_headers.get("Set-Cookie","").split(";",1)[0]
            require(cookie.startswith("archive_session="),"Phone pairing did not issue a session")
            phone_status,_ = json_request("/api/status",phone=True,cookie=cookie)
            require("access_code" not in phone_status["remote"],"The phone API exposed the pairing code")
            request(rendered["images"][0],phone=True,cookie=cookie)
            json_request("/api/connect-browser","POST",{},phone=True,cookie=cookie,expected=403)
            require(Path(app.store.db_path).is_relative_to(root) and app.worker.root == root and app.settings.root == root,"A persistent component used the user's workspace data")

            # No manual retry or clock acceleration: the real worker records
            # its normal 30-second backoff and later submits reconnect itself.
            before_failure={row['id']:app.store.channel_status(row['id'])['cursor'] for row in CHANNELS}
            transport.offline=True
            json_request('/api/capture','POST',{},expected=202)
            failed=wait_for_state(lambda status:status['state'].get('last_job_status')=='failed' and not status['state'].get('active_job'))
            failed_run=app.store.list_runs(limit=1)[0]
            require(failed_run['status']=='failed' and failed_run['trigger']=='manual','The synthetic outage was not recorded as a failed attempt')
            require(failed['connectivity']['online'] is False and failed['state'].get('retry_at') and not failed['state'].get('requires_attention'),'Network failure did not enter automatic recovery')
            persisted=json.loads((root/'data/worker-state.json').read_text())
            require(persisted.get('offline_since') and persisted.get('retry_at')==failed['state']['retry_at'],'Recovery state was not persisted')
            require(before_failure=={row['id']:app.store.channel_status(row['id'])['cursor'] for row in CHANNELS},'Failed capture advanced a successful cursor')
            require(transport.failed_calls==3,'The API client did not finish its bounded retries')
            transport.offline=False
            restored_at=time.monotonic()
            recovered=wait_for_state(lambda status:not status['state'].get('active_job') and status['state'].get('last_job_status')=='success'
                and len((status['state'].get('last_result') or {}).get('channels',[]))==5
                and min(row['run_id'] for row in status['state']['last_result']['channels'])>failed_run['run_id'])
            recovery_wait=round(time.monotonic()-restored_at,2)
            require(all(app.store.get_run(row['run_id'])['trigger']=='reconnect' for row in recovered['state']['last_result']['channels']),'Recovery required manual submission')
            require(recovered['connectivity']['online'] is True and recovered['state'].get('offline_since') is None and recovered['state'].get('retry_at') is None and recovered['state'].get('failures')==0,'Successful recovery did not clear offline/backoff state')
            after_recovery=app.store.summary()
            require(after_recovery['message_count']==9 and after_recovery['version_count']==10,'Recovery duplicated messages or lost edit history')
            return {"status":"passed","temporary_root":str(root),"server_url":base,"server_stopped":True,
                "source_counts":{"channels":5,"rounds":2,"successful_capture_rounds":3,"failed_capture_rounds":1,"messages":counts["message_count"],"versions":counts["version_count"],"target_messages":draft["message_count"],"latest_round_target_messages":incremental["message_count"],"fake_api_requests":transport.calls,"metadata_requests":transport.metadata_calls},
                "draft_path":draft["path"],"images":[str(root/unquote(path).lstrip("/")) for path in rendered["images"]],
                "mobile_image_count":len(all_images)-len(rendered["images"]),"image_dimensions":dimensions,
                "stacked_bands":bands,
                "phone_auth":{"unauthenticated":401,"paired":200,"remote_browser_connect":403},
                "schedule_and_recovery":{"scheduled_channels":5,"manual_capture":True,"failed_api_attempts":transport.failed_calls,
                    "failed_cursor_unchanged":True,"persisted_retry":True,"automatic_reconnect_channels":5,"manual_retry":False,"wait_seconds":recovery_wait,"same_worker_thread":True},
                "isolated_data":True,"elapsed_seconds":round(time.monotonic()-began,2)}
        finally:
            if app:
                app.worker.stop_event.set()
                if hasattr(app.worker,"thread"):
                    app.worker.thread.join(timeout=5)
            if server:
                server.shutdown()
                server.server_close()
            if server_thread:
                server_thread.join(timeout=5)
            if app:
                app.store.close()
                app.process_lock.close()


def main():
    try:
        result = verify()
    except Exception as exc:
        print(json.dumps({"status":"failed","error":str(exc)},ensure_ascii=False))
        return 1
    print(json.dumps(result,ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
