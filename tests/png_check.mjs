// Native canvas is the independent encoder/decoder for this lossless codec.
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {stitchHorizontalPng,stitchPngGrid,writePngGrid} from '../scripts/png.mjs';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const colorTypes=new Set(['sRGB','iCCP','gAMA','cHRM']);
function checksum(buffer){
  let value=0xffffffff;
  for(const byte of buffer){value^=byte;for(let bit=0;bit<8;bit++)value=(value>>>1)^((value&1)?0xedb88320:0);}
  return (value^0xffffffff)>>>0;
}
function chunks(buffer){
  assert.ok(buffer.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])));
  const result=[];let offset=8;
  while(offset<buffer.length){
    const length=buffer.readUInt32BE(offset),end=offset+length+12;
    assert.ok(end<=buffer.length,'Incomplete output chunk');
    const type=buffer.toString('ascii',offset+4,offset+8),data=buffer.subarray(offset+8,end-4);
    assert.equal(buffer.readUInt32BE(end-4),checksum(buffer.subarray(offset+4,end-4)),`Invalid ${type} output CRC`);
    result.push({type,data,raw:buffer.subarray(offset,end)});offset=end;
  }
  assert.equal(result[0].type,'IHDR');assert.equal(result.at(-1).type,'IEND');return result;
}
function colorChunk(type,data){
  const name=Buffer.from(type),result=Buffer.alloc(data.length+12);result.writeUInt32BE(data.length);name.copy(result,4);data.copy(result,8);result.writeUInt32BE(checksum(Buffer.concat([name,data])),data.length+8);return result;
}
function assertSrgb(buffer){
  const parts=chunks(buffer),colors=parts.filter(part=>colorTypes.has(part.type));
  assert.equal(colors.length,1);assert.equal(colors[0].type,'sRGB');assert.deepEqual(colors[0].data,Buffer.from([0]));
  assert.ok(parts.findIndex(part=>part.type==='sRGB')<parts.findIndex(part=>part.type==='IDAT'));
}
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const directory=await fs.mkdtemp(path.join(os.tmpdir(),'discord-png-stream-'));
try{
  const page=await browser.newPage();
  const fixtures=await page.evaluate(()=>{
    const result=[];
    for(let start=0;start<16692;start+=4096){
      const canvas=document.createElement('canvas');canvas.width=Math.min(4096,16692-start);canvas.height=32;
      const context=canvas.getContext('2d'),pixels=context.createImageData(canvas.width,canvas.height);
      for(let y=0;y<32;y++)for(let x=0;x<canvas.width;x++){
        const index=(y*canvas.width+x)*4,globalX=start+x;
        pixels.data.set([(globalX*37+y*3)&255,(globalX>>>8)&255,(y*7)&255,255],index);
      }
      context.putImageData(pixels,0,0);result.push(canvas.toDataURL('image/png').split(',')[1]);
    }
    return result;
  });
  const tiles=fixtures.map(value=>Buffer.from(value,'base64')),joined=stitchHorizontalPng(tiles);
  assertSrgb(joined);
  assert.equal(joined.readUInt32BE(16),16692);assert.equal(joined.readUInt32BE(20),32);
  const samples=await page.evaluate(async source=>{
    const image=new Image();image.src=source;await image.decode();
    const canvas=document.createElement('canvas');canvas.width=canvas.height=1;
    const context=canvas.getContext('2d',{willReadFrequently:true}),samples=[];
    for(const x of [0,4095,4096,8191,8192,12287,12288,16383,16384,16691])for(const y of [0,13,31]){
      context.clearRect(0,0,1,1);context.drawImage(image,x,y,1,1,0,0,1,1);
      samples.push({x,y,pixel:[...context.getImageData(0,0,1,1).data]});
    }
    return samples;
  },'data:image/png;base64,'+joined.toString('base64'));
  for(const {x,y,pixel} of samples)assert.deepEqual(pixel,[(x*37+y*3)&255,(x>>>8)&255,(y*7)&255,255],`Pixel changed at ${x},${y}`);
  const nativeChunks=chunks(tiles[0]),untaggedParts=nativeChunks.filter(part=>!colorTypes.has(part.type));
  const untagged=Buffer.concat([tiles[0].subarray(0,8),...untaggedParts.map(part=>part.raw)]);
  const tagged=stitchHorizontalPng([untagged]);assertSrgb(tagged);
  const taggedAgain=stitchHorizontalPng([tagged]);assertSrgb(taggedAgain);
  assert.deepEqual(taggedAgain,tagged,'An existing sRGB label or pixel stream changed');
  const p3=Buffer.from(await page.evaluate(()=>{
    const canvas=document.createElement('canvas');canvas.width=canvas.height=1;
    const context=canvas.getContext('2d',{colorSpace:'display-p3'});context.fillStyle='color(display-p3 1 0 .5)';context.fillRect(0,0,1,1);
    return canvas.toDataURL('image/png').split(',')[1];
  }),'base64');
  const profile=chunks(p3).find(part=>part.type==='iCCP');assert.ok(profile,'Native wide-gamut fixture did not provide an ICC profile');
  const gamma=Buffer.alloc(4);gamma.writeUInt32BE(45455);
  const chromaticities=Buffer.alloc(32);[31270,32900,64000,33000,30000,60000,15000,6000].forEach((value,index)=>chromaticities.writeUInt32BE(value,index*4));
  for(const [type,data] of [['sRGB',Buffer.from([1])],['iCCP',profile.data],['gAMA',gamma],['cHRM',chromaticities]]){
    const input=Buffer.concat([untagged.subarray(0,8),untaggedParts[0].raw,colorChunk(type,data),...untaggedParts.slice(1).map(part=>part.raw)]);
    const colors=chunks(stitchHorizontalPng([input])).filter(part=>colorTypes.has(part.type));
    assert.equal(colors.length,1,`${type} was supplemented with an unwanted sRGB label`);
    assert.equal(colors[0].type,type);assert.deepEqual(colors[0].data,data,`${type} metadata changed`);
    const filename=path.join(directory,`profile-${type}.png`);
    await writePngGrid([{buffer:input,x:0,y:0}],4096,32,filename);
    const streamedColors=chunks(await fs.readFile(filename)).filter(part=>colorTypes.has(part.type));
    assert.equal(streamedColors.length,1);assert.equal(streamedColors[0].type,type);assert.deepEqual(streamedColors[0].data,data);
  }
  const broken=Buffer.from(tiles[0]);broken[broken.length-1]^=1;
  assert.throws(()=>stitchHorizontalPng([broken]),/校验/);
  assert.throws(()=>stitchHorizontalPng([tiles[0].subarray(0,20)]),/完整/);
  assert.throws(()=>stitchHorizontalPng(Array(8).fill(tiles[0])),/尺寸/);
  assert.throws(()=>stitchHorizontalPng([]),/没有/);
  const gridFixtures=await page.evaluate(()=>{
    const result=[];
    for(const [width,height] of [[4109,4113],[32,16692]]){
      const tiles=[];
      for(let top=0;top<height;top+=4096)for(let left=0;left<width;left+=4096){
        const canvas=document.createElement('canvas');canvas.width=Math.min(4096,width-left);canvas.height=Math.min(4096,height-top);
        const context=canvas.getContext('2d'),pixels=context.createImageData(canvas.width,canvas.height);
        for(let y=0;y<canvas.height;y++)for(let x=0;x<canvas.width;x++){
          const index=(y*canvas.width+x)*4,globalX=left+x,globalY=top+y;
          pixels.data.set([(globalX*37+globalY*3)&255,((globalX>>>8)+(globalY>>>4)*11)&255,((globalY>>>8)*17+(globalX>>>4)*3)&255,255],index);
        }
        context.putImageData(pixels,0,0);tiles.push({x:left,y:top,buffer:canvas.toDataURL('image/png').split(',')[1]});
      }
      result.push({width,height,tiles});
    }
    return result;
  });
  const gridResults=[];
  async function verifyGridPixels(composed,width,height){
    const gridSamples=await page.evaluate(async({source,width,height})=>{
      const image=new Image();image.src=source;await image.decode();
      const canvas=document.createElement('canvas');canvas.width=canvas.height=1;
      const context=canvas.getContext('2d',{willReadFrequently:true}),samples=[];
      const xs=width>4096?[0,4095,4096,width-1]:[0,13,width-1];
      const ys=[...new Set([0,height-1,...Array.from({length:Math.floor((height-1)/4096)},(_,index)=>(index+1)*4096).flatMap(y=>[y-1,y])])];
      for(const x of xs)for(const y of ys){
        context.clearRect(0,0,1,1);context.drawImage(image,x,y,1,1,0,0,1,1);
        samples.push({x,y,pixel:[...context.getImageData(0,0,1,1).data]});
      }
      return samples;
    },{source:'data:image/png;base64,'+composed.toString('base64'),width,height});
    for(const {x,y,pixel} of gridSamples)assert.deepEqual(pixel,[(x*37+y*3)&255,((x>>>8)+(y>>>4)*11)&255,((y>>>8)*17+(x>>>4)*3)&255,255],`Grid pixel changed at ${x},${y}`);
    return gridSamples.length;
  }
  for(const fixture of gridFixtures){
    const placements=fixture.tiles.map(tile=>({...tile,buffer:Buffer.from(tile.buffer,'base64')}));
    // Reverse input order to verify that x/y placement drives composition.
    const composed=stitchPngGrid([...placements].reverse(),fixture.width,fixture.height);
    assertSrgb(composed);
    assert.equal(composed.readUInt32BE(16),fixture.width);assert.equal(composed.readUInt32BE(20),fixture.height);
    const nativeSamples=await verifyGridPixels(composed,fixture.width,fixture.height);
    const filename=path.join(directory,`${fixture.width}x${fixture.height}.png`);
    let largestAllocation=0;const allocate=Buffer.alloc;
    try{
      Buffer.alloc=(size,...options)=>{largestAllocation=Math.max(largestAllocation,size);return allocate(size,...options);};
      assert.deepEqual(await writePngGrid([...placements].reverse(),fixture.width,fixture.height,filename),{width:fixture.width,height:fixture.height});
    }finally{Buffer.alloc=allocate;}
    assert.ok(largestAllocation<=Math.max(fixture.width*4+1,16*1024+12),'Streaming writer exceeded the scanline/deflate chunk allocation bound');
    const streamed=await fs.readFile(filename);assertSrgb(streamed);
    assert.equal(streamed.readUInt32BE(16),fixture.width);assert.equal(streamed.readUInt32BE(20),fixture.height);
    const streamedSamples=await verifyGridPixels(streamed,fixture.width,fixture.height);
    await assert.rejects(writePngGrid(placements.slice(0,-1),fixture.width,fixture.height,path.join(directory,'missing.png')),/缺失/);
    await assert.rejects(writePngGrid([...placements,placements[0]],fixture.width,fixture.height,path.join(directory,'overlap.png')),/重叠/);
    assert.throws(()=>stitchPngGrid(placements.slice(0,-1),fixture.width,fixture.height),/缺失/);
    assert.throws(()=>stitchPngGrid([...placements,placements[0]],fixture.width,fixture.height),/重叠/);
    assert.throws(()=>stitchPngGrid([{...placements[0],x:fixture.width}],fixture.width,fixture.height),/边界/);
    assert.throws(()=>stitchPngGrid([{...placements[0],x:.5}],fixture.width,fixture.height),/位置/);
    gridResults.push({width:fixture.width,height:fixture.height,tiles:placements.length,native_pixel_samples:nativeSamples,streamed_native_pixel_samples:streamedSamples,largest_stream_allocation:largestAllocation});
  }
  assert.throws(()=>stitchPngGrid([],32,32),/没有/);
  assert.throws(()=>stitchPngGrid([{buffer:tiles[0],x:0,y:0}],32001,32),/尺寸/);
  assert.throws(()=>stitchPngGrid([{buffer:tiles[0],x:0,y:0}],32,32001),/尺寸/);
  assert.throws(()=>stitchPngGrid([{buffer:tiles[0],x:0,y:0}],10000,10000),/尺寸/);
  assert.throws(()=>stitchPngGrid([{buffer:broken,x:0,y:0}],4096,32),/校验/);
  assert.throws(()=>stitchPngGrid([{buffer:tiles[0].subarray(0,20),x:0,y:0}],4096,32),/完整/);
  // Repair the IHDR checksum after changing bit depth so format rejection is
  // tested separately from the corruption guard, without using this codec.
  const unsupported=Buffer.from(tiles[0]);unsupported[24]=16;
  unsupported.writeUInt32BE(checksum(unsupported.subarray(12,29)),29);
  assert.throws(()=>stitchPngGrid([{buffer:unsupported,x:0,y:0}],4096,32),/格式/);
  const oversized=Buffer.from(tiles[0]);oversized.writeUInt32BE(4097,16);oversized.writeUInt32BE(checksum(oversized.subarray(12,29)),29);
  const wideFixtures=await page.evaluate(()=>{
    const tiles=[];
    for(let x=0;x<64000;x+=4096){
      const canvas=document.createElement('canvas');canvas.width=Math.min(4096,64000-x);canvas.height=1;
      const context=canvas.getContext('2d');context.fillStyle='rgb(37, 89, 173)';context.fillRect(0,0,canvas.width,1);
      tiles.push({x,y:0,buffer:canvas.toDataURL('image/png').split(',')[1]});
    }
    return tiles;
  });
  const widePlacements=wideFixtures.map(tile=>({...tile,buffer:Buffer.from(tile.buffer,'base64')}));
  const wideFile=path.join(directory,'64000x1.png');await writePngGrid(widePlacements,64000,1,wideFile);
  const wideOutput=await fs.readFile(wideFile);assertSrgb(wideOutput);
  assert.equal(wideOutput.readUInt32BE(16),64000);assert.equal(wideOutput.readUInt32BE(20),1);
  const widePixel=await page.evaluate(async source=>{
    const image=new Image();image.src=source;await image.decode();
    const canvas=document.createElement('canvas');canvas.width=canvas.height=1;
    const context=canvas.getContext('2d');context.drawImage(image,63999,0,1,1,0,0,1,1);
    return [...context.getImageData(0,0,1,1).data];
  },'data:image/png;base64,'+wideOutput.toString('base64'));
  assert.deepEqual(widePixel,[37,89,173,255]);
  assert.throws(()=>stitchPngGrid(widePlacements,64000,1),/尺寸/,'The synchronous API unexpectedly relaxed its size limit');
  await assert.rejects(writePngGrid([{buffer:oversized,x:0,y:0}],4097,32,path.join(directory,'oversized.png')),/4096/);
  await assert.rejects(writePngGrid([{buffer:tiles[0],x:0,y:0}],64001,32,path.join(directory,'too-wide.png')),/尺寸/);
  await assert.rejects(writePngGrid([{buffer:tiles[0],x:0,y:0}],32,64001,path.join(directory,'too-tall.png')),/尺寸/);
  await assert.rejects(writePngGrid([{buffer:tiles[0],x:0,y:0}],20000,20000,path.join(directory,'too-many-pixels.png')),/尺寸/);
  await assert.rejects(writePngGrid([{buffer:broken,x:0,y:0}],4096,32,path.join(directory,'bad-crc.png')),/校验/);
  await assert.rejects(writePngGrid([{buffer:tiles[0].subarray(0,20),x:0,y:0}],4096,32,path.join(directory,'truncated.png')),/完整/);
  await assert.rejects(writePngGrid([{buffer:unsupported,x:0,y:0}],4096,32,path.join(directory,'bad-format.png')),/格式/);
  await assert.rejects(writePngGrid(Array.from({length:65},(_,x)=>({buffer:p3,x,y:0})),65,1,path.join(directory,'too-many-streams.png')),/片段过多/);
  const protectedFile=path.join(directory,'protected.png'),sentinel=Buffer.from('existing output must survive an incomplete stream');
  await fs.writeFile(protectedFile,sentinel);
  const invalidStream=Buffer.concat([tiles[0].subarray(0,8),nativeChunks[0].raw,colorChunk('IDAT',Buffer.from([0,0,0])),colorChunk('IEND',Buffer.alloc(0))]);
  await assert.rejects(writePngGrid([{buffer:invalidStream,x:0,y:0}],4096,32,protectedFile));
  assert.deepEqual(await fs.readFile(protectedFile),sentinel,'A failed stream replaced an existing output');
  assert.ok(!(await fs.readdir(directory)).some(name=>name.endsWith('.part')),'A failed stream left its temporary output');
  for(const name of ['missing.png','overlap.png','oversized.png','too-wide.png','too-tall.png','too-many-pixels.png','bad-crc.png','truncated.png','bad-format.png','too-many-streams.png'])await assert.rejects(fs.access(path.join(directory,name)),{code:'ENOENT'});
  console.log(JSON.stringify({status:'passed',directory,width:16692,height:32,native_pixel_samples:samples.length,seams_verified:true,right_edge_wrap:false,corrupt_tiles_rejected:true,grid:gridResults,grid_missing_overlap_bounds_format_rejected:true,streaming_grid_verified:true,failed_stream_cleanup:true,output_chunk_crcs_valid:true,default_srgb_tagged:true,existing_color_tags_preserved:['sRGB','iCCP','gAMA','cHRM']}));
}finally{await browser.close();}
