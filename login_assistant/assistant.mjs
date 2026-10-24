// Standalone: bundled Node + playwright-core, existing Chrome/Edge, no project or keychain.
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const directory=path.dirname(fileURLToPath(import.meta.url));
const require=createRequire(import.meta.url);
export function serverOrigin(value){
  const u=new URL(value);
  if(u.protocol!=='https:'||!u.hostname.endsWith('.ts.net')||u.username||u.password||u.port||u.pathname!=='/'||u.search||u.hash)throw Error('请输入 Tailscale HTTPS 根地址');
  return u.origin;
}
export function findBrowser(preferred){
  const candidates=process.platform==='darwin'?[
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    path.join(os.homedir(),'Applications/Google Chrome.app/Contents/MacOS/Google Chrome')]:process.platform==='win32'?[
    ...['PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA'].flatMap(key=>process.env[key]?[
      path.join(process.env[key],'Microsoft','Edge','Application','msedge.exe'),path.join(process.env[key],'Google','Chrome','Application','chrome.exe')]:[])]:[];
  return candidates.find(p=>fs.existsSync(p)&&(!preferred||p.toLowerCase().includes(preferred==='edge'?'edge':'chrome')));
}
export async function requestServer(origin,route,body){
  origin=serverOrigin(origin);
  const r=await fetch(origin+route,{method:'POST',headers:{'Content-Type':'application/json','Origin':origin},body:JSON.stringify(body),redirect:'error',signal:AbortSignal.timeout(20000)});
  const result=await r.json();
  if(!r.ok)throw Error(typeof result.error==='string'?result.error:'服务器未接受请求');
  return result;
}
export function makeBridge(origin,localOrigin,expiresAt){
  const ecdh=crypto.createECDH('prime256v1');ecdh.generateKeys();
  return {ecdh,used:false,meta:{bridge:localOrigin,server_url:serverOrigin(origin),nonce:crypto.randomBytes(32).toString('base64url'),public_key:ecdh.getPublicKey().toString('base64'),expires_at:Math.min(expiresAt,Date.now()+300000)}};
}
export function decryptBridge(bridge,envelope){
  if(!bridge||bridge.used||bridge.meta.expires_at<=Date.now())throw Error('浏览器连接已过期，请重新发起');
  const peer=Buffer.from(envelope.public_key||'','base64'),iv=Buffer.from(envelope.iv||'','base64'),cipher=Buffer.from(envelope.ciphertext||'','base64');
  if(peer.length!==65||iv.length!==12||cipher.length<17||cipher.length>10000)throw Error('加密连接无效');
  const key=bridge.ecdh.computeSecret(peer);const decipher=crypto.createDecipheriv('aes-256-gcm',key,iv);
  decipher.setAAD(Buffer.from(bridge.meta.server_url));decipher.setAuthTag(cipher.subarray(-16));
  const clear=Buffer.concat([decipher.update(cipher.subarray(0,-16)),decipher.final()]);key.fill(0);
  let payload;try{payload=JSON.parse(clear.toString());}finally{clear.fill(0);}
  if(payload.nonce!==bridge.meta.nonce||payload.server_url!==bridge.meta.server_url||!validCandidate(payload.credential)||!/^\d+$/.test(payload.user_id))throw Error('浏览器身份或目标不匹配');
  bridge.used=true;return payload;
}
function validCandidate(value){return typeof value==='string'&&value.length>=16&&value.length<=4096&&!/\s/.test(value);}
async function main(){
  const {chromium}=require('playwright-core');
  const executablePath=findBrowser();
  if(!executablePath)throw Error('需要已安装的 Google Chrome 或 Microsoft Edge；请先安装浏览器，再打开助手。');
  const selfTest=process.argv.includes('--self-test');
  const browser=await chromium.launch({headless:selfTest,executablePath});
  let uiContext,loginContext,ui,pending=null,candidate=null,identity=null,busy=false,polling=false,finished=false,bridge=null;
  const key=crypto.randomBytes(32).toString('hex');let localOrigin='';
  let state={phase:'ready',message:'连接你的 Ubuntu 工作台'};
  let preset='';
  const preferences=path.join(process.platform==='win32'?(process.env.LOCALAPPDATA||os.homedir()):path.join(os.homedir(),'Library/Application Support'),'DiscordArchiveLogin','server.json');
  const configPaths=[path.join(directory,'server.json'),path.resolve(directory,'../../../../server.json'),preferences];
  for(const p of configPaths){try{preset=serverOrigin(JSON.parse(fs.readFileSync(p,'utf8')).server_url);break;}catch{}}
  const extensionConfig=JSON.parse(fs.readFileSync(path.join(directory,'bridge.json'),'utf8'));
  const extensionOrigin='chrome-extension://'+extensionConfig.extension_id;
  const extensionFolder=process.platform==='darwin'?path.resolve(directory,'../../../../Browser Extension'):path.resolve(directory,'../Browser Extension');
  const safeState=()=>({...state,server_url:preset,browsers:['chrome','edge'].filter(x=>findBrowser(x)),extension_folder:extensionFolder,account:identity?.global_name||identity?.username||null,authorization_url:pending?.authorization_url||null});
  async function login(){
    if(!pending?.pairing_code)throw Error('请先打开授权链接并允许连接');
    if(busy)throw Error('已有登录任务');busy=true;candidate=null;identity=null;
    state={phase:'logging_in',message:'请在专用 Discord 窗口本人登录或扫码'};
    try{
      loginContext=await browser.newContext();const page=await loginContext.newPage();
      let observed=null;
      loginContext.on('request',async r=>{try{const u=new URL(r.url());if(u.origin==='https://discord.com'&&/^\/api\/v\d+\/(users\/@me|channels\/\d+\/messages)(\/|$)/.test(u.pathname)){const h=await r.allHeaders();if(validCandidate(h.authorization))observed=h.authorization;}}catch{}});
      await page.goto('https://discord.com/channels/@me',{waitUntil:'domcontentloaded',timeout:30000}).catch(()=>{});
      const deadline=Date.now()+480000;
      while(Date.now()<deadline&&!page.isClosed()){
        let value=observed;
        if(!value)value=await page.evaluate(()=>{
          if(location.origin!=='https://discord.com'||!location.pathname.startsWith('/channels/'))return null;
          let raw=null;try{raw=localStorage.getItem('token');}catch{}
          if(!raw){const f=document.createElement('iframe');document.documentElement.append(f);try{raw=f.contentWindow.localStorage.getItem('token');}catch{}finally{f.remove();}}
          try{return JSON.parse(raw);}catch{return raw;}
        }).catch(()=>null);
        if(validCandidate(value)){
          const verified=await page.evaluate(async token=>{
            if(location.origin!=='https://discord.com')throw Error('登录窗口地址不匹配');
            const r=await fetch('/api/v10/users/@me',{headers:{Authorization:token}});
            return {ok:r.ok,account:await r.json()};
          },value);
          const account=verified.account;if(!verified.ok||!/^\d+$/.test(String(account.id)))throw Error('Discord 身份验证失败，请正常重新登录');
          candidate=value;identity=account;observed=null;
          state={phase:'confirm',message:'请核对账号和目标服务器，再确认绑定'};await loginContext.close();loginContext=null;return;
        }
        await new Promise(r=>setTimeout(r,500));
      }
      throw Error('登录已关闭或超时，请重新打开登录窗口');
    }finally{busy=false;if(loginContext){await loginContext.close().catch(()=>{});loginContext=null;}if(!candidate)identity=null;}
  }
  async function poll(){
    if(pending?.pairing_code && Date.now()/1000>=pending.binding_expiry){candidate=null;identity=null;pending=null;state={phase:'error',message:'本次授权已过期，请重新连接并授权'};}
    if(!pending||polling||pending.pairing_code)return;polling=true;
    try{
      const result=await requestServer(preset,'/api/helper/poll',{request_id:pending.request_id,poll_secret:pending.poll_secret});
      if(result.approved){pending.pairing_code=result.pairing_code;pending.binding_expiry=result.expires_at;state={phase:'authorized',message:'网页已授权，请使用已登录的日常浏览器绑定'};}
    }catch(e){state={phase:'error',message:e.message};pending=null;}finally{polling=false;}
  }
  const server=http.createServer(async(req,res)=>{
    const respond=(code,value,type='application/json')=>{res.writeHead(code,{'Content-Type':type,'Cache-Control':'no-store','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer'});res.end(type==='application/json'?JSON.stringify(value):value);};
    if(req.headers.host!==new URL(localOrigin).host)return respond(403,{error:'host'});
    if(req.method==='GET'&&req.url==='/')return respond(200,fs.readFileSync(path.join(directory,'assistant.html'),'utf8'),'text/html; charset=utf-8');
    if(req.url==='/browser-session'){
      if(req.headers.origin!==extensionOrigin)return respond(403,{error:'只接受本项目绑定扩展'});
      res.setHeader('Access-Control-Allow-Origin',extensionOrigin);res.setHeader('Access-Control-Allow-Headers','Content-Type');res.setHeader('Access-Control-Allow-Methods','POST, OPTIONS');
      if(req.method==='OPTIONS'){res.writeHead(204);res.end();return;}
      if(req.method!=='POST')return respond(405,{error:'method'});
      try{
        if(!pending?.pairing_code||busy)throw Error('请先在助手通过网页授权');
        let raw='';for await(const chunk of req){raw+=chunk;if(raw.length>16384)throw Error('请求过大');}
        const payload=decryptBridge(bridge,JSON.parse(raw));bridge=null;busy=true;
        try{
          const result=await requestServer(preset,'/api/helper/bind',{pairing_code:pending.pairing_code,credential:payload.credential,expected_user_id:payload.user_id});
          if(!result.ok)throw Error('Ubuntu 未确认绑定');
          payload.credential=null;candidate=null;identity=null;pending=null;state={phase:'done',message:'绑定成功。Ubuntu 已保存连接并暂停自动任务，可以打开工作台。'};
          return respond(200,{ok:true});
        }finally{busy=false;payload.credential=null;}
      }catch(e){bridge=null;candidate=null;identity=null;pending=null;state={phase:'error',message:'浏览器绑定未完成，请重新连接并授权'};return respond(400,{error:state.message});}
    }
    if(req.headers['x-assistant-key']!==key||(req.headers.origin&&req.headers.origin!==localOrigin))return respond(403,{error:'请求未授权'});
    if(req.method==='GET'&&req.url==='/status')return respond(200,safeState());
    if(req.method!=='POST')return respond(404,{error:'not found'});
    try{
      let raw='';for await(const chunk of req){raw+=chunk;if(raw.length>8192)throw Error('请求过大');}const data=JSON.parse(raw||'{}');
      if(req.url==='/start'){
        if(busy||candidate)throw Error('请先完成或关闭当前登录');
        preset=serverOrigin(data.server_url||preset);fs.mkdirSync(path.dirname(preferences),{recursive:true,mode:0o700});fs.writeFileSync(preferences,JSON.stringify({server_url:preset}),{mode:0o600});pending=await requestServer(preset,'/api/helper/request',{device:os.hostname().slice(0,70)+' / '+process.platform});
        const link=new URL(pending.authorization_url);if(link.origin!==preset)throw Error('服务器返回了不匹配的授权地址');
        state={phase:'waiting',message:'请打开授权链接，在网页允许这台助手连接'};
        respond(200,safeState());return;
      }
      if(req.url==='/existing-browser'){
        if(!pending?.pairing_code||busy)throw Error('请先打开授权链接并允许连接');
        bridge=makeBridge(preset,localOrigin,pending.binding_expiry*1000);
        const link='https://discord.com/channels/@me#archive-bind='+Buffer.from(JSON.stringify(bridge.meta)).toString('base64url');
        const normalBrowser=findBrowser(data.browser);if(!normalBrowser)throw Error('所选日常浏览器未安装，请选择已安装的 Chrome 或 Edge');
        spawn(normalBrowser,[link],{detached:true,stdio:'ignore'}).unref();
        state={phase:'browser_binding',message:'请在日常浏览器的 Discord 标签页点击一次性绑定扩展，识别并确认账号'};
        return respond(200,safeState());
      }
      if(req.url==='/login'){if(busy)throw Error('登录正在进行');respond(200,safeState());login().catch(e=>{candidate=null;identity=null;state={phase:'error',message:e.message};});return;}
      if(req.url==='/bind'){
        if(!candidate||!identity||!pending?.pairing_code||busy)throw Error('请先完成登录和账号确认');busy=true;
        try{const result=await requestServer(preset,'/api/helper/bind',{pairing_code:pending.pairing_code,credential:candidate,expected_user_id:String(identity.id)});if(!result.ok)throw Error('绑定未确认');state={phase:'done',message:'绑定成功。Ubuntu 已保存连接并暂停自动任务；可以关闭助手。'};candidate=null;identity=null;pending=null;}
        catch(e){identity=null;pending=null;state={phase:'error',message:'绑定未完成，请重新连接并授权：'+e.message};throw e;}
        finally{busy=false;candidate=null;}
        return respond(200,safeState());
      }
      return respond(404,{error:'not found'});
    }catch(e){state={phase:'error',message:e.message};return respond(400,{error:e.message});}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));localOrigin='http://127.0.0.1:'+server.address().port;
  uiContext=await browser.newContext({proxy:{server:'http://127.0.0.1:9',bypass:'*'}});ui=await uiContext.newPage();
  await ui.goto(localOrigin+'/#'+key);await ui.bringToFront();
  const timer=setInterval(()=>poll().catch(()=>{}),2000);timer.unref();
  const shutdown=async()=>{if(finished)return;finished=true;candidate=null;identity=null;pending=null;bridge=null;clearInterval(timer);server.close();await browser.close().catch(()=>{});};
  const closeWhenEmpty=()=>setTimeout(()=>{if(!browser.contexts().some(c=>c.pages().length))shutdown();},200);
  ui.on('close',closeWhenEmpty);uiContext.on('page',p=>p.on('close',closeWhenEmpty));browser.on('disconnected',()=>{server.close();});process.on('SIGTERM',()=>shutdown());
  if(selfTest){
    if(await ui.title()!=='Discord 登录助手')throw Error('助手界面异常');
    const title=await ui.locator('h1').textContent();if(!title.includes('登录助手'))throw Error('界面未加载');
    await ui.screenshot({path:path.join(os.tmpdir(),'discord-login-assistant-check.png')});
    if(preset){const p=await uiContext.newPage();const r=await p.goto(preset+'/api/health',{timeout:30000});if(r.status()!==200)throw Error('私网 HTTPS 检查失败');await p.close();}
    await shutdown();console.log('独立运行时、浏览器与助手界面检查通过；未读取账号或项目数据。');
  }
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(()=>{console.error('助手未能启动。请确认 Chrome/Edge 已安装；重新解压完整助手包后重试。');process.exitCode=1;});
