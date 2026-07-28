"""Stable HTTP and response contracts for the task API boundary."""

import inspect
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from fastapi.routing import APIRoute

import app.api.tasks as tasks_module
from app.api.task_runtime_summary_routes import (
    serialize_model_service_summary,
    serialize_worker_runtime_summary,
)
from app.api.task_schemas import CreateTaskRequest
from app.api.tasks import (
    _serialize_task,
    download_task_archive,
    get_task_archive,
    get_task_payload,
    router,
)
from app.core.worker_runtime import capture_provider_runtime_snapshot
from app.dependencies.project_access import ProjectAccessScope
from app.models import (
    Task,
    TaskSkillVersionReference,
    TaskStatus,
    TaskWorkerProfileSnapshot,
)

EXPECTED_TASK_ROUTES = {
    ("GET", "/tasks"),
    ("POST", "/tasks"),
    ("GET", "/tasks/filter-options"),
    ("GET", "/tasks/scheduled"),
    ("GET", "/tasks/slot-capacity"),
    ("GET", "/tasks/run-instruction-template-defaults"),
    ("POST", "/tasks/render-run-instruction-template-preview"),
    ("GET", "/tasks/{task_id}"),
    ("GET", "/tasks/{task_id}/model-service-summary"),
    ("GET", "/tasks/{task_id}/worker-runtime-summary"),
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
    fresh = CreateTaskRequest(issue_id=1, session_mode="fresh")

    assert execute.task_mode == "execute"
    assert execute.session_mode == "continue"
    assert execute.effective_require_changes is False
    assert plan.effective_require_changes is False
    assert fresh.session_mode == "fresh"


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
        session_mode="fresh",
        input_session_id=None,
        output_session_id="session-new",
        provider_id=None,
        worker_profile_id=None,
        created_at=now,
        updated_at=now,
        started_at=None,
        completed_at=None,
        is_manually_overridden=False,
        override_reason=None,
    )
    task.worker_profile_snapshot = TaskWorkerProfileSnapshot(
        task_id=12,
        profile_name="Deleted profile",
        image="worker:latest",
        runtime_mode="mounted_kit",
        worker_kit_version="0.3.5",
        worker_kit_path="/opt/codify/worker-kits/0.3.5-linux-amd64",
        volume_mounts=[],
        environment_variables=[],
        skill_selection_source="task",
        skill_references=[
            TaskSkillVersionReference(
                position=0,
                skill_id=None,
                skill_version_id=71,
                name="deleted-review",
                description="Review the frozen task input.",
            )
        ],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="{{user_prompt}}",
        default_plan_run_instruction_template="{{user_prompt}}",
        ci_auto_repair_run_instruction_template="{{user_prompt}}",
        created_at=now,
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
        "session_mode",
        "input_session_id",
        "output_session_id",
        "provider_id",
        "worker_profile_id",
        "worker_profile_name",
        "worker_image",
        "worker_runtime_mode",
        "worker_kit_version",
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
    assert response["session_mode"] == "fresh"
    assert response["output_session_id"] == "session-new"
    assert response["project_url"] == "https://gitlab.example.com/team/codify"
    assert response["skill_ids"] == []
    assert response["skill_snapshots"] == [
        {
            "id": None,
            "name": "deleted-review",
            "description": "Review the frozen task input.",
            "version_id": 71,
        }
    ]


def test_model_service_summary_exposes_runtime_config_without_api_key() -> None:
    task = SimpleNamespace(
        provider_id=7,
        model_name="claude-sonnet-4-6",
        provider_runtime_snapshot=None,
        provider=SimpleNamespace(
            name="Production AI Service",
            base_url="https://ai.example.com",
            model="claude-sonnet-4-5",
            max_turns=64,
            system_prompt="Follow the repository instructions.",
            api_key="encrypted-secret",
        ),
    )

    response = serialize_model_service_summary(task)

    assert response == {
        "configuration_source": "current_provider",
        "provider_config_available": True,
        "provider_id": 7,
        "provider_name": "Production AI Service",
        "base_url": "https://ai.example.com",
        "configured_model": "claude-sonnet-4-5",
        "actual_model": "claude-sonnet-4-6",
        "max_turns": 64,
        "system_prompt": "Follow the repository instructions.",
        "api_key_configured": True,
        "configuration_captured_at": None,
    }
    assert "api_key" not in response
    assert "encrypted-secret" not in repr(response)


def test_model_service_summary_prefers_execution_snapshot_over_mutated_provider() -> None:
    now = datetime(2026, 7, 18, 10, 0, 0)
    provider = SimpleNamespace(
        id=7,
        name="Production AI Service",
        base_url="https://ai.example.com",
        model="claude-sonnet-4-5",
        max_turns=64,
        system_prompt="Follow the repository instructions.",
        api_key="encrypted-secret",
    )
    task = SimpleNamespace(
        provider_id=7,
        model_name="claude-sonnet-4-6",
        provider=provider,
        provider_runtime_snapshot=None,
    )

    with patch("app.core.worker_runtime.utcnow", return_value=now):
        capture_provider_runtime_snapshot(task, provider)

    provider.name = "Renamed service"
    provider.model = "claude-sonnet-5"
    provider.system_prompt = "Changed after execution."
    response = serialize_model_service_summary(task)

    assert response["configuration_source"] == "execution_snapshot"
    assert response["provider_name"] == "Production AI Service"
    assert response["configured_model"] == "claude-sonnet-4-5"
    assert response["system_prompt"] == "Follow the repository instructions."
    assert response["configuration_captured_at"] == now.isoformat()
    assert response["actual_model"] == "claude-sonnet-4-6"
    assert "api_key" not in response
    assert "encrypted-secret" not in repr(response)


def test_worker_runtime_summary_uses_snapshot_and_never_returns_environment_values() -> None:
    now = datetime(2026, 7, 18, 9, 30, 0)
    task = SimpleNamespace(
        worker_profile_id=3,
        worker_profile_snapshot=SimpleNamespace(
            worker_profile_id=3,
            profile_name="Java 21 Maven Worker",
            image="registry.example.com/codify/worker-java21:2026.07",
            runtime_mode="mounted_kit",
            worker_kit_version="2026.07.18",
            worker_kit_path="/srv/codify/worker-kits/2026.07.18",
            docker_host="ssh://sensitive-host",
            docker_tls_key="/sensitive/client.key",
            codegraph_enabled=True,
            volume_mounts=[
                {
                    "host_path": "/srv/maven-cache",
                    "container_path": "/root/.m2",
                    "mode": "rw",
                }
            ],
            environment_variables=[
                {"key": "JAVA_HOME", "value": "/opt/java", "is_secret": False},
                {"key": "NPM_TOKEN", "value": "top-secret", "is_secret": True},
            ],
            pre_script="npm ci",
            post_script="",
            created_at=now,
        ),
    )

    response = serialize_worker_runtime_summary(task)

    assert response["snapshot_available"] is True
    assert response["runtime_mode"] == "mounted_kit"
    assert response["worker_kit_version"] == "2026.07.18"
    assert response["mounts"] == [
        {
            "source": "worker_kit",
            "host_path": "/srv/codify/worker-kits/2026.07.18",
            "container_path": "/opt/codify-kit",
            "mode": "ro",
        },
        {
            "source": "worker_kit",
            "host_path": "/srv/codify/worker-kits/2026.07.18/nix/store",
            "container_path": "/nix/store",
            "mode": "ro",
        },
        {
            "source": "profile",
            "host_path": "/srv/maven-cache",
            "container_path": "/root/.m2",
            "mode": "rw",
        },
    ]
    assert response["environment_variables"] == [
        {"key": "JAVA_HOME", "is_secret": False, "value_configured": True},
        {"key": "NPM_TOKEN", "is_secret": True, "value_configured": True},
    ]
    assert response["pre_script_configured"] is True
    assert response["post_script_configured"] is False
    assert "docker_host" not in response
    assert "docker_tls_key" not in response
    assert "/opt/java" not in repr(response)
    assert "top-secret" not in repr(response)
