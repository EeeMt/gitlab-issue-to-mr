# Issue Branch Deletion on Close — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When an issue is closed (manually or via webhook), automatically delete its GitLab branch, with user control over the behaviour and a manual delete button on the closed issue page.

**Architecture:** Add two boolean columns to the `issues` table (`delete_branch_on_close`, `branch_deleted`), a `delete_branch()` method to `GitLabClient`, a shared async helper `_try_delete_issue_branch()` called from both the manual-close endpoint and the webhook handler, and a new `POST /issues/{id}/delete-branch` endpoint. The frontend gains a toggle in the create form and badges + a button in the issue detail view.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, Alembic, python-gitlab, Vue 3, Naive UI, vue-i18n, TypeScript.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `backend/alembic/versions/038_add_branch_deletion_fields.py` | Create | DB migration — two new columns |
| `backend/app/models.py` | Modify | Add `delete_branch_on_close`, `branch_deleted` to `Issue` |
| `backend/app/core/gitlab_client.py` | Modify | Add `delete_branch(project_id, branch_name) -> bool` |
| `backend/app/api/issues.py` | Modify | `CreateIssueRequest`, `_serialize_issue`, `_try_delete_issue_branch`, `close_issue`, new `delete_issue_branch` endpoint |
| `backend/app/api/webhook_handler.py` | Modify | Call `_try_delete_issue_branch` in MR-merged loop |
| `backend/tests/unit/test_issues_api.py` | Modify | New tests for close (with branch deletion) + new endpoint |
| `backend/tests/unit/test_webhook_handler.py` | Modify | Test that branch deletion is triggered on auto-close |
| `frontend/src/api/index.ts` | Modify | Extend `Issue`, `CreateIssueRequest`; add `deleteIssueBranch()` |
| `frontend/src/i18n/messages/en.ts` | Modify | New i18n keys |
| `frontend/src/i18n/messages/zh-CN.ts` | Modify | New i18n keys (Chinese) |
| `frontend/src/views/CreateIssue.vue` | Modify | Toggle field for `delete_branch_on_close` |
| `frontend/src/views/IssueView.vue` | Modify | Branch-deletion badges + delete-branch button |

---

## Task 1: Alembic Migration

**Files:**
- Create: `backend/alembic/versions/038_add_branch_deletion_fields.py`

- [ ] **Step 1: Create migration file**

```python
# backend/alembic/versions/038_add_branch_deletion_fields.py
"""Add delete_branch_on_close and branch_deleted to issues

Revision ID: 038_add_branch_deletion_fields
Revises: 037_task_commit_message
Create Date: 2026-05-10 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "038_add_branch_deletion_fields"
down_revision = "037_task_commit_message"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "issues",
        sa.Column(
            "delete_branch_on_close",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "issues",
        sa.Column(
            "branch_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("issues", "branch_deleted")
    op.drop_column("issues", "delete_branch_on_close")
```

- [ ] **Step 2: Verify migration parses cleanly**

```bash
cd backend && python -c "import alembic.versions.versions; print('ok')" 2>/dev/null; python -c "
import sys; sys.path.insert(0,'.')
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
  'mig', 'alembic/versions/038_add_branch_deletion_fields.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print('revision:', m.revision)
print('down_revision:', m.down_revision)
"
```
Expected: `revision: 038_add_branch_deletion_fields` and `down_revision: 037_task_commit_message`

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/038_add_branch_deletion_fields.py
git commit -m "feat: add branch deletion migration 038

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: Update Issue Model

**Files:**
- Modify: `backend/app/models.py`

- [ ] **Step 1: Add two columns to the `Issue` class**

In `backend/app/models.py`, find the block with `target_branch` (around line 74). Add the two new mapped columns immediately after `target_branch`:

```python
    # Branch deletion policy
    delete_branch_on_close: Mapped[bool] = mapped_column(
        sa.Boolean, default=True, server_default=sa.text("true"), nullable=False
    )
    branch_deleted: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.text("false"), nullable=False
    )
```

`sa` is available via `import sqlalchemy as sa` — check the existing imports at the top of `models.py`. If only `from sqlalchemy import ...` style is used, add `Boolean` and `text` to that import instead:

```python
# If models.py uses: from sqlalchemy import Integer, String, Text, ...
# Add Boolean and text to that import line.
# Then write:
    delete_branch_on_close: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    branch_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
```

> **Check first:** Open `backend/app/models.py` and see whether `Boolean` and `text` are already imported. Add them if missing.

- [ ] **Step 2: Verify model imports cleanly**

```bash
cd backend && python -c "from app.models import Issue; i = Issue(); print(i.delete_branch_on_close, i.branch_deleted)"
```
Expected: `True False`

- [ ] **Step 3: Commit**

