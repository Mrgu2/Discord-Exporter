/* Local image viewer: anchored zoom, bounded drag, pinch, and native dialog focus. */
(() => {
  'use strict';
  let dialog, stage, picture, caption, percent, download, message, lastFocus, channelSelect;
  let groups = [];
  let pages = [], index = 0, scale = 1, tx = 0, ty = 0, fitWidth = 0, fitHeight = 0;
  let pointers = new Map(), gesture = null, frame = 0, generation = 0;
  const clamp = (value, lower, upper) => Math.min(upper, Math.max(lower, value));
  const distance = points => Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
  const midpoint = points => ({x:(points[0].x + points[1].x)/2,y:(points[0].y + points[1].y)/2});
  function element(tag, className, text) { const item=document.createElement(tag);if(className)item.className=className;if(text)item.textContent=text;return item; }
  function bound() {
    tx=clamp(tx,-Math.max(0,(fitWidth*scale-stage.clientWidth)/2),Math.max(0,(fitWidth*scale-stage.clientWidth)/2));
    ty=clamp(ty,-Math.max(0,(fitHeight*scale-stage.clientHeight)/2),Math.max(0,(fitHeight*scale-stage.clientHeight)/2));
  }
  function paint() {
    bound();
    if(frame)return;
    frame=requestAnimationFrame(()=>{
      frame=0;
      // Resize the image itself so the browser samples its original pixels,
      // rather than enlarging a compositor texture made for the fitted view.
      picture.style.width=fitWidth*scale+'px';picture.style.height=fitHeight*scale+'px';
      picture.style.transform=`translate(calc(-50% + ${tx}px),calc(-50% + ${ty}px))`;
      percent.textContent=`${Math.round(scale*100)}%`;
    });
  }
  function reset(fitAll=false) {
    if(!picture.naturalWidth)return;
    const ratio=Math.min((stage.clientWidth-32)/picture.naturalWidth,(stage.clientHeight-32)/picture.naturalHeight,1);
    fitWidth=Math.max(1,picture.naturalWidth*ratio);fitHeight=Math.max(1,picture.naturalHeight*ratio);
    scale=1;tx=ty=0;
    if(!fitAll && picture.naturalWidth/picture.naturalHeight>2.2) {
      // Keep the whole-image fit as scale 1, so zooming out remains possible.
      const heightRatio=Math.min((stage.clientHeight-32)/picture.naturalHeight,1);
      scale=Math.max(1,heightRatio/ratio);
      tx=Math.max(0,(fitWidth*scale-stage.clientWidth)/2);
    }
    paint();
  }
  function zoom(next, x, y) {
    if(!fitWidth)return;
    const box=stage.getBoundingClientRect();
    const px=x===undefined?0:x-box.left-box.width/2, py=y===undefined?0:y-box.top-box.height/2;
    const minimum=Math.min(1,picture.naturalWidth/(fitWidth*devicePixelRatio));
    next=clamp(next,minimum,Math.max(6,picture.naturalWidth/fitWidth));
    const factor=next/scale;tx=px-(px-tx)*factor;ty=py-(py-ty)*factor;scale=next;paint();
  }
  function showPage(next) {
    index=clamp(next,0,pages.length-1);const current=++generation;
    message.textContent='正在载入图片…';message.hidden=false;picture.style.visibility='hidden';
    caption.textContent=`${dialog.dataset.title || '长图'} · ${index+1}/${pages.length}`;
    const density=pages[index].match(/\/scale-([12])\//)?.[1];
    download.href=pages[index];download.download=density?`${dialog.dataset.title||'稿件'}-${density}x-${String(index+1).padStart(2,'0')}.png`:pages[index].split('/').pop()||'长图.png';
    picture.onload=()=>{if(current!==generation)return;message.hidden=true;picture.style.visibility='visible';reset();};
    picture.onerror=()=>{if(current===generation)message.textContent='图片暂时无法读取，可关闭后重试。';};
    picture.src=pages[index];
    dialog.querySelector('[data-action=previous]').disabled=index===0;
    dialog.querySelector('[data-action=next]').disabled=index===pages.length-1;
  }
  function create() {
    dialog=element('dialog','image-preview');dialog.setAttribute('aria-label','查看长图');
    const bar=element('div','image-preview-bar');caption=element('span','image-preview-title');bar.append(caption);
    const buttons=[['previous','上一张'],['next','下一张'],['out','−'],['in','＋'],['fit','适应屏幕'],['native','原始像素']];
    for(const [action,text] of buttons){const button=element('button','',text);button.type='button';button.dataset.action=action;button.setAttribute('aria-label',{in:'放大',out:'缩小'}[action]||text);bar.append(button);}
    percent=element('span','image-preview-status','100%');bar.append(percent);
    download=element('a','','下载');bar.append(download);
    channelSelect=element('select');channelSelect.setAttribute('aria-label','选择频道');channelSelect.hidden=true;bar.insertBefore(channelSelect,caption.nextSibling);
    channelSelect.addEventListener('change',()=>{pages=groups[Number(channelSelect.value)].images;showPage(0);});
    const close=element('button','','关闭');close.type='button';close.dataset.action='close';bar.append(close);
    stage=element('div','image-preview-stage');picture=element('img');picture.alt='生成的长图';picture.draggable=false;message=element('div','image-preview-status-message');stage.append(picture,message);
    dialog.append(bar,stage,element('div','image-preview-hint','滚轮或双指缩放 · 放大后拖动 · 双击复位 · Esc 关闭'));
    document.body.append(dialog);
    bar.addEventListener('click',event=>{const action=event.target.closest('button')?.dataset.action;if(action==='close')dialog.close();if(action==='in')zoom(scale*1.3);if(action==='out')zoom(scale/1.3);if(action==='fit')reset(true);if(action==='native'&&fitWidth){scale=picture.naturalWidth/(fitWidth*devicePixelRatio);tx=Math.max(0,(fitWidth*scale-stage.clientWidth)/2);ty=Math.max(0,(fitHeight*scale-stage.clientHeight)/2);paint();}if(action==='previous')showPage(index-1);if(action==='next')showPage(index+1);});
    stage.addEventListener('wheel',event=>{event.preventDefault();zoom(scale*Math.exp(-event.deltaY*.002),event.clientX,event.clientY);},{passive:false});
    stage.addEventListener('dblclick',event=>scale>1.05?reset(true):zoom(2,event.clientX,event.clientY));
    function begin(){const points=[...pointers.values()];gesture=points.length===1?{type:'drag',point:points[0],tx,ty,started:false}:points.length>=2?{type:'pinch',distance:Math.max(1,distance(points)),center:midpoint(points),scale}:null;}
    stage.addEventListener('pointerdown',event=>{if(event.button!==0&&event.pointerType==='mouse')return;stage.setPointerCapture(event.pointerId);pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});begin();});
    stage.addEventListener('pointermove',event=>{if(!pointers.has(event.pointerId))return;pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});const points=[...pointers.values()];if(gesture?.type==='pinch'&&points.length>=2){const center=midpoint(points);zoom(gesture.scale*distance(points)/gesture.distance,center.x,center.y);}else if(gesture?.type==='drag'&&points.length===1){const dx=points[0].x-gesture.point.x,dy=points[0].y-gesture.point.y;if(!gesture.started&&Math.hypot(dx,dy)<4)return;gesture.started=true;stage.classList.add('is-dragging');tx=gesture.tx+dx;ty=gesture.ty+dy;paint();}});
    function end(event){pointers.delete(event.pointerId);stage.classList.remove('is-dragging');begin();}
    stage.addEventListener('pointerup',end);stage.addEventListener('pointercancel',end);
    dialog.addEventListener('keydown',event=>{
      if(event.key==='ArrowLeft'||event.key==='ArrowRight') {
        event.preventDefault();
        const direction=event.key==='ArrowRight'?1:-1;
        if(pages.length===1 && picture.naturalWidth/picture.naturalHeight>2.2) {tx-=direction*stage.clientWidth*.75;paint();}
        else showPage(index+direction);
      }
      if(event.key==='+'||event.key==='='){event.preventDefault();zoom(scale*1.3);}
      if(event.key==='-'){event.preventDefault();zoom(scale/1.3);}
      if(event.key==='0'){event.preventDefault();reset(true);}
    });
    dialog.addEventListener('close',()=>{if(dialog.open)return;pointers.clear();gesture=null;generation++;picture.removeAttribute('src');lastFocus?.focus();});
    new ResizeObserver(()=>{if(dialog.open)reset();}).observe(stage);
  }
  function safeUrls(urls) {
    const safe=(Array.isArray(urls)?urls:[urls]).filter(value=>{try{const url=new URL(value,location.href);return url.origin===location.origin&&/\.(png|jpe?g|webp)$/i.test(url.pathname)&&/^\/(output|drafts|media)\//.test(url.pathname);}catch{return false;}});
    return safe;
  }
  function open(urls,title='长图') {
    const safe=safeUrls(urls);
    if(!safe.length)return;
    if(!dialog)create();channelSelect.hidden=true;groups=[];lastFocus=document.activeElement;pages=safe;dialog.dataset.title=title;if(!dialog.open)dialog.showModal();showPage(0);dialog.querySelector('[data-action=close]').focus();
  }
  function openGroups(columns,title='分栏图') {
    const selected=columns.map(column=>({...column,images:safeUrls(column.images)})).filter(column=>column.images.length);
    if(!selected.length)return;
    open(selected[0].images,title);groups=selected;
    channelSelect.replaceChildren(...groups.map((group,index)=>{const option=element('option','',group.title||`频道 ${index+1}`);option.value=String(index);return option;}));
    channelSelect.hidden=false;
  }
  window.ArchivePreview={open,openGroups};
})();
