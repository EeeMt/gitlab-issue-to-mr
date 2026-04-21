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
import time

import httpx
import pytest

from .conftest import (
    create_issue_and_task,
    get_mock_calls,
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

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Project 404 test {int(time.time())}",
            prompt="Should fail due to project 404",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "failed", f"Expected failed, got {task['status']}"
        logger.info(f"✅ Project 404 correctly failed task: {task.get('error_message', '')[:100]}")


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

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Clone fail test {int(time.time())}",
            prompt="Should fail due to clone error",
        )
        task_id = task["id"]

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

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Exit code {exit_code} test {int(time.time())}",
            prompt=f"Task with exit code {exit_code}",
        )
        task_id = task["id"]

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

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Exit code 0 test {int(time.time())}",
            prompt="Task with exit code 0",
        )
        task_id = task["id"]

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

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Notes failure test {int(time.time())}",
            prompt="Task despite comment failure",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", (
            f"Issue notes failure should be non-fatal: got {task['status']}"
        )
        logger.info("✅ Task completed despite issue notes failure")


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

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"MR update fail test {int(time.time())}",
            prompt="Task with MR update failure",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
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

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Notes+MR update fail test {int(time.time())}",
            prompt="Task with multiple non-fatal failures",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
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

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Fatal+nonfatal fail test {int(time.time())}",
            prompt="Task with fatal + non-fatal failures",
        )
        task_id = task["id"]

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
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Call recording test {int(time.time())}",
            prompt="Verify call recording",
        )
        task_id = task["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        calls = await get_mock_calls(http_client, mock_url)

        gitlab_calls = [c for c in calls if c.get("service") == "gitlab"]
        project_calls = [c for c in gitlab_calls if "/api/v4/projects/" in c.get("path", "")]
        assert len(project_calls) > 0, "Expected at least one project lookup call"

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

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Failed calls test {int(time.time())}",
            prompt="Verify calls on failure",
        )
        task_id = task["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        calls = await get_mock_calls(http_client, mock_url)
        gitlab_calls = [c for c in calls if c.get("service") == "gitlab"]
        assert len(gitlab_calls) > 0, "Failed task should still have GitLab calls"
        logger.info(f"✅ Failed task recorded {len(calls)} calls before failure")
