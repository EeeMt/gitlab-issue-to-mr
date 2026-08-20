"""Behavioral test for migration 074 (open-harness v2 foundation).

Runs the real ``074_open_harness_v2`` upgrade through alembic on a throwaway
PostgreSQL database and asserts the V2 foundation semantics from
open-harness-v2-phase1-design.md §1:

- ``ai_providers.wire_protocol`` is renamed to ``model_protocol`` (RENAME, no
  data change, no legacy alias) and the new nullable ``compat_profile`` column
  exists; pre-existing provider rows read back byte-for-byte unchanged.
- ``worker_profiles.harness_options`` defaults to ``{}``.
- ``task_harness_attempts`` gains the control gate / sequence / lease columns
  with ``control_state`` backfilled ``disabled`` for historical V1 attempts.
- ``task_harness_commands`` exists with the attempt-scoped unique sequence and
  status/consistency checks.

The module fixture upgrades the fresh DB to ``073_task_freeform_mode``; each
test re-arms by downgrading to 073. Skipped when the test database is
unreachable.
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

ADMIN_URL = os.environ.get(
    "CODIFY_TEST_DATABASE_URL",
    "postgresql+asyncpg://codify:codify_password@192.168.50.129:5432/codify_test",
)
HOST_BASE = ADMIN_URL.rsplit("/", 1)[0] + "/"
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
ALEMBIC_INI = os.path.join(BACKEND_DIR, "alembic.ini")
ALEMBIC_DIR = os.path.join(BACKEND_DIR, "alembic")


def test_074_revision_id_fits_alembic_version_varchar32():
    assert len("074_open_harness_v2") <= 32


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
def migration_db():
    dbname = f"codify_migration_074_{uuid.uuid4().hex[:8]}"
    url = HOST_BASE + dbname
    cfg = _alembic_config(url)
    try:
        asyncio.run(_create_database(dbname))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"074 migration DB unreachable: {exc!r}")
    original_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(cfg, "073_task_freeform_mode")
        yield {"url": url, "cfg": cfg, "dbname": dbname}
    finally:
        asyncio.run(_drop_database(dbname))
        if original_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_url


@pytest.fixture
async def maker(migration_db):
    engine = create_async_engine(migration_db["url"], poolclass=NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
async def seeded_073(maker, migration_db):
    """Re-arm the 074 upgrade: downgrade to 073 and clear seed tables."""
    cfg = migration_db["cfg"]
    await asyncio.to_thread(command.downgrade, cfg, "073_task_freeform_mode")
    async with maker() as db:
        await db.execute(
            sa.text(
                "TRUNCATE task_harness_attempts, ai_providers, worker_profiles "
                "RESTART IDENTITY CASCADE"
            )
        )
        await db.commit()
    yield maker  # noqa: PT022


async def _insert_073_provider(db, *, name, wire_protocol="anthropic_messages"):
    """Insert a pre-074 provider row (wire_protocol name still valid at 073)."""
    return (
        await db.execute(
            sa.text(
                "INSERT INTO ai_providers (name, base_url, api_key, model, max_turns, "
                "system_prompt, is_default, is_disabled, provider_kind, wire_protocol, "
                "provider_driver, provider_options, created_at, updated_at) "
                "VALUES (:name, 'https://api.example.com/v1', 'sk-test-123', "
                "'deepseek-v4', 20, NULL, false, false, 'anthropic_compatible', "
                ":wire_protocol, 'anthropic', '{}', now(), now()) RETURNING id"
            ),
            {"name": name, "wire_protocol": wire_protocol},
        )
    ).scalar_one()


async def _insert_073_attempt(db, *, task_id, attempt_no=1, event_schema="codify.worker.event/v1"):
    return (
        await db.execute(
            sa.text(
                "INSERT INTO task_harness_attempts (attempt_id, task_id, attempt_no, "
                "event_schema, harness_key, adapter_version, cli_version, last_seq, "
                "created_at, updated_at) "
                "VALUES (:aid, :task_id, :attempt_no, :event_schema, 'claude', '1.0.0', "
                "'2.1.152', 0, now(), now()) RETURNING attempt_id"
            ),
            {
                "aid": f"task-{task_id}-attempt-{attempt_no}",
                "task_id": task_id,
                "attempt_no": attempt_no,
                "event_schema": event_schema,
            },
        )
    ).scalar_one()


async def _insert_task(db, *, issue_id, project_id=1) -> int:
    return (
        await db.execute(
            sa.text(
                "INSERT INTO tasks (issue_id, project_id, user_prompt, status, priority, "
                "additions, deletions, total_changes, require_changes, task_mode, "
                "trigger_source, session_mode, issue_sequence, created_at, updated_at) "
                "VALUES (:issue_id, :project_id, 'do the thing', 'pending', 0, 0, 0, 0, "
                "true, 'execute', 'manual', 'continue', 1, now(), now()) RETURNING id"
            ),
            {"issue_id": issue_id, "project_id": project_id},
        )
    ).scalar_one()


async def _insert_issue(db, *, project_id=1, worker_profile_id=None) -> int:
    if worker_profile_id is None:
        worker_profile_id = (
            await db.execute(
                sa.text(
                    "INSERT INTO worker_profiles (name, image) "
                    "VALUES ('seed', 'codify-worker:latest') RETURNING id"
                )
            )
        ).scalar_one()
    return (
        await db.execute(
            sa.text(
                "INSERT INTO issues (title, description, project_id, status, "
                "worker_profile_id, ci_auto_repair_enabled, created_at, updated_at) "
                "VALUES (:title, 'desc', :project_id, 'open', :wp, "
                "true, now(), now()) RETURNING id"
            ),
            {"title": "issue", "project_id": project_id, "wp": worker_profile_id},
        )
    ).scalar_one()


# ── §1 migration behavior ────────────────────────────────────────────────────


async def test_074_renames_wire_protocol_keeps_data(seeded_073, migration_db):
    """V1 provider data survives the RENAME byte-for-byte; column is model_protocol."""
    async with seeded_073() as db:
        await _insert_073_provider(db, name="V1 Provider")
        await db.commit()

    await asyncio.to_thread(
        command.upgrade, migration_db["cfg"], "074_open_harness_v2"
    )
    async with seeded_073() as db:
        columns = {
            row[0]
            for row in await db.execute(
                sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'ai_providers'"
                )
            )
        }
        assert "wire_protocol" not in columns
        assert "model_protocol" in columns
        assert "compat_profile" in columns

        # Read from the ORM/V1-reader perspective (model_protocol column).
        row = (
            await db.execute(
                sa.text(
                    "SELECT name, model_protocol FROM ai_providers "
                    "WHERE name = 'V1 Provider'"
                )
            )
        ).first()
        assert row is not None
        assert row.model_protocol == "anthropic_messages"


async def test_074_adds_compat_profile_and_harness_options(seeded_073, migration_db):
    """New columns exist post-upgrade; harness_options defaults to {}."""
    await asyncio.to_thread(
        command.upgrade, migration_db["cfg"], "074_open_harness_v2"
    )
    async with seeded_073() as db:
        # worker_profiles.harness_options default
        profile_id = (
            await db.execute(
                sa.text(
                    "INSERT INTO worker_profiles (name, image) "
                    "VALUES ('p', 'codify-worker:latest') RETURNING id"
                )
            )
        ).scalar_one()
        assert (
            await db.execute(
                sa.text("SELECT harness_options FROM worker_profiles WHERE id = :p"),
                {"p": profile_id},
            )
        ).scalar_one() == {}


async def test_074_attempts_backfill_control_state_disabled(seeded_073, migration_db):
    """Historical V1 attempts get control_state='disabled', seq=1, NULL lease."""
    # Seed a V1 attempt at 073, then upgrade; the backfill must apply.
    issue_id = None
    task_id = None
    attempt_id = None
    async with seeded_073() as db:
        issue_id = await _insert_issue(db, worker_profile_id=None)
        task_id = await _insert_task(db, issue_id=issue_id)
        attempt_id = await _insert_073_attempt(db, task_id=task_id)
        await db.commit()

    await asyncio.to_thread(
        command.upgrade, migration_db["cfg"], "074_open_harness_v2"
    )
    async with seeded_073() as db:
        row = (
            await db.execute(
                sa.text(
                    "SELECT control_state, next_command_sequence, command_dispatch_owner, "
                    "command_dispatch_expires_at FROM task_harness_attempts "
                    "WHERE attempt_id = :a"
                ),
                {"a": attempt_id},
            )
        ).one()
        assert row.control_state == "disabled"
        assert row.next_command_sequence == 1
        assert row.command_dispatch_owner is None
        assert row.command_dispatch_expires_at is None


async def test_074_commands_table_constraints_and_cascade(seeded_073, migration_db):
    """Command unique sequence, status checks, and cascade-on-delete behavior."""
    await asyncio.to_thread(
        command.upgrade, migration_db["cfg"], "074_open_harness_v2"
    )
    async with seeded_073() as db:
        issue_id = await _insert_issue(db)
        task_id = await _insert_task(db, issue_id=issue_id)
        attempt_id = await _insert_073_attempt(db, task_id=task_id)
        await db.commit()

        # Insert a valid command.
        await db.execute(
            sa.text(
                "INSERT INTO task_harness_commands (command_id, task_id, attempt_id, "
                "sequence_no, command_type, payload, payload_digest, status, created_by, "
                "created_at, delivery_attempts) "
                "VALUES ("
                "  'cmd-1', :task_id, :attempt_id, 1, 'steer', "
                "  CAST('{\"text\":\"go\"}' AS json), 'digest-1', 'queued', 'user', "
                "  now(), 0)"
            ),
            {"task_id": task_id, "attempt_id": attempt_id},
        )
        await db.commit()

        # Duplicate (attempt_id, sequence_no) violates the unique constraint.
        with pytest.raises(Exception):
            await db.execute(
                sa.text(
                    "INSERT INTO task_harness_commands (command_id, task_id, attempt_id, "
                    "sequence_no, command_type, payload, payload_digest, status, created_by, "
                    "created_at, delivery_attempts) "
                    "VALUES ("
                    "  'cmd-2', :task_id, :attempt_id, 1, 'steer', "
                    "  CAST('{\"text\":\"go\"}' AS json), 'digest-2', 'queued', 'user', "
                    "  now(), 0)"
                ),
                {"task_id": task_id, "attempt_id": attempt_id},
            )
            await db.commit()
        await db.rollback()

        # Invalid command_type rejected by check constraint.
        with pytest.raises(Exception):
            await db.execute(
                sa.text(
                    "INSERT INTO task_harness_commands (command_id, task_id, attempt_id, "
                    "sequence_no, command_type, payload, payload_digest, status, created_by, "
                    "created_at, delivery_attempts) "
                    "VALUES ("
                    "  'cmd-3', :task_id, :attempt_id, 2, 'explode', "
                    "  CAST('{\"text\":\"go\"}' AS json), 'digest-3', 'queued', 'user', "
                    "  now(), 0)"
                ),
                {"task_id": task_id, "attempt_id": attempt_id},
            )
            await db.commit()
        await db.rollback()

        # delivered state must be consistent with delivered_at NOT NULL.
        with pytest.raises(Exception):
            await db.execute(
                sa.text(
                    "INSERT INTO task_harness_commands (command_id, task_id, attempt_id, "
                    "sequence_no, command_type, payload, payload_digest, status, created_by, "
                    "created_at, delivered_at) "
                    "VALUES ("
                    "  'cmd-4', :task_id, :attempt_id, 3, 'steer', "
                    "  CAST('{\"text\":\"go\"}' AS json), 'digest-4', 'delivered', 'user', "
                    "  now(), NULL)"
                ),
                {"task_id": task_id, "attempt_id": attempt_id},
            )
            await db.commit()
        await db.rollback()

        # Deleting the attempt cascades its commands.
        await db.execute(
            sa.text("DELETE FROM task_harness_attempts WHERE attempt_id = :a"),
            {"a": attempt_id},
        )
        await db.commit()
        remaining = (
            await db.execute(
                sa.text(
                    "SELECT count(*) FROM task_harness_commands WHERE task_id = :t"
                ),
                {"t": task_id},
            )
        ).scalar_one()
        assert remaining == 0
