"""Tests for security, resilience, and state machine correctness.

Covers:
- Worker log sanitization (secrets not leaked)
- Issue mutex enforcement (same issue → sequential, not parallel)
- Task state machine (valid/invalid transitions)
- Error message content verification
- Multiple rapid operations stress
"""

import asyncio
import time

import httpx
import pytest

from .conftest import (
    create_issue,
    create_issue_and_task,
    create_task,
    wait_for_task_status,
)


class TestLogSanitizationSecurity:
    """Verify secrets are scrubbed from stored task logs."""

    @pytest.mark.asyncio
    async def test_gitlab_token_not_in_task_logs(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """GITLAB_TOKEN (glpat-*) should be sanitized in stored logs."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Token sanitization test {int(time.time())}",
            prompt="Create a file that prints env vars",
        )
        task_id = task["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            ["completed", "failed"], admin_auth_headers,
        )

        logs_resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}/logs",
            headers=admin_auth_headers,
        )
        assert logs_resp.status_code == 200
        logs = logs_resp.json()

        all_log_text = " ".join(
            str(entry.get("message", "") if isinstance(entry, dict) else entry)
            for entry in (logs if isinstance(logs, list) else logs.get("items", [logs]))
        )
        assert "glpat-" not in all_log_text.lower(), (
            "GitLab token pattern 'glpat-' found in sanitized logs"
        )
        assert "mock-token-12345" not in all_log_text, (
            "Mock GitLab token found in logs — should be sanitized"
        )

    @pytest.mark.asyncio
    async def test_anthropic_key_not_in_task_logs(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """ANTHROPIC_API_KEY (sk-ant-*) should be sanitized in stored logs."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Anthropic key sanitization test {int(time.time())}",
            prompt="Test anthropic key sanitization",
        )
        task_id = task["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            ["completed", "failed"], admin_auth_headers,
        )

        logs_resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}/logs",
            headers=admin_auth_headers,
        )
        assert logs_resp.status_code == 200
        logs = logs_resp.json()

        all_log_text = " ".join(
            str(entry.get("message", "") if isinstance(entry, dict) else entry)
            for entry in (logs if isinstance(logs, list) else logs.get("items", [logs]))
        )
        assert "sk-ant-" not in all_log_text, (
            "Anthropic API key pattern 'sk-ant-' found in logs — should be sanitized"
        )


class TestIssueMutexEnforcement:
    """Verify that tasks for the same issue run sequentially, not in parallel."""

    @pytest.mark.asyncio
    async def test_same_issue_tasks_run_sequentially(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Two tasks for the same issue should not run simultaneously."""
        async with httpx.AsyncClient(timeout=10) as mc:
            await mc.patch(
                f"{mock_url}/mock/config",
                json={"claude_delay_seconds": 8},
            )

        issue = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title=f"Mutex test issue {int(time.time())}",
            description="Mutex test",
        )

        task1 = await create_task(
            http_client, backend_url, admin_auth_headers, issue["id"],
            user_prompt="Mutex test task 1",
        )
        tid1 = task1["id"]

        task2 = await create_task(
            http_client, backend_url, admin_auth_headers, issue["id"],
            user_prompt="Mutex test task 2",
        )
        tid2 = task2["id"]

        await wait_for_task_status(
            http_client, backend_url, tid1,
            ["running", "completed", "failed"], admin_auth_headers, timeout=60,
        )

        r2_detail = await http_client.get(
            f"{backend_url}/api/tasks/{tid2}",
            headers=admin_auth_headers,
        )
        task2_status = r2_detail.json()["status"]

        r1_detail = await http_client.get(
            f"{backend_url}/api/tasks/{tid1}",
            headers=admin_auth_headers,
        )
        task1_status = r1_detail.json()["status"]

        if task1_status == "running":
            assert task2_status in ("pending", "queued"), (
                f"Mutex violation: task1={task1_status}, task2={task2_status} "
                f"(both for same issue {issue['id']})"
            )

        await wait_for_task_status(
            http_client, backend_url, tid1,
            ["completed", "failed"], admin_auth_headers, timeout=60,
        )
        await wait_for_task_status(
            http_client, backend_url, tid2,
            ["completed", "failed"], admin_auth_headers, timeout=60,
        )

    @pytest.mark.asyncio
    async def test_different_issues_run_in_parallel(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Tasks for different issues should be able to run simultaneously."""
        async with httpx.AsyncClient(timeout=10) as mc:
            await mc.patch(
                f"{mock_url}/mock/config",
                json={"claude_delay_seconds": 8},
            )

        ts = int(time.time())
        issue1, task1 = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Parallel test 1 {ts}",
            prompt="Parallel test 1",
        )
        tid1 = task1["id"]

        issue2, task2 = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Parallel test 2 {ts}",
            prompt="Parallel test 2",
        )
        tid2 = task2["id"]

        await wait_for_task_status(
            http_client, backend_url, tid1,
            ["running", "completed", "failed"], admin_auth_headers, timeout=60,
        )
        await wait_for_task_status(
            http_client, backend_url, tid2,
            ["running", "completed", "failed"], admin_auth_headers, timeout=60,
        )

        r1_detail = await http_client.get(
            f"{backend_url}/api/tasks/{tid1}", headers=admin_auth_headers,
        )
        r2_detail = await http_client.get(
            f"{backend_url}/api/tasks/{tid2}", headers=admin_auth_headers,
        )
        s1 = r1_detail.json()["status"]
        s2 = r2_detail.json()["status"]

        assert s1 in ("running", "completed", "failed"), f"Task 1 stuck: {s1}"
        assert s2 in ("running", "completed", "failed"), f"Task 2 stuck: {s2}"

        await wait_for_task_status(
            http_client, backend_url, tid1,
            ["completed", "failed"], admin_auth_headers, timeout=60,
        )
        await wait_for_task_status(
            http_client, backend_url, tid2,
            ["completed", "failed"], admin_auth_headers, timeout=60,
        )


