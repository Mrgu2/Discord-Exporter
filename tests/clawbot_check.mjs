// ClawBot binding UI regression. Every network request is fictional and intercepted.
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
  data.remote.administrator=true;
  data.state.clawbot={status:'unbound',connected:false,ready:false};
  await context.route('**/*',async route=> {
   const request=route.request(),url=new URL(request.url());
   assert.equal(url.origin,'http://archive.example:8765','External request blocked');
   if(url.pathname==='/api/status') return route.fulfill({json:data});
   if(url.pathname==='/api/config'&&request.method()==='PUT') {
    const body=request.postDataJSON();actions.push({path:url.pathname,body});
    assert.equal(request.headers()['x-archive-key'],'fixture-key');
    data.config={...data.config,...body,export:{...data.config.export,...body.export}};return route.fulfill({json:data.config});
   }
   if(url.pathname==='/api/clawbot/connect') {
    actions.push({path:url.pathname,body:request.postDataJSON()});
    data.state.clawbot={status:'unbound',connected:false,ready:false,login_status:'wait',login_id:'fixture',qr_url:'/api/clawbot/qr?id=fixture'};
    return route.fulfill({json:data.state.clawbot});
   }
   if(url.pathname==='/api/clawbot/qr') return route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=','base64')});
   if(url.pathname==='/api/clawbot/verify') {
    actions.push({path:url.pathname,body:request.postDataJSON()});
    return route.fulfill({json:{ok:true}});
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
  assert.equal(await page.locator('#delivery-clawbot-enabled').isChecked(),false);
  assert.equal(await page.locator('#delivery-clawbot-enabled').isEnabled(),false);
  await page.locator('[data-delivery-channel="clawbot"] summary').click();
  await page.locator('#clawbot-connect').click();
  await page.waitForFunction(()=>!document.querySelector('#clawbot-qr-panel').hidden);
  assert.equal(await page.locator('#clawbot-qr').getAttribute('src'),'/api/clawbot/qr?id=fixture');
  assert.match(await page.locator('#clawbot-status').innerText(),/等待扫码/);
  data.state.clawbot={...data.state.clawbot,login_status:'need_verifycode'};
  await page.locator('#refresh-button').click();
  await page.waitForFunction(()=>!document.querySelector('#clawbot-verify-panel').hidden);
  await page.locator('#clawbot-verify-code').fill('123456');
  await page.locator('#clawbot-verify').click();
  await page.waitForFunction(()=>!document.querySelector('#clawbot-verify').disabled);
  assert.equal(await page.locator('#clawbot-verify-code').inputValue(),'');
  assert.deepEqual(actions.find(x=>x.path==='/api/clawbot/verify').body,{id:'fixture',code:'123456'});
  data.state.clawbot={status:'needs_message',connected:true,ready:false,login_status:'confirmed',qr_url:null};
  await page.locator('#refresh-button').click();
  await page.waitForFunction(()=>document.querySelector('#clawbot-qr-panel').hidden);
  assert.match(await page.locator('#clawbot-status').innerText(),/发一条消息/);
  assert.equal(await page.locator('#delivery-clawbot-enabled').isEnabled(),true);
  data.state.clawbot={...data.state.clawbot,status:'ready',ready:true};
  await page.locator('#refresh-button').click();
  await page.waitForFunction(()=>document.querySelector('#clawbot-status').textContent.includes('可发送'));
  await page.locator('label').filter({has:page.locator('#delivery-clawbot-enabled')}).click();
  await page.locator('#delivery-save').click();
  await page.waitForFunction(()=>document.querySelector('#delivery-save-status').textContent==='推送设置已保存。');
  assert.deepEqual(data.config.delivery.clawbot,{enabled:true});
  await page.locator('[data-delivery-test="clawbot"]').click();
  await page.waitForFunction(()=>document.querySelector('#delivery-history').textContent.includes('微信 ClawBot'));
  assert.equal(actions.at(-1).path,'/api/delivery/test');
  assert.equal(actions.at(-1).body.channel,'clawbot');
  data.state.delivery[0]={...data.state.delivery[0],status:'attention',retry_at:null,error:'请向微信 ClawBot 发一条消息后重试'};
  await page.locator('#refresh-button').click();
  await page.waitForFunction(()=>document.querySelector('#delivery-history').textContent.includes('需微信操作'));
  await page.getByRole('button',{name:'重试发送',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#delivery-history').textContent.includes('已发送'));
  assert.deepEqual(errors,[]);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Horizontal overflow');
  const dir=path.join(root,'artifacts/clawbot-ui');fs.mkdirSync(dir,{recursive:true});
  await page.locator('#delivery-settings').screenshot({path:path.join(dir,`${width}.png`)});
  results.push({width,actions:actions.length,errors});await context.close();
 }
} finally {await browser.close();}
console.log(JSON.stringify(results,null,2));
