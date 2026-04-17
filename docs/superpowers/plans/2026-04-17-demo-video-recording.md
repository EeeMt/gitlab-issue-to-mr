# Demo Video Recording Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a Playwright script that records a 4-5 minute demo video of the Codify system, showcasing login → Dashboard → create Issue (Echo Hello) → real-time task execution → monitoring/analytics → configuration pages.

**Architecture:** A standalone TypeScript Playwright script (`scripts/demo/`) with helper utilities for human-like interactions (typing, scrolling, pausing). Uses Playwright's built-in video recording at 1920×1080. The script targets the dev environment at `http://192.168.50.129:8880/` and reads credentials from environment variables.

**Tech Stack:** Playwright (npm `@playwright/test`), TypeScript, ts-node

---

## File Structure

```
scripts/demo/
  record-demo.ts       — Main recording script (orchestrates all 6 segments)
  helpers.ts           — Human-like interaction utilities
  package.json         — Dependencies (playwright, ts-node, typescript)
  tsconfig.json        — TypeScript config
  .env.example         — Example environment variables
```

Output: `videos/codify-demo.webm`

---

## Reference: Key Selectors

These selectors are used throughout the tasks below. Derived from existing E2E tests and Vue component source:

| Element | Selector |
|---------|----------|
| Login page | `[data-testid="login-page"]` |
| Username input | `[data-testid="login-username-input"]` |
| Password input | `[data-testid="login-password-input"]` |
| Login button | `[data-testid="login-submit-button"]` |
| Dashboard page | `[data-testid="dashboard-page"]` |
| Dashboard summary | `[data-testid="dashboard-summary"]` |
| Activity heatmap | `[data-testid="dashboard-activity-heatmap"]` |
| Trend chart | `[data-testid="dashboard-trend-chart"]` |
| Sidebar menu | `.nav-menu` |
| Issue list page | `[data-testid="issue-list-page"]` |
| Issue create button | `[data-testid="issue-list-create-button"]` |
| Create issue page | `[data-testid="create-issue-page"]` |
| Create issue form | `[data-testid="create-issue-form"]` |
| Create issue submit | `[data-testid="create-issue-submit"]` |
| Issue view page | `[data-testid="issue-view-page"]` |
| Issue tasks card | `[data-testid="issue-tasks-card"]` |
| Task view page | `[data-testid="task-view-page"]` |
| Task process panel | `.task-process-panel` |
| Task result panel | `.task-result-panel` |
| Config tabs | NaiveUI `.n-tabs` inside config page |

Sidebar navigation: `page.locator('.nav-menu').getByText('菜单文本')` — use Chinese menu text since UI is in zh-CN.

Menu text mapping (zh-CN):
- Dashboard → `仪表盘`
- Issues → `议题`
- Tasks → `任务`
- Monitor → `监控`
- Analytics → `分析`
- Schedule Overview → `排期概览`
- Access Management → `访问管理`
- Configuration → `配置`

---

### Task 1: Project Scaffolding

**Files:**
- Create: `scripts/demo/package.json`
- Create: `scripts/demo/tsconfig.json`
- Create: `scripts/demo/.env.example`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "codify-demo-recorder",
  "private": true,
  "scripts": {
    "record": "npx playwright install chromium && npx ts-node record-demo.ts"
  },
  "dependencies": {
    "playwright": "^1.52.0",
    "ts-node": "^10.9.2",
    "typescript": "^5.4.0",
    "dotenv": "^16.4.0"
  }
}
```

- [ ] **Step 2: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "commonjs",
    "esModuleInterop": true,
    "strict": true,
    "outDir": "./dist",
    "rootDir": ".",
    "resolveJsonModule": true
  },
  "include": ["*.ts"]
}
```

- [ ] **Step 3: Create .env.example**

```bash
DEMO_URL=http://192.168.50.129:8880
DEMO_USERNAME=admin
DEMO_PASSWORD=your_password_here
```

- [ ] **Step 4: Install dependencies**

```bash
cd scripts/demo && npm install
```

Run: `cd scripts/demo && npm install`
Expected: `added N packages` with no errors.

