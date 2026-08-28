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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.core.harness_protocol import CANONICAL_EVENT_SCHEMA_V2, HARNESS_CONTRACT_VERSION_V2
from app.core.task_harness_commands import create_command
from app.core.worker_command_pump import (
    dispatch_one_command,
    docker_exec_control_transport,
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
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "TRUNCATE task_harness_commands, task_harness_attempts, tasks, "
                    "issues, worker_profiles, worker_runtime_bundles "
                    "RESTART IDENTITY CASCADE"
                )
            )
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
                "control_transport": {"kind": "rpc_stdio", "protocol": "pi-rpc"},
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
                "control_state, next_command_sequence, awaiting_follow_up_turn, "
                "force_close_requested, created_at, updated_at) "
                "VALUES (:a, :t, 1, :es, 'pi', '2.0.0', '0.84.2', 0, :cs, 1, false, false, now(), now()) "
                "RETURNING attempt_id"
            ),
            {"a": aid, "t": task_id, "es": CANONICAL_EVENT_SCHEMA_V2, "cs": control_state},
        )
    ).scalar_one()

async def _seed_task_with_commands(
    maker, *, control_state="accepting", count=2, create_commands=True
):
    async with maker() as db:
        issue_id = await _insert_issue(db)
        task_id = await _insert_task(db, issue_id=issue_id, status="running")
        attempt_id = await _insert_v2_attempt(db, task_id=task_id, control_state=control_state)
        command_ids = []
        if create_commands:
            for i in range(count):
                cid = str(uuid.uuid4())
                seeded = await create_command(
                    db,
                    task_id=task_id,
                    command_id=cid,
                    command_type="steer",
                    payload={"text": f"msg-{i}"},
                    created_by="pump-test",
                )
                assert seeded.created, f"seed failed: {seeded.outcome}"
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
    task_id, _, command_ids = await _seed_task_with_commands(maker, count=1)
    async with maker() as db:
        result = await run_pump_cycle(
            db, task_id=task_id, owner=_owner(), transport=_ack_transport
        )
        assert result.commands_processed == 1
        await db.commit()
        assert await _row_status(db, command_ids[0]) == "delivered"


async def test_idle_accepting_attempt_does_not_starve_newer_queued_work(maker):
    """An accepting attempt with no queue item must not win the claim."""
    await _seed_task_with_commands(maker, create_commands=False)
    task_id, _, command_ids = await _seed_task_with_commands(maker, count=1)

    async with maker() as db:
        result = await run_pump_cycle(
            db, task_id=task_id, owner=_owner(), transport=_ack_transport
        )
        await db.commit()

        assert result.attempts_seen == 1
        assert result.commands_processed == 1
        assert await _row_status(db, command_ids[0]) == "delivered"


async def test_waiting_closing_attempt_does_not_starve_newer_queued_work(maker):
    """A drained closing attempt awaiting native follow-up must stay idle."""
    _, waiting_attempt_id, _ = await _seed_task_with_commands(
        maker, control_state="closing", create_commands=False
    )
    async with maker() as db:
        await db.execute(
            sa.text(
                "UPDATE task_harness_attempts SET awaiting_follow_up_turn = true "
                "WHERE attempt_id = :a"
            ),
            {"a": waiting_attempt_id},
        )
        await db.commit()
    task_id, _, command_ids = await _seed_task_with_commands(maker, count=1)

    async with maker() as db:
        result = await run_pump_cycle(
            db, task_id=task_id, owner=_owner(), transport=_ack_transport
        )
        await db.commit()

        assert result.attempts_seen == 1
        assert result.commands_processed == 1
        assert await _row_status(db, command_ids[0]) == "delivered"


