# Dashboard My Work Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dashboard's `Recent Issues` and `Running` sections with a tabbed, read-only kanban board showing the current user's issues and tasks grouped by status.

**Architecture:** Keep `frontend/src/views/Dashboard.vue` as the page-level data orchestrator and introduce a dedicated `frontend/src/components/dashboard/MyWorkBoard.vue` presentation component. The dashboard will fetch broader current-user issue/task datasets, normalize them into status-column props, and pass them to the new board; the board handles tabs, column layout, card rendering, empty states, and click navigation.

**Tech Stack:** Vue 3 `<script setup>`, TypeScript, Naive UI, Vue Router, Vue I18n, Vitest, Vue Test Utils

---

## File Structure

### Create
- `frontend/src/components/dashboard/MyWorkBoard.vue` — presentational board component with tabs, status columns, cards, empty states, and responsive layout

### Modify
- `frontend/src/views/Dashboard.vue` — replace table sections with the board, fetch board data, group items by status, and pass props
- `frontend/src/views/Dashboard.spec.ts` — update dashboard tests for board rendering, grouping, tab behavior, empty states, and navigation
- `frontend/src/i18n/messages/en.ts` — add board title and empty-state strings
- `frontend/src/i18n/messages/zh-CN.ts` — add board title and empty-state strings

### Reference
- `frontend/src/api/index.ts:706-721` — `getTasksPaginated(...)`
- `frontend/src/api/index.ts:1097-1110` — `getIssues(...)`
- `frontend/src/views/Config.vue:40-72` — existing `n-tabs` / `n-tab-pane` usage pattern
- `frontend/src/test/mocks/api.ts:16-56` — `createMockTask(...)` factory for test data

---

### Task 1: Add focused failing tests for the new dashboard board contract

**Files:**
- Modify: `frontend/src/views/Dashboard.spec.ts`
- Reference: `frontend/src/test/mocks/api.ts`

- [ ] **Step 1: Replace the old dashboard section expectations with board-focused failing tests**

Add these cases to `frontend/src/views/Dashboard.spec.ts` so the suite describes the target behavior before implementation:

```ts
it('renders my work board instead of recent issues and running sections', async () => {
  await mountDashboard()

  expect(wrapper.find('[data-testid="dashboard-my-work-board"]').exists()).toBe(true)
  expect(wrapper.find('[data-testid="dashboard-recent-issues"]').exists()).toBe(false)
  expect(wrapper.find('[data-testid="dashboard-running-tasks"]').exists()).toBe(false)
})

it('defaults to the issues tab', async () => {
  await mountDashboard()

  expect(wrapper.find('[data-testid="my-work-board-tab-issues"]').attributes('data-active')).toBe('true')
})

it('groups issues into issue status columns', async () => {
  await mountDashboard()

  expect(wrapper.find('[data-testid="issue-column-open"]').text()).toContain('#1')
  expect(wrapper.find('[data-testid="issue-column-in_progress"]').text()).toContain('#2')
})

it('switches to the tasks tab and shows task status columns', async () => {
  await mountDashboard()

  await wrapper.find('[data-testid="my-work-board-tab-tasks"]').trigger('click')

  expect(wrapper.find('[data-testid="task-column-running"]').exists()).toBe(true)
  expect(wrapper.find('[data-testid="task-column-queued"]').exists()).toBe(true)
})
```

- [ ] **Step 2: Add empty-state and navigation failing tests**

Append tests that lock down the remaining spec behavior:

```ts
it('keeps empty columns visible with empty text', async () => {
  setupDefaultMocks()
  mockApi.getIssues.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 })
  mockApi.getTasksPaginated.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 })

  wrapper = mount(Dashboard, { global: { plugins: [router] } })
  await flushPromises()
  await nextTick()

  expect(wrapper.find('[data-testid="issue-column-open"]').text()).toContain('dashboard.myWorkBoard.emptyColumn')
  expect(wrapper.find('[data-testid="my-work-board-empty-issues"]').exists()).toBe(true)
})

it('navigates to issue detail when an issue card is clicked', async () => {
  await mountDashboard()

  await wrapper.find('[data-testid="issue-card-1"]').trigger('click')
  expect(router.currentRoute.value.fullPath).toBe('/issues/1')
})

it('navigates to task detail when a task card is clicked', async () => {
  await mountDashboard()

  await wrapper.find('[data-testid="my-work-board-tab-tasks"]').trigger('click')
  await wrapper.find('[data-testid="task-card-10"]').trigger('click')
  expect(router.currentRoute.value.fullPath).toBe('/tasks/10')
})
```

