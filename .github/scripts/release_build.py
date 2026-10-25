"""Stage a new private draft; never publishes, changes old releases or uses user data."""
import hashlib,http.client,importlib.util,json,os,re,shutil,subprocess,tarfile,time,urllib.request,urllib.error,zipfile
from urllib.parse import quote,urlsplit
from pathlib import Path
ROOT=Path.cwd();TAG=os.environ['RELEASE_TAG'];assert re.fullmatch(r'v\d+\.\d+\.\d+(?:\.\d+)?',TAG)
REPO=os.environ['GITHUB_REPOSITORY'];SHA=os.environ['GITHUB_SHA'];OUT=ROOT/'dist/releases'/TAG;OUT.mkdir(parents=True)
WORK=ROOT/'dist/release-job';WORK.mkdir()

def run(*args,**kw):return subprocess.run(args,check=True,**kw)
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def load(path,name):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def api(path):return json.loads(subprocess.check_output(['gh','api',path],text=True))
draft=next(r for r in api(f'repos/{REPO}/releases?per_page=100') if r['tag_name']==TAG)
assert draft['draft'] and draft['target_commitish']==SHA
rid=draft['id'];auth={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'User-Agent':'DiscordArchive-release'}
class SafeRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,url):
  result=super().redirect_request(req,fp,code,msg,headers,url)
  if urlsplit(url).hostname!='api.github.com':result.remove_header('Authorization')
  return result
def download_draft(name,target):
 asset=next(a for a in api(f'repos/{REPO}/releases/{rid}/assets?per_page=100') if a['name']==name)
 request=urllib.request.Request(f'https://api.github.com/repos/{REPO}/releases/assets/{asset["id"]}',headers={**auth,'Accept':'application/octet-stream'})
 with urllib.request.build_opener(SafeRedirect()).open(request,timeout=120) as response,Path(target).open('xb') as f:shutil.copyfileobj(response,f)
 assert sha(target)==asset['digest'].removeprefix('sha256:')
def upload_draft(path):
 assert api(f'repos/{REPO}/releases/{rid}')['draft']
 for asset in api(f'repos/{REPO}/releases/{rid}/assets?per_page=100'):
  if asset['name']==path.name:subprocess.run(['gh','api','--method','DELETE',f'repos/{REPO}/releases/assets/{asset["id"]}'],check=True)
 connection=http.client.HTTPSConnection('uploads.github.com',timeout=180,blocksize=1024*1024)
 with path.open('rb') as f:
  connection.request('POST',f'/repos/{REPO}/releases/{rid}/assets?name='+quote(path.name),body=f,headers={**auth,'Content-Type':'application/octet-stream','Content-Length':str(path.stat().st_size)})
  response=connection.getresponse();body=response.read();assert response.status==201,(path.name,response.status)
  asset=json.loads(body);assert asset['digest']=='sha256:'+sha(path)
 connection.close()
download_draft('build-input.tar.gz',WORK/'build-input.tar.gz')
assert sha(WORK/'build-input.tar.gz')==os.environ['INPUT_SHA256']
with tarfile.open(WORK/'build-input.tar.gz') as t:t.extractall(WORK/'input',filter='data')
INPUT=WORK/'input';meta=json.loads((INPUT/'BUILD.json').read_text());assert meta['commit']==SHA
for n,h in meta['files'].items():assert sha(INPUT/n)==h,n
context=INPUT/'context'
package=load(ROOT/'scripts/package_app.py','package')
for source in package.source_files(ROOT):
 relative=source.relative_to(ROOT)
 if relative.parts[0]!='helpers':assert source.read_bytes()==(context/relative).read_bytes(),str(relative)
