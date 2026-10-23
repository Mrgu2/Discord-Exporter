"""Local-only, content-addressed speech derivatives; Discord evidence is immutable."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .assets import is_audio_asset, iter_message_assets
from .settings import atomic_json
from .store import utc_now


def local_model():
    hub = Path.home()/'.cache/huggingface/hub'
    # Prefer a compact multilingual model, then the existing medium. Tiny is
    # a fallback: its financial vocabulary was noticeably worse in acceptance.
    for name in ('whisper-small-mlx', 'whisper-small', 'whisper-medium-mlx', 'whisper-base-mlx', 'whisper-base', 'whisper-tiny'):
        base = hub/f'models--mlx-community--{name}'
        for folder in sorted((base/'snapshots').glob('*'), reverse=True):
            if (folder/'config.json').is_file() and any((folder/name).is_file() for name in ('weights.npz','weights.safetensors')):
                return folder
    return None


class SpeechArchive:
    def __init__(self, root, options=None):
        self.root = Path(root)
        self.options = options or {}
        self.directory = self.root/'data/transcripts'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.last_summary = {}

    def configuration(self):
        if self.options.get('enabled', True) is False:
            raise ValueError('本地语音转写已关闭')
        python = Path(self.options.get('python') or self.root/'.venv/whisper/bin/python')
        model = Path(self.options['model_path']).expanduser() if self.options.get('model_path') else local_model()
        if not python.is_file() or not os.access(python, os.X_OK):
            raise ValueError('本地语音环境未安装，请按 README 的语音设置安装后重新出稿')
        if not model or not (model/'config.json').is_file():
            raise ValueError('未找到本机多语言 Whisper 模型，请在本机配置 speech.model_path 后重新出稿')
        config = json.loads((model/'config.json').read_text())
        if config.get('n_vocab', 0) < 51865:
            raise ValueError('当前 Whisper 是英文专用模型，请选择多语言模型')
        weights = next((model/name for name in ('weights.safetensors','weights.npz') if (model/name).is_file()), None)
        if not weights:
            raise ValueError('本机 Whisper 模型权重不完整')
        language = str(self.options.get('language') or 'zh')
        stamp = weights.stat()
        descriptor = {'schema':1,'engine':'mlx-whisper','model':str(model.resolve()),
            'weights':str(weights.resolve()),'bytes':stamp.st_size,'mtime_ns':stamp.st_mtime_ns,
            'config':config,'language':language,'temperature':0,'condition_on_previous_text':False,
            'runner_sha256':hashlib.sha256((Path(__file__).resolve().parent.parent/'scripts/transcribe_local.py').read_bytes()).hexdigest()}
        fingerprint = hashlib.sha256(json.dumps(descriptor,sort_keys=True).encode()).hexdigest()
        return {'python':str(python.absolute()),'model':str(model.resolve()),'language':language,
            'model_name':model.parent.parent.name.removeprefix('models--mlx-community--'), 'fingerprint':fingerprint}

    def _asset(self, record, config):
        filename = record.get('file') or ''
        path = self.root/'data/media'/filename
        if record.get('status') != 'saved' or Path(filename).name != filename or not path.is_file():
            raise ValueError('语音原文件尚未保存')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        identity = hashlib.sha256(f'{digest}:{config["fingerprint"]}'.encode()).hexdigest()
        return {'key':identity,'audio_sha256':digest,'path':str(path.absolute()),'model_fingerprint':config['fingerprint']}

    def _cached(self, asset):
        try:
            result = json.loads((self.directory/f'{asset["key"]}.json').read_text())
            if (result.get('status') == 'complete' and result.get('audio_sha256') == asset['audio_sha256']
                    and result.get('model_fingerprint') == asset['model_fingerprint']
                    and isinstance(result.get('text'), str) and isinstance(result.get('segments'), list)):
                return result
        except (OSError, ValueError):
            pass
        return None

    def process_saved(self, media, keys=None, progress=None):
        selected = {key:record for key,record in media.manifest.items()
            if (keys is None or key in keys) and is_audio_asset(record)}
        summary = {'total':len(selected),'complete':0,'cached':0,'failed':0,'model':None}
        if not selected:
            return summary
        try:
            config = self.configuration()
        except (OSError, ValueError) as exc:
            summary.update(failed=len(selected),error=str(exc))
            self.last_summary = summary
            return summary
        summary['model'] = config['model_name']
        pending, asset_keys = {}, {}
        for key,record in selected.items():
            try:
                asset = self._asset(record,config)
                if self._cached(asset):
                    summary['cached'] += 1
                    summary['complete'] += 1
                else:
                    pending[asset['key']] = asset
                    asset_keys[key] = asset
            except (OSError, ValueError):
                summary['failed'] += 1
        started = time.perf_counter()
        if pending:
            if progress:
                progress(f'正在本地转写 {len(pending)} 条语音')
            # One process per batch: MLX keeps the model warm across clips, then
            # releases all model/GPU memory when the process exits.
            with tempfile.TemporaryDirectory(prefix='speech-',dir=self.directory) as temporary:
                request = Path(temporary)/'request.json'
                atomic_json(request,{'model':config['model'],'language':config['language'],
                    'model_name':config['model_name'],'output':str(self.directory.absolute()),'assets':list(pending.values())})
                environment = {key:value for key,value in os.environ.items()
                    if key not in {'DISCORD_ARCHIVE_TOKEN','ARCHIVE_MODEL_KEY','OPENAI_API_KEY'}}
                environment.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',TOKENIZERS_PARALLELISM='false',
                    PATH=os.pathsep.join(dict.fromkeys([str(Path(shutil.which('ffmpeg') or '/opt/homebrew/bin/ffmpeg').parent),environment.get('PATH','')])) )
                try:
                    result = subprocess.run([config['python'],str(Path(__file__).resolve().parent.parent/'scripts/transcribe_local.py'),str(request)],
                        capture_output=True,text=True,timeout=900,env=environment)
                    if result.returncode:
                        summary['error'] = '本地语音转写未完成；原音频已保留，重新出稿会重试'
                except (OSError, subprocess.SubprocessError):
                    summary['error'] = '本地语音转写未完成；原音频已保留，重新出稿会重试'
            for asset in asset_keys.values():
                if self._cached(asset):
                    summary['complete'] += 1
                else:
                    summary['failed'] += 1
        summary['elapsed_seconds'] = round(time.perf_counter()-started,4)
        self.last_summary = summary
        atomic_json(self.directory/'status.json',{'updated_at':utc_now(),**summary})
        return summary

    def attach(self, objects, media):
        """Annotate selected message objects, including reference snapshots, never SQL."""
        try:
            config = self.configuration()
        except (OSError,ValueError) as exc:
            config, error = None,str(exc)
        seen = set()
        def visit(value):
            if isinstance(value,dict):
                if id(value) in seen:
                    return
                seen.add(id(value))
                if value.get('channel_id') and value.get('message_id') and 'content' in value:
                    transcripts = []
                    for attachment in iter_message_assets(value):
                        if not is_audio_asset(attachment):
                            continue
                        key = f'{value["channel_id"]}/{value["message_id"]}/{attachment["id"]}'
                        record = media.manifest.get(key,{})
                        result = None
                        if config:
                            try:
                                result = self._cached(self._asset(record,config))
                            except (OSError,ValueError):
                                pass
                        transcripts.append({'asset_id':attachment['id'],**(result or {'status':'pending','text':'',
                            'error':error if not config else '语音尚未转写成功，重新出稿可重试'})})
                    if transcripts:
                        value['audio_transcripts'] = transcripts
                for key,item in list(value.items()):
                    if key not in {'raw','normalized','audio_transcripts'}:
                        visit(item)
            elif isinstance(value,list):
                for item in value:
                    visit(item)
        visit(objects)
