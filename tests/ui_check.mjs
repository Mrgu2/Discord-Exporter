// UI acceptance with fictional API data. Every API mutation is intercepted;
// no real account, capture, settings save or browser login is used.
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
  for(const [name,width,height,timezoneId,dpr] of [['desktop',1360,900,'Asia/Shanghai',1],['mobile',390,844,'Europe/London',3]]){
    const context=await browser.newContext({viewport:{width,height},timezoneId,deviceScaleFactor:dpr,isMobile:name==='mobile',hasTouch:name==='mobile'});
    const page=await context.newPage(),errors=[],mutations=[];
    page.on('pageerror',error=>errors.push(error.message));
    const rasterFixture=Buffer.from(await page.evaluate(()=>{
      const canvas=document.createElement('canvas');canvas.width=24000;canvas.height=800;
      const context=canvas.getContext('2d');context.fillStyle='white';context.fillRect(0,0,24000,800);
      context.fillStyle='#60766b';context.fillRect(0,0,800,800);
      for(let x=64;x<192;x++){context.fillStyle=x%2?'white':'black';context.fillRect(x,0,1,800);}
      context.fillStyle='#345ed0';context.fillRect(23200,0,800,800);
      return canvas.toDataURL('image/png').split(',')[1];
    }),'base64');
    await page.route('**/api/**',route=>{
      if(route.request().method()!=='GET')mutations.push(new URL(route.request().url()).pathname);
      return route.fulfill({json:{
        config:{channels:Array.from({length:5},(_,i)=>({id:String(i+1),label:`虚构频道 ${i+1}`,enabled:true})),target_author_id:'123456',timezone:'auto',market_timezone:'America/New_York',day_boundary_hour:4,schedule:{enabled:true,interval_minutes:360,times:[],window:{enabled:true,start:'15:50',end:'16:10',every_minutes:5}},model:{enabled:false}},
        state:{market_day:'2026-10-21'},connectivity:{online:true},credentials:{discord:true},archive:{message_count:9,channel_count:5,attachment_count:0,attachment_failures:0},drafts:[],runs:[],remote:{}
      }});
    });
    await page.route('**/output/ui-check/*.png',route=>route.request().url().endsWith('/raster.png')?route.fulfill({status:200,contentType:'image/png',body:rasterFixture}):route.fulfill({status:200,contentType:'image/svg+xml',body:route.request().url().endsWith('/wide.png')
      ? '<svg xmlns="http://www.w3.org/2000/svg" width="24000" height="2400"><defs><pattern id="pixels" width="2" height="2" patternUnits="userSpaceOnUse"><rect width="2" height="2" fill="white"/><rect width="1" height="2" fill="black"/></pattern></defs><rect width="24000" height="2400" fill="white"/><rect width="800" height="2400" fill="#60766b"/><rect x="64" width="128" height="2400" fill="url(#pixels)"/><rect x="23200" width="800" height="2400" fill="#345ed0"/></svg>'
      : '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="2000"><rect width="640" height="2000" fill="white"/><path d="M40 100H600M40 300H600M40 600H600M40 900H600M40 1200H600M40 1500H600M40 1800H600" stroke="#60766b" stroke-width="6"/></svg>'}));
    await page.goto(base,{waitUntil:'networkidle'});
    await page.waitForFunction(()=>document.querySelectorAll('.channel-option').length===5);
    assert.equal(await page.locator('.advanced-settings').evaluate(element=>element.open),false,'Advanced settings should start closed');
    assert.equal(await page.locator('body').evaluate(element=>element.scrollWidth),width,'Page overflowed horizontally');
    const visible=await page.locator('body').innerText();
    assert.ok(!visible.includes('America/New_York'),'Raw market timezone leaked into the normal flow');
    assert.ok(!visible.includes('频道 ID'),'Normal operation exposed channel IDs');
    assert.equal(await page.locator('#draft-layout').inputValue(),'horizontal','Horizontal export should be the default');
    assert.match(await page.locator('#draft-options-label').textContent(),/左右分区高清图/);
    assert.equal(await page.locator('#draft-layout option[value="stacked"]').count(),1,'Stacked export must remain selectable');
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
    await page.evaluate(()=>window.ArchivePreview.open(['/output/ui-check/wide.png'],'虚构横向长图'));
    await page.waitForFunction(()=>document.querySelector('.image-preview img')?.naturalWidth===24000 && document.querySelector('.image-preview img').style.visibility==='visible',null,{timeout:10000}).catch(async error=>{
      const state=await page.locator('.image-preview img').evaluate(image=>({width:image.naturalWidth,complete:image.complete,visibility:image.style.visibility,source:image.src}));
      throw new Error(`${name}: horizontal fixture did not load: ${JSON.stringify(state)}`,{cause:error});
    });
    await page.locator('.image-preview').evaluate(async element=>Promise.all(element.getAnimations().map(animation=>animation.finished.catch(()=>{}))));
    await page.waitForFunction(()=>{
      const stage=document.querySelector('.image-preview-stage').getBoundingClientRect(),image=document.querySelector('.image-preview img').getBoundingClientRect();
      return Math.abs(stage.left-image.left)<1 && image.width>stage.width*2;
    });
    const wideStage=await page.locator('.image-preview-stage').boundingBox();
    const initialWide=await page.locator('.image-preview img').boundingBox();
    assert.ok(initialWide.height<=wideStage.height && initialWide.height>=wideStage.height-34,'Horizontal preview did not fit its height');
    await page.keyboard.press('ArrowRight');
    await page.waitForFunction(left=>document.querySelector('.image-preview img').getBoundingClientRect().left<left-1,initialWide.x);
    await page.keyboard.press('ArrowLeft');
    await page.waitForFunction(left=>Math.abs(document.querySelector('.image-preview img').getBoundingClientRect().left-left)<1,wideStage.x);
    await page.locator('.image-preview [data-action="out"]').click();
    await page.waitForFunction(initial=>document.querySelector('.image-preview img').getBoundingClientRect().width<initial,initialWide.width-1);
    await page.locator('.image-preview [data-action="in"]').click();
    await page.waitForFunction(initial=>Math.abs(document.querySelector('.image-preview img').getBoundingClientRect().width-initial)<1,initialWide.width);
    const wx=wideStage.x+wideStage.width/2,wy=wideStage.y+wideStage.height/2;
    await page.mouse.move(wx,wy);await page.mouse.down();await page.mouse.move(wx-initialWide.width,wy,{steps:8});await page.mouse.up();
    await page.waitForFunction(()=>{
      const stage=document.querySelector('.image-preview-stage').getBoundingClientRect(),image=document.querySelector('.image-preview img').getBoundingClientRect();
      return Math.abs(stage.right-image.right)<1;
    });
    await page.locator('.image-preview [data-action="fit"]').click();
    await page.waitForFunction(()=>document.querySelector('.image-preview-status').textContent==='100%');
    const fittedWide=await page.locator('.image-preview img').boundingBox();
    assert.ok(fittedWide.width<=wideStage.width && fittedWide.height<=wideStage.height,'Fit screen cropped a horizontal image');
    await page.locator('.image-preview [data-action="in"]').click();
    await page.waitForFunction(fitted=>document.querySelector('.image-preview img').getBoundingClientRect().width>fitted,fittedWide.width+1);
    await page.locator('.image-preview [data-action="out"]').click();
    await page.waitForFunction(()=>document.querySelector('.image-preview-status').textContent==='100%');
    await page.evaluate(()=>window.ArchivePreview.open(['/output/ui-check/raster.png'],'虚构位图清晰度验收'));
    await page.waitForFunction(()=>{
      const image=document.querySelector('.image-preview img');return image.naturalWidth===24000&&image.naturalHeight===800&&image.style.visibility==='visible';
    });
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    // At one source pixel per physical display pixel, stripes must stay black/white and the
    // far right must retain its own colour rather than wrap the first column.
    await page.locator('.image-preview [data-action="native"]').click();
    await page.waitForFunction(()=>{
      const image=document.querySelector('.image-preview img');return Math.abs(image.getBoundingClientRect().width*devicePixelRatio-image.naturalWidth)<1;
    },null,{timeout:5000}).catch(async error=>{
      const state=await page.locator('.image-preview img').evaluate(image=>({natural_width:image.naturalWidth,css_width:image.getBoundingClientRect().width,dpr:devicePixelRatio,style_width:image.style.width}));
      throw new Error(`${name}: native display scale was not reached: ${JSON.stringify(state)}`,{cause:error});
    });
    await page.mouse.move(wx,wy);await page.mouse.down();await page.mouse.move(wx+24000,wy,{steps:8});await page.mouse.up();
    await page.waitForFunction(()=>{
      const stage=document.querySelector('.image-preview-stage').getBoundingClientRect(),image=document.querySelector('.image-preview img').getBoundingClientRect();return Math.abs(stage.left-image.left)<1;
    });
    const pixelSample=async(x,y,count)=>{
      const encoded=(await page.screenshot({animations:'disabled'})).toString('base64');
      return page.evaluate(async({encoded,x,y,count})=>{
        const image=new Image();image.src='data:image/png;base64,'+encoded;await image.decode();
        const canvas=document.createElement('canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
        const context=canvas.getContext('2d');context.drawImage(image,0,0);
        return [...context.getImageData(Math.round(x*devicePixelRatio),Math.round(y*devicePixelRatio),count,1).data];
      },{encoded,x,y,count});
    };
    const stripePixels=await pixelSample(wideStage.x+80/dpr,wy,64);
    const stripeValues=Array.from({length:64},(_,i)=>stripePixels[i*4]);
    assert.ok(stripeValues.filter(value=>value<=8||value>=247).length>=60,'Native pixels became a blurred fitted texture');
    assert.ok(stripeValues.some(value=>value<=8)&&stripeValues.some(value=>value>=247),'Native one-pixel detail was lost');
    await page.mouse.move(wx,wy);await page.mouse.down();await page.mouse.move(wx-24000,wy,{steps:8});await page.mouse.up();
    await page.waitForFunction(()=>{
      const stage=document.querySelector('.image-preview-stage').getBoundingClientRect(),image=document.querySelector('.image-preview img').getBoundingClientRect();return Math.abs(stage.right-image.right)<1;
    });
    const rightPixel=await pixelSample(wideStage.x+wideStage.width-40,wy,1);
    assert.ok([52,94,208].every((value,i)=>Math.abs(rightPixel[i]-value)<=2),'The right edge repeated pixels from a different column');
    await page.screenshot({path:path.join(directory,`preview-horizontal-${name}.png`)});
    await page.keyboard.press('Escape');
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.evaluate(()=>window.ArchivePreview.open(['/output/ui-check/first.png'],'减少动态效果验收'));
    assert.equal(await page.locator('.image-preview').evaluate(element=>getComputedStyle(element).animationName),'none');
    await page.keyboard.press('Escape');
    await page.screenshot({path:path.join(directory,`ui-final-${name}.png`),fullPage:true});
    assert.deepEqual(errors,[]);
    assert.deepEqual(mutations,[],'UI acceptance unexpectedly attempted an API mutation');
    results.push({viewport:name,width,device_pixel_ratio:await page.evaluate(()=>devicePixelRatio),timezone:timezoneId,channels:5,console_errors:errors.length,advanced_fields_hidden:true,preview_keyboard:true,horizontal_preview:{height_fit:true,left_start:true,right_edge_reachable:true,keyboard_pan:true,zoom_in_out:true,fit_screen:true,native_pixel_detail:true,no_right_edge_wrap:true},reduced_motion:true});
    await context.close();
  }
  console.log(JSON.stringify({status:'passed',read_only:true,results,screenshots:directory},null,2));
}finally{await browser.close();}
