# UI Polish Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 12 UI/UX improvements: Dashboard restyle with Grafana stat cards + GitHub-style 365-day activity heatmap, IssueView layout overhaul (side-by-side, modal create task, retry rework, "No MR"), IssueList row-click, TaskView navigation fix, CreateIssue auto-fill, plus housekeeping.

**Architecture:** New components (StatCard, ActivityHeatmap) + new backend endpoint for daily activity data + modifications to 6 existing Vue pages. All i18n keys added inline per task.

**Tech Stack:** Vue 3 / Naive UI / TypeScript / Python FastAPI / SQLAlchemy

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `frontend/src/components/StatCard.vue` | Grafana-style compact stat card with colored left border + icon |
| `frontend/src/components/ActivityHeatmap.vue` | GitHub-style 365-day contribution heatmap grid |

### Modified Files

| File | Changes |
|------|---------|
| `frontend/src/views/Dashboard.vue` | Replace SummaryCard with StatCard (5 metrics), replace Recent Activity with ActivityHeatmap |
| `frontend/src/views/IssueView.vue` | Side-by-side layout, retry rework, "No MR" text, create task modal |
| `frontend/src/views/IssueList.vue` | Add row-props for row-click navigation |
| `frontend/src/views/TaskView.vue` | Watch route.params.id to fix same-route navigation |
| `frontend/src/views/CreateIssue.vue` | Auto-fill target_branch from project default when MR enabled |
| `frontend/src/api/index.ts` | Add `getActivityHeatmap()` + `ActivityHeatmapEntry` type |
| `frontend/src/i18n/messages/en.ts` | New keys for all features |
| `frontend/src/i18n/messages/zh-CN.ts` | New keys for all features |
| `backend/app/api/stats.py` | New `/stats/activity-heatmap` endpoint |

---

## Task 1: Create StatCard Component

**Files:**
- Create: `frontend/src/components/StatCard.vue`

- [ ] **Step 1: Create StatCard.vue**

```vue
<template>
  <n-card
    size="small"
    :bordered="false"
    class="stat-card"
    :style="{ '--stat-card-accent': color }"
  >
    <div class="stat-card__body">
      <div class="stat-card__icon-wrap">
        <n-icon :size="22" :color="color" :component="icon" />
      </div>
      <div class="stat-card__content">
        <div class="stat-card__value">{{ value }}{{ suffix }}</div>
        <div class="stat-card__label">{{ label }}</div>
      </div>
    </div>
  </n-card>
</template>

<script setup lang="ts">
import { NCard, NIcon } from 'naive-ui'
import type { Component } from 'vue'

defineProps<{
  label: string
  value: string | number
  icon: Component
  color: string
  suffix?: string
}>()
</script>

<style scoped>
.stat-card {
  border-radius: var(--app-card-radius, 12px);
  border-left: 4px solid var(--stat-card-accent, #2080f0);
  background: var(--n-color);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  min-height: 80px;
}

.stat-card__body {
  display: flex;
  align-items: center;
  gap: 14px;
}

.stat-card__icon-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--stat-card-accent) 10%, transparent);
  flex-shrink: 0;
}

.stat-card__value {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
  color: var(--n-text-color);
}

.stat-card__label {
  font-size: 12px;
  color: var(--n-text-color-3);
  margin-top: 2px;
}
</style>
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: No errors related to StatCard.vue

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/StatCard.vue
git commit -m "feat: add StatCard component (Grafana-style stat panel)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: Create ActivityHeatmap Component + Backend Endpoint

**Files:**
- Create: `frontend/src/components/ActivityHeatmap.vue`
- Modify: `frontend/src/api/index.ts`
- Modify: `backend/app/api/stats.py`

- [ ] **Step 1: Add backend endpoint**

Add to `backend/app/api/stats.py` after the existing `get_stats` endpoint:

```python
@router.get("/stats/activity-heatmap")
async def get_activity_heatmap(
    days: int = Query(default=365, ge=1, le=730),
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
    _user=Depends(require_page_access),
):
    """Return daily completed-task counts for the heatmap."""
    now = utcnow()
    since = now - timedelta(days=days)

    query = (
        select(
            func.date(Task.completed_at).label("date"),
            func.count().label("count"),
        )
        .where(Task.status == TaskStatus.COMPLETED)
        .where(Task.completed_at >= since)
        .group_by(func.date(Task.completed_at))
        .order_by(func.date(Task.completed_at))
    )

    if access_scope.project_ids is not None:
        query = query.where(Task.project_id.in_(access_scope.project_ids))

    result = await db.execute(query)
    rows = result.all()

    return [{"date": str(row.date), "count": row.count} for row in rows]
