from datetime import datetime
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.models import Base, IssueExecutionLock, TaskStatus


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
        db.execute = AsyncMock(side_effect=[locks_result, task_result, MagicMock()])

        removed = await cleanup_inactive_issue_execution_locks(db)

        self.assertEqual(removed, 1)
        self.assertEqual(db.execute.await_count, 3)