verifier=load(ROOT/'scripts/install_login_assistants.py','helpers')
for platform,valid in [('mac',{'darwin-arm64'}),('windows',{'win32-x64'})]:verifier.verify(context/'helpers'/f'login-assistant-{platform}.zip',valid)
# Public, previously verified model/runtime layers only; credentials never enter this context.
run('gh','release','download','v2026.10.25.3','--repo',REPO,'--pattern','discordarchive-linux-amd64.tar.gz','--dir',str(WORK))
assert sha(WORK/'discordarchive-linux-amd64.tar.gz')=='f4e13160a0985481113453387786061711f6867db2e8d8af27986d56cfe7c271'
run('docker','load','-i',str(WORK/'discordarchive-linux-amd64.tar.gz'))
base='discordarchive-linux:v2026.10.25.3';image='discordarchive-linux:'+TAG
base_layers=json.loads(subprocess.check_output(['docker','image','inspect',base],text=True))[0]['RootFS']['Layers']
dockerfile=WORK/'Dockerfile';dockerfile.write_text('FROM '+base+'\n'+''.join('COPY --chown=app:app '+n+' /app/'+n+'\n' for n in ['app.py','discord_archive/','web/','scripts/','tests/','docker/','helpers/'])+'COPY --chown=app:app helpers/ /app/.local/login-assistants/\n')
run('docker','build','--label','org.opencontainers.image.revision='+SHA,'-f',str(dockerfile),'-t',image,str(context))
info=json.loads(subprocess.check_output(['docker','image','inspect',image],text=True))[0];assert info['Config']['User']=='app' and info['RootFS']['Layers'][:len(base_layers)]==base_layers
# Inspect image seed only, with no app initialization or host mounts.
seed="from pathlib import Path;import hashlib,json;assert not list(Path('/app/data').rglob('*'));assert not list(Path('/app/output').rglob('*'));print(json.dumps({'model_sha256':hashlib.sha256(Path('/app/.runtime/models/faster-whisper-small/model.bin').read_bytes()).hexdigest()}))"
model=json.loads(subprocess.check_output(['docker','run','--rm','--read-only','--cap-drop','ALL','--entrypoint','python',image,'-c',seed],text=True))
for platform in ('mac','windows'):
 expected=sha(context/'helpers'/f'login-assistant-{platform}.zip')
 actual=subprocess.check_output(['docker','run','--rm','--read-only','--entrypoint','python',image,'-c',"import hashlib;print(hashlib.sha256(open('/app/.local/login-assistants/login-assistant-"+platform+".zip','rb').read()).hexdigest())"],text=True).strip();assert actual==expected
# Fresh tmpfs libraries; no existing volumes, Tailscale routes or credentials.
name='release-fixture-'+TAG.replace('.','-');port=29887;origin=f'http://127.0.0.1:{port}';opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
run('docker','run','--detach','--name',name,'--network','host','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--shm-size','1g','--tmpfs','/tmp:rw,mode=1777','--tmpfs','/app/data:uid=1000,gid=1000,mode=700','--tmpfs','/app/output:uid=1000,gid=1000,mode=700','-e','ARCHIVE_PORT='+str(port),image)
try:
 for _ in range(90):
  try:
   with opener.open(origin+'/api/status',timeout=3) as r:status=json.load(r)
   break
  except OSError:time.sleep(1)
 else:raise RuntimeError('image not ready')
 assert status['platform']['container'] and status['connection_helper']['local_binding'] and not status['remote']['https_url'] and not status['credentials']['discord'] and status['archive']['message_count']==0
 for platform in ('windows','mac'):
  with opener.open(origin+'/download/login-assistant-'+platform+'.zip') as r:payload=r.read()
  import io
  with zipfile.ZipFile(io.BytesIO(payload)) as z:
   config=json.loads(z.read('server.json'));assert config=={'server_url':origin,'project_id':status['system']['project_id']}
   helper_meta=json.loads(z.read('ASSISTANT-MANIFEST.json'))
   for n,h in helper_meta['files'].items():assert hashlib.sha256(z.read(n)).hexdigest()==h
  if platform=='windows':
   client=WORK/'client';client.mkdir();(client/'server.json').write_text(json.dumps(config));run('go','build','-o',str(client/'connector'),str(ROOT/'login_assistant/native_client.go'));run(str(client/'connector'),'--check')
 bad=urllib.request.Request(origin+'/api/bind-discord',method='POST',data=json.dumps({'credential':'synthetic_never_real','expected_user_id':'9001','expected_project_id':'b'*64}).encode(),headers={'Content-Type':'application/json','Origin':origin,'X-Archive-Key':status['archive_key']})
 try:opener.open(bad);raise AssertionError('wrong project accepted')
 except urllib.error.HTTPError as e:assert e.code==400
 run('docker','exec',name,'python','scripts/doctor.py')
 run('docker','exec','-e','DISCORD_ARCHIVE_DOCKER=','-e','DISCORD_ARCHIVE_CREDENTIAL_STORE=',name,'python','-m','unittest','discover','-s','tests','-q')
 install=subprocess.run(['sudo','apt-get','install','-y','-qq','--no-install-recommends','espeak-ng'])
 if install.returncode:
  run('sudo','apt-get','update','-qq');run('sudo','apt-get','install','-y','-qq','--no-install-recommends','espeak-ng')
 audio=WORK/'public-fixture.wav';run('espeak-ng','-s','145','-w',str(audio),'This is a small offline speech transcription test. The account connection is ready.')
 run('docker','exec','-i',name,'python','-c',"from pathlib import Path;import sys;Path('/tmp/public-fixture.wav').write_bytes(sys.stdin.buffer.read())",input=audio.read_bytes())
 speech="from faster_whisper import WhisperModel;import json;m=WhisperModel('/app/.runtime/models/faster-whisper-small',device='cpu',compute_type='int8',cpu_threads=2,local_files_only=True);s,_=m.transcribe('/tmp/public-fixture.wav',language='en',beam_size=1);text=' '.join(x.text for x in s).strip();assert text;print(json.dumps({'synthetic_speech_transcribed':True,'text':text}))"
 speech_result=json.loads(subprocess.check_output(['docker','exec',name,'/opt/whisper/bin/python','-c',speech],text=True))
 # Actual manuscript rendering on public fixture text; no Discord content.
 import html
 fixture_html='<!doctype html>'+'<meta charset=utf-8><main id=manuscript><h1>Public fixture</h1><div class=panel-grid><section class=content-panel data-kind=qa><h2 class=category-title>Fixture</h2><article class=topic><h2>Speech test</h2><section class="block answer" data-segment data-evidence-id=fixture/1><p class=message-text>'+html.escape(speech_result['text'])+'</p></section></article></section></div></main>'
 render_input="from pathlib import Path;Path('/tmp/fixture.html').write_text("+repr(fixture_html)+")"
 run('docker','exec',name,'python','-c',render_input)
 render=json.loads(subprocess.check_output(['docker','exec',name,'node','scripts/render.mjs','/tmp/fixture.html','/app/output/fixture','1'],text=True));assert render['images'] and render['source_coverage']['missing']==0
 # Check runtime source bytes against the allowlist context before exporting.
 check="from pathlib import Path;import hashlib,json;root=Path('/app');files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['discord_archive','web','scripts','docker'] for p in (root/folder).rglob('*') if p.is_file() and p.suffix in ['.py','.js','.mjs','.css','.html','.yaml','.sh','.ps1','.cmd']};files['app.py']=hashlib.sha256((root/'app.py').read_bytes()).hexdigest();print(json.dumps(files))"
 actual=json.loads(subprocess.check_output(['docker','exec',name,'python','-c',check],text=True))
 for n,h in actual.items():
  if (context/n).is_file():assert sha(context/n)==h,n
 report={'passed':True,'commit':SHA,'image':image,'fresh_library':True,'same_host_without_tailscale':True,'project_pinning':True,'helpers_verified':True,'base_model_layers_preserved':True,**model,'speech':speech_result,'png_images':len(render['images']),'png_sources_missing':0,'windows_docker_desktop_full_tested':False}
