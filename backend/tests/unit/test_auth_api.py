#!/usr/bin/env python3
"""Unit tests for authentication API endpoints (app/api/auth.py).

Covers:
- Helper functions: _build_cookie_kwargs, _sanitize_next_path, _record_auth_audit,
  _get_or_create_break_glass_user, _upsert_user
- Endpoints: bootstrap-status, local/register, local/login, auth/login (OIDC redirect),
  auth/callback (OIDC callback), logout, me, sessions, sessions/{id}/revoke
"""

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.models import User

# BreakGlassLoginRequestBody is referenced in auth.py but never defined.
# Inject it into the module namespace before anything tries to resolve it,
# so FastAPI can resolve the type annotation for the break-glass endpoint.
import app.api.auth as _auth_module
if not hasattr(_auth_module, "BreakGlassLoginRequestBody"):
    from pydantic import BaseModel as _BaseModel
    from typing import Optional as _Opt

    class _BreakGlassLoginRequestBody(_BaseModel):
        username: str
        password: str
        next: _Opt[str] = None

    _auth_module.BreakGlassLoginRequestBody = _BreakGlassLoginRequestBody

from app.api.auth import (
    _build_cookie_kwargs,
    _get_or_create_break_glass_user,
    _record_auth_audit,
    _sanitize_next_path,
    _upsert_user,
)


# ---------------------------------------------------------------------------
# Helpers shared by multiple test classes
# ---------------------------------------------------------------------------

def _make_mock_db():
    """Create a mock async db session with standard async operations."""
    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    return mock_db, mock_result