```bash
git add backend/app/models.py
git commit -m "feat: add delete_branch_on_close and branch_deleted to Issue model

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: GitLab Client — `delete_branch` Method

**Files:**
- Modify: `backend/app/core/gitlab_client.py`

- [ ] **Step 1: Write the failing test**

Add this test class to `backend/tests/unit/test_gitlab_client_coverage.py` (or create `backend/tests/unit/test_gitlab_client_delete_branch.py` if that file is large):

```python
# backend/tests/unit/test_gitlab_client_delete_branch.py
import unittest
from unittest.mock import MagicMock, patch
from gitlab.exceptions import GitlabGetError


class DeleteBranchTests(unittest.TestCase):
    def _get_client(self):
        from app.core.gitlab_client import GitLabClient
        client = GitLabClient.__new__(GitLabClient)
        client.gl = MagicMock()
        client._url = "https://gitlab.example.com"
        return client

    def test_delete_branch_success(self):
        """Returns True when branch exists and is deleted."""
        client = self._get_client()
        mock_project = MagicMock()
        mock_branch = MagicMock()
        mock_project.branches.get.return_value = mock_branch
        with patch.object(client, "get_project", return_value=mock_project):
            result = client.delete_branch(42, "codify/issue-1")
        self.assertTrue(result)
        mock_branch.delete.assert_called_once()

    def test_delete_branch_not_found_returns_true(self):
        """Returns True (treat as already deleted) when branch not found (404)."""
        client = self._get_client()
        mock_project = MagicMock()
        err = GitlabGetError("Not Found", 404)
        mock_project.branches.get.side_effect = err
        with patch.object(client, "get_project", return_value=mock_project):
            result = client.delete_branch(42, "codify/issue-1")
        self.assertTrue(result)

    def test_delete_branch_other_error_returns_false(self):
        """Returns False when GitLab returns a non-404 error."""
        client = self._get_client()
        mock_project = MagicMock()
        err = GitlabGetError("Internal Server Error", 500)
        mock_project.branches.get.side_effect = err
        with patch.object(client, "get_project", return_value=mock_project):
            result = client.delete_branch(42, "codify/issue-1")
        self.assertFalse(result)

    def test_delete_branch_unexpected_exception_returns_false(self):
        """Returns False on unexpected exceptions."""
        client = self._get_client()
        mock_project = MagicMock()
        mock_project.branches.get.side_effect = RuntimeError("timeout")
        with patch.object(client, "get_project", return_value=mock_project):
            result = client.delete_branch(42, "codify/issue-1")
        self.assertFalse(result)
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd backend && python -m pytest tests/unit/test_gitlab_client_delete_branch.py -v
```
Expected: 4 tests collected, all FAIL with `AttributeError: 'GitLabClient' object has no attribute 'delete_branch'`

- [ ] **Step 3: Implement `delete_branch` in `GitLabClient`**

In `backend/app/core/gitlab_client.py`, add after `get_or_create_branch` (around line 143):

```python
    def delete_branch(self, project_id: int, branch_name: str) -> bool:
        """Delete a branch. Returns True if deleted or already gone. Returns False on other errors."""
        try:
            project = self.get_project(project_id)
            branch = project.branches.get(branch_name)
            branch.delete()
            logger.info(f"Deleted branch: {branch_name} in project {project_id}")
            return True
        except GitlabGetError as e:
            if e.response_code == 404:
                logger.info(f"Branch already gone: {branch_name} in project {project_id}")
                return True
            logger.warning(f"GitLab error deleting branch {branch_name} in project {project_id}: {e}")
            return False
        except Exception as e:
            logger.warning(f"Unexpected error deleting branch {branch_name} in project {project_id}: {e}")
            return False
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd backend && python -m pytest tests/unit/test_gitlab_client_delete_branch.py -v
```
Expected: 4 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/gitlab_client.py backend/tests/unit/test_gitlab_client_delete_branch.py
git commit -m "feat: add GitLabClient.delete_branch method

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 4: `_serialize_issue` + `_try_delete_issue_branch` Helper

**Files:**
- Modify: `backend/app/api/issues.py`
- Modify: `backend/tests/unit/test_issues_api.py`

- [ ] **Step 1: Write failing tests for the helper**

Add at the bottom of `backend/tests/unit/test_issues_api.py`:

```python
# ---------------------------------------------------------------------------
# _try_delete_issue_branch helper
# ---------------------------------------------------------------------------

