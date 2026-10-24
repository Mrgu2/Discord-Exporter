import assert from 'node:assert/strict';
import {serverOrigin,requestServer} from '../login_assistant/assistant.mjs';
assert.equal(serverOrigin('https://archive.example.ts.net'),'https://archive.example.ts.net');
for(const value of ['http://archive.example.ts.net','https://example.com','https://secret@archive.example.ts.net','https://archive.example.ts.net/path','https://archive.example.ts.net/?token=x','https://archive.example.ts.net/#x'])assert.throws(()=>serverOrigin(value));
const original=globalThis.fetch;
try{
 let call;
 globalThis.fetch=async(url,opts)=>{call={url,opts};return {ok:true,json:async()=>({approved:false})};};
 await requestServer('https://archive.example.ts.net','/api/helper/request',{device:'Synthetic Windows'});
 assert.equal(call.opts.redirect,'error');assert.equal(call.opts.headers.Origin,'https://archive.example.ts.net');assert.ok(call.opts.signal);
 globalThis.fetch=async()=>({ok:false,json:async()=>({error:'配对码无效或已过期'})});
 await assert.rejects(()=>requestServer('https://archive.example.ts.net','/api/helper/bind',{}),/过期/);
}finally{globalThis.fetch=original;}
console.log('助手 HTTPS 地址约束、禁止重定向、超时、授权错误传播通过；测试未使用凭证。');
const {makeBridge,decryptBridge}=await import('../login_assistant/assistant.mjs');
async function envelope(bridge,payload){
 const pair=await crypto.subtle.generateKey({name:'ECDH',namedCurve:'P-256'},true,['deriveBits']);
 const pub=await crypto.subtle.importKey('raw',Buffer.from(bridge.meta.public_key,'base64'),{name:'ECDH',namedCurve:'P-256'},false,[]);
 const bits=await crypto.subtle.deriveBits({name:'ECDH',public:pub},pair.privateKey,256),key=await crypto.subtle.importKey('raw',bits,'AES-GCM',false,['encrypt']);
 const iv=crypto.getRandomValues(new Uint8Array(12));
 const cipher=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:new TextEncoder().encode(bridge.meta.server_url)},key,new TextEncoder().encode(JSON.stringify(payload)));
 return {public_key:Buffer.from(await crypto.subtle.exportKey('raw',pair.publicKey)).toString('base64'),iv:Buffer.from(iv).toString('base64'),ciphertext:Buffer.from(cipher).toString('base64')};
}
const bridge=makeBridge('https://archive.example.ts.net','http://127.0.0.1:12345',Date.now()+60000);
const payload={nonce:bridge.meta.nonce,server_url:bridge.meta.server_url,credential:'synthetic_never_real_credential',user_id:'9001'};
const encrypted=await envelope(bridge,payload);assert.ok(!JSON.stringify(encrypted).includes(payload.credential));
assert.deepEqual(decryptBridge(bridge,encrypted),payload);assert.throws(()=>decryptBridge(bridge,encrypted));
const other=makeBridge('https://archive.example.ts.net','http://127.0.0.1:12345',Date.now()+60000);
const bad=await envelope(other,{...payload,nonce:other.meta.nonce});const bytes=Buffer.from(bad.ciphertext,'base64');bytes[0]^=1;bad.ciphertext=bytes.toString('base64');assert.throws(()=>decryptBridge(other,bad));
const wrongNonce=await envelope(other,{...payload,nonce:'wrong'});assert.throws(()=>decryptBridge(other,wrongNonce));
other.meta.expires_at=Date.now()-1;assert.throws(()=>decryptBridge(other,bad));
console.log('浏览器 WebCrypto 与 Node ECDH/AES-GCM 互通、加密负载、篡改/重复/过期/nonce 拒绝通过。');
