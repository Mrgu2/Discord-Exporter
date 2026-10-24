#!/usr/bin/env python3
"""Explicit opt-in: download the speech environment and a local model."""
import json
import argparse
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description='安装本地语音环境并检查模型')
    parser.add_argument('--model', choices=['tiny','base','small','medium','large-v3'])
    parser.add_argument('--device', choices=['cpu','cuda'], default='cpu')
    parser.add_argument('--compute-type', choices=['int8','float32','float16','int8_float16'])
    args = parser.parse_args()
    if platform.system() == 'Linux':
        return install_linux(args)
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('语音安装支持 Apple Silicon Mac 和 Linux')
    if args.model or args.device != 'cpu' or args.compute_type:
        raise ValueError('这些模型和设备选项用于 Linux；Mac 使用现有 MLX Medium 路径')
    print('将下载 MLX Whisper 环境和 Medium 多语言模型（约数 GB），语音推理在本机进行。', flush=True)
    environment = ROOT / '.venv/whisper'
    subprocess.run([sys.executable, '-m', 'venv', str(environment)], check=True)
    python = str(environment / 'bin/python')
    subprocess.run([python, '-m', 'pip', 'install', 'mlx-whisper==0.4.3'], check=True)
    # stdout is a machine pipe; progress from Hugging Face goes to stderr.
    script = "from huggingface_hub import snapshot_download; import json; print(json.dumps(snapshot_download('mlx-community/whisper-medium-mlx')))"
    completed = subprocess.run([python, '-c', script], check=True, stdout=subprocess.PIPE, text=True)
    model = json.loads(completed.stdout)
    from discord_archive.speech import SpeechArchive
    from discord_archive.settings import Settings
    options = {'enabled': True, 'language': 'zh', 'python': python, 'model_path': model}
    SpeechArchive(ROOT, options).configuration()
    Settings(ROOT).update({'speech': options})
    print('语音环境与模型检查通过；下次保存或生成稿件会加载配置。')


def install_linux(args):
    size = args.model or 'small'
    precision = args.compute_type or ('float16' if args.device == 'cuda' else 'int8')
    print(f'安装 Linux 本地语音：{size} / {args.device} / {precision}，需要联网下载。', flush=True)
    environment = ROOT / '.venv/whisper-linux'
    subprocess.run([sys.executable, '-m', 'venv', str(environment)], check=True)
    python = str(environment / 'bin/python')
    subprocess.run([python, '-m', 'pip', 'install', 'faster-whisper==1.2.1'], check=True)
    model = ROOT / '.runtime/models' / ('faster-whisper-' + size)
    script = '''import sys
from huggingface_hub import snapshot_download
from faster_whisper import WhisperModel
snapshot_download('Systran/faster-whisper-'+sys.argv[1],local_dir=sys.argv[2],
    allow_patterns=['config.json','model.bin','tokenizer.json','vocabulary.*','preprocessor_config.json'])
WhisperModel(sys.argv[2],device=sys.argv[3],compute_type=sys.argv[4],local_files_only=True)
'''
    subprocess.run([python, '-c', script, size, str(model), args.device, precision], check=True)
    from discord_archive.speech import SpeechArchive
    from discord_archive.settings import Settings
    options = {'enabled':True,'engine':'faster-whisper','language':'zh','python':python,
        'model_path':str(model),'device':args.device,'compute_type':precision}
    SpeechArchive(ROOT, options).configuration()
    Settings(ROOT).update({'speech': options})
    print('语音环境和模型已实际加载；下次保存或生成稿件会启用本地转写。')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('语音安装未完成：' + str(exc), file=sys.stderr)
        raise SystemExit(1)
