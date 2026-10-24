#!/usr/bin/env python3
"""Explicit local-audio acceptance: real ASR, cache, manuscript and PNG; no Discord."""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import shutil
import sys
import tempfile
import time

SOURCE=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(SOURCE))
from discord_archive.settings import Settings,atomic_json
from discord_archive.speech import SpeechArchive
from discord_archive.media import MediaArchive
from discord_archive.store import ArchiveStore
from discord_archive.editorial import DraftService


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio',type=Path)
    parser.add_argument('--language',default='zh')
    args=parser.parse_args()
    if not args.audio.is_file(): raise ValueError('测试音频不存在')
    options=dict(Settings(SOURCE).read().get('speech') or {})
    if not options.get('enabled'): raise ValueError('请先安装并启用本地语音')
    options['language']=args.language
    artifacts=SOURCE/'artifacts';artifacts.mkdir(exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='speech-verify-',dir=artifacts))
    settings=Settings(root)
    settings.update({'speech':options,'channels':[{'id':'100','label':'语音验收','kind':'qa'}],
        'target_author_id':'9001','schedule':{'enabled':False}})
    media=MediaArchive(root);speech=SpeechArchive(root,options)
    filename='sample'+args.audio.suffix
    shutil.copyfile(args.audio,media.directory/filename)
    media.manifest['100/2/9']={'status':'saved','file':filename,'filename':filename,
        'content_type':'audio/'+args.audio.suffix.lstrip('.'),
        'sha256':hashlib.sha256((media.directory/filename).read_bytes()).hexdigest()}
    atomic_json(media.path,media.manifest)
    started=time.perf_counter();summary=speech.process_saved(media);elapsed=time.perf_counter()-started
    if summary['complete']!=1: raise RuntimeError(str(summary))
    asset=speech._asset(media.manifest['100/2/9'],speech.configuration())
    receipt=speech._cached(asset)
    if not receipt or not receipt['text'].strip(): raise RuntimeError('没有可核对的转写文字')
    rss=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    if sys.platform=='darwin': rss/=1024
    if speech.process_saved(media)['cached']!=1: raise RuntimeError('未复用转写缓存')
    with ArchiveStore(root/'data/archive.sqlite3') as store:
        run=store.start_run('100')
        store.ingest_messages('100',[{'id':'2','channel_id':'100','author':{'id':'9001','username':'测试用户'},
            'timestamp':'2026-10-24T08:00:00Z','content':'',
            'attachments':[{'id':'9','filename':filename,'content_type':'audio/'+args.audio.suffix.lstrip('.')}]}],run)
        store.finish_run(run,True)
        drafts=DraftService(store,root,settings,None);drafts.media=media;drafts.speech=speech
        draft=drafts.generate({'scope':'latest','layout':'horizontal'})
        folder=root/'output'/draft['id']
        if receipt['text'] not in (folder/'manuscript.md').read_text(): raise RuntimeError('转写未进入文字稿')
        result=drafts.render(draft['id'],target='all',render_scale=2)
        if not result.get('images'): raise RuntimeError('未生成长图')
    report={'passed':True,'engine':receipt['engine'],'device':options.get('device','mlx'),
        'model':receipt['model'],'audio_seconds':receipt['duration_seconds'],
        'inference_seconds':receipt['elapsed_seconds'],'total_seconds':round(elapsed,2),
        'peak_child_rss_mib':round(rss/1024,1),'text':receipt['text'],'cache_reused':True,
        'transcript_in_manuscript':True,'images':result['images'],'root':str(root)}
    atomic_json(root/'acceptance.json',report)
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__': main()
