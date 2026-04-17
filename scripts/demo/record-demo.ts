import { chromium, Browser, BrowserContext, Page } from 'playwright';
import * as dotenv from 'dotenv';
import * as path from 'path';
import * as fs from 'fs';
import {
  pause, humanType, smoothScroll, scrollToTop, scrollIntoView,
  clickWithDelay, navigateSidebar, waitForVisible, selectNaiveOption,
  humanTypeCodeMirror, logStep
} from './helpers';

dotenv.config();

const BASE_URL = process.env.DEMO_URL || 'http://192.168.50.129:8880';
const USERNAME = process.env.DEMO_USERNAME || 'admin';
const PASSWORD = process.env.DEMO_PASSWORD || '';

if (!PASSWORD) {
  console.error('❌ DEMO_PASSWORD environment variable is required');
  process.exit(1);
}

const VIDEO_DIR = path.resolve(__dirname, '../../videos');

async function main() {
  fs.mkdirSync(VIDEO_DIR, { recursive: true });

  console.log('🎬 Starting Codify demo recording...');
  console.log(`   URL: ${BASE_URL}`);
  console.log(`   Resolution: 1920x1080`);
  console.log(`   Output: ${VIDEO_DIR}/`);

  const browser = await chromium.launch({
    headless: true,
    args: ['--disable-dev-shm-usage', '--no-sandbox'],
  });

  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    locale: 'zh-CN',
    recordVideo: {
      dir: VIDEO_DIR,
      size: { width: 1920, height: 1080 },
    },
  });

  const page = await context.newPage();

  try {
    await segment1_login(page);
    await segment2_dashboard(page);
    await segment3_createIssue(page);
    await segment4_taskExecution(page);
    await segment5_monitoring(page);
    await segment6_configuration(page);

    console.log('✅ Demo recording completed!');
  } catch (error) {
    console.error('❌ Recording failed:', error);
  } finally {
    await page.close();
    await context.close();
    await browser.close();

    // Find and rename the video file
    const files = fs.readdirSync(VIDEO_DIR).filter(f => f.endsWith('.webm'));
    if (files.length > 0) {
      const latest = files.sort().pop()!;
      const src = path.join(VIDEO_DIR, latest);
      const dest = path.join(VIDEO_DIR, 'codify-demo.webm');
      if (fs.existsSync(dest)) fs.unlinkSync(dest);
      fs.renameSync(src, dest);
      console.log(`📁 Video saved to: ${dest}`);
    }
  }
}

// ─── Segment 1: Login (~20s) ───────────────────────────────────────────────

async function segment1_login(page: Page): Promise<void> {
  logStep('Segment 1', 'Navigating to login page');
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');
  await waitForVisible(page, '[data-testid="login-page"]');

  logStep('Segment 1', 'Showing login page');
  await pause(2500);

  // Check if language needs switching to Chinese
  const htmlLang = await page.locator('html').getAttribute('lang');
  logStep('Segment 1', `Current lang: ${htmlLang}`);

  logStep('Segment 1', 'Typing username');
  await humanType(page, '[data-testid="login-username-input"] input', USERNAME);
  await pause(500);

  logStep('Segment 1', 'Typing password');
  await humanType(page, '[data-testid="login-password-input"] input', PASSWORD);
  await pause(500);

  logStep('Segment 1', 'Clicking login button');
  await clickWithDelay(page, '[data-testid="login-submit-button"]', { prePause: 500, postPause: 300 });

  logStep('Segment 1', 'Waiting for dashboard');
  await page.waitForURL('**/dashboard', { timeout: 10000 });
  await page.waitForLoadState('networkidle');
  await pause(2000);

  logStep('Segment 1', '✅ Login complete');
}

// ─── Segment 2: Dashboard Overview (~45s) ──────────────────────────────────

async function segment2_dashboard(page: Page): Promise<void> {
  logStep('Segment 2', 'Viewing dashboard summary cards');
  await waitForVisible(page, '[data-testid="dashboard-summary"]');
  await pause(3000);

  logStep('Segment 2', 'Scrolling to activity heatmap and trend chart');
  await smoothScroll(page, 500, 2000);
  await pause(2500);

  logStep('Segment 2', 'Scrolling to work board');
  await smoothScroll(page, 400, 1500);
  await pause(2000);

  logStep('Segment 2', 'Scrolling back to top');
  await scrollToTop(page, 1500);

  logStep('Segment 2', '✅ Dashboard overview complete');
}

// ─── Placeholder segments (to be implemented in subsequent tasks) ──────────

async function segment3_createIssue(page: Page): Promise<void> {
  logStep('Segment 3', '⏳ Placeholder — will be implemented in Task 4');
}

async function segment4_taskExecution(page: Page): Promise<void> {
  logStep('Segment 4', '⏳ Placeholder — will be implemented in Task 5');
}

async function segment5_monitoring(page: Page): Promise<void> {
  logStep('Segment 5', '⏳ Placeholder — will be implemented in Task 6');
}

async function segment6_configuration(page: Page): Promise<void> {
  logStep('Segment 6', '⏳ Placeholder — will be implemented in Task 7');
}

main().catch(console.error);
