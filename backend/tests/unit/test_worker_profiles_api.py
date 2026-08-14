from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.worker_profiles import (
    DockerConnectionTestRequest,
    WorkerProfileCreateRequest,
    WorkerProfileEnvironmentVariableRequest,
    WorkerProfileUpdateRequest,
    WorkerRuntimeVerificationRequest,
    create_worker_profile,
    delete_worker_profile,
    disable_worker_profile,
    duplicate_worker_profile,
    set_default_worker_profile_endpoint,
    update_worker_profile,
    verify_worker_profile_runtime,
)
from app.api.worker_profiles import (
    test_worker_profile_docker_connection as run_docker_connection_test,
)
from app.core.worker_profiles import parse_worker_profile_mounts
from app.database import get_db
from app.dependencies.auth import (
    require_admin_user,
    require_authenticated_user,
)
from app.main import app
from app.models import (
    Base,
    Issue,
    IssueStatus,
    Skill,
    SkillVersion,
    WorkerProfile,
    WorkerProfileEnvironmentVariable,
)


def _make_profile(
    *,
    id=1,
    name="Default Worker",
    enabled=True,
    is_default=False,
    environment_variables=None,
):
    return SimpleNamespace(
        id=id,
        name=name,
        description=None,
        enabled=enabled,
        is_default=is_default,
        image="codify-worker/java21-maven:2026.07",
        runtime_mode="baked_image",
        worker_kit_version=None,
        worker_kit_path=None,
        docker_host="tcp://worker:2376",
        docker_tls_ca="/certs/ca.pem",
        docker_tls_cert="/certs/cert.pem",
        docker_tls_key="/certs/key.pem",
        codegraph_enabled=False,
        volume_mounts=[],
        environment_variables=environment_variables or [],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )


@pytest.mark.parametrize(
    ("request_type", "request_kwargs"),
    [
        (
            WorkerProfileCreateRequest,
            {"name": "Worker", "image": "worker:latest", "default_skill_ids": [True]},
        ),
        (WorkerProfileUpdateRequest, {"default_skill_ids": [True]}),
        (WorkerProfileUpdateRequest, {"default_skill_ids": [0]}),
        (WorkerProfileUpdateRequest, {"default_skill_ids": [1, 1]}),
    ],
)
def test_worker_profile_requests_reject_invalid_skill_ids(request_type, request_kwargs):
    with pytest.raises(ValidationError):
        request_type(**request_kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"enabled_harnesses": ["claude", "opencode"], "default_harness_key": "claude"},
        {"enabled_harnesses": ["claude"], "default_harness_key": "codex"},
        {"enabled_harnesses": [], "default_harness_key": "claude"},
        {"harness_constraints": {"privileged": True}},
        {"harness_runtimes": {"claude": {"source": "docker exec rm -rf"}}},
        {"harness_runtimes": {"unknown": {"source": "image"}}},
    ],
)
def test_worker_profile_requests_reject_invalid_harness_fields(kwargs):
    with pytest.raises(ValidationError):
        WorkerProfileCreateRequest(name="Worker", image="worker:latest", **kwargs)


def test_worker_profile_request_accepts_valid_harness_fields():
    request = WorkerProfileCreateRequest(
        name="Worker",
        image="worker:latest",
        enabled_harnesses=["claude"],
        default_harness_key="claude",
        harness_constraints={"max_turns": 20},
        harness_runtimes={
            "claude": {
                "source": "image",
                "executable_path": "/usr/local/bin/claude",
            }
        },
    )
    assert request.enabled_harnesses == ["claude"]
    assert request.default_harness_key == "claude"
    assert request.harness_constraints == {"max_turns": 20}


