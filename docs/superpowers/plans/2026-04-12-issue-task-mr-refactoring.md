# Issue→Task→MR Refactoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor Codify from a flat Task→MR model to a three-layer Issue→Task→MR model where Issues are requirement containers, Tasks are execution units (one `claude -p` call), and MRs belong to Issues.

**Architecture:** Add an Issue entity as the parent of Tasks. Issues own branch/MR info and Claude session state. Tasks are created under Issues and inherit branch/session context. Session files are persisted to the host file system and mounted into Docker containers for resume. The scheduler prevents concurrent tasks within the same Issue. Issue status auto-transitions based on child task states.

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy (async) / Alembic / Vue 3 / Naive UI / TypeScript / Docker

**Spec:** `docs/superpowers/specs/2026-04-12-issue-task-mr-refactoring-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `backend/app/api/issues.py` | Issue CRUD API endpoints |
| `backend/alembic/versions/022_issue_task_mr_refactoring.py` | DB migration: create issues table, modify tasks table |
| `backend/tests/unit/test_issues_api.py` | Unit tests for Issue API |
| `backend/tests/unit/test_scheduler_issue.py` | Unit tests for scheduler Issue-aware changes |
| `frontend/src/views/IssueList.vue` | Issue list page |
| `frontend/src/views/IssueView.vue` | Issue detail page with embedded task creation |
| `frontend/src/views/CreateIssue.vue` | Create Issue form page |

### Modified Files

| File | Changes |
|------|---------|
| `backend/app/models.py` | Add Issue model + IssueStatus enum, modify Task model (add issue_id FK, remove promoted fields) |
| `backend/app/api/tasks.py` | Require issue_id on create, update retry to create new task, update queries |
| `backend/app/scheduler.py` | Issue-based mutex, auto status transition, updated container naming |
| `backend/app/core/worker.py` | Read branch/MR from Issue, session management, new container env vars |
| `backend/app/config.py` | Add SESSION_STORAGE_ROOT setting |
| `backend/app/main.py` | Register issues router |
| `backend/app/api/stats.py` | Add issue stats to dashboard endpoint |
| `deploy/entrypoint.sh` | Session resume logic, remove --no-session-persistence |
| `frontend/src/api/index.ts` | Add Issue types + API functions, update Task type |
| `frontend/src/router/index.ts` | Add Issue routes |
| `frontend/src/views/Dashboard.vue` | Redesign to Overview style |
| `frontend/src/views/TaskView.vue` | Add Issue link in metadata |
| `frontend/src/App.vue` | Add Issues nav item |
| `frontend/src/i18n/messages/en.ts` | Add Issue i18n keys |
| `frontend/src/i18n/messages/zh-CN.ts` | Add Issue i18n keys |

### Removed/Deprecated

| File | Changes |
|------|---------|
| `backend/app/api/webhook.py` | Remove or gut webhook handler (keep file, remove routes from main.py) |
| `frontend/src/views/CreateTask.vue` | Keep but simplify — primary task creation moves to IssueView |

---

## Task 1: Issue Model + Migration

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/022_issue_task_mr_refactoring.py`

- [ ] **Step 1: Add IssueStatus enum and Issue model to models.py**

Add after the existing `TaskStatus` enum (around line 30):

```python
class IssueStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CLOSED = "closed"
```

Add the Issue class after the Task class (after line 123):

```python
class Issue(Base):
    __tablename__ = "issues"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    project_id = Column(Integer, nullable=False, index=True)
    status = Column(String(20), default=IssueStatus.OPEN.value, nullable=False)

    branch_name = Column(String(255), nullable=True)
    base_branch = Column(String(255), nullable=True)
    target_branch = Column(String(255), nullable=True)

    merge_request_iid = Column(Integer, nullable=True)
    merge_request_url = Column(String(512), nullable=True)

    claude_session_id = Column(String(255), nullable=True)
    session_storage_path = Column(String(512), nullable=True)

    initiator_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    initiator_username = Column(String(255), nullable=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    tasks = relationship("Task", back_populates="issue", order_by="Task.created_at")

    __table_args__ = (
        Index("ix_issues_status_created", "status", "created_at"),
        Index("ix_issues_project_status", "project_id", "status"),
    )
```

- [ ] **Step 2: Modify Task model — add issue_id FK and retry fields**

Add these columns to the Task class (around line 40, after `project_id`):

```python
    issue_id = Column(Integer, ForeignKey("issues.id"), nullable=True, index=True)
    is_retry = Column(Boolean, default=False, nullable=False)
    retry_source_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
```

Add relationships:

```python
    issue = relationship("Issue", back_populates="tasks")
    retry_source = relationship("Task", remote_side="Task.id", foreign_keys="Task.retry_source_task_id")
```

- [ ] **Step 3: Remove deprecated fields from Task model**

Remove these columns from the Task class:
- `issue_iid` (line ~41)
- `issue_id` (the old GitLab one, line ~42) — rename our new FK carefully
- `note_id` (line ~43)
- `is_manual` (line ~49)
- `branch_name` (line ~59)
- `base_branch` (line ~60)
- `target_branch` (line ~62)
- `merge_request_iid` (line ~63)
- `merge_request_url` (line ~64)

Also update the `__table_args__` indexes to remove references to deleted columns and add `issue_id` index.

- [ ] **Step 4: Create Alembic migration**

Create `backend/alembic/versions/022_issue_task_mr_refactoring.py`:

```python
"""issue task mr refactoring

Revision ID: 022_issue_task_mr_refactoring
Revises: 021_add_structured_logs
Create Date: 2026-04-12
"""
from alembic import op
import sqlalchemy as sa

revision: str = "022_issue_task_mr_refactoring"
down_revision: str = "021_add_structured_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create issues table
    op.create_table(
        "issues",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), server_default="open", nullable=False),
        sa.Column("branch_name", sa.String(255), nullable=True),
        sa.Column("base_branch", sa.String(255), nullable=True),
        sa.Column("target_branch", sa.String(255), nullable=True),
        sa.Column("merge_request_iid", sa.Integer(), nullable=True),
        sa.Column("merge_request_url", sa.String(512), nullable=True),
        sa.Column("claude_session_id", sa.String(255), nullable=True),
        sa.Column("session_storage_path", sa.String(512), nullable=True),
        sa.Column("initiator_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("initiator_username", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_issues_project_id", "issues", ["project_id"])
    op.create_index("ix_issues_status_created", "issues", ["status", "created_at"])
    op.create_index("ix_issues_project_status", "issues", ["project_id", "status"])

    # Add new columns to tasks
    op.add_column("tasks", sa.Column("issue_id", sa.Integer(), sa.ForeignKey("issues.id"), nullable=True))
    op.add_column("tasks", sa.Column("is_retry", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("tasks", sa.Column("retry_source_task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=True))
    op.create_index("ix_tasks_issue_id", "tasks", ["issue_id"])

    # Remove deprecated columns from tasks
    op.drop_index("ix_tasks_project_id_issue_iid", table_name="tasks")
    op.drop_column("tasks", "issue_iid")
    op.drop_column("tasks", "issue_id")  # old GitLab issue_id
    op.drop_column("tasks", "note_id")
    op.drop_column("tasks", "is_manual")
    op.drop_column("tasks", "branch_name")
    op.drop_column("tasks", "base_branch")
    op.drop_column("tasks", "target_branch")
    op.drop_column("tasks", "merge_request_iid")
    op.drop_column("tasks", "merge_request_url")


def downgrade() -> None:
    # Re-add removed columns to tasks
    op.add_column("tasks", sa.Column("merge_request_url", sa.String(512), nullable=True))
    op.add_column("tasks", sa.Column("merge_request_iid", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("target_branch", sa.String(255), nullable=True))
    op.add_column("tasks", sa.Column("base_branch", sa.String(255), nullable=True))
    op.add_column("tasks", sa.Column("branch_name", sa.String(255), nullable=True))
    op.add_column("tasks", sa.Column("is_manual", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("tasks", sa.Column("note_id", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("issue_id", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("issue_iid", sa.Integer(), nullable=True))
    op.create_index("ix_tasks_project_id_issue_iid", "tasks", ["project_id", "issue_iid"])

    # Remove new columns from tasks
    op.drop_index("ix_tasks_issue_id", table_name="tasks")
    op.drop_column("tasks", "retry_source_task_id")
    op.drop_column("tasks", "is_retry")
    op.drop_column("tasks", "issue_id")

    # Drop issues table
    op.drop_index("ix_issues_project_status", table_name="issues")
    op.drop_index("ix_issues_status_created", table_name="issues")
    op.drop_index("ix_issues_project_id", table_name="issues")
    op.drop_table("issues")
```

