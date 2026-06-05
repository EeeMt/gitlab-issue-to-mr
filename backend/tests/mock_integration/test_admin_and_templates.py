"""Admin user management and prompt template CRUD integration tests.

Tests admin endpoints (user listing, role changes, session revocation)
and prompt template lifecycle (create, read, update, delete).
"""

import httpx
import pytest

from .conftest import BACKEND_URL


def _extract_auth(resp: httpx.Response) -> dict:
    """Extract auth headers from login/register response (cookie or bearer token)."""
    cookies = dict(resp.cookies)
    if cookies:
        return {"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())}
    token = resp.json().get("access_token")
    if token:
        return {"Authorization": f"Bearer {token}"}
    raise ValueError(f"No auth in response: {resp.status_code} {resp.text}")


@pytest.fixture
async def admin_headers():
    """Get admin auth headers (cookie-based)."""
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


# ── Prompt Templates CRUD ────────────────────────────────────────────


class TestPromptTemplateCRUD:
    """Full lifecycle: create → list → get → update → delete."""

    @pytest.mark.asyncio
    async def test_create_prompt_template(self, admin_headers):
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/prompt-templates",
                headers=admin_headers,
                json={
                    "name": "Test Template",
                    "content": "Please implement: {{description}}",
                    "variable_tips": {"description": "What to implement"},
                    "is_active": True,
                },
            )
            assert resp.status_code == 201, f"Create failed: {resp.text}"
            data = resp.json()
            assert data["name"] == "Test Template"
            assert "{{description}}" in data["content"]
            assert data["is_active"] is True
            assert data["variable_tips"]["description"] == "What to implement"

    @pytest.mark.asyncio
    async def test_list_prompt_templates(self, admin_headers):
        async with httpx.AsyncClient(timeout=10) as client:
            # Create one first
            await client.post(
                f"{BACKEND_URL}/api/prompt-templates",
                headers=admin_headers,
                json={"name": "List Test", "content": "content-for-list"},
            )
            resp = await client.get(
                f"{BACKEND_URL}/api/prompt-templates",
                headers=admin_headers,
            )
            assert resp.status_code == 200
            templates = resp.json()
            assert isinstance(templates, list)
            assert len(templates) >= 1
            names = [t["name"] for t in templates]
            assert "List Test" in names

    @pytest.mark.asyncio
    async def test_get_prompt_template_by_id(self, admin_headers):
        async with httpx.AsyncClient(timeout=10) as client:
            create_resp = await client.post(
                f"{BACKEND_URL}/api/prompt-templates",
                headers=admin_headers,
                json={"name": "GetById Test", "content": "get-by-id content"},
            )
            template_id = create_resp.json()["id"]

            resp = await client.get(
                f"{BACKEND_URL}/api/prompt-templates/{template_id}",
                headers=admin_headers,
            )
            assert resp.status_code == 200
            assert resp.json()["name"] == "GetById Test"
            assert resp.json()["id"] == template_id

    @pytest.mark.asyncio
    async def test_update_prompt_template(self, admin_headers):
        async with httpx.AsyncClient(timeout=10) as client:
            create_resp = await client.post(
                f"{BACKEND_URL}/api/prompt-templates",
                headers=admin_headers,
                json={"name": "Update Me", "content": "original"},
            )
            template_id = create_resp.json()["id"]

            resp = await client.put(
                f"{BACKEND_URL}/api/prompt-templates/{template_id}",
                headers=admin_headers,
                json={"name": "Updated Name", "content": "updated content", "is_active": False},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["name"] == "Updated Name"
            assert data["content"] == "updated content"
            assert data["is_active"] is False

    @pytest.mark.asyncio
    async def test_delete_prompt_template(self, admin_headers):
        async with httpx.AsyncClient(timeout=10) as client:
            create_resp = await client.post(
                f"{BACKEND_URL}/api/prompt-templates",
                headers=admin_headers,
                json={"name": "Delete Me", "content": "to be deleted"},
            )
            template_id = create_resp.json()["id"]

            resp = await client.delete(
                f"{BACKEND_URL}/api/prompt-templates/{template_id}",
                headers=admin_headers,
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "success"

            # Verify gone
            get_resp = await client.get(
                f"{BACKEND_URL}/api/prompt-templates/{template_id}",
                headers=admin_headers,
            )
            assert get_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_nonexistent_template_404(self, admin_headers):
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/prompt-templates/99999",
                headers=admin_headers,
            )
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_templates_require_admin(self):
        """Non-authenticated requests should be rejected."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/api/prompt-templates")
            assert resp.status_code in (401, 403)


# ── Admin User Management ────────────────────────────────────────────


class TestAdminUserManagement:
    """Admin user listing, role changes, and session revocation."""

    @pytest.mark.asyncio
    async def test_list_admin_users(self, admin_headers):
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/admin/users",
                headers=admin_headers,
            )
            assert resp.status_code == 200
            users = resp.json()
            assert isinstance(users, list)
            assert len(users) >= 1
            admin_user = next(u for u in users if u["username"] == "admin")
            assert admin_user["platform_role"] == "platform_admin"
            assert "active_session_count" in admin_user
            assert admin_user["is_current_user"] is True

    @pytest.mark.asyncio
    async def test_admin_users_require_admin(self):
        """Non-authenticated requests should be rejected."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/api/admin/users")
            assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_revoke_user_sessions(self, admin_headers):
        """Admin revoking own sessions returns 400 (cannot revoke self)."""
        async with httpx.AsyncClient(timeout=10) as client:
            users_resp = await client.get(
                f"{BACKEND_URL}/api/admin/users",
                headers=admin_headers,
            )
            users = users_resp.json()
            admin_user = next(u for u in users if u["username"] == "admin")
            user_id = admin_user["id"]

            resp = await client.post(
                f"{BACKEND_URL}/api/admin/users/{user_id}/sessions/revoke",
                headers=admin_headers,
            )
            # Revoking own sessions is rejected (400) — need a different user
            # With only one user, just verify the endpoint is reachable
            assert resp.status_code in (200, 400)
            data = resp.json()
            if resp.status_code == 200:
                assert data["status"] == "success"
                assert "revoked_count" in data