@pytest.mark.asyncio
async def test_create_worker_profile_rejects_duplicate_env_keys():
    db = MagicMock()
    db.add = MagicMock()
    name_check_result = MagicMock()
    name_check_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=name_check_result)
    db.flush = AsyncMock()
    db.rollback = AsyncMock()

    request = WorkerProfileCreateRequest(
        name="Java Worker",
        image="codify-worker-java:latest",
        volume_mounts=[],
        environment_variables=[
            WorkerProfileEnvironmentVariableRequest(key="MAVEN_OPTS", value="-Xmx1g"),
            WorkerProfileEnvironmentVariableRequest(key="MAVEN_OPTS", value="-Xmx2g"),
        ],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
    )

    with pytest.raises(HTTPException) as exc:
        await create_worker_profile(request, db=db)
    assert exc.value.status_code == 422
    assert "Duplicate worker environment variable key" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_create_worker_profile_returns_created_profile_after_commit_without_lazy_load():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        version = SkillVersion(
            name="review-changes",
            description="Review changes before delivery.",
            skill_md=(
                "---\n"
                "name: review-changes\n"
                "description: Review changes before delivery.\n"
                "---\n\n"
                "Inspect the final diff.\n"
            ),
            files=[],
            package_size_bytes=23,
            digest="a" * 64,
        )
        skill = Skill(
            name=version.name,
            description=version.description,
            current_version=version,
            enabled=True,
        )
        db.add(skill)
        await db.flush()
        request = WorkerProfileCreateRequest(
            name="Java Worker",
            image="codify-worker-java:latest",
            runtime_mode="mounted_kit",
            worker_kit_version="0.3.5",
            worker_kit_path="/opt/codify/worker-kits/0.3.5-linux-amd64",
            codegraph_enabled=True,
            volume_mounts=[],
            environment_variables=[
                WorkerProfileEnvironmentVariableRequest(key="JAVA_OPTS", value="-Xmx1g")
            ],
            default_skill_ids=[skill.id],
            default_execute_run_instruction_template="Execute {{user_prompt}}",
            default_plan_run_instruction_template="Plan {{user_prompt}}",
            ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
        )

        response = await create_worker_profile(request, db=db)

    await engine.dispose()

    assert response["name"] == "Java Worker"
    assert response["image"] == "codify-worker-java:latest"
    assert response["codegraph_enabled"] is True
    assert response["environment_variables"][0]["key"] == "JAVA_OPTS"
    assert response["default_skill_ids"] == [skill.id]


