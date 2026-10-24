#!/usr/bin/env python3
"""One offline MLX or CTranslate2 batch; publish each local clip atomically."""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from discord_archive.settings import atomic_json


def main(request_path):
    request = json.loads(Path(request_path).read_text())
    model = Path(request['model'])
    engine = request.get('engine', 'mlx-whisper')
    names = ('model.bin',) if engine == 'faster-whisper' else ('weights.npz','weights.safetensors')
    if not model.is_dir() or not (model/'config.json').is_file() or not any((model/name).is_file() for name in names):
        raise ValueError('Only an existing local model is allowed')
    import numpy as np
    if engine == 'faster-whisper':
        from faster_whisper import WhisperModel
        recognizer = WhisperModel(str(model), device=request.get('device', 'cpu'),
            compute_type=request.get('compute_type', 'int8'), cpu_threads=request.get('cpu_threads', 4),
            local_files_only=True)
    elif engine == 'mlx-whisper':
        import mlx_whisper
    else:
        raise ValueError('Unsupported speech engine')
    output = Path(request['output'])
    completed,failed = 0,0
    for asset in request['assets']:
        try:
            if len(asset['key']) != 64 or any(char not in '0123456789abcdef' for char in asset['key']):
                raise ValueError('Invalid cache key')
            audio = Path(asset['path'])
            if hashlib.sha256(audio.read_bytes()).hexdigest() != asset['audio_sha256']:
                raise ValueError('Audio changed during transcription')
            started = time.perf_counter()
            # The protocol whitelist also prevents media playlists from opening
            # remote resources through ffmpeg. Decode, never upload.
            decoded = subprocess.run(['ffmpeg','-nostdin','-v','error','-protocol_whitelist','file,pipe','-i',str(audio),
                '-t','1800','-f','f32le','-ac','1','-ar','16000','pipe:1'],capture_output=True,timeout=60,check=True)
            samples = np.frombuffer(decoded.stdout,dtype=np.float32).copy()
            if not len(samples) or len(samples) >= 1800*16000:
                raise ValueError('Empty or over-30-minute audio; do not publish a truncated transcript')
            if engine == 'faster-whisper':
                found, info = recognizer.transcribe(samples, language=request['language'], task='transcribe',
                    beam_size=5, temperature=0, condition_on_previous_text=False)
                result = {'language':info.language, 'segments':[
                    {key:getattr(segment,key) for key in ('start','end','text','avg_logprob','no_speech_prob')}
                    for segment in found]}
            else:
                result = mlx_whisper.transcribe(samples,path_or_hf_repo=str(model),language=request['language'],task='transcribe',
                    verbose=None,temperature=0,condition_on_previous_text=False)
            segments = [{key:segment.get(key) for key in ('start','end','text','avg_logprob','no_speech_prob')}
                for segment in result.get('segments',[]) if str(segment.get('text') or '').strip()]
            # Segment line breaks aid reading without inventing punctuation or
            # silently rewriting tickers, quantities, or financial claims.
            text = '\n'.join(segment['text'].strip() for segment in segments).strip()
            receipt = {'status':'complete','text':text,'segments':segments,'language':result.get('language',request['language']),
                'audio_sha256':asset['audio_sha256'],'model_fingerprint':asset['model_fingerprint'],
                'model':request['model_name'],'engine':engine,'duration_seconds':len(samples)/16000,
                'elapsed_seconds':round(time.perf_counter()-started,4)}
            atomic_json(output/f'{asset["key"]}.json',receipt)
            completed += 1
        except Exception:
            failed += 1
    print(json.dumps({'complete':completed,'failed':failed}))
    return int(failed > 0)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))
