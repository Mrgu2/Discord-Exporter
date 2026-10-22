// Browser acceptance with fictional status and intercepted mutations only.
// The running service supplies the actual HTML/CSS/JS; no real data is changed.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
let playwright;
try { playwright = require('playwright'); }
catch { playwright = require(process.env.PLAYWRIGHT_MODULE || path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')); }
const base = process.argv[2] || 'http://127.0.0.1:8765';
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(base).hostname));
const directory = path.resolve('artifacts/design-a');
fs.mkdirSync(directory, {recursive: true});
function fixture() {
  return {
    config: {
      channels: ['盘前答疑', '尾盘补充', '每周回顾', '宏观与市场观察的长名称频道', '自由讨论'].map((label, i) => ({id: String(i + 1), label, enabled: true})),
      target_author_id: '123456', timezone: 'auto', market_timezone: 'America/New_York', day_boundary_hour: 4,
      schedule: {enabled: true, interval_minutes: 360, times: [], window: {enabled: true, start: '15:50', end: '16:10', every_minutes: 5}}, model: {enabled: false}
    },
    state: {market_day: '2026-10-21', last_success_at: '2026-10-22T01:12:00Z', next_capture_at: '2026-10-22T07:12:00Z'},
    connectivity: {online: true}, credentials: {discord: true, model: false},
    archive: {message_count: 84, channel_count: 5, attachment_count: 2, attachment_failures: 0},
    drafts: [
      {id: 'fictional-one', title: '演示 · 10 月 21 日尾盘答疑', created_at: '2026-10-22T01:20:00Z', status: 'ready', scope: 'day', date: '2026-10-21', message_count: 46, mode: 'evidence', layout: 'stacked'},
      {id: 'fictional-two', title: '演示 · 多个频道的每周回顾与后续补充核对记录', created_at: '2026-10-21T13:40:00Z', status: 'ready', scope: 'latest', message_count: 32, mode: 'evidence', layout: 'qa'},
      {id: 'fictional-failed', title: '演示 · 未完成的稿件', created_at: '2026-10-21T12:00:00Z', status: 'failed', error: '演示错误：请重试生成。'}
    ],
    runs: [{status: 'success', started_at: '2026-10-22T01:12:00Z', message_count: 84}], remote: {}
  };
}
const browser = await playwright.chromium.launch({headless: true, executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const results = [];
try {
  for (const width of [320, 390, 768, 1360, 1920]) {
    let data = fixture();
    const mutations = [], errors = [];
    const context = await browser.newContext({viewport: {width, height: 900}, timezoneId: 'Asia/Shanghai', reducedMotion: 'reduce'});
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/api/**', async route => {
      const request = route.request(), endpoint = new URL(request.url()).pathname;
      if (request.method() !== 'GET') mutations.push({endpoint, body: request.postDataJSON()});
      if (endpoint === '/api/config' && request.method() === 'PUT') {
        data.config = request.postDataJSON();
        return route.fulfill({json: data.config});
      }
      if (endpoint === '/api/status') return route.fulfill({json: data});
      return route.fulfill({json: {queued: true}});
    });
    await page.goto(base, {waitUntil: 'networkidle'});
    await page.waitForFunction(() => document.querySelectorAll('.channel-option').length === 5);
    const noOverflow = async label => assert.equal(await page.locator('body').evaluate(e => e.scrollWidth), width, `${width}px: ${label} overflowed`);
    await noOverflow('workspace');
    assert.equal(await page.locator('#draft-layout').inputValue(), 'stacked');
    assert.match(await page.locator('#draft-options-label').innerText(), /上下分区拼图/);
    assert.match(await page.locator('#recent-drafts .draft-row').first().innerText(), /上下分区拼图/);
    assert.equal(await page.locator('#draft-layout option[value="horizontal"]').count(), 1);
    assert.equal(await page.locator('#capture-button').isEnabled(), true);
    assert.equal(await page.locator('#draft-button').isEnabled(), true);
    assert.match(await page.locator('#connection-state').innerText(), /已连接/);
    assert.equal(await page.locator('#connection-detail').isVisible(), false);
    assert.equal(await page.locator('#capture-hint').isVisible(), false);
    const target = await page.locator('.channel-option').first().boundingBox();
    assert.ok(target.height >= 44, 'Channel target too small');
    await page.locator('.channel-option input').first().focus();
    await page.keyboard.press('Space');
    await page.waitForFunction(() => document.querySelector('#capture-badge').textContent === '4 个已选');
    assert.equal(mutations.at(-1).endpoint, '/api/config');
    assert.equal(mutations.at(-1).body.channels[0].enabled, false);
    await page.locator('.draft-options > summary').click();
    await page.locator('input[name="scope"][value="range"]').check();
    await page.locator('#range-fields').waitFor({state: 'visible'});
    await page.locator('#draft-start').fill('2026-10-20');
    await page.locator('#draft-end').fill('2026-10-21');
    await page.locator('#draft-title').fill('演示：范围稿件');
    await noOverflow('expanded draft options');
    await page.locator('#draft-button').click();
    await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('整理任务已提交'));
    const draftRequest = mutations.find(m => m.endpoint === '/api/drafts');
    assert.deepEqual(draftRequest.body, {scope: 'range', mode: 'evidence', format: 'both', layout: 'stacked', presentation: 'reading', title: '演示：范围稿件', start: '2026-10-20', end: '2026-10-21'});
    await page.locator('.draft-options > summary').click();
    await page.locator('[data-view="library"]').click();
    assert.equal(await page.locator('#all-drafts .draft-row').count(), 3);
    assert.equal(await page.locator('#page-title').innerText(), '我的稿件');
    await page.locator('#draft-search').fill('每周回顾');
    assert.equal(await page.locator('#all-drafts .draft-row').count(), 1);
    await page.locator('#draft-search').fill('不存在的关键词');
    assert.match(await page.locator('#all-drafts').innerText(), /没有找到匹配/);
    await page.locator('#draft-search').fill('');
    await page.locator('.history-section > summary').click();
    await noOverflow('library and history');
    await page.locator('.advanced-settings > summary').click();
    await page.locator('#timezone').waitFor({state: 'visible'});
    await noOverflow('settings');
    await page.locator('.advanced-settings > summary').click();
    await page.locator('[data-view="workspace"]').click();
    const contrast = await page.evaluate(() => {
      const styles = getComputedStyle(document.documentElement);
      const luminance = hex => {
        const channels = hex.trim().replace('#', '').match(/../g).map(v => parseInt(v, 16) / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
        return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
      };
      return Object.fromEntries(['--ink', '--muted', '--accent'].map(token => [token, 1.05 / (luminance(styles.getPropertyValue(token)) + .05)]));
    });
    for (const [token, ratio] of Object.entries(contrast)) assert.ok(ratio >= 4.5, `${token} contrast ${ratio}`);
    // Screenshots explicitly contain fictional manuscripts, never real archive content.
    await page.evaluate(() => { document.activeElement.blur(); document.querySelector('#toast').hidden = true; window.scrollTo(0, 0); });
    await page.screenshot({path: path.join(directory, `workspace-${width}.png`), fullPage: true});
    // Exercise truthful empty, offline, busy and login presentation, all via fixtures.
    data = {...fixture(), drafts: [], credentials: {discord: false}, connectivity: {online: false}};
    await page.locator('#refresh-button').click();
    await page.waitForFunction(() => document.querySelector('#capture-button').disabled);
    assert.match(await page.locator('#recent-drafts').innerText(), /还没有稿件/);
    await noOverflow('offline empty state');
    data = {...fixture(), state: {active_job: {id: 'fictional-job', message: '演示 · 正在保存对话'}}};
    await page.locator('#refresh-button').click();
    await page.locator('#active-job').waitFor({state: 'visible'});
    assert.equal(await page.locator('#capture-hint').isVisible(), true);
    assert.equal(await page.locator('#draft-button').isDisabled(), true);
    await page.route('**/api/status', route => route.fulfill({status: 401, json: {error: '演示：需要访问口令'}}));
    await page.locator('#refresh-button').click();
    await page.locator('#login-overlay').waitFor({state: 'visible'});
    assert.equal(await page.locator('.app-shell').evaluate(e => e.inert), true);
    await noOverflow('login');
    assert.deepEqual(errors, []);
    results.push({width, overflow: false, intercepted_mutations: mutations.length, scope_submission: 'passed', channel_keyboard: 'passed', search: 'passed', states: 'passed', contrast});
    await context.close();
  }
  const report = {status: 'passed', data: 'fictional; all API mutations intercepted', results};
  fs.writeFileSync(path.join(directory, 'acceptance.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} finally { await browser.close(); }
