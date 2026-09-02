#!/usr/bin/env python3
"""
Test P0.1: Initial MR creation and MR_IID passing to worker.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import hashlib
import io
import json
import tarfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock config before importing worker
mock_settings = MagicMock()
mock_settings.gitlab_url = "http://gitlab.example.com"
mock_settings.gitlab_bot_token = "test-token"
mock_settings.worker_image = "test-worker:latest"
mock_settings.task_timeout = 1800
mock_settings.anthropic_base_url = "http://localhost:11434/v1"
mock_settings.anthropic_api_key = "test-key"
mock_settings.anthropic_model = "claude-sonnet-4-20250514"
mock_settings.default_target_branch = "main"
mock_settings.max_retries = 0

mock_settings.dashboard_url = "http://localhost:3000"
mock_settings.alert_on_failure = False
mock_settings.claude_max_turns = 10
mock_settings.custom_ca_bundle = ""
mock_settings.worker_network = ""
mock_settings.worker_extra_volumes = ""
mock_settings.worker_workspace_host_path = "/tmp/test-codify-workspace"
mock_settings.worker_skip_image_pull = True
mock_settings.harness_execution_mode = "dual_canary"

from app.core.worker import WorkerExecutor
from app.core.worker_runtime_bundle import (
    bundle_manifest_digest_from_files,
    v2_launcher_manifest_bytes,
)
from app.models import Issue, Task, TaskStatus

_V2_WORKER_IMAGE_IDENTITY = {
    "schema": "codify.worker-image-identity/v1",
    "daemon_key": "priority-tests",
    "image_reference": f"registry.example.com/codify-worker@sha256:{'1' * 64}",
    "image_id": f"sha256:{'2' * 64}",
    "runtime_platform": "linux/amd64",
}
_V2_HARNESS_EVIDENCE = {
    "schema": "codify.worker-harness-verification/v1",
    "harness_key": "claude",
    "contract_version": "codify.worker.harness/v2",
    "adapter": {"version": "1.0.0"},
    "cli": {
        "source": "host_mount",
        "executable_path": "/usr/local/bin/claude",
        "version": "2.1.200",
        "binary_digest": "b" * 64,
    },
    "verification_input_digest": "4" * 64,
    "image_identity": _V2_WORKER_IMAGE_IDENTITY,
    "generation": 1,
    "verified_at": "2026-08-24T00:00:00+00:00",
}


def _make_v2_runtime_bundle():
    """Build persisted V2 bytes so priority tests traverse the real verifier."""
    entrypoint = b"#!/bin/sh\nexit 0\n"
    files = [
        {
            "path": "entrypoint.sh",
            "size": len(entrypoint),
            "sha256": hashlib.sha256(entrypoint).hexdigest(),
        }
    ]
    files_digest = bundle_manifest_digest_from_files(files)
    digest = hashlib.sha256(
        json.dumps(
            {
                "files_digest": files_digest,
                "worker_image_identity": _V2_WORKER_IMAGE_IDENTITY,
                "harness_verification_evidence": _V2_HARNESS_EVIDENCE,
                "worker_kit_identity": None,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    manifest = {
        "schema": "codify.worker.runtime-manifest/v2",
        "contract_version": "codify.worker.harness/v2",
        "event_schema": "codify.worker.event/v2",
        "orchestration_version": "1.0.0",
        "bundle_digest": digest,
        "runtime_platform": "linux/amd64",
        "worker_image_identity": _V2_WORKER_IMAGE_IDENTITY,
        "harness_verification_evidence": _V2_HARNESS_EVIDENCE,
        "files": files,
        "adapters": {
            "claude": {
                "adapter": {"version": "1.0.0", "digest": digest},
                "capabilities": {"steering": False},
            }
        },
    }
    launcher_manifest = v2_launcher_manifest_bytes(SimpleNamespace(manifest=manifest))
    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, payload, mode in (
            ("codify-runtime/orchestration/manifest.json", launcher_manifest, 0o644),
            ("codify-runtime/orchestration/entrypoint.sh", entrypoint, 0o755),
        ):
            member = tarfile.TarInfo(name=name)
            member.size = len(payload)
            member.mode = mode
            member.mtime = 0
            archive.addfile(member, io.BytesIO(payload))
    archive_bytes = archive_buffer.getvalue()
    return SimpleNamespace(
        id=81,
        digest=digest,
        contract_version="codify.worker.harness/v2",
        orchestration_version="1.0.0",
        manifest={
            **manifest,
            "archive_sha256": hashlib.sha256(archive_bytes).hexdigest(),
        },
        bundle_bytes=archive_bytes,
        size_bytes=len(archive_bytes),
    )


_V2_RUNTIME_BUNDLE = _make_v2_runtime_bundle()


@pytest.fixture(autouse=True)
def _worker_test_dependencies():
    """Keep worker settings and sleep patches scoped to this test module."""
    attempt = SimpleNamespace(
        attempt_id="task-attempt-1",
        harness_key="claude",
        adapter_version="1.0.0",
        event_schema="codify.worker.event/v2",
        control_state="disabled",
        control_supported=False,
    )
    with (
        patch('asyncio.sleep', new_callable=AsyncMock),
        patch('app.core.worker.get_settings', return_value=mock_settings),
        patch(
            "app.core.worker_task_lifecycle.inspect_v2_worker_image_identity",
            return_value=_V2_WORKER_IMAGE_IDENTITY,
        ),
        patch(
            "app.core.worker_task_lifecycle.create_task_attempt",
            new=AsyncMock(return_value=attempt),
        ),
    ):
        yield


class MockContainer:
    """Mock Docker container."""
    def __init__(self):
        self.id = "mock-container-id"


def create_mock_db(task, issue=None):
    """Create a properly configured mock database session."""
    from app.models import AIProvider, Issue, TaskWorkerProfileSnapshot

    if getattr(task, "worker_profile_id", None) is None:
        task.worker_profile_id = 1
    task.runtime_bundle_id = _V2_RUNTIME_BUNDLE.id
    task.worker_profile_snapshot = TaskWorkerProfileSnapshot(
        task_id=task.id,
        worker_profile_id=task.worker_profile_id,
        profile_name="Default Worker",
        image="test-worker:latest",
        volume_mounts=[],
        environment_variables=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
        harness_key="claude",
        cli_source="host_mount",
        cli_executable_path="/usr/local/bin/claude",
        cli_version="2.1.200",
        cli_binary_digest="b" * 64,
        harness_config_snapshot={
            "requested_runtime_contract_version": "codify.worker.harness/v2",
            "v2_worker_image_identity": _V2_WORKER_IMAGE_IDENTITY,
            "v2_harness_verification_evidence": _V2_HARNESS_EVIDENCE,
        },
        harness_adapter_version="1.0.0",
        harness_adapter_digest=_V2_RUNTIME_BUNDLE.digest,
        runtime_contract_version="codify.worker.harness/v2",
        orchestration_version="1.0.0",
        runtime_bundle_digest=_V2_RUNTIME_BUNDLE.digest,
    )
    # Ordered-turn projected lineage defaults (the scheduler repairs these before
    # claim; the worker fails closed on a missing projection).
    if getattr(task, "projected_harness_key", None) is None:
        task.projected_harness_key = "claude"
        task.projected_session_namespace = "claude-0000000000000000"
        task.projected_lineage_generation = 0
        task.projected_reset_task_id = None
        task.lineage_projection_reason = "initial"
        task.input_lineage_reason = None
    if getattr(task, "provider_id", None) is None:
        task.provider_id = 1
    task.provider = AIProvider(
        id=task.provider_id,
        name="test-provider",
        base_url="http://localhost:11434/v1",
        api_key="test-key",
        model="claude-sonnet-4-20250514",
        max_turns=10,
        is_default=True,
    )

    mock_db = MagicMock()

    async def _mock_execute(statement, *args, **kwargs):
        mock_result = MagicMock()
        statement_str = str(statement)
        if 'FROM ai_providers' in statement_str:
            provider = getattr(task, 'provider', None)
            mock_result.scalar_one_or_none.return_value = provider
            mock_result.scalars.return_value.all.return_value = [provider] if provider else []
        elif 'FROM worker_runtime_bundles' in statement_str:
            mock_result.scalar_one_or_none.return_value = _V2_RUNTIME_BUNDLE
            mock_result.scalars.return_value.all.return_value = [_V2_RUNTIME_BUNDLE]
        elif 'FROM issue_session_lineages' in statement_str:
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalars.return_value.all.return_value = []
        else:
            mock_result.scalar_one_or_none.return_value = task
            mock_result.scalars.return_value.all.return_value = [task] if task else []
        return mock_result

    mock_db.execute = AsyncMock(side_effect=_mock_execute)
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()

    async def _mock_get(model_cls, id_val):
        if model_cls is Issue:
            return issue
        if model_cls is TaskWorkerProfileSnapshot:
            return task.worker_profile_snapshot
        if model_cls is AIProvider:
            provider = getattr(task, 'provider', None)
            if provider is not None and getattr(provider, 'id', None) == id_val:
                return provider
        return None

    mock_db.get = AsyncMock(side_effect=_mock_get)
    mock_db.refresh = AsyncMock()
    return mock_db


def create_mock_issue(issue_id, project_id, branch_name=None, target_branch="main"):
    """Create a mock Issue object with the needed fields."""
    issue = MagicMock(spec=Issue)
    issue.id = issue_id
    issue.project_id = project_id
    issue.branch_name = branch_name or f"codify-issue{issue_id}"
    issue.base_branch = None
    issue.target_branch = target_branch
    issue.merge_request_iid = None
    issue.merge_request_url = None
    issue.claude_session_id = None
    issue.session_storage_path = None
    return issue


def test_create_initial_mr():
    """Test that worker creates initial draft MR before running container."""
    print("=" * 60)
    print("Testing: Create initial draft MR")
    print("=" * 60)

    # Create mock GitLab client
    mock_gitlab = MagicMock()
    mock_gitlab.normalize_web_url.side_effect = lambda url: url
    mock_gitlab.get_merge_request_stats = AsyncMock(return_value=None)
    mock_docker = MagicMock()

    # Mock the create_container to return a mock container
    mock_container = MockContainer()
    mock_docker.create_container.return_value = mock_container

    # Create mock project and MR objects
    mock_project = MagicMock()
    mock_mr = MagicMock()
    mock_mr.iid = 42
    mock_mr.web_url = "http://gitlab.example.com/project/-/merge_requests/42"
    mock_project.mergerequests.list.return_value = []
    mock_project.mergerequests.create.return_value = mock_mr

    mock_gitlab.gl.projects.get.return_value = mock_project

    # Create worker with mocks
    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    # Create mock task
    task = Task(
        id=1,
        project_id=123,
        issue_id=456,
        user_prompt="Add user authentication feature",
        rendered_prompt="Add user authentication feature",
        priority=2,
        status=TaskStatus.PENDING,
    )

    issue = create_mock_issue(456, 123, branch_name="codify-1-issue456", target_branch="main")
    mock_db = create_mock_db(task, issue)

    # Run execute_task (it's async)
    async def run_test():
        with patch.object(worker, "_stream_logs_to_db", AsyncMock(return_value=(0, "Success", 1, False))):
            with patch('app.core.worker.notify_task_event', new_callable=AsyncMock):
                with patch(
                    "app.core.worker_task_lifecycle.build_task_runtime_archive",
                    return_value=b"runtime",
                ):
                    result = await worker.execute_task(mock_db, task.id)
                    return result

    asyncio.run(run_test())

    # Verify MR was created
    mock_project.mergerequests.create.assert_called_once()
    call_args = mock_project.mergerequests.create.call_args

    # The worker passes a single dict as positional arg
    call_dict = call_args[0][0]

    # Verify it's a draft MR
    assert call_dict.get("draft") == True, "MR should be created as draft"

    # Verify title contains AI prefix
    assert call_dict["title"].startswith("AI:"), "Title should start with AI:"

    # Verify description contains the prompt
    assert "Add user authentication feature" in call_dict.get("description", ""), \
        "Description should contain user prompt"

    # Verify MR info was set on the issue (not the task)
    assert issue.merge_request_iid == 42, "Issue merge_request_iid should be set"
    assert issue.merge_request_url == "http://gitlab.example.com/project/-/merge_requests/42"

    print("✓ Worker creates initial draft MR")
    print(f"  - MR IID: {issue.merge_request_iid}")
    print(f"  - MR URL: {issue.merge_request_url}")


def test_initial_mr_description_links_issue():
    """Test initial MR description contains the user prompt."""
    print("\n" + "=" * 60)
    print("Testing: Initial MR description includes user prompt")
    print("=" * 60)

    mock_gitlab = MagicMock()
    mock_docker = MagicMock()
    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    task = Task(
        id=11,
        project_id=123,
        issue_id=456,
        user_prompt="Add user authentication feature",
        rendered_prompt="Add user authentication feature",
        priority=2,
        status=TaskStatus.PENDING,
    )

    description = worker._build_initial_mr_description(task)

    assert "Add user authentication feature" in description

    print("✓ Initial MR description contains user prompt")


def test_mr_iid_passed_to_container():
    """Test that MR_IID is passed to container environment."""
    print("\n" + "=" * 60)
    print("Testing: MR_IID passed to container environment")
    print("=" * 60)

    mock_gitlab = MagicMock()
    mock_gitlab.normalize_web_url.side_effect = lambda url: url
    mock_gitlab.get_merge_request_stats = AsyncMock(return_value=None)
    mock_docker = MagicMock()

    mock_container = MockContainer()
    mock_docker.create_container.return_value = mock_container

    mock_project = MagicMock()
    mock_mr = MagicMock()
    mock_mr.iid = 42
    mock_mr.web_url = "http://gitlab.example.com/project/-/merge_requests/42"
    mock_project.mergerequests.list.return_value = []
    mock_project.mergerequests.create.return_value = mock_mr

    mock_gitlab.gl.projects.get.return_value = mock_project

    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    task = Task(
        id=2,
        project_id=123,
        issue_id=456,
        user_prompt="Fix login bug",
        rendered_prompt="Fix login bug",
        priority=2,
        status=TaskStatus.PENDING,
    )

    issue = create_mock_issue(456, 123, branch_name="codify-2-issue456", target_branch="main")
    mock_db = create_mock_db(task, issue)

    async def run_test():
        with patch.object(worker, "_stream_logs_to_db", AsyncMock(return_value=(0, "Success", 1, False))):
            with patch('app.core.worker.notify_task_event', new_callable=AsyncMock):
                with patch(
                    "app.core.worker_task_lifecycle.build_task_runtime_archive",
                    return_value=b"runtime",
                ):
                    await worker.execute_task(mock_db, task.id)

    asyncio.run(run_test())

    # Verify create_container was called with correct environment
    mock_docker.create_container.assert_called_once()
    call_kwargs = mock_docker.create_container.call_args[1]

    # Verify MR_IID is in environment
    environment = call_kwargs.get("environment", {})
    assert "MR_IID" in environment, "MR_IID should be in container environment"
    assert environment["MR_IID"] == "42", "MR_IID should be 42"

    print("✓ MR_IID passed to container environment")
    print(f"  - MR_IID: {environment.get('MR_IID')}")


def test_mr_creation_failure_handled():
    """Test that worker continues if MR creation fails."""
    print("\n" + "=" * 60)
    print("Testing: MR creation failure handled gracefully")
    print("=" * 60)

    mock_gitlab = MagicMock()
    mock_gitlab.normalize_web_url.side_effect = lambda url: url
    mock_gitlab.get_merge_request_stats = AsyncMock(return_value=None)
    mock_docker = MagicMock()

    mock_container = MockContainer()
    mock_docker.create_container.return_value = mock_container

    # Make MR creation fail
    mock_project = MagicMock()
    mock_project.mergerequests.list.return_value = []
    mock_project.mergerequests.create.side_effect = Exception("Network error")
    mock_gitlab.gl.projects.get.return_value = mock_project

    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    task = Task(
        id=3,
        project_id=123,
        issue_id=456,
        user_prompt="Test feature",
        rendered_prompt="Test feature",
        priority=2,
        status=TaskStatus.PENDING,
    )

    issue = create_mock_issue(456, 123, branch_name="codify-3-issue456", target_branch="main")
    mock_db = create_mock_db(task, issue)

    async def run_test():
        with patch.object(worker, "_stream_logs_to_db", AsyncMock(return_value=(0, "Success", 1, False))):
            with patch('app.core.worker.notify_task_event', new_callable=AsyncMock):
                with patch(
                    "app.core.worker_task_lifecycle.build_task_runtime_archive",
                    return_value=b"runtime",
                ):
                    result = await worker.execute_task(mock_db, task.id)
                    return result

    asyncio.run(run_test())

    # Verify container was still created (worker continues without MR)
    mock_docker.create_container.assert_called_once()

    # Verify MR_IID is NOT in environment when MR creation fails
    call_kwargs = mock_docker.create_container.call_args[1]
    environment = call_kwargs.get("environment", {})
    assert "MR_IID" not in environment, "MR_IID should not be in environment when MR creation fails"

    print("✓ Worker continues when MR creation fails")
    print(f"  - MR_IID in env: {'MR_IID' in environment}")


def test_draft_removed_on_completion():
    """Test that draft status is removed from MR on task completion."""
    print("\n" + "=" * 60)
    print("Testing: Draft status removed on task completion")
    print("=" * 60)

    mock_gitlab = MagicMock()
    mock_gitlab.normalize_web_url.side_effect = lambda url: url
    mock_gitlab.get_merge_request_stats = AsyncMock(return_value=None)
    mock_docker = MagicMock()

    mock_container = MockContainer()
    mock_docker.create_container.return_value = mock_container

    mock_project = MagicMock()
    mock_mr = MagicMock()
    mock_mr.iid = 42
    mock_mr.web_url = "http://gitlab.example.com/project/-/merge_requests/42"
    mock_project.mergerequests.list.return_value = []
    mock_project.mergerequests.create.return_value = mock_mr

    # Mock the MR reload/save flow used to mark ready and remove draft status
    mock_existing_mr = MagicMock()
    mock_existing_mr.title = "Draft: AI: Complete feature"
    mock_project.mergerequests.get.return_value = mock_existing_mr

    mock_gitlab.gl.projects.get.return_value = mock_project

    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    task = Task(
        id=4,
        project_id=123,
        issue_id=456,
        user_prompt="Complete feature",
        rendered_prompt="Complete feature",
        priority=2,
        status=TaskStatus.PENDING,
    )

    issue = create_mock_issue(456, 123, branch_name="codify-4-issue456", target_branch="main")
    mock_db = create_mock_db(task, issue)

    async def run_test():
        with patch.object(
            worker,
            "_stream_logs_to_db",
            AsyncMock(return_value=(0, "Success", 1, False)),
        ):
            with patch('app.core.worker.notify_task_event', new_callable=AsyncMock):
                with patch(
                    "app.core.worker_task_lifecycle.build_task_runtime_archive",
                    return_value=b"runtime",
                ):
                    await worker.execute_task(mock_db, task.id)

    asyncio.run(run_test())

    mock_project.mergerequests.get.assert_called_with(42)
    assert not mock_existing_mr.draft
    assert mock_existing_mr.title == "AI: Complete feature"
    mock_existing_mr.save.assert_called_once()

    print("✓ Draft status removed on completion")
    print(f"  - updated title: {mock_existing_mr.title}")



if __name__ == "__main__":
    test_create_initial_mr()
    test_initial_mr_description_links_issue()
    test_mr_iid_passed_to_container()
    test_mr_creation_failure_handled()
    test_draft_removed_on_completion()

    print("\n" + "=" * 60)
    print("All P0.1 tests passed!")
    print("=" * 60)
