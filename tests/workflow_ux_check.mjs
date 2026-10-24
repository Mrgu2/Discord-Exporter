// Fictional API and PNG data only: density variants, downloads and job locks.
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
// Chrome cancels downloads fulfilled by request interception. Serve only these
// isolated fictional files through the real local file route for byte QA.
const fixtureDirectory=fs.mkdtempSync(path.resolve('output/ui-ux-check-'));
const downloadNames={1:'答疑存档-2026-10-23-01.png',2:'答疑存档-2026-10-23-HiDPI-01.png'};
for(const name of Object.values(downloadNames))fs.writeFileSync(path.join(fixtureDirectory,name),png);
const downloadUrl=scale=>`/output/${path.basename(fixtureDirectory)}/${encodeURIComponent(downloadNames[scale])}`;
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const results=[];
try {
  for(const width of [1360,390]) {
    const context=await browser.newContext({viewport:{width,height:900},deviceScaleFactor:width===390?3:1,acceptDownloads:true});
    const page=await context.newPage(),errors=[],mutations=[],imageRequests=[];
    page.on('pageerror',error=>errors.push(error.message));
    const id='274ee8a1-f0de-4d97-8987-536815bd5671',empty='274ee8a1-f0de-4d97-8987-536815bd5672',both='274ee8a1-f0de-4d97-8987-536815bd5673';
    const columns=[{title:'示例栏目甲',channel_id:'100',file:'feed.html',images:['/output/ui-ux/feed.png']},
      {title:'示例问答',channel_id:'200',file:'qa.html',images:['/output/ui-ux/qa1.png','/output/ui-ux/qa2.png']}];
    const data={config:{channels:[{id:'100',label:'示例栏目甲',enabled:true}],target_author_id:'owner',market_timezone:'America/New_York',timezone:'auto',schedule:{enabled:false}},
      state:{market_day:'2026-10-22',render_jobs:[]},connectivity:{online:true},credentials:{discord:true},archive:{message_count:7},runs:[],remote:{},
      drafts:[{id,title:'虚构语音稿',status:'ready',created_at:'2026-10-22T20:00:00Z',layout:'horizontal',render_scale:2,audio:{complete:7},
        images:[downloadUrl(2)],single_columns:columns},
      {id:empty,title:'虚构待出图稿',status:'ready',created_at:'2026-10-22T20:00:00Z',single_columns:[{title:'答疑',channel_id:'200',file:'qa.html',images:[]}]},
      {id:both,title:'虚构双倍率稿',status:'ready',created_at:'2026-10-22T20:00:00Z',render_scale:2,images:[downloadUrl(2)],single_columns:columns,
        image_variants:{'1':{render_scale:1,images:[downloadUrl(1)],single_columns:columns.map(column=>({...column,images:[]}))},
          '2':{render_scale:2,images:[downloadUrl(2)],single_columns:columns}}},
      {id:'274ee8a1-f0de-4d97-8987-536815bd5674',title:'虚构旧分栏稿',status:'ready',images:[],
        single_columns:[{title:'答疑',channel_id:'200',render_scale:2,images:['/output/ui-ux/qa1.png']}]}]};
    await context.route('**/api/**',async route=>{
      const endpoint=new URL(route.request().url()).pathname;
      if(route.request().method()!=='GET'){
        const body=route.request().postDataJSON();mutations.push({endpoint,body});
        const jobId=`fixture-job-${mutations.length}`;
        data.state.render_jobs.push({id:jobId,type:'render',draft_id:body.draft_id,target:body.target,render_scale:body.render_scale});
        return route.fulfill({status:202,json:{id:jobId,status:'queued'}});
      }
      return route.fulfill({json:data});
    });
    await context.route('**/output/ui-ux/*.png',route=>{imageRequests.push(route.request().url());return route.fulfill({contentType:'image/png',body:png});});
    await context.route('**/output/naming-check/**',route=>route.fulfill({contentType:'image/png',body:png}));
    await page.goto(base,{waitUntil:'networkidle'});
    const row=page.locator('#recent-drafts .draft-row').first();
    const density=row.getByRole('combobox',{name:'图片清晰度'});
    assert.match(await row.innerText(),/7 条语音转写/);
    assert.equal(await density.inputValue(),'1','Standard export must be the initial choice');
    assert.equal(await row.getByRole('button',{name:'查看长图',exact:true}).count(),0,'Legacy 2x image leaked into 1x selection');
    assert.equal(await row.getByRole('link',{name:'下载图片',exact:true}).count(),0);
    assert.equal(await row.getByRole('button',{name:'生成分栏图',exact:true}).count(),1,'Missing variant must retain channel generation actions');
    assert.equal(imageRequests.length,0,'Listing drafts decoded an image');
    await row.getByRole('button',{name:'生成图片',exact:true}).click();
    assert.deepEqual(mutations[0].body,{draft_id:id,target:'main',render_scale:1});
    await page.waitForFunction(()=>document.querySelector('#recent-drafts .draft-row button:last-child').disabled);
    await density.selectOption('2');
    assert.equal(await row.getByRole('button',{name:'更新图片',exact:true}).isEnabled(),true,'1x job locked the 2x variant');
    assert.equal(await row.getByRole('link',{name:'下载图片',exact:true}).getAttribute('href'),downloadUrl(2));
    const download=await Promise.all([page.waitForEvent('download'),row.getByRole('link',{name:'下载图片',exact:true}).click()]);
    assert.equal(download[0].suggestedFilename(),downloadNames[2]);
    const destination=path.join(directory,`direct-${width}.png`);await download[0].saveAs(destination);
    assert.deepEqual(fs.readFileSync(destination),png);
    assert.equal(await page.locator('.image-preview').count(),0,'Download unnecessarily opened a preview');
    await row.getByRole('button',{name:'分栏图',exact:true}).click();
    const select=page.getByRole('combobox',{name:'选择频道'});await select.selectOption('1');
    await page.waitForFunction(()=>document.querySelector('.image-preview img').src.endsWith('/qa1.png'));
    await page.waitForFunction(()=>document.querySelector('.image-preview img').naturalWidth===1);
    assert.equal(await page.locator('.image-preview a').getAttribute('download'),'qa1.png','Column preview rewrote the published filename');
    await page.locator('.image-preview [data-action="native"]').click();
    await page.waitForFunction(()=>Math.abs(document.querySelector('.image-preview img').getBoundingClientRect().width*devicePixelRatio-1)<.1);
    const nativeWidth=await page.locator('.image-preview img').evaluate(img=>img.getBoundingClientRect().width);
    await page.locator('.image-preview [data-action="out"]').click();
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(resolve)));
    assert.ok(await page.locator('.image-preview img').evaluate((img,width)=>img.getBoundingClientRect().width<=width+.01,nativeWidth),'Zooming out after native pixels enlarged a small image');
    await page.locator('.image-preview [data-action="next"]').click();
    await page.waitForFunction(()=>document.querySelector('.image-preview img').src.endsWith('/qa2.png'));
    assert.equal(await page.locator('.image-preview a').getAttribute('download'),'qa2.png','Next page kept the previous filename');
    assert.equal(await page.locator('.image-preview [data-action="next"]').isDisabled(),true);
    assert.equal(await page.locator('body').evaluate(body=>body.scrollWidth),width);
    await page.keyboard.press('Escape');
    const namedPages=[
      {url:`/output/naming-check/scale-1/${encodeURIComponent('答疑存档-2026-10-23-02.png')}?version=fixture#preview`,name:'答疑存档-2026-10-23-02.png'},
      {url:`/output/naming-check/scale-2/${encodeURIComponent('答疑存档-2026-10-23-HiDPI-03.png')}`,name:'答疑存档-2026-10-23-HiDPI-03.png'},
      {url:'/output/naming-check/unsafe%2Fname.png',name:'长图.png'},
      {url:'/output/naming-check/malformed%ZZ.png',name:'长图.png'},
    ];
    await page.evaluate(pages=>window.ArchivePreview.open(pages.map(item=>item.url),'标题不能覆盖文件名 · 2×'),namedPages);
    for(let index=0;index<namedPages.length;index++) {
      assert.equal(await page.locator('.image-preview a').getAttribute('download'),namedPages[index].name);
      if(index<namedPages.length-1) await page.locator('.image-preview [data-action="next"]').click();
    }
    await page.locator('.image-preview [data-action="previous"]').click();
    assert.equal(await page.locator('.image-preview a').getAttribute('download'),namedPages[2].name);
    await page.keyboard.press('Escape');
    await row.getByRole('button',{name:'更新图片',exact:true}).click();
    assert.deepEqual(mutations[1].body,{draft_id:id,target:'main',render_scale:2});
    await page.reload({waitUntil:'networkidle'});
    assert.equal(await density.inputValue(),'1');
    assert.equal(await row.getByRole('button',{name:'图片生成中…'}).isDisabled(),true);
    await density.selectOption('2');
    assert.equal(await row.getByRole('button',{name:'图片生成中…'}).isDisabled(),true,'2x job lock must survive page reload');
    const second=page.locator('#recent-drafts .draft-row').nth(1);
    await second.getByRole('button',{name:'生成分栏图',exact:true}).click();
    assert.deepEqual(mutations.at(-1).body,{draft_id:empty,target:'mobile',render_scale:1});
    await second.getByRole('combobox',{name:'图片清晰度'}).selectOption('2');
    assert.equal(await second.getByRole('button',{name:'生成分栏图',exact:true}).isEnabled(),true);
    await second.getByRole('button',{name:'生成分栏图',exact:true}).click();
    assert.deepEqual(mutations.at(-1).body,{draft_id:empty,target:'mobile',render_scale:2});
    const third=page.locator('#recent-drafts .draft-row').nth(2);
    assert.equal(await third.getByRole('link',{name:'下载图片',exact:true}).getAttribute('href'),downloadUrl(1));
    assert.equal(await third.getByRole('link',{name:'下载图片',exact:true}).getAttribute('download'),downloadNames[1]);
    assert.equal(await third.getByRole('button',{name:'生成分栏图',exact:true}).count(),1,'1x variant reused 2x channel images');
    await third.getByRole('combobox',{name:'图片清晰度'}).selectOption('2');
    assert.equal(await third.getByRole('link',{name:'下载图片',exact:true}).getAttribute('href'),downloadUrl(2));
    assert.equal(await third.getByRole('button',{name:'分栏图',exact:true}).count(),1);
    await page.locator('[data-view="library"]').click();
    const oldMobile=page.locator('#all-drafts .draft-row').nth(3);
    assert.equal(await oldMobile.getByRole('button',{name:'生成分栏图',exact:true}).count(),1);
    await oldMobile.getByRole('combobox',{name:'图片清晰度'}).selectOption('2');
    assert.equal(await oldMobile.getByRole('button',{name:'分栏图',exact:true}).count(),1,'Legacy column density was inferred from the missing top-level value');
    assert.equal(mutations.length,4);
    assert.deepEqual(errors,[]);
    await page.screenshot({path:path.join(directory,`workspace-${width}.png`),fullPage:true});
    results.push({width,direct_download_bytes_equal:true,no_preview_for_download:true,channel_jump:true,
      standard_default:true,legacy_density_isolated:true,variant_urls_isolated:true,
      published_download_filenames:true,busy_survives_reload:true,busy_per_density:true,main_and_mobile_separate:true,console_errors:errors.length});
    await context.close();
  }
  console.log(JSON.stringify({status:'passed',fictional_only:true,results},null,2));
}finally{await browser.close();}
