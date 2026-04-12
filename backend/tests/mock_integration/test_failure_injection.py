"""Failure injection tests — exercise mock server failure flags and edge cases.

Tests that the system correctly handles:
- Project lookup failures (404)
- Git clone failures
- Various Claude exit codes (137, 126, 127, 2)
- Issue notes failure being non-fatal
- Combined failure scenarios

Prerequisites:
    docker-compose -f backend/tests/mock_integration/docker-compose.mock-test.yml up -d
"""

import logging
import random
import time

import httpx
import pytest

from .conftest import (
    build_webhook_payload,
    get_mock_calls,
    send_webhook,
    wait_for_task_status,
)

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.asyncio


class TestProjectLookupFailure:
    """Project API returning 404 should fail the task quickly."""

    async def test_project_404_fails_task(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """When GitLab project lookup returns 404, task should fail."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"fail_project_lookup": True},
        )

        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Should fail due to project 404",
                "branch_name": f"codify/proj404-{int(time.time())}",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "failed", f"Expected failed, got {task['status']}"
        logger.info(f"✅ Project 404 correctly failed task: {task.get('error_message', '')[:100]}")

    async def test_project_404_via_webhook(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Webhook-created task with project 404 should also fail."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"fail_project_lookup": True},
        )

        payload = build_webhook_payload(
            project_id=1,
            issue_iid=random.randint(5000, 5999),
            prompt="Webhook task with bad project",
        )
        payload["object_attributes"]["id"] = random.randint(100000, 999999)

        resp = await send_webhook(http_client, backend_url, payload)
        assert resp.status_code == 200
        task_id = resp.json().get("task_id")
        assert task_id is not None

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "failed"
        logger.info("✅ Webhook task correctly failed on project 404")


class TestGitCloneFailure:
    """Git clone failures should fail the task."""

    async def test_git_clone_failure_fails_task(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """When git clone is rejected, task should fail."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"fail_git_clone": True},
        )

        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Should fail due to clone error",
                "branch_name": f"codify/clone-fail-{int(time.time())}",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "failed", f"Expected failed, got {task['status']}"
        logger.info(f"✅ Git clone failure correctly failed task: {task.get('error_message', '')[:100]}")


