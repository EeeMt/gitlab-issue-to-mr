"""PostgreSQL integration tests for lifecycle-statistics archive semantics (§7).

Verifies the same-transaction property and the row-lock ordering of the
deletion archive against a real PostgreSQL instance named by
``CODIFY_TEST_DATABASE_URL`` (must be at the 069 schema). Skipped when the test
database is unreachable so the mock/unit suite stays green in environments
without the remote dev host.

Covered here:
- archive + business delete commit atomically (both persisted),
- archive + business delete rollback atomically (neither persisted),
- the Issue row lock taken by the archive blocks a concurrent writer until the
  holder commits (Issue → Tasks ID-ascending lock order).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.system_statistics_deletion import archive_issue_statistics_before_delete
from app.core.utcnow import utcnow
from app.models import (
    AIProvider,
    Base,
    DeletedIssueStatistics,
    DeletedTaskStatistics,
    Issue,
    Task,
    TaskStatus,
    TaskWorkerProfileSnapshot,
    WorkerProfile,
)

TEST_DATABASE_URL = os.environ.get(
    "CODIFY_TEST_DATABASE_URL",
    "postgresql+asyncpg://codify:codify_password@192.168.50.129:5432/codify_test",
)


@pytest.fixture(scope="module")
async def test_engine():
    """Reachability-guarded async engine bound to the lifecycle test DB."""
    # NullPool keeps every test on its own event-loop connection.
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True, poolclass=NullPool)
    try:
        # The codify_test schema is often built from an older revision, so
        # create the lifecycle tables idempotently and add the 069 column when
        # it is missing. Committed: engine.begin() wraps the DDL transaction.
        async with engine.begin() as conn:
            await conn.execute(sa.text("SELECT 1"))
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(
                sa.text(
                    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS "
                    "change_stats_recorded_at TIMESTAMP"
                )
            )
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        pytest.skip(f"lifecycle test DB unreachable: {exc!r}")
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(test_engine):
    """Session factory with a clean slate for the tables these tests touch."""
    maker = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    await _reset_tables(maker)
    yield maker
    await _reset_tables(maker)


async def _reset_tables(maker) -> None:
    async with maker() as db:
        await db.execute(
            sa.text(
                "TRUNCATE deleted_issue_statistics, deleted_task_statistics, "
                "task_worker_profile_snapshots, tasks, issues, ai_providers, "
                "worker_profiles RESTART IDENTITY CASCADE"
            )
        )
        await db.commit()


async def _seed_issue_with_tasks(maker) -> int:
    async with maker() as db:
        profile = WorkerProfile(
            name=f"wp-{uuid.uuid4().hex[:8]}",
            image="test-image",
            default_execute_run_instruction_template="",
            default_plan_run_instruction_template="",
            ci_auto_repair_run_instruction_template="",
        )
        db.add(profile)
        provider = AIProvider(
            name=f"prov-{uuid.uuid4().hex[:8]}",
            model="test-model",
            base_url="https://example.test",
            is_default=False,
            is_disabled=False,
        )
        db.add(provider)
        await db.flush()
        issue = Issue(
            title="lifecycle-pg-test",
            project_id=1,
            worker_profile_id=profile.id,
            merge_request_iid=5,
        )
        db.add(issue)
        await db.flush()

        now = utcnow()
        for i, status in ((1, TaskStatus.COMPLETED), (2, TaskStatus.FAILED)):
            task = Task(
                issue_id=issue.id,
                project_id=1,
                user_prompt=f"pg-task-{i}",
                status=status,
                provider_id=provider.id,
                provider_runtime_snapshot={
                    "provider_id": provider.id,
                    "provider_name": provider.name,
                    "configured_model": "test-model",
                },
                started_at=now - timedelta(hours=1),
                completed_at=now if status == TaskStatus.COMPLETED else None,
                input_tokens=10,
                output_tokens=5,
                additions=1,
                deletions=1,
                total_changes=2,
                change_stats_recorded_at=now if status == TaskStatus.COMPLETED else None,
            )
            db.add(task)
            await db.flush()
            db.add(
                TaskWorkerProfileSnapshot(
                    task_id=task.id,
                    worker_profile_id=profile.id,
                    profile_name=profile.name,
                    image="test-image",
                    volume_mounts=[],
                    environment_variables=[],
                    pre_script="",
                    post_script="",
                    default_execute_run_instruction_template="",
                    default_plan_run_instruction_template="",
                    ci_auto_repair_run_instruction_template="",
                    harness_key="claude",
                    harness_adapter_version="1.2",
                    cli_version="2.0",
                )
            )
        await db.commit()
        return issue.id


async def _counts(maker, issue_id: int) -> tuple[int, int, int]:
    async with maker() as db:
        issues = await db.scalar(select(func.count()).select_from(Issue).where(Issue.id == issue_id))
        tasks = await db.scalar(select(func.count()).select_from(Task).where(Task.issue_id == issue_id))
        archived = await db.scalar(
            select(func.count())
            .select_from(DeletedTaskStatistics)
            .where(DeletedTaskStatistics.source_issue_id == issue_id)
        )
        return int(issues or 0), int(tasks or 0), int(archived or 0)


async def test_archive_row_lock_and_same_transaction_delete(session_factory):
    """Archive + delete commit atomically, roll back atomically, and row-lock."""
    # 1) Same-transaction commit: archive + delete persisted together.
    issue_id = await _seed_issue_with_tasks(session_factory)
    async with session_factory() as db:
        archived = await archive_issue_statistics_before_delete(
            db, issue_id=issue_id, deletion_reason="manual", deleted_by_user_id=1, now=utcnow()
        )
        assert archived == 2
        await db.execute(delete(Issue).where(Issue.id == issue_id))
        await db.commit()
    assert await _counts(session_factory, issue_id) == (0, 0, 2)
    async with session_factory() as db:
        issue_archive = await db.scalar(
            select(func.count())
            .select_from(DeletedIssueStatistics)
            .where(DeletedIssueStatistics.source_issue_id == issue_id)
        )
        assert int(issue_archive or 0) == 1

    # 2) Same-transaction rollback: archive + delete rolled back together.
    issue2 = await _seed_issue_with_tasks(session_factory)
    async with session_factory() as db:
        await archive_issue_statistics_before_delete(
            db, issue_id=issue2, deletion_reason="manual", now=utcnow()
        )
        await db.execute(delete(Issue).where(Issue.id == issue2))
        await db.rollback()
    assert await _counts(session_factory, issue2) == (1, 2, 0)

    # 3) Row lock: B's archive blocks on the Issue lock held by A until A commits.
    issue3 = await _seed_issue_with_tasks(session_factory)
    async with session_factory() as holder:
        await holder.execute(select(Issue).where(Issue.id == issue3).with_for_update())
        entered = asyncio.Event()
        completed = asyncio.Event()

        async def contender():
            async with session_factory() as contender_db:
                entered.set()
                await archive_issue_statistics_before_delete(
                    contender_db, issue_id=issue3, deletion_reason="manual", now=utcnow()
                )
                completed.set()

        contender_task = asyncio.create_task(contender())
        await asyncio.wait_for(entered.wait(), timeout=5)
        await asyncio.sleep(0.3)
        assert not completed.is_set(), "contender should be blocked on the Issue row lock"

        await holder.commit()  # release the lock

        await asyncio.wait_for(completed.wait(), timeout=10)
        await contender_task


async def test_create_path_waits_for_archive_holder_commit(session_factory):
    """The real create/retry path blocks on the archive's Issue lock (§15.1).

    The previous contender only ran another archive; this drives the actual
    create path (select Issue FOR UPDATE, then insert a Task) and verifies it
    cannot interleave with a concurrent archive of the same issue.
    """
    issue_id = await _seed_issue_with_tasks(session_factory)
    async with session_factory() as holder:
        await holder.execute(select(Issue).where(Issue.id == issue_id).with_for_update())
        entered = asyncio.Event()
        completed = asyncio.Event()
        errors: list[BaseException] = []

        async def create_path():
            try:
                async with session_factory() as create_db:
                    # Create/retry acquires the Issue row lock first, then inserts
                    # the new Task under the same transaction. entered.set() runs
                    # before the SELECT so the test can observe the blocked state.
                    entered.set()
                    issue = (
                        await create_db.execute(
                            select(Issue).where(Issue.id == issue_id).with_for_update()
                        )
                    ).scalar_one()
                    create_db.add(
                        Task(
                            issue_id=issue.id,
                            project_id=1,
                            user_prompt="create-after-archive",
                            status=TaskStatus.PENDING,
                        )
                    )
                    await create_db.commit()
                    completed.set()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
                raise

        contender = asyncio.create_task(create_path())
        await asyncio.wait_for(entered.wait(), timeout=5)
        await asyncio.sleep(0.3)
        assert not completed.is_set(), "create path should be blocked on the Issue row lock"

        await holder.commit()  # archive holder releases the lock

        try:
            await asyncio.wait_for(completed.wait(), timeout=10)
        except Exception:  # noqa: BLE001
            raise AssertionError(f"create path did not finish after unlock: {errors!r}") from None
        await contender
        assert not errors

    async with session_factory() as db:
        created = await db.scalar(
            select(func.count())
            .select_from(Task)
            .where(
                Task.issue_id == issue_id,
                Task.user_prompt == "create-after-archive",
            )
        )
        assert int(created or 0) == 1


async def test_pg_day_bucket_uses_shanghai_timezone(session_factory):
    """Day-bucket trends convert to Asia/Shanghai before date_trunc.

    UTC 00:30 stays on the same Shanghai day; UTC 16:30 rolls over to the next
    Shanghai day (the §15.1 boundary the SQLite fallback cannot exercise).
    """
    async with session_factory() as db:
        profile = WorkerProfile(
            name=f"wp-{uuid.uuid4().hex[:8]}",
            image="test-image",
            default_execute_run_instruction_template="",
            default_plan_run_instruction_template="",
            ci_auto_repair_run_instruction_template="",
        )
        db.add(profile)
        provider = AIProvider(
            name=f"prov-{uuid.uuid4().hex[:8]}",
            model="test-model",
            base_url="https://example.test",
            is_default=False,
            is_disabled=False,
        )
        db.add(provider)
        await db.flush()
        issue = Issue(
            title="lifecycle-pg-bucket",
            project_id=1,
            worker_profile_id=profile.id,
        )
        db.add(issue)
        await db.flush()

        now = utcnow()
        for i, created_at in enumerate(
            (datetime(2026, 1, 1, 0, 30), datetime(2026, 1, 1, 16, 30))
        ):
            task = Task(
                issue_id=issue.id,
                project_id=1,
                user_prompt=f"pg-bucket-{i}",
                status=TaskStatus.COMPLETED,
                provider_id=provider.id,
                provider_runtime_snapshot={
                    "provider_id": provider.id,
                    "provider_name": provider.name,
                    "configured_model": "test-model",
                },
                created_at=created_at,
                started_at=now - timedelta(hours=1),
                completed_at=now,
            )
            db.add(task)
            await db.flush()
            db.add(
                TaskWorkerProfileSnapshot(
                    task_id=task.id,
                    worker_profile_id=profile.id,
                    profile_name=profile.name,
                    image="test-image",
                    volume_mounts=[],
                    environment_variables=[],
                    pre_script="",
                    post_script="",
                    default_execute_run_instruction_template="",
                    default_plan_run_instruction_template="",
                    ci_auto_repair_run_instruction_template="",
                    harness_key="claude",
                )
            )
        await db.commit()

    from app.api import system_statistics_queries as q

    all_tasks = q.build_all_task_statistics_cte(
        dialect="postgresql",
        project_id=None,
        provider_id=None,
        harness_key=None,
        data_state="all",
    )
    async with session_factory() as db:
        rows = list(
            (
                await db.execute(
                    q.build_task_created_trend(all_tasks, "postgresql", "day", None)
                )
            ).all()
        )

    buckets = {row.bucket.date() for row in rows}
    assert buckets == {datetime(2026, 1, 1).date(), datetime(2026, 1, 2).date()}
