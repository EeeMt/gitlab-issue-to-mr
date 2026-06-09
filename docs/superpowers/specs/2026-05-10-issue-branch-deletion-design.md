# Issue Branch Deletion on Close — Design

**Date:** 2026-05-10  
**Status:** Approved  

## Problem

Every issue in Codify creates a dedicated branch (`codify/issue-{id}`). When an issue is closed
(manually or via MR merge webhook), the branch is often no longer needed. Currently there is no
automated way to clean it up, leaving stale branches in the GitLab repository.

## Goals

1. Allow users to opt-in (default: opt-in) to auto-delete the issue branch when the issue is closed.
2. Automatically attempt branch deletion on both close paths: manual and webhook-triggered.
3. Provide a manual "Delete Branch" button on closed issues, disabled once the branch is gone.
4. Track deletion state in the database so the UI accurately reflects the current status.

## Non-Goals

- Deleting branches for issues still in OPEN / IN_PROGRESS / IN_REVIEW state.
- Asynchronous/background deletion (synchronous is sufficient and simpler).
- Blocking issue close if branch deletion fails.

---

## Data Model

### New columns on `issues` table

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `delete_branch_on_close` | Boolean | `True` | Whether to auto-delete the branch on issue close |
| `branch_deleted` | Boolean | `False` | Whether the branch has been successfully deleted |

### Alembic migration

New file: `backend/alembic/versions/034_add_branch_deletion_fields.py`

Both columns are nullable=False with `server_default`. Existing rows will inherit the defaults.

### Serialization

`_serialize_issue()` and `_serialize_issue_detail()` in `issues.py` expose both new fields.

---

## Backend

### GitLab Client

New method: `GitLabClient.delete_branch(project_id: int, branch_name: str) -> bool`

- Calls `DELETE /projects/:id/repository/branches/:branch_name`
- Returns `True` if deleted or branch not found (404 → treat as already deleted)
- Returns `False` on any other error (logs a warning)

### Shared Helper

```python
async def _try_delete_issue_branch(issue: Issue, db: AsyncSession) -> None:
    """Attempt to delete the issue's branch. Silently handles failures."""
```

Logic:
1. Skip if `issue.branch_name` is None or `issue.delete_branch_on_close` is False
2. Call `get_gitlab_client().delete_branch(issue.project_id, issue.branch_name)`
3. On success (`True`): set `issue.branch_deleted = True`
4. On failure (`False`): log a warning, leave `branch_deleted = False`
5. Caller is responsible for `db.commit()` after this helper

### Close Paths

**Manual close** (`POST /issues/{issue_id}/close`):
1. Set `issue.status = CLOSED`, `issue.closed_via = "manual"`
2. Call `await _try_delete_issue_branch(issue, db)`
3. `await db.commit()`

**Webhook auto-close** (`webhook_handler.py`, MR merged path):
1. Set `issue.status = CLOSED`, `issue.closed_via = "webhook_mr_merged"`
2. Call `await _try_delete_issue_branch(issue, db)`
3. `await db.commit()` (already present at end of handler, no extra commit needed)

Note: If GitLab already deleted the source branch on merge, `delete_branch()` will receive a 404
and return `True`, so `branch_deleted` will be set correctly.

### New API Endpoint

`POST /api/issues/{issue_id}/delete-branch`

- Authentication: same as `close_issue` (`require_authenticated_user`, `_require_issue_operator`)
- Pre-conditions:
  - Issue must exist (404 if not)
  - Issue must be CLOSED (400 if not)
  - `branch_name` must be set (400 if not)
- Action: call `delete_branch()`, update `branch_deleted`, commit
- Response: updated issue detail (same shape as `close_issue`)

---

## Frontend

### Create Issue Form (`CreateIssue.vue`)

- New Toggle/Switch field: "关闭时自动删除分支 / Auto-delete branch on close"
- Default: `true`
- Bound to `delete_branch_on_close` in the create request body
- i18n keys added to `en.ts` and `zh-CN.ts`

### Issue Detail Page (`IssueView.vue`)

**Branch info section — new badges:**

| Condition | Badge |
|-----------|-------|
| `delete_branch_on_close = true` | 🔵 "关闭时删除分支 / Delete on close" (blue/info) |
| `delete_branch_on_close = false` | ⚪ "保留分支 / Keep branch" (default/gray) |
| `branch_deleted = true` | 🟠 "分支已删除 / Branch deleted" (warning/orange) |

**"Delete Branch" button:**

- Shown only when `issue.status === 'closed'` AND `issue.branch_name` is set
- `branch_deleted = false`: button enabled; click → confirm dialog → `POST .../delete-branch` → refresh
- `branch_deleted = true`: button disabled (grayed); tooltip: "分支已删除 / Branch already deleted"
- Hidden entirely when issue is not closed

### API layer (`src/api/index.ts`)

New function: `deleteIssueBranch(issueId: number): Promise<IssueDetail>`

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Branch not found (404) during auto-close | `branch_deleted = true`, no error |
| GitLab API error during auto-close | Log warning, `branch_deleted = false`, issue still closed |
| Manual delete endpoint called on open issue | 400 Bad Request |
| Manual delete endpoint: GitLab returns error | 500 with error message propagated to UI |
| `branch_name` is null | Skip deletion silently |

---

## Files Changed

### Backend
- `backend/app/models.py` — two new columns on `Issue`
- `backend/alembic/versions/034_add_branch_deletion_fields.py` — migration
- `backend/app/api/issues.py` — `_try_delete_issue_branch`, updated `close_issue`, new `delete_branch_on_close` param in create, new endpoint
- `backend/app/api/webhook_handler.py` — call `_try_delete_issue_branch` after issue close
- `backend/app/core/gitlab_client.py` — new `delete_branch()` method

### Frontend
- `frontend/src/views/CreateIssue.vue` — toggle field
- `frontend/src/views/IssueView.vue` — badges + delete button
- `frontend/src/api/index.ts` — `deleteIssueBranch()`
- `frontend/src/i18n/messages/en.ts` — new keys
- `frontend/src/i18n/messages/zh-CN.ts` — new keys

---

## Testing

- **Unit**: `test_issues.py` — close_issue with deletion success/failure/not-found; new endpoint happy path and error cases
- **Unit**: `test_gitlab_client.py` — `delete_branch` with 200, 404, 500 responses
- **Unit**: `test_webhook_handler.py` — MR merge auto-close triggers branch deletion
- **Frontend**: `IssueView.spec.ts` — badge rendering, button enabled/disabled states; `CreateIssue.spec.ts` — toggle default and submission
