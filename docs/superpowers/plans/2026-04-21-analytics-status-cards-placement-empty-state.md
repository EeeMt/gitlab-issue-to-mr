# Analytics Status Cards Placement and Empty State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the Analytics issue/task status distribution cards to immediately after the summary cards and show explicit whole-card empty states when the filtered totals are zero.

**Architecture:** Keep the existing Analytics page data flow, status-card toggle state, and status-row computations in `Analytics.vue`, but reorder the status-card section above the trend charts and branch each card body on its computed total. Extend the focused Analytics view spec first to lock the new DOM order and empty-state behavior, then add localized empty-state copy and the minimal template/CSS changes needed to render an intentional placeholder state.

**Tech Stack:** Vue 3, TypeScript, Naive UI, vue-i18n, Vitest, vue-test-utils

---

## File Map

- `frontend/src/views/Analytics.vue`
  - Reorder the status-card section so it renders after the summary grid and before the trend-chart cards.
  - Add per-card `hasIssueStatusData` / `hasTaskStatusData` checks and whole-card empty-state bodies.
  - Keep existing bar/donut toggle controls visible while data is empty.
- `frontend/src/views/Analytics.spec.ts`
  - Add failing tests first for new section order and whole-card empty-state behavior.
  - Reuse the existing mocked `Analytics` response shape and extend it with an empty-data fixture.
- `frontend/src/i18n/messages/en.ts`
  - Add English empty-state copy for issue/task status cards.
- `frontend/src/i18n/messages/zh-CN.ts`
  - Add Chinese empty-state copy for issue/task status cards.

---

### Task 1: Lock the new order and empty-state behavior with failing tests

**Files:**
- Modify: `frontend/src/views/Analytics.spec.ts`

- [ ] **Step 1: Write the failing tests**

Add an empty-data fixture near `mockAnalytics`:

```ts
const mockAnalyticsEmptyStatus = {
  ...mockAnalytics,
  issue_status_breakdown: [
    { status: 'open', count: 0, share: 0 },
    { status: 'in_progress', count: 0, share: 0 },
    { status: 'in_review', count: 0, share: 0 },
    { status: 'closed', count: 0, share: 0 }
  ],
  task_status_breakdown: [
    { status: 'pending', count: 0, share: 0 },
    { status: 'queued', count: 0, share: 0 },
    { status: 'running', count: 0, share: 0 },
    { status: 'completed', count: 0, share: 0 },
    { status: 'failed', count: 0, share: 0 },
    { status: 'cancelled', count: 0, share: 0 }
  ]
}
```

Then add these tests:

```ts
  it('renders the status distribution cards before the trend charts', async () => {
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    const cardTexts = wrapper.findAll('.n-card').map((card) => card.text())
    const issueCardIndex = cardTexts.findIndex((text) => text.includes('analytics.issueStatusDistribution'))
    const taskCardIndex = cardTexts.findIndex((text) => text.includes('analytics.taskStatusDistribution'))
    const trendCardIndex = cardTexts.findIndex((text) => text.includes('analytics.taskVolumeTrend'))

    expect(issueCardIndex).toBeGreaterThan(-1)
    expect(taskCardIndex).toBeGreaterThan(-1)
    expect(trendCardIndex).toBeGreaterThan(-1)
    expect(issueCardIndex).toBeLessThan(trendCardIndex)
    expect(taskCardIndex).toBeLessThan(trendCardIndex)
  })

  it('shows whole-card empty states when both status distributions have no data', async () => {
    ;(mockApi.getAnalytics as Mock).mockResolvedValue(mockAnalyticsEmptyStatus)
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    expect(wrapper.text()).toContain('analytics.issueStatusDistributionEmpty')
    expect(wrapper.text()).toContain('analytics.taskStatusDistributionEmpty')
    expect(wrapper.findAll('.status-chart__bar-row')).toHaveLength(0)
  })
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/views/Analytics.spec.ts`

Expected: FAIL because `Analytics.vue` still renders the trend cards before the status-card grid and has no localized empty-state copy or zero-total branch.

- [ ] **Step 3: Keep the failing assertions focused**

If the failure comes from fixture shape or selector mistakes instead of missing behavior, fix only the test setup and rerun until the failures clearly point at:

- missing order change
- missing empty-state text / branch

Do not touch production code in this step.

- [ ] **Step 4: Commit the red test**

```bash
git add frontend/src/views/Analytics.spec.ts
git commit -m "test: cover analytics status card order and empty states"
```

---

