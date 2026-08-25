"""Behavioral tests for the V2 command plane (open-harness-v2-phase1-design §2.2).

Runs against a real PostgreSQL (throwaway 074-migrated DB) and exercises:

- ``create_command`` idempotency: same command_id+payload -> existing,
  different payload -> 409-style conflict, no duplicate sequence allocated.
- Eligibility gates: task must be RUNNING, the attempt must be exact V2 and
  harness-capable, and the control gate must be ``accepting``.
- Attempt-scoped strict sequence allocation under the row lock.
- ``queued -> delivered|rejected`` CAS written by the pump; terminals immutable.

Fixtures build a fresh 074-head database (like test_074_migration) and seed a
RUNNING task + accepting V2 Pi attempt.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.core.harness_protocol import (
    CANONICAL_EVENT_SCHEMA_V2,
    HARNESS_CONTRACT_VERSION_V2,
    MAX_COMMAND_TEXT_UTF16_CODE_UNITS,
    command_text_utf16_code_units,
    is_valid_command_id,
    is_valid_command_text,
    normalize_command_id,
)
from app.core.task_harness_commands import (
    CommandError,
    begin_command_dispatch,
    create_command,
    write_command_delivery,
    write_command_rejection,
)
from app.core.utcnow import utcnow
from app.models import TaskStatus

ADMIN_URL = os.environ.get(
    "CODIFY_TEST_DATABASE_URL",
    "postgresql+asyncpg://codify:codify_password@192.168.50.129:5432/codify_test",
)
HOST_BASE = ADMIN_URL.rsplit("/", 1)[0] + "/"
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
ALEMBIC_INI = os.path.join(BACKEND_DIR, "alembic.ini")
ALEMBIC_DIR = os.path.join(BACKEND_DIR, "alembic")


def _alembic_config(url: str) -> Config:
    cfg = Config(ALEMBIC_INI)
    cfg.config_file_name = None
    cfg.set_main_option("script_location", ALEMBIC_DIR)
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.print_stdout = lambda *args, **kwargs: None  # type: ignore[method-assign]
    return cfg


async def _create_database(dbname: str) -> None:
    engine = create_async_engine(ADMIN_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
    finally:
        await engine.dispose()


async def _drop_database(dbname: str) -> None:
    engine = create_async_engine(ADMIN_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}"'))
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def commands_db():
    dbname = f"codify_commands_{uuid.uuid4().hex[:8]}"
    url = HOST_BASE + dbname
    cfg = _alembic_config(url)
    try:
        asyncio.run(_create_database(dbname))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"command-plane DB unreachable: {exc!r}")
    original_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(cfg, "075_pi_command_dispatch_journal")
        yield {"url": url, "cfg": cfg, "dbname": dbname}
    finally:
        asyncio.run(_drop_database(dbname))
        if original_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_url


@pytest.fixture
async def maker(commands_db):
    engine = create_async_engine(commands_db["url"], poolclass=NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _insert_profile(db, name=None):
    if name is None:
        name = f"seed_{uuid.uuid4().hex[:8]}"
    return (
        await db.execute(
            sa.text(
                "INSERT INTO worker_profiles (name, image) VALUES (:n, 'codify-worker:latest') "
                "RETURNING id"
            ),
            {"n": name},
        )
    ).scalar_one()


async def _insert_issue(db, *, project_id=1):
    wp = await _insert_profile(db)
    return (
        await db.execute(
            sa.text(
                "INSERT INTO issues (title, description, project_id, status, "
                "worker_profile_id, ci_auto_repair_enabled, created_at, updated_at) "
                "VALUES ('t', 'd', :p, 'open', :wp, true, now(), now()) RETURNING id"
            ),
            {"p": project_id, "wp": wp},
        )
    ).scalar_one()


async def _insert_task(db, *, issue_id, status="pending"):
    bundle_id = await _insert_v2_bundle(db)
    return (
        await db.execute(
            sa.text(
                "INSERT INTO tasks (issue_id, project_id, user_prompt, status, priority, "
                "additions, deletions, total_changes, require_changes, task_mode, "
                "trigger_source, session_mode, issue_sequence, runtime_bundle_id, created_at, updated_at) "
                "VALUES (:i, 1, 'do', :s, 0, 0, 0, 0, true, 'execute', "
                "'manual', 'continue', 1, :bundle_id, now(), now()) RETURNING id"
            ),
            {"i": issue_id, "s": status, "bundle_id": bundle_id},
        )
    ).scalar_one()


async def _insert_v2_bundle(db, *, pi_steering=True, pi_follow_up=True):
    manifest = {
        "schema": "codify.worker.runtime-manifest/v2",
        "maturity": "internal_preview",
        "contract_version": HARNESS_CONTRACT_VERSION_V2,
        "event_schema": CANONICAL_EVENT_SCHEMA_V2,
        "command_schema": "codify.worker.command/v2",
        "result_schema": "codify.worker.result/v2",
        "files": [],
        "adapters": {
            "pi": {
                "support_tier": "default",
                "adapter": {"version": "2.0.0", "digest": "a" * 64},
                "control_transport": {"kind": "rpc_stdio", "protocol": "pi-rpc"},
                "model_protocols": ["anthropic_messages"],
                "capabilities": {
                    "resume": True,
                    "task_skills": True,
                    "usage_tokens": True,
                    "steering": pi_steering,
                    "follow_up": pi_follow_up,
                },
            },
            "claude": {
                "support_tier": "default",
                "adapter": {"version": "1.0.0", "digest": "b" * 64},
                "control_transport": {"kind": "cli_stream_json", "protocol": "claude-json"},
                "model_protocols": ["anthropic_messages"],
                "capabilities": {
                    "resume": True,
                    "task_skills": True,
                    "usage_tokens": True,
                    "steering": False,
                    "follow_up": False,
                },
            },
        },
    }
    return (
        await db.execute(
            sa.text(
                "INSERT INTO worker_runtime_bundles "
                "(digest, bundle_bytes, contract_version, orchestration_version, manifest, size_bytes, created_at) "
                "VALUES (:digest, :bundle_bytes, :contract_version, '1.0.0', CAST(:manifest AS json), 1, now()) "
                "RETURNING id"
            ),
            {
                "digest": uuid.uuid4().hex + uuid.uuid4().hex,
                "bundle_bytes": b"x",
                "contract_version": HARNESS_CONTRACT_VERSION_V2,
                "manifest": __import__("json").dumps(manifest),
            },
        )
    ).scalar_one()


async def _insert_v2_attempt(
    db,
    *,
    task_id,
    control_state="accepting",
    harness_key="pi",
):
    aid = f"task-{task_id}-attempt-{uuid.uuid4().hex[:4]}"
    return (
        await db.execute(
            sa.text(
                "INSERT INTO task_harness_attempts (attempt_id, task_id, attempt_no, "
                "event_schema, harness_key, adapter_version, cli_version, last_seq, "
                "control_state, next_command_sequence, awaiting_follow_up_turn, "
                "force_close_requested, created_at, updated_at) "
                "VALUES (:a, :t, 1, :es, :hk, '2.0.0', '0.84.2', 0, :cs, 1, false, false, now(), now()) "
                "RETURNING attempt_id"
            ),
            {
                "a": aid,
                "t": task_id,
                "es": CANONICAL_EVENT_SCHEMA_V2,
                "hk": harness_key,
                "cs": control_state,
            },
        )
    ).scalar_one()


async def _seed_running_pi(maker):
    """Create a RUNNING task with an accepting V2 Pi attempt; return ids."""
    async with maker() as db:
        issue_id = await _insert_issue(db)
        task_id = await _insert_task(db, issue_id=issue_id, status="running")
        attempt_id = await _insert_v2_attempt(db, task_id=task_id)
        await db.commit()
        return task_id, attempt_id


async def _command_count(db, task_id):
    return (
        await db.execute(
            sa.text(
                "SELECT count(*) FROM task_harness_commands WHERE task_id = :t"
            ),
            {"t": task_id},
        )
    ).scalar_one()


def _cid(label: str) -> str:
    # command_id is globally unique; the module-scoped DB is shared across
    # tests, so each call must yield a distinct id.
    return str(uuid.uuid4())


def test_command_id_validation_accepts_uuid_and_case_insensitive_ulid():
    assert is_valid_command_id("550e8400-e29b-41d4-a716-446655440000")
    assert is_valid_command_id("550E8400-E29B-41D4-A716-446655440000")
    assert is_valid_command_id("01ARZ3NDEKTSV4RRFFQ69G5FAV")
    assert is_valid_command_id("01arz3ndektsv4rrffq69g5fav")
    assert not is_valid_command_id("x" * 64)
    assert not is_valid_command_id("01ARZ3NDEKTSV4RRFFQ69G5FAI")
    assert normalize_command_id("550E8400-E29B-41D4-A716-446655440000") == (
        "550e8400-e29b-41d4-a716-446655440000"
    )
    assert normalize_command_id("01arz3ndektsv4rrffq69g5fav") == "01ARZ3NDEKTSV4RRFFQ69G5FAV"


def test_command_text_limit_uses_utf16_code_units_without_normalizing():
    assert MAX_COMMAND_TEXT_UTF16_CODE_UNITS == 4000
    assert command_text_utf16_code_units("a" * 4000) == 4000
    assert is_valid_command_text("a" * 4000)
    assert not is_valid_command_text("a" * 4001)
    assert command_text_utf16_code_units("😀" * 2000) == 4000
    assert is_valid_command_text("😀" * 2000)
    assert not is_valid_command_text("😀" * 2000 + "a")
    mixed = "a" * 3998 + "😀"
    assert is_valid_command_text(mixed)
    assert not is_valid_command_text(mixed + "a")
    # Combining marks remain distinct code units; no normalization is applied.
    assert is_valid_command_text("e\u0301" * 2000)
    assert not is_valid_command_text("e\u0301" * 2000 + "e")


# ── create_command ──────────────────────────────────────────────────────────


async def test_create_command_allocates_strict_sequence(maker):
    task_id, _ = await _seed_running_pi(maker)
    async with maker() as db:
        r1 = await create_command(
            db, task_id=task_id, command_id=_cid("cmd"), command_type="steer",
            payload={"text": "first"}, created_by="alice",
        )
        r2 = await create_command(
            db, task_id=task_id, command_id=_cid("cmd"), command_type="follow_up",
            payload={"text": "second"}, created_by="alice",
        )
        await db.commit()
        assert r1.created and r1.outcome == "created" and r1.sequence_no == 1
        assert r2.created and r2.sequence_no == 2
        assert await _command_count(db, task_id) == 2


async def test_create_command_idempotent_same_payload(maker):
    task_id, _ = await _seed_running_pi(maker)
    cid = _cid("cmd")
    async with maker() as db:
        await create_command(
            db, task_id=task_id, command_id=cid, command_type="steer",
            payload={"text": "go"}, created_by="alice",
        )
        await db.commit()
        r2 = await create_command(
            db, task_id=task_id, command_id=cid, command_type="steer",
            payload={"text": "go"}, created_by="alice",
        )
        await db.commit()
        assert not r2.created
        assert r2.outcome == "existing_same"
        assert r2.sequence_no == 1
        assert await _command_count(db, task_id) == 1


async def test_create_command_conflict_on_different_payload(maker):
    task_id, _ = await _seed_running_pi(maker)
    cid = _cid("cmd")
    async with maker() as db:
        await create_command(
            db, task_id=task_id, command_id=cid, command_type="steer",
            payload={"text": "go"}, created_by="alice",
        )
        await db.commit()
        r2 = await create_command(
            db, task_id=task_id, command_id=cid, command_type="steer",
            payload={"text": "different"}, created_by="alice",
        )
        await db.commit()
        assert not r2.created
        assert r2.outcome == "existing_conflict"
        assert r2.rejection_code == "existing_conflict"
        assert await _command_count(db, task_id) == 1


async def test_create_command_canonicalizes_id_case_for_idempotency_and_conflict(maker):
    task_id, _ = await _seed_running_pi(maker)
    upper_uuid = "550E8400-E29B-41D4-A716-446655440000"
    canonical_uuid = upper_uuid.lower()
    async with maker() as db:
        first = await create_command(
            db, task_id=task_id, command_id=upper_uuid, command_type="steer",
            payload={"text": "go"}, created_by="alice",
        )
        await db.commit()
        replay = await create_command(
            db, task_id=task_id, command_id=canonical_uuid, command_type="steer",
            payload={"text": "go"}, created_by="alice",
        )
        conflict = await create_command(
            db, task_id=task_id, command_id=canonical_uuid, command_type="steer",
            payload={"text": "different"}, created_by="alice",
        )
        assert first.command_id == canonical_uuid
        assert not replay.created and replay.outcome == "existing_same"
        assert conflict.outcome == "existing_conflict"
        assert await _command_count(db, task_id) == 1


async def test_create_command_rejects_when_task_not_running(maker):
    async with maker() as db:
        issue_id = await _insert_issue(db)
        task_id = await _insert_task(db, issue_id=issue_id, status="pending")
        await _insert_v2_attempt(db, task_id=task_id)
        await db.commit()
        r = await create_command(
            db, task_id=task_id, command_id=_cid("cmd"), command_type="steer",
            payload={"text": "x"}, created_by="alice",
        )
        await db.commit()
        assert not r.created
        assert r.rejection_code == "task_not_running"


async def test_create_command_rejects_unsupported_harness(maker):
    async with maker() as db:
        issue_id = await _insert_issue(db)
        task_id = await _insert_task(db, issue_id=issue_id, status="running")
        await _insert_v2_attempt(db, task_id=task_id, harness_key="claude")
        await db.commit()
        r = await create_command(
            db, task_id=task_id, command_id=_cid("cmd"), command_type="steer",
            payload={"text": "x"}, created_by="alice",
        )
        assert r.rejection_code == "unsupported_harness"


async def test_create_command_reads_capability_from_frozen_bundle(maker):
    async with maker() as db:
        issue_id = await _insert_issue(db)
        task_id = await _insert_task(db, issue_id=issue_id, status="running")
        await db.execute(
            sa.text(
                "UPDATE worker_runtime_bundles SET manifest = CAST(:manifest AS json) "
                "WHERE id = (SELECT runtime_bundle_id FROM tasks WHERE id = :task_id)"
            ),
            {
                "task_id": task_id,
                "manifest": __import__("json").dumps(
                    {
                        **{
                            "schema": "codify.worker.runtime-manifest/v2",
                            "maturity": "internal_preview",
                            "contract_version": HARNESS_CONTRACT_VERSION_V2,
                            "event_schema": CANONICAL_EVENT_SCHEMA_V2,
                            "command_schema": "codify.worker.command/v2",
                            "result_schema": "codify.worker.result/v2",
                            "files": [],
                        },
                        "adapters": {
                            "pi": {
                                "support_tier": "default",
                                "adapter": {"version": "2.0.0", "digest": "a" * 64},
                                "control_transport": {"kind": "rpc_stdio", "protocol": "pi-rpc"},
                                "model_protocols": ["anthropic_messages"],
                                "capabilities": {"steering": False, "follow_up": True},
                            }
                        },
                    }
                ),
            },
        )
        await _insert_v2_attempt(db, task_id=task_id)
        await db.commit()
        result = await create_command(
            db, task_id=task_id, command_id=_cid("cmd"), command_type="steer",
            payload={"text": "x"}, created_by="alice",
        )
        assert result.rejection_code == "unsupported_harness"


async def test_create_command_rejects_closed_control_gate(maker):
    async with maker() as db:
        issue_id = await _insert_issue(db)
        task_id = await _insert_task(db, issue_id=issue_id, status="running")
        await _insert_v2_attempt(db, task_id=task_id, control_state="closed")
        await db.commit()
        r = await create_command(
            db, task_id=task_id, command_id=_cid("cmd"), command_type="steer",
            payload={"text": "x"}, created_by="alice",
        )
        assert r.rejection_code == "control_gate_closed"


async def test_create_command_rejects_invalid_type_and_oversize(maker):
    task_id, _ = await _seed_running_pi(maker)
    async with maker() as db:
        r = await create_command(
            db, task_id=task_id, command_id=_cid("cmd"), command_type="explode",
            payload={"text": "x"}, created_by="alice",
        )
        assert r.rejection_code == "invalid_command_type"
        r = await create_command(
            db, task_id=task_id, command_id=_cid("cmd"), command_type="steer",
            payload={"text": "x" * 4001}, created_by="alice",
        )
        assert r.rejection_code == "payload_too_large"


async def test_create_command_unknown_task_raises(maker):
    with pytest.raises(CommandError) as exc:
        async with maker() as db:
            await create_command(
                db, task_id=999999, command_id=_cid("cmd"), command_type="steer",
                payload={"text": "x"}, created_by="alice",
            )
    assert exc.value.code == "task_not_found"


# ── CAS delivery / rejection (pump only) ────────────────────────────────────


async def test_write_delivery_transitions_dispatching_to_delivered(maker):
    task_id, _ = await _seed_running_pi(maker)
    cid = _cid("cmd")
    async with maker() as db:
        await create_command(
            db, task_id=task_id, command_id=cid, command_type="steer",
            payload={"text": "go"}, created_by="alice",
        )
        await db.commit()
        # Commit-before-send: the pump must durably claim the head as
        # ``dispatching`` before a native ACK can be recorded.
        claimed = await begin_command_dispatch(
            db, command_id=cid, started_at=utcnow()
        )
        assert claimed is not None
        await db.commit()
        ok = await write_command_delivery(
            db, command_id=cid, delivered_at=utcnow()
        )
        await db.commit()
        assert ok
        row = (
            await db.execute(
                sa.text(
                    "SELECT status, delivered_at, delivery_attempts FROM "
                    "task_harness_commands WHERE command_id = :c"
                ),
                {"c": cid},
            )
        ).one()
        assert row.status == "delivered"
        assert row.delivered_at is not None
        assert row.delivery_attempts == 1


async def test_write_rejection_transitions_to_rejected(maker):
    task_id, _ = await _seed_running_pi(maker)
    cid = _cid("cmd")
    async with maker() as db:
        await create_command(
            db, task_id=task_id, command_id=cid, command_type="steer",
            payload={"text": "go"}, created_by="alice",
        )
        await db.commit()
        # Rejection terminalizes an unsent command from queued or dispatching.
        ok = await write_command_rejection(
            db, command_id=cid, rejection_code="delivery_outcome_unknown",
            rejection_message="boom", rejected_at=utcnow(),
        )
        await db.commit()
        assert ok
        row = (
            await db.execute(
                sa.text(
                    "SELECT status, rejection_code, rejected_at FROM "
                    "task_harness_commands WHERE command_id = :c"
                ),
                {"c": cid},
            )
        ).one()
        assert row.status == "rejected"
        assert row.rejection_code == "delivery_outcome_unknown"
        assert row.rejected_at is not None


async def test_terminal_states_are_immutable(maker):
    task_id, _ = await _seed_running_pi(maker)
    cid = _cid("cmd")
    async with maker() as db:
        await create_command(
            db, task_id=task_id, command_id=cid, command_type="steer",
            payload={"text": "go"}, created_by="alice",
        )
        claimed = await begin_command_dispatch(
            db, command_id=cid, started_at=utcnow()
        )
        assert claimed is not None
        await db.commit()
        await write_command_delivery(db, command_id=cid, delivered_at=utcnow())
        await db.commit()
        # A second CAS on a delivered (non-queued) row is a no-op.
        ok = await write_command_rejection(
            db, command_id=cid, rejection_code="delivery_outcome_unknown",
            rejection_message="late", rejected_at=utcnow(),
        )
        await db.commit()
        assert not ok
        row = (
            await db.execute(
                sa.text(
                    "SELECT status FROM task_harness_commands WHERE command_id = :c"
                ),
                {"c": cid},
            )
        ).one()
        assert row.status == "delivered"


# ── unique-key race recovery (schemas.md §4) ────────────────────────────────


def _mock_db_for_flush_race(*, existing_digest: str, flush_raises: bool, command_id: str):
    """Drive ``create_command`` past its existence check and force the flush
    path, then re-read a committed row on the unique-key race."""
    db = MagicMock()
    # Existence check returns None first, then the re-read returns the row a
    # concurrent caller committed between our check and flush.
    existing = MagicMock()
    existing.command_id = command_id
    existing.sequence_no = 1
    existing.payload_digest = existing_digest
    db.get = AsyncMock(side_effect=[None, existing])

    task = MagicMock()
    task.status = TaskStatus.RUNNING
    task.runtime_bundle = MagicMock(
        contract_version=HARNESS_CONTRACT_VERSION_V2,
        manifest={
            "schema": "codify.worker.runtime-manifest/v2",
            "maturity": "internal_preview",
            "contract_version": HARNESS_CONTRACT_VERSION_V2,
            "event_schema": CANONICAL_EVENT_SCHEMA_V2,
            "command_schema": "codify.worker.command/v2",
            "result_schema": "codify.worker.result/v2",
            "files": [],
            "adapters": {
                "pi": {
                    "support_tier": "default",
                    "adapter": {"version": "2.0.0", "digest": "a" * 64},
                    "control_transport": {"kind": "rpc_stdio", "protocol": "pi-rpc"},
                    "model_protocols": ["anthropic_messages"],
                    "capabilities": {"steering": True, "follow_up": True},
                }
            },
        },
    )
    attempt = MagicMock()
    attempt.harness_key = "pi"
    attempt.event_schema = CANONICAL_EVENT_SCHEMA_V2
    attempt.control_state = "accepting"
    attempt.next_command_sequence = 1
    dstmt = MagicMock()
    dstmt.scalar_one_or_none = MagicMock(side_effect=[task, attempt])
    db.execute = AsyncMock(return_value=dstmt)
    if flush_raises:
        db.flush = AsyncMock(
            side_effect=IntegrityError("INSERT ...", {}, Exception("duplicate key"))
        )
    else:
        db.flush = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()
    return db


@patch("app.core.task_harness_commands.canonical_digest", return_value="dd" * 32)
async def test_create_command_recovers_unique_key_race_to_existing_same(_digest):
    command_id = "550e8400-e29b-41d4-a716-446655440000"
    db = _mock_db_for_flush_race(
        existing_digest="dd" * 32, flush_raises=True, command_id=command_id
    )
    with patch("app.core.task_harness_commands.bundle_supports_command", return_value=True):
        result = await create_command(
            db, task_id=1, command_id=command_id, command_type="steer",
            payload={"text": "go"}, created_by="alice",
        )
    assert db.rollback.called
    assert not result.created
    assert result.outcome == "existing_same"
    assert result.sequence_no == 1


@patch("app.core.task_harness_commands.canonical_digest", return_value="ee" * 32)
async def test_create_command_recovers_unique_key_race_to_conflict(_digest):
    command_id = "550e8400-e29b-41d4-a716-446655440001"
    db = _mock_db_for_flush_race(
        existing_digest="ff" * 32, flush_raises=True, command_id=command_id
    )
    with patch("app.core.task_harness_commands.bundle_supports_command", return_value=True):
        result = await create_command(
            db, task_id=1, command_id=command_id, command_type="steer",
            payload={"text": "different"}, created_by="alice",
        )
    assert db.rollback.called
    assert not result.created
    assert result.outcome == "existing_conflict"
    assert result.rejection_code == "existing_conflict"


def test_bundle_supports_command_reads_harness_manifest_from_archive():
    """A V2 bundle whose DB manifest column is the runtime-bundle envelope must
    still resolve steering/follow_up capability from the archive's harness
    manifest (regression: envelope shape made every command unsupported)."""
    import io
    import json
    import tarfile

    from app.core.task_harness_commands import bundle_supports_command

    harness_manifest = {
        "schema": "codify.worker.runtime-manifest/v2",
        "maturity": "internal_preview",
        "contract_version": "codify.worker.harness/v2",
        "event_schema": "codify.worker.event/v2",
        "command_schema": "codify.worker.command/v2",
        "result_schema": "codify.worker.result/v2",
        "files": [],
        "adapters": {
            "pi": {
                "support_tier": "default",
                "control_transport": {"kind": "rpc_stdio", "protocol": "pi-rpc"},
                "model_protocols": ["anthropic_messages"],
                "options_schema": "codify.worker.options/pi-v1",
                "capabilities": {
                    "resume": True,
                    "task_skills": True,
                    "usage_tokens": True,
                    "steering": True,
                    "follow_up": True,
                },
            }
        },
    }
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as archive:
        member = tarfile.TarInfo(
            "codify-runtime/orchestration/worker-entrypoint/harness/manifest.json"
        )
        data = json.dumps(harness_manifest).encode()
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))

    bundle = MagicMock()
    bundle.contract_version = "codify.worker.harness/v2"
    # DB column holds the runtime-bundle envelope, NOT the harness shape.
    bundle.manifest = {"schema": "codify.worker.runtime-bundle/v2", "adapters": {}}
    bundle.bundle_bytes = payload.getvalue()

    assert bundle_supports_command(bundle, "pi", "steer") is True
    assert bundle_supports_command(bundle, "pi", "follow_up") is True
    # A harness-shaped manifest attribute still wins (existing mock contract).
    bundle.manifest = harness_manifest
    assert bundle_supports_command(bundle, "pi", "steer") is True
