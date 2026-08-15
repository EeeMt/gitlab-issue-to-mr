"""Profile API inheritance semantics for the shared worker configuration.

Covers §11.2/§11.3: creating a Profile with ``worker_kit_source=system``
inherits its kit from the shared baseline and fails when none is configured,
``volume_mount_masks`` and ``mask`` environment operations are preserved
through create/update/duplicate, and ``expected_shared_revision`` enforces an
optimistic-revision check (409) on the Profile write path.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import StaticPool

from app.api.worker_profiles import (
    WorkerProfileCreateRequest,
    WorkerProfileEnvironmentVariableRequest,
    WorkerProfileUpdateRequest,
    create_worker_profile,
    duplicate_worker_profile,
    update_worker_profile,
)
from app.core.worker_shared_configuration import (
    ENV_OPERATION_MASK,
    ENV_OPERATION_SET,
    WorkerSharedConfigurationContext,
    resolve_effective_configuration,
)
from app.models import (
    Base,
    WorkerProfile,
    WorkerProfileEnvironmentVariable,
    WorkerSharedConfiguration,
    WorkerSharedEnvironmentVariable,
)


@pytest.fixture
def db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    return _create


async def _seed_shared(db, *, revision: int = 1) -> WorkerSharedConfiguration:
    row = WorkerSharedConfiguration(
        id=1,
        revision=revision,
        runtime_mode="mounted_kit",
        worker_kit_version="0.4.0",
        worker_kit_path="/opt/codify/worker-kits/0.4.0",
        volume_mounts=[
            {"host_path": "/srv/shared", "container_path": "/shared", "mode": "ro"}
        ],
        pre_script="shared-pre",
        post_script="shared-post",
        default_execute_run_instruction_template="shared execute {{user_prompt}}",
        default_plan_run_instruction_template="shared plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="shared repair {{issue_title}}",
    )
    db.add(row)
    db.add(
        WorkerSharedEnvironmentVariable(
            worker_shared_configuration_id=1,
            key="SHARED_A",
            value="a",
            is_secret=False,
        )
    )
    await db.flush()
    return row


async def _reload_shared(db) -> WorkerSharedConfigurationContext:
    row = await db.get(WorkerSharedConfiguration, 1)
    env = tuple(
        (
            await db.execute(
                select(WorkerSharedEnvironmentVariable).order_by(
                    WorkerSharedEnvironmentVariable.key
                )
            )
        )
        .scalars()
        .all()
    )
    return WorkerSharedConfigurationContext(row=row, environment_variables=env)


async def _effective(db, profile_id: int):
    profile = await db.get(
        WorkerProfile,
        profile_id,
        options=[selectinload(WorkerProfile.environment_variables)],
    )
    shared = await _reload_shared(db)
    return resolve_effective_configuration(profile, shared)


def _create_request(**overrides) -> WorkerProfileCreateRequest:
    kwargs = dict(
        name="Inheriting Worker",
        image="codify-worker/java21:2026.07",
        default_execute_run_instruction_template="execute {{user_prompt}}",
        default_plan_run_instruction_template="plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="repair {{issue_title}}",
    )
    kwargs.update(overrides)
    return WorkerProfileCreateRequest(**kwargs)


@pytest.mark.asyncio
async def test_create_system_kit_profile_inherits_shared_runtime(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        response = await create_worker_profile(
            _create_request(worker_kit_source="system", runtime_mode="baked_image"),
            db=db,
        )
        effective = await _effective(db, response["id"])

    assert response["worker_kit_source"] == "system"
    assert effective.runtime_mode == "mounted_kit"
    assert effective.worker_kit_version == "0.4.0"
    assert effective.worker_kit_path == "/opt/codify/worker-kits/0.4.0"


@pytest.mark.asyncio
async def test_create_profile_defaults_to_system_kit_and_inherits_shared(db_factory):
    """F1: a new Profile defaults to ``worker_kit_source=system`` and inherits the
    shared Kit (§18.6)."""
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        response = await create_worker_profile(
            _create_request(runtime_mode="baked_image"),
            db=db,
        )
        effective = await _effective(db, response["id"])

    assert response["worker_kit_source"] == "system"
    assert effective.runtime_mode == "mounted_kit"
    assert effective.worker_kit_version == "0.4.0"
    assert effective.worker_kit_path == "/opt/codify/worker-kits/0.4.0"


@pytest.mark.asyncio
async def test_create_profile_default_system_kit_requires_shared_baseline(db_factory):
    """F1: the default ``worker_kit_source=system`` requires a shared baseline, so
    a bare create without one fails closed (§18.6)."""
    session_factory = await db_factory()
    async with session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await create_worker_profile(_create_request(), db=db)

    assert exc.value.status_code == 422
    assert "requires a configured shared" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_create_system_kit_profile_requires_shared_baseline(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await create_worker_profile(_create_request(worker_kit_source="system"), db=db)

    assert exc.value.status_code == 422
    assert "requires a configured shared" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_create_profile_with_volume_mount_masks(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        response = await create_worker_profile(
            _create_request(
                volume_mounts=[
                    {"host_path": "/srv/a", "container_path": "/shared/a", "mode": "rw"}
                ],
                volume_mount_masks=["/shared"],
            ),
            db=db,
        )
        effective = await _effective(db, response["id"])

    assert response["volume_mount_masks"] == ["/shared"]
    by_path = {mount["container_path"]: mount for mount in effective.volume_mounts}
    assert "/shared" not in by_path
    assert by_path["/shared/a"]["host_path"] == "/srv/a"


@pytest.mark.asyncio
async def test_create_profile_with_env_mask_operation(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        response = await create_worker_profile(
            _create_request(
                environment_variables=[
                    WorkerProfileEnvironmentVariableRequest(
                        key="SHARED_A",
                        value=None,
                        operation=ENV_OPERATION_MASK,
                    )
                ],
            ),
            db=db,
        )
        effective = await _effective(db, response["id"])

    assert "SHARED_A" not in {item["key"] for item in effective.environment_variables}


@pytest.mark.asyncio
async def test_create_profile_expected_shared_revision_conflict(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db, revision=3)
        with pytest.raises(HTTPException) as exc:
            await create_worker_profile(
                _create_request(
                    worker_kit_source="system",
                    expected_shared_revision=99,
                ),
                db=db,
            )

    assert exc.value.status_code == 409
    assert exc.value.detail == "shared_configuration_changed"


@pytest.mark.asyncio
async def test_update_profile_to_system_kit_validates_against_shared(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        profile = WorkerProfile(
            name="Standalone Worker",
            enabled=True,
            is_default=False,
            image="codify-worker/java21:2026.07",
            worker_kit_source="profile",
            runtime_mode="baked_image",
            volume_mounts=[],
            pre_script="",
            post_script="",
            default_execute_run_instruction_template="execute {{user_prompt}}",
            default_plan_run_instruction_template="plan {{user_prompt}}",
            ci_auto_repair_run_instruction_template="repair {{issue_title}}",
        )
        db.add(profile)
        await db.commit()
        profile_id = profile.id

        response = await update_worker_profile(
            profile_id,
            WorkerProfileUpdateRequest(
                worker_kit_source="system",
                expected_shared_revision=1,
            ),
            db=db,
        )
        effective = await _effective(db, profile_id)

    assert response["worker_kit_source"] == "system"
    assert effective.runtime_mode == "mounted_kit"
    assert effective.worker_kit_version == "0.4.0"


@pytest.mark.asyncio
async def test_duplicate_preserves_inheritance_intent(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        source = WorkerProfile(
            name="Inheriting Source",
            enabled=True,
            is_default=False,
            image="codify-worker/java21:2026.07",
            worker_kit_source="system",
            runtime_mode="baked_image",
            volume_mounts=[],
            volume_mount_masks=["/shared"],
            pre_script="",
            post_script="",
            default_execute_run_instruction_template="execute {{user_prompt}}",
            default_plan_run_instruction_template="plan {{user_prompt}}",
            ci_auto_repair_run_instruction_template="repair {{issue_title}}",
            environment_variables=[
                WorkerProfileEnvironmentVariable(
                    key="SHARED_A",
                    value=None,
                    operation=ENV_OPERATION_MASK,
                    is_secret=False,
                ),
                WorkerProfileEnvironmentVariable(
                    key="PROFILE_ONLY",
                    value="p",
                    operation=ENV_OPERATION_SET,
                    is_secret=False,
                ),
            ],
        )
        db.add(source)
        await db.commit()
        source_id = source.id

        response = await duplicate_worker_profile(source_id, db=db)
        copy = await db.get(
            WorkerProfile,
            response["id"],
            options=[selectinload(WorkerProfile.environment_variables)],
        )

        env_by_key = {row.key: row for row in copy.environment_variables}

    assert copy.worker_kit_source == "system"
    assert copy.volume_mount_masks == ["/shared"]
    assert env_by_key["SHARED_A"].operation == ENV_OPERATION_MASK
    assert env_by_key["PROFILE_ONLY"].operation == ENV_OPERATION_SET


@pytest.mark.asyncio
async def test_create_profile_with_null_scripts_validates_shared_kit_collision(
    db_factory,
):
    """F1: NULL scripts inherit the shared baseline (§11.2).

    A create that only sets the mounted-kit coordinates but leaves the scripts
    NULL must resolve the shared baseline, so a shared mount that collides with
    the kit path fails the create instead of being silently ignored.
    """
    session_factory = await db_factory()
    async with session_factory() as db:
        db.add(
            WorkerSharedConfiguration(
                id=1,
                revision=1,
                runtime_mode="mounted_kit",
                worker_kit_version="0.4.0",
                worker_kit_path="/opt/codify/worker-kits/0.4.0",
                volume_mounts=[
                    {
                        "host_path": "/srv/kit",
                        "container_path": "/opt/codify-kit",
                        "mode": "ro",
                    }
                ],
                pre_script="shared-pre",
                post_script="shared-post",
                default_execute_run_instruction_template="shared execute {{user_prompt}}",
                default_plan_run_instruction_template="shared plan {{user_prompt}}",
                ci_auto_repair_run_instruction_template="shared repair {{issue_title}}",
            )
        )
        await db.flush()

        with pytest.raises(HTTPException) as exc:
            await create_worker_profile(
                _create_request(
                    worker_kit_source="profile",
                    runtime_mode="mounted_kit",
                    worker_kit_version="0.4.0",
                    worker_kit_path="/opt/codify/worker-kits/0.4.0",
                    pre_script=None,
                    post_script=None,
                ),
                db=db,
            )

    assert exc.value.status_code == 422
    assert "worker-kit path" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_update_profile_mounts_only_rejects_set_mask_conflict(db_factory):
    """F2: a mounts-only PATCH that sets a path the profile also masks must 422.

    Before the fix the PATCH applied ``volume_mounts`` without revalidating the
    mask set, leaving the profile with a path that was both set and masked
    (§7.3/§24.17).
    """
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        profile = WorkerProfile(
            name="Masked Worker",
            enabled=True,
            is_default=False,
            image="codify-worker/java21:2026.07",
            worker_kit_source="profile",
            runtime_mode="baked_image",
            volume_mounts=[],
            volume_mount_masks=["/data"],
            pre_script="",
            post_script="",
            default_execute_run_instruction_template="execute {{user_prompt}}",
            default_plan_run_instruction_template="plan {{user_prompt}}",
            ci_auto_repair_run_instruction_template="repair {{issue_title}}",
        )
        db.add(profile)
        await db.commit()
        profile_id = profile.id

        with pytest.raises(HTTPException) as exc:
            await update_worker_profile(
                profile_id,
                WorkerProfileUpdateRequest(
                    volume_mounts=[
                        {
                            "host_path": "/srv/data",
                            "container_path": "/data",
                            "mode": "rw",
                        }
                    ],
                ),
                db=db,
            )

    assert exc.value.status_code == 422
    assert "cannot be both set and masked" in str(exc.value.detail)


def _overridden_profile(*, name="Override Worker"):
    return WorkerProfile(
        name=name,
        enabled=True,
        is_default=False,
        image="codify-worker/java21:2026.07",
        worker_kit_source="profile",
        runtime_mode="baked_image",
        volume_mounts=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="execute {{user_prompt}}",
        default_plan_run_instruction_template="plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="repair {{issue_title}}",
    )


@pytest.mark.asyncio
async def test_update_null_template_restores_inheritance_and_keeps_other_overrides(
    db_factory,
):
    """PATCHing one of three overridden run-instruction templates to null restores
    inheritance for that template while the other two keep their overrides."""
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        profile = _overridden_profile()
        db.add(profile)
        await db.commit()
        profile_id = profile.id

        response = await update_worker_profile(
            profile_id,
            WorkerProfileUpdateRequest(
                default_execute_run_instruction_template=None,
            ),
            db=db,
        )
        effective = await _effective(db, profile_id)

    assert response["default_execute_run_instruction_template"] is None
    assert response["default_plan_run_instruction_template"] == "plan {{user_prompt}}"
    assert response["ci_auto_repair_run_instruction_template"] == "repair {{issue_title}}"
    assert effective.default_execute_run_instruction_template == (
        "shared execute {{user_prompt}}"
    )
    assert effective.default_plan_run_instruction_template == "plan {{user_prompt}}"
    assert effective.ci_auto_repair_run_instruction_template == "repair {{issue_title}}"


@pytest.mark.asyncio
async def test_update_explicit_blank_template_remains_rejected(db_factory):
    """An explicit empty-string template is still a blank (not inheritance) and
    keeps being rejected with 422; the profile's prior override survives."""
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        profile = _overridden_profile()
        db.add(profile)
        await db.commit()
        profile_id = profile.id

        with pytest.raises(HTTPException) as exc:
            await update_worker_profile(
                profile_id,
                WorkerProfileUpdateRequest(
                    default_execute_run_instruction_template="",
                ),
                db=db,
            )
        # The failed PATCH rolled back and expired the session's copy; reload the
        # collection explicitly so the effective resolution does not lazy-load.
        profile = await db.get(WorkerProfile, profile_id)
        await db.refresh(profile, attribute_names=["environment_variables"])
        effective = await _effective(db, profile_id)

    assert exc.value.status_code == 422
    assert "cannot be blank" in str(exc.value.detail)
    assert effective.default_execute_run_instruction_template == "execute {{user_prompt}}"
    assert effective.default_plan_run_instruction_template == "plan {{user_prompt}}"
    assert effective.ci_auto_repair_run_instruction_template == "repair {{issue_title}}"