- [ ] **Step 5: Install Playwright browsers**

```bash
cd scripts/demo && npx playwright install chromium
```

Run: `cd scripts/demo && npx playwright install chromium`
Expected: `Downloading chromium ... done`

- [ ] **Step 6: Commit scaffolding**

```bash
git add scripts/demo/package.json scripts/demo/tsconfig.json scripts/demo/.env.example
git commit -m "chore: scaffold demo video recording project

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Helper Utilities

**Files:**
- Create: `scripts/demo/helpers.ts`

- [ ] **Step 1: Create helpers.ts with all utility functions**

```typescript
import { Page } from 'playwright';

/**
 * Pause execution for the given duration.
 * Use for deliberate pauses that let the viewer absorb information.
 */
export async function pause(ms: number): Promise<void> {
  await new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Type text character-by-character with human-like delays.
 * Each character is typed with a random delay between minDelay and maxDelay ms.
 */
export async function humanType(
  page: Page,
  selector: string,
  text: string,
  { minDelay = 60, maxDelay = 100 }: { minDelay?: number; maxDelay?: number } = {}
): Promise<void> {
  const element = page.locator(selector);
  await element.click();
  for (const char of text) {
    await element.pressSequentially(char, { delay: 0 });
    const delay = minDelay + Math.random() * (maxDelay - minDelay);
    await pause(delay);
  }
}

/**
 * Type into a CodeMirror 6 editor (used for description/prompt fields).
 * Clicks the editor to focus, then types character-by-character.
 */
export async function humanTypeCodeMirror(
  page: Page,
  selector: string,
  text: string,
  { minDelay = 40, maxDelay = 80 }: { minDelay?: number; maxDelay?: number } = {}
): Promise<void> {
  const editor = page.locator(selector).locator('.cm-content');
  await editor.click();
  for (const char of text) {
    await page.keyboard.type(char, { delay: 0 });
    const delay = minDelay + Math.random() * (maxDelay - minDelay);
    await pause(delay);
  }
}

/**
 * Smooth scroll the page by deltaY pixels over the given duration.
 * Breaks the scroll into small increments for a smooth visual effect.
 */
export async function smoothScroll(
  page: Page,
  deltaY: number,
  durationMs: number = 2000
): Promise<void> {
  const steps = 30;
  const stepDelay = durationMs / steps;
  const stepDelta = deltaY / steps;
  for (let i = 0; i < steps; i++) {
    await page.mouse.wheel(0, stepDelta);
    await pause(stepDelay);
  }
}

/**
 * Scroll to top of page smoothly.
 */
export async function scrollToTop(page: Page, durationMs: number = 1500): Promise<void> {
  await page.evaluate(() => {
    const scrollContainer = document.querySelector('.n-layout-scroll-container') || document.documentElement;
    scrollContainer.scrollTo({ top: 0, behavior: 'smooth' });
  });
  await pause(durationMs);
}

/**
 * Scroll a specific element into view smoothly.
 */
export async function scrollIntoView(page: Page, selector: string, pauseAfterMs: number = 1000): Promise<void> {
  await page.locator(selector).first().evaluate(el => {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
  await pause(pauseAfterMs);
}

/**
 * Click an element with a natural pre-click pause and post-click settle time.
 */
export async function clickWithDelay(
  page: Page,
  selector: string,
  { prePause = 300, postPause = 500 }: { prePause?: number; postPause?: number } = {}
): Promise<void> {
  await pause(prePause);
  await page.locator(selector).click();
  await pause(postPause);
}

/**
 * Click a sidebar navigation menu item by its Chinese label text.
 * Waits for navigation to settle after clicking.
 */
export async function navigateSidebar(
  page: Page,
  menuText: string,
  waitMs: number = 2000
): Promise<void> {
  await pause(500);
  const menuItem = page.locator('.nav-menu').getByText(menuText, { exact: true });
  await menuItem.click();
  await page.waitForLoadState('domcontentloaded');
  await pause(waitMs);
}

/**
 * Wait for an element matching the selector to appear, with timeout.
 * Returns true if found, false if timed out.
 */
export async function waitForVisible(
  page: Page,
  selector: string,
  timeoutMs: number = 10000
): Promise<boolean> {
  try {
    await page.locator(selector).first().waitFor({ state: 'visible', timeout: timeoutMs });
    return true;
  } catch {
    return false;
  }
}

/**
 * Select an option from a NaiveUI n-select dropdown.
 * Clicks the select trigger, waits for options, then clicks the matching option.
 */
export async function selectNaiveOption(
  page: Page,
  selectSelector: string,
  optionText: string,
  pauseAfterMs: number = 1000
): Promise<void> {
  await page.locator(selectSelector).click();
  await pause(500);
  await page.locator('.n-base-select-option').filter({ hasText: optionText }).first().click();
  await pause(pauseAfterMs);
}

/**
 * Log a step to the console for debugging during recording.
 */
export function logStep(segment: string, step: string): void {
  const timestamp = new Date().toISOString().substring(11, 19);
  console.log(`[${timestamp}] 📹 ${segment}: ${step}`);
}
```

- [ ] **Step 2: Verify helpers.ts compiles**

Run: `cd scripts/demo && npx tsc --noEmit helpers.ts`
Expected: No errors.

- [ ] **Step 3: Commit helpers**

```bash
git add scripts/demo/helpers.ts
git commit -m "feat(demo): add human-like interaction helper utilities

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Main Recording Script — Segments 1 & 2 (Login + Dashboard)

**Files:**
- Create: `scripts/demo/record-demo.ts`

- [ ] **Step 1: Create record-demo.ts with setup, segment 1 (login), and segment 2 (dashboard)**

```typescript
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

// Segments 3-6 are defined below and will be filled in subsequent tasks.

async function segment3_createIssue(page: Page): Promise<void> {
  // TODO: Task 4 will implement this
  logStep('Segment 3', '⏳ Placeholder — will be implemented in Task 4');
}

async function segment4_taskExecution(page: Page): Promise<void> {
  // TODO: Task 5 will implement this
  logStep('Segment 4', '⏳ Placeholder — will be implemented in Task 5');
}

async function segment5_monitoring(page: Page): Promise<void> {
  // TODO: Task 6 will implement this
  logStep('Segment 5', '⏳ Placeholder — will be implemented in Task 6');
}

async function segment6_configuration(page: Page): Promise<void> {
  // TODO: Task 7 will implement this
  logStep('Segment 6', '⏳ Placeholder — will be implemented in Task 7');
}

main().catch(console.error);
```

- [ ] **Step 2: Verify compilation**

Run: `cd scripts/demo && npx tsc --noEmit record-demo.ts`
Expected: No errors.

- [ ] **Step 3: Test run segments 1 & 2 only**

Create a `.env` file from `.env.example` with real credentials, then:

Run: `cd scripts/demo && npx ts-node record-demo.ts`
Expected: Console output showing segment 1 and 2 steps, video file created in `videos/`.

- [ ] **Step 4: Commit**

```bash
git add scripts/demo/record-demo.ts
git commit -m "feat(demo): implement login and dashboard segments

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Segment 3 — Create Issue with Echo Hello Template

**Files:**
- Modify: `scripts/demo/record-demo.ts` (replace `segment3_createIssue` placeholder)

- [ ] **Step 1: Replace segment3_createIssue with full implementation**

Replace the placeholder `segment3_createIssue` function with:

```typescript
async function segment3_createIssue(page: Page): Promise<void> {
  logStep('Segment 3', 'Navigating to Issues page');
  await navigateSidebar(page, '议题', 1500);
  await waitForVisible(page, '[data-testid="issue-list-page"]');
  await pause(1500);

  logStep('Segment 3', 'Clicking Create Issue button');
  await clickWithDelay(page, '[data-testid="issue-list-create-button"]', { prePause: 500, postPause: 1500 });
  await waitForVisible(page, '[data-testid="create-issue-page"]');

  logStep('Segment 3', 'Selecting project');
  // Click the first select (project selector)
  const projectSelect = page.locator('[data-testid="create-issue-form"]').locator('.n-base-selection').first();
  await projectSelect.click();
  await pause(800);
  // Select the first available project
  await page.locator('.n-base-select-option').first().click();
  await pause(1000);

  logStep('Segment 3', 'Typing issue title');
  await humanType(page, '[data-testid="create-issue-form"] input[placeholder]', 'Demo: Echo Hello 测试', { minDelay: 50, maxDelay: 90 });
  await pause(800);

  logStep('Segment 3', 'Opening prompt template drawer');
  // Click the template button (it has a template/document icon near the description area)
  const templateButton = page.locator('[data-testid="create-issue-form"]').getByRole('button').filter({ hasText: /模板|Template/i });
  if (await templateButton.isVisible()) {
    await templateButton.click();
    await pause(1000);

    logStep('Segment 3', 'Selecting Echo Hello template');
    const echoTemplate = page.locator('.prompt-template-dropdown__item').filter({ hasText: /echo.*hello/i });
    if (await echoTemplate.isVisible()) {
      await echoTemplate.click();
      await pause(1500);
    } else {
      logStep('Segment 3', '⚠️ Echo Hello template not found, typing manually');
      await humanTypeCodeMirror(page, '.variable-editor', 'echo "Hello, World!"', { minDelay: 40, maxDelay: 70 });
      await pause(1000);
    }
  } else {
    logStep('Segment 3', '⚠️ Template button not found, typing description manually');
    await humanTypeCodeMirror(page, '.variable-editor', 'echo "Hello, World!"', { minDelay: 40, maxDelay: 70 });
    await pause(1000);
  }

  logStep('Segment 3', 'Selecting base branch');
  // Base branch selector - second .n-base-selection in the form
  const branchSelects = page.locator('[data-testid="create-issue-form"]').locator('.n-base-selection');
  const branchSelectCount = await branchSelects.count();
  if (branchSelectCount >= 2) {
    await branchSelects.nth(1).click();
    await pause(500);
    // Select 'main' or first available branch
    const mainOption = page.locator('.n-base-select-option').filter({ hasText: 'main' });
    if (await mainOption.isVisible()) {
      await mainOption.click();
    } else {
      await page.locator('.n-base-select-option').first().click();
    }
    await pause(1000);
  }

  logStep('Segment 3', 'Pausing to show complete form');
  await pause(2000);

  logStep('Segment 3', 'Submitting issue');
  await clickWithDelay(page, '[data-testid="create-issue-submit"]', { prePause: 500, postPause: 500 });

  logStep('Segment 3', 'Waiting for issue detail page');
  await page.waitForURL('**/issues/**', { timeout: 10000 });
  await page.waitForLoadState('networkidle');
  await waitForVisible(page, '[data-testid="issue-view-page"]');
  await pause(2000);

  logStep('Segment 3', '✅ Issue created');
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd scripts/demo && npx tsc --noEmit record-demo.ts`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add scripts/demo/record-demo.ts
git commit -m "feat(demo): implement create issue segment with Echo Hello template

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Segment 4 — Real-Time Task Execution & Results

**Files:**
- Modify: `scripts/demo/record-demo.ts` (replace `segment4_taskExecution` placeholder)

- [ ] **Step 1: Replace segment4_taskExecution with full implementation**

Replace the placeholder `segment4_taskExecution` function with:

```typescript
async function segment4_taskExecution(page: Page): Promise<void> {
  logStep('Segment 4', 'On issue detail page, showing initial state');
  await pause(2000);

  logStep('Segment 4', 'Looking for associated task in tasks card');
  const tasksCard = page.locator('[data-testid="issue-tasks-card"]');
  await waitForVisible(page, '[data-testid="issue-tasks-card"]', 15000);
  await pause(1500);

  // Click the first task row to navigate to task detail
  logStep('Segment 4', 'Clicking task to view details');
  const taskRow = tasksCard.locator('.n-data-table-tr').filter({ hasNotText: /ID|状态/ }).first();
  if (await taskRow.isVisible({ timeout: 5000 })) {
    await taskRow.click();
  } else {
    // Fallback: the task might appear as a link or button
    const taskLink = tasksCard.locator('td').first();
    await taskLink.click();
  }
  await page.waitForURL('**/tasks/**', { timeout: 10000 });
  await page.waitForLoadState('networkidle');
  await pause(1500);

  logStep('Segment 4', 'On task detail page, monitoring status changes');

  // Poll for task status changes, showing real-time updates
  const maxWaitMs = 120_000; // 2 minute max wait
  const pollIntervalMs = 3000;
  let elapsed = 0;
  let completed = false;

  while (elapsed < maxWaitMs) {
    // Check for terminal status
    const statusTag = page.locator('[data-testid="task-view-page"]').locator('.n-tag').first();
    const statusText = await statusTag.textContent().catch(() => '');

    logStep('Segment 4', `Current status: ${statusText?.trim()}`);

    if (statusText?.includes('完成') || statusText?.includes('completed') || statusText?.includes('COMPLETED')) {
      completed = true;
      break;
    }
    if (statusText?.includes('失败') || statusText?.includes('failed') || statusText?.includes('FAILED')) {
      logStep('Segment 4', '⚠️ Task failed, continuing with result display');
      completed = true;
      break;
    }

    // Scroll to process panel to show logs if running
    if (statusText?.includes('运行') || statusText?.includes('running') || statusText?.includes('RUNNING')) {
      const processPanel = page.locator('.task-process-panel');
      if (await processPanel.isVisible({ timeout: 2000 }).catch(() => false)) {
        logStep('Segment 4', 'Scrolling to process panel to show live logs');
        await scrollIntoView(page, '.task-process-panel', 500);
        await pause(5000); // Let the viewer see live log streaming
      }
    }

    // Refresh the page to get updated status (or rely on SSE if available)
    await pause(pollIntervalMs);
    await page.reload();
    await page.waitForLoadState('networkidle');
    elapsed += pollIntervalMs + 2000;
  }

  if (completed) {
    logStep('Segment 4', 'Task completed! Showing results');
    await pause(3000);

    // Scroll to show result information
    logStep('Segment 4', 'Scrolling to show task results');
    await scrollToTop(page, 1000);
    await pause(1500);

    // Show the metadata (branch, MR link, code changes)
    await smoothScroll(page, 300, 1500);
    await pause(2000);

    // Scroll to result panel if exists
    const resultPanel = page.locator('.task-result-panel');
    if (await resultPanel.isVisible({ timeout: 3000 }).catch(() => false)) {
      await scrollIntoView(page, '.task-result-panel', 2000);
    }
  } else {
    logStep('Segment 4', '⚠️ Task did not complete within timeout, showing current state');
    await pause(2000);
  }

  // Navigate back to issue to show the branch flow visualization
  logStep('Segment 4', 'Navigating back to issue detail');
  await page.goBack();
  await page.waitForLoadState('networkidle');
  await waitForVisible(page, '[data-testid="issue-view-page"]', 5000);
  await pause(2000);

  logStep('Segment 4', '✅ Task execution segment complete');
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd scripts/demo && npx tsc --noEmit record-demo.ts`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add scripts/demo/record-demo.ts
git commit -m "feat(demo): implement real-time task execution segment

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Segment 5 — Monitoring & Analytics

**Files:**
- Modify: `scripts/demo/record-demo.ts` (replace `segment5_monitoring` placeholder)

- [ ] **Step 1: Replace segment5_monitoring with full implementation**

Replace the placeholder `segment5_monitoring` function with:

```typescript
async function segment5_monitoring(page: Page): Promise<void> {
  logStep('Segment 5', 'Navigating to Monitor page');
  await navigateSidebar(page, '监控', 2000);
  await page.waitForLoadState('networkidle');
  await pause(2000);

  logStep('Segment 5', 'Showing Kanban view of active tasks');
  // Look for the kanban/table toggle or the kanban board
  await pause(2500);

  // Scroll down to see more of the monitor page
  await smoothScroll(page, 300, 1500);
  await pause(1500);
  await scrollToTop(page, 1000);

  logStep('Segment 5', 'Navigating to Analytics page');
  await navigateSidebar(page, '分析', 2000);
  await page.waitForLoadState('networkidle');
  await pause(2500);

  logStep('Segment 5', 'Scrolling through trend charts');
  await smoothScroll(page, 500, 2000);
  await pause(2000);
  await smoothScroll(page, 400, 1500);
  await pause(1500);
  await scrollToTop(page, 1000);

  logStep('Segment 5', 'Navigating to Schedule Overview page');
  await navigateSidebar(page, '排期概览', 2000);
  await page.waitForLoadState('networkidle');
  await pause(2500);

  logStep('Segment 5', '✅ Monitoring & analytics segment complete');
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd scripts/demo && npx tsc --noEmit record-demo.ts`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add scripts/demo/record-demo.ts
git commit -m "feat(demo): implement monitoring and analytics segment

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 7: Segment 6 — Configuration & Management

**Files:**
- Modify: `scripts/demo/record-demo.ts` (replace `segment6_configuration` placeholder)

- [ ] **Step 1: Replace segment6_configuration with full implementation**

Replace the placeholder `segment6_configuration` function with:

```typescript
async function segment6_configuration(page: Page): Promise<void> {
  logStep('Segment 6', 'Navigating to Access Management page');
  await navigateSidebar(page, '访问管理', 2000);
  await page.waitForLoadState('networkidle');
  await pause(2000);

  // Scroll to show user cards
  await smoothScroll(page, 200, 1000);
  await pause(1500);
  await scrollToTop(page, 800);

  logStep('Segment 6', 'Navigating to Configuration page');
  await navigateSidebar(page, '配置', 2000);
  await page.waitForLoadState('networkidle');
  await pause(2000);

  logStep('Segment 6', 'Switching to AI Providers tab');
  const aiTab = page.locator('.n-tabs').getByText(/AI|供应商|Provider/i);
  if (await aiTab.isVisible({ timeout: 3000 }).catch(() => false)) {
    await aiTab.click();
    await pause(1500);
  }

  logStep('Segment 6', 'Switching to GitLab tab');
  const gitlabTab = page.locator('.n-tabs').getByText(/GitLab/i);
  if (await gitlabTab.isVisible({ timeout: 3000 }).catch(() => false)) {
    await gitlabTab.click();
    await pause(1500);
  }

  logStep('Segment 6', 'Final pause for closing shot');
  await pause(2000);

  logStep('Segment 6', '✅ Configuration segment complete');
}
```

- [ ] **Step 2: Verify compilation**

Run: `cd scripts/demo && npx tsc --noEmit record-demo.ts`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add scripts/demo/record-demo.ts
git commit -m "feat(demo): implement configuration and management segment

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 8: End-to-End Test Run & Polish

**Files:**
- Modify: `scripts/demo/record-demo.ts` (bug fixes from test run)
- Modify: `scripts/demo/helpers.ts` (bug fixes from test run)

- [ ] **Step 1: Create .env with real credentials**

Create `scripts/demo/.env` with actual credentials (not committed):

```bash
DEMO_URL=http://192.168.50.129:8880
DEMO_USERNAME=admin
DEMO_PASSWORD=<real_password>
```

- [ ] **Step 2: Full test run**

Run: `cd scripts/demo && npx ts-node record-demo.ts`
Expected: All 6 segments complete, video saved to `videos/codify-demo.webm`.

- [ ] **Step 3: Fix any issues found during test run**

Debug and fix selector mismatches, timing issues, or navigation failures. Common fixes:
- Adjust pause durations if pages load slower than expected
- Fix selectors if Chinese text differs from what was expected
- Handle cases where elements need scrolling to be visible

- [ ] **Step 4: Re-run to verify fixes**

Run: `cd scripts/demo && npx ts-node record-demo.ts`
Expected: Clean run with all segments, video file produced.

- [ ] **Step 5: Add .env to .gitignore**

Verify `scripts/demo/.env` is gitignored (add to root `.gitignore` if needed):

```bash
echo "scripts/demo/.env" >> .gitignore
```

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat(demo): complete demo recording script with all 6 segments

- Login with human-like typing
- Dashboard overview with smooth scrolling
- Create Issue using Echo Hello prompt template
- Real-time task execution monitoring with log streaming
- Monitor, Analytics, and Schedule Overview pages
- Access Management and Configuration pages

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```
