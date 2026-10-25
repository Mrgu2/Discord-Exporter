#!/usr/bin/env python3
"""Make the flat Linux installer ZIP; the offline image remains a separate asset."""
import argparse,hashlib,importlib.util,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def package(destination):
 destination=Path(destination).resolve()
 if not destination.is_relative_to(ROOT/'dist'):raise ValueError('输出必须位于 dist')
 image=destination/'discordarchive-linux-amd64.tar.gz'
 if not image.is_file():raise ValueError('请先准备已验收的离线镜像')
 out=destination/'DiscordArchive-Docker-linux-amd64.zip'
 if out.exists():raise FileExistsError('保留旧包，请使用新目录')
 spec=importlib.util.spec_from_file_location('source_package',ROOT/'scripts/package_app.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 image_hash=digest(image);entries={}
 for name in ['compose.yaml','Install-Docker.sh','Start-Docker.sh','Stop-Docker.sh','Configure-Tailscale.sh']:
  entries[name]=(ROOT/'docker'/name).read_bytes()
 for source in m.source_files(ROOT):
  relative=str(source.relative_to(ROOT))
  if relative=='README.md' or relative.startswith('docs/'):entries[relative]=source.read_bytes()
 entries['README-Docker.md']='# Discord Archive Linux Docker\n\n从同一 Release 下载离线镜像至本目录，按 [Ubuntu Docker 教程](docs/DOCKER.md)安装。\n\nMac 保留原生安装。容器只管理本应用，不控制 Ubuntu 关机或重启。已有资料保存在独立命名卷中，不要运行 down -v。\n'.encode()
 entries['CHECKSUMS.sha256']=(image_hash+'  '+image.name+'\n').encode()
 entries['.env.example']=b'ARCHIVE_IMAGE=discordarchive-linux:v2026.10.25.2\nARCHIVE_PORT=8765\n'
 with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
  for name,content in entries.items():bundle.writestr(name,content)
 with zipfile.ZipFile(out) as bundle:
  assert bundle.testzip() is None and set(bundle.namelist())==set(entries)
 print(json.dumps({'zip':out.name,'files':len(entries),'sha256':digest(out),'image_sha256':image_hash}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--destination',type=Path,required=True);package(p.parse_args().destination)
