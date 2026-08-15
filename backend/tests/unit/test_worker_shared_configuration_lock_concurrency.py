"""Two-session PostgreSQL concurrency tests for the shared-config revision lock.

The §11.2 lock protocol makes the shared baseline read, the expected-revision
check, and the combined validation one transactional unit for every writer:
Profile create/update/duplicate and Task create/F6-switch/CI-repair load the
singleton row with ``SELECT ... FOR UPDATE`` via
``load_shared_configuration(..., for_update=True)`` and keep the lock until
commit, passing the same ``WorkerSharedConfigurationContext`` to the readiness
gate and the frozen snapshot.

These tests prove the protocol against a real PostgreSQL instance: a shared
PATCH cannot interleave between a Profile-save / Task-create baseline read and
its commit (so a reader can never produce a mixed revision or bypass the 409 /
static-combination checks), and a PATCH that commits first makes a stale
``expected_shared_revision`` writer fail 409.

The module uses its own throwaway database migrated to head so the schema is
authoritative. Skipped when the test database is unreachable.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import NullPool

from alembic import command
from app.api.worker_profiles import WorkerProfileUpdateRequest, update_worker_profile
from app.api.worker_shared_configuration import (
    WorkerSharedConfigurationPatchRequest,
    update_shared_configuration,
)
from app.config import get_effective_settings
from app.core.worker_profiles import replace_task_worker_snapshot
from app.core.worker_runtime_readiness import readiness_for_profile
from app.core.worker_shared_configuration import load_shared_configuration
from app.models import (
    Issue,
    Task,
    WorkerProfile,
    WorkerSharedConfiguration,
    WorkerSharedEnvironmentVariable,
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
def migration_db():
    dbname = f"codify_shared_lock_{uuid.uuid4().hex[:8]}"
    url = HOST_BASE + dbname
    cfg = _alembic_config(url)
    try:
        asyncio.run(_create_database(dbname))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"shared-config lock DB unreachable: {exc!r}")
    original_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(cfg, "head")
        yield {"url": url, "cfg": cfg, "dbname": dbname}
    finally:
        asyncio.run(_drop_database(dbname))
        if original_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_url


@pytest.fixture
async def maker(migration_db):
    engine = create_async_engine(
        migration_db["url"],
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    finally:
        await engine.dispose()


async def _seed(maker) -> tuple[int, int, int, int]:
    """Seed a shared baseline (rev 1) plus an enabled standalone Profile, an
    Issue, and a minimal Task. Returns (shared_id, profile_id, issue_id, task_id).

    The head migration pre-seeds the shared singleton (id=1), so this resets that
    row and its environment variables to a known rev-1 baseline before seeding.
    """
    async with maker() as db:
        await db.execute(
            sa.text(
                "DELETE FROM worker_shared_environment_variables "
                "WHERE worker_shared_configuration_id = 1"
            )
        )
        await db.execute(
            sa.text("DELETE FROM worker_shared_configurations WHERE id = 1")
        )
        shared = WorkerSharedConfiguration(
            id=1,
            revision=1,
            runtime_mode="mounted_kit",
            worker_kit_version="0.4.0",
            worker_kit_path="/opt/codify/worker-kits/0.4.0",
            volume_mounts=[],
            pre_script="shared-pre",
            post_script="shared-post",
            default_execute_run_instruction_template="shared execute {{user_prompt}}",
            default_plan_run_instruction_template="shared plan {{user_prompt}}",
            ci_auto_repair_run_instruction_template="shared repair {{issue_title}}",
        )
        db.add(shared)
        await db.flush()
        db.add(
            WorkerSharedEnvironmentVariable(
                worker_shared_configuration_id=1,
                key="SHARED_A",
                value="a",
                is_secret=False,
            )
        )
        profile = WorkerProfile(
            name=f"lock-wp-{uuid.uuid4().hex[:8]}",
            enabled=True,
            is_default=False,
            image="codify-worker/java21:2026.07",
            worker_kit_source="profile",
            runtime_mode="baked_image",
            volume_mounts=[],
            volume_mount_masks=[],
            pre_script="",
            post_script="",
            default_execute_run_instruction_template="execute {{user_prompt}}",
            default_plan_run_instruction_template="plan {{user_prompt}}",
            ci_auto_repair_run_instruction_template="repair {{issue_title}}",
            enabled_harnesses=["claude"],
            default_harness_key="claude",
            harness_constraints={},
            harness_runtimes={},
        )
        db.add(profile)
        await db.flush()
        issue = Issue(title="shared-lock-concurrency", project_id=1, worker_profile_id=profile.id)
        db.add(issue)
        await db.flush()
        task = Task(
            user_prompt="prompt",
            issue_id=issue.id,
            project_id=1,
            worker_profile_id=profile.id,
        )
        db.add(task)
        await db.commit()
        return (shared.id, profile.id, issue.id, task.id)


async def _patch_pre_script(db, *, expected_revision: int):
    """Run the real shared PATCH handler with a pre_script change."""
    return await update_shared_configuration(
        WorkerSharedConfigurationPatchRequest(
            expected_revision=expected_revision,
            pre_script="patched pre",
        ),
        db=db,
        _admin=None,
    )


# ── §11.2 Profile save holds the shared lock until commit ────────────────────


async def test_profile_save_holds_shared_lock_blocks_concurrent_patch(
    maker, migration_db
):
    """A Profile save's locked baseline read blocks a concurrent shared PATCH
    until the save commits: the PATCH cannot interleave between the read and the
    commit, so the save can never validate against one revision and persist with
    another."""
    _, profile_id, _, _ = await _seed(maker)

    async with maker() as save_db:
        # Profile save (create/update path): load the baseline under lock.
        shared = await load_shared_configuration(save_db, for_update=True)
        assert shared.revision == 1
        save_read = asyncio.Event()
        release_save = asyncio.Event()

        async def save_holds_lock():
            save_read.set()
            await release_save.wait()
            # The save validated against rev 1; commit with the lock still held.
            await save_db.commit()

        save_task = asyncio.create_task(save_holds_lock())
        await save_read.wait()

        patch_db = maker()
        patch_launched = asyncio.Event()

        async def run_patch():
            patch_launched.set()
            return await _patch_pre_script(patch_db, expected_revision=1)

        patch = asyncio.create_task(run_patch())
        await patch_launched.wait()
        await asyncio.sleep(0.05)  # let the PATCH block on the FOR UPDATE

        assert not patch.done(), (
            "concurrent PATCH must block while the Profile save holds the shared lock"
        )

        release_save.set()
        await save_task
        await patch
        await patch_db.close()

    # The PATCH serialized after the save and bumped the revision.
    async with maker() as db:
        row = await db.get(WorkerSharedConfiguration, 1)
        assert row is not None
        assert row.revision == 2
        assert row.pre_script == "patched pre"


# ── §11.2 Task create / F6 switch gate + snapshot share one locked baseline ──


async def test_task_create_gate_and_snapshot_share_one_locked_baseline(
    maker, migration_db
):
    """Task create (and the identical F6-switch / CI-repair path) resolves the
    readiness gate and freezes the snapshot from the *same* locked baseline, so a
    concurrent shared PATCH cannot land between the two reads."""
    _, profile_id, _, task_id = await _seed(maker)

    async with maker() as create_db:
        shared = await load_shared_configuration(create_db, for_update=True)
        assert shared.revision == 1
        profile = await create_db.get(
            WorkerProfile,
            profile_id,
            options=[selectinload(WorkerProfile.environment_variables)],
        )
        assert profile is not None
        readiness = await readiness_for_profile(
            create_db,
            profile,
            get_effective_settings(),
            shared=shared,
        )
        task = await create_db.get(Task, task_id)
        assert task is not None
        snapshot = await replace_task_worker_snapshot(
            create_db,
            task,
            profile,
            shared_configuration=shared,
        )

        patch_db = maker()
        patch_launched = asyncio.Event()

        async def run_patch():
            patch_launched.set()
            return await _patch_pre_script(patch_db, expected_revision=1)

        patch = asyncio.create_task(run_patch())
        await patch_launched.wait()
        await asyncio.sleep(0.05)

        assert not patch.done(), (
            "concurrent PATCH must block while task-create holds the shared lock"
        )

        await create_db.commit()
        await patch
        await patch_db.close()

    # The snapshot froze the same rev-1 baseline the gate resolved; the PATCH
    # then advanced the shared baseline to rev 2 after the task was committed.
    assert snapshot.shared_configuration_revision == 1
    async with maker() as db:
        row = await db.get(WorkerSharedConfiguration, 1)
        assert row is not None
        assert row.revision == 2
        assert row.pre_script == "patched pre"


# ── §11.2 A PATCH that commits first makes a stale writer fail 409 ───────────


async def test_stale_profile_save_fails_409_when_patch_commits_first(
    maker, migration_db
):
    """A Profile save that still holds an old expected revision must 409 once a
    concurrent PATCH has advanced the baseline: the optimistic-revision check
    cannot be bypassed by reading the row and checking revision separately."""
    _, profile_id, _, _ = await _seed(maker)

    # A shared PATCH commits rev 2 before the Profile save re-reads.
    async with maker() as db:
        await _patch_pre_script(db, expected_revision=1)

    async with maker() as db:
        with pytest.raises(HTTPException) as exc:
            await update_worker_profile(
                profile_id,
                WorkerProfileUpdateRequest(
                    expected_shared_revision=1,
                    description="stale edit",
                ),
                db=db,
            )

    assert exc.value.status_code == 409
    assert exc.value.detail == "shared_configuration_changed"
