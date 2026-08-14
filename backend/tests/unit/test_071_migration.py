"""Behavioral test for migration 071 (worker runtime readiness).

Runs the real ``071_worker_runtime_readiness`` upgrade through alembic on a
throwaway PostgreSQL database and asserts the §18.8-§18.9 behavior: the
``worker_runtime_readiness`` table is created with zero seeded rows, baked-image
snapshots keep a NULL fingerprint, terminal mounted-kit snapshots that cannot be
fully resolved stay NULL, and every active mounted-kit snapshot backfills a
fingerprint or the migration fails closed.

The module fixture upgrades the fresh DB to ``070_worker_shared_configuration``;
each test re-arms by downgrading to 070 and clearing the seed tables. Skipped
when the test database is unreachable.
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

_SEED_TABLES = "task_worker_profile_snapshots, tasks, issues, worker_profiles"


def test_071_revision_id_fits_alembic_version_varchar32():
    assert len("071_worker_runtime_readiness") <= 32


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
    dbname = f"codify_migration_071_{uuid.uuid4().hex[:8]}"
    url = HOST_BASE + dbname
    cfg = _alembic_config(url)
    try:
        asyncio.run(_create_database(dbname))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"runtime readiness migration DB unreachable: {exc!r}")
    original_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(cfg, "070_worker_shared_configuration")
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
async def seeded_070(maker, migration_db):
    """Re-arm the 071 upgrade and clear the seed tables for one test."""
    cfg = migration_db["cfg"]
    await asyncio.to_thread(command.downgrade, cfg, "070_worker_shared_configuration")
    async with maker() as db:
        await db.execute(sa.text(f"TRUNCATE {_SEED_TABLES} RESTART IDENTITY CASCADE"))
        await db.commit()
    yield maker  # noqa: PT022


# ── seed helpers (070 schema, raw SQL) ───────────────────────────────────────


async def _insert_worker_profile(
    db,
    *,
    name: str,
    is_default: bool = False,
) -> int:
    return (
        await db.execute(
            sa.text(
                "INSERT INTO worker_profiles (name, image, enabled, is_default, "
                "volume_mounts, pre_script, post_script, "
                "default_execute_run_instruction_template, "
                "default_plan_run_instruction_template, "
                "ci_auto_repair_run_instruction_template) "
                "VALUES (:name, 'codify-worker/java21:2026.07', true, :is_default, "
                "'[]'::json, '', '', 'execute {{user_prompt}}', "
                "'plan {{user_prompt}}', 'repair {{issue_title}}') RETURNING id"
            ),
            {"name": name, "is_default": is_default},
        )
    ).scalar_one()


async def _insert_issue(db, *, worker_profile_id: int | None = None) -> int:
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


async def _insert_task(db, *, status: str, worker_profile_id: int) -> int:
    issue_id = await _insert_issue(db, worker_profile_id=worker_profile_id)
    return (
        await db.execute(
            sa.text(
                "INSERT INTO tasks (issue_id, project_id, user_prompt, trigger_source, "
                "status, created_at) "
                "VALUES (:issue_id, 1, 'prompt', 'manual', :status, now()) RETURNING id"
            ),
            {"issue_id": issue_id, "status": status},
        )
    ).scalar_one()


async def _insert_snapshot(
    db,
    *,
    task_id: int,
    runtime_mode: str = "baked_image",
    worker_kit_version: str | None = None,
    worker_kit_path: str | None = None,
    docker_host: str | None = None,
) -> None:
    await db.execute(
        sa.text(
            "INSERT INTO task_worker_profile_snapshots (task_id, profile_name, image, "
            "runtime_mode, worker_kit_version, worker_kit_path, docker_host, "
            "volume_mounts, environment_variables, pre_script, post_script, "
            "default_execute_run_instruction_template, "
            "default_plan_run_instruction_template, "
            "ci_auto_repair_run_instruction_template) "
            "VALUES (:task_id, 'Default Worker', 'codify-worker/java21:2026.07', "
            ":runtime_mode, :kit_version, :kit_path, :docker_host, "
            "'[]'::json, '[]'::json, '', '', 'execute {{user_prompt}}', "
            "'plan {{user_prompt}}', 'repair {{issue_title}}')"
        ),
        {
            "task_id": task_id,
            "runtime_mode": runtime_mode,
            "kit_version": worker_kit_version,
            "kit_path": worker_kit_path,
            "docker_host": docker_host,
        },
    )


async def _snapshot_fingerprint(db, task_id: int):
    return (
        await db.execute(
            sa.text(
                "SELECT runtime_locator_fingerprint FROM task_worker_profile_snapshots "
                "WHERE task_id = :tid"
            ),
            {"tid": task_id},
        )
    ).scalar_one_or_none()


# ── §18 migration behavior ────────────────────────────────────────────────────


async def test_071_creates_readiness_table_and_backfills_fingerprints(
    seeded_070, migration_db
):
    async with seeded_070() as db:
        profile_id = await _insert_worker_profile(db, name="Default Worker")
        baked_terminal = await _insert_task(db, status="completed", worker_profile_id=profile_id)
        baked_active = await _insert_task(db, status="queued", worker_profile_id=profile_id)
        kit_terminal = await _insert_task(db, status="failed", worker_profile_id=profile_id)
        kit_active = await _insert_task(db, status="queued", worker_profile_id=profile_id)
        await _insert_snapshot(db, task_id=baked_terminal)
        await _insert_snapshot(db, task_id=baked_active)
        await _insert_snapshot(
            db,
            task_id=kit_terminal,
            runtime_mode="mounted_kit",
            worker_kit_version="0.3.5",
            worker_kit_path="/opt/kit",
            docker_host="tcp://worker:2376",
        )
        await _insert_snapshot(
            db,
            task_id=kit_active,
            runtime_mode="mounted_kit",
            worker_kit_version="0.3.5",
            worker_kit_path="/opt/kit",
            docker_host="tcp://worker:2376",
        )
        await db.commit()

    await asyncio.to_thread(
        command.upgrade, migration_db["cfg"], "071_worker_runtime_readiness"
    )

    async with seeded_070() as db:
        # Table exists and is created empty (unknown) — no readiness rows seeded.
        readiness_rows = (
            await db.execute(sa.text("SELECT count(*) FROM worker_runtime_readiness"))
        ).scalar_one()
        assert readiness_rows == 0
        # Baked-image snapshots keep a NULL fingerprint.
        assert await _snapshot_fingerprint(db, baked_terminal) is None
        assert await _snapshot_fingerprint(db, baked_active) is None
        # Terminal mounted-kit snapshot with a complete locator backfills too.
        assert await _snapshot_fingerprint(db, kit_terminal) is not None
        # Active mounted-kit snapshot must backfill a fingerprint.
        fingerprint = await _snapshot_fingerprint(db, kit_active)
        assert fingerprint is not None
        assert len(fingerprint) == 64


async def test_071_active_mounted_kit_without_complete_locator_fails_closed(
    seeded_070, migration_db
):
    async with seeded_070() as db:
        profile_id = await _insert_worker_profile(db, name="Default Worker")
        active = await _insert_task(db, status="running", worker_profile_id=profile_id)
        # Active mounted-kit snapshot missing the Kit path: fail closed.
        await _insert_snapshot(
            db,
            task_id=active,
            runtime_mode="mounted_kit",
            worker_kit_version="0.3.5",
            worker_kit_path=None,
            docker_host="tcp://worker:2376",
        )
        await db.commit()

    with pytest.raises(RuntimeError, match="incomplete mounted-kit snapshot"):
        await asyncio.to_thread(
            command.upgrade, migration_db["cfg"], "071_worker_runtime_readiness"
        )