@pytest.mark.asyncio
async def test_update_single_field_non_empty_template_override(db_factory):
    """A single-field non-empty override still applies while the other two
    templates keep their current values."""
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        profile = _overridden_profile()
        db.add(profile)
        await db.commit()
        profile_id = profile.id

        response = await update_worker_profile(
            profile_id,
            WorkerProfileUpdateRequest(
                default_plan_run_instruction_template="plan-v2 {{user_prompt}}",
            ),
            db=db,
        )

    assert response["default_plan_run_instruction_template"] == "plan-v2 {{user_prompt}}"
    assert response["default_execute_run_instruction_template"] == "execute {{user_prompt}}"
    assert response["ci_auto_repair_run_instruction_template"] == "repair {{issue_title}}"


@pytest.mark.asyncio
async def test_update_unrelated_field_preserves_all_templates(db_factory):
    """A PATCH that does not touch the templates leaves all three untouched."""
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        profile = _overridden_profile()
        db.add(profile)
        await db.commit()
        profile_id = profile.id

        response = await update_worker_profile(
            profile_id,
            WorkerProfileUpdateRequest(description="Unrelated edit"),
            db=db,
        )

    assert response["description"] == "Unrelated edit"
    assert response["default_execute_run_instruction_template"] == "execute {{user_prompt}}"
    assert response["default_plan_run_instruction_template"] == "plan {{user_prompt}}"
    assert response["ci_auto_repair_run_instruction_template"] == "repair {{issue_title}}"


