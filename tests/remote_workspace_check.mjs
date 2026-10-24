// Real private HTTPS workspace and first-connection entry. No credential submission or capture.
import assert from 'node:assert/strict';
import {loadPlaywright,browserOptions} from '../scripts/browser_runtime.mjs';
const origin=new URL(process.argv[2]).origin;
assert.ok(origin.startsWith('https://')&&new URL(origin).hostname.endsWith('.ts.net'));
const p=await loadPlaywright({localOnly:true}),browser=await p.chromium.launch({headless:true,...browserOptions(p)});
try{
 for(const width of [390,1360]){
  const context=await browser.newContext({viewport:{width,height:1000},proxy:{server:'http://127.0.0.1:9',bypass:'*'}}),page=await context.newPage();
  await page.goto(origin);
  await page.waitForFunction(()=>!document.querySelector('#service-restart').hidden);
  assert.equal(await page.locator('#login-overlay').isHidden(),true);
  assert.equal(await page.locator('#connect-browser-button').isEnabled(),true);
  await page.locator('#connect-browser-button').click();
  await page.locator('#helper-downloads').waitFor({state:'visible'});
  assert.equal(await page.locator('#legacy-binding').isHidden(),true);
  assert.equal(await page.locator('#connect-browser-fallback').isHidden(),true);
  assert.ok((await page.locator('#helper-downloads').textContent()).includes('首次连接 Discord'));
  assert.equal(await page.locator('#helper-downloads a').count(),2);
  assert.equal(await page.locator('#helper-authorization').isVisible(),false);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:`artifacts/remote-workspace-final-${width}.png`,fullPage:true});
  await context.close();
 }
 console.log('真实 Tailscale HTTPS：本人身份自动识别、390/1360 工作台、首次连接说明、平台下载入口与无配对弹窗检查通过；未提交凭证或采集。');
}finally{await browser.close();}
