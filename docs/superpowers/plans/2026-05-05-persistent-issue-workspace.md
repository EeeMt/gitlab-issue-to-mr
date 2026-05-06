# Persistent Issue Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add system-level issue execution locking and optional issue-scoped persistent worker workspaces so failed or cancelled tasks can preserve repository state without committing runtime artifacts.

**Architecture:** Introduce a database-backed `IssueExecutionLock` as the authoritative same-issue execution gate, while retaining the scheduler's in-memory `_running_issues` as a fast local cache. Add optional host workspace settings and mount an issue repo directory to `/workspace` plus a task runtime directory to `/tmp/codify-runtime`; entrypoint becomes idempotent and reuses an existing git checkout safely.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Alembic, Docker SDK for Python, Bash worker entrypoint, pytest/unittest.

---

## File Structure

- Create `backend/alembic/versions/035_issue_execution_locks.py`
  - Adds `issue_execution_locks` table.
- Modify `backend/app/models.py`
  - Adds `IssueExecutionLock` ORM model.
- Create `backend/app/core/issue_execution_locks.py`
  - Owns acquire/release/recovery helpers for issue execution locks.
- Modify `backend/app/scheduler.py`
  - Uses DB lock before transitioning tasks to `RUNNING`; releases locks after background completion and crash recovery.
- Modify `backend/app/api/tasks.py`
  - Releases DB lock on cancel after stopping the worker container.
- Modify `backend/app/config.py`
  - Adds persisted/runtime workspace settings.
- Modify `backend/app/api/config_runtime.py`
  - Exposes and validates workspace settings in runtime config.
- Modify `backend/app/core/worker_runtime.py`
  - Adds issue workspace and task runtime volume mounts.
- Modify `deploy/docker-compose.yml`
  - Mounts `/opt/codify-workspaces` into backend for host directory creation when using Docker Engine paths.
- Modify `deploy/offline-bundle/docker-compose.yml`
  - Mirrors production compose workspace archive mount.
- Modify `deploy/entrypoint.worker.sh`
  - Reuses existing `/workspace/.git`; rejects dirty branch mismatch.
- Modify tests:
  - `backend/tests/unit/test_issue_execution_locks.py`
  - `backend/tests/unit/test_scheduler_core.py`
  - `backend/tests/unit/test_worker_coverage.py`
  - `backend/tests/unit/test_worker_coverage_ext.py`
  - `backend/tests/unit/test_config_runtime_api.py`
  - `backend/tests/unit/test_tasks_api.py`

Implementation is split so each task can be committed independently and keeps software working after every task.

---

### Task 1: Add Issue Execution Lock Model And Migration

**Files:**
- Create: `backend/alembic/versions/035_issue_execution_locks.py`
- Modify: `backend/app/models.py`
- Test: `backend/tests/unit/test_issue_execution_locks.py`

- [ ] **Step 1: Add failing model test**

Create `backend/tests/unit/test_issue_execution_locks.py`:

```python
from datetime import datetime

from app.models import Base, IssueExecutionLock


def test_issue_execution_lock_model_mapping():
    table = IssueExecutionLock.__table__

    assert table.name == "issue_execution_locks"
    assert table.c.issue_id.primary_key is True
    assert table.c.task_id.nullable is False
    assert table.c.acquired_at.nullable is False
    assert table.c.heartbeat_at.nullable is True
    assert "issue_execution_locks" in Base.metadata.tables


def test_issue_execution_lock_can_be_instantiated():
    acquired_at = datetime(2026, 5, 5, 12, 0, 0)
    lock = IssueExecutionLock(
        issue_id=42,
        task_id=296,
        acquired_at=acquired_at,
    )

    assert lock.issue_id == 42
    assert lock.task_id == 296
    assert lock.acquired_at == acquired_at
    assert lock.heartbeat_at is None
```

- [ ] **Step 2: Run failing test**

Run:

```bash
python -m pytest backend/tests/unit/test_issue_execution_locks.py -q
```

Expected: FAIL with `ImportError` or `AttributeError` because `IssueExecutionLock` does not exist.

- [ ] **Step 3: Add ORM model**

Modify `backend/app/models.py` imports already include needed SQLAlchemy types. Add this class after `Task`:

```python
class IssueExecutionLock(Base):
    """Authoritative lock ensuring only one task per issue executes at a time."""

    __tablename__ = "issue_execution_locks"

    issue_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("issues.id", ondelete="CASCADE"),
        primary_key=True,
    )
    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
```

- [ ] **Step 4: Add Alembic migration**

Create `backend/alembic/versions/035_issue_execution_locks.py`:

```python
"""add issue execution locks

Revision ID: 035_issue_execution_locks
Revises: 034_add_task_event_archive_state
Create Date: 2026-05-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "035_issue_execution_locks"
down_revision = "034_add_task_event_archive_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "issue_execution_locks",
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("issue_id"),
    )
    op.create_index(
        "ix_issue_execution_locks_task_id",
        "issue_execution_locks",
        ["task_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_issue_execution_locks_task_id", table_name="issue_execution_locks")
    op.drop_table("issue_execution_locks")
```

- [ ] **Step 5: Run model test**

Run:

```bash
python -m pytest backend/tests/unit/test_issue_execution_locks.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/035_issue_execution_locks.py backend/tests/unit/test_issue_execution_locks.py
git commit -m "feat: add issue execution lock model"
```

---

### Task 2: Implement Issue Execution Lock Helpers

**Files:**
- Create: `backend/app/core/issue_execution_locks.py`
- Modify: `backend/tests/unit/test_issue_execution_locks.py`

- [ ] **Step 1: Add failing helper tests**

Append to `backend/tests/unit/test_issue_execution_locks.py`:

```python
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.core.utcnow import utcnow
from app.models import TaskStatus


class IssueExecutionLockHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_acquire_issue_execution_lock_inserts_when_issue_present(self):
        from app.core.issue_execution_locks import acquire_issue_execution_lock

        db = MagicMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()
        task = MagicMock(id=7, issue_id=11)

        acquired = await acquire_issue_execution_lock(db, task)

        self.assertTrue(acquired)
        db.execute.assert_awaited_once()
        db.flush.assert_awaited_once()

    async def test_acquire_issue_execution_lock_returns_true_for_issue_less_task(self):
        from app.core.issue_execution_locks import acquire_issue_execution_lock

        db = MagicMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()
        task = MagicMock(id=7, issue_id=None)

        acquired = await acquire_issue_execution_lock(db, task)

        self.assertTrue(acquired)
        db.execute.assert_not_called()
        db.flush.assert_not_called()

    async def test_acquire_issue_execution_lock_returns_false_on_integrity_error(self):
        from sqlalchemy.exc import IntegrityError
        from app.core.issue_execution_locks import acquire_issue_execution_lock

        db = MagicMock()
        db.execute = AsyncMock(side_effect=IntegrityError("stmt", "params", "orig"))
        db.rollback = AsyncMock()
        task = MagicMock(id=8, issue_id=11)

        acquired = await acquire_issue_execution_lock(db, task)

        self.assertFalse(acquired)
        db.rollback.assert_awaited_once()

    async def test_release_issue_execution_lock_deletes_by_issue_id(self):
        from app.core.issue_execution_locks import release_issue_execution_lock

        db = MagicMock()
        db.execute = AsyncMock()

        await release_issue_execution_lock(db, issue_id=11)

        db.execute.assert_awaited_once()

    async def test_release_issue_execution_lock_skips_none_issue(self):
        from app.core.issue_execution_locks import release_issue_execution_lock

        db = MagicMock()
        db.execute = AsyncMock()

        await release_issue_execution_lock(db, issue_id=None)

        db.execute.assert_not_called()

    async def test_cleanup_inactive_issue_execution_locks_removes_terminal_task_locks(self):
        from app.core.issue_execution_locks import cleanup_inactive_issue_execution_locks

        active_lock = MagicMock(issue_id=1, task_id=101)
        terminal_lock = MagicMock(issue_id=2, task_id=102)
        running_task = MagicMock(id=101, status=TaskStatus.RUNNING)
        failed_task = MagicMock(id=102, status=TaskStatus.FAILED)

        locks_result = MagicMock()
        locks_result.scalars.return_value.all.return_value = [active_lock, terminal_lock]
        task_result = MagicMock()
        task_result.scalars.return_value.all.return_value = [running_task, failed_task]

        db = MagicMock()
        db.execute = AsyncMock(side_effect=[locks_result, task_result])

        removed = await cleanup_inactive_issue_execution_locks(db)

        self.assertEqual(removed, 1)
        self.assertEqual(db.execute.await_count, 3)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest backend/tests/unit/test_issue_execution_locks.py -q
```

Expected: FAIL because `app.core.issue_execution_locks` does not exist.

- [ ] **Step 3: Add helper implementation**

Create `backend/app/core/issue_execution_locks.py`:

```python
"""Database-backed issue execution locks."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utcnow import utcnow
from app.models import IssueExecutionLock, Task, TaskStatus

logger = logging.getLogger(__name__)
_TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}


async def acquire_issue_execution_lock(db: AsyncSession, task: Task) -> bool:
    """Acquire the issue-level execution lock for a task.

    Tasks without an issue_id are independent and do not need this lock.
    """
    if task.issue_id is None:
        return True

    try:
        await db.execute(
            insert(IssueExecutionLock).values(
                issue_id=task.issue_id,
                task_id=task.id,
                acquired_at=utcnow(),
                heartbeat_at=None,
            )
        )
        await db.flush()
        return True
    except IntegrityError:
        await db.rollback()
        logger.info(
            "Issue %s is already locked; task %s will wait",
            task.issue_id,
            task.id,
        )
        return False


async def release_issue_execution_lock(
    db: AsyncSession,
    *,
    issue_id: Optional[int],
) -> None:
    """Release the issue-level execution lock if the task has an issue."""
    if issue_id is None:
        return

    await db.execute(
        delete(IssueExecutionLock).where(IssueExecutionLock.issue_id == issue_id)
    )


async def cleanup_inactive_issue_execution_locks(db: AsyncSession) -> int:
    """Delete locks whose task is missing or terminal.

    This is used by scheduler crash recovery before new work is scheduled.
    """
    result = await db.execute(select(IssueExecutionLock))
    locks = list(result.scalars().all())
    if not locks:
        return 0

    task_ids = [lock.task_id for lock in locks]
    task_result = await db.execute(select(Task).where(Task.id.in_(task_ids)))
    tasks_by_id = {task.id: task for task in task_result.scalars().all()}

    stale_issue_ids = [
        lock.issue_id
        for lock in locks
        if (task := tasks_by_id.get(lock.task_id)) is None
        or task.status in _TERMINAL_STATUSES
    ]
    if not stale_issue_ids:
        return 0

    await db.execute(
        delete(IssueExecutionLock).where(IssueExecutionLock.issue_id.in_(stale_issue_ids))
    )
    return len(stale_issue_ids)
```

- [ ] **Step 4: Run helper tests**

Run:

```bash
python -m pytest backend/tests/unit/test_issue_execution_locks.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/issue_execution_locks.py backend/tests/unit/test_issue_execution_locks.py
git commit -m "feat: add issue execution lock helpers"
```

---

### Task 3: Gate Scheduler Execution With DB Locks

**Files:**
- Modify: `backend/app/scheduler.py`
- Modify: `backend/tests/unit/test_scheduler_core.py`

- [ ] **Step 1: Add failing scheduler lock tests**

Append to `SchedulerExecuteTaskTests` in `backend/tests/unit/test_scheduler_core.py`:

```python
    async def test_execute_task_skips_when_issue_db_lock_is_held(self) -> None:
        """_execute_task should leave queued task untouched when DB issue lock is held."""
        from app.scheduler import Scheduler
        from app.models import TaskStatus

        scheduler = Scheduler()

        task = MagicMock()
        task.id = 17
        task.issue_id = 44
        task.status = TaskStatus.QUEUED

        mock_db = MagicMock()
        mock_db.commit = AsyncMock()

        with patch("app.scheduler.acquire_issue_execution_lock", new=AsyncMock(return_value=False)):
            with patch("app.scheduler.asyncio.create_task") as mock_create_task:
                await scheduler._execute_task(mock_db, task)

        self.assertEqual(task.status, TaskStatus.QUEUED)
        self.assertNotIn(17, scheduler._running_tasks)
        self.assertNotIn(44, scheduler._running_issues)
        mock_db.commit.assert_not_called()
        mock_create_task.assert_not_called()

    async def test_execute_task_releases_db_lock_when_commit_fails_after_acquire(self) -> None:
        """_execute_task should release DB issue lock if marking RUNNING fails."""
        from app.scheduler import Scheduler
        from app.models import TaskStatus

        scheduler = Scheduler()

        task = MagicMock()
        task.id = 18
        task.issue_id = 45
        task.status = TaskStatus.QUEUED

        mock_db = MagicMock()
        mock_db.commit = AsyncMock(side_effect=Exception("commit failed"))

        with patch("app.scheduler.acquire_issue_execution_lock", new=AsyncMock(return_value=True)):
            with patch("app.scheduler.release_issue_execution_lock", new=AsyncMock()) as mock_release:
                await scheduler._execute_task(mock_db, task)

        mock_release.assert_awaited_once_with(mock_db, issue_id=45)
        self.assertEqual(task.status, TaskStatus.FAILED)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest backend/tests/unit/test_scheduler_core.py::SchedulerExecuteTaskTests -q
```

Expected: FAIL because scheduler does not import/use DB lock helpers.

- [ ] **Step 3: Modify scheduler imports**

In `backend/app/scheduler.py`, add:

```python
from app.core.issue_execution_locks import (
    acquire_issue_execution_lock,
    cleanup_inactive_issue_execution_locks,
    release_issue_execution_lock,
)
```

- [ ] **Step 4: Update `_execute_task` lock flow**

Replace the start of `_execute_task` body in `backend/app/scheduler.py` with this sequence:

```python
        lock_acquired = await acquire_issue_execution_lock(db, task)
        if not lock_acquired:
            logger.debug("Issue %s locked; task %s remains queued", task.issue_id, task.id)
            return

        self._running_tasks.add(task.id)
        if task.issue_id is not None:
            self._running_issues.add(task.issue_id)

        try:
```

Inside the `UsageLimitExceeded` branch, before removing in-memory tracking, add:

```python
                    await release_issue_execution_lock(db, issue_id=task.issue_id)
```

Inside the `except Exception as e:` handler, before `await db.commit()`, add:

```python
            await release_issue_execution_lock(db, issue_id=task.issue_id)
```

- [ ] **Step 5: Release lock in background finally**

In `_run_task_background` finally block, after loading `task` and before `_maybe_complete_issue`, add:

```python
                        await release_issue_execution_lock(db, issue_id=task.issue_id)
```

In `_resume_task_background` finally block, add the same call before `_maybe_complete_issue`.

- [ ] **Step 6: Run scheduler tests**

Run:

```bash
python -m pytest backend/tests/unit/test_scheduler_core.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/scheduler.py backend/tests/unit/test_scheduler_core.py
git commit -m "feat: gate scheduler with issue execution locks"
```

---

### Task 4: Crash Recovery And Cancel Release Locks

**Files:**
- Modify: `backend/app/scheduler.py`
- Modify: `backend/app/api/tasks.py`
- Modify: `backend/tests/unit/test_scheduler_core.py`
- Modify: `backend/tests/unit/test_tasks_api.py`

- [ ] **Step 1: Add crash recovery cleanup test**

Append to a crash recovery test class in `backend/tests/unit/test_scheduler_core.py`:

```python
    async def test_crash_recovery_cleans_inactive_issue_execution_locks(self) -> None:
        """_crash_recovery should clear stale DB locks before marking stuck tasks."""
        from app.scheduler import Scheduler

        scheduler = Scheduler()
        mock_db = MagicMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = empty_result

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_db)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scheduler.AsyncSessionLocal", return_value=mock_context):
            with patch("app.scheduler.cleanup_inactive_issue_execution_locks", new=AsyncMock(return_value=2)) as mock_cleanup:
                with patch("app.scheduler.get_docker_client") as mock_docker:
                    mock_docker.side_effect = Exception("docker unavailable")
                    await scheduler._crash_recovery()

        mock_cleanup.assert_awaited_once_with(mock_db)
        mock_db.commit.assert_awaited_once()
```

- [ ] **Step 2: Add cancel release test**

Find the cancel tests in `backend/tests/unit/test_tasks_api.py` and add:

```python
    def test_cancel_task_releases_issue_execution_lock(self) -> None:
        """POST /cancel should release the DB issue execution lock."""
        task = MagicMock()
        task.id = 2
        task.project_id = 1
        task.issue_id = 33
        task.status = TaskStatus.RUNNING
        task.scheduled_at = None

        client, app = self._get_client(task)

        with patch("app.api.task_operations.notify_task_cancelled", new=AsyncMock()):
            with patch("app.core.task_helpers._require_task_operator", return_value=None):
                with patch("app.api.tasks.release_issue_execution_lock", new=AsyncMock()) as mock_release:
                    response = client.post("/api/tasks/2/cancel")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        mock_release.assert_awaited_once()
        self.assertEqual(mock_release.await_args.kwargs["issue_id"], 33)
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
python -m pytest backend/tests/unit/test_scheduler_core.py backend/tests/unit/test_tasks_api.py -q
```

Expected: FAIL because crash recovery and cancel do not call lock cleanup/release.

- [ ] **Step 4: Update scheduler crash recovery**

In `backend/app/scheduler.py`, inside `_crash_recovery` after opening the DB session and before selecting stuck `RUNNING` tasks, add:

```python
            removed_locks = await cleanup_inactive_issue_execution_locks(db)
            if removed_locks:
                logger.warning("Cleaned up %s inactive issue execution lock(s)", removed_locks)
```

When marking stuck tasks failed in `_crash_recovery`, add:

```python
                await release_issue_execution_lock(db, issue_id=task.issue_id)
```

- [ ] **Step 5: Update cancel API**

In `backend/app/api/tasks.py`, add import:

```python
from app.core.issue_execution_locks import release_issue_execution_lock
```

In `cancel_task`, after `await db.refresh(task)` and before Docker container stop, add:

```python
    await release_issue_execution_lock(db, issue_id=task.issue_id)
    await db.commit()
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
python -m pytest backend/tests/unit/test_scheduler_core.py backend/tests/unit/test_tasks_api.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/scheduler.py backend/app/api/tasks.py backend/tests/unit/test_scheduler_core.py backend/tests/unit/test_tasks_api.py
git commit -m "fix: release issue execution locks on recovery and cancel"
```

