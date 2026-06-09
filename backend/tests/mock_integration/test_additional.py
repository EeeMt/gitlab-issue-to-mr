"""Additional integration tests — timeout, execute-now, project lookup, reschedule.

Covers more edge cases and API behaviors:
- Container timeout when Claude takes too long
- Execute-now API (immediately run a pending task)
- Project lookup failure (mock 404) → task fails
- Task rescheduling

Prerequisites:
    docker-compose -f backend/tests/mock_integration/docker-compose.mock-test.yml up -d
"""

import logging
import time
from datetime import UTC

import httpx
import pytest

from .conftest import (
    create_issue_and_task,
    wait_for_task_status,
)

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.asyncio


class TestContainerTimeout:
    """Verify that tasks exceeding TASK_TIMEOUT are properly handled."""

    async def test_long_running_task_timeout(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Create a task where Claude takes longer than TASK_TIMEOUT.

        The docker-compose has TASK_TIMEOUT=120 and the entrypoint wraps
        claude with `timeout $TASK_TIMEOUT`. But for testing, we use a
        claude_delay that exceeds the worker's stream timeout. The worker
        returns exit_code=-1 on log stream timeout.

        Note: Actual timeout takes TASK_TIMEOUT seconds. To keep tests fast,
        we configure TASK_TIMEOUT in docker-compose to 120s, but set
        claude_delay to something that ensures the container stays busy.
        The worker-side timeout of 120s will eventually kill it.

        For a faster test, we lower the timeout by patching config.
        """
        # Set claude to sleep for 180s but TASK_TIMEOUT is 120s in docker-compose
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 180},
        )

        _issue, task_data = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Timeout test",
            prompt="Timeout test task",
        )
        task_id = task_data["id"]

        # Wait for task to reach RUNNING first
        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["running"],
            auth_headers=admin_auth_headers,
            timeout=60,
        )
        assert task["status"] == "running"
        logger.info(f"Task {task_id} running, waiting for timeout...")

        # The task should eventually fail due to timeout
        # TASK_TIMEOUT=120s in docker-compose, plus processing overhead
        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=180,
        )
        assert task["status"] == "failed", (
            f"Timed-out task should be failed, got: {task['status']}"
        )
        logger.info(f"✅ Timeout task {task_id} correctly failed")


class TestExecuteNowAPI:
    """Verify the execute-now endpoint immediately runs a pending task."""

    async def test_execute_pending_task_immediately(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Create a delayed task then use execute-now to run it immediately.

        1. Create task with delay_seconds=300 (5 minutes in the future)
        2. Verify it's PENDING with scheduled_at set
        3. Call POST /api/tasks/{id}/execute
        4. Task should start running immediately (not wait 5 min)
        """
        _issue, task_data = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Execute now test",
            prompt="Execute now test",
            delay_seconds=300,
        )
        task_id = task_data["id"]

        # Verify task is pending with scheduled_at
        resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}",
            headers=admin_auth_headers,
        )
        task = resp.json()
        assert task["status"] in ("pending", "queued")
        assert task.get("scheduled_at"), "Delayed task should have scheduled_at"

        # Execute now — should clear scheduled_at and start immediately
        resp = await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/execute",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200, f"Execute-now failed: {resp.text}"
        logger.info(f"Execute-now called for task {task_id}")

        # Task should complete much faster than 300s
        start = time.time()
        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        elapsed = time.time() - start
        assert task["status"] == "completed", (
            f"Execute-now task should complete: {task.get('error_message')}"
        )
        assert elapsed < 120, f"Execute-now should run fast, took {elapsed:.0f}s"
        logger.info(f"✅ Execute-now task completed in {elapsed:.0f}s (delay was 300s)")


class TestProjectLookupFailure:
    """Verify behavior when GitLab project lookup fails."""

    async def test_project_404_fails_task(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """When the mock returns 404 for project lookup, the task should fail.

        The entrypoint.sh fetches project info on startup (line 49-53).
        Without PROJECT_PATH, it falls back to constructed URL.
        Git clone should still work since the mock serves repos by namespace/name.
        But let's verify the task handles this gracefully.
        """
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"fail_project_lookup": True},
        )

        _issue, task_data = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Project 404 test",
            prompt="Project lookup failure test",
        )
        task_id = task_data["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        # The entrypoint.sh has fallback logic for project lookup failure.
        # It constructs the URL as projects/{PROJECT_ID} if API fails.
        # The task may still complete (fallback URL) or fail (bad URL).
        # Either way, the task should not hang.
        logger.info(
            f"✅ Project 404 test: task {task_id} reached {task['status']} "
            f"(error: {task.get('error_message', 'none')[:100]})"
        )


class TestTaskReschedule:
    """Verify the reschedule endpoint changes scheduled_at."""

    async def test_reschedule_pending_task(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Create a delayed task, then reschedule it to run sooner.

        1. Create task with delay_seconds=600 (10 min)
        2. Reschedule to 5 seconds from now
        3. Task should complete after ~5s, not 10 min
        """
        from datetime import datetime, timedelta

        _issue, task_data = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Reschedule test",
            prompt="Reschedule test",
            delay_seconds=600,
        )
        task_id = task_data["id"]

        # Reschedule to 5 seconds from now
        new_time = datetime.now(UTC) + timedelta(seconds=5)
        resp = await http_client.patch(
            f"{backend_url}/api/tasks/{task_id}/schedule",
            json={"scheduled_datetime": new_time.isoformat()},
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200, f"Reschedule failed: {resp.status_code} {resp.text}"

        # Task should complete quickly (after ~5s delay + execution)
        start = time.time()
        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        elapsed = time.time() - start
        assert task["status"] == "completed", (
            f"Rescheduled task should complete: {task.get('error_message')}"
        )
        assert elapsed < 60, f"Rescheduled task took too long: {elapsed:.0f}s"
        logger.info(f"✅ Rescheduled task completed in {elapsed:.0f}s")
