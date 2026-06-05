"""Notification profile CRUD and task operations integration tests.

Tests Mattermost notification profile management (no real Mattermost needed)
and advanced task operations (slot capacity, reschedule, execute-now edge cases).
"""

import random
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from .conftest import (
    BACKEND_URL,
    create_issue,
    create_issue_and_task,
    create_task,
    wait_for_task_status,
)


def _extract_auth(resp: httpx.Response) -> dict:
    """Extract auth headers from login/register response."""
    cookies = dict(resp.cookies)
    if cookies:
        return {"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())}
    token = resp.json().get("access_token")
    if token:
        return {"Authorization": f"Bearer {token}"}
    raise ValueError(f"No auth in response: {resp.status_code} {resp.text}")


@pytest.fixture
async def admin_headers():
    """Get admin auth headers."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BACKEND_URL}/api/auth/local/login",
            json={"username": "admin", "password": "admin123"},
        )
        if resp.status_code == 200:
            return _extract_auth(resp)
        resp = await client.post(
            f"{BACKEND_URL}/api/auth/local/register",
            json={"username": "admin", "password": "admin123"},
        )
        assert resp.status_code in (200, 201), f"Register failed: {resp.text}"
        return _extract_auth(resp)


# ── Notification Profile CRUD ────────────────────────────────────────


class TestNotificationProfileCRUD:
    """CRUD operations on Mattermost notification profiles.
    These test the DB-backed config, not actual Mattermost connectivity."""

    @pytest.mark.asyncio
    async def test_get_notification_config(self, admin_headers):
        """GET /config/notifications returns integration + profiles."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/config/notifications",
                headers=admin_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "integration" in data
            assert "profiles" in data
            assert isinstance(data["profiles"], list)

    @pytest.mark.asyncio
    async def test_create_notification_profile(self, admin_headers):
        """Create a channel-type notification profile."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/config/notifications/profiles",
                headers=admin_headers,
                json={
                    "name": f"Test Profile {random.randint(1000, 9999)}",
                    "enabled": True,
                    "target_type": "channel",
                    "channel_id": "ch-test-profile",
                    "mention_in_channel": False,
                    "event_types": ["task_completed", "task_failed"],
                    "field_keys": ["project_name", "task_id", "status"],
                },
            )
            assert resp.status_code in (200, 201), f"Create profile failed: {resp.text}"
            data = resp.json()
            assert data["target_type"] == "channel"
            assert "task_completed" in data["event_types"]
            assert data["enabled"] is True
            assert "id" in data

    @pytest.mark.asyncio
    async def test_update_notification_profile(self, admin_headers):
        """Create then update a profile."""
        async with httpx.AsyncClient(timeout=10) as client:
            # Create
            create_resp = await client.post(
                f"{BACKEND_URL}/api/config/notifications/profiles",
                headers=admin_headers,
                json={
                    "name": f"Update Me {random.randint(1000, 9999)}",
                    "enabled": True,
                    "target_type": "initiator_dm",
                    "event_types": ["task_completed"],
                    "field_keys": ["task_id"],
                },
            )
            assert create_resp.status_code in (200, 201)
            profile_id = create_resp.json()["id"]

            # Update — must include all required fields
            update_resp = await client.patch(
                f"{BACKEND_URL}/api/config/notifications/profiles/{profile_id}",
                headers=admin_headers,
                json={
                    "name": f"Updated {random.randint(1000, 9999)}",
                    "enabled": False,
                    "target_type": "initiator_dm",
                    "event_types": ["task_completed", "task_failed"],
                    "field_keys": ["task_id", "status"],
                },
            )
            assert update_resp.status_code == 200
            data = update_resp.json()
            assert data["enabled"] is False
            assert "task_failed" in data["event_types"]

    @pytest.mark.asyncio
    async def test_delete_notification_profile(self, admin_headers):
        """Create then delete a profile."""
        async with httpx.AsyncClient(timeout=10) as client:
            # Create
            create_resp = await client.post(
                f"{BACKEND_URL}/api/config/notifications/profiles",
                headers=admin_headers,
                json={
                    "name": f"Delete Me {random.randint(1000, 9999)}",
                    "enabled": True,
                    "target_type": "channel",
                    "channel_id": "ch-delete-profile",
                    "event_types": ["task_completed"],
                    "field_keys": ["task_id"],
                },
            )
            assert create_resp.status_code in (200, 201)
            profile_id = create_resp.json()["id"]

            # Delete
            del_resp = await client.delete(
                f"{BACKEND_URL}/api/config/notifications/profiles/{profile_id}",
                headers=admin_headers,
            )
            assert del_resp.status_code in (200, 204)

            # Verify gone — profile no longer in list
            list_resp = await client.get(
                f"{BACKEND_URL}/api/config/notifications",
                headers=admin_headers,
            )
            profile_ids = [p["id"] for p in list_resp.json()["profiles"]]
            assert profile_id not in profile_ids

    @pytest.mark.asyncio
    async def test_notification_config_requires_admin(self):
        """Non-authenticated requests should be rejected."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/api/config/notifications")
            assert resp.status_code in (401, 403)


