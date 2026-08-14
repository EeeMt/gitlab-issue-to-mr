from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.task_schemas import RetryTaskRequest, UpdateTaskRequest
from app.api.tasks import CreateTaskRequest, create_task, update_task
from app.core.skills import skill_snapshots_from_task_snapshot
from app.core.worker_profiles import WorkerProfileValidationError, load_task_worker_runtime
from app.dependencies.project_access import ProjectAccessScope
from app.models import (
    AIProvider,
    Base,
    Issue,
    Skill,
    SkillVersion,
    Task,
    TaskStatus,
    TaskWorkerProfileSnapshot,
    WorkerProfile,
)


@pytest.mark.asyncio
async def test_create_task_uses_issue_pinned_worker_and_default_provider():
    request = CreateTaskRequest(
        issue_id=1,
        user_prompt="Implement worker profiles",
        priority=1,
    )
    issue = MagicMock()
    issue.id = 1
    issue.project_id = 101
    issue.description = "Implement worker profiles"
    issue.status = "open"
    issue.worker_profile_id = 33
    issue.default_provider_id = 44

    worker_profile = MagicMock()
    worker_profile.id = 33
    worker_profile.name = "Java Worker"
    worker_profile.enabled = True
    worker_profile.image = "codify-worker-java:latest"
    worker_profile.runtime_mode = "baked_image"
    worker_profile.worker_kit_version = None
    worker_profile.worker_kit_path = None
    worker_profile.volume_mounts = []
    worker_profile.environment_variables = []
    worker_profile.pre_script = ""
    worker_profile.post_script = ""
    worker_profile.docker_host = None
    worker_profile.codegraph_enabled = False
    worker_profile.harness_key = "claude"
    worker_profile.harness_config_snapshot = None
    worker_profile.default_execute_run_instruction_template = "Execute {{user_prompt}}"
    worker_profile.default_plan_run_instruction_template = "Plan {{user_prompt}}"
    worker_profile.ci_auto_repair_run_instruction_template = "Repair {{issue_title}}"

    provider = MagicMock()
    provider.id = 44
    provider.is_disabled = False

    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=issue)
    _empty_issue_tasks = MagicMock()
    _empty_issue_tasks.scalars.return_value.all.return_value = []
    _empty_issue_tasks.all.return_value = []
    db.execute = AsyncMock(return_value=_empty_issue_tasks)

    async def refresh(task, attribute_names=None):
        task.id = 88
        task.status = TaskStatus.PENDING
        task.created_at = datetime(2026, 6, 25, 9, 0, 0)
        task.updated_at = datetime(2026, 6, 25, 9, 0, 0)

    db.refresh = AsyncMock(side_effect=refresh)
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
    current_user = SimpleNamespace(
        id=7,
        gitlab_user_id=77,
        username="alice",
        display_name=None,
        email=None,
    )

    with (
        patch(
            "app.api.tasks.resolve_worker_profile_for_issue",
            new=AsyncMock(return_value=worker_profile),
        ),
        patch("app.api.tasks.resolve_provider_for_issue", new=AsyncMock(return_value=provider)),
        patch("app.api.tasks.replace_task_worker_snapshot", new=AsyncMock(return_value=worker_profile)),
        patch("app.api.tasks.bind_runtime_bundle", new=AsyncMock(return_value=MagicMock(id=1))),
        patch("app.api.tasks.select_snapshot_run_instruction_template", return_value="Execute {{user_prompt}}"),
        patch(
            "app.api.task_creation_service.get_issue_latest_harness_key",
            new=AsyncMock(return_value=None),
        ),
        patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
        patch(
            "app.api.tasks.get_usage_quota_service",
            return_value=MagicMock(raise_if_over_limit=AsyncMock()),
        ),
    ):
        await create_task(request=request, db=db, current_user=current_user, access_scope=access_scope)

    task = db.add.call_args.args[0]
    assert task.worker_profile_id == 33
    assert task.provider_id == 44