@pytest.mark.asyncio
async def test_create_baked_worker_profile_rejects_default_skills():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            version = SkillVersion(
                name="review-changes",
                description="Review changes before delivery.",
                skill_md=(
                    "---\n"
                    "name: review-changes\n"
                    "description: Review changes before delivery.\n"
                    "---\n\n"
                    "Inspect the final diff.\n"
                ),
                files=[],
                package_size_bytes=100,
                digest="b" * 64,
            )
            skill = Skill(
                name=version.name,
                description=version.description,
                current_version=version,
                enabled=True,
            )
            db.add(skill)
            await db.flush()

            with pytest.raises(HTTPException, match="baked-image mode is deprecated") as exc:
                await create_worker_profile(
                    WorkerProfileCreateRequest(
                        name="Legacy Worker",
                        image="legacy-worker:latest",
                        default_skill_ids=[skill.id],
                    ),
                    db=db,
                )
            assert exc.value.status_code == 422
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_worker_profile_locks_and_revalidates_default_skills():
    version = SkillVersion(
        id=19,
        name="review-changes",
        description="Review changes before delivery.",
        skill_md="---\nname: review-changes\ndescription: Review changes.\n---\n",
        files=[],
        package_size_bytes=100,
        digest="c" * 64,
    )
    skill = Skill(
        id=9,
        name=version.name,
        description=version.description,
        current_version=version,
        enabled=True,
    )
    source = _make_profile(id=3, name="Java Worker")
    source.runtime_mode = "mounted_kit"
    source.worker_kit_version = "0.3.5"
    source.worker_kit_path = "/opt/codify/worker-kits/0.3.5-linux-amd64"
    source.default_skills = [skill]
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    with (
        patch(
            "app.api.worker_profiles._load_profile_or_404",
            new=AsyncMock(return_value=source),
        ) as load_profile,
        patch(
            "app.api.worker_profiles._unique_copy_name",
            new=AsyncMock(return_value="Java Worker (copy)"),
        ),
        patch(
            "app.api.worker_profiles.load_worker_profile_skills",
            new=AsyncMock(return_value=[skill]),
        ) as load_skills,
        patch("app.api.worker_profiles.validate_runtime_supports_skills") as validate_runtime,
        patch(
            "app.api.worker_profiles.serialize_worker_profile_for_api",
            return_value={"name": "Java Worker (copy)", "default_skill_ids": [9]},
        ),
    ):
        response = await duplicate_worker_profile(3, db=db)

    assert response["default_skill_ids"] == [9]
    load_profile.assert_awaited_once_with(db, 3, for_update=True)
    load_skills.assert_awaited_once_with(
        db,
        [9],
        retained_disabled_skill_ids=[9],
    )
    validate_runtime.assert_called_once_with(source, [skill])
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_worker_profile_preserves_disabled_default_skill():
    version = SkillVersion(
        id=19,
        name="review-changes",
        description="Review changes before delivery.",
        skill_md="---\nname: review-changes\ndescription: Review changes.\n---\n",
        files=[],
        package_size_bytes=100,
        digest="d" * 64,
    )
    disabled_skill = Skill(
        id=9,
        name=version.name,
        description=version.description,
        current_version=version,
        enabled=False,
    )
    source = _make_profile(id=3, name="Java Worker")
    source.default_skills = [disabled_skill]
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    with (
        patch(
            "app.api.worker_profiles._load_profile_or_404",
            new=AsyncMock(return_value=source),
        ),
        patch(
            "app.api.worker_profiles.load_worker_profile_skills",
            new=AsyncMock(return_value=[disabled_skill]),
        ) as load_skills,
        patch(
            "app.api.worker_profiles._unique_copy_name",
            new=AsyncMock(return_value="Java Worker Copy"),
        ),
        patch(
            "app.api.worker_profiles.serialize_worker_profile_for_api",
            return_value={"name": "Java Worker Copy", "default_skill_ids": [9]},
        ),
    ):
        response = await duplicate_worker_profile(3, db=db)

    assert response["default_skill_ids"] == [9]
    load_skills.assert_awaited_once_with(
        db,
        [9],
        retained_disabled_skill_ids=[9],
    )
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_worker_profile_persists_loaded_relationships_without_lazy_load():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            version = SkillVersion(
                name="review-changes",
                description="Review changes before delivery.",
                skill_md=(
                    "---\n"
                    "name: review-changes\n"
                    "description: Review changes before delivery.\n"
                    "---\n\n"
                    "Inspect the final diff.\n"
                ),
                files=[],
                package_size_bytes=100,
                digest="f" * 64,
            )
            skill = Skill(
                name=version.name,
                description=version.description,
                current_version=version,
                enabled=True,
            )
            source = WorkerProfile(
                name="Mounted Worker",
                description="Profile to duplicate",
                enabled=True,
                is_default=False,
                image="runtime:latest",
                runtime_mode="mounted_kit",
                worker_kit_version="0.3.5",
                worker_kit_path="/opt/codify/worker-kits/0.3.5-linux-amd64",
                volume_mounts=[],
                pre_script="prepare",
                post_script="cleanup",
                default_execute_run_instruction_template="Execute {{user_prompt}}",
                default_plan_run_instruction_template="Plan {{user_prompt}}",
                ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
                default_skills=[skill],
                environment_variables=[
                    WorkerProfileEnvironmentVariable(
                        key="RUNTIME_SECRET",
                        value="encrypted-value",
                        is_secret=True,
                    )
                ],
            )
            db.add(source)
            await db.commit()

            response = await duplicate_worker_profile(source.id, db=db)

            assert response["name"] == "Mounted Worker Copy"
            assert response["default_skill_ids"] == [skill.id]
            assert len(response["environment_variables"]) == 1
            response_variable = response["environment_variables"][0]
            assert response_variable["key"] == "RUNTIME_SECRET"
            assert response_variable["value"] is None
            assert response_variable["is_secret"] is True
            assert response_variable["value_configured"] is True

            copied = await db.get(WorkerProfile, response["id"])
            assert copied is not None
            assert copied.environment_variables[0].value == "encrypted-value"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_worker_profile_retains_but_cannot_add_disabled_default_skill():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            version = SkillVersion(
                name="review-changes",
                description="Review changes before delivery.",
                skill_md=(
                    "---\n"
                    "name: review-changes\n"
                    "description: Review changes before delivery.\n"
                    "---\n\n"
                    "Inspect the final diff.\n"
                ),
                files=[],
                package_size_bytes=100,
                digest="e" * 64,
            )
            disabled_skill = Skill(
                name=version.name,
                description=version.description,
                current_version=version,
                enabled=False,
            )
            retained_profile = WorkerProfile(
                name="Legacy Worker",
                enabled=True,
                is_default=False,
                image="legacy-worker:latest",
                runtime_mode="baked_image",
                volume_mounts=[],
                pre_script="",
                post_script="",
                default_execute_run_instruction_template="{{user_prompt}}",
                default_plan_run_instruction_template="{{user_prompt}}",
                ci_auto_repair_run_instruction_template="{{user_prompt}}",
                default_skills=[disabled_skill],
            )
            new_profile = WorkerProfile(
                name="Mounted Worker",
                enabled=True,
                is_default=False,
                image="runtime:latest",
                runtime_mode="mounted_kit",
                worker_kit_version="0.3.5",
                worker_kit_path="/opt/codify/worker-kits/0.3.5-linux-amd64",
                volume_mounts=[],
                pre_script="",
                post_script="",
                default_execute_run_instruction_template="{{user_prompt}}",
                default_plan_run_instruction_template="{{user_prompt}}",
                ci_auto_repair_run_instruction_template="{{user_prompt}}",
            )
            db.add_all([retained_profile, new_profile])
            await db.commit()

            response = await update_worker_profile(
                retained_profile.id,
                WorkerProfileUpdateRequest(
                    description="Unrelated edit",
                    default_skill_ids=[disabled_skill.id],
                ),
                db=db,
            )
            assert response["description"] == "Unrelated edit"
            assert response["default_skill_ids"] == [disabled_skill.id]

            with pytest.raises(HTTPException, match="disabled") as exc:
                await update_worker_profile(
                    new_profile.id,
                    WorkerProfileUpdateRequest(default_skill_ids=[disabled_skill.id]),
                    db=db,
                )
            assert exc.value.status_code == 422
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_mounted_worker_profile_persists_portable_kit_contract():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        request = WorkerProfileCreateRequest(
            name="External Java Runtime",
            image="team/java21-maven:2026.07",
            runtime_mode="mounted_kit",
            worker_kit_version="0.1.0",
            worker_kit_path="/opt/codify/worker-kits/0.1.0-linux-amd64",
            volume_mounts=[],
            environment_variables=[],
            default_execute_run_instruction_template="Execute {{user_prompt}}",
            default_plan_run_instruction_template="Plan {{user_prompt}}",
            ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
        )

        response = await create_worker_profile(request, db=db)

    await engine.dispose()

    assert response["runtime_mode"] == "mounted_kit"
    assert response["worker_kit_version"] == "0.1.0"
    assert response["worker_kit_path"] == "/opt/codify/worker-kits/0.1.0-linux-amd64"


