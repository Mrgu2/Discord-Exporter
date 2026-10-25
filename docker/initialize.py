#!/usr/bin/env python3
"""Initialize only this container's volumes and load the CPU small model."""
import argparse
import os
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from discord_archive.container_runtime import ensure_identity
from discord_archive.settings import Settings
from discord_archive.speech import SpeechArchive


def main():
    p=argparse.ArgumentParser();p.add_argument('--skip-speech',action='store_true');args=p.parse_args()
    os.umask(0o077);root=Path(os.environ.get('ARCHIVE_ROOT','/app'))
    for name in ('data','output','.runtime/models'):(root/name).mkdir(parents=True,exist_ok=True,mode=0o700)
    ensure_identity(root);settings=Settings(root);config=settings.read()
    if args.skip_speech:
        print('基础环境已准备；语音保留当前设置。');return
    options=config.get('speech') or {}
    if options.get('enabled') and options.get('model_path'):
        checked=SpeechArchive(root,options).configuration()
        if checked['engine']!='faster-whisper':raise ValueError('原语音配置不是容器 CPU 引擎，请先检查，未覆盖配置')
        python=checked['python'];model=checked['model'];device=checked['device'];precision=checked['compute_type']
    else:
        python='/opt/whisper/bin/python';model=str(root/'.runtime/models/faster-whisper-small');device='cpu';precision='int8'
        print('准备 small 多语言模型 / CPU INT8。镜像附带默认模型，模型会保留在独立卷中。',flush=True)
        script="from huggingface_hub import snapshot_download;import sys;snapshot_download('Systran/faster-whisper-small',local_dir=sys.argv[1],allow_patterns=['config.json','model.bin','tokenizer.json','vocabulary.*','preprocessor_config.json'])"
        if not (Path(model)/'model.bin').is_file():
            subprocess.run([python,'-c',script,model],check=True)
        options={'enabled':True,'engine':'faster-whisper','language':'zh','python':python,'model_path':model,'device':device,'compute_type':precision,'cpu_threads':min(4,os.cpu_count() or 1)}
    subprocess.run([python,'-c','from faster_whisper import WhisperModel;import sys;WhisperModel(sys.argv[1],device=sys.argv[2],compute_type=sys.argv[3],local_files_only=True)',model,device,precision],check=True)
    SpeechArchive(root,options).configuration();settings.update({'speech':options})
    print('语音环境和 small 模型已实际加载，配置已保存。',flush=True)
if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(str(exc) if isinstance(exc,ValueError) else '初始化未完成，原资料保留；检查网络或模型目录后重试。',file=sys.stderr);raise SystemExit(1)