async def test_pump_processes_queue_front_in_strict_order(maker):
    task_id, attempt_id, command_ids = await _seed_task_with_commands(maker, count=3)
    processed = []

    async def tracking_transport(frame, **kwargs):
        processed.append(frame["sequence_no"])
        return {"status": "ack"}

    async with maker() as db:
        owner = _owner()
        # First cycle delivers only the sequence-1 head.
        await run_pump_cycle(
            db,
            task_id=task_id,
            owner=owner,
            transport=tracking_transport,
            max_commands_per_attempt=1,
        )
        await db.commit()
        assert processed == [1]
        # Next cycle delivers 2 (same owner renews its lease).
        await run_pump_cycle(
            db,
            task_id=task_id,
            owner=owner,
            transport=tracking_transport,
            max_commands_per_attempt=1,
        )
        await db.commit()
        assert processed == [1, 2]
        # And finally 3.
        await run_pump_cycle(
            db,
            task_id=task_id,
            owner=owner,
            transport=tracking_transport,
            max_commands_per_attempt=1,
        )
        await db.commit()
        assert processed == [1, 2, 3]
        for cid in command_ids:
            assert await _row_status(db, cid) == "delivered"


async def test_pump_waits_for_locked_queue_front_instead_of_skipping_it(maker, monkeypatch):
    """A locked lower sequence must block the pump rather than expose a later command."""
    from app.core import worker_command_pump as module

    task_id, _, command_ids = await _seed_task_with_commands(maker, count=2)
    head_lookup_started = asyncio.Event()
    pump_started = asyncio.Event()
    real_load_head = module._load_head_command

    async def load_head(db, *, task_id, attempt_id):
        head_lookup_started.set()
        return await real_load_head(db, task_id=task_id, attempt_id=attempt_id)

    monkeypatch.setattr(module, "_load_head_command", load_head)
    processed: list[int] = []

    async def tracking_transport(frame, **kwargs):
        processed.append(frame["sequence_no"])
        return {"status": "ack"}

    async def pump_once():
        async with maker() as db:
            pid = await db.scalar(sa.text("SELECT pg_backend_pid()"))
            pump_pid["value"] = pid
            pump_started.set()
            result = await run_pump_cycle(
                db,
                task_id=task_id,
                owner=_owner(),
                transport=tracking_transport,
                max_commands_per_attempt=1,
            )
            await db.commit()
            return result

    pump_pid: dict[str, int] = {}
    async with maker() as locker:
        await locker.execute(
            sa.text(
                "SELECT command_id FROM task_harness_commands "
                "WHERE command_id = :command_id FOR UPDATE"
            ),
            {"command_id": command_ids[0]},
        )
        pump_task = asyncio.create_task(pump_once())
        try:
            await asyncio.wait_for(pump_started.wait(), timeout=5)
            await asyncio.wait_for(head_lookup_started.wait(), timeout=5)

            deadline = asyncio.get_running_loop().time() + 5
            locked_front_seen = False
            async with maker() as observer:
                while asyncio.get_running_loop().time() < deadline:
                    wait_event_type = await observer.scalar(
                        sa.text(
                            "SELECT wait_event_type FROM pg_stat_activity "
                            "WHERE pid = :pid"
                        ),
                        {"pid": pump_pid["value"]},
                    )
                    if wait_event_type == "Lock":
                        locked_front_seen = True
                        break
                    if pump_task.done():
                        break
                    await asyncio.sleep(0.01)

            assert locked_front_seen, "pump did not wait for the locked queue front"
            assert not pump_task.done()
        finally:
            await locker.rollback()

        result = await asyncio.wait_for(pump_task, timeout=5)

    assert result.commands_processed == 1
    assert processed == [1]
    async with maker() as db:
        assert await _row_status(db, command_ids[0]) == "delivered"
        assert await _row_status(db, command_ids[1]) == "queued"