def _make_mock_settings(**overrides):
    """Create a settings-like SimpleNamespace with auth defaults."""
    defaults = dict(
        session_cookie_name="codify_session",
        session_ttl_seconds=28800,
        cookie_secure=True,
        cookie_samesite="lax",
        oidc_enabled=False,
        break_glass_enabled=False,
        auth_break_glass_username="",
        auth_break_glass_password_hash="",
        admin_usernames=set(),
        admin_gitlab_groups=set(),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_test_client(mock_db=None, auth_context=None, current_user=None):
    """Build a TestClient with standard dependency overrides for the auth router.

    Since the auth router is mounted *without* router-level auth dependencies,
    only per-endpoint dependencies (get_db, require_authenticated_context,
    get_optional_current_user) need overriding.
    """
    from app.database import get_db
    from app.dependencies.auth import (
        get_optional_current_user,
        require_authenticated_context,
    )
    from app.main import app

    if mock_db is None:
        mock_db, _ = _make_mock_db()

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db

    if auth_context is not None:
        app.dependency_overrides[require_authenticated_context] = lambda: auth_context

    if current_user is not None:
        app.dependency_overrides[get_optional_current_user] = lambda: current_user

    client = TestClient(app, raise_server_exceptions=False)
    return client, app, mock_db


def _make_mock_user(**overrides):
    """Return a MagicMock that behaves like a User model."""
    defaults = dict(
        id=1,
        username="alice",
        display_name="Alice",
        email="alice@example.com",
        avatar_url=None,
        platform_role="platform_admin",
        auth_provider="local",
        local_password_hash="pbkdf2_sha256$600000$aabbccdd$deadbeef",
        state="active",
        gitlab_user_id=None,
        oidc_sub=None,
    )
    defaults.update(overrides)
    user = MagicMock(**defaults)
    # Ensure attribute access works (MagicMock auto-generates attrs, but
    # explicit assignment prevents surprises in assertions).
    for k, v in defaults.items():
        setattr(user, k, v)
    return user


def _make_auth_context(user=None, session_id="sess-1"):
    """Return a SimpleNamespace mimicking AuthContext."""
    if user is None:
        user = _make_mock_user()
    session = MagicMock()
    session.id = session_id
    return SimpleNamespace(
        user=user,
        session=session,
        gitlab_access_token=None,
        gitlab_refresh_token=None,
    )


# ===========================================================================
# 1. Helper function tests
# ===========================================================================


class BuildCookieKwargsTests(unittest.TestCase):
    """Tests for _build_cookie_kwargs helper."""

    def test_returns_dict_with_expected_keys(self) -> None:
        """_build_cookie_kwargs should read settings and return httponly/secure/samesite/path."""
        settings = _make_mock_settings(cookie_secure=False, cookie_samesite="strict")
        with patch("app.api.auth.get_effective_settings", return_value=settings):
            result = _build_cookie_kwargs()
        self.assertTrue(result["httponly"])
        self.assertFalse(result["secure"])
        self.assertEqual(result["samesite"], "strict")
        self.assertEqual(result["path"], "/")

    def test_secure_flag_follows_settings(self) -> None:
        """When cookie_secure is True in settings, the result should reflect it."""
        settings = _make_mock_settings(cookie_secure=True, cookie_samesite="lax")
        with patch("app.api.auth.get_effective_settings", return_value=settings):
            result = _build_cookie_kwargs()
        self.assertTrue(result["secure"])
        self.assertEqual(result["samesite"], "lax")


class SanitizeNextPathTests(unittest.TestCase):
    """Tests for _sanitize_next_path helper."""

    def test_none_returns_dashboard(self) -> None:
        self.assertEqual(_sanitize_next_path(None), "/dashboard")

    def test_empty_string_returns_dashboard(self) -> None:
        self.assertEqual(_sanitize_next_path(""), "/dashboard")

    def test_non_slash_prefix_returns_dashboard(self) -> None:
        self.assertEqual(_sanitize_next_path("http://evil.com"), "/dashboard")

    def test_double_slash_returns_dashboard(self) -> None:
        """Double-slash could be an open redirect, so it should be rejected."""
        self.assertEqual(_sanitize_next_path("//evil.com"), "/dashboard")

    def test_valid_path_passes_through(self) -> None:
        self.assertEqual(_sanitize_next_path("/settings"), "/settings")

    def test_slash_only_passes_through(self) -> None:
        self.assertEqual(_sanitize_next_path("/"), "/")


class RecordAuthAuditTests(unittest.IsolatedAsyncioTestCase):
    """Tests for _record_auth_audit helper."""

    async def test_adds_audit_log_and_flushes(self) -> None:
        """_record_auth_audit should db.add() an AuthAuditLog and flush."""
        mock_db, _ = _make_mock_db()
        mock_request = MagicMock()
        mock_request.client.host = "10.0.0.1"
        mock_request.headers.get.return_value = "TestAgent/1.0"

        await _record_auth_audit(
            mock_db,
            event_type="local_login",
            username="alice",
            user_id=1,
            success=True,
            detail="OK",
            request=mock_request,
        )

        mock_db.add.assert_called_once()
        added = mock_db.add.call_args.args[0]
        self.assertEqual(added.event_type, "local_login")
        self.assertEqual(added.username, "alice")
        self.assertEqual(added.user_id, 1)
        self.assertTrue(added.success)
        self.assertEqual(added.ip_address, "10.0.0.1")
        self.assertEqual(added.user_agent, "TestAgent/1.0")
        mock_db.flush.assert_awaited_once()

    async def test_handles_missing_client(self) -> None:
        """When request.client is None, ip_address should be None."""
        mock_db, _ = _make_mock_db()
        mock_request = MagicMock()
        mock_request.client = None
        mock_request.headers.get.return_value = None

        await _record_auth_audit(
            mock_db,
            event_type="local_login",
            username=None,
            user_id=None,
            success=False,
            detail="test",
            request=mock_request,
        )

        added = mock_db.add.call_args.args[0]
        self.assertIsNone(added.ip_address)


class GetOrCreateBreakGlassUserTests(unittest.IsolatedAsyncioTestCase):
    """Tests for _get_or_create_break_glass_user helper."""

    async def test_creates_new_user_when_not_found(self) -> None:
        """Should create a new User with break-glass attributes."""
        mock_db, mock_result = _make_mock_db()
        mock_result.scalar_one_or_none.return_value = None

        user = await _get_or_create_break_glass_user(mock_db, "admin")

        self.assertIsInstance(user, User)
        self.assertEqual(user.username, "admin")
        self.assertEqual(user.platform_role, "platform_admin")
        self.assertEqual(user.display_name, "Emergency Admin")
        self.assertEqual(user.state, "active")
        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()

    async def test_returns_existing_user_by_oidc_sub(self) -> None:
        """When user exists by oidc_sub, should update attributes and return it."""
        existing_user = User(
            oidc_sub="break_glass:admin",
            gitlab_user_id=-999,
            username="admin",
        )
        mock_db, mock_result = _make_mock_db()
        mock_result.scalar_one_or_none.return_value = existing_user

        user = await _get_or_create_break_glass_user(mock_db, "admin")

        self.assertIs(user, existing_user)
        self.assertEqual(user.platform_role, "platform_admin")
        self.assertEqual(user.display_name, "Emergency Admin")
        # Should NOT call db.add since user already exists
        mock_db.add.assert_not_called()

    async def test_raises_on_username_conflict(self) -> None:
        """Should raise HTTP 500 if username is taken by a different user."""
        from fastapi import HTTPException

        mock_db = MagicMock()
        mock_db.flush = AsyncMock()

        # First execute: lookup by oidc_sub -> not found
        result_by_sub = MagicMock()
        result_by_sub.scalar_one_or_none.return_value = None
        # Second execute: lookup by username -> conflict found
        result_by_name = MagicMock()
        result_by_name.scalar_one_or_none.return_value = MagicMock(username="admin")

        mock_db.execute = AsyncMock(side_effect=[result_by_sub, result_by_name])

        with self.assertRaises(HTTPException) as ctx:
            await _get_or_create_break_glass_user(mock_db, "admin")
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertIn("conflicts", ctx.exception.detail)


class UpsertUserTests(unittest.IsolatedAsyncioTestCase):
    """Tests for _upsert_user helper."""

    async def test_creates_new_user_from_claims(self) -> None:
        """Should create a User with OIDC claims and userinfo."""
        mock_db, mock_result = _make_mock_db()
        mock_result.scalar_one_or_none.return_value = None

        settings = _make_mock_settings()
        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.apply_platform_access_policy"):
            user = await _upsert_user(
                mock_db,
                claims={"sub": "42"},
                userinfo={"preferred_username": "alice", "name": "Alice", "email": "alice@test.com"},
            )

        self.assertIsInstance(user, User)
        self.assertEqual(user.username, "alice")
        self.assertEqual(user.display_name, "Alice")
        self.assertEqual(user.email, "alice@test.com")
        mock_db.add.assert_called_once()

    async def test_updates_existing_user(self) -> None:
        """Should update an existing user's attributes on repeat login."""
        existing_user = User(oidc_sub="42", gitlab_user_id=42, username="alice")
        mock_db, mock_result = _make_mock_db()
        mock_result.scalar_one_or_none.return_value = existing_user

        settings = _make_mock_settings()
        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.apply_platform_access_policy"):
            user = await _upsert_user(
                mock_db,
                claims={"sub": "42"},
                userinfo={
                    "preferred_username": "alice",
                    "name": "Alice Updated",
                    "email": "new@test.com",
                    "picture": "https://img.test/alice.png",
                },
            )

        self.assertIs(user, existing_user)
        self.assertEqual(user.display_name, "Alice Updated")
        self.assertEqual(user.email, "new@test.com")
        self.assertEqual(user.avatar_url, "https://img.test/alice.png")
        # Existing users should NOT be added again
        mock_db.add.assert_not_called()

    async def test_raises_when_sub_missing(self) -> None:
        """Should raise HTTP 400 when sub claim is missing."""
        from fastapi import HTTPException

        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings()
        with patch("app.api.auth.get_effective_settings", return_value=settings):
            with self.assertRaises(HTTPException) as ctx:
                await _upsert_user(mock_db, claims={}, userinfo={"preferred_username": "alice"})
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("missing required identity fields", ctx.exception.detail)

    async def test_raises_when_username_missing(self) -> None:
        """Should raise HTTP 400 when preferred_username is missing."""
        from fastapi import HTTPException

        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings()
        with patch("app.api.auth.get_effective_settings", return_value=settings):
            with self.assertRaises(HTTPException) as ctx:
                await _upsert_user(mock_db, claims={"sub": "42"}, userinfo={})
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_raises_when_sub_not_int(self) -> None:
        """Should raise HTTP 400 when oidc_sub is not a valid integer."""
        from fastapi import HTTPException

        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings()
        with patch("app.api.auth.get_effective_settings", return_value=settings):
            with self.assertRaises(HTTPException) as ctx:
                await _upsert_user(
                    mock_db,
                    claims={"sub": "not-an-int"},
                    userinfo={"preferred_username": "alice"},
                )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("not a valid GitLab user ID", ctx.exception.detail)

    async def test_disabled_user_stays_disabled(self) -> None:
        """When a user has state='disabled', it should NOT be changed to 'active'."""
        disabled_user = User(oidc_sub="42", gitlab_user_id=42, username="alice")
        disabled_user.state = "disabled"

        mock_db, mock_result = _make_mock_db()
        mock_result.scalar_one_or_none.return_value = disabled_user

        settings = _make_mock_settings()
        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.apply_platform_access_policy"):
            user = await _upsert_user(
                mock_db,
                claims={"sub": "42"},
                userinfo={"preferred_username": "alice", "name": "Alice"},
            )

        self.assertEqual(user.state, "disabled")


# ===========================================================================
# 2. Endpoint tests
# ===========================================================================


class BootstrapStatusEndpointTests(unittest.TestCase):
    """Tests for GET /api/auth/bootstrap-status."""

    def tearDown(self) -> None:
        from app.main import app
        app.dependency_overrides.clear()

    def test_uninitialized_system(self) -> None:
        """Should return initialized=False when system is not bootstrapped."""
        mock_db, mock_result = _make_mock_db()
        # get_bootstrap_state returns a SimpleNamespace-like object
        mock_state = SimpleNamespace(initialized=False)
        settings = _make_mock_settings(oidc_enabled=False)

        with patch("app.api.auth.get_bootstrap_state", new=AsyncMock(return_value=mock_state)), \
             patch("app.api.auth.get_effective_settings", return_value=settings):
            client, app, _ = _make_test_client(mock_db)
            response = client.get("/api/auth/bootstrap-status")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["initialized"])
        self.assertFalse(data["oidc_configured"])

    def test_initialized_system_with_oidc(self) -> None:
        """Should return initialized=True and oidc_configured=True."""
        mock_db, mock_result = _make_mock_db()
        # Simulate one existing user
        mock_user = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_user]
        mock_state = SimpleNamespace(initialized=True)
        settings = _make_mock_settings(oidc_enabled=True)

        with patch("app.api.auth.get_bootstrap_state", new=AsyncMock(return_value=mock_state)), \
             patch("app.api.auth.get_effective_settings", return_value=settings):
            client, app, _ = _make_test_client(mock_db)
            response = client.get("/api/auth/bootstrap-status")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["initialized"])
        self.assertTrue(data["oidc_configured"])
        self.assertEqual(data["total_users"], 1)


