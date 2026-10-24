// Protocol helpers use Node's crypto and the pinned local QRCode dependency.
import {createCipheriv} from 'node:crypto';
const chunks=[];
for await (const chunk of process.stdin) chunks.push(chunk);
const input=Buffer.concat(chunks);
try {
  if(process.argv[2]==='encrypt') {
    if(input.length<16) throw new Error('key');
    const cipher=createCipheriv('aes-128-ecb',input.subarray(0,16),null);
    process.stdout.write(Buffer.concat([cipher.update(input.subarray(16)),cipher.final()]));
  } else if(process.argv[2]==='qr') {
    const {default:QRCode}=await import('qrcode');
    process.stdout.write(await QRCode.toBuffer(input.toString('utf8'),{type:'png',width:320,margin:3,errorCorrectionLevel:'M'}));
  } else throw new Error('action');
} catch {process.stderr.write('ClawBot helper failed');process.exitCode=1;}