@pytest.mark.asyncio
async def test_create_mounted_worker_profile_rejects_kit_mount_collision():
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)
    db.rollback = AsyncMock()

    request = WorkerProfileCreateRequest(
        name="Invalid Runtime",
        image="team/node22:2026.07",
        runtime_mode="mounted_kit",
        worker_kit_version="0.1.0",
        worker_kit_path="/opt/codify/worker-kits/0.1.0-linux-amd64",
        volume_mounts=[
            {"host_path": "/tmp/override", "container_path": "/nix", "mode": "rw"}
        ],
        environment_variables=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
    )

    with pytest.raises(HTTPException) as exc:
        await create_worker_profile(request, db=db)

    assert exc.value.status_code == 422
    assert "conflicts with worker-kit path" in str(exc.value.detail)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "container_path",
    [
        "/workspace",
        "/opt",
        "/opt/codify-issue-meta/owner",
        "/tmp/codify-runtime/ci-failure",
    ],
)
async def test_create_worker_profile_rejects_system_mount_collision(container_path):
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)
    db.rollback = AsyncMock()

    request = WorkerProfileCreateRequest(
        name="Invalid Mount",
        image="codify-worker:latest",
        volume_mounts=[
            {
                "host_path": "/srv/override",
                "container_path": container_path,
                "mode": "rw",
            }
        ],
        environment_variables=[],
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
    )

    with pytest.raises(HTTPException) as exc:
        await create_worker_profile(request, db=db)

    assert exc.value.status_code == 422
    assert "conflicts with Codify system path" in str(exc.value.detail)