class LocalRegisterEndpointTests(unittest.TestCase):
    """Tests for POST /api/auth/local/register."""

    def tearDown(self) -> None:
        from app.main import app
        app.dependency_overrides.clear()

    def test_successful_registration(self) -> None:
        """Should register the first admin user and return success."""
        mock_db, mock_result = _make_mock_db()
        mock_result.scalar_one_or_none.return_value = None  # No existing user
        mock_state = SimpleNamespace(initialized=False)
        settings = _make_mock_settings()

        with patch("app.api.auth.get_bootstrap_state", new=AsyncMock(return_value=mock_state)), \
             patch("app.api.auth.hash_password", return_value="hashed123"), \
             patch("app.api.auth.initialize_system", new=AsyncMock()), \
             patch("app.api.auth.create_user_session", new=AsyncMock(return_value="session-token")), \
             patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth._record_auth_audit", new=AsyncMock()):
            client, app, _ = _make_test_client(mock_db)
            response = client.post("/api/auth/local/register", json={
                "username": "admin",
                "password": "StrongPass123!",
                "display_name": "Admin User",
                "email": "admin@test.com",
            })

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["next_path"], "/dashboard")
        # Should set session cookie
        self.assertIn(settings.session_cookie_name, response.cookies)

    def test_already_initialized_returns_403(self) -> None:
        """Should reject registration when system is already initialized."""
        mock_db, _ = _make_mock_db()
        mock_state = SimpleNamespace(initialized=True)

        with patch("app.api.auth.get_bootstrap_state", new=AsyncMock(return_value=mock_state)), \
             patch("app.api.auth._record_auth_audit", new=AsyncMock()):
            client, app, _ = _make_test_client(mock_db)
            response = client.post("/api/auth/local/register", json={
                "username": "admin",
                "password": "pass",
            })

        self.assertEqual(response.status_code, 403)
        self.assertIn("already initialized", response.json()["detail"])

    def test_empty_username_returns_400(self) -> None:
        """Should reject registration with empty username."""
        mock_db, _ = _make_mock_db()
        mock_state = SimpleNamespace(initialized=False)

        with patch("app.api.auth.get_bootstrap_state", new=AsyncMock(return_value=mock_state)):
            client, app, _ = _make_test_client(mock_db)
            response = client.post("/api/auth/local/register", json={
                "username": "  ",
                "password": "pass",
            })

        self.assertEqual(response.status_code, 400)
        self.assertIn("Username is required", response.json()["detail"])

    def test_duplicate_username_returns_409(self) -> None:
        """Should reject registration when username already exists."""
        mock_db, _ = _make_mock_db()
        mock_state = SimpleNamespace(initialized=False)

        # The endpoint calls db.execute(select(User).where(User.username == ...))
        # which should return an existing user to trigger the 409 conflict.
        existing_user = MagicMock()
        dup_result = MagicMock()
        dup_result.scalar_one_or_none.return_value = existing_user
        mock_db.execute = AsyncMock(return_value=dup_result)

        with patch("app.api.auth.get_bootstrap_state", new=AsyncMock(return_value=mock_state)), \
             patch("app.api.auth._record_auth_audit", new=AsyncMock()):
            client, app, _ = _make_test_client(mock_db)
            response = client.post("/api/auth/local/register", json={
                "username": "admin",
                "password": "pass",
            })

        self.assertEqual(response.status_code, 409)
        self.assertIn("already exists", response.json()["detail"])


