"""Tests for per-issue/per-harness session namespace and lineage."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.harness_sessions import (
    find_session,
    record_task_output_session,
    resolve_resume_session,
    session_namespace_for,
    upsert_session,
)
from app.models import Base, Issue


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


def test_namespace_is_harness_and_endpoint_scoped():
    ns = session_namespace_for("claude", "v1:abcdef")
    assert ns.startswith("claude-")
    assert ns == session_namespace_for("claude", "v1:abcdef")
    assert ns != session_namespace_for("claude", "v1:zzzzzz")
    assert ns != session_namespace_for("codex", "v1:abcdef")


async def test_continue_resolves_exact_match_only(session_factory):
    async with session_factory() as db:
        issue = _issue()
        db.add(issue)
        await db.flush()
        ns = session_namespace_for("claude", "v1:abc")
        await upsert_session(
            db,
            issue_id=issue.id,
            harness_key="claude",
            session_namespace=ns,
            session_id="session-1",
            lineage_reason="completed",
        )
        await db.flush()

        resume, reason = await resolve_resume_session(
            db, issue=issue, harness_key="claude",
            session_namespace=ns, session_mode="continue",
        )
        assert resume == "session-1"
        assert reason == "resumed"

        other_ns = session_namespace_for("codex", "v1:abc")
        resume2, reason2 = await resolve_resume_session(
            db, issue=issue, harness_key="codex",
            session_namespace=other_ns, session_mode="continue",
        )
        assert resume2 is None
        assert reason2 == "fresh_no_match"


async def test_fresh_never_resumes(session_factory):
    async with session_factory() as db:
        issue = _issue()
        db.add(issue)
        await db.flush()
        ns = session_namespace_for("claude", "v1:abc")
        await upsert_session(
            db, issue_id=issue.id, harness_key="claude",
            session_namespace=ns, session_id="session-1",
        )
        resume, reason = await resolve_resume_session(
            db, issue=issue, harness_key="claude",
            session_namespace=ns, session_mode="fresh",
        )
        assert resume is None
        assert reason == "fresh"


async def test_record_output_mirrors_claude_legacy_pointer(session_factory):
    async with session_factory() as db:
        issue = _issue()
        db.add(issue)
        await db.flush()
        ns = session_namespace_for("claude", "v1:abc")
        await record_task_output_session(
            db, issue=issue, harness_key="claude",
            session_namespace=ns, session_id="session-out",
        )
        await db.flush()
        assert issue.claude_session_id == "session-out"
        found = await find_session(
            db, issue_id=issue.id, harness_key="claude", session_namespace=ns
        )
        assert found.session_id == "session-out"


async def test_record_output_does_not_touch_claude_pointer_for_codex(session_factory):
    async with session_factory() as db:
        issue = _issue()
        issue.claude_session_id = "claude-old"
        db.add(issue)
        await db.flush()
        ns = session_namespace_for("codex", "v1:abc")
        await record_task_output_session(
            db, issue=issue, harness_key="codex",
            session_namespace=ns, session_id="codex-session",
        )
        await db.flush()
        assert issue.claude_session_id == "claude-old"
