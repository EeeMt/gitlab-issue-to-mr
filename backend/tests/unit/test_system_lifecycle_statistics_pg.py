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
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.task_creation_service import TaskCreationServices
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


async def _seed_empty_issue(maker) -> tuple[int, WorkerProfile, AIProvider]:
    """Seed a provider + enabled worker profile + an Issue with no tasks."""
    from sqlalchemy.orm import selectinload

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
            is_default=True,
            is_disabled=False,
        )
        db.add(provider)
        await db.flush()
        issue = Issue(
            title="lifecycle-pg-concurrency",
            project_id=1,
            worker_profile_id=profile.id,
        )
        db.add(issue)
        await db.commit()
        # Re-load the profile with its lazy relationships so the real create
        # path (readiness resolution reads profile.environment_variables) works
        # on a detached instance.
        profile = (
            await db.execute(
                select(WorkerProfile)
                .where(WorkerProfile.id == profile.id)
                .options(selectinload(WorkerProfile.environment_variables))
            )
        ).scalar_one()
        return issue.id, profile, provider


def _create_services(
    profile: WorkerProfile,
    provider: AIProvider,
    *,
    lock_acquired: asyncio.Event | None = None,
    release: asyncio.Event | None = None,
) -> TaskCreationServices:
    """Real ``create_task_record`` with heavy/external services stubbed out.

    The production create/retry path is what the concurrency contract (§15.1)
    cares about: it must lock the Issue row before inserting a Task. Those two
    steps run against the real DB; the runtime-bundle/prompt/GitLab machinery
    that a create would otherwise touch is stubbed so the test stays focused on
    the lock + insert semantics.
    """
    from app.api.task_creation_service import TaskCreationServices

    async def prepare_snapshot(*_args, **_kwargs):
        # Runs after the Issue row lock and the new Task insert (flush), so it
        # is the earliest point the test can observe that the create holds the
        # lock and has a live Task in its transaction. When ``release`` is given
        # the create stays in-flight (holding the lock) until the test lets it
        # finish, which makes the lock-blocking deterministic. Returns None so
        # the ORM does not try to persist the stubbed snapshot on commit.
        if lock_acquired is not None:
            lock_acquired.set()
        if release is not None:
            await release.wait()
        return None

    return TaskCreationServices(
        require_issue_operator=MagicMock(),
        get_task_with_access_check=AsyncMock(),
        validate_task_status_for_retry=MagicMock(),
        validate_scheduled_datetime_in_future=AsyncMock(),
        get_usage_quota_service=MagicMock(),
        get_project_metadata=AsyncMock(return_value={}),
        resolve_provider_for_issue=AsyncMock(return_value=provider),
        resolve_worker_profile_for_issue=AsyncMock(return_value=profile),
        prepare_task_runtime_snapshot=prepare_snapshot,
        replace_task_worker_snapshot=MagicMock(),
        clone_task_worker_snapshot=AsyncMock(),
        bind_runtime_bundle=AsyncMock(return_value=MagicMock()),
        select_snapshot_run_instruction_template=MagicMock(return_value=None),
        render_and_store_task_prompt=AsyncMock(return_value="rendered prompt"),
        notify_task_retried=AsyncMock(),
    )


async def _run_create(
    session_factory,
    *,
    issue_id: int,
    provider_id: int,
    user_prompt: str,
    services: TaskCreationServices,
) -> list[BaseException]:
    errors: list[BaseException] = []
    try:
        from app.api.task_creation_service import create_task_record
        from app.api.task_schemas import CreateTaskRequest
        from app.dependencies.project_access import ProjectAccessScope

        async with session_factory() as db:
            await create_task_record(
                request=CreateTaskRequest(
                    issue_id=issue_id,
                    user_prompt=user_prompt,
                    provider_id=provider_id,
                ),
                db=db,
                current_user=None,
                access_scope=ProjectAccessScope(
                    is_unrestricted=True, accessible_projects=[]
                ),
                services=services,
            )
    except BaseException as exc:  # noqa: BLE001
        errors.append(exc)
    return errors


