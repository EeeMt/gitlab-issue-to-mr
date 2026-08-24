"""Behavioral tests for the V2 command dispatch pump (phase1-design §2.2).

Covers the delivery contract: attempt lease claim, strictly-ordered queue-front
processing (a later command is never dispatched before an earlier non-terminal
one), the ``queued -> delivered|rejected`` CAS, and journaling an uncertain
outcome as ``delivery_outcome_unknown`` instead of leaving it ambiguous.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.core.harness_protocol import CANONICAL_EVENT_SCHEMA_V2, HARNESS_CONTRACT_VERSION_V2
from app.core.task_harness_commands import create_command
from app.core.worker_command_pump import (
    dispatch_one_command,
    run_pump_cycle,
)

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
def pump_db():
    dbname = f"codify_pump_{uuid.uuid4().hex[:8]}"
    url = HOST_BASE + dbname
    cfg = _alembic_config(url)
    try:
        asyncio.run(_create_database(dbname))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"pump DB unreachable: {exc!r}")
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
async def maker(pump_db):
    engine = create_async_engine(pump_db["url"], poolclass=NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _insert_profile(db):
    return (
        await db.execute(
            sa.text(
                "INSERT INTO worker_profiles (name, image) VALUES (:n, 'codify-worker:latest') "
                "RETURNING id"
            ),
            {"n": f"seed_{uuid.uuid4().hex[:8]}"},
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


async def _insert_task(db, *, issue_id, status="running"):
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


async def _insert_v2_bundle(db):
    import json

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
                "control_transport": {"kind": "rpc_stdio"},
                "model_protocols": ["anthropic_messages"],
                "capabilities": {
                    "resume": True, "task_skills": True, "usage_tokens": True,
                    "steering": True, "follow_up": True,
                },
            }
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
                "manifest": json.dumps(manifest),
            },
        )
    ).scalar_one()


async def _insert_v2_attempt(db, *, task_id, control_state="accepting"):
    aid = f"task-{task_id}-attempt-{uuid.uuid4().hex[:4]}"
    return (
        await db.execute(
            sa.text(
                "INSERT INTO task_harness_attempts (attempt_id, task_id, attempt_no, "
                "event_schema, harness_key, adapter_version, cli_version, last_seq, "
                "control_state, next_command_sequence, created_at, updated_at) "
                "VALUES (:a, :t, 1, :es, 'pi', '2.0.0', '0.84.2', 0, :cs, 1, now(), now()) "
                "RETURNING attempt_id"
            ),
            {"a": aid, "t": task_id, "es": CANONICAL_EVENT_SCHEMA_V2, "cs": control_state},
        )
    ).scalar_one()


async def _seed_task_with_commands(maker, *, control_state="accepting", count=2):
    async with maker() as db:
        issue_id = await _insert_issue(db)
        task_id = await _insert_task(db, issue_id=issue_id, status="running")
        attempt_id = await _insert_v2_attempt(db, task_id=task_id, control_state=control_state)
        command_ids = []
        for i in range(count):
            cid = f"cmd-{uuid.uuid4().hex[:16]}"
            await create_command(
                db,
                task_id=task_id,
                command_id=cid,
                command_type="steer",
                payload={"text": f"msg-{i}"},
                created_by="pump-test",
            )
            command_ids.append(cid)
        await db.commit()
        return task_id, attempt_id, command_ids


async def _row_status(db, command_id):
    return (
        await db.execute(
            sa.text("SELECT status FROM task_harness_commands WHERE command_id = :c"),
            {"c": command_id},
        )
    ).scalar_one()


def _owner() -> str:
    # Unique dispatcher identity per test so a test only claims its own fresh
    # attempt (the module-scoped DB accumulates attempts across tests and the
    # pump claims in attempt_id order).
    return f"dp-{uuid.uuid4().hex[:12]}"


async def _ack_transport(frame, **kwargs):
    return {"status": "ack"}


async def _reject_transport(frame, **kwargs):
    return {"status": "reject", "rejection_code": "control_gate_closed", "rejection_message": "no"}


async def _unknown_transport(frame, **kwargs):
    return {"status": "mystery"}


# ── pump cycle ──────────────────────────────────────────────────────────────


async def test_pump_delivers_head_command(maker):
    _, _, command_ids = await _seed_task_with_commands(maker, count=1)
    async with maker() as db:
        result = await run_pump_cycle(
            db, owner=_owner(), transport=_ack_transport
        )
        assert result.commands_processed == 1
        await db.commit()
        assert await _row_status(db, command_ids[0]) == "delivered"


async def test_pump_processes_queue_front_in_strict_order(maker):
    _, attempt_id, command_ids = await _seed_task_with_commands(maker, count=3)
    processed = []

    async def tracking_transport(frame, **kwargs):
        processed.append(frame["sequence_no"])
        return {"status": "ack"}

    async with maker() as db:
        owner = _owner()
        # First cycle delivers only the sequence-1 head.
        await run_pump_cycle(
            db, owner=owner, transport=tracking_transport, max_commands_per_attempt=1
        )
        await db.commit()
        assert processed == [1]
        # Next cycle delivers 2 (same owner renews its lease).
        await run_pump_cycle(
            db, owner=owner, transport=tracking_transport, max_commands_per_attempt=1
        )
        await db.commit()
        assert processed == [1, 2]
        # And finally 3.
        await run_pump_cycle(
            db, owner=owner, transport=tracking_transport, max_commands_per_attempt=1
        )
        await db.commit()
        assert processed == [1, 2, 3]
        for cid in command_ids:
            assert await _row_status(db, cid) == "delivered"


async def test_pump_journals_reject_to_rejected(maker):
    _, _, command_ids = await _seed_task_with_commands(maker, count=1)
    async with maker() as db:
        result = await run_pump_cycle(
            db, owner=_owner(), transport=_reject_transport
        )
        await db.commit()
        assert result.commands_processed == 1
        row = (
            await db.execute(
                sa.text(
                    "SELECT status, rejection_code FROM task_harness_commands "
                    "WHERE command_id = :c"
                ),
                {"c": command_ids[0]},
            )
        ).one()
        assert row.status == "rejected"
        assert row.rejection_code == "control_gate_closed"


async def test_pump_journals_unknown_outcome_fail_closed(maker):
    """Uncertain post-send outcome is terminal and never left queued."""
    _, _, command_ids = await _seed_task_with_commands(maker, count=1)
    async with maker() as db:
        result = await run_pump_cycle(
            db, owner=_owner(), transport=_unknown_transport
        )
        await db.commit()
        assert result.commands_processed == 1
        row = (
            await db.execute(
                sa.text(
                    "SELECT status, rejection_code FROM task_harness_commands "
                    "WHERE command_id = :c"
                ),
                {"c": command_ids[0]},
            )
        ).one()
        assert row.status == "outcome_unknown"
        assert row.rejection_code == "delivery_outcome_unknown"


async def test_pump_transport_error_fails_closed(maker):
    _, _, command_ids = await _seed_task_with_commands(maker, count=1)

    async def exploding_transport(frame, **kwargs):
        raise RuntimeError("daemon unreachable")

    async with maker() as db:
        result = await run_pump_cycle(
            db, owner=_owner(), transport=exploding_transport
        )
        await db.commit()
        assert result.commands_processed == 1
        row = (
            await db.execute(
                sa.text(
                    "SELECT status, rejection_code FROM task_harness_commands "
                    "WHERE command_id = :c"
                ),
                {"c": command_ids[0]},
            )
        ).one()
        assert row.status == "outcome_unknown"
        assert row.rejection_code == "delivery_outcome_unknown"


async def test_pump_does_not_claim_closed_control_gate(maker):
    await _seed_task_with_commands(maker, control_state="closed", count=1)
    async with maker() as db:
        result = await run_pump_cycle(
            db, owner=_owner(), transport=_ack_transport
        )
        await db.commit()
        assert result.attempts_seen == 0
        assert result.commands_processed == 0


async def test_closing_queue_drains_then_owner_ack_closes_gate(maker):
    _, attempt_id, command_ids = await _seed_task_with_commands(maker, count=1)
    seen = []

    async def transport(frame, **_kwargs):
        seen.append(frame["type"])
        return {"status": "ack"}

    async with maker() as db:
        # The command was admitted while accepting; settled races afterward.
        await db.execute(
            sa.text("UPDATE task_harness_attempts SET control_state = 'closing' WHERE attempt_id = :a"),
            {"a": attempt_id},
        )
        result = await run_pump_cycle(db, owner=_owner(), transport=transport)
        await db.commit()
        assert result.commands_processed == 1
        assert seen == ["steer", "close"]
        assert await _row_status(db, command_ids[0]) == "delivered"
        state = (await db.execute(
            sa.text("SELECT control_state FROM task_harness_attempts WHERE attempt_id = :a"),
            {"a": attempt_id},
        )).scalar_one()
        assert state == "closed"


async def test_follow_up_ack_keeps_closing_until_native_turn_start(maker):
    _, attempt_id, command_ids = await _seed_task_with_commands(maker, count=1)
    seen = []

    async def transport(frame, **_kwargs):
        seen.append(frame["type"])
        return {"status": "ack"}

    async with maker() as db:
        await db.execute(
            sa.text(
                "UPDATE task_harness_commands SET command_type = 'follow_up' WHERE command_id = :c"
            ),
            {"c": command_ids[0]},
        )
        await db.execute(
            sa.text("UPDATE task_harness_attempts SET control_state = 'closing' WHERE attempt_id = :a"),
            {"a": attempt_id},
        )
        await run_pump_cycle(db, owner=_owner(), transport=transport)
        await db.commit()
        assert seen == ["follow_up"]
        state = (await db.execute(
            sa.text("SELECT control_state FROM task_harness_attempts WHERE attempt_id = :a"),
            {"a": attempt_id},
        )).scalar_one()
        assert state == "closing"


async def test_force_close_cas_does_nothing_when_terminal_wins(maker):
    from app.core.task_command_gate import request_force_close_after_unknown_follow_up
    from app.models import TaskHarnessAttempt

    _, attempt_id, command_ids = await _seed_task_with_commands(maker, count=1)
    async with maker() as db:
        await db.execute(
            sa.text(
                "UPDATE task_harness_attempts SET control_state='closed', awaiting_follow_up_turn=true, "
                "pending_follow_up_command_id=:c, pending_follow_up_native_id='1000001' WHERE attempt_id=:a"
            ),
            {"a": attempt_id, "c": command_ids[0]},
        )
        attempt = await db.get(TaskHarnessAttempt, attempt_id)
        assert attempt is not None
        assert not await request_force_close_after_unknown_follow_up(
            db, attempt=attempt, command_id=command_ids[0], native_id="1000001", reason="test"
        )
        await db.commit()
        row = (await db.execute(sa.text(
            "SELECT control_state, force_close_requested FROM task_harness_attempts WHERE attempt_id=:a"
        ), {"a": attempt_id})).one()
        assert row.control_state == "closed"
        assert row.force_close_requested is False


async def test_force_close_cas_arms_closing_attempt_for_owner_reap(maker):
    from app.core.task_command_gate import request_force_close_after_unknown_follow_up
    from app.models import TaskHarnessAttempt

    _, attempt_id, command_ids = await _seed_task_with_commands(maker, count=1)
    async with maker() as db:
        await db.execute(
            sa.text(
                "UPDATE task_harness_attempts SET control_state='closing', awaiting_follow_up_turn=true, "
                "pending_follow_up_command_id=:c, pending_follow_up_native_id='1000001' WHERE attempt_id=:a"
            ),
            {"a": attempt_id, "c": command_ids[0]},
        )
        attempt = await db.get(TaskHarnessAttempt, attempt_id)
        assert attempt is not None
        assert await request_force_close_after_unknown_follow_up(
            db, attempt=attempt, command_id=command_ids[0], native_id="1000001", reason="test"
        )
        await db.commit()
        row = (await db.execute(sa.text(
            "SELECT control_state, force_close_requested, awaiting_follow_up_turn "
            "FROM task_harness_attempts WHERE attempt_id=:a"
        ), {"a": attempt_id})).one()
        assert row.control_state == "closing"
        assert row.force_close_requested is True
        assert row.awaiting_follow_up_turn is False


@pytest.mark.asyncio
async def test_pump_waits_through_queued_scheduler_handoff(monkeypatch):
    """The scheduler may create the pump before WorkerExecutor commits RUNNING."""
    from app.core import worker_command_pump as module
    from app.models import TaskStatus

    statuses = iter([TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.COMPLETED])
    cycles = []
    closed_contexts = []

    class Db:
        async def scalar(self, _statement):
            return next(statuses)

        async def get(self, *_args):
            return object()

        async def commit(self):
            return None

        async def rollback(self):
            return None

    class Factory:
        def __call__(self):
            class Context:
                async def __aenter__(self):
                    return Db()

                async def __aexit__(self, *_args):
                    closed_contexts.append(True)
                    return False
            return Context()

    async def cycle(*_args, **_kwargs):
        cycles.append(True)
        return module.PumpCycleResult(attempts_seen=0, commands_processed=0, commands_updated=0)

    monkeypatch.setattr(module, "run_pump_cycle", cycle)
    processed = await module.run_pump_until_task_ends(
        1, session_factory=Factory(), owner="test", interval_seconds=0
    )
    assert processed == 0
    assert cycles == [True]
    # The QUEUED wait occurs after the first context exited; a backlog cannot
    # pin one DB connection per scheduler thread during startup.
    assert len(closed_contexts) == 3


async def test_dispatch_one_command_returns_final_status(maker):
    _, attempt_id, command_ids = await _seed_task_with_commands(maker, count=1)
    async with maker() as db:
        from sqlalchemy import select

        from app.models import TaskHarnessAttempt, TaskHarnessCommand

        cmd = (
            await db.execute(
                select(TaskHarnessCommand).where(
                    TaskHarnessCommand.command_id == command_ids[0]
                )
            )
        ).scalar_one()
        attempt = (
            await db.execute(
                select(TaskHarnessAttempt).where(
                    TaskHarnessAttempt.attempt_id == attempt_id
                )
            )
        ).scalar_one()
        status = await dispatch_one_command(
            db, command=cmd, attempt=attempt, transport=_ack_transport, owner="x"
        )
        await db.commit()
        assert status == "delivered"


async def test_pump_recovers_dispatching_as_outcome_unknown(maker):
    """Crash after durable dispatch claim never causes a second native send."""
    _, _, command_ids = await _seed_task_with_commands(maker, count=1)
    async with maker() as db:
        await db.execute(
            sa.text(
                "UPDATE task_harness_commands SET status = 'dispatching', "
                "dispatch_started_at = now(), delivery_attempts = 1 WHERE command_id = :c"
            ),
            {"c": command_ids[0]},
        )
        await db.commit()
        calls = 0

        async def must_not_send(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            return {"status": "ack"}

        await run_pump_cycle(db, owner=_owner(), transport=must_not_send)
        await db.commit()
        assert calls == 0
        row = (
            await db.execute(
                sa.text("SELECT status, rejection_code FROM task_harness_commands WHERE command_id = :c"),
                {"c": command_ids[0]},
            )
        ).one()
        assert row.status == "outcome_unknown"
        assert row.rejection_code == "delivery_outcome_unknown"