```

- [ ] **Step 2: Add frontend API function**

In `frontend/src/api/index.ts`, add after the `Stats` interface (around line 217):

```typescript
export interface ActivityHeatmapEntry {
  date: string
  count: number
}
```

Add the API function (near the other stats functions):

```typescript
export async function getActivityHeatmap(days = 365): Promise<ActivityHeatmapEntry[]> {
  const res = await api.get<ActivityHeatmapEntry[]>('/stats/activity-heatmap', { params: { days } })
  return res.data
}
```

- [ ] **Step 3: Create ActivityHeatmap.vue**

```vue
<template>
  <div class="activity-heatmap" data-testid="activity-heatmap">
    <div class="activity-heatmap__grid">
      <div class="activity-heatmap__months">
        <span
          v-for="m in monthLabels"
          :key="m.key"
          class="activity-heatmap__month-label"
          :style="{ gridColumnStart: m.col }"
        >{{ m.label }}</span>
      </div>
      <div class="activity-heatmap__days">
        <span class="activity-heatmap__day-label">{{ t('common.mon') }}</span>
        <span class="activity-heatmap__day-label"></span>
        <span class="activity-heatmap__day-label">{{ t('common.wed') }}</span>
        <span class="activity-heatmap__day-label"></span>
        <span class="activity-heatmap__day-label">{{ t('common.fri') }}</span>
        <span class="activity-heatmap__day-label"></span>
        <span class="activity-heatmap__day-label"></span>
      </div>
      <div class="activity-heatmap__cells" :style="{ gridTemplateColumns: `repeat(${weeks.length}, 13px)` }">
        <template v-for="(week, wi) in weeks" :key="wi">
          <div
            v-for="(day, di) in week"
            :key="`${wi}-${di}`"
            class="activity-heatmap__cell"
            :class="day ? `activity-heatmap__cell--level-${getLevel(day.count)}` : 'activity-heatmap__cell--empty'"
            :title="day ? `${day.count} ${day.count === 1 ? 'task' : 'tasks'} on ${day.date}` : ''"
            :style="{ gridRow: di + 1, gridColumn: wi + 1 }"
          />
        </template>
      </div>
    </div>
    <div class="activity-heatmap__legend">
      <span class="activity-heatmap__legend-label">{{ t('common.less') }}</span>
      <div class="activity-heatmap__cell activity-heatmap__cell--level-0" />
      <div class="activity-heatmap__cell activity-heatmap__cell--level-1" />
      <div class="activity-heatmap__cell activity-heatmap__cell--level-2" />
      <div class="activity-heatmap__cell activity-heatmap__cell--level-3" />
      <div class="activity-heatmap__cell activity-heatmap__cell--level-4" />
      <span class="activity-heatmap__legend-label">{{ t('common.more') }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ActivityHeatmapEntry } from '../api'

const { t } = useI18n()

const props = defineProps<{
  data: ActivityHeatmapEntry[]
}>()

interface DayCell {
  date: string
  count: number
}

const countMap = computed(() => {
  const map = new Map<string, number>()
  for (const entry of props.data) {
    map.set(entry.date, entry.count)
  }
  return map
})

const weeks = computed(() => {
  const result: (DayCell | null)[][] = []
  const today = new Date()
  today.setHours(0, 0, 0, 0)

  // Find the start: go back ~52 weeks to the nearest Sunday
  const dayOfWeek = today.getDay() // 0=Sun
  const daysBack = 364 + dayOfWeek
  const start = new Date(today)
  start.setDate(start.getDate() - daysBack)

  let currentWeek: (DayCell | null)[] = []
  const d = new Date(start)

  while (d <= today) {
    const dateStr = d.toISOString().slice(0, 10)
    const count = countMap.value.get(dateStr) ?? 0
    currentWeek.push({ date: dateStr, count })

    if (currentWeek.length === 7) {
      result.push(currentWeek)
      currentWeek = []
    }
    d.setDate(d.getDate() + 1)
  }

  // Pad the last week
  if (currentWeek.length > 0) {
    while (currentWeek.length < 7) {
      currentWeek.push(null)
    }
    result.push(currentWeek)
  }

  return result
})