- [ ] **Step 5: Verify migration compiles**

Run: `cd backend && python -c "from alembic.versions import *; print('OK')"`

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/022_issue_task_mr_refactoring.py
git commit -m "feat: add Issue model and migration for Issue→Task→MR refactoring"
```

---

## Task 2: Config — Add SESSION_STORAGE_ROOT

**Files:**
- Modify: `backend/app/config.py`

- [ ] **Step 1: Add session storage config to Settings class**

In `backend/app/config.py`, add to the Settings class (around line 140, near other path settings like `worker_ca_cert_host_path`):

```python
    session_storage_root: str = Field(
        default="/var/codify/sessions",
        description="Root directory for Claude session file storage"
    )
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/config.py
git commit -m "feat: add SESSION_STORAGE_ROOT config for session persistence"
```

---

## Task 3: Issue API

**Files:**
- Create: `backend/app/api/issues.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/unit/test_issues_api.py`

- [ ] **Step 1: Write tests for Issue API**

Create `backend/tests/unit/test_issues_api.py`:

```python
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from app.models import Issue, IssueStatus


class TestCreateIssue(unittest.IsolatedAsyncioTestCase):
    """Test POST /api/issues"""

    async def test_create_issue_success(self):
        from app.api.issues import create_issue

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.flush = AsyncMock()

        request = MagicMock()
        request.title = "Test Issue"
        request.description = "Test description"
        request.project_id = 1
        request.base_branch = "main"
        request.target_branch = "main"

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "testuser"

        with patch("app.api.issues.get_effective_settings") as mock_settings:
            mock_settings.return_value = MagicMock(session_storage_root="/var/codify/sessions")
            result = await create_issue(request, mock_db, mock_user)

        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()
        added_issue = mock_db.add.call_args[0][0]
        assert added_issue.title == "Test Issue"
        assert added_issue.project_id == 1
        assert added_issue.status == IssueStatus.OPEN.value


class TestListIssues(unittest.IsolatedAsyncioTestCase):
    """Test GET /api/issues"""

    async def test_list_issues_default(self):
        from app.api.issues import list_issues

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_result])

        mock_user = MagicMock()
        result = await list_issues(db=mock_db, current_user=mock_user)
        assert result["total"] == 0
        assert result["items"] == []


class TestCloseIssue(unittest.IsolatedAsyncioTestCase):
    """Test POST /api/issues/{id}/close"""

    async def test_close_issue_success(self):
        from app.api.issues import close_issue

        mock_issue = MagicMock()
        mock_issue.id = 1
        mock_issue.status = IssueStatus.OPEN.value

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=mock_issue)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        mock_user = MagicMock()
        result = await close_issue(issue_id=1, db=mock_db, current_user=mock_user)
        assert mock_issue.status == IssueStatus.CLOSED.value


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_issues_api.py -v`
Expected: ImportError — `app.api.issues` does not exist yet.

- [ ] **Step 3: Implement Issue API**

Create `backend/app/api/issues.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field
from typing import Optional, List

from app.models import Issue, IssueStatus, Task
from app.database import get_db
from app.api.auth import require_authenticated_user
from app.config import get_effective_settings

router = APIRouter(prefix="/issues", tags=["issues"])


class CreateIssueRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    description: Optional[str] = None
    project_id: int
    base_branch: Optional[str] = None
    target_branch: Optional[str] = None


class UpdateIssueRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=512)
    description: Optional[str] = None
    status: Optional[str] = None


def _serialize_issue(issue: Issue, task_count: int = None) -> dict:
    data = {
        "id": issue.id,
        "title": issue.title,
        "description": issue.description,
        "project_id": issue.project_id,
        "status": issue.status,
        "branch_name": issue.branch_name,
        "base_branch": issue.base_branch,
        "target_branch": issue.target_branch,
        "merge_request_iid": issue.merge_request_iid,
        "merge_request_url": issue.merge_request_url,
        "claude_session_id": issue.claude_session_id,
        "initiator_user_id": issue.initiator_user_id,
        "initiator_username": issue.initiator_username,
        "created_at": issue.created_at.isoformat() if issue.created_at else None,
        "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
    }
    if task_count is not None:
        data["task_count"] = task_count
    return data


def _serialize_issue_with_tasks(issue: Issue) -> dict:
    data = _serialize_issue(issue)
    data["tasks"] = [
        {
            "id": t.id,
            "user_prompt": t.user_prompt,
            "status": t.status.value if hasattr(t.status, "value") else t.status,
            "priority": t.priority,
            "is_retry": t.is_retry,
            "retry_source_task_id": t.retry_source_task_id,
            "commit_sha": t.commit_sha,
            "error_message": t.error_message,
            "input_tokens": t.input_tokens,
            "output_tokens": t.output_tokens,
            "model_name": t.model_name,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        }
        for t in (issue.tasks or [])
    ]
    return data


@router.post("")
async def create_issue(
    request: CreateIssueRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_authenticated_user),
):
    settings = get_effective_settings()

    issue = Issue(
        title=request.title,
        description=request.description,
        project_id=request.project_id,
        status=IssueStatus.OPEN.value,
        base_branch=request.base_branch,
        target_branch=request.target_branch,
        initiator_user_id=current_user.id,
        initiator_username=getattr(current_user, "username", None),
    )
    db.add(issue)
    await db.flush()

    # Generate branch name and session storage path using the issue ID
    issue.branch_name = f"codify/issue-{issue.id}"
    issue.session_storage_path = f"{settings.session_storage_root}/{issue.id}/claude"

    await db.commit()
    await db.refresh(issue)
    return _serialize_issue(issue)


