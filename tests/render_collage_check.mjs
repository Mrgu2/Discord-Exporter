#!/usr/bin/env node
// Real Chromium regression check, using fictitious text and an optional saved
// 9-question/3-short-panel HTML fixture. No Discord account or network is used.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const project=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const directory=fs.mkdtempSync(path.join(os.tmpdir(),'discord-render-regression-'));
const style=`
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;color:#22252a;background:#f4f3ef}
main{width:2400px;padding:64px;background:white}h1{font-size:44px}h2{font-size:31px;line-height:1.5;margin:0 0 25px}
.document-meta{font-size:21px}.panel-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:40px}
.content-panel{min-width:0}.category-title{font-size:34px;border-bottom:3px solid #303945;padding-bottom:20px;margin-bottom:30px}
.topic{padding:0 0 35px;margin:0 0 38px}.content-panel .topic>h2{font-size:27px}.block{margin-bottom:28px}
.block-label{font-size:22px;font-weight:650;margin-bottom:8px}.source-meta{font-size:17px;color:#7a818b;line-height:1.65;margin-bottom:10px}
.message-text{font-size:27px;line-height:1.75;white-space:pre-wrap;margin:0;overflow-wrap:anywhere}.answer{padding-left:22px;border-left:3px solid #c8d0d8}
.render-page{width:1080px;background:white;padding:56px 60px 40px;margin:0 0 24px;overflow:hidden}.page-heading{font-size:25px;line-height:1.4;margin-bottom:8px}
.page-subtitle{font-size:16px;margin-bottom:34px}.page-footer{font-size:16px;border-top:1px solid #d9dde0;padding-top:17px;margin-top:26px;display:flex;justify-content:space-between}
.composition-lanes{display:grid;gap:36px;align-items:start}.composition-lane{min-width:0;align-self:start}.composition-page .content-panel{margin-bottom:32px}
.composition-page .topic{border-bottom:1px solid #d9dde0;padding-bottom:20px;margin-bottom:24px}.composition-page .topic>h2{font-size:27px}
.render-page .block:last-child{margin-bottom:0}.source-image{display:block;max-width:100%;width:auto;height:auto;max-height:2600px;object-fit:contain;margin:20px 0}
`;
const block=(id,label,text,image='')=>`<section class="block ${label==='回答'?'answer':''}" data-segment data-evidence-id="${id}"><div class="block-label">${label}</div><div class="source-meta">虚构作者 · 10:00 · 证据 ${id}</div><p class="message-text">${text}</p>${image}</section>`;
const questions=Array.from({length:9},(_,index)=>{
  const question=`第${index+1}个虚构问题：到观察位置以后，应该等待哪些条件再确认？`;
  const answer='价格、量能和市场环境都需要一起核对。价格到位置只代表开始观察，条件尚未满足时，原判断仍有不确定性。\n这是测试布局的虚构文字，不是实际投资建议。';
  return `<article class="topic"><h2>${String(index+1).padStart(2,'0')}　${question}</h2>${block(`100/q${index+1}`,'原问题',question)}${block(`100/a${index+1}`,'回答',answer)}</article>`;
}).join('');
const image='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="320"><rect width="640" height="320" fill="#e7edf6"/><path d="M30 260L170 170L300 210L450 80L610 110" fill="none" stroke="#536b87" stroke-width="6"/></svg>');
const feeds=Array.from({length:3},(_,index)=>`<section class="content-panel"><h2 class="category-title">短栏目 ${index+1}</h2>${[0,1].map(row=>`<article class="topic">${block(`feed${index+1}/${row}`,'回答','这是一条用于验证长图拼版的虚构记录。保留原文、时间和条件，不补写没有保存到的信息。')}</article>`).join('')}</section>`).join('');
const shell=(content,layout='collage')=>`<!doctype html><meta charset="utf-8"><style>${style}</style><body data-layout="${layout}"><main id="manuscript"><header><h1>虚构自适应拼版回归</h1><div class="document-meta">仅供测试 · 非群聊原文</div></header>${content}</main></body>`;
const generated=shell(`<div class="panel-grid"><section class="content-panel"><h2 class="category-title">九组问答</h2>${questions}</section>${feeds}</div>`);
const fixture=process.argv[2]?fs.readFileSync(path.resolve(process.argv[2]),'utf8'):generated;

