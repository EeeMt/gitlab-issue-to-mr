"""Behavioral tests for migration 068 (issue sequence + lineage backfill).

The concurrency suite in ``test_issue_execution_lock_concurrency.py`` covers
§10.2; this module covers §10.1's migration behavior on a real PostgreSQL
instance: historical sequence backfill by ``(created_at, id)``, uniqueness within
an issue (cross-issue sharing allowed), projected-lineage backfill for
fresh/continue/namespace-change, the ``legacy`` namespace for terminal tasks
without a frozen snapshot, NULL projections for active tasks without one, and
legacy ``IssueHarnessSession`` import for generation 0 only (reset generations
never import legacy pointers).

Each test runs against a throwaway database ``codify_migration_<uuid>`` created
by the codify user's CREATEDB privilege, so the shared ``codify_test`` schema is
never touched. The module fixture upgrades the fresh DB to ``067_harness_key``;
each test seeds historical rows at that schema, applies ``068_issue_sequence_lineage``
through alembic, and asserts the backfilled data. Downgrading back to 067 between
tests re-arms the 068 upgrade so every test exercises the real backfill. The
module is skipped when the test database is unreachable.

The one content check kept (revision id length) guards an operational constraint:
``alembic_version.version_num`` is ``varchar(32)``, so a longer revision id would
break ``alembic upgrade`` on any database that has not yet applied 068.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command

ADMIN_URL = os.environ.get(
    "CODIFY_TEST_DATABASE_URL",
    "postgresql+asyncpg://codify:codify_password@192.168.50.129:5432/codify_test",
)
HOST_BASE = ADMIN_URL.rsplit("/", 1)[0] + "/"
BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
ALEMBIC_DIR = BACKEND_DIR / "alembic"

_SEED_TABLES = (
    "issue_harness_sessions, task_worker_profile_snapshots, tasks, issues, worker_profiles"
)


def test_revision_id_fits_alembic_version_varchar32():
    # alembic_version.version_num is varchar(32); a longer revision id makes
    # ``alembic upgrade`` fail on any database that has not yet applied 068.
    assert len("068_issue_sequence_lineage") <= 32


# ── throwaway database plumbing ──────────────────────────────────────────────


def _alembic_config(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    # env.py runs fileConfig(config.config_file_name), which reconfigures the
    # root logger and breaks assertLogs in later tests. Nulling the file name
    # keeps alembic's logging out of the process; the ini section is still loaded
    # programmatically below.
    cfg.config_file_name = None
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
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
    """Throwaway DB upgraded to 067_harness_key, dropped after the module."""
    dbname = f"codify_migration_{uuid.uuid4().hex[:8]}"
    url = HOST_BASE + dbname
    cfg = _alembic_config(url)
    asyncio.run(_create_database(dbname))
    # alembic env.py prefers DATABASE_URL, but the Config's sqlalchemy.url is set
    # too; restore the caller's value so this module never leaks a pointer to the
    # dropped DB into later tests.
    original_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        _upgrade(cfg, "067_harness_key")
        yield {"url": url, "cfg": cfg, "dbname": dbname}
    finally:
        asyncio.run(_drop_database(dbname))
        if original_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_url


@pytest.fixture
async def maker(migration_db):
    """Per-test async session factory; NullPool keeps each test on its own loop."""
    engine = create_async_engine(migration_db["url"], poolclass=NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
async def seeded_067(maker, migration_db):
    """Re-arm the 068 upgrade and clear the seed tables for one test."""
    cfg = migration_db["cfg"]
    await asyncio.to_thread(_downgrade, cfg, "067_harness_key")
    async with maker() as db:
        await db.execute(sa.text(f"TRUNCATE {_SEED_TABLES} RESTART IDENTITY CASCADE"))
        await db.commit()
    # PT022: deliberately a generator so tests can ``async with seeded_067() as db``.
    yield maker  # noqa: PT022


def _upgrade(cfg: Config, revision: str) -> None:
    command.upgrade(cfg, revision)


def _downgrade(cfg: Config, revision: str) -> None:
    command.downgrade(cfg, revision)


async def _apply_068(cfg: Config) -> None:
    await asyncio.to_thread(_upgrade, cfg, "068_issue_sequence_lineage")


# ── seed helpers (067 schema, raw SQL) ───────────────────────────────────────


async def _insert_worker_profile(db) -> int:
    return (
        await db.execute(
            sa.text(
                "INSERT INTO worker_profiles (name, image, "
                "default_execute_run_instruction_template, "
                "default_plan_run_instruction_template, "
                "ci_auto_repair_run_instruction_template) "
                "VALUES (:name, 'img', '', '', '') RETURNING id"
            ),
            {"name": f"wp-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()


async def _insert_issue(db, *, worker_profile_id: int | None = None) -> int:
    if worker_profile_id is None:
        worker_profile_id = await _insert_worker_profile(db)
    return (
        await db.execute(
            sa.text(
                "INSERT INTO issues (title, project_id, worker_profile_id, "
                "ci_auto_repair_enabled) VALUES ('migration-test', 1, :wp, false) "
                "RETURNING id"
            ),
            {"wp": worker_profile_id},
        )
    ).scalar_one()


async def _insert_snapshot(
    db, task_id: int, *, harness_key: str, fingerprint: str | None = None
) -> None:
    endpoint = None if fingerprint is None else json.dumps({"fingerprint": fingerprint})
    await db.execute(
        sa.text(
            "INSERT INTO task_worker_profile_snapshots (task_id, profile_name, image, "
            "harness_key, model_endpoint_snapshot, "
            "default_execute_run_instruction_template, "
            "default_plan_run_instruction_template, "
            "ci_auto_repair_run_instruction_template) "
            "VALUES (:tid, 'profile', 'img', :hk, CAST(:endpoint AS json), '', '', '')"
        ),
        {"tid": task_id, "hk": harness_key, "endpoint": endpoint},
    )


async def _insert_task(
    db,
    issue_id: int,
    *,
    created_at: str,
    status: str = "completed",
    session_mode: str = "continue",
    output_session_id: str | None = None,
    snapshot: tuple[str, str | None] | None = None,
) -> int:
    task_id = (
        await db.execute(
            sa.text(
                "INSERT INTO tasks (issue_id, project_id, user_prompt, trigger_source, "
                "status, session_mode, created_at, output_session_id) "
                "VALUES (:iid, 1, 'prompt', 'manual', :status, :mode, :created, :out) "
                "RETURNING id"
            ),
            {
                "iid": issue_id,
                "status": status,
                "mode": session_mode,
                "created": datetime.fromisoformat(created_at),
                "out": output_session_id,
            },
        )
    ).scalar_one()
    if snapshot is not None:
        await _insert_snapshot(db, task_id, harness_key=snapshot[0], fingerprint=snapshot[1])
    return task_id


async def _insert_legacy_session(
    db, issue_id: int, *, harness_key: str, namespace: str, session_id: str
) -> None:
    await db.execute(
        sa.text(
            "INSERT INTO issue_harness_sessions (issue_id, harness_key, "
            "session_namespace, session_id, created_at, updated_at) "
            "VALUES (:iid, :hk, :ns, :sid, now(), now())"
        ),
        {"iid": issue_id, "hk": harness_key, "ns": namespace, "sid": session_id},
    )


def _namespace(harness_key: str, fingerprint: str | None) -> str:
    # Mirrors migration 068._session_namespace_for / app.core.harness_sessions.
    material = f"{harness_key}|{fingerprint or ''}|state-1"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"{harness_key}-{digest}"


async def _task_projection(db, task_id: int) -> dict:
    return dict(
        (
            await db.execute(
                sa.text(
                    "SELECT issue_sequence, projected_harness_key, "
                    "projected_session_namespace, projected_lineage_generation, "
                    "projected_reset_task_id, lineage_projection_reason "
                    "FROM tasks WHERE id = :tid"
                ),
                {"tid": task_id},
            )
        )
        .mappings()
        .one()
    )


async def _lineage_rows(db, issue_id: int) -> list[dict]:
    return [
        dict(row)
        for row in (
            await db.execute(
                sa.text(
                    "SELECT lineage_generation, harness_key, session_namespace, "
                    "reset_task_id, session_id, last_output_task_id, "
                    "last_output_issue_sequence, lineage_reason "
                    "FROM issue_session_lineages WHERE issue_id = :iid "
                    "ORDER BY lineage_generation"
                ),
                {"iid": issue_id},
            )
        )
        .mappings()
        .all()
    ]


# ── §10.1 migration behavior ─────────────────────────────────────────────────


async def test_sequence_backfill_orders_by_created_at_then_id(seeded_067, migration_db):
    """Historical tasks get contiguous per-issue sequences in (created_at, id) order."""
    async with seeded_067() as db:
        issue = await _insert_issue(db)
        t1 = await _insert_task(db, issue, created_at="2026-01-01 00:00:00")
        t3 = await _insert_task(db, issue, created_at="2026-01-03 00:00:00")
        t2 = await _insert_task(db, issue, created_at="2026-01-02 00:00:00")
        issue2 = await _insert_issue(db)
        u1 = await _insert_task(db, issue2, created_at="2026-02-01 00:00:00")
        u2 = await _insert_task(db, issue2, created_at="2026-02-02 00:00:00")
        await db.commit()

    await _apply_068(migration_db["cfg"])

    async with seeded_067() as db:
        assert (await _task_projection(db, t1))["issue_sequence"] == 1
        assert (await _task_projection(db, t2))["issue_sequence"] == 2
        assert (await _task_projection(db, t3))["issue_sequence"] == 3
        assert (await _task_projection(db, u1))["issue_sequence"] == 1
        assert (await _task_projection(db, u2))["issue_sequence"] == 2
        # No duplicate sequence within an issue (cross-issue sharing is allowed).
        for iid in (issue, issue2):
            dups = (
                await db.execute(
                    sa.text(
                        "SELECT issue_sequence FROM tasks WHERE issue_id = :iid "
                        "GROUP BY issue_sequence HAVING COUNT(*) > 1"
                    ),
                    {"iid": iid},
                )
            ).all()
            assert dups == []


async def test_unique_sequence_index_rejects_duplicate_within_issue(seeded_067, migration_db):
    """The 068 partial unique index enforces per-issue sequence uniqueness."""
    async with seeded_067() as db:
        issue = await _insert_issue(db)
        await _insert_task(db, issue, created_at="2026-01-01 00:00:00")
        await db.commit()

    await _apply_068(migration_db["cfg"])

    async with seeded_067() as db:
        with pytest.raises(IntegrityError):
            await db.execute(
                sa.text(
                    "INSERT INTO tasks (issue_id, project_id, user_prompt, "
                    "trigger_source, status, session_mode, created_at, "
                    "issue_sequence) VALUES (:iid, 1, 'dup', 'manual', 'pending', "
                    "'continue', now(), 1)"
                ),
                {"iid": issue},
            )


async def test_lineage_generation_reset_and_namespace_change(seeded_067, migration_db):
    """Fresh/continue/namespace-change map to the correct generation/reset/reason."""
    async with seeded_067() as db:
        issue = await _insert_issue(db)
        t1 = await _insert_task(
            db, issue, created_at="2026-01-01 00:00:00", session_mode="fresh",
            output_session_id="out-1", snapshot=("claude", "f1"),
        )
        t2 = await _insert_task(
            db, issue, created_at="2026-01-02 00:00:00", session_mode="continue",
            output_session_id="out-2", snapshot=("claude", "f1"),
        )
        t3 = await _insert_task(
            db, issue, created_at="2026-01-03 00:00:00", session_mode="continue",
            snapshot=("claude", "f1"),
        )
        t4 = await _insert_task(
            db, issue, created_at="2026-01-04 00:00:00", session_mode="fresh",
            output_session_id="out-4", snapshot=("claude", "f1"),
        )
        t5 = await _insert_task(
            db, issue, created_at="2026-01-05 00:00:00", session_mode="continue",
            snapshot=("codex", "f2"),
        )
        await db.commit()

    await _apply_068(migration_db["cfg"])

    ns_f1 = _namespace("claude", "f1")
    ns_f2 = _namespace("codex", "f2")
    async with seeded_067() as db:
        assert await _task_projection(db, t1) == {
            "issue_sequence": 1, "projected_harness_key": "claude",
            "projected_session_namespace": ns_f1, "projected_lineage_generation": 1,
            "projected_reset_task_id": t1, "lineage_projection_reason": "initial",
        }
        assert await _task_projection(db, t2) == {
            "issue_sequence": 2, "projected_harness_key": "claude",
            "projected_session_namespace": ns_f1, "projected_lineage_generation": 1,
            "projected_reset_task_id": t1, "lineage_projection_reason": "inherited",
        }
        assert await _task_projection(db, t3) == {
            "issue_sequence": 3, "projected_harness_key": "claude",
            "projected_session_namespace": ns_f1, "projected_lineage_generation": 1,
            "projected_reset_task_id": t1, "lineage_projection_reason": "inherited",
        }
        assert await _task_projection(db, t4) == {
            "issue_sequence": 4, "projected_harness_key": "claude",
            "projected_session_namespace": ns_f1, "projected_lineage_generation": 2,
            "projected_reset_task_id": t4, "lineage_projection_reason": "fresh",
        }
        assert await _task_projection(db, t5) == {
            "issue_sequence": 5, "projected_harness_key": "codex",
            "projected_session_namespace": ns_f2, "projected_lineage_generation": 3,
            "projected_reset_task_id": t5, "lineage_projection_reason": "legacy_namespace_change",
        }

        assert await _lineage_rows(db, issue) == [
            {
                "lineage_generation": 1, "harness_key": "claude",
                "session_namespace": ns_f1, "reset_task_id": t1, "session_id": "out-2",
                "last_output_task_id": t2, "last_output_issue_sequence": 2,
                # lineage_reason mirrors the most recent Task's projection reason
                # in the generation (t3 is inherited), matching the runtime write
                # convention in issue_task_lineage.py.
                "lineage_reason": "inherited",
            },
            {
                "lineage_generation": 2, "harness_key": "claude",
                "session_namespace": ns_f1, "reset_task_id": t4, "session_id": "out-4",
                "last_output_task_id": t4, "last_output_issue_sequence": 4,
                "lineage_reason": "fresh",
            },
            {
                "lineage_generation": 3, "harness_key": "codex",
                "session_namespace": ns_f2, "reset_task_id": t5, "session_id": None,
                "last_output_task_id": None, "last_output_issue_sequence": None,
                "lineage_reason": "legacy_namespace_change",
            },
        ]


async def test_terminal_without_snapshot_legacy_active_without_snapshot_null(
    seeded_067, migration_db
):
    """Terminal tasks without a frozen snapshot map to legacy; active ones stay NULL."""
    async with seeded_067() as db:
        issue = await _insert_issue(db)
        t1 = await _insert_task(db, issue, created_at="2026-01-01 00:00:00", status="completed")
        t2 = await _insert_task(db, issue, created_at="2026-01-02 00:00:00", status="running")
        t3 = await _insert_task(db, issue, created_at="2026-01-03 00:00:00", status="completed")
        await db.commit()

    await _apply_068(migration_db["cfg"])

    async with seeded_067() as db:
        p1 = await _task_projection(db, t1)
        assert p1["issue_sequence"] == 1
        assert p1["projected_harness_key"] == "legacy"
        assert p1["projected_session_namespace"] == "legacy"
        assert p1["projected_lineage_generation"] == 0
        assert p1["projected_reset_task_id"] is None
        assert p1["lineage_projection_reason"] == "initial"

        p2 = await _task_projection(db, t2)
        assert p2["issue_sequence"] == 2
        assert p2["projected_harness_key"] is None
        assert p2["projected_session_namespace"] is None
        assert p2["projected_lineage_generation"] is None
        assert p2["projected_reset_task_id"] is None
        assert p2["lineage_projection_reason"] is None

        p3 = await _task_projection(db, t3)
        assert p3["issue_sequence"] == 3
        assert p3["projected_harness_key"] == "legacy"
        assert p3["projected_session_namespace"] == "legacy"
        assert p3["projected_lineage_generation"] == 0
        assert p3["projected_reset_task_id"] is None
        assert p3["lineage_projection_reason"] == "inherited"

        rows = await _lineage_rows(db, issue)
        assert rows == [
            {
                "lineage_generation": 0, "harness_key": "legacy",
                "session_namespace": "legacy", "reset_task_id": None,
                "session_id": None, "last_output_task_id": None,
                "last_output_issue_sequence": None,
                # The generation was established by t1 (initial) but the most
                # recent Task in it (t3) was inherited.
                "lineage_reason": "inherited",
            }
        ]


async def test_legacy_session_import_for_generation_zero_only(seeded_067, migration_db):
    """Generation 0 imports a legacy pointer; a reset generation never does."""
    async with seeded_067() as db:
        issue = await _insert_issue(db)
        ns_f1 = _namespace("claude", "f1")
        ns_f2 = _namespace("codex", "f2")
        await _insert_legacy_session(
            db, issue, harness_key="claude", namespace=ns_f1, session_id="legacy-claude-sess"
        )
        await _insert_legacy_session(
            db, issue, harness_key="codex", namespace=ns_f2, session_id="legacy-codex-sess"
        )
        await _insert_task(
            db, issue, created_at="2026-01-01 00:00:00", session_mode="continue",
            snapshot=("claude", "f1"),
        )
        t2 = await _insert_task(
            db, issue, created_at="2026-01-02 00:00:00", session_mode="fresh",
            snapshot=("codex", "f2"),
        )
        await db.commit()

    await _apply_068(migration_db["cfg"])

    async with seeded_067() as db:
        rows = await _lineage_rows(db, issue)
        assert len(rows) == 2
        assert rows[0] == {
            "lineage_generation": 0, "harness_key": "claude",
            "session_namespace": ns_f1, "reset_task_id": None,
            "session_id": "legacy-claude-sess", "last_output_task_id": None,
            "last_output_issue_sequence": None, "lineage_reason": "imported_legacy",
        }
        # t2 is a fresh (reset) generation with no output evidence; even though a
        # matching legacy codex pointer exists, it must NOT be imported.
        assert rows[1] == {
            "lineage_generation": 1, "harness_key": "codex",
            "session_namespace": ns_f2, "reset_task_id": t2,
            "session_id": None, "last_output_task_id": None,
            "last_output_issue_sequence": None, "lineage_reason": "fresh",
        }
