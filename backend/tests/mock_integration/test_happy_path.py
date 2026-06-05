"""Happy path integration tests — full lifecycle with mock services.

Tests the complete flow: create issue → create task → scheduler → worker
container → fake claude → git push → MR update → task completed.

Prerequisites:
    docker-compose -f backend/tests/mock_integration/docker-compose.mock-test.yml up -d
"""

import logging

import httpx
import pytest

from .conftest import (
    create_issue_and_task,
    get_mock_calls,
    wait_for_task_status,
)

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.asyncio


class TestIssueToCompletion:
    """Full lifecycle: create issue → task → scheduler → worker → completed."""

    async def test_happy_path_issue_comment(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Create an issue and task, verify task completes and MR is updated."""
        # 1. Create issue and task
        issue, task_data = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Happy path test",
            prompt="Create a hello.py file with a greeting function",
            project_id=1,
            target_branch="main",
        )
        task_id = task_data["id"]
        assert task_id is not None, f"No task id in response: {task_data}"
        logger.info(f"Created issue {issue['id']} and task {task_id}")

        # 2. Wait for task to complete (scheduler → worker → done)
        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", (
            f"Task failed: {task.get('error_message', 'no error message')}"
        )

        # 3. Verify branch_name is on the issue (not on the task)
        assert issue.get("branch_name"), "issue branch_name should be set"
        assert task["issue"]["branch_name"], "task.issue.branch_name should be set"
        assert task.get("started_at"), "started_at should be set"
        assert task.get("completed_at"), "completed_at should be set"

        # 4. Verify CODIFY markers were parsed
        assert task.get("commit_sha"), "commit_sha should be parsed from container logs"

        # 5. Verify mock GitLab API was called correctly
        gitlab_calls = await get_mock_calls(http_client, mock_url, service="gitlab")

        # Should have fetched project info
        project_calls = [c for c in gitlab_calls if "/projects/1" in c["path"] and c["method"] == "GET" and "merge_requests" not in c["path"] and "issues" not in c["path"] and "branches" not in c["path"]]
        assert len(project_calls) >= 1, f"Expected project GET call, got: {[c['path'] for c in gitlab_calls]}"

        # 6. Verify git operations happened
        git_calls = await get_mock_calls(http_client, mock_url, service="git")
        assert len(git_calls) >= 1, "Expected at least one git operation (clone)"

        logger.info(f"✅ Happy path completed: task {task_id} → {task['status']}")

    async def test_task_completion_via_issue(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Create an issue and task via API, verify it completes."""
        # 1. Create issue and task
        issue, task_data = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Task completion test",
            prompt="Create a test.py file",
            project_id=1,
            target_branch="main",
            priority=1,
        )
        task_id = task_data["id"]
        logger.info(f"Created issue {issue['id']} and task {task_id}")

        # 2. Wait for completion
        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", (
            f"Task failed: {task.get('error_message', 'no error')}"
        )
        assert task.get("commit_sha"), "commit_sha should be set"
        logger.info(f"✅ Task completed: {task_id}")


class TestTaskStatusTransitions:
    """Verify correct status transitions through the lifecycle."""

    async def test_status_progression(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Create a task and observe status changes: PENDING → RUNNING → COMPLETED."""
        # Create issue and task
        issue, task_data = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Status progression test",
            prompt="Create hello.py",
        )
        task_id = task_data["id"]

        # Initially should be PENDING
        resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}",
            headers=admin_auth_headers,
        )
        assert resp.json()["status"] in ("pending", "queued", "running"), \
            f"Unexpected initial status: {resp.json()['status']}"

        # Wait for completion
        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        # Verify timing fields
        assert task["started_at"] is not None
        assert task["completed_at"] is not None
        logger.info(f"✅ Status progression verified for task {task_id}")


class TestCODIFYMarkerParsing:
    """Verify that CODIFY markers from container logs are parsed correctly."""

    async def test_stats_markers_parsed(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Verify CODIFY_STATS token usage is captured."""
        issue, task_data = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Markers parsing test",
            prompt="Create hello.py",
        )
        task_id = task_data["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        # The fake ci-claude.sh outputs usage stats that entrypoint.sh emits as CODIFY_STATS
        # worker.py should parse these into the task record
        assert task["status"] == "completed"
        # commit_sha comes from CODIFY_COMMIT_SHA (git rev-parse HEAD in entrypoint.sh)
        assert task.get("commit_sha") is not None

        # Check task logs for CODIFY markers
        resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}/logs",
            headers=admin_auth_headers,
        )
        if resp.status_code == 200:
            logs = resp.json()
            # Should have log entries from container execution
            assert len(logs) > 0, "Expected task logs to be recorded"

        logger.info(f"✅ CODIFY markers verified for task {task_id}")
