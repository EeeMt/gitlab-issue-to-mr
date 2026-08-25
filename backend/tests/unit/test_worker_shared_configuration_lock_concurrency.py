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
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import NullPool

from alembic import command
from app.api.task_creation_service import TaskCreationServices, create_task_record
from app.api.task_operations import get_task_with_access_check
from app.api.task_schemas import CreateTaskRequest, UpdateTaskRequest
from app.api.task_update_service import TaskUpdateServices, update_task_record
from app.api.worker_profiles import WorkerProfileUpdateRequest, update_worker_profile
from app.api.worker_shared_configuration import (
    WorkerSharedConfigurationPatchRequest,
    update_shared_configuration,
)
from app.config import get_effective_settings
from app.core.worker_profiles import (
    replace_task_worker_snapshot,
    resolve_worker_profile_for_issue,
)
from app.core.worker_runtime_readiness import readiness_for_profile
from app.core.worker_shared_configuration import load_shared_configuration
from app.dependencies.project_access import ProjectAccessScope
from app.models import (
    AIProvider,
    Issue,
    Task,
    TaskWorkerProfileSnapshot,
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
        # Full lineage projection: the issue-order integrity gate treats an
        # ACTIVE task without a frozen projection as a manual-repair condition,
        # which would block create_task_record during this lock-order test.
        # The task stays PENDING so update flows (F6) can still edit it.
        task = Task(
            user_prompt="prompt",
            issue_id=issue.id,
            project_id=1,
            worker_profile_id=profile.id,
            projected_harness_key="claude",
            projected_session_namespace="legacy",
            projected_lineage_generation=0,
            lineage_projection_reason="initial",
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
        assert not readiness.is_unavailable
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


# ── Global Shared -> Profile order for every dual-lock writer ────────────────


async def test_duplicate_route_serializes_shared_patch_before_source_profile(
    maker, migration_db, monkeypatch
):
    """The real duplicate route holds Shared before it locks its source Profile.

    The barrier is intentionally placed *after* the source Profile is locked.
    With the old Profile -> Shared order, PATCH would hold Shared and wait for
    that Profile while duplicate waited for Shared: a PostgreSQL deadlock.  With
    the global order, PATCH is already blocked on Shared and both writers finish.
    """
    _, profile_id, _, _ = await _seed(maker)
    from app.api import worker_profiles as profiles_api

    profile_locked = asyncio.Event()
    release_profile = asyncio.Event()
    original_load = profiles_api._load_profile_or_404

    async def hold_locked_source(*args, **kwargs):
        profile = await original_load(*args, **kwargs)
        profile_locked.set()
        await release_profile.wait()
        return profile

    monkeypatch.setattr(profiles_api, "_load_profile_or_404", hold_locked_source)

    duplicate_db = maker()
    duplicate = asyncio.create_task(
        profiles_api.duplicate_worker_profile(profile_id, db=duplicate_db, _admin=None)
    )
    await asyncio.wait_for(profile_locked.wait(), timeout=2)

    patch_db = maker()
    patch_task = asyncio.create_task(_patch_pre_script(patch_db, expected_revision=1))
    await asyncio.sleep(0.05)
    assert not patch_task.done(), "PATCH must wait for duplicate's Shared lock"

    release_profile.set()
    response = await asyncio.wait_for(duplicate, timeout=2)
    await asyncio.wait_for(patch_task, timeout=2)
    await duplicate_db.close()
    await patch_db.close()

    assert response["name"].endswith(" Copy")
    async with maker() as db:
        shared = await db.get(WorkerSharedConfiguration, 1)
        assert shared is not None and shared.revision == 2


async def test_task_create_service_serializes_patch_and_snapshots_locked_revision(
    maker, migration_db, monkeypatch
):
    """Task create passes its Shared-locked revision through to snapshotting."""
    _, profile_id, issue_id, _ = await _seed(maker)
    # Persist the provider: create_task_record freezes provider.id onto the
    # new Task row and PostgreSQL enforces fk_tasks_provider_id.
    async with maker() as db:
        provider = AIProvider(
            id=991,
            name="lock-order-provider",
            base_url="https://provider.example.test",
            model="test-model",
            provider_kind="anthropic_compatible",
            model_protocol="anthropic_messages",
            is_default=True,
            is_disabled=False,
        )
        db.add(provider)
        await db.commit()
    profile_locked = asyncio.Event()
    release_profile = asyncio.Event()
    captured_revisions: list[int] = []

    async def hold_locked_profile(db, issue, *args, **kwargs):
        profile = await resolve_worker_profile_for_issue(db, issue, *args, **kwargs)
        assert profile.id == profile_id
        profile_locked.set()
        await release_profile.wait()
        return profile

    async def ready(*_args, shared, **_kwargs):
        return SimpleNamespace(is_unavailable=False, is_ready=True, harness_inventory=None)

    async def capture_snapshot(*_args, shared_configuration, **_kwargs):
        captured_revisions.append(shared_configuration.revision)
        raise RuntimeError("stop after snapshot revision capture")

    services = TaskCreationServices(
        require_issue_operator=MagicMock(),
        get_task_with_access_check=AsyncMock(),
        validate_task_status_for_retry=MagicMock(),
        validate_scheduled_datetime_in_future=AsyncMock(),
        get_usage_quota_service=MagicMock(),
        get_project_metadata=AsyncMock(return_value={}),
        resolve_provider_for_issue=AsyncMock(return_value=provider),
        resolve_worker_profile_for_issue=hold_locked_profile,
        prepare_task_runtime_snapshot=capture_snapshot,
        replace_task_worker_snapshot=AsyncMock(),
        clone_task_worker_snapshot=AsyncMock(),
        bind_runtime_bundle=AsyncMock(),
        select_snapshot_run_instruction_template=MagicMock(),
        render_and_store_task_prompt=AsyncMock(),
        notify_task_retried=AsyncMock(),
    )

    async def create() -> None:
        async with maker() as db:
            with pytest.raises(HTTPException, match="stop after snapshot"):
                await create_task_record(
                    request=CreateTaskRequest(issue_id=issue_id, user_prompt="lock-order"),
                    db=db,
                    current_user=None,
                    access_scope=ProjectAccessScope(is_unrestricted=True, accessible_projects=[]),
                    services=services,
                )

    with patch("app.api.task_creation_service.readiness_for_profile", ready):
        create_task = asyncio.create_task(create())
        await asyncio.wait_for(profile_locked.wait(), timeout=2)
        patch_db = maker()
        patch_task = asyncio.create_task(_patch_pre_script(patch_db, expected_revision=1))
        await asyncio.sleep(0.05)
        assert not patch_task.done(), "PATCH must wait for task create's Shared lock"
        release_profile.set()
        await asyncio.wait_for(create_task, timeout=2)
        await asyncio.wait_for(patch_task, timeout=2)
        await patch_db.close()

    assert captured_revisions == [1]
    async with maker() as db:
        shared = await db.get(WorkerSharedConfiguration, 1)
        assert shared is not None and shared.revision == 2


async def test_ci_repair_context_service_serializes_patch_before_profile(
    maker, migration_db, monkeypatch
):
    """The CI repair service uses the same order and returns that shared revision."""
    _, profile_id, issue_id, _ = await _seed(maker)
    from app.core import ci_failure_collector as collector

    profile_locked = asyncio.Event()
    release_profile = asyncio.Event()
    provider = SimpleNamespace(id=992)

    async def hold_locked_profile(db, issue, *args, **kwargs):
        profile = await resolve_worker_profile_for_issue(db, issue, *args, **kwargs)
        assert profile.id == profile_id
        profile_locked.set()
        await release_profile.wait()
        return profile

    monkeypatch.setattr(collector, "resolve_worker_profile_for_issue", hold_locked_profile)
    monkeypatch.setattr(collector, "resolve_provider_for_issue", AsyncMock(return_value=provider))

    async def resolve_context():
        async with maker() as db:
            issue = await db.get(Issue, issue_id)
            assert issue is not None
            return await collector._resolve_ci_repair_execution_context(db, issue)

    context_task = asyncio.create_task(resolve_context())
    await asyncio.wait_for(profile_locked.wait(), timeout=2)
    patch_db = maker()
    patch_task = asyncio.create_task(_patch_pre_script(patch_db, expected_revision=1))
    await asyncio.sleep(0.05)
    assert not patch_task.done(), "PATCH must wait for CI repair's Shared lock"
    release_profile.set()
    shared, profile, resolved_provider = await asyncio.wait_for(context_task, timeout=2)
    await asyncio.wait_for(patch_task, timeout=2)
    await patch_db.close()

    assert shared.revision == 1
    assert profile.id == profile_id
    assert resolved_provider is provider


async def test_f6_switch_reloads_target_profile_after_shared_lock_barrier(
    maker, migration_db, monkeypatch
):
    """F6 must freeze the Profile version serialized after the Shared lock.

    ``get_task_with_access_check`` eagerly loads the Task's current Profile, so
    this reproduces the dangerous identity-map window: a Profile writer has an
    uncommitted new image while F6 first observes the old image, then waits for
    Shared.  Once the writer commits, F6 must lock and repopulate the target
    Profile before readiness/snapshotting; reusing the identity-map object would
    freeze the old image.
    """
    _, profile_id, issue_id, task_id = await _seed(maker)
    old_image = "codify-worker/java21:2026.07"
    new_image = "codify-worker/java21:2026.08"
    async with maker() as db:
        profile = await db.get(WorkerProfile, profile_id)
        task = await db.get(Task, task_id)
        assert profile is not None and profile.image == old_image
        assert task is not None
        provider = AIProvider(
            name=f"f6-provider-{uuid.uuid4().hex[:8]}",
            base_url="https://provider.example.test",
            model="test-model",
            provider_kind="anthropic_compatible",
            model_protocol="anthropic_messages",
            provider_options={},
            is_default=False,
            is_disabled=False,
        )
        db.add(provider)
        await db.flush()
        task.provider_id = provider.id
        snapshot = TaskWorkerProfileSnapshot(
            task_id=task.id,
            worker_profile_id=profile.id,
            profile_name=profile.name,
            image=profile.image,
            runtime_mode=profile.runtime_mode,
            volume_mounts=[],
            environment_variables=[],
            pre_script="",
            post_script="",
            default_execute_run_instruction_template="execute {{user_prompt}}",
            default_plan_run_instruction_template="plan {{user_prompt}}",
            ci_auto_repair_run_instruction_template="repair {{issue_title}}",
            harness_key="claude",
            runtime_contract_version="codify.worker.harness/v1",
            skill_selection_source="profile",
            shared_configuration_revision=1,
        )
        snapshot.skill_references = []
        db.add(snapshot)
        await db.commit()
        provider_id = provider.id

    writer_ready = asyncio.Event()
    release_writer = asyncio.Event()

    async def profile_writer() -> None:
        async with maker() as db:
            shared = await load_shared_configuration(db, for_update=True)
            assert shared.revision == 1
            profile = await db.get(
                WorkerProfile,
                profile_id,
                with_for_update=True,
                populate_existing=True,
            )
            assert profile is not None
            profile.image = new_image
            await db.flush()
            writer_ready.set()
            await release_writer.wait()
            await db.commit()

    captured: list[tuple[str, int]] = []

    class SnapshotCaptured(RuntimeError):
        pass

    async def ready(*_args, **_kwargs):
        return SimpleNamespace(is_unavailable=False, is_ready=True, harness_inventory=None)

    async def capture_snapshot(
        _db,
        _task,
        target_profile,
        *,
        shared_configuration,
        **_kwargs,
    ):
        captured.append((target_profile.image, shared_configuration.revision))
        raise SnapshotCaptured

    async def resolve_provider(db, _issue, _provider_id):
        provider = await db.get(AIProvider, provider_id)
        assert provider is not None
        return provider

    async def load_task(task_id, db, access_scope, current_user, *, with_for_update):
        return await get_task_with_access_check(
            task_id,
            db,
            access_scope,
            current_user,
            require_operator=False,
            with_for_update=with_for_update,
        )

    services = TaskUpdateServices(
        get_task_with_access_check=load_task,
        get_project_metadata=AsyncMock(return_value={}),
        resolve_provider_for_issue=resolve_provider,
        select_snapshot_run_instruction_template=MagicMock(),
        render_and_store_task_prompt=MagicMock(),
    )

    async def run_f6() -> None:
        async with maker() as db:
            with pytest.raises(SnapshotCaptured):
                await update_task_record(
                    task_id=task_id,
                    request=UpdateTaskRequest(worker_profile_id=profile_id),
                    db=db,
                    current_user=None,
                    access_scope=ProjectAccessScope(
                        is_unrestricted=True,
                        accessible_projects=[],
                    ),
                    services=services,
                )

    monkeypatch.setattr("app.api.task_update_service.readiness_for_profile", ready)
    monkeypatch.setattr(
        "app.api.task_update_service.replace_task_worker_snapshot",
        capture_snapshot,
    )
    monkeypatch.setattr(
        "app.api.task_update_service.require_task_execution_writer",
        MagicMock(),
    )

    writer = asyncio.create_task(profile_writer())
    await asyncio.wait_for(writer_ready.wait(), timeout=2)
    f6 = asyncio.create_task(run_f6())
    await asyncio.sleep(0.05)
    assert not f6.done(), "F6 must wait for the Profile writer's Shared lock"

    release_writer.set()
    await asyncio.wait_for(asyncio.gather(writer, f6), timeout=5)

    assert captured == [(new_image, 1)]