const monthLabels = computed(() => {
  const labels: { key: string; label: string; col: number }[] = []
  const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  let lastMonth = -1

  for (let wi = 0; wi < weeks.value.length; wi++) {
    const firstDay = weeks.value[wi].find(d => d !== null)
    if (!firstDay) continue
    const month = new Date(firstDay.date).getMonth()
    if (month !== lastMonth) {
      labels.push({ key: `${wi}-${month}`, label: monthNames[month], col: wi + 1 })
      lastMonth = month
    }
  }
  return labels
})

function getLevel(count: number): number {
  if (count === 0) return 0
  if (count <= 2) return 1
  if (count <= 4) return 2
  if (count <= 6) return 3
  return 4
}
</script>

<style scoped>
.activity-heatmap__grid {
  display: flex;
  gap: 4px;
  overflow-x: auto;
}

.activity-heatmap__months {
  display: grid;
  grid-template-rows: 1fr;
  font-size: 10px;
  color: var(--n-text-color-3);
  margin-bottom: 2px;
  margin-left: 32px;
}

.activity-heatmap__month-label {
  white-space: nowrap;
}

.activity-heatmap__days {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-right: 4px;
  justify-content: flex-start;
}

.activity-heatmap__day-label {
  height: 11px;
  font-size: 9px;
  line-height: 11px;
  color: var(--n-text-color-3);
  text-align: right;
  min-width: 24px;
}

.activity-heatmap__cells {
  display: grid;
  grid-template-rows: repeat(7, 11px);
  gap: 2px;
}

.activity-heatmap__cell {
  width: 11px;
  height: 11px;
  border-radius: 2px;
}

.activity-heatmap__cell--empty {
  background: transparent;
}

.activity-heatmap__cell--level-0 {
  background: var(--n-border-color);
}

.activity-heatmap__cell--level-1 {
  background: #9be9a8;
}

.activity-heatmap__cell--level-2 {
  background: #40c463;
}

.activity-heatmap__cell--level-3 {
  background: #30a14e;
}

.activity-heatmap__cell--level-4 {
  background: #216e39;
}

.activity-heatmap__legend {
  display: flex;
  align-items: center;
  gap: 3px;
  margin-top: 8px;
  justify-content: flex-end;
}

