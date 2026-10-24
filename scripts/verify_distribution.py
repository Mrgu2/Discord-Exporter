#!/usr/bin/env python3
"""Verify a source ZIP in a new HOME, using only local installed dependencies.

Does not access real Discord or keychain: verify_workflow patches both. A second
physical Mac and actual account sign-in remain separate acceptance requirements.
"""
import argparse
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import zipfile
from pathlib import Path


def verify(archive):
    spec = importlib.util.spec_from_file_location('package', Path(__file__).with_name('package_app.py'))
    package = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package)
    receipt = package.verify_zip(archive)
    base = Path(tempfile.mkdtemp(prefix='discord-clean-install-')).resolve()
    home = base / 'home'
    home.mkdir()
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(base)
        for entry in bundle.infolist():
            (base / entry.filename).chmod(stat.S_IMODE(entry.external_attr >> 16) or 0o644)
    root = base / package.ZIP_ROOT
    assert not any((root / name).exists() for name in ('data', 'output', '.runtime', '.venv', 'node_modules'))
    env = {key: value for key, value in os.environ.items() if not key.startswith(('DISCORD_', 'ARCHIVE_', 'PLAYWRIGHT_', 'PYTHON'))}
    env.update(HOME=str(home), npm_config_cache=str(base / 'npm-cache'),
               PLAYWRIGHT_BROWSERS_PATH=str(base / 'browsers'))
    def run(arguments, timeout=180):
        subprocess.run(arguments, cwd=root, env=env, check=True, timeout=timeout)
    # Uses the actual installer with real downloads and real browser checks.
    # No-open prevents connecting to a pre-existing service on this Mac.
    run(['/bin/bash', str(root / 'Install.command'), '--no-open', '--no-system-install'], timeout=600)
    env['PATH'] = str(root / '.runtime/bin') + os.pathsep + env.get('PATH', '')
    (root / 'artifacts').mkdir()
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        run(['node', 'tests/onboarding_check.mjs', f'http://127.0.0.1:{server.server_port}'])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    run([sys.executable, 'scripts/verify_workflow.py'], timeout=240)
    return {'status':'passed', 'package':receipt, 'isolated_root':str(root),
            'new_home':True, 'codex_runtime_used':False, 'private_data_bundled':False,
            'physical_second_mac_tested':False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='干净 HOME 解包、安装与虚构数据全流程验收')
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.archive.resolve()), ensure_ascii=False, indent=2))