class TryDeleteIssueBranchTests(unittest.IsolatedAsyncioTestCase):
    """Tests for the _try_delete_issue_branch helper."""

    async def test_skips_when_no_branch_name(self):
        """Should do nothing when branch_name is None."""
        from app.api.issues import _try_delete_issue_branch
        issue = _make_issue(branch_name=None)
        issue.delete_branch_on_close = True
        issue.branch_deleted = False
        mock_db = MagicMock()
        with patch("app.api.issues.get_gitlab_client") as mock_gc:
            await _try_delete_issue_branch(issue, mock_db)
        mock_gc.assert_not_called()
        self.assertFalse(issue.branch_deleted)

    async def test_skips_when_delete_branch_on_close_is_false(self):
        """Should do nothing when delete_branch_on_close is False."""
        from app.api.issues import _try_delete_issue_branch
        issue = _make_issue(branch_name="codify/issue-1")
        issue.delete_branch_on_close = False
        issue.branch_deleted = False
        mock_db = MagicMock()
        with patch("app.api.issues.get_gitlab_client") as mock_gc:
            await _try_delete_issue_branch(issue, mock_db)
        mock_gc.assert_not_called()
        self.assertFalse(issue.branch_deleted)

    async def test_sets_branch_deleted_true_on_success(self):
        """Should set branch_deleted=True when GitLab client returns True."""
        from app.api.issues import _try_delete_issue_branch
        issue = _make_issue(branch_name="codify/issue-1", project_id=42)
        issue.delete_branch_on_close = True
        issue.branch_deleted = False
        mock_db = MagicMock()
        mock_client = MagicMock()
        mock_client.delete_branch.return_value = True
        with patch("app.api.issues.get_gitlab_client", return_value=mock_client):
            await _try_delete_issue_branch(issue, mock_db)
        mock_client.delete_branch.assert_called_once_with(42, "codify/issue-1")
        self.assertTrue(issue.branch_deleted)

    async def test_leaves_branch_deleted_false_on_failure(self):
        """Should leave branch_deleted=False when GitLab client returns False."""
        from app.api.issues import _try_delete_issue_branch
        issue = _make_issue(branch_name="codify/issue-1", project_id=42)
        issue.delete_branch_on_close = True
        issue.branch_deleted = False
        mock_db = MagicMock()
        mock_client = MagicMock()
        mock_client.delete_branch.return_value = False
        with patch("app.api.issues.get_gitlab_client", return_value=mock_client):
            await _try_delete_issue_branch(issue, mock_db)
        self.assertFalse(issue.branch_deleted)
```

Also update `_make_issue` helper to include the new fields (add at the end of the existing `_make_issue` kwargs):
```python
    # Add these two params to _make_issue signature:
    delete_branch_on_close=True,
    branch_deleted=False,
    # And these assignments in the body:
    issue.delete_branch_on_close = delete_branch_on_close
    issue.branch_deleted = branch_deleted
```

- [ ] **Step 2: Run failing tests**

```bash
cd backend && python -m pytest tests/unit/test_issues_api.py::TryDeleteIssueBranchTests -v
```
Expected: ImportError or AttributeError — `_try_delete_issue_branch` not found

- [ ] **Step 3: Update `_serialize_issue` to include new fields**

In `backend/app/api/issues.py`, find `_serialize_issue`. Add two lines after `"merge_request_url": issue.merge_request_url,`:

```python
        "delete_branch_on_close": issue.delete_branch_on_close,
        "branch_deleted": issue.branch_deleted,
```

- [ ] **Step 4: Add `get_gitlab_client` import to `issues.py`**

At the top of `backend/app/api/issues.py`, add to the existing imports:

```python
from app.core.gitlab_client import get_gitlab_client
```

- [ ] **Step 5: Add `_try_delete_issue_branch` helper to `issues.py`**

Add after `_serialize_issue_detail` (before the first `@router` decorator, around line 119):

```python
async def _try_delete_issue_branch(issue: Issue, db: AsyncSession) -> None:
    """Attempt to delete the issue's GitLab branch. Silently handles all failures."""
    if not issue.branch_name or not issue.delete_branch_on_close:
        return
    try:
        client = get_gitlab_client()
        success = client.delete_branch(issue.project_id, issue.branch_name)
        if success:
            issue.branch_deleted = True
        else:
            logger.warning(
                f"Branch deletion failed for issue {issue.id} "
                f"(branch: {issue.branch_name}) — leaving branch_deleted=False"
            )
    except Exception as e:
        logger.warning(f"Unexpected error in _try_delete_issue_branch for issue {issue.id}: {e}")
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
cd backend && python -m pytest tests/unit/test_issues_api.py::TryDeleteIssueBranchTests -v
```
Expected: 4 tests PASSED

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/issues.py backend/tests/unit/test_issues_api.py
git commit -m "feat: add _try_delete_issue_branch helper and serialize new fields

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 5: Update `CreateIssueRequest` and `close_issue`

**Files:**
- Modify: `backend/app/api/issues.py`
- Modify: `backend/tests/unit/test_issues_api.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/unit/test_issues_api.py`:

```python
class CloseIssueWithBranchDeletionTests(unittest.IsolatedAsyncioTestCase):
    """Tests for close_issue with branch deletion integration."""

    async def test_close_issue_calls_branch_deletion(self):
        """close_issue should call _try_delete_issue_branch when branch_name is set."""
        from app.api.issues import close_issue
        from app.models import IssueStatus

        issue = _make_issue(
            id=1,
            status=IssueStatus.OPEN.value,
            branch_name="codify/issue-1",
            delete_branch_on_close=True,
            branch_deleted=False,
        )

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = issue
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_user = MagicMock()

        with patch("app.api.issues._try_delete_issue_branch") as mock_helper:
            mock_helper.return_value = None  # async mock
            mock_helper.side_effect = AsyncMock(return_value=None)
            await close_issue(issue_id=1, db=mock_db, current_user=mock_user)

        mock_helper.assert_awaited_once_with(issue, mock_db)

    async def test_close_issue_still_commits_when_branch_deletion_fails(self):
        """close_issue should commit even if _try_delete_issue_branch raises."""
        from app.api.issues import close_issue
        from app.models import IssueStatus

        issue = _make_issue(id=1, status=IssueStatus.OPEN.value, delete_branch_on_close=True)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = issue
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_user = MagicMock()

        async def raise_on_delete(issue, db):
            raise RuntimeError("GitLab down")

        with patch("app.api.issues._try_delete_issue_branch", side_effect=raise_on_delete):
            # close_issue should not propagate the exception from _try_delete_issue_branch
            # because _try_delete_issue_branch itself swallows exceptions.
            # This test ensures the helper catches it internally.
            # Actually _try_delete_issue_branch itself catches all exceptions,
            # so close_issue should always succeed.
            result = await close_issue(issue_id=1, db=mock_db, current_user=mock_user)

        mock_db.commit.assert_awaited_once()