.activity-heatmap__legend-label {
  font-size: 10px;
  color: var(--n-text-color-3);
  margin: 0 2px;
}
</style>
```

- [ ] **Step 4: Build to verify**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ActivityHeatmap.vue frontend/src/api/index.ts backend/app/api/stats.py
git commit -m "feat: add ActivityHeatmap component + backend /stats/activity-heatmap endpoint

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: Dashboard Overhaul — StatCard + Heatmap

**Files:**
- Modify: `frontend/src/views/Dashboard.vue`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

**Depends on:** Task 1 (StatCard), Task 2 (ActivityHeatmap + API)

- [ ] **Step 1: Add i18n keys**

In `en.ts`, add to the `dashboard` section:

```typescript
openIssues: 'Open Issues',
tasks: 'Tasks',
successRate: 'Success Rate',
activity: 'Activity',
```

In `zh-CN.ts`, add to the `dashboard` section:

```typescript
openIssues: '进行中需求',
tasks: '任务总数',
successRate: '成功率',
activity: '活动',
```

Also add to the `common` section in both files:

**en.ts:**
```typescript
mon: 'Mon',
wed: 'Wed',
fri: 'Fri',
less: 'Less',
more: 'More',
```

**zh-CN.ts:**
```typescript
mon: '一',
wed: '三',
fri: '五',
less: '少',
more: '多',
```

- [ ] **Step 2: Update Dashboard.vue imports**

Replace the import block to use StatCard + ActivityHeatmap instead of SummaryCard:

Change:
```typescript
import SummaryCard from '../components/SummaryCard.vue'
```

To:
```typescript
import StatCard from '../components/StatCard.vue'
import ActivityHeatmap from '../components/ActivityHeatmap.vue'
import { getActivityHeatmap, type ActivityHeatmapEntry } from '../api'
```

Add icon imports:
```typescript
import {
  FolderOpenOutline,
  AlertCircleOutline,
  CodeOutline,
  PlayOutline,
  CheckmarkCircleOutline
} from '@vicons/ionicons5'
```

- [ ] **Step 3: Update Dashboard.vue state**

Add new state variables:

```typescript
const statsOpenIssues = ref(0)
const statsFailed = ref(0)
const heatmapData = ref<ActivityHeatmapEntry[]>([])
```

Update `fetchStats()`:

```typescript
async function fetchStats() {
  try {
    const stats = await getStats()
    statsTotal.value = stats.total
    statsRunning.value = stats.running
    statsCompleted.value = stats.completed
    statsFailed.value = stats.failed
    statsIssueTotal.value = stats.issues?.total ?? 0
    statsOpenIssues.value = stats.issues?.by_status?.open ?? 0
  } catch {
    // Stats are supplementary; don't block UI
  }
}
```

Add heatmap fetch:

```typescript
async function fetchHeatmap() {
  try {
    heatmapData.value = await getActivityHeatmap()
  } catch {
    // Supplementary
  }
}
```

Update `refreshAll`:

```typescript
function refreshAll() {
  fetchData()
  fetchStats()
  fetchHeatmap()
}
```

Update `onMounted`:

```typescript
onMounted(() => {
  fetchStats()
  fetchData()
  fetchHeatmap()
  startPolling()
})
```

Add computed for success rate:

```typescript
const successRate = computed(() => {
  const total = statsCompleted.value + statsFailed.value
  if (total === 0) return '0'
  return Math.round((statsCompleted.value / total) * 100).toString()
})
```

- [ ] **Step 4: Update Dashboard.vue template — Summary Cards**

Replace the summary cards section (lines 15-32) with:

```vue
<n-grid
  v-if="hasLoadedOnce"
  data-testid="dashboard-summary"
  :cols="isMobile ? 2 : 5"
  :x-gap="12"
  :y-gap="12"
>
  <n-gi>
    <StatCard
      :label="t('dashboard.issueCount')"
      :value="statsIssueTotal"
      :icon="FolderOpenOutline"
      color="#2080f0"
      data-testid="dashboard-summary-card"
    />
  </n-gi>
  <n-gi>
    <StatCard
      :label="t('dashboard.openIssues')"
      :value="statsOpenIssues"
      :icon="AlertCircleOutline"
      color="#18a058"
      data-testid="dashboard-summary-card"
    />
  </n-gi>
  <n-gi>
    <StatCard
      :label="t('dashboard.tasks')"
      :value="statsTotal"
      :icon="CodeOutline"
      color="#8b5cf6"
      data-testid="dashboard-summary-card"
    />
  </n-gi>
  <n-gi>
    <StatCard
      :label="t('dashboard.running')"
      :value="statsRunning"
      :icon="PlayOutline"
      color="#f0a020"
      data-testid="dashboard-summary-card"
    />
  </n-gi>
  <n-gi>
    <StatCard
      :label="t('dashboard.successRate')"
      :value="successRate"
      :icon="CheckmarkCircleOutline"
      color="#0ea5e9"
      suffix="%"
      data-testid="dashboard-summary-card"
    />
  </n-gi>
</n-grid>
```

- [ ] **Step 5: Replace Recent Activity with ActivityHeatmap**

Replace the Recent Activity card (lines 66-80) with:

```vue
<n-card
  :title="t('dashboard.activity')"
  :bordered="false"
  class="dashboard-table-card"
  data-testid="dashboard-activity-heatmap"
>
  <ActivityHeatmap :data="heatmapData" />
</n-card>
```

Remove `activityColumns`, `recentActivityTasks`, `recentActivity` computed, and the activity fetch code from `fetchData()` (lines 297-312).

- [ ] **Step 6: Remove stale summaryItems computed**

Delete the `summaryItems` computed (lines 130-135) — no longer used.

- [ ] **Step 7: Build to verify**

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 8: Commit**

```bash
git add frontend/src/views/Dashboard.vue frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: Dashboard — Grafana stat cards + GitHub activity heatmap

