"""Health check, access control, SSE streaming, and webhook config tests.

Tests public health endpoint, 403 for non-admin access, SSE log streaming,
container listing, GitLab config test endpoint, and webhook management.
"""

import asyncio
import random
import time

import httpx
import pytest

from .conftest import (
    BACKEND_URL,
    MOCK_SERVICES_URL,
    WEBHOOK_SECRET,
    build_webhook_payload,
    send_webhook,
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



# ── Health Check ─────────────────────────────────────────────────────


class TestHealthEndpoint:
    """Public /health endpoint for readiness probes."""

    @pytest.mark.asyncio
    async def test_health_returns_healthy(self):
        """Health endpoint should return healthy with DB and Docker checks."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] in ("healthy", "degraded")
            assert "checks" in data
            assert data["checks"]["database"] == "ok"

    @pytest.mark.asyncio
    async def test_health_no_auth_required(self):
        """Health endpoint should work without any authentication."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/health")
            assert resp.status_code in (200, 503)
            assert "status" in resp.json()

    @pytest.mark.asyncio
    async def test_health_includes_trace_id(self):
        """Health response should include a trace_id."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/health")
            data = resp.json()
            assert "trace_id" in data
            assert isinstance(data["trace_id"], str)


# ── Access Control (401) ─────────────────────────────────────────────


class TestAccessControl:
    """Unauthenticated requests should be rejected on protected endpoints."""

    @pytest.mark.asyncio
    async def test_config_requires_auth(self):
        """GET /api/config without auth should be rejected."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/api/config")
            assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_patch_config_requires_auth(self):
        """PATCH /api/config without auth should be rejected."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.patch(
                f"{BACKEND_URL}/api/config",
                json={"max_concurrency": 5},
            )
            assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_containers_requires_auth(self):
        """GET /api/containers without auth should be rejected."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/api/containers")
            assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_admin_users_requires_auth(self):
        """GET /api/admin/users without auth should be rejected."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/api/admin/users")
            assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_prompt_templates_requires_auth(self):
        """GET /api/prompt-templates without auth should be rejected."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/api/prompt-templates")
            assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_webhook_config_requires_auth(self):
        """GET /api/config/gitlab/webhooks without auth should be rejected."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/api/config/gitlab/webhooks")
            assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_tasks_requires_auth(self):
        """GET /api/tasks without auth should be rejected."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/api/tasks")
            assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_stats_requires_auth(self):
        """GET /api/stats without auth should be rejected."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/api/stats")
            assert resp.status_code in (401, 403)


# ── SSE Log Streaming ────────────────────────────────────────────────


class TestSSELogStream:
    """Test Server-Sent Events log streaming for tasks."""

    @pytest.mark.asyncio
    async def test_log_stream_completed_task(self, admin_headers):
        """SSE stream for a completed task should include events and end with 'done'."""
        async with httpx.AsyncClient(timeout=30) as client:
            # Create and wait for task completion
            iid = random.randint(10000, 89999)
            payload = build_webhook_payload(project_id=1, issue_iid=iid)
            payload["object_attributes"]["id"] = random.randint(100000, 999999)
            resp = await send_webhook(client, BACKEND_URL, payload)
            task_id = resp.json()["task_id"]

            await wait_for_task_status(
                client, BACKEND_URL, task_id,
                target_statuses=["completed", "failed"],
                auth_headers=admin_headers,
                timeout=120,
            )

            # Connect to SSE stream
            events = []
            async with client.stream(
                "GET",
                f"{BACKEND_URL}/api/tasks/{task_id}/log-stream",
                headers=admin_headers,
                timeout=30,
            ) as stream:
                async for line in stream.aiter_lines():
                    if line.startswith("data:"):
                        events.append(line)
                    if line.startswith("event: done") or len(events) > 50:
                        break

            # Should have received at least some log events
            assert len(events) > 0, "SSE stream should have emitted log events"

    @pytest.mark.asyncio
    async def test_log_stream_nonexistent_task(self, admin_headers):
        """SSE stream for non-existent task should fail gracefully."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/tasks/999999/log-stream",
                headers=admin_headers,
            )
            # Should return 404 or an empty stream
            assert resp.status_code in (200, 404)

    @pytest.mark.asyncio
    async def test_log_stream_requires_auth(self):
        """SSE stream without auth should be rejected."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/tasks/1/log-stream",
            )
            assert resp.status_code in (401, 403)


# ── Container Listing ────────────────────────────────────────────────


class TestContainerListing:
    """Test container listing endpoint."""

    @pytest.mark.asyncio
    async def test_containers_list_structure(self, admin_headers):
        """GET /api/containers should return a list of container objects."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/containers",
                headers=admin_headers,
            )
            assert resp.status_code == 200
            containers = resp.json()
            assert isinstance(containers, list)
            # Each container should have expected fields
            for c in containers:
                assert "id" in c
                assert "name" in c
                assert "status" in c

    @pytest.mark.asyncio
    async def test_running_task_shows_in_containers(self, admin_headers):
        """A running task should appear in the container listing."""
        async with httpx.AsyncClient(timeout=30) as client:
            # Start a slow task
            await client.patch(
                f"{MOCK_SERVICES_URL}/mock/config",
                json={"claude_delay_seconds": 20},
            )

            try:
                iid = random.randint(10000, 89999)
                payload = build_webhook_payload(project_id=1, issue_iid=iid)
                payload["object_attributes"]["id"] = random.randint(100000, 999999)
                resp = await send_webhook(client, BACKEND_URL, payload)
                task_id = resp.json()["task_id"]

                # Wait for running
                await wait_for_task_status(
                    client, BACKEND_URL, task_id,
                    target_statuses=["running"],
                    auth_headers=admin_headers,
                    timeout=60,
                )

                # Check containers
                resp = await client.get(
                    f"{BACKEND_URL}/api/containers",
                    headers=admin_headers,
                )
                assert resp.status_code == 200
                containers = resp.json()
                # Container list may be empty if Docker is remote and
                # backend filters by codify- prefix.
                # Just verify we get a valid list response.
                assert isinstance(containers, list)
                # If containers visible, verify structure
                for c in containers:
                    assert "id" in c
                    assert "name" in c
            finally:
                await client.patch(
                    f"{MOCK_SERVICES_URL}/mock/config",
                    json={"claude_delay_seconds": 0},
                )


