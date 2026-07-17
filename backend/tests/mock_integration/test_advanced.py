"""Advanced integration tests: base branch, scheduling, crash recovery, issue mutex.

Tests complex scheduler and worker behaviors:
- Base branch handling (creating branch from specific base)
- Delayed/scheduled tasks (delay_seconds support)
- Crash recovery (scheduler restart marks orphaned tasks as failed)
- Issue mutex (same issue cannot have concurrent tasks)

Prerequisites:
    docker-compose -f backend/tests/mock_integration/docker-compose.mock-test.yml up -d
"""

import asyncio
import logging
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from .conftest import (
    create_issue,
    create_issue_and_task,
    create_task,
    get_mock_calls,
    get_worker_profile_id,
    wait_for_task_status,
)

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.asyncio

# Project root: backend/tests/mock_integration/test_advanced.py -> 4 levels up
PROJECT_ROOT = str(Path(__file__).resolve().parents[3])


class TestBaseBranch:
    """Verify that BASE_BRANCH env var is correctly passed to the worker container."""

    async def test_task_with_explicit_base_branch(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Create a task with base_branch set on the issue."""
        # Create issue with explicit base_branch via direct API call
        worker_profile_id = await get_worker_profile_id(
            http_client, backend_url, admin_auth_headers
        )
        resp = await http_client.post(
            f"{backend_url}/api/issues",
            json={
                "title": f"Base branch test {int(time.time())}",
                "description": "Test base branch handling",
                "project_id": 1,
                "base_branch": "main",
                "target_branch": "main",
                "worker_profile_id": worker_profile_id,
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201), f"Create issue failed: {resp.text}"
        issue = resp.json()

        task = await create_task(
            http_client, backend_url, admin_auth_headers, issue["id"],
            user_prompt="Test base branch handling",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", (
            f"Task with base_branch should complete: {task.get('error_message')}"
        )
        # base_branch is on the issue, not the task
        issue_data = task.get("issue", {})
        assert issue_data.get("base_branch") == "main", "base_branch should be stored on issue"

        git_calls = await get_mock_calls(http_client, mock_url, service="git")
        assert len(git_calls) >= 2, "Expected at least clone + push git operations"

    async def test_task_without_base_branch_uses_target(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """When no base_branch is set, entrypoint falls back to TARGET_BRANCH."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"No base branch test {int(time.time())}",
            prompt="Test without base branch",
            target_branch="main",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", (
            f"Task without base_branch should complete: {task.get('error_message')}"
        )
        issue_data = task.get("issue", {})
        assert issue_data.get("base_branch") is None, "base_branch should be None when not set"


