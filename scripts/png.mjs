// Lossless horizontal assembly of the 8-bit, non-interlaced PNG tiles emitted
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

export function stitchHorizontalPng(buffers){
  if(!buffers.length)throw new Error('没有可拼接的 PNG 片段。');
  const tiles=buffers.map(parse),first=tiles[0],width=tiles.reduce((sum,tile)=>sum+tile.width,0),height=first.height,channels=first.channels;
  if(width>32000||width*height>80_000_000||!width||!height)throw new Error('横向长图超过单图尺寸限制。');
  if(tiles.some(tile=>tile.height!==height||tile.channels!==channels))throw new Error('PNG 渲染片段尺寸或格式不一致。');
  const stride=width*channels,raw=Buffer.alloc((stride+1)*height);let horizontal=0;
  for(const tile of tiles){
    const tileStride=tile.width*channels,scanlines=zlib.inflateSync(Buffer.concat(tile.data),{maxOutputLength:(tileStride+1)*height});
    if(scanlines.length!==(tileStride+1)*height)throw new Error('PNG 渲染片段像素不完整。');
    let previous=Buffer.alloc(tileStride);
    for(let y=0;y<height;y++){
      const filter=scanlines[y*(tileStride+1)],row=Buffer.from(scanlines.subarray(y*(tileStride+1)+1,(y+1)*(tileStride+1)));
      if(filter>4)throw new Error('PNG 渲染滤波格式不受支持。');
      for(let x=0;x<tileStride;x++){
        const a=x>=channels?row[x-channels]:0,b=previous[x],c=x>=channels?previous[x-channels]:0;
        row[x]=(row[x]+(filter===1?a:filter===2?b:filter===3?Math.floor((a+b)/2):filter===4?paeth(a,b,c):0))&255;
      }
      row.copy(raw,y*(stride+1)+1+horizontal*channels);previous=row;
    }
    horizontal+=tile.width;
  }
  const header=Buffer.from(first.header);header.writeUInt32BE(width);header.writeUInt32BE(height,4);
  return Buffer.concat([SIGNATURE,chunk('IHDR',header),...first.color.map(item=>chunk(item.type,item.data)),chunk('IDAT',zlib.deflateSync(raw,{level:6})),chunk('IEND',Buffer.alloc(0))]);
}
