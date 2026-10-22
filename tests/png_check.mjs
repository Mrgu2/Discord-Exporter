// Native canvas is the independent encoder/decoder for this lossless codec.
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {stitchHorizontalPng} from '../scripts/png.mjs';
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
  console.log(JSON.stringify({status:'passed',width:16692,height:32,native_pixel_samples:samples.length,seams_verified:true,right_edge_wrap:false,corrupt_tiles_rejected:true}));
}finally{await browser.close();}
