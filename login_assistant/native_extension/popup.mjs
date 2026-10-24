import {sessionCandidate} from './session.mjs';
const $=id=>document.getElementById(id),host='local.discordarchive.connector';
let tab,session=null,timer=null,listener=null,expires=0,account=null,generation=0;
function stop(){if(listener)chrome.webRequest.onBeforeSendHeaders.removeListener(listener);listener=null;clearTimeout(timer);expires=0;}
function discard(){generation++;stop();session=null;account=null;$('confirm').hidden=true;}
function fail(message){discard();$('status').textContent=message;$('bind').disabled=false;$('bind').hidden=false;}
window.addEventListener('pagehide',discard);
$('cancel').onclick=()=>{discard();$('status').textContent='已取消；未更改 工作台 连接。';$('bind').disabled=false;$('bind').hidden=false;};
try{
 const info=await chrome.runtime.sendNativeMessage(host,{action:'info'});if(!info.ok)throw Error(info.error);
 $('server').textContent=info.server_url;
 const id=Number(new URLSearchParams(location.search).get('tab'));
 if(!Number.isInteger(id)||id<0)throw Error('请回到日常已登录的 Discord 标签页，点击扩展图标。');
 tab=await chrome.tabs.get(id);
 if(!tab.url||new URL(tab.url).origin!=='https://discord.com')throw Error('请回到日常已登录的 Discord 标签页，点击扩展图标。');
 const checked=await chrome.runtime.sendNativeMessage(host,{action:'check'});if(!checked.ok)throw Error(checked.error||'未通过服务器本人身份验证');
 $('status').textContent='点击后将刷新你选中的 Discord 标签页，识别账号后由你确认。';$('bind').disabled=false;
}catch(e){$('status').textContent=/native messaging|Native host|specified native/i.test(e.message)?'请先打开包内“首次连接 Discord”，安装本机连接组件；再回到 Discord 点击扩展。':e.message;}
$('bind').onclick=async()=>{
 discard();const attempt=generation;$('bind').disabled=true;$('status').textContent='正在识别账号…';
 try{
  const current=await chrome.tabs.get(tab.id);if(new URL(current.url).origin!=='https://discord.com')throw Error('所选标签页已离开 Discord，请重新从 Discord 打开扩展。');
  expires=Date.now()+60000;
  listener=details=>{
   const candidate=sessionCandidate(details,tab.id,expires);if(!candidate)return;
   stop();session=candidate;
   (async()=>{
    // Validate in the user's selected Discord tab. No storage keys, passwords,
    // cookies, chat bodies or other tabs are read; only a verified display identity returns.
    const result=await chrome.scripting.executeScript({target:{tabId:tab.id},world:'MAIN',func:async credential=>{
     if(location.origin!=='https://discord.com')return null;
     try{const response=await fetch('/api/v10/users/@me',{headers:{Authorization:credential},redirect:'error'});if(!response.ok)return null;const u=await response.json();return /^\d+$/.test(String(u.id))?{user_id:String(u.id),name:u.global_name||u.username}:null;}catch{return null;}
    },args:[candidate]});
    if(generation!==attempt||session!==candidate)return;
    account=result[0]?.result;if(!account)throw Error('当前 Discord 身份验证未成功；未向 工作台 提交连接。');
    $('status').textContent='已识别：'+account.name+'。确认将此账号连接到上方 工作台？';$('bind').hidden=true;$('confirm').hidden=false;
    timer=setTimeout(()=>fail('确认已超时；未上传账号连接，请重新识别。'),60000);
   })().catch(e=>{if(generation===attempt)fail(e.message);});
  };
  chrome.webRequest.onBeforeSendHeaders.addListener(listener,{urls:['https://discord.com/api/*'],tabId:tab.id,types:['xmlhttprequest']},['requestHeaders','extraHeaders']);
  timer=setTimeout(()=>fail('没有识别到登录请求。请在所选 Discord 页面本人正常登录后重试；未上传任何连接。'),60000);
  await chrome.tabs.reload(tab.id);
 }catch(e){fail(e.message);}
};
$('confirm').onclick=async()=>{
 if(!session||!account)return;$('confirm').disabled=true;$('cancel').disabled=true;clearTimeout(timer);
 let candidate=session;const identity=account;session=null;account=null;
 try{
  const result=await chrome.runtime.sendNativeMessage(host,{action:'bind',credential:candidate,user_id:identity.user_id});candidate=null;
  if(!result.ok)throw Error(result.error||'工作台 未确认连接');
  $('confirm').hidden=true;$('status').textContent='连接成功：'+identity.name+'。工作台 已验证并保存连接，可独立采集；自动任务保持暂停。';
 }catch(e){candidate=null;fail(e.message);}finally{$('confirm').disabled=false;$('cancel').disabled=false;}
};
