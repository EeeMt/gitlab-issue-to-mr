# Linear-Style Filter/Sort/Columns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ad-hoc NSelect dropdowns on IssueList and TaskList with a unified Linear-style filter toolbar featuring search, cascading filter popover, sort controls, and column visibility toggles.

**Architecture:** A `useFilterSort` composable manages all filter/sort/column state with localStorage persistence and computed API params. A `FilterToolbar` component wraps search, filter, sort, and column popover sub-components. Backend APIs are enhanced with search, date-range, sort, and priority query parameters.

**Tech Stack:** Vue 3, Naive UI (NPopover, NCheckbox, NSwitch, NInput, NDatePicker, NTag), TypeScript, FastAPI, SQLAlchemy

---

## File Map

### New Files (Frontend)
| File | Responsibility |
|------|---------------|
| `frontend/src/composables/useFilterSort.ts` | State management: filters, sort, columns, localStorage persistence, computed apiParams |
| `frontend/src/components/filter/FilterToolbar.vue` | Container: search, filter/sort/columns buttons, active filter chips |
| `frontend/src/components/filter/FilterPopover.vue` | Two-step popover: category list → options panel |
| `frontend/src/components/filter/SortPopover.vue` | Sort field dropdown + direction toggle |
| `frontend/src/components/filter/ColumnsPopover.vue` | Column visibility toggle switches |
| `frontend/src/composables/useFilterSort.spec.ts` | Unit tests for composable |

### Modified Files (Frontend)
| File | Change |
|------|--------|
| `frontend/src/views/IssueList.vue` | Replace NSelect filters with FilterToolbar |
| `frontend/src/views/TaskList.vue` | Replace NSelect filters with FilterToolbar |
| `frontend/src/api/index.ts` | Add new query params to `getIssues` and `getTasksPaginated` |
| `frontend/src/i18n/messages/en.ts` | Add `filter.*` i18n keys |
| `frontend/src/i18n/messages/zh-CN.ts` | Add `filter.*` i18n keys |

### Modified Files (Backend)
| File | Change |
|------|--------|
| `backend/app/api/issues.py` | Add search, created_after/before, sort_by/sort_order, multi-status params |
| `backend/app/api/tasks.py` | Add priority, search, created_after/before, sort_by/sort_order params |

### New Test Files
| File | Responsibility |
|------|---------------|
| `backend/tests/unit/test_issues_api_filters.py` | Tests for new issues query params |
| `backend/tests/unit/test_tasks_api_filters.py` | Tests for new tasks query params |

---

### Task 1: Backend — Enhance Issues API with Search, Sort, Date Range, Multi-Status

**Files:**
- Modify: `backend/app/api/issues.py:150-226`
- Test: `backend/tests/unit/test_issues_api_filters.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_issues_api_filters.py`:

```python
"""Tests for enhanced issues list filtering, sorting, and search."""

import sys
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def _make_issue(**overrides):
    issue = MagicMock()
    defaults = {
        "id": 1,
        "title": "Test Issue",
        "description": "desc",
        "project_id": 10,
        "status": "open",
        "branch_name": None,
        "base_branch": None,
        "target_branch": None,
        "merge_request_iid": None,
        "merge_request_url": None,
        "claude_session_id": None,
        "session_storage_path": None,
        "initiator_user_id": 1,
        "initiator_username": "alice",
        "created_at": datetime(2026, 1, 1, 12, 0, 0),
        "updated_at": datetime(2026, 1, 1, 12, 0, 0),
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(issue, k, v)
    return issue


class TestListIssuesMultiStatus(unittest.IsolatedAsyncioTestCase):
    """Test comma-separated multi-status filtering on GET /api/issues."""

    @patch("app.api.issues.get_db")
    async def test_multi_status_accepted(self, _mock_db):
        """Passing status=open,closed should not raise 400."""
        from starlette.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.get("/api/issues?status=open,closed", headers={"Cookie": "session=test"})
        # Should NOT be 400 — multi-status is now accepted
        self.assertNotEqual(response.status_code, 400)


class TestListIssuesSortParams(unittest.IsolatedAsyncioTestCase):
    """Test sort_by and sort_order params on GET /api/issues."""

    async def test_invalid_sort_by_returns_422(self):
        from starlette.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.get("/api/issues?sort_by=invalid_field", headers={"Cookie": "session=test"})
        self.assertIn(response.status_code, [400, 422])

    async def test_invalid_sort_order_returns_422(self):
        from starlette.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.get("/api/issues?sort_order=random", headers={"Cookie": "session=test"})
        self.assertIn(response.status_code, [400, 422])


class TestListIssuesSearchParam(unittest.IsolatedAsyncioTestCase):
    """Test search param on GET /api/issues."""

    async def test_search_param_accepted(self):
        from starlette.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.get("/api/issues?search=auth", headers={"Cookie": "session=test"})
        # Should not be 422 — search is a valid param
        self.assertNotEqual(response.status_code, 422)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_issues_api_filters.py -v --no-header 2>&1 | head -30`
Expected: Failures for multi-status (400 error), invalid sort_by (no 422), search (422 unknown param)

- [ ] **Step 3: Implement enhanced list_issues endpoint**

In `backend/app/api/issues.py`, replace the `list_issues` function (lines 150-243) with:

```python
ISSUES_SORT_FIELDS = {"created_at", "status"}
SORT_ORDERS = {"asc", "desc"}


@router.get("")
async def list_issues(
    status: Optional[str] = None,
    project_id: Optional[int] = None,
    initiator_user_id: Optional[int] = None,
    search: Optional[str] = None,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """List issues with optional filtering, sorting, and pagination."""
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    offset = (page - 1) * page_size

    # Validate sort params
    effective_sort_by = "created_at"
    effective_sort_order = "desc"
    if sort_by:
        if sort_by not in ISSUES_SORT_FIELDS:
            raise HTTPException(status_code=400, detail=f"Invalid sort_by: {sort_by}. Allowed: {', '.join(sorted(ISSUES_SORT_FIELDS))}")
        effective_sort_by = sort_by
    if sort_order:
        if sort_order not in SORT_ORDERS:
            raise HTTPException(status_code=400, detail=f"Invalid sort_order: {sort_order}. Allowed: asc, desc")
        effective_sort_order = sort_order

    # Build a subquery for task_count and totals
    task_agg_subq = (
        select(
            Task.issue_id,
            func.count(Task.id).label("task_count"),
            func.coalesce(func.sum(Task.additions), 0).label("total_additions"),
            func.coalesce(func.sum(Task.deletions), 0).label("total_deletions"),
            func.coalesce(func.sum(Task.total_changes), 0).label("total_changes"),
            func.coalesce(func.sum(Task.input_tokens), 0).label("total_input_tokens"),
            func.coalesce(func.sum(Task.output_tokens), 0).label("total_output_tokens"),
        )
        .group_by(Task.issue_id)
        .subquery()
    )

    # Determine sort column and direction
    sort_column = getattr(Issue, effective_sort_by)
    order_clause = sort_column.asc() if effective_sort_order == "asc" else sort_column.desc()

    query = (
        select(
            Issue,
            task_agg_subq.c.task_count,
            task_agg_subq.c.total_additions,
            task_agg_subq.c.total_deletions,
            task_agg_subq.c.total_changes,
            task_agg_subq.c.total_input_tokens,
            task_agg_subq.c.total_output_tokens,
        )
        .outerjoin(task_agg_subq, Issue.id == task_agg_subq.c.issue_id)
        .order_by(order_clause)
    )

    # Multi-status filter (comma-separated)
    if status:
        status_parts = [s.strip() for s in status.split(",") if s.strip()]
        valid_statuses = []
        for part in status_parts:
            try:
                valid_statuses.append(IssueStatus(part))
            except ValueError:
                pass
        if len(valid_statuses) == 1:
            query = query.where(Issue.status == valid_statuses[0])
        elif valid_statuses:
            query = query.where(Issue.status.in_(valid_statuses))

    if project_id is not None:
        query = query.where(Issue.project_id == project_id)
    elif not access_scope.is_unrestricted:
        allowed_project_ids = access_scope.accessible_project_ids
        if not allowed_project_ids:
            query = query.where(false())
        else:
            query = query.where(Issue.project_id.in_(allowed_project_ids))

    if initiator_user_id is not None:
        query = query.where(Issue.initiator_user_id == initiator_user_id)

    # Text search on title
    if search and len(search) >= 2:
        query = query.where(Issue.title.ilike(f"%{search}%"))

    # Date range filters
    if created_after:
        try:
            dt = datetime.fromisoformat(created_after.replace("Z", "+00:00"))
            query = query.where(Issue.created_at >= dt)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid created_after: {created_after}")
    if created_before:
        try:
            dt = datetime.fromisoformat(created_before.replace("Z", "+00:00"))
            query = query.where(Issue.created_at <= dt)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid created_before: {created_before}")

    # Total count
    count_q = select(func.count()).select_from(
        query.with_only_columns(Issue.id).subquery()
    )
    total = (await db.execute(count_q)).scalar() or 0

    result = await db.execute(query.limit(page_size).offset(offset))
    rows = result.all()
    # ... rest of serialization unchanged
```

