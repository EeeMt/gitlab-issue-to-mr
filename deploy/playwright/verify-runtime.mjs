#!/usr/bin/env node
import { constants } from 'node:fs';
import { access } from 'node:fs/promises';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const packageJson = require('/node_modules/@playwright/test/package.json');
const { chromium, firefox, webkit } = require('/node_modules/@playwright/test');
const expectedVersion = process.env.PLAYWRIGHT_VERSION;
const launchBrowsers = process.argv.includes('--launch');
const headed = process.argv.includes('--headed');

const runtimePaths = [
  ['/usr/bin/Xvfb', constants.X_OK],
  ['/usr/bin/fluxbox', constants.X_OK],
  ['/usr/bin/x11vnc', constants.X_OK],
  ['/usr/bin/websockify', constants.X_OK],
  ['/usr/bin/xterm', constants.X_OK],
  ['/usr/share/novnc/vnc.html', constants.R_OK],
  ['/usr/local/bin/playwright-ui', constants.X_OK],
  ['/usr/local/bin/playwright-desktop', constants.X_OK],
];

if (!expectedVersion) {
  throw new Error('PLAYWRIGHT_VERSION is not set');
}
if (packageJson.version !== expectedVersion) {
  throw new Error(
    `Playwright package ${packageJson.version} does not match image ${expectedVersion}`,
  );
}
if (headed && !launchBrowsers) {
  throw new Error('--headed requires --launch');
}

for (const [path, mode] of runtimePaths) {
  await access(path, mode);
}

for (const [name, browserType] of Object.entries({ chromium, firefox, webkit })) {
  const executablePath = browserType.executablePath();
  await access(executablePath, constants.X_OK);

  if (launchBrowsers) {
    const browser = await browserType.launch({ headless: !headed });
    try {
      const page = await browser.newPage();
      await page.setContent(`<title>${name}</title><main>runtime-ok</main>`);
      const content = await page.locator('main').textContent();
      if (content !== 'runtime-ok') {
        throw new Error(`${name} smoke page returned unexpected content: ${content}`);
      }
    } finally {
      await browser.close();
    }
  }

  const launchMode = headed ? 'headed launch ok' : 'headless launch ok';
  console.log(`${name}: ${launchBrowsers ? launchMode : executablePath}`);
}

console.log('Playwright UI and noVNC desktop paths are available');
console.log(`Playwright ${packageJson.version} runtime verification passed`);
