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

// ─── Segment 3: Create Issue with Echo Hello Template (~50s) ────────────────

async function segment3_createIssue(page: Page): Promise<void> {
  logStep('Segment 3', 'Navigating to Issues page');
  await navigateSidebar(page, '需求', 1500);
  await waitForVisible(page, '[data-testid="issue-list-page"]');
  await pause(1500);

  logStep('Segment 3', 'Clicking Create Issue button');
  await clickWithDelay(page, '[data-testid="issue-list-create-button"]', { prePause: 500, postPause: 1500 });
  await waitForVisible(page, '[data-testid="create-issue-page"]');

  logStep('Segment 3', 'Selecting project');
  const projectSelect = page.locator('[data-testid="create-issue-form"] .n-base-selection').first();
  await projectSelect.click();
  await pause(800);
  await page.locator('.n-base-select-option').first().click();
  await pause(1000);

  logStep('Segment 3', 'Typing issue title');
  const titleInput = page.locator('[data-testid="create-issue-form"]').locator('.n-input').first().locator('input');
  await titleInput.click();
  await pause(300);
  for (const char of 'Demo: Echo Hello 测试') {
    await titleInput.pressSequentially(char, { delay: 0 });
    await pause(60 + Math.random() * 40);
  }
  await pause(800);

  logStep('Segment 3', 'Opening prompt template drawer');
  const templateButton = page.locator('.prompt-label-row').locator('button');
  if (await templateButton.isVisible({ timeout: 3000 }).catch(() => false)) {
    await templateButton.click();
    await pause(1000);

    logStep('Segment 3', 'Selecting Echo Hello template');
    const echoTemplate = page.locator('.prompt-template-dropdown__item').filter({ hasText: /echo/i }).first();
    if (await echoTemplate.isVisible({ timeout: 3000 }).catch(() => false)) {
      await echoTemplate.click();
      await pause(1500);
    } else {
      logStep('Segment 3', '⚠️ Echo Hello template not found, typing manually');
      // Close the drawer first
      await page.keyboard.press('Escape');
      await pause(500);
      await humanTypeCodeMirror(page, '.variable-editor', 'echo "Hello, World!"');
      await pause(1000);
    }
  } else {
    logStep('Segment 3', '⚠️ Template button not found, typing description manually');
    await humanTypeCodeMirror(page, '.variable-editor', 'echo "Hello, World!"');
    await pause(1000);
  }

  logStep('Segment 3', 'Pausing to show complete form');
  await pause(2000);

  logStep('Segment 3', 'Submitting issue');
  await clickWithDelay(page, '[data-testid="create-issue-submit"]', { prePause: 500, postPause: 500 });

  logStep('Segment 3', 'Waiting for issue detail page');
  await page.waitForURL('**/issues/**', { timeout: 15000 });
  await page.waitForLoadState('networkidle');
  await waitForVisible(page, '[data-testid="issue-view-page"]');
  await pause(2000);

  logStep('Segment 3', '✅ Issue created');
}

// ─── Segment 4: Real-Time Task Execution & Results (~60s) ──────────────────

