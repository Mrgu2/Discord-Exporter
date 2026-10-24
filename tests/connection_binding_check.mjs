// Fixture status and intercepted mutations; never sends an account credential.
import assert from 'node:assert/strict';
import {loadPlaywright,browserOptions} from '../scripts/browser_runtime.mjs';
const p=await loadPlaywright({localOnly:true});
const browser=await p.chromium.launch({headless:true,...browserOptions(p)});
const base=process.argv[2]||'http://127.0.0.1:8765';
assert.equal(new URL(base).hostname,'127.0.0.1');
try {
 for(const system of ['darwin','linux'])for(const width of [390,1360]) {
  const page=await browser.newPage({viewport:{width,height:1000}});
  const data={platform:{system,login_desktop:false},system:{binding_root:"/home/example/Archive Folder"},config:{channels:[],schedule:{enabled:false},model:{}},credentials:{discord:false},archive:{message_count:0},state:{},drafts:[],runs:[],remote:{}};
  let mutations=0,popups=0;
  page.on('popup',()=>popups++);
  await page.route('**/api/**',async route=>{
   if(route.request().method()!=='GET') {
    mutations++;assert.equal(new URL(route.request().url()).pathname,'/api/connect-browser');
    return route.fulfill({status:202,json:{status:'queued'}});
   }
   await route.fulfill({json:data});
  });
  await page.goto(base+'/web/index.html');
  await page.waitForFunction(expected=>document.querySelector('#setup-action').textContent===expected,system==='linux'?'本机登录后绑定':'连接 Discord');
  await page.locator('#connect-browser-button').click();
  if(system==='linux') {
   assert.equal(mutations,0);assert.equal(popups,0);
   assert.equal(await page.locator('#advanced-settings').evaluate(el=>el.open),true);
   assert.ok(await page.locator('#linux-binding-command').textContent().then(s=>s.includes("--remote-root '/home/example/Archive Folder'")));
   assert.ok(await page.locator('#connect-browser-fallback').isHidden());
   data.platform.login_desktop=true;await page.locator('#refresh-button').click();
   await page.waitForFunction(()=>!document.querySelector('#connect-browser-fallback').hidden);
   await page.locator('#connect-browser-fallback').click();
   assert.equal(mutations,1);await page.waitForTimeout(100);assert.equal(popups,1);
  } else {
   await page.waitForFunction(()=>!document.querySelector('#connect-browser-button').disabled);
   assert.equal(mutations,1);assert.ok(await page.locator('#linux-binding').isHidden());
  }
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  if(system==='linux'&&width===1360)await page.screenshot({path:'/private/tmp/discord-binding-settings.png',fullPage:true});
  await page.close();
 }
 console.log('Mac/Linux 390/1360: local login preserved; Linux binding primary sends no login request; VNC explicit fallback only; no horizontal overflow.');
} finally {await browser.close();}
