#!/usr/bin/env python3
"""Prepare a strict source allowlist context; never includes host data or tokens."""
import argparse,hashlib,importlib.util,json,shutil,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def prepare(destination,mac,windows):
    destination=Path(destination).resolve()
    if not destination.is_relative_to(ROOT/'dist'):raise ValueError('构建目录须位于项目 dist 中')
    if destination.exists():raise FileExistsError('构建目录已存在，保留旧版本')
    verifier=module('helper_verify',ROOT/'scripts/install_login_assistants.py')
    verifier.verify(mac,{'darwin-arm64'});verifier.verify(windows,{'win32-x64'})
    package=module('source_package',ROOT/'scripts/package_app.py')
    files=package.source_files(ROOT)
    destination.mkdir(parents=True)
    context=destination/'context';context.mkdir()
    records={}
    for source in files:
        relative=source.relative_to(ROOT)
        if relative.parts[0]=='helpers':continue
        target=context/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        records[str(relative)]=hashlib.sha256(source.read_bytes()).hexdigest()
    for name,source in [('login-assistant-mac.zip',mac),('login-assistant-windows.zip',windows)]:
        target=context/'helpers'/name;target.parent.mkdir(exist_ok=True);shutil.copy2(source,target)
        records['helpers/'+name]=hashlib.sha256(source.read_bytes()).hexdigest()
    (context/'models').mkdir();(context/'models/.keep').write_text('Public small model seed; no credentials.\n');records['models/.keep']=hashlib.sha256((context/'models/.keep').read_bytes()).hexdigest()
    (destination/'CONTEXT.json').write_text(json.dumps(records,indent=2))
    archive=destination/'context.tar.gz'
    with tarfile.open(archive,'w:gz') as t:
        for name in records:t.add(context/name,arcname=name)
    return {'context':str(context),'archive':str(archive),'files':len(records)}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--destination',type=Path,required=True);p.add_argument('--mac-helper',type=Path,required=True);p.add_argument('--windows-helper',type=Path,required=True);a=p.parse_args();print(json.dumps(prepare(a.destination,a.mac_helper,a.windows_helper),ensure_ascii=False))