@router.get("")
async def list_issues(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_authenticated_user),
    status: Optional[str] = Query(None),
    project_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    # Count query
    count_q = select(func.count(Issue.id))
    if status:
        count_q = count_q.where(Issue.status == status)
    if project_id:
        count_q = count_q.where(Issue.project_id == project_id)
    total = (await db.execute(count_q)).scalar()

    # Data query with task count subquery
    task_count_subq = (
        select(Task.issue_id, func.count(Task.id).label("task_count"))
        .group_by(Task.issue_id)
        .subquery()
    )

    q = (
        select(Issue, task_count_subq.c.task_count)
        .outerjoin(task_count_subq, Issue.id == task_count_subq.c.issue_id)
        .order_by(desc(Issue.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if status:
        q = q.where(Issue.status == status)
    if project_id:
        q = q.where(Issue.project_id == project_id)

    result = await db.execute(q)
    rows = result.all()

    items = [_serialize_issue(row[0], task_count=row[1] or 0) for row in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{issue_id}")
async def get_issue(
    issue_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_authenticated_user),
):
    result = await db.execute(
        select(Issue).where(Issue.id == issue_id).options(selectinload(Issue.tasks))
    )
    issue = result.scalars().first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return _serialize_issue_with_tasks(issue)


@router.patch("/{issue_id}")
async def update_issue(
    issue_id: int,
    request: UpdateIssueRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_authenticated_user),
):
    issue = await db.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    if request.title is not None:
        issue.title = request.title
    if request.description is not None:
        issue.description = request.description
    if request.status is not None:
        if request.status not in [s.value for s in IssueStatus]:
            raise HTTPException(status_code=400, detail=f"Invalid status: {request.status}")
        issue.status = request.status

    await db.commit()
    await db.refresh(issue)
    return _serialize_issue(issue)


@router.post("/{issue_id}/close")
async def close_issue(
    issue_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_authenticated_user),
):
    issue = await db.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue.status = IssueStatus.CLOSED.value
    await db.commit()
    await db.refresh(issue)
    return _serialize_issue(issue)


@router.delete("/{issue_id}")
async def delete_issue(
    issue_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_authenticated_user),
):
    issue = await db.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Check if there are running tasks
    running = await db.execute(
        select(func.count(Task.id)).where(
            Task.issue_id == issue_id,
            Task.status.in_(["running", "queued", "pending"])
        )
    )
    if running.scalar() > 0:
        raise HTTPException(status_code=409, detail="Cannot delete issue with active tasks")

    await db.delete(issue)
    await db.commit()
    return {"detail": "Issue deleted"}
```

- [ ] **Step 4: Register issues router in main.py**

In `backend/app/main.py`, add the import and router include alongside existing routers (around line 202-277):

```python
from app.api.issues import router as issues_router
# ... in the router setup section:
app.include_router(issues_router, prefix="/api")
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python -m pytest tests/unit/test_issues_api.py -v`
Expected: Tests pass (may need adjustments for import paths).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/issues.py backend/app/main.py backend/tests/unit/test_issues_api.py
git commit -m "feat: add Issue CRUD API endpoints"
```

---

## Task 4: Modify Task API

**Files:**
- Modify: `backend/app/api/tasks.py`

- [ ] **Step 1: Update CreateTaskRequest to require issue_id**

In `backend/app/api/tasks.py`, find the `CreateTaskRequest` Pydantic model and update it:

```python
class CreateTaskRequest(BaseModel):
    issue_id: int  # Required — every task belongs to an issue
    user_prompt: Optional[str] = None  # If None, uses Issue.description
    priority: Optional[int] = Field(default=0, ge=0, le=2)
    delay_seconds: Optional[int] = None
    scheduled_datetime: Optional[str] = None
```

Remove fields that are now on Issue: `project_id`, `branch_name`, `base_branch`, `target_branch`.

- [ ] **Step 2: Update create_task endpoint**

Update the `create_task()` function (around line 628) to:
1. Load the Issue by `issue_id`
2. Use `issue.description` as default prompt if `user_prompt` is not provided
3. Set `task.project_id = issue.project_id`
4. Remove branch/MR field assignment

```python
@router.post("")
async def create_task(
    request: CreateTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_authenticated_user),
):
    from app.models import Issue
    issue = await db.get(Issue, request.issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    prompt = request.user_prompt or issue.description
    if not prompt:
        raise HTTPException(status_code=400, detail="No prompt provided and issue has no description")

    scheduled_at = resolve_scheduled_at(request.delay_seconds, request.scheduled_datetime)

    task = Task(
        issue_id=issue.id,
        project_id=issue.project_id,
        user_prompt=prompt,
        priority=request.priority or 0,
        scheduled_at=scheduled_at,
        status=TaskStatus.PENDING,
        initiator_user_id=current_user.id,
        initiator_username=getattr(current_user, "username", None),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return _serialize_task(task)
```

- [ ] **Step 3: Update retry_task endpoint**

Update the `retry_task()` function (around line 514) to create a new task instead of resetting the old one:

```python
@router.post("/{task_id}/retry")
async def retry_task(
    task_id: int,
    scheduled_at: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_authenticated_user),
):
    original_task = await db.get(Task, task_id)
    if not original_task:
        raise HTTPException(status_code=404, detail="Task not found")
    if original_task.status not in (TaskStatus.FAILED, TaskStatus.CANCELLED):
        raise HTTPException(status_code=400, detail="Only failed or cancelled tasks can be retried")

    resolved_scheduled_at = resolve_scheduled_at(None, scheduled_at) if scheduled_at else None

    new_task = Task(
        issue_id=original_task.issue_id,
        project_id=original_task.project_id,
        user_prompt=original_task.user_prompt,
        priority=original_task.priority,
        scheduled_at=resolved_scheduled_at,
        status=TaskStatus.PENDING,
        is_retry=True,
        retry_source_task_id=original_task.id,
        initiator_user_id=current_user.id,
        initiator_username=getattr(current_user, "username", None),
    )
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)
    return _serialize_task(new_task)
```

- [ ] **Step 4: Update task serialization**

Update `_serialize_task()` to include `issue_id`, `is_retry`, `retry_source_task_id` and remove deleted fields (`branch_name`, `base_branch`, etc.). Add issue info if available:

```python
def _serialize_task(task, issue=None):
    data = {
        "id": task.id,
        "issue_id": task.issue_id,
        "project_id": task.project_id,
        "user_prompt": task.user_prompt,
        "status": task.status.value if hasattr(task.status, "value") else task.status,
        "priority": task.priority,
        "is_retry": task.is_retry,
        "retry_source_task_id": task.retry_source_task_id,
        "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
        "container_id": task.container_id,
        "commit_sha": task.commit_sha,
        "error_message": task.error_message,
        "additions": task.additions,
        "deletions": task.deletions,
        "total_changes": task.total_changes,
        "input_tokens": task.input_tokens,
        "output_tokens": task.output_tokens,
        "model_name": task.model_name,
        "merge_request_title": task.merge_request_title,
        "retry_count": task.retry_count,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }
    if issue:
        data["issue"] = {
            "id": issue.id,
            "title": issue.title,
            "branch_name": issue.branch_name,
            "merge_request_url": issue.merge_request_url,
        }
    return data
```

- [ ] **Step 5: Update list_tasks to support issue_id filter**

Add `issue_id` query parameter to `list_tasks()`:

```python
@router.get("")
async def list_tasks(
    # ... existing params ...
    issue_id: Optional[int] = Query(None),
    # ...
):
    # Add filter:
    if issue_id:
        query = query.where(Task.issue_id == issue_id)
```

- [ ] **Step 6: Update get_task to include issue info**

In `get_task()`, also load the related Issue and include it in the response.

- [ ] **Step 7: Run existing tests and fix breakages**

