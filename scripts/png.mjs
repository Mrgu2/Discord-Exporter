// Lossless assembly of the 8-bit, non-interlaced PNG tiles emitted
// by Chromium. No native package or second image encoder is required.
import zlib from 'node:zlib';
import fs from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import {Readable,Writable} from 'node:stream';
import {pipeline} from 'node:stream/promises';

const SIGNATURE=Buffer.from([137,80,78,71,13,10,26,10]);
const CRC_TABLE=Array.from({length:256},(_,value)=>{
  for(let bit=0;bit<8;bit++)value=(value&1)?0xedb88320^(value>>>1):value>>>1;
  return value>>>0;
});
function crc32(buffer){let value=0xffffffff;for(const byte of buffer)value=CRC_TABLE[(value^byte)&255]^(value>>>8);return (value^0xffffffff)>>>0;}
function chunk(type,data){const name=Buffer.from(type),result=Buffer.alloc(data.length+12);result.writeUInt32BE(data.length);name.copy(result,4);data.copy(result,8);result.writeUInt32BE(crc32(Buffer.concat([name,data])),data.length+8);return result;}
function parse(buffer){
  if(!buffer.subarray(0,8).equals(SIGNATURE))throw new Error('无效的 PNG 渲染片段。');
  const result={data:[],color:[]};
  for(let offset=8;offset<buffer.length;){
    if(offset+12>buffer.length)throw new Error('PNG 渲染片段不完整。');
    const length=buffer.readUInt32BE(offset),type=buffer.toString('ascii',offset+4,offset+8),end=offset+12+length;
    if(end>buffer.length)throw new Error('PNG 渲染片段不完整。');
    const data=buffer.subarray(offset+8,offset+8+length);
    if(crc32(buffer.subarray(offset+4,offset+8+length))!==buffer.readUInt32BE(offset+8+length))throw new Error('PNG 渲染片段校验失败。');
    if(type==='IHDR')result.header=Buffer.from(data);
    if(type==='IDAT')result.data.push(data);
    if(['sRGB','iCCP','gAMA','cHRM'].includes(type))result.color.push({type,data});
    offset=end;if(type==='IEND'){result.complete=true;break;}
  }
  const header=result.header;
  if(!result.complete||!header||header.length!==13||!header.readUInt32BE(0)||!header.readUInt32BE(4)||header[8]!==8||![2,6].includes(header[9])||header[10]||header[11]||header[12]||!result.data.length)throw new Error('PNG 渲染格式不受支持。');
  return {...result,width:header.readUInt32BE(0),height:header.readUInt32BE(4),channels:header[9]===2?3:4};
}
const paeth=(a,b,c)=>{const p=a+b-c,pa=Math.abs(p-a),pb=Math.abs(p-b),pc=Math.abs(p-c);return pa<=pb&&pa<=pc?a:pb<=pc?b:c;};

function restoreRow(row,previous,filter,channels){
  if(filter>4)throw new Error('PNG 渲染滤波格式不受支持。');
  for(let x=0;x<row.length;x++){
    const a=x>=channels?row[x-channels]:0,b=previous[x],c=x>=channels?previous[x-channels]:0;
    row[x]=(row[x]+(filter===1?a:filter===2?b:filter===3?Math.floor((a+b)/2):filter===4?paeth(a,b,c):0))&255;
  }
}

function copyPixels(tile,raw,stride,left,top){
  const tileStride=tile.width*tile.channels,scanlines=zlib.inflateSync(Buffer.concat(tile.data),{maxOutputLength:(tileStride+1)*tile.height});
  if(scanlines.length!==(tileStride+1)*tile.height)throw new Error('PNG 渲染片段像素不完整。');
  let previous=Buffer.alloc(tileStride);
  for(let y=0;y<tile.height;y++){
    const filter=scanlines[y*(tileStride+1)],row=Buffer.from(scanlines.subarray(y*(tileStride+1)+1,(y+1)*(tileStride+1)));
    restoreRow(row,previous,filter,tile.channels);
    row.copy(raw,(top+y)*(stride+1)+1+left*tile.channels);previous=row;
  }
}