def test_worker_profile_allows_workspace_cache_subdirectory_mount():
    mounts = parse_worker_profile_mounts(
        [
            {
                "host_path": "/srv/cache",
                "container_path": "/workspace/.cache",
                "mode": "rw",
            }
        ]
    )

    assert mounts[0]["container_path"] == "/workspace/.cache"


@pytest.mark.asyncio
async def test_set_default_rejects_disabled_profile():
    profile = _make_profile(id=10, name="Disabled Worker", enabled=False)

    db = MagicMock()
    db.get = AsyncMock(return_value=profile)
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await set_default_worker_profile_endpoint(
            profile_id=10,
            db=db,
        )
    assert exc.value.status_code == 422
    assert "Disabled worker profiles cannot be default" in str(exc.value.detail)
    assert db.get.await_args.kwargs["with_for_update"] is True


@pytest.mark.asyncio
async def test_update_assigned_worker_allows_unchanged_docker_target_fields():
    profile = _make_profile(id=11)
    db = MagicMock()
    db.get = AsyncMock(return_value=profile)
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    response = await update_worker_profile(
        11,
        WorkerProfileUpdateRequest(
            description="Updated description",
            docker_host=profile.docker_host,
            docker_tls_ca=profile.docker_tls_ca,
            docker_tls_cert=profile.docker_tls_cert,
            docker_tls_key=profile.docker_tls_key,
        ),
        db=db,
    )

    assert response["description"] == "Updated description"
    db.execute.assert_not_awaited()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_assigned_worker_rejects_actual_docker_target_change():
    profile = _make_profile(id=11)
    count_result = MagicMock()
    count_result.scalar_one.return_value = 1
    db = MagicMock()
    db.get = AsyncMock(return_value=profile)
    db.execute = AsyncMock(return_value=count_result)
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await update_worker_profile(
            11,
            WorkerProfileUpdateRequest(docker_host="tcp://other-worker:2376"),
            db=db,
        )

    assert exc.value.status_code == 422
    assert "assigned to 1 active issue" in str(exc.value.detail)
    assert profile.docker_host == "tcp://worker:2376"


@pytest.mark.asyncio
async def test_disable_worker_profile_ignores_closed_issue_with_retained_workspace():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        profile = WorkerProfile(
            name="Closed Issue Worker",
            enabled=True,
            is_default=False,
            image="codify-worker:test",
            volume_mounts=[],
            pre_script="",
            post_script="",
            default_execute_run_instruction_template="{{user_prompt}}",
            default_plan_run_instruction_template="{{user_prompt}}",
            ci_auto_repair_run_instruction_template="{{user_prompt}}",
        )
        db.add(profile)
        await db.flush()
        db.add(
            Issue(
                title="Closed issue",
                project_id=100,
                status=IssueStatus.CLOSED.value,
                worker_profile_id=profile.id,
                workspace_last_used_at=datetime(2026, 1, 1),
                workspace_deleted_at=None,
            )
        )
        await db.commit()

        response = await disable_worker_profile(profile.id, db=db)

    await engine.dispose()

    assert response["enabled"] is False


