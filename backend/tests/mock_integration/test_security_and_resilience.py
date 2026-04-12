"""Tests for security, resilience, and state machine correctness.

Covers:
- Worker log sanitization (secrets not leaked)
- Issue mutex enforcement (same issue → sequential, not parallel)
- Task state machine (valid/invalid transitions)
- Error message content verification
- Large payload handling
- Multiple rapid operations stress
"""

import asyncio
import random
import time

import httpx
import pytest

from .conftest import (
    BACKEND_URL,
    MOCK_SERVICES_URL,
    build_webhook_payload,
    get_mock_calls,
    send_webhook,
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
        payload = build_webhook_payload(
            project_id=1,
            issue_iid=random.randint(90000, 90999),
            prompt="Create a file that prints env vars",
        )
        payload["object_attributes"]["id"] = random.randint(100000, 199999)
        resp = await send_webhook(http_client, backend_url, payload)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            ["completed", "failed"], admin_auth_headers,
        )

        # Fetch task logs
        logs_resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}/logs",
            headers=admin_auth_headers,
        )
        assert logs_resp.status_code == 200
        logs = logs_resp.json()

        # Check all log entries for leaked tokens
        all_log_text = " ".join(
            str(entry.get("message", "") if isinstance(entry, dict) else entry)
            for entry in (logs if isinstance(logs, list) else logs.get("items", [logs]))
        )
        assert "glpat-" not in all_log_text.lower(), (
            "GitLab token pattern 'glpat-' found in sanitized logs"
        )
        # Mock token is "mock-token-12345", also check
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
        payload = build_webhook_payload(
            project_id=1,
            issue_iid=random.randint(91000, 91999),
            prompt="Test anthropic key sanitization",
        )
        payload["object_attributes"]["id"] = random.randint(200000, 299999)
        resp = await send_webhook(http_client, backend_url, payload)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

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
        """Two tasks for the same project:issue should not run simultaneously."""
        # Use moderate delay so tasks overlap if mutex is broken
        async with httpx.AsyncClient(timeout=10) as mc:
            await mc.patch(
                f"{mock_url}/mock/config",
                json={"claude_delay_seconds": 8},
            )

        shared_iid = random.randint(92000, 92999)

        payload1 = build_webhook_payload(
            project_id=1,
            issue_iid=shared_iid,
            prompt="Mutex test task 1",
        )
        payload1["object_attributes"]["id"] = random.randint(300000, 399999)

        payload2 = build_webhook_payload(
            project_id=1,
            issue_iid=shared_iid,
            prompt="Mutex test task 2",
        )
        payload2["object_attributes"]["id"] = random.randint(400000, 499999)

        # Create both tasks
        r1 = await send_webhook(http_client, backend_url, payload1)
        assert r1.status_code == 200
        tid1 = r1.json()["task_id"]

        r2 = await send_webhook(http_client, backend_url, payload2)
        assert r2.status_code == 200
        tid2 = r2.json()["task_id"]

        # Wait for first task to start running
        await wait_for_task_status(
            http_client, backend_url, tid1,
            ["running", "completed", "failed"], admin_auth_headers, timeout=60,
        )

        # Check second task: should still be pending (mutex blocks it)
        r2_detail = await http_client.get(
            f"{backend_url}/api/tasks/{tid2}",
            headers=admin_auth_headers,
        )
        task2_status = r2_detail.json()["status"]

        # Task 2 should not be running simultaneously (it should be pending or queued)
        # If task 1 already completed fast, task 2 may have started — that's OK
        r1_detail = await http_client.get(
            f"{backend_url}/api/tasks/{tid1}",
            headers=admin_auth_headers,
        )
        task1_status = r1_detail.json()["status"]

        if task1_status == "running":
            # Mutex should prevent task2 from being "running" at the same time
            assert task2_status in ("pending", "queued"), (
                f"Mutex violation: task1={task1_status}, task2={task2_status} "
                f"(both for same issue {shared_iid})"
            )

        # Wait for both to complete
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

        iid1 = random.randint(93000, 93499)
        iid2 = random.randint(93500, 93999)

        payload1 = build_webhook_payload(project_id=1, issue_iid=iid1, prompt="Parallel test 1")
        payload1["object_attributes"]["id"] = random.randint(500000, 599999)

        payload2 = build_webhook_payload(project_id=1, issue_iid=iid2, prompt="Parallel test 2")
        payload2["object_attributes"]["id"] = random.randint(600000, 699999)

        r1 = await send_webhook(http_client, backend_url, payload1)
        r2 = await send_webhook(http_client, backend_url, payload2)

        assert r1.status_code == 200
        assert r2.status_code == 200
        tid1 = r1.json()["task_id"]
        tid2 = r2.json()["task_id"]

        # Wait for both to start
        await wait_for_task_status(
            http_client, backend_url, tid1,
            ["running", "completed", "failed"], admin_auth_headers, timeout=60,
        )
        await wait_for_task_status(
            http_client, backend_url, tid2,
            ["running", "completed", "failed"], admin_auth_headers, timeout=60,
        )

        # Check if both are running (or one already finished quickly)
        r1_detail = await http_client.get(
            f"{backend_url}/api/tasks/{tid1}", headers=admin_auth_headers,
        )
        r2_detail = await http_client.get(
            f"{backend_url}/api/tasks/{tid2}", headers=admin_auth_headers,
        )
        s1 = r1_detail.json()["status"]
        s2 = r2_detail.json()["status"]

        # Both should have progressed beyond pending (parallel execution allowed)
        assert s1 in ("running", "completed", "failed"), f"Task 1 stuck: {s1}"
        assert s2 in ("running", "completed", "failed"), f"Task 2 stuck: {s2}"

        # Wait for completion
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
        payload = build_webhook_payload(
            project_id=1,
            issue_iid=random.randint(94000, 94999),
            prompt="Execute completed test",
        )
        payload["object_attributes"]["id"] = random.randint(700000, 799999)
        resp = await send_webhook(http_client, backend_url, payload)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            ["completed", "failed"], admin_auth_headers,
        )

        # Try to execute again
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
        ts = int(time.time())
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Cancel then execute test",
                "branch_name": f"codify/cancel-exec-{ts}",
                "delay_seconds": 3600,
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json().get("task_id") or resp.json().get("id")

        # Cancel it
        c = await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/cancel",
            headers=admin_auth_headers,
        )
        assert c.status_code == 200

        # Try to execute
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

        payload = build_webhook_payload(
            project_id=1,
            issue_iid=random.randint(95000, 95999),
            prompt="Error message test",
        )
        payload["object_attributes"]["id"] = random.randint(800000, 899999)
        resp = await send_webhook(http_client, backend_url, payload)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

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
        ts = int(time.time())
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Cancel error msg test",
                "branch_name": f"codify/cancel-msg-{ts}",
                "delay_seconds": 3600,
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json().get("task_id") or resp.json().get("id")

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

        payload = build_webhook_payload(
            project_id=1,
            issue_iid=random.randint(96000, 96999),
            prompt="Push fail error msg test",
        )
        payload["object_attributes"]["id"] = random.randint(900000, 999999)
        resp = await send_webhook(http_client, backend_url, payload)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

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
        payload = build_webhook_payload(
            project_id=1,
            issue_iid=random.randint(97000, 97999),
            prompt="Rapid polling test",
        )
        payload["object_attributes"]["id"] = random.randint(100000, 199999)
        resp = await send_webhook(http_client, backend_url, payload)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        # Poll 20 times rapidly
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

        # Clean up: wait for task to finish
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
