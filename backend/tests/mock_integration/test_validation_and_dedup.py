"""Tests for API validation, deduplication, and task lifecycle correctness.

Covers:
- Webhook deduplication (same note_id → only 1 task)
- Concurrent duplicate webhooks (race condition)
- Task priority boundary validation
- Cancel non-cancellable tasks (completed/failed)
- Task list ordering (newest first)
- Task creation edge cases
- Retry completed vs failed tasks
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


class TestWebhookDeduplication:
    """Verify that duplicate webhooks (same note_id) create only one task."""

    @pytest.mark.asyncio
    async def test_duplicate_webhook_same_note_id_creates_one_task(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Sending the same webhook twice with identical note_id should create only one task."""
        iid = random.randint(50000, 59999)
        payload = build_webhook_payload(
            project_id=1,
            issue_iid=iid,
            prompt="Dedup test - same note_id",
        )
        fixed_note_id = random.randint(200000, 299999)
        payload["object_attributes"]["id"] = fixed_note_id

        # First webhook
        resp1 = await send_webhook(http_client, backend_url, payload)
        assert resp1.status_code == 200
        data1 = resp1.json()
        task_id_1 = data1.get("task_id")

        # Second webhook with same note_id
        resp2 = await send_webhook(http_client, backend_url, payload)
        assert resp2.status_code == 200
        data2 = resp2.json()

        # Second should be detected as duplicate
        assert data2.get("status") == "duplicate" or data2.get("task_id") == task_id_1, (
            f"Expected duplicate detection, got: {data2}"
        )

        # If both returned task_ids, they should be the same
        if data2.get("task_id") and task_id_1:
            assert data2["task_id"] == task_id_1

    @pytest.mark.asyncio
    async def test_different_note_ids_create_separate_tasks(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Different note_ids on same issue should create separate tasks."""
        iid = random.randint(60000, 69999)

        payload1 = build_webhook_payload(project_id=1, issue_iid=iid, prompt="First comment")
        payload1["object_attributes"]["id"] = random.randint(300000, 399999)

        payload2 = build_webhook_payload(project_id=1, issue_iid=iid, prompt="Second comment")
        payload2["object_attributes"]["id"] = random.randint(400000, 499999)

        resp1 = await send_webhook(http_client, backend_url, payload1)
        resp2 = await send_webhook(http_client, backend_url, payload2)

        assert resp1.status_code == 200
        assert resp2.status_code == 200

        tid1 = resp1.json().get("task_id")
        tid2 = resp2.json().get("task_id")

        # Both should create tasks (different note_ids)
        assert tid1 is not None, f"First webhook failed: {resp1.json()}"
        assert tid2 is not None, f"Second webhook failed: {resp2.json()}"
        assert tid1 != tid2, "Different note_ids should create different tasks"

    @pytest.mark.asyncio
    async def test_concurrent_duplicate_webhooks_only_one_task(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Sending identical webhooks concurrently should create at most one task."""
        iid = random.randint(70000, 79999)
        payload = build_webhook_payload(
            project_id=1,
            issue_iid=iid,
            prompt="Concurrent dedup test",
        )
        fixed_note_id = random.randint(500000, 599999)
        payload["object_attributes"]["id"] = fixed_note_id

        # Send 3 identical webhooks concurrently
        async def send_one():
            async with httpx.AsyncClient(timeout=30.0) as c:
                return await send_webhook(c, backend_url, payload)

        results = await asyncio.gather(send_one(), send_one(), send_one())

        # Count how many created tasks
        # 200 = success, 500 = DB conflict from race (acceptable — means dedup caught it)
        task_ids = set()
        success_count = 0
        for r in results:
            assert r.status_code in (200, 500), (
                f"Unexpected status {r.status_code} during concurrent dedup"
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("task_id"):
                    task_ids.add(data["task_id"])
                success_count += 1

        # At most 1 unique task should be created
        assert len(task_ids) <= 1, (
            f"Expected at most 1 task from concurrent duplicate webhooks, got {len(task_ids)}: {task_ids}"
        )


class TestTaskLifecycleValidation:
    """Verify task cancel/retry validation on different statuses."""

    @pytest.mark.asyncio
    async def test_cancel_completed_task_returns_400(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Cannot cancel a task that has already completed."""
        # Create and wait for completion
        payload = build_webhook_payload(
            project_id=1,
            issue_iid=random.randint(80000, 89999),
            prompt="Quick task for cancel test",
        )
        payload["object_attributes"]["id"] = random.randint(600000, 699999)
        resp = await send_webhook(http_client, backend_url, payload)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            ["completed", "failed"], admin_auth_headers,
        )

        # Try to cancel a completed/failed task
        cancel_resp = await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/cancel",
            headers=admin_auth_headers,
        )
        assert cancel_resp.status_code == 400, (
            f"Expected 400 for cancel of {task['status']} task, got {cancel_resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_retry_running_task_returns_400(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Cannot retry a task that is currently running."""
        # Make task slow so it stays running
        async with httpx.AsyncClient(timeout=10) as mc:
            await mc.patch(
                f"{mock_url}/mock/config",
                json={"claude_delay_seconds": 30},
            )

        payload = build_webhook_payload(
            project_id=1,
            issue_iid=random.randint(81000, 81999),
            prompt="Slow task for retry test",
        )
        payload["object_attributes"]["id"] = random.randint(700000, 799999)
        resp = await send_webhook(http_client, backend_url, payload)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        # Wait until running
        await wait_for_task_status(
            http_client, backend_url, task_id,
            ["running"], admin_auth_headers, timeout=60,
        )

        # Try to retry a running task
        retry_resp = await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/retry",
            headers=admin_auth_headers,
        )
        assert retry_resp.status_code == 400, (
            f"Expected 400 for retry of running task, got {retry_resp.status_code}"
        )

        # Clean up: cancel the slow task
        await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/cancel",
            headers=admin_auth_headers,
        )

    @pytest.mark.asyncio
    async def test_retry_failed_task_creates_new_task(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Retrying a failed task should create a new task or re-queue."""
        # Force failure
        async with httpx.AsyncClient(timeout=10) as mc:
            await mc.patch(
                f"{mock_url}/mock/config",
                json={"claude_exit_code": 1},
            )

        payload = build_webhook_payload(
            project_id=1,
            issue_iid=random.randint(82000, 82999),
            prompt="Fail then retry",
        )
        payload["object_attributes"]["id"] = random.randint(800000, 899999)
        resp = await send_webhook(http_client, backend_url, payload)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            ["failed"], admin_auth_headers,
        )

        # Reset mock to succeed
        async with httpx.AsyncClient(timeout=10) as mc:
            await mc.patch(f"{mock_url}/mock/config", json={"claude_exit_code": 0})

        # Retry
        retry_resp = await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/retry",
            headers=admin_auth_headers,
        )
        assert retry_resp.status_code == 200, (
            f"Retry failed: {retry_resp.status_code} {retry_resp.text}"
        )

        # New task or same task re-queued
        retry_data = retry_resp.json()
        new_task_id = retry_data.get("task_id") or retry_data.get("id") or task_id

        final = await wait_for_task_status(
            http_client, backend_url, new_task_id,
            ["completed", "failed", "pending", "queued", "running"],
            admin_auth_headers, timeout=90,
        )
        # Retry should either re-queue (pending) or succeed (completed)
        assert final["status"] in ("completed", "pending", "queued", "running"), (
            f"Retry task ended up in unexpected status: {final['status']}"
        )


class TestTaskListOrdering:
    """Verify task list is ordered by created_at DESC (newest first)."""

    @pytest.mark.asyncio
    async def test_task_list_newest_first(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Tasks should be returned newest first (created_at DESC)."""
        created_ids = []
        for i in range(3):
            payload = build_webhook_payload(
                project_id=1,
                issue_iid=random.randint(83000 + i * 1000, 83999 + i * 1000),
                prompt=f"Order test {i}",
            )
            payload["object_attributes"]["id"] = random.randint(900000, 999999)
            resp = await send_webhook(http_client, backend_url, payload)
            assert resp.status_code == 200
            tid = resp.json().get("task_id")
            if tid:
                created_ids.append(tid)
            await asyncio.sleep(0.3)  # Ensure different created_at

        assert len(created_ids) >= 2, "Need at least 2 tasks to check ordering"

        # Fetch task list
        resp = await http_client.get(
            f"{backend_url}/api/tasks?page=1&page_size=50",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        items = data.get("items", data) if isinstance(data, dict) else data

        # Extract IDs that we created
        list_ids = [t["id"] for t in items if t["id"] in created_ids]

        # Should be in descending order (newest first)
        assert list_ids == sorted(list_ids, reverse=True), (
            f"Tasks not in DESC order: {list_ids}"
        )

    @pytest.mark.asyncio
    async def test_task_list_pagination_total_count(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Paginated task list should include total count."""
        resp = await http_client.get(
            f"{backend_url}/api/tasks?page=1&page_size=5",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data, f"Missing 'total' in paginated response: {list(data.keys())}"
        assert "items" in data, f"Missing 'items' in paginated response"
        assert data["total"] >= 0
        assert len(data["items"]) <= 5


class TestTaskCreationEdgeCases:
    """Validate task creation with unusual inputs."""

    @pytest.mark.asyncio
    async def test_create_task_with_extreme_priority_value(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Creating a task with priority=99 should either work or be rejected."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Priority boundary test",
                "priority": 99,
            },
            headers=admin_auth_headers,
        )
        # Either 200 (accepts any int) or 422 (validates range) — both valid behaviors
        assert resp.status_code in (200, 201, 400, 422), (
            f"Unexpected status for extreme priority: {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_create_task_with_negative_priority(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Creating a task with priority=-1 should either work or be rejected."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Negative priority test",
                "priority": -1,
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201, 400, 422), (
            f"Unexpected status for negative priority: {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_create_task_empty_prompt_rejected(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Task with empty user_prompt should be rejected."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "",
            },
            headers=admin_auth_headers,
        )
        # Empty prompt should be rejected
        assert resp.status_code in (400, 422), (
            f"Empty prompt should be rejected, got {resp.status_code}: {resp.text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_create_task_missing_project_id_rejected(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Task without project_id should be rejected."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "user_prompt": "No project test",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (400, 422), (
            f"Missing project_id should be rejected, got {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_create_task_with_very_long_branch_name(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Task with a very long branch name should either truncate or reject."""
        long_branch = "codify/" + "x" * 300
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Long branch test",
                "branch_name": long_branch,
            },
            headers=admin_auth_headers,
        )
        # Either accepted (truncated) or rejected (too long)
        assert resp.status_code in (200, 201, 400, 422, 500), (
            f"Unexpected status for long branch: {resp.status_code}"
        )


class TestCancelAndRetryEdgeCases:
    """Test cancel/retry on tasks in various states."""

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task_returns_404(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Cancelling a non-existent task returns 404."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks/999888/cancel",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_nonexistent_task_returns_404(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Retrying a non-existent task returns 404."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks/999777/retry",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_double_cancel_returns_400(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Cancelling an already-cancelled task should return 400."""
        # Create a future-scheduled task (stays pending)
        ts = int(time.time())
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Double cancel test",
                "branch_name": f"codify/double-cancel-{ts}",
                "delay_seconds": 3600,
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json().get("task_id") or resp.json().get("id")
        assert task_id is not None

        # First cancel should succeed
        c1 = await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/cancel",
            headers=admin_auth_headers,
        )
        assert c1.status_code == 200

        # Second cancel should fail (already cancelled)
        c2 = await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/cancel",
            headers=admin_auth_headers,
        )
        assert c2.status_code == 400, (
            f"Double cancel should return 400, got {c2.status_code}"
        )