---

### Task 5: Add Workspace Runtime Configuration

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/api/config_runtime.py`
- Test: `backend/tests/unit/test_config_runtime_api.py`

- [ ] **Step 1: Add failing config tests**

Add these methods to `ConfigRuntimeAPITests` in `backend/tests/unit/test_config_runtime_api.py`:

```python
    def test_get_runtime_config_includes_worker_workspace_settings(self):
        """GET /config/runtime should expose persistent workspace settings."""
        response = self.client.get("/api/config/runtime")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("worker_workspace_host_path", data)
        self.assertIn("worker_workspace_retention_days", data)
        self.assertIn("worker_failed_workspace_retention_days", data)

    def test_serialize_runtime_config_includes_worker_workspace_settings(self):
        from app.api.config_runtime import _serialize_runtime_config
        from app.config import Settings

        settings = Settings(
            worker_workspace_host_path="/opt/codify-workspaces",
            worker_workspace_retention_days=14,
            worker_failed_workspace_retention_days=30,
        )

        result = _serialize_runtime_config(settings)

        self.assertEqual(result.worker_workspace_host_path, "/opt/codify-workspaces")
        self.assertEqual(result.worker_workspace_retention_days, 14)
        self.assertEqual(result.worker_failed_workspace_retention_days, 30)

    def test_validate_worker_workspace_retention_days_bounds(self):
        from fastapi import HTTPException
        from app.api.config_runtime import _validate_config_value

        self.assertEqual(_validate_config_value("worker_workspace_retention_days", 14), 14)
        with self.assertRaises(HTTPException) as ctx:
            _validate_config_value("worker_workspace_retention_days", -1)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_validate_worker_workspace_host_path_allows_empty_or_absolute(self):
        from fastapi import HTTPException
        from app.api.config_runtime import _validate_config_value

        self.assertEqual(_validate_config_value("worker_workspace_host_path", ""), "")
        self.assertEqual(
            _validate_config_value("worker_workspace_host_path", "/opt/codify-workspaces"),
            "/opt/codify-workspaces",
        )
        with self.assertRaises(HTTPException) as ctx:
            _validate_config_value("worker_workspace_host_path", "relative/path")
        self.assertEqual(ctx.exception.status_code, 400)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest backend/tests/unit/test_config_runtime_api.py -q
```

Expected: FAIL because settings/response fields do not exist.

- [ ] **Step 3: Add settings**

In `backend/app/config.py`, add to `PERSISTED_CONFIG_TYPES`:

```python
    "worker_workspace_host_path": str,
    "worker_workspace_retention_days": int,
    "worker_failed_workspace_retention_days": int,
```

In `Settings`, near worker configuration fields, add:

```python
    worker_workspace_host_path: str = Field(default="")
    worker_workspace_retention_days: int = Field(default=14)
    worker_failed_workspace_retention_days: int = Field(default=30)
```

- [ ] **Step 4: Expose runtime config fields**

In `backend/app/api/config_runtime.py`, add fields to `RuntimeConfigSection`:

```python
    worker_workspace_host_path: str
    worker_workspace_retention_days: int
    worker_failed_workspace_retention_days: int
```

Add optional fields to `RuntimeConfigUpdate`:

```python
    worker_workspace_host_path: Optional[str] = None
    worker_workspace_retention_days: Optional[int] = None
    worker_failed_workspace_retention_days: Optional[int] = None
```

In `_serialize_runtime_config`, add:

```python
        worker_workspace_host_path=settings.worker_workspace_host_path,
        worker_workspace_retention_days=settings.worker_workspace_retention_days,
        worker_failed_workspace_retention_days=settings.worker_failed_workspace_retention_days,
```

In `_validate_config_value`, add:

```python
    if key == "worker_workspace_host_path":
        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="worker_workspace_host_path must be a string",
            )
        stripped = value.strip()
        if stripped and not stripped.startswith("/"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="worker_workspace_host_path must be empty or an absolute path",
            )
        return stripped

    if key in {"worker_workspace_retention_days", "worker_failed_workspace_retention_days"}:
        if not isinstance(value, int) or value < 0 or value > 365:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key} must be between 0 and 365 days",
            )
        return value
```

- [ ] **Step 5: Run runtime config tests**

Run:

```bash
python -m pytest backend/tests/unit/test_config_runtime_api.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/app/api/config_runtime.py backend/tests
git commit -m "feat: add worker workspace runtime config"
```

---

### Task 6: Add Persistent Workspace Volume Mounts

**Files:**
- Modify: `backend/app/core/worker_runtime.py`
- Modify: `backend/tests/unit/test_worker_coverage.py`

- [ ] **Step 1: Add failing volume tests**

Append to `TestBuildContainerVolumes` in `backend/tests/unit/test_worker_coverage.py`:

```python
    def test_issue_workspace_and_task_runtime_volumes_enabled(self):
        """Persistent workspace mounts issue repo and task runtime outside repo."""
        settings = _make_settings(worker_workspace_host_path="/opt/codify-workspaces")
        worker = _make_worker()
        issue = MagicMock()
        issue.project_id = 123
        issue.id = 456
        task = MagicMock()
        task.id = 789

        volumes = worker._build_container_volumes(settings, issue, task=task)

        repo_path = "/opt/codify-workspaces/project-123/issue-456/repo"
        runtime_path = "/opt/codify-workspaces/project-123/issue-456/runtime/task-789"
        self.assertEqual(volumes[repo_path]["bind"], "/workspace")
        self.assertEqual(volumes[repo_path]["mode"], "rw")
        self.assertEqual(volumes[runtime_path]["bind"], "/tmp/codify-runtime")
        self.assertEqual(volumes[runtime_path]["mode"], "rw")

    def test_issue_workspace_volumes_disabled_when_setting_empty(self):
        settings = _make_settings(worker_workspace_host_path="")
        worker = _make_worker()
        issue = MagicMock(project_id=123, id=456)
        task = MagicMock(id=789)

        volumes = worker._build_container_volumes(settings, issue, task=task)

        self.assertNotIn("/workspace", [v["bind"] for v in volumes.values()])
        self.assertNotIn("/tmp/codify-runtime", [v["bind"] for v in volumes.values()])
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
python -m pytest backend/tests/unit/test_worker_coverage.py::TestBuildContainerVolumes -q
```

Expected: FAIL because `_build_container_volumes` does not accept `task`.

- [ ] **Step 3: Modify volume helper signature**

In `backend/app/core/worker_runtime.py`, change:

```python
def build_container_volumes(settings: Any, issue: Optional[Issue] = None) -> dict:
```

to:

```python
def build_container_volumes(settings: Any, issue: Optional[Issue] = None, *, task: Optional[Task] = None) -> dict:
```

Add constants near existing Maven constants:

```python
_WORKSPACE_CONTAINER_PATH = "/workspace"
_RUNTIME_CONTAINER_PATH = "/tmp/codify-runtime"
```

Before session storage handling, add:

```python
    workspace_root = getattr(settings, "worker_workspace_host_path", "") or ""
    if workspace_root and issue is not None and task is not None:
        project_id = getattr(issue, "project_id", None)
        issue_id = getattr(issue, "id", None)
        task_id = getattr(task, "id", None)
        if project_id is not None and issue_id is not None and task_id is not None:
            issue_root = os.path.join(
                workspace_root,
                f"project-{project_id}",
                f"issue-{issue_id}",
            )
            repo_path = os.path.join(issue_root, "repo")
            runtime_path = os.path.join(issue_root, "runtime", f"task-{task_id}")
            os.makedirs(repo_path, exist_ok=True)
            os.makedirs(runtime_path, exist_ok=True)
            volumes[repo_path] = {"bind": _WORKSPACE_CONTAINER_PATH, "mode": "rw"}
            volumes[runtime_path] = {"bind": _RUNTIME_CONTAINER_PATH, "mode": "rw"}