@pytest.mark.asyncio
async def test_disable_worker_profile_still_rejects_active_issue():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        profile = WorkerProfile(
            name="Active Issue Worker",
            enabled=True,
            is_default=False,
            image="codify-worker:test",
            volume_mounts=[],
            pre_script="",
            post_script="",
            default_execute_run_instruction_template="{{user_prompt}}",
            default_plan_run_instruction_template="{{user_prompt}}",
            ci_auto_repair_run_instruction_template="{{user_prompt}}",
        )
        db.add(profile)
        await db.flush()
        db.add(
            Issue(
                title="Open issue",
                project_id=100,
                status=IssueStatus.OPEN.value,
                worker_profile_id=profile.id,
            )
        )
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await disable_worker_profile(profile.id, db=db)

    await engine.dispose()

    assert exc.value.status_code == 422
    assert "assigned to 1 active issue" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_update_disabled_worker_profile_can_enable():
    profile = _make_profile(id=11, name="Disabled Worker", enabled=False)
    db = MagicMock()
    db.get = AsyncMock(return_value=profile)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    response = await update_worker_profile(
        11,
        WorkerProfileUpdateRequest(enabled=True),
        db=db,
    )

    assert response["enabled"] is True
    assert profile.enabled is True
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile", "expected_detail"),
    [
        (
            _make_profile(id=11, name="Default Worker", enabled=True, is_default=True),
            "Default worker profile cannot be deleted",
        ),
        (
            _make_profile(id=12, name="Enabled Worker", enabled=True, is_default=False),
            "Worker profile must be disabled before it can be deleted",
        ),
    ],
)
async def test_delete_worker_profile_rejects_default_or_enabled_profile(
    profile,
    expected_detail,
):
    db = MagicMock()
    db.get = AsyncMock(return_value=profile)
    db.delete = AsyncMock()
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await delete_worker_profile(profile.id, db=db)

    assert exc.value.status_code == 422
    assert exc.value.detail == expected_detail
    db.delete.assert_not_awaited()
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_worker_profile_rejects_closed_issue_assignment():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            profile = WorkerProfile(
                name="Closed Issue Worker",
                enabled=False,
                is_default=False,
                image="codify-worker:test",
                volume_mounts=[],
                pre_script="",
                post_script="",
                default_execute_run_instruction_template="{{user_prompt}}",
                default_plan_run_instruction_template="{{user_prompt}}",
                ci_auto_repair_run_instruction_template="{{user_prompt}}",
            )
            db.add(profile)
            await db.flush()
            db.add(
                Issue(
                    title="Closed issue",
                    project_id=100,
                    status=IssueStatus.CLOSED.value,
                    worker_profile_id=profile.id,
                )
            )
            await db.commit()
            profile_id = profile.id

            with pytest.raises(HTTPException) as exc:
                await delete_worker_profile(profile_id, db=db)

            assert exc.value.status_code == 422
            assert "assigned to 1 issue(s)" in str(exc.value.detail)
            assert await db.get(WorkerProfile, profile_id) is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_worker_profile_removes_disabled_unassigned_profile():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            profile = WorkerProfile(
                name="Unused Worker",
                enabled=False,
                is_default=False,
                image="codify-worker:test",
                volume_mounts=[],
                pre_script="",
                post_script="",
                default_execute_run_instruction_template="{{user_prompt}}",
                default_plan_run_instruction_template="{{user_prompt}}",
                ci_auto_repair_run_instruction_template="{{user_prompt}}",
            )
            db.add(profile)
            await db.commit()
            profile_id = profile.id

            response = await delete_worker_profile(profile_id, db=db)

            assert response == {"status": "deleted", "id": profile_id}
            assert await db.get(WorkerProfile, profile_id) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_assigned_worker_allows_tls_credential_rotation_on_same_daemon():
    profile = _make_profile(id=11)
    db = MagicMock()
    db.get = AsyncMock(return_value=profile)
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    response = await update_worker_profile(
        11,
        WorkerProfileUpdateRequest(
            docker_tls_ca="/certs-v2/ca.pem",
            docker_tls_cert="/certs-v2/cert.pem",
            docker_tls_key="/certs-v2/key.pem",
        ),
        db=db,
    )

    assert response["docker_tls_ca"] == "/certs-v2/ca.pem"
    db.execute.assert_not_awaited()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_mounted_worker_profile_runs_preflight_on_profile_target():
    profile = _make_profile(
        id=12,
        name="Java Runtime",
        environment_variables=[
            SimpleNamespace(
                key="CODIFY_CLAUDE_BIN",
                value="/usr/local/bin/claude",
                is_secret=False,
            ),
            SimpleNamespace(
                key="RUNTIME_SECRET",
                value="encrypted-value",
                is_secret=True,
            ),
        ],
    )
    profile.image = "team/java21-maven:2026.07"
    profile.runtime_mode = "mounted_kit"
    profile.worker_kit_version = "0.3.5"
    profile.worker_kit_path = "/opt/codify/worker-kits/0.3.5-linux-amd64"
    profile.volume_mounts = [
        {
            "host_path": "/opt/codify/overrides/claude",
            "container_path": "/usr/local/bin/claude",
            "mode": "ro",
        }
    ]
    db = MagicMock()
    db.get = AsyncMock(return_value=profile)
    db.commit = AsyncMock()

    container = MagicMock()
    client = MagicMock()
    client.create_container.return_value = container
    client.wait_for_container.return_value = (0, "Worker kit verification passed")
    client.resolve_image_repo_digest.return_value = (
        "team/java21-maven@sha256:abc123def456"
    )

    with patch("app.api.worker_profiles.DockerClientWrapper", return_value=client):
        response = await verify_worker_profile_runtime(
            12,
            WorkerRuntimeVerificationRequest(smoke_command="java -version"),
            db=db,
        )

    assert response["ok"] is True
    assert response["image"] == "team/java21-maven:2026.07"
    assert response["image_digest"] == "team/java21-maven@sha256:abc123def456"
    assert profile.image_digest == "team/java21-maven@sha256:abc123def456"
    assert profile.verified_at is not None
    db.commit.assert_awaited_once()
    client.client.images.get.assert_called_once_with("team/java21-maven:2026.07")
    client.resolve_image_repo_digest.assert_called_once_with("team/java21-maven:2026.07")
    create_kwargs = client.create_container.call_args.kwargs
    assert create_kwargs["command"] == [
        "--verify",
        "--require-skill-support",
        "--smoke",
        "java -version",
    ]
    assert create_kwargs["entrypoint"] == "/opt/codify-kit/launcher"
    assert create_kwargs["user"] == "0:0"
    assert create_kwargs["tmpfs"] == {"/workspace": "rw,exec,mode=1777"}
    assert create_kwargs["environment"]["CODIFY_CLAUDE_BIN"] == "/usr/local/bin/claude"
    assert "RUNTIME_SECRET" not in create_kwargs["environment"]
    assert response["omitted_secret_environment_keys"] == ["RUNTIME_SECRET"]
    assert create_kwargs["volumes"]["/opt/codify/overrides/claude"] == {
        "bind": "/usr/local/bin/claude",
        "mode": "ro",
    }
    assert create_kwargs["volumes"][profile.worker_kit_path] == {
        "bind": "/opt/codify-kit",
        "mode": "ro",
    }
    assert create_kwargs["volumes"][f"{profile.worker_kit_path}/nix/store"] == {
        "bind": "/nix/store",
        "mode": "ro",
    }
    container.remove.assert_called_once_with(force=True, v=True)
    client.close.assert_called_once()


