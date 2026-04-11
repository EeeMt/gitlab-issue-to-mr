"""Advanced integration tests — base branch, scheduling, crash recovery, issue mutex.

Tests complex scheduler and worker behaviors:
- Base branch handling (creating branch from specific base)
- Delayed/scheduled tasks (delay_seconds support)
- Crash recovery (scheduler restart marks orphaned tasks as failed)
- Issue mutex (same issue can't have concurrent tasks)

Prerequisites:
    docker-compose -f backend/tests/mock_integration/docker-compose.mock-test.yml up -d
"""

import asyncio
import logging
import subprocess
import time

import httpx
import pytest

from .conftest import (
    build_webhook_payload,
    get_mock_calls,
    send_webhook,
    wait_for_task_status,
    DOCKER_HOST_IP,
)

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.asyncio


class TestBaseBranch:
    """Verify that BASE_BRANCH env var is correctly passed to the worker container."""

    async def test_task_with_explicit_base_branch(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Create a manual task with base_branch set.

        The entrypoint.sh should:
        1. Clone the repo
        2. Create the new branch from origin/<base_branch>
        3. Complete successfully
        """
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Test base branch handling",
                "branch_name": "codify/test-base-branch",
                "base_branch": "main",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201), f"Create task failed: {resp.text}"
        task_id = resp.json()["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", (
            f"Task with base_branch should complete: {task.get('error_message')}"
        )
        assert task.get("base_branch") == "main", "base_branch should be stored on task"

        # Verify git operations
        git_calls = await get_mock_calls(http_client, mock_url, service="git")
        assert len(git_calls) >= 2, "Expected at least clone + push git operations"
        logger.info("✅ Task with explicit base_branch completed successfully")

    async def test_task_without_base_branch_uses_target(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """When no base_branch is set, entrypoint falls back to TARGET_BRANCH.

        Worker.py only sets BASE_BRANCH env when task.base_branch is set.
        entrypoint.sh falls back: BASE_BRANCH = TARGET_BRANCH or default_branch.
        """
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Test without base branch",
                "branch_name": "codify/test-no-base",
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
            f"Task without base_branch should complete: {task.get('error_message')}"
        )
        # base_branch should be None/null when not explicitly set
        assert task.get("base_branch") is None, "base_branch should be None when not set"
        logger.info("✅ Task without base_branch completed (falls back to target)")


class TestScheduledTasks:
    """Verify that delay_seconds and scheduled_datetime work correctly."""

    async def test_delay_seconds_defers_execution(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Create a task with delay_seconds=15.

        The task should:
        1. Be created immediately as PENDING with scheduled_at in the future
        2. NOT start running during the first ~12 seconds
        3. Eventually be picked up after the delay expires
        4. Complete successfully
        """
        delay = 15

        # Create the delayed task
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Delayed task test",
                "branch_name": "codify/test-delayed",
                "target_branch": "main",
                "delay_seconds": delay,
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201), f"Create delayed task failed: {resp.text}"
        task_id = resp.json()["id"]
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

        # The task should still be pending/queued (not running) before delay expires
        # Allow some slack: the scheduler polls every 2-3 seconds
        if elapsed < delay - 3:
            assert early_status in ("pending", "queued"), (
                f"Task should still be pending/queued at {elapsed:.0f}s "
                f"(delay={delay}s), got: {early_status}"
            )

        # Now wait for the task to complete after the delay
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

        # The task should have taken at least delay_seconds to start
        logger.info(
            f"✅ Delayed task completed after {total_elapsed:.0f}s "
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
        """Create two webhook tasks for the same issue.

        The scheduler's issue mutex should prevent the second task from
        running while the first is still active. Both should eventually complete.
        """
        # Add delay so first task takes a while
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 8},
        )

        # Send two webhooks for the same project/issue but different prompts
        payload1 = build_webhook_payload(
            project_id=1,
            issue_iid=99,
            prompt="First task for mutex test",
        )
        resp1 = await send_webhook(http_client, backend_url, payload1)
        assert resp1.status_code == 200
        task1_id = resp1.json()["task_id"]

        # Small delay so second task is created after first
        await asyncio.sleep(1)

        payload2 = build_webhook_payload(
            project_id=1,
            issue_iid=99,
            prompt="Second task for mutex test",
        )
        resp2 = await send_webhook(http_client, backend_url, payload2)
        assert resp2.status_code == 200
        task2_id = resp2.json()["task_id"]

        logger.info(f"Created mutex test tasks: {task1_id}, {task2_id}")

        # Wait for first task to start running
        task1 = await wait_for_task_status(
            http_client, backend_url, task1_id,
            target_statuses=["running", "completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=60,
        )

        # While first task is running, second should still be pending
        if task1["status"] == "running":
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

        # Both should eventually complete
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

        # Verify sequential execution: task2 should have started after task1 completed
        t1_completed = task1_final.get("completed_at", "")
        t2_started = task2_final.get("started_at", "")
        if t1_completed and t2_started:
            assert t2_started >= t1_completed, (
                f"Task2 should start after Task1 completes (issue mutex): "
                f"T1 completed={t1_completed}, T2 started={t2_started}"
            )

        logger.info(
            f"✅ Issue mutex verified: tasks ran sequentially "
            f"(T1 done={t1_completed}, T2 start={t2_started})"
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
        """Simulate a crash recovery scenario.

        Steps:
        1. Create a task with very long claude delay
        2. Wait for it to reach RUNNING status
        3. Kill the worker container (simulating crash — orphan in DB)
        4. Restart the scheduler (triggers crash recovery)
        5. The task should be marked as FAILED (container gone)
           OR completed if the scheduler resumes from exited container
        """
        # Use long delay so the task stays running
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 60},
        )

        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Crash recovery test task",
                "branch_name": "codify/crash-recovery-test",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]
        logger.info(f"Created crash recovery test task {task_id}")

        # Wait for task to reach RUNNING
        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["running"],
            auth_headers=admin_auth_headers,
            timeout=60,
        )
        assert task["status"] == "running"
        logger.info(f"Task {task_id} is now running")

        # IMPORTANT: Stop the scheduler FIRST so its monitoring thread can't
        # process the container removal. Then kill the worker container.
        # When we restart the scheduler, crash recovery finds RUNNING task but
        # no container → marks FAILED.
        compose_file = "backend/tests/mock_integration/docker-compose.mock-test.yml"
        logger.info("Stopping scheduler before killing worker container...")
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "stop", "scheduler"],
            capture_output=True, text=True, timeout=30,
            cwd="/Users/AI/Projects/codify",
        )
        await asyncio.sleep(2)

        # Now kill the worker container (scheduler can't react)
        container_name = f"codify-{task_id}-"
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}", "--filter", f"name={container_name}"],
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

        # Restart the scheduler — crash recovery runs on startup
        logger.info("Starting scheduler to trigger crash recovery...")
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "start", "scheduler"],
            capture_output=True, text=True, timeout=30,
            cwd="/Users/AI/Projects/codify",
        )

        # Wait for scheduler to boot and run crash recovery
        await asyncio.sleep(10)

        # The task should now be marked as FAILED
        # (crashed task with no container → "Task was running when scheduler restarted")
        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=60,
        )

        # Task should be failed since we killed the container
        assert task["status"] == "failed", (
            f"Orphaned task should be marked failed after crash recovery, "
            f"got: {task['status']}"
        )
        error_msg = task.get("error_message", "")
        assert "scheduler restarted" in error_msg.lower() or "container" in error_msg.lower(), (
            f"Error message should mention restart/container, got: {error_msg}"
        )
        logger.info(f"✅ Crash recovery: orphaned task {task_id} marked failed: {error_msg}")

    async def test_scheduler_resumes_running_container(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """If a worker container is still running during restart, scheduler resumes it.

        Steps:
        1. Create a task with moderate delay
        2. Wait for RUNNING status
        3. Restart scheduler (container still alive)
        4. Task should eventually COMPLETE (scheduler resumes monitoring)
        """
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 10},
        )

        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Resume test task",
                "branch_name": "codify/crash-resume-test",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        # Wait for RUNNING
        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["running"],
            auth_headers=admin_auth_headers,
            timeout=60,
        )
        assert task["status"] == "running"
        logger.info(f"Task {task_id} running, restarting scheduler...")

        # Restart scheduler — container is still alive so it should resume
        compose_file = "backend/tests/mock_integration/docker-compose.mock-test.yml"
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "restart", "scheduler"],
            capture_output=True, text=True, timeout=30,
            cwd="/Users/AI/Projects/codify",
        )

        # Wait for task to complete (scheduler resumes monitoring)
        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", (
            f"Resumed task should complete: {task.get('error_message')}"
        )
        logger.info(f"✅ Scheduler resumed task {task_id} after restart")