@pytest.mark.asyncio
async def test_create_null_templates_inherit_shared_baseline(db_factory):
    """The create contract accepts NULL templates (= inherit the shared
    baseline) in one atomic request, matching the update contract (§11.2)."""
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        response = await create_worker_profile(
            _create_request(
                default_execute_run_instruction_template=None,
                default_plan_run_instruction_template=None,
                ci_auto_repair_run_instruction_template=None,
            ),
            db=db,
        )
        effective = await _effective(db, response["id"])

    assert response["default_execute_run_instruction_template"] is None
    assert response["default_plan_run_instruction_template"] is None
    assert response["ci_auto_repair_run_instruction_template"] is None
    assert effective.default_execute_run_instruction_template == "shared execute {{user_prompt}}"
    assert effective.default_plan_run_instruction_template == "shared plan {{user_prompt}}"
    assert effective.ci_auto_repair_run_instruction_template == "shared repair {{issue_title}}"


@pytest.mark.asyncio
async def test_duplicate_preserves_harness_intent(db_factory):
    """Duplicating a non-default-Harness Profile carries its Harness intent
    verbatim and re-validates skills against the resolved effective config."""
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        source = WorkerProfile(
            name="Codex Source",
            enabled=True,
            is_default=False,
            image="codify-worker/java21:2026.07",
            worker_kit_source="system",
            runtime_mode="baked_image",
            volume_mounts=[],
            volume_mount_masks=[],
            pre_script="",
            post_script="",
            default_execute_run_instruction_template="execute {{user_prompt}}",
            default_plan_run_instruction_template="plan {{user_prompt}}",
            ci_auto_repair_run_instruction_template="repair {{issue_title}}",
            enabled_harnesses=["codex"],
            default_harness_key="codex",
            harness_constraints={"max_turns": 50},
            harness_runtimes={
                "codex": {
                    "source": "image",
                    "executable_path": "/usr/bin/codex",
                    "version": "0.1",
                    "binary_digest": "sha256:abc",
                }
            },
        )
        db.add(source)
        await db.commit()
        source_id = source.id

        response = await duplicate_worker_profile(source_id, db=db)
        copy = await db.get(WorkerProfile, response["id"])

    assert copy.enabled_harnesses == ["codex"]
    assert copy.default_harness_key == "codex"
    assert copy.harness_constraints == {"max_turns": 50}
    assert copy.harness_runtimes["codex"]["source"] == "image"
