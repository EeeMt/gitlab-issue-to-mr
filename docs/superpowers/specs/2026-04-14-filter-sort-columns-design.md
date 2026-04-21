# Linear-Style Filter/Sort/Columns UI Design

**Date:** 2026-04-14
**Status:** Approved
**Scope:** IssueList + TaskList pages — unified filter toolbar, server-side filtering/sorting, column visibility toggles

---

## Overview

Replace the current ad-hoc NSelect dropdowns on IssueList and TaskList with a unified Linear-style toolbar. The toolbar provides search, cascading filter popover, sort controls, and column visibility toggles. State is persisted to localStorage per page.

## Approach

**A. Linear-Style Toolbar** (selected from 3 options):
- Compact icon-button toolbar above the data table
- Popover-based filter/sort/column panels
- Active filters displayed as removable chips
- Generic `useFilterSort` composable + `FilterToolbar` component, configured per page

---

## Component Architecture

### New Files

| File | Purpose |
|------|---------|
| `src/composables/useFilterSort.ts` | State management composable — filters, sort, columns, localStorage, computed API params |
| `src/components/FilterToolbar.vue` | Container: search box, filter/sort/columns buttons, active filter chips |
| `src/components/FilterPopover.vue` | Two-step popover: category list → options panel (checkboxes / radio / date range) |
| `src/components/SortPopover.vue` | Field dropdown + direction toggle |
| `src/components/ColumnsPopover.vue` | Toggle switches per column |

### Modified Files

| File | Change |
|------|--------|
| `src/views/IssueList.vue` | Replace NSelect filters with FilterToolbar, use useFilterSort |
| `src/views/TaskList.vue` | Replace NSelect filters with FilterToolbar, use useFilterSort |
| `src/api/index.ts` | Update `getIssuesPaginated` / `getTasksPaginated` to pass new query params |
| `src/i18n/messages/en.ts` | Add filter/sort/column i18n keys |
| `src/i18n/messages/zh-CN.ts` | Add filter/sort/column i18n keys |
| `backend/app/api/issues.py` | Add search, created_after/before, sort_by/sort_order, multi-status |
| `backend/app/api/tasks.py` | Add priority, search, created_after/before, sort_by/sort_order |

### Data Flow

```
Page config (filterFields[], sortFields[], columns[])
    ↓
useFilterSort(config)
    ↓ returns
{ filters, sort, visibleColumns, apiParams, addFilter, removeFilter, ... }
    ↓ binds to
FilterToolbar.vue (UI) + API calls (apiParams → query string)
```

---

## useFilterSort Composable

```typescript
interface FilterField {
  key: string              // e.g. 'status', 'project_id'
  label: string            // i18n key
  icon: Component          // naive-ui icon
  type: 'multi-select' | 'single-select' | 'date-range'
  options?: () => { label: string; value: any; color?: string; count?: number }[]
  apiParam?: string        // override key name in API query (default: same as key)
}

interface SortField {
  key: string              // e.g. 'created_at', 'priority'
  label: string            // i18n key
}

interface ColumnDef {
  key: string
  label: string
  defaultVisible: boolean
  alwaysVisible?: boolean  // true for title, actions
}

interface FilterSortConfig {
  storageKey: string       // e.g. 'codify:filters:issues'
  filterFields: FilterField[]
  sortFields: SortField[]
  columns: ColumnDef[]
  defaultSort: { field: string; order: 'asc' | 'desc' }
}
```

**Returns:**
- `filters: Ref<Record<string, any>>` — active filter values
- `sort: Ref<{ field: string; order: 'asc' | 'desc' }>` — current sort
- `visibleColumns: Ref<string[]>` — visible column keys
- `apiParams: ComputedRef<Record<string, string>>` — flattened query params for API
- `addFilter(key, value)`, `removeFilter(key)`, `clearAllFilters()`
- `setSort(field, order)`, `resetSort()`
- `toggleColumn(key)`, `resetColumns()`
- `activeFilterCount: ComputedRef<number>`
- `hasActiveFilters: ComputedRef<boolean>`

**Persistence:** On every change, debounce-write to `localStorage[storageKey]`. On init, read from localStorage.

---