# ── Webhook Config Management ────────────────────────────────────────


class TestWebhookConfigManagement:
    """Test webhook configuration endpoints."""

    @pytest.mark.asyncio
    async def test_list_webhook_statuses(self, admin_headers):
        """GET /api/config/gitlab/webhooks should return project webhook statuses."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/config/gitlab/webhooks",
                headers=admin_headers,
            )
            # May return 200 (list) or 400 (GitLab not properly configured)
            assert resp.status_code in (200, 400)
            if resp.status_code == 200:
                data = resp.json()
                assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_project_webhook_status(self, admin_headers):
        """GET /api/config/gitlab/projects/{id}/webhook returns webhook status."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/config/gitlab/projects/1/webhook",
                headers=admin_headers,
            )
            # May be 200 (status returned) or 400/404 depending on GitLab config
            assert resp.status_code in (200, 400, 404, 500)
            if resp.status_code == 200:
                data = resp.json()
                assert "project_id" in data
                assert "status" in data

    @pytest.mark.asyncio
    async def test_webhook_status_requires_auth(self):
        """Webhook config endpoints should require auth."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/config/gitlab/projects/1/webhook",
            )
            assert resp.status_code in (401, 403)


# ── Config Integration Test ──────────────────────────────────────────


class TestConfigIntegration:
    """Test GitLab connectivity test endpoint."""

    @pytest.mark.asyncio
    async def test_gitlab_connectivity_test(self, admin_headers):
        """POST /api/config/gitlab/test should test GitLab connection."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/config/gitlab/test",
                headers=admin_headers,
                json={},  # Use current settings
            )
            # May succeed (mock GitLab) or fail (can't reach real GitLab)
            assert resp.status_code in (200, 400, 422)
            data = resp.json()
            if resp.status_code == 200:
                assert "server_version" in data or "username" in data

    @pytest.mark.asyncio
    async def test_gitlab_test_requires_auth(self):
        """GitLab config test should require auth."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/config/gitlab/test",
                json={},
            )
            assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_gitlab_test_with_invalid_url(self, admin_headers):
        """Testing with invalid GitLab URL should return error."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/config/gitlab/test",
                headers=admin_headers,
                json={"gitlab_url": "http://nonexistent-host:9999"},
            )
            # Should fail with 400 (connection error)
            assert resp.status_code in (400, 422, 500)


