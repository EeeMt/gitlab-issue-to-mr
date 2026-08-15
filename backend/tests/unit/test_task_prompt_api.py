"""Focused API contract tests for task run-instruction templates."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.task_schemas import CreateTaskRequest, RunInstructionTemplatePreviewRequest
from app.api.tasks import (
    create_task,
    get_run_instruction_template_defaults,
    preview_run_instruction_template,
)
from app.core.task_prompt import (
    BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE,
    BUILT_IN_PLAN_RUN_INSTRUCTION_TEMPLATE,
)
from app.dependencies.project_access import ProjectAccessScope
from app.models import AIProvider, Issue, TaskStatus, TaskWorkerProfileSnapshot


def _scope() -> ProjectAccessScope:
    return ProjectAccessScope(is_unrestricted=True, accessible_projects=[])


@pytest.mark.asyncio
async def test_operator_defaults_return_only_execute_and_plan() -> None:
    settings = SimpleNamespace(
        default_execute_run_instruction_template="execute {{user_prompt}}",
        default_plan_run_instruction_template="plan {{user_prompt}}",
        unrelated_secret="hidden",
    )
    with patch("app.api.tasks.get_effective_settings", return_value=settings):
        response = await get_run_instruction_template_defaults(_scope())
    assert set(response) == {"execute", "plan"}
    assert response["execute"]["content"] == "execute {{user_prompt}}"
    assert "unrelated_secret" not in str(response)


@pytest.mark.asyncio
async def test_preview_uses_issue_and_project_context_without_mutation() -> None:
    issue = Issue(
        id=5,
        title="Login",
        project_id=9,
        status="open",
        branch_name="feature/login",
        target_branch="main",
    )
    db = MagicMock()
    db.get = AsyncMock(return_value=issue)
    request = RunInstructionTemplatePreviewRequest(
        issue_id=5,
        task_mode="execute",
        user_prompt="Implement auth",
        run_instruction_template="{{issue_title}} {{project_path}} {{user_prompt}}",
    )
    with (
        patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={
            "project_path_with_namespace": "group/repo"
        })),
        patch(
            "app.core.task_helpers.get_effective_settings",
            return_value=SimpleNamespace(oidc_enabled=False, gitlab_url="https://gitlab.example.com"),
        ),
    ):
        response = await preview_run_instruction_template(request, db, None, _scope())
    assert response["rendered_prompt"] == "Login group/repo Implement auth"
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_preview_rejects_unknown_placeholder() -> None:
    issue = Issue(id=5, title="Login", project_id=9, status="open")
    db = MagicMock()
    db.get = AsyncMock(return_value=issue)
    request = RunInstructionTemplatePreviewRequest(
        issue_id=5,
        user_prompt="Implement auth",
        run_instruction_template="{{unknown}}",
    )
    with (
        patch("app.core.task_helpers.get_effective_settings", return_value=SimpleNamespace(oidc_enabled=False)),
        patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await preview_run_instruction_template(request, db, None, _scope())
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_create_persists_snapshot_and_rendered_prompt_before_commit() -> None:
    issue = Issue(id=5, title="Login", project_id=9, status="open", description="Issue body")
    provider = AIProvider(
        id=3,
        name="provider",
        base_url="http://provider",
        model="model",
        max_turns=10,
        is_default=True,
        is_disabled=False,
    )
    db = MagicMock()
    worker_profile = SimpleNamespace(id=12)
    snapshot = TaskWorkerProfileSnapshot(
        task_id=10,
        worker_profile_id=12,
        profile_name="Default Worker",
        image="codify-worker/java21-maven:2026.07",
        volume_mounts=[],
        environment_variables=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
        created_at=datetime(2026, 6, 19, 10, 0, 0),
    )

    async def flush() -> None:
        task = db.add.call_args.args[0]
        task.id = 10
        task.status = TaskStatus.PENDING
        task.trigger_source = "manual"
        task.created_at = datetime(2026, 6, 19, 10, 0, 0)
        task.updated_at = task.created_at

    db.get = AsyncMock(return_value=issue)
    db.add = MagicMock()
    db.flush = AsyncMock(side_effect=flush)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    _no_lineage = MagicMock()
    _no_lineage.scalar_one_or_none.return_value = None
    _no_lineage.scalars.return_value.all.return_value = []
    _no_lineage.all.return_value = []
    db.execute = AsyncMock(return_value=_no_lineage)
    request = CreateTaskRequest(
        issue_id=5,
        user_prompt="Implement auth",
        provider_id=3,
        run_instruction_template="Do {{user_prompt}} in {{project_path}}",
    )
    with (
        patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={
            "project_path_with_namespace": "group/repo"
        })),
        patch(
            "app.api.tasks.resolve_worker_profile_for_issue",
            new=AsyncMock(return_value=worker_profile),
        ),
        patch("app.api.tasks.resolve_provider_for_issue", new=AsyncMock(return_value=provider)),
        patch("app.api.tasks.replace_task_worker_snapshot", new=AsyncMock(return_value=snapshot)),
        patch(
            "app.api.task_creation_service.readiness_for_profile",
            new=AsyncMock(return_value=SimpleNamespace(is_unavailable=False)),
        ),
        patch("app.api.tasks.bind_runtime_bundle", new=AsyncMock(return_value=MagicMock(id=1))),
        patch(
            "app.core.task_helpers.get_effective_settings",
            return_value=SimpleNamespace(
                oidc_enabled=False,
                gitlab_url="https://gitlab.example.com",
            ),
        ),
    ):
        response = await create_task(request, db, None, _scope())
    task = db.add.call_args.args[0]
    assert task.run_instruction_template == "Do {{user_prompt}} in {{project_path}}"
    assert task.rendered_prompt == "Do Implement auth in group/repo"
    assert task.rendered_prompt_at is not None
    assert response["rendered_prompt"] == task.rendered_prompt
    db.flush.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_rejects_explicitly_blank_run_instruction_template() -> None:
    issue = Issue(id=5, title="Login", project_id=9, status="open")
    provider = AIProvider(
        id=3,
        name="provider",
        base_url="http://provider",
        model="model",
        max_turns=10,
        is_default=True,
        is_disabled=False,
    )
    db = MagicMock()
    worker_profile = SimpleNamespace(id=12)
    snapshot = TaskWorkerProfileSnapshot(
        task_id=10,
        worker_profile_id=12,
        profile_name="Default Worker",
        image="codify-worker/java21-maven:2026.07",
        volume_mounts=[],
        environment_variables=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
        created_at=datetime(2026, 6, 19, 10, 0, 0),
    )

    db.get = AsyncMock(return_value=issue)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    _no_lineage = MagicMock()
    _no_lineage.scalar_one_or_none.return_value = None
    _no_lineage.scalars.return_value.all.return_value = []
    _no_lineage.all.return_value = []
    db.execute = AsyncMock(return_value=_no_lineage)
    request = CreateTaskRequest(
        issue_id=5,
        user_prompt="Implement auth",
        provider_id=3,
        run_instruction_template="",
    )

    with (
        patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
        patch(
            "app.api.tasks.resolve_worker_profile_for_issue",
            new=AsyncMock(return_value=worker_profile),
        ),
        patch("app.api.tasks.resolve_provider_for_issue", new=AsyncMock(return_value=provider)),
        patch("app.api.tasks.replace_task_worker_snapshot", new=AsyncMock(return_value=snapshot)),
        patch(
            "app.api.task_creation_service.readiness_for_profile",
            new=AsyncMock(return_value=SimpleNamespace(is_unavailable=False)),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await create_task(request, db, None, _scope())

    assert exc_info.value.status_code == 422
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


def test_built_in_constants_remain_nonempty() -> None:
    assert BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE.strip()
    assert BUILT_IN_PLAN_RUN_INSTRUCTION_TEMPLATE.strip()