```

- [ ] **Step 2: Run failing tests**

```bash
cd backend && python -m pytest tests/unit/test_issues_api.py::CloseIssueWithBranchDeletionTests -v
```
Expected: FAIL — `close_issue` does not call `_try_delete_issue_branch` yet

- [ ] **Step 3: Update `CreateIssueRequest` in `issues.py`**

In `backend/app/api/issues.py`, update the `CreateIssueRequest` class:

```python
class CreateIssueRequest(BaseModel):
    """Request body for creating an issue."""

    title: str
    description: Optional[str] = None
    project_id: int
    base_branch: Optional[str] = None
    target_branch: Optional[str] = None
    delete_branch_on_close: bool = True
```

- [ ] **Step 4: Use `delete_branch_on_close` in `create_issue`**

In the `create_issue` endpoint, update the `Issue(...)` constructor call to include:

```python
    issue = Issue(
        title=body.title,
        description=body.description,
        project_id=body.project_id,
        status=IssueStatus.OPEN.value,
        base_branch=body.base_branch,
        target_branch=body.target_branch,
        delete_branch_on_close=body.delete_branch_on_close,
        initiator_user_id=current_user.id if current_user else None,
        initiator_username=current_user.username if current_user else None,
    )
```

- [ ] **Step 5: Call `_try_delete_issue_branch` in `close_issue`**

Update `close_issue` endpoint in `backend/app/api/issues.py`:

```python
@router.post("/{issue_id}/close")
async def close_issue(
    issue_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
):
    """Close an issue."""
    result = await db.execute(
        select(Issue)
        .where(Issue.id == issue_id)
        .options(selectinload(Issue.tasks))
    )
    issue = result.scalar_one_or_none()
    if issue is None:
        raise HTTPException(
            status_code=404,
            detail=f"Issue {issue_id} not found",
        )
    _require_issue_operator(issue, current_user)

    issue.status = IssueStatus.CLOSED.value
    issue.closed_via = "manual"
    await _try_delete_issue_branch(issue, db)
    await db.commit()
    await db.refresh(issue, attribute_names=["tasks"])
    return _serialize_issue_detail(issue)
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
cd backend && python -m pytest tests/unit/test_issues_api.py::CloseIssueWithBranchDeletionTests -v
```
Expected: 2 tests PASSED

- [ ] **Step 7: Run all issue API tests to check for regressions**

```bash
cd backend && python -m pytest tests/unit/test_issues_api.py -v
```
Expected: All existing tests still PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/issues.py backend/tests/unit/test_issues_api.py
git commit -m "feat: integrate branch deletion into close_issue and CreateIssueRequest

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 6: New `POST /issues/{id}/delete-branch` Endpoint

**Files:**
- Modify: `backend/app/api/issues.py`
- Modify: `backend/tests/unit/test_issues_api.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/unit/test_issues_api.py`:

```python
class DeleteIssueBranchEndpointTests(unittest.IsolatedAsyncioTestCase):
    """Tests for POST /issues/{id}/delete-branch."""

    async def _call(self, issue, mock_db, mock_user=None):
        from app.api.issues import delete_issue_branch
        if mock_user is None:
            mock_user = MagicMock()
        return await delete_issue_branch(
            issue_id=issue.id, db=mock_db, current_user=mock_user
        )

    async def test_delete_branch_success(self):
        """Should delete branch and set branch_deleted=True."""
        from app.models import IssueStatus

        issue = _make_issue(
            id=1, status=IssueStatus.CLOSED.value,
            branch_name="codify/issue-1", project_id=42,
            branch_deleted=False,
        )

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = issue
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        mock_client = MagicMock()
        mock_client.delete_branch.return_value = True

        with patch("app.api.issues.get_gitlab_client", return_value=mock_client):
            await self._call(issue, mock_db)

        mock_client.delete_branch.assert_called_once_with(42, "codify/issue-1")
        self.assertTrue(issue.branch_deleted)
        mock_db.commit.assert_awaited_once()

    async def test_delete_branch_not_found(self):
        """Should return 404 when issue does not exist."""
        from fastapi import HTTPException

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)

        issue = _make_issue(id=999)
        with self.assertRaises(HTTPException) as ctx:
            await self._call(issue, mock_db)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_delete_branch_issue_not_closed_returns_400(self):
        """Should return 400 when issue is still open."""
        from fastapi import HTTPException

        issue = _make_issue(id=1, status="open", branch_name="codify/issue-1")

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = issue
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)

        with self.assertRaises(HTTPException) as ctx:
            await self._call(issue, mock_db)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_delete_branch_no_branch_name_returns_400(self):
        """Should return 400 when issue has no branch_name."""
        from fastapi import HTTPException
        from app.models import IssueStatus

        issue = _make_issue(id=1, status=IssueStatus.CLOSED.value, branch_name=None)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = issue
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)

        with self.assertRaises(HTTPException) as ctx:
            await self._call(issue, mock_db)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_delete_branch_gitlab_failure_returns_500(self):
        """Should return 500 when GitLab deletion fails."""
        from fastapi import HTTPException
        from app.models import IssueStatus

        issue = _make_issue(
            id=1, status=IssueStatus.CLOSED.value,
            branch_name="codify/issue-1", project_id=42,
            branch_deleted=False,
        )

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = issue
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)

        mock_client = MagicMock()
        mock_client.delete_branch.return_value = False

        with patch("app.api.issues.get_gitlab_client", return_value=mock_client):
            with self.assertRaises(HTTPException) as ctx:
                await self._call(issue, mock_db)
        self.assertEqual(ctx.exception.status_code, 500)