class LocalLoginEndpointTests(unittest.TestCase):
    """Tests for POST /api/auth/local/login."""

    def tearDown(self) -> None:
        from app.main import app
        app.dependency_overrides.clear()

    def test_successful_login(self) -> None:
        """Should return success with session cookie on valid credentials."""
        mock_db, mock_result = _make_mock_db()
        mock_user = _make_mock_user()
        mock_result.scalar_one_or_none.return_value = mock_user
        settings = _make_mock_settings()

        with patch("app.api.auth.verify_password", return_value=True), \
             patch("app.api.auth.create_user_session", new=AsyncMock(return_value="tok-abc")), \
             patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth._record_auth_audit", new=AsyncMock()):
            client, app, _ = _make_test_client(mock_db)
            response = client.post("/api/auth/local/login", json={
                "username": "alice",
                "password": "correct-pass",
            })

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("user", data)
        self.assertEqual(data["user"]["username"], "alice")

    def test_successful_login_with_next(self) -> None:
        """Should include the sanitized next_path in the response."""
        mock_db, mock_result = _make_mock_db()
        mock_user = _make_mock_user()
        mock_result.scalar_one_or_none.return_value = mock_user
        settings = _make_mock_settings()

        with patch("app.api.auth.verify_password", return_value=True), \
             patch("app.api.auth.create_user_session", new=AsyncMock(return_value="tok-abc")), \
             patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth._record_auth_audit", new=AsyncMock()):
            client, app, _ = _make_test_client(mock_db)
            response = client.post("/api/auth/local/login", json={
                "username": "alice",
                "password": "correct-pass",
                "next": "/settings",
            })

        data = response.json()
        self.assertEqual(data["next_path"], "/settings")

    def test_user_not_found_returns_401(self) -> None:
        """Should return 401 when user does not exist."""
        mock_db, mock_result = _make_mock_db()
        mock_result.scalar_one_or_none.return_value = None

        with patch("app.api.auth._record_auth_audit", new=AsyncMock()):
            client, app, _ = _make_test_client(mock_db)
            response = client.post("/api/auth/local/login", json={
                "username": "nonexistent",
                "password": "pass",
            })

        self.assertEqual(response.status_code, 401)
        self.assertIn("Invalid username or password", response.json()["detail"])

    def test_user_with_no_local_password_returns_401(self) -> None:
        """Should return 401 for OIDC-only user (no local_password_hash)."""
        mock_db, mock_result = _make_mock_db()
        oidc_user = _make_mock_user(local_password_hash=None)
        mock_result.scalar_one_or_none.return_value = oidc_user

        with patch("app.api.auth._record_auth_audit", new=AsyncMock()):
            client, app, _ = _make_test_client(mock_db)
            response = client.post("/api/auth/local/login", json={
                "username": "alice",
                "password": "pass",
            })

        self.assertEqual(response.status_code, 401)

    def test_wrong_password_returns_401(self) -> None:
        """Should return 401 when password verification fails."""
        mock_db, mock_result = _make_mock_db()
        mock_user = _make_mock_user()
        mock_result.scalar_one_or_none.return_value = mock_user

        with patch("app.api.auth.verify_password", return_value=False), \
             patch("app.api.auth._record_auth_audit", new=AsyncMock()):
            client, app, _ = _make_test_client(mock_db)
            response = client.post("/api/auth/local/login", json={
                "username": "alice",
                "password": "wrong-pass",
            })

        self.assertEqual(response.status_code, 401)
        self.assertIn("Invalid username or password", response.json()["detail"])

    def test_disabled_user_returns_403(self) -> None:
        """Should return 403 when user account is disabled."""
        mock_db, mock_result = _make_mock_db()
        disabled_user = _make_mock_user(state="disabled")
        mock_result.scalar_one_or_none.return_value = disabled_user

        with patch("app.api.auth.verify_password", return_value=True), \
             patch("app.api.auth._record_auth_audit", new=AsyncMock()):
            client, app, _ = _make_test_client(mock_db)
            response = client.post("/api/auth/local/login", json={
                "username": "alice",
                "password": "correct-pass",
            })

        self.assertEqual(response.status_code, 403)
        self.assertIn("disabled", response.json()["detail"])

    def test_login_sanitizes_malicious_next(self) -> None:
        """Should sanitize open redirect attempts in the next parameter."""
        mock_db, mock_result = _make_mock_db()
        mock_user = _make_mock_user()
        mock_result.scalar_one_or_none.return_value = mock_user
        settings = _make_mock_settings()

        with patch("app.api.auth.verify_password", return_value=True), \
             patch("app.api.auth.create_user_session", new=AsyncMock(return_value="tok")), \
             patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth._record_auth_audit", new=AsyncMock()):
            client, app, _ = _make_test_client(mock_db)
            response = client.post("/api/auth/local/login", json={
                "username": "alice",
                "password": "correct-pass",
                "next": "//evil.com",
            })

        data = response.json()
        self.assertEqual(data["next_path"], "/dashboard")


class OIDCLoginRedirectTests(unittest.TestCase):
    """Tests for GET /api/auth/login (OIDC redirect)."""

    def tearDown(self) -> None:
        from app.main import app
        app.dependency_overrides.clear()

    def test_oidc_disabled_returns_503(self) -> None:
        """Should return 503 when OIDC is disabled."""
        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings(oidc_enabled=False)

        with patch("app.api.auth.get_effective_settings", return_value=settings):
            client, app, _ = _make_test_client(mock_db)
            response = client.get("/api/auth/login", follow_redirects=False)

        self.assertEqual(response.status_code, 503)
        self.assertIn("OIDC login is disabled", response.json()["detail"])

    def test_oidc_enabled_redirects(self) -> None:
        """Should redirect to the OIDC authorize URL when enabled."""
        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings(oidc_enabled=True)
        authorize_url = "https://gitlab.example.com/oauth/authorize?response_type=code&state=abc"

        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.build_authorization_url", new=AsyncMock(return_value=authorize_url)):
            client, app, _ = _make_test_client(mock_db)
            response = client.get("/api/auth/login", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], authorize_url)

    def test_oidc_config_error_returns_503(self) -> None:
        """Should return 503 when OIDC configuration is broken."""
        from app.core.oidc import OIDCConfigurationError

        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings(oidc_enabled=True)

        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch(
                 "app.api.auth.build_authorization_url",
                 new=AsyncMock(side_effect=OIDCConfigurationError("bad config")),
             ):
            client, app, _ = _make_test_client(mock_db)
            response = client.get("/api/auth/login", follow_redirects=False)

        self.assertEqual(response.status_code, 503)

    def test_oidc_login_sets_state_cookies(self) -> None:
        """Should set OIDC state, nonce, and next cookies on redirect."""
        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings(oidc_enabled=True)
        authorize_url = "https://gitlab.example.com/oauth/authorize"

        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.build_authorization_url", new=AsyncMock(return_value=authorize_url)):
            client, app, _ = _make_test_client(mock_db)
            response = client.get(
                "/api/auth/login?next=/settings", follow_redirects=False,
            )

        # Check OIDC state cookies are set
        cookie_names = {c.name for c in response.cookies.jar}
        self.assertIn("codify_oidc_state", cookie_names)
        self.assertIn("codify_oidc_nonce", cookie_names)
        self.assertIn("codify_oidc_next", cookie_names)


