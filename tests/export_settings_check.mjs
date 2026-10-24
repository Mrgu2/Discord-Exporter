// Real application UI with fictional API responses; never changes local settings.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
let playwright;
try { playwright = require('playwright'); }
catch { playwright = require(process.env.PLAYWRIGHT_MODULE || path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')); }
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const artifacts = path.join(root, 'artifacts/export-settings');
fs.mkdirSync(artifacts, {recursive:true});
const defaults = {name_prefix:'答疑存档',date_format:'YYYY-MM-DD',sequence_digits:2,separator:'-',copy_directory:''};
function fixture() {
  return {config:{channels:[{id:'100',label:'示例讨论',enabled:true,kind:'qa'}],target_author_id:'123456',
    timezone:'auto',market_timezone:'America/New_York',day_boundary_hour:4,
    schedule:{enabled:true,interval_minutes:360,times:[],window:{enabled:true,start:'15:50',end:'16:10',every_minutes:5}},
    model:{enabled:false}},state:{market_day:'2026-10-23'},credentials:{discord:true},connectivity:{online:true},
    archive:{message_count:100,channel_count:1},runs:[],drafts:[],remote:{}};
}
const browser = await playwright.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const report = [];
try {
  for (const [local,width] of [[true,1360],[true,390],[false,390],[false,320]]) {
    let data=fixture(), chosen={cancelled:true};
    const mutations=[],errors=[];
    const context=await browser.newContext({viewport:{width,height:900},timezoneId:'Asia/Tokyo',reducedMotion:'reduce'});
    const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*',async route=>{
      const request=route.request(), url=new URL(request.url()), endpoint=url.pathname;
      if (endpoint.startsWith('/api/')) {
        if (request.method()!=='GET') mutations.push({endpoint,body:request.postDataJSON()});
        if (endpoint==='/api/status') return route.fulfill({json:data});
        if (endpoint==='/api/config' && request.method()==='PUT') {
          const body=request.postDataJSON();
          data.config={...body,export:{...defaults,...data.config.export,...body.export}};
          return route.fulfill({json:data.config});
        }
        if (endpoint==='/api/export-directory') return route.fulfill({json:chosen});
        return route.fulfill({json:{items:[],total:0,has_more:false}});
      }
      if (endpoint==='/') return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'web/index.html'),'utf8').replace('__ARCHIVE_KEY__','fictional-csrf')});
      if (endpoint.startsWith('/web/') && !endpoint.includes('..')) {
        const file=path.join(root,endpoint.slice(1));
        if (fs.existsSync(file)) return route.fulfill({path:file});
      }
      return route.fulfill({status:404,body:''});
    });
    await page.goto(`http://${local?'127.0.0.1':'192.168.99.9'}:8765/#settings`);
    await page.waitForFunction(()=>document.querySelector('#target-author').value==='123456');
    assert.equal(await page.locator('#export-name-preview').textContent(),'答疑存档-2026-10-23-01.png');
    await page.locator('#export-prefix').fill('示例周刊');
    await page.locator('#export-date-format').selectOption('YYYYMMDD');
    await page.locator('#export-sequence-digits').selectOption('3');
    await page.locator('#export-separator').selectOption('_');
    assert.equal(await page.locator('#export-name-preview').textContent(),'示例周刊_20261023_001.png');
    data.drafts=[{id:'274ee8a1-f0de-4d97-8987-536815bd5671',title:'虚构另存失败稿',status:'ready',
      created_at:'2026-10-24T06:17:00Z',images:['/output/test.png'],
      export_copy:{enabled:true,copied:0,failed:1,error:'另存目录不可用'}}];
    await page.evaluate(()=>window.dispatchEvent(new Event('online')));
    await page.getByRole('button',{name:'自动另存未完成，查看原因'}).click();
    assert.match(await page.locator('#toast').textContent(),/另存目录不可用.*现有图片仍可下载/);
    // Polling must not overwrite an unfinished edit.
    await page.evaluate(()=>window.dispatchEvent(new Event('online')));
    await page.waitForResponse(response=>response.url().includes('/api/status'));
    assert.equal(await page.locator('#export-prefix').inputValue(),'示例周刊');
    if (local) {
      await page.locator('#export-copy-directory').fill('~/Downloads/示例导出');
      await page.locator('#export-directory-choose').click();
      await page.waitForFunction(()=>document.querySelector('#export-directory-choose').textContent==='选择文件夹');
      assert.equal(await page.locator('#export-copy-directory').inputValue(),'~/Downloads/示例导出','Cancel must preserve input');
      chosen={path:'/tmp/fictional-export'};
      await page.locator('#export-directory-choose').click();
      await page.waitForFunction(()=>document.querySelector('#export-copy-directory').value==='/tmp/fictional-export');
    } else {
      assert.equal(await page.locator('#export-copy-directory').getAttribute('readonly'),'');
      assert.equal(await page.locator('#export-directory-choose').isDisabled(),true);
      assert.equal(await page.locator('#export-directory-phone-note').isVisible(),true);
    }
    await page.locator('#config-form button[type=submit]').click();
    await page.waitForFunction(()=>document.querySelector('#config-save-status').textContent==='设置已保存。');
    const saved=mutations.find(row=>row.endpoint==='/api/config');assert.ok(saved);
    assert.equal(saved.body.export.name_prefix,'示例周刊');
    assert.equal(saved.body.export.sequence_digits,3);
    if (local) assert.equal(saved.body.export.copy_directory,'/tmp/fictional-export');
    else assert.equal(Object.hasOwn(saved.body.export,'copy_directory'),false);
    await page.reload();await page.waitForFunction(()=>document.querySelector('#export-prefix').value==='示例周刊');
    assert.equal(await page.locator('#export-name-preview').textContent(),'示例周刊_20261023_001.png');
    assert.equal(await page.locator('body').evaluate(element=>element.scrollWidth),width,'Settings must fit viewport');
    assert.deepEqual(errors,[]);
    await page.locator('#export-settings').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(artifacts,`${local?'mac':'phone'}-${width}.png`)});
    report.push({local,width,preview:true,save:true,reload:true,directoryBoundary:true,noOverflow:true});
    await context.close();
  }
  fs.writeFileSync(path.join(artifacts,'browser-acceptance.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
} finally { await browser.close(); }