Run: `cd backend && python -m pytest tests/unit/test_task*.py -v`
Fix any tests broken by model changes. Many tests reference `is_manual`, `branch_name`, etc. — update them.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/tasks.py
git commit -m "feat: update Task API for Issue→Task model"
```

---

## Task 5: Scheduler Changes

**Files:**
- Modify: `backend/app/scheduler.py`

- [ ] **Step 1: Update Issue mutex from string to int**

In `__init__` (line ~46), change:
```python
# Old:
self._running_issues: Set[str] = set()  # "project_id:issue_iid"
# New:
self._running_issues: Set[int] = set()  # issue_id
```

- [ ] **Step 2: Update _get_next_task to use issue_id for mutex**

In `_get_next_task()` (line ~126), update the issue key extraction:

```python
# Old:
if not task.is_manual and task.issue_iid:
    issue_key = f"{task.project_id}:{task.issue_iid}"
# New:
if task.issue_id:
    issue_key = task.issue_id
```

- [ ] **Step 3: Update _execute_task for Issue status transition**

In `_execute_task()` (line ~154), after setting task to RUNNING, add Issue status transition:

```python
from app.models import Issue, IssueStatus

# After task status = RUNNING:
if task.issue_id:
    issue = await db.get(Issue, task.issue_id)
    if issue and issue.status == IssueStatus.OPEN.value:
        issue.status = IssueStatus.IN_PROGRESS.value
        await db.commit()
```

- [ ] **Step 4: Add _on_task_completed for Issue status auto-transition**

Add a method to check if all tasks in an Issue are done and update Issue status:

```python
async def _update_issue_on_task_complete(self, db: AsyncSession, task):
    """Update Issue status when a task completes."""
    if not task.issue_id:
        return

    issue = await db.get(Issue, task.issue_id)
    if not issue or issue.status == IssueStatus.CLOSED.value:
        return

    # Check for any remaining active tasks
    active_count = (await db.execute(
        select(func.count(Task.id)).where(
            Task.issue_id == task.issue_id,
            Task.status.in_([
                TaskStatus.PENDING.value,
                TaskStatus.QUEUED.value,
                TaskStatus.RUNNING.value,
            ])
        )
    )).scalar()

    if active_count == 0 and task.status == TaskStatus.COMPLETED:
        issue.status = IssueStatus.COMPLETED.value
        await db.commit()