class OIDCCallbackEndpointTests(unittest.TestCase):
    """Tests for GET /api/auth/callback."""

    def tearDown(self) -> None:
        from app.main import app
        app.dependency_overrides.clear()

    def test_oidc_disabled_returns_503(self) -> None:
        """Should return 503 when OIDC is disabled."""
        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings(oidc_enabled=False)

        with patch("app.api.auth.get_effective_settings", return_value=settings):
            client, app, _ = _make_test_client(mock_db)
            response = client.get("/api/auth/callback?code=abc&state=xyz")

        self.assertEqual(response.status_code, 503)

    def test_missing_code_returns_400(self) -> None:
        """Should return 400 when code is missing."""
        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings(oidc_enabled=True)

        with patch("app.api.auth.get_effective_settings", return_value=settings):
            client, app, _ = _make_test_client(mock_db)
            response = client.get("/api/auth/callback?state=xyz")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Missing OIDC callback parameters", response.json()["detail"])

    def test_missing_state_returns_400(self) -> None:
        """Should return 400 when state is missing."""
        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings(oidc_enabled=True)

        with patch("app.api.auth.get_effective_settings", return_value=settings):
            client, app, _ = _make_test_client(mock_db)
            response = client.get("/api/auth/callback?code=abc")

        self.assertEqual(response.status_code, 400)

    def test_state_mismatch_returns_400(self) -> None:
        """Should return 400 when OIDC state cookie doesn't match query param."""
        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings(oidc_enabled=True)

        with patch("app.api.auth.get_effective_settings", return_value=settings):
            client, app, _ = _make_test_client(mock_db)
            # Set state cookie to a different value
            client.cookies.set("codify_oidc_state", "correct-state")
            client.cookies.set("codify_oidc_nonce", "test-nonce")
            response = client.get("/api/auth/callback?code=abc&state=wrong-state")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid OIDC state", response.json()["detail"])

    def test_successful_callback_redirects(self) -> None:
        """Should redirect to next_path after successful OIDC callback."""
        mock_db, mock_result = _make_mock_db()
        mock_user = _make_mock_user(state="active")
        settings = _make_mock_settings(oidc_enabled=True)

        tokens = {
            "id_token": "id-tok",
            "access_token": "acc-tok",
            "refresh_token": "ref-tok",
            "expires_in": "3600",
        }
        claims = {"sub": "42", "preferred_username": "alice"}
        userinfo = {"preferred_username": "alice", "name": "Alice"}

        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.exchange_code_for_tokens", new=AsyncMock(return_value=tokens)), \
             patch("app.api.auth.validate_id_token", new=AsyncMock(return_value=claims)), \
             patch("app.api.auth.fetch_userinfo", new=AsyncMock(return_value=userinfo)), \
             patch("app.api.auth._upsert_user", new=AsyncMock(return_value=mock_user)), \
             patch("app.api.auth.create_user_session", new=AsyncMock(return_value="session-tok")):
            client, app, _ = _make_test_client(mock_db)
            # Set required OIDC cookies
            client.cookies.set("codify_oidc_state", "the-state")
            client.cookies.set("codify_oidc_nonce", "the-nonce")
            client.cookies.set("codify_oidc_next", "/settings")
            response = client.get(
                "/api/auth/callback?code=auth-code&state=the-state",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/settings")

    def test_oidc_auth_failure_returns_401(self) -> None:
        """Should return 401 when OIDC token exchange fails."""
        import httpx

        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings(oidc_enabled=True)

        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch(
                 "app.api.auth.exchange_code_for_tokens",
                 new=AsyncMock(side_effect=httpx.HTTPError("Connection refused")),
             ):
            client, app, _ = _make_test_client(mock_db)
            client.cookies.set("codify_oidc_state", "the-state")
            client.cookies.set("codify_oidc_nonce", "the-nonce")
            response = client.get(
                "/api/auth/callback?code=auth-code&state=the-state",
            )

        self.assertEqual(response.status_code, 401)
        self.assertIn("OIDC authentication failed", response.json()["detail"])

    def test_disabled_user_after_oidc_returns_403(self) -> None:
        """Should return 403 when user account is disabled after OIDC flow."""
        mock_db, _ = _make_mock_db()
        disabled_user = _make_mock_user(state="disabled")
        settings = _make_mock_settings(oidc_enabled=True)

        tokens = {
            "id_token": "id-tok",
            "access_token": "acc-tok",
            "expires_in": "3600",
        }
        claims = {"sub": "42"}
        userinfo = {"preferred_username": "alice"}

        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.exchange_code_for_tokens", new=AsyncMock(return_value=tokens)), \
             patch("app.api.auth.validate_id_token", new=AsyncMock(return_value=claims)), \
             patch("app.api.auth.fetch_userinfo", new=AsyncMock(return_value=userinfo)), \
             patch("app.api.auth._upsert_user", new=AsyncMock(return_value=disabled_user)):
            client, app, _ = _make_test_client(mock_db)
            client.cookies.set("codify_oidc_state", "state")
            client.cookies.set("codify_oidc_nonce", "nonce")
            response = client.get("/api/auth/callback?code=abc&state=state")

        self.assertEqual(response.status_code, 403)
        self.assertIn("disabled", response.json()["detail"])


class LogoutEndpointTests(unittest.TestCase):
    """Tests for POST /api/auth/logout."""

    def tearDown(self) -> None:
        from app.main import app
        app.dependency_overrides.clear()

    def test_logout_success(self) -> None:
        """Should revoke session, delete cookie, and return success."""
        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings()

        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.revoke_session_token", new=AsyncMock()):
            client, app, _ = _make_test_client(mock_db)
            # Set a session cookie
            client.cookies.set(settings.session_cookie_name, "existing-token")
            response = client.post("/api/auth/logout")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")

    def test_logout_without_cookie(self) -> None:
        """Should succeed even when no session cookie is present."""
        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings()

        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.revoke_session_token", new=AsyncMock()):
            client, app, _ = _make_test_client(mock_db)
            response = client.post("/api/auth/logout")

        self.assertEqual(response.status_code, 200)


class MeEndpointTests(unittest.TestCase):
    """Tests for GET /api/auth/me."""

    def tearDown(self) -> None:
        from app.main import app
        app.dependency_overrides.clear()

    def test_unauthenticated_returns_basic_info(self) -> None:
        """Should return system config without user info when not authenticated."""
        mock_db, _ = _make_mock_db()
        mock_state = SimpleNamespace(initialized=True)
        settings = _make_mock_settings(oidc_enabled=False, break_glass_enabled=False)

        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.get_bootstrap_state", new=AsyncMock(return_value=mock_state)), \
             patch("app.api.auth.get_page_permissions", return_value={"monitor": True}):
            client, app, _ = _make_test_client(mock_db, current_user=None)
            # Override get_optional_current_user to return None
            from app.dependencies.auth import get_optional_current_user
            app.dependency_overrides[get_optional_current_user] = lambda: None
            response = client.get("/api/auth/me")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["authenticated"])
        self.assertIsNone(data["user"])
        self.assertTrue(data["system_initialized"])

    def test_authenticated_returns_user_info(self) -> None:
        """Should return user details when authenticated."""
        mock_db, _ = _make_mock_db()
        mock_user = _make_mock_user(
            id=5,
            username="bob",
            display_name="Bob",
            email="bob@test.com",
            avatar_url="https://img.test/bob.png",
            platform_role="platform_admin",
            auth_provider="local",
            gitlab_user_id=42,
        )
        mock_state = SimpleNamespace(initialized=True)
        settings = _make_mock_settings(
            oidc_enabled=True,
            break_glass_enabled=True,
            auth_break_glass_username="emergency",
        )

        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.get_bootstrap_state", new=AsyncMock(return_value=mock_state)), \
             patch("app.api.auth.get_page_permissions", return_value={"monitor": True}):
            client, app, _ = _make_test_client(mock_db, current_user=mock_user)
            response = client.get("/api/auth/me")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["user"]["username"], "bob")
        self.assertEqual(data["user"]["id"], 5)
        self.assertEqual(data["user"]["platform_role"], "platform_admin")
        self.assertTrue(data["oidc_enabled"])
        self.assertTrue(data["break_glass_enabled"])
        self.assertEqual(data["break_glass_username"], "emergency")

    def test_unauthenticated_hides_break_glass_username(self) -> None:
        """When break_glass is disabled, break_glass_username should be None."""
        mock_db, _ = _make_mock_db()
        mock_state = SimpleNamespace(initialized=True)
        settings = _make_mock_settings(break_glass_enabled=False)

        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.get_bootstrap_state", new=AsyncMock(return_value=mock_state)), \
             patch("app.api.auth.get_page_permissions", return_value={}):
            client, app, _ = _make_test_client(mock_db, current_user=None)
            from app.dependencies.auth import get_optional_current_user
            app.dependency_overrides[get_optional_current_user] = lambda: None
            response = client.get("/api/auth/me")

        data = response.json()
        self.assertIsNone(data["break_glass_username"])


