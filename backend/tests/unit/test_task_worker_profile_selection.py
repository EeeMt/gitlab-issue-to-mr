from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.task_schemas import UpdateTaskRequest
from app.api.tasks import CreateTaskRequest, create_task, update_task
from app.core.worker_profiles import WorkerProfileValidationError
from app.dependencies.project_access import ProjectAccessScope
from app.models import Issue, Task, TaskStatus, TaskWorkerProfileSnapshot


@pytest.mark.asyncio
async def test_create_task_uses_issue_default_worker_and_provider_when_omitted():
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
    issue.default_worker_profile_id = 33
    issue.default_provider_id = 44

    worker_profile = MagicMock()
    worker_profile.id = 33
    worker_profile.name = "Java Worker"
    worker_profile.enabled = True
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

    async def refresh(task):
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
        patch("app.api.tasks.select_snapshot_run_instruction_template", return_value="Execute {{user_prompt}}"),
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
async def test_create_task_rejects_disabled_issue_default_worker():
    request = CreateTaskRequest(issue_id=1, user_prompt="x", priority=1)
    issue = MagicMock(id=1, project_id=101, description="x", status="open")
    db = MagicMock()
    db.get = AsyncMock(return_value=issue)
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


@pytest.mark.asyncio
async def test_update_task_worker_profile_rebuilds_snapshot_prompt_from_snapshot_template():
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
    issue = Issue(
        id=1,
        title="Worker defaults",
        project_id=101,
        status="open",
        description="Implement worker profiles",
        created_at=datetime(2026, 6, 25, 9, 0, 0),
        updated_at=datetime(2026, 6, 25, 9, 0, 0),
    )
    worker_profile = SimpleNamespace(id=77)
    snapshot = TaskWorkerProfileSnapshot(
        task_id=88,
        worker_profile_id=77,
        profile_name="Java Worker",
        image="codify-worker:java",
        volume_mounts=[],
        environment_variables=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="Snapshot {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
        created_at=datetime(2026, 6, 25, 9, 0, 0),
    )

    db = MagicMock()
    db.get = AsyncMock(return_value=issue)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    with (
        patch("app.api.tasks.get_task_with_access_check", new=AsyncMock(return_value=task)),
        patch(
            "app.api.tasks.resolve_worker_profile_for_issue",
            new=AsyncMock(return_value=worker_profile),
        ),
        patch("app.api.tasks.replace_task_worker_snapshot", new=AsyncMock(return_value=snapshot)),
        patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
    ):
        response = await update_task(
            88,
            UpdateTaskRequest(worker_profile_id=77),
            db=db,
            current_user=SimpleNamespace(id=7),
            access_scope=access_scope,
        )

    assert task.worker_profile_id == 77
    assert task.run_instruction_template == "Snapshot {{user_prompt}}"
    assert task.rendered_prompt == "Snapshot Implement worker profiles"
    assert response["worker_profile_id"] == 77
    assert response["worker_profile_name"] == "Java Worker"