class TestScheduledTasks:
    """Verify that delay_seconds and scheduled_datetime work correctly."""

    async def test_delay_seconds_defers_execution(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Create a task with delay_seconds=15."""
        delay = 15

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Delayed task test {int(time.time())}",
            prompt="Delayed task test",
            target_branch="main",
            delay_seconds=delay,
        )
        task_id = task["id"]
        create_time = time.time()
        logger.info(f"Created delayed task {task_id} with delay={delay}s")

        # Verify task is PENDING and has scheduled_at set
        resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}",
            headers=admin_auth_headers,
        )
        task_data = resp.json()
        assert task_data["status"] in ("pending", "queued"), (
            f"Delayed task should be pending/queued initially, got: {task_data['status']}"
        )
        assert task_data.get("scheduled_at"), "Delayed task should have scheduled_at set"

        # Check that the task is NOT running during the first ~10 seconds
        await asyncio.sleep(8)
        resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}",
            headers=admin_auth_headers,
        )
        early_status = resp.json()["status"]
        elapsed = time.time() - create_time
        logger.info(f"Task status after {elapsed:.0f}s: {early_status}")

        if elapsed < delay - 3:
            assert early_status in ("pending", "queued"), (
                f"Task should still be pending/queued at {elapsed:.0f}s "
                f"(delay={delay}s), got: {early_status}"
            )

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        total_elapsed = time.time() - create_time
        assert task["status"] == "completed", (
            f"Delayed task should complete: {task.get('error_message')}"
        )

        logger.info(
            f"Delayed task completed after {total_elapsed:.0f}s "
            f"(delay was {delay}s)"
        )
        assert total_elapsed >= delay - 3, (
            f"Task completed too quickly ({total_elapsed:.0f}s), "
            f"delay should enforce ~{delay}s wait"
        )


class TestIssueMutex:
    """Verify that the scheduler prevents concurrent tasks for the same issue."""

    async def test_same_issue_tasks_run_sequentially(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Create two tasks for the same issue — mutex prevents parallel execution."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 8},
        )

        # Create one issue and two tasks under it
        issue = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title=f"Mutex test {int(time.time())}",
            description="Mutex test issue",
            target_branch="main",
        )

        task1 = await create_task(
            http_client, backend_url, admin_auth_headers, issue["id"],
            user_prompt="First task for mutex test",
        )
        task1_id = task1["id"]

        await asyncio.sleep(1)

        task2 = await create_task(
            http_client, backend_url, admin_auth_headers, issue["id"],
            user_prompt="Second task for mutex test",
        )
        task2_id = task2["id"]

        logger.info(f"Created mutex test tasks: {task1_id}, {task2_id}")

        task1_data = await wait_for_task_status(
            http_client, backend_url, task1_id,
            target_statuses=["running", "completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=60,
        )

        if task1_data["status"] == "running":
            resp = await http_client.get(
                f"{backend_url}/api/tasks/{task2_id}",
                headers=admin_auth_headers,
            )
            task2_interim = resp.json()
            logger.info(
                f"Task1 status: running, Task2 status: {task2_interim['status']}"
            )
            assert task2_interim["status"] in ("pending", "queued"), (
                f"Second task should be pending while first runs (issue mutex), "
                f"got: {task2_interim['status']}"
            )

        task1_final = await wait_for_task_status(
            http_client, backend_url, task1_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        task2_final = await wait_for_task_status(
            http_client, backend_url, task2_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        assert task1_final["status"] == "completed", (
            f"First mutex task should complete: {task1_final.get('error_message')}"
        )
        assert task2_final["status"] == "completed", (
            f"Second mutex task should complete: {task2_final.get('error_message')}"
        )

        t1_completed = task1_final.get("completed_at", "")
        t2_started = task2_final.get("started_at", "")
        if t1_completed and t2_started:
            assert t2_started >= t1_completed, (
                f"Task2 should start after Task1 completes (issue mutex): "
                f"T1 completed={t1_completed}, T2 started={t2_started}"
            )


class TestCrashRecovery:
    """Verify scheduler crash recovery marks orphaned tasks as failed."""

    async def test_orphaned_running_task_marked_failed(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Simulate a crash recovery scenario."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 60},
        )

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Crash recovery test {int(time.time())}",
            prompt="Crash recovery test task",
            target_branch="main",
        )
        task_id = task["id"]
        logger.info(f"Created crash recovery test task {task_id}")

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["running"],
            auth_headers=admin_auth_headers,
            timeout=60,
        )
        assert task["status"] == "running"
        logger.info(f"Task {task_id} is now running")

        compose_file = "backend/tests/mock_integration/docker-compose.mock-test.yml"
        logger.info("Stopping scheduler before removing worker container...")
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "stop", "scheduler"],
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT_ROOT,
        )
        await asyncio.sleep(2)

        container_prefix = f"codify-{task_id}-"
        fmt = "{{.Names}}"
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", fmt, "--filter", f"name={container_prefix}"],
            capture_output=True, text=True, timeout=10,
        )
        containers = [c.strip() for c in result.stdout.strip().split("\n") if c.strip()]
        logger.info(f"Found worker containers: {containers}")

        for c in containers:
            logger.info(f"Force removing container {c}")
            subprocess.run(
                ["docker", "rm", "-f", c],
                capture_output=True, text=True, timeout=10,
            )
        await asyncio.sleep(2)

        logger.info("Starting scheduler to trigger crash recovery...")
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "start", "scheduler"],
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT_ROOT,
        )

        await asyncio.sleep(10)

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=60,
        )

        assert task["status"] == "failed", (
            f"Orphaned task should be marked failed after crash recovery, "
            f"got: {task['status']}"
        )
        error_msg = task.get("error_message", "")
        assert "scheduler restarted" in error_msg.lower() or "container" in error_msg.lower(), (
            f"Error message should mention restart/container, got: {error_msg}"
        )

    async def test_scheduler_resumes_running_container(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """If a worker container is still running during restart, scheduler resumes it."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 10},
        )

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Crash resume test {int(time.time())}",
            prompt="Resume test task",
            target_branch="main",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["running"],
            auth_headers=admin_auth_headers,
            timeout=60,
        )
        assert task["status"] == "running"
        logger.info(f"Task {task_id} running, restarting scheduler...")

        compose_file = "backend/tests/mock_integration/docker-compose.mock-test.yml"
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "restart", "scheduler"],
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT_ROOT,
        )

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", (
            f"Resumed task should complete: {task.get('error_message')}"
        )
