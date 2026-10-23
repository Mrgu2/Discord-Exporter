// Real UI assets, fictional 5,000-draft API. No archive writes or image decodes.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const base=process.argv[2]||'http://127.0.0.1:8765';
assert.ok(['127.0.0.1','localhost'].includes(new URL(base).hostname));
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const reports=[];
try {
  for(const width of [390,1360]) {
    const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});
    const page=await context.newPage(), errors=[], calls=[], images=[];
    page.on('pageerror',error=>errors.push(error.message));
    let revision='v1',failNext=false;
    const rows=Array.from({length:5000},(_,i)=>({id:`fictional-${String(i).padStart(5,'0')}`,
      title:i===4999?'虚构 · 最早一份记录':`虚构稿件 ${String(i).padStart(5,'0')}`,
      status:'ready',created_at:'2026-10-22T20:00:00Z',manuscript_url:'/fictional.md',
      images:[],single_columns:[],warning_count:0,
      image_variants:{'1':{images:[],single_columns:[]},'2':{images:['/output/fictional/two.png'],single_columns:[]}}}));
    const status=()=>({config:{channels:[{id:'100',label:'答疑',enabled:true}],target_author_id:'owner',schedule:{enabled:false}},
      state:{render_jobs:[]},connectivity:{online:true},credentials:{discord:true},archive:{message_count:7},runs:[],remote:{},
      drafts:rows.slice(0,3),draft_count:rows.length,draft_revision:revision});
    await page.route('**/api/**',async route=>{
      const url=new URL(route.request().url());
      if(url.pathname==='/api/status') return route.fulfill({json:status()});
      if(url.pathname==='/api/drafts') {
        const limit=Number(url.searchParams.get('limit')),offset=Number(url.searchParams.get('offset'));
        const search=url.searchParams.get('search')||'';calls.push({limit,offset,search,revision});
        if(failNext) {failNext=false;return route.fulfill({status:503,json:{error:'合成故障，请重试'}});}
        const matches=rows.filter(row=>row.title.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
        if(search==='虚构稿件 000') await new Promise(resolve=>setTimeout(resolve,600));
        return route.fulfill({json:{items:matches.slice(offset,offset+limit),total:matches.length,
          limit,offset,has_more:offset+limit<matches.length,revision}});
      }
      throw new Error(`Unexpected mutation or API ${url.pathname}`);
    });
    await page.route('**/output/**/*.png',route=>{images.push(route.request().url());return route.abort();});
    await page.goto(base,{waitUntil:'networkidle'});
    assert.equal(await page.locator('#recent-drafts .draft-row').count(),3);
    assert.equal(await page.locator('#draft-count').textContent(),'5000');
    assert.equal(calls.length,0,'Workspace fetched the whole library');
    await page.locator('[data-view="library"]').click();
    await page.waitForFunction(()=>document.querySelectorAll('#all-drafts .draft-row').length===20);
    assert.equal(await page.locator('#draft-page-count').innerText(),'1–20 / 5,000');
    await page.locator('#draft-page-next').click();
    await page.waitForFunction(()=>document.querySelector('#draft-page-count').textContent.startsWith('21–40'));
    assert.equal(await page.locator('#all-drafts .draft-row').count(),20);
    assert.match(await page.locator('#all-drafts .draft-row').first().innerText(),/00020/);
    await page.locator('#draft-page-previous').click();
    await page.waitForFunction(()=>document.querySelector('#draft-page-count').textContent.startsWith('1–20'));
    await page.locator('#draft-search').fill('最早');
    await page.waitForFunction(()=>document.querySelectorAll('#all-drafts .draft-row').length===1);
    assert.match(await page.locator('#all-drafts .draft-row').first().innerText(),/最早一份记录/);
    assert.ok(calls.some(call=>call.search==='最早' && call.offset===0));
    await page.locator('#draft-search').fill('虚构稿件 000');
    await page.waitForTimeout(300);
    await page.locator('#draft-search').fill('最早');
    await page.waitForTimeout(950);
    assert.equal(await page.locator('#all-drafts .draft-row').count(),1,'Stale search result replaced a later query');
    assert.match(await page.locator('#all-drafts .draft-row').first().innerText(),/最早一份记录/);
    rows[4999].title='虚构 · 最早一份记录已更新';revision='v2';
    await page.locator('#refresh-button').click();
    await page.waitForFunction(()=>document.querySelector('#all-drafts .draft-row')?.textContent.includes('已更新'));
    failNext=true;
    await page.locator('#draft-search').fill('不存在');
    await page.waitForFunction(()=>!document.querySelector('#draft-list-error').hidden);
    assert.match(await page.locator('#draft-list-error').innerText(),/合成故障/);
    await page.locator('#draft-list-retry').click();
    await page.waitForFunction(()=>document.querySelector('#draft-list-error').hidden);
    assert.equal(await page.locator('#all-drafts .draft-row').count(),0);
    await page.locator('#draft-search').fill('虚构稿件');
    await page.waitForFunction(()=>document.querySelectorAll('#all-drafts .draft-row').length===20);
    const row=page.locator('#all-drafts .draft-row').first();
    assert.equal(await row.getByRole('link',{name:'下载图片',exact:true}).count(),0);
    await row.getByRole('combobox',{name:'图片清晰度'}).selectOption('2');
    assert.equal(await row.getByRole('link',{name:'下载图片',exact:true}).getAttribute('href'),'/output/fictional/two.png');
    assert.equal(await page.locator('body').evaluate(element=>element.scrollWidth),width);
    assert.equal(images.length,0,'Library decoded full-size images');
    assert.deepEqual(errors,[]);
    assert.ok(calls.every(call=>call.limit===20),'Unbounded API request');
    reports.push({width,total:5000,recent_rows:3,library_dom_rows:20,pagination:true,full_library_search:true,
      stale_search_discarded:true,external_update_visible:true,retry:true,density_variants:true,image_requests:0,console_errors:0});
    await context.close();
  }
  const report={status:'passed',fictional_only:true,reports};
  fs.mkdirSync('artifacts',{recursive:true});fs.writeFileSync('artifacts/draft-library-acceptance.json',JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
}finally{await browser.close();}
