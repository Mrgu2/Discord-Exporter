// Browser checks use fictional API responses and intercept every request.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const require=createRequire(import.meta.url);
let playwright;
try {playwright=require('playwright');} catch {playwright=require(path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));}
const browser=await playwright.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const results=[];
try {
 for(const width of [1360,390]) {
  const context=await browser.newContext({viewport:{width,height:900}});
  const page=await context.newPage(),errors=[],actions=[];
  page.on('pageerror',error=>errors.push(error.message));
  const data={platform:{system:'linux'},config:{channels:[{id:'100',label:'虚构频道',enabled:true}],target_author_id:'123',timezone:'auto',market_timezone:'America/New_York',day_boundary_hour:4,schedule:{enabled:false,interval_minutes:360},model:{enabled:false},export:{name_prefix:'虚构稿件',date_format:'YYYY-MM-DD',sequence_digits:2,separator:'-',copy_directory:''},delivery:{email:{enabled:false,host:'',port:465,security:'ssl',username:'',sender:'',recipients:[]},telegram:{enabled:false,chat_id:''},discord:{enabled:false}}},state:{market_day:'2026-10-25',browser_connected:true,delivery:[]},credentials:{discord:true},connectivity:{online:true},archive:{message_count:7},runs:[],drafts:[],remote:{administrator:false}};
  await context.route('**/*',async route=> {
   const request=route.request(),url=new URL(request.url());
   assert.equal(url.origin,'http://archive.example:8765','External request blocked');
   if(url.pathname==='/api/status') return route.fulfill({json:data});
   if(url.pathname==='/api/config'&&request.method()==='PUT') {
    const body=request.postDataJSON();actions.push({path:url.pathname,body});
    assert.equal(request.headers()['x-archive-key'],'fixture-key');
    data.config={...data.config,...body,export:{...data.config.export,...body.export}};return route.fulfill({json:data.config});
   }
   if(url.pathname==='/api/delivery/credential') {
    const body=request.postDataJSON();actions.push({path:url.pathname,body});
    data.credentials[`delivery_${body.channel}`]=true;return route.fulfill({json:{ok:true,backend:'private_file'}});
   }
   if(url.pathname==='/api/delivery/test') {
    const body=request.postDataJSON();actions.push({path:url.pathname,body});
    data.state.delivery=[{id:'fake-delivery',channel:body.channel,title:'答疑存档 · 测试发送',test:true,status:'retrying',retry_at:'2026-10-25T01:01:00Z',error:'虚构网络故障'}];
    return route.fulfill({status:202,json:{id:'fake-delivery',status:'pending'}});
   }
   if(url.pathname==='/api/delivery/retry') {
    actions.push({path:url.pathname,body:request.postDataJSON()});
    data.state.delivery[0]={...data.state.delivery[0],status:'sent',error:null,retry_at:null};
    return route.fulfill({status:202,json:{status:'pending'}});
   }
   if(url.pathname.startsWith('/api/'))throw new Error('Unexpected endpoint '+url.pathname);
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'web/index.html'),'utf8').replace('__ARCHIVE_KEY__','fixture-key')});
   if(url.pathname.startsWith('/web/'))return route.fulfill({contentType:url.pathname.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync(path.join(root,url.pathname.slice(1)))});
   return route.fulfill({status:404,body:''});
  });
  await page.goto('http://archive.example:8765/#settings',{waitUntil:'networkidle'});
  for(const name of ['email','telegram','discord'])assert.equal(await page.locator(`#delivery-${name}-enabled`).isChecked(),false);
  await page.locator('[data-delivery-channel="telegram"] summary').click();
  await page.locator('#delivery-telegram-chat_id').fill('123456');
  await page.locator('#refresh-button').click();
  assert.equal(await page.locator('#delivery-telegram-chat_id').inputValue(),'123456','Polling clobbered unsaved destination');
  await page.locator('#delivery-telegram-secret').fill('123:FAKE_token');
  await page.locator('[data-delivery-test="telegram"]').click();
  await page.waitForFunction(()=>document.querySelector('#delivery-history').textContent.includes('虚构网络故障'));
  assert.equal(await page.locator('#delivery-telegram-secret').inputValue(),'');
  assert.equal(await page.locator('#delivery-telegram-enabled').isChecked(),false,'Test silently enabled automatic sending');
  assert.match(await page.locator('#delivery-telegram-configured').innerText(),/已保存/);
  assert.deepEqual(actions.slice(0,3).map(x=>x.path),['/api/delivery/credential','/api/config','/api/delivery/test']);
  assert.equal(actions[1].body.delivery.telegram.chat_id,'123456');
  assert.equal(JSON.stringify(actions[1].body).includes('FAKE_token'),false);
  await page.getByRole('button',{name:'重试发送',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#delivery-history').textContent.includes('已发送'));
  assert.equal(await page.getByRole('button',{name:'重试发送',exact:true}).count(),0);
  // Enable Telegram, then enable automatic exports with no copy directory.
  await page.locator('label').filter({has:page.locator('#delivery-telegram-enabled')}).click();
  await page.locator('#delivery-save').click();
  await page.waitForFunction(()=>document.querySelector('#delivery-save-status').textContent==='推送设置已保存。');
  await page.locator('label').filter({has:page.locator('#auto-export-enabled')}).click();
  await page.locator('#config-save-button').click();
  await page.waitForFunction(()=>document.querySelector('#config-save-status').textContent==='设置已保存。');
  assert.equal(data.config.auto_export.enabled,true);
  assert.equal(data.config.export.copy_directory,'');
  await page.reload({waitUntil:'networkidle'});
  assert.equal(await page.locator('#delivery-telegram-enabled').isChecked(),true);
  assert.equal(await page.locator('#delivery-telegram-secret').inputValue(),'');
  // Exercise all field types and both additional test buttons.
  await page.locator('[data-delivery-channel="email"] summary').click();
  await page.locator('#delivery-email-host').fill('smtp.example.com');
  await page.locator('#delivery-email-security').selectOption('starttls');
  await page.locator('#delivery-email-port').fill('587');
  await page.locator('#delivery-email-username').fill('sender@example.com');
  await page.locator('#delivery-email-sender').fill('sender@example.com');
  await page.locator('#delivery-email-recipients').fill('one@example.com, two@example.com');
  await page.locator('#delivery-email-secret').fill('fake-mail-secret');
  await page.locator('[data-delivery-test="email"]').click();
  await page.waitForFunction(()=>document.querySelector('#delivery-history').textContent.includes('邮箱'));
  assert.deepEqual(data.config.delivery.email.recipients,['one@example.com','two@example.com']);
  assert.equal(data.config.delivery.email.port,587);
  assert.equal(data.config.delivery.email.security,'starttls');
  await page.locator('[data-delivery-channel="discord"] summary').click();
  await page.locator('#delivery-discord-secret').fill('https://discord.com/api/webhooks/123/fake');
  await page.locator('[data-delivery-test="discord"]').click();
  await page.waitForFunction(()=>document.querySelector('#delivery-history').textContent.includes('Discord'));
  assert.equal(await page.locator('#delivery-discord-secret').inputValue(),'');
  assert.deepEqual(errors,[]);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Horizontal overflow');
  const dir=path.join(root,'artifacts/delivery-ui');fs.mkdirSync(dir,{recursive:true});
  await page.locator('#delivery-settings').screenshot({path:path.join(dir,`${width}.png`)});
  results.push({width,actions:actions.length,errors});await context.close();
 }
} finally {await browser.close();}
console.log(JSON.stringify(results,null,2));