async function segment4_taskExecution(page: Page): Promise<void> {
  logStep('Segment 4', 'On issue detail page, showing initial state');
  await pause(2000);

  logStep('Segment 4', 'Looking for associated task');
  const tasksCard = page.locator('[data-testid="issue-tasks-card"]');
  const tasksVisible = await waitForVisible(page, '[data-testid="issue-tasks-card"]', 15000);

  if (tasksVisible) {
    await pause(1500);
    // Click the first task row in the data table
    logStep('Segment 4', 'Clicking task to view details');
    const taskRow = tasksCard.locator('tbody tr').first();
    if (await taskRow.isVisible({ timeout: 5000 }).catch(() => false)) {
      await taskRow.click();
    } else {
      // Fallback: look for any clickable element with a task ID
      const taskLink = tasksCard.locator('td').first();
      await taskLink.click();
    }
  } else {
    logStep('Segment 4', '⚠️ Tasks card not visible, navigating to tasks list');
    await navigateSidebar(page, '任务', 1500);
    const firstRow = page.locator('.n-data-table tbody tr').first();
    await firstRow.click();
  }

  await page.waitForURL('**/tasks/**', { timeout: 10000 });
  await page.waitForLoadState('networkidle');
  await pause(1500);

  logStep('Segment 4', 'Monitoring task status changes');

  const maxWaitMs = 120_000;
  const pollIntervalMs = 3000;
  let elapsed = 0;
  let completed = false;
  let hasScrolledToLogs = false;

  while (elapsed < maxWaitMs) {
    const statusTag = page.locator('[data-testid="task-view-page"]').locator('.n-tag').first();
    const statusText = (await statusTag.textContent().catch(() => '')) || '';
    logStep('Segment 4', `Current status: ${statusText.trim()}`);

    // Check terminal states
    if (/完成|completed|COMPLETED/i.test(statusText)) {
      completed = true;
      break;
    }
    if (/失败|failed|FAILED/i.test(statusText)) {
      logStep('Segment 4', '⚠️ Task failed, continuing with result display');
      completed = true;
      break;
    }

    // Show live logs when running
    if (!hasScrolledToLogs && /运行|running|RUNNING/i.test(statusText)) {
      const processPanel = page.locator('.task-process-panel');
      if (await processPanel.isVisible({ timeout: 2000 }).catch(() => false)) {
        logStep('Segment 4', 'Scrolling to process panel for live logs');
        await scrollIntoView(page, '.task-process-panel', 500);
        await pause(8000); // Let viewer see live log streaming
        hasScrolledToLogs = true;
      }
    }

    await pause(pollIntervalMs);
    // Refresh to get updated status
    await page.reload();
    await page.waitForLoadState('networkidle');
    elapsed += pollIntervalMs + 2000;
  }

  if (completed) {
    logStep('Segment 4', 'Task completed! Showing results');
    await pause(3000);

    await scrollToTop(page, 1000);
    await pause(1500);

    // Scroll through result info
    await smoothScroll(page, 300, 1500);
    await pause(2000);

    // Show result panel if present
    const resultPanel = page.locator('.task-result-panel');
    if (await resultPanel.isVisible({ timeout: 3000 }).catch(() => false)) {
      await scrollIntoView(page, '.task-result-panel', 2000);
    }
  } else {
    logStep('Segment 4', '⚠️ Task did not complete within timeout');
    await pause(2000);
  }

  // Navigate back to issue to show branch flow
  logStep('Segment 4', 'Navigating back to issue detail');
  await page.goBack();
  await page.waitForLoadState('networkidle');
  await waitForVisible(page, '[data-testid="issue-view-page"]', 5000);
  await pause(2000);

  logStep('Segment 4', '✅ Task execution segment complete');
}

// ─── Segment 5: Monitoring & Analytics (~45s) ──────────────────────────────

async function segment5_monitoring(page: Page): Promise<void> {
  logStep('Segment 5', 'Navigating to Monitor page');
  await navigateSidebar(page, '监控', 2000);
  await page.waitForLoadState('networkidle');
  await pause(2500);

  logStep('Segment 5', 'Showing monitor overview and Kanban view');
  await smoothScroll(page, 300, 1500);
  await pause(2000);
  await scrollToTop(page, 1000);

  logStep('Segment 5', 'Navigating to Analytics page');
  await navigateSidebar(page, '统计分析', 2000);
  await page.waitForLoadState('networkidle');
  await pause(2500);

  logStep('Segment 5', 'Scrolling through trend charts');
  await smoothScroll(page, 500, 2000);
  await pause(2000);
  await smoothScroll(page, 400, 1500);
  await pause(1500);
  await scrollToTop(page, 1000);

  logStep('Segment 5', 'Navigating to Schedule Overview page');
  await navigateSidebar(page, '调度总览', 2000);
  await page.waitForLoadState('networkidle');
  await pause(2500);

  logStep('Segment 5', '✅ Monitoring & analytics segment complete');
}

// ─── Segment 6: Configuration & Management (~30s) ──────────────────────────

async function segment6_configuration(page: Page): Promise<void> {
  logStep('Segment 6', 'Navigating to Access Management page');
  await navigateSidebar(page, '访问管理', 2000);
  await page.waitForLoadState('networkidle');
  await pause(2000);

  await smoothScroll(page, 200, 1000);
  await pause(1500);
  await scrollToTop(page, 800);

  logStep('Segment 6', 'Navigating to Configuration page');
  await navigateSidebar(page, '系统配置', 2000);
  await page.waitForLoadState('networkidle');
  await pause(2000);

  logStep('Segment 6', 'Switching config tabs');
  // Try clicking AI Providers tab
  const tabs = page.locator('.n-tabs .n-tabs-tab');
  const tabCount = await tabs.count();
  if (tabCount >= 3) {
    // Click the 3rd tab (typically AI Providers or similar)
    await tabs.nth(2).click();
    await pause(1500);
    // Click another tab (GitLab settings)
    await tabs.nth(1).click();
    await pause(1500);
  }

  logStep('Segment 6', 'Final pause for closing shot');
  await pause(2000);

  logStep('Segment 6', '✅ Configuration segment complete');
}

main().catch(console.error);
