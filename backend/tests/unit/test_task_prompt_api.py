"""Focused API contract tests for task run-instruction templates."""

from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import app.api.tasks as tasks_module
from app.api.task_schemas import CreateTaskRequest, RunInstructionTemplatePreviewRequest
from app.api.tasks import (
    create_task,
    get_run_instruction_template_defaults,
    preview_run_instruction_template,
)
from app.core.task_prompt import (
    BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE,
    BUILT_IN_PLAN_RUN_INSTRUCTION_TEMPLATE,
    FREEFORM_RUN_INSTRUCTION_TEMPLATE,
    PLACEHOLDER_NAMES,
)
from app.dependencies.project_access import ProjectAccessScope
from app.models import AIProvider, Issue, TaskStatus, TaskWorkerProfileSnapshot


def _scope() -> ProjectAccessScope:
    return ProjectAccessScope(is_unrestricted=True, accessible_projects=[])


def _make_create_task_fixtures() -> tuple[Any, ...]:
    """Build shared mocks for create_task API tests."""
    issue = Issue(
        id=5,
        title="Login",
        project_id=9,
        status="open",
        description="Issue body",
    )
    provider = AIProvider(
        id=3,
        name="provider",
        base_url="http://provider",
        model="model",
        max_turns=10,
        is_default=True,
        is_disabled=False,
    )
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
    db = MagicMock()
    captured: dict[str, Any] = {}

    async def flush() -> None:
        task = db.add.call_args.args[0]
        captured["task"] = task
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
    db.rollback = AsyncMock()
    _no_lineage = MagicMock()
    _no_lineage.scalar_one_or_none.return_value = None
    _no_lineage.scalars.return_value.all.return_value = []
    _no_lineage.all.return_value = []
    db.execute = AsyncMock(return_value=_no_lineage)
    return issue, db, provider, worker_profile, snapshot, captured