```

Call this method in `_run_worker_task()` after task completion.

- [ ] **Step 5: Update container naming pattern**

In `backend/app/scheduler.py` (line ~31), update the container pattern:

```python
# Old:
WORKER_CONTAINER_PATTERN = re.compile(r"codify-(\d+)-p(\d+)-(i\d+|manual)")
# New:
WORKER_CONTAINER_PATTERN = re.compile(r"codify-(\d+)-issue(\d+)")
```

Update `_extract_task_id()` accordingly.

- [ ] **Step 6: Update crash recovery**

Update `_crash_recovery()` (line ~222) to match the new container naming pattern and use `issue_id` for the issue key.

- [ ] **Step 7: Run scheduler tests**

Run: `cd backend && python -m pytest tests/unit/test_scheduler*.py -v`
Fix any broken tests.

- [ ] **Step 8: Commit**

```bash
git add backend/app/scheduler.py
git commit -m "feat: update scheduler for Issue-based mutex and status transitions"
```

---

## Task 6: Worker Changes

**Files:**
- Modify: `backend/app/core/worker.py`

- [ ] **Step 1: Update execute_task to read from Issue**

In `execute_task()` (line ~866), load the Issue and use its branch/MR info:

```python
async def execute_task(self, db, task_id):
    task = await db.get(Task, task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")

    # Load parent issue
    from app.models import Issue
    issue = await db.get(Issue, task.issue_id)
    if not issue:
        raise ValueError(f"Issue {task.issue_id} not found for task {task_id}")

    branch_name = issue.branch_name
    base_branch = issue.base_branch
    target_branch = issue.target_branch
    claude_session_id = issue.claude_session_id
    session_storage_path = issue.session_storage_path
```

- [ ] **Step 2: Update container environment variables**

In the env var building section (line ~503), add session-related vars and remove task-level branch vars:

```python
env = {
    # ... existing vars ...
    "BRANCH_NAME": branch_name,
    "BASE_BRANCH": base_branch or "",
    "TARGET_BRANCH": target_branch or "",
    "ISSUE_ID": str(issue.id),
    "CLAUDE_SESSION_ID": claude_session_id or "",
    # Remove: task.branch_name, task.base_branch, task.target_branch
}
```

- [ ] **Step 3: Add session storage volume mount**

In the volume building section (line ~556), add:

```python
import os

if session_storage_path:
    os.makedirs(session_storage_path, exist_ok=True)
    volumes[session_storage_path] = {"bind": "/home/codify/.claude", "mode": "rw"}
```

- [ ] **Step 4: Update container naming**

Update the container name generation:

```python
# Old:
container_name = f"codify-{task_id}-p{project_id}-{'i' + str(issue_iid) if issue_iid else 'manual'}"
# New:
container_name = f"codify-{task_id}-issue{issue.id}"
```

- [ ] **Step 5: Parse CODIFY_SESSION_ID from container output**

In the result parsing section (line ~963), add session ID extraction:

```python
# After existing marker parsing:
session_match = re.search(r"CODIFY_SESSION_ID:(\S+)", full_logs)
if session_match:
    new_session_id = session_match.group(1)
    if not issue.claude_session_id:
        issue.claude_session_id = new_session_id
        await db.commit()
```

- [ ] **Step 6: Update MR creation to use Issue**

In `_create_mr_if_needed()`, update to read/write MR info from the Issue instead of the Task:

```python
# After MR creation:
issue.merge_request_iid = mr_iid
issue.merge_request_url = mr_url
await db.commit()
```

- [ ] **Step 7: Run worker tests**

Run: `cd backend && python -m pytest tests/unit/test_worker*.py -v`
Fix any broken tests.

- [ ] **Step 8: Commit**

```bash
git add backend/app/core/worker.py
git commit -m "feat: update worker for Issue-based execution and session management"
```

---

## Task 7: Entrypoint Script Changes

**Files:**
- Modify: `deploy/entrypoint.sh`

- [ ] **Step 1: Add CLAUDE_SESSION_ID environment variable handling**

Near the top of the script (after existing env var validation), add:

```bash
# Session resume support (optional)
CLAUDE_SESSION_ID="${CLAUDE_SESSION_ID:-}"
ISSUE_ID="${ISSUE_ID:-}"
```

- [ ] **Step 2: Update Claude CLI invocation for session resume**

Find the main Claude CLI invocation (around line 443) and wrap it with session logic:

```bash
# Build claude command
CLAUDE_BASE_CMD="claude -p --dangerously-skip-permissions --output-format text --max-turns ${CLAUDE_MAX_TURNS} --model ${ANTHROPIC_MODEL}"

if [ -n "${CLAUDE_SESSION_ID}" ]; then
    echo "Resuming Claude session: ${CLAUDE_SESSION_ID}"
    CLAUDE_CMD="${CLAUDE_BASE_CMD} -r ${CLAUDE_SESSION_ID}"
else
    echo "Starting new Claude session"
    CLAUDE_CMD="${CLAUDE_BASE_CMD}"
fi

# Remove --no-session-persistence from the command (delete it if present)
```

- [ ] **Step 3: Add session ID extraction after Claude execution**

After the Claude CLI execution completes, add:

```bash
# Extract session ID from saved session files
touch /tmp/task_start 2>/dev/null || true
SESSION_FILE=$(find /home/codify/.claude/projects/ -name "*.jsonl" -type f 2>/dev/null | sort -t/ -k6 | tail -1)
if [ -n "${SESSION_FILE}" ]; then
    EXTRACTED_SESSION_ID=$(basename "${SESSION_FILE}" .jsonl)
    echo "CODIFY_SESSION_ID:${EXTRACTED_SESSION_ID}"
fi
```

- [ ] **Step 4: Remove --no-session-persistence from all claude invocations**

Find all instances of `--no-session-persistence` in the file (lines 566, 648) and remove them. For the commit message and MR title generation calls, keep `--no-session-persistence` since those are utility calls that shouldn't pollute the main session.

- [ ] **Step 5: Test entrypoint locally**

Run: `bash -n deploy/entrypoint.sh` (syntax check)
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add deploy/entrypoint.sh
git commit -m "feat: add session resume support to worker entrypoint"
```

---

## Task 8: Remove Webhook Routes

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Remove webhook router registration**

In `backend/app/main.py`, comment out or remove the webhook router include:

```python
# Remove or comment out:
# app.include_router(webhook_router, prefix="/api")
```

Keep `backend/app/api/webhook.py` file intact for future use but don't register the routes.

- [ ] **Step 2: Run the app to verify startup**

Run: `cd backend && python -c "from app.main import app; print('OK')"`
Expected: No import errors.

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: disable webhook routes (to be re-implemented later)"
```

---

## Task 9: Update Stats API

**Files:**
- Modify: `backend/app/api/stats.py`

- [ ] **Step 1: Add issue statistics to stats endpoint**

In the `GET /stats` endpoint, add Issue counts:

```python
from app.models import Issue, IssueStatus

# Add to stats response:
issue_total = (await db.execute(select(func.count(Issue.id)))).scalar()
issue_by_status = {}
for status in IssueStatus:
    count = (await db.execute(
        select(func.count(Issue.id)).where(Issue.status == status.value)
    )).scalar()
    issue_by_status[status.value] = count

# Add recent issues
recent_issues_q = (
    select(Issue)
    .order_by(desc(Issue.updated_at))
    .limit(5)
)
recent_issues = (await db.execute(recent_issues_q)).scalars().all()
```

Include in response: `issue_total`, `issue_by_status`, `recent_issues`.

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/stats.py
git commit -m "feat: add issue statistics to stats API"
```

---

## Task 10: Frontend — Types and API Client

**Files:**
- Modify: `frontend/src/api/index.ts`

- [ ] **Step 1: Add Issue types**

Add after the Task interface definition (around line 104):

```typescript
export type IssueStatus = 'open' | 'in_progress' | 'completed' | 'closed'

export interface Issue {
  id: number
  title: string
  description: string | null
  project_id: number
  status: IssueStatus
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
  task_count?: number
  tasks?: Task[]
}

export interface CreateIssueRequest {
  title: string
  description?: string
  project_id: number
  base_branch?: string
  target_branch?: string
}

export interface IssueListResponse {
  items: Issue[]
  total: number
  page: number
  page_size: number
}
```

- [ ] **Step 2: Update Task interface**

Update the Task interface to reflect model changes:

```typescript
export interface Task {
  id: number
  issue_id: number
  project_id: number
  user_prompt: string
  status: TaskStatus
  priority: number
  is_retry: boolean
  retry_source_task_id: number | null
  scheduled_at: string | null
  container_id: string | null
  commit_sha: string | null
  error_message: string | null
  additions: number
  deletions: number
  total_changes: number
  input_tokens: number | null
  output_tokens: number | null
  model_name: string | null
  merge_request_title: string | null
  retry_count: number
  created_at: string
  updated_at: string
  started_at: string | null
  completed_at: string | null
  issue?: {
    id: number
    title: string
    branch_name: string | null
    merge_request_url: string | null
  }
}
```

Remove: `issue_iid`, `issue_id` (old GitLab one), `note_id`, `is_manual`, `branch_name`, `base_branch`, `target_branch`, `merge_request_iid`, `merge_request_url`.

- [ ] **Step 3: Update CreateTaskRequest**

```typescript
export interface CreateTaskRequest {
  issue_id: number
  user_prompt?: string
  priority?: number
  delay_seconds?: number
  scheduled_datetime?: string
}
```

Remove: `project_id`, `branch_name`, `base_branch`, `target_branch`.

- [ ] **Step 4: Add Issue API functions**

```typescript
export function getIssues(params?: {
  status?: string
  project_id?: number
  page?: number
  page_size?: number
}): Promise<AxiosResponse<IssueListResponse>> {
  return api.get('/issues', { params })
}

export function getIssue(id: number): Promise<AxiosResponse<Issue>> {
  return api.get(`/issues/${id}`)
}

export function createIssue(data: CreateIssueRequest): Promise<AxiosResponse<Issue>> {
  return api.post('/issues', data)
}

export function updateIssue(id: number, data: Partial<{
  title: string
  description: string
  status: string
}>): Promise<AxiosResponse<Issue>> {
  return api.patch(`/issues/${id}`, data)
}

export function closeIssue(id: number): Promise<AxiosResponse<Issue>> {
  return api.post(`/issues/${id}/close`)
}

export function deleteIssue(id: number): Promise<AxiosResponse<void>> {
  return api.delete(`/issues/${id}`)
}
```

- [ ] **Step 5: Build to verify types compile**

Run: `cd frontend && npm run build`
Expected: Type errors from components referencing deleted Task fields. These will be fixed in subsequent tasks.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/index.ts
git commit -m "feat: add Issue types and API functions to frontend client"
```

---

## Task 11: Frontend — Router and Navigation

**Files:**
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: Add Issue routes**

In `frontend/src/router/index.ts`, add routes:

```typescript
{
  path: '/issues',
  name: 'issues',
  component: () => import('@/views/IssueList.vue'),
  meta: { requiresAuth: true }
},
{
  path: '/issues/create',
  name: 'create-issue',
  component: () => import('@/views/CreateIssue.vue'),
  meta: { requiresAuth: true }
},
{
  path: '/issues/:id',
  name: 'issue-detail',
  component: () => import('@/views/IssueView.vue'),
  meta: { requiresAuth: true }
},
```

- [ ] **Step 2: Add Issues to navigation menu**

In `frontend/src/App.vue`, in the `menuOptions` computed property (around line 240), add the Issues menu item after Dashboard:

```typescript
{
  label: () => h(RouterLink, { to: '/issues' }, { default: () => t('nav.issues') }),
  key: '/issues',
  icon: renderIcon(ListIcon),  // choose appropriate icon
},
```

Also add a "Create Issue" quick-access item if desired.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/router/index.ts frontend/src/App.vue
git commit -m "feat: add Issue routes and navigation"
```

---

## Task 12: Frontend — i18n Messages

**Files:**
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1: Add English Issue messages**

In `en.ts`, add to the `nav` object:

```typescript
issues: 'Issues',
createIssue: 'Create Issue',
```

Add a new `issue` section:

```typescript
issue: {
  title: 'Issues',
  subtitle: 'Manage your development issues',
  create: 'Create Issue',
  detail: 'Issue Detail',
  list: 'Issue List',
  edit: 'Edit Issue',
  close: 'Close Issue',
  delete: 'Delete Issue',
  noDescription: 'No description',
  taskCount: '{count} tasks',
  createFirstTask: 'Create First Task',
  createTask: 'Create Task',
  retryTask: 'Retry',
  promptPlaceholder: 'Enter task prompt (defaults to issue description)',
  scheduleImmediate: 'Execute Immediately',
  scheduleDelayed: 'Schedule',
  confirmClose: 'Are you sure you want to close this issue?',
  confirmDelete: 'Are you sure you want to delete this issue? This cannot be undone.',
  status: {
    open: 'Open',
    in_progress: 'In Progress',
    completed: 'Completed',
    closed: 'Closed',
  },
  field: {
    title: 'Title',
    description: 'Description',
    project: 'Project',
    baseBranch: 'Base Branch',
    targetBranch: 'Target Branch',
    branch: 'Branch',
    mergeRequest: 'Merge Request',
    sessionId: 'Session ID',
    createdAt: 'Created',
    updatedAt: 'Updated',
  },
},
```

Add to `dashboard` section:

```typescript
recentIssues: 'Recent Issues',
activity: 'Activity',
createIssue: 'New Issue',
issueCount: 'Issues',
```

- [ ] **Step 2: Add Chinese Issue messages**

Mirror the same structure in `zh-CN.ts`:

```typescript
// nav
issues: '需求',
createIssue: '创建需求',

// issue section
issue: {
  title: '需求',
  subtitle: '管理你的开发需求',
  create: '创建需求',
  detail: '需求详情',
  list: '需求列表',
  edit: '编辑需求',
  close: '关闭需求',
  delete: '删除需求',
  noDescription: '暂无描述',
  taskCount: '{count} 个任务',
  createFirstTask: '创建首个任务',
  createTask: '创建任务',
  retryTask: '重试',
  promptPlaceholder: '输入任务提示词（默认使用需求描述）',
  scheduleImmediate: '立即执行',
  scheduleDelayed: '预约执行',
  confirmClose: '确定要关闭此需求吗？',
  confirmDelete: '确定要删除此需求吗？此操作不可撤销。',
  status: {
    open: '待处理',
    in_progress: '进行中',
    completed: '已完成',
    closed: '已关闭',
  },
  field: {
    title: '标题',
    description: '描述',
    project: '项目',
    baseBranch: '基础分支',
    targetBranch: '目标分支',
    branch: '分支',
    mergeRequest: '合并请求',
    sessionId: '会话 ID',
    createdAt: '创建时间',
    updatedAt: '更新时间',
  },
},

// dashboard
recentIssues: '最近的需求',
activity: '活动',
createIssue: '新建需求',
issueCount: '需求数',
```

- [ ] **Step 3: Build to verify i18n**

Run: `cd frontend && npm run build`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: add Issue i18n messages for en and zh-CN"
```

---

## Task 13: Frontend — CreateIssue Page

**Files:**
- Create: `frontend/src/views/CreateIssue.vue`

- [ ] **Step 1: Create CreateIssue.vue**

```vue
<template>
  <div class="create-issue-page">
    <PageHeader :title="t('issue.create')" />
    <n-card>
      <n-form ref="formRef" :model="form" :rules="rules" label-placement="top">
        <n-form-item :label="t('issue.field.project')" path="project_id">
          <n-select
            v-model:value="form.project_id"
            :options="projectOptions"
            :placeholder="t('issue.field.project')"
            filterable
            @update:value="onProjectChange"
          />
        </n-form-item>

        <n-form-item :label="t('issue.field.title')" path="title">
          <n-input v-model:value="form.title" :placeholder="t('issue.field.title')" />
        </n-form-item>

        <n-form-item :label="t('issue.field.description')" path="description">
          <n-input
            v-model:value="form.description"
            type="textarea"
            :rows="6"
            :placeholder="t('issue.field.description')"
          />
        </n-form-item>

        <n-form-item :label="t('issue.field.baseBranch')" path="base_branch">
          <n-select
            v-model:value="form.base_branch"
            :options="branchOptions"
            :placeholder="t('issue.field.baseBranch')"
            filterable
          />
        </n-form-item>

        <n-form-item :label="t('issue.field.targetBranch')" path="target_branch">
          <n-select
            v-model:value="form.target_branch"
            :options="branchOptions"
            :placeholder="t('issue.field.targetBranch')"
            filterable
          />
        </n-form-item>

        <n-form-item>
          <n-button type="primary" :loading="submitting" @click="handleSubmit">
            {{ t('issue.create') }}
          </n-button>
        </n-form-item>
      </n-form>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useMessage } from 'naive-ui'
