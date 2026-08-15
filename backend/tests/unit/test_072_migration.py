"""Behavioral test for migration 072 (per-item shared inheritance masks).

Runs the real ``072_shared_per_item_inheritance`` upgrade
through alembic on a throwaway PostgreSQL database and asserts the F1 zero-drift
compensation: a fully explicit Profile (the pre-F1 whole-Profile gate returned
False) receives one ``operation='mask'`` environment row per shared key it does
not override and one ``volume_mount_masks`` entry per shared mount path it does
not override, while Profiles that already inherit shared (NULL scalars, system
Kit, existing masks) are left untouched. After upgrade, resolving the fully
explicit Profile against the loaded shared baseline produces the exact same
effective configuration as its pre-F1 resolution (empty baseline), proving the
migration is byte-for-byte drift-free.

The module fixture upgrades the fresh DB to ``071_worker_runtime_readiness``;
each test re-arms by downgrading to 071 and clearing the shared/profile seed
tables. Skipped when the test database is unreachable.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import NullPool

from alembic import command
from app.core.worker_shared_configuration import (
    effective_configuration_digest,
    load_shared_configuration,
    resolve_effective_configuration,
)
from app.models import WorkerProfile

ADMIN_URL = os.environ.get(
    "CODIFY_TEST_DATABASE_URL",
    "postgresql+asyncpg://codify:codify_password@192.168.50.129:5432/codify_test",
)
HOST_BASE = ADMIN_URL.rsplit("/", 1)[0] + "/"
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
ALEMBIC_INI = os.path.join(BACKEND_DIR, "alembic.ini")
ALEMBIC_DIR = os.path.join(BACKEND_DIR, "alembic")

_SEED_TABLES = (
    "worker_shared_environment_variables, worker_shared_configurations, "
    "worker_profile_environment_variables, worker_profiles"
)


def test_072_revision_id_fits_alembic_version_varchar32():
    assert len("072_shared_per_item_inheritance") <= 32


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
    dbname = f"codify_migration_072_{uuid.uuid4().hex[:8]}"
    url = HOST_BASE + dbname
    cfg = _alembic_config(url)
    try:
        asyncio.run(_create_database(dbname))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"per-item inheritance migration DB unreachable: {exc!r}")
    original_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(cfg, "071_worker_runtime_readiness")
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
async def seeded_071(maker, migration_db):
    """Re-arm the 072 upgrade and clear the shared/profile seed tables."""
    cfg = migration_db["cfg"]
    await asyncio.to_thread(command.downgrade, cfg, "071_worker_runtime_readiness")
    async with maker() as db:
        await db.execute(sa.text(f"TRUNCATE {_SEED_TABLES} RESTART IDENTITY CASCADE"))
        await db.commit()
    yield maker  # noqa: PT022


# ── seed helpers (071 schema, raw SQL) ───────────────────────────────────────


async def _insert_shared_configuration(
    db,
    *,
    volume_mounts: list[dict],
    env_rows: list[tuple[str, str, bool]],
) -> None:
    await db.execute(
        sa.text(
            "INSERT INTO worker_shared_configurations (id, revision, runtime_mode, "
            "worker_kit_version, worker_kit_path, volume_mounts, pre_script, post_script, "
            "default_execute_run_instruction_template, "
            "default_plan_run_instruction_template, "
            "ci_auto_repair_run_instruction_template, created_at, updated_at) "
            "VALUES (:id, 1, 'mounted_kit', '0.4.0', '/opt/codify/worker-kits/0.4.0', "
            "CAST(:volume_mounts AS json), 'shared-pre', 'shared-post', "
            "'shared execute {{user_prompt}}', 'shared plan {{user_prompt}}', "
            "'shared repair {{issue_title}}', now(), now())"
        ),
        {
            "id": 1,
            "volume_mounts": json.dumps(volume_mounts),
        },
    )
    for key, value, is_secret in env_rows:
        await db.execute(
            sa.text(
                "INSERT INTO worker_shared_environment_variables "
                "(worker_shared_configuration_id, key, value, is_secret, created_at, updated_at) "
                "VALUES (1, :key, :value, :is_secret, now(), now())"
            ),
            {"key": key, "value": value, "is_secret": is_secret},
        )


async def _insert_worker_profile(
    db,
    *,
    name: str,
    worker_kit_source: str = "profile",
    pre_script: str | None = "",
    volume_mounts: list[dict] | None = None,
    volume_mount_masks: list[str] | None = None,
    env_rows: list[tuple[str, str, str | None, bool]] | None = None,
) -> int:
    return (
        await db.execute(
            sa.text(
                "INSERT INTO worker_profiles (name, image, enabled, is_default, "
                "worker_kit_source, runtime_mode, worker_kit_version, worker_kit_path, "
                "volume_mounts, volume_mount_masks, pre_script, post_script, "
                "default_execute_run_instruction_template, "
                "default_plan_run_instruction_template, "
                "ci_auto_repair_run_instruction_template) "
                "VALUES (:name, 'codify-worker/java21:2026.07', true, false, "
                ":kit_source, 'baked_image', NULL, NULL, CAST(:volume_mounts AS json), "
                "CAST(:volume_mount_masks AS json), :pre_script, '', "
                "'execute {{user_prompt}}', 'plan {{user_prompt}}', "
                "'repair {{issue_title}}') RETURNING id"
            ),
            {
                "name": name,
                "kit_source": worker_kit_source,
                "volume_mounts": json.dumps(volume_mounts or []),
                "volume_mount_masks": json.dumps(volume_mount_masks or []),
                "pre_script": pre_script,
            },
        )
    ).scalar_one()


async def _insert_profile_env(
    db,
    *,
    worker_profile_id: int,
    key: str,
    operation: str,
    value: str | None,
    is_secret: bool = False,
) -> None:
    await db.execute(
        sa.text(
            "INSERT INTO worker_profile_environment_variables "
            "(worker_profile_id, key, operation, value, is_secret, created_at, updated_at) "
            "VALUES (:pid, :key, :operation, :value, :is_secret, now(), now())"
        ),
        {
            "pid": worker_profile_id,
            "key": key,
            "operation": operation,
            "value": value,
            "is_secret": is_secret,
        },
    )


async def _profile_env_ops(db, *, worker_profile_id: int) -> list[tuple[str, str]]:
    return [
        (key, operation)
        for key, operation in (
            await db.execute(
                sa.text(
                    "SELECT key, operation FROM worker_profile_environment_variables "
                    "WHERE worker_profile_id = :pid ORDER BY key"
                ),
                {"pid": worker_profile_id},
            )
        ).all()
    ]


async def _profile_mount_masks(db, *, worker_profile_id: int) -> list[str]:
    return (
        await db.execute(
            sa.text(
                "SELECT volume_mount_masks FROM worker_profiles WHERE id = :pid"
            ),
            {"pid": worker_profile_id},
        )
    ).scalar_one()


async def _seed_default_scenario(db) -> dict[str, int]:
    """Seed the shared baseline plus every Profile inheritance posture."""
    await _insert_shared_configuration(
        db,
        volume_mounts=[
            {"host_path": "/srv/shared", "container_path": "/shared", "mode": "ro"}
        ],
        env_rows=[
            ("SHARED_A", "a", False),
            ("SHARED_SECRET", "ciphertext", True),
        ],
    )
    fully_explicit = await _insert_worker_profile(db, name="Fully Explicit")
    partial_override = await _insert_worker_profile(
        db,
        name="Partial Override",
        volume_mounts=[{"host_path": "/srv/own", "container_path": "/shared", "mode": "rw"}],
    )
    await _insert_profile_env(
        db,
        worker_profile_id=partial_override,
        key="SHARED_A",
        operation="set",
        value="override",
    )
    null_scalar = await _insert_worker_profile(
        db,
        name="Null Scalar",
        pre_script=None,
    )
    system_kit = await _insert_worker_profile(
        db,
        name="System Kit",
        worker_kit_source="system",
    )
    existing_masks = await _insert_worker_profile(
        db,
        name="Existing Masks",
        volume_mount_masks=["/other"],
    )
    await db.commit()
    return {
        "fully_explicit": fully_explicit,
        "partial_override": partial_override,
        "null_scalar": null_scalar,
        "system_kit": system_kit,
        "existing_masks": existing_masks,
    }


# ── §7.2/§7.3 migration behavior ─────────────────────────────────────────────


async def test_072_adds_compensation_masks_to_fully_explicit_profiles(
    seeded_071, migration_db
):
    async with seeded_071() as db:
        ids = await _seed_default_scenario(db)

    await asyncio.to_thread(
        command.upgrade, migration_db["cfg"], "072_shared_per_item_inheritance"
    )

    async with seeded_071() as db:
        # Fully explicit: every shared env key not overridden becomes a mask row,
        # and every shared mount path not overridden joins volume_mount_masks.
        assert await _profile_env_ops(db, worker_profile_id=ids["fully_explicit"]) == [
            ("SHARED_A", "mask"),
            ("SHARED_SECRET", "mask"),
        ]
        assert await _profile_mount_masks(db, worker_profile_id=ids["fully_explicit"]) == [
            "/shared"
        ]
        # Partial override: the overridden key/path are untouched; only the
        # shared secret it does not own is masked.
        assert await _profile_env_ops(db, worker_profile_id=ids["partial_override"]) == [
            ("SHARED_A", "set"),
            ("SHARED_SECRET", "mask"),
        ]
        assert await _profile_mount_masks(db, worker_profile_id=ids["partial_override"]) == []
        # NULL-scalar, system-kit, and existing-mask Profiles already merged
        # shared pre-F1: nothing is added.
        assert await _profile_env_ops(db, worker_profile_id=ids["null_scalar"]) == []
        assert await _profile_mount_masks(db, worker_profile_id=ids["null_scalar"]) == []
        assert await _profile_env_ops(db, worker_profile_id=ids["system_kit"]) == []
        assert await _profile_mount_masks(db, worker_profile_id=ids["system_kit"]) == []
        assert await _profile_env_ops(db, worker_profile_id=ids["existing_masks"]) == []
        assert await _profile_mount_masks(db, worker_profile_id=ids["existing_masks"]) == [
            "/other"
        ]


async def test_072_fully_explicit_profile_is_zero_drift_after_upgrade(
    seeded_071, migration_db
):
    async with seeded_071() as db:
        ids = await _seed_default_scenario(db)

    await asyncio.to_thread(
        command.upgrade, migration_db["cfg"], "072_shared_per_item_inheritance"
    )

    async with seeded_071() as db:
        profile = await db.get(
            WorkerProfile,
            ids["fully_explicit"],
            options=[selectinload(WorkerProfile.environment_variables)],
        )
        shared = await load_shared_configuration(db)
        # Pre-F1 the whole-Profile gate resolved this Profile without the shared
        # baseline; the compensation masks it now carries are no-ops against an
        # empty baseline, so this is the pre-F1 effective configuration.
        pre_f1 = resolve_effective_configuration(profile, None)
        # Post-F1 the resolver always merges shared; the masks hide every shared
        # item, so the effective configuration must be byte-for-byte identical.
        post_f1 = resolve_effective_configuration(profile, shared)

        assert post_f1.environment_variables == pre_f1.environment_variables == ()
        assert post_f1.volume_mounts == pre_f1.volume_mounts == ()
        assert post_f1.runtime_mode == pre_f1.runtime_mode == "baked_image"
        assert post_f1.worker_kit_version is pre_f1.worker_kit_version is None
        assert post_f1.pre_script == pre_f1.pre_script == ""
        assert post_f1.shared_configuration_revision == 1
        assert effective_configuration_digest(post_f1) == effective_configuration_digest(pre_f1)