@pytest.mark.asyncio
async def test_create_task_rejects_known_unavailable_runtime():
    """Create refuses a Kit locator that is known unavailable (§12) with 409."""
    from app.core.worker_runtime_readiness import (
        FAILURE_WORKER_KIT_NOT_FOUND,
        READINESS_UNAVAILABLE,
        RuntimeReadiness,
    )

    request = CreateTaskRequest(
        issue_id=1,
        user_prompt="Implement worker profiles",
        priority=1,
    )
    issue = MagicMock()
    issue.id = 1
    issue.project_id = 101
    issue.description = "Implement worker profiles"
    issue.status = "open"
    issue.worker_profile_id = 33
    issue.default_provider_id = 44

    worker_profile = MagicMock()
    worker_profile.id = 33
    worker_profile.name = "Java Worker"
    worker_profile.enabled = True
    worker_profile.image = "codify-worker-java:latest"
    worker_profile.runtime_mode = "mounted_kit"
    worker_profile.worker_kit_version = "0.3.5"
    worker_profile.worker_kit_path = "/opt/kit"
    worker_profile.volume_mounts = []
    worker_profile.environment_variables = []
    worker_profile.pre_script = ""
    worker_profile.post_script = ""
    worker_profile.docker_host = None
    worker_profile.codegraph_enabled = False
    worker_profile.harness_key = "claude"
    worker_profile.harness_config_snapshot = None
    worker_profile.default_execute_run_instruction_template = "Execute {{user_prompt}}"
    worker_profile.default_plan_run_instruction_template = "Plan {{user_prompt}}"
    worker_profile.ci_auto_repair_run_instruction_template = "Repair {{issue_title}}"

    provider = MagicMock()
    provider.id = 44
    provider.is_disabled = False

    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=issue)
    _empty_issue_tasks = MagicMock()
    _empty_issue_tasks.scalars.return_value.all.return_value = []
    _empty_issue_tasks.all.return_value = []
    db.execute = AsyncMock(return_value=_empty_issue_tasks)
    db.refresh = AsyncMock()
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
    current_user = SimpleNamespace(
        id=7,
        gitlab_user_id=77,
        username="alice",
        display_name=None,
        email=None,
    )

    with (
        patch(
            "app.api.tasks.resolve_worker_profile_for_issue",
            new=AsyncMock(return_value=worker_profile),
        ),
        patch("app.api.tasks.resolve_provider_for_issue", new=AsyncMock(return_value=provider)),
        patch("app.api.tasks.replace_task_worker_snapshot", new=AsyncMock(return_value=worker_profile)),
        patch("app.api.tasks.bind_runtime_bundle", new=AsyncMock(return_value=MagicMock(id=1))),
        patch("app.api.tasks.select_snapshot_run_instruction_template", return_value="Execute {{user_prompt}}"),
        patch(
            "app.api.task_creation_service.get_issue_latest_harness_key",
            new=AsyncMock(return_value=None),
        ),
        patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
        patch(
            "app.api.tasks.get_usage_quota_service",
            return_value=MagicMock(raise_if_over_limit=AsyncMock()),
        ),
        patch(
            "app.api.task_creation_service.readiness_for_profile",
            new=AsyncMock(
                return_value=RuntimeReadiness(
                    status=READINESS_UNAVAILABLE,
                    failure_code=FAILURE_WORKER_KIT_NOT_FOUND,
                )
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await create_task(request=request, db=db, current_user=current_user, access_scope=access_scope)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "worker_runtime_unavailable"
    assert exc_info.value.detail["failure_code"] == FAILURE_WORKER_KIT_NOT_FOUND
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_continue_without_harness_key_rejects_lineage_mismatch():
    request = CreateTaskRequest(
        issue_id=1,
        user_prompt="Continue the work",
        priority=1,
        session_mode="continue",
        # harness_key omitted: must still respect the issue's harness lineage
    )
    issue = MagicMock()
    issue.id = 1
    issue.project_id = 101
    issue.description = "Continue the work"
    issue.status = "open"
    issue.worker_profile_id = 33
    issue.default_provider_id = 44

    worker_profile = MagicMock()
    worker_profile.id = 33
    worker_profile.name = "Default Worker"
    worker_profile.enabled = True
    worker_profile.default_harness_key = "claude"
    worker_profile.enabled_harnesses = ["claude"]

    provider = MagicMock()
    provider.id = 44
    provider.is_disabled = False

    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=issue)
    _empty_issue_tasks = MagicMock()
    _empty_issue_tasks.scalars.return_value.all.return_value = []
    _empty_issue_tasks.all.return_value = []
    db.execute = AsyncMock(return_value=_empty_issue_tasks)
    db.refresh = AsyncMock()
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
    current_user = SimpleNamespace(
        id=7,
        gitlab_user_id=77,
        username="alice",
        display_name=None,
        email=None,
    )

    with (
        patch(
            "app.api.tasks.resolve_worker_profile_for_issue",
            new=AsyncMock(return_value=worker_profile),
        ),
        patch("app.api.tasks.resolve_provider_for_issue", new=AsyncMock(return_value=provider)),
        patch("app.api.tasks.replace_task_worker_snapshot", new=AsyncMock(return_value=worker_profile)),
        patch("app.api.tasks.bind_runtime_bundle", new=AsyncMock(return_value=MagicMock(id=1))),
        patch("app.api.tasks.select_snapshot_run_instruction_template", return_value="Execute {{user_prompt}}"),
        patch(
            "app.api.task_creation_service.get_issue_latest_harness_key",
            new=AsyncMock(return_value="codex"),
        ),
        patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
        patch(
            "app.api.tasks.get_usage_quota_service",
            return_value=MagicMock(raise_if_over_limit=AsyncMock()),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await create_task(
                request=request,
                db=db,
                current_user=current_user,
                access_scope=access_scope,
            )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_create_task_uses_issue_default_harness_when_request_omits_key():
    request = CreateTaskRequest(
        issue_id=1,
        user_prompt="Use issue harness default",
        priority=1,
        session_mode="fresh",
    )
    issue = MagicMock()
    issue.id = 1
    issue.project_id = 101
    issue.description = "Use issue harness default"
    issue.status = "open"
    issue.worker_profile_id = 33
    issue.default_provider_id = 44
    issue.default_harness_key = "codex"

    worker_profile = MagicMock()
    worker_profile.id = 33
    worker_profile.name = "Default Worker"
    worker_profile.enabled = True
    worker_profile.default_harness_key = "claude"
    worker_profile.enabled_harnesses = ["claude", "codex"]

    provider = _provider_mock(44, wire_protocol="openai_responses")

    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=issue)
    _empty_issue_tasks = MagicMock()
    _empty_issue_tasks.scalars.return_value.all.return_value = []
    _empty_issue_tasks.all.return_value = []
    db.execute = AsyncMock(return_value=_empty_issue_tasks)

    async def refresh(task, attribute_names=None):
        task.id = 88
        task.status = TaskStatus.PENDING
        task.created_at = datetime(2026, 6, 25, 9, 0, 0)
        task.updated_at = datetime(2026, 6, 25, 9, 0, 0)

    db.refresh = AsyncMock(side_effect=refresh)
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
    current_user = SimpleNamespace(
        id=7,
        gitlab_user_id=77,
        username="alice",
        display_name=None,
        email=None,
    )

    prepare_snapshot = AsyncMock(return_value=MagicMock(harness_key="codex"))

    with (
        patch(
            "app.api.tasks.resolve_worker_profile_for_issue",
            new=AsyncMock(return_value=worker_profile),
        ),
        patch("app.api.tasks.resolve_provider_for_issue", new=AsyncMock(return_value=provider)),
        patch("app.api.tasks.prepare_task_runtime_snapshot", new=prepare_snapshot),
        patch("app.api.tasks.bind_runtime_bundle", new=AsyncMock(return_value=MagicMock(id=1))),
        patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
        patch(
            "app.api.tasks.get_usage_quota_service",
            return_value=MagicMock(raise_if_over_limit=AsyncMock()),
        ),
    ):
        await create_task(
            request=request,
            db=db,
            current_user=current_user,
            access_scope=access_scope,
        )

    _, kwargs = prepare_snapshot.call_args
    assert kwargs["harness_key"] == "codex"


@pytest.mark.asyncio
async def test_create_task_loads_worker_profile_environment_from_existing_identity():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    try:
        async with session_factory() as db:
            provider = AIProvider(
                name="default",
                base_url="http://ai.example",
                model="test-model",
                is_default=True,
                is_disabled=False,
            )
            worker_profile = WorkerProfile(
                name="Default Worker",
                enabled=True,
                is_default=True,
                image="codify-worker/java21-maven:2026.07",
                runtime_mode="mounted_kit",
                worker_kit_version="0.3.5",
                worker_kit_path="/opt/codify/worker-kits/0.3.5-linux-amd64",
                volume_mounts=[],
                pre_script="",
                post_script="",
                default_execute_run_instruction_template="Execute {{user_prompt}}",
                default_plan_run_instruction_template="Plan {{user_prompt}}",
                ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
                default_skills=[
                    Skill(
                        name="review-changes",
                        description="Review changes before delivery.",
                        current_version=SkillVersion(
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
                        ),
                        enabled=True,
                    )
                ],
            )
            issue = Issue(
                title="Worker defaults",
                project_id=101,
                status="open",
                description="Implement worker profiles",
                worker_profile=worker_profile,
                default_provider=provider,
            )
            db.add_all([provider, worker_profile, issue])
            await db.commit()

            request = CreateTaskRequest(
                issue_id=issue.id,
                user_prompt="Implement worker profiles",
                priority=1,
                provider_id=provider.id,
            )

            with patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})):
                response = await create_task(
                    request=request,
                    db=db,
                    current_user=None,
                    access_scope=ProjectAccessScope(
                        is_unrestricted=True,
                        accessible_projects=[],
                    ),
                )
                override_response = await create_task(
                    request=CreateTaskRequest(
                        issue_id=issue.id,
                        user_prompt="Implement without managed skills",
                        priority=1,
                        provider_id=provider.id,
                        skill_ids=[],
                    ),
                    db=db,
                    current_user=None,
                    access_scope=ProjectAccessScope(
                        is_unrestricted=True,
                        accessible_projects=[],
                    ),
                )
                restored_response = await update_task(
                    override_response["id"],
                    UpdateTaskRequest(skill_ids=None),
                    db=db,
                    current_user=None,
                    access_scope=ProjectAccessScope(
                        is_unrestricted=True,
                        accessible_projects=[],
                    ),
                )
            snapshot = await db.get(TaskWorkerProfileSnapshot, response["id"])
            await db.refresh(snapshot, attribute_names=["skill_references"])
            assert skill_snapshots_from_task_snapshot(snapshot) == [
                {
                    "id": worker_profile.default_skills[0].id,
                    "name": "review-changes",
                    "description": "Review changes before delivery.",
                    "version_id": worker_profile.default_skills[0].current_version_id,
                }
            ]
            runtime = await load_task_worker_runtime(
                db,
                SimpleNamespace(id=response["id"]),
            )
            assert "Inspect the final diff." in runtime.skills[0]["skill_md"]

        assert response["worker_profile_id"] == worker_profile.id
        assert response["worker_profile_name"] == "Default Worker"
        assert response["worker_image"] == "codify-worker/java21-maven:2026.07"
        assert response["worker_runtime_mode"] == "mounted_kit"
        assert response["worker_kit_version"] == "0.3.5"
        assert response["skill_names"] == ["review-changes"]
        assert response["skill_snapshots"] == [
            {
                "id": worker_profile.default_skills[0].id,
                "name": "review-changes",
                "description": "Review changes before delivery.",
                "version_id": worker_profile.default_skills[0].current_version_id,
            }
        ]
        assert response["skill_selection_source"] == "profile"
        assert override_response["skill_ids"] == []
        assert override_response["skill_selection_source"] == "task"
        assert restored_response["skill_names"] == ["review-changes"]
        assert restored_response["skill_selection_source"] == "profile"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_task_rejects_disabled_issue_worker():
    request = CreateTaskRequest(issue_id=1, user_prompt="x", priority=1)
    issue = MagicMock(id=1, project_id=101, description="x", status="open")
    db = MagicMock()
    db.get = AsyncMock(return_value=issue)
    _empty_issue_tasks = MagicMock()
    _empty_issue_tasks.scalars.return_value.all.return_value = []
    _empty_issue_tasks.all.return_value = []
    db.execute = AsyncMock(return_value=_empty_issue_tasks)
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    with patch(
        "app.api.tasks.resolve_worker_profile_for_issue",
        new=AsyncMock(
            side_effect=WorkerProfileValidationError("Worker profile 'Old' is disabled")
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await create_task(
                request=request,
                db=db,
                current_user=SimpleNamespace(id=7),
                access_scope=access_scope,
            )
    assert exc.value.status_code == 422
    assert "disabled" in exc.value.detail


def test_task_request_schemas_do_not_expose_worker_switching():
    assert "worker_profile_id" not in CreateTaskRequest.model_fields
    assert "worker_profile_id" not in RetryTaskRequest.model_fields
    assert "worker_profile_id" not in UpdateTaskRequest.model_fields
    with pytest.raises(ValidationError, match="fixed by the parent issue"):
        CreateTaskRequest.model_validate({
            "issue_id": 1,
            "user_prompt": "x",
            "worker_profile_id": 7,
        })
    with pytest.raises(ValidationError, match="fixed by the parent issue"):
        UpdateTaskRequest.model_validate({"worker_profile_id": 7})
    with pytest.raises(ValidationError, match="fixed by the parent issue"):
        RetryTaskRequest.model_validate({"worker_profile_id": 7})


@pytest.mark.parametrize("skill_ids", [[True], ["1"], [0], [1, 1]])
def test_task_request_schemas_reject_invalid_skill_ids(skill_ids):
    with pytest.raises(ValidationError):
        CreateTaskRequest(issue_id=1, skill_ids=skill_ids)


@pytest.mark.asyncio
async def test_update_task_preserves_worker_metadata_after_refresh_without_snapshot_rebuild():
    task = Task(
        id=88,
        issue_id=1,
        project_id=101,
        user_prompt="Implement worker profiles",
        priority=1,
        status=TaskStatus.PENDING,
        provider_id=44,
        worker_profile_id=33,
        task_mode="execute",
        require_changes=True,
        trigger_source="manual",
        created_at=datetime(2026, 6, 25, 9, 0, 0),
        updated_at=datetime(2026, 6, 25, 9, 0, 0),
    )
    snapshot = TaskWorkerProfileSnapshot(
        task_id=88,
        worker_profile_id=33,
        profile_name="Default Worker",
        image="codify-worker/java21-maven:2026.07",
        volume_mounts=[],
        environment_variables=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
        created_at=datetime(2026, 6, 25, 9, 0, 0),
    )
    task.worker_profile_snapshot = snapshot

    async def refresh(obj, attribute_names=None):
        if attribute_names == ["status"]:
            return
        obj.worker_profile_snapshot = None

    db = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock(side_effect=refresh)
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    with (
        patch("app.api.tasks.get_task_with_access_check", new=AsyncMock(return_value=task)),
        patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
    ):
        response = await update_task(
            88,
            UpdateTaskRequest(priority=2),
            db=db,
            current_user=SimpleNamespace(id=7),
            access_scope=access_scope,
        )

    assert task.priority == 2
    assert response["worker_profile_id"] == 33
    assert response["worker_profile_name"] == "Default Worker"
    assert response["worker_image"] == "codify-worker/java21-maven:2026.07"


def _provider_mock(id_, wire_protocol, base_url="https://api.example", model="test-model"):
    provider = MagicMock()
    provider.id = id_
    provider.name = f"provider-{id_}"
    provider.base_url = base_url
    provider.model = model
    provider.provider_kind = (
        "openai_compatible" if wire_protocol.startswith("openai") else "anthropic_compatible"
    )
    provider.wire_protocol = wire_protocol
    provider.provider_driver = None
    provider.provider_options = {}
    provider.credential_ref = None
    return provider


@pytest.mark.asyncio
async def test_update_task_rejects_provider_incompatible_with_frozen_harness():
    task = Task(
        id=99,
        issue_id=1,
        project_id=101,
        user_prompt="Implement",
        priority=1,
        status=TaskStatus.PENDING,
        provider_id=44,
        worker_profile_id=33,
        task_mode="execute",
        require_changes=True,
        trigger_source="manual",
        created_at=datetime(2026, 6, 25, 9, 0, 0),
        updated_at=datetime(2026, 6, 25, 9, 0, 0),
    )
    snapshot = TaskWorkerProfileSnapshot(
        task_id=99,
        worker_profile_id=33,
        profile_name="Default Worker",
        image="codify-worker/java21-maven:2026.07",
        volume_mounts=[],
        environment_variables=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
        harness_key="codex",
        model_endpoint_snapshot={
            "wire_protocol": "openai_responses",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
        },
        created_at=datetime(2026, 6, 25, 9, 0, 0),
    )
    task.worker_profile_snapshot = snapshot

    new_provider = _provider_mock(55, wire_protocol="anthropic_messages")
    issue = MagicMock()
    issue.id = 1
    issue.project_id = 101

    db = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.get = AsyncMock(side_effect=lambda model, pk, *a, **k: issue if model is Issue else None)
    db.refresh = AsyncMock()
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    with (
        patch("app.api.tasks.get_task_with_access_check", new=AsyncMock(return_value=task)),
        patch(
            "app.api.tasks.resolve_provider_for_issue",
            new=AsyncMock(return_value=new_provider),
        ),
        patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
        patch(
            "app.api.tasks.select_snapshot_run_instruction_template",
            return_value="Execute {{user_prompt}}",
        ),
        patch("app.api.tasks.render_and_store_task_prompt", new=MagicMock()),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await update_task(
                99,
                UpdateTaskRequest(provider_id=55),
                db=db,
                current_user=SimpleNamespace(id=7),
                access_scope=access_scope,
            )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_update_task_provider_change_refreshes_snapshot_endpoint():
    task = Task(
        id=100,
        issue_id=1,
        project_id=101,
        user_prompt="Implement",
        priority=1,
        status=TaskStatus.PENDING,
        provider_id=44,
        worker_profile_id=33,
        task_mode="execute",
        require_changes=True,
        trigger_source="manual",
        created_at=datetime(2026, 6, 25, 9, 0, 0),
        updated_at=datetime(2026, 6, 25, 9, 0, 0),
    )
    snapshot = TaskWorkerProfileSnapshot(
        task_id=100,
        worker_profile_id=33,
        profile_name="Default Worker",
        image="codify-worker/java21-maven:2026.07",
        volume_mounts=[],
        environment_variables=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
        harness_key="codex",
        model_endpoint_snapshot={
            "wire_protocol": "openai_responses",
            "base_url": "https://api-old.example",
            "model": "old-model",
        },
        credential_ref=None,
        created_at=datetime(2026, 6, 25, 9, 0, 0),
    )
    task.worker_profile_snapshot = snapshot

    new_provider = _provider_mock(
        55, wire_protocol="openai_responses", base_url="https://api-new.example"
    )
    new_provider.model = "new-model"
    new_provider.credential_ref = "mc-rotated-1"
    issue = MagicMock()
    issue.id = 1
    issue.project_id = 101

    db = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.get = AsyncMock(side_effect=lambda model, pk, *a, **k: issue if model is Issue else None)
    db.refresh = AsyncMock()
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    with (
        patch("app.api.tasks.get_task_with_access_check", new=AsyncMock(return_value=task)),
        patch(
            "app.api.tasks.resolve_provider_for_issue",
            new=AsyncMock(return_value=new_provider),
        ),
        patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
        patch(
            "app.api.tasks.select_snapshot_run_instruction_template",
            return_value="Execute {{user_prompt}}",
        ),
        patch("app.api.tasks.render_and_store_task_prompt", new=MagicMock()),
    ):
        await update_task(
            100,
            UpdateTaskRequest(provider_id=55),
            db=db,
            current_user=SimpleNamespace(id=7),
            access_scope=access_scope,
        )

    assert task.provider_id == 55
    assert snapshot.model_endpoint_snapshot["wire_protocol"] == "openai_responses"
    assert snapshot.model_endpoint_snapshot["base_url"] == "https://api-new.example"
    assert snapshot.model_endpoint_snapshot["model"] == "new-model"
    assert snapshot.credential_ref == "mc-rotated-1"


@pytest.mark.asyncio
async def test_create_task_continue_cannot_switch_harness():
    """A continue task must reuse the issue's current harness lineage."""
    request = CreateTaskRequest(
        issue_id=1,
        user_prompt="Implement",
        priority=1,
        session_mode="continue",
        harness_key="claude",
    )
    issue = MagicMock()
    issue.id = 1
    issue.project_id = 101
    issue.description = "Implement"
    issue.status = "open"
    issue.worker_profile_id = 33
    issue.default_provider_id = 44

    worker_profile = MagicMock()
    worker_profile.id = 33
    worker_profile.name = "Java Worker"
    worker_profile.enabled = True
    worker_profile.default_execute_run_instruction_template = "Execute {{user_prompt}}"
    worker_profile.default_plan_run_instruction_template = "Plan {{user_prompt}}"
    worker_profile.ci_auto_repair_run_instruction_template = "Repair {{issue_title}}"
    worker_profile.default_harness_key = "claude"
    worker_profile.enabled_harnesses = ["claude", "codex"]

    provider = MagicMock()
    provider.id = 44
    provider.is_disabled = False

    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=issue)
    _empty_issue_tasks = MagicMock()
    _empty_issue_tasks.scalars.return_value.all.return_value = []
    _empty_issue_tasks.all.return_value = []
    db.execute = AsyncMock(return_value=_empty_issue_tasks)
    db.refresh = AsyncMock()

    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
    current_user = SimpleNamespace(
        id=7,
        gitlab_user_id=77,
        username="alice",
        display_name=None,
        email=None,
    )

    with (
        patch(
            "app.api.tasks.resolve_worker_profile_for_issue",
            new=AsyncMock(return_value=worker_profile),
        ),
        patch("app.api.tasks.resolve_provider_for_issue", new=AsyncMock(return_value=provider)),
        patch("app.api.tasks.replace_task_worker_snapshot", new=AsyncMock(return_value=worker_profile)),
        patch("app.api.tasks.bind_runtime_bundle", new=AsyncMock(return_value=MagicMock(id=1))),
        patch("app.api.tasks.select_snapshot_run_instruction_template", return_value="Execute {{user_prompt}}"),
        patch(
            "app.api.task_creation_service.get_issue_latest_harness_key",
            new=AsyncMock(return_value="codex"),
        ),
        patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
        patch(
            "app.api.tasks.get_usage_quota_service",
            return_value=MagicMock(raise_if_over_limit=AsyncMock()),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await create_task(
                request=request,
                db=db,
                current_user=current_user,
                access_scope=access_scope,
            )
    assert exc.value.status_code == 422
    assert "续跑" in str(exc.value.detail)
