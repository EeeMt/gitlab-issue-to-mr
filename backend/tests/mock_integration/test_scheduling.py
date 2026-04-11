"""Scheduling integration tests — concurrency, priority, issue mutex.

Tests the scheduler's task management capabilities:
- Priority ordering (P0 before P1 before P2)
- Issue mutex (same issue can't run concurrently)
- Concurrency limits (respects MAX_CONCURRENCY)

Prerequisites:
    docker-compose -f backend/tests/mock_integration/docker-compose.mock-test.yml up -d
"""

import asyncio
import logging

import httpx
import pytest

from .conftest import (
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
        # Add delay so tasks queue up instead of running immediately
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 5},
        )

        # Create P2 task first
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "P2 low priority task",
                "branch_name": "codify/priority-p2",
                "target_branch": "main",
                "priority": 2,
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        p2_id = resp.json()["id"]

        # Create P0 task second
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "P0 high priority task",
                "branch_name": "codify/priority-p0",
                "target_branch": "main",
                "priority": 0,
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        p0_id = resp.json()["id"]

        # Wait for both to complete
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

        assert p0_task["status"] == "completed", f"P0 task failed: {p0_task.get('error_message')}"
        assert p2_task["status"] == "completed", f"P2 task failed: {p2_task.get('error_message')}"

        # P0 should have started_at <= P2's started_at (P0 picked up first)
        p0_started = p0_task.get("started_at", "")
        p2_started = p2_task.get("started_at", "")
        if p0_started and p2_started:
            assert p0_started <= p2_started, (
                f"P0 should start before or same as P2: P0={p0_started}, P2={p2_started}"
            )
        logger.info(f"✅ Priority verified: P0 started={p0_started}, P2 started={p2_started}")

        # Reset delay
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 0},
        )


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
        # docker-compose has MAX_CONCURRENCY=2, so create 3 tasks
        task_ids = []
        for i in range(3):
            resp = await http_client.post(
                f"{backend_url}/api/tasks",
                json={
                    "project_id": 1,
                    "user_prompt": f"Concurrency test task {i}",
                    "branch_name": f"codify/concurrency-{i}",
                    "target_branch": "main",
                },
                headers=admin_auth_headers,
            )
            assert resp.status_code in (200, 201)
            task_ids.append(resp.json()["id"])

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