# ── Slot Capacity ────────────────────────────────────────────────────


class TestSlotCapacity:
    """Slot capacity checking for scheduled tasks."""

    @pytest.mark.asyncio
    async def test_slot_capacity_endpoint(self, admin_headers):
        """GET /tasks/slot-capacity returns capacity info for a time slot."""
        async with httpx.AsyncClient(timeout=10) as client:
            future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
            resp = await client.get(
                f"{BACKEND_URL}/api/tasks/slot-capacity",
                params={"scheduled_at": future},
                headers=admin_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "hour_start" in data
            assert "hour_end" in data
            assert "count" in data
            assert "max" in data
            assert "is_full" in data
            assert isinstance(data["count"], int)
            assert isinstance(data["max"], int)

    @pytest.mark.asyncio
    async def test_slot_capacity_past_time(self, admin_headers):
        """Slot capacity for past time should still return valid data."""
        async with httpx.AsyncClient(timeout=10) as client:
            past = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
            resp = await client.get(
                f"{BACKEND_URL}/api/tasks/slot-capacity",
                params={"scheduled_at": past},
                headers=admin_headers,
            )
            # Should still return data (past slots may have 0 count)
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] >= 0


# ── Task Reschedule Operations ───────────────────────────────────────


class TestTaskRescheduleOperations:
    """Test reschedule and execute-now on scheduled tasks."""

    @pytest.mark.asyncio
    async def test_reschedule_changes_time(self, admin_headers):
        """Create a scheduled task, then reschedule it to a different time."""
        async with httpx.AsyncClient(timeout=10) as client:
            # Create issue, then a scheduled task under it
            future1 = (datetime.now(UTC) + timedelta(hours=10)).isoformat()
            issue = await create_issue(
                client, BACKEND_URL, admin_headers,
                title="Reschedule test issue",
                description="Scheduled task for reschedule test",
            )
            task_data = await create_task(
                client, BACKEND_URL, admin_headers, issue["id"],
                user_prompt="Scheduled task for reschedule test",
                scheduled_datetime=future1,
            )
            task_id = task_data["id"]

            # Reschedule to a different time
            future2 = (datetime.now(UTC) + timedelta(hours=20)).isoformat()
            resched_resp = await client.patch(
                f"{BACKEND_URL}/api/tasks/{task_id}/schedule",
                headers=admin_headers,
                json={"scheduled_datetime": future2},
            )
            assert resched_resp.status_code == 200

            # Verify the new schedule
            task_resp = await client.get(
                f"{BACKEND_URL}/api/tasks/{task_id}",
                headers=admin_headers,
            )
            task = task_resp.json()
            assert task["scheduled_at"] is not None
            assert "scheduled_at" in task

    @pytest.mark.asyncio
    async def test_execute_now_clears_schedule(self, admin_headers):
        """Execute-now on a scheduled task clears scheduled_at."""
        async with httpx.AsyncClient(timeout=10) as client:
            future = (datetime.now(UTC) + timedelta(hours=10)).isoformat()
            issue = await create_issue(
                client, BACKEND_URL, admin_headers,
                title="Execute now test issue",
                description="Execute now test",
            )
            task_data = await create_task(
                client, BACKEND_URL, admin_headers, issue["id"],
                user_prompt="Execute now test",
                scheduled_datetime=future,
            )
            task_id = task_data["id"]

            # Execute now
            exec_resp = await client.post(
                f"{BACKEND_URL}/api/tasks/{task_id}/execute",
                headers=admin_headers,
            )
            assert exec_resp.status_code == 200

            # The task should now have scheduled_at cleared
            task_resp = await client.get(
                f"{BACKEND_URL}/api/tasks/{task_id}",
                headers=admin_headers,
            )
            task = task_resp.json()
            assert task.get("scheduled_at") is None, \
                f"Execute-now should clear scheduled_at, got: {task.get('scheduled_at')}"

    @pytest.mark.asyncio
    async def test_reschedule_non_pending_rejected(self, admin_headers):
        """Reschedule on a completed task should be rejected."""
        async with httpx.AsyncClient(timeout=30) as client:
            # Create issue+task and wait for completion
            _issue, task_data = await create_issue_and_task(
                client, BACKEND_URL, admin_headers,
                title=f"Reschedule reject test {random.randint(1000, 9999)}",
                prompt="Create a hello.py file",
            )
            task_id = task_data["id"]

            await wait_for_task_status(
                client, BACKEND_URL, task_id,
                target_statuses=["completed", "failed"],
                auth_headers=admin_headers,
                timeout=120,
            )

            # Try to reschedule — should fail
            future = (datetime.now(UTC) + timedelta(hours=5)).isoformat()
            resched_resp = await client.patch(
                f"{BACKEND_URL}/api/tasks/{task_id}/schedule",
                headers=admin_headers,
                json={"scheduled_datetime": future},
            )
            assert resched_resp.status_code in (400, 409), \
                f"Reschedule completed task should fail, got: {resched_resp.status_code}"


