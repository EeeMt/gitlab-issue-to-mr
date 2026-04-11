"""Failure path integration tests — container failures, cancel, retry.

Tests that the system correctly handles:
- Worker container failures (non-zero exit from fake claude)
- Task cancellation of a running task
- Retry of a failed task

Prerequisites:
    docker-compose -f backend/tests/mock_integration/docker-compose.mock-test.yml up -d
"""

import asyncio
import logging
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


class TestContainerFailure:
    """Worker container fails (non-zero exit code from Claude CLI)."""

    async def test_claude_failure_marks_task_failed(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """When fake-claude exits non-zero, task should end up FAILED."""
        # Configure mock to make Claude fail
        resp = await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_exit_code": 1},
        )
        assert resp.status_code == 200

        # Create task via webhook with unique issue_iid
        payload = build_webhook_payload(
            project_id=1,
            issue_iid=100,
            prompt="This should fail because claude returns exit code 1",
        )
        resp = await send_webhook(http_client, backend_url, payload)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]
        logger.info(f"Created task {task_id} (expected to fail)")

        # Wait for failure
        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "failed", f"Expected FAILED but got {task['status']}"
        assert task.get("error_message"), "Failed task should have error_message"
        logger.info(f"✅ Claude failure → task FAILED: {task.get('error_message', '')[:80]}")

        # Reset mock config for other tests
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_exit_code": 0},
        )


class TestTaskCancel:
    """Cancel a running task via API."""

    async def test_cancel_running_task(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Cancel a task while its worker container is running."""
        # Configure mock to add a delay so we can catch it mid-execution
        resp = await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 30},
        )
        assert resp.status_code == 200

        # Create task
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "This task will be cancelled",
                "branch_name": "codify/cancel-test",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]
        logger.info(f"Created task {task_id} for cancel test")

        # Wait for it to start running
        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["running"],
            auth_headers=admin_auth_headers,
            timeout=60,
        )
        assert task["status"] == "running"
        logger.info(f"Task {task_id} is running, cancelling...")

        # Cancel it
        resp = await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/cancel",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200, f"Cancel failed: {resp.text}"

        # Verify it's cancelled
        resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}",
            headers=admin_auth_headers,
        )
        task = resp.json()
        assert task["status"] == "cancelled", f"Expected cancelled, got {task['status']}"
        assert task.get("error_message") == "Cancelled by user"
        logger.info(f"✅ Task {task_id} cancelled successfully")

        # Reset mock config
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 0},
        )


class TestTaskRetry:
    """Retry a failed task."""

    async def test_retry_failed_task_succeeds(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Fail a task, then retry it with success config — should complete."""
        # 1. Make it fail first
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_exit_code": 1},
        )

        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "This will fail then succeed on retry",
                "branch_name": "codify/retry-test",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "failed"
        logger.info(f"Task {task_id} failed as expected, now retrying...")

        # 2. Fix the mock and retry
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_exit_code": 0},
        )

        resp = await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/retry",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200, f"Retry failed: {resp.text}"

        # 3. Wait for completion
        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", (
            f"Retried task should complete but got {task['status']}: "
            f"{task.get('error_message', '')}"
        )
        logger.info(f"✅ Retry succeeded: task {task_id} → completed")
