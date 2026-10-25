"""Real loopback HTTP + native messaging against an isolated container, synthetic account only."""
import functools,io,json,os,socket,struct,subprocess,sys,tempfile,threading,time,urllib.request,zipfile
from pathlib import Path
from http.server import ThreadingHTTPServer
FIXTURE='synthetic_never_real_credential'

def serve(port):
 sys.path.insert(0,'/src')
 from app import Application,make_handler
 from discord_archive.connection_binding import bind_connection
 import app
 class FixtureDiscord:
  def __init__(self,credential):
   if credential!=FIXTURE:raise ValueError('unexpected synthetic credential')
  def get(self,path):
   assert path=='/users/@me';return {'id':'9001','username':'fixture'}
 with tempfile.TemporaryDirectory() as temp:
  root=Path(temp);(root/'data').mkdir();(root/'data/docker-identity.json').write_text('{"id":"isolated-fixture"}')
  helpers=root/'.local/login-assistants';helpers.mkdir(parents=True)
  for platform in ['windows','mac']:
   with zipfile.ZipFile(helpers/f'login-assistant-{platform}.zip','w') as z:z.writestr('fixture','non-executable')
  os.environ.update(DISCORD_ARCHIVE_DOCKER='1',DISCORD_ARCHIVE_CREDENTIAL_STORE='file',ARCHIVE_ROOT=str(root))
  application=Application(root,'127.0.0.1',port)
  app.bind_connection=functools.partial(bind_connection,client_factory=FixtureDiscord)
  ThreadingHTTPServer(('127.0.0.1',port),make_handler(application)).serve_forever()

def probe(binary,port):
 origin=f'http://127.0.0.1:{port}'
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 def get(path):
  with opener.open(origin+path,timeout=5) as r:return r.read()
 for _ in range(60):
  try:status=json.loads(get('/api/status'));break
  except OSError:time.sleep(.5)
 else:raise RuntimeError('fixture unavailable')
 assert not status['credentials']['discord'] and status['platform']['container']
 with zipfile.ZipFile(io.BytesIO(get('/download/login-assistant-windows.zip'))) as z:config=json.loads(z.read('server.json'))
 assert config=={'server_url':origin,'project_id':status['system']['project_id']}
 source=Path('login_assistant/native_client.go').read_text()
 import re
 extension=re.search(r'const extensionID\s*=\s*"([a-p]+)"',source).group(1)
 with tempfile.TemporaryDirectory() as home:
  folder=Path(home)/'Library/Application Support/DiscordArchiveConnector';folder.mkdir(parents=True)
  config_file=folder/'binding.json'
  def native(config):
   config_file.write_text(json.dumps(config));payload=json.dumps({'action':'bind','credential':FIXTURE,'user_id':'9001'}).encode()
   r=subprocess.run([str(Path(binary).resolve()),'chrome-extension://'+extension+'/'],input=struct.pack('<I',len(payload))+payload,capture_output=True,env={**os.environ,'HOME':home},timeout=15)
   assert r.returncode==0 and len(r.stdout)>=4
   length=struct.unpack('<I',r.stdout[:4])[0];assert length==len(r.stdout)-4
   return json.loads(r.stdout[4:])
  assert not native({**config,'project_id':'b'*64})['ok']
  assert not json.loads(get('/api/status'))['credentials']['discord']
  assert native(config)['ok']
 after=json.loads(get('/api/status'));assert after['credentials']['discord'] and after['state']['browser_account']['id']=='9001' and after['state']['automatic_paused']
 # Server must independently reject stale library pins even if a client skips its preflight.
 request=urllib.request.Request(origin+'/api/bind-discord',method='POST',data=json.dumps({'credential':FIXTURE,'expected_user_id':'9001','expected_project_id':'b'*64}).encode(),headers={'Content-Type':'application/json','Origin':origin,'X-Archive-Key':after['archive_key']})
 try:opener.open(request);raise AssertionError('stale project accepted')
 except urllib.error.HTTPError as error:assert error.code==400
 print(json.dumps({'passed':True,'same_host_http':True,'tailscale_required':False,'personalized_package':True,'native_protocol':True,'project_mismatch_rejected_before_commit':True,'server_independently_pins_project':True,'synthetic_account_persisted':True,'automatic_tasks_paused':True,'real_discord_account_used':False}))
if __name__=='__main__':
 if sys.argv[1]=='serve':serve(int(sys.argv[2]))
 else:probe(sys.argv[2],int(sys.argv[3]))
