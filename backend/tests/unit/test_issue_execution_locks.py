import unittest
from datetime import datetime
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
        result = MagicMock()
        result.scalar_one_or_none.return_value = 7
        db.execute = AsyncMock(return_value=result)
        db.flush = AsyncMock()
        task = MagicMock(id=7, issue_id=11)

        acquired = await acquire_issue_execution_lock(db, task)

        self.assertTrue(acquired)
        db.execute.assert_awaited_once()
        db.flush.assert_awaited_once()

    async def test_acquire_issue_execution_lock_returns_false_on_conflict(self):
        from app.core.issue_execution_locks import acquire_issue_execution_lock

        db = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None  # ON CONFLICT DO NOTHING -> no row
        db.execute = AsyncMock(return_value=result)
        db.rollback = AsyncMock()
        task = MagicMock(id=8, issue_id=11)

        acquired = await acquire_issue_execution_lock(db, task)

        self.assertFalse(acquired)
        db.rollback.assert_not_awaited()

    async def test_release_issue_execution_lock_deletes_by_issue_and_owner(self):
        from app.core.issue_execution_locks import release_issue_execution_lock

        db = MagicMock()
        result = MagicMock()
        result.rowcount = 1
        db.execute = AsyncMock(return_value=result)

        removed = await release_issue_execution_lock(db, issue_id=11, owner_task_id=7)

        self.assertTrue(removed)
        db.execute.assert_awaited_once()
        delete_stmt = db.execute.await_args.args[0]
        from sqlalchemy.sql.dml import Delete

        self.assertIsInstance(delete_stmt, Delete)

    async def test_release_issue_execution_lock_returns_false_when_already_gone(self):
        from app.core.issue_execution_locks import release_issue_execution_lock

        db = MagicMock()
        result = MagicMock()
        result.rowcount = 0
        db.execute = AsyncMock(return_value=result)

        removed = await release_issue_execution_lock(db, issue_id=11, owner_task_id=7)

        self.assertFalse(removed)

    async def test_cleanup_inactive_issue_execution_locks_removes_terminal_task_locks(self):
        from app.core.issue_execution_locks import cleanup_inactive_issue_execution_locks

        active_lock = MagicMock(issue_id=1, task_id=101)
        terminal_lock = MagicMock(issue_id=2, task_id=102)
        running_task = MagicMock(id=101, status=TaskStatus.RUNNING, container_id="running-101")
        failed_task = MagicMock(id=102, status=TaskStatus.FAILED, container_id=None)

        locks_result = MagicMock()
        locks_result.scalars.return_value.all.return_value = [active_lock, terminal_lock]
        task_result = MagicMock()
        task_result.scalars.return_value.all.return_value = [running_task, failed_task]

        db = MagicMock()
        db.execute = AsyncMock(side_effect=[locks_result, task_result, MagicMock()])

        removed = await cleanup_inactive_issue_execution_locks(db)

        self.assertEqual(removed, 1)
        self.assertEqual(db.execute.await_count, 3)

    async def test_cleanup_keeps_terminal_task_lock_until_container_is_reaped(self):
        from app.core.issue_execution_locks import cleanup_inactive_issue_execution_locks

        retained_lock = MagicMock(issue_id=2, task_id=102)
        failed_task = MagicMock(
            id=102,
            status=TaskStatus.FAILED,
            container_id="container-102",
        )
        locks_result = MagicMock()
        locks_result.scalars.return_value.all.return_value = [retained_lock]
        task_result = MagicMock()
        task_result.scalars.return_value.all.return_value = [failed_task]
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[locks_result, task_result])

        removed = await cleanup_inactive_issue_execution_locks(db)

        self.assertEqual(removed, 0)
        self.assertEqual(db.execute.await_count, 2)