Replace SummaryCard with StatCard (5 metrics: Issues, Open, Tasks,
Running, Success Rate). Replace Recent Activity table with 365-day
GitHub-style activity heatmap.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 4: IssueList Row-Click Navigation

**Files:**
- Modify: `frontend/src/views/IssueList.vue`

- [ ] **Step 1: Add row-props function**

Add after line 109 (after `projectOptions` computed):

```typescript
function issueRowProps(row: Issue) {
  return {
    style: 'cursor: pointer',
    onClick: () => router.push(`/issues/${row.id}`)
  }
}
```

- [ ] **Step 2: Add row-props to data-table**

Change line 40-49 (the `n-data-table` element) to include `:row-props="issueRowProps"`:

```vue
<n-data-table
  data-testid="issue-list-table"
  :columns="columns"
  :data="issues"
  :loading="tableLoading"
  :row-key="(row: Issue) => row.id"
  :row-props="issueRowProps"
  :pagination="pagination"
  remote
  :bordered="false"
/>
```

- [ ] **Step 3: Add stopPropagation to Title column click**

Update the Title column render function (lines 138-147) to add `e.stopPropagation()`:

```typescript
render: (row) =>
  h(
    NButton,
    {
      text: true,
      type: 'primary',
      onClick: (e: MouseEvent) => {
        e.stopPropagation()
        router.push(`/issues/${row.id}`)
      },
    },
    () => row.title
  ),
```

- [ ] **Step 4: Build to verify**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/IssueList.vue
git commit -m "feat: IssueList — add row-click navigation

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 5: IssueView — Side-by-Side Layout, Retry Rework, "No MR", Modal

**Files:**
- Modify: `frontend/src/views/IssueView.vue`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1: Add i18n keys**

In `en.ts`, add to `issue` section:

```typescript
noMergeRequest: 'No MR',
retriedAs: 'Retried →',
```

In `zh-CN.ts`, add to `issue` section:

```typescript
noMergeRequest: '无合并请求',
retriedAs: '已重试 →',
```

- [ ] **Step 2: Side-by-side layout for Detail + Description**

Wrap the metadata card (lines 37-135) and description card (lines 138-150) in an `NGrid`:

```vue
<!-- Metadata + Description side by side -->
<n-grid :cols="issue.description ? (isMobile ? 1 : 2) : 1" :x-gap="16" :y-gap="16">
  <n-gi>
    <!-- Metadata card (existing, unchanged) -->
    <n-card class="issue-card" :bordered="false" data-testid="issue-metadata-card">
      ...keep existing content...
    </n-card>
  </n-gi>
  <n-gi v-if="issue.description">
    <!-- Description card (existing, unchanged) -->
    <n-card class="issue-card" :bordered="false" data-testid="issue-description-card">
      ...keep existing content...
    </n-card>
  </n-gi>
</n-grid>
```

- [ ] **Step 3: Replace "No MR" dash with explicit text**

In the Merge Request metadata row (line 100), change:

```vue
<span v-else class="metadata-muted">-</span>
```

To:

```vue
<span v-else class="metadata-muted">{{ t('issue.noMergeRequest') }}</span>
```

- [ ] **Step 4: Implement retry rework in task columns**

Add a computed to build the retried-task lookup map:

```typescript
const retriedTaskMap = computed(() => {
  const map = new Map<number, Task>()
  if (!issue.value?.tasks) return map
  for (const task of issue.value.tasks) {
    if (task.is_retry && task.retry_source_task_id) {
      map.set(task.retry_source_task_id, task)
    }
  }
  return map
})
```

Update the actions column render function (currently lines 448-470) in `taskColumns`:

```typescript
{
  title: '',
  key: 'actions',
  width: 120,
  render: (row) => {
    const retryTask = retriedTaskMap.value.get(row.id)
    if (retryTask) {
      return h('span', { style: 'font-size: 12px; color: var(--n-text-color-3)' }, [
        t('issue.retriedAs'),
        ' ',
        h(
          NButton,
          {
            text: true,
            type: 'primary',
            size: 'small',
            onClick: (e: MouseEvent) => {
              e.stopPropagation()
              router.push({ name: 'TaskView', params: { id: retryTask.id } })
            }
          },
          () => `Task #${retryTask.id}`
        )
      ])
    }
    if (!['failed', 'cancelled'].includes(row.status)) return ''
    return h(
      NButton,
      {
        size: 'small',
        secondary: true,
        strong: true,
        round: true,
        type: 'default',
        onClick: (e: MouseEvent) => {
          e.stopPropagation()
          handleRetryTask(row.id)
        }
      },
      () => t('issue.retryTask')
    )
  }
}
```

- [ ] **Step 5: Convert create task to modal**

Replace the inline create task section (currently lines 177-243) with a modal trigger button and a separate NModal.

In the tasks card header, change the toggle button to open a modal:

```vue
<n-button
  size="small"
  type="primary"
  @click="showCreateModal = true"
  data-testid="issue-toggle-create-task"
