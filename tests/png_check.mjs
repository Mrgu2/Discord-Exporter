// Native canvas is the independent encoder/decoder for this lossless codec.
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {stitchHorizontalPng,stitchPngGrid} from '../scripts/png.mjs';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
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
  for(const fixture of gridFixtures){
    const placements=fixture.tiles.map(tile=>({...tile,buffer:Buffer.from(tile.buffer,'base64')}));
    // Reverse input order to verify that x/y placement drives composition.
    const composed=stitchPngGrid([...placements].reverse(),fixture.width,fixture.height);
    assert.equal(composed.readUInt32BE(16),fixture.width);assert.equal(composed.readUInt32BE(20),fixture.height);
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
    },{source:'data:image/png;base64,'+composed.toString('base64'),width:fixture.width,height:fixture.height});
    for(const {x,y,pixel} of gridSamples)assert.deepEqual(pixel,[(x*37+y*3)&255,((x>>>8)+(y>>>4)*11)&255,((y>>>8)*17+(x>>>4)*3)&255,255],`Grid pixel changed at ${x},${y}`);
    assert.throws(()=>stitchPngGrid(placements.slice(0,-1),fixture.width,fixture.height),/缺失/);
    assert.throws(()=>stitchPngGrid([...placements,placements[0]],fixture.width,fixture.height),/重叠/);
    assert.throws(()=>stitchPngGrid([{...placements[0],x:fixture.width}],fixture.width,fixture.height),/边界/);
    assert.throws(()=>stitchPngGrid([{...placements[0],x:.5}],fixture.width,fixture.height),/位置/);
    gridResults.push({width:fixture.width,height:fixture.height,tiles:placements.length,native_pixel_samples:gridSamples.length});
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
  let checksum=0xffffffff;
  for(const byte of unsupported.subarray(12,29)){checksum^=byte;for(let bit=0;bit<8;bit++)checksum=(checksum>>>1)^((checksum&1)?0xedb88320:0);}
  unsupported.writeUInt32BE((checksum^0xffffffff)>>>0,29);
  assert.throws(()=>stitchPngGrid([{buffer:unsupported,x:0,y:0}],4096,32),/格式/);
  console.log(JSON.stringify({status:'passed',width:16692,height:32,native_pixel_samples:samples.length,seams_verified:true,right_edge_wrap:false,corrupt_tiles_rejected:true,grid:gridResults,grid_missing_overlap_bounds_format_rejected:true}));
}finally{await browser.close();}
