from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("CONFIG_ENCRYPTION_KEY", "unit-test-key")

from app.core.harness_attempts import (  # noqa: E402
    assert_attempt_complete,
    create_task_attempt,
    ingest_canonical_event,
)
from app.core.harness_protocol import HarnessProtocolError, build_event  # noqa: E402
from app.models import Base, Task  # noqa: E402


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


def _event(attempt_id: str, seq: int, event_type: str) -> dict:
    payload = {}
    if event_type == "run.completed":
        payload = {"status": "completed", "success": True}
    elif event_type == "run.failed":
        payload = {
            "status": "failed",
            "success": False,
            "failure": {"kind": "engine_error"},
        }
    return build_event(
        attempt_id=attempt_id,
        seq=seq,
        task_id=1,
        harness_key="claude",
        adapter_version="1.0.0",
        cli_version="2.1.152",
        event_type=event_type,
        payload=payload,
        event_id=f"event-{seq}",
        occurred_at=f"2026-08-01T00:00:{seq:02d}Z",
    )


async def _task_and_attempt(db):
    task = Task(id=1, issue_id=1, project_id=1, user_prompt="probe")
    db.add(task)
    await db.flush()
    attempt = await create_task_attempt(
        db,
        task=task,
        harness_key="claude",
        adapter_version="1.0.0",
        cli_version="2.1.152",
        attempt_id="task-1-attempt-1",
    )
    return task, attempt


@pytest.mark.asyncio
async def test_attempt_is_reused_on_scheduler_recovery(session_factory):
    async with session_factory() as db:
        task, attempt = await _task_and_attempt(db)
        recovered = await create_task_attempt(
            db,
            task=task,
            harness_key="claude",
            adapter_version="1.0.0",
        )
        assert recovered.id == attempt.id
        assert recovered.attempt_id == "task-1-attempt-1"


@pytest.mark.asyncio
async def test_recovery_cannot_change_frozen_adapter(session_factory):
    async with session_factory() as db:
        task, _attempt = await _task_and_attempt(db)
        with pytest.raises(HarnessProtocolError, match="change the frozen"):
            await create_task_attempt(
                db,
                task=task,
                harness_key="claude",
                adapter_version="2.0.0",
            )


@pytest.mark.asyncio
async def test_exact_duplicate_is_idempotent_and_divergent_duplicate_fails(session_factory):
    async with session_factory() as db:
        _task, attempt = await _task_and_attempt(db)
        event = _event(attempt.attempt_id, 1, "run.started")
        first = await ingest_canonical_event(db, event)
        duplicate = await ingest_canonical_event(db, event)
        assert first.duplicate is False
        assert duplicate.duplicate is True

        divergent = dict(event)
        divergent["payload"] = {"changed": True}
        with pytest.raises(HarnessProtocolError, match="divergent duplicate"):
            await ingest_canonical_event(db, divergent)


@pytest.mark.asyncio
async def test_sequence_gap_is_rejected_before_receipt_is_written(session_factory):
    async with session_factory() as db:
        _task, attempt = await _task_and_attempt(db)
        await ingest_canonical_event(db, _event(attempt.attempt_id, 1, "run.started"))
        with pytest.raises(HarnessProtocolError, match="sequence gap"):
            await ingest_canonical_event(db, _event(attempt.attempt_id, 3, "harness.completed"))
        assert attempt.last_seq == 1


@pytest.mark.asyncio
async def test_complete_attempt_persists_one_task_terminal(session_factory):
    async with session_factory() as db:
        _task, attempt = await _task_and_attempt(db)
        for seq, event_type in enumerate(
            ["run.started", "harness.completed", "worker.finalization", "run.completed"],
            start=1,
        ):
            await ingest_canonical_event(db, _event(attempt.attempt_id, seq, event_type))
        complete = await assert_attempt_complete(db, attempt.attempt_id)
        assert complete.last_seq == 4
        assert complete.terminal_event_id == "event-4"
        assert complete.terminal_event_type == "run.completed"


@pytest.mark.asyncio
async def test_harness_completed_alone_is_not_complete(session_factory):
    async with session_factory() as db:
        _task, attempt = await _task_and_attempt(db)
        await ingest_canonical_event(db, _event(attempt.attempt_id, 1, "run.started"))
        await ingest_canonical_event(db, _event(attempt.attempt_id, 2, "harness.completed"))
        with pytest.raises(HarnessProtocolError, match="missing task terminal"):
            await assert_attempt_complete(db, attempt.attempt_id)


@pytest.mark.asyncio
async def test_first_event_freezes_cli_version_and_later_change_is_rejected(session_factory):
    async with session_factory() as db:
        task = Task(id=1, issue_id=1, project_id=1, user_prompt="probe")
        db.add(task)
        await db.flush()
        attempt = await create_task_attempt(
            db,
            task=task,
            harness_key="claude",
            adapter_version="1.0.0",
            cli_version=None,
            attempt_id="task-1-attempt-1",
        )
        await ingest_canonical_event(db, _event(attempt.attempt_id, 1, "run.started"))
        assert attempt.cli_version == "2.1.152"
        changed = _event(attempt.attempt_id, 2, "harness.completed")
        changed["harness"]["cli_version"] = "2.2.0"
        with pytest.raises(HarnessProtocolError, match="CLI does not match"):
            await ingest_canonical_event(db, changed)