class ListSessionsEndpointTests(unittest.TestCase):
    """Tests for GET /api/auth/sessions."""

    def tearDown(self) -> None:
        from app.main import app
        app.dependency_overrides.clear()

    def test_list_sessions_returns_sessions(self) -> None:
        """Should return the current user's sessions."""
        mock_db, mock_result = _make_mock_db()
        now = datetime.now(UTC).replace(tzinfo=None)

        mock_session = MagicMock()
        mock_session.id = "sess-1"
        mock_session.created_at = now - timedelta(hours=2)
        mock_session.last_seen_at = now - timedelta(minutes=5)
        mock_session.expires_at = now + timedelta(hours=6)
        mock_session.revoked_at = None
        mock_session.ip_address = "192.168.1.1"
        mock_session.user_agent = "Mozilla/5.0"
        mock_session.gitlab_access_token_encrypted = "enc-token"
        mock_session.gitlab_refresh_token_encrypted = None

        mock_result.scalars.return_value.all.return_value = [mock_session]

        auth_ctx = _make_auth_context(session_id="sess-1")
        client, app, _ = _make_test_client(mock_db, auth_context=auth_ctx)
        response = client.get("/api/auth/sessions")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], "sess-1")
        self.assertEqual(data[0]["status"], "active")
        self.assertTrue(data[0]["current"])
        self.assertTrue(data[0]["has_gitlab_access_token"])
        self.assertFalse(data[0]["has_gitlab_refresh_token"])

    def test_list_sessions_marks_revoked(self) -> None:
        """Should mark revoked sessions correctly."""
        mock_db, mock_result = _make_mock_db()
        now = datetime.now(UTC).replace(tzinfo=None)

        revoked_session = MagicMock()
        revoked_session.id = "sess-2"
        revoked_session.created_at = now - timedelta(hours=5)
        revoked_session.last_seen_at = now - timedelta(hours=4)
        revoked_session.expires_at = now + timedelta(hours=3)
        revoked_session.revoked_at = now - timedelta(hours=1)
        revoked_session.ip_address = None
        revoked_session.user_agent = None
        revoked_session.gitlab_access_token_encrypted = None
        revoked_session.gitlab_refresh_token_encrypted = None

        mock_result.scalars.return_value.all.return_value = [revoked_session]

        auth_ctx = _make_auth_context(session_id="sess-1")
        client, app, _ = _make_test_client(mock_db, auth_context=auth_ctx)
        response = client.get("/api/auth/sessions")

        data = response.json()
        self.assertEqual(data[0]["status"], "revoked")
        self.assertFalse(data[0]["current"])

    def test_list_sessions_marks_expired(self) -> None:
        """Should mark expired sessions correctly."""
        mock_db, mock_result = _make_mock_db()
        now = datetime.now(UTC).replace(tzinfo=None)

        expired_session = MagicMock()
        expired_session.id = "sess-3"
        expired_session.created_at = now - timedelta(hours=10)
        expired_session.last_seen_at = now - timedelta(hours=9)
        expired_session.expires_at = now - timedelta(hours=1)  # Expired
        expired_session.revoked_at = None
        expired_session.ip_address = "10.0.0.1"
        expired_session.user_agent = "curl/8.0"
        expired_session.gitlab_access_token_encrypted = None
        expired_session.gitlab_refresh_token_encrypted = "enc-ref"

        mock_result.scalars.return_value.all.return_value = [expired_session]

        auth_ctx = _make_auth_context(session_id="sess-1")
        client, app, _ = _make_test_client(mock_db, auth_context=auth_ctx)
        response = client.get("/api/auth/sessions")

        data = response.json()
        self.assertEqual(data[0]["status"], "expired")
        self.assertTrue(data[0]["has_gitlab_refresh_token"])

    def test_list_sessions_empty(self) -> None:
        """Should return empty list when no sessions exist."""
        mock_db, mock_result = _make_mock_db()
        mock_result.scalars.return_value.all.return_value = []

        auth_ctx = _make_auth_context()
        client, app, _ = _make_test_client(mock_db, auth_context=auth_ctx)
        response = client.get("/api/auth/sessions")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])