>
  {{ t('issue.createTask') }}
</n-button>
```

Add a new `NModal` after the edit modal (after line 289):

```vue
<!-- Create Task Modal -->
<n-modal
  v-model:show="showCreateModal"
  preset="card"
  :title="t('issue.createTask')"
  style="width: 680px; max-width: 90vw;"
  data-testid="issue-create-task-modal"
>
  <div class="prompt-label-row">
    <span class="prompt-label">{{ t('issue.field.description') }}</span>
    <n-button
      size="small"
      :disabled="promptTemplatesLoading || promptTemplates.length === 0"
      :loading="promptTemplatesLoading"
      type="default"
      @click="showTemplateDrawer = true"
    >
      <template #icon>
        <n-icon :component="DocumentTextOutline" />
      </template>
      {{ t('createTask.useTemplate') }}
    </n-button>
  </div>
  <n-form label-placement="top" class="issue-view__create-form">
    <n-form-item :show-label="false">
      <VariableEditor
        v-model="newTaskPrompt"
        :variable-tips="promptVariableTips"
        :placeholder="issue?.description || t('issue.promptPlaceholder')"
      />
      <template #feedback>
        <div v-if="unreplacedVariables.length > 0" class="prompt-variable-warning">
          <n-icon :component="WarningOutline" size="14" />
          <span>{{ t('createTask.unreplacedVariablesHint') }}: {{ unreplacedVariables.join(', ') }}</span>
        </div>
      </template>
    </n-form-item>
    <n-grid :cols="isMobile ? 1 : 3" :x-gap="16" :y-gap="12">
      <n-gi>
        <n-form-item :label="t('common.priority')">
          <n-select
            v-model:value="newTaskPriority"
            :options="priorityOptions"
          />
        </n-form-item>
      </n-gi>
      <n-gi>
        <n-form-item :label="t('issue.scheduleDelayed')">
          <n-date-picker
            v-model:value="newTaskSchedule"
            type="datetime"
            clearable
            style="width: 100%"
            :is-date-disabled="isScheduleDateDisabled"
          />
        </n-form-item>
      </n-gi>
      <n-gi>
        <n-form-item label="&nbsp;">
          <n-button
            type="primary"
            :loading="createTaskLoading"
            data-testid="issue-create-task-button"
            @click="handleCreateTask"
          >
            {{ t('issue.createTask') }}
          </n-button>
        </n-form-item>
      </n-gi>
    </n-grid>
  </n-form>
</n-modal>
```

Update state: rename `showCreateForm` to `showCreateModal`:

```typescript
const showCreateModal = ref(false)
```

Update `handleCreateTask` to close modal on success:

```typescript
showCreateModal.value = false
```

Remove the old inline create section from the tasks card body. The `n-data-table` and the inline form section inside the tasks card body should be simplified to just the table.

Remove the `NDivider` import if it was only used for the create task section separator.

- [ ] **Step 6: Build to verify**

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/IssueView.vue frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: IssueView — side-by-side layout, retry rework, No MR, modal create task

- Detail + Description cards side-by-side on desktop
- Hide retry button when retry exists, show link to retry task
- Show 'No MR' text instead of dash
- Convert inline create-task to modal dialog

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 6: TaskView — Fix Same-Route Navigation Bug

**Files:**
- Modify: `frontend/src/views/TaskView.vue`

- [ ] **Step 1: Add watch on route params**

Add `watch` to the imports from vue (line 241):

```typescript
import { ref, onMounted, onBeforeUnmount, computed, watch } from 'vue'
```

Add watcher after the `onMounted` block (after line ~665):

```typescript
watch(
  () => route.params.id,
  (newId, oldId) => {
    if (newId && newId !== oldId) {
      // Reset state for new task
      resetLogsState()
      task.value = null
      hasLoadedOnce.value = false
      fetchTask()
    }
  }
)
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/TaskView.vue
git commit -m "fix: TaskView — re-fetch task when route param changes