Add `from datetime import datetime` to the imports at the top of the file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/test_issues_api_filters.py -v --no-header 2>&1 | head -30`
Expected: All tests PASS

- [ ] **Step 5: Run existing issues tests to verify no regression**

Run: `cd backend && python -m pytest tests/unit/test_issues_api.py -v --no-header 2>&1 | tail -20`
Expected: All existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/issues.py backend/tests/unit/test_issues_api_filters.py
git commit -m "feat(api): enhance issues list with search, sort, date range, multi-status

- Add search param (ILIKE on title)
- Add sort_by/sort_order params (created_at, status)
- Add created_after/created_before date range params
- Change status to support comma-separated multi-values

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Backend — Enhance Tasks API with Priority, Search, Sort, Date Range

**Files:**
- Modify: `backend/app/api/tasks.py:48-131`
- Test: `backend/tests/unit/test_tasks_api_filters.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_tasks_api_filters.py`:

```python
"""Tests for enhanced tasks list filtering, sorting, and search."""

import sys
import os
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class TestListTasksSortParams(unittest.IsolatedAsyncioTestCase):
    """Test sort_by and sort_order params on GET /api/tasks."""

    async def test_invalid_sort_by_returns_400(self):
        from starlette.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.get("/api/tasks?sort_by=invalid_field&page=1", headers={"Cookie": "session=test"})
        self.assertIn(response.status_code, [400, 422])

    async def test_invalid_sort_order_returns_400(self):
        from starlette.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.get("/api/tasks?sort_order=random&page=1", headers={"Cookie": "session=test"})
        self.assertIn(response.status_code, [400, 422])

    async def test_valid_sort_params_accepted(self):
        from starlette.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.get("/api/tasks?sort_by=priority&sort_order=asc&page=1", headers={"Cookie": "session=test"})
        self.assertNotEqual(response.status_code, 400)

    async def test_search_param_accepted(self):
        from starlette.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.get("/api/tasks?search=refactor&page=1", headers={"Cookie": "session=test"})
        self.assertNotEqual(response.status_code, 422)

    async def test_priority_filter_accepted(self):
        from starlette.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.get("/api/tasks?priority=0,1&page=1", headers={"Cookie": "session=test"})
        self.assertNotEqual(response.status_code, 422)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_tasks_api_filters.py -v --no-header 2>&1 | head -30`
Expected: Failures for sort_by (no 400 for invalid), search (422), priority (422)

- [ ] **Step 3: Implement enhanced list_tasks endpoint**

In `backend/app/api/tasks.py`, replace the `list_tasks` function (lines 48-131):

```python
TASKS_SORT_FIELDS = {"created_at", "status", "priority"}
SORT_ORDERS = {"asc", "desc"}


