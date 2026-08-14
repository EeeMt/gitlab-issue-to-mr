"""Behavioral test for migration 070 (worker shared configuration).

Runs the real ``070_worker_shared_configuration`` upgrade through alembic on a
throwaway PostgreSQL database and asserts the §18 behavior: the shared
configuration singleton is seeded from the default Worker Profile (including
its environment variables), every existing Profile stays fully explicit
(``worker_kit_source='profile'``, environment rows become ``operation='set'``,
``volume_mount_masks`` empty), active Task snapshots backfill their
``effective_configuration_digest``, and an active Task with an incomplete
snapshot fails the migration closed rather than leaving a digest unbackfilled.

The module fixture upgrades the fresh DB to ``069_system_lifecycle_statistics``;
each test re-arms by downgrading to 069 and clearing the seed tables. Skipped
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

_SEED_TABLES = (
    "task_worker_profile_snapshots, tasks, issues, worker_profiles, "
    "worker_profile_environment_variables"
)


def test_070_revision_id_fits_alembic_version_varchar32():
    assert len("070_worker_shared_configuration") <= 32


# ── throwaway database plumbing ──────────────────────────────────────────────


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
    dbname = f"codify_migration_070_{uuid.uuid4().hex[:8]}"
    url = HOST_BASE + dbname
    cfg = _alembic_config(url)
    try:
        asyncio.run(_create_database(dbname))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"shared configuration migration DB unreachable: {exc!r}")
    original_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(cfg, "069_system_lifecycle_statistics")
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
async def seeded_069(maker, migration_db):
    """Re-arm the 070 upgrade and clear the seed tables for one test."""
    cfg = migration_db["cfg"]
    await asyncio.to_thread(command.downgrade, cfg, "069_system_lifecycle_statistics")
    async with maker() as db:
        await db.execute(sa.text(f"TRUNCATE {_SEED_TABLES} RESTART IDENTITY CASCADE"))
        await db.commit()
    yield maker  # noqa: PT022


# ── seed helpers (069 schema, raw SQL) ───────────────────────────────────────


async def _insert_worker_profile(
    db,
    *,
    name: str,
    is_default: bool = False,
    runtime_mode: str = "baked_image",
    worker_kit_version: str | None = None,
    worker_kit_path: str | None = None,
    pre_script: str = "",
    post_script: str = "",
    execute_template: str = "execute {{user_prompt}}",
    plan_template: str = "plan {{user_prompt}}",
    ci_template: str = "repair {{issue_title}}",
) -> int:
    return (
        await db.execute(
            sa.text(
                "INSERT INTO worker_profiles (name, image, enabled, is_default, "
                "runtime_mode, worker_kit_version, worker_kit_path, volume_mounts, "
                "pre_script, post_script, "
                "default_execute_run_instruction_template, "
                "default_plan_run_instruction_template, "
                "ci_auto_repair_run_instruction_template) "
                "VALUES (:name, 'codify-worker/java21:2026.07', true, :is_default, "
                ":runtime_mode, :kit_version, :kit_path, '[]'::json, "
                ":pre_script, :post_script, :execute, :plan, :ci) RETURNING id"
            ),
            {
                "name": name,
                "is_default": is_default,
                "runtime_mode": runtime_mode,
                "kit_version": worker_kit_version,
                "kit_path": worker_kit_path,
                "pre_script": pre_script,
                "post_script": post_script,
                "execute": execute_template,
                "plan": plan_template,
                "ci": ci_template,
            },
        )
    ).scalar_one()


async def _insert_profile_env_var(db, profile_id: int, key: str, value: str, is_secret: bool = False) -> None:
    await db.execute(
        sa.text(
            "INSERT INTO worker_profile_environment_variables "
            "(worker_profile_id, key, value, is_secret) "
            "VALUES (:pid, :key, :value, :is_secret)"
        ),
        {"pid": profile_id, "key": key, "value": value, "is_secret": is_secret},
    )


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
    execute_template: str = "execute {{user_prompt}}",
    plan_template: str = "plan {{user_prompt}}",
    ci_template: str = "repair {{issue_title}}",
    image: str = "codify-worker/java21:2026.07",
) -> None:
    await db.execute(
        sa.text(
            "INSERT INTO task_worker_profile_snapshots (task_id, profile_name, image, "
            "runtime_mode, worker_kit_version, worker_kit_path, volume_mounts, "
            "environment_variables, pre_script, post_script, "
            "default_execute_run_instruction_template, "
            "default_plan_run_instruction_template, "
            "ci_auto_repair_run_instruction_template) "
            "VALUES (:task_id, 'Default Worker', :image, :runtime_mode, NULL, NULL, "
            "'[]'::json, '[]'::json, '', '', :execute, :plan, :ci)"
        ),
        {
            "task_id": task_id,
            "image": image,
            "runtime_mode": runtime_mode,
            "execute": execute_template,
            "plan": plan_template,
            "ci": ci_template,
        },
    )


async def _snapshot_digest(db, task_id: int):
    return (
        await db.execute(
            sa.text(
                "SELECT effective_configuration_digest FROM task_worker_profile_snapshots "
                "WHERE task_id = :tid"
            ),
            {"tid": task_id},
        )
    ).scalar_one_or_none()


# ── §18 migration behavior ────────────────────────────────────────────────────


async def test_070_seeds_shared_configuration_from_default_profile(
    seeded_069, migration_db
):
    async with seeded_069() as db:
        profile_id = await _insert_worker_profile(
            db,
            name="Default Worker",
            is_default=True,
            runtime_mode="mounted_kit",
            worker_kit_version="0.4.0",
            worker_kit_path="/opt/codify/worker-kits/0.4.0",
            pre_script="default-pre",
            post_script="default-post",
            execute_template="default execute {{user_prompt}}",
        )
        await _insert_profile_env_var(db, profile_id, "SHARED_A", "a")
        await _insert_profile_env_var(db, profile_id, "SHARED_SECRET", "cipher", is_secret=True)
        await db.commit()

    await asyncio.to_thread(
        command.upgrade, migration_db["cfg"], "070_worker_shared_configuration"
    )

    async with seeded_069() as db:
        row = (
            await db.execute(
                sa.text(
                    "SELECT runtime_mode, worker_kit_version, worker_kit_path, "
                    "pre_script, post_script, "
                    "default_execute_run_instruction_template, revision "
                    "FROM worker_shared_configurations WHERE id = 1"
                )
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "mounted_kit"
        assert row[1] == "0.4.0"
        assert row[2] == "/opt/codify/worker-kits/0.4.0"
        assert row[3] == "default-pre"
        assert row[4] == "default-post"
        assert row[5] == "default execute {{user_prompt}}"
        assert row[6] == 1
        env_rows = (
            await db.execute(
                sa.text(
                    "SELECT key, is_secret FROM worker_shared_environment_variables "
                    "WHERE worker_shared_configuration_id = 1 ORDER BY key"
                )
            )
        ).fetchall()
        assert [(r[0], r[1]) for r in env_rows] == [("SHARED_A", False), ("SHARED_SECRET", True)]


async def test_070_keeps_existing_profiles_explicit(seeded_069, migration_db):
    async with seeded_069() as db:
        await _insert_worker_profile(db, name="Default Worker", is_default=True)
        other_id = await _insert_worker_profile(db, name="Java Worker")
        await _insert_profile_env_var(db, other_id, "JAVA_OPTS", "-Xmx1g")
        await db.commit()

    await asyncio.to_thread(
        command.upgrade, migration_db["cfg"], "070_worker_shared_configuration"
    )

    async with seeded_069() as db:
        profiles = (
            await db.execute(
                sa.text(
                    "SELECT name, worker_kit_source, volume_mount_masks "
                    "FROM worker_profiles ORDER BY id"
                )
            )
        ).fetchall()
        assert {p[0]: p[1] for p in profiles} == {
            "Default Worker": "profile",
            "Java Worker": "profile",
        }
        assert all(p[2] == [] for p in profiles)
        env_rows = (
            await db.execute(
                sa.text(
                    "SELECT operation, key, value FROM worker_profile_environment_variables"
                )
            )
        ).fetchall()
        assert env_rows == [("set", "JAVA_OPTS", "-Xmx1g")]


async def test_070_backfills_snapshot_digests_for_active_and_closed_tasks(
    seeded_069, migration_db
):
    async with seeded_069() as db:
        profile_id = await _insert_worker_profile(
            db, name="Default Worker", is_default=True
        )
        closed = await _insert_task(db, status="completed", worker_profile_id=profile_id)
        active = await _insert_task(db, status="running", worker_profile_id=profile_id)
        await _insert_snapshot(db, task_id=closed)
        await _insert_snapshot(db, task_id=active)
        await db.commit()

    await asyncio.to_thread(
        command.upgrade, migration_db["cfg"], "070_worker_shared_configuration"
    )

    async with seeded_069() as db:
        closed_digest = await _snapshot_digest(db, closed)
        active_digest = await _snapshot_digest(db, active)
        revision = (
            await db.execute(
                sa.text(
                    "SELECT shared_configuration_revision "
                    "FROM task_worker_profile_snapshots WHERE task_id = :tid"
                ),
                {"tid": active},
            )
        ).scalar_one()
        assert closed_digest is not None and len(closed_digest) == 64
        assert active_digest is not None and len(active_digest) == 64
        assert closed_digest == active_digest
        # §18.8/F5: pre-feature snapshots were fully explicit, so the backfill
        # leaves shared_configuration_revision NULL — matching a freshly created
        # explicit Profile snapshot instead of implying a shared merge.
        assert revision is None


async def test_070_active_incomplete_snapshot_fails_closed(seeded_069, migration_db):
    async with seeded_069() as db:
        profile_id = await _insert_worker_profile(
            db, name="Default Worker", is_default=True
        )
        active = await _insert_task(db, status="queued", worker_profile_id=profile_id)
        await _insert_snapshot(db, task_id=active, ci_template="")
        await db.commit()

    with pytest.raises(RuntimeError, match="incomplete worker snapshot"):
        await asyncio.to_thread(
            command.upgrade, migration_db["cfg"], "070_worker_shared_configuration"
        )
