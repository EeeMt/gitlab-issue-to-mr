"""Stable HTTP and response contracts for the task API boundary."""

import inspect
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from fastapi.routing import APIRoute

import app.api.tasks as tasks_module
from app.api.task_schemas import CreateTaskRequest
from app.api.tasks import (
    _serialize_task,
    download_task_archive,
    get_task_archive,
    get_task_payload,
    router,
)
from app.dependencies.project_access import ProjectAccessScope
from app.models import Task, TaskStatus

EXPECTED_TASK_ROUTES = {
    ("GET", "/tasks"),
    ("POST", "/tasks"),
    ("GET", "/tasks/scheduled"),
    ("GET", "/tasks/slot-capacity"),
    ("GET", "/tasks/run-instruction-template-defaults"),
    ("POST", "/tasks/render-run-instruction-template-preview"),
    ("GET", "/tasks/{task_id}"),
    ("PATCH", "/tasks/{task_id}"),
    ("GET", "/tasks/{task_id}/logs"),
    ("GET", "/tasks/{task_id}/log-stream"),
    ("GET", "/tasks/{task_id}/stats"),
    ("PATCH", "/tasks/{task_id}/stats"),
    ("POST", "/tasks/{task_id}/cancel"),
    ("POST", "/tasks/{task_id}/override-status"),
    ("POST", "/tasks/{task_id}/retry"),
    ("POST", "/tasks/{task_id}/execute"),
    ("PATCH", "/tasks/{task_id}/schedule"),
    ("GET", "/tasks/{task_id}/workspace"),
    ("DELETE", "/tasks/{task_id}/workspace"),
    ("GET", "/tasks/{task_id}/archive"),
    ("GET", "/tasks/{task_id}/archive/download"),
    ("GET", "/tasks/{task_id}/payloads/{payload_id}"),
}


def test_task_router_preserves_public_method_and_path_surface() -> None:
    actual = {
        (method, route.path)
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    assert actual == EXPECTED_TASK_ROUTES


@pytest.mark.parametrize(
    ("handler", "service_call"),
    [
        (tasks_module.update_task, "update_task_record("),
        (tasks_module.retry_task, "retry_task_record("),
        (tasks_module.create_task, "create_task_record("),
    ],
)
def test_task_mutation_routes_delegate_business_implementation(handler, service_call) -> None:
    source = inspect.getsource(handler)

    assert service_call in source
    assert "db.execute(" not in source
    assert "db.commit(" not in source


def test_task_mutation_service_factories_capture_patchable_module_dependencies() -> None:
    metadata_lookup = AsyncMock(return_value={})
    issue_operator_check = MagicMock()

    with (
        patch.object(tasks_module, "get_project_metadata", new=metadata_lookup),
        patch(
            "app.core.task_helpers._require_issue_operator",
            new=issue_operator_check,
        ),
    ):
        creation_services = tasks_module._task_creation_services()
        assert creation_services.get_project_metadata is metadata_lookup
        assert creation_services.require_issue_operator is issue_operator_check
        assert tasks_module._task_update_services().get_project_metadata is metadata_lookup


@pytest.mark.asyncio
async def test_task_artifact_routes_enforce_task_access_before_loading_content() -> None:
    db = MagicMock()
    access_scope = ProjectAccessScope(
        is_unrestricted=False,
        accessible_projects=[],
    )
    access_check = AsyncMock(return_value=SimpleNamespace(project_id=7))

    with (
        patch("app.api.tasks.get_task_with_access_check", new=access_check),
        patch(
            "app.api.tasks.get_task_archive_metadata",
            new=AsyncMock(return_value={"archive_name": "run.tar.gz"}),
        ),
        patch(
            "app.api.tasks.get_task_archive_file",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    archive_path="/tmp/run.tar.gz",
                    archive_name="run.tar.gz",
                )
            ),
        ),
        patch(
            "app.api.tasks.get_task_payload_content",
            new=AsyncMock(return_value={"content": "summary"}),
        ),
    ):
        await get_task_archive(12, db, access_scope)
        await download_task_archive(12, db, access_scope)
        await get_task_payload(12, 91, db, access_scope)

    access_check.assert_has_awaits(
        [
            call(12, db, access_scope, require_operator=False),
            call(12, db, access_scope, require_operator=False),
            call(12, db, access_scope, require_operator=False),
        ]
    )


def test_create_request_preserves_execute_and_plan_invariants() -> None:
    execute = CreateTaskRequest(issue_id=1)
    plan = CreateTaskRequest(issue_id=1, task_mode="plan", require_changes=True)

    assert execute.task_mode == "execute"
    assert execute.effective_require_changes is False
    assert plan.effective_require_changes is False


def test_task_response_preserves_required_frontend_fields() -> None:
    now = datetime(2026, 7, 4, 10, 0, 0)
    task = Task(
        id=12,
        issue_id=7,
        project_id=3,
        user_prompt="Implement the contract",
        status=TaskStatus.PENDING,
        priority=1,
        is_retry=False,
        retry_source_task_id=None,
        trigger_source="manual",
        ci_failure_run_id=None,
        scheduled_at=None,
        container_id=None,
        commit_sha=None,
        error_message=None,
        additions=0,
        deletions=0,
        total_changes=0,
        input_tokens=None,
        output_tokens=None,
        model_name=None,
        commit_message=None,
        require_changes=False,
        task_mode="execute",
        provider_id=None,
        worker_profile_id=None,
        created_at=now,
        updated_at=now,
        started_at=None,
        completed_at=None,
        is_manually_overridden=False,
        override_reason=None,
    )

    response = _serialize_task(
        task,
        {
            "project_name": "Codify",
            "project_path_with_namespace": "team/codify",
        },
        SimpleNamespace(gitlab_url="https://gitlab.example.com"),
        include_prompt_details=True,
    )

    required_fields = {
        "id",
        "issue_id",
        "project_id",
        "project_name",
        "project_path_with_namespace",
        "project_url",
        "user_prompt",
        "status",
        "priority",
        "require_changes",
        "task_mode",
        "provider_id",
        "worker_profile_id",
        "worker_profile_name",
        "worker_image",
        "worker_snapshot_created_at",
        "created_at",
        "updated_at",
        "run_instruction_template",
        "rendered_prompt",
        "rendered_prompt_at",
    }
    assert required_fields <= response.keys()
    assert response["status"] == "pending"
    assert response["require_changes"] is False
    assert response["project_url"] == "https://gitlab.example.com/team/codify"