```

- [ ] **Step 2: Run failing tests**

```bash
cd backend && python -m pytest tests/unit/test_issues_api.py::DeleteIssueBranchEndpointTests -v
```
Expected: ImportError — `delete_issue_branch` not found

- [ ] **Step 3: Implement the new endpoint in `issues.py`**

Add after `close_issue` (before `delete_issue`):

```python
@router.post("/{issue_id}/delete-branch")
async def delete_issue_branch(
    issue_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
):
    """Manually delete the GitLab branch associated with a closed issue."""
    result = await db.execute(
        select(Issue)
        .where(Issue.id == issue_id)
        .options(selectinload(Issue.tasks))
    )
    issue = result.scalar_one_or_none()
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    _require_issue_operator(issue, current_user)

    if issue.status != IssueStatus.CLOSED.value:
        raise HTTPException(
            status_code=400,
            detail="Issue must be closed before its branch can be deleted",
        )
    if not issue.branch_name:
        raise HTTPException(status_code=400, detail="Issue has no branch to delete")

    client = get_gitlab_client()
    success = client.delete_branch(issue.project_id, issue.branch_name)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete branch in GitLab")

    issue.branch_deleted = True
    await db.commit()
    await db.refresh(issue, attribute_names=["tasks"])
    return _serialize_issue_detail(issue)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd backend && python -m pytest tests/unit/test_issues_api.py::DeleteIssueBranchEndpointTests -v
```
Expected: 5 tests PASSED

- [ ] **Step 5: Run all issue API tests**

```bash
cd backend && python -m pytest tests/unit/test_issues_api.py -v
```
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/issues.py backend/tests/unit/test_issues_api.py
git commit -m "feat: add POST /issues/{id}/delete-branch endpoint

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 7: Webhook Handler — Branch Deletion on Auto-Close

**Files:**
- Modify: `backend/app/api/webhook_handler.py`
- Modify: `backend/tests/unit/test_webhook_handler.py`

- [ ] **Step 1: Write failing test**

Find the existing test class for MR merge in `backend/tests/unit/test_webhook_handler.py`. Add a new test (the existing `_make_issue_row` or mock patterns can be reused — inspect the file first):

```python
async def test_mr_merge_triggers_branch_deletion(self):
    """Branch deletion should be attempted when MR closes an issue."""
    # (Inspect existing test class name — add this alongside test_mr_merge_closes_issue)
    # Pattern: find the test that patches db.execute to return a matching issue,
    # then assert _try_delete_issue_branch is called.
    pass  # Replace with actual implementation after inspecting the file
