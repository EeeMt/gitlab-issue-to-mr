"""Task lifecycle and runtime configuration integration tests.

Tests task state transitions, runtime config endpoints,
and authentication/logout behavior.
"""

import asyncio

import httpx
import pytest

from .conftest import (
    BACKEND_URL,
    MOCK_SERVICES_URL,
    create_issue_and_task,
    wait_for_task_status,
)


# ── Runtime Config API ───────────────────────────────────────────────


class TestRuntimeConfigEndpoint:
    """Test /config/runtime GET, PATCH, DELETE endpoints."""

    @pytest.mark.asyncio
    async def test_get_runtime_config(self, http_client, backend_url, admin_auth_headers):
        resp = await http_client.get(
            f"{backend_url}/api/config/runtime",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    @pytest.mark.asyncio
    async def test_patch_runtime_config(self, http_client, backend_url, admin_auth_headers):
        """Set a runtime config value and verify it persists."""
        resp = await http_client.patch(
            f"{backend_url}/api/config/runtime",
            headers=admin_auth_headers,
            json={"max_concurrency": "5"},
        )
        assert resp.status_code == 200

        # Read back
        get_resp = await http_client.get(
            f"{backend_url}/api/config/runtime",
            headers=admin_auth_headers,
        )
        data = get_resp.json()
        assert data.get("max_concurrency") == "5" or data.get("max_concurrency") == 5

    @pytest.mark.asyncio
    async def test_delete_runtime_config_key(self, http_client, backend_url, admin_auth_headers):
        """Reset a specific runtime config key."""
        # Set first
        await http_client.patch(
            f"{backend_url}/api/config/runtime",
            headers=admin_auth_headers,
            json={"max_concurrency": "99"},
        )

        # Delete/reset
        resp = await http_client.delete(
            f"{backend_url}/api/config/runtime/max_concurrency",
            headers=admin_auth_headers,
        )
        # Should succeed (200 or 204)
        assert resp.status_code in (200, 204)

    @pytest.mark.asyncio
    async def test_runtime_config_requires_auth(self, http_client, backend_url):
        resp = await http_client.get(f"{backend_url}/api/config/runtime")
        assert resp.status_code in (401, 403)


# ── Task State Transition Verification ───────────────────────────────


class TestTaskStateTransitions:
    """Verify tasks go through correct state transitions."""

    @pytest.mark.asyncio
    async def test_task_passes_through_queued_and_running(
        self, http_client, backend_url, mock_url, admin_auth_headers,
    ):
        """A task should transition through multiple states to completed."""
        # Configure delay so we can observe intermediate states
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 5},
        )

        try:
            _issue, task = await create_issue_and_task(
                http_client, backend_url, admin_auth_headers,
                title="State transition test issue",
            )
            task_id = task["id"]

            observed_states = set()
            for _ in range(60):
                task_resp = await http_client.get(
                    f"{backend_url}/api/tasks/{task_id}",
                    headers=admin_auth_headers,
                )
                if task_resp.status_code == 200:
                    state = task_resp.json()["status"]
                    observed_states.add(state)
                    if state in ("completed", "failed"):
                        break
                await asyncio.sleep(2)

            assert "completed" in observed_states or "failed" in observed_states, \
                f"Task should complete, observed: {observed_states}"
            assert len(observed_states) >= 2, \
                f"Should observe multiple states, got: {observed_states}"
        finally:
            await http_client.patch(
                f"{mock_url}/mock/config",
                json={"claude_delay_seconds": 0},
            )

    @pytest.mark.asyncio
    async def test_completed_task_has_timestamps(
        self, http_client, backend_url, mock_url, admin_auth_headers,
    ):
        """Completed tasks should have created_at, updated_at, and started_at."""
        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Timestamp verification test issue",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task.get("created_at") is not None
        assert task.get("updated_at") is not None
        if task["status"] == "completed":
            assert task.get("started_at") is not None, "Completed task should have started_at"


# ── Logout ───────────────────────────────────────────────────────────


class TestLogout:
    """Test logout endpoint."""

    @pytest.mark.asyncio
    async def test_logout_invalidates_session(self):
        """After logout, the session token should no longer work."""
        async with httpx.AsyncClient(timeout=10) as client:
            # Login
            login_resp = await client.post(
                f"{BACKEND_URL}/api/auth/local/login",
                json={"username": "admin", "password": "admin123"},
            )
            cookies = dict(login_resp.cookies)
            if cookies:
                headers = {"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())}
            else:
                token = login_resp.json().get("access_token")
                assert token, f"No auth in login response: {login_resp.status_code}"
                headers = {"Authorization": f"Bearer {token}"}

            # Verify session works
            me_resp = await client.get(
                f"{BACKEND_URL}/api/auth/me",
                headers=headers,
            )
            assert me_resp.status_code == 200
            assert me_resp.json().get("authenticated") is True

            # Logout
            logout_resp = await client.post(
                f"{BACKEND_URL}/api/auth/logout",
                headers=headers,
            )
            assert logout_resp.status_code == 200

            # Verify session is invalidated
            me_resp2 = await client.get(
                f"{BACKEND_URL}/api/auth/me",
                headers=headers,
            )
            # Should be unauthenticated or return 401
            if me_resp2.status_code == 200:
                assert me_resp2.json().get("authenticated") is False
            else:
                assert me_resp2.status_code in (401, 403)