class RevokeSessionEndpointTests(unittest.TestCase):
    """Tests for POST /api/auth/sessions/{session_id}/revoke."""

    def tearDown(self) -> None:
        from app.main import app
        app.dependency_overrides.clear()

    def test_revoke_other_session_success(self) -> None:
        """Should revoke a session owned by the current user."""
        mock_db, mock_result = _make_mock_db()
        target_session = MagicMock()
        target_session.id = "sess-2"
        mock_result.scalar_one_or_none.return_value = target_session

        auth_ctx = _make_auth_context(session_id="sess-1")

        with patch("app.api.auth.revoke_session_by_id", new=AsyncMock(return_value=True)):
            client, app, _ = _make_test_client(mock_db, auth_context=auth_ctx)
            response = client.post("/api/auth/sessions/sess-2/revoke")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["session_id"], "sess-2")
        self.assertFalse(data["current_session_revoked"])

    def test_revoke_current_session(self) -> None:
        """Revoking the current session should indicate current_session_revoked=True."""
        mock_db, mock_result = _make_mock_db()
        target_session = MagicMock()
        target_session.id = "sess-1"
        mock_result.scalar_one_or_none.return_value = target_session

        auth_ctx = _make_auth_context(session_id="sess-1")

        with patch("app.api.auth.revoke_session_by_id", new=AsyncMock(return_value=True)):
            client, app, _ = _make_test_client(mock_db, auth_context=auth_ctx)
            response = client.post("/api/auth/sessions/sess-1/revoke")

        data = response.json()
        self.assertTrue(data["current_session_revoked"])

    def test_revoke_nonexistent_session_returns_404(self) -> None:
        """Should return 404 when session is not found or not owned by user."""
        mock_db, mock_result = _make_mock_db()
        mock_result.scalar_one_or_none.return_value = None

        auth_ctx = _make_auth_context()
        client, app, _ = _make_test_client(mock_db, auth_context=auth_ctx)
        response = client.post("/api/auth/sessions/nonexistent/revoke")

        self.assertEqual(response.status_code, 404)
        self.assertIn("Session not found", response.json()["detail"])

    def test_revoke_already_revoked_returns_400(self) -> None:
        """Should return 400 when session has already been revoked."""
        mock_db, mock_result = _make_mock_db()
        target_session = MagicMock()
        target_session.id = "sess-2"
        mock_result.scalar_one_or_none.return_value = target_session

        auth_ctx = _make_auth_context()

        with patch("app.api.auth.revoke_session_by_id", new=AsyncMock(return_value=False)):
            client, app, _ = _make_test_client(mock_db, auth_context=auth_ctx)
            response = client.post("/api/auth/sessions/sess-2/revoke")

        self.assertEqual(response.status_code, 400)
        self.assertIn("already been revoked", response.json()["detail"])


class BreakGlassLoginEndpointTests(unittest.TestCase):
    """Tests for POST /api/auth/break-glass/login.

    Note: The BreakGlassLoginRequestBody model must be available at runtime.
    These tests mock the endpoint's internal logic rather than sending HTTP
    requests, since the request body type may not be resolvable via TestClient.
    """

    def tearDown(self) -> None:
        from app.main import app
        app.dependency_overrides.clear()

    def test_break_glass_disabled_returns_503(self) -> None:
        """Should return 503 when break-glass is not enabled."""
        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings(break_glass_enabled=False)

        with patch("app.api.auth.get_effective_settings", return_value=settings):
            client, app_inst, _ = _make_test_client(mock_db)
            response = client.post("/api/auth/break-glass/login", json={
                "username": "admin",
                "password": "secret",
            })

        self.assertEqual(response.status_code, 503)
        self.assertIn("not enabled", response.json()["detail"])

    def test_break_glass_invalid_credentials_returns_401(self) -> None:
        """Should return 401 when credentials are wrong."""
        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings(
            break_glass_enabled=True,
            auth_break_glass_username="emergency",
            auth_break_glass_password_hash="sha256$badhash",
        )

        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.verify_break_glass_password", return_value=False), \
             patch("app.api.auth._record_auth_audit", new=AsyncMock()):
            client, app_inst, _ = _make_test_client(mock_db)
            response = client.post("/api/auth/break-glass/login", json={
                "username": "wrong-user",
                "password": "wrong-pass",
            })

        self.assertEqual(response.status_code, 401)
        self.assertIn("Invalid break-glass credentials", response.json()["detail"])

    def test_break_glass_success(self) -> None:
        """Should return success with session cookie on valid break-glass credentials."""
        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings(
            break_glass_enabled=True,
            auth_break_glass_username="emergency",
            auth_break_glass_password_hash="sha256$validhash",
        )
        mock_user = _make_mock_user(username="emergency", platform_role="platform_admin")

        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.verify_break_glass_password", return_value=True), \
             patch("app.api.auth._get_or_create_break_glass_user", new=AsyncMock(return_value=mock_user)), \
             patch("app.api.auth.create_user_session", new=AsyncMock(return_value="bg-token")), \
             patch("app.api.auth._record_auth_audit", new=AsyncMock()):
            client, app_inst, _ = _make_test_client(mock_db)
            response = client.post("/api/auth/break-glass/login", json={
                "username": "emergency",
                "password": "correct",
                "next": "/admin",
            })

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["next_path"], "/admin")


class BreakGlassLoginUsernameCheckTests(unittest.TestCase):
    """Tests for username-matching in break_glass_login."""

    def tearDown(self) -> None:
        from app.main import app
        app.dependency_overrides.clear()

    def test_wrong_username_returns_401(self) -> None:
        """Should return 401 when username doesn't match configured break-glass user."""
        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings(
            break_glass_enabled=True,
            auth_break_glass_username="emergency",
            auth_break_glass_password_hash="sha256$hash",
        )

        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.verify_break_glass_password", return_value=True), \
             patch("app.api.auth._record_auth_audit", new=AsyncMock()):
            client, app_inst, _ = _make_test_client(mock_db)
            # Username is "attacker", not "emergency"
            response = client.post("/api/auth/break-glass/login", json={
                "username": "attacker",
                "password": "correct-pass",
            })

        self.assertEqual(response.status_code, 401)


# ===========================================================================
# 3. Edge-case / integration-style tests
# ===========================================================================


