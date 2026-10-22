// Read-only UI acceptance against the running local service. No real account,
// capture, settings save, or browser login is triggered by this test.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';

const require=createRequire(import.meta.url);
let playwright;
try{playwright=require('playwright');}
catch{playwright=require(process.env.PLAYWRIGHT_MODULE||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));}
const base=process.argv[2]||'http://127.0.0.1:8765';
const parsed=new URL(base);
assert.ok(['127.0.0.1','localhost'].includes(parsed.hostname),'Only a local test service is accepted');
const directory=path.resolve('artifacts');fs.mkdirSync(directory,{recursive:true});
const browser=await playwright.chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const results=[];
try{
  for(const [name,width,height,timezoneId] of [['desktop',1360,900,'Asia/Shanghai'],['mobile',390,844,'Europe/London']]){
    const context=await browser.newContext({viewport:{width,height},timezoneId});
    const page=await context.newPage(),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/output/ui-check/*.png',route=>route.fulfill({status:200,contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="2000"><rect width="640" height="2000" fill="white"/><path d="M40 100H600M40 300H600M40 600H600M40 900H600M40 1200H600M40 1500H600M40 1800H600" stroke="#60766b" stroke-width="6"/></svg>'}));
    await page.goto(base,{waitUntil:'networkidle'});
    await page.waitForFunction(()=>document.querySelectorAll('.channel-option').length===5);
    assert.equal(await page.locator('.advanced-settings').evaluate(element=>element.open),false,'Advanced settings should start closed');
    assert.equal(await page.locator('body').evaluate(element=>element.scrollWidth),width,'Page overflowed horizontally');
    const visible=await page.locator('body').innerText();
    assert.ok(!visible.includes('America/New_York'),'Raw market timezone leaked into the normal flow');
    assert.ok(!visible.includes('频道 ID'),'Normal operation exposed channel IDs');
    await page.locator('.advanced-settings > summary').click();
    await page.locator('#timezone').waitFor({state:'visible'});
    assert.equal(await page.locator('#timezone').evaluate(element=>element.tagName),'SELECT');
    assert.equal(await page.locator('#timezone option[value="auto"]').textContent(),'跟随手机或电脑');
    await page.locator('.advanced-settings > summary').click();
    await page.locator('#refresh-button').focus();
    await page.evaluate(()=>window.ArchivePreview.open(['/output/ui-check/first.png','/output/ui-check/second.png'],'虚构长图预览验收'));
    await page.waitForFunction(()=>document.querySelector('.image-preview img')?.naturalWidth===640);
    await page.locator('.image-preview').waitFor({state:'visible'});
    assert.equal(await page.locator('.image-preview [data-action="previous"]').isDisabled(),true);
    if(name==='desktop'){
      const stage=await page.locator('.image-preview-stage').boundingBox();
      const x=stage.x+stage.width/2,y=stage.y+stage.height/2;
      await page.mouse.move(x,y);await page.mouse.wheel(0,-350);
      await page.waitForFunction(()=>parseInt(document.querySelector('.image-preview-status').textContent)>100);
      const before=await page.locator('.image-preview img').evaluate(element=>element.style.transform);
      await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+2,y+2);await page.mouse.up();
      assert.equal(await page.locator('.image-preview img').evaluate(element=>element.style.transform),before,'Small hand movement was treated as a drag');
      await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x,y+80,{steps:5});await page.mouse.up();
      await page.waitForFunction(previous=>document.querySelector('.image-preview img').style.transform!==previous,before);
    }
    await page.locator('.image-preview [data-action="next"]').click();
    await page.waitForFunction(()=>document.querySelector('.image-preview-title').textContent.includes('2/2'));
    await page.screenshot({path:path.join(directory,`preview-${name}.png`)});
    await page.keyboard.press('Escape');
    await page.locator('.image-preview').waitFor({state:'hidden'});
    assert.equal(await page.locator('#refresh-button').evaluate(element=>element===document.activeElement),true,'Closing preview lost keyboard focus');
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.evaluate(()=>window.ArchivePreview.open(['/output/ui-check/first.png'],'减少动态效果验收'));
    assert.equal(await page.locator('.image-preview').evaluate(element=>getComputedStyle(element).animationName),'none');
    await page.keyboard.press('Escape');
    await page.screenshot({path:path.join(directory,`ui-final-${name}.png`),fullPage:true});
    assert.deepEqual(errors,[]);
    results.push({viewport:name,width,timezone:timezoneId,channels:5,console_errors:errors.length,advanced_fields_hidden:true,preview_keyboard:true,reduced_motion:true});
    await context.close();
  }
  console.log(JSON.stringify({status:'passed',read_only:true,results,screenshots:directory},null,2));
}finally{await browser.close();}
