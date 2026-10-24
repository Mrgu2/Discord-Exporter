// No Discord, credentials, or real API mutations: fictional first-run states.
import assert from 'node:assert/strict';
import {loadPlaywright, browserOptions} from '../scripts/browser_runtime.mjs';
const playwright = await loadPlaywright({localOnly:true});
const browser = await playwright.chromium.launch({headless:true, ...browserOptions(playwright)});
const base = process.argv[2] || 'http://127.0.0.1:18876';
assert.equal(new URL(base).hostname, '127.0.0.1');
try {
  for (const width of [390, 1360]) {
    const page = await browser.newPage({viewport:{width,height:900}});
    const data = {config:{channels:[],target_author_id:'',target_message_url:'',speech:{enabled:false},schedule:{enabled:false},model:{}},
      credentials:{discord:false}, archive:{message_count:0},state:{},drafts:[],runs:[],remote:{}};
    let mutations = 0;
    await page.route('**/api/**', route => {
      if (route.request().method() !== 'GET') mutations++;
      return route.fulfill({json:data});
    });
    await page.goto(`${base}/web/index.html`);
    await page.locator('#setup-alert').waitFor({state:'visible'});
    assert.equal(await page.locator('#setup-action').textContent(), '连接 Discord');
    assert.equal(await page.locator('#capture-button').isDisabled(), true);
    data.credentials.discord = true;
    await page.locator('#refresh-button').click();
    await page.waitForFunction(() => document.querySelector('#setup-action').textContent === '添加频道与答疑人');
    await page.locator('#setup-action').click();
    assert.equal(await page.locator('#advanced-settings').getAttribute('open'), '');
    assert.equal(await page.locator('#channels').evaluate(el => el === document.activeElement), true);
    await page.locator('#channels').fill('https://discord.com/channels/8000/101/10001');
    await page.locator('#target-message-url').fill('https://discord.com/channels/8000/101/10001');
    // Configuration stays fictional even on submit.
    await page.route('**/api/config', async route => {
      if (route.request().method() !== 'GET') {
        mutations++;
        Object.assign(data.config, route.request().postDataJSON());
      }
      await route.fulfill({json:{config:data.config}});
    });
    await page.locator('#setup-save').click();
    await page.waitForFunction(() => document.querySelector('#config-save-status').textContent === '设置已保存。');
    await page.locator('#refresh-button').click();
    await page.locator('#setup-alert').waitFor({state:'hidden'});
    assert.equal(data.config.channels[0].id, '101');
    await page.waitForFunction(() => !document.querySelector('#advanced-settings').open);
    assert.equal(await page.locator('#capture-button').isEnabled(), true);
    assert.equal(mutations, 1);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await page.screenshot({path:`artifacts/onboarding-${width}.png`,fullPage:true});
    await page.close();
  }
  console.log('首次配置：空白安装、登录后引导、配置保存、桌面与手机宽度均通过。');
} finally { await browser.close(); }
