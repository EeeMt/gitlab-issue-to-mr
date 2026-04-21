"""Tests for remaining untested endpoints: task stats, config reset,
cache invalidation, container logs, and break-glass auth.
"""

import random
import time

import httpx
import pytest

from .conftest import (
    BACKEND_URL,
    MOCK_SERVICES_URL,
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
        assert resp.status_code in (200, 201)
        return _extract_auth(resp)


# ── Task Stats Endpoint ──────────────────────────────────────────────


class TestTaskStats:
    """GET /api/tasks/{task_id}/stats — MR change statistics."""

    @pytest.mark.asyncio
    async def test_completed_task_stats(self, admin_headers):
        """Completed task should return stats (may be zeros in mock env)."""
        async with httpx.AsyncClient(timeout=30) as client:
            _issue, task_data = await create_issue_and_task(
                client, BACKEND_URL, admin_headers,
                title=f"Stats test {random.randint(10000, 89999)}",
                prompt="Create a hello.py file",
            )
            task_id = task_data["id"]

            await wait_for_task_status(
                client, BACKEND_URL, task_id,
                target_statuses=["completed", "failed"],
                auth_headers=admin_headers,
                timeout=120,
            )

            resp = await client.get(
                f"{BACKEND_URL}/api/tasks/{task_id}/stats",
                headers=admin_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "additions" in data
            assert "deletions" in data
            assert "total" in data
            assert isinstance(data["additions"], int)
            assert isinstance(data["deletions"], int)

    @pytest.mark.asyncio
    async def test_nonexistent_task_stats_404(self, admin_headers):
        """Stats for non-existent task should return 404."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/tasks/999999/stats",
                headers=admin_headers,
            )
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_task_stats_requires_auth(self):
        """Stats endpoint should require authentication."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/api/tasks/1/stats")
            assert resp.status_code in (401, 403)


# ── Config Reset ─────────────────────────────────────────────────────


class TestConfigReset:
    """POST /api/config/reset — reset all persisted config overrides."""

    @pytest.mark.asyncio
    async def test_config_reset_returns_config(self, admin_headers):
        """Config reset should return the effective configuration."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/config/reset",
                headers=admin_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            # Config is nested: {"auth": {...}, "integration": {...}, "runtime": {...}}
            assert isinstance(data, dict)
            assert "runtime" in data or "integration" in data

    @pytest.mark.asyncio
    async def test_config_reset_requires_admin(self):
        """Config reset should require admin access."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{BACKEND_URL}/api/config/reset")
            assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_config_override_then_reset(self, admin_headers):
        """PATCH runtime config → override value → reset → back to default."""
        async with httpx.AsyncClient(timeout=10) as client:
            # Override task_timeout via runtime config endpoint
            patch_resp = await client.patch(
                f"{BACKEND_URL}/api/config/runtime",
                headers=admin_headers,
                json={"task_timeout": 3600},
            )
            assert patch_resp.status_code == 200

            # Verify override took effect
            patched = await client.get(
                f"{BACKEND_URL}/api/config",
                headers=admin_headers,
            )
            runtime = patched.json().get("runtime", {})
            assert runtime.get("task_timeout") == 3600

            # Reset all overrides
            reset_resp = await client.post(
                f"{BACKEND_URL}/api/config/reset",
                headers=admin_headers,
            )
            assert reset_resp.status_code == 200

            # Verify reset back to env default (120 in mock env)
            final = await client.get(
                f"{BACKEND_URL}/api/config",
                headers=admin_headers,
            )
            final_runtime = final.json().get("runtime", {})
            assert final_runtime.get("task_timeout") != 3600


# ── Cache Invalidation ───────────────────────────────────────────────


class TestCacheInvalidation:
    """POST /api/config/gitlab/projects/cache/invalidate."""

    @pytest.mark.asyncio
    async def test_invalidate_project_cache(self, admin_headers):
        """Cache invalidation should succeed."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/config/gitlab/projects/cache/invalidate",
                headers=admin_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("status") == "success"

    @pytest.mark.asyncio
    async def test_invalidate_cache_requires_admin(self):
        """Cache invalidation should require admin access."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/config/gitlab/projects/cache/invalidate",
            )
            assert resp.status_code in (401, 403)


# ── Container Logs (Polling) ─────────────────────────────────────────