## FilterToolbar.vue

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│ [🔍 Search...]  [⊕ Filter]  [↕ Sort: Created ↓]  [⚙ Col]  │  ← toolbar row
│ [Status: Open ✕] [Priority: P0 ✕]           [Clear all]    │  ← chips row (if filters active)
└─────────────────────────────────────────────────────────────┘
```

### Props

```typescript
interface FilterToolbarProps {
  config: FilterSortConfig
  filters: Record<string, any>
  sort: { field: string; order: 'asc' | 'desc' }
  visibleColumns: string[]
  resultCount?: number
  searchPlaceholder?: string
}
```

### Events

```typescript
'update:filters', 'update:sort', 'update:visibleColumns', 'search'
```

---

## FilterPopover.vue — Two-Step Panel

### Step 1: Category List

Shows all available filter categories with icons. Click a category → transitions to Step 2.

### Step 2: Options Panel

Header: `← Back | {Category Name}`

Content varies by field type:
- **multi-select**: Checkboxes with optional color dots and counts. Footer: Clear / Apply.
- **single-select**: Radio buttons or searchable list (for long lists like Project/Issue). Auto-applies on selection.
- **date-range**: NDatePicker with `type="daterange"`. Footer: Clear / Apply.

### Animation

Slide transition between Step 1 and Step 2 (left/right). Panel width fixed at 240px.

---

## SortPopover.vue

```
┌──────────────────────────┐
│ ORDERING                 │
│                          │
│ Sort by                  │
│ [Created time      ▾]   │
│                          │
│ Direction                │
│ [↑ Asc] [↓ Desc ✓]     │
│                          │
│ ─── Reset to default ── │
└──────────────────────────┘
```

Auto-applies on change (no Apply button). Width: 220px.

---

## ColumnsPopover.vue

```
┌──────────────────────────┐
│ COLUMNS                  │
│                          │
│ Status           [====]  │
│ Project          [====]  │
│ Priority         [====]  │
│ Initiator        [    ]  │
│ Branch           [    ]  │
│ Created          [====]  │
│                          │
│ ─── Show all / Reset ── │
└──────────────────────────┘
```

Uses NSwitch for each toggleable column. `alwaysVisible` columns (Title, Actions) not shown. Auto-applies on toggle. Width: 220px.

---

## Backend API Changes

### GET /api/issues — New/Enhanced Parameters

| Param | Type | Description | Change |
|-------|------|-------------|--------|
| `status` | string | Comma-separated status values | **Enhance** — currently single value only |
| `project_id` | int | Filter by project | Exists |
| `search` | string | ILIKE search on title | **New** |
| `created_after` | datetime (ISO) | Created after this time | **New** |
| `created_before` | datetime (ISO) | Created before this time | **New** |
| `sort_by` | enum: `created_at`, `status` | Sort field | **New** (default: `created_at`) |
| `sort_order` | enum: `asc`, `desc` | Sort direction | **New** (default: `desc`) |

### GET /api/tasks — New Parameters

| Param | Type | Description | Change |
|-------|------|-------------|--------|
| `priority` | string | Comma-separated priority values (0,1,2) | **New** |
| `search` | string | ILIKE search on user_prompt | **New** |
| `created_after` | datetime (ISO) | Created after this time | **New** |
| `created_before` | datetime (ISO) | Created before this time | **New** |
| `sort_by` | enum: `created_at`, `status`, `priority` | Sort field | **New** (default: `created_at`) |
| `sort_order` | enum: `asc`, `desc` | Sort direction | **New** (default: `desc`) |

### Implementation Notes

- Search uses `ILIKE '%{term}%'` — no full-text index needed at current scale
- All sorting validates against allowed enum values, rejects unknown fields
- No database migration required — all filters operate on existing columns
- Existing pagination (page/page_size) unchanged

---

## Page Configurations

### IssueList

```typescript
const issueFilterConfig: FilterSortConfig = {
  storageKey: 'codify:filters:issues',
  filterFields: [
    { key: 'status', label: 'filter.status', icon: CircleOutline, type: 'multi-select',
      options: () => [{ label: 'Open', value: 'open', color: '#18a058' }, { label: 'Closed', value: 'closed', color: '#888' }] },
    { key: 'project_id', label: 'filter.project', icon: FolderOutline, type: 'single-select',
      options: () => projects.value.map(p => ({ label: p.name, value: p.id })) },
    { key: 'created', label: 'filter.created', icon: CalendarOutline, type: 'date-range',
      apiParam: 'created_after,created_before' },
  ],
  sortFields: [
    { key: 'created_at', label: 'filter.sortCreated' },
    { key: 'status', label: 'filter.sortStatus' },
  ],
  columns: [
    { key: 'title', label: 'issue.title', defaultVisible: true, alwaysVisible: true },
    { key: 'status', label: 'issue.status', defaultVisible: true },
    { key: 'project', label: 'issue.project', defaultVisible: true },
    { key: 'task_count', label: 'issue.taskCount', defaultVisible: true },
    { key: 'created_at', label: 'issue.created', defaultVisible: true },
  ],
  defaultSort: { field: 'created_at', order: 'desc' },
}
```

### TaskList

```typescript
const taskFilterConfig: FilterSortConfig = {
  storageKey: 'codify:filters:tasks',
  filterFields: [
    { key: 'status', label: 'filter.status', icon: CircleOutline, type: 'multi-select',
      options: () => statusOptions },
    { key: 'project_id', label: 'filter.project', icon: FolderOutline, type: 'single-select',
      options: () => projects.value.map(p => ({ label: p.name, value: p.id })) },
    { key: 'priority', label: 'filter.priority', icon: FlagOutline, type: 'multi-select',
      options: () => [
        { label: 'P0', value: 0, color: '#d03050' },
        { label: 'P1', value: 1, color: '#f0a020' },
        { label: 'P2', value: 2, color: '#18a058' },
      ] },
    { key: 'initiator_username', label: 'filter.initiator', icon: PersonOutline, type: 'single-select',
      options: () => initiators.value.map(u => ({ label: u, value: u })) },
    { key: 'issue_id', label: 'filter.issue', icon: DocumentOutline, type: 'single-select',
      options: () => issues.value.map(i => ({ label: i.title, value: i.id })) },
    { key: 'created', label: 'filter.created', icon: CalendarOutline, type: 'date-range',
      apiParam: 'created_after,created_before' },
  ],
  sortFields: [
    { key: 'created_at', label: 'filter.sortCreated' },
    { key: 'priority', label: 'filter.sortPriority' },
    { key: 'status', label: 'filter.sortStatus' },
  ],
  columns: [
    { key: 'user_prompt', label: 'task.prompt', defaultVisible: true, alwaysVisible: true },
    { key: 'status', label: 'task.status', defaultVisible: true },
    { key: 'project', label: 'task.project', defaultVisible: true },
    { key: 'priority', label: 'task.priority', defaultVisible: true },
    { key: 'initiator', label: 'task.initiator', defaultVisible: false },
    { key: 'issue', label: 'task.issue', defaultVisible: false },
    { key: 'branch', label: 'task.branch', defaultVisible: false },
    { key: 'created_at', label: 'task.created', defaultVisible: true },
  ],
  defaultSort: { field: 'created_at', order: 'desc' },
}
```

---

## i18n Keys

```typescript
// en.ts
filter: {
  search: 'Search...',
  filter: 'Filter',
  sort: 'Sort',
  columns: 'Columns',
  clearAll: 'Clear all',
  clear: 'Clear',
  apply: 'Apply',
  back: 'Back',
  resetDefault: 'Reset to default',
  showAll: 'Show all',
  noResults: 'No results',
  status: 'Status',
  project: 'Project',
  priority: 'Priority',
  initiator: 'Initiator',
  issue: 'Issue',
  created: 'Created',
  sortCreated: 'Created time',
  sortPriority: 'Priority',
  sortStatus: 'Status',
  ascending: 'Ascending',
  descending: 'Descending',
  ordering: 'Ordering',
  sortBy: 'Sort by',
  direction: 'Direction',
  resultCount: '{count} results',
}