finally:
 run('docker','stop',name)
# Export and package the verified image, not an older asset with new documentation.
with (OUT/'discordarchive-linux-amd64.tar.gz').open('wb') as f:
 save=subprocess.Popen(['docker','save',image],stdout=subprocess.PIPE);gz=subprocess.Popen(['gzip','-1'],stdin=save.stdout,stdout=f);save.stdout.close();assert gz.wait()==0 and save.wait()==0
pack=load(ROOT/'scripts/package_docker_release.py','docker_release')
for edition in ['linux','desktop','complete']:pack.package(OUT,edition,INPUT/'html')
for p in (INPUT/'metadata').iterdir():shutil.copy2(p,OUT/p.name)
for n in ['DiscordArchive-source.zip','login-assistant-mac.zip','login-assistant-windows.zip']:download_draft(n,OUT/n)
for name in ['DiscordArchive-source.zip','DiscordArchive-Docker-linux-amd64.zip','DiscordArchive-Docker-desktop-preview.zip','DiscordArchive-Docker-complete-preview.zip']:
 with zipfile.ZipFile(OUT/name) as z:
  assert z.testzip() is None
  prefix='DiscordArchive/' if name=='DiscordArchive-source.zip' else ''
  for p in [ROOT/'README.md',*sorted((ROOT/'docs').glob('*.md'))]:assert z.read(prefix+str(p.relative_to(ROOT)))==p.read_bytes()
(OUT/'IMAGE-ACCEPTANCE.json').write_text(json.dumps(report,indent=2))
(OUT/'CHECKSUMS.sha256').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='CHECKSUMS.sha256'))
for p in OUT.iterdir():
 if p.name not in ['DiscordArchive-source.zip','login-assistant-mac.zip','login-assistant-windows.zip']:upload_draft(p)
print(json.dumps(report))