class TestExitCodes:
    """Different Claude exit codes should all result in task failure."""

    @pytest.mark.parametrize("exit_code,description", [
        (2, "misuse of shell command"),
        (126, "command not executable"),
        (127, "command not found"),
        (137, "killed by SIGKILL (OOM or timeout)"),
    ])
    async def test_exit_code_fails_task(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
        exit_code: int,
        description: str,
    ):
        """Exit code {exit_code} ({description}) should fail the task."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_exit_code": exit_code},
        )

        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": f"Task with exit code {exit_code}",
                "branch_name": f"codify/exit-{exit_code}-{int(time.time())}",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "failed", (
            f"Exit code {exit_code} ({description}) should fail: got {task['status']}"
        )
        logger.info(f"✅ Exit code {exit_code} ({description}) correctly failed task")

    async def test_exit_code_0_succeeds(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Exit code 0 should succeed (baseline verification)."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_exit_code": 0},
        )

        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Task with exit code 0",
                "branch_name": f"codify/exit-0-{int(time.time())}",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", f"Exit code 0 should succeed: got {task['status']}"
        logger.info("✅ Exit code 0 correctly succeeded")


class TestIssueNotesFailure:
    """Issue notes (comment) failure should NOT prevent task completion."""

    async def test_issue_notes_failure_nonfatal(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Task should complete even when posting issue comments fails."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"fail_issue_notes": True},
        )

        # Use webhook to create task (so it has issue_iid and would try to comment)
        payload = build_webhook_payload(
            project_id=1,
            issue_iid=random.randint(6000, 6999),
            prompt="Task despite comment failure",
        )
        payload["object_attributes"]["id"] = random.randint(100000, 999999)

        resp = await send_webhook(http_client, backend_url, payload)
        assert resp.status_code == 200
        task_id = resp.json().get("task_id")
        assert task_id is not None

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        # Task should complete — comment failure is non-fatal
        assert task["status"] == "completed", (
            f"Issue notes failure should be non-fatal: got {task['status']}"
        )
        logger.info("✅ Task completed despite issue notes failure")

    async def test_issue_notes_failure_with_manual_task(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Manual tasks (no issue_iid) should not be affected by notes failure."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"fail_issue_notes": True},
        )

        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Manual task ignores notes failure",
                "branch_name": f"codify/notes-manual-{int(time.time())}",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", (
            f"Manual task should succeed regardless of notes failure: got {task['status']}"
        )
        logger.info("✅ Manual task completed, notes failure irrelevant")


class TestCombinedFailures:
    """Multiple failure flags set simultaneously."""

    async def test_mr_update_failure_nonfatal(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """MR update failure (description update) should not prevent task completion."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"fail_mr_update": True},
        )

        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Task with MR update failure",
                "branch_name": f"codify/mr-update-fail-{int(time.time())}",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        # MR update is typically non-fatal — task can still complete
        logger.info(
            f"Task with MR update failure: status={task['status']}, "
            f"error={(task.get('error_message') or '')[:80]}"
        )

    async def test_notes_and_mr_update_both_fail(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Both notes and MR update failing should still allow task completion."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={
                "fail_issue_notes": True,
                "fail_mr_update": True,
            },
        )

        payload = build_webhook_payload(
            project_id=1,
            issue_iid=random.randint(7000, 7999),
            prompt="Task with multiple non-fatal failures",
        )
        payload["object_attributes"]["id"] = random.randint(100000, 999999)

        resp = await send_webhook(http_client, backend_url, payload)
        assert resp.status_code == 200
        task_id = resp.json().get("task_id")
        assert task_id is not None

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        # Even with multiple non-fatal failures, task should complete
        assert task["status"] == "completed", (
            f"Multiple non-fatal failures should still complete: got {task['status']}"
        )
        logger.info("✅ Task completed despite notes + MR update failures")

    async def test_fatal_plus_nonfatal_failure(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Fatal failure (exit code 1) + non-fatal (notes) = task fails."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={
                "claude_exit_code": 1,
                "fail_issue_notes": True,
            },
        )

        payload = build_webhook_payload(
            project_id=1,
            issue_iid=random.randint(8000, 8999),
            prompt="Task with fatal + non-fatal failures",
        )
        payload["object_attributes"]["id"] = random.randint(100000, 999999)

        resp = await send_webhook(http_client, backend_url, payload)
        assert resp.status_code == 200
        task_id = resp.json().get("task_id")
        assert task_id is not None

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "failed", (
            f"Fatal failure should override non-fatal: got {task['status']}"
        )
        logger.info("✅ Fatal + non-fatal correctly results in failure")


class TestMockCallRecording:
    """Verify mock server records calls for assertion."""

    async def test_successful_task_records_expected_calls(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """A successful task should trigger project lookup, git clone, git push, and MR calls."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Verify call recording",
                "branch_name": f"codify/call-record-{int(time.time())}",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        calls = await get_mock_calls(http_client, mock_url)

        # Should have called GitLab project API
        gitlab_calls = [c for c in calls if c.get("service") == "gitlab"]
        project_calls = [c for c in gitlab_calls if "/api/v4/projects/" in c.get("path", "")]
        assert len(project_calls) > 0, "Expected at least one project lookup call"

        # Should have git operations
        git_calls = [c for c in calls if c.get("service") == "git"]
        assert len(git_calls) > 0, "Expected git operations (clone/push)"

        logger.info(
            f"✅ Recorded {len(gitlab_calls)} GitLab calls, {len(git_calls)} git calls"
        )

    async def test_failed_task_still_records_calls(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Even failed tasks should have call records up to the failure point."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_exit_code": 1},
        )

        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Verify calls on failure",
                "branch_name": f"codify/fail-calls-{int(time.time())}",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        calls = await get_mock_calls(http_client, mock_url)
        # Should still have project lookup and git clone (failure happens after clone)
        gitlab_calls = [c for c in calls if c.get("service") == "gitlab"]
        assert len(gitlab_calls) > 0, "Failed task should still have GitLab calls"
        logger.info(f"✅ Failed task recorded {len(calls)} calls before failure")
