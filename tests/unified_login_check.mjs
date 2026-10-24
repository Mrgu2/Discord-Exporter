import assert from 'node:assert/strict';
import {loadPlaywright,browserOptions} from '../scripts/browser_runtime.mjs';
const p=await loadPlaywright({localOnly:true}),b=await p.chromium.launch({headless:true,...browserOptions(p)});
const base=process.argv[2]||'http://127.0.0.1:18766';assert.equal(new URL(base).hostname,'127.0.0.1');
try{for(const system of ['darwin','linux'])for(const width of [390,1360]){
 const page=await b.newPage({viewport:{width,height:1000}});let mutations=0;
 const data={platform:{system,login_desktop:false},connection_helper:{available:system==='darwin'},remote:{administrator:true,https_url:system==='linux'?'https://fixture.ts.net':''},config:{channels:[],schedule:{enabled:false},model:{}},credentials:{discord:false},archive:{message_count:0},state:{},drafts:[],runs:[]};
 await page.route('**/api/**',route=>{if(route.request().method()!=='GET')mutations++;return route.fulfill({json:data});});
 await page.goto(base);await page.waitForFunction(()=>document.querySelector('#setup-action').textContent==='首次连接 Discord');await page.locator('#setup-action').click();await page.locator('#helper-downloads').waitFor({state:'visible'});
 assert.equal(mutations,0);assert.equal(await page.locator('#legacy-binding').isHidden(),true);assert.equal(await page.locator('#windows-helper-download').isHidden(),system==='darwin');assert.equal(await page.locator('#connect-browser-fallback').isHidden(),true);assert.ok(!(await page.locator('#connection-detail').textContent()).includes('SSH'));assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.close();
}console.log('Mac/Linux首次连接入口：390/1360、无需自动化登录请求、平台下载、无旧SSH指引与溢出均通过；虚构状态。');}finally{await b.close();}
