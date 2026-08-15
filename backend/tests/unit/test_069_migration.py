"""Behavioral test for migration 069 (system lifecycle statistics backfill).

Runs the real ``069_system_lifecycle_statistics`` upgrade through alembic on a
throwaway PostgreSQL database and asserts the §6.4 conservative backfill: only
pre-feature Tasks with a code-change field > 0 AND a self-consistent triple
(total == additions + deletions, all non-negative) are treated as recorded;
inconsistent and all-zero rows stay Unknown (change_stats_recorded_at NULL).

The module fixture upgrades the fresh DB to ``068_issue_sequence_lineage``;
the test seeds historical rows at that schema, applies 069 through alembic, and
asserts the markers. The module is skipped when the test database is
unreachable.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime
from pathlib import Path

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
BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
ALEMBIC_DIR = BACKEND_DIR / "alembic"

_SEED_TABLES = "task_worker_profile_snapshots, tasks, issues, worker_profiles"


def test_revision_id_fits_alembic_version_varchar32():
    # alembic_version.version_num is varchar(32); a longer revision id would
    # break ``alembic upgrade`` on any database that has not yet applied 069.
    assert len("069_system_lifecycle_statistics") <= 32


# ── throwaway database plumbing ──────────────────────────────────────────────


def _alembic_config(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    # env.py runs fileConfig(config.config_file_name), which reconfigures the
    # root logger and breaks assertLogs in later tests. Nulling the file name
    # keeps alembic's logging out of the process; the ini section is still
    # loaded programmatically below.
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
    """Throwaway DB upgraded to 068_issue_sequence_lineage, dropped after."""
    dbname = f"codify_migration_069_{uuid.uuid4().hex[:8]}"
    url = HOST_BASE + dbname
    cfg = _alembic_config(url)
    try:
        asyncio.run(_create_database(dbname))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"lifecycle migration DB unreachable: {exc!r}")
    original_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        _upgrade(cfg, "068_issue_sequence_lineage")
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
async def seeded_068(maker, migration_db):
    """Re-arm the 069 upgrade and clear the seed tables for one test."""
    cfg = migration_db["cfg"]
    await asyncio.to_thread(_downgrade, cfg, "068_issue_sequence_lineage")
    async with maker() as db:
        await db.execute(sa.text(f"TRUNCATE {_SEED_TABLES} RESTART IDENTITY CASCADE"))
        await db.commit()
    # PT022: deliberately a generator so tests can ``async with seeded_068() as db``.
    yield maker  # noqa: PT022


def _upgrade(cfg: Config, revision: str) -> None:
    command.upgrade(cfg, revision)


def _downgrade(cfg: Config, revision: str) -> None:
    command.downgrade(cfg, revision)


# ── seed helpers (068 schema, raw SQL) ───────────────────────────────────────


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


async def _insert_issue(db, *, worker_profile_id: int) -> int:
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


async def _insert_task(
    db,
    issue_id: int,
    *,
    status: str = "completed",
    created_at: str,
    additions: int,
    deletions: int,
    total_changes: int,
) -> int:
    return (
        await db.execute(
            sa.text(
                "INSERT INTO tasks (issue_id, project_id, user_prompt, trigger_source, "
                "status, created_at, additions, deletions, total_changes) "
                "VALUES (:iid, 1, 'prompt', 'manual', :status, :created, "
                ":add, :del, :total) RETURNING id"
            ),
            {
                "iid": issue_id,
                "status": status,
                "created": datetime.fromisoformat(created_at),
                "add": additions,
                "del": deletions,
                "total": total_changes,
            },
        )
    ).scalar_one()


async def _recorded_at(db, task_id: int):
    return (
        await db.execute(
            sa.text("SELECT change_stats_recorded_at FROM tasks WHERE id = :tid"),
            {"tid": task_id},
        )
    ).scalar_one_or_none()


# ── §6.4 migration backfill behavior ─────────────────────────────────────────


async def test_069_backfill_marks_only_consistent_nonzero_triples(
    seeded_068, migration_db
):
    """The real 069 upgrade backfills self-consistent triples, keeps the rest Unknown."""
    async with seeded_068() as db:
        wp = await _insert_worker_profile(db)
        issue = await _insert_issue(db, worker_profile_id=wp)
        consistent = await _insert_task(
            db, issue, created_at="2026-01-01 00:00:00",
            additions=5, deletions=2, total_changes=7,
        )
        inconsistent_total = await _insert_task(
            db, issue, created_at="2026-01-02 00:00:00",
            additions=5, deletions=2, total_changes=9,
        )
        total_only = await _insert_task(
            db, issue, created_at="2026-01-03 00:00:00",
            additions=0, deletions=0, total_changes=5,
        )
        all_zero = await _insert_task(
            db, issue, created_at="2026-01-04 00:00:00",
            additions=0, deletions=0, total_changes=0,
        )
        negative = await _insert_task(
            db, issue, created_at="2026-01-05 00:00:00",
            additions=5, deletions=-2, total_changes=3,
        )
        await db.commit()

    await asyncio.to_thread(
        _upgrade, migration_db["cfg"], "069_system_lifecycle_statistics"
    )

    async with seeded_068() as db:
        assert (await _recorded_at(db, consistent)) is not None
        assert (await _recorded_at(db, inconsistent_total)) is None
        assert (await _recorded_at(db, total_only)) is None
        assert (await _recorded_at(db, all_zero)) is None
        assert (await _recorded_at(db, negative)) is None
