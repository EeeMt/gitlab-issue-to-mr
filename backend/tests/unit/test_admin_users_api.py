#!/usr/bin/env python3
"""Unit tests for admin user management API endpoints.

Tests cover:
- _serialize_admin_user helper
- _count_other_active_admins helper
- list_admin_users endpoint (GET /admin/users)
- update_admin_user endpoint (PATCH /admin/users/{user_id})
- revoke_admin_user_sessions endpoint (POST /admin/users/{user_id}/sessions/revoke)
"""

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

def _make_mock_user(
    id=1,
    gitlab_user_id=100,
    username="testuser",
    display_name="Test User",
    email="test@example.com",
    avatar_url=None,
    platform_role="platform_user",
    platform_role_source="bootstrap",
    state="active",
    last_login_at=None,
    created_at=None,
):
    """Build a MagicMock with all User model attributes properly typed."""
    user = MagicMock()
    user.id = id
    user.gitlab_user_id = gitlab_user_id
    user.username = username
    user.display_name = display_name
    user.email = email
    user.avatar_url = avatar_url
    user.platform_role = platform_role
    user.platform_role_source = platform_role_source
    user.state = state
    user.last_login_at = last_login_at
    user.created_at = created_at or datetime(2024, 1, 1, 0, 0, 0)
    return user


def _make_db_override():
    """Build a mock DB that works as an async generator override for get_db."""
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=MagicMock())
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.get = AsyncMock(return_value=None)

    async def override_db():
        yield mock_db

    return override_db, mock_db


def _get_test_client(current_user=None):
    """Build TestClient with dependency overrides for admin auth and DB."""
    from app.database import get_db
    from app.dependencies.auth import require_admin_user, require_authenticated_user
    from app.main import app

    override_db, mock_db = _make_db_override()

    if current_user is None:
        current_user = _make_mock_user(
            id=99, username="admin", platform_role="platform_admin",
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin_user] = lambda: current_user
    app.dependency_overrides[require_authenticated_user] = lambda: current_user

    return TestClient(app, raise_server_exceptions=False), app, mock_db, current_user


# ---------------------------------------------------------------------------
# _serialize_admin_user
# ---------------------------------------------------------------------------

class SerializeAdminUserTests(unittest.TestCase):
    """Tests for _serialize_admin_user helper (covers line 62)."""

    def test_serialize_current_user(self):
        """Serializing a user with matching current_user_id sets is_current_user=True."""
        from app.api.admin_users import _serialize_admin_user

        user = _make_mock_user(id=5, username="alice", platform_role="platform_admin")
        result = _serialize_admin_user(
            user,
            active_session_count=2,
            last_session_seen_at=datetime(2024, 6, 1, 12, 0, 0),
            current_user_id=5,
        )

        self.assertEqual(result.id, 5)
        self.assertEqual(result.username, "alice")
        self.assertEqual(result.platform_role, "platform_admin")
        self.assertEqual(result.active_session_count, 2)
        self.assertIsNotNone(result.last_session_seen_at)
        self.assertTrue(result.is_current_user)

    def test_serialize_other_user(self):
        """Serializing another user should have is_current_user=False."""
        from app.api.admin_users import _serialize_admin_user

        user = _make_mock_user(
            id=5, username="bob", platform_role="platform_user",
            email="bob@example.com", display_name="Bob Smith",
        )
        result = _serialize_admin_user(
            user,
            active_session_count=0,
            last_session_seen_at=None,
            current_user_id=99,
        )

        self.assertFalse(result.is_current_user)
        self.assertEqual(result.active_session_count, 0)
        self.assertIsNone(result.last_session_seen_at)
        self.assertEqual(result.email, "bob@example.com")
        self.assertEqual(result.display_name, "Bob Smith")

    def test_serialize_disabled_user(self):
        """Disabled user state is correctly reflected."""
        from app.api.admin_users import _serialize_admin_user

        user = _make_mock_user(id=7, username="disabled_user", state="disabled")
        result = _serialize_admin_user(
            user,
            active_session_count=0,
            last_session_seen_at=None,
            current_user_id=99,
        )

        self.assertEqual(result.state, "disabled")
        self.assertEqual(result.id, 7)


# ---------------------------------------------------------------------------
# _count_other_active_admins
# ---------------------------------------------------------------------------

class CountOtherActiveAdminsTests(unittest.IsolatedAsyncioTestCase):
    """Tests for _count_other_active_admins helper (covers lines 81-88)."""

    async def test_returns_positive_count(self):
        """Should return the count of other active admins."""
        from app.api.admin_users import _count_other_active_admins

        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 3

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        count = await _count_other_active_admins(mock_db, exclude_user_id=1)
        self.assertEqual(count, 3)
        mock_db.execute.assert_awaited_once()

    async def test_returns_zero_when_no_other_admins(self):
        """Should return 0 when the excluded user is the only admin."""
        from app.api.admin_users import _count_other_active_admins

        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        count = await _count_other_active_admins(mock_db, exclude_user_id=42)
        self.assertEqual(count, 0)