```

> **Important:** Open `backend/tests/unit/test_webhook_handler.py` and find the test class/method that tests `"MR merge event → issue closed"`. Study how it mocks `db`, the `Issue` objects, and how it calls the handler. Add a test alongside it that patches `app.api.webhook_handler._try_delete_issue_branch` and asserts it was called with each newly-closed issue.

Concrete test to add after studying the file:

```python
async def test_mr_merge_calls_branch_deletion_for_each_closed_issue(self):
    """_try_delete_issue_branch is called for every newly-closed issue."""
    import json
    from app.api.webhook_handler import webhook_handler

    payload = _build_mr_merge_payload(project_id=42, mr_iid=7)

    mock_issue = MagicMock()
    mock_issue.id = 1
    mock_issue.status = "open"
    mock_issue.project_id = 42
    mock_issue.branch_name = "codify/issue-1"
    mock_issue.delete_branch_on_close = True
    mock_issue.branch_deleted = False

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_issue]

    webhook_event_result = MagicMock()
    webhook_event_result.scalars.return_value = mock_scalars

    # Mock db.execute to return issues on first call (MR lookup) and a webhook event mock otherwise
    call_count = [0]
    async def mock_execute(query, *args, **kwargs):
        call_count[0] += 1
        return webhook_event_result

    mock_db = MagicMock()
    mock_db.execute = mock_execute
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()

    with patch("app.api.webhook_handler._try_delete_issue_branch") as mock_del:
        mock_del.return_value = None
        mock_del.side_effect = AsyncMock(return_value=None)
        with patch("app.api.webhook_handler.get_effective_settings") as mock_settings:
            mock_settings.return_value.gitlab_webhook_secret = "secret"
            with patch("app.api.webhook_handler.load_runtime_config_from_db") as mock_load:
                mock_load.return_value = None
                with patch("app.api.webhook_handler.get_project_webhook_secret") as mock_proj_secret:
                    mock_proj_secret.return_value = None
                    # ... call the handler per existing test pattern
                    pass

    # Verify _try_delete_issue_branch was called with the issue
    mock_del.assert_awaited_once()
```

> **Note:** The webhook handler test setup is complex. Study the existing test that verifies issue closing. Replicate its mock structure exactly, then add a `patch("app.api.webhook_handler._try_delete_issue_branch")` wrapper and assert it was awaited. Use the existing test as a template.

- [ ] **Step 2: Run the failing test**

```bash
cd backend && python -m pytest tests/unit/test_webhook_handler.py -k "branch_deletion" -v
```
Expected: FAIL

- [ ] **Step 3: Update `webhook_handler.py` to import and call the helper**

At the top of `backend/app/api/webhook_handler.py`, add:

```python
from app.api.issues import _try_delete_issue_branch
```

In the MR-merged loop (around line 246-263), add the call immediately after setting `issue.closed_via`:

```python
        else:
            prev_status = issue.status
            issue.status = IssueStatus.CLOSED.value
            issue.closed_via = "webhook_mr_merged"
            await _try_delete_issue_branch(issue, db)   # <-- add this line
            await _log_event(
                db,
                ...
            )
            results.append({"issue_id": issue.id, "result": "issue_closed"})
```

The existing `await db.commit()` after the loop persists both the status change and `branch_deleted`.

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/unit/test_webhook_handler.py -v
```
Expected: All tests PASS (including the new one)

- [ ] **Step 5: Run full backend unit test suite**

```bash
cd backend && python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -30
```
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/webhook_handler.py backend/tests/unit/test_webhook_handler.py
git commit -m "feat: trigger branch deletion on webhook auto-close

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 8: Frontend — API Types and Function

**Files:**
- Modify: `frontend/src/api/index.ts`

- [ ] **Step 1: Extend the `Issue` interface**

In `frontend/src/api/index.ts`, find `export interface Issue {` (around line 147). Add two fields after `task_count?`:

```typescript
export interface Issue {
  id: number
  title: string
  description: string | null
  project_id: number
  status: IssueStatus
  closed_via: string | null
  branch_name: string | null
  base_branch: string | null
  target_branch: string | null
  merge_request_iid: number | null
  merge_request_url: string | null
  claude_session_id: string | null
  initiator_user_id: number | null
  initiator_username: string | null
  created_at: string
  updated_at: string
  delete_branch_on_close: boolean        // <-- add
  branch_deleted: boolean                // <-- add
  task_count?: number
  tasks?: Task[]
  totals?: {
    additions: number
    deletions: number
    total_changes: number
    input_tokens: number
    output_tokens: number
  }
}
```

- [ ] **Step 2: Extend `CreateIssueRequest`**

Find `export interface CreateIssueRequest {` (around line 175). Add:

```typescript
export interface CreateIssueRequest {
  title: string
  description?: string
  project_id: number
  base_branch?: string
  target_branch?: string
  delete_branch_on_close?: boolean     // <-- add
}
```

- [ ] **Step 3: Add `deleteIssueBranch` function**

