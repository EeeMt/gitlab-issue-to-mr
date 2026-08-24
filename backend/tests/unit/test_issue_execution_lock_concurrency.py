"""Two-session PostgreSQL concurrency tests for issue execution locks (§10.2 #11-#13).

These tests exercise the real owner-conditioned lock primitives
(``acquire_issue_execution_lock`` / ``release_issue_execution_lock`` /
``cleanup_inactive_issue_execution_locks`` and the scheduler atomic claim)
against a real PostgreSQL instance named by ``CODIFY_TEST_DATABASE_URL``.

They are skipped when the test database is unreachable so the mock/unit suite
stays green in environments without the remote dev host. The database must be
at the 068 schema (``issue_sequence`` present); the module fixture truncates
only the tables these tests touch.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy import delete, select, tuple_
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.issue_execution_locks import (
    acquire_issue_execution_lock,
    cleanup_inactive_issue_execution_locks,
    release_issue_execution_lock,
)
from app.core.utcnow import utcnow
from app.models import Issue, IssueExecutionLock, Task, TaskStatus, WorkerProfile

TEST_DATABASE_URL = os.environ.get(
    "CODIFY_TEST_DATABASE_URL",
    "postgresql+asyncpg://codify:codify_password@192.168.50.129:5432/codify_test",
)

_TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}


@pytest.fixture(scope="module")
async def test_engine():
    """Reachability-guarded async engine bound to the concurrency test DB."""
    # NullPool: pytest-asyncio runs a fresh event loop per test, and pooled
    # connections bound to a previous loop raise "Event loop is closed" on
    # reuse. A per-session connection (opened in the current loop, closed on
    # release) keeps every test on its own loop.
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        pytest.skip(f"concurrency test DB unreachable: {exc!r}")
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(test_engine):
    """Session factory with a clean slate for the tables these tests write."""
    maker = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    await _reset_tables(maker)
    yield maker
    await _reset_tables(maker)


async def _reset_tables(maker) -> None:
    async with maker() as db:
        await db.execute(
            sa.text(
                "TRUNCATE issue_execution_locks, tasks, issues, worker_profiles "
                "RESTART IDENTITY CASCADE"
            )
        )
        await db.commit()


async def _seed_issue(maker) -> int:
    async with maker() as db:
        profile = WorkerProfile(
            name=f"wp-{uuid.uuid4().hex[:8]}",
            image="test-image",
            default_execute_run_instruction_template="",
            default_plan_run_instruction_template="",
            ci_auto_repair_run_instruction_template="",
        )
        db.add(profile)
        await db.flush()
        issue = Issue(title="concurrency-test", project_id=1, worker_profile_id=profile.id)
        db.add(issue)
        await db.commit()
        return issue.id


async def _seed_task(
    maker,
    issue_id: int,
    *,
    status: TaskStatus = TaskStatus.QUEUED,
    issue_sequence: int | None = None,
    container_id: str | None = None,
    cancel_requested_at=None,
    scheduled_at=None,
) -> int:
    """Insert a Task whose frozen identity satisfies the execution policy.

    The scheduler claim gate requires a bound Runtime Bundle plus a Worker
    snapshot whose contract, digest and harness_key match that Bundle, so the
    fixture freezes a consistent legacy-V1 identity (dual_canary executable).
    """
    async with maker() as db:
        bundle_digest = uuid.uuid4().hex + uuid.uuid4().hex
        bundle_row = await db.execute(
            sa.text(
                "INSERT INTO worker_runtime_bundles "
                "(digest, bundle_bytes, contract_version, orchestration_version, manifest, size_bytes, created_at) "
                "VALUES (:digest, 'x', 'codify.worker.harness/v1', '1.0.0', CAST(:manifest AS json), 1, now()) "
                "RETURNING id"
            ),
            {
                "digest": bundle_digest,
                "manifest": json.dumps({"adapters": {"claude": {}}}),
            },
        )
        bundle_id = bundle_row.scalar_one()
        task = Task(
            user_prompt="prompt",
            issue_id=issue_id,
            project_id=1,
            status=status,
            issue_sequence=issue_sequence,
            container_id=container_id,
            cancel_requested_at=cancel_requested_at,
            scheduled_at=scheduled_at,
            runtime_bundle_id=bundle_id,
        )
        db.add(task)
        await db.flush()
        await db.execute(
            sa.text(
                "INSERT INTO task_worker_profile_snapshots "
                "(task_id, profile_name, image, runtime_mode, harness_key, "
                "default_execute_run_instruction_template, default_plan_run_instruction_template, "
                "ci_auto_repair_run_instruction_template, "
                "runtime_contract_version, orchestration_version, runtime_bundle_digest) "
                "VALUES (:t, 'concurrency-test', 'test-image', 'baked_image', 'claude', "
                "'', '', '', "
                "'codify.worker.harness/v1', '1.0.0', :digest)"
            ),
            {"t": task.id, "digest": bundle_digest},
        )
        await db.commit()
        return task.id


async def _acquire_lock_for(maker, task_id: int) -> bool:
    async with maker() as db:
        task = (
            await db.execute(select(Task).where(Task.id == task_id))
        ).scalar_one()
        acquired = await acquire_issue_execution_lock(db, task)
        await db.commit()
        return acquired


async def _run_claim(session, task_id: int, *, started: asyncio.Event | None = None):
    """Drive the real ``Scheduler._execute_task`` atomic claim on ``session``.

    The worker/notifications/docker machinery is mocked; every DB statement of
    the atomic claim (Issue row lock, ordering-integrity re-check, Task re-read,
    ``acquire_issue_execution_lock`` ON CONFLICT, CAS QUEUED->RUNNING, commit)
    runs against the real PostgreSQL instance.
    """
    from app.scheduler import Scheduler

    scheduler = Scheduler()
    scheduler._run_task_background = AsyncMock()
    scheduler._transition_issue_to_in_progress = AsyncMock()

    task = (
        await session.execute(select(Task).where(Task.id == task_id))
    ).scalar_one()
    if started is not None:
        started.set()
    with patch(
        "app.scheduler.ensure_issue_order_integrity_locked",
        new=AsyncMock(return_value={"repaired_sequences": 0, "repaired_projections": 0}),
    ):
        await scheduler._execute_task(session, task)
    return scheduler


async def _lock_rows_for(maker, issue_id: int) -> list[IssueExecutionLock]:
    async with maker() as db:
        rows = (
            await db.execute(
                select(IssueExecutionLock).where(IssueExecutionLock.issue_id == issue_id)
            )
        ).scalars().all()
        return list(rows)


# ── §10.2 #11 claim-vs-cancel ───────────────────────────────────────────────


async def test_claim_vs_cancel_cancel_commits_first_leaves_no_lock(session_factory):
    issue_id = await _seed_issue(session_factory)
    task_id = await _seed_task(session_factory, issue_id, status=TaskStatus.QUEUED, issue_sequence=1)

    # Cancel holds the Issue row lock first (Phase A §6.7), then the claim races
    # in and blocks on the same lock. Cancel CAS's QUEUED -> CANCELLED and
    # commits before the claim can re-read.
    async with session_factory() as cancel_db:
        await cancel_db.execute(
            select(Issue).where(Issue.id == issue_id).with_for_update()
        )
        claim_db = session_factory()
        started = asyncio.Event()
        claim_task = asyncio.create_task(_run_claim(claim_db, task_id, started=started))
        await started.wait()
        await asyncio.sleep(0.05)  # let the claim issue (and block on) its Issue FOR UPDATE

        task = (
            await cancel_db.execute(
                select(Task).where(Task.id == task_id).with_for_update()
            )
        ).scalar_one()
        assert task.status == TaskStatus.QUEUED
        task.status = TaskStatus.CANCELLED
        task.completed_at = utcnow()
        await cancel_db.commit()

        scheduler = await claim_task
        await claim_db.close()

    # Claim CAS failed: no RUNNING state, no worker started, and no lock left
    # behind for the cancelled task (§10.2 #11: never CANCELLED + new Worker).
    async with session_factory() as db:
        task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one()
        assert task.status == TaskStatus.CANCELLED
    assert scheduler._run_task_background.call_count == 0
    assert await _lock_rows_for(session_factory, issue_id) == []


async def test_claim_vs_cancel_claim_commits_first_keeps_owner(session_factory):
    issue_id = await _seed_issue(session_factory)
    task_id = await _seed_task(session_factory, issue_id, status=TaskStatus.QUEUED, issue_sequence=1)

    # Claim wins the race: QUEUED -> RUNNING with an owner lock committed first.
    async with session_factory() as claim_db:
        scheduler = await _run_claim(claim_db, task_id)
    assert scheduler._run_task_background.call_count == 1

    # Cancel re-reads RUNNING and only writes the cancellation intent, keeping
    # the owner lock until the finalizer converges (§10.2 #11: never RUNNING
    # without an owner).
    async with session_factory() as cancel_db:
        await cancel_db.execute(
            select(Issue).where(Issue.id == issue_id).with_for_update()
        )
        task = (
            await cancel_db.execute(
                select(Task).where(Task.id == task_id).with_for_update()
            )
        ).scalar_one()
        assert task.status == TaskStatus.RUNNING
        task.cancel_requested_at = utcnow()
        await cancel_db.commit()

    async with session_factory() as db:
        task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one()
        assert task.status == TaskStatus.RUNNING
        assert task.cancel_requested_at is not None
    locks = await _lock_rows_for(session_factory, issue_id)
    assert [lock.task_id for lock in locks] == [task_id]


# ── §10.2 #12 stale-owner late release ──────────────────────────────────────


async def test_stale_owner_late_release_rowcount_zero_keeps_new_owner(session_factory):
    issue_id = await _seed_issue(session_factory)
    task_a = await _seed_task(
        session_factory, issue_id, status=TaskStatus.RUNNING, container_id="ctr-a", issue_sequence=1
    )
    assert await _acquire_lock_for(session_factory, task_a)

    # Late finalizer of owner A pauses before its owner-conditioned release.
    late_db = session_factory()
    paused = asyncio.Event()
    release_gate = asyncio.Event()

    async def late_finalizer():
        paused.set()
        await release_gate.wait()
        return await release_issue_execution_lock(
            late_db, issue_id=issue_id, owner_task_id=task_a
        )

    late_task = asyncio.create_task(late_finalizer())
    await paused.wait()

    # A is released by another convergence path, then B acquires the same Issue.
    async with session_factory() as db:
        removed = await release_issue_execution_lock(
            db, issue_id=issue_id, owner_task_id=task_a
        )
        await db.commit()
    assert removed is True

    task_b = await _seed_task(
        session_factory, issue_id, status=TaskStatus.RUNNING, container_id="ctr-b", issue_sequence=2
    )
    assert await _acquire_lock_for(session_factory, task_b)

    release_gate.set()
    removed_late = await late_task
    await late_db.close()

    # A's late DELETE(issue_id, A) is a no-op; B's owner row is untouched.
    assert removed_late is False
    locks = await _lock_rows_for(session_factory, issue_id)
    assert [lock.task_id for lock in locks] == [task_b]


# ── §10.2 #13 cleanup-vs-reacquire ──────────────────────────────────────────


async def test_cleanup_stale_snapshot_does_not_delete_reacquired_lock(session_factory):
    issue_id = await _seed_issue(session_factory)
    task_a = await _seed_task(
        session_factory, issue_id, status=TaskStatus.FAILED, container_id=None, issue_sequence=1
    )
    assert await _acquire_lock_for(session_factory, task_a)

    # Cleanup snapshots the lock table (sees only A) then pauses before deleting.
    cleanup_db = session_factory()
    snapshot_seen = asyncio.Event()
    release_gate = asyncio.Event()

    async def cleanup_with_stale_snapshot():
        # Mirrors cleanup_inactive_issue_execution_locks: select all locks, then
        # delete only the (issue_id, task_id) pairs observed to be stale.
        locks = list((await cleanup_db.execute(select(IssueExecutionLock))).scalars().all())
        snapshot_seen.set()
        await release_gate.wait()
        task_ids = [lock.task_id for lock in locks]
        task_result = await cleanup_db.execute(select(Task).where(Task.id.in_(task_ids)))
        tasks_by_id = {task.id: task for task in task_result.scalars().all()}
        stale_pairs = [
            (lock.issue_id, lock.task_id)
            for lock in locks
            if (task := tasks_by_id.get(lock.task_id)) is None
            or (
                task.status in _TERMINAL_STATUSES
                and getattr(task, "container_id", None) is None
            )
        ]
        await cleanup_db.execute(
            delete(IssueExecutionLock).where(
                tuple_(IssueExecutionLock.issue_id, IssueExecutionLock.task_id).in_(
                    stale_pairs
                )
            )
        )
        await cleanup_db.commit()
        return stale_pairs

    cleanup_task = asyncio.create_task(cleanup_with_stale_snapshot())
    await snapshot_seen.wait()

    # Meanwhile the finalizer releases A and a new task B re-acquires the Issue.
    async with session_factory() as db:
        await release_issue_execution_lock(db, issue_id=issue_id, owner_task_id=task_a)
        await db.commit()
    task_b = await _seed_task(
        session_factory, issue_id, status=TaskStatus.RUNNING, container_id="ctr-b", issue_sequence=2
    )
    assert await _acquire_lock_for(session_factory, task_b)

    release_gate.set()
    stale_pairs = await cleanup_task
    await cleanup_db.close()

    # The stale snapshot only knew about A; its delete cannot reach B.
    assert stale_pairs == [(issue_id, task_a)]
    locks = await _lock_rows_for(session_factory, issue_id)
    assert [lock.task_id for lock in locks] == [task_b]

    # The production cleanup path, given B's current state, also keeps B.
    async with session_factory() as db:
        removed = await cleanup_inactive_issue_execution_locks(db)
        await db.commit()
    assert removed == 0
    locks = await _lock_rows_for(session_factory, issue_id)
    assert [lock.task_id for lock in locks] == [task_b]
