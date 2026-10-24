#!/usr/bin/env python3
"""Build standalone Mac/Windows helpers with verified official Node runtimes."""
import argparse,hashlib,json,os,plistlib,re,shutil,stat,subprocess,tarfile,tempfile,zipfile
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parent.parent

def build(platform,destination):
    if platform not in ('darwin-arm64','darwin-x64','win32-x64'):raise ValueError('unsupported platform')
    destination=Path(destination).resolve()
    if destination.exists():raise FileExistsError('保留原包，请使用新的输出目录')
    vendor=ROOT/'node_modules/playwright-core';assert (vendor/'package.json').is_file(),'请先 npm ci'
    cache=ROOT/'.runtime/login-assistant-build';cache.mkdir(parents=True,exist_ok=True)
    system,arch=platform.split('-');suffix='win-x64.zip' if system=='win32' else f'darwin-{arch}.tar.gz'
    base='https://nodejs.org/dist/latest-v22.x/'
    with urlopen(base+'SHASUMS256.txt',timeout=60) as r:manifest=r.read().decode()
    matches=re.findall(r'^([0-9a-f]{64})\s+(node-v22\.[\d.]+-'+re.escape(suffix)+')$',manifest,re.M);assert len(matches)==1
    digest,name=matches[0];archive=cache/name
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest()!=digest:
        with urlopen(base+name,timeout=120) as r:content=r.read()
        assert hashlib.sha256(content).hexdigest()==digest;archive.write_bytes(content)
    destination.mkdir(parents=True);tree=destination/'package';tree.mkdir()
    prefix=name.removesuffix('.tar.gz').removesuffix('.zip')
    if system=='darwin':
        app=tree/'Discord Login Assistant.app'
        script='''on run
set resourcePath to (POSIX path of (path to me)) & "Contents/Resources/"
try
with timeout of 86400 seconds
do shell script (quoted form of (resourcePath & "runtime/node")) & " " & (quoted form of (resourcePath & "assistant/assistant.mjs"))
end timeout
on error errorMessage
display dialog "登录助手未能启动。请确认 Chrome 或 Edge 已安装，并重新解压完整助手包。" buttons {"好"} default button "好"
end try
end run'''
        with tempfile.NamedTemporaryFile(suffix='.applescript',mode='w') as source:
            source.write(script);source.flush();subprocess.run(['osacompile','-o',str(app),source.name],check=True,capture_output=True)
        resources=app/'Contents/Resources';runtime=resources/'runtime';runtime.mkdir()
        with tarfile.open(archive) as bundle:
            binary=bundle.extractfile(prefix+'/bin/node').read();license=bundle.extractfile(prefix+'/LICENSE').read()
        (runtime/'node').write_bytes(binary);(runtime/'node').chmod(0o755)
        target=resources/'assistant';target.mkdir()
        info=app/'Contents/Info.plist';p=plistlib.loads(info.read_bytes());p.update(CFBundleName='Discord Login Assistant',CFBundleIdentifier='local.discordarchive.loginassistant',NSHighResolutionCapable=True);info.write_bytes(plistlib.dumps(p))
    else:
        runtime=tree/'runtime';runtime.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            (runtime/'node.exe').write_bytes(bundle.read(prefix+'/node.exe'));license=bundle.read(prefix+'/LICENSE')
        target=tree/'assistant';target.mkdir()
        (tree/'Start Login Assistant.cmd').write_bytes(b'@echo off\r\ncd /d "%~dp0"\r\nruntime\\node.exe assistant\\assistant.mjs\r\nif errorlevel 1 pause\r\n')
    (tree/'NODE-LICENSE.txt').write_bytes(license)
    for name in ['assistant.mjs','assistant.html','bridge.json']:shutil.copy2(ROOT/'login_assistant'/name,target/name)
    shutil.copytree(vendor,target/'node_modules/playwright-core')
    shutil.copytree(ROOT/'login_assistant/extension',tree/'Browser Extension')
    (tree/'README.txt').write_text('Discord 独立登录助手\n仅需已安装 Chrome 或 Edge，以及已连接本人 Tailscale。\n完整解压；Mac 打开 App，Windows 打开 Start Login Assistant.cmd。\n首次点连接 Discord 账号，打开授权链接确认设备，再本人登录 Discord 并确认绑定。日常可在助手点打开 Ubuntu 工作台，专用私网窗口绕过系统代理，不改全局设置。\n不需要 Python、Node、完整项目或语音模型；关闭后不保留 Discord 会话。\nMac 当前构建架构：'+platform+'；Windows 构建尚需 Windows 实机验收。\nMac 尚未 Developer ID 公证，请仅对可信来源按系统提示允许打开。\n')
    if system=='darwin':
        subprocess.run(['codesign','--force','--sign','-',str(app)],check=True,capture_output=True)
        subprocess.run(['codesign','--verify','--strict',str(app)],check=True,capture_output=True)
    receipt={'platform':platform,'node_archive':name,'node_sha256':digest,'playwright':json.loads((vendor/'package.json').read_text())['version'],'files':{str(p.relative_to(tree)):hashlib.sha256(p.read_bytes()).hexdigest() for p in tree.rglob('*') if p.is_file()}}
    (tree/'ASSISTANT-MANIFEST.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    output=destination/('login-assistant-mac.zip' if system=='darwin' else 'login-assistant-windows.zip')
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as bundle:
        for p in tree.rglob('*'):
            if p.is_file():bundle.write(p,p.relative_to(tree))
    return {'archive':str(output),'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'platform':platform}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--platform',choices=['darwin-arm64','darwin-x64','win32-x64'],required=True);p.add_argument('--destination',type=Path,required=True);a=p.parse_args();print(json.dumps(build(a.platform,a.destination),ensure_ascii=False))