Find `closeIssue` in `frontend/src/api/index.ts` (around line 1425). Add `deleteIssueBranch` right after it:

```typescript
export async function closeIssue(id: number): Promise<Issue> {
  const response = await api.post(`/issues/${id}/close`)
  return response.data
}

export async function deleteIssueBranch(id: number): Promise<Issue> {
  const response = await api.post(`/issues/${id}/delete-branch`)
  return response.data
}
```

- [ ] **Step 4: Type-check frontend**

```bash
cd frontend && npm run build 2>&1 | tail -20
```
Expected: Build succeeds with no TypeScript errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/index.ts
git commit -m "feat: extend Issue interface and add deleteIssueBranch API function

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 9: i18n Keys

**Files:**
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1: Add keys to `en.ts`**

In `frontend/src/i18n/messages/en.ts`, find the `issue:` section. Add these keys inside it (alongside `createMergeRequest`, `mrEnabled`, etc.):

```typescript
    deleteBranchOnClose: 'Delete branch on close',
    deleteBranchOnCloseEnabled: 'Branch will be deleted on close',
    deleteBranchOnCloseDisabled: 'Branch will be kept on close',
    deleteBranchBadge: 'Delete on close',
    keepBranchBadge: 'Keep branch',
    branchDeletedBadge: 'Branch deleted',
    deleteBranch: 'Delete Branch',
    deleteBranchConfirm: 'Delete the branch "{branch}" from GitLab? This cannot be undone.',
    deleteBranchSuccess: 'Branch deleted',
    deleteBranchFailed: 'Failed to delete branch',
    branchAlreadyDeleted: 'Branch already deleted',
```

- [ ] **Step 2: Add keys to `zh-CN.ts`**

In `frontend/src/i18n/messages/zh-CN.ts`, find the same `issue:` section and add:

```typescript
    deleteBranchOnClose: '关闭时删除分支',
    deleteBranchOnCloseEnabled: '关闭 issue 时将删除分支',
    deleteBranchOnCloseDisabled: '关闭 issue 时保留分支',
    deleteBranchBadge: '关闭时删除分支',
    keepBranchBadge: '保留分支',
    branchDeletedBadge: '分支已删除',
    deleteBranch: '删除分支',
    deleteBranchConfirm: '确认从 GitLab 删除分支 "{branch}"？此操作不可撤销。',
    deleteBranchSuccess: '分支已删除',
    deleteBranchFailed: '删除分支失败',
    branchAlreadyDeleted: '分支已删除',
```

- [ ] **Step 3: Build to verify no i18n errors**

```bash
cd frontend && npm run build 2>&1 | tail -10
```
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: add i18n keys for branch deletion feature

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 10: `CreateIssue.vue` — Toggle Field

**Files:**
- Modify: `frontend/src/views/CreateIssue.vue`

- [ ] **Step 1: Add `delete_branch_on_close` to the form value type and initial value**

Find `createInitialFormValue` (around line 252). Add `delete_branch_on_close` to the type and return value:

```typescript
function createInitialFormValue(): {
  title: string
  description: string
  project_id: number | undefined
  base_branch: string | undefined
  target_branch: string | undefined
  create_mr: boolean
  delete_branch_on_close: boolean       // <-- add
} {
  return {
    title: '',
    description: '',
    project_id: undefined,
    base_branch: undefined,
    target_branch: undefined,
    create_mr: true,
    delete_branch_on_close: true,       // <-- add (default true)
  }
}
```

- [ ] **Step 2: Add the toggle to the form template**

In `frontend/src/views/CreateIssue.vue`, find the `<n-gi>` block containing the `create_mr` switch (around line 101). Add a new `<n-gi>` block immediately after it (before `<n-gi v-if="formValue.create_mr">`):

```html
                <n-gi>
                  <n-form-item :label="t('issue.deleteBranchOnClose')" path="delete_branch_on_close">
                    <n-space align="center" :size="8">
                      <n-switch v-model:value="formValue.delete_branch_on_close" />
                      <span style="font-size: 13px; color: var(--n-text-color-2)">
                        {{ formValue.delete_branch_on_close
                          ? t('issue.deleteBranchOnCloseEnabled')
                          : t('issue.deleteBranchOnCloseDisabled') }}
                      </span>
                    </n-space>
                  </n-form-item>
                </n-gi>
```

- [ ] **Step 3: Include `delete_branch_on_close` in the submit request**

Find `handleSubmit` (around line 414). Update the `request` object:

```typescript
    const request: CreateIssueRequest = {
      title: formValue.value.title,
      project_id: formValue.value.project_id!,
      description: formValue.value.description || undefined,
      base_branch: formValue.value.base_branch,
      target_branch: formValue.value.create_mr ? formValue.value.target_branch || undefined : undefined,
      delete_branch_on_close: formValue.value.delete_branch_on_close,  // <-- add
    }
```

- [ ] **Step 4: Build to verify no errors**