async def test_pump_claim_is_task_scoped_under_concurrency(maker):
    """Concurrent per-task pumps must never claim or send another Task's head."""
    task_one, _, command_one = await _seed_task_with_commands(maker, count=1)
    task_two, _, command_two = await _seed_task_with_commands(maker, count=1)
    seen: list[tuple[int, str]] = []

    async def pump_one(task_id: int):
        async with maker() as db:
            async def transport(frame, **_kwargs):
                seen.append((frame["task_id"], frame["command_id"]))
                await asyncio.sleep(0)
                return {"status": "ack"}

            result = await run_pump_cycle(
                db, task_id=task_id, owner=_owner(), transport=transport
            )
            await db.commit()
            return result

    results = await asyncio.gather(pump_one(task_one), pump_one(task_two))

    assert [result.commands_processed for result in results] == [1, 1]
    assert sorted(seen) == sorted(
        [(task_one, command_one[0]), (task_two, command_two[0])]
    )
    async with maker() as db:
        assert await _row_status(db, command_one[0]) == "delivered"
        assert await _row_status(db, command_two[0]) == "delivered"


async def test_pump_promotion_is_task_scoped_under_concurrency(maker, monkeypatch):
    """Starting-gate probes must use the requested Task's attempt only."""
    from app.core import worker_command_pump as module

    task_one, _, _ = await _seed_task_with_commands(
        maker, control_state="starting", create_commands=False
    )
    task_two, _, _ = await _seed_task_with_commands(
        maker, control_state="starting", create_commands=False
    )
    probed: list[tuple[int, int]] = []

    async def probe(attempt, task, db):
        probed.append((attempt.task_id, task.id))
        await asyncio.sleep(0)
        return {"status": "ack"}

    monkeypatch.setattr(module, "_probe_bridge", probe)

    async def promote(task_id: int):
        async with maker() as db:
            result = await run_pump_cycle(
                db, task_id=task_id, owner=_owner(), transport=_ack_transport
            )
            await db.commit()
            return result

    results = await asyncio.gather(promote(task_one), promote(task_two))

    assert [result.attempts_seen for result in results] == [1, 1]
    assert sorted(probed) == [(task_one, task_one), (task_two, task_two)]


async def test_pump_closing_and_recovery_are_task_scoped_under_concurrency(maker):
    """Closing and crash recovery must retain the same Task boundary too."""
    task_one, attempt_one, commands_one = await _seed_task_with_commands(maker, count=1)
    task_two, attempt_two, commands_two = await _seed_task_with_commands(maker, count=1)
    async with maker() as db:
        await db.execute(
            sa.text(
                "UPDATE task_harness_attempts SET control_state = 'closing' "
                "WHERE attempt_id IN (:a1, :a2)"
            ),
            {"a1": attempt_one, "a2": attempt_two},
        )
        await db.commit()

    closing_seen: list[tuple[int, str]] = []

    async def close_pump(task_id: int):
        async with maker() as db:
            async def transport(frame, **_kwargs):
                closing_seen.append((frame["task_id"], frame["type"]))
                await asyncio.sleep(0)
                return {"status": "ack"}

            result = await run_pump_cycle(
                db, task_id=task_id, owner=_owner(), transport=transport
            )
            await db.commit()
            return result

    close_results = await asyncio.gather(close_pump(task_one), close_pump(task_two))

    assert [result.commands_processed for result in close_results] == [1, 1]
    assert sorted(closing_seen) == sorted(
        [(task_one, "steer"), (task_one, "close"), (task_two, "steer"), (task_two, "close")]
    )
    async with maker() as db:
        states = (
            await db.execute(
                sa.text(
                    "SELECT task_id, control_state FROM task_harness_attempts "
                    "WHERE attempt_id IN (:a1, :a2) ORDER BY task_id"
                ),
                {"a1": attempt_one, "a2": attempt_two},
            )
        ).all()
        assert [row.control_state for row in states] == ["closed", "closed"]

    recovery_one, _, recovery_commands_one = await _seed_task_with_commands(maker, count=1)
    recovery_two, _, recovery_commands_two = await _seed_task_with_commands(maker, count=1)
    async with maker() as db:
        await db.execute(
            sa.text(
                "UPDATE task_harness_commands SET status = 'dispatching', "
                "dispatch_started_at = now(), delivery_attempts = 1 "
                "WHERE command_id IN (:c1, :c2)"
            ),
            {"c1": recovery_commands_one[0], "c2": recovery_commands_two[0]},
        )
        await db.commit()

    recovery_transport_calls: list[int] = []

    async def recover_pump(task_id: int):
        async with maker() as db:
            async def must_not_send(frame, **_kwargs):
                recovery_transport_calls.append(frame["task_id"])
                return {"status": "ack"}

            result = await run_pump_cycle(
                db, task_id=task_id, owner=_owner(), transport=must_not_send
            )
            await db.commit()
            return result

    recovery_results = await asyncio.gather(
        recover_pump(recovery_one), recover_pump(recovery_two)
    )

    assert [result.commands_processed for result in recovery_results] == [1, 1]
    assert recovery_transport_calls == []
    async with maker() as db:
        rows = (
            await db.execute(
                sa.text(
                    "SELECT task_id, status, rejection_code FROM task_harness_commands "
                    "WHERE command_id IN (:c1, :c2) ORDER BY task_id"
                ),
                {"c1": recovery_commands_one[0], "c2": recovery_commands_two[0]},
            )
        ).all()
        assert [row.status for row in rows] == ["outcome_unknown", "outcome_unknown"]
        assert [row.rejection_code for row in rows] == [
            "delivery_outcome_unknown",
            "delivery_outcome_unknown",
        ]


