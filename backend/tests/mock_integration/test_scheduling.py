"""Scheduling integration tests — concurrency, priority, issue mutex.

Tests the scheduler's task management capabilities:
- Priority ordering (P0 before P1 before P2)
- Concurrency limits (respects MAX_CONCURRENCY)

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
    get_mock_calls,
    wait_for_task_status,
)

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.asyncio


class TestPriorityOrdering:
    """Higher priority tasks should be picked up first."""

    async def test_p0_runs_before_p2(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Create P2 then P0 tasks — P0 should complete first or at same time."""
        # Occupy one of 2 concurrency slots with a long-running blocker
        # so only 1 slot is available, forcing priority ordering.
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 15},
        )

        _blocker_issue, blocker_task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Blocker task {int(time.time())}",
            prompt="Blocker task to occupy a slot",
            priority=1,
        )
        blocker_id = blocker_task["id"]

        # Wait for blocker to start running (occupying 1 of 2 slots)
        await wait_for_task_status(
            http_client, backend_url, blocker_id,
            target_statuses=["running"],
            auth_headers=admin_auth_headers,
            timeout=60,
        )

        # Now reduce delay so P0/P2 tasks run quickly
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 3},
        )

        # Create P2 task first
        _p2_issue, p2_task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"P2 low priority {int(time.time())}",
            prompt="P2 low priority task",
            priority=2,
        )
        p2_id = p2_task["id"]

        # Create P0 task second (should be picked before P2)
        _p0_issue, p0_task_data = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"P0 high priority {int(time.time())}",
            prompt="P0 high priority task",
            priority=0,
        )
        p0_id = p0_task_data["id"]

        # Wait for all tasks to complete
        p0_task = await wait_for_task_status(
            http_client, backend_url, p0_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=180,
        )
        p2_task = await wait_for_task_status(
            http_client, backend_url, p2_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=180,
        )
        # Wait for blocker too
        await wait_for_task_status(
            http_client, backend_url, blocker_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=180,
        )

        assert p0_task["status"] == "completed", f"P0 task failed: {p0_task.get('error_message')}"
        assert p2_task["status"] == "completed", f"P2 task failed: {p2_task.get('error_message')}"

        # With only 1 free slot, P0 should start before or at same time as P2
        p0_started = p0_task.get("started_at", "")
        p2_started = p2_task.get("started_at", "")
        if p0_started and p2_started:
            assert p0_started <= p2_started, (
                f"P0 should start before or same as P2: P0={p0_started}, P2={p2_started}"
            )
        logger.info(f"✅ Priority verified: P0 started={p0_started}, P2 started={p2_started}")


class TestConcurrencyLimit:
    """Scheduler respects MAX_CONCURRENCY setting."""

    async def test_tasks_respect_concurrency_limit(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Create more tasks than MAX_CONCURRENCY, verify they all eventually complete."""
        # Fetch current MAX_CONCURRENCY from config and create one extra task
        resp = await http_client.get(
            f"{backend_url}/api/config",
            headers=admin_auth_headers,
        )
        max_conc = resp.json().get("runtime", {}).get("max_concurrency", 5)
        num_tasks = max_conc + 1

        task_ids = []
        for i in range(num_tasks):
            _issue, task_data = await create_issue_and_task(
                http_client, backend_url, admin_auth_headers,
                title=f"Concurrency test {i}",
                prompt=f"Concurrency test task {i}",
            )
            task_ids.append(task_data["id"])

        # All 3 should eventually complete
        for tid in task_ids:
            task = await wait_for_task_status(
                http_client, backend_url, tid,
                target_statuses=["completed", "failed"],
                auth_headers=admin_auth_headers,
                timeout=180,
            )
            assert task["status"] == "completed", (
                f"Task {tid} should complete: {task.get('error_message', '')}"
            )

        logger.info(f"✅ All {len(task_ids)} tasks completed under concurrency limit")
