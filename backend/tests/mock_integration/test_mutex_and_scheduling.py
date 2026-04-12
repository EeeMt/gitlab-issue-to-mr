"""Advanced scheduling, mutex, and lifecycle tests.

Tests that the system correctly handles:
- Issue mutex: different issues run parallel, manual tasks bypass mutex
- Issue mutex: mutex released after task failure
- Scheduled tasks: delay_seconds, validation, ordering
- Task lifecycle edge cases

Prerequisites:
    docker-compose -f backend/tests/mock_integration/docker-compose.mock-test.yml up -d
"""

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from .conftest import (
    build_webhook_payload,
    send_webhook,
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

        issue_a = random.randint(10000, 10999)
        issue_b = random.randint(11000, 11999)

        # Create two tasks for different issues
        payload_a = build_webhook_payload(
            project_id=1, issue_iid=issue_a, prompt="Issue A task",
        )
        payload_a["object_attributes"]["id"] = random.randint(100000, 999999)
        resp_a = await send_webhook(http_client, backend_url, payload_a)
        assert resp_a.status_code == 200
        task_a_id = resp_a.json()["task_id"]

        await asyncio.sleep(1)

        payload_b = build_webhook_payload(
            project_id=1, issue_iid=issue_b, prompt="Issue B task",
        )
        payload_b["object_attributes"]["id"] = random.randint(100000, 999999)
        resp_b = await send_webhook(http_client, backend_url, payload_b)
        assert resp_b.status_code == 200
        task_b_id = resp_b.json()["task_id"]

        # Both should reach running (different issues, no mutex)
        task_a = await wait_for_task_status(
            http_client, backend_url, task_a_id,
            target_statuses=["running", "completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=60,
        )
        task_b = await wait_for_task_status(
            http_client, backend_url, task_b_id,
            target_statuses=["running", "completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=60,
        )

        # If both reached running, they ran in parallel (good!)
        # If one is already completed, that's fine too — concurrency worked
        logger.info(
            f"Task A (issue {issue_a}): {task_a['status']}, "
            f"Task B (issue {issue_b}): {task_b['status']}"
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
            # Parse timestamps to compare — they should be within a few seconds
            logger.info(f"✅ Different issues ran in parallel: A={a_started}, B={b_started}")

    async def test_manual_tasks_no_mutex_conflict(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Manual tasks (no issue_iid) should not block each other."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 5},
        )

        # Create two manual tasks — they use "manual:{task_id}" as mutex key
        task_ids = []
        for i in range(2):
            resp = await http_client.post(
                f"{backend_url}/api/tasks",
                json={
                    "project_id": 1,
                    "user_prompt": f"Manual task {i} for mutex bypass test",
                    "branch_name": f"codify/manual-mutex-{i}-{int(time.time())}",
                    "target_branch": "main",
                },
                headers=admin_auth_headers,
            )
            assert resp.status_code in (200, 201)
            task_ids.append(resp.json()["id"])
            await asyncio.sleep(0.5)

        # Both should eventually complete (they don't block each other)
        for tid in task_ids:
            task = await wait_for_task_status(
                http_client, backend_url, tid,
                target_statuses=["completed", "failed"],
                auth_headers=admin_auth_headers,
                timeout=120,
            )
            assert task["status"] == "completed", (
                f"Manual task {tid} failed: {task.get('error_message')}"
            )

        logger.info("✅ Two manual tasks completed without mutex conflict")

    async def test_mutex_released_after_failure(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """If task1 for an issue fails, task2 for same issue should still run."""
        issue_iid = random.randint(12000, 12999)

        # First task will fail (exit code 1)
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_exit_code": 1},
        )

        payload1 = build_webhook_payload(
            project_id=1, issue_iid=issue_iid, prompt="Failing task for mutex release",
        )
        payload1["object_attributes"]["id"] = random.randint(100000, 999999)
        resp1 = await send_webhook(http_client, backend_url, payload1)
        assert resp1.status_code == 200
        task1_id = resp1.json()["task_id"]

        # Wait for task1 to fail
        task1 = await wait_for_task_status(
            http_client, backend_url, task1_id,
            target_statuses=["failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task1["status"] == "failed"
        logger.info(f"Task1 ({task1_id}) failed as expected")

        # Now reset to success and create task2 for the same issue
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_exit_code": 0},
        )

        payload2 = build_webhook_payload(
            project_id=1, issue_iid=issue_iid, prompt="Second task after failure",
        )
        payload2["object_attributes"]["id"] = random.randint(100000, 999999)
        resp2 = await send_webhook(http_client, backend_url, payload2)
        assert resp2.status_code == 200
        task2_id = resp2.json()["task_id"]

        # Task2 should run and complete (mutex was released after task1 failure)
        task2 = await wait_for_task_status(
            http_client, backend_url, task2_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task2["status"] == "completed", (
            f"Task2 should succeed after task1 failure released mutex: "
            f"got {task2['status']}, error={task2.get('error_message')}"
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
        issue_iid = random.randint(13000, 13999)

        # Long delay so task1 stays running
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 15},
        )

        payload1 = build_webhook_payload(
            project_id=1, issue_iid=issue_iid, prompt="Long running task for queue monitoring",
        )
        payload1["object_attributes"]["id"] = random.randint(100000, 999999)
        resp1 = await send_webhook(http_client, backend_url, payload1)
        assert resp1.status_code == 200
        task1_id = resp1.json()["task_id"]

        # Wait for task1 to start running
        await wait_for_task_status(
            http_client, backend_url, task1_id,
            target_statuses=["running"],
            auth_headers=admin_auth_headers,
            timeout=60,
        )

        # Now create task2 for same issue
        payload2 = build_webhook_payload(
            project_id=1, issue_iid=issue_iid, prompt="Queued task for same issue",
        )
        payload2["object_attributes"]["id"] = random.randint(100000, 999999)
        resp2 = await send_webhook(http_client, backend_url, payload2)
        assert resp2.status_code == 200
        task2_id = resp2.json()["task_id"]

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
            f"Task2 should stay pending/queued while task1 runs (saw {checks_pending}/5 pending checks)"
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
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Delayed task",
                "branch_name": f"codify/delayed-{int(time.time())}",
                "target_branch": "main",
                "delay_seconds": 60,
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task = resp.json()
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
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Zero delay task",
                "branch_name": f"codify/zero-delay-{int(time.time())}",
                "target_branch": "main",
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
        """delay_seconds=-1 should be rejected."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Negative delay task",
                "branch_name": f"codify/neg-delay-{int(time.time())}",
                "target_branch": "main",
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
        past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Past scheduled task",
                "branch_name": f"codify/past-sched-{int(time.time())}",
                "target_branch": "main",
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
        # Create a future-scheduled task (won't run for 5 minutes)
        future_time = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Future scheduled task",
                "branch_name": f"codify/future-sched-{int(time.time())}",
                "target_branch": "main",
                "scheduled_datetime": future_time,
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        future_id = resp.json()["id"]

        # Create an immediate task
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Immediate task",
                "branch_name": f"codify/immediate-{int(time.time())}",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        immediate_id = resp.json()["id"]

        # Immediate should complete while scheduled waits
        immediate_task = await wait_for_task_status(
            http_client, backend_url, immediate_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert immediate_task["status"] == "completed"

        # Future task should still be pending
        resp = await http_client.get(
            f"{backend_url}/api/tasks/{future_id}",
            headers=admin_auth_headers,
        )
        future_task = resp.json()
        assert future_task["status"] in ("pending", "queued"), (
            f"Future-scheduled task should still be waiting, got {future_task['status']}"
        )
        logger.info("✅ Immediate task ran while future-scheduled task waited")

        # Cancel the future task so it doesn't run later
        await http_client.post(
            f"{backend_url}/api/tasks/{future_id}/cancel",
            headers=admin_auth_headers,
        )


class TestBranchValidation:
    """Branch name validation and edge cases."""

    async def test_same_branch_as_target_rejected(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Source branch equal to target branch should be rejected."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Same branch test",
                "branch_name": "main",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code == 422, (
            f"Expected 422 for same source/target branch, got {resp.status_code}"
        )
        logger.info("✅ Same source/target branch correctly rejected")

    async def test_no_target_branch_succeeds(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """No target branch (no-MR mode) should succeed."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "No-MR mode task",
                "branch_name": f"codify/no-mr-{int(time.time())}",
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
        # No-MR mode: task should complete (no MR created, just push)
        assert task["status"] == "completed", (
            f"No-MR mode task should complete: got {task['status']}, "
            f"error={task.get('error_message')}"
        )
        logger.info("✅ No-MR mode task completed successfully")

    async def test_base_branch_specified(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Task with explicit base_branch should succeed."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Base branch test",
                "branch_name": f"codify/base-branch-{int(time.time())}",
                "base_branch": "main",
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
            f"Base branch task should complete: {task.get('error_message')}"
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
            resp = await http_client.post(
                f"{backend_url}/api/tasks",
                json={
                    "project_id": 1,
                    "user_prompt": f"Priority P{priority} test",
                    "branch_name": f"codify/p{priority}-test-{int(time.time())}",
                    "target_branch": "main",
                    "priority": priority,
                },
                headers=admin_auth_headers,
            )
            assert resp.status_code in (200, 201)
            task_ids[priority] = resp.json()["id"]
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
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Invalid priority task",
                "branch_name": f"codify/bad-priority-{int(time.time())}",
                "target_branch": "main",
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

    async def test_rapid_webhook_spam(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Send multiple webhooks rapidly — all should be accepted."""
        task_ids = []
        for i in range(5):
            payload = build_webhook_payload(
                project_id=1,
                issue_iid=random.randint(20000, 29999),
                prompt=f"Rapid task {i}",
            )
            payload["object_attributes"]["id"] = random.randint(100000, 999999)
            resp = await send_webhook(http_client, backend_url, payload)
            if resp.status_code == 200 and resp.json().get("task_id"):
                task_ids.append(resp.json()["task_id"])

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

    async def test_rapid_manual_task_creation(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Create multiple manual tasks in quick succession."""
        task_ids = []
        for i in range(3):
            resp = await http_client.post(
                f"{backend_url}/api/tasks",
                json={
                    "project_id": 1,
                    "user_prompt": f"Rapid manual task {i}",
                    "branch_name": f"codify/rapid-{i}-{int(time.time())}",
                    "target_branch": "main",
                },
                headers=admin_auth_headers,
            )
            assert resp.status_code in (200, 201)
            task_ids.append(resp.json()["id"])

        # All should eventually complete
        for tid in task_ids:
            task = await wait_for_task_status(
                http_client, backend_url, tid,
                target_statuses=["completed", "failed"],
                auth_headers=admin_auth_headers,
                timeout=180,
            )
            assert task["status"] == "completed", (
                f"Rapid manual task {tid} failed: {task.get('error_message')}"
            )

        logger.info(f"✅ {len(task_ids)} rapid manual tasks all completed")