async def test_create_wins_then_delete_archives_new_task(session_factory):
    """§15.1 outcome A: the new Task is created first and fully archived.

    The contender drives the real ``create_task_record`` (Issue lock then Task
    insert) while the holder runs the real archive + business-delete transaction.
    The holder blocks on the Issue lock until the create commits, then archives
    the freshly created Task before deleting the Issue.
    """
    from sqlalchemy import select

    issue_id, profile, provider = await _seed_empty_issue(session_factory)
    lock_acquired = asyncio.Event()
    release = asyncio.Event()
    create_done = asyncio.Event()
    create_errors: list[BaseException] = []

    async def create_path():
        errors = await _run_create(
            session_factory,
            issue_id=issue_id,
            provider_id=provider.id,
            user_prompt="create-wins-task",
            services=_create_services(
                profile, provider, lock_acquired=lock_acquired, release=release
            ),
        )
        create_errors.extend(errors)
        create_done.set()

    async def delete_path():
        async with session_factory() as db:
            await archive_issue_statistics_before_delete(
                db, issue_id=issue_id, deletion_reason="manual", now=utcnow()
            )
            await db.execute(delete(Issue).where(Issue.id == issue_id))
            await db.commit()

    asyncio.create_task(create_path())
    # The create holds the Issue lock and has inserted its Task once the mocked
    # snapshot preparation signals; it stays in-flight until released.
    await asyncio.wait_for(lock_acquired.wait(), timeout=10)

    holder = asyncio.create_task(delete_path())
    await asyncio.sleep(0.3)
    assert not create_done.is_set(), "create should still hold the lock before release"

    release.set()
    await asyncio.wait_for(create_done.wait(), timeout=10)
    assert not create_errors, f"create path failed unexpectedly: {create_errors!r}"
    await asyncio.wait_for(holder, timeout=10)
    assert not create_errors

    # The Issue is gone and the freshly created Task was fully archived.
    async with session_factory() as db:
        issue_count = await db.scalar(
            select(func.count()).select_from(Issue).where(Issue.id == issue_id)
        )
        assert int(issue_count or 0) == 0
        archived = await db.scalar(
            select(func.count())
            .select_from(DeletedTaskStatistics)
            .where(
                DeletedTaskStatistics.source_issue_id == issue_id,
                DeletedTaskStatistics.source_task_id.is_not(None),
            )
        )
        assert int(archived or 0) == 1
        archive = await db.scalar(
            select(DeletedTaskStatistics).where(
                DeletedTaskStatistics.source_issue_id == issue_id
            )
        )
        assert archive is not None
        # It is the task created by the real create path, snapshotted as
        # deleted-before-terminal because it never ran.
        assert archive.source_task_id is not None
        assert archive.last_status == "pending"
        assert archive.deleted_before_terminal is True


async def test_delete_wins_then_create_fails(session_factory):
    """§15.1 outcome B: delete commits first, then the create fails (404).

    The real create path blocks on the Issue row lock held by the real
    archive + delete transaction; once the delete commits, ``create_task_record``
    cannot find the Issue and raises 404.
    """
    from fastapi import HTTPException
    from sqlalchemy import select

    issue_id, profile, provider = await _seed_empty_issue(session_factory)
    delete_done = asyncio.Event()
    create_done = asyncio.Event()
    create_errors: list[BaseException] = []
    lock_held = asyncio.Event()

    async def delete_path():
        async with session_factory() as db:
            # Deterministically take the Issue row lock before running the real
            # archive + business-delete transaction, and hold it long enough to
            # observe the create blocking on it (§15.1).
            await db.execute(
                select(Issue).where(Issue.id == issue_id).with_for_update()
            )
            lock_held.set()
            await asyncio.sleep(1.0)
            await archive_issue_statistics_before_delete(
                db, issue_id=issue_id, deletion_reason="manual", now=utcnow()
            )
            await db.execute(delete(Issue).where(Issue.id == issue_id))
            await db.commit()
        delete_done.set()

    async def create_path():
        errors = await _run_create(
            session_factory,
            issue_id=issue_id,
            provider_id=provider.id,
            user_prompt="delete-wins-task",
            services=_create_services(profile, provider),
        )
        create_errors.extend(errors)
        create_done.set()

    holder = asyncio.create_task(delete_path())
    await asyncio.wait_for(lock_held.wait(), timeout=5)

    asyncio.create_task(create_path())
    await asyncio.sleep(0.3)
    assert not create_done.is_set(), "create path should be blocked on the Issue lock"

    await asyncio.wait_for(delete_done.wait(), timeout=10)
    await asyncio.wait_for(create_done.wait(), timeout=10)
    await holder

    assert len(create_errors) == 1, f"expected exactly one create error, got {create_errors!r}"
    assert isinstance(create_errors[0], HTTPException)
    assert create_errors[0].status_code == 404



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
