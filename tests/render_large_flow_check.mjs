// Native large-flow pagination using generated content, without archive writes.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const directory=fs.mkdtempSync(path.join(os.tmpdir(),'discord-large-flow-'));
const reports=[];
function fixture(count,layout,{height=4000}={}) {
  const topics=Array.from({length:count},(_,index)=>{
    const image=index%6===0?`<img class="source-image" src="data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="128" height="64"><rect width="128" height="64" fill="rgb(${index},90,130)"/></svg>`)}">`:'';
    return `<article class="topic"><h2>虚构完整主题 ${index}</h2><section class="block answer" data-segment data-evidence-id="fictional/${index}"><div class="source-meta">虚构资料 ${index}</div><p class="message-text">先读第一段 ${index}。\n再读第二段 ${index}。保持原文顺序、字号与图片比例。</p>${image}</section></article>`;
  });
  const feedCount=Math.floor(count/4);
  const feed=`<section class="content-panel" data-kind="feed"><h2 class="category-title">虚构实盘</h2>${topics.slice(0,feedCount).join('')}</section>`;
  const qa=`<section class="content-panel" data-kind="qa"><h2 class="category-title">虚构讨论</h2>${topics.slice(feedCount).join('')}</section>`;
  const notice='<article class="topic" data-archive-warnings><h2>归档提示</h2><section class="block note" data-segment><p class="message-text">虚构提示只应出现在最后一页一次。</p></section></article>';
  return `<!doctype html><meta charset="utf-8"><style>.topic:not([data-archive-warnings]){min-height:${height}px}</style><body data-layout="${layout}" data-presentation="reading"><main id="manuscript"><header><h1>虚构大内容原生分页验收</h1><div class="document-meta">全部文字图片均为本地生成测试资料</div></header><div class="panel-grid">${qa}${feed}</div>${notice}</main>`;
}

function render(name,html,scale=1) {
  const input=path.join(directory,name+'.html'),output=path.join(directory,name);
  fs.writeFileSync(input,html);
  const child=spawnSync(process.execPath,[path.join(root,'scripts/render.mjs'),input,output,String(scale)],{encoding:'utf8',timeout:240000});
  assert.equal(child.status,0,child.stderr);
  const result=JSON.parse(child.stdout);
  fs.writeFileSync(path.join(directory,name+'.result.json'),JSON.stringify(result,null,2));
  assert.equal(result.source_coverage.missing,0);assert.equal(result.image_coverage.missing,0);
  assert.equal(result.text_coverage.mismatched_sources,0);assert.equal(result.topic_integrity.fragmented_topics,0);
  assert.equal(result.topic_manifest.matched,true);assert.equal(result.reading_order.sequential,true);
  assert.equal(result.geometry.within_pages,true);assert.equal(result.geometry.image_aspect_preserved,true);
  assert.equal(result.topic_manifest.expected_topics,result.topic_manifest.rendered_topics);
  assert.equal(result.images.length,result.page_count);assert.equal(result.page_layouts.length,result.page_count);
  const orders=result.page_layouts.flatMap(page=>page.topic_orders);
  assert.deepEqual(orders,Array.from({length:result.topic_manifest.expected_topics},(_,i)=>i),'Topics were omitted, duplicated or moved');
  assert.equal(new Set(orders).size,orders.length);
  for(const [index,box] of result.dimensions.entries()) {
    assert.ok(box.width<=64000 && box.height<=64000 && box.width*box.height<=320_000_000);
    assert.ok(result.css_dimensions[index].width<=32000 && result.css_dimensions[index].height<=32000);
    assert.ok(result.css_dimensions[index].width*result.css_dimensions[index].height<=80_000_000);
    assert.ok(box.width>box.height,'A large-flow page became an inconvenient portrait strip');
    const file=fs.openSync(result.images[index],'r'),header=Buffer.alloc(24);fs.readSync(file,header,0,24,0);fs.closeSync(file);
    assert.equal(header.readUInt32BE(16),box.width);assert.equal(header.readUInt32BE(20),box.height);
    assert.ok(result.raster_tiles.some(tile=>tile.page===index));
  }
  for(const image of result.source_images) assert.ok(Math.abs(image.width/image.height-image.natural_width/image.natural_height)<0.01);
  assert.equal(result.structure.headings,result.page_count);assert.equal(result.structure.footers,result.page_count>1?result.page_count:0);
  assert.ok(result.raster_tiles.every(tile=>tile.width<=4096 && tile.height<=4096));
  if(result.page_count>1)assert.ok(result.bands.every(band=>Number.isInteger(band.page) && band.page<result.page_count));
  reports.push({name,layout:result.layout_mode,pages:result.page_count,scale,dimensions:result.dimensions,
    source_coverage:result.source_coverage,topic_manifest:result.topic_manifest,page_layouts:result.page_layouts});
  return result;
}

const two=render('horizontal-two',fixture(24,'horizontal'));
assert.equal(two.page_count,2);assert.equal(two.source_coverage.expected_unique_sources,24);
const twoHidpi=render('horizontal-two-hidpi',fixture(24,'horizontal'),2);
assert.deepEqual(twoHidpi.css_dimensions,two.css_dimensions,'HiDPI changed the pagination/composition');
assert.deepEqual(twoHidpi.dimensions,two.dimensions.map(box=>({width:box.width*2,height:box.height*2})));
assert.ok(twoHidpi.pixel_font_sizes.includes('54px'));
const three=render('stacked-three',fixture(36,'stacked',{height:3800}));
assert.equal(three.page_count,3);assert.equal(three.source_coverage.expected_unique_sources,36);
const small=render('small',fixture(6,'horizontal',{height:0}));
assert.equal(small.page_count,1);
// Single-page exports deliberately keep their established footer-free layout.
assert.equal(small.structure.footers,0);
const oversizedInput=path.join(directory,'one-topic-too-large.html');
fs.writeFileSync(oversizedInput,fixture(1,'horizontal',{height:40000}));
const oversized=spawnSync(process.execPath,[path.join(root,'scripts/render.mjs'),oversizedInput,path.join(directory,'oversized')],{encoding:'utf8',timeout:60000});
assert.notEqual(oversized.status,0);assert.match(oversized.stderr,/单个主题|无法.*分页/);
assert.ok(!fs.existsSync(path.join(directory,'oversized/long-01.png')));
const report={status:'passed',directory,fictional_only:true,oversized_topic_rejected:true,reports};
fs.writeFileSync(path.join(directory,'acceptance.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify(report,null,2));