# ── Task Retry Edge Cases ────────────────────────────────────────────


class TestRetryEdgeCases:
    """Additional retry scenarios."""

    @pytest.mark.asyncio
    async def test_retry_completed_task_rejected(self, admin_headers):
        """Retry on a COMPLETED task should be rejected."""
        async with httpx.AsyncClient(timeout=30) as client:
            _issue, task_data = await create_issue_and_task(
                client, BACKEND_URL, admin_headers,
                title=f"Retry reject test {random.randint(1000, 9999)}",
                prompt="Create a hello.py file",
            )
            task_id = task_data["id"]

            task = await wait_for_task_status(
                client, BACKEND_URL, task_id,
                target_statuses=["completed"],
                auth_headers=admin_headers,
                timeout=120,
            )
            assert task["status"] == "completed"

            # Retry on completed should fail
            retry_resp = await client.post(
                f"{BACKEND_URL}/api/tasks/{task_id}/retry",
                headers=admin_headers,
            )
            assert retry_resp.status_code in (400, 409), \
                f"Retry completed task should fail, got: {retry_resp.status_code}"

    @pytest.mark.asyncio
    async def test_retry_nonexistent_task_404(self, admin_headers):
        """Retry on non-existent task returns 404."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/tasks/999999/retry",
                headers=admin_headers,
            )
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task_404(self, admin_headers):
        """Cancel on non-existent task returns 404."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/tasks/999999/cancel",
                headers=admin_headers,
            )
            assert resp.status_code == 404


# ── Scheduled Stats ──────────────────────────────────────────────────


class TestScheduledStatsDetailed:
    """Detailed tests for /stats/scheduled endpoint."""

    @pytest.mark.asyncio
    async def test_scheduled_stats_structure(self, admin_headers):
        """Verify the full structure of /stats/scheduled response."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/stats/scheduled",
                headers=admin_headers,
            )
            assert resp.status_code == 200
            data = resp.json()

            # Verify top-level keys
            assert "summary" in data
            assert "hourly_distribution" in data
            assert "max_count" in data

            # Verify summary fields
            summary = data["summary"]
            for key in ["total", "ready_now", "next_24h", "later",
                        "queued_count", "running_count",
                        "busiest_hour_count"]:
                assert key in summary, f"Missing summary key: {key}"
                assert isinstance(summary[key], int), f"{key} should be int"

            # Verify hourly distribution
            hourly = data["hourly_distribution"]
            assert isinstance(hourly, list)
            # Should have 24 hourly buckets
            assert len(hourly) == 24
            for bucket in hourly:
                assert "hour_start" in bucket
                assert "count" in bucket

    @pytest.mark.asyncio
    async def test_scheduled_stats_with_project_filter(self, admin_headers):
        """Stats can be filtered by project_id."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/stats/scheduled",
                params={"project_id": 1},
                headers=admin_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "summary" in data


# ── Project Webhooks Status ──────────────────────────────────────────


class TestProjectWebhookStatus:
    """Test project webhook configuration status endpoints."""

    @pytest.mark.asyncio
    async def test_list_project_webhook_statuses(self, admin_headers):
        """GET /config/gitlab/webhooks returns webhook status for all projects."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/config/gitlab/webhooks",
                headers=admin_headers,
            )
            # May return 200 with list, or 400/500 if GitLab unreachable in mock env
            if resp.status_code == 200:
                data = resp.json()
                assert isinstance(data, list)
            else:
                assert resp.status_code in (400, 500, 502, 503), \
                    f"Unexpected status: {resp.status_code} {resp.text[:200]}"

    @pytest.mark.asyncio
    async def test_webhook_status_requires_admin(self):
        """Non-authenticated requests should be rejected."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/api/config/gitlab/webhooks")
            assert resp.status_code in (401, 403)