# ---------------------------------------------------------------------------
# list_admin_users endpoint
# ---------------------------------------------------------------------------

class ListAdminUsersTests(unittest.TestCase):
    """Tests for GET /api/admin/users endpoint (covers lines 97-127)."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_list_users_returns_multiple(self):
        """Returns list of users with session summary."""
        client, app, mock_db, current_user = _get_test_client()

        user1 = _make_mock_user(id=1, username="alice", platform_role="platform_admin")
        user2 = _make_mock_user(id=2, username="bob", platform_role="platform_user")

        mock_result = MagicMock()
        mock_result.all.return_value = [
            (user1, 3, datetime(2024, 6, 1, 12, 0, 0)),
            (user2, 0, None),
        ]
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/admin/users")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["username"], "alice")
        self.assertEqual(data[0]["platform_role"], "platform_admin")
        self.assertEqual(data[0]["active_session_count"], 3)
        self.assertIsNotNone(data[0]["last_session_seen_at"])
        self.assertEqual(data[1]["username"], "bob")
        self.assertEqual(data[1]["active_session_count"], 0)
        self.assertIsNone(data[1]["last_session_seen_at"])

    def test_list_users_empty(self):
        """Returns empty array when no users exist."""
        client, app, mock_db, _ = _get_test_client()

        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/admin/users")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_users_marks_current_user(self):
        """The is_current_user flag should be True for the admin making the request."""
        current_user = _make_mock_user(id=99, username="admin", platform_role="platform_admin")
        client, app, mock_db, _ = _get_test_client(current_user=current_user)

        mock_result = MagicMock()
        mock_result.all.return_value = [
            (current_user, 1, datetime(2024, 6, 15, 8, 0, 0)),
        ]
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/admin/users")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertTrue(data[0]["is_current_user"])

    def test_list_users_with_disabled_user(self):
        """Disabled users appear in the list with state=disabled."""
        client, app, mock_db, _ = _get_test_client()

        user = _make_mock_user(id=5, username="disabled_user", state="disabled")
        mock_result = MagicMock()
        mock_result.all.return_value = [(user, 0, None)]
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/admin/users")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data[0]["state"], "disabled")


# ---------------------------------------------------------------------------
# update_admin_user endpoint
# ---------------------------------------------------------------------------

class UpdateAdminUserTests(unittest.TestCase):
    """Tests for PATCH /api/admin/users/{user_id} endpoint (covers lines 146-210)."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_no_fields_provided_returns_400(self):
        """Empty payload should return 400 asking for at least one field."""
        client, app, mock_db, _ = _get_test_client()

        response = client.patch("/api/admin/users/5", json={})

        self.assertEqual(response.status_code, 400)
        self.assertIn("At least one field", response.json()["detail"])

    def test_user_not_found_returns_404(self):
        """Non-existent user_id should return 404."""
        client, app, mock_db, _ = _get_test_client()
        mock_db.get = AsyncMock(return_value=None)

        response = client.patch(
            "/api/admin/users/999",
            json={"platform_role": "platform_admin"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("User not found", response.json()["detail"])

    def test_self_modification_returns_400(self):
        """Admin cannot change their own role/state from the admin screen."""
        current_user = _make_mock_user(id=99, username="admin", platform_role="platform_admin")
        client, app, mock_db, _ = _get_test_client(current_user=current_user)

        # db.get returns the same user (same id)
        target_user = _make_mock_user(id=99, username="admin")
        mock_db.get = AsyncMock(return_value=target_user)

        response = client.patch(
            "/api/admin/users/99",
            json={"platform_role": "platform_user"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("cannot change your own", response.json()["detail"])

    def test_invalid_platform_role_returns_400(self):
        """Invalid platform_role value should return 400."""
        client, app, mock_db, _ = _get_test_client()

        target_user = _make_mock_user(id=5, platform_role="platform_user")
        mock_db.get = AsyncMock(return_value=target_user)

        response = client.patch(
            "/api/admin/users/5",
            json={"platform_role": "super_admin"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("platform_role must be", response.json()["detail"])

    def test_invalid_state_returns_400(self):
        """Invalid state value should return 400."""
        client, app, mock_db, _ = _get_test_client()

        target_user = _make_mock_user(id=5, platform_role="platform_user")
        mock_db.get = AsyncMock(return_value=target_user)

        response = client.patch(
            "/api/admin/users/5",
            json={"state": "suspended"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("state must be", response.json()["detail"])

    def test_update_role_success(self):
        """Successfully updating platform_role from user to admin."""
        client, app, mock_db, _ = _get_test_client()

        target_user = _make_mock_user(id=5, platform_role="platform_user", state="active")
        mock_db.get = AsyncMock(return_value=target_user)

        # Session count query (only execute call needed — no admin demotion check)
        session_result = MagicMock()
        session_result.one.return_value = (1, datetime(2024, 6, 1, 12, 0, 0))
        mock_db.execute = AsyncMock(return_value=session_result)

        response = client.patch(
            "/api/admin/users/5",
            json={"platform_role": "platform_admin"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], 5)
        self.assertEqual(data["platform_role"], "platform_admin")
        # Verify the user object was mutated
        self.assertEqual(target_user.platform_role, "platform_admin")
        self.assertEqual(target_user.platform_role_source, "manual")
        mock_db.flush.assert_awaited_once()
        mock_db.commit.assert_awaited_once()

    def test_update_state_success(self):
        """Successfully updating state from active to disabled."""
        client, app, mock_db, _ = _get_test_client()

        target_user = _make_mock_user(id=5, platform_role="platform_user", state="active")
        mock_db.get = AsyncMock(return_value=target_user)

        session_result = MagicMock()
        session_result.one.return_value = (0, None)
        mock_db.execute = AsyncMock(return_value=session_result)

        with patch("app.api.admin_users.revoke_user_sessions", new=AsyncMock(return_value=2)) as mock_revoke:
            response = client.patch(
                "/api/admin/users/5",
                json={"state": "disabled"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(target_user.state, "disabled")
        mock_revoke.assert_awaited_once_with(mock_db, 5)

    def test_disable_user_revokes_sessions(self):
        """Disabling a user should trigger session revocation."""
        client, app, mock_db, _ = _get_test_client()

        target_user = _make_mock_user(id=5, platform_role="platform_user", state="active")
        mock_db.get = AsyncMock(return_value=target_user)

        session_result = MagicMock()
        session_result.one.return_value = (0, None)
        mock_db.execute = AsyncMock(return_value=session_result)

        with patch("app.api.admin_users.revoke_user_sessions", new=AsyncMock(return_value=3)) as mock_revoke:
            response = client.patch(
                "/api/admin/users/5",
                json={"state": "disabled"},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["state"], "disabled")
        mock_revoke.assert_awaited_once_with(mock_db, 5)
        mock_db.flush.assert_awaited()
        mock_db.commit.assert_awaited()

    def test_reenable_user_does_not_revoke_sessions(self):
        """Re-enabling a user should NOT revoke sessions."""
        client, app, mock_db, _ = _get_test_client()

        target_user = _make_mock_user(id=5, platform_role="platform_user", state="disabled")
        mock_db.get = AsyncMock(return_value=target_user)

        session_result = MagicMock()
        session_result.one.return_value = (0, None)
        mock_db.execute = AsyncMock(return_value=session_result)

        with patch("app.api.admin_users.revoke_user_sessions", new=AsyncMock(return_value=0)) as mock_revoke:
            response = client.patch(
                "/api/admin/users/5",
                json={"state": "active"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(target_user.state, "active")
        mock_revoke.assert_not_awaited()

    def test_update_both_role_and_state(self):
        """Updating both platform_role and state in one request."""
        client, app, mock_db, _ = _get_test_client()

        target_user = _make_mock_user(id=5, platform_role="platform_user", state="disabled")
        mock_db.get = AsyncMock(return_value=target_user)

        session_result = MagicMock()
        session_result.one.return_value = (0, None)
        mock_db.execute = AsyncMock(return_value=session_result)

        response = client.patch(
            "/api/admin/users/5",
            json={"platform_role": "platform_admin", "state": "active"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["platform_role"], "platform_admin")
        self.assertEqual(data["state"], "active")
        self.assertEqual(target_user.platform_role, "platform_admin")
        self.assertEqual(target_user.state, "active")

    def test_last_admin_protection_on_role_change(self):
        """Cannot demote the only active admin to a regular user."""
        client, app, mock_db, _ = _get_test_client()

        target_user = _make_mock_user(id=5, platform_role="platform_admin", state="active")
        mock_db.get = AsyncMock(return_value=target_user)

        # _count_other_active_admins returns 0 — this is the last admin
        admin_count_result = MagicMock()
        admin_count_result.scalar_one.return_value = 0
        mock_db.execute = AsyncMock(return_value=admin_count_result)

        response = client.patch(
            "/api/admin/users/5",
            json={"platform_role": "platform_user"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("last active platform admin", response.json()["detail"])

    def test_last_admin_protection_on_disable(self):
        """Cannot disable the only active admin."""
        client, app, mock_db, _ = _get_test_client()

        target_user = _make_mock_user(id=5, platform_role="platform_admin", state="active")
        mock_db.get = AsyncMock(return_value=target_user)

        admin_count_result = MagicMock()
        admin_count_result.scalar_one.return_value = 0
        mock_db.execute = AsyncMock(return_value=admin_count_result)

        response = client.patch(
            "/api/admin/users/5",
            json={"state": "disabled"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("last active platform admin", response.json()["detail"])

    def test_demote_admin_when_others_exist(self):
        """Can demote an admin when other active admins exist."""
        client, app, mock_db, _ = _get_test_client()

        target_user = _make_mock_user(id=5, platform_role="platform_admin", state="active")
        mock_db.get = AsyncMock(return_value=target_user)

        # First execute: _count_other_active_admins returns 1
        admin_count_result = MagicMock()
        admin_count_result.scalar_one.return_value = 1

        # Second execute: session count after update
        session_result = MagicMock()
        session_result.one.return_value = (0, None)

        mock_db.execute = AsyncMock(side_effect=[admin_count_result, session_result])

        response = client.patch(
            "/api/admin/users/5",
            json={"platform_role": "platform_user"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(target_user.platform_role, "platform_user")
        self.assertEqual(target_user.platform_role_source, "manual")

    def test_disable_admin_when_others_exist(self):
        """Can disable an admin when other active admins exist."""
        client, app, mock_db, _ = _get_test_client()

        target_user = _make_mock_user(id=5, platform_role="platform_admin", state="active")
        mock_db.get = AsyncMock(return_value=target_user)

        # First execute: admin count
        admin_count_result = MagicMock()
        admin_count_result.scalar_one.return_value = 2

        # Second execute: session count
        session_result = MagicMock()
        session_result.one.return_value = (0, None)

        mock_db.execute = AsyncMock(side_effect=[admin_count_result, session_result])

        with patch("app.api.admin_users.revoke_user_sessions", new=AsyncMock(return_value=1)):
            response = client.patch(
                "/api/admin/users/5",
                json={"state": "disabled"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(target_user.state, "disabled")


# ---------------------------------------------------------------------------
# revoke_admin_user_sessions endpoint
# ---------------------------------------------------------------------------

class RevokeAdminUserSessionsTests(unittest.TestCase):
    """Tests for POST /api/admin/users/{user_id}/sessions/revoke (covers lines 225-237)."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_revoke_success(self):
        """Successfully revokes sessions for another user."""
        client, app, mock_db, _ = _get_test_client()

        target_user = _make_mock_user(id=5, username="bob")
        mock_db.get = AsyncMock(return_value=target_user)

        with patch("app.api.admin_users.revoke_user_sessions", new=AsyncMock(return_value=3)):
            response = client.post("/api/admin/users/5/sessions/revoke")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["revoked_count"], 3)
        mock_db.commit.assert_awaited_once()

    def test_revoke_user_not_found_returns_404(self):
        """Non-existent user_id should return 404."""
        client, app, mock_db, _ = _get_test_client()
        mock_db.get = AsyncMock(return_value=None)

        response = client.post("/api/admin/users/999/sessions/revoke")

        self.assertEqual(response.status_code, 404)
        self.assertIn("User not found", response.json()["detail"])

    def test_revoke_own_sessions_returns_400(self):
        """Admin cannot revoke their own sessions via this endpoint."""
        current_user = _make_mock_user(id=99, username="admin", platform_role="platform_admin")
        client, app, mock_db, _ = _get_test_client(current_user=current_user)

        target_user = _make_mock_user(id=99, username="admin")
        mock_db.get = AsyncMock(return_value=target_user)

        response = client.post("/api/admin/users/99/sessions/revoke")

        self.assertEqual(response.status_code, 400)
        self.assertIn("normal logout flow", response.json()["detail"])

    def test_revoke_zero_sessions(self):
        """Revoking when user has no active sessions returns count=0."""
        client, app, mock_db, _ = _get_test_client()

        target_user = _make_mock_user(id=5, username="inactive_user")
        mock_db.get = AsyncMock(return_value=target_user)

        with patch("app.api.admin_users.revoke_user_sessions", new=AsyncMock(return_value=0)):
            response = client.post("/api/admin/users/5/sessions/revoke")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["revoked_count"], 0)

    def test_revoke_many_sessions(self):
        """Revoking many sessions returns the correct count."""
        client, app, mock_db, _ = _get_test_client()

        target_user = _make_mock_user(id=5, username="busy_user")
        mock_db.get = AsyncMock(return_value=target_user)

        with patch("app.api.admin_users.revoke_user_sessions", new=AsyncMock(return_value=15)):
            response = client.post("/api/admin/users/5/sessions/revoke")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["revoked_count"], 15)


if __name__ == "__main__":
    unittest.main()