- [ ] **Step 3: Update the Naive UI test stubs so tabs can be exercised**

Replace the current `naive-ui` mock block with one that includes lightweight `NTabs` and `NTabPane` stubs while preserving existing stubs:

```ts
vi.mock('naive-ui', () => ({
  NTabs: {
    name: 'NTabs',
    props: ['value'],
    emits: ['update:value'],
    setup(props: any, { slots, emit }: any) {
      return () =>
        h('div', {
          class: 'n-tabs',
          'data-value': props.value,
          onClick: (event: MouseEvent) => {
            const target = event.target as HTMLElement | null
            const next = target?.getAttribute('data-tab-value')
            if (next) emit('update:value', next)
          },
        }, slots.default?.())
    },
  },
  NTabPane: {
    name: 'NTabPane',
    props: ['name', 'tab'],
    setup(props: any, { slots }: any) {
      return () =>
        h('section', {
          class: 'n-tab-pane',
          'data-tab-pane': props.name,
          'data-tab-label': props.tab,
        }, slots.default?.())
    },
  },
  // keep the existing NSpin / NSpace / NCard / NDataTable / ... stubs here
}))
```

- [ ] **Step 4: Run the focused dashboard spec to confirm it fails for the right reason**

Run:

```bash
cd /Users/AI/Projects/codify_observe/frontend && npx vitest run src/views/Dashboard.spec.ts
```

Expected: FAIL with missing `dashboard-my-work-board` / board tab / board column assertions because the dashboard still renders the old `Recent Issues` and `Running` sections.

- [ ] **Step 5: Commit the failing test scaffold**

```bash
git add frontend/src/views/Dashboard.spec.ts
git commit -m "test: define dashboard my work board behavior"
```

---

### Task 2: Build the `MyWorkBoard` presentation component

**Files:**
- Create: `frontend/src/components/dashboard/MyWorkBoard.vue`
- Test via: `frontend/src/views/Dashboard.spec.ts`
- Reference: `frontend/src/views/Config.vue:40-72`

- [ ] **Step 1: Create the component shell with typed props and tab state**

Create `frontend/src/components/dashboard/MyWorkBoard.vue` with this initial structure:

```vue
<template>
  <n-card class="my-work-board" :bordered="false" data-testid="dashboard-my-work-board">
    <template #header>
      <div class="my-work-board__header">
        <span>{{ t('dashboard.myWorkBoard.title') }}</span>
      </div>
    </template>

    <n-tabs v-model:value="activeTab" type="line" animated>
      <n-tab-pane name="issues" :tab="t('common.issues')">
        <div class="my-work-board__tab-panel">
          <slot name="issues" />
        </div>
      </n-tab-pane>
      <n-tab-pane name="tasks" :tab="t('common.tasks')">
        <div class="my-work-board__tab-panel">
          <slot name="tasks" />
        </div>
      </n-tab-pane>
    </n-tabs>
  </n-card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NCard, NTabPane, NTabs } from 'naive-ui'
import { useI18n } from 'vue-i18n'

export type BoardKind = 'issues' | 'tasks'

export interface BoardCardItem {
  id: number
  title: string
  subtitle: string
  meta: string[]
  route: string
}

export interface BoardColumn {
  status: string
  label: string
  count: number
  items: BoardCardItem[]
}

const props = defineProps<{
  issueColumns: BoardColumn[]
  taskColumns: BoardColumn[]
  isMobile: boolean
}>()

const { t } = useI18n()
const activeTab = ref<BoardKind>('issues')

const activeColumns = computed(() =>
  activeTab.value === 'issues' ? props.issueColumns : props.taskColumns,
)
</script>
```

- [ ] **Step 2: Replace the slot placeholders with actual column and card rendering**

Update the template so the component renders board columns and clickable cards for the active tab:

