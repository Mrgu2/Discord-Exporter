import assert from 'node:assert/strict';
import {loadPlaywright,browserOptions} from '../scripts/browser_runtime.mjs';
const p=await loadPlaywright({localOnly:true}),b=await p.chromium.launch({headless:true,...browserOptions(p)});
const base=process.argv[2]||'http://127.0.0.1:18766';assert.equal(new URL(base).hostname,'127.0.0.1');
try{for(const mode of ['mac','mac-installed-helper','linux','docker'])for(const width of [390,1360]){
 const mac=mode.startsWith('mac'),system=mac?'darwin':'linux';
 const page=await b.newPage({viewport:{width,height:1000}});const mutations=[];
 // The second Mac case deliberately supplies the previous server's helper flag.
 const data={platform:{system,container:mode==='docker',login_desktop:false},connection_helper:{available:mode==='mac-installed-helper'||mode==='docker',local_binding:true},remote:{administrator:true,https_url:mode==='linux'?'https://fixture.ts.net':''},config:{channels:[],schedule:{enabled:false},model:{}},credentials:{discord:false},archive:{message_count:0},state:{},drafts:[],runs:[]};
 await page.route('**/api/**',route=>{if(route.request().method()!=='GET')mutations.push(new URL(route.request().url()).pathname);return route.fulfill({status:route.request().method()==='GET'?200:202,json:data});});
 await page.goto(base);await page.waitForFunction(label=>document.querySelector('#setup-action').textContent===label,mac?'连接 Discord':'首次连接 Discord');await page.locator('#setup-action').click();
 if(mac){
  await page.waitForFunction(()=>!document.querySelector('#connect-browser-button').disabled);
  assert.deepEqual(mutations,['/api/connect-browser']);
  assert.equal(await page.locator('#linux-binding').isHidden(),true);
  assert.ok(!(await page.locator('#connection-detail').textContent()).includes('下载客户端'));
 }else{
  await page.locator('#helper-downloads').waitFor({state:'visible'});
  assert.deepEqual(mutations,[]);assert.equal(await page.locator('#legacy-binding').isHidden(),true);assert.equal(await page.locator('#windows-helper-download').isHidden(),false);assert.equal(await page.locator('#connect-browser-fallback').isHidden(),true);
  assert.ok(!(await page.locator('#connection-detail').textContent()).includes('SSH'));
 }
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.close();
}console.log('Mac 原生：有无助手均直接登录；远端 Linux/同机 Docker 保留助手；390/1360 入口与布局通过，未使用真实账号。');}finally{await b.close();}