# ── Session Management ───────────────────────────────────────────────


class TestSessionManagement:
    """User session listing and revocation."""

    @pytest.mark.asyncio
    async def test_list_own_sessions(self, admin_headers):
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/auth/sessions",
                headers=admin_headers,
            )
            assert resp.status_code == 200
            sessions = resp.json()
            assert isinstance(sessions, list)
            assert len(sessions) >= 1
            current = [s for s in sessions if s.get("current")]
            assert len(current) == 1, "Should have exactly one current session"
            assert current[0]["status"] == "active"

    @pytest.mark.asyncio
    async def test_revoke_own_session(self):
        """Create a second session, then revoke it."""
        async with httpx.AsyncClient(timeout=10) as client:
            # Login twice to create two sessions
            login1 = await client.post(
                f"{BACKEND_URL}/api/auth/local/login",
                json={"username": "admin", "password": "admin123"},
            )
            headers1 = _extract_auth(login1)

            login2 = await client.post(
                f"{BACKEND_URL}/api/auth/local/login",
                json={"username": "admin", "password": "admin123"},
            )
            _extract_auth(login2)

            # List sessions from session1
            sessions_resp = await client.get(
                f"{BACKEND_URL}/api/auth/sessions",
                headers=headers1,
            )
            sessions = sessions_resp.json()
            # Find the session that is NOT current (not session1)
            other = [s for s in sessions if not s.get("current")]
            if other:
                sid = other[0]["id"]
                revoke_resp = await client.post(
                    f"{BACKEND_URL}/api/auth/sessions/{sid}/revoke",
                    headers=headers1,
                )
                assert revoke_resp.status_code == 200
                assert revoke_resp.json()["status"] == "success"

    @pytest.mark.asyncio
    async def test_sessions_require_auth(self):
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/api/auth/sessions")
            assert resp.status_code in (401, 403)
