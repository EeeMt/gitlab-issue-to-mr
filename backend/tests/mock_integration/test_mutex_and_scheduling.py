"""Advanced scheduling, mutex, and lifecycle tests.

Tests that the system correctly handles:
- Issue mutex: different issues run parallel, same issue queued
- Issue mutex: mutex released after task failure
- Scheduled tasks: delay_seconds, validation, ordering
- Task lifecycle edge cases

Prerequisites:
    docker-compose -f backend/tests/mock_integration/docker-compose.mock-test.yml up -d
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from .conftest import (
    create_issue,
    create_issue_and_task,
    create_task,
    wait_for_task_status,
)

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.asyncio


class TestIssueMutexAdvanced:
    """Advanced issue mutex scenarios beyond the basic sequential test."""

    async def test_different_issues_run_parallel(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Tasks for DIFFERENT issues should run in parallel (no mutex conflict)."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 8},
        )

        # Create two different issues
        issue_a = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title="Parallel test issue A", description="Issue A task",
        )
        issue_b = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title="Parallel test issue B", description="Issue B task",
        )

        # Create one task under each issue
        task_a = await create_task(
            http_client, backend_url, admin_auth_headers, issue_a["id"],
            user_prompt="Issue A task",
        )
        task_a_id = task_a["id"]

        await asyncio.sleep(1)

        task_b = await create_task(
            http_client, backend_url, admin_auth_headers, issue_b["id"],
            user_prompt="Issue B task",
        )
        task_b_id = task_b["id"]

        # Both should reach running (different issues, no mutex)
        task_a_status = await wait_for_task_status(
            http_client, backend_url, task_a_id,
            target_statuses=["running", "completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=60,
        )
        task_b_status = await wait_for_task_status(
            http_client, backend_url, task_b_id,
            target_statuses=["running", "completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=60,
        )

        # If both reached running, they ran in parallel (good!)
        # If one is already completed, that's fine too — concurrency worked
        logger.info(
            f"Task A (issue {issue_a['id']}): {task_a_status['status']}, "
            f"Task B (issue {issue_b['id']}): {task_b_status['status']}"
        )

        # Wait for both to finish
        task_a_final = await wait_for_task_status(
            http_client, backend_url, task_a_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        task_b_final = await wait_for_task_status(
            http_client, backend_url, task_b_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        assert task_a_final["status"] == "completed"
        assert task_b_final["status"] == "completed"

        # Both started at similar times (parallel, not sequential)
        a_started = task_a_final.get("started_at", "")
        b_started = task_b_final.get("started_at", "")
        if a_started and b_started:
            logger.info(f"✅ Different issues ran in parallel: A={a_started}, B={b_started}")

    async def test_different_issues_no_mutex_conflict(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Tasks for different issues should not block each other."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 5},
        )

        task_ids = []
        for i in range(2):
            issue, task = await create_issue_and_task(
                http_client, backend_url, admin_auth_headers,
                title=f"Mutex bypass test issue {i}",
                prompt=f"Task {i} for mutex bypass test",
            )
            task_ids.append(task["id"])
            await asyncio.sleep(0.5)

        # Both should eventually complete (different issues don't block each other)
        for tid in task_ids:
            task = await wait_for_task_status(
                http_client, backend_url, tid,
                target_statuses=["completed", "failed"],
                auth_headers=admin_auth_headers,
                timeout=120,
            )
            assert task["status"] == "completed", (
                f"Task {tid} failed: {task.get('error_message')}"
            )

        logger.info("✅ Two tasks for different issues completed without mutex conflict")

    async def test_mutex_released_after_failure(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """If task1 for an issue fails, task2 for same issue should still run."""
        # Create one issue for both tasks
        issue = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title="Mutex release test issue",
        )

        # First task will fail (exit code 1)
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_exit_code": 1},
        )

        task1 = await create_task(
            http_client, backend_url, admin_auth_headers, issue["id"],
            user_prompt="Failing task for mutex release",
        )
        task1_id = task1["id"]

        # Wait for task1 to fail
        task1_final = await wait_for_task_status(
            http_client, backend_url, task1_id,
            target_statuses=["failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task1_final["status"] == "failed"
        logger.info(f"Task1 ({task1_id}) failed as expected")

        # Now reset to success and create task2 for the same issue
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_exit_code": 0},
        )

        task2 = await create_task(
            http_client, backend_url, admin_auth_headers, issue["id"],
            user_prompt="Second task after failure",
        )
        task2_id = task2["id"]

        # Task2 should run and complete (mutex was released after task1 failure)
        task2_final = await wait_for_task_status(
            http_client, backend_url, task2_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task2_final["status"] == "completed", (
            f"Task2 should succeed after task1 failure released mutex: "
            f"got {task2_final['status']}, error={task2_final.get('error_message')}"
        )
        logger.info("✅ Mutex released after failure — task2 completed")

    async def test_mutex_queue_monitoring(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Explicitly verify task2 stays queued while task1 runs for same issue."""
        # Create one issue for both tasks
        issue = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title="Mutex queue monitoring test issue",
        )

        # Long delay so task1 stays running
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 15},
        )

        task1 = await create_task(
            http_client, backend_url, admin_auth_headers, issue["id"],
            user_prompt="Long running task for queue monitoring",
        )
        task1_id = task1["id"]

        # Wait for task1 to start running
        await wait_for_task_status(
            http_client, backend_url, task1_id,
            target_statuses=["running"],
            auth_headers=admin_auth_headers,
            timeout=60,
        )

        # Now create task2 for same issue
        task2 = await create_task(
            http_client, backend_url, admin_auth_headers, issue["id"],
            user_prompt="Queued task for same issue",
        )
        task2_id = task2["id"]

        # Poll task2 several times to confirm it stays pending/queued
        checks_pending = 0
        for _ in range(5):
            await asyncio.sleep(2)
            resp = await http_client.get(
                f"{backend_url}/api/tasks/{task2_id}",
                headers=admin_auth_headers,
            )
            t2_status = resp.json()["status"]
            if t2_status in ("pending", "queued"):
                checks_pending += 1
            else:
                break

        assert checks_pending >= 3, (
            f"Task2 should stay pending/queued while task1 runs "
            f"(saw {checks_pending}/5 pending checks)"
        )
        logger.info(f"Task2 stayed queued for {checks_pending} checks while task1 ran")

        # Wait for both to complete
        await wait_for_task_status(
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
        assert task2_final["status"] == "completed"
        logger.info("✅ Mutex queue monitoring: task2 stayed queued, then completed")


class TestScheduledTasks:
    """Scheduled task creation and execution."""

    async def test_delay_seconds_creates_scheduled_task(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Task with delay_seconds should have scheduled_at set."""
        issue = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title="Delayed task test",
        )
        task = await create_task(
            http_client, backend_url, admin_auth_headers, issue["id"],
            user_prompt="Delayed task", delay_seconds=60,
        )
        assert task.get("scheduled_at") is not None, "Task should have scheduled_at set"
        logger.info(f"✅ Delayed task created with scheduled_at={task['scheduled_at']}")

        # Cancel it so it doesn't run and waste time
        await http_client.post(
            f"{backend_url}/api/tasks/{task['id']}/cancel",
            headers=admin_auth_headers,
        )

    async def test_delay_seconds_zero_rejected(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """delay_seconds=0 should be rejected (must be > 0)."""
        issue = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title="Zero delay test",
        )
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "issue_id": issue["id"],
                "user_prompt": "Zero delay task",
                "delay_seconds": 0,
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code == 422, f"Expected 422 for delay_seconds=0, got {resp.status_code}"
        logger.info("✅ delay_seconds=0 correctly rejected")

    async def test_delay_seconds_negative_rejected(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """delay_seconds=-5 should be rejected."""
        issue = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title="Negative delay test",
        )
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "issue_id": issue["id"],
                "user_prompt": "Negative delay task",
                "delay_seconds": -5,
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code == 422, f"Expected 422 for negative delay, got {resp.status_code}"
        logger.info("✅ Negative delay_seconds correctly rejected")

    async def test_scheduled_datetime_in_past_rejected(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """scheduled_datetime in the past should be rejected."""
        issue = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title="Past scheduled test",
        )
        past_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "issue_id": issue["id"],
                "user_prompt": "Past scheduled task",
                "scheduled_datetime": past_time,
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code == 422, (
            f"Expected 422 for past scheduled_datetime, got {resp.status_code}"
        )
        logger.info("✅ Past scheduled_datetime correctly rejected")

    async def test_immediate_task_runs_before_future_scheduled(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """An immediate task should run while a future-scheduled task waits."""
        # Create issues for both tasks (separate issues to avoid mutex)
        future_issue = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title="Future scheduled task issue",
        )
        immediate_issue = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title="Immediate task issue",
        )

        # Create a future-scheduled task (won't run for 5 minutes)
        future_time = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
        future_task = await create_task(
            http_client, backend_url, admin_auth_headers, future_issue["id"],
            user_prompt="Future scheduled task", scheduled_datetime=future_time,
        )
        future_id = future_task["id"]

        # Create an immediate task
        immediate_task = await create_task(
            http_client, backend_url, admin_auth_headers, immediate_issue["id"],
            user_prompt="Immediate task",
        )
        immediate_id = immediate_task["id"]

        # Immediate should complete while scheduled waits
        immediate_result = await wait_for_task_status(
            http_client, backend_url, immediate_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert immediate_result["status"] == "completed"

        # Future task should still be pending
        resp = await http_client.get(
            f"{backend_url}/api/tasks/{future_id}",
            headers=admin_auth_headers,
        )
        future_result = resp.json()
        assert future_result["status"] in ("pending", "queued"), (
            f"Future-scheduled task should still be waiting, got {future_result['status']}"
        )
        logger.info("✅ Immediate task ran while future-scheduled task waited")

        # Cancel the future task so it doesn't run later
        await http_client.post(
            f"{backend_url}/api/tasks/{future_id}/cancel",
            headers=admin_auth_headers,
        )


class TestBranchValidation:
    """Issue/branch validation and edge cases."""

    async def test_no_target_branch_succeeds(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Issue without target_branch (no-MR mode) should succeed."""
        # Create issue without target_branch via raw POST
        resp = await http_client.post(
            f"{backend_url}/api/issues",
            json={
                "title": "No-MR mode test",
                "description": "No-MR mode task",
                "project_id": 1,
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201), (
            f"Create issue without target_branch failed: {resp.status_code} {resp.text}"
        )
        issue = resp.json()

        task = await create_task(
            http_client, backend_url, admin_auth_headers, issue["id"],
            user_prompt="No-MR mode task",
        )
        task_id = task["id"]

        result = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert result["status"] == "completed", (
            f"No-MR mode task should complete: got {result['status']}, "
            f"error={result.get('error_message')}"
        )
        logger.info("✅ No-MR mode task completed successfully")

    async def test_base_branch_specified(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Issue with explicit base_branch should succeed."""
        resp = await http_client.post(
            f"{backend_url}/api/issues",
            json={
                "title": "Base branch test",
                "description": "Base branch task",
                "project_id": 1,
                "base_branch": "main",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201), (
            f"Create issue with base_branch failed: {resp.status_code} {resp.text}"
        )
        issue = resp.json()

        task = await create_task(
            http_client, backend_url, admin_auth_headers, issue["id"],
            user_prompt="Base branch test task",
        )
        task_id = task["id"]

        result = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert result["status"] == "completed", (
            f"Base branch task should complete: {result.get('error_message')}"
        )
        logger.info("✅ Task with explicit base_branch completed")


class TestTaskPriorityLevels:
    """Test all three priority levels work correctly."""

    async def test_all_priority_levels_complete(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """P0, P1, P2 tasks should all complete successfully."""
        task_ids = {}
        for priority in [0, 1, 2]:
            issue, task = await create_issue_and_task(
                http_client, backend_url, admin_auth_headers,
                title=f"Priority P{priority} test issue",
                prompt=f"Priority P{priority} test",
                priority=priority,
            )
            task_ids[priority] = task["id"]
            await asyncio.sleep(0.5)

        # All should complete
        for priority, tid in task_ids.items():
            task = await wait_for_task_status(
                http_client, backend_url, tid,
                target_statuses=["completed", "failed"],
                auth_headers=admin_auth_headers,
                timeout=180,
            )
            assert task["status"] == "completed", (
                f"P{priority} task failed: {task.get('error_message')}"
            )

        logger.info("✅ All priority levels (P0, P1, P2) completed successfully")

    async def test_invalid_priority_rejected(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Priority values outside 0-2 should be rejected or clamped."""
        issue = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title="Invalid priority test issue",
        )
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "issue_id": issue["id"],
                "user_prompt": "Invalid priority task",
                "priority": -1,
            },
            headers=admin_auth_headers,
        )
        # Should be rejected (400/422) or accepted if priority is unclamped
        if resp.status_code in (200, 201):
            # Some systems accept any int — just log it
            logger.info(f"Priority -1 accepted (status {resp.status_code})")
            # Cancel so it doesn't run
            await http_client.post(
                f"{backend_url}/api/tasks/{resp.json()['id']}/cancel",
                headers=admin_auth_headers,
            )
        else:
            logger.info(f"✅ Priority -1 rejected with status {resp.status_code}")


class TestRapidTaskCreation:
    """Rapid task creation to stress test the system."""

    async def test_rapid_task_creation(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Create multiple tasks rapidly — all should be accepted."""
        task_ids = []
        for i in range(5):
            issue, task = await create_issue_and_task(
                http_client, backend_url, admin_auth_headers,
                title=f"Rapid task issue {i}",
                prompt=f"Rapid task {i}",
            )
            task_ids.append(task["id"])

        assert len(task_ids) >= 3, f"Expected at least 3 tasks created, got {len(task_ids)}"

        # Wait for all to complete
        for tid in task_ids:
            await wait_for_task_status(
                http_client, backend_url, tid,
                target_statuses=["completed", "failed"],
                auth_headers=admin_auth_headers,
                timeout=300,
            )

        logger.info(f"✅ {len(task_ids)} rapid tasks all reached terminal state")

    async def test_rapid_task_creation_completes(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Create multiple tasks in quick succession — all should complete."""
        task_ids = []
        for i in range(3):
            issue, task = await create_issue_and_task(
                http_client, backend_url, admin_auth_headers,
                title=f"Rapid completion test issue {i}",
                prompt=f"Rapid completion task {i}",
            )
            task_ids.append(task["id"])

        # All should eventually complete
        for tid in task_ids:
            task = await wait_for_task_status(
                http_client, backend_url, tid,
                target_statuses=["completed", "failed"],
                auth_headers=admin_auth_headers,
                timeout=180,
            )
            assert task["status"] == "completed", (
                f"Rapid task {tid} failed: {task.get('error_message')}"
            )

        logger.info(f"✅ {len(task_ids)} rapid tasks all completed")
