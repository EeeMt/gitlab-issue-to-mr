"""Per-issue, per-harness, per-namespace session lineage.

Sessions are keyed by ``(issue_id, harness_key, session_namespace)``. The
namespace derives from the harness, the Endpoint fingerprint and the Adapter
state major version so switching harness (or a compat-changing endpoint edit)
never resumes a foreign conversation, while switching back can recover the
original Claude lineage.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, IssueHarnessSession

LEGACY_NAMESPACE = "legacy"


def session_namespace_for(
    harness_key: str,
    endpoint_fingerprint: str | None,
    adapter_state_major: str = "1",
) -> str:
    """Stable namespace for a harness/endpoint/state-major combination."""
    material = f"{harness_key}|{endpoint_fingerprint or ''}|state-{adapter_state_major}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"{harness_key}-{digest}"


async def find_session(
    db: AsyncSession,
    *,
    issue_id: int,
    harness_key: str,
    session_namespace: str,
) -> IssueHarnessSession | None:
    return (
        await db.execute(
            select(IssueHarnessSession).where(
                IssueHarnessSession.issue_id == issue_id,
                IssueHarnessSession.harness_key == harness_key,
                IssueHarnessSession.session_namespace == session_namespace,
            )
        )
    ).scalar_one_or_none()


async def upsert_session(
    db: AsyncSession,
    *,
    issue_id: int,
    harness_key: str,
    session_namespace: str,
    session_id: str | None,
    lineage_reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> IssueHarnessSession:
    session = await find_session(
        db,
        issue_id=issue_id,
        harness_key=harness_key,
        session_namespace=session_namespace,
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    if session is None:
        session = IssueHarnessSession(
            issue_id=issue_id,
            harness_key=harness_key,
            session_namespace=session_namespace,
            session_id=session_id,
            lineage_reason=lineage_reason,
            session_metadata=metadata,
            created_at=now,
            updated_at=now,
        )
        db.add(session)
    else:
        if session_id is not None:
            session.session_id = session_id
        if lineage_reason is not None:
            session.lineage_reason = lineage_reason
        if metadata is not None:
            session.session_metadata = metadata
        session.updated_at = now
    await db.flush()
    return session


async def get_issue_latest_harness_key(
    db: AsyncSession,
    issue_id: int,
) -> str | None:
    """Return the harness_key of the most recent session lineage for an issue.

    This is the issue's current harness: as tasks are appended and fresh
    sessions started, the latest lineage's harness wins over any profile
    default. ``None`` means the issue has no session lineage yet.
    """
    result = await db.execute(
        select(IssueHarnessSession)
        .where(IssueHarnessSession.issue_id == issue_id)
        .order_by(IssueHarnessSession.id.desc())
        .limit(1)
    )
    session = result.scalar_one_or_none()
    return session.harness_key if session is not None else None


async def resolve_resume_session(
    db: AsyncSession,
    *,
    issue: Issue,
    harness_key: str,
    session_namespace: str,
    session_mode: str,
) -> tuple[str | None, str | None]:
    """Return ``(resume_session_id, lineage_reason)`` for a new Task.

    ``session_mode=continue`` resumes only an exact match; otherwise a fresh
    lineage is recorded explicitly (never a silent cross-namespace fallback).
    """
    if session_mode != "continue":
        await upsert_session(
            db,
            issue_id=issue.id,
            harness_key=harness_key,
            session_namespace=session_namespace,
            session_id=None,
            lineage_reason="fresh",
            metadata={"source": "task_start"},
        )
        return None, "fresh"
    session = await find_session(
        db,
        issue_id=issue.id,
        harness_key=harness_key,
        session_namespace=session_namespace,
    )
    if session is not None and session.session_id:
        return session.session_id, "resumed"
    await upsert_session(
        db,
        issue_id=issue.id,
        harness_key=harness_key,
        session_namespace=session_namespace,
        session_id=None,
        lineage_reason="fresh_no_match",
        metadata={"source": "continue_without_match"},
    )
    return None, "fresh_no_match"


async def record_task_output_session(
    db: AsyncSession,
    *,
    issue: Issue,
    harness_key: str,
    session_namespace: str,
    session_id: str | None,
) -> None:
    """Upsert the current namespace session after a run completes."""
    if not session_id:
        return
    await upsert_session(
        db,
        issue_id=issue.id,
        harness_key=harness_key,
        session_namespace=session_namespace,
        session_id=session_id,
        lineage_reason="completed",
    )
    # Mirror the current Claude legacy compatibility value for existing readers.
    if harness_key == "claude":
        issue.claude_session_id = session_id
    await db.flush()
