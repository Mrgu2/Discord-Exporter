// Local UI assets and entirely fictional API responses. Never changes real settings.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const require=createRequire(import.meta.url);
let playwright;
try{playwright=require('playwright');}catch{playwright=require(process.env.PLAYWRIGHT_MODULE||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));}
const html=fs.readFileSync(path.join(root,'web/index.html'),'utf8').replace('__ARCHIVE_KEY__','fictional-key');
const directory=path.join(root,'artifacts/auto-export-ui');fs.mkdirSync(directory,{recursive:true});
const defaults={enabled:false,times:['16:15'],weekdays:[0,1,2,3,4],render_scales:[1],layout:'horizontal',presentation:'reading',target:'main'};
const browser=await playwright.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const results=[];
try{
 for(const width of [1360,390])for(const local of [true,false]){
  const hostname=local?'127.0.0.1':'archive-mac.local';
  const zone=local?'Asia/Shanghai':'Europe/London';
  const context=await browser.newContext({viewport:{width,height:900},timezoneId:zone,reducedMotion:'reduce'});
  const page=await context.newPage(),errors=[],mutations=[];
  page.on('pageerror',error=>errors.push(error.message));
  const data={config:{channels:[{id:'100',label:'答疑',kind:'qa',enabled:true}],target_author_id:'123456',target_message_url:'',timezone:'auto',market_timezone:'America/New_York',day_boundary_hour:4,schedule:{enabled:true,interval_minutes:360,times:[],window:{enabled:true,start:'15:50',end:'16:10',every_minutes:5}},model:{enabled:false},export:{name_prefix:'虚构稿件',date_format:'YYYY-MM-DD',sequence_digits:2,separator:'-',copy_directory:''}},state:{market_day:'2026-10-23',browser_connected:true},credentials:{discord:true},connectivity:{online:true},archive:{message_count:7},runs:[],drafts:[],remote:{}};
  await context.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url());
   if(url.origin!==`http://${hostname}:8765`)throw new Error('Unexpected external request');
   if(url.pathname==='/api/status')return route.fulfill({json:data});
   if(url.pathname==='/api/config'&&request.method()==='PUT'){
    const body=request.postDataJSON();mutations.push(body);
    assert.equal(request.headers()['x-archive-key'],'fictional-key');
    data.config={...body,export:{...data.config.export,...body.export}};
    data.state.auto_export={enabled:body.auto_export.enabled,next_at:'2026-10-23T20:15:00Z',last_status:'success',last_completed_at:'2026-10-22T20:15:00Z',last_draft_id:'274ee8a1-f0de-4d97-8987-536815bd5671'};
    return route.fulfill({json:data.config});
   }
   if(url.pathname.startsWith('/api/'))throw new Error(`Unexpected API action ${url.pathname}`);
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:html});
   if(url.pathname.startsWith('/web/'))return route.fulfill({contentType:url.pathname.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync(path.join(root,url.pathname.slice(1)))});
   return route.fulfill({status:404,body:''});
  });
  await page.goto(`http://${hostname}:8765/#settings`,{waitUntil:'networkidle'});
  await page.locator('#auto-export-settings').waitFor();
  assert.equal(await page.locator('#auto-export-enabled').isChecked(),false,'Legacy config enabled automatic exports');
  assert.equal(await page.locator('#auto-export-times').inputValue(),'16:15');
  assert.equal(await page.locator('#auto-export-scales').inputValue(),'1');
  assert.equal(await page.locator('#auto-export-next').innerText(),'未启用');
  assert.equal(await page.locator('#auto-export-status').innerText(),'尚未执行');
  assert.equal(await page.locator('#export-copy-directory').getAttribute('readonly')!==null,!local);
  await page.locator('label').filter({has:page.locator('#auto-export-enabled')}).click();
  await page.locator('#auto-export-times').fill('16:15, 9:45，16:15');
  await page.locator('#auto-export-weekdays').selectOption('daily');
  await page.locator('#auto-export-scales').selectOption('both');
  await page.locator('#auto-export-layout').selectOption('stacked');
  await page.locator('#auto-export-presentation').selectOption('full');
  await page.locator('label').filter({has:page.locator('#auto-export-columns')}).click();
  await page.locator('#refresh-button').click();
  assert.equal(await page.locator('#auto-export-enabled').isChecked(),true,'Polling overwrote unsaved automatic export fields');
  assert.equal(await page.locator('#auto-export-times').inputValue(),'16:15, 9:45，16:15');
  await page.locator('#config-save-button').click();
  await page.waitForFunction(()=>document.querySelector('#config-save-status').textContent.includes('未保存'));
  assert.equal(mutations.length,0,'Enabled without a destination');
  assert.match(await page.locator('#toast').innerText(),local?/自动另存目录/:/Mac 上设置自动另存目录/);
  if(local)await page.locator('#export-copy-directory').fill('/Users/example/Documents/虚构稿件');
  else{
   data.config.export.copy_directory='/Users/example/Documents/虚构稿件';
   await page.locator('#refresh-button').click();
   assert.equal(await page.locator('#auto-export-times').inputValue(),'16:15, 9:45，16:15');
  }
  await page.locator('#config-save-button').click();
  await page.waitForFunction(()=>document.querySelector('#config-save-status').textContent==='设置已保存。');
  assert.equal(mutations.length,1);
  assert.deepEqual(mutations[0].auto_export,{...defaults,enabled:true,times:['09:45','16:15'],weekdays:[0,1,2,3,4,5,6],render_scales:[1,2],layout:'stacked',presentation:'full',target:'all'});
  if(local)assert.equal(mutations[0].export.copy_directory,'/Users/example/Documents/虚构稿件');
  else assert.equal(Object.hasOwn(mutations[0].export,'copy_directory'),false,'Phone PUT included protected copy destination');
  assert.equal(mutations[0].schedule.interval_minutes,360);
  assert.equal(await page.locator('#auto-export-times').inputValue(),'09:45, 16:15');
  assert.equal(await page.locator('#auto-export-next').innerText(),local?'10/24 04:15':'10/23 21:15');
  assert.match(await page.locator('#auto-export-status').innerText(),/已完成/);
  assert.equal(await page.locator('#auto-export-last-draft').getAttribute('href'),'/drafts/274ee8a1-f0de-4d97-8987-536815bd5671/');
  await page.reload({waitUntil:'networkidle'});
  assert.equal(await page.locator('#auto-export-enabled').isChecked(),true);
  assert.equal(await page.locator('#auto-export-times').inputValue(),'09:45, 16:15');
  assert.equal(await page.locator('#auto-export-scales').inputValue(),'both');
  assert.equal(await page.locator('#auto-export-columns').isChecked(),true);
  await page.locator('#auto-export-settings').screenshot({path:path.join(directory,`${local?'mac':'phone'}-${width}.png`)});
  data.state.auto_export={...data.state.auto_export,last_status:'failed',stage:'render',last_error:'虚构故障：另存目录不可写',retry_at:'2026-10-23T20:20:00Z'};
  await page.locator('#refresh-button').click();
  await page.waitForFunction(()=>!document.querySelector('#auto-export-error').hidden);
  assert.match(await page.locator('#auto-export-error').innerText(),/另存目录不可写/);
  assert.match(await page.locator('#auto-export-status').innerText(),/重试/);
  assert.match(await page.locator('#auto-export-status').innerText(),/^图片生成未完成/);
  data.state.auto_export={...data.state.auto_export,last_status:'running',last_error:null,retry_at:null,stage:'render'};
  await page.locator('#refresh-button').click();
  await page.waitForFunction(()=>document.querySelector('#auto-export-status').textContent==='正在生成图片');
  data.state.auto_export={...data.state.auto_export,last_status:'failed',stage:'capture_partial'};
  await page.locator('#refresh-button').click();
  await page.waitForFunction(()=>document.querySelector('#auto-export-status').textContent==='频道保存未完整');
  data.state.auto_export={...data.state.auto_export,last_status:'skipped',stage:'render'};
  await page.locator('#refresh-button').click();
  await page.waitForFunction(()=>document.querySelector('#auto-export-status').textContent==='该交易日无可导出发言');
  data.state.auto_export={...data.state.auto_export,last_status:'idle'};
  await page.locator('#refresh-button').click();
  await page.waitForFunction(()=>document.querySelector('#auto-export-status').textContent==='尚未执行');
  await page.locator('#auto-export-times').fill('25:99');
  await page.locator('#config-save-button').click();
  assert.equal(mutations.length,1,'Invalid time reached the API');
  assert.equal(await page.locator('body').evaluate(body=>body.scrollWidth),width,'Export settings overflowed the viewport');
  assert.deepEqual(errors,[]);
  results.push({width,caller:local?'Mac':'phone',timezone:zone,default_disabled:true,dirty_preserved:true,multiple_times_normalized:true,save_reload:true,destination_required:true,remote_destination_omitted:!local,status_and_error:true,partial_capture_idle_skip:true,overflow:false,console_errors:0});
  await context.close();
 }
 const report={status:'passed',fictional_only:true,results};fs.writeFileSync(path.join(root,'artifacts/auto-export-ui-acceptance.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
}finally{await browser.close();}
