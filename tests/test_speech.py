import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from discord_archive.assets import is_audio_asset, iter_message_assets
from discord_archive.editorial import DraftService
from discord_archive.media import MediaArchive
from discord_archive.settings import atomic_json
from discord_archive.speech import SpeechArchive
from discord_archive.store import ArchiveStore


class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.media = MediaArchive(self.root)
        self.speech = SpeechArchive(self.root)
        self.config = {'python':'/fixture/python','model':'/fixture/local-model','language':'zh',
            'model_name':'fixture-small','fingerprint':'model-one'}

    def tearDown(self):
        self.temporary.cleanup()

    def audio(self, message='2', asset='9', payload=b'fake audio'):
        filename = f'{message}-{asset}.ogg'
        (self.media.directory/filename).write_bytes(payload)
        key = f'100/{message}/{asset}'
        self.media.manifest[key] = {'status':'saved','file':filename,'filename':'voice-message.ogg',
            'content_type':'audio/ogg','sha256':hashlib.sha256(payload).hexdigest()}
        atomic_json(self.media.path,self.media.manifest)
        return key

    def fake_runner(self, command, **options):
        self.assertEqual(options['env']['HF_HUB_OFFLINE'],'1')
        self.assertNotIn('DISCORD_ARCHIVE_TOKEN',options['env'])
        request = json.loads(Path(command[-1]).read_text())
        self.assertEqual(request['model'],'/fixture/local-model')
        for asset in request['assets']:
            atomic_json(Path(request['output'])/f'{asset["key"]}.json',{
                'status':'complete','text':'等待确认后平仓。','segments':[{'start':0,'end':2,'text':'等待确认后平仓。'}],
                'audio_sha256':asset['audio_sha256'],'model_fingerprint':asset['model_fingerprint'],'model':'fixture-small'})
        return type('Result',(),{'returncode':0})()

    def test_audio_detection_includes_forwarded_voice_but_not_video(self):
        self.assertTrue(is_audio_asset({'filename':'voice.ogg'}))
        self.assertTrue(is_audio_asset({'content_type':'audio/webm','filename':'voice'}))
        self.assertFalse(is_audio_asset({'content_type':'video/webm','filename':'clip.webm'}))
        assets = iter_message_assets({'message_snapshots':[{'message':{'attachments':[
            {'id':'9','filename':'voice-message.ogg','content_type':'audio/ogg','url':'https://cdn.discordapp.com/attachments/1/9/a.ogg'}]}}]})
        self.assertTrue(assets[0]['is_audio'])
        self.assertFalse(assets[0]['is_image'])

    def test_identical_audio_batches_once_and_reuses_cache_after_restart(self):
        self.audio(); self.audio('3','10')
        with patch.object(self.speech,'configuration',return_value=self.config), \
                patch('discord_archive.speech.subprocess.run',side_effect=self.fake_runner) as runner:
            first = self.speech.process_saved(self.media)
            second = self.speech.process_saved(self.media)
        self.assertEqual(first['complete'],2)
        self.assertEqual(second['cached'],2)
        self.assertEqual(runner.call_count,1)
        restarted = SpeechArchive(self.root)
        with patch.object(restarted,'configuration',return_value=self.config),patch('discord_archive.speech.subprocess.run') as runner:
            self.assertEqual(restarted.process_saved(self.media)['cached'],2)
            runner.assert_not_called()

    def test_audio_or_model_changes_invalidate_cache(self):
        key = self.audio()
        with patch.object(self.speech,'configuration',return_value=self.config), \
                patch('discord_archive.speech.subprocess.run',side_effect=self.fake_runner) as runner:
            self.speech.process_saved(self.media)
            (self.media.directory/self.media.manifest[key]['file']).write_bytes(b'changed audio')
            self.assertEqual(self.speech.process_saved(self.media)['cached'],0)
            self.config['fingerprint']='model-two'
            self.assertEqual(self.speech.process_saved(self.media)['cached'],0)
        self.assertEqual(runner.call_count,3)

    def test_failed_transcription_is_visible_and_retries_without_losing_audio(self):
        key = self.audio()
        with patch.object(self.speech,'configuration',return_value=self.config), \
                patch('discord_archive.speech.subprocess.run',side_effect=TimeoutError('synthetic')):
            # OSError includes TimeoutError; no transcript is manufactured.
            summary = self.speech.process_saved(self.media)
        self.assertEqual(summary['failed'],1)
        self.assertTrue((self.media.directory/self.media.manifest[key]['file']).exists())
        with patch.object(self.speech,'configuration',return_value=self.config), \
                patch('discord_archive.speech.subprocess.run',side_effect=self.fake_runner):
            self.assertEqual(self.speech.process_saved(self.media)['complete'],1)

    def test_voice_context_and_answer_render_in_place_without_mutating_source(self):
        self.audio('1','91',b'question audio');self.audio('2','92',b'answer audio')
        class Settings:
            def read(inner):
                return {'channels':[{'id':'100','label':'示例问答','kind':'qa'}],'target_author_id':'owner',
                    'market_timezone':'America/New_York','day_boundary_hour':4}
        with ArchiveStore(self.root/'archive.sqlite3') as store:
            run=store.start_run('100')
            messages=[{'id':identity,'channel_id':'100','author':{'id':'owner' if identity=='2' else 'member'},
                'timestamp':f'2026-10-22T19:42:0{identity}Z','content':'',
                'attachments':[{'id':'91' if identity=='1' else '92','filename':'voice-message.ogg','content_type':'audio/ogg'}],
                **({'message_reference':{'message_id':'1'}} if identity=='2' else {})} for identity in ('1','2')]
            store.ingest_messages('100',messages,run);store.finish_run(run,True)
            before=copy.deepcopy(store.get_message('100','2'))
            service=DraftService(store,self.root,Settings(),None);service.media=self.media;service.speech=self.speech
            with patch.object(self.speech,'configuration',return_value=self.config), \
                    patch('discord_archive.speech.subprocess.run',side_effect=self.fake_runner):
                draft=service.generate({'scope':'day','date':'2026-10-22','layout':'qa'})
            folder=Path(draft['path']).parent
            archive=(folder/'archive.md').read_text();document=Path(draft['path']).read_text()
            self.assertLess(archive.index('原问题 / 回复背景'),archive.index('语音转写'))
            self.assertLess(archive.index('语音转写'),archive.index('群主原话'))
            self.assertEqual(document.count('语音转写'),2)
            self.assertEqual(document.count('<audio controls'),2)
            self.assertEqual(draft['audio']['complete'],2)
            after=store.get_message('100','2')
            self.assertEqual(before,after)
            evidence=json.loads((folder/'evidence.json').read_text())
            self.assertEqual(evidence['groups'][0]['answers'][0]['content'],'')
            self.assertEqual(evidence['groups'][0]['answers'][0]['audio_transcripts'][0]['status'],'complete')

    def test_missing_model_preserves_voice_in_reading_copy_with_concrete_status(self):
        self.audio()
        message={'channel_id':'100','message_id':'2','content':'','raw':{'attachments':[
            {'id':'9','filename':'voice-message.ogg','content_type':'audio/ogg'}]}}
        with patch.object(self.speech,'configuration',side_effect=ValueError('本机模型尚未配置')):
            self.speech.attach([message],self.media)
        self.assertEqual(message['content'],'')
        self.assertEqual(message['audio_transcripts'][0]['status'],'pending')
        self.assertIn('模型',message['audio_transcripts'][0]['error'])


if __name__ == '__main__':
    unittest.main()