import { createIssue, getProjects, getBranches } from '@/api'
import PageHeader from '@/components/PageHeader.vue'

const { t } = useI18n()
const router = useRouter()
const message = useMessage()

const formRef = ref()
const submitting = ref(false)
const projectOptions = ref<Array<{ label: string; value: number }>>([])
const branchOptions = ref<Array<{ label: string; value: string }>>([])

const form = ref({
  title: '',
  description: '',
  project_id: null as number | null,
  base_branch: null as string | null,
  target_branch: null as string | null,
})

const rules = {
  title: { required: true, message: t('issue.field.title'), trigger: 'blur' },
  project_id: { required: true, type: 'number', message: t('issue.field.project'), trigger: 'change' },
}

onMounted(async () => {
  try {
    const res = await getProjects()
    projectOptions.value = res.data.map((p: any) => ({
      label: p.path_with_namespace || p.name,
      value: p.id,
    }))
  } catch (e) {
    message.error('Failed to load projects')
  }
})

async function onProjectChange(projectId: number) {
  try {
    const res = await getBranches(projectId)
    branchOptions.value = res.data.map((b: any) => ({
      label: b.name,
      value: b.name,
    }))
  } catch (e) {
    branchOptions.value = []
  }
}

async function handleSubmit() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }

  submitting.value = true
  try {
    const res = await createIssue({
      title: form.value.title,
      description: form.value.description || undefined,
      project_id: form.value.project_id!,
      base_branch: form.value.base_branch || undefined,
      target_branch: form.value.target_branch || undefined,
    })
    message.success(t('issue.create'))
    router.push(`/issues/${res.data.id}`)
  } catch (e: any) {
    message.error(e.response?.data?.detail || 'Failed to create issue')
  } finally {
    submitting.value = false
  }
}
</script>
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/CreateIssue.vue
git commit -m "feat: add CreateIssue page"
```

---

## Task 14: Frontend — IssueList Page

**Files:**
- Create: `frontend/src/views/IssueList.vue`

- [ ] **Step 1: Create IssueList.vue**

```vue
<template>
  <div class="issue-list-page">
    <PageHeader :title="t('issue.list')" :subtitle="t('issue.subtitle')">
      <template #extra>
        <n-button type="primary" @click="$router.push('/issues/create')">
          {{ t('issue.create') }}
        </n-button>
      </template>
    </PageHeader>

    <n-card>
      <div style="margin-bottom: 16px; display: flex; gap: 12px;">
        <n-select
          v-model:value="filters.status"
          :options="statusOptions"
          :placeholder="t('common.status')"
          clearable
          style="width: 160px"
          @update:value="loadIssues"
        />
        <n-select
          v-model:value="filters.project_id"
          :options="projectOptions"
          :placeholder="t('issue.field.project')"
          clearable
          filterable
          style="width: 240px"
          @update:value="loadIssues"
        />
      </div>

      <n-data-table
        :columns="columns"
        :data="issues"
        :loading="loading"
        :pagination="pagination"
        :row-key="(row: any) => row.id"
        @update:page="onPageChange"
      />
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, h, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { NTag, NButton } from 'naive-ui'
import { getIssues, getProjects } from '@/api'
import type { Issue } from '@/api'
import PageHeader from '@/components/PageHeader.vue'

