// Shared by login, rendering, and installation checks.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require = createRequire(import.meta.url);
export async function loadPlaywright({localOnly = false} = {}) {
  try { return require('playwright'); } catch {}
  if (!localOnly) {
    for (const candidate of [process.env.PLAYWRIGHT_MODULE,
      path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js')].filter(Boolean)) {
      try { const module = await import(pathToFileURL(candidate).href); return module.default || module; } catch {}
    }
  }
  throw new Error('缺少项目浏览器工具，请双击 Install.command 完成安装。');
}
export function browserOptions(playwright) {
  const explicit = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  if (explicit) {
    if (!fs.existsSync(explicit)) throw new Error('指定的浏览器不存在，请检查 PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH。');
    return {executablePath: explicit};
  }
  // The installer supplies this browser; Chrome is an optional fallback.
  if (fs.existsSync(playwright.chromium.executablePath())) return {};
  const executablePath = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'].find(file => fs.existsSync(file));
  if (executablePath) return {executablePath};
  throw new Error('缺少浏览器，请重新运行 Install.command 安装 Chromium。');
}