async def test_pump_journals_reject_to_rejected(maker):
    task_id, _, command_ids = await _seed_task_with_commands(maker, count=1)
    async with maker() as db:
        result = await run_pump_cycle(
            db, task_id=task_id, owner=_owner(), transport=_reject_transport
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
    task_id, _, command_ids = await _seed_task_with_commands(maker, count=1)
    async with maker() as db:
        result = await run_pump_cycle(
            db, task_id=task_id, owner=_owner(), transport=_unknown_transport
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
    task_id, _, command_ids = await _seed_task_with_commands(maker, count=1)

    async def exploding_transport(frame, **kwargs):
        raise RuntimeError("daemon unreachable")

    async with maker() as db:
        result = await run_pump_cycle(
            db, task_id=task_id, owner=_owner(), transport=exploding_transport
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


@pytest.mark.asyncio
async def test_control_transport_has_a_bounded_remote_docker_wait(monkeypatch):
    """A hung remote Docker exec must not pin the scheduler command pump."""
    from types import SimpleNamespace

    from app.core import worker_command_pump as module
    from app.core import worker_docker_targets

    async def find_container(*_args, **_kwargs):
        return None, SimpleNamespace(id="container-1"), SimpleNamespace()

    async def slow_to_thread(*_args, **_kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(worker_docker_targets, "find_task_container", find_container)
    monkeypatch.setattr(module.asyncio, "to_thread", slow_to_thread)
    monkeypatch.setattr(module, "CONTROL_TRANSPORT_TIMEOUT_SECONDS", 0.01)

    result = await docker_exec_control_transport(
        {"type": "close"},
        SimpleNamespace(),
        task=SimpleNamespace(id=1, issue_id=1, container_id="container-1"),
    )

    assert result == {
        "status": "unknown",
        "rejection_code": "delivery_outcome_unknown",
        "rejection_message": "control transport timed out",
    }


@pytest.mark.asyncio
async def test_control_container_lookup_has_a_bounded_remote_docker_wait(monkeypatch):
    """A hung container lookup must not prevent later close retries."""
    from types import SimpleNamespace

    from app.core import worker_command_pump as module
    from app.core import worker_docker_targets

    async def slow_find_container(*_args, **_kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(
        worker_docker_targets,
        "find_task_container",
        slow_find_container,
    )
    monkeypatch.setattr(module, "CONTROL_TRANSPORT_TIMEOUT_SECONDS", 0.01)

    result = await docker_exec_control_transport(
        {"type": "close"},
        SimpleNamespace(),
        task=SimpleNamespace(id=1, issue_id=1, container_id="container-1"),
    )

    assert result == {
        "status": "unknown",
        "rejection_code": "delivery_outcome_unknown",
        "rejection_message": "control container lookup timed out",
    }


async def test_pump_does_not_claim_closed_control_gate(maker):
    task_id, _, _ = await _seed_task_with_commands(
        maker, control_state="closed", count=1, create_commands=False
    )
    async with maker() as db:
        result = await run_pump_cycle(
            db, task_id=task_id, owner=_owner(), transport=_ack_transport
        )
        await db.commit()
        assert result.attempts_seen == 0
        assert result.commands_processed == 0


async def test_pre_drained_closing_attempt_is_claimed_and_closed(maker):
    task_id, attempt_id, _ = await _seed_task_with_commands(
        maker, control_state="closing", create_commands=False
    )
    seen = []

    async def transport(frame, **_kwargs):
        seen.append(frame["type"])
        return {"status": "ack"}

    async with maker() as db:
        result = await run_pump_cycle(
            db, task_id=task_id, owner=_owner(), transport=transport
        )
        await db.commit()

        assert result.attempts_seen == 1
        assert result.commands_processed == 0
        assert seen == ["close"]
        state = (
            await db.execute(
                sa.text(
                    "SELECT control_state FROM task_harness_attempts "
                    "WHERE attempt_id = :a"
                ),
                {"a": attempt_id},
            )
        ).scalar_one()
        assert state == "closed"


async def test_closing_queue_drains_then_owner_ack_closes_gate(maker):
    task_id, attempt_id, command_ids = await _seed_task_with_commands(maker, count=1)
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
        result = await run_pump_cycle(
            db, task_id=task_id, owner=_owner(), transport=transport
        )
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
    task_id, attempt_id, command_ids = await _seed_task_with_commands(maker, count=1)
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
        await run_pump_cycle(
            db, task_id=task_id, owner=_owner(), transport=transport
        )
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
        attempt = (
            await db.execute(
                select(TaskHarnessAttempt).where(TaskHarnessAttempt.attempt_id == attempt_id)
            )
        ).scalar_one()
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
        attempt = (
            await db.execute(
                select(TaskHarnessAttempt).where(TaskHarnessAttempt.attempt_id == attempt_id)
            )
        ).scalar_one()
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
    cycle_kwargs = []
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
        cycle_kwargs.append(_kwargs)
        return module.PumpCycleResult(attempts_seen=0, commands_processed=0, commands_updated=0)

    monkeypatch.setattr(module, "run_pump_cycle", cycle)
    processed = await module.run_pump_until_task_ends(
        1, session_factory=Factory(), owner="test", interval_seconds=0
    )
    assert processed == 0
    assert cycles == [True]
    assert cycle_kwargs[0]["task_id"] == 1
    assert cycle_kwargs[0]["owner"] == "test"
    assert callable(cycle_kwargs[0]["transport"])
    # The QUEUED wait occurs after the first context exited; a backlog cannot
    # pin one DB connection per scheduler thread during startup.
    assert len(closed_contexts) == 3


async def test_dispatch_one_command_returns_final_status(maker):
    task_id, attempt_id, command_ids = await _seed_task_with_commands(maker, count=1)
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
            db,
            task_id=task_id,
            command=cmd,
            attempt=attempt,
            transport=_ack_transport,
            owner="x",
        )
        await db.commit()
        assert status == "delivered"


async def test_pump_recovers_dispatching_as_outcome_unknown(maker):
    """Crash after durable dispatch claim never causes a second native send."""
    task_id, _, command_ids = await _seed_task_with_commands(maker, count=1)
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

        await run_pump_cycle(
            db, task_id=task_id, owner=_owner(), transport=must_not_send
        )
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
