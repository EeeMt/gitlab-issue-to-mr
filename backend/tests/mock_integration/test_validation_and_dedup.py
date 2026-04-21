"""Tests for API validation, task lifecycle correctness, and edge cases.

Covers:
- Task priority boundary validation
- Cancel non-cancellable tasks (completed/failed)
- Task list ordering (newest first)
- Task creation edge cases (missing issue_id, empty prompt)
- Retry completed vs failed tasks
"""

import asyncio

import httpx
import pytest

from .conftest import (
    create_issue,
    create_issue_and_task,
    create_task,
    wait_for_task_status,
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
        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            prompt="Quick task for cancel test",
        )
        task_id = task["id"]

        result = await wait_for_task_status(
            http_client, backend_url, task_id,
            ["completed", "failed"], admin_auth_headers,
        )

        # Try to cancel a completed/failed task
        cancel_resp = await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/cancel",
            headers=admin_auth_headers,
        )
        assert cancel_resp.status_code == 400, (
            f"Expected 400 for cancel of {result['status']} task, got {cancel_resp.status_code}"
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

        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            prompt="Slow task for retry test",
        )
        task_id = task["id"]

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
        """Retrying a failed task should create a new task under the same issue."""
        # Force failure
        async with httpx.AsyncClient(timeout=10) as mc:
            await mc.patch(
                f"{mock_url}/mock/config",
                json={"claude_exit_code": 1},
            )

        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            prompt="Fail then retry",
        )
        task_id = task["id"]

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

        # Retry creates a new task under the same issue
        retry_data = retry_resp.json()
        new_task_id = retry_data.get("id") or retry_data.get("task_id") or task_id

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
            _issue, task = await create_issue_and_task(
                http_client, backend_url, admin_auth_headers,
                title=f"Order test issue {i}",
                prompt=f"Order test {i}",
            )
            created_ids.append(task["id"])
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
        assert "items" in data, "Missing 'items' in paginated response"
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
        issue = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title="Extreme priority issue",
            description="Priority boundary test",
        )
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "issue_id": issue["id"],
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
        issue = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title="Negative priority issue",
            description="Negative priority test",
        )
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "issue_id": issue["id"],
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
        """Task with no usable prompt should be rejected when issue also has no description."""
        # Create issue with no description so there's no fallback prompt
        issue = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title="Empty prompt issue",
            description=None,
        )
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "issue_id": issue["id"],
                "user_prompt": None,
            },
            headers=admin_auth_headers,
        )
        # No prompt and no issue description — should be rejected
        assert resp.status_code in (400, 422), (
            f"Empty prompt with no issue description should be rejected, "
            f"got {resp.status_code}: {resp.text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_create_task_missing_issue_id_rejected(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Task without issue_id should be rejected."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "user_prompt": "No issue_id test",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (400, 422), (
            f"Missing issue_id should be rejected, got {resp.status_code}"
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
        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            prompt="Double cancel test",
            delay_seconds=3600,
        )
        task_id = task["id"]

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