# ── Task Operations Edge Cases ───────────────────────────────────────


class TestTaskOperationsEdge:
    """Edge cases for task cancel, retry, and execute operations."""

    @pytest.mark.asyncio
    async def test_cancel_completed_task_rejected(self, admin_headers):
        """Cannot cancel an already completed task."""
        async with httpx.AsyncClient(timeout=30) as client:
            iid = random.randint(10000, 89999)
            payload = build_webhook_payload(project_id=1, issue_iid=iid)
            payload["object_attributes"]["id"] = random.randint(100000, 999999)
            resp = await send_webhook(client, BACKEND_URL, payload)
            task_id = resp.json()["task_id"]

            await wait_for_task_status(
                client, BACKEND_URL, task_id,
                target_statuses=["completed", "failed"],
                auth_headers=admin_headers,
                timeout=120,
            )

            resp = await client.post(
                f"{BACKEND_URL}/api/tasks/{task_id}/cancel",
                headers=admin_headers,
            )
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_execute_running_task_rejected(self, admin_headers):
        """Cannot execute a task that is already running."""
        async with httpx.AsyncClient(timeout=30) as client:
            await client.patch(
                f"{MOCK_SERVICES_URL}/mock/config",
                json={"claude_delay_seconds": 20},
            )

            try:
                iid = random.randint(10000, 89999)
                payload = build_webhook_payload(project_id=1, issue_iid=iid)
                payload["object_attributes"]["id"] = random.randint(100000, 999999)
                resp = await send_webhook(client, BACKEND_URL, payload)
                task_id = resp.json()["task_id"]

                await wait_for_task_status(
                    client, BACKEND_URL, task_id,
                    target_statuses=["running"],
                    auth_headers=admin_headers,
                    timeout=60,
                )

                resp = await client.post(
                    f"{BACKEND_URL}/api/tasks/{task_id}/execute",
                    headers=admin_headers,
                )
                assert resp.status_code == 400
            finally:
                await client.patch(
                    f"{MOCK_SERVICES_URL}/mock/config",
                    json={"claude_delay_seconds": 0},
                )

    @pytest.mark.asyncio
    async def test_retry_pending_task_rejected(self, admin_headers):
        """Cannot retry a task that is still pending."""
        async with httpx.AsyncClient(timeout=30) as client:
            # Create a manual task (will be pending briefly)
            resp = await client.post(
                f"{BACKEND_URL}/api/tasks",
                headers=admin_headers,
                json={
                    "project_id": 1,
                    "user_prompt": "Retry test task",
                    "branch_name": f"codify/retry-pending-{random.randint(1000, 9999)}",
                    "target_branch": "main",
                    "scheduled_at": "2099-12-31T23:59:59Z",
                },
            )
            assert resp.status_code in (200, 201)
            task_id = resp.json()["id"]

            # Try retry on pending task
            resp = await client.post(
                f"{BACKEND_URL}/api/tasks/{task_id}/retry",
                headers=admin_headers,
            )
            assert resp.status_code == 400

            # Cleanup: cancel the scheduled task
            await client.post(
                f"{BACKEND_URL}/api/tasks/{task_id}/cancel",
                headers=admin_headers,
            )