```vue
<template>
  <n-card class="my-work-board" :bordered="false" data-testid="dashboard-my-work-board">
    <template #header>
      <div class="my-work-board__header">
        <span>{{ t('dashboard.myWorkBoard.title') }}</span>
      </div>
    </template>

    <div class="my-work-board__tabs">
      <button
        type="button"
        data-testid="my-work-board-tab-issues"
        data-tab-value="issues"
        :data-active="String(activeTab === 'issues')"
        class="my-work-board__tab-button"
        @click="activeTab = 'issues'"
      >
        {{ t('common.issues') }}
      </button>
      <button
        type="button"
        data-testid="my-work-board-tab-tasks"
        data-tab-value="tasks"
        :data-active="String(activeTab === 'tasks')"
        class="my-work-board__tab-button"
        @click="activeTab = 'tasks'"
      >
        {{ t('common.tasks') }}
      </button>
    </div>

    <div v-if="activeColumns.length === 0 || activeColumns.every((column) => column.count === 0)" :data-testid="`my-work-board-empty-${activeTab}`" class="my-work-board__empty">
      {{ t('dashboard.myWorkBoard.emptyBoard') }}
    </div>

    <div v-else class="my-work-board__columns" :class="{ 'my-work-board__columns--mobile': isMobile }">
      <section
        v-for="column in activeColumns"
        :key="`${activeTab}-${column.status}`"
        class="my-work-board__column"
        :data-testid="`${activeTab === 'issues' ? 'issue' : 'task'}-column-${column.status}`"
      >
        <header class="my-work-board__column-header">
          <span>{{ column.label }}</span>
          <span>{{ column.count }}</span>
        </header>

        <div class="my-work-board__column-body">
          <button
            v-for="item in column.items"
            :key="item.id"
            type="button"
            class="my-work-board__card"
            :data-testid="`${activeTab === 'issues' ? 'issue' : 'task'}-card-${item.id}`"
            @click="$emit('select', item.route)"
          >
            <div class="my-work-board__card-title">{{ item.title }}</div>
            <div class="my-work-board__card-subtitle">{{ item.subtitle }}</div>
            <div class="my-work-board__card-meta">{{ item.meta.join(' · ') }}</div>
          </button>

          <div v-if="column.items.length === 0" class="my-work-board__column-empty">
            {{ t('dashboard.myWorkBoard.emptyColumn') }}
          </div>
        </div>
      </section>
    </div>
  </n-card>
</template>
```

Also add the matching script updates:

```ts
const emit = defineEmits<{
  select: [route: string]
}>()
```

and change the click handler to:

```vue
@click="emit('select', item.route)"
```

- [ ] **Step 3: Add scoped styles for responsive columns, fixed-height scroll areas, and cards**

Append these styles to `frontend/src/components/dashboard/MyWorkBoard.vue`:

```vue
<style scoped>
.my-work-board {
  border-radius: var(--app-card-radius);
}

.my-work-board__tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.my-work-board__tab-button {
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: #fff;
  border-radius: 999px;
  padding: 6px 12px;
  cursor: pointer;
}

.my-work-board__tab-button[data-active='true'] {
  background: rgba(24, 160, 88, 0.08);
  border-color: rgba(24, 160, 88, 0.32);
  color: #18a058;
}

.my-work-board__columns {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.my-work-board__columns--mobile {
  grid-template-columns: 1fr;
}

.my-work-board__column {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 12px;
  padding: 12px;
  background: rgba(248, 250, 252, 0.8);
}

.my-work-board__column-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-weight: 600;
}

.my-work-board__column-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 440px;
  overflow-y: auto;
}

.my-work-board__card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  width: 100%;
  text-align: left;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 10px;
  background: #fff;
  padding: 12px;
  cursor: pointer;
}

.my-work-board__card:hover {
  border-color: rgba(24, 160, 88, 0.28);
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06);
}

.my-work-board__card-title {
  font-weight: 600;
  color: var(--n-text-color);
}

.my-work-board__card-subtitle,
.my-work-board__card-meta,
.my-work-board__column-empty,
.my-work-board__empty {
  color: rgba(15, 23, 42, 0.6);
  font-size: 12px;
}
</style>
```

- [ ] **Step 4: Run the dashboard spec again to confirm the component exists but integration still fails**

Run:

```bash
cd /Users/AI/Projects/codify_observe/frontend && npx vitest run src/views/Dashboard.spec.ts
```

Expected: FAIL with grouping / navigation assertions because `Dashboard.vue` does not yet import the new component or provide board props.

- [ ] **Step 5: Commit the new board component**

```bash
git add frontend/src/components/dashboard/MyWorkBoard.vue
git commit -m "feat: add dashboard my work board component"
```

---

### Task 3: Refactor `Dashboard.vue` to fetch and prepare board data

**Files:**
- Modify: `frontend/src/views/Dashboard.vue`
- Create/Use: `frontend/src/components/dashboard/MyWorkBoard.vue`
- Reference: `frontend/src/api/index.ts:706-721`, `frontend/src/api/index.ts:1097-1110`

- [ ] **Step 1: Replace the old table-section template with the new board component**