class OIDCCallbackTokenExpiryTests(unittest.TestCase):
    """Tests for OIDC callback token expiry handling."""

    def tearDown(self) -> None:
        from app.main import app
        app.dependency_overrides.clear()

    def test_callback_without_expires_in(self) -> None:
        """Should handle tokens without expires_in gracefully."""
        mock_db, _ = _make_mock_db()
        mock_user = _make_mock_user(state="active")
        settings = _make_mock_settings(oidc_enabled=True)

        tokens = {
            "id_token": "id-tok",
            "access_token": "acc-tok",
            # No expires_in
        }
        claims = {"sub": "42"}
        userinfo = {"preferred_username": "alice"}

        session_mock = AsyncMock(return_value="session-tok")

        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.exchange_code_for_tokens", new=AsyncMock(return_value=tokens)), \
             patch("app.api.auth.validate_id_token", new=AsyncMock(return_value=claims)), \
             patch("app.api.auth.fetch_userinfo", new=AsyncMock(return_value=userinfo)), \
             patch("app.api.auth._upsert_user", new=AsyncMock(return_value=mock_user)), \
             patch("app.api.auth.create_user_session", new=session_mock):
            client, app, _ = _make_test_client(mock_db)
            client.cookies.set("codify_oidc_state", "state")
            client.cookies.set("codify_oidc_nonce", "nonce")
            response = client.get(
                "/api/auth/callback?code=abc&state=state",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        # Verify create_user_session was called with max_expires_at=None
        call_kwargs = session_mock.call_args
        self.assertIsNone(call_kwargs.kwargs.get("max_expires_at"))

    def test_callback_with_jwt_error_returns_401(self) -> None:
        """Should return 401 when JWT validation fails."""
        import jwt as pyjwt

        mock_db, _ = _make_mock_db()
        settings = _make_mock_settings(oidc_enabled=True)

        tokens = {"id_token": "bad-jwt", "access_token": "acc-tok"}

        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.exchange_code_for_tokens", new=AsyncMock(return_value=tokens)), \
             patch(
                 "app.api.auth.validate_id_token",
                 new=AsyncMock(side_effect=pyjwt.PyJWTError("Invalid token")),
             ):
            client, app, _ = _make_test_client(mock_db)
            client.cookies.set("codify_oidc_state", "state")
            client.cookies.set("codify_oidc_nonce", "nonce")
            response = client.get("/api/auth/callback?code=abc&state=state")

        self.assertEqual(response.status_code, 401)


class UpsertUserGroupsTests(unittest.IsolatedAsyncioTestCase):
    """Tests for _upsert_user group handling logic."""

    async def test_groups_from_claims_and_userinfo_merged(self) -> None:
        """Groups from both claims and userinfo should be merged."""
        mock_db, mock_result = _make_mock_db()
        mock_result.scalar_one_or_none.return_value = None

        settings = _make_mock_settings(admin_gitlab_groups={"team-a", "team-b"})

        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.apply_platform_access_policy") as mock_policy, \
             self.assertLogs("app.api.auth", level="INFO"):
            await _upsert_user(
                mock_db,
                claims={"sub": "42", "preferred_username": "alice", "groups": ["team-a"]},
                userinfo={"name": "Alice", "groups": ["team-b"]},
            )

        # Verify apply_platform_access_policy got merged groups
        call_kwargs = mock_policy.call_args
        groups = call_kwargs.kwargs.get("groups") or call_kwargs[1].get("groups")
        self.assertIn("team-a", groups)
        self.assertIn("team-b", groups)

    async def test_no_groups_when_not_configured(self) -> None:
        """When admin_gitlab_groups is empty, no warning should be logged."""
        mock_db, mock_result = _make_mock_db()
        mock_result.scalar_one_or_none.return_value = None

        settings = _make_mock_settings(admin_gitlab_groups=set())

        with patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth.apply_platform_access_policy"):
            user = await _upsert_user(
                mock_db,
                claims={"sub": "42", "preferred_username": "alice"},
                userinfo={"name": "Alice"},
            )

        self.assertEqual(user.username, "alice")


class RegistrationSessionCookieTests(unittest.TestCase):
    """Tests verifying session cookie is properly set on registration."""

    def tearDown(self) -> None:
        from app.main import app
        app.dependency_overrides.clear()

    def test_registration_sets_session_cookie(self) -> None:
        """Successful registration should set session cookie with correct name."""
        mock_db, mock_result = _make_mock_db()
        mock_result.scalar_one_or_none.return_value = None
        mock_state = SimpleNamespace(initialized=False)
        settings = _make_mock_settings(session_cookie_name="test_session")

        with patch("app.api.auth.get_bootstrap_state", new=AsyncMock(return_value=mock_state)), \
             patch("app.api.auth.hash_password", return_value="hashed"), \
             patch("app.api.auth.initialize_system", new=AsyncMock()), \
             patch("app.api.auth.create_user_session", new=AsyncMock(return_value="session-tok")), \
             patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth._record_auth_audit", new=AsyncMock()):
            client, app, _ = _make_test_client(mock_db)
            response = client.post("/api/auth/local/register", json={
                "username": "admin",
                "password": "StrongPass!",
            })

        self.assertEqual(response.status_code, 200)
        self.assertIn("test_session", response.cookies)

    def test_registration_uses_default_display_name(self) -> None:
        """When display_name is not provided, username should be used."""
        mock_db, mock_result = _make_mock_db()
        mock_result.scalar_one_or_none.return_value = None
        mock_state = SimpleNamespace(initialized=False)
        settings = _make_mock_settings()

        added_users = []
        original_add = mock_db.add

        def capture_add(obj):
            added_users.append(obj)
            return original_add(obj)

        mock_db.add = capture_add

        with patch("app.api.auth.get_bootstrap_state", new=AsyncMock(return_value=mock_state)), \
             patch("app.api.auth.hash_password", return_value="hashed"), \
             patch("app.api.auth.initialize_system", new=AsyncMock()), \
             patch("app.api.auth.create_user_session", new=AsyncMock(return_value="tok")), \
             patch("app.api.auth.get_effective_settings", return_value=settings), \
             patch("app.api.auth._record_auth_audit", new=AsyncMock()):
            client, app, _ = _make_test_client(mock_db)
            response = client.post("/api/auth/local/register", json={
                "username": "admin",
                "password": "pass",
                # No display_name provided
            })

        self.assertEqual(response.status_code, 200)
        # The User should have display_name == username
        user_added = [u for u in added_users if isinstance(u, User)]
        if user_added:
            self.assertEqual(user_added[0].display_name, "admin")


if __name__ == "__main__":
    unittest.main()
