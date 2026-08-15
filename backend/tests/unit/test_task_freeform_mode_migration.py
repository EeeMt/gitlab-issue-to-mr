"""Behavioral test for migration 073 (freeform task mode constraint).

Runs the real ``073_task_freeform_mode`` upgrade/downgrade through alembic on a
throwaway PostgreSQL database. Verifies the ``ck_tasks_task_mode`` check
constraint is extended to ``execute/freeform/plan`` on upgrade, the ``tasks``
server default stays ``execute``, and the downgrade maps every ``freeform`` row
to ``execute`` with ``require_changes=false`` before restoring the binary
constraint. Skipped when the test database is unreachable.
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

REVISION = "073_task_freeform_mode"
BASE_REVISION = "072_shared_per_item_inheritance"


def test_073_revision_id_fits_alembic_version_varchar32() -> None:
    assert len(REVISION) <= 32


def test_migration_extends_from_the_single_head() -> None:
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config(ADMIN_URL))
    heads = script.get_heads()
    assert len(heads) == 1
    revisions = {item.revision: item for item in script.walk_revisions()}
    migration = revisions.get(REVISION)
    assert migration is not None
    assert migration.down_revision == BASE_REVISION
    assert heads == [REVISION]


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
    dbname = f"codify_migration_073_{uuid.uuid4().hex[:8]}"
    url = HOST_BASE + dbname
    cfg = _alembic_config(url)
    try:
        asyncio.run(_create_database(dbname))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"freeform migration DB unreachable: {exc!r}")
    original_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(cfg, BASE_REVISION)
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
async def seeded_072(maker, migration_db):
    """Re-arm the 073 upgrade and clear the issue/task seed tables."""
    cfg = migration_db["cfg"]
    await asyncio.to_thread(command.downgrade, cfg, BASE_REVISION)
    async with maker() as db:
        await db.execute(
            sa.text(
                "TRUNCATE worker_profiles, issues, tasks RESTART IDENTITY CASCADE"
            )
        )
        await db.commit()
    yield maker  # noqa: PT022


async def _insert_worker_profile(db) -> int:
    return (
        await db.execute(
            sa.text(
                "INSERT INTO worker_profiles (name, image, enabled, is_default, "
                "volume_mounts, pre_script, post_script, "
                "default_execute_run_instruction_template, "
                "default_plan_run_instruction_template, "
                "ci_auto_repair_run_instruction_template) "
                "VALUES ('migration-worker', 'codify-worker/java21:2026.07', true, true, "
                "'[]'::json, '', '', 'execute {{user_prompt}}', "
                "'plan {{user_prompt}}', 'repair {{issue_title}}') RETURNING id"
            )
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


async def _insert_task(
    db,
    *,
    issue_id: int,
    task_mode: str,
    require_changes: bool = True,
) -> int:
    return (
        await db.execute(
            sa.text(
                "INSERT INTO tasks (issue_id, project_id, user_prompt, trigger_source, "
                "status, task_mode, require_changes, created_at) "
                "VALUES (:issue_id, 1, 'prompt', 'manual', 'pending', :task_mode, "
                ":require_changes, now()) RETURNING id"
            ),
            {"issue_id": issue_id, "task_mode": task_mode, "require_changes": require_changes},
        )
    ).scalar_one()


async def _task_mode_default(db) -> str:
    return (
        await db.execute(
            sa.text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = 'tasks' AND column_name = 'task_mode'"
            )
        )
    ).scalar_one() or ""


async def _task_mode_constraint(db) -> str:
    return (
        await db.execute(
            sa.text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_tasks_task_mode'"
            )
        )
    ).scalar_one()


async def test_upgrade_extends_constraint_and_keeps_execute_default(
    seeded_072, migration_db
) -> None:
    await asyncio.to_thread(command.upgrade, migration_db["cfg"], REVISION)

    async with seeded_072() as db:
        assert "execute" in await _task_mode_default(db)
        constraint = await _task_mode_constraint(db)
        assert "freeform" in constraint
        assert "execute" in constraint and "plan" in constraint

        issue_id = await _insert_issue(db)
        for mode in ("execute", "freeform", "plan"):
            await _insert_task(db, issue_id=issue_id, task_mode=mode)
        await db.commit()

        with pytest.raises(sa.exc.DBAPIError):
            await _insert_task(db, issue_id=issue_id, task_mode="bogus")
            await db.commit()


async def test_downgrade_maps_freeform_to_execute_and_restores_binary_constraint(
    seeded_072, migration_db
) -> None:
    await asyncio.to_thread(command.upgrade, migration_db["cfg"], REVISION)

    async with seeded_072() as db:
        issue_id = await _insert_issue(db)
        freeform_id = await _insert_task(
            db, issue_id=issue_id, task_mode="freeform", require_changes=True
        )
        await db.commit()

    await asyncio.to_thread(command.downgrade, migration_db["cfg"], BASE_REVISION)

    async with seeded_072() as db:
        row = (
            await db.execute(
                sa.text("SELECT task_mode, require_changes FROM tasks WHERE id = :id"),
                {"id": freeform_id},
            )
        ).fetchone()
        assert row.task_mode == "execute"
        assert row.require_changes is False

        constraint = await _task_mode_constraint(db)
        assert "freeform" not in constraint
        assert "execute" in constraint and "plan" in constraint

        with pytest.raises(sa.exc.DBAPIError):
            await _insert_task(db, issue_id=issue_id, task_mode="freeform")
            await db.commit()