### Task 2: Reorder the status cards, add empty-state copy, and keep the controls stable

**Files:**
- Modify: `frontend/src/views/Analytics.vue`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`
- Test: `frontend/src/views/Analytics.spec.ts`

- [ ] **Step 1: Add the localized empty-state copy**

In `frontend/src/i18n/messages/en.ts` under the existing `analytics` block, add:

```ts
    issueStatusDistributionEmpty: 'No issues match the current filters and time window yet.',
    taskStatusDistributionEmpty: 'No tasks match the current filters and time window yet.',
```

In `frontend/src/i18n/messages/zh-CN.ts`, add:

```ts
    issueStatusDistributionEmpty: '当前筛选条件和时间窗口下还没有匹配的需求。',
    taskStatusDistributionEmpty: '当前筛选条件和时间窗口下还没有匹配的任务。',
```

- [ ] **Step 2: Add explicit zero-data guards in `Analytics.vue`**

Keep the existing total computations and add booleans immediately after them:

```ts
const hasIssueStatusData = computed(() => issueStatusTotal.value > 0)
const hasTaskStatusData = computed(() => taskStatusTotal.value > 0)
```

- [ ] **Step 3: Move the status-card section above the trend-card section**

In `frontend/src/views/Analytics.vue`, move the whole:

```vue
<n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="16">
  <!-- analytics-issue-status-card -->
  <!-- analytics-task-status-card -->
</n-grid>
```

from below the breakdown table card to immediately after:

```vue
<n-grid v-if="hasLoadedOnce" :cols="isMobile ? 2 : 3" :x-gap="16" :y-gap="16">
  <n-gi v-for="item in summaryItems" :key="item.label" class="analytics-grid-cell">
```

and before the first trend card (`analytics.taskVolumeTrend`).

- [ ] **Step 4: Replace empty chart bodies with whole-card empty states**

Update the issue card body:

```vue
<div v-if="!hasIssueStatusData" class="analytics-empty-state">
  <div class="analytics-empty-state__title">{{ t('analytics.issueStatusDistributionEmpty') }}</div>
</div>
<div v-else-if="issueStatusChartMode === 'bar'" class="status-chart status-chart--bar">
  <!-- existing issue bar chart -->
</div>
<div v-else class="status-chart status-chart--donut">
  <!-- existing issue donut chart -->
</div>
```

Apply the same structure to the task card:

```vue
<div v-if="!hasTaskStatusData" class="analytics-empty-state">
  <div class="analytics-empty-state__title">{{ t('analytics.taskStatusDistributionEmpty') }}</div>
</div>
<div v-else-if="taskStatusChartMode === 'bar'" class="status-chart status-chart--bar">
  <!-- existing task bar chart -->
</div>
<div v-else class="status-chart status-chart--donut">
  <!-- existing task donut chart -->
</div>
```

Do not hide or move the chart-mode toggle in the card header.

- [ ] **Step 5: Add minimal empty-state styling**

In the scoped CSS for `frontend/src/views/Analytics.vue`, add:

```css
.analytics-empty-state {
  min-height: 220px;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 24px;
  border-radius: 18px;
  background: rgba(148, 163, 184, 0.08);
  border: 1px dashed rgba(148, 163, 184, 0.28);
}

.analytics-empty-state__title {
  max-width: 320px;
  font-size: 14px;
  line-height: 1.6;
  color: rgba(15, 23, 42, 0.6);
}
```

Keep the styling lightweight and within the existing analytics card language.

- [ ] **Step 6: Run the focused spec to verify green**

Run: `cd frontend && npx vitest run src/views/Analytics.spec.ts`

Expected: PASS with the new order/empty-state tests green alongside the existing analytics tests.

- [ ] **Step 7: Run the frontend build**

Run: `cd frontend && npm run build`

Expected: successful `vue-tsc && vite build` completion.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/views/Analytics.vue frontend/src/views/Analytics.spec.ts frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: polish analytics status card placement"
```

---

## Self-Review

- **Spec coverage:** The plan covers both approved changes: moving the cards ahead of trends and replacing zero-data charts with whole-card empty states. The localized copy requirement is explicitly mapped to both locale files.
- **Placeholder scan:** No TODO/TBD placeholders remain; every code step includes concrete snippets or commands.
- **Type consistency:** The plan uses the existing `issueStatusTotal`, `taskStatusTotal`, `issueStatusChartMode`, and `taskStatusChartMode` names already present in `Analytics.vue`, so later implementation steps match the current code.