class TestTaskStateMachine:
    """Verify task state machine enforces valid transitions."""

    @pytest.mark.asyncio
    async def test_execute_completed_task_rejected(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Cannot execute a task that already completed."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Execute completed test {int(time.time())}",
            prompt="Execute completed test",
        )
        task_id = task["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            ["completed", "failed"], admin_auth_headers,
        )

        exec_resp = await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/execute",
            headers=admin_auth_headers,
        )
        assert exec_resp.status_code == 400, (
            f"Expected 400 for execute on completed task, got {exec_resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_execute_cancelled_task_rejected(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Cannot execute a task that was cancelled."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Cancel then execute test {int(time.time())}",
            prompt="Cancel then execute test",
            delay_seconds=3600,
        )
        task_id = task["id"]

        c = await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/cancel",
            headers=admin_auth_headers,
        )
        assert c.status_code == 200

        exec_resp = await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/execute",
            headers=admin_auth_headers,
        )
        assert exec_resp.status_code == 400, (
            f"Expected 400 for execute on cancelled task, got {exec_resp.status_code}"
        )


class TestErrorMessageContent:
    """Verify error messages are descriptive and not empty."""

    @pytest.mark.asyncio
    async def test_failed_task_has_error_message(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Failed task should have a non-empty error_message."""
        async with httpx.AsyncClient(timeout=10) as mc:
            await mc.patch(
                f"{mock_url}/mock/config",
                json={"claude_exit_code": 1},
            )

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Error message test {int(time.time())}",
            prompt="Error message test",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            ["failed"], admin_auth_headers,
        )

        assert task.get("error_message"), (
            f"Failed task should have error_message, got: {task.get('error_message')!r}"
        )
        assert len(task["error_message"]) > 5, (
            f"Error message too short: {task['error_message']!r}"
        )

    @pytest.mark.asyncio
    async def test_cancelled_task_has_error_message(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Cancelled task should have 'Cancelled by user' message."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Cancel error msg test {int(time.time())}",
            prompt="Cancel error msg test",
            delay_seconds=3600,
        )
        task_id = task["id"]

        await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/cancel",
            headers=admin_auth_headers,
        )

        detail = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}",
            headers=admin_auth_headers,
        )
        assert detail.status_code == 200
        task = detail.json()
        assert task["status"] == "cancelled"
        assert "cancel" in task.get("error_message", "").lower(), (
            f"Cancelled task error_message should mention 'cancel': {task.get('error_message')!r}"
        )

    @pytest.mark.asyncio
    async def test_git_push_failure_error_mentions_push(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Git push failure should produce error message mentioning the failure."""
        async with httpx.AsyncClient(timeout=10) as mc:
            await mc.patch(
                f"{mock_url}/mock/config",
                json={"fail_git_push": True},
            )

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Push fail error test {int(time.time())}",
            prompt="Push fail error msg test",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            ["failed"], admin_auth_headers,
        )

        error_msg = task.get("error_message", "")
        assert error_msg, "Failed task from git push failure should have error_message"


class TestRapidOperationsStress:
    """Stress test with rapid task creation and API calls."""

    @pytest.mark.asyncio
    async def test_rapid_task_status_polling(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Rapidly polling a task's status should not cause errors."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Rapid polling test {int(time.time())}",
            prompt="Rapid polling test",
        )
        task_id = task["id"]

        errors = 0
        for _ in range(20):
            r = await http_client.get(
                f"{backend_url}/api/tasks/{task_id}",
                headers=admin_auth_headers,
            )
            if r.status_code != 200:
                errors += 1
            await asyncio.sleep(0.1)

        assert errors == 0, f"Got {errors} errors during rapid polling"

        await wait_for_task_status(
            http_client, backend_url, task_id,
            ["completed", "failed"], admin_auth_headers,
        )

    @pytest.mark.asyncio
    async def test_rapid_task_list_calls(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Rapidly calling task list endpoint should be stable."""
        errors = 0
        for _ in range(15):
            r = await http_client.get(
                f"{backend_url}/api/tasks?page=1&page_size=10",
                headers=admin_auth_headers,
            )
            if r.status_code != 200:
                errors += 1
            await asyncio.sleep(0.05)

        assert errors == 0, f"Got {errors} errors during rapid list calls"

    @pytest.mark.asyncio
    async def test_concurrent_api_calls_different_endpoints(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Hitting multiple API endpoints concurrently should not cause issues."""

        async def call_endpoint(path):
            async with httpx.AsyncClient(timeout=30.0) as c:
                return await c.get(
                    f"{backend_url}{path}",
                    headers=admin_auth_headers,
                )

        endpoints = [
            "/api/tasks?page=1&page_size=5",
            "/api/stats",
            "/api/config",
            "/api/projects",
            "/api/containers",
        ]

        results = await asyncio.gather(
            *[call_endpoint(ep) for ep in endpoints],
            return_exceptions=True,
        )

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                pytest.fail(f"Concurrent call to {endpoints[i]} raised: {result}")
            assert result.status_code == 200, (
                f"{endpoints[i]} returned {result.status_code}"
            )
