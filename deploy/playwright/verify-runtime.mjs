#!/usr/bin/env node
import { constants } from 'node:fs';
import { access } from 'node:fs/promises';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const packageJson = require('/node_modules/@playwright/test/package.json');
const { chromium, firefox, webkit } = require('/node_modules/@playwright/test');
const expectedVersion = process.env.PLAYWRIGHT_VERSION;
const launchBrowsers = process.argv.includes('--launch');

if (!expectedVersion) {
  throw new Error('PLAYWRIGHT_VERSION is not set');
}
if (packageJson.version !== expectedVersion) {
  throw new Error(
    `Playwright package ${packageJson.version} does not match image ${expectedVersion}`,
  );
}

for (const [name, browserType] of Object.entries({ chromium, firefox, webkit })) {
  const executablePath = browserType.executablePath();
  await access(executablePath, constants.X_OK);

  if (launchBrowsers) {
    const browser = await browserType.launch({ headless: true });
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

  console.log(`${name}: ${launchBrowsers ? 'launch ok' : executablePath}`);
}

console.log(`Playwright ${packageJson.version} runtime verification passed`);
