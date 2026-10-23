// HiDPI acceptance with fictional, locally rendered content only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'discord-hidpi-'));
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const block=(id,text)=>`<section class="block answer" data-segment data-evidence-id="${id}"><div class="source-meta">虚构作者 · 纽约时间</div><p class="message-text">${text}</p></section>`;
const topic=(id,text)=>`<article class="topic"><h2>HiDPI 清晰度 ${id}</h2>${block(id,text)}</article>`;
const text='高清正文应当直接以二倍设备像素绘制。保持原文字号和内容，问答连续阅读。Aa 0123456789。';
const feeds=['示例栏目甲','示例栏目丁'].map((title,panel)=>`<section class="content-panel" data-kind="feed"><h2 class="category-title">${title}</h2>${Array.from({length:3},(_,i)=>topic(`feed${panel}/${i}`,text)).join('')}</section>`).join('');
const qa=`<section class="content-panel" data-kind="qa"><h2 class="category-title">示例问答</h2>${Array.from({length:8},(_,i)=>topic(`qa/${i}`,text.repeat(2))).join('')}</section>`;
const notice='<article class="topic" data-archive-warnings><h2>归档提示</h2><section class="block note" data-segment><p class="message-text">有一条引用消息未保存在本地。</p></section></article>';
const html=`<!doctype html><meta charset="utf-8"><body data-layout="horizontal" data-presentation="reading"><main id="manuscript"><header><h1>虚构左右分区高清验收</h1><div class="document-meta">仅供测试</div></header><div class="panel-grid">${qa}${feeds}</div>${notice}</main>`;
const input=path.join(dir,'input.html');fs.writeFileSync(input,html);
function render(name,scale){
 const args=[path.join(root,'scripts/render.mjs'),input,path.join(dir,name)];if(scale!==undefined)args.push(String(scale));
 const child=spawnSync(process.execPath,args,{encoding:'utf8',timeout:180000});assert.equal(child.status,0,child.stderr);
 return JSON.parse(child.stdout);
}
const baseline=render('one'),hidpi=render('two',2);
assert.equal(hidpi.render_scale,2,'Selected export is not HiDPI');assert.equal(baseline.render_scale,1,'Default export is not standard');
assert.deepEqual(hidpi.css_dimensions,baseline.css_dimensions,'Density changed the composition');
assert.deepEqual(hidpi.dimensions,hidpi.css_dimensions.map(({width,height})=>({width:width*2,height:height*2})));
assert.ok(hidpi.pixel_font_sizes.includes('54px'),'27px body text did not receive 54 output pixels');
assert.ok(hidpi.raster_tiles.every(t=>t.width<=4096&&t.height<=4096),'Device-pixel tile exceeded the texture bound');
assert.equal(hidpi.images.length,1);assert.ok(hidpi.dimensions[0].width>hidpi.dimensions[0].height,'Expected a landscape image');
assert.deepEqual(hidpi.bands.map(b=>b.kind),['feed','qa']);
assert.equal(hidpi.bands[0].y,hidpi.bands[1].y,'Sections are not top aligned');
assert.ok(hidpi.bands[1].x>=hidpi.bands[0].x+hidpi.bands[0].width,'Q&A is not to the right of the feeds');
assert.equal(hidpi.topic_integrity.fragmented_topics,0);assert.equal(hidpi.reading_order.sequential,true);
assert.equal(hidpi.source_coverage.missing,0);assert.equal(hidpi.source_coverage.expected_unique_sources,14);
assert.equal(hidpi.text_coverage.mismatched_sources,0);assert.deepEqual(hidpi.source_coverage,baseline.source_coverage);
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
let detail;
try{
 const page=await browser.newPage();
 detail=await page.evaluate(async({one,two})=>{
  const load=async data=>{const image=new Image();image.src='data:image/png;base64,'+data;await image.decode();return image;};
  const low=await load(one),high=await load(two),canvas=document.createElement('canvas');canvas.width=high.naturalWidth;canvas.height=high.naturalHeight;
  const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(high,0,0);const actual=ctx.getImageData(0,0,canvas.width,canvas.height).data;
  const counts=[];
  for(const smooth of [false,true]){
   ctx.clearRect(0,0,canvas.width,canvas.height);ctx.imageSmoothingEnabled=smooth;ctx.drawImage(low,0,0,canvas.width,canvas.height);
   const enlarged=ctx.getImageData(0,0,canvas.width,canvas.height).data;let count=0;
   for(let i=0;i<actual.length;i+=4)if(Math.abs(actual[i]-enlarged[i])+Math.abs(actual[i+1]-enlarged[i+1])+Math.abs(actual[i+2]-enlarged[i+2])>30)count++;
   counts.push(count);
  }
  return {nearest_different_pixels:counts[0],smooth_different_pixels:counts[1],pixels:canvas.width*canvas.height};
 },{one:fs.readFileSync(baseline.images[0]).toString('base64'),two:fs.readFileSync(hidpi.images[0]).toString('base64')});
 assert.ok(detail.nearest_different_pixels>1000&&detail.smooth_different_pixels>1000,'2x output only enlarged the existing 1x pixels');
}finally{await browser.close();}
console.log(JSON.stringify({status:'passed',directory:dir,render_scale:2,dimensions:hidpi.dimensions,css_dimensions:hidpi.css_dimensions,pixel_font_sizes:hidpi.pixel_font_sizes,bands:hidpi.bands,source_coverage:hidpi.source_coverage,topic_integrity:hidpi.topic_integrity,native_glyph_detail:detail},null,2));
