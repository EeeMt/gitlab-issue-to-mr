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
