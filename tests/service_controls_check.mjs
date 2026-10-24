// Real isolated HTTP process + actual browser UI; no user archive or agent used.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import http from 'node:http';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
let playwright;
try { playwright = require('playwright'); }
catch { playwright = require(path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')); }
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'archive-service-ui-'));
fs.symlinkSync(path.resolve('web'), path.join(root, 'web'), 'dir');
const listener = net.createServer();
await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve));
const port = listener.address().port;
await new Promise(resolve => listener.close(resolve));
const base = `http://127.0.0.1:${port}`;
const child = spawn(process.env.PYTHON || 'python3', [path.resolve('app.py'), '--root', root, '--host', '127.0.0.1', '--port', String(port)],
  {env: {...process.env, DISCORD_ARCHIVE_TOKEN:'fictional-service-test', ARCHIVE_MODEL_KEY:'fictional-service-test'}, stdio: ['ignore','pipe','pipe']});
let logs = ''; child.stdout.on('data', b => logs += b); child.stderr.on('data', b => logs += b);
let exited = false; child.on('exit', () => exited = true);
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(fn, timeout = 15000) {
  const end = Date.now()+timeout;
  while (Date.now()<end) { try { if(await fn()) return; } catch {} await wait(100); }
  throw new Error('Timed out. '+logs);
}
let browser;
try {
  await until(async () => (await fetch(base+'/api/health')).ok);
  browser = await playwright.chromium.launch({headless:true, executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page = await browser.newPage({viewport:{width:1280,height:900}});
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(base); await page.waitForFunction(() => document.querySelector('#service-pause')?.disabled === false);
  await page.locator('#advanced-settings').evaluate(e => e.open = true);
  assert.equal(await page.locator('#service-stop').isVisible(), false);
  await page.locator('#service-pause').click();
  await page.waitForFunction(() => document.querySelector('#service-pause').textContent === '恢复自动任务');
  assert.equal(await page.locator('#next-capture').innerText(),'已暂停');
  const configPath = path.join(root,'data/config.json');
  const config = fs.existsSync(configPath) ? JSON.parse(fs.readFileSync(configPath, 'utf8')) : {};
  assert.equal(config.schedule?.enabled ?? true, true);
  await page.reload(); await page.locator('#advanced-settings').evaluate(e => e.open = true);
  await page.getByRole('button',{name:'恢复自动任务',exact:true}).waitFor();
  await page.locator('#service-pause').click(); await page.getByRole('button',{name:'暂停自动任务',exact:true}).waitFor();
  // Settings changes must be saved before a deliberate service action.
  await page.locator('#interval').fill('365');
  await page.locator('#service-restart').click();
  assert.match(await page.locator('#toast').innerText(),/请先保存设置/);
  await page.reload(); await page.locator('#advanced-settings').evaluate(e => e.open = true);
  // Pause survives a real process restart, and the page receives a fresh CSRF key.
  await page.locator('#service-pause').click(); await page.getByRole('button',{name:'恢复自动任务',exact:true}).waitFor();
  const first = await (await fetch(base+'/api/status')).json();
  const csrf = await page.locator('meta[name="archive-key"]').getAttribute('content');
  // A browser on a remote origin is proxied to the real server with a
  // non-local Host, so both pairing and authorization use the actual backend.
  const remote = await browser.newPage({viewport:{width:390,height:900}});
  remote.on('pageerror', error => errors.push(error.message));
  let remoteOffline = false;
  let remoteNavigations = 0;
  let rejectedStaleKeys = 0;
  remote.on('framenavigated', frame => { if (frame === remote.mainFrame()) remoteNavigations++; });
  await remote.route('http://192.168.50.10/**',async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (remoteOffline && url.pathname === '/api/status') { await route.abort('connectionrefused'); return; }
    const original = await request.allHeaders();
    const headers = {Host:`127.0.0.2:${port}`};
    for (const key of ['cookie','x-archive-key','content-type']) if (original[key]) headers[key] = original[key];
    if (original.origin) headers.Origin = `http://127.0.0.2:${port}`;
    try {
      const response = await remote.request.fetch(base+url.pathname+url.search, {
        method:request.method(),headers,data:request.postDataBuffer() || undefined});
      if (response.status() === 403 && (await response.json()).code === 'csrf_expired') rejectedStaleKeys++;
      await route.fulfill({response});
    } catch { await route.abort('connectionrefused'); }
  });
  await remote.goto('http://192.168.50.10/');
  await remote.locator('#login-overlay').waitFor({state:'visible'});
  await remote.locator('#access-code').fill(fs.readFileSync(path.join(root,'data/access-code.txt'),'utf8').trim());
  await remote.locator('#login-button').click();
  await remote.locator('#login-overlay').waitFor({state:'hidden'});
  await remote.locator('#advanced-settings').evaluate(e => e.open = true);
  await remote.locator('#interval').fill('777');
  const remoteKey = await remote.locator('meta[name="archive-key"]').getAttribute('content');
  const remoteCookie = (await remote.context().cookies()).find(cookie => cookie.name === 'archive_session');
  assert.ok(remoteCookie?.httpOnly);
  remoteOffline = true;
  await remote.locator('#refresh-button').click();
  await remote.locator('#connection-alert').waitFor({state:'visible'});
  page.once('dialog', dialog => dialog.accept());
  await page.locator('#service-restart').click();
  await until(async () => (await (await fetch(base+'/api/status')).json()).service.instance !== first.service.instance);
  await page.waitForFunction(old => document.querySelector('meta[name="archive-key"]').content !== old, csrf);
  remoteOffline = false;
  await remote.waitForFunction(old => document.querySelector('meta[name="archive-key"]').content !== old, remoteKey);
  await remote.locator('#connection-alert').waitFor({state:'hidden'});
  assert.equal(await remote.locator('#login-overlay').isVisible(),false);
  assert.equal(remoteNavigations,1, 'Phone must reconnect without reloading');
  assert.equal(await remote.locator('#interval').inputValue(),'777','Unsaved settings must survive');
  assert.equal((await remote.context().cookies()).find(cookie => cookie.name === 'archive_session').value,remoteCookie.value);
  // Force a stale key before the next poll: retry only the rejected request.
  await remote.evaluate(key => {
    document.querySelector('meta[name="archive-key"]').content = key;
    document.querySelector('#service-pause').click();
  },remoteKey);
  await remote.getByRole('button',{name:'暂停自动任务',exact:true}).waitFor();
  assert.equal((await (await fetch(base+'/api/status')).json()).state.automatic_paused,false);
  assert.equal(remoteNavigations,1);
  assert.equal(await remote.locator('#login-overlay').isVisible(),false);
  assert.equal(rejectedStaleKeys,1,'Only the rejected stale-key mutation should be retried');
  const remoteStatus = cookie => new Promise((resolve,reject) => {
    http.get(base+'/api/status',{headers:{Host:`127.0.0.2:${port}`, ...(cookie ? {Cookie:cookie} : {})}},response => {
      response.resume(); resolve(response.statusCode);
    }).on('error',reject);
  });
  assert.equal(await remoteStatus(),401, 'Unpaired devices remain unauthorized');
  assert.equal(await remoteStatus('archive_session=forged'),401);
  await page.locator('#advanced-settings').evaluate(e => e.open = true);
  await page.getByRole('button',{name:'暂停自动任务',exact:true}).waitFor();
  for (const width of [1280,390]) {
    await page.setViewportSize({width,height:900});
    await page.locator('#service-controls').scrollIntoViewIfNeeded();
    assert.equal(await page.locator('body').evaluate(e => e.scrollWidth), width);
    fs.mkdirSync('artifacts/service-controls',{recursive:true});
    await page.screenshot({path:`artifacts/service-controls/${width}.png`});
  }
  assert.equal(await remote.locator('#service-pause').isVisible(),true);
  assert.equal(await remote.locator('#service-restart').isVisible(),false);
  assert.equal(await remote.locator('#service-more').isVisible(),false);
  await remote.close();
  await page.locator('#service-more').evaluate(e => e.open = true);
  page.once('dialog', dialog => dialog.dismiss()); await page.locator('#service-stop').click();
  assert.equal(exited,false);
  page.once('dialog', dialog => dialog.accept()); await page.locator('#service-stop').click();
  await until(() => exited);
  await page.getByText('服务已断开。再次打开 Mac App 或 Start.command 可启动。',{exact:true}).waitFor({timeout:10000});
  await wait(1200); assert.equal(exited,true);
  assert.ok(fs.existsSync(path.join(root,'data/archive.sqlite3')));
  assert.deepEqual(errors,[]);
  console.log('PASS: pause/resume, durable state, unsaved guard, real restart + new CSRF without reload, paired phone automatic reconnect with unchanged cookie and unsaved input, stale-key retry, unpaired/forged-cookie denial, responsive UI, remote layout, stop cancel/confirm + process exit, data preserved.');
} finally {
  await browser?.close();
  if (!exited) { child.kill('SIGTERM'); await until(() => exited,5000).catch(() => child.kill('SIGKILL')); }
  fs.rmSync(root,{recursive:true,force:true});
}
