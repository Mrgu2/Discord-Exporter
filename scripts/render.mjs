#!/usr/bin/env node
// Render semantic manuscript layouts directly at 2x device-pixel density.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { writePngGrid } from './png.mjs';

const require = createRequire(import.meta.url);
const input = path.resolve(process.argv[2] || '');
const output = path.resolve(process.argv[3] || path.dirname(input));
const RENDER_SCALE = Number(process.argv[4] || 2);
const WIDTH = 1080, MAX_HEIGHT = 3600, MAX_CANVAS_WIDTH = 32000, MAX_CANVAS_PIXELS = 80_000_000;

async function loadPlaywright() {
  const candidates = [process.env.PLAYWRIGHT_MODULE,
    path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js')].filter(Boolean);
  try { return require('playwright'); } catch {}
  for (const candidate of candidates) {
    try { const loaded=await import(pathToFileURL(candidate).href); return loaded.default || loaded; } catch {}
  }
  throw new Error('缺少 Playwright。请在工具目录运行 npm install playwright，然后运行 npx playwright install chromium。');
}

async function main() {
  if (![1,2].includes(RENDER_SCALE)) throw new Error('导出倍率仅支持 1× 或 2× HiDPI。');
  if (!fs.statSync(input).isFile()) throw new Error('稿件 HTML 不存在。');
  fs.mkdirSync(output, { recursive: true });
  const playwright = await loadPlaywright();
  const executables = [process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'].filter(Boolean);
  const executablePath = executables.find(candidate => fs.existsSync(candidate));
  const browser = await playwright.chromium.launch({headless:true, ...(executablePath ? {executablePath} : {})});
  try {
    const page = await browser.newPage({viewport:{width:3200,height:MAX_HEIGHT},deviceScaleFactor:RENDER_SCALE});
    await page.route('**/*', route => /^(file:|data:)/.test(route.request().url()) ? route.continue() : route.abort());
    await page.goto(pathToFileURL(input).href, {waitUntil:'load'});
    // Apply the current export design to new and previously saved manuscripts,
    // without rewriting their source HTML, Markdown or evidence files.
    await page.addStyleTag({content: fs.readFileSync(new URL('../web/manuscript.css', import.meta.url), 'utf8')+'\n.audio-playback{display:none!important}'});
    await page.evaluate(async () => {
      for(const image of document.querySelectorAll('img[data-local-src]')) image.src=new URL(image.dataset.localSrc,location.href).href;
      await Promise.all([...document.images].map(image=>image.complete ? Promise.resolve() : new Promise(resolve=>{image.onload=resolve;image.onerror=resolve;})));
      if([...document.images].some(image=>!image.naturalWidth))throw new Error('本地图像读取失败，不能生成含原图的完整长图。');
      await document.fonts.ready;
      for(const meta of document.querySelectorAll('[data-render-meta]')) {
        // Older manuscripts used the complete local ID only in readable text.
        // Retain that ID before applying the compact image caption, so the
        // source-completeness check also covers those saved manuscripts.
        if(!meta.dataset.evidenceId) {
          const local=meta.textContent.match(/本地证据\s+([^\s]+\/[^\s]+)/);
          if(local) meta.dataset.evidenceId=local[1];
        }
        meta.textContent=meta.dataset.renderMeta;
      }
    });
    const rendered = await page.evaluate(({WIDTH,MAX_HEIGHT,MAX_CANVAS_WIDTH,MAX_CANVAS_PIXELS}) => {
      const original = document.querySelector('#manuscript');
      if (!original) throw new Error('稿件缺少 manuscript 节点。');
      const title = original.querySelector('h1').textContent;
      const subtitle = original.querySelector('.document-meta')?.textContent || '';
      const sourcePanels = [...original.querySelectorAll('.panel-grid > .content-panel')];
      if(sourcePanels.length) {
        const stacked=document.body.dataset.layout==='stacked',horizontal=document.body.dataset.layout==='horizontal';
        const flowPanels=stacked||horizontal?[...sourcePanels.filter(panel=>panel.dataset.kind==='feed'),...sourcePanels.filter(panel=>panel.dataset.kind!=='feed')]:sourcePanels;
        let topicOrder=0;
        for(const panel of flowPanels)for(const topic of panel.querySelectorAll(':scope > .topic:not([data-archive-warnings])'))topic.dataset.topicOrder=String(topicOrder++);
        for(const topic of original.querySelectorAll('[data-archive-warnings]'))topic.dataset.topicOrder=String(topicOrder++);
        const measurement=document.createElement('div');
        measurement.style.cssText='position:absolute;left:-10000px;top:0;width:1080px;visibility:hidden';
        document.body.append(measurement);
        const measured=sourcePanels.map((panel,index)=>{
          const copy=panel.cloneNode(true);copy.style.width='1080px';measurement.append(copy);
          const height=Math.ceil(copy.getBoundingClientRect().height);copy.remove();return {index,height};
        });
        measurement.remove();
        const descending=[...measured].sort((a,b)=>b.height-a.height);
        const total=measured.reduce((sum,item)=>sum+item.height,0);
        const board=document.body.dataset.layout==='board';
        let mode,width,assignments;
        if(board){mode='board';width=3200;assignments=sourcePanels.map((_,index)=>[index]);}
        else if(sourcePanels.length===1){mode='single';width=1080;assignments=[[0]];}
        else if(descending[0].height>=1.6*descending[1].height && descending[0].height/total>=0.52){
          mode='main-side';width=2880;const main=descending[0].index;assignments=[[main],sourcePanels.map((_,index)=>index).filter(index=>index!==main)];
        }else{
          mode='balanced-two';width=2160;assignments=[[],[]];const loads=[0,0];
          for(const item of measured){const lane=loads[0]<=loads[1]?0:1;assignments[lane].push(item.index);loads[lane]+=item.height;}
        }
        const holder=document.createElement('div');holder.id='render-pages';document.body.append(holder);original.style.display='none';
        const titleFor=panel=>sourcePanels[panel].querySelector(':scope > .category-title').textContent;
        const panelEntries=panel=>[...sourcePanels[panel].querySelectorAll(':scope > .topic')].map(element=>({panel,element:element.cloneNode(true)}));
        if(stacked || horizontal) {
          const feeds=sourcePanels.map((panel,index)=>panel.dataset.kind==='feed'?index:null).filter(index=>index!==null);
          const questions=sourcePanels.map((panel,index)=>panel.dataset.kind!=='feed'?index:null).filter(index=>index!==null);
          const qaEntries=questions.flatMap(panelEntries).filter(entry=>!entry.element.hasAttribute('data-archive-warnings'));
          const columns=Math.min(4,Math.max(feeds.length,Math.ceil(qaEntries.length/6),1));
          const columnWidth=1002,gutter=36,bandGap=48;
          let width=120+columns*columnWidth+(columns-1)*gutter;
          const canvas=document.createElement('div');canvas.className='render-page composition-page '+(horizontal?'side-by-side-page':'stacked-page');canvas.style.width=width+'px';
          const heading=document.createElement('div');heading.className='page-heading';heading.textContent=title;
          const sub=document.createElement('div');sub.className='page-subtitle';sub.textContent=subtitle;
          canvas.append(heading,sub);holder.append(canvas);
          const bandHolder=horizontal?document.createElement('div'):canvas;
          if(horizontal){bandHolder.className='side-by-side-bands';bandHolder.style.cssText='display:flex;gap:48px;align-items:flex-start';canvas.append(bandHolder);}
          const models=[];
          const prepareBand=(kind,entries,sharedTitle=false)=>{
            if(!entries.length)return;
            const band=document.createElement('section');band.className='stacked-band';band.dataset.bandKind=kind;band.style.flex='none';
            const row=document.createElement('div');row.className='composition-lanes';band.append(row);bandHolder.append(band);
            if(sharedTitle){const h2=document.createElement('h2');h2.className='category-title';h2.textContent=titleFor(entries[0].panel);band.prepend(h2);}
            const probe=document.createElement('section');probe.className='content-panel';
            const measure=document.createElement('div');measure.className='composition-lane';measure.style.width=columnWidth+'px';measure.append(probe);row.append(measure);
            const weights=entries.map(entry=>{
              const copy=entry.element.cloneNode(true);probe.append(copy);
              const weight=copy.getBoundingClientRect().height+parseFloat(getComputedStyle(copy).marginBottom);
              copy.remove();return weight;
            });measure.remove();models.push({kind,band,row,entries,weights,sharedTitle});
          };
          const populate=(model,count)=>{
            const {band,row,entries,weights,sharedTitle}=model;
            row.replaceChildren();row.style.gridTemplateColumns=`repeat(${count},minmax(0,1fr))`;
            band.style.width=(count*columnWidth+(count-1)*gutter)+'px';
            const target=Math.min(count,entries.length);
            const partition=limit=>{
              const parts=[[]];let load=0;
              entries.forEach((entry,index)=>{
                if(parts.at(-1).length && (load+weights[index]>limit || entries.length-index===target-parts.length)){parts.push([]);load=0;}
                parts.at(-1).push(entry);load+=weights[index];
              });return parts;
            };
            let low=Math.max(...weights),high=weights.reduce((sum,value)=>sum+value,0);
            while(high-low>1){const middle=(low+high)/2;if(partition(middle).length>target)low=middle;else high=middle;}
            const parts=partition(high),seen=new Set();
            for(const part of parts) {
              const lane=document.createElement('div');lane.className='composition-lane';row.append(lane);
              let section,identity;
              for(const entry of part) {
                if(identity!==entry.panel) {
                  section=document.createElement('section');section.className='content-panel';identity=entry.panel;
                  if(!sharedTitle){const h2=document.createElement('h2');h2.className='category-title';h2.textContent=titleFor(identity)+(seen.has(identity)?'（续）':'');section.append(h2);}
                  lane.append(section);seen.add(identity);
                }
                section.append(entry.element.cloneNode(true));
              }
            }
            const box=band.getBoundingClientRect(),heights=[...row.children].map(lane=>lane.getBoundingClientRect().height);
            const tallest=Math.max(...heights);
            return {count,width:Math.ceil(box.width),height:Math.ceil(box.height),blank:tallest?1-heights.reduce((sum,value)=>sum+value,0)/(count*tallest):0};
          };
          prepareBand('feed',feeds.flatMap(panelEntries).filter(entry=>!entry.element.hasAttribute('data-archive-warnings')));
          prepareBand('qa',qaEntries,questions.length===1);
          if(horizontal && models.length) {
            // Keep the two semantic sections beside each other. Allocate each
            // section its own consecutive columns and balance their heights.
            const options=models.map(model=>Array.from({length:Math.min(8,model.entries.length)},(_,index)=>populate(model,index+1)));
            const headerHeight=Math.ceil(heading.getBoundingClientRect().height+sub.getBoundingClientRect().height)+100;
            let best;
            for(const left of options[0])for(const right of options[1]||[null]) {
              const chosen=right?[left,right]:[left],candidateWidth=120+chosen.reduce((sum,item)=>sum+item.width,0)+(chosen.length-1)*bandGap;
              const candidateHeight=headerHeight+Math.max(...chosen.map(item=>item.height));
              if(candidateWidth>MAX_CANVAS_WIDTH || candidateHeight>MAX_CANVAS_WIDTH || candidateWidth*candidateHeight>MAX_CANVAS_PIXELS)continue;
              const imbalance=right?Math.abs(Math.log(left.height/right.height)):0;
              const score=Math.abs(Math.log((candidateWidth/candidateHeight)/1.6))+0.35*imbalance+0.6*chosen.reduce((sum,item)=>sum+item.blank,0)+0.002*chosen.reduce((sum,item)=>sum+item.count,0);
              if(!best || score<best.score)best={score,chosen,width:candidateWidth};
            }
            if(!best)throw new Error('横向长图超过单图尺寸限制，请缩小日期范围后重试。');
            width=best.width;canvas.style.width=width+'px';models.forEach((model,index)=>populate(model,best.chosen[index].count));
          }else models.forEach(model=>populate(model,columns));
          const notice=original.querySelector('[data-archive-warnings]');
          if(notice){const copy=notice.cloneNode(true);copy.classList.add('archive-notice');canvas.append(copy);}
          const height=Math.ceil(canvas.getBoundingClientRect().height);
          if(height>MAX_CANVAS_WIDTH || width*height>MAX_CANVAS_PIXELS)throw new Error((horizontal?'横向长图':'上下分区拼图')+'超过单图尺寸限制，请缩小日期范围后重试。');
          let usedArea=0,totalArea=0;
          for(const {band} of models){const boxes=[...band.querySelectorAll('.composition-lane')].map(lane=>lane.getBoundingClientRect());const tallest=Math.max(...boxes.map(box=>box.height));usedArea+=boxes.reduce((sum,box)=>sum+box.width*box.height,0);totalArea+=boxes.reduce((sum,box)=>sum+box.width*tallest,0);}
          return {count:1,width,layout_mode:horizontal?'horizontal':'stacked',panel_heights:measured,column_width:columnWidth,blank_ratio:totalArea?Math.max(0,1-usedArea/totalArea):0,
            horizontal_columns:horizontal?models.reduce((sum,model)=>sum+model.row.children.length,0):undefined,
            bands:models.map(({band})=>({kind:band.dataset.bandKind,columns:band.querySelectorAll('.composition-lane').length,
              x:Math.round(band.getBoundingClientRect().x-canvas.getBoundingClientRect().x),y:Math.round(band.getBoundingClientRect().y-canvas.getBoundingClientRect().y),
              width:Math.round(band.getBoundingClientRect().width),height:Math.ceil(band.getBoundingClientRect().height)}))};
        }
        const ordered= (document.body.dataset.presentation==='reading' && !board && sourcePanels.length>1);
        const candidates=ordered?[{mode:'ordered-two',width:2160,queues:[sourcePanels.flatMap((_,index)=>panelEntries(index))]}]:[{mode,width,queues:assignments.map(indices=>indices.flatMap(panelEntries))}];
        if(!ordered && !board && sourcePanels.length>1 && sourcePanels[descending[0].index].querySelectorAll(':scope > .topic').length>1) {
          // Measure complete question/answer topics at their real output width.
          // A large panel may occupy both lanes; short panels stay consecutive
          // in one lane rather than leaving an almost empty sidebar.
          const stage=document.createElement('div');stage.className='render-page composition-page';stage.style.cssText='position:absolute;left:-10000px;top:0;width:2160px;visibility:hidden';
          const row=document.createElement('div');row.className='composition-lanes';row.style.gridTemplateColumns='repeat(2,minmax(0,1fr))';stage.append(row);
          const lanes=[0,1].map(()=>{const lane=document.createElement('div');lane.className='composition-lane';row.append(lane);return lane;});
          document.body.append(stage);
          const masonry=[[],[]],dominant=descending[0].index;
          const sections=[null,null],lastPanels=[null,null],placedPanels=new Set();
          for(let panel=0;panel<sourcePanels.length;panel++) {
            const entries=panelEntries(panel);
            const units=panel===dominant?entries.map(entry=>[entry]):[entries];
            for(const unit of units) {
              if(!unit.length)continue;
              const laneIndex=lanes[0].getBoundingClientRect().height<=lanes[1].getBoundingClientRect().height?0:1;
              if(lastPanels[laneIndex]!==panel) {
                const section=document.createElement('section');section.className='content-panel';
                const heading=document.createElement('h2');heading.className='category-title';heading.textContent=titleFor(panel)+(placedPanels.has(panel)?'（续）':'');
                section.append(heading);lanes[laneIndex].append(section);sections[laneIndex]=section;lastPanels[laneIndex]=panel;
              }
              for(const entry of unit) {sections[laneIndex].append(entry.element.cloneNode(true));masonry[laneIndex].push(entry);}
              placedPanels.add(panel);
            }
          }
          stage.remove();
          candidates.push({mode:'masonry-two',width:2160,queues:masonry});
        }
        function renderCandidate(candidate) {
        const {mode,width}=candidate;
        const copied=candidate.queues.map(queue=>queue.map(entry=>({panel:entry.panel,element:entry.element.cloneNode(true)})));
        // Read down the left lane, then the right lane, then the next page.
        // Both lanes consume one queue so shorter topics cannot jump ahead.
        const queues=mode==='ordered-two'?[copied[0],copied[0]]:copied;
        const pages=[],seenPanels=new Set();
        function createPage(){
          const container=document.createElement('div');container.className='render-page composition-page';container.style.width=width+'px';
          const heading=document.createElement('div');heading.className='page-heading';heading.textContent=title;
          const sub=document.createElement('div');sub.className='page-subtitle';sub.textContent=subtitle;
          const row=document.createElement('div');row.className='composition-lanes';row.style.gridTemplateColumns=mode==='main-side'?'minmax(0,2fr) minmax(0,1fr)':`repeat(${queues.length},minmax(0,1fr))`;
          const lanes=queues.map(()=>{const lane=document.createElement('div');lane.className='composition-lane';row.append(lane);return lane;});
          const footer=document.createElement('div');footer.className='page-footer';footer.innerHTML='<span>原文与原图 · 本地归档</span><span class="page-number"></span>';
          container.append(heading,sub,row,footer);holder.append(container);pages.push(container);
          const available=MAX_HEIGHT-(container.getBoundingClientRect().height-row.getBoundingClientRect().height);
          return {container,lanes,available};
        }
        const continuationTitle=topic=>{const heading=topic.querySelector(':scope > h2');if(heading&&!heading.textContent.endsWith('（续）'))heading.textContent+='（续）';};
        let safety=0;
        while(queues.some(queue=>queue.length)){
          if(++safety>1000)throw new Error('稿件分页数量异常。');
          const {container,lanes,available}=createPage();let progress=false;
          queues.forEach((queue,laneIndex)=>{
            const lane=lanes[laneIndex];let panelSection=null,panelIdentity=null;
            while(queue.length){
              const entry=queue[0];
              if(entry.panel!==panelIdentity){
                panelSection=document.createElement('section');panelSection.className='content-panel';
                panelSection.dataset.panelIndex=String(entry.panel);
                const h2=document.createElement('h2');h2.className='category-title';h2.textContent=titleFor(entry.panel)+(seenPanels.has(entry.panel)?'（续）':'');
                panelSection.append(h2);lane.append(panelSection);panelIdentity=entry.panel;
              }
              const existing=lane.querySelectorAll('.topic').length;
              const clone=entry.element.cloneNode(true);panelSection.append(clone);
              if(Math.ceil(lane.getBoundingClientRect().height)<=Math.floor(available)){
                queue.shift();seenPanels.add(entry.panel);progress=true;continue;
              }
              clone.remove();
              if(existing){if(!panelSection.querySelector('.topic'))panelSection.remove();break;}
              panelSection.append(clone);
              const blocks=[...clone.querySelectorAll(':scope > [data-segment]')];
              if(blocks.length>1){
                clone.remove();
                const split=[];
                // Keep the original question and first answer together when
                // that pair fits; only an oversized topic may be continued.
                let firstCount=Math.min(2,blocks.length);
                const first=entry.element.cloneNode(true);
                [...first.querySelectorAll(':scope > [data-segment]')].slice(firstCount).forEach(node=>node.remove());
                panelSection.append(first);
                if(Math.ceil(lane.getBoundingClientRect().height)>Math.floor(available))firstCount=1;
                first.remove();
                for(let start=0;start<blocks.length;){
                  const count=start===0?firstCount:1;
                  const fragment=entry.element.cloneNode(true);
                  [...fragment.querySelectorAll(':scope > [data-segment]')].forEach((block,index)=>{if(index<start||index>=start+count)block.remove();});
                  if(start)continuationTitle(fragment);split.push({panel:entry.panel,element:fragment});start+=count;
                }
                queue.splice(0,1,...split);continue;
              }
              const text=clone.querySelector('.message-text');
              if(!text)throw new Error('单个问答或图片过高，无法按语义分页。');
              const characters=Array.from(text.textContent);let low=1,high=characters.length,best=0;
              while(low<=high){const middle=Math.floor((low+high)/2);text.textContent=characters.slice(0,middle).join('');if(Math.ceil(lane.getBoundingClientRect().height)<=Math.floor(available)){best=middle;low=middle+1;}else high=middle-1;}
              if(!best)throw new Error('单条来源信息或图片超过页面高度。');
              const preferred=characters.slice(0,best).map((character,index)=>/[\n。！？.!?]/.test(character)?index+1:0).filter(index=>index>best*0.5).pop();
              const cut=preferred||best;text.textContent=characters.slice(0,cut).join('');
              const remainder=entry.element.cloneNode(true);remainder.querySelector('.message-text').textContent=characters.slice(cut).join('');continuationTitle(remainder);
              const label=remainder.querySelector('.block-label');if(label&&!label.textContent.endsWith('（续）'))label.textContent+='（续）';
              if(cut<characters.length)queue[0]={panel:entry.panel,element:remainder};else queue.shift();
              seenPanels.add(entry.panel);progress=true;break;
            }
          });
          if(!progress)throw new Error('内容无法放入页面。');
          if(Math.ceil(container.getBoundingClientRect().height)>MAX_HEIGHT)throw new Error('拼版高度超出限制。');
        }
        if(mode==='ordered-two') {
          // Balance each page by moving complete consecutive topics;
          // never shrink text, stretch an image, or shuffle the reading order.
          for(const [pageIndex,last] of pages.entries()) {
          const lanes=[...last.querySelectorAll('.composition-lane')];
          const entries=lanes.flatMap(lane=>[...lane.querySelectorAll('.topic')].map(element=>({panel:Number(element.closest('.content-panel').dataset.panelIndex),element:element.cloneNode(true)})));
          const earlier=new Set(pages.slice(0,pageIndex).flatMap(element=>[...element.querySelectorAll('[data-panel-index]')].map(section=>Number(section.dataset.panelIndex))));
          const available=MAX_HEIGHT-(last.getBoundingClientRect().height-last.querySelector('.composition-lanes').getBoundingClientRect().height);
          const populate=split=>{
            const placed=new Set(earlier);
            lanes.forEach((lane,index)=>{
              lane.replaceChildren();let section,identity;
              for(const entry of (index===0?entries.slice(0,split):entries.slice(split))) {
                if(identity!==entry.panel) {
                  section=document.createElement('section');section.className='content-panel';section.dataset.panelIndex=String(entry.panel);
                  const heading=document.createElement('h2');heading.className='category-title';heading.textContent=titleFor(entry.panel)+(placed.has(entry.panel)?'（续）':'');
                  section.append(heading);lane.append(section);identity=entry.panel;
                }
                section.append(entry.element.cloneNode(true));placed.add(entry.panel);
              }
            });
            return Math.max(...lanes.map(lane=>Math.ceil(lane.getBoundingClientRect().height)));
          };
          if(entries.length>1) {
            let split=lanes[0].querySelectorAll('.topic').length,best=populate(split);
            for(let point=1;point<entries.length;point++) {
              const height=populate(point);
              if(height<=Math.floor(available) && height<best){best=height;split=point;}
            }
            populate(split);
          }
          }
        }
        pages.forEach((element,index)=>element.querySelector('.page-number').textContent=`${String(index+1).padStart(2,'0')} / ${String(pages.length).padStart(2,'0')}`);
        let usedArea=0,totalArea=0;
        const laneHeights=pages.map(element=>{
          const lanes=[...element.querySelectorAll('.composition-lane')].map(lane=>lane.getBoundingClientRect());
          const tallest=Math.max(...lanes.map(lane=>lane.height));
          usedArea+=lanes.reduce((sum,lane)=>sum+lane.width*lane.height,0);
          totalArea+=lanes.reduce((sum,lane)=>sum+lane.width*tallest,0);
          return lanes.map(lane=>Math.ceil(lane.height));
        });
        return {pages,width,mode,blank_ratio:totalArea?Math.max(0,1-usedArea/totalArea):0,lane_heights:laneHeights};
        }
        const choices=[];
        let candidateError;
        for(const candidate of candidates) {
          const before=new Set(holder.children);
          try { choices.push(renderCandidate(candidate)); }
          catch(error) {
            for(const element of [...holder.children])if(!before.has(element))element.remove();
            candidateError ||= error;
          }
        }
        if(!choices.length)throw candidateError || new Error('没有可用的拼版布局。');
        choices.sort((a,b)=>a.blank_ratio-b.blank_ratio || a.pages.length-b.pages.length);
        const best=choices[0];
        for(const choice of choices.slice(1))for(const element of choice.pages)element.remove();
        return {count:best.pages.length,width:best.width,layout_mode:best.mode,panel_heights:measured,
          blank_ratio:best.blank_ratio,lane_heights:best.lane_heights,
          layout_candidates:choices.map(choice=>({mode:choice.mode,page_count:choice.pages.length,blank_ratio:choice.blank_ratio,lane_heights:choice.lane_heights}))};
      }
      const topics = [...original.querySelectorAll(':scope > .topic')];
      topics.forEach((topic,index)=>topic.dataset.topicOrder=String(index));
      const holder = document.createElement('div');
      holder.id = 'render-pages';
      document.body.append(holder);
      original.style.display = 'none';
      document.body.style.margin = '0';
      let current, body, footer;
      const pages = [];
      function newPage() {
        current = document.createElement('div');
        current.className = 'render-page';
        current.style.width = WIDTH+'px';
        const header = document.createElement('div');
        const heading = document.createElement('div'); heading.className='page-heading'; heading.textContent=title;
        const sub = document.createElement('div'); sub.className='page-subtitle'; sub.textContent=subtitle;
        header.append(heading,sub);
        body = document.createElement('div'); body.className='page-body';
        footer = document.createElement('div'); footer.className='page-footer';
        const caption = document.createElement('span'); caption.textContent='依据本地归档整理 · 保留原话与出处';
        const number = document.createElement('span'); number.className='page-number'; number.textContent=String(pages.length+1);
        footer.append(caption,number); current.append(header,body,footer);holder.append(current);pages.push(current);
      }
      const height = () => Math.ceil(current.getBoundingClientRect().height);
      const hasContent = () => body.querySelector('[data-segment]') !== null;
      newPage();
      for (const originalTopic of topics) {
        const priorContent=hasContent(),probe=originalTopic.cloneNode(true);
        body.append(probe);
        const fitsCurrent=height()<=MAX_HEIGHT;
        const available=MAX_HEIGHT-(current.getBoundingClientRect().height-body.getBoundingClientRect().height);
        const topicHeight=probe.getBoundingClientRect().height;
        probe.remove();
        if(priorContent && !fitsCurrent && topicHeight<=available)newPage();
        const heading = originalTopic.querySelector('h2').textContent;
        const queue = [...originalTopic.querySelectorAll(':scope > [data-segment]')].map(element => element.cloneNode(true));
        let placed = false, topic;
        function topicOnPage() {
          topic = document.createElement('article'); topic.className='topic';
          topic.dataset.topicOrder=originalTopic.dataset.topicOrder;
          const h2 = document.createElement('h2'); h2.textContent=heading+(placed ? '（续）' : '');
          topic.append(h2);body.append(topic);
        }
        topicOnPage();
        while (queue.length) {
          let block = queue.shift();
          topic.append(block);
          if (height() <= MAX_HEIGHT) { placed=true; continue; }
          block.remove();
          if (!topic.querySelector('[data-segment]')) topic.remove();
          if (hasContent()) { newPage(); topicOnPage(); topic.append(block); }
          else { if (!topic.isConnected) topicOnPage(); topic.append(block); }
          if (height() <= MAX_HEIGHT) { placed=true; continue; }
          const text = block.querySelector('.message-text');
          if (!text) throw new Error('章节过高且无法按文字拆分。');
          const characters = Array.from(text.textContent);
          const fullText = text.textContent;
          let low=1,high=characters.length,best=0;
          while (low<=high) {
            const middle=Math.floor((low+high)/2);
            text.textContent=characters.slice(0,middle).join('');
            if (height()<=MAX_HEIGHT) {best=middle;low=middle+1;} else high=middle-1;
          }
          if (!best) throw new Error('页面标题或来源信息过长，无法生成长图。');
          const preferred = characters.slice(0,best).map((character,index) => /[\n。！？.!?]/.test(character) ? index+1 : 0).filter(index=>index>best*0.5).pop();
          const cut = preferred || best;
          text.textContent=characters.slice(0,cut).join('');
          const continuation=block.cloneNode(true);
          continuation.querySelector('.message-text').textContent=characters.slice(cut).join('');
          const label=continuation.querySelector('.block-label');
          if (label && !label.textContent.endsWith('（续）')) label.textContent+='（续）';
          if (cut<characters.length) queue.unshift(continuation);
          placed=true;
          if (fullText.length && height()>MAX_HEIGHT) throw new Error('文字分页后仍超出高度限制。');
        }
      }
      pages.forEach((element,index) => {
        element.querySelector('.page-number').textContent=`${String(index+1).padStart(2,'0')} / ${String(pages.length).padStart(2,'0')}`;
        if (Math.ceil(element.getBoundingClientRect().height)>MAX_HEIGHT) throw new Error('分页高度超出限制。');
      });
      return {count:pages.length,width:WIDTH,layout_mode:'single'};
    }, {WIDTH,MAX_HEIGHT,MAX_CANVAS_WIDTH,MAX_CANVAS_PIXELS});
    const verification=await page.evaluate(async()=>{
      const images=[...document.querySelectorAll('#render-pages img')];
      await Promise.all(images.map(image=>image.complete?Promise.resolve():new Promise(resolve=>{image.onload=resolve;image.onerror=resolve;})));
      const expectedImages=new Set([...document.querySelectorAll('#manuscript img')].map(image=>image.src));
      const renderedImages=new Set(images.map(image=>image.src));
      const missingImages=[...expectedImages].filter(source=>!renderedImages.has(source));
      if(missingImages.length||images.some(image=>!image.naturalWidth||!image.getBoundingClientRect().width||!image.getBoundingClientRect().height))throw new Error('拼版有图片未能完整呈现，停止导出。');
      const expected=new Set([...document.querySelectorAll('#manuscript [data-evidence-id]')].map(element=>element.dataset.evidenceId));
      const actual=new Set([...document.querySelectorAll('#render-pages [data-evidence-id]')].map(element=>element.dataset.evidenceId));
      const missing=[...expected].filter(identity=>!actual.has(identity));
      if(missing.length)throw new Error(`拼版遗漏了 ${missing.length} 条来源消息，停止导出。`);
      const originalFonts=new Set([...document.querySelectorAll('#manuscript .message-text')].map(element=>getComputedStyle(element).fontSize));
      const renderedFonts=new Set([...document.querySelectorAll('#render-pages .message-text')].map(element=>getComputedStyle(element).fontSize));
      if([...renderedFonts].some(size=>!originalFonts.has(size)))throw new Error('拼版改变了原文正文字号，停止导出。');
      const ids=topic=>new Set([...topic.querySelectorAll('[data-evidence-id]')].map(element=>element.dataset.evidenceId));
      const originalTopics=[...document.querySelectorAll('#manuscript .content-panel > .topic, #manuscript > .topic')].filter(topic=>ids(topic).size);
      const renderedTopics=[...document.querySelectorAll('#render-pages .content-panel > .topic, #render-pages .page-body > .topic')];
      const intactTopics=originalTopics.filter(topic=>renderedTopics.filter(rendered=>rendered.dataset.topicOrder===topic.dataset.topicOrder).length===1).length;
      const textTotals=selector=>{
        const totals=new Map();
        for(const paragraph of document.querySelectorAll(selector)) {
          const identity=paragraph.closest('[data-evidence-id]')?.dataset.evidenceId||'__note__';
          totals.set(identity,(totals.get(identity)||'')+paragraph.textContent);
        }
        return new Map([...totals].map(([identity,text])=>[identity,Array.from(text).sort().join('')]));
      };
      const originalText=textTotals('#manuscript .message-text'),renderedText=textTotals('#render-pages .message-text');
      const mismatchedText=[...new Set([...originalText.keys(),...renderedText.keys()])].filter(identity=>originalText.get(identity)!==renderedText.get(identity));
      if(mismatchedText.length)throw new Error('拼版正文有遗漏或重复，停止导出。');
      const readingOrder=[...document.querySelectorAll('#render-pages [data-topic-order]')].map(topic=>Number(topic.dataset.topicOrder));
      const sequential=readingOrder.every((value,index)=>!index||value>=readingOrder[index-1]);
      if(((document.body.dataset.presentation==='reading' && document.body.dataset.layout!=='board') || document.body.dataset.layout==='horizontal') && !sequential)throw new Error('阅读版主题顺序发生倒退，停止导出。');
      return {source_images:images.map(image=>({natural_width:image.naturalWidth,natural_height:image.naturalHeight,width:image.getBoundingClientRect().width,height:image.getBoundingClientRect().height})),
        reading_order:{sequential,topic_fragments:readingOrder.length},
        structure:{headings:document.querySelectorAll('#render-pages .page-heading').length,footers:document.querySelectorAll('#render-pages .page-footer').length,columns:document.querySelectorAll('#render-pages .composition-lane').length},
        text_coverage:{expected_characters:[...originalText.values()].reduce((sum,text)=>sum+Array.from(text).length,0),rendered_characters:[...renderedText.values()].reduce((sum,text)=>sum+Array.from(text).length,0),mismatched_sources:mismatchedText.length},
        image_coverage:{expected_unique_images:expectedImages.size,rendered_unique_images:renderedImages.size,missing:missingImages.length},
        topic_integrity:{expected_topics:originalTopics.length,intact_topics:intactTopics,fragmented_topics:originalTopics.length-intactTopics},
        body_font_sizes:[...renderedFonts],
        source_coverage:{expected_unique_sources:expected.size,rendered_unique_sources:actual.size,missing:missing.length}};
    });
    const images=[],dimensions=[],cssDimensions=[],rasterTiles=[];
    const boxes=[];
    for(let index=0;index<rendered.count;index++) {
      const box=await page.locator('.render-page').nth(index).boundingBox();
      const width=Math.round(box.width),height=Math.ceil(box.height);
      if(width*RENDER_SCALE>64000 || height*RENDER_SCALE>64000 || width*height*RENDER_SCALE**2>320_000_000)throw new Error('HiDPI 高清图超过单图尺寸限制，请缩小日期范围后重试。');
      boxes.push({width,height});
    }
    for(let index=0;index<rendered.count;index++) {
      const locator=page.locator('.render-page').nth(index),{width,height}=boxes[index];
      const filename=path.join(output,`long-${String(index+1).padStart(2,'0')}.png`);
      await locator.evaluate(element=>{
        const frame=document.createElement('div');frame.id='raster-frame';frame.style.cssText='position:absolute;left:0;top:0;overflow:hidden;background:white;z-index:1000';
        element.before(frame);frame.append(element);element.style.position='relative';element.style.margin='0';
      });
      // Rasterize the DOM at the output density. Each captured device-pixel
      // tile stays <=4096px; the final image is streamed without a full raw canvas.
      const tiles=[],tileSize=4096/RENDER_SCALE;
      for(let y=0;y<height;y+=tileSize)for(let x=0;x<width;x+=tileSize) {
        const tileWidth=Math.min(tileSize,width-x),tileHeight=Math.min(tileSize,height-y);
        await page.locator('#raster-frame').evaluate((frame,{x,y,width,height})=>{
          frame.style.width=width+'px';frame.style.height=height+'px';frame.firstElementChild.style.left=-x+'px';frame.firstElementChild.style.top=-y+'px';
        },{x,y,width:tileWidth,height:tileHeight});
        const tile=await page.locator('#raster-frame').screenshot({animations:'disabled',scale:'device'});
        if(tile.readUInt32BE(16)!==tileWidth*RENDER_SCALE || tile.readUInt32BE(20)!==tileHeight*RENDER_SCALE)throw new Error(`HiDPI 渲染片段尺寸异常：${tile.readUInt32BE(16)}×${tile.readUInt32BE(20)}，应为 ${tileWidth*RENDER_SCALE}×${tileHeight*RENDER_SCALE}。`);
        tiles.push({buffer:tile,x:x*RENDER_SCALE,y:y*RENDER_SCALE});
        rasterTiles.push({page:index,x:x*RENDER_SCALE,y:y*RENDER_SCALE,width:tileWidth*RENDER_SCALE,height:tileHeight*RENDER_SCALE});
      }
      await writePngGrid(tiles,width*RENDER_SCALE,height*RENDER_SCALE,filename);
      // Remove only the temporary DOM wrapper before preparing the next page.
      await page.locator('#raster-frame').evaluate(frame=>frame.replaceWith(frame.firstElementChild));
      images.push(filename);dimensions.push({width:width*RENDER_SCALE,height:height*RENDER_SCALE});cssDimensions.push({width,height});
    }
    process.stdout.write(JSON.stringify({images,dimensions,render_scale:RENDER_SCALE,css_dimensions:cssDimensions,pixel_font_sizes:verification.body_font_sizes.map(size=>`${parseFloat(size)*RENDER_SCALE}px`),page_count:rendered.count,layout_mode:rendered.layout_mode,panel_heights:rendered.panel_heights,horizontal_columns:rendered.horizontal_columns,column_width:rendered.column_width,bands:rendered.bands,
      blank_ratio:rendered.blank_ratio,lane_heights:rendered.lane_heights,layout_candidates:rendered.layout_candidates,raster_tiles:rasterTiles,...verification}));
  } finally { await browser.close(); }
}

main().catch(error => { process.stderr.write(String(error.message)+'\n'); process.exitCode=1; });
