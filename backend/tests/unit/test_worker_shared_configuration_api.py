"""Behavioral tests for the shared worker configuration API (GET/PATCH).

Covers §11.1: the shared baseline is validated and persisted as a revisioned
singleton, secret ciphertext is preserved across blank resubmissions, the
optimistic expected_revision check rejects concurrent edits, and a shared
change that leaves any enabled Profile statically invalid fails the whole
patch before commit.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import StaticPool

from app.api.worker_shared_configuration import (
    WorkerSharedConfigurationPatchRequest,
    get_shared_configuration,
    update_shared_configuration,
)
from app.config import get_effective_settings
from app.core.docker_client import resolve_docker_connection
from app.core.harness_registry import capability_policy
from app.core.worker_shared_configuration import (
    WorkerSharedConfigurationContext,
    effective_configuration_digest,
    resolve_effective_configuration,
)
from app.models import (
    Base,
    WorkerProfile,
    WorkerSharedConfiguration,
    WorkerSharedEnvironmentVariable,
)

_RESOLVE = object()


def _profile_digest(
    profile: WorkerProfile, effective=None, *, docker_host=_RESOLVE
) -> str:
    """Digest the API uses for one Profile in the shared-PATCH response.

    F3: the API digests the *resolved* Docker target (the Task Snapshot
    semantics), so the default mirrors ``resolve_docker_connection``. Passing an
    explicit ``docker_host`` (including ``None`` for the raw profile field)
    bypasses resolution so tests can prove the raw field is not used.
    """
    effective = effective or resolve_effective_configuration(profile)
    constraints = dict(profile.harness_constraints or {})
    harness_key = profile.default_harness_key or "claude"
    capabilities = capability_policy(harness_key, constraints)
    skills = [
        {
            "skill_id": skill.id,
            "skill_version_id": getattr(getattr(skill, "current_version", None), "id", None),
        }
        for skill in (getattr(profile, "default_skills", None) or [])
        if bool(getattr(skill, "enabled", False))
    ]
    if docker_host is _RESOLVE:
        connection = resolve_docker_connection(
            get_effective_settings(),
            docker_host=getattr(profile, "docker_host", None),
            docker_tls_ca=getattr(profile, "docker_tls_ca", None),
            docker_tls_cert=getattr(profile, "docker_tls_cert", None),
            docker_tls_key=getattr(profile, "docker_tls_key", None),
        )
        docker_host = connection.host if connection else getattr(profile, "docker_host", None)
    return effective_configuration_digest(
        effective,
        docker_host=docker_host,
        codegraph_enabled=bool(profile.codegraph_enabled),
        harness_key=harness_key,
        harness_config={
            "capabilities": capabilities,
            "sandbox_mode": capabilities.get("sandbox_mode"),
            "constraints": constraints,
        },
        skills=skills,
    )


@pytest.fixture
def db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    return _create


async def _seed_shared_configuration(db) -> WorkerSharedConfiguration:
    row = WorkerSharedConfiguration(
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
    db.add(row)
    db.add(
        WorkerSharedEnvironmentVariable(
            worker_shared_configuration_id=1,
            key="SHARED_A",
            value="a",
            is_secret=False,
        )
    )
    db.add(
        WorkerSharedEnvironmentVariable(
            worker_shared_configuration_id=1,
            key="SHARED_SECRET",
            value="ciphertext-v1",
            is_secret=True,
        )
    )
    await db.flush()
    return row


def _explicit_profile_kwargs() -> dict:
    return dict(
        name="Explicit Worker",
        enabled=True,
        is_default=True,
        image="codify-worker/java21:2026.07",
        worker_kit_source="profile",
        runtime_mode="baked_image",
        volume_mounts=[],
        pre_script="profile-pre",
        post_script="profile-post",
        default_execute_run_instruction_template="profile execute {{user_prompt}}",
        default_plan_run_instruction_template="profile plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="profile repair {{issue_title}}",
    )


async def _seed_enabled_profile(db) -> WorkerProfile:
    profile = WorkerProfile(**_explicit_profile_kwargs())
    db.add(profile)
    await db.flush()
    return profile


@pytest.mark.asyncio
async def test_get_shared_configuration_returns_seeded_values(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared_configuration(db)
        await db.commit()

        response = await get_shared_configuration(db, _admin=object())

    assert response["id"] == 1
    assert response["revision"] == 1
    assert response["runtime_mode"] == "mounted_kit"
    assert response["pre_script"] == "shared-pre"
    by_key = {item["key"]: item for item in response["environment_variables"]}
    assert by_key["SHARED_SECRET"]["value"] is None
    assert by_key["SHARED_SECRET"]["is_secret"] is True
    assert by_key["SHARED_A"]["value"] == "a"


@pytest.mark.asyncio
async def test_get_shared_configuration_404_when_not_seeded(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await get_shared_configuration(db, _admin=object())

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_patch_shared_configuration_increments_revision_and_validates_profiles(
    db_factory,
):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared_configuration(db)
        await _seed_enabled_profile(db)
        await db.commit()

        response = await update_shared_configuration(
            WorkerSharedConfigurationPatchRequest(
                expected_revision=1,
                pre_script="shared-pre-v2",
                environment_variables=[
                    {"key": "SHARED_A", "value": "a2", "is_secret": False},
                    {"key": "SHARED_SECRET", "value": "", "is_secret": True},
                    {"key": "SHARED_NEW", "value": "n", "is_secret": False},
                ],
            ),
            db=db,
        )
        # F1: even a fully explicit Profile (worker_kit_source=profile, every
        # scalar set, no masks) merges the shared baseline per-item, so the
        # shared PATCH validates and digests it against the merged config.
        profile = await db.get(
            WorkerProfile,
            1,
            options=[
                selectinload(WorkerProfile.environment_variables),
                selectinload(WorkerProfile.default_skills),
            ],
        )
        shared_row = await db.get(WorkerSharedConfiguration, 1)
        shared_env = tuple(
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
        shared = WorkerSharedConfigurationContext(
            row=shared_row, environment_variables=shared_env
        )
        expected_digest = _profile_digest(
            profile, resolve_effective_configuration(profile, shared)
        )

    assert response["revision"] == 2
    assert response["pre_script"] == "shared-pre-v2"
    assert response["profiles"] == [
        {
            "id": 1,
            "name": "Explicit Worker",
            "effective_configuration_digest": expected_digest,
            "valid": True,
        }
    ]


@pytest.mark.asyncio
async def test_patch_shared_configuration_conflicts_on_revision_mismatch(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared_configuration(db)
        await _seed_enabled_profile(db)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await update_shared_configuration(
                WorkerSharedConfigurationPatchRequest(expected_revision=99),
                db=db,
            )

    assert exc.value.status_code == 409
    assert exc.value.detail == "shared_configuration_changed"


@pytest.mark.asyncio
async def test_patch_shared_configuration_preserves_secret_ciphertext(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared_configuration(db)
        await _seed_enabled_profile(db)
        await db.commit()

        await update_shared_configuration(
            WorkerSharedConfigurationPatchRequest(
                expected_revision=1,
                environment_variables=[
                    {"key": "SHARED_A", "value": "a2", "is_secret": False},
                    {"key": "SHARED_SECRET", "value": "", "is_secret": True},
                ],
            ),
            db=db,
        )
        stored = (
            await db.execute(
                select(WorkerSharedEnvironmentVariable).where(
                    WorkerSharedEnvironmentVariable.key == "SHARED_SECRET"
                )
            )
        ).scalar_one()
        assert stored.value == "ciphertext-v1"


@pytest.mark.asyncio
async def test_patch_shared_configuration_rejects_invalid_env_key(db_factory):
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared_configuration(db)
        await _seed_enabled_profile(db)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await update_shared_configuration(
                WorkerSharedConfigurationPatchRequest(
                    expected_revision=1,
                    environment_variables=[
                        {"key": "lowercase", "value": "v", "is_secret": False}
                    ],
                ),
                db=db,
            )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_patch_shared_configuration_rejects_statically_invalid_profile(
    db_factory,
):
    from app.models import Skill, SkillVersion

    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared_configuration(db)
        # The profile inherits its kit from the shared baseline and carries a
        # default skill; a shared edit that flips the shared runtime to baked
        # image (no skills) must be rejected on the combined config.
        version = SkillVersion(
            name="review-changes",
            description="Review changes before delivery.",
            skill_md=(
                "---\nname: review-changes\ndescription: Review changes.\n---\n\n"
                "Inspect the final diff.\n"
            ),
            files=[],
            package_size_bytes=100,
            digest="a" * 64,
        )
        skill = Skill(
            name=version.name,
            description=version.description,
            current_version=version,
            enabled=True,
        )
        profile_kwargs = _explicit_profile_kwargs()
        profile_kwargs["worker_kit_source"] = "system"
        profile = WorkerProfile(
            **profile_kwargs,
            default_skills=[skill],
        )
        db.add(profile)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await update_shared_configuration(
                WorkerSharedConfigurationPatchRequest(
                    expected_revision=1,
                    runtime_mode="baked_image",
                    worker_kit_version=None,
                    worker_kit_path=None,
                ),
                db=db,
            )

    assert exc.value.status_code == 422
    assert "Explicit Worker" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_patch_shared_configuration_merges_for_explicit_profile(db_factory):
    """F1: a fully explicit Profile is validated and digested WITH the shared merge."""
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared_configuration(db)
        await _seed_enabled_profile(db)
        await db.commit()

        response = await update_shared_configuration(
            WorkerSharedConfigurationPatchRequest(
                expected_revision=1,
                pre_script="shared-pre-v2",
            ),
            db=db,
        )
        profile = await db.get(
            WorkerProfile,
            1,
            options=[
                selectinload(WorkerProfile.environment_variables),
                selectinload(WorkerProfile.default_skills),
            ],
        )
        shared_row = await db.get(WorkerSharedConfiguration, 1)
        shared_env = tuple(
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
        shared = WorkerSharedConfigurationContext(
            row=shared_row, environment_variables=shared_env
        )

    returned_digest = response["profiles"][0]["effective_configuration_digest"]
    # F1: the response resolves every Profile against the shared baseline, so
    # its digest reflects the merged config (shared SHARED_A/SHARED_SECRET).
    assert returned_digest == _profile_digest(
        profile, resolve_effective_configuration(profile, shared)
    )
    # Resolving without the shared baseline must produce a different digest,
    # proving the PATCH folded the shared env/mounts in.
    standalone_digest = _profile_digest(profile)
    assert returned_digest != standalone_digest


@pytest.mark.asyncio
async def test_patch_shared_configuration_digest_uses_resolved_docker_host(db_factory):
    """F3: the preview digest uses the resolved Docker target (Task Snapshot
    semantics), so a profile with no explicit host digests the deployment
    default instead of the empty raw field (§12.3/§16.2)."""
    session_factory = await db_factory()
    async with session_factory() as db:
        await _seed_shared_configuration(db)
        await _seed_enabled_profile(db)
        await db.commit()

        response = await update_shared_configuration(
            WorkerSharedConfigurationPatchRequest(
                expected_revision=1,
                pre_script="shared-pre-v2",
            ),
            db=db,
        )
        profile = await db.get(
            WorkerProfile,
            1,
            options=[
                selectinload(WorkerProfile.environment_variables),
                selectinload(WorkerProfile.default_skills),
            ],
        )
        shared_row = await db.get(WorkerSharedConfiguration, 1)
        shared_env = tuple(
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
        shared = WorkerSharedConfigurationContext(
            row=shared_row, environment_variables=shared_env
        )

    returned_digest = response["profiles"][0]["effective_configuration_digest"]
    effective = resolve_effective_configuration(profile, shared)
    connection = resolve_docker_connection(
        get_effective_settings(),
        docker_host=getattr(profile, "docker_host", None),
        docker_tls_ca=getattr(profile, "docker_tls_ca", None),
        docker_tls_cert=getattr(profile, "docker_tls_cert", None),
        docker_tls_key=getattr(profile, "docker_tls_key", None),
    )
    assert returned_digest == _profile_digest(
        profile, effective, docker_host=connection.host
    )
    # The raw profile.docker_host is None, so a digest built from it (empty
    # docker target) must differ from the resolved one — proving the PATCH no
    # longer feeds the raw field into the digest.
    assert returned_digest != _profile_digest(
        profile, effective, docker_host=getattr(profile, "docker_host", None)
    )