function render(name,html) {
  const input=path.join(directory,name+'.html'),output=path.join(directory,name);
  fs.writeFileSync(input,html);
  const child=spawnSync(process.execPath,[path.join(project,'scripts','render.mjs'),input,output],{encoding:'utf8',timeout:120000});
  assert.equal(child.status,0,child.stderr || 'Renderer failed');
  const result=JSON.parse(child.stdout);
  assert.ok(result.dimensions.every(box=>box.height<=3600),'Page exceeded 3600px');
  assert.equal(result.source_coverage.missing,0,'Source IDs were lost');
  assert.equal(result.image_coverage.missing,0,'Images were lost');
  assert.equal(result.text_coverage.mismatched_sources,0,'Text was lost or duplicated');
  assert.ok(result.source_coverage.expected_unique_sources>0,'Completeness check was vacuous');
  for(const asset of result.source_images) {
    const natural=asset.natural_width/asset.natural_height,rendered=asset.width/asset.height;
    assert.ok(Math.abs(natural-rendered)/natural<0.01,'Source image aspect ratio changed');
  }
  return result;
}

const masonry=render('masonry',fixture);
assert.equal(masonry.layout_mode,'masonry-two');
assert.equal(masonry.source_coverage.expected_unique_sources,24);
assert.equal(masonry.source_coverage.rendered_unique_sources,24);
assert.equal(masonry.topic_integrity.fragmented_topics,0,'A complete small question/answer topic was split');
assert.ok(masonry.blank_ratio<0.10,'Two-column composition retained too much empty area');
const legacy=masonry.layout_candidates.find(candidate=>candidate.mode==='main-side');
assert.ok(legacy,'Expected a measured main-side comparison');
assert.ok(masonry.blank_ratio<legacy.blank_ratio/2,'Empty area did not materially improve');
assert.ok(masonry.page_count<=legacy.page_count,'Composition added pages');

const withImage=render('with-image',generated.replace('</div></main>',`<section class="content-panel"><h2 class="category-title">等比原图</h2><article class="topic">${block('image/1','原图','640 × 320 虚构图片',`<img class="source-image" src="${image}">`)}</article></section></div></main>`));
assert.equal(withImage.source_images.length,1);
assert.equal(withImage.source_coverage.expected_unique_sources,25);
assert.equal(withImage.topic_integrity.fragmented_topics,0);

const reading=render('reading',generated.replace('data-layout="collage"','data-presentation="reading" data-layout="collage"'));
assert.equal(reading.layout_mode,'ordered-two');
assert.equal(reading.reading_order.sequential,true,'Reading topics moved backwards across lanes/pages');
assert.equal(reading.source_coverage.expected_unique_sources,24);
assert.equal(reading.topic_integrity.fragmented_topics,0,'A small reading topic was fragmented');
assert.ok(reading.blank_ratio<0.15,'The final reading page was not balanced');

const board=render('board',generated.replace('data-layout="collage"','data-layout="board"'));
assert.equal(board.layout_mode,'board');
assert.ok(board.dimensions.every(box=>box.width===3200));
const qa=render('qa',shell(questions,'qa'));
assert.equal(qa.layout_mode,'single');
assert.ok(qa.dimensions.every(box=>box.width===1080));
assert.equal(qa.source_coverage.expected_unique_sources,18);
assert.equal(qa.topic_integrity.fragmented_topics,0,'Mobile pages separated a small question from its answer');

console.log(JSON.stringify({directory,masonry,with_image:withImage,reading,board:{page_count:board.page_count,source_coverage:board.source_coverage},qa:{page_count:qa.page_count,source_coverage:qa.source_coverage}},null,2));
