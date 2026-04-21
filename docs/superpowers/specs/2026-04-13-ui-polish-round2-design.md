# UI Polish Round 2 — Design Spec

**Date:** 2026-04-13
**Status:** Approved
**Scope:** 12 UI/UX improvements + 1 backend endpoint + housekeeping

---

## Requirements Summary

| # | Requirement | Scope |
|---|------------|-------|
| 1 | Dashboard summary cards — Grafana-style stat panels, 5 metrics | Frontend |
| 2 | Dashboard — title column truncation with tooltip | Frontend |
| 3 | IssueList — row-click navigation (any position) | Frontend |
| 4 | IssueView — side-by-side Detail + Description layout | Frontend |
| 5 | Failed task retry — hide retry when retried, show link to new task | Frontend |
| 6 | TaskView — retry source link navigation bug (same-route) | Frontend |
| 7 | CreateIssue — auto-fill target branch from project default | Frontend |
| 8 | IssueView — show "No MR" explicitly instead of "-" | Frontend |
| 9 | Dashboard — GitHub-style 365-day activity heatmap | Frontend + Backend |
| 10 | IssueView — create task as modal instead of inline | Frontend |
| 11 | *(merged into #5)* | — |
| 12 | Code review from commit d8100d6 | Review |
| 13 | Update progress document | Docs |

---

## Section A: Dashboard Overhaul (#1, #2, #9)

### A1: Summary Cards Restyle (#1)

**Current:** `SummaryCard.vue` — gradient background cards with label + large number + optional note.

**New design:** Compact Grafana-style stat panels with colored left border + icon.

**5 metrics:**
1. **Issues** — total issue count, blue icon (FolderOpenOutline)
2. **Open Issues** — open status count, green icon (AlertCircleOutline)
3. **Tasks** — total task count, purple icon (CodeOutline)
4. **Running** — running task count, orange icon (PlayOutline)
5. **Success Rate** — `completed / (completed + failed) * 100`%, teal icon (CheckmarkCircleOutline)

**Implementation:**
- Create new `StatCard.vue` component with props: `label, value, icon, color, suffix?`
- Template: left colored border (4px), icon (24px, colored), value (24px bold), label (12px muted), optional suffix (e.g. "%")
- Replace SummaryCard usage in Dashboard.vue with StatCard
- SummaryCard.vue remains for Analytics.vue (no changes there)

**Data source:** Existing `getStats()` already returns `total, running, completed, failed, issues.total, issues.by_status.open`.

### A2: Title Column Truncation (#2)

Add `ellipsis: { tooltip: true }` to:
- Recent Issues table "Title" column
- Running Tasks table "Description" column

No other changes needed — NDataTable handles tooltip rendering automatically.

### A3: Activity Heatmap (#9)

**Replaces:** Recent Activity section in Dashboard.

**New component:** `ActivityHeatmap.vue`
- GitHub-style 365-day contribution grid
- 7 rows (Mon–Sun) × 52 columns (weeks)
- Cell color: green intensity based on task completion count per day
- Tooltip on hover: "N tasks on YYYY-MM-DD"
- Legend: 0 (gray) → 1-2 (light green) → 3-5 (medium) → 6+ (dark green)

**New backend endpoint:** `GET /api/stats/activity-heatmap`
- Query param: `days=365` (optional, default 365)
- Returns: `[{"date": "2026-01-15", "count": 3}, ...]`
- Query: count tasks with `status=completed` grouped by `DATE(completed_at)` for last N days
- Only include days with count > 0 (frontend fills zeros)

**Dashboard integration:**
- Replace Recent Activity NCard with ActivityHeatmap component
- Card title: "Activity" / "活动"
- Fetch data via new `getActivityHeatmap()` API function

---

## Section B: IssueView Improvements (#4, #5, #8, #10)

### B1: Side-by-Side Layout (#4)

**Current:** Detail card and Description card stacked vertically.

**New:** Use `NGrid` with `cols="1 m:2"` to place Detail and Description side by side on medium+ screens, stack on mobile.

### B2: Retry Logic Rework (#5 — merged with #11)

**Retry eligibility:** A task can be retried if:
1. `status == FAILED` (or CANCELLED)
2. No task exists with `retry_source_task_id == this_task.id` (any status)

**Frontend implementation (IssueView task table):**
- Compute `retriedTaskMap`: Map<taskId, retryTask> from the issue's task list
- For each task row:
  - If task has a retry → hide retry button, show "Retried → Task #X" as RouterLink
  - If task is failed/cancelled and no retry → show retry button
  - Otherwise → no action column content

**No backend changes needed.** Existing 409 guard stays as safety net.

### B3: Explicit "No MR" Display (#8)

**Current:** MR field shows `"-"` when no MR exists.

**New:** Show styled text "No MR" / "无合并请求" with muted color (var(--text-color-3)).

### B4: Create Task as Modal (#10)

**Current:** Inline section within Tasks card, toggled by button.

**New:** `NModal` dialog triggered by "Create Task" button in Tasks card header.
- Modal title: "Create Task" / "创建任务"
- Same form content (prompt editor, priority, schedule)
- Template picker stays as NDrawer (opened from within modal)
- On success: close modal, refresh task list

---

## Section C: Other Pages (#3, #6, #7)

### C0: IssueList Row-Click Navigation (#3)

**Current:** Only the Title column NButton is clickable. Clicking elsewhere on the row does nothing.

**Fix:** Add `row-props` to `n-data-table`:
```typescript
function issueRowProps(row: Issue) {
  return { style: 'cursor: pointer', onClick: () => router.push(`/issues/${row.id}`) }
}
```
Add `:row-props="issueRowProps"` to the data-table element.

### C1: TaskView Navigation Bug (#6)

**Problem:** Clicking retry source link (`/tasks/X`) on TaskView doesn't refresh because Vue Router doesn't re-render for same-route param changes.

**Fix:** Add watcher on `route.params.id`:
```typescript
watch(() => route.params.id, (newId) => {
  if (newId) fetchTask()
})
```

### C2: CreateIssue Auto-Fill Target Branch (#7)

**Current:** When MR toggle enabled, target_branch select is empty.

**New:** When MR toggle switched ON and project is selected, auto-fill `target_branch` with project's `default_branch` from the projects API response.

**Implementation:**
- Store `projectDefaultBranch` when project is selected
- In MR toggle handler: if enabling, set `formValue.target_branch = projectDefaultBranch`

---

## Section D: Housekeeping (#12, #13)

### D1: Code Review (#12)
Dispatch code-reviewer agent on changes since commit d8100d6.

### D2: Update Progress Document (#13)
Update `docs/superpowers/plans/2026-04-12-issue-task-mr-refactoring.md` — mark all 18 tasks as complete.

---

## i18n Keys Required

### English (en.ts)
```
dashboard.issues: 'Issues'
dashboard.openIssues: 'Open Issues'
dashboard.tasks: 'Tasks'
dashboard.successRate: 'Success Rate'
dashboard.activity: 'Activity'
dashboard.noActivity: 'No activity yet'
issue.noMergeRequest: 'No MR'
issue.retriedAs: 'Retried as'
issue.createTaskModal: 'Create Task'
```

### Chinese (zh-CN.ts)
```
dashboard.issues: '需求总数'
dashboard.openIssues: '进行中需求'
dashboard.tasks: '任务总数'
dashboard.successRate: '成功率'
dashboard.activity: '活动'
dashboard.noActivity: '暂无活动'
issue.noMergeRequest: '无合并请求'
issue.retriedAs: '已重试为'
issue.createTaskModal: '创建任务'
```

---

## File Change Matrix

| File | Changes |
|------|---------|
| `frontend/src/components/StatCard.vue` | **NEW** — Grafana-style stat card |
| `frontend/src/components/ActivityHeatmap.vue` | **NEW** — 365-day heatmap |
| `frontend/src/views/Dashboard.vue` | Summary cards → StatCard, truncation, heatmap |
| `frontend/src/views/IssueList.vue` | Add row-props for row-click navigation |
| `frontend/src/views/IssueView.vue` | Side-by-side, retry rework, "No MR", modal |
| `frontend/src/views/TaskView.vue` | Watch route params fix |
| `frontend/src/views/CreateIssue.vue` | Auto-fill target branch |
| `frontend/src/api/index.ts` | Add `getActivityHeatmap()` |
| `frontend/src/i18n/messages/en.ts` | New keys |
| `frontend/src/i18n/messages/zh-CN.ts` | New keys |
| `backend/app/api/stats.py` | New `/stats/activity-heatmap` endpoint |
| `docs/superpowers/plans/2026-04-12-issue-task-mr-refactoring.md` | Update progress |

---

## Dependencies

- StatCard.vue and ActivityHeatmap.vue are new standalone components — no dependencies
- Backend heatmap endpoint is independent
- IssueView changes (#4, #5, #8, #10) all touch same file — must be sequential
- Dashboard changes (#1, #2, #9) all touch same file — must be sequential
- TaskView (#6), CreateIssue (#7) are independent
