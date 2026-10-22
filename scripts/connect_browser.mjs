#!/usr/bin/env node
// Internal backend child process. Its stdout is a private machine pipe, never a
// diagnostic log. It only uses this application's dedicated Chrome profile.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require=createRequire(import.meta.url);
const profile=path.resolve(process.argv[2]||'');
const waitMs=Math.min(565000,Math.max(250,Number(process.argv[3])||565000));
let wrote=false;
function result(value){if(!wrote){wrote=true;process.stdout.write(JSON.stringify(value));}}

export function validSessionCandidate(value){
  return typeof value==='string'&&value.length>=16&&value.length<=4096&&!/\s/.test(value)?value:null;
}

export function safePageState(value){
  try{
    const url=new URL(value);
    if(url.origin!=='https://discord.com')return url.protocol==='about:'?'blank':'other_site';
    if(url.pathname.startsWith('/channels/'))return 'discord_channels';
    if(url.pathname.startsWith('/login'))return 'discord_login';
    return 'discord_other';
  }catch{return 'unknown';}
}

export async function requestCandidate(request){
  try{
    const url=new URL(request.url());
    if(url.origin!=='https://discord.com'||!/^\/api\/v\d+\/(?:users\/@me(?:\/|$)|channels\/\d+\/messages(?:\/|$))/.test(url.pathname))return null;
    const headers=await request.allHeaders();
    return validSessionCandidate(headers.authorization);
  }catch{return null;}
}

async function loadPlaywright(){
  try{return require('playwright');}catch{}
  const candidates=[process.env.PLAYWRIGHT_MODULE,path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js')].filter(Boolean);
  for(const candidate of candidates){try{const loaded=await import(pathToFileURL(candidate).href);return loaded.default||loaded;}catch{}}
  throw new Error('playwright_missing');
}

async function main(){
  if(process.stdout.isTTY)throw new Error('backend_pipe_required');
  if(path.basename(profile)!=='browser-profile'||path.basename(path.dirname(profile))!=='data')throw new Error('dedicated_profile_required');
  fs.mkdirSync(profile,{recursive:true,mode:0o700});fs.chmodSync(profile,0o700);
  // Operational diagnostics contain no URLs, account names, page text, headers
  // or storage values. They let the local service distinguish an unseen login
  // window from a session that was logged in but not recognized.
  const diagnosticPath=path.join(path.dirname(profile),'browser-connection.json');
  let diagnostic={phase:'opening',page_state:'unknown',candidate_observed:false};
  function record(update){
    const next={...diagnostic,...update};
    if(JSON.stringify(next)===JSON.stringify(diagnostic)&&fs.existsSync(diagnosticPath))return;
    diagnostic=next;
    try{fs.writeFileSync(diagnosticPath,JSON.stringify({...diagnostic,updated_at:new Date().toISOString()}),{mode:0o600});}catch{}
  }
  record({});
  const playwright=await loadPlaywright();
  const executable='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  let context,closed=false,observedCandidate=null;
  const deadline=Date.now()+waitMs;
  try{
    context=await playwright.chromium.launchPersistentContext(profile,{
      headless:false,timeout:Math.min(30000,waitMs),viewport:null,
      ...(fs.existsSync(executable)?{executablePath:executable}:{channel:'chrome'}),
      args:['--no-first-run','--no-default-browser-check'],
    });
    context.on('close',()=>{closed=true;});
    // Only the dedicated, user-initiated login window is observed. This avoids
    // depending solely on the web client's private storage implementation.
    // Header values stay in this process and the private parent pipe.
    context.on('request',async request=>{
      const candidate=await requestCandidate(request);
      if(candidate){observedCandidate=candidate;record({candidate_observed:true,candidate_source:'request'});}
    });
    const page=context.pages()[0]||await context.newPage();
    try{await page.goto('https://discord.com/channels/@me',{waitUntil:'domcontentloaded',timeout:Math.min(30000,Math.max(250,deadline-Date.now()))});}catch{record({navigation_incomplete:true});}
    while(Date.now()<deadline&&!closed){
      if(page.isClosed()){record({phase:'cancelled'});result({status:'cancelled'});return;}
      record({phase:'waiting',page_state:safePageState(page.url())});
      let candidate=observedCandidate;
      try{
        // Read one fixed key only, after an exact origin check. A blank iframe
        // inherits this same Discord origin if the app hides window storage.
        if(!candidate)candidate=await page.evaluate(()=>{
          if(location.origin!=='https://discord.com'||!location.pathname.startsWith('/channels/'))return null;
          let raw=null;
          try{raw=window.localStorage.getItem('token');}catch{}
          if(!raw){
            const frame=document.createElement('iframe');frame.style.display='none';
            document.documentElement.append(frame);
            try{if(frame.contentWindow.location.origin===location.origin||frame.contentWindow.location.href==='about:blank')raw=frame.contentWindow.localStorage.getItem('token');}catch{}
            finally{frame.remove();}
          }
          if(typeof raw!=='string')return null;
          let value;
          try{value=JSON.parse(raw);}catch{value=raw;}
          return typeof value==='string'&&value.length>=16&&value.length<=4096&&!/\s/.test(value)?value:null;
        });
      }catch{}
      if(candidate){record({phase:'candidate',candidate_observed:true,candidate_source:observedCandidate?'request':'storage'});result({status:'candidate',token:candidate});candidate=null;observedCandidate=null;return;}
      await new Promise(resolve=>setTimeout(resolve,500));
    }
    record({phase:closed?'cancelled':'timeout'});
    result({status:closed?'cancelled':'timeout'});
  }finally{
    observedCandidate=null;
    if(context&&!closed){
      let timer;
      await Promise.race([context.close().catch(()=>{}),new Promise(resolve=>{timer=setTimeout(resolve,3000);timer.unref();})]);
      if(timer)clearTimeout(timer);
    }
  }
}

if(path.resolve(process.argv[1]||'')===fileURLToPath(import.meta.url)){
  main().catch(()=>{result({status:'error',code:'browser_unavailable'});process.exitCode=1;});
}
