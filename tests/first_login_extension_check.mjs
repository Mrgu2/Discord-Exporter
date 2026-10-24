import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {sessionCandidate} from '../login_assistant/native_extension/session.mjs';
const token='synthetic_fixture_credential_never_real';
const event={tabId:7,initiator:'https://discord.com',method:'GET',url:'https://discord.com/api/v10/channels/9001/messages',requestHeaders:[{name:'Authorization',value:token}]};
assert.equal(sessionCandidate(event,7,200,100),token);
for(const altered of [{tabId:8},{initiator:'https://other.example'},{method:'POST'},{url:'https://example.com/api/v10/users/@me'},{url:'https://discord.com/api/v10/guilds/9001'},{requestHeaders:[{name:'Authorization',value:'bad'}]}])assert.equal(sessionCandidate({...event,...altered},7,200,100),null);
assert.equal(sessionCandidate(event,7,100,100),null);
async function fixture(){
 const elements=new Map();let observer=null,timeout=null;const messages=[];
 const chrome={runtime:{sendNativeMessage:async(_host,m)=>{messages.push(m);return m.action==='info'?{ok:true,server_url:'https://fixture.ts.net'}:{ok:true};}},tabs:{get:async()=>({id:7,url:'https://discord.com/channels/@me'}),reload:async()=>{}},scripting:{executeScript:async()=>[{result:{user_id:'9001',name:'Fixture'}}]},webRequest:{onBeforeSendHeaders:{addListener:f=>observer=f,removeListener:f=>{if(observer===f)observer=null;}}}};
 const context={chrome,sessionCandidate,URL,URLSearchParams,location:{search:'?tab=7'},window:{addEventListener(){}},document:{getElementById:id=>{if(!elements.has(id))elements.set(id,{hidden:id==='confirm',disabled:false,textContent:''});return elements.get(id);}},setTimeout:f=>{timeout=f;return 1;},clearTimeout:()=>{timeout=null;},Date};
 vm.createContext(context);const source=(await fs.readFile(new URL('../login_assistant/native_extension/popup.mjs',import.meta.url),'utf8')).replace("import {sessionCandidate} from './session.mjs';",'');await vm.runInContext('(async()=>{'+source+'})()',context);
 return {elements,messages,get observer(){return observer;},get timeout(){return timeout;}};
}
let f=await fixture();assert.equal(f.observer,null);await f.elements.get('bind').onclick();assert.ok(f.observer);f.observer({...event,tabId:8});assert.ok(f.observer);f.observer(event);await new Promise(r=>setImmediate(r));assert.equal(f.observer,null);assert.equal(f.messages.filter(x=>x.action==='bind').length,0);assert.equal(f.elements.get('confirm').hidden,false);await f.elements.get('confirm').onclick();assert.equal(f.messages.filter(x=>x.action==='bind').length,1);assert.ok(f.elements.get('status').textContent.includes('连接成功'));
f=await fixture();await f.elements.get('bind').onclick();f.observer(event);await new Promise(r=>setImmediate(r));f.elements.get('cancel').onclick();await f.elements.get('confirm').onclick();assert.equal(f.messages.filter(x=>x.action==='bind').length,0);
f=await fixture();await f.elements.get('bind').onclick();f.timeout();assert.equal(f.observer,null);assert.equal(f.messages.filter(x=>x.action==='bind').length,0);
const manifest=JSON.parse(await fs.readFile(new URL('../login_assistant/native_extension/manifest.json',import.meta.url)));assert.deepEqual(manifest.host_permissions,['https://discord.com/*']);assert.equal(manifest.permissions.includes('storage'),false);assert.equal(manifest.permissions.includes('webRequestBlocking'),false);
console.log('首次连接扩展：点击前不观察、仅所选 Discord 标签页、限时与取消、本人确认前不上传、确认后提交一次、最小权限检查通过；虚构连接测试。');
