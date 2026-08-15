"""Admin Profile API §16.2 contract tests.

Covers F4: the Profile management API distinguishes overrides/effective/sources
and returns the current shared revision plus runtime sections. ``matches_current_input``
is recomputed server-side from the current shared baseline + Profile overrides +
resolved Docker target, and ``runtime_readiness.status`` is the read-time derived
status (an expired ``ready`` row reads as ``unknown``).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.worker_profiles import (
    _build_verification_runtime,
    _verification_digest,
    create_worker_profile,
    list_worker_profiles_for_admin,
)
from app.config import get_effective_settings
from app.core.utcnow import utcnow
from app.core.worker_runtime_readiness import fingerprint_from_docker_target
from app.core.worker_shared_configuration import (
    WorkerSharedConfigurationContext,
    resolve_effective_configuration,
)
from app.models import (
    Base,
    WorkerProfile,
    WorkerRuntimeReadiness,
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
        volume_mounts=[],
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


def _profile_kwargs(**overrides) -> dict:
    kwargs = dict(
        name="Explicit Worker",
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
    kwargs.update(overrides)
    return kwargs


async def _seed_profile(db, **overrides) -> WorkerProfile:
    profile = WorkerProfile(**_profile_kwargs(**overrides))
    profile.environment_variables = []
    db.add(profile)
    await db.flush()
    return profile


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


async def _effective(db, profile: WorkerProfile):
    shared = await _reload_shared(db)
    return resolve_effective_configuration(profile, shared)


def _current_verification_digest(db_profile: WorkerProfile, effective) -> str:
    settings = get_effective_settings()
    runtime = _build_verification_runtime(db_profile, effective, settings)
    return _verification_digest(db_profile, effective, runtime, settings)


def _locator_fingerprint(db_profile: WorkerProfile, effective, settings) -> str:
    return fingerprint_from_docker_target(
        settings,
        docker_host=getattr(db_profile, "docker_host", None),
        docker_tls_ca=getattr(db_profile, "docker_tls_ca", None),
        docker_tls_cert=getattr(db_profile, "docker_tls_cert", None),
        docker_tls_key=getattr(db_profile, "docker_tls_key", None),
        runtime_mode=effective.runtime_mode,
        worker_kit_version=effective.worker_kit_version,
        worker_kit_path=effective.worker_kit_path,
    )


async def _admin_list(db):
    return await list_worker_profiles_for_admin(db)


@pytest.mark.asyncio
async def test_admin_list_includes_16_2_sections(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        await _seed_profile(db)
        await db.commit()

        profiles = await _admin_list(db)

    assert len(profiles) == 1
    payload = profiles[0]
    assert set(payload) >= {
        "overrides",
        "effective",
        "sources",
        "shared_revision",
        "runtime_verification",
        "runtime_readiness",
    }
    overrides = payload["overrides"]
    assert set(overrides) == {
        "worker_kit",
        "pre_script",
        "post_script",
        "volume_mounts",
        "masked_volume_mount_paths",
        "environment_variables",
    }
    assert set(payload["effective"]) == {"worker_kit_version", "worker_kit_path"}
    assert set(payload["sources"]) == {"worker_kit", "pre_script", "post_script"}
    assert payload["shared_revision"] == 1
    assert set(payload["runtime_verification"]) == {
        "verified_at",
        "verified_runtime_configuration_digest",
        "matches_current_input",
    }
    assert set(payload["runtime_readiness"]) == {"status", "checked_at", "ready_until"}
    assert payload["runtime_readiness"]["status"] == "unknown"


@pytest.mark.asyncio
async def test_sources_vocabulary_system_vs_override(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        await _seed_profile(
            db,
            worker_kit_source="system",
            runtime_mode="mounted_kit",
            worker_kit_version="0.4.0",
            worker_kit_path="/opt/codify/worker-kits/0.4.0",
            pre_script=None,
            post_script="profile-post",
        )
        await db.commit()

        payload = (await _admin_list(db))[0]

    assert payload["overrides"]["worker_kit"] is None
    assert payload["sources"] == {
        "worker_kit": "system",
        "pre_script": "system",
        "post_script": "profile_override",
    }


@pytest.mark.asyncio
async def test_matches_current_input_true_when_digest_current(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        profile = await _seed_profile(db)
        effective = await _effective(db, profile)
        profile.verified_runtime_configuration_digest = _current_verification_digest(
            profile, effective
        )
        profile.verified_at = utcnow()
        await db.commit()

        payload = (await _admin_list(db))[0]

    assert payload["runtime_verification"]["matches_current_input"] is True
    assert payload["runtime_verification"]["verified_runtime_configuration_digest"] is not None


@pytest.mark.asyncio
async def test_matches_current_input_false_when_digest_stale(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        profile = await _seed_profile(db)
        profile.verified_runtime_configuration_digest = "stale-digest"
        profile.verified_at = utcnow()
        await db.commit()

        payload = (await _admin_list(db))[0]

    assert payload["runtime_verification"]["matches_current_input"] is False


@pytest.mark.asyncio
async def test_matches_current_input_false_when_no_digest(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        await _seed_profile(db)
        await db.commit()

        payload = (await _admin_list(db))[0]

    assert payload["runtime_verification"]["verified_runtime_configuration_digest"] is None
    assert payload["runtime_verification"]["matches_current_input"] is False


@pytest.mark.asyncio
async def test_runtime_readiness_unknown_for_expired_ready_row(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        profile = await _seed_profile(
            db,
            worker_kit_source="system",
            runtime_mode="mounted_kit",
            worker_kit_version="0.4.0",
            worker_kit_path="/opt/codify/worker-kits/0.4.0",
        )
        effective = await _effective(db, profile)
        settings = get_effective_settings()
        fingerprint = _locator_fingerprint(profile, effective, settings)
        assert fingerprint is not None
        db.add(
            WorkerRuntimeReadiness(
                runtime_locator_fingerprint=fingerprint,
                docker_daemon_key="tcp://localhost:2376",
                runtime_mode=effective.runtime_mode,
                worker_kit_version=effective.worker_kit_version,
                worker_kit_path=effective.worker_kit_path,
                status="ready",
                checked_at=utcnow() - timedelta(hours=2),
                ready_until=utcnow() - timedelta(hours=1),
            )
        )
        await db.commit()

        payload = (await _admin_list(db))[0]

    # F4: an expired ready row must read back as unknown, never stale-ready.
    assert payload["runtime_readiness"]["status"] == "unknown"
    assert payload["runtime_readiness"]["checked_at"] is not None


@pytest.mark.asyncio
async def test_runtime_readiness_ready_for_active_row(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)
        profile = await _seed_profile(
            db,
            worker_kit_source="system",
            runtime_mode="mounted_kit",
            worker_kit_version="0.4.0",
            worker_kit_path="/opt/codify/worker-kits/0.4.0",
        )
        effective = await _effective(db, profile)
        settings = get_effective_settings()
        fingerprint = _locator_fingerprint(profile, effective, settings)
        assert fingerprint is not None
        db.add(
            WorkerRuntimeReadiness(
                runtime_locator_fingerprint=fingerprint,
                docker_daemon_key="tcp://localhost:2376",
                runtime_mode=effective.runtime_mode,
                worker_kit_version=effective.worker_kit_version,
                worker_kit_path=effective.worker_kit_path,
                status="ready",
                checked_at=utcnow(),
                ready_until=utcnow() + timedelta(minutes=10),
            )
        )
        await db.commit()

        payload = (await _admin_list(db))[0]

    assert payload["runtime_readiness"]["status"] == "ready"


@pytest.mark.asyncio
async def test_create_response_includes_16_2_sections(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared(db)

        from app.api.worker_profiles import WorkerProfileCreateRequest

        response = await create_worker_profile(
            WorkerProfileCreateRequest(
                name="Create Contract",
                image="codify-worker/java21:2026.07",
                worker_kit_source="profile",
                runtime_mode="baked_image",
                default_execute_run_instruction_template="execute {{user_prompt}}",
                default_plan_run_instruction_template="plan {{user_prompt}}",
                ci_auto_repair_run_instruction_template="repair {{issue_title}}",
            ),
            db=db,
        )

    assert response["overrides"]["worker_kit"]["runtime_mode"] == "baked_image"
    assert response["sources"]["worker_kit"] == "profile_override"
    assert response["shared_revision"] == 1
    assert response["runtime_verification"]["matches_current_input"] is False
    assert response["runtime_readiness"]["status"] == "unknown"
