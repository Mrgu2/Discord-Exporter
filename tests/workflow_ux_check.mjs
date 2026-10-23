// Fictional API and PNG data only: direct download, channel navigation and job locks.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const base=process.argv[2]||'http://127.0.0.1:8765';
assert.ok(['127.0.0.1','localhost'].includes(new URL(base).hostname));
const directory=path.resolve('artifacts/workflow-ux');fs.mkdirSync(directory,{recursive:true});
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aO1cAAAAASUVORK5CYII=','base64');
// Chrome cancels downloads fulfilled by request interception. Serve only this
// isolated fictional file through the real local file route for download QA.
const fixtureDirectory=fs.mkdtempSync(path.resolve('output/ui-ux-check-'));
fs.writeFileSync(path.join(fixtureDirectory,'main.png'),png);
const downloadUrl=`/output/${path.basename(fixtureDirectory)}/main.png`;
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const results=[];
try {
  for(const width of [1360,390]) {
    const context=await browser.newContext({viewport:{width,height:900},acceptDownloads:true});
    const page=await context.newPage(),errors=[],mutations=[],imageRequests=[];
    page.on('pageerror',error=>errors.push(error.message));
    const id='274ee8a1-f0de-4d97-8987-536815bd5671',empty='274ee8a1-f0de-4d97-8987-536815bd5672';
    const columns=[{title:'示例栏目甲',channel_id:'100',images:['/output/ui-ux/feed.png']},
      {title:'示例问答',channel_id:'200',images:['/output/ui-ux/qa1.png','/output/ui-ux/qa2.png']}];
    const data={config:{channels:[{id:'100',label:'示例栏目甲',enabled:true}],target_author_id:'owner',market_timezone:'America/New_York',timezone:'auto',schedule:{enabled:false}},
      state:{market_day:'2026-10-22',render_jobs:[]},connectivity:{online:true},credentials:{discord:true},archive:{message_count:7},runs:[],remote:{},
      drafts:[{id,title:'虚构语音稿',status:'ready',created_at:'2026-10-22T20:00:00Z',layout:'horizontal',render_scale:2,audio:{complete:7},
        images:[downloadUrl],single_columns:columns},
      {id:empty,title:'虚构待出图稿',status:'ready',created_at:'2026-10-22T20:00:00Z',single_columns:[{title:'答疑',channel_id:'200',images:[]}]}]};
    await context.route('**/api/**',async route=>{
      const endpoint=new URL(route.request().url()).pathname;
      if(route.request().method()!=='GET'){
        const body=route.request().postDataJSON();mutations.push({endpoint,body});
        data.state.render_jobs.push({id:'fixture-job',type:'render',draft_id:body.draft_id,target:body.target});
        return route.fulfill({status:202,json:{id:'fixture-job',status:'queued'}});
      }
      return route.fulfill({json:data});
    });
    await context.route('**/output/ui-ux/*.png',route=>{imageRequests.push(route.request().url());return route.fulfill({contentType:'image/png',body:png});});
    await page.goto(base,{waitUntil:'networkidle'});
    const row=page.locator('#recent-drafts .draft-row').first();
    assert.match(await row.innerText(),/7 条语音转写/);
    assert.equal(imageRequests.length,0,'Listing drafts decoded a large image');
    const download=await Promise.all([page.waitForEvent('download'),row.getByRole('link',{name:'下载高清图',exact:true}).click()]);
    assert.equal(download[0].suggestedFilename(),'虚构语音稿-高清.png');
    const destination=path.join(directory,`direct-${width}.png`);await download[0].saveAs(destination);
    assert.deepEqual(fs.readFileSync(destination),png);
    assert.equal(await page.locator('.image-preview').count(),0,'Download unnecessarily opened a preview');
    await row.getByRole('button',{name:'分栏图',exact:true}).click();
    const select=page.getByRole('combobox',{name:'选择频道'});await select.selectOption('1');
    await page.waitForFunction(()=>document.querySelector('.image-preview img').src.endsWith('/qa1.png'));
    await page.locator('.image-preview [data-action="next"]').click();
    await page.waitForFunction(()=>document.querySelector('.image-preview img').src.endsWith('/qa2.png'));
    assert.equal(await page.locator('.image-preview [data-action="next"]').isDisabled(),true);
    assert.equal(await page.locator('body').evaluate(body=>body.scrollWidth),width);
    await page.keyboard.press('Escape');
    await row.getByRole('button',{name:'更新图片',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#recent-drafts .draft-row button:last-child').disabled);
    assert.equal(mutations[0].body.target,'main');
    await page.reload({waitUntil:'networkidle'});
    assert.equal(await page.locator('#recent-drafts .draft-row').first().getByRole('button',{name:'图片生成中…'}).isDisabled(),true);
    const second=page.locator('#recent-drafts .draft-row').nth(1);
    await second.getByRole('button',{name:'生成分栏图',exact:true}).click();
    assert.equal(mutations.at(-1).body.target,'mobile');
    assert.equal(mutations.length,2);
    assert.deepEqual(errors,[]);
    await page.screenshot({path:path.join(directory,`workspace-${width}.png`),fullPage:true});
    results.push({width,direct_download_bytes_equal:true,no_preview_for_download:true,channel_jump:true,
      busy_survives_reload:true,main_and_mobile_separate:true,console_errors:errors.length});
    await context.close();
  }
  console.log(JSON.stringify({status:'passed',fictional_only:true,results},null,2));
}finally{await browser.close();}