@router.get("/tasks")
async def list_tasks(
    status: Optional[str] = None,
    project_id: Optional[int] = None,
    issue_id: Optional[int] = None,
    initiator_username: Optional[str] = None,
    priority: Optional[str] = None,
    search: Optional[str] = None,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    page: Optional[int] = None,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """List tasks with optional filtering, sorting, and pagination.

    When ``page`` is provided, returns ``{items, total, page, page_size}``.
    Without ``page``, returns a plain ``Task[]`` array (legacy behaviour).
    """
    # Validate sort params
    effective_sort_by = "created_at"
    effective_sort_order = "desc"
    if sort_by:
        if sort_by not in TASKS_SORT_FIELDS:
            raise HTTPException(status_code=400, detail=f"Invalid sort_by: {sort_by}. Allowed: {', '.join(sorted(TASKS_SORT_FIELDS))}")
        effective_sort_by = sort_by
    if sort_order:
        if sort_order not in SORT_ORDERS:
            raise HTTPException(status_code=400, detail=f"Invalid sort_order: {sort_order}. Allowed: asc, desc")
        effective_sort_order = sort_order

    # Determine sort column and direction
    sort_column = getattr(Task, effective_sort_by)
    order_clause = sort_column.asc() if effective_sort_order == "asc" else sort_column.desc()

    query = select(Task).options(selectinload(Task.issue)).order_by(order_clause)

    if status:
        status_parts = [s.strip() for s in status.split(",") if s.strip()]
        valid_statuses = []
        for part in status_parts:
            try:
                valid_statuses.append(TaskStatus(part))
            except ValueError:
                pass
        if len(valid_statuses) == 1:
            query = query.where(Task.status == valid_statuses[0])
        elif valid_statuses:
            query = query.where(Task.status.in_(valid_statuses))

    if project_id:
        query = query.where(Task.project_id == project_id)
    elif not access_scope.is_unrestricted:
        allowed_project_ids = access_scope.accessible_project_ids
        if not allowed_project_ids:
            query = query.where(false())
        else:
            query = query.where(Task.project_id.in_(allowed_project_ids))

    if initiator_username:
        query = query.where(Task.initiator_username == initiator_username)

    if issue_id:
        query = query.where(Task.issue_id == issue_id)

    # Priority filter (comma-separated integers: "0,1")
    if priority:
        priority_parts = [p.strip() for p in priority.split(",") if p.strip()]
        valid_priorities = []
        for p in priority_parts:
            try:
                valid_priorities.append(int(p))
            except ValueError:
                pass
        if len(valid_priorities) == 1:
            query = query.where(Task.priority == valid_priorities[0])
        elif valid_priorities:
            query = query.where(Task.priority.in_(valid_priorities))

    # Text search on user_prompt
    if search and len(search) >= 2:
        query = query.where(Task.user_prompt.ilike(f"%{search}%"))

    # Date range filters
    if created_after:
        try:
            dt = datetime.fromisoformat(created_after.replace("Z", "+00:00"))
            query = query.where(Task.created_at >= dt)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid created_after: {created_after}")
    if created_before:
        try:
            dt = datetime.fromisoformat(created_before.replace("Z", "+00:00"))
            query = query.where(Task.created_at <= dt)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid created_before: {created_before}")

    project_lookup = await build_project_lookup(
        accessible_projects=access_scope.accessible_projects,
        is_unrestricted=access_scope.is_unrestricted,
    )

    # Paginated mode
    if page is not None:
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size

        count_result = await db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar() or 0

        result = await db.execute(query.limit(page_size).offset(offset))
        tasks = result.scalars().all()

        return {
            "items": [
                _serialize_task(task, project_lookup.get(task.project_id))
                for task in tasks
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # Legacy mode
    result = await db.execute(query.limit(100))
    tasks = result.scalars().all()

    return [
        _serialize_task(task, project_lookup.get(task.project_id))
        for task in tasks
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/test_tasks_api_filters.py -v --no-header 2>&1 | head -30`
Expected: All tests PASS

- [ ] **Step 5: Run existing tasks tests to verify no regression**

Run: `cd backend && python -m pytest tests/unit/test_tasks_api.py -v --no-header 2>&1 | tail -20`
Expected: All existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/tasks.py backend/tests/unit/test_tasks_api_filters.py
git commit -m "feat(api): enhance tasks list with priority, search, sort, date range

- Add priority param (comma-separated integers)
- Add search param (ILIKE on user_prompt)
- Add sort_by/sort_order params (created_at, status, priority)
- Add created_after/created_before date range params

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Frontend — Create useFilterSort Composable

**Files:**
- Create: `frontend/src/composables/useFilterSort.ts`
- Test: `frontend/src/composables/useFilterSort.spec.ts` (create)

- [ ] **Step 1: Write the tests**

Create `frontend/src/composables/useFilterSort.spec.ts`:

```typescript
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { nextTick } from 'vue'
import { useFilterSort, type FilterSortConfig, type FilterField, type SortField, type ColumnDef } from './useFilterSort'

const mockConfig: FilterSortConfig = {
  storageKey: 'codify:filters:test',
  filterFields: [
    { key: 'status', label: 'Status', type: 'multi-select', options: () => [
      { label: 'Open', value: 'open' },
      { label: 'Closed', value: 'closed' },
    ] },
    { key: 'project_id', label: 'Project', type: 'single-select', options: () => [
      { label: 'App', value: 1 },
    ] },
  ] as FilterField[],
  sortFields: [
    { key: 'created_at', label: 'Created' },
    { key: 'status', label: 'Status' },
  ] as SortField[],
  columns: [
    { key: 'title', label: 'Title', defaultVisible: true, alwaysVisible: true },
    { key: 'status', label: 'Status', defaultVisible: true },
    { key: 'project', label: 'Project', defaultVisible: true },
    { key: 'creator', label: 'Creator', defaultVisible: false },
  ] as ColumnDef[],
  defaultSort: { field: 'created_at', order: 'desc' },
}

describe('useFilterSort', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('initializes with empty filters and default sort', () => {
    const { filters, sort, activeFilterCount } = useFilterSort(mockConfig)
    expect(filters.value).toEqual({})
    expect(sort.value).toEqual({ field: 'created_at', order: 'desc' })
    expect(activeFilterCount.value).toBe(0)
  })

  it('adds and removes a filter', () => {
    const { filters, addFilter, removeFilter, activeFilterCount } = useFilterSort(mockConfig)
    addFilter('status', ['open'])
    expect(filters.value.status).toEqual(['open'])
    expect(activeFilterCount.value).toBe(1)

    removeFilter('status')
    expect(filters.value.status).toBeUndefined()
    expect(activeFilterCount.value).toBe(0)
  })

  it('clears all filters', () => {
    const { filters, addFilter, clearAllFilters } = useFilterSort(mockConfig)
    addFilter('status', ['open'])
    addFilter('project_id', 1)
    clearAllFilters()
    expect(filters.value).toEqual({})
  })

  it('sets sort field and order', () => {
    const { sort, setSort } = useFilterSort(mockConfig)
    setSort('status', 'asc')
    expect(sort.value).toEqual({ field: 'status', order: 'asc' })
  })

  it('resets sort to default', () => {
    const { sort, setSort, resetSort } = useFilterSort(mockConfig)
    setSort('status', 'asc')
    resetSort()
    expect(sort.value).toEqual({ field: 'created_at', order: 'desc' })
  })

  it('initializes column visibility from defaults', () => {
    const { visibleColumns } = useFilterSort(mockConfig)
    expect(visibleColumns.value).toContain('title')
    expect(visibleColumns.value).toContain('status')
    expect(visibleColumns.value).toContain('project')
    expect(visibleColumns.value).not.toContain('creator')
  })

  it('toggles column visibility', () => {
    const { visibleColumns, toggleColumn } = useFilterSort(mockConfig)
    toggleColumn('creator')
    expect(visibleColumns.value).toContain('creator')
    toggleColumn('creator')
    expect(visibleColumns.value).not.toContain('creator')
  })

  it('cannot hide alwaysVisible columns', () => {
    const { visibleColumns, toggleColumn } = useFilterSort(mockConfig)
    toggleColumn('title')
    expect(visibleColumns.value).toContain('title')
  })

  it('computes apiParams from filters and sort', () => {
    const { apiParams, addFilter, setSort } = useFilterSort(mockConfig)
    addFilter('status', ['open', 'closed'])
    setSort('status', 'asc')
    expect(apiParams.value.status).toBe('open,closed')
    expect(apiParams.value.sort_by).toBe('status')
    expect(apiParams.value.sort_order).toBe('asc')
  })

  it('persists to and restores from localStorage', () => {
    const { addFilter, setSort, toggleColumn } = useFilterSort(mockConfig)
    addFilter('status', ['open'])
    setSort('status', 'asc')
    toggleColumn('creator')

    // Create a new instance — should restore from localStorage
    const { filters: f2, sort: s2, visibleColumns: v2 } = useFilterSort(mockConfig)
    expect(f2.value.status).toEqual(['open'])
    expect(s2.value).toEqual({ field: 'status', order: 'asc' })
    expect(v2.value).toContain('creator')
  })

  it('handles corrupted localStorage gracefully', () => {
    localStorage.setItem('codify:filters:test', 'not-valid-json')
    const { filters, sort } = useFilterSort(mockConfig)
    expect(filters.value).toEqual({})
    expect(sort.value).toEqual({ field: 'created_at', order: 'desc' })
  })

  it('omits default sort from apiParams', () => {
    const { apiParams } = useFilterSort(mockConfig)
    // Default sort should still be present for API clarity
    expect(apiParams.value.sort_by).toBe('created_at')
    expect(apiParams.value.sort_order).toBe('desc')
  })

  it('handles date-range filter in apiParams', () => {
    const configWithDate: FilterSortConfig = {
      ...mockConfig,
      filterFields: [
        ...mockConfig.filterFields,
        { key: 'created', label: 'Created', type: 'date-range', apiParam: 'created_after,created_before' } as FilterField,
      ],
    }
    const { apiParams, addFilter } = useFilterSort(configWithDate)
    addFilter('created', [1704067200000, 1704153600000])
    expect(apiParams.value.created_after).toBeDefined()
    expect(apiParams.value.created_before).toBeDefined()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/composables/useFilterSort.spec.ts --no-color 2>&1 | tail -20`
Expected: FAIL — module not found

- [ ] **Step 3: Implement useFilterSort composable**

Create `frontend/src/composables/useFilterSort.ts`:

```typescript
import { ref, computed, watch, type Ref, type ComputedRef, type Component } from 'vue'

export interface FilterField {
  key: string
  label: string
  icon?: Component
  type: 'multi-select' | 'single-select' | 'date-range'
  options?: () => { label: string; value: any; color?: string; count?: number }[]
  apiParam?: string
}

export interface SortField {
  key: string
  label: string
}

export interface ColumnDef {
  key: string
  label: string
  defaultVisible: boolean
  alwaysVisible?: boolean
}

export interface FilterSortConfig {
  storageKey: string
  filterFields: FilterField[]
  sortFields: SortField[]
  columns: ColumnDef[]
  defaultSort: { field: string; order: 'asc' | 'desc' }
}

interface PersistedState {
  filters: Record<string, any>
  sort: { field: string; order: 'asc' | 'desc' }
  visibleColumns: string[]
}

function loadFromStorage(key: string): PersistedState | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object' && 'filters' in parsed) {
      return parsed as PersistedState
    }
    return null
  } catch {
    return null
  }
}

function saveToStorage(key: string, state: PersistedState) {
  try {
    localStorage.setItem(key, JSON.stringify(state))
  } catch {
    // localStorage full or unavailable
  }
}

export function useFilterSort(config: FilterSortConfig) {
  const saved = loadFromStorage(config.storageKey)

  const filters: Ref<Record<string, any>> = ref(saved?.filters ?? {})
  const sort: Ref<{ field: string; order: 'asc' | 'desc' }> = ref(
    saved?.sort ?? { ...config.defaultSort }
  )

  const defaultVisibleColumns = config.columns
    .filter((c) => c.defaultVisible)
    .map((c) => c.key)
  const visibleColumns: Ref<string[]> = ref(saved?.visibleColumns ?? [...defaultVisibleColumns])

  function persist() {
    saveToStorage(config.storageKey, {
      filters: filters.value,
      sort: sort.value,
      visibleColumns: visibleColumns.value,
    })
  }

  function addFilter(key: string, value: any) {
    filters.value = { ...filters.value, [key]: value }
    persist()
  }

  function removeFilter(key: string) {
    const next = { ...filters.value }
    delete next[key]
    filters.value = next
    persist()
  }

  function clearAllFilters() {
    filters.value = {}
    persist()
  }

  function setSort(field: string, order: 'asc' | 'desc') {
    sort.value = { field, order }
    persist()
  }

  function resetSort() {
    sort.value = { ...config.defaultSort }
    persist()
  }

  function toggleColumn(key: string) {
    const col = config.columns.find((c) => c.key === key)
    if (col?.alwaysVisible) return
    const current = visibleColumns.value
    if (current.includes(key)) {
      visibleColumns.value = current.filter((k) => k !== key)
    } else {
      visibleColumns.value = [...current, key]
    }
    persist()
  }

  function resetColumns() {
    visibleColumns.value = [...defaultVisibleColumns]
    persist()
  }

  const activeFilterCount: ComputedRef<number> = computed(() => {
    return Object.keys(filters.value).length
  })

  const hasActiveFilters: ComputedRef<boolean> = computed(() => {
    return activeFilterCount.value > 0
  })

  const apiParams: ComputedRef<Record<string, string>> = computed(() => {
    const params: Record<string, string> = {}

    // Filters
    for (const field of config.filterFields) {
      const val = filters.value[field.key]
      if (val === undefined || val === null) continue

      if (field.type === 'date-range' && field.apiParam) {
        const [afterKey, beforeKey] = field.apiParam.split(',').map((s) => s.trim())
        if (Array.isArray(val) && val.length === 2) {
          if (val[0]) params[afterKey] = new Date(val[0]).toISOString()
          if (val[1]) params[beforeKey] = new Date(val[1]).toISOString()
        }
      } else if (field.type === 'multi-select' && Array.isArray(val)) {
        if (val.length > 0) {
          params[field.apiParam ?? field.key] = val.join(',')
        }
      } else {
        params[field.apiParam ?? field.key] = String(val)
      }
    }

    // Sort
    params.sort_by = sort.value.field
    params.sort_order = sort.value.order

    return params
  })

  return {
    filters,
    sort,
    visibleColumns,
    apiParams,
    addFilter,
    removeFilter,
    clearAllFilters,
    setSort,
    resetSort,
    toggleColumn,
    resetColumns,
    activeFilterCount,
    hasActiveFilters,
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/composables/useFilterSort.spec.ts --no-color 2>&1 | tail -20`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/composables/useFilterSort.ts frontend/src/composables/useFilterSort.spec.ts
git commit -m "feat: add useFilterSort composable with localStorage persistence

- Manages filter, sort, column visibility state
- Computes flat apiParams for API calls
- Persists to localStorage per storageKey
- Handles corrupted storage gracefully

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Frontend — Create FilterPopover Component

**Files:**
- Create: `frontend/src/components/filter/FilterPopover.vue`

- [ ] **Step 1: Create the filter directory**

```bash
mkdir -p frontend/src/components/filter
```

- [ ] **Step 2: Implement FilterPopover.vue**

Create `frontend/src/components/filter/FilterPopover.vue`:

```vue
<template>
  <div class="filter-popover">
    <transition name="filter-slide" mode="out-in">
      <!-- Step 1: Category List -->
      <div v-if="!selectedCategory" key="categories" class="filter-popover__categories">
        <div class="filter-popover__header">{{ t('filter.filter') }}</div>
        <div
          v-for="field in fields"
          :key="field.key"
          class="filter-popover__item"
          :class="{ 'filter-popover__item--active': hasFilter(field.key) }"
          @click="selectCategory(field)"
        >
          <n-icon v-if="field.icon" size="16" class="filter-popover__item-icon">
            <component :is="field.icon" />
          </n-icon>
          <span class="filter-popover__item-label">{{ t(field.label) }}</span>
          <span v-if="hasFilter(field.key)" class="filter-popover__item-dot" />
          <span class="filter-popover__item-arrow">›</span>
        </div>
      </div>

      <!-- Step 2: Options Panel -->
      <div v-else key="options" class="filter-popover__options">
        <div class="filter-popover__options-header">
          <span class="filter-popover__back" @click="selectedCategory = null">← {{ t('filter.back') }}</span>
          <span class="filter-popover__options-title">{{ t(selectedCategory.label) }}</span>
        </div>

        <!-- Multi-select: checkboxes -->
        <template v-if="selectedCategory.type === 'multi-select'">
          <n-checkbox-group v-model:value="tempMultiValue" class="filter-popover__checkbox-group">
            <div
              v-for="opt in categoryOptions"
              :key="opt.value"
              class="filter-popover__option-row"
            >
              <n-checkbox :value="opt.value" :label="opt.label">
                <template #default>
                  <div class="filter-popover__option-content">
                    <span v-if="opt.color" class="filter-popover__color-dot" :style="{ background: opt.color }" />
                    <span>{{ opt.label }}</span>
                  </div>
                </template>
              </n-checkbox>
              <span v-if="opt.count !== undefined" class="filter-popover__count">{{ opt.count }}</span>
            </div>
          </n-checkbox-group>
          <div class="filter-popover__footer">
            <span class="filter-popover__footer-action" @click="clearCurrent">{{ t('filter.clear') }}</span>
            <span class="filter-popover__footer-action filter-popover__footer-action--primary" @click="applyMulti">{{ t('filter.apply') }}</span>
          </div>
        </template>

        <!-- Single-select: radio-style list -->
        <template v-else-if="selectedCategory.type === 'single-select'">
          <n-input
            v-if="categoryOptions.length > 6"
            v-model:value="optionSearch"
            :placeholder="t('filter.search')"
            size="small"
            clearable
            class="filter-popover__search"
          />
          <div
            v-for="opt in filteredOptions"
            :key="opt.value"
            class="filter-popover__option-row filter-popover__option-row--clickable"
            :class="{ 'filter-popover__option-row--selected': filters[selectedCategory.key] === opt.value }"
            @click="applySingle(opt.value)"
          >
            <span v-if="opt.color" class="filter-popover__color-dot" :style="{ background: opt.color }" />
            <span>{{ opt.label }}</span>
          </div>
          <div class="filter-popover__footer">
            <span class="filter-popover__footer-action" @click="clearCurrent">{{ t('filter.clear') }}</span>
          </div>
        </template>

        <!-- Date range -->
        <template v-else-if="selectedCategory.type === 'date-range'">
          <n-date-picker
            v-model:value="tempDateRange"
            type="daterange"
            clearable
            class="filter-popover__date-picker"
          />
          <div class="filter-popover__footer">
            <span class="filter-popover__footer-action" @click="clearCurrent">{{ t('filter.clear') }}</span>
            <span class="filter-popover__footer-action filter-popover__footer-action--primary" @click="applyDate">{{ t('filter.apply') }}</span>
          </div>
        </template>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { NIcon, NCheckboxGroup, NCheckbox, NInput, NDatePicker } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { FilterField } from '../../composables/useFilterSort'

const props = defineProps<{
  fields: FilterField[]
  filters: Record<string, any>
}>()

const emit = defineEmits<{
  (e: 'addFilter', key: string, value: any): void
  (e: 'removeFilter', key: string): void
}>()

const { t } = useI18n()
const selectedCategory = ref<FilterField | null>(null)
const tempMultiValue = ref<any[]>([])
const tempDateRange = ref<[number, number] | null>(null)
const optionSearch = ref('')

function hasFilter(key: string): boolean {
  const val = props.filters[key]
  if (val === undefined || val === null) return false
  if (Array.isArray(val)) return val.length > 0
  return true
}

const categoryOptions = computed(() => {
  if (!selectedCategory.value?.options) return []
  return selectedCategory.value.options()
})

const filteredOptions = computed(() => {
  if (!optionSearch.value) return categoryOptions.value
  const q = optionSearch.value.toLowerCase()
  return categoryOptions.value.filter((o) => o.label.toLowerCase().includes(q))
})

function selectCategory(field: FilterField) {
  selectedCategory.value = field
  optionSearch.value = ''
  if (field.type === 'multi-select') {
    tempMultiValue.value = props.filters[field.key] ? [...props.filters[field.key]] : []
  } else if (field.type === 'date-range') {
    tempDateRange.value = props.filters[field.key] ?? null
  }
}

function applyMulti() {
  if (!selectedCategory.value) return
  if (tempMultiValue.value.length > 0) {
    emit('addFilter', selectedCategory.value.key, [...tempMultiValue.value])
  } else {
    emit('removeFilter', selectedCategory.value.key)
  }
  selectedCategory.value = null
}

function applySingle(value: any) {
  if (!selectedCategory.value) return
  emit('addFilter', selectedCategory.value.key, value)
  selectedCategory.value = null
}

function applyDate() {
  if (!selectedCategory.value) return
  if (tempDateRange.value) {
    emit('addFilter', selectedCategory.value.key, [...tempDateRange.value])
  } else {
    emit('removeFilter', selectedCategory.value.key)
  }
  selectedCategory.value = null
}

function clearCurrent() {
  if (!selectedCategory.value) return
  emit('removeFilter', selectedCategory.value.key)
  selectedCategory.value = null
}
</script>

<style scoped>
.filter-popover {
  width: 240px;
  max-height: 360px;
  overflow-y: auto;
}
.filter-popover__header {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--n-text-color-3, #888);
  padding: 8px 12px 4px;
}
.filter-popover__item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  border-radius: 4px;
  margin: 0 4px;
  transition: background 0.15s;
}
.filter-popover__item:hover {
  background: var(--n-color-hover, rgba(255,255,255,0.06));
}
.filter-popover__item--active {
  color: var(--n-primary-color, #4080ff);
}
.filter-popover__item-icon {
  flex-shrink: 0;
}
.filter-popover__item-label {
  flex: 1;
}
.filter-popover__item-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--n-primary-color, #4080ff);
}
.filter-popover__item-arrow {
  color: var(--n-text-color-3, #888);
  font-size: 14px;
}
.filter-popover__options-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--n-border-color, #333);
  margin-bottom: 4px;
}
.filter-popover__back {
  color: var(--n-primary-color, #4080ff);
  cursor: pointer;
  font-size: 13px;
}
.filter-popover__options-title {
  font-weight: 600;
  font-size: 13px;
}
.filter-popover__checkbox-group {
  display: flex;
  flex-direction: column;
  padding: 0 8px;
}
.filter-popover__option-row {
  display: flex;
  align-items: center;
  padding: 6px 12px;
  gap: 8px;
}
.filter-popover__option-row--clickable {
  cursor: pointer;
  border-radius: 4px;
  margin: 0 4px;
}
.filter-popover__option-row--clickable:hover {
  background: var(--n-color-hover, rgba(255,255,255,0.06));
}
.filter-popover__option-row--selected {
  color: var(--n-primary-color, #4080ff);
  font-weight: 500;
}
.filter-popover__option-content {
  display: flex;
  align-items: center;
  gap: 6px;
}
.filter-popover__color-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.filter-popover__count {
  margin-left: auto;
  font-size: 12px;
  color: var(--n-text-color-3, #888);
}
.filter-popover__search {
  margin: 4px 8px 8px;
}
.filter-popover__date-picker {
  margin: 8px;
}
.filter-popover__footer {
  display: flex;
  justify-content: space-between;
  padding: 8px 12px;
  border-top: 1px solid var(--n-border-color, #333);
  margin-top: 4px;
}
.filter-popover__footer-action {
  font-size: 12px;
  color: var(--n-text-color-3, #888);
  cursor: pointer;
}
.filter-popover__footer-action--primary {
  color: var(--n-primary-color, #4080ff);
}
.filter-slide-enter-active,
.filter-slide-leave-active {
  transition: opacity 0.15s ease;
}
.filter-slide-enter-from,
.filter-slide-leave-to {
  opacity: 0;
}
</style>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/filter/FilterPopover.vue
git commit -m "feat: add FilterPopover component with two-step category/options panels

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Frontend — Create SortPopover and ColumnsPopover Components

**Files:**
- Create: `frontend/src/components/filter/SortPopover.vue`
- Create: `frontend/src/components/filter/ColumnsPopover.vue`

- [ ] **Step 1: Implement SortPopover.vue**

Create `frontend/src/components/filter/SortPopover.vue`:

```vue
<template>
  <div class="sort-popover">
    <div class="sort-popover__header">{{ t('filter.ordering') }}</div>

    <div class="sort-popover__section">
      <div class="sort-popover__label">{{ t('filter.sortBy') }}</div>
      <n-select
        :value="sort.field"
        :options="fieldOptions"
        size="small"
        @update:value="(val: string) => emit('setSort', val, sort.order)"
      />
    </div>

    <div class="sort-popover__section">
      <div class="sort-popover__label">{{ t('filter.direction') }}</div>
      <n-button-group size="small" class="sort-popover__direction">
        <n-button
          :type="sort.order === 'asc' ? 'primary' : 'default'"
          :secondary="sort.order !== 'asc'"
          @click="emit('setSort', sort.field, 'asc')"
        >
          ↑ {{ t('filter.ascending') }}
        </n-button>
        <n-button
          :type="sort.order === 'desc' ? 'primary' : 'default'"
          :secondary="sort.order !== 'desc'"
          @click="emit('setSort', sort.field, 'desc')"
        >
          ↓ {{ t('filter.descending') }}
        </n-button>
      </n-button-group>
    </div>

    <div class="sort-popover__footer">
      <span class="sort-popover__reset" @click="emit('resetSort')">{{ t('filter.resetDefault') }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NSelect, NButtonGroup, NButton } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { SortField } from '../../composables/useFilterSort'

const props = defineProps<{
  fields: SortField[]
  sort: { field: string; order: 'asc' | 'desc' }
}>()

const emit = defineEmits<{
  (e: 'setSort', field: string, order: 'asc' | 'desc'): void
  (e: 'resetSort'): void
}>()

const { t } = useI18n()

const fieldOptions = computed(() =>
  props.fields.map((f) => ({ label: t(f.label), value: f.key }))
)
</script>

<style scoped>
.sort-popover {
  width: 220px;
}
.sort-popover__header {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--n-text-color-3, #888);
  padding: 8px 12px 4px;
}
.sort-popover__section {
  padding: 8px 12px;
}
.sort-popover__label {
  font-size: 11px;
  color: var(--n-text-color-3, #888);
  margin-bottom: 4px;
}
.sort-popover__direction {
  width: 100%;
  display: flex;
}
.sort-popover__direction .n-button {
  flex: 1;
}
.sort-popover__footer {
  padding: 8px 12px;
  border-top: 1px solid var(--n-border-color, #333);
}
.sort-popover__reset {
  font-size: 12px;
  color: var(--n-text-color-3, #888);
  cursor: pointer;
}
</style>
```

- [ ] **Step 2: Implement ColumnsPopover.vue**

Create `frontend/src/components/filter/ColumnsPopover.vue`:

```vue
<template>
  <div class="columns-popover">
    <div class="columns-popover__header">{{ t('filter.columns') }}</div>
    <div
      v-for="col in toggleableColumns"
      :key="col.key"
      class="columns-popover__row"
    >
      <span class="columns-popover__label">{{ t(col.label) }}</span>
      <n-switch
        :value="visibleColumns.includes(col.key)"
        size="small"
        @update:value="() => emit('toggleColumn', col.key)"
      />
    </div>
    <div class="columns-popover__footer">
      <span class="columns-popover__reset" @click="emit('resetColumns')">{{ t('filter.resetDefault') }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NSwitch } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { ColumnDef } from '../../composables/useFilterSort'

const props = defineProps<{
  columns: ColumnDef[]
  visibleColumns: string[]
}>()

const emit = defineEmits<{
  (e: 'toggleColumn', key: string): void
  (e: 'resetColumns'): void
}>()

const { t } = useI18n()

const toggleableColumns = computed(() =>
  props.columns.filter((c) => !c.alwaysVisible)
)
</script>

<style scoped>
.columns-popover {
  width: 220px;
}
.columns-popover__header {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--n-text-color-3, #888);
  padding: 8px 12px 4px;
}
.columns-popover__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--n-border-color, rgba(255,255,255,0.06));
}
.columns-popover__label {
  font-size: 13px;
}
.columns-popover__footer {
  padding: 8px 12px;
  border-top: 1px solid var(--n-border-color, #333);
}
.columns-popover__reset {
  font-size: 12px;
  color: var(--n-text-color-3, #888);
  cursor: pointer;
}
</style>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/filter/SortPopover.vue frontend/src/components/filter/ColumnsPopover.vue
git commit -m "feat: add SortPopover and ColumnsPopover components

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Frontend — Create FilterToolbar Container Component

**Files:**
- Create: `frontend/src/components/filter/FilterToolbar.vue`

- [ ] **Step 1: Implement FilterToolbar.vue**

Create `frontend/src/components/filter/FilterToolbar.vue`:

```vue
<template>
  <div class="filter-toolbar" data-testid="filter-toolbar">
    <!-- Toolbar row -->
    <div class="filter-toolbar__row">
      <!-- Search -->
      <n-input
        :value="searchValue"
        :placeholder="searchPlaceholder || t('filter.search')"
        size="small"
        clearable
        class="filter-toolbar__search"
        data-testid="filter-toolbar-search"
        @update:value="onSearchInput"
      >
        <template #prefix>
          <n-icon size="16"><SearchOutline /></n-icon>
        </template>
      </n-input>

      <!-- Filter button -->
      <n-popover trigger="click" placement="bottom-start" :show-arrow="false" raw>
        <template #trigger>
          <n-button size="small" :secondary="!hasActiveFilters" :type="hasActiveFilters ? 'primary' : 'default'" data-testid="filter-toolbar-filter-btn">
            <template #icon>
              <n-icon size="14"><FunnelOutline /></n-icon>
            </template>
            {{ t('filter.filter') }}
            <n-badge v-if="activeFilterCount > 0" :value="activeFilterCount" :max="9" class="filter-toolbar__badge" />
          </n-button>
        </template>
        <FilterPopover
          :fields="config.filterFields"
          :filters="filters"
          @add-filter="(key, val) => emit('addFilter', key, val)"
          @remove-filter="(key) => emit('removeFilter', key)"
        />
      </n-popover>

      <!-- Sort button -->
      <n-popover trigger="click" placement="bottom-start" :show-arrow="false" raw>
        <template #trigger>
          <n-button size="small" secondary data-testid="filter-toolbar-sort-btn">
            <template #icon>
              <n-icon size="14"><SwapVerticalOutline /></n-icon>
            </template>
            {{ t('filter.sort') }}
            <span class="filter-toolbar__sort-label">{{ currentSortLabel }}</span>
          </n-button>
        </template>
        <SortPopover
          :fields="config.sortFields"
          :sort="sort"
          @set-sort="(field, order) => emit('setSort', field, order)"
          @reset-sort="emit('resetSort')"
        />
      </n-popover>

      <!-- Columns button -->
      <n-popover trigger="click" placement="bottom-start" :show-arrow="false" raw>
        <template #trigger>
          <n-button size="small" secondary data-testid="filter-toolbar-columns-btn">
            <template #icon>
              <n-icon size="14"><SettingsOutline /></n-icon>
            </template>
            {{ t('filter.columns') }}
          </n-button>
        </template>
        <ColumnsPopover
          :columns="config.columns"
          :visible-columns="visibleColumns"
          @toggle-column="(key) => emit('toggleColumn', key)"
          @reset-columns="emit('resetColumns')"
        />
      </n-popover>

      <div class="filter-toolbar__spacer" />

      <!-- Result count -->
      <span v-if="resultCount !== undefined" class="filter-toolbar__count" data-testid="filter-toolbar-count">
        {{ t('filter.resultCount', { count: resultCount }) }}
      </span>
    </div>

    <!-- Active filter chips row -->
    <div v-if="hasActiveFilters" class="filter-toolbar__chips" data-testid="filter-toolbar-chips">
      <n-tag
        v-for="chip in filterChips"
        :key="chip.key"
        :type="chip.type || 'info'"
        size="small"
        round
        closable
        @close="emit('removeFilter', chip.key)"
      >
        {{ chip.label }}
      </n-tag>
      <span class="filter-toolbar__clear-all" @click="emit('clearAllFilters')">
        {{ t('filter.clearAll') }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { NInput, NButton, NIcon, NPopover, NBadge, NTag } from 'naive-ui'
import { SearchOutline, FunnelOutline, SwapVerticalOutline, SettingsOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import type { FilterSortConfig } from '../../composables/useFilterSort'
import FilterPopover from './FilterPopover.vue'
import SortPopover from './SortPopover.vue'
import ColumnsPopover from './ColumnsPopover.vue'

const props = defineProps<{
  config: FilterSortConfig
  filters: Record<string, any>
  sort: { field: string; order: 'asc' | 'desc' }
  visibleColumns: string[]
  activeFilterCount: number
  hasActiveFilters: boolean
  resultCount?: number
  searchPlaceholder?: string
}>()

const emit = defineEmits<{
  (e: 'addFilter', key: string, value: any): void
  (e: 'removeFilter', key: string): void
  (e: 'clearAllFilters'): void
  (e: 'setSort', field: string, order: 'asc' | 'desc'): void
  (e: 'resetSort'): void
  (e: 'toggleColumn', key: string): void
  (e: 'resetColumns'): void
  (e: 'search', term: string): void
}>()

const { t } = useI18n()
const searchValue = ref('')
let debounceTimer: ReturnType<typeof setTimeout> | null = null

function onSearchInput(val: string) {
  searchValue.value = val
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    emit('search', val)
  }, 300)
}

const currentSortLabel = computed(() => {
  const field = props.config.sortFields.find((f) => f.key === props.sort.field)
  const label = field ? t(field.label) : props.sort.field
  const arrow = props.sort.order === 'asc' ? '↑' : '↓'
  return `${label} ${arrow}`
})

const filterChips = computed(() => {
  const chips: { key: string; label: string; type?: 'info' | 'success' | 'warning' | 'error' }[] = []
  for (const field of props.config.filterFields) {
    const val = props.filters[field.key]
    if (val === undefined || val === null) continue
    if (Array.isArray(val) && val.length === 0) continue

    let displayValue: string
    if (field.type === 'multi-select' && Array.isArray(val)) {
      const opts = field.options?.() ?? []
      displayValue = val.map((v: any) => opts.find((o) => o.value === v)?.label ?? String(v)).join(', ')
    } else if (field.type === 'single-select') {
      const opts = field.options?.() ?? []
      displayValue = opts.find((o) => o.value === val)?.label ?? String(val)
    } else if (field.type === 'date-range' && Array.isArray(val)) {
      const fmt = (ts: number) => new Date(ts).toLocaleDateString()
      displayValue = `${fmt(val[0])} – ${fmt(val[1])}`
    } else {
      displayValue = String(val)
    }

    chips.push({ key: field.key, label: `${t(field.label)}: ${displayValue}` })
  }
  return chips
})
</script>

<style scoped>
.filter-toolbar {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.filter-toolbar__row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.filter-toolbar__search {
  width: 200px;
  flex-shrink: 0;
}
.filter-toolbar__sort-label {
  font-size: 11px;
  color: var(--n-text-color-3, #888);
  margin-left: 4px;
}
.filter-toolbar__badge {
  margin-left: 4px;
}
.filter-toolbar__spacer {
  flex: 1;
}
.filter-toolbar__count {
  font-size: 12px;
  color: var(--n-text-color-3, #888);
}
.filter-toolbar__chips {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.filter-toolbar__clear-all {
  font-size: 12px;
  color: var(--n-text-color-3, #888);
  cursor: pointer;
  margin-left: 4px;
}
.filter-toolbar__clear-all:hover {
  color: var(--n-text-color, #fff);
}
</style>
```

- [ ] **Step 2: Verify the build compiles**

Run: `cd frontend && npx vue-tsc --noEmit 2>&1 | tail -20`
Expected: No errors related to filter components

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/filter/FilterToolbar.vue
git commit -m "feat: add FilterToolbar container component with search, filter, sort, columns

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 7: Frontend — Add i18n Keys

**Files:**
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1: Add filter i18n keys to en.ts**

In `frontend/src/i18n/messages/en.ts`, add a `filter` section. Find an appropriate location (after the `common` section) and add:

```typescript
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
},
```

- [ ] **Step 2: Add filter i18n keys to zh-CN.ts**

In `frontend/src/i18n/messages/zh-CN.ts`, add:

```typescript
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
},
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: add filter/sort/columns i18n keys (en + zh-CN)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 8: Frontend — Update API Functions with New Params

**Files:**
- Modify: `frontend/src/api/index.ts:669-678,1054-1063`

- [ ] **Step 1: Update getIssues function**

In `frontend/src/api/index.ts`, find the `getIssues` function (around line 1054) and update the params type:

```typescript
export async function getIssues(params?: {
  status?: string
  project_id?: number
  initiator_user_id?: number
  search?: string
  created_after?: string
  created_before?: string
  sort_by?: string
  sort_order?: string
  page?: number
  page_size?: number
}): Promise<IssueListResponse> {
  const response = await api.get('/issues', { params })
  return response.data
}
```

- [ ] **Step 2: Update getTasksPaginated function**

In `frontend/src/api/index.ts`, find `getTasksPaginated` (around line 669) and update:

```typescript
export async function getTasksPaginated(params: {
  page: number
  page_size?: number
  status?: string
  project_id?: number
  initiator_username?: string
  priority?: string
  search?: string
  created_after?: string
  created_before?: string
  sort_by?: string
  sort_order?: string
}): Promise<PaginatedResponse<Task>> {
  const response = await api.get('/tasks', { params })
  return response.data
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/index.ts
git commit -m "feat: add new filter/sort query params to API functions

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 9: Frontend — Integrate FilterToolbar into IssueList

**Files:**
- Modify: `frontend/src/views/IssueList.vue`

- [ ] **Step 1: Replace filter UI in template**

Replace the `PageHeader` section (lines 5-37) and insert FilterToolbar. The new template structure:

```vue
<PageHeader
  data-testid="issue-list-header"
  root-class="issue-list__hero"
  actions-class="issue-list__actions"
  :title="t('issue.list')"
  :subtitle="t('issue.subtitle')"
>
  <template #actions>
    <n-button
      type="primary"
      data-testid="issue-list-create-button"
      @click="router.push('/issues/create')"
    >
      {{ t('issue.create') }}
    </n-button>
  </template>
</PageHeader>

<FilterToolbar
  :config="filterConfig"
  :filters="filterState.filters.value"
  :sort="filterState.sort.value"
  :visible-columns="filterState.visibleColumns.value"
  :active-filter-count="filterState.activeFilterCount.value"
  :has-active-filters="filterState.hasActiveFilters.value"
  :result-count="totalIssues"
  :search-placeholder="t('filter.search')"
  @add-filter="filterState.addFilter"
  @remove-filter="filterState.removeFilter"
  @clear-all-filters="filterState.clearAllFilters"
  @set-sort="filterState.setSort"
  @reset-sort="filterState.resetSort"
  @toggle-column="filterState.toggleColumn"
  @reset-columns="filterState.resetColumns"
  @search="onSearch"
/>
```

- [ ] **Step 2: Update script setup**

Replace the filter state refs and watch with useFilterSort. Add imports and config:

```typescript
import FilterToolbar from '../components/filter/FilterToolbar.vue'
import { useFilterSort, type FilterSortConfig } from '../composables/useFilterSort'
import { EllipseOutline, FolderOpenOutline, CalendarOutline } from '@vicons/ionicons5'

// Remove: statusFilter, projectFilter refs
// Remove: watch([statusFilter, projectFilter], ...)

const filterConfig: FilterSortConfig = {
  storageKey: 'codify:filters:issues',
  filterFields: [
    {
      key: 'status',
      label: 'filter.status',
      icon: EllipseOutline,
      type: 'multi-select',
      options: () => [
        { label: t('issue.status.open'), value: 'open', color: '#18a058' },
        { label: t('issue.status.in_progress'), value: 'in_progress', color: '#4080ff' },
        { label: t('issue.status.in_review'), value: 'in_review', color: '#f0a020' },
        { label: t('issue.status.closed'), value: 'closed', color: '#888' },
      ],
    },
    {
      key: 'project_id',
      label: 'filter.project',
      icon: FolderOpenOutline,
      type: 'single-select',
      options: () => projects.value.map((p) => ({ label: p.name, value: p.id })),
    },
    {
      key: 'created',
      label: 'filter.created',
      icon: CalendarOutline,
      type: 'date-range',
      apiParam: 'created_after,created_before',
    },
  ],
  sortFields: [
    { key: 'created_at', label: 'filter.sortCreated' },
    { key: 'status', label: 'filter.sortStatus' },
  ],
  columns: [
    { key: 'id', label: 'ID', defaultVisible: true, alwaysVisible: true },
    { key: 'title', label: 'issue.field.title', defaultVisible: true, alwaysVisible: true },
    { key: 'project_id', label: 'issue.field.project', defaultVisible: true },
    { key: 'status', label: 'common.status', defaultVisible: true },
    { key: 'task_count', label: 'issue.taskCount', defaultVisible: true },
    { key: 'total_changes', label: 'common.changes', defaultVisible: true },
    { key: 'total_tokens', label: 'analytics.tokens', defaultVisible: true },
    { key: 'initiator_username', label: 'issue.field.creator', defaultVisible: false },
    { key: 'created_at', label: 'issue.field.createdAt', defaultVisible: true },
  ],
  defaultSort: { field: 'created_at', order: 'desc' },
}

const filterState = useFilterSort(filterConfig)
const searchTerm = ref('')

function onSearch(term: string) {
  searchTerm.value = term
  currentPage.value = 1
  fetchIssues()
}

// Watch filter/sort changes
watch([() => filterState.filters.value, () => filterState.sort.value], () => {
  currentPage.value = 1
  fetchIssues()
}, { deep: true })
```

- [ ] **Step 3: Update fetchIssues to use apiParams**

Replace the `fetchIssues` function:

```typescript
async function fetchIssues() {
  if (loading.value) return
  loading.value = true
  try {
    const params: Record<string, any> = {
      page: currentPage.value,
      page_size: pageSize.value,
      ...filterState.apiParams.value,
    }
    if (searchTerm.value && searchTerm.value.length >= 2) {
      params.search = searchTerm.value
    }
    const result = await getIssues(params)
    issues.value = result.items
    totalIssues.value = result.total
  } catch {
    message.error('Failed to fetch issues')
  } finally {
    hasLoadedOnce.value = true
    loading.value = false
  }
}
```

- [ ] **Step 4: Filter columns based on visibleColumns**

Update the `columns` computed to filter based on `filterState.visibleColumns`:

```typescript
const allColumns = computed<DataTableColumns<Issue>>(() => [
  // ... existing column definitions unchanged
])

const columns = computed(() =>
  allColumns.value.filter((col) => {
    const key = (col as any).key
    if (!key) return true
    return filterState.visibleColumns.value.includes(key)
  })
)
```

- [ ] **Step 5: Remove old NSelect imports**

Remove `NSelect` from the naive-ui import. Remove old `statusFilter`, `projectFilter` refs. Remove old `statusOptions`, `projectOptions` computeds if they exist.

- [ ] **Step 6: Build and verify**

Run: `cd frontend && npm run build 2>&1 | tail -20`
Expected: Build succeeds

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/IssueList.vue
git commit -m "feat: integrate FilterToolbar into IssueList page

- Replace NSelect filters with FilterToolbar
- Use useFilterSort composable for state management
- Column visibility controlled by Columns popover
- Search, date range, multi-status filtering

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 10: Frontend — Integrate FilterToolbar into TaskList

**Files:**
- Modify: `frontend/src/views/TaskList.vue`

- [ ] **Step 1: Replace filter UI in template**

Same pattern as IssueList: replace the three NSelects in PageHeader#actions with just the refresh button, add FilterToolbar below PageHeader.

- [ ] **Step 2: Update script setup**

```typescript
import FilterToolbar from '../components/filter/FilterToolbar.vue'
import { useFilterSort, type FilterSortConfig } from '../composables/useFilterSort'
import { EllipseOutline, FolderOpenOutline, FlagOutline, PersonOutline, DocumentTextOutline, CalendarOutline } from '@vicons/ionicons5'

// Remove: statusFilter, projectFilter, initiatorFilter refs
// Remove: watch([statusFilter, projectFilter, initiatorFilter], ...)

const filterConfig: FilterSortConfig = {
  storageKey: 'codify:filters:tasks',
  filterFields: [
    {
      key: 'status',
      label: 'filter.status',
      icon: EllipseOutline,
      type: 'multi-select',
      options: () => [
        { label: t('status.pending'), value: 'pending', color: '#888' },
        { label: t('status.queued'), value: 'queued', color: '#4080ff' },
        { label: t('status.running'), value: 'running', color: '#f0a020' },
        { label: t('status.completed'), value: 'completed', color: '#18a058' },
        { label: t('status.failed'), value: 'failed', color: '#d03050' },
        { label: t('status.cancelled'), value: 'cancelled', color: '#888' },
      ],
    },
    {
      key: 'project_id',
      label: 'filter.project',
      icon: FolderOpenOutline,
      type: 'single-select',
      options: () => projects.value.map((p) => ({ label: p.name, value: p.id })),
    },
    {
      key: 'priority',
      label: 'filter.priority',
      icon: FlagOutline,
      type: 'multi-select',
      options: () => [
        { label: 'P0', value: '0', color: '#d03050' },
        { label: 'P1', value: '1', color: '#f0a020' },
        { label: 'P2', value: '2', color: '#18a058' },
      ],
    },
    {
      key: 'initiator_username',
      label: 'filter.initiator',
      icon: PersonOutline,
      type: 'single-select',
      options: () => initiatorOptions.value.map((o: any) => ({ label: o.label, value: o.value })),
    },
    {
      key: 'created',
      label: 'filter.created',
      icon: CalendarOutline,
      type: 'date-range',
      apiParam: 'created_after,created_before',
    },
  ],
  sortFields: [
    { key: 'created_at', label: 'filter.sortCreated' },
    { key: 'priority', label: 'filter.sortPriority' },
    { key: 'status', label: 'filter.sortStatus' },
  ],
  columns: [
    { key: 'id', label: 'ID', defaultVisible: true, alwaysVisible: true },
    { key: 'user_prompt', label: 'task.prompt', defaultVisible: true, alwaysVisible: true },
    { key: 'project', label: 'filter.project', defaultVisible: true },
    { key: 'initiator', label: 'filter.initiator', defaultVisible: true },
    { key: 'issue', label: 'filter.issue', defaultVisible: false },
    { key: 'status', label: 'filter.status', defaultVisible: true },
    { key: 'priority', label: 'filter.priority', defaultVisible: true },
    { key: 'branch', label: 'task.branch', defaultVisible: false },
    { key: 'merge_request', label: 'task.mergeRequest', defaultVisible: false },
    { key: 'total_changes', label: 'common.changes', defaultVisible: true },
    { key: 'created_at', label: 'filter.created', defaultVisible: true },
    { key: 'scheduled_at', label: 'task.scheduled', defaultVisible: false },
  ],
  defaultSort: { field: 'created_at', order: 'desc' },
}

const filterState = useFilterSort(filterConfig)
const searchTerm = ref('')

function onSearch(term: string) {
  searchTerm.value = term
  currentPage.value = 1
  fetchTasks()
}

watch([() => filterState.filters.value, () => filterState.sort.value], () => {
  currentPage.value = 1
  fetchTasks()
}, { deep: true })
```

- [ ] **Step 3: Update fetchTasks to use apiParams**

```typescript
async function fetchTasks() {
  if (loading.value) return
  loading.value = true
  try {
    const params: Record<string, any> = {
      page: currentPage.value,
      page_size: pageSize.value,
      ...filterState.apiParams.value,
    }
    if (searchTerm.value && searchTerm.value.length >= 2) {
      params.search = searchTerm.value
    }
    const result = await getTasksPaginated(params)
    tasks.value = result.items
    totalTasks.value = result.total
  } catch (error) {
    message.error(t('dashboard.failedToFetchTasks'))
  } finally {
    hasLoadedOnce.value = true
    loading.value = false
  }
}
```

- [ ] **Step 4: Filter columns based on visibleColumns**

Same pattern as IssueList — split columns into `allColumns` and `columns` computed that filters by visibility.

- [ ] **Step 5: Build and verify**

Run: `cd frontend && npm run build 2>&1 | tail -20`
Expected: Build succeeds

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/TaskList.vue
git commit -m "feat: integrate FilterToolbar into TaskList page

- Replace NSelect filters with FilterToolbar
- Add priority filter, date range, search
- Column visibility controlled by Columns popover
- Sort by created_at, priority, status

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 11: Full Build + Backend Tests + Deploy

**Files:** None (verification only)

- [ ] **Step 1: Run all backend unit tests**

Run: `cd backend && python -m pytest tests/unit/ -v --no-header 2>&1 | tail -30`
Expected: All tests PASS

- [ ] **Step 2: Run frontend build**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: Build succeeds

- [ ] **Step 3: Run frontend unit tests**

Run: `cd frontend && npx vitest run --no-color 2>&1 | tail -30`
Expected: All tests PASS (some existing IssueList/TaskList tests may need minor updates if they exist)

- [ ] **Step 4: Build and deploy**

```bash
docker build -f deploy/Dockerfile.backend -t deploy-backend .
docker build -f deploy/Dockerfile.frontend -t codify-nginx:latest .
cd deploy && docker-compose up -d --force-recreate backend scheduler nginx
```

- [ ] **Step 5: Push to origin**

```bash
git push origin HEAD
```

---

## Dependency Graph

```
Task 1 (backend issues API) ─────────────────────────────────────┐
Task 2 (backend tasks API) ──────────────────────────────────────┤
Task 3 (useFilterSort composable) ──┐                            │
Task 4 (FilterPopover) ─────────────┤                            │
Task 5 (Sort + Columns popovers) ───┤                            │
Task 6 (FilterToolbar container) ───┤← depends on 3,4,5          │
Task 7 (i18n keys) ─────────────────┤                            │
Task 8 (API function params) ───────┤                            │
Task 9 (IssueList integration) ─────┤← depends on 1,6,7,8       │
Task 10 (TaskList integration) ─────┤← depends on 2,6,7,8       │
Task 11 (Verify + Deploy) ──────────┘← depends on all           │
```

**Parallelizable groups:**
- Group A: Tasks 1, 2 (backend — independent)
- Group B: Tasks 3, 4, 5, 7 (frontend components — independent)
- Group C: Tasks 6, 8 (depend on Group B)
- Group D: Tasks 9, 10 (depend on A + C)
- Group E: Task 11 (depends on D)