In `frontend/src/views/Dashboard.vue`, remove the two `n-card` sections with test ids `dashboard-recent-issues` and `dashboard-running-tasks`, and replace them with:

```vue
<MyWorkBoard
  :issue-columns="issueBoardColumns"
  :task-columns="taskBoardColumns"
  :is-mobile="isMobile"
  @select="router.push($event)"
/>
```

Also remove the now-unused `NButton`, `NDataTable`, `NTag`, and `DataTableColumns` imports if they are no longer needed by the file.

- [ ] **Step 2: Import the component and add typed board helpers**

Replace the old issue/task table helpers with these definitions in `frontend/src/views/Dashboard.vue`:

```ts
import MyWorkBoard, { type BoardCardItem, type BoardColumn } from '../components/dashboard/MyWorkBoard.vue'

const issueStatuses = ['open', 'in_progress', 'in_review', 'closed'] as const
const taskStatuses = ['pending', 'queued', 'running', 'completed', 'failed', 'cancelled'] as const

const boardIssues = ref<Issue[]>([])
const boardTasks = ref<Task[]>([])

function buildIssueCard(issue: Issue): BoardCardItem {
  return {
    id: issue.id,
    title: issue.title,
    subtitle: `#${issue.id}`,
    meta: [
      t('dashboard.projectFallback', { id: issue.project_id }),
      `${issue.task_count ?? 0} ${t('issue.field.tasks')}`,
      issue.created_at ? formatDateTimeUtc8Compact(issue.created_at) : '-',
    ],
    route: `/issues/${issue.id}`,
  }
}

function buildTaskCard(task: Task): BoardCardItem {
  return {
    id: task.id,
    title: task.user_prompt,
    subtitle: `#${task.id}`,
    meta: [
      task.project_path_with_namespace || t('dashboard.projectFallback', { id: task.project_id }),
      formatPriority(task.priority),
      formatDateTimeUtc8Compact(task.started_at || task.created_at),
    ],
    route: `/tasks/${task.id}`,
  }
}
```

- [ ] **Step 3: Add grouping computed values and remove the table-only state**

Delete these stale declarations from `Dashboard.vue`:

```ts
const recentIssues = ref<Issue[]>([])
const runningTasks = ref<Task[]>([])
const queuedTasks = ref<Task[]>([])
const runningAndQueuedTasks = computed(() => [...runningTasks.value, ...queuedTasks.value])
const issueColumns = computed<DataTableColumns<Issue>>(() => [/* ... */])
const taskColumns = computed<DataTableColumns<Task>>(() => [/* ... */])
```

and replace them with these computed columns:

```ts
const issueBoardColumns = computed<BoardColumn[]>(() =>
  issueStatuses.map((status) => {
    const items = boardIssues.value.filter((issue) => issue.status === status).map(buildIssueCard)
    return {
      status,
      label: t(`issue.status.${status}`),
      count: items.length,
      items,
    }
  }),
)

const taskBoardColumns = computed<BoardColumn[]>(() =>
  taskStatuses.map((status) => {
    const items = boardTasks.value.filter((task) => task.status === status).map(buildTaskCard)
    return {
      status,
      label: t(`status.${status}`),
      count: items.length,
      items,
    }
  }),
)
```

- [ ] **Step 4: Replace `fetchData()` with a board-oriented data load**

Rewrite `fetchData()` in `frontend/src/views/Dashboard.vue` to fetch one issue page and one task page for the current user:

```ts
async function fetchData() {
  if (loading.value) return
  loading.value = true

  try {
    const userId = authState.user?.id
    const username = authState.user?.username

    const [issuesRes, tasksRes] = await Promise.all([
      getIssues({
        page: 1,
        page_size: 100,
        ...(userId ? { initiator_user_id: userId } : {}),
      }),
      getTasksPaginated({
        page: 1,
        page_size: 100,
        ...(username ? { initiator_username: username } : {}),
      }),
    ])

    boardIssues.value = issuesRes.items
    boardTasks.value = tasksRes.items
  } catch {
    message.error(t('dashboard.failedToFetchTasks'))
  } finally {
    hasLoadedOnce.value = true
    loading.value = false
  }
}
```

This intentionally keeps the existing dashboard-level error behavior and broadens the fetched task scope beyond only `running` / `queued`.

- [ ] **Step 5: Remove dead row handlers and old issue status tag helpers**

Delete these functions and constants from `Dashboard.vue` because the new board does not use table rows or tags:

```ts
function issueRowProps(row: Issue) {
  return { style: 'cursor: pointer', onClick: () => router.push(`/issues/${row.id}`) }
}