@pytest.mark.asyncio
async def test_verify_baked_worker_profile_is_rejected_without_docker_access():
    profile = _make_profile(id=13)
    db = MagicMock()
    db.get = AsyncMock(return_value=profile)

    with (
        patch("app.api.worker_profiles.DockerClientWrapper") as client_class,
        pytest.raises(HTTPException) as exc,
    ):
        await verify_worker_profile_runtime(
            13,
            WorkerRuntimeVerificationRequest(),
            db=db,
        )

    assert exc.value.status_code == 422
    assert "mounted_kit" in str(exc.value.detail)
    client_class.assert_not_called()


def test_list_worker_profiles_exposes_secret_configured_not_plaintext():
    secret_row = SimpleNamespace(
        id=20,
        key="SECRET_VALUE",
        value="encrypted-secret",
        is_secret=True,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    profile = _make_profile(id=3, environment_variables=[secret_row])

    result = MagicMock()
    result.scalars.return_value.all.return_value = [profile]
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[require_admin_user] = lambda: SimpleNamespace(id=1)
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.get("/api/worker-profiles")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    env_item = response.json()[0]["environment_variables"][0]
    assert env_item["value"] is None
    assert env_item["value_configured"] is True
    assert "encrypted-secret" not in response.text
    assert "docker_host" not in response.json()[0]


def test_admin_worker_profile_list_includes_docker_target():
    result = MagicMock()
    result.scalars.return_value.all.return_value = [_make_profile(id=3)]
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[require_admin_user] = lambda: SimpleNamespace(id=1)
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.get("/api/worker-profiles/admin")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["docker_host"] == "tcp://worker:2376"


@pytest.mark.asyncio
async def test_worker_profile_docker_connection_returns_server_identity():
    docker = MagicMock()
    docker.inspect_server.return_value = {
        "server_version": "27.1.0",
        "architecture": "aarch64",
        "operating_system": "Linux",
    }
    settings = SimpleNamespace(
        docker_host="unix:///var/run/docker.sock",
        docker_tls_ca=None,
        docker_tls_cert=None,
        docker_tls_key=None,
    )
    with (
        patch("app.api.worker_profiles.get_effective_settings", return_value=settings),
        patch("app.api.worker_profiles.DockerClientWrapper", return_value=docker) as wrapper,
    ):
        response = await run_docker_connection_test(
            DockerConnectionTestRequest(docker_host="tcp://arm-worker:2376"),
            _admin=SimpleNamespace(id=1),
        )

    assert response["architecture"] == "aarch64"
    assert response["docker_host"] == "tcp://arm-worker:2376"
    wrapper.assert_called_once()
    assert wrapper.call_args.args[0].host == "tcp://arm-worker:2376"
    assert wrapper.call_args.kwargs == {
        "connect_timeout": 3,
        "operation_timeout": 3,
    }
    docker.close.assert_called_once()


def test_list_worker_profiles_allows_regular_authenticated_user():
    result = MagicMock()
    result.scalars.return_value.all.return_value = [_make_profile(id=3, name="Java Worker")]
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[require_admin_user] = lambda: (_ for _ in ()).throw(
        HTTPException(status_code=403, detail="Admin access required")
    )
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.get("/api/worker-profiles")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["name"] == "Java Worker"


def test_create_worker_profile_still_rejects_regular_authenticated_user():
    db = MagicMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[require_admin_user] = lambda: (_ for _ in ()).throw(
        HTTPException(status_code=403, detail="Admin access required")
    )
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.post(
            "/api/worker-profiles",
            json={
                "name": "Java Worker",
                "image": "codify-worker-java:latest",
                "default_execute_run_instruction_template": "Execute {{user_prompt}}",
                "default_plan_run_instruction_template": "Plan {{user_prompt}}",
                "ci_auto_repair_run_instruction_template": "Repair {{issue_title}}",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"


@pytest.mark.parametrize(
    ("payload_patch", "expected_field"),
    [
        ({"name": "x" * 101}, "name"),
        ({"image": "x" * 256}, "image"),
        (
            {"environment_variables": [{"key": "X" * 256, "value": "value"}]},
            "environment_variables",
        ),
    ],
)
def test_create_worker_profile_rejects_over_length_fields(payload_patch, expected_field):
    db = MagicMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[require_admin_user] = lambda: SimpleNamespace(
        id=1,
        platform_role="platform_admin",
    )
    client = TestClient(app, raise_server_exceptions=False)
    payload = {
        "name": "Java Worker",
        "image": "codify-worker-java:latest",
        "default_execute_run_instruction_template": "Execute {{user_prompt}}",
        "default_plan_run_instruction_template": "Plan {{user_prompt}}",
        "ci_auto_repair_run_instruction_template": "Repair {{issue_title}}",
    }
    payload.update(payload_patch)
    try:
        response = client.post("/api/worker-profiles", json=payload)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert expected_field in response.text


def test_disable_default_worker_profile_returns_422():
    profile = _make_profile(id=4, is_default=True)
    db = MagicMock()
    db.get = AsyncMock(return_value=profile)
    db.rollback = AsyncMock()

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[require_admin_user] = lambda: SimpleNamespace(id=1)
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.post("/api/worker-profiles/4/disable")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"] == "Default worker profile cannot be disabled"
    assert db.get.await_args.kwargs["with_for_update"] is True