```bash
cd frontend && npm run build 2>&1 | tail -10
```
Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/CreateIssue.vue
git commit -m "feat: add delete_branch_on_close toggle to create issue form

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 11: `IssueView.vue` — Badges and Delete Branch Button

**Files:**
- Modify: `frontend/src/views/IssueView.vue`

- [ ] **Step 1: Import `deleteIssueBranch` in the script**

Find the import line for `closeIssue` (around line 534):

```typescript
  getIssue, updateIssue, closeIssue, createTask, retryTask, getPromptTemplates,
```

Add `deleteIssueBranch`:

```typescript
  getIssue, updateIssue, closeIssue, deleteIssueBranch, createTask, retryTask, getPromptTemplates,
```

- [ ] **Step 2: Add `deletingBranch` reactive state**

Find where reactive state variables are declared (e.g., `const loading = ref(false)`). Add:

```typescript
const deletingBranch = ref(false)
```

- [ ] **Step 3: Add `handleDeleteBranch` function**

Near `handleClose` (around line 886), add:

```typescript
async function handleDeleteBranch() {
  if (!issue.value) return
  deletingBranch.value = true
  try {
    issue.value = await deleteIssueBranch(issueId.value)
    message.success(t('issue.deleteBranchSuccess'))
  } catch {
    message.error(t('issue.deleteBranchFailed'))
  } finally {
    deletingBranch.value = false
  }
}
```

- [ ] **Step 4: Add branch-policy badges and delete button to the branch flow section**

Find the branch flow `<div class="metadata-row">` in the template (around line 102). After the closing `</div>` of that row (line ~118), add a new metadata row for the branch policy badges and delete button:

```html
              <!-- Branch deletion policy -->
              <div v-if="issue.branch_name" class="metadata-row">
                <span class="metadata-label">
                  <n-icon size="14" class="metadata-label-icon"><GitBranchOutline /></n-icon>
                  {{ t('issue.deleteBranchOnClose') }}
                </span>
                <span class="metadata-value">
                  <n-space align="center" :size="6">
                    <n-tag
                      size="small"
                      round
                      :type="issue.delete_branch_on_close ? 'info' : 'default'"
                    >
                      {{ issue.delete_branch_on_close
                        ? t('issue.deleteBranchBadge')
                        : t('issue.keepBranchBadge') }}
                    </n-tag>
                    <n-tag
                      v-if="issue.branch_deleted"
                      size="small"
                      round
                      type="warning"
                    >
                      {{ t('issue.branchDeletedBadge') }}
                    </n-tag>
                    <n-tooltip v-if="issue.status === 'closed'" :disabled="!issue.branch_deleted">
                      <template #trigger>
                        <n-button
                          size="tiny"
                          :disabled="issue.branch_deleted || deletingBranch"
                          :loading="deletingBranch"
                          @click="handleDeleteBranch"
                        >
                          {{ t('issue.deleteBranch') }}
                        </n-button>
                      </template>
                      {{ t('issue.branchAlreadyDeleted') }}
                    </n-tooltip>
                  </n-space>
                </span>
              </div>
```

- [ ] **Step 5: Ensure `NTooltip` is imported in the component**

Find the component imports section (around line 511):

```typescript
  NButton, NSpace, NCard, NTag, NGrid, NGi, NSpin,
```

Add `NTooltip` if it's not already imported:

```typescript
  NButton, NSpace, NCard, NTag, NGrid, NGi, NSpin, NTooltip,
```

Also ensure `NTooltip` is in the `import { ... } from 'naive-ui'` statement at the top of the `<script>` block.

- [ ] **Step 6: Build to verify no TypeScript or template errors**

```bash
cd frontend && npm run build 2>&1 | tail -20
```
Expected: Build succeeds with no errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/IssueView.vue
git commit -m "feat: add branch deletion badges and delete-branch button to IssueView

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 12: Final Validation

- [ ] **Step 1: Run all backend unit tests**

```bash
cd backend && python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -30
```
Expected: All tests PASS, 0 failures

- [ ] **Step 2: Run mock E2E tests**

```bash
cd backend && python -m pytest tests/mock_e2e/ -v --tb=short 2>&1 | tail -20
```
Expected: All tests PASS

- [ ] **Step 3: Run frontend type-check + build**

```bash
cd frontend && npm run build 2>&1 | tail -10
```
Expected: Build succeeds

- [ ] **Step 4: Commit final summary**

```bash
git commit --allow-empty -m "feat: issue branch deletion on close — complete

- New Issue fields: delete_branch_on_close (default true), branch_deleted
- Migration 038_add_branch_deletion_fields
- GitLabClient.delete_branch() — 404 treated as already deleted
- _try_delete_issue_branch() helper called on both close paths
- POST /issues/{id}/delete-branch endpoint
- CreateIssue.vue: toggle for delete_branch_on_close
- IssueView.vue: policy badges + delete-branch button (disabled when deleted)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```
