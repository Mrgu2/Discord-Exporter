#!/usr/bin/env python3
"""Publish verified, explicitly supplied helper archives without executing them."""
import argparse,hashlib,json,os,shutil,tempfile,zipfile
from pathlib import Path,PurePosixPath
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent.parent

def verify(path,platform,require_first_login=True):
    with zipfile.ZipFile(path) as z:
        if sum(i.file_size for i in z.infolist())>400*1024**2:raise ValueError('助手包过大')
        names=z.namelist()
        if len(names)!=len(set(names)):raise ValueError('助手包含重复路径')
        if any(PurePosixPath(n).is_absolute() or '..' in PurePosixPath(n).parts or '\\' in n for n in names):raise ValueError('助手路径无效')
        manifest=json.loads(z.read('ASSISTANT-MANIFEST.json'))
        if manifest.get('platform') not in platform:raise ValueError('助手平台不匹配')
        if require_first_login:
            required={'Browser Extension/manifest.json','Browser Extension/popup.mjs','Browser Extension/launch.mjs','Browser Extension/session.mjs'}
            required.add('Connect Discord.cmd' if manifest['platform']=='win32-x64' else '首次连接 Discord.app/Contents/MacOS/applet')
            if manifest.get('first_login_included') is not True or manifest.get('connection_protocol')!=2 or not required.issubset(names):raise ValueError('此包只有访问功能，缺少首次连接工具；请重新构建 --with-first-login')
        if set(names)!=set(manifest['files'])|{'ASSISTANT-MANIFEST.json'}:raise ValueError('助手清单不匹配')
        for name,digest in manifest['files'].items():
            if hashlib.sha256(z.read(name)).hexdigest()!=digest:raise ValueError('助手校验失败')
    return manifest['platform']

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--mac-zip',type=Path);p.add_argument('--windows-zip',type=Path);a=p.parse_args()
    if not a.mac_zip and not a.windows_zip:raise ValueError('请指定至少一个助手 ZIP')
    values=[('mac',a.mac_zip,{'darwin-arm64','darwin-x64'}),('windows',a.windows_zip,{'win32-x64'})]
    for _,source,platform in values:
        if source:verify(source,platform)
    folder=a.root.resolve()/'.local/login-assistants';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    for kind,source,_ in values:
        if not source:continue
        target=folder/f'login-assistant-{kind}.zip'
        if target.exists():
            backup=a.root/'data/service-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f');backup.mkdir(parents=True,exist_ok=True);shutil.copy2(target,backup/target.name)
        fd,temp=tempfile.mkstemp(dir=folder)
        try:
            with os.fdopen(fd,'wb') as out,source.open('rb') as handle:shutil.copyfileobj(handle,out)
            os.replace(temp,target)
        except Exception:
            # The original published package remains intact on a failed copy.
            raise
    print('助手已校验并发布；只对管理员下载开放。')
if __name__=='__main__':main()