function prelude(first,width,height){
  const header=Buffer.from(first.header);header.writeUInt32BE(width);header.writeUInt32BE(height,4);
  // This renderer's untagged Chrome captures contain sRGB samples. Label them
  // for image viewers while preserving any color metadata supplied by a tile.
  const color=first.color.length?first.color:[{type:'sRGB',data:Buffer.from([0])}];
  return Buffer.concat([SIGNATURE,chunk('IHDR',header),...color.map(item=>chunk(item.type,item.data))]);
}

function encodePixels(first,raw,width,height){
  return Buffer.concat([prelude(first,width,height),chunk('IDAT',zlib.deflateSync(raw,{level:6})),chunk('IEND',Buffer.alloc(0))]);
}

export function stitchHorizontalPng(buffers){
  if(!buffers.length)throw new Error('没有可拼接的 PNG 片段。');
  const tiles=buffers.map(parse),first=tiles[0],width=tiles.reduce((sum,tile)=>sum+tile.width,0),height=first.height,channels=first.channels;
  if(width>32000||width*height>80_000_000||!width||!height)throw new Error('横向长图超过单图尺寸限制。');
  if(tiles.some(tile=>tile.height!==height||tile.channels!==channels))throw new Error('PNG 渲染片段尺寸或格式不一致。');
  const stride=width*channels,raw=Buffer.alloc((stride+1)*height);let horizontal=0;
  for(const tile of tiles){
    copyPixels(tile,raw,stride,horizontal,0);
    horizontal+=tile.width;
  }
  return encodePixels(first,raw,width,height);
}

// Each row must fill the complete canvas width, with equally tall tiles in
// that row. Rows may have different heights; input order does not matter.
function grid(tiles,width,height,{maxSide=32000,maxPixels=80_000_000,maxTileSide=Infinity,maxBandTiles=Infinity}={}){
  if(!Array.isArray(tiles)||!tiles.length)throw new Error('没有可拼接的 PNG 片段。');
  if(!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||width>maxSide||height>maxSide||width*height>maxPixels)throw new Error('拼图超过单图尺寸限制。');
  const placements=tiles.map(placement=>{
    if(!placement||!Buffer.isBuffer(placement.buffer)||!Number.isInteger(placement.x)||!Number.isInteger(placement.y)||placement.x<0||placement.y<0)throw new Error('PNG 网格片段位置或格式无效。');
    const tile=parse(placement.buffer);
    if(tile.width>maxTileSide||tile.height>maxTileSide)throw new Error('PNG 渲染片段超过 4096 像素限制。');
    if(placement.x+tile.width>width||placement.y+tile.height>height)throw new Error('PNG 网格片段超出画布边界。');
    return {tile,x:placement.x,y:placement.y};
  }).sort((left,right)=>left.y-right.y||left.x-right.x);
  const first=placements[0].tile;
  if(placements.some(({tile})=>tile.channels!==first.channels))throw new Error('PNG 渲染片段尺寸或格式不一致。');
  let bottom=0,index=0;
  while(index<placements.length){
    const rowY=placements[index].y,rowHeight=placements[index].tile.height;
    if(rowY!==bottom)throw new Error('PNG 网格片段重叠或缺失。');
    let right=0,bandTiles=0;
    while(index<placements.length&&placements[index].y===rowY){
      if(++bandTiles>maxBandTiles)throw new Error('PNG 网格横带片段过多。');
      const placement=placements[index++];
      if(placement.x!==right||placement.tile.height!==rowHeight)throw new Error('PNG 网格片段重叠、缺失或行高不一致。');
      right+=placement.tile.width;
    }
    if(right!==width)throw new Error('PNG 网格片段缺失，未覆盖整行。');
    bottom+=rowHeight;
  }
  if(bottom!==height)throw new Error('PNG 网格片段缺失，未覆盖完整画布。');
  return {placements,first};
}

