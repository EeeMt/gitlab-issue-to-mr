from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.worker_task_lifecycle import load_resume_task_or_fail
from app.models import Base, Task, TaskWorkerProfileSnapshot


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_resume_task_loads_worker_snapshot_before_async_policy_access(session_factory):
    async with session_factory() as db:
        task = Task(id=1, issue_id=1, project_id=1, user_prompt="resume")
        task.worker_profile_snapshot = TaskWorkerProfileSnapshot(
            task_id=task.id,
            profile_name="default",
            image="codify-worker:latest",
            default_execute_run_instruction_template="execute",
            default_plan_run_instruction_template="plan",
            ci_auto_repair_run_instruction_template="repair",
        )
        db.add(task)
        await db.commit()

    async with session_factory() as db:
        loaded = await load_resume_task_or_fail(db, task_id=1)

        assert loaded is not None
        assert loaded.worker_profile_snapshot is not None
        assert "worker_profile_snapshot" not in inspect(loaded).unloaded
