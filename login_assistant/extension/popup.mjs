const $=id=>document.getElementById(id);let meta,tab,account;
const decode=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));const encode=a=>btoa(String.fromCharCode(...a));
try{
 [tab]=await chrome.tabs.query({active:true,currentWindow:true});
 if(new URL(tab.url).origin!=='https://discord.com')throw Error('请先切到已登录的 Discord 标签页。');
 meta=await chrome.runtime.sendMessage({action:'get-intent',tab_id:tab.id});if(meta.error)throw Error(meta.error);
 $('target').textContent='目标服务器：'+meta.server_url;$('status').textContent='请核对目标服务器，再识别当前账号。';$('identify').disabled=false;
}catch(e){$('status').textContent=e.message;}
$('identify').onclick=async()=>{
 $('identify').disabled=true;
 try{
  const results=await chrome.scripting.executeScript({target:{tabId:tab.id},func:async()=>{
   if(location.origin!=='https://discord.com')return {error:'当前标签页不是 Discord'};
   let raw=null;try{raw=window.localStorage.getItem('token');}catch{}
   if(!raw){const f=document.createElement('iframe');f.hidden=true;document.documentElement.append(f);try{raw=f.contentWindow.localStorage.getItem('token');}catch{}finally{f.remove();}}
   let credential;try{credential=JSON.parse(raw);}catch{credential=raw;}
   if(typeof credential!=='string'||credential.length<16||credential.length>4096||/\s/.test(credential))return {error:'未找到可用登录连接。请确认在日常浏览器正常登录，再回助手重试。'};
   try{
    const r=await fetch('/api/v10/users/@me',{headers:{Authorization:credential}});const user=await r.json();
    if(!r.ok||!/^\d+$/.test(String(user.id)))return {error:'当前登录连接无法通过 Discord 验证'};
    return {credential,user_id:String(user.id),display_name:user.global_name||user.username};
   }catch{return {error:'Discord 身份验证暂时失败，请检查原浏览器网络'};}
  }});
  account=results[0]?.result;if(!account||account.error)throw Error(account?.error||'未识别到账号');
  $('account').textContent='账号：'+account.display_name;$('status').textContent='确认后只将此连接交给自己的 Ubuntu。';$('identify').hidden=true;$('bind').hidden=false;
 }catch(e){$('status').textContent=e.message;$('identify').disabled=false;}
};
$('bind').onclick=async()=>{
 $('bind').disabled=true;
 try{
  if(!account||meta.expires_at<=Date.now())throw Error('授权已过期，请回到助手重新连接');
  const pair=await crypto.subtle.generateKey({name:'ECDH',namedCurve:'P-256'},true,['deriveBits']);
  const pub=await crypto.subtle.importKey('raw',decode(meta.public_key),{name:'ECDH',namedCurve:'P-256'},false,[]);
  const bits=await crypto.subtle.deriveBits({name:'ECDH',public:pub},pair.privateKey,256);const key=await crypto.subtle.importKey('raw',bits,'AES-GCM',false,['encrypt']);
  const iv=crypto.getRandomValues(new Uint8Array(12));
  const payload=new TextEncoder().encode(JSON.stringify({...account,nonce:meta.nonce,server_url:meta.server_url}));
  const ciphertext=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:new TextEncoder().encode(meta.server_url)},key,payload);
  account.credential=null;account=null;payload.fill(0);
  const peer=await crypto.subtle.exportKey('raw',pair.publicKey);
  const response=await fetch(meta.bridge+'/browser-session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({public_key:encode(new Uint8Array(peer)),iv:encode(iv),ciphertext:encode(new Uint8Array(ciphertext))})});
  const result=await response.json();if(!response.ok||!result.ok)throw Error(result.error||'助手未确认绑定');
  await chrome.runtime.sendMessage({action:'clear-intent',tab_id:tab.id});$('status').textContent='绑定成功。可以回到助手打开 Ubuntu 工作台；扩展可以移除。';$('bind').hidden=true;
 }catch(e){account=null;$('status').textContent=e.message+'；请回助手重新连接。';}
};
