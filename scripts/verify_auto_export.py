#!/usr/bin/env python3
"""Opt-in scheduled export acceptance using fake Discord and real HTTP/Chrome."""
import hashlib
import json
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote
from urllib.request import ProxyHandler, Request, build_opener
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(SOURCE))
from app import Application, make_handler
from discord_archive.auto_export import ScheduledExporter
from discord_archive.collector import DiscordClient
from discord_archive.settings import atomic_json
from scripts.verify_workflow import CHANNELS, OWNER, FakeCredentials, FakeDiscordTransport, fixture_png


def verify():
    root=Path(tempfile.mkdtemp(prefix='discord-auto-export-')).resolve()
    shutil.copytree(SOURCE/'web',root/'web')
    transport=FakeDiscordTransport();transport.round=2
    now=datetime(2026,10,21,20,15,3,tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return now.astimezone(tz) if tz else now.replace(tzinfo=None)
    app=server=None
    with patch('app.Credentials',FakeCredentials), \
            patch('discord_archive.worker.DiscordClient',side_effect=lambda token:DiscordClient(token,transport=transport,sleep=lambda _:None)), \
            patch('discord_archive.worker.datetime',Clock):
        try:
            app=Application(root,host='127.0.0.1',port=0)
            server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(app));server.daemon_threads=True
            threading.Thread(target=server.serve_forever,daemon=True).start()
            base=f'http://127.0.0.1:{server.server_address[1]}'
            opener=build_opener(ProxyHandler({}))
            def request(path,method='GET',data=None):
                body=json.dumps(data).encode() if data is not None else None
                headers={'X-Archive-Key':app.csrf,'Content-Type':'application/json'}
                with opener.open(Request(base+path,data=body,headers=headers,method=method),timeout=10) as response:
                    payload=response.read()
                return json.loads(payload) if path.startswith('/api/') or path.endswith('.json') else payload
            config=request('/api/config','PUT',{'channels':CHANNELS,'target_author_id':OWNER,
                'download_media':False,'schedule':{'enabled':False},
                'export':{'copy_directory':str(root/'chosen-exports'),'name_prefix':'定时验收'},
                'auto_export':{'enabled':True,'times':['16:15'],'render_scales':[1,2],'target':'all'}})
            app.worker.state['retry_at']=None
            media=root/'data/media/synthetic.png';media.write_bytes(fixture_png())
            app.worker.media.manifest['102/10201/7002']={'status':'saved','file':'synthetic.png','filename':'synthetic.png'}
            atomic_json(app.worker.media.path,app.worker.media.manifest)
            app.worker.start()
            deadline=time.monotonic()+100
            while time.monotonic()<deadline:
                state=request('/api/status')['state'];summary=state['auto_export']
                if summary['last_status']=='failed':raise AssertionError(summary['last_error'])
                if summary['last_status']=='success' and not state.get('active_job'):break
                time.sleep(.25)
            else:raise AssertionError('Scheduled export exceeded acceptance time budget')
            identity=summary['last_draft_id']
            metadata=request(f'/drafts/{identity}/metadata.json')
            assert metadata['date']=='2026-10-21'
            assert metadata['scope']=='day'
            assert metadata['message_count']==7
            files=[]
            for scale in (1,2):
                variant=metadata['image_variants'][str(scale)]
                urls=variant['images']+[url for column in variant['single_columns'] for url in column['images']]
                assert len(urls)==6
                for url in urls:
                    image=request(url);name=Path(unquote(url)).name;copy=root/'chosen-exports'/name
                    assert image.startswith(b'\x89PNG\r\n\x1a\n')
                    assert copy.read_bytes()==image
                    files.append({'name':name,'scale':scale,'bytes':len(image),'sha256':hashlib.sha256(image).hexdigest()})
            assert len(list((root/'chosen-exports').glob('*.png')))==12
            assert len(list((root/'output').glob('*/metadata.json')))==1
            assert all(run['trigger']=='scheduled_export' for run in app.store.list_runs())
            app.worker.stop_event.set();app.worker.thread.join(timeout=3)
            assert not app.worker.thread.is_alive()
            resumed=ScheduledExporter(root)
            assert resumed.due(config,now) is None
            assert resumed.summary(config,now)['last_draft_id']==identity
            assert request('/api/config')['auto_export']['times']==['16:15']
            return {'status':'passed','isolated_root':str(root),'fake_discord_only':True,
                'scheduled_clock_new_york':'2026-10-21 16:15','scheduled_capture_channels':5,
                'whole_trading_day':True,'draft_count':1,'source_messages':7,'files':files,
                'restart_no_duplicate':True,'byte_identical_http_and_copies':True}
        finally:
            if app:
                app.worker.stop_event.set()
                if hasattr(app.worker,'thread'):app.worker.thread.join(timeout=3)
            if server:server.shutdown();server.server_close()
            if app:app.store.close();app.process_lock.close()


if __name__=='__main__':print(json.dumps(verify(),ensure_ascii=False,indent=2))
