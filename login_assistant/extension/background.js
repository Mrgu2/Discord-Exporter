chrome.runtime.onMessage.addListener((message,sender,reply)=>{
 (async()=>{
  if(message.action==='intent'){
   if(!sender.tab||new URL(sender.url).origin!=='https://discord.com')throw Error('origin');
   const m=message.meta,url=new URL(m.bridge),server=new URL(m.server_url);
   if(url.origin!==m.bridge||url.protocol!=='http:'||url.hostname!=='127.0.0.1'||!url.port||server.protocol!=='https:'||!server.hostname.endsWith('.ts.net')||server.origin!==m.server_url||typeof m.nonce!=='string'||m.nonce.length!==43||typeof m.public_key!=='string'||m.public_key.length>120||!Number.isFinite(m.expires_at)||m.expires_at<=Date.now()||m.expires_at>Date.now()+301000)throw Error('intent');
   await chrome.storage.session.set({['intent-'+sender.tab.id]:m});return {ok:true};
  }
  if(message.action==='get-intent'){
   const key='intent-'+message.tab_id,item=(await chrome.storage.session.get(key))[key];
   if(!item||item.expires_at<=Date.now())throw Error('请回到助手，重新点“使用日常浏览器绑定”，再打开这个扩展。');
   return item;
  }
  if(message.action==='clear-intent'){await chrome.storage.session.remove('intent-'+message.tab_id);return {ok:true};}
  throw Error('unsupported');
 })().then(reply,e=>reply({error:e.message}));return true;
});
