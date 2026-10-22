// Lossless assembly of the 8-bit, non-interlaced PNG tiles emitted
// by Chromium. No native package or second image encoder is required.
import zlib from 'node:zlib';

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

function copyPixels(tile,raw,stride,left,top){
  const tileStride=tile.width*tile.channels,scanlines=zlib.inflateSync(Buffer.concat(tile.data),{maxOutputLength:(tileStride+1)*tile.height});
  if(scanlines.length!==(tileStride+1)*tile.height)throw new Error('PNG 渲染片段像素不完整。');
  let previous=Buffer.alloc(tileStride);
  for(let y=0;y<tile.height;y++){
    const filter=scanlines[y*(tileStride+1)],row=Buffer.from(scanlines.subarray(y*(tileStride+1)+1,(y+1)*(tileStride+1)));
    if(filter>4)throw new Error('PNG 渲染滤波格式不受支持。');
    for(let x=0;x<tileStride;x++){
      const a=x>=tile.channels?row[x-tile.channels]:0,b=previous[x],c=x>=tile.channels?previous[x-tile.channels]:0;
      row[x]=(row[x]+(filter===1?a:filter===2?b:filter===3?Math.floor((a+b)/2):filter===4?paeth(a,b,c):0))&255;
    }
    row.copy(raw,(top+y)*(stride+1)+1+left*tile.channels);previous=row;
  }
}

function encodePixels(first,raw,width,height){
  const header=Buffer.from(first.header);header.writeUInt32BE(width);header.writeUInt32BE(height,4);
  // This renderer's untagged Chrome captures contain sRGB samples. Label them
  // for image viewers while preserving any color metadata supplied by a tile.
  const color=first.color.length?first.color:[{type:'sRGB',data:Buffer.from([0])}];
  return Buffer.concat([SIGNATURE,chunk('IHDR',header),...color.map(item=>chunk(item.type,item.data)),chunk('IDAT',zlib.deflateSync(raw,{level:6})),chunk('IEND',Buffer.alloc(0))]);
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
export function stitchPngGrid(tiles,width,height){
  if(!Array.isArray(tiles)||!tiles.length)throw new Error('没有可拼接的 PNG 片段。');
  if(!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||width>32000||height>32000||width*height>80_000_000)throw new Error('拼图超过单图尺寸限制。');
  const placements=tiles.map(placement=>{
    if(!placement||!Buffer.isBuffer(placement.buffer)||!Number.isInteger(placement.x)||!Number.isInteger(placement.y)||placement.x<0||placement.y<0)throw new Error('PNG 网格片段位置或格式无效。');
    const tile=parse(placement.buffer);
    if(placement.x+tile.width>width||placement.y+tile.height>height)throw new Error('PNG 网格片段超出画布边界。');
    return {tile,x:placement.x,y:placement.y};
  }).sort((left,right)=>left.y-right.y||left.x-right.x);
  const first=placements[0].tile;
  if(placements.some(({tile})=>tile.channels!==first.channels))throw new Error('PNG 渲染片段尺寸或格式不一致。');
  let bottom=0,index=0;
  while(index<placements.length){
    const rowY=placements[index].y,rowHeight=placements[index].tile.height;
    if(rowY!==bottom)throw new Error('PNG 网格片段重叠或缺失。');
    let right=0;
    while(index<placements.length&&placements[index].y===rowY){
      const placement=placements[index++];
      if(placement.x!==right||placement.tile.height!==rowHeight)throw new Error('PNG 网格片段重叠、缺失或行高不一致。');
      right+=placement.tile.width;
    }
    if(right!==width)throw new Error('PNG 网格片段缺失，未覆盖整行。');
    bottom+=rowHeight;
  }
  if(bottom!==height)throw new Error('PNG 网格片段缺失，未覆盖完整画布。');
  const stride=width*first.channels,raw=Buffer.alloc((stride+1)*height);
  // Inflate one tile at a time rather than retaining a second full canvas.
  for(const {tile,x,y} of placements)copyPixels(tile,raw,stride,x,y);
  return encodePixels(first,raw,width,height);
}