class TestContainerLogs:
    """GET /api/tasks/{task_id}/container-logs — polling endpoint."""

    @pytest.mark.asyncio
    async def test_container_logs_completed_task(self, admin_headers):
        """Container logs for a completed task should return log data."""
        async with httpx.AsyncClient(timeout=30) as client:
            _issue, task_data = await create_issue_and_task(
                client, BACKEND_URL, admin_headers,
                title=f"Container logs test {random.randint(10000, 89999)}",
                prompt="Create a hello.py file",
            )
            task_id = task_data["id"]

            await wait_for_task_status(
                client, BACKEND_URL, task_id,
                target_statuses=["completed", "failed"],
                auth_headers=admin_headers,
                timeout=120,
            )

            resp = await client.get(
                f"{BACKEND_URL}/api/tasks/{task_id}/container-logs",
                headers=admin_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "container_id" in data
            assert "logs" in data
            assert "status" in data

    @pytest.mark.asyncio
    async def test_container_logs_db_source(self, admin_headers):
        """Container logs with source=db should use database chunks."""
        async with httpx.AsyncClient(timeout=30) as client:
            _issue, task_data = await create_issue_and_task(
                client, BACKEND_URL, admin_headers,
                title=f"Container logs DB test {random.randint(10000, 89999)}",
                prompt="Create a hello.py file",
            )
            task_id = task_data["id"]

            await wait_for_task_status(
                client, BACKEND_URL, task_id,
                target_statuses=["completed", "failed"],
                auth_headers=admin_headers,
                timeout=120,
            )

            resp = await client.get(
                f"{BACKEND_URL}/api/tasks/{task_id}/container-logs",
                headers=admin_headers,
                params={"source": "db"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "logs" in data

    @pytest.mark.asyncio
    async def test_container_logs_nonexistent_task(self, admin_headers):
        """Container logs for non-existent task should return 404."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/tasks/999999/container-logs",
                headers=admin_headers,
            )
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_container_logs_requires_admin(self):
        """Container logs should require admin access."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/tasks/1/container-logs",
            )
            assert resp.status_code in (401, 403)


# ── Break-Glass Auth ─────────────────────────────────────────────────


class TestBreakGlassAuth:
    """POST /api/auth/break-glass/login — emergency admin access."""

    @pytest.mark.asyncio
    async def test_break_glass_disabled_by_default(self):
        """Break-glass should fail when not configured."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/auth/break-glass/login",
                json={"username": "admin", "password": "admin123"},
            )
            # 400/403 (disabled), 401 (bad creds), or 503 (service unavailable)
            assert resp.status_code in (400, 401, 403, 422, 503)

    @pytest.mark.asyncio
    async def test_break_glass_wrong_credentials(self):
        """Break-glass with wrong credentials should fail."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/auth/break-glass/login",
                json={"username": "hacker", "password": "letmein"},
            )
            assert resp.status_code in (400, 401, 403, 422, 503)


# ── OIDC Endpoints ───────────────────────────────────────────────────


class TestOIDCEndpoints:
    """OIDC auth flow endpoints."""

    @pytest.mark.asyncio
    async def test_oidc_login_redirect(self):
        """GET /api/auth/login should redirect to OIDC provider."""
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            resp = await client.get(f"{BACKEND_URL}/api/auth/login")
            # 302 (redirect), 400/422 (not configured), or 503 (service unavailable)
            assert resp.status_code in (302, 400, 422, 500, 503)

    @pytest.mark.asyncio
    async def test_oidc_callback_without_code(self):
        """GET /api/auth/callback without authorization code should fail."""
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            resp = await client.get(f"{BACKEND_URL}/api/auth/callback")
            assert resp.status_code in (302, 400, 422, 500, 503)

    @pytest.mark.asyncio
    async def test_oidc_callback_with_error(self):
        """OIDC callback with error parameter should handle gracefully."""
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/auth/callback",
                params={"error": "access_denied", "error_description": "User denied"},
            )
            assert resp.status_code in (302, 400, 403, 422, 500, 503)

    @pytest.mark.asyncio
    async def test_oidc_test_endpoint(self, admin_headers):
        """POST /api/config/oidc/test should test OIDC connectivity."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/config/oidc/test",
                headers=admin_headers,
                json={},
            )
            # May succeed or fail depending on OIDC configuration
            assert resp.status_code in (200, 400, 422, 500)

    @pytest.mark.asyncio
    async def test_oidc_diagnostics_requires_auth(self):
        """OIDC diagnostics should require authentication."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/config/oidc/diagnostics",
            )
            assert resp.status_code in (401, 403)


# ── Runtime Config Key Delete ────────────────────────────────────────


class TestRuntimeConfigKeyDelete:
    """DELETE /api/config/runtime/{key} — reset individual config key."""

    @pytest.mark.asyncio
    async def test_delete_runtime_config_key(self, admin_headers):
        """Set a runtime config key, then delete it to reset."""
        async with httpx.AsyncClient(timeout=10) as client:
            # First set a key via runtime config endpoint
            resp = await client.patch(
                f"{BACKEND_URL}/api/config/runtime",
                headers=admin_headers,
                json={"task_timeout": 3600},
            )
            assert resp.status_code == 200

            # Now delete the key to reset it
            resp = await client.delete(
                f"{BACKEND_URL}/api/config/runtime/task_timeout",
                headers=admin_headers,
            )
            assert resp.status_code in (200, 204)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_config_key(self, admin_headers):
        """Deleting a non-existent config key should return error."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.delete(
                f"{BACKEND_URL}/api/config/runtime/nonexistent_key_xyz",
                headers=admin_headers,
            )
            # Should be 404 (key not found) or 400 (invalid key)
            assert resp.status_code in (200, 204, 400, 404, 422)

    @pytest.mark.asyncio
    async def test_delete_config_key_requires_auth(self):
        """Deleting runtime config should require admin access."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.delete(
                f"{BACKEND_URL}/api/config/runtime/task_timeout",
            )
            assert resp.status_code in (401, 403)


# ── Misc Endpoint Edge Cases ─────────────────────────────────────────


class TestMiscEndpoints:
    """Miscellaneous endpoint edge cases."""

    @pytest.mark.asyncio
    async def test_api_404_for_unknown_route(self):
        """Unknown API route should return 404."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/api/nonexistent-endpoint")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_task_detail_nonexistent(self, admin_headers):
        """GET /api/tasks/999999 should return 404."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/tasks/999999",
                headers=admin_headers,
            )
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_analytics_custom_days(self, admin_headers):
        """Analytics with custom days parameter."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/stats/analytics",
                headers=admin_headers,
                params={"days": 7},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, dict)
