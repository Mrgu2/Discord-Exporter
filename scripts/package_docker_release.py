#!/usr/bin/env python3
"""Build Docker installers; the complete edition includes the offline image."""
import argparse,hashlib,importlib.util,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def package(destination, edition="linux", html_directory=None):
 destination=Path(destination).resolve()
 if not destination.is_relative_to(ROOT/'dist'):raise ValueError('输出必须位于 dist')
 image=destination/'discordarchive-linux-amd64.tar.gz'
 if not image.is_file():raise ValueError('请先准备已验收的离线镜像')
 names={'linux':'DiscordArchive-Docker-linux-amd64.zip','desktop':'DiscordArchive-Docker-desktop-preview.zip','complete':'DiscordArchive-Docker-complete-preview.zip'}
 out=destination/names[edition]
 if out.exists():raise FileExistsError('保留旧包，请使用新目录')
 spec=importlib.util.spec_from_file_location('source_package',ROOT/'scripts/package_app.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 image_hash=digest(image);entries={}
 for name in ['compose.yaml','Install-Docker.sh','Start-Docker.sh','Stop-Docker.sh','Configure-Tailscale.sh','Doctor-Docker.sh']:
  entries[name]=(ROOT/'docker'/name).read_bytes()
 for name in ['Archive-Docker.psm1']+[base+extension for base in ['Install-Docker','Start-Docker','Stop-Docker','Doctor-Docker','Configure-Tailscale','Backup-Docker'] for extension in ['.ps1','.cmd']]:
  entries[name]=(ROOT/'docker'/name).read_bytes()
 for name in ['compose.exports.example.yaml', 'compose.resources.example.yaml', 'windows.env.example', 'linux.env.example', 'windows.exports.env.example', 'linux.exports.env.example']:
  entries['examples/'+name]=(ROOT/'docker/examples'/name).read_bytes()
 for source in m.source_files(ROOT):
  relative=str(source.relative_to(ROOT))
  if relative=='README.md' or relative.startswith('docs/'):entries[relative]=source.read_bytes()
 entries['README-Docker.md']=('# Discord Archive Docker\n\n'+('完整包已含镜像和 small 模型，无需另下文件。' if edition=='complete' else '这是拆分配置包，需将同版离线镜像放到本目录。')+'\n\nLinux 按 [Ubuntu Docker 教程](docs/DOCKER.md)；Windows 按 [Docker Desktop 预览教程](docs/WINDOWS_DOCKER.md)。目录、端口和变量见 [配置指南](docs/DOCKER_CONFIG.md)。\n\nMac 保留原生安装。容器只管理本应用，不控制 Ubuntu 关机或重启。已有资料保存在独立命名卷中，不要运行 down -v。\n').encode()
 if html_directory is not None:
  html_directory=Path(html_directory).resolve()
  for source in m.source_files(ROOT):
   relative=source.relative_to(ROOT)
   if relative.suffix=='.md':
    rendered=relative.with_suffix('.html');candidate=html_directory/rendered
    if candidate.is_file() and not candidate.is_symlink():entries[str(rendered)]=candidate.read_bytes()
 entries['START-HERE.html']=('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Docker 安装</title><style>body{font:16px/1.7 system-ui;max-width:850px;margin:40px auto;padding:0 20px;color:#25324a}a{color:#355bdc}li{margin:12px 0}</style><h1>Docker 安装</h1><p>PACKAGE_INTRO</p><p>程序镜像 v0.1.1。Windows Docker Desktop 入口尚待 Windows 实机验收；Mac 保留原生安装。</p><ol><li>完整解压到固定目录，然后只看自己系统的教程。</li><li>Windows 按<a href="docs/WINDOWS_DOCKER.html">Windows 教程</a>准备 Docker Desktop，再双击 Install-Docker.cmd。</li><li>Linux 按<a href="docs/DOCKER.html">Ubuntu 教程</a>，在本目录运行 sudo bash Install-Docker.sh。</li></ol><p><a href="docs/DOCKER_CONFIG.html">目录、端口、变量与备份</a> · <a href="docs/LOGIN_ASSISTANT.html">首次连接</a> · <a href="docs/USAGE.html">首次出图</a> · <a href="docs/DOCKER_CONFIG_ACCEPTANCE.html">验收边界</a></p><p>不修改原生安装数据。Docker 只管理容器内应用，不控制主机关机或重启。先在新资料库使用小频道验收，不做全量采集。</p></html>'''.replace('PACKAGE_INTRO', '已含镜像和 small 模型，无需另下文件。' if edition=='complete' else '这是拆分配置包，需另放入同版离线镜像。首次安装推荐完整包，见 <a href="docs/DOWNLOADS.html">下载说明</a>。') if html_directory is not None else '请打开 docs/WINDOWS_DOCKER.md 或 docs/DOCKER.md；Windows Docker Desktop 尚待实机验收。').encode()
 entries['CHECKSUMS.sha256']=(image_hash+'  '+image.name+'\n').encode()
 entries['.env.example']=(ROOT/'docker/env.example').read_bytes()
 with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
  for name,content in entries.items():bundle.writestr(name,content)
  if edition=='complete':bundle.write(image,image.name,compress_type=zipfile.ZIP_STORED)
 with zipfile.ZipFile(out) as bundle:
  assert bundle.testzip() is None and set(bundle.namelist())==set(entries)|({image.name} if edition=='complete' else set())
 print(json.dumps({'zip':out.name,'files':len(entries),'sha256':digest(out),'image_sha256':image_hash}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--destination',type=Path,required=True);p.add_argument('--edition',choices=['linux','desktop','complete'],default='linux');p.add_argument('--html-directory',type=Path);a=p.parse_args();package(a.destination,a.edition,a.html_directory)
