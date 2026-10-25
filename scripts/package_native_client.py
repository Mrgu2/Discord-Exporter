#!/usr/bin/env python3
"""Small native client: Go standard library, no Node/Python/Whisper on the client."""
import argparse,base64,hashlib,json,os,plistlib,re,shutil,subprocess,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

def build(platform,destination,first_login=False):
    destination=Path(destination).resolve()
    if destination.exists():raise FileExistsError('保留旧包，请使用新的输出目录')
    if platform not in ('darwin-arm64','darwin-x64','win32-x64'):raise ValueError('platform')
    manifest=json.loads((ROOT/'login_assistant/native_extension/manifest.json').read_text());public=base64.b64decode(manifest['key']);identity=''.join(chr(97+int(x,16)) for x in hashlib.sha256(public).hexdigest()[:32])
    source=(ROOT/'login_assistant/native_client.go').read_text();assert re.search(r'const extensionID\s*=\s*"'+identity+r'"',source)
    destination.mkdir(parents=True);tree=destination/'package';tree.mkdir()
    system,arch=platform.split('-');env=os.environ.copy();env.update(GOOS='windows' if system=='win32' else 'darwin',GOARCH='amd64' if arch=='x64' else 'arm64',CGO_ENABLED='0',GOCACHE=str(ROOT/'.runtime/go-cache'))
    if system=='darwin':
        app=tree/'Ubuntu Workspace.app';binary=app/'Contents/MacOS/client';binary.parent.mkdir(parents=True)
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'client','CFBundleIdentifier':'local.discordarchive.workspace','CFBundleName':'Ubuntu 工作台','CFBundleDisplayName':'Ubuntu 工作台','CFBundlePackageType':'APPL','CFBundleVersion':'1','LSUIElement':True,'NSHighResolutionCapable':True}))
    else:binary=tree/'Ubuntu Workspace.exe'
    flags='-s -w'+(' -H=windowsgui' if system=='win32' else '')
    subprocess.run(['go','build','-trimpath','-ldflags='+flags,'-o',str(binary),str(ROOT/'login_assistant/native_client.go')],check=True,env=env)
    if system=='darwin':
        binary.chmod(0o755);subprocess.run(['codesign','--force','--sign','-',str(app)],check=True,capture_output=True);subprocess.run(['codesign','--verify','--strict',str(app)],check=True,capture_output=True)
    if first_login:shutil.copytree(ROOT/'login_assistant/native_extension',tree/'Browser Extension')
    if system=='darwin':
        settings=tree/'设置工作台.app'
        script='''on run
set folderPath to do shell script "/usr/bin/dirname " & quoted form of (POSIX path of (path to me))
do shell script (quoted form of (folderPath & "/Ubuntu Workspace.app/Contents/MacOS/client")) & " --configure"
end run'''
        source_path=destination/'settings.applescript';source_path.write_text(script)
        subprocess.run(['osacompile','-o',str(settings),str(source_path)],check=True,capture_output=True)
        subprocess.run(['codesign','--force','--sign','-',str(settings)],check=True,capture_output=True)
        if first_login:
            setup=tree/'首次连接 Discord.app'
            setup_source=destination/'connect.applescript'
            setup_source.write_text('''on run
set folderPath to do shell script "/usr/bin/dirname " & quoted form of (POSIX path of (path to me))
do shell script (quoted form of (folderPath & "/Ubuntu Workspace.app/Contents/MacOS/client")) & " --install-only"
display dialog "本机组件已就绪。请在 Chrome / Edge 加载同目录的 Browser Extension（只需一次）；回到日常 Discord 标签页，点扩展图标，识别并确认账号。" buttons {"好"} default button "好" with title "首次连接 Discord"
end run''')
            subprocess.run(['osacompile','-o',str(setup),str(setup_source)],check=True,capture_output=True)
            subprocess.run(['codesign','--force','--sign','-',str(setup)],check=True,capture_output=True)
    else:
        (tree/'设置工作台.cmd').write_bytes(b'@echo off\r\n"%~dp0Ubuntu Workspace.exe" --configure\r\n')
        if first_login:
            (tree/'Connect Discord.cmd').write_bytes(b'@echo off\r\nstart "" /wait "%~dp0Ubuntu Workspace.exe" --install-only\r\necho Load Browser Extension once, then click its icon on your signed-in Discord tab.\r\npause\r\n')
    go_root=Path(subprocess.check_output(['go','env','GOROOT'],text=True).strip());license=next(p for p in [go_root/'LICENSE',go_root.parent/'LICENSE'] if p.is_file());shutil.copy2(license,tree/'GO-LICENSE.txt')
    instructions='Ubuntu 工作台轻客户端\n日常访问已有 Ubuntu：登录同一个 Tailscale 账号，双击 Ubuntu Workspace。无需重新绑定 Discord、扩展、网页配对或 SSH 隧道。\n自动发现同私网中名称以 discordarchive 开头的工作台；找不到才输入一次 HTTPS 地址。设置工具可修改日常访问地址。\n不需要完整项目、Python、Node、Playwright 或语音模型；日常启动不注册浏览器组件。\n'
    if first_login:
        instructions+='首次连接本机 Docker：先打开本机工作台，下载带本机地址的连接包；不需要 Tailscale。跨电脑连接使用 Tailscale HTTPS。\n首次连接：Mac 双击“首次连接 Discord.app”，Windows 双击 Connect Discord.cmd；仅安装当前用户的本机连接组件。Chrome/Edge 的扩展管理页开启开发者模式，加载本目录 Browser Extension（一次）。在日常浏览器正常登录 Discord，回到 Discord 标签页点扩展图标，点击识别，核对服务器和账号后确认。连接完成后 Ubuntu 可独立运行；以后换电脑无需重复。\n当前扩展未上架，首次手动加载仍需本人操作。验证码由本人在日常浏览器处理，本工具不绕过人机验证。\n'
    instructions+='Windows x64 与 Intel Mac 尚待实机验证；Mac 本地签名，尚无 Developer ID 公证。账号连接迁移不是 Discord 官方 OAuth。\n'
    (tree/'README.txt').write_text(instructions)


    record={'platform':platform,'kind':'native-access','first_login_included':first_login,'connection_protocol':2,'extension_id':identity,'go':subprocess.check_output(['go','version'],text=True).strip(),'files':{str(p.relative_to(tree)):hashlib.sha256(p.read_bytes()).hexdigest() for p in tree.rglob('*') if p.is_file()}}
    (tree/'ASSISTANT-MANIFEST.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
    output=destination/('login-assistant-mac.zip' if system=='darwin' else 'login-assistant-windows.zip')
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as z:
        for p in tree.rglob('*'):
            if p.is_file():z.write(p,p.relative_to(tree))
    return {'archive':str(output),'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'platform':platform,'kind':'native-access'}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--platform',choices=['darwin-arm64','darwin-x64','win32-x64'],required=True);p.add_argument('--destination',type=Path,required=True);p.add_argument('--with-first-login','--with-experimental-binding',dest='first_login',action='store_true');a=p.parse_args();print(json.dumps(build(a.platform,a.destination,a.first_login),ensure_ascii=False))
