"""Tests for projected session-lineage resolution and recording.

Covers ``app.core.issue_task_lineage``: ``projection_for_task``, the
``fresh``/``continue`` resume decision in ``resolve_projected_resume_session``
(including the fail-closed stale-generation check) and
``record_projected_output_session`` which writes the produced session into the
per-generation ``IssueSessionLineage`` row. These are the runtime callers the
worker startup path is wired to (EEE-23 F1).
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.issue_task_lineage import (
    INPUT_REASON_FRESH,
    INPUT_REASON_FRESH_NO_MATCH,
    INPUT_REASON_RESUMED,
    projection_for_task,
    record_projected_output_session,
    resolve_projected_resume_session,
)
from app.models import Base, Issue, IssueSessionLineage, Task


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


def _issue(issue_id=1):
    return Issue(
        id=issue_id,
        project_id=1,
        title="t",
        status="open",
        worker_profile_id=1,
    )


def _task(
    task_id=1,
    issue_id=1,
    generation=0,
    *,
    namespace="claude-ns",
    harness="claude",
    reset_task_id=None,
    reason="initial",
    session_mode="continue",
    issue_sequence=1,
):
    return Task(
        id=task_id,
        issue_id=issue_id,
        project_id=1,
        user_prompt="p",
        session_mode=session_mode,
        issue_sequence=issue_sequence,
        projected_harness_key=harness,
        projected_session_namespace=namespace,
        projected_lineage_generation=generation,
        projected_reset_task_id=reset_task_id,
        lineage_projection_reason=reason,
        input_lineage_reason=None,
    )


def test_projection_for_task_requires_full_tuple():
    complete = _task(generation=0)
    assert projection_for_task(complete) == {
        "harness_key": "claude",
        "session_namespace": "claude-ns",
        "generation": 0,
        "reset_task_id": None,
        "reason": "initial",
    }
    assert projection_for_task(_task(generation=0, namespace=None)) is None
    assert projection_for_task(_task(generation=0, harness=None)) is None
    assert projection_for_task(_task(generation=None)) is None


async def test_fresh_clears_generation_and_returns_fresh(session_factory):
    async with session_factory() as db:
        issue = _issue()
        db.add(issue)
        task = _task(generation=1, session_mode="fresh")
        db.add(task)
        await db.flush()

        resume, reason = await resolve_projected_resume_session(
            db,
            task=task,
            harness_key="claude",
            session_namespace="claude-ns",
            generation=1,
            reset_task_id=task.id,
            session_mode="fresh",
        )
        assert resume is None
        assert reason == INPUT_REASON_FRESH

        row = (
            await db.execute(
                __import__("sqlalchemy").select(IssueSessionLineage).where(
                    IssueSessionLineage.issue_id == 1,
                    IssueSessionLineage.lineage_generation == 1,
                )
            )
        ).scalar_one()
        assert row.session_id is None
        assert row.lineage_reason == "fresh"
        assert row.harness_key == "claude"


async def test_continue_without_row_starts_fresh_no_match(session_factory):
    async with session_factory() as db:
        issue = _issue()
        db.add(issue)
        task = _task(generation=0)
        db.add(task)
        await db.flush()

        resume, reason = await resolve_projected_resume_session(
            db,
            task=task,
            harness_key="claude",
            session_namespace="claude-ns",
            generation=0,
            reset_task_id=None,
            session_mode="continue",
        )
        assert resume is None
        assert reason == INPUT_REASON_FRESH_NO_MATCH
        # A continue with no generation session never creates a row by itself.
        assert (
            await db.execute(
                __import__("sqlalchemy").select(IssueSessionLineage).where(
                    IssueSessionLineage.issue_id == 1
                )
            )
        ).scalars().all() == []


async def test_continue_resumes_exact_generation_match(session_factory):
    async with session_factory() as db:
        issue = _issue()
        db.add(issue)
        db.add(IssueSessionLineage(
            issue_id=1,
            lineage_generation=0,
            harness_key="claude",
            session_namespace="claude-ns",
            reset_task_id=None,
            session_id="session-1",
            lineage_reason="completed",
        ))
        task = _task(generation=0)
        db.add(task)
        await db.flush()

        resume, reason = await resolve_projected_resume_session(
            db,
            task=task,
            harness_key="claude",
            session_namespace="claude-ns",
            generation=0,
            reset_task_id=None,
            session_mode="continue",
        )
        assert resume == "session-1"
        assert reason == INPUT_REASON_RESUMED


async def test_continue_never_resumes_foreign_generation_row(session_factory):
    """A stale lineage row (different harness/namespace) fails closed."""
    async with session_factory() as db:
        issue = _issue()
        db.add(issue)
        db.add(IssueSessionLineage(
            issue_id=1,
            lineage_generation=0,
            harness_key="codex",
            session_namespace="codex-ns",
            reset_task_id=None,
            session_id="session-codex",
            lineage_reason="completed",
        ))
        task = _task(generation=0, harness="claude", namespace="claude-ns")
        db.add(task)
        await db.flush()

        resume, reason = await resolve_projected_resume_session(
            db,
            task=task,
            harness_key="claude",
            session_namespace="claude-ns",
            generation=0,
            reset_task_id=None,
            session_mode="continue",
        )
        assert resume is None
        assert reason == INPUT_REASON_FRESH_NO_MATCH


async def test_record_output_creates_and_updates_generation_row(session_factory):
    async with session_factory() as db:
        issue = _issue()
        db.add(issue)
        task = _task(task_id=5, generation=1, reset_task_id=5, reason="fresh", issue_sequence=3)
        db.add(task)
        await db.flush()

        await record_projected_output_session(db, task=task, session_id="session-out")
        await db.flush()

        row = (
            await db.execute(
                __import__("sqlalchemy").select(IssueSessionLineage).where(
                    IssueSessionLineage.issue_id == 1,
                    IssueSessionLineage.lineage_generation == 1,
                )
            )
        ).scalar_one()
        assert row.session_id == "session-out"
        assert row.last_output_task_id == 5
        assert row.last_output_issue_sequence == 3
        assert row.harness_key == "claude"


async def test_record_output_refuses_generation_mismatch(session_factory):
    """Writing into a row that no longer matches the Task's projection must fail closed."""
    async with session_factory() as db:
        issue = _issue()
        db.add(issue)
        db.add(IssueSessionLineage(
            issue_id=1,
            lineage_generation=1,
            harness_key="codex",
            session_namespace="codex-ns",
            reset_task_id=9,
            session_id="session-codex",
            lineage_reason="fresh",
        ))
        task = _task(task_id=5, generation=1, reset_task_id=5, reason="fresh")
        db.add(task)
        await db.flush()

        try:
            await record_projected_output_session(db, task=task, session_id="session-out")
        except ValueError:
            pass
        else:  # pragma: no cover - the assertion below is the real check
            raise AssertionError("expected a ValueError for a cross-generation write")

        row = (
            await db.execute(
                __import__("sqlalchemy").select(IssueSessionLineage).where(
                    IssueSessionLineage.issue_id == 1,
                    IssueSessionLineage.lineage_generation == 1,
                )
            )
        ).scalar_one()
        assert row.session_id == "session-codex"
        assert row.last_output_task_id is None