```

- [ ] **Step 4: Pass task from lifecycle**

In `backend/app/core/worker_task_lifecycle.py`, change:

```python
    volumes = worker._build_container_volumes(settings, issue)
```

to:

```python
    volumes = worker._build_container_volumes(settings, issue, task=task)
```

In `backend/app/core/worker.py`, update the wrapper:

```python
'_build_container_volumes': lambda *args, **kwargs: build_container_volumes(*args, **kwargs),
```

This wrapper already forwards args; no change is needed if it already matches exactly.

- [ ] **Step 5: Run volume tests**

Run:

```bash
python -m pytest backend/tests/unit/test_worker_coverage.py::TestBuildContainerVolumes -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/worker_runtime.py backend/app/core/worker_task_lifecycle.py backend/tests/unit/test_worker_coverage.py
git commit -m "feat: mount persistent issue workspaces"
```

---

### Task 7: Make Entrypoint Reuse Existing Workspace Safely

**Files:**
- Modify: `deploy/entrypoint.worker.sh`
- Modify: `backend/tests/unit/test_worker_coverage.py`

- [ ] **Step 1: Add failing entrypoint text test**

Append to `TestEntrypointCommitAttribution` in `backend/tests/unit/test_worker_coverage.py`:

```python
    def test_entrypoint_reuses_existing_git_workspace_safely(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = script.read_text()

        self.assertIn('if [ -d /workspace/.git ]; then', content)
        self.assertIn('git remote set-url origin "${GIT_REPO_URL}"', content)
        self.assertIn('git fetch origin', content)
        self.assertIn('WORKSPACE_CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD', content)
        self.assertIn('Workspace has uncommitted changes on branch', content)
        self.assertIn('git clone "${GIT_REPO_URL}" /workspace', content)
```

- [ ] **Step 2: Run failing test**

Run:

```bash
python -m pytest backend/tests/unit/test_worker_coverage.py::TestEntrypointCommitAttribution -q
```

Expected: FAIL because entrypoint always clones.

- [ ] **Step 3: Replace clone block**

In `deploy/entrypoint.worker.sh`, replace:

```bash
# Clone repository with authentication
echo "Cloning repository..."
git clone "${GIT_REPO_URL}" /workspace
cd /workspace
```

with:

```bash
# Clone or reuse repository with authentication.
if [ -d /workspace/.git ]; then
    echo "Reusing existing workspace..."
    cd /workspace
    git remote set-url origin "${GIT_REPO_URL}"
    git fetch origin
else
    echo "Cloning repository..."
    git clone "${GIT_REPO_URL}" /workspace
    cd /workspace
fi
```

- [ ] **Step 4: Add branch mismatch guard**

After git config and before `echo "Checking out branch: ${BRANCH_NAME}"`, add:

```bash
WORKSPACE_CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
if [ -n "${WORKSPACE_CURRENT_BRANCH}" ] && [ "${WORKSPACE_CURRENT_BRANCH}" != "HEAD" ] && [ "${WORKSPACE_CURRENT_BRANCH}" != "${BRANCH_NAME}" ]; then
    WORKSPACE_DIRTY=$(git status --porcelain || true)
    if [ -n "${WORKSPACE_DIRTY}" ]; then
        echo "ERROR: Workspace has uncommitted changes on branch ${WORKSPACE_CURRENT_BRANCH}, cannot switch to ${BRANCH_NAME}"
        exit 1
    fi
fi
```

- [ ] **Step 5: Avoid duplicate fetch noise**

The script later runs `git fetch origin` before branch checkout. Leave it in place. It is harmless and ensures fresh refs even for newly cloned repositories.

- [ ] **Step 6: Run syntax and entrypoint tests**

Run:

```bash
bash -n deploy/entrypoint.worker.sh
python -m pytest backend/tests/unit/test_worker_coverage.py::TestEntrypointCommitAttribution -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add deploy/entrypoint.worker.sh backend/tests/unit/test_worker_coverage.py
git commit -m "feat: reuse persistent worker workspace"
```

---

### Task 8: Compose Mounts For Workspace Root

**Files:**
- Modify: `deploy/docker-compose.yml`
- Modify: `deploy/offline-bundle/docker-compose.yml`
- Test: `backend/tests/unit/test_worker_coverage.py`

- [ ] **Step 1: Add failing compose text test**

Add to `backend/tests/unit/test_worker_coverage.py`:

```python
class TestDeployComposeWorkspaceMounts(unittest.TestCase):
    def test_backend_compose_mounts_workspace_root(self):
        compose = Path(__file__).resolve().parents[3] / "deploy" / "docker-compose.yml"
        content = compose.read_text()

        self.assertIn("/opt/codify-workspaces:/opt/codify-workspaces", content)

    def test_offline_compose_mounts_workspace_root(self):
        compose = Path(__file__).resolve().parents[3] / "deploy" / "offline-bundle" / "docker-compose.yml"
        content = compose.read_text()

        self.assertIn("/opt/codify-workspaces:/opt/codify-workspaces", content)
```

- [ ] **Step 2: Run failing test**

Run:

```bash
python -m pytest backend/tests/unit/test_worker_coverage.py::TestDeployComposeWorkspaceMounts -q
```

Expected: FAIL because compose files do not mount workspace root.

- [ ] **Step 3: Update compose files**

In both compose files, under backend service volumes near existing `/opt/codify-archives`, add:

```yaml
      - /opt/codify-workspaces:/opt/codify-workspaces
```

Do not mount this into the worker service directly. The backend creates Docker containers using host paths, so the path must exist on the Docker host and be visible to the Docker Engine.

- [ ] **Step 4: Run compose tests**

Run:

```bash
python -m pytest backend/tests/unit/test_worker_coverage.py::TestDeployComposeWorkspaceMounts -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add deploy/docker-compose.yml deploy/offline-bundle/docker-compose.yml backend/tests/unit/test_worker_coverage.py
git commit -m "deploy: mount worker workspace root"
```

---

### Task 9: Add Workspace Cleanup Helpers

**Files:**
- Create: `backend/app/core/worker_workspace.py`
- Test: `backend/tests/unit/test_worker_workspace.py`

- [ ] **Step 1: Add failing workspace helper tests**

Create `backend/tests/unit/test_worker_workspace.py`:

```python
from pathlib import Path
from types import SimpleNamespace

from app.core.worker_workspace import (
    build_issue_workspace_paths,
    remove_issue_workspace,
)


def test_build_issue_workspace_paths():
    settings = SimpleNamespace(worker_workspace_host_path="/opt/codify-workspaces")
    issue = SimpleNamespace(id=456, project_id=123)
    task = SimpleNamespace(id=789)

    paths = build_issue_workspace_paths(settings, issue, task)

    assert paths.issue_root == "/opt/codify-workspaces/project-123/issue-456"
    assert paths.repo_path == "/opt/codify-workspaces/project-123/issue-456/repo"
    assert paths.runtime_path == "/opt/codify-workspaces/project-123/issue-456/runtime/task-789"


def test_build_issue_workspace_paths_disabled_when_root_empty():
    settings = SimpleNamespace(worker_workspace_host_path="")
    issue = SimpleNamespace(id=456, project_id=123)
    task = SimpleNamespace(id=789)

    assert build_issue_workspace_paths(settings, issue, task) is None


def test_remove_issue_workspace_deletes_directory(tmp_path):
    issue_root = tmp_path / "project-1" / "issue-2"
    repo = issue_root / "repo"
    repo.mkdir(parents=True)
    (repo / "file.txt").write_text("data", encoding="utf-8")

    removed = remove_issue_workspace(str(issue_root))

    assert removed is True
    assert not issue_root.exists()


def test_remove_issue_workspace_returns_false_for_missing_path(tmp_path):
    assert remove_issue_workspace(str(tmp_path / "missing")) is False
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
python -m pytest backend/tests/unit/test_worker_workspace.py -q
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement helper**

Create `backend/app/core/worker_workspace.py`:

```python
"""Helpers for persistent worker workspace paths and cleanup."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class IssueWorkspacePaths:
    issue_root: str
    repo_path: str
    runtime_path: str


def build_issue_workspace_paths(settings: Any, issue: Any, task: Any) -> IssueWorkspacePaths | None:
    root = (getattr(settings, "worker_workspace_host_path", "") or "").strip()
    if not root:
        return None

    issue_root = os.path.join(
        root,
        f"project-{issue.project_id}",
        f"issue-{issue.id}",
    )
    return IssueWorkspacePaths(
        issue_root=issue_root,
        repo_path=os.path.join(issue_root, "repo"),
        runtime_path=os.path.join(issue_root, "runtime", f"task-{task.id}"),
    )


def remove_issue_workspace(issue_root: str) -> bool:
    if not issue_root or not os.path.exists(issue_root):
        return False
    shutil.rmtree(issue_root)
    return True
```

- [ ] **Step 4: Refactor volume helper to use shared path helper**

In `backend/app/core/worker_runtime.py`, import:

```python
from app.core.worker_workspace import build_issue_workspace_paths
```

Replace inline workspace path construction from Task 6 with:

```python
    workspace_paths = (
        build_issue_workspace_paths(settings, issue, task)
        if issue is not None and task is not None
        else None
    )
    if workspace_paths is not None:
        os.makedirs(workspace_paths.repo_path, exist_ok=True)
        os.makedirs(workspace_paths.runtime_path, exist_ok=True)
        volumes[workspace_paths.repo_path] = {"bind": _WORKSPACE_CONTAINER_PATH, "mode": "rw"}
        volumes[workspace_paths.runtime_path] = {"bind": _RUNTIME_CONTAINER_PATH, "mode": "rw"}
```

- [ ] **Step 5: Run helper and volume tests**

Run:

```bash
python -m pytest backend/tests/unit/test_worker_workspace.py backend/tests/unit/test_worker_coverage.py::TestBuildContainerVolumes -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/worker_workspace.py backend/app/core/worker_runtime.py backend/tests/unit/test_worker_workspace.py
git commit -m "feat: add worker workspace helpers"
```

---

### Task 10: Add Workspace Status And Cleanup API

**Files:**
- Modify: `backend/app/api/tasks.py`
- Test: `backend/tests/unit/test_tasks_api.py`

- [ ] **Step 1: Add failing API tests**

Add tests in `backend/tests/unit/test_tasks_api.py` matching existing API fixture style:

```python
@pytest.mark.asyncio
async def test_get_task_workspace_status_returns_disabled_when_not_configured(client, db_session, monkeypatch):
    from app.api import tasks as tasks_api
    from app.models import Task, TaskStatus

    task = Task(issue_id=1, project_id=100, user_prompt="x", status=TaskStatus.FAILED)
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    monkeypatch.setattr(
        tasks_api,
        "get_effective_settings",
        lambda: type("Settings", (), {"worker_workspace_host_path": ""})(),
    )

    response = await client.get(f"/api/tasks/{task.id}/workspace")

    assert response.status_code == 200
    assert response.json()["enabled"] is False


@pytest.mark.asyncio
async def test_delete_task_workspace_calls_remove_helper(client, db_session, monkeypatch):
    from app.api import tasks as tasks_api
    from app.models import Task, TaskStatus

    task = Task(issue_id=1, project_id=100, user_prompt="x", status=TaskStatus.FAILED)
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    monkeypatch.setattr(
        tasks_api,
        "get_effective_settings",
        lambda: type("Settings", (), {"worker_workspace_host_path": "/opt/codify-workspaces"})(),
    )
    monkeypatch.setattr(
        tasks_api,
        "build_issue_workspace_paths",
        lambda settings, issue, task: type("Paths", (), {
            "issue_root": "/opt/codify-workspaces/project-100/issue-1",
            "repo_path": "/opt/codify-workspaces/project-100/issue-1/repo",
            "runtime_path": "/opt/codify-workspaces/project-100/issue-1/runtime/task-1",
        })(),
    )

    called = {}

    def fake_remove(path):
        called["path"] = path
        return True

    monkeypatch.setattr(tasks_api, "remove_issue_workspace", fake_remove)

    response = await client.delete(f"/api/tasks/{task.id}/workspace")

    assert response.status_code == 200
    assert called["path"] == "/opt/codify-workspaces/project-100/issue-1"
    assert response.json()["removed"] is True
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
python -m pytest backend/tests/unit/test_tasks_api.py -q
```

Expected: FAIL because endpoints do not exist.

- [ ] **Step 3: Add imports**

In `backend/app/api/tasks.py`, add:

```python
from app.config import get_effective_settings
from app.core.worker_workspace import build_issue_workspace_paths, remove_issue_workspace
```

If `get_effective_settings` is already imported under a different name, reuse that import.

- [ ] **Step 4: Add workspace status endpoint**

In `backend/app/api/tasks.py`, before archive endpoints, add:

```python
@router.get("/tasks/{task_id}/workspace")
async def get_task_workspace_status(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    task = await get_task_with_access_check(task_id, db, access_scope, current_user)
    if task.issue is None and task.issue_id is not None:
        task.issue = await db.get(Issue, task.issue_id)

    settings = get_effective_settings()
    if not task.issue:
        return {"enabled": False, "reason": "task has no issue"}

    paths = build_issue_workspace_paths(settings, task.issue, task)
    if paths is None:
        return {"enabled": False, "reason": "worker workspace host path is not configured"}

    repo_exists = os.path.isdir(paths.repo_path)
    return {
        "enabled": True,
        "issue_root": paths.issue_root,
        "repo_path": paths.repo_path,
        "runtime_path": paths.runtime_path,
        "repo_exists": repo_exists,
    }
```

- [ ] **Step 5: Add cleanup endpoint**

In `backend/app/api/tasks.py`, add:

```python
@router.delete("/tasks/{task_id}/workspace")
async def delete_task_workspace(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    task = await get_task_with_access_check(task_id, db, access_scope, current_user)
    if task.status == TaskStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Cannot delete workspace while task is running")
    if task.issue is None and task.issue_id is not None:
        task.issue = await db.get(Issue, task.issue_id)
    if not task.issue:
        raise HTTPException(status_code=404, detail="Workspace not available for task without issue")

    settings = get_effective_settings()
    paths = build_issue_workspace_paths(settings, task.issue, task)
    if paths is None:
        raise HTTPException(status_code=404, detail="Worker workspace host path is not configured")

    removed = remove_issue_workspace(paths.issue_root)
    return {"removed": removed, "issue_root": paths.issue_root}
```

- [ ] **Step 6: Run API tests**

Run:

```bash
python -m pytest backend/tests/unit/test_tasks_api.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/tasks.py backend/tests/unit/test_tasks_api.py
git commit -m "feat: expose worker workspace controls"
```

---

### Task 11: Add Workspace TTL Cleanup

**Files:**
- Modify: `backend/app/core/worker_workspace.py`
- Modify: `backend/app/scheduler.py`
- Test: `backend/tests/unit/test_worker_workspace.py`
- Test: `backend/tests/unit/test_scheduler_core.py`

- [ ] **Step 1: Add cleanup helper tests**

Append to `backend/tests/unit/test_worker_workspace.py`:

```python
from datetime import timedelta
import os
import time


def test_cleanup_expired_workspaces_removes_old_issue_dirs(tmp_path):
    from app.core.worker_workspace import cleanup_expired_workspaces

    old_issue = tmp_path / "project-1" / "issue-1"
    old_issue.mkdir(parents=True)
    old_mtime = time.time() - (40 * 24 * 60 * 60)
    os.utime(old_issue, (old_mtime, old_mtime))

    removed = cleanup_expired_workspaces(str(tmp_path), retention_days=30)

    assert removed == 1
    assert not old_issue.exists()


def test_cleanup_expired_workspaces_keeps_recent_issue_dirs(tmp_path):
    from app.core.worker_workspace import cleanup_expired_workspaces

    recent_issue = tmp_path / "project-1" / "issue-2"
    recent_issue.mkdir(parents=True)

    removed = cleanup_expired_workspaces(str(tmp_path), retention_days=30)

    assert removed == 0
    assert recent_issue.exists()
```

- [ ] **Step 2: Run failing helper tests**

Run:

```bash
python -m pytest backend/tests/unit/test_worker_workspace.py -q
```

Expected: FAIL because `cleanup_expired_workspaces` does not exist.

- [ ] **Step 3: Implement cleanup helper**

In `backend/app/core/worker_workspace.py`, add:

```python
import time


def cleanup_expired_workspaces(root: str, *, retention_days: int) -> int:
    if not root or retention_days <= 0 or not os.path.isdir(root):
        return 0

    cutoff = time.time() - (retention_days * 24 * 60 * 60)
    removed = 0

    for project_name in os.listdir(root):
        project_path = os.path.join(root, project_name)
        if not os.path.isdir(project_path):
            continue
        for issue_name in os.listdir(project_path):
            issue_path = os.path.join(project_path, issue_name)
            if not os.path.isdir(issue_path):
                continue
            if os.path.getmtime(issue_path) < cutoff:
                shutil.rmtree(issue_path)
                removed += 1

    return removed
```

- [ ] **Step 4: Add scheduler cleanup invocation test**

Add to `SchedulerCleanupWithDeletesTests` in `backend/tests/unit/test_scheduler_core.py`:

```python
    async def test_maybe_cleanup_workspaces_invokes_helper_when_configured(self) -> None:
        from app.scheduler import Scheduler
        from types import SimpleNamespace

        scheduler = Scheduler()
        scheduler._last_workspace_cleanup_at = 0.0
        mock_db = MagicMock()

        settings = SimpleNamespace(
            worker_workspace_host_path="/opt/codify-workspaces",
            worker_workspace_retention_days=14,
        )

        with patch("app.scheduler.get_settings", return_value=settings):
            with patch("app.scheduler.cleanup_expired_workspaces", return_value=3) as mock_cleanup:
                await scheduler._maybe_cleanup_workspaces(mock_db)

        mock_cleanup.assert_called_once_with("/opt/codify-workspaces", retention_days=14)
```

- [ ] **Step 5: Implement scheduler periodic cleanup**

In `backend/app/scheduler.py`, import:

```python
from app.core.worker_workspace import cleanup_expired_workspaces
```

Add constant near session cleanup interval:

```python
_WORKSPACE_CLEANUP_INTERVAL_SECONDS = 21600
```

In `Scheduler.__init__`, add:

```python
        self._last_workspace_cleanup_at = 0.0
```

In `_run_cycle`, after `_maybe_cleanup_sessions(db)`, add:

```python
            await self._maybe_cleanup_workspaces(db)
```

Add method:

```python
    async def _maybe_cleanup_workspaces(self, db: AsyncSession) -> None:
        now = time.time()
        if now - self._last_workspace_cleanup_at < _WORKSPACE_CLEANUP_INTERVAL_SECONDS:
            return

        settings = get_settings()
        root = (getattr(settings, "worker_workspace_host_path", "") or "").strip()
        if not root:
            self._last_workspace_cleanup_at = now
            return

        removed = await asyncio.to_thread(
            cleanup_expired_workspaces,
            root,
            retention_days=settings.worker_workspace_retention_days,
        )
        if removed:
            logger.info("Cleaned up %s expired worker workspace(s)", removed)
        self._last_workspace_cleanup_at = now
```

- [ ] **Step 6: Run cleanup tests**

Run:

```bash
python -m pytest backend/tests/unit/test_worker_workspace.py backend/tests/unit/test_scheduler_core.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/worker_workspace.py backend/app/scheduler.py backend/tests/unit/test_worker_workspace.py backend/tests/unit/test_scheduler_core.py
git commit -m "feat: clean up expired worker workspaces"
```

---

### Task 12: Final Verification And Documentation Update

**Files:**
- Modify: `docs/superpowers/specs/2026-05-05-persistent-issue-workspace-design.md`
- Optional modify: `deploy/offline-bundle/docs/CONFIGURATION.md`

- [ ] **Step 1: Run backend unit tests touched by this plan**

Run:

```bash
python -m pytest \
  backend/tests/unit/test_issue_execution_locks.py \
  backend/tests/unit/test_worker_workspace.py \
  backend/tests/unit/test_scheduler_core.py \
  backend/tests/unit/test_worker_coverage.py \
  backend/tests/unit/test_tasks_api.py -q
```

Expected: PASS.

- [ ] **Step 2: Run shell syntax checks**

Run:

```bash
bash -n deploy/entrypoint.worker.sh deploy/ci-claude.sh
```

Expected: no output and exit code 0.

- [ ] **Step 3: Search for forbidden workspace runtime paths**

Run:

```bash
rg -n "/workspace/(event\\.jsonl|runtime\\.json|console\\.log)|/workspace/\\.codify-archive" backend deploy
```

Expected: no matches.

- [ ] **Step 4: Update design doc implementation status**

Append to `docs/superpowers/specs/2026-05-05-persistent-issue-workspace-design.md`:

```markdown
## Implementation Notes

Implemented in phases:

- Database-backed `issue_execution_locks` provides the authoritative issue execution gate.
- Worker workspace persistence is optional and controlled by `WORKER_WORKSPACE_HOST_PATH`.
- Runtime files and archives remain outside `/workspace` and are read from `/tmp/codify-runtime`.
- Backend persists downloadable archives to `/opt/codify-archives` before worker containers are removed.
```

- [ ] **Step 5: Run full backend test suite if time allows**

Run:

```bash
python -m pytest backend/tests/unit -q
```

Expected: PASS. If unrelated tests fail, record exact failures in final handoff.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-05-05-persistent-issue-workspace-design.md deploy/offline-bundle/docs/CONFIGURATION.md
git commit -m "docs: document persistent workspace implementation"
```

If `deploy/offline-bundle/docs/CONFIGURATION.md` was not changed, omit it from `git add`.

---

## Self-Review

Spec coverage:

- Strict same-issue execution: Tasks 1-4 add DB lock model, helpers, scheduler gate, cancel/recovery release.
- Persistent issue workspace: Tasks 5-7 add settings, volume mounts, and idempotent entrypoint reuse.
- Runtime/archive outside repo: Tasks 6-8 preserve `/tmp/codify-runtime` and compose host mount behavior.
- Workspace cleanup: Tasks 9-11 add helpers, API controls, and TTL cleanup.
- Documentation and verification: Task 12 updates docs and runs focused checks.

Placeholder scan:

- Placeholder scan passed; no vague implementation steps remain.
- Each implementation step includes concrete code or exact command.

Type consistency:

- `IssueExecutionLock`, `acquire_issue_execution_lock`, `release_issue_execution_lock`, `cleanup_inactive_issue_execution_locks`, `build_issue_workspace_paths`, `remove_issue_workspace`, and `cleanup_expired_workspaces` are consistently named across tasks.
- Workspace paths consistently use `/workspace` for repo and `/tmp/codify-runtime` for task runtime artifacts.