Fixes retry source link navigation not refreshing page content
when clicking a link to a different task on the same route.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 7: CreateIssue — Auto-Fill Target Branch

**Files:**
- Modify: `frontend/src/views/CreateIssue.vue`

- [ ] **Step 1: Update MR toggle handler**

The auto-fill logic is already partially implemented in `fetchBranches()` (lines 299-308). But when the user toggles MR ON after project is already selected and branches are loaded, the target_branch isn't set. Add a watch or update the switch handler.

Add after `handleProjectChange` (line 322):

```typescript
// When MR toggle is switched on, auto-fill target_branch with project default
watch(
  () => formValue.value.create_mr,
  (enabled) => {
    if (enabled && formValue.value.project_id && !formValue.value.target_branch) {
      const project = projects.value.find(p => p.id === formValue.value.project_id)
      const defaultBranch = project?.default_branch
      if (defaultBranch && branches.value.some(b => b.name === defaultBranch)) {
        formValue.value.target_branch = defaultBranch
      }
    }
  }
)
```

Add `watch` to the imports from vue:

```typescript
import { ref, computed, onMounted, watch } from 'vue'
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/CreateIssue.vue
git commit -m "feat: CreateIssue — auto-fill target branch when MR toggle enabled

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 8: Update Progress Document

**Files:**
- Modify: `docs/superpowers/plans/2026-04-12-issue-task-mr-refactoring.md`

- [ ] **Step 1: Update all task statuses to Complete**

Read the document and change all "Not Started" statuses to "Complete". Update all progress percentages to 100%.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-04-12-issue-task-mr-refactoring.md
git commit -m "docs: update Issue-Task-MR refactoring progress — all tasks complete

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 9: Code Review

Dispatch code-reviewer agent on changes since commit d8100d6.

- [ ] **Step 1: Run code review**

Review all changes from commit d8100d6 to HEAD for:
- Logic bugs
- Security vulnerabilities
- Missing error handling
- Type mismatches

- [ ] **Step 2: Address findings**

Fix any critical issues found by the reviewer.

---

## Task 10: Full Verification

- [ ] **Step 1: Build frontend**

Run: `cd frontend && npm run build`
Expected: Build succeeds (includes vue-tsc type checking)

- [ ] **Step 2: Run backend unit tests**

Run: `cd backend && pytest tests/unit/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 3: Rebuild E2E test images**

Run: `cd deploy && docker-compose -f docker-compose.e2e.yml build --no-cache nginx e2e`

- [ ] **Step 4: Run E2E tests**

Run: `make test-e2e-down && make test-e2e-up && make test-e2e-run`
Expected: All tests pass (may need fixes for Dashboard/IssueView UI changes)

- [ ] **Step 5: Fix any test failures**

Update E2E test selectors/assertions for:
- Dashboard: `dashboard-summary-card` data-testid still present on StatCard
- Dashboard: `dashboard-recent-activity` changed to `dashboard-activity-heatmap`
- IssueView: create task button opens modal instead of inline section
- IssueView: retry column may show "Retried →" text

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "fix: update E2E tests for UI polish round 2 changes

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Dependency Graph

```
Task 1 (StatCard) ─────────┐
Task 2 (ActivityHeatmap) ───┼─→ Task 3 (Dashboard overhaul)
                            │
Task 4 (IssueList)          │   (independent)
Task 5 (IssueView)          │   (independent)
Task 6 (TaskView)           │   (independent)
Task 7 (CreateIssue)        │   (independent)
Task 8 (Progress doc)       │   (independent)
                            │
All above ──────────────────┴─→ Task 9 (Code review) → Task 10 (Verification)
```

**Recommended parallel batches:**
- **Batch 1:** Tasks 1, 2, 4, 5, 6, 7, 8 (all independent)
- **Batch 2:** Task 3 (depends on T1 + T2)
- **Batch 3:** Task 9 (code review) + Task 10 (verification)