export function stitchPngGrid(tiles,width,height){
  const {placements,first}=grid(tiles,width,height);
  const stride=width*first.channels,raw=Buffer.alloc((stride+1)*height);
  // Inflate one tile at a time rather than retaining a second full canvas.
  for(const {tile,x,y} of placements)copyPixels(tile,raw,stride,x,y);
  return encodePixels(first,raw,width,height);
}

async function* tileRows(tile){
  const stride=tile.width*tile.channels,expected=(stride+1)*tile.height;
  const source=Readable.from(tile.data,{objectMode:false});
  const inflater=zlib.createInflate(),iterator=inflater[Symbol.asyncIterator]();
  source.pipe(inflater);
  let pending=Buffer.alloc(0),offset=0,produced=0,previous=Buffer.alloc(stride);
  async function readRow(){
    const scanline=Buffer.alloc(stride+1);let copied=0;
    while(copied<scanline.length){
      if(offset===pending.length){
        const next=await iterator.next();
        if(next.done)throw new Error('PNG 渲染片段像素不完整。');
        pending=next.value;offset=0;produced+=pending.length;
        if(produced>expected)throw new Error('PNG 渲染片段像素长度异常。');
      }
      const count=Math.min(scanline.length-copied,pending.length-offset);
      pending.copy(scanline,copied,offset,offset+count);offset+=count;copied+=count;
    }
    const row=scanline.subarray(1);restoreRow(row,previous,scanline[0],tile.channels);previous=row;
    return row;
  }
  try{
    for(let y=0;y<tile.height;y++)yield await readRow();
    if(offset!==pending.length||!(await iterator.next()).done)throw new Error('PNG 渲染片段像素长度异常。');
  }finally{source.destroy();inflater.destroy();}
}

async function* gridRows(placements,width,channels){
  let index=0;
  while(index<placements.length){
    const top=placements[index].y,band=[];
    while(index<placements.length&&placements[index].y===top)band.push(placements[index++]);
    const readers=band.map(({tile})=>tileRows(tile));
    try{
      for(let y=0;y<band[0].tile.height;y++){
        const row=Buffer.alloc(width*channels+1);
        for(let column=0;column<band.length;column++){
          const next=await readers[column].next();
          if(next.done)throw new Error('PNG 渲染片段像素不完整。');
          next.value.copy(row,1+band[column].x*channels);
        }
        yield row;
      }
      for(const reader of readers)if(!(await reader.next()).done)throw new Error('PNG 渲染片段像素长度异常。');
    }finally{await Promise.allSettled(readers.map(reader=>reader.return()));}
  }
}

// The HiDPI path keeps only scanlines and bounded zlib buffers in memory.
// The final filename becomes visible only after the complete stream succeeds.
export async function writePngGrid(tiles,width,height,filename){
  const {placements,first}=grid(tiles,width,height,{maxSide:64000,maxPixels:320_000_000,maxTileSide:4096,maxBandTiles:64});
  if(typeof filename!=='string'||!filename)throw new Error('PNG 输出路径无效。');
  const temporary=filename+'.'+randomUUID()+'.part';let handle,created=false;
  try{
    handle=await fs.open(temporary,'wx',0o600);created=true;
    await handle.writeFile(prelude(first,width,height));
    const destination=new Writable({write(data,_encoding,done){handle.writeFile(chunk('IDAT',data)).then(()=>done(),done);}});
    await pipeline(Readable.from(gridRows(placements,width,first.channels),{objectMode:false,highWaterMark:64*1024}),zlib.createDeflate({level:6}),destination);
    await handle.writeFile(chunk('IEND',Buffer.alloc(0)));
    await handle.close();handle=null;
    await fs.rename(temporary,filename);created=false;
    return {width,height};
  }catch(error){
    if(handle)await handle.close().catch(()=>{});
    if(created)await fs.unlink(temporary).catch(()=>{});
    throw error;
  }
}
