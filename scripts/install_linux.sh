#!/usr/bin/env bash
# Install only application-local tools; system packages are an explicit step.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "$(uname -s)" == Linux ]] || { echo '此入口仅支持 Linux。'; exit 1; }
export PATH="$PWD/.runtime/node/bin:$PATH"
python3 -c 'import sys; assert sys.version_info >= (3,10), "需要 Python 3.10+"'
if [[ "${1:-}" == --check ]]; then exec python3 scripts/doctor.py; fi
[[ $# == 0 || ( $# == 1 && "$1" == --with-system-deps ) ]] || { echo '用法：bash scripts/install_linux.sh [--check|--with-system-deps]'; exit 2; }
if ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) < 20 ? 1 : 0)' 2>/dev/null || ! command -v npm >/dev/null; then
  python3 - <<'PY'
import hashlib, json, os, platform, re, tarfile, tempfile
from pathlib import Path
from urllib.request import urlopen
arch = {'x86_64': 'x64', 'aarch64': 'arm64'}.get(platform.machine())
if not arch:
    raise SystemExit('自动安装 Node 仅支持 x86_64 / aarch64')
base = 'https://nodejs.org/dist/latest-v22.x/'
with urlopen(base + 'SHASUMS256.txt', timeout=60) as response:
    manifest = response.read().decode()
matches = re.findall(r'^([0-9a-f]{64})  (node-v22\.[0-9]+\.[0-9]+-linux-' + arch + r'\.tar\.xz)$', manifest, re.M)
if len(matches) != 1:
    raise SystemExit('官方 Node 校验清单异常，未安装')
digest, name = matches[0]
runtime = Path('.runtime'); runtime.mkdir(exist_ok=True)
destination = runtime / name.removesuffix('.tar.xz')
link = runtime / 'node'
if link.exists() or link.is_symlink() or destination.exists():
    raise SystemExit('已有本地 Node 路径但不可用，请检查 .runtime；未覆盖原文件')
print('下载并校验官方 Node：' + name, flush=True)
with tempfile.TemporaryDirectory(prefix='node-install-', dir=runtime) as temporary:
    archive = Path(temporary) / name
    checksum = hashlib.sha256()
    with urlopen(base + name, timeout=120) as response, archive.open('wb') as target:
        while chunk := response.read(1024 * 1024):
            target.write(chunk); checksum.update(chunk)
    if checksum.hexdigest() != digest:
        raise SystemExit('Node SHA-256 校验失败，未解包')
    with tarfile.open(archive) as bundle:
        prefix = name.removesuffix('.tar.xz')
        for member in bundle.getmembers():
            path = Path(member.name)
            if path.is_absolute() or '..' in path.parts or path.parts[0] != prefix:
                raise SystemExit('Node 压缩包路径异常，未解包')
            if member.issym() or member.islnk():
                target = Path(member.linkname)
                resolved = Path(os.path.normpath(str(path.parent / target if member.issym() else target)))
                if target.is_absolute() or not resolved.parts or resolved.parts[0] != prefix or '..' in resolved.parts:
                    raise SystemExit('Node 压缩包链接异常，未解包')
        bundle.extractall(runtime)
link.symlink_to(destination.name, target_is_directory=True)
(runtime / 'node-install.json').write_text(json.dumps({'archive': name, 'sha256': digest}) + '\n')
PY
fi
export npm_config_cache="$PWD/.runtime/npm-cache"
npm ci --ignore-scripts --no-audit --no-fund
if [[ "${1:-}" == --with-system-deps ]]; then
  sudo env PATH="$PATH" node node_modules/playwright/cli.js install-deps chromium
  sudo apt-get install -y python3-venv ffmpeg fonts-noto-cjk
fi
node node_modules/playwright/cli.js install chromium
python3 scripts/doctor.py
echo 'Linux 环境检查通过。启动：PATH="$PWD/.runtime/node/bin:$PATH" python3 app.py --host 127.0.0.1'