@contextmanager
def _create_task_patches(provider, worker_profile, snapshot):
    with (
        patch(
            "app.api.tasks.get_project_metadata",
            new=AsyncMock(return_value={"project_path_with_namespace": "group/repo"}),
        ),
        patch(
            "app.api.tasks.resolve_worker_profile_for_issue",
            new=AsyncMock(return_value=worker_profile),
        ),
        patch(
            "app.api.tasks.resolve_provider_for_issue",
            new=AsyncMock(return_value=provider),
        ),
        patch(
            "app.api.tasks.replace_task_worker_snapshot",
            new=AsyncMock(return_value=snapshot),
        ),
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
        yield


@pytest.mark.asyncio
async def test_operator_defaults_include_readonly_freeform() -> None:
    settings = SimpleNamespace(
        default_execute_run_instruction_template="execute {{user_prompt}}",
        default_plan_run_instruction_template="plan {{user_prompt}}",
        unrelated_secret="hidden",
    )
    with patch("app.api.tasks.get_effective_settings", return_value=settings):
        response = await get_run_instruction_template_defaults(_scope())
    assert set(response) == {"execute", "plan", "freeform"}
    assert response["execute"]["content"] == "execute {{user_prompt}}"
    assert response["plan"]["content"] == "plan {{user_prompt}}"
    assert response["freeform"] == {
        "content": FREEFORM_RUN_INSTRUCTION_TEMPLATE,
        "available_placeholders": ["user_prompt"],
        "known_placeholders": list(PLACEHOLDER_NAMES),
    }
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


# ---------------------------------------------------------------------------
# Create freeform invariants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_freeform_omits_template_and_saves_canonical() -> None:
    issue, db, provider, worker_profile, snapshot, captured = _make_create_task_fixtures()
    request = CreateTaskRequest(
        issue_id=issue.id,
        user_prompt="Implement auth",
        provider_id=3,
        task_mode="freeform",
    )
    with _create_task_patches(provider, worker_profile, snapshot):
        response = await create_task(request, db, None, _scope())
    task = captured["task"]
    assert task.task_mode == "freeform"
    assert task.require_changes is False
    assert task.run_instruction_template == FREEFORM_RUN_INSTRUCTION_TEMPLATE
    assert task.rendered_prompt == "Implement auth"
    assert task.rendered_prompt_at is not None
    assert response["task_mode"] == "freeform"
    assert response["require_changes"] is False
    assert response["run_instruction_template"] == FREEFORM_RUN_INSTRUCTION_TEMPLATE
    assert response["rendered_prompt"] == "Implement auth"
    db.commit.assert_awaited_once()


@pytest.mark.parametrize(
    "require_changes",
    [None, False, True],
)
@pytest.mark.asyncio
async def test_create_freeform_always_persists_require_changes_false(require_changes) -> None:
    issue, db, provider, worker_profile, snapshot, captured = _make_create_task_fixtures()
    kwargs = {"task_mode": "freeform"}
    if require_changes is not None:
        kwargs["require_changes"] = require_changes
    request = CreateTaskRequest(
        issue_id=issue.id,
        user_prompt="Implement auth",
        provider_id=3,
        **kwargs,
    )
    with _create_task_patches(provider, worker_profile, snapshot):
        await create_task(request, db, None, _scope())
    assert captured["task"].require_changes is False
    assert captured["task"].task_mode == "freeform"


@pytest.mark.asyncio
async def test_create_freeform_accepts_explicit_canonical_template() -> None:
    issue, db, provider, worker_profile, snapshot, captured = _make_create_task_fixtures()
    request = CreateTaskRequest(
        issue_id=issue.id,
        user_prompt="Implement auth",
        provider_id=3,
        task_mode="freeform",
        run_instruction_template="{{user_prompt}}",
    )
    with _create_task_patches(provider, worker_profile, snapshot):
        await create_task(request, db, None, _scope())
    task = captured["task"]
    assert task.run_instruction_template == FREEFORM_RUN_INSTRUCTION_TEMPLATE
    assert task.rendered_prompt == "Implement auth"


@pytest.mark.asyncio
async def test_create_freeform_rejects_non_canonical_template_without_partial_commit() -> None:
    issue, db, provider, worker_profile, snapshot, _ = _make_create_task_fixtures()
    request = CreateTaskRequest(
        issue_id=issue.id,
        user_prompt="Implement auth",
        provider_id=3,
        task_mode="freeform",
        run_instruction_template="Must change: {{user_prompt}}",
    )
    with _create_task_patches(provider, worker_profile, snapshot):
        with pytest.raises(HTTPException) as exc_info:
            await create_task(request, db, None, _scope())
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == (
        "freeform mode only accepts the canonical user-prompt template"
    )
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_omitting_task_mode_still_creates_execute() -> None:
    issue, db, provider, worker_profile, snapshot, captured = _make_create_task_fixtures()
    request = CreateTaskRequest(
        issue_id=issue.id,
        user_prompt="Implement auth",
        provider_id=3,
        run_instruction_template="Do {{user_prompt}} in {{project_path}}",
    )
    with _create_task_patches(provider, worker_profile, snapshot):
        await create_task(request, db, None, _scope())
    task = captured["task"]
    assert task.task_mode == "execute"
    assert task.run_instruction_template == "Do {{user_prompt}} in {{project_path}}"
    assert task.rendered_prompt == "Do Implement auth in group/repo"


# ---------------------------------------------------------------------------
# Freeform prompt preview invariants
# ---------------------------------------------------------------------------


def _make_preview_db(issue: Issue) -> MagicMock:
    db = MagicMock()
    db.get = AsyncMock(return_value=issue)
    return db


@contextmanager
def _preview_patches(project_metadata: dict[str, Any] | None = None):
    with (
        patch(
            "app.api.tasks.get_project_metadata",
            new=AsyncMock(return_value=project_metadata or {}),
        ),
        patch(
            "app.core.task_helpers.get_effective_settings",
            return_value=SimpleNamespace(oidc_enabled=False),
        ),
    ):
        yield


@pytest.mark.asyncio
async def test_preview_freeform_omits_template_and_uses_canonical() -> None:
    issue = Issue(id=5, title="Login", project_id=9, status="open")
    db = _make_preview_db(issue)
    request = RunInstructionTemplatePreviewRequest(
        issue_id=5,
        task_mode="freeform",
        user_prompt="Explain the failure",
    )
    with _preview_patches():
        response = await preview_run_instruction_template(request, db, None, _scope())
    assert response["rendered_prompt"] == "Explain the failure"
    assert response["used_placeholders"] == ["user_prompt"]
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_preview_freeform_accepts_explicit_canonical_template() -> None:
    issue = Issue(id=5, title="Login", project_id=9, status="open")
    db = _make_preview_db(issue)
    request = RunInstructionTemplatePreviewRequest(
        issue_id=5,
        task_mode="freeform",
        user_prompt="Explain the failure",
        run_instruction_template="{{user_prompt}}",
    )
    with _preview_patches():
        response = await preview_run_instruction_template(request, db, None, _scope())
    assert response["rendered_prompt"] == "Explain the failure"


@pytest.mark.asyncio
async def test_preview_freeform_rejects_non_canonical_template() -> None:
    issue = Issue(id=5, title="Login", project_id=9, status="open")
    db = _make_preview_db(issue)
    request = RunInstructionTemplatePreviewRequest(
        issue_id=5,
        task_mode="freeform",
        user_prompt="Explain the failure",
        run_instruction_template="Must change: {{user_prompt}}",
    )
    with _preview_patches():
        with pytest.raises(HTTPException) as exc_info:
            await preview_run_instruction_template(request, db, None, _scope())
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == (
        "freeform mode only accepts the canonical user-prompt template"
    )
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_preview_freeform_normalizes_require_changes_in_context() -> None:
    issue = Issue(id=5, title="Login", project_id=9, status="open")
    db = _make_preview_db(issue)
    request = RunInstructionTemplatePreviewRequest(
        issue_id=5,
        task_mode="freeform",
        user_prompt="Explain",
        require_changes=True,
    )
    captured: dict[str, Any] = {}
    real_render = tasks_module.render_run_instruction_template

    def spy(template, context, **kwargs):
        captured["template"] = template
        captured["context"] = dict(context)
        return real_render(template, context, **kwargs)

    with (
        _preview_patches(),
        patch("app.api.tasks.render_run_instruction_template", side_effect=spy),
    ):
        response = await preview_run_instruction_template(request, db, None, _scope())
    assert captured["template"] == FREEFORM_RUN_INSTRUCTION_TEMPLATE
    assert captured["context"]["require_changes"] == "false"
    assert captured["context"]["task_mode"] == "freeform"
    assert response["rendered_prompt"] == "Explain"


@pytest.mark.asyncio
async def test_preview_execute_omitting_template_is_rejected() -> None:
    issue = Issue(id=5, title="Login", project_id=9, status="open")
    db = _make_preview_db(issue)
    request = RunInstructionTemplatePreviewRequest(
        issue_id=5,
        task_mode="execute",
        user_prompt="Explain",
    )
    with _preview_patches():
        with pytest.raises(HTTPException) as exc_info:
            await preview_run_instruction_template(request, db, None, _scope())
    assert exc_info.value.status_code == 422
    db.add.assert_not_called()
    db.commit.assert_not_called()