function taskRowProps(row: Task) {
  return { style: 'cursor: pointer', onClick: () => router.push(`/tasks/${row.id}`) }
}

const issueStatusColors: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  open: 'default',
  in_progress: 'warning',
  in_review: 'info',
  closed: 'success',
}
```

- [ ] **Step 6: Run the focused dashboard spec to verify the board integration passes**

Run:

```bash
cd /Users/AI/Projects/codify_observe/frontend && npx vitest run src/views/Dashboard.spec.ts
```

Expected: PASS for the new board-rendering, tab, grouping, empty-state, and navigation assertions.

- [ ] **Step 7: Commit the dashboard refactor**

```bash
git add frontend/src/views/Dashboard.vue frontend/src/components/dashboard/MyWorkBoard.vue frontend/src/views/Dashboard.spec.ts
git commit -m "feat: replace dashboard tables with my work board"
```

---

### Task 4: Add the new i18n strings and align tests with the final copy

**Files:**
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`
- Modify: `frontend/src/views/Dashboard.spec.ts`

- [ ] **Step 1: Add the English strings under `dashboard`**

In `frontend/src/i18n/messages/en.ts`, extend the `dashboard` block with:

```ts
myWorkBoard: {
  title: 'My Work Board',
  emptyBoard: 'No items in this view yet.',
  emptyColumn: 'No items in this status.',
},
```

Place it near the existing dashboard labels so the object remains readable.

- [ ] **Step 2: Add the Simplified Chinese strings under `dashboard`**

In `frontend/src/i18n/messages/zh-CN.ts`, extend the `dashboard` block with:

```ts
myWorkBoard: {
  title: '我的工作看板',
  emptyBoard: '当前视图下暂无内容。',
  emptyColumn: '该状态下暂无内容。',
},
```

- [ ] **Step 3: Adjust dashboard spec assertions to match the final translated keys or final copy strategy**

If the spec currently asserts raw i18n keys, keep the test translator stub simple and verify those keys intentionally:

```ts
expect(wrapper.find('[data-testid="my-work-board-empty-issues"]').text()).toContain('dashboard.myWorkBoard.emptyBoard')
expect(wrapper.find('[data-testid="issue-column-open"]').text()).toContain('dashboard.myWorkBoard.emptyColumn')
```

If you instead switch the i18n stub to return readable strings, update the expectations to the actual copy. Pick one approach and use it consistently across all new assertions.

- [ ] **Step 4: Run the dashboard spec again after the copy changes**

Run:

```bash
cd /Users/AI/Projects/codify_observe/frontend && npx vitest run src/views/Dashboard.spec.ts
```

Expected: PASS with the final board copy and no brittle translation mismatches.

- [ ] **Step 5: Commit the localization updates**

```bash
git add frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts frontend/src/views/Dashboard.spec.ts
git commit -m "feat: localize dashboard my work board"
```

---

### Task 5: Run final verification and clean up plan coverage

**Files:**
- Verify: `frontend/src/views/Dashboard.vue`
- Verify: `frontend/src/components/dashboard/MyWorkBoard.vue`
- Verify: `frontend/src/views/Dashboard.spec.ts`
- Verify: `frontend/src/i18n/messages/en.ts`
- Verify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1: Run the focused frontend dashboard test file one final time**

Run:

```bash
cd /Users/AI/Projects/codify_observe/frontend && npx vitest run src/views/Dashboard.spec.ts
```

Expected: PASS.

- [ ] **Step 2: Run the full frontend unit test suite through the project-standard Make target**

Run:

```bash
cd /Users/AI/Projects/codify_observe && make test-frontend
```

Expected: PASS for the full Vitest suite.

- [ ] **Step 3: Do a quick manual self-check against the spec before handing off**

Confirm these exact conditions in the code and test results:

```text
- Dashboard no longer renders Recent Issues or Running sections.
- MyWorkBoard exists as a dedicated component.
- Default tab is Issues.
- Issue columns: open, in_progress, in_review, closed.
- Task columns: pending, queued, running, completed, failed, cancelled.
- Empty columns remain visible.
- Empty tab shows board-level empty state.
- Issue cards route to /issues/:id.
- Task cards route to /tasks/:id.
- English and Chinese strings exist under dashboard.myWorkBoard.
```

- [ ] **Step 4: Commit the final verified state**

```bash
git add frontend/src/views/Dashboard.vue frontend/src/components/dashboard/MyWorkBoard.vue frontend/src/views/Dashboard.spec.ts frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: add dashboard my work board"
```