// zh-CN.ts
filter: {
  search: '搜索...',
  filter: '筛选',
  sort: '排序',
  columns: '列',
  clearAll: '清除全部',
  clear: '清除',
  apply: '应用',
  back: '返回',
  resetDefault: '恢复默认',
  showAll: '显示全部',
  noResults: '无结果',
  status: '状态',
  project: '项目',
  priority: '优先级',
  initiator: '发起人',
  issue: '需求',
  created: '创建时间',
  sortCreated: '创建时间',
  sortPriority: '优先级',
  sortStatus: '状态',
  ascending: '升序',
  descending: '降序',
  ordering: '排序方式',
  sortBy: '排序字段',
  direction: '排序方向',
  resultCount: '{count} 条结果',
}
```

---

## Error Handling

- Invalid sort_by/sort_order values: backend returns 422 with descriptive error
- Search input: debounced 300ms, min 2 chars to trigger API call
- Empty filter state: no chips shown, all data returned (no filter applied)
- localStorage corruption: fall back to defaults, log warning

---

## Testing Strategy

### Backend Unit Tests
- Test each new query parameter individually and in combination
- Test sort_by/sort_order validation (invalid values → 422)
- Test ILIKE search with special characters (%, _)
- Test date range filtering with timezone handling

### Frontend Unit Tests
- `useFilterSort` composable: state management, localStorage persistence, apiParams computation
- `FilterToolbar`: renders correctly, emits events on interaction
- `FilterPopover`: two-step navigation, category → options → apply
- `SortPopover`: field/direction selection, reset
- `ColumnsPopover`: toggle visibility, always-visible columns

### E2E Tests
- Apply filter → verify table updates
- Apply sort → verify row order changes
- Toggle column → verify column hidden/shown
- Search → verify filtered results
- Clear all → verify reset to unfiltered state
- Refresh page → verify localStorage restoration

---

## Non-Goals (Explicit Exclusions)

- Filter presets / saved filters — future iteration
- Per-user server-side filter persistence — localStorage only
- Card/kanban view toggle — table view only
- Full-text search with ranking — simple ILIKE sufficient
- URL query param sync — localStorage only as chosen
