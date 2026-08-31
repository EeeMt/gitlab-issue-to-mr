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
    create_issue_and_task,
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

        # Create issue and task
        _issue, task_data = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Claude failure test",
            prompt="This should fail because claude returns exit code 1",
        )
        task_id = task_data["id"]
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
        # Configure mock to add a long delay so the task stays running
        resp = await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 60},
        )
        assert resp.status_code == 200

        try:
            # Create issue and task
            _issue, task_data = await create_issue_and_task(
                http_client, backend_url, admin_auth_headers,
                title=f"Cancel test {int(time.time())}",
                prompt="This task will be cancelled",
            )
            task_id = task_data["id"]
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

            # Small pause to let the container fully start
            await asyncio.sleep(2)

            # Cancel it
            resp = await http_client.post(
                f"{backend_url}/api/tasks/{task_id}/cancel",
                headers=admin_auth_headers,
            )

            if resp.status_code == 200:
                # The API persists the cancellation intent and stops the
                # container before returning; the worker finalizer converges
                # the terminal asynchronously.  Allow the documented
                # completed-vs-cancelled race while waiting for convergence.
                task = await wait_for_task_status(
                    http_client,
                    backend_url,
                    task_id,
                    target_statuses=["completed", "failed", "cancelled"],
                    auth_headers=admin_auth_headers,
                    timeout=30,
                )
                assert task["status"] in ("completed", "cancelled", "failed"), (
                    f"Expected a terminal status after cancel, got {task['status']}"
                )
                logger.info(f"✅ Task {task_id} cancel result: status={task['status']}")
            else:
                # Task finished between running check and cancel (rare race)
                logger.info(
                    f"Cancel returned {resp.status_code} — task finished "
                    f"before cancel (acceptable race condition)"
                )
                resp = await http_client.get(
                    f"{backend_url}/api/tasks/{task_id}",
                    headers=admin_auth_headers,
                )
                task = resp.json()
                assert task["status"] in ("completed", "failed", "cancelled")
        finally:
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

        _issue, task_data = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Retry test",
            prompt="This will fail then succeed on retry",
        )
        task_id = task_data["id"]

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

        # The retry creates a new task under the same issue
        retry_data = resp.json()
        retry_task_id = retry_data.get("task_id") or retry_data.get("id") or task_id

        # 3. Wait for completion
        task = await wait_for_task_status(
            http_client, backend_url, retry_task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", (
            f"Retried task should complete but got {task['status']}: "
            f"{task.get('error_message', '')}"
        )
        logger.info(f"✅ Retry succeeded: task {retry_task_id} → completed")
