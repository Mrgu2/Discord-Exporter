import {loadPlaywright, browserOptions} from './browser_runtime.mjs';
try {
  const playwright = await loadPlaywright({localOnly:true});
  const browser = await playwright.chromium.launch({headless:true, ...browserOptions(playwright)});
  try {
    const page = await browser.newPage();
    await page.setContent('<p>安装检查 · Browser ready</p>');
    if (!(await page.screenshot()).length) throw new Error('浏览器绘图失败');
  } finally { await browser.close(); }
  console.log('浏览器启动及绘图通过');
} catch (error) { console.error(error.message); process.exitCode = 1; }
