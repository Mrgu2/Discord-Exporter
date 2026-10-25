// Fictional accounts only. All API writes are intercepted in this browser.
import http from 'node:http';
import assert from 'node:assert/strict';import fs from 'node:fs';import path from 'node:path';
import {loadPlaywright,browserOptions} from '../scripts/browser_runtime.mjs';
const root=path.resolve(new URL('..',import.meta.url).pathname),pw=await loadPlaywright({localOnly:true});
const samplePng=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=','base64');
const server=http.createServer((req,res)=>{if(req.url!=='/output/example/first.png'){res.writeHead(404);return res.end();}res.writeHead(200,{'Content-Type':'image/png','Content-Length':samplePng.length});res.end(samplePng);});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin=`http://127.0.0.1:${server.address().port}`;
const browser=await pw.chromium.launch({headless:true,...browserOptions(pw)}),results=[];
try{for(const platform of ['darwin','linux'])for(const width of [390,1360]){
 const context=await browser.newContext({viewport:{width,height:900},acceptDownloads:true}),page=await context.newPage(),errors=[],calls=[];
 page.on('pageerror',e=>errors.push(e.message));
 const data={platform:{system:platform},config:{channels:[{id:'100',label:'虚构小频道',enabled:true}],target_author_id:'123',target_message_url:'',market_timezone:'America/New_York',schedule:{enabled:false},model:{}},state:{automatic_paused:true},credentials:{discord:true},archive:{message_count:0},drafts:[],draft_count:0,runs:[],remote:{administrator:true,https_url:platform==='linux'?'https://fixture.example.ts.net':''}};
 let captureAttempts=0,renderAttempts=0;
 const image='/output/example/first.png',png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=','base64');
 await context.route('**/*',async route=>{const r=route.request(),u=new URL(r.url());assert.equal(u.origin,origin);
  if(r.method()==='POST'){const body=r.postDataJSON();calls.push({path:u.pathname,body});
   if(u.pathname==='/api/capture'){captureAttempts++;data.state.active_job={type:'capture',message:'虚构保存中'};return route.fulfill({status:202,json:{id:'capture-job'}});}
   if(u.pathname==='/api/drafts'){assert.equal(body.scope,'latest');assert.equal(body.mode,'evidence');data.state.active_job={type:'draft'};return route.fulfill({status:202,json:{id:'draft-job'}});}
   if(u.pathname==='/api/render'){renderAttempts++;assert.equal(body.render_scale,1);assert.equal(body.target,'main');if(renderAttempts===1)return route.fulfill({status:500,json:{error:'虚构生成故障'}});data.state.active_job={type:'render'};return route.fulfill({status:202,json:{id:'render-job'}});}
   throw new Error('Unexpected write '+u.pathname);
  }
  if(u.pathname==='/api/status')return route.fulfill({json:data});
  if(u.pathname==='/')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'web/index.html'),'utf8').replace('__ARCHIVE_KEY__','fake-key')});
  if(u.pathname.startsWith('/web/'))return route.fulfill({contentType:u.pathname.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync(path.join(root,u.pathname.slice(1)))});
  if(u.pathname===image)return route.continue();
  throw new Error('Unexpected read '+u.pathname);
 });
 const refresh=async()=>{await page.locator('#refresh-button').click();};
 await page.goto(origin+'/#workspace',{waitUntil:'networkidle'});
 await page.locator('#first-output-guide').waitFor({state:'visible'});assert.match(await page.locator('#first-output-detail').textContent(),/全部可见历史/);
 await page.locator('#first-output-action').click();await page.waitForFunction(()=>document.querySelector('#first-output-action').disabled);
 data.state.active_job=null;data.state.last_job_status='failed';data.state.last_job_error='虚构网络断开';data.archive.message_count=1;await refresh();
 await page.waitForFunction(()=>document.querySelector('#first-output-action').textContent==='确认保存所选频道'&&!document.querySelector('#first-output-action').disabled);
 await page.locator('#first-output-action').click();
 data.state.active_job=null;data.state.last_job_status='success';data.state.last_job_error=null;data.state.last_success_at='2026-10-25T01:00:00Z';data.archive.message_count=7;data.runs=[{status:'success'}];await refresh();
 await page.waitForFunction(()=>document.querySelector('#first-output-action').textContent==='生成首份稿件'&&!document.querySelector('#first-output-action').disabled);
 await page.evaluate(()=>{document.querySelector('input[name="scope"][value="day"]').checked=true;document.querySelector('#draft-mode').value='model';});
 await page.locator('#first-output-action').evaluate(el=>{el.click();el.click();});
 await page.waitForFunction(()=>document.querySelector('#first-output-action').disabled);
 data.state.active_job=null;data.drafts=[{id:'first',title:'虚构首份稿件',status:'ready',scope:'latest'}];data.draft_count=1;await refresh();
 await page.waitForFunction(()=>document.querySelector('#first-output-action').textContent==='生成第一张图片'&&!document.querySelector('#first-output-action').disabled);
 await page.locator('#first-output-action').click();await page.waitForFunction(()=>!document.querySelector('#first-output-action').disabled);
 assert.equal(await page.locator('#first-output-download').isVisible(),false);
 await page.locator('#first-output-action').click();await page.waitForFunction(()=>document.querySelector('#first-output-action').disabled);
 data.state.active_job=null;data.drafts[0].images=[image];data.drafts[0].render_scale=1;await refresh();
 await page.waitForFunction(()=>document.querySelector('#first-output-action').textContent==='查看图片');
 assert.equal(await page.locator('#first-output-download').getAttribute('href'),image);
 await page.locator('#first-output-action').click();assert.equal(await page.getByRole('dialog').isVisible(),true);
 await page.keyboard.press('Escape');
 const event=page.waitForEvent('download');await page.locator('#first-output-download').click();const download=await event;
 assert.ok(await download.path());assert.equal(await page.locator('#first-output-guide').isVisible(),false);
 assert.equal(captureAttempts,2);assert.equal(calls.filter(x=>x.path==='/api/drafts').length,1);assert.equal(renderAttempts,2);
 await page.reload({waitUntil:'networkidle'});assert.equal(await page.locator('#first-output-guide').isVisible(),false);
 assert.equal(data.state.automatic_paused,true);assert.deepEqual(errors,[]);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 fs.mkdirSync(path.join(root,'artifacts/first-output-ui'),{recursive:true});await page.screenshot({path:path.join(root,`artifacts/first-output-ui/${platform}-${width}.png`),fullPage:true});results.push({platform,width,orderedStages:true,failureRecovery:true,noDuplicateDraft:true,existingLibraryGuideHidden:true,writes:calls.length,errors});await context.close();
}}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}console.log(JSON.stringify(results,null,2));