const { t } = useI18n()
const router = useRouter()

const issues = ref<Issue[]>([])
const loading = ref(false)
const total = ref(0)
const currentPage = ref(1)
const pageSize = 20
const projectOptions = ref<Array<{ label: string; value: number }>>([])

const filters = ref({
  status: null as string | null,
  project_id: null as number | null,
})

const statusOptions = computed(() => [
  { label: t('issue.status.open'), value: 'open' },
  { label: t('issue.status.in_progress'), value: 'in_progress' },
  { label: t('issue.status.completed'), value: 'completed' },
  { label: t('issue.status.closed'), value: 'closed' },
])

const statusColorMap: Record<string, string> = {
  open: 'info',
  in_progress: 'warning',
  completed: 'success',
  closed: 'default',
}

const columns = [
  { title: 'ID', key: 'id', width: 60 },
  {
    title: t('issue.field.title'),
    key: 'title',
    render: (row: Issue) =>
      h(
        NButton,
        { text: true, type: 'primary', onClick: () => router.push(`/issues/${row.id}`) },
        { default: () => row.title }
      ),
  },
  {
    title: t('common.status'),
    key: 'status',
    width: 120,
    render: (row: Issue) =>
      h(NTag, { type: statusColorMap[row.status] || 'default', size: 'small' }, {
        default: () => t(`issue.status.${row.status}`),
      }),
  },
  {
    title: t('common.task'),
    key: 'task_count',
    width: 100,
    render: (row: Issue) => `${row.task_count || 0} tasks`,
  },
  {
    title: t('issue.field.createdAt'),
    key: 'created_at',
    width: 160,
    render: (row: Issue) => row.created_at ? new Date(row.created_at).toLocaleString() : '-',
  },
]

const pagination = computed(() => ({
  page: currentPage.value,
  pageSize,
  itemCount: total.value,
}))

async function loadIssues() {
  loading.value = true
  try {
    const res = await getIssues({
      status: filters.value.status || undefined,
      project_id: filters.value.project_id || undefined,
      page: currentPage.value,
      page_size: pageSize,
    })
    issues.value = res.data.items
    total.value = res.data.total
  } catch (e) {
    console.error('Failed to load issues', e)
  } finally {
    loading.value = false
  }
}

function onPageChange(page: number) {
  currentPage.value = page
  loadIssues()
}

onMounted(async () => {
  loadIssues()
  try {
    const res = await getProjects()
    projectOptions.value = res.data.map((p: any) => ({
      label: p.path_with_namespace || p.name,
      value: p.id,
    }))
  } catch (e) {
    // ignore
  }
})
</script>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/IssueList.vue
git commit -m "feat: add IssueList page"
```

---

## Task 15: Frontend — IssueView Page (with embedded Task creation)

**Files:**
- Create: `frontend/src/views/IssueView.vue`

- [ ] **Step 1: Create IssueView.vue**

This is the most complex new component. It contains:
1. Issue metadata header
2. Issue description
3. Task list table
4. Embedded task creation form
5. Action buttons (edit, close, retry tasks)

```vue
<template>
  <div class="issue-view-page" v-if="issue">
    <PageHeader :title="`#${issue.id} ${issue.title}`">
      <template #extra>
        <n-space>
          <n-button @click="showEditModal = true">{{ t('issue.edit') }}</n-button>
          <n-popconfirm @positive-click="handleClose">
            <template #trigger>
              <n-button type="warning" :disabled="issue.status === 'closed'">
                {{ t('issue.close') }}
              </n-button>
            </template>
            {{ t('issue.confirmClose') }}
          </n-popconfirm>
        </n-space>
      </template>
    </PageHeader>

    <!-- Issue Metadata -->
    <n-card style="margin-bottom: 16px">
      <n-descriptions :column="3" label-placement="top">
        <n-descriptions-item :label="t('common.status')">
          <n-tag :type="statusColorMap[issue.status]" size="small">
            {{ t(`issue.status.${issue.status}`) }}
          </n-tag>
        </n-descriptions-item>
        <n-descriptions-item :label="t('issue.field.branch')">
          {{ issue.branch_name || '-' }}
        </n-descriptions-item>
        <n-descriptions-item :label="t('issue.field.mergeRequest')">
          <a v-if="issue.merge_request_url" :href="issue.merge_request_url" target="_blank">
            !{{ issue.merge_request_iid }}
          </a>
          <span v-else>-</span>
        </n-descriptions-item>
        <n-descriptions-item :label="t('issue.field.sessionId')">
          <n-text code v-if="issue.claude_session_id">{{ issue.claude_session_id }}</n-text>
          <span v-else>-</span>
        </n-descriptions-item>
        <n-descriptions-item :label="t('issue.field.createdAt')">
          {{ issue.created_at ? new Date(issue.created_at).toLocaleString() : '-' }}
        </n-descriptions-item>
      </n-descriptions>
    </n-card>

    <!-- Description -->
    <n-card v-if="issue.description" style="margin-bottom: 16px">
      <template #header>{{ t('issue.field.description') }}</template>
      <div style="white-space: pre-wrap;">{{ issue.description }}</div>
    </n-card>

    <!-- Task List -->
    <n-card style="margin-bottom: 16px">
      <template #header>
        {{ t('common.task') }} ({{ issue.tasks?.length || 0 }})
      </template>
      <n-data-table
        :columns="taskColumns"
        :data="issue.tasks || []"
        :row-key="(row: any) => row.id"
      />
    </n-card>

    <!-- Create Task Form -->
    <n-card>
      <template #header>{{ t('issue.createTask') }}</template>
      <n-form :model="taskForm" label-placement="top">
        <n-form-item :label="t('issue.promptPlaceholder')">
          <n-input
            v-model:value="taskForm.user_prompt"
            type="textarea"
            :rows="4"
            :placeholder="issue.description || t('issue.promptPlaceholder')"
          />
        </n-form-item>
        <n-space>
          <n-form-item label="Priority">
            <n-select
              v-model:value="taskForm.priority"
              :options="[
                { label: 'P0', value: 0 },
                { label: 'P1', value: 1 },
                { label: 'P2', value: 2 },
              ]"
              style="width: 100px"
            />
          </n-form-item>
          <n-form-item :label="t('issue.scheduleDelayed')">
            <n-date-picker
              v-model:value="taskForm.scheduled_timestamp"
              type="datetime"
              clearable
            />
          </n-form-item>
        </n-space>
        <n-button type="primary" :loading="creatingTask" @click="handleCreateTask">
          {{ t('issue.createTask') }}
        </n-button>
      </n-form>
    </n-card>

    <!-- Edit Issue Modal -->
    <n-modal v-model:show="showEditModal" preset="dialog" :title="t('issue.edit')">
      <n-form :model="editForm">
        <n-form-item :label="t('issue.field.title')">
          <n-input v-model:value="editForm.title" />
        </n-form-item>
        <n-form-item :label="t('issue.field.description')">
          <n-input v-model:value="editForm.description" type="textarea" :rows="4" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-button @click="showEditModal = false">{{ t('common.cancel') }}</n-button>
        <n-button type="primary" :loading="updatingIssue" @click="handleUpdate">
          {{ t('common.save') }}
        </n-button>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, h, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useMessage, NTag, NButton, NSpace } from 'naive-ui'
