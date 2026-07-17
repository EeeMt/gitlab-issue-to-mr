import unittest

import pytest
from sqlalchemy import Boolean, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base, Issue, Task, WorkerProfile


class TestTaskRequireChanges(unittest.TestCase):
    def test_require_changes_column_exists_not_nullable_default_true(self):
        col = Task.__table__.c.require_changes

        self.assertIsInstance(col.type, Boolean)
        self.assertFalse(col.nullable)


class TestTaskIssueOwnership(unittest.TestCase):
    def test_issue_id_is_required_and_cascades_on_issue_delete(self):
        column = Task.__table__.c.issue_id
        foreign_key = next(iter(column.foreign_keys))

        self.assertFalse(column.nullable)
        self.assertEqual(foreign_key.target_fullname, "issues.id")
        self.assertEqual(foreign_key.ondelete, "CASCADE")

    def test_issue_relationship_uses_database_delete_cascade(self):
        relationship = Issue.__mapper__.relationships["tasks"]

        self.assertTrue(relationship.passive_deletes)
        self.assertIn("delete", relationship.cascade)
        self.assertIn("delete-orphan", relationship.cascade)


@pytest.mark.asyncio
async def test_task_issue_constraint_and_delete_cascade() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            session.add(Task(project_id=1, issue_id=None, user_prompt="orphan"))
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

            worker = WorkerProfile(
                name="Task Worker",
                enabled=True,
                image="codify-worker:test",
                volume_mounts=[],
                pre_script="",
                post_script="",
                default_execute_run_instruction_template="{{user_prompt}}",
                default_plan_run_instruction_template="{{user_prompt}}",
                ci_auto_repair_run_instruction_template="{{user_prompt}}",
            )
            session.add(worker)
            await session.flush()
            issue = Issue(
                project_id=1,
                title="Owned task",
                description="Task must be deleted with its issue",
                status="open",
                worker_profile_id=worker.id,
            )
            session.add(issue)
            await session.flush()
            task = Task(project_id=1, issue_id=issue.id, user_prompt="owned")
            session.add(task)
            await session.commit()
            task_id = task.id
            issue_id = issue.id

        async with session_factory() as session:
            issue = await session.get(Issue, issue_id)
            assert issue is not None
            await session.delete(issue)
            await session.commit()

        async with session_factory() as session:
            assert await session.scalar(select(Task).where(Task.id == task_id)) is None
    finally:
        await engine.dispose()