import { getIssue, updateIssue, closeIssue, createTask, retryTask } from '@/api'
import type { Issue, Task } from '@/api'
import PageHeader from '@/components/PageHeader.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const message = useMessage()

const issue = ref<Issue | null>(null)
const creatingTask = ref(false)
const updatingIssue = ref(false)
const showEditModal = ref(false)

const statusColorMap: Record<string, string> = {
  open: 'info',
  in_progress: 'warning',
  completed: 'success',
  closed: 'default',
}

const taskStatusColorMap: Record<string, string> = {
  pending: 'default',
  queued: 'info',
  running: 'warning',
  completed: 'success',
  failed: 'error',
  cancelled: 'default',
}

const taskForm = ref({
  user_prompt: '',
  priority: 0,
  scheduled_timestamp: null as number | null,
})

const editForm = ref({ title: '', description: '' })

const taskColumns = [
  { title: 'ID', key: 'id', width: 60 },
  {
    title: t('common.status'),
    key: 'status',
    width: 100,
    render: (row: Task) =>
      h(NTag, { type: taskStatusColorMap[row.status] || 'default', size: 'small' }, {
        default: () => row.status,
      }),
  },
  {
    title: 'Prompt',
    key: 'user_prompt',
    ellipsis: { tooltip: true },
    render: (row: Task) =>
      h(
        NButton,
        { text: true, type: 'primary', onClick: () => router.push(`/tasks/${row.id}`) },
        { default: () => (row.user_prompt || '').substring(0, 80) + ((row.user_prompt || '').length > 80 ? '...' : '') }
      ),
  },
  {
    title: 'Retry',
    key: 'is_retry',
    width: 60,
    render: (row: Task) => row.is_retry ? h(NTag, { size: 'tiny' }, { default: () => 'Retry' }) : '',
  },
  {
    title: t('issue.field.createdAt'),
    key: 'created_at',
    width: 160,
    render: (row: Task) => row.created_at ? new Date(row.created_at).toLocaleString() : '-',
  },
  {
    title: '',
    key: 'actions',
    width: 120,
    render: (row: Task) => {
      const buttons = []
      if (row.status === 'failed' || row.status === 'cancelled') {
        buttons.push(
          h(NButton, { size: 'small', onClick: () => handleRetry(row.id) }, { default: () => t('issue.retryTask') })
        )
      }
      return h(NSpace, {}, { default: () => buttons })
    },
  },
]

async function loadIssue() {
  const id = Number(route.params.id)
  try {
    const res = await getIssue(id)
    issue.value = res.data
    editForm.value = {
      title: res.data.title,
      description: res.data.description || '',
    }
  } catch (e) {
    message.error('Failed to load issue')
  }
}

async function handleCreateTask() {
  if (!issue.value) return
  creatingTask.value = true
  try {
    await createTask({
      issue_id: issue.value.id,
      user_prompt: taskForm.value.user_prompt || undefined,
      priority: taskForm.value.priority,
      scheduled_datetime: taskForm.value.scheduled_timestamp
        ? new Date(taskForm.value.scheduled_timestamp).toISOString()
        : undefined,
    })
    message.success('Task created')
    taskForm.value = { user_prompt: '', priority: 0, scheduled_timestamp: null }
    await loadIssue()
  } catch (e: any) {
    message.error(e.response?.data?.detail || 'Failed to create task')
  } finally {
    creatingTask.value = false
  }
}

async function handleRetry(taskId: number) {
  try {
    await retryTask(taskId)
    message.success('Retry task created')
    await loadIssue()
  } catch (e: any) {
    message.error(e.response?.data?.detail || 'Failed to retry')
  }
}

async function handleUpdate() {
  if (!issue.value) return
  updatingIssue.value = true
  try {
    await updateIssue(issue.value.id, editForm.value)
    message.success('Issue updated')
    showEditModal.value = false
    await loadIssue()
  } catch (e: any) {
    message.error(e.response?.data?.detail || 'Failed to update')
  } finally {
    updatingIssue.value = false
  }
}

async function handleClose() {
  if (!issue.value) return
  try {
    await closeIssue(issue.value.id)
    message.success('Issue closed')
    await loadIssue()
  } catch (e: any) {
    message.error(e.response?.data?.detail || 'Failed to close')
  }
}

onMounted(loadIssue)
</script>
```

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/IssueView.vue
git commit -m "feat: add IssueView page with embedded task creation"
```

---

## Task 16: Frontend — Dashboard Redesign

**Files:**
- Modify: `frontend/src/views/Dashboard.vue`

- [ ] **Step 1: Redesign Dashboard layout**

Replace the current task-centric Dashboard with the Overview design:

1. **Stats cards row**: Issues count, Tasks count, Running count, Completed count + "New Issue" button
2. **Activity section**: Reuse existing HeatmapChart component
3. **Recent Issues section**: Table of 5 most recently updated issues
4. **Running tasks section**: List of currently running/queued tasks

Key changes:
- Import `getIssues` and `getStats` APIs
- Add `recentIssues` ref populated from API
- Keep existing task stats/activity code
- Rearrange template sections to match the new layout order
- Add "New Issue" button in stats area linking to `/issues/create`

- [ ] **Step 2: Build and verify**

Run: `cd frontend && npm run build`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/Dashboard.vue
git commit -m "feat: redesign Dashboard with Issue overview style"
```

---

## Task 17: Frontend — Update TaskView and Task List

**Files:**
- Modify: `frontend/src/views/TaskView.vue`

- [ ] **Step 1: Add Issue link to TaskView metadata**

In the task metadata section of TaskView.vue, add an Issue reference:

```vue
<!-- Add in the metadata descriptions section -->
<n-descriptions-item :label="t('issue.title')" v-if="task.issue">
  <router-link :to="`/issues/${task.issue.id}`">
    #{{ task.issue.id }} {{ task.issue.title }}
  </router-link>
</n-descriptions-item>
```

Remove or guard references to `task.branch_name`, `task.merge_request_url` — these now come from the Issue. Use `task.issue.branch_name` and `task.issue.merge_request_url`.

- [ ] **Step 2: Update task list table (if Dashboard still has one)**

Add an "Issue" column to any remaining task table:

```typescript
{
  title: t('issue.title'),
  key: 'issue',
  render: (row: Task) => row.issue
    ? h(RouterLink, { to: `/issues/${row.issue.id}` }, { default: () => `#${row.issue.id} ${row.issue.title}` })
    : '-',
},
```

- [ ] **Step 3: Build and verify**

Run: `cd frontend && npm run build`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/TaskView.vue
git commit -m "feat: add Issue link to TaskView and task tables"
```

---

## Task 18: Integration Verification

- [ ] **Step 1: Full backend test run**

Run: `cd backend && python -m pytest tests/unit/ -v --tb=short`
Fix any remaining test failures.

- [ ] **Step 2: Full frontend build**

Run: `cd frontend && npm run build`
Fix any remaining TypeScript errors.

- [ ] **Step 3: Verify Docker build**

Run: `docker build -f deploy/Dockerfile.backend -t deploy-backend . && echo "Backend OK"`
Run: `docker build -f deploy/Dockerfile.worker -t codify-worker:latest . && echo "Worker OK"`

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "fix: resolve remaining integration issues from Issue→Task→MR refactoring"
```
