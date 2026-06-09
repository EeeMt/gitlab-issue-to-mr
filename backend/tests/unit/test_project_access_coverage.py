#!/usr/bin/env python3
"""Additional unit tests to increase coverage for project_access dependency.

Targets previously uncovered lines: 97, 100-103, 118-153, 160, 203-246.
"""

import asyncio
import os
import sys
import time
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import HTTPException

from app.dependencies.auth import AuthContext
from app.dependencies.project_access import (
    ProjectAccessScope,
    _fetch_and_cache_projects,
    _project_access_cache,
    _project_access_refresh_tasks,
    _refresh_auth_context_tokens,
    require_project_access,
    require_project_access_scope,
)
from app.models import User, UserSession


def _make_user(uid: int = 10, role: str = "platform_user", username: str = "testuser") -> User:
    """Create a minimal User for testing."""
    return User(
        id=uid,
        oidc_sub=str(uid),
        gitlab_user_id=uid,
        username=username,
        platform_role=role,
    )


def _make_session(sid: str = "sess-cov", uid: int = 10, expires_at: datetime | None = None) -> UserSession:
    """Create a minimal UserSession for testing."""
    session = UserSession(
        id=sid,
        user_id=uid,
        session_token_hash="hash",
    )
    session.expires_at = expires_at
    return session


def _make_auth_context(
    *,
    uid: int = 10,
    role: str = "platform_user",
    username: str = "testuser",
    session_id: str = "sess-cov",
    access_token: str | None = "gl-token",
    refresh_token: str | None = "gl-refresh",
    session_expires_at: datetime | None = None,
) -> AuthContext:
    """Build an AuthContext with sensible defaults."""
    if session_expires_at is None:
        session_expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
    return AuthContext(
        user=_make_user(uid=uid, role=role, username=username),
        session=_make_session(sid=session_id, uid=uid, expires_at=session_expires_at),
        gitlab_access_token=access_token,
        gitlab_refresh_token=refresh_token,
    )


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    """Create an httpx.HTTPStatusError with a given status code."""
    request = httpx.Request("GET", "https://gitlab.example.com/api")
    response = httpx.Response(status_code=status_code, request=request)
    return httpx.HTTPStatusError(f"HTTP {status_code}", request=request, response=response)


def _settings(oidc_enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(oidc_enabled=oidc_enabled)


# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------
_PATCH_SETTINGS = "app.dependencies.project_access.get_effective_settings"
_PATCH_FETCH_PROJECTS = "app.dependencies.project_access.get_accessible_projects_for_oauth_token"
_PATCH_EXCHANGE_REFRESH = "app.dependencies.project_access.exchange_refresh_token"
_PATCH_UPDATE_SESSION = "app.dependencies.project_access.update_session_gitlab_tokens"
_PATCH_ASYNC_SESSION = "app.dependencies.project_access.AsyncSessionLocal"


def _make_mock_db_session():
    """Return (mock_asl_patch_target_value, mock_db) for mocking AsyncSessionLocal."""
    mock_db = MagicMock()
    mock_db.commit = AsyncMock()
    mock_asl = MagicMock()
    mock_asl.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_asl.return_value.__aexit__ = AsyncMock(return_value=None)
    return mock_asl, mock_db


class TestProjectAccessScopeDataclass(unittest.TestCase):
    """Tests for the ProjectAccessScope dataclass properties."""

    def test_accessible_project_ids_returns_set_of_ints(self) -> None:
        """accessible_project_ids should return a set of integer project IDs."""
        scope = ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[{"id": 1}, {"id": "2"}, {"id": 3}],
        )
        self.assertEqual(scope.accessible_project_ids, {1, 2, 3})

    def test_allows_unrestricted_always_true(self) -> None:
        """Unrestricted scope allows any project."""
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        self.assertTrue(scope.allows(999))

    def test_allows_restricted_checks_membership(self) -> None:
        """Restricted scope only allows listed projects."""
        scope = ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[{"id": 5}],
        )
        self.assertTrue(scope.allows(5))
        self.assertFalse(scope.allows(6))


class TestRequireProjectAccess(unittest.TestCase):
    """Tests for the require_project_access helper."""

    def test_allows_accessible_project(self) -> None:
        """Should not raise for an accessible project."""
        scope = ProjectAccessScope(is_unrestricted=False, accessible_projects=[{"id": 42}])
        require_project_access(42, scope)  # should not raise

    def test_rejects_inaccessible_project(self) -> None:
        """Should raise 403 for a project not in the scope."""
        scope = ProjectAccessScope(is_unrestricted=False, accessible_projects=[{"id": 42}])
        with self.assertRaises(HTTPException) as ctx:
            require_project_access(99, scope)
        self.assertEqual(ctx.exception.status_code, 403)


class TestFetchAndCacheProjects(unittest.IsolatedAsyncioTestCase):
    """Tests for the _fetch_and_cache_projects internal helper."""

    def setUp(self) -> None:
        _project_access_cache.clear()
        _project_access_refresh_tasks.clear()

    def tearDown(self) -> None:
        _project_access_cache.clear()
        _project_access_refresh_tasks.clear()

    async def test_fetch_populates_cache(self) -> None:
        """_fetch_and_cache_projects should populate the cache for the session."""
        projects = [{"id": 1, "name": "p1"}]
        with patch(_PATCH_FETCH_PROJECTS, AsyncMock(return_value=projects)):
            result = await _fetch_and_cache_projects("s1", "token", time.time() + 600)

        self.assertEqual(result, projects)
        self.assertIn("s1", _project_access_cache)
        cached_expires, cached_projects = _project_access_cache["s1"]
        self.assertEqual(cached_projects, projects)
        self.assertGreater(cached_expires, time.time())

    async def test_fetch_cleans_up_refresh_task(self) -> None:
        """_fetch_and_cache_projects should remove the in-flight task entry."""
        _project_access_refresh_tasks["s2"] = MagicMock()  # type: ignore[assignment]
        with patch(_PATCH_FETCH_PROJECTS, AsyncMock(return_value=[])):
            await _fetch_and_cache_projects("s2", "token", time.time() + 600)
        self.assertNotIn("s2", _project_access_refresh_tasks)


class TestRequireProjectAccessScopeCachePaths(unittest.IsolatedAsyncioTestCase):
    """Cover the fresh-cache and stale-cache branches (lines 97, 100-103)."""

    def setUp(self) -> None:
        _project_access_cache.clear()
        _project_access_refresh_tasks.clear()

    def tearDown(self) -> None:
        _project_access_cache.clear()
        _project_access_refresh_tasks.clear()

    async def test_fresh_cache_returns_immediately(self) -> None:
        """Line 97: When cache is fresh, return cached projects without calling GitLab."""
        ctx = _make_auth_context(session_id="sess-fresh")
        cached_projects = [{"id": 77, "name": "cached"}]
        _project_access_cache["sess-fresh"] = (time.time() + 999, cached_projects)

        mock_fetch = AsyncMock()
        with patch(_PATCH_SETTINGS, return_value=_settings()), \
             patch(_PATCH_FETCH_PROJECTS, mock_fetch):
            scope = await require_project_access_scope(ctx)

        self.assertFalse(scope.is_unrestricted)
        self.assertEqual(scope.accessible_projects, cached_projects)
        mock_fetch.assert_not_called()

    async def test_stale_cache_returns_stale_and_triggers_background_refresh(self) -> None:
        """Lines 100-103: When cache is stale, return stale data and spawn a background task."""
        ctx = _make_auth_context(session_id="sess-stale")
        stale_projects = [{"id": 88, "name": "stale"}]
        # Expired 10 seconds ago
        _project_access_cache["sess-stale"] = (time.time() - 10, stale_projects)

        fresh_projects = [{"id": 88, "name": "stale"}, {"id": 89, "name": "new"}]
        mock_fetch = AsyncMock(return_value=fresh_projects)

        with patch(_PATCH_SETTINGS, return_value=_settings()), \
             patch(_PATCH_FETCH_PROJECTS, mock_fetch):
            scope = await require_project_access_scope(ctx)
            # Allow the background task to run
            await asyncio.sleep(0.05)

        # Should return stale data immediately
        self.assertEqual(scope.accessible_projects, stale_projects)

    async def test_stale_cache_does_not_duplicate_refresh_tasks(self) -> None:
        """Lines 101-102: If a refresh task is already running, don't spawn another."""
        ctx = _make_auth_context(session_id="sess-dedup")
        _project_access_cache["sess-dedup"] = (time.time() - 10, [{"id": 1}])

        # Simulate an existing in-flight task that's not done
        existing_task = MagicMock()
        existing_task.done.return_value = False
        _project_access_refresh_tasks["sess-dedup"] = existing_task

        with patch(_PATCH_SETTINGS, return_value=_settings()), \
             patch(_PATCH_FETCH_PROJECTS, AsyncMock(return_value=[])):
            scope = await require_project_access_scope(ctx)

        # Should return stale data and NOT replace the in-flight task
        self.assertEqual(scope.accessible_projects, [{"id": 1}])
        # The existing task should still be in the dict (not replaced)
        self.assertIs(_project_access_refresh_tasks.get("sess-dedup"), existing_task)

    async def test_stale_cache_replaces_completed_refresh_task(self) -> None:
        """Line 102: If the existing refresh task is done, spawn a new one."""
        ctx = _make_auth_context(session_id="sess-done")
        _project_access_cache["sess-done"] = (time.time() - 10, [{"id": 1}])

        done_task = MagicMock()
        done_task.done.return_value = True
        _project_access_refresh_tasks["sess-done"] = done_task

        with patch(_PATCH_SETTINGS, return_value=_settings()), \
             patch(_PATCH_FETCH_PROJECTS, AsyncMock(return_value=[])):
            await require_project_access_scope(ctx)
            await asyncio.sleep(0.05)

        # A new task should have been created (replacing the done one)
        self.assertIsNot(_project_access_refresh_tasks.get("sess-done"), done_task)

    async def test_session_without_expires_at_uses_default_ttl(self) -> None:
        """Line 92-93: When session.expires_at is None, use default TTL."""
        ctx = _make_auth_context(session_id="sess-no-exp", session_expires_at=None)
        ctx.session.expires_at = None

        with patch(_PATCH_SETTINGS, return_value=_settings()), \
             patch(_PATCH_FETCH_PROJECTS, AsyncMock(return_value=[{"id": 1}])):
            scope = await require_project_access_scope(ctx)

        self.assertFalse(scope.is_unrestricted)
        self.assertEqual(scope.accessible_project_ids, {1})


class TestRequireProjectAccessScopeErrorPaths(unittest.IsolatedAsyncioTestCase):
    """Cover cold-cache error handling branches (lines 118-153)."""

    def setUp(self) -> None:
        _project_access_cache.clear()
        _project_access_refresh_tasks.clear()

    def tearDown(self) -> None:
        _project_access_cache.clear()
        _project_access_refresh_tasks.clear()

    async def test_cold_cache_401_triggers_refresh_and_retry_succeeds(self) -> None:
        """Lines 118-127: Cold cache → 401 → refresh succeeds → retry fetch succeeds →
        returns valid ProjectAccessScope with the retried projects.

        This covers lines 122-127 (the inner try block with successful retry).
        """
        ctx = _make_auth_context(session_id="sess-retry-ok", refresh_token="rt")
        projects = [{"id": 50}]
        mock_asl, mock_db = _make_mock_db_session()

        call_count = 0

        async def fetch_side_effect(token: str) -> list:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _http_status_error(401)
            return projects

        with patch(_PATCH_SETTINGS, return_value=_settings()), \
             patch(_PATCH_FETCH_PROJECTS, AsyncMock(side_effect=fetch_side_effect)), \
             patch(_PATCH_EXCHANGE_REFRESH, AsyncMock(return_value={
                 "access_token": "new-token", "refresh_token": "new-rt", "expires_in": "3600",
             })), \
             patch(_PATCH_UPDATE_SESSION, AsyncMock()), \
             patch(_PATCH_ASYNC_SESSION, mock_asl):
            scope = await require_project_access_scope(ctx)

        self.assertFalse(scope.is_unrestricted)
        self.assertEqual(scope.accessible_projects, projects)

    async def test_cold_cache_403_retry_fails_401_raises_unauthorized(self) -> None:
        """Lines 128-133: Cold cache → 403 → refresh → retry → 401 → 401 HTTPException."""
        ctx = _make_auth_context(session_id="sess-retry-401", refresh_token="rt")
        mock_asl, mock_db = _make_mock_db_session()

        with patch(_PATCH_SETTINGS, return_value=_settings()), \
             patch(_PATCH_FETCH_PROJECTS, AsyncMock(side_effect=_http_status_error(403))), \
             patch(_PATCH_EXCHANGE_REFRESH, AsyncMock(return_value={
                 "access_token": "new-token", "expires_in": "3600",
             })), \
             patch(_PATCH_UPDATE_SESSION, AsyncMock()), \
             patch(_PATCH_ASYNC_SESSION, mock_asl):
            with self.assertRaises(HTTPException) as exc_ctx:
                await require_project_access_scope(ctx)

        self.assertEqual(exc_ctx.exception.status_code, 401)
        self.assertIn("refresh failed", exc_ctx.exception.detail)

    async def test_cold_cache_401_retry_fails_500_raises_502(self) -> None:
        """Lines 134-137: Cold cache → 401 → refresh → retry → 500 → 502 HTTPException."""
        ctx = _make_auth_context(session_id="sess-retry-500", refresh_token="rt")
        mock_asl, mock_db = _make_mock_db_session()

        call_count = 0

        async def fetch_side_effect(token: str) -> list:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _http_status_error(401)
            raise _http_status_error(500)

        with patch(_PATCH_SETTINGS, return_value=_settings()), \
             patch(_PATCH_FETCH_PROJECTS, AsyncMock(side_effect=fetch_side_effect)), \
             patch(_PATCH_EXCHANGE_REFRESH, AsyncMock(return_value={
                 "access_token": "new-token", "expires_in": "3600",
             })), \
             patch(_PATCH_UPDATE_SESSION, AsyncMock()), \
             patch(_PATCH_ASYNC_SESSION, mock_asl):
            with self.assertRaises(HTTPException) as exc_ctx:
                await require_project_access_scope(ctx)

        self.assertEqual(exc_ctx.exception.status_code, 502)

    async def test_cold_cache_401_retry_fails_network_error_raises_502(self) -> None:
        """Lines 138-142: Cold cache → 401 → refresh → retry → HTTPError → 502."""
        ctx = _make_auth_context(session_id="sess-retry-net", refresh_token="rt")
        mock_asl, mock_db = _make_mock_db_session()

        call_count = 0

        async def fetch_side_effect(token: str) -> list:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _http_status_error(401)
            raise httpx.ConnectError("Connection refused")

        with patch(_PATCH_SETTINGS, return_value=_settings()), \
             patch(_PATCH_FETCH_PROJECTS, AsyncMock(side_effect=fetch_side_effect)), \
             patch(_PATCH_EXCHANGE_REFRESH, AsyncMock(return_value={
                 "access_token": "new-token", "expires_in": "3600",
             })), \
             patch(_PATCH_UPDATE_SESSION, AsyncMock()), \
             patch(_PATCH_ASYNC_SESSION, mock_asl):
            with self.assertRaises(HTTPException) as exc_ctx:
                await require_project_access_scope(ctx)

        self.assertEqual(exc_ctx.exception.status_code, 502)
        self.assertIn("refreshing project access", exc_ctx.exception.detail)

    async def test_cold_cache_401_refresh_fails_raises_unauthorized(self) -> None:
        """Lines 143-147: Cold cache → 401 → refresh returns False → 401 HTTPException."""
        ctx = _make_auth_context(session_id="sess-no-refresh", refresh_token=None)

        with patch(_PATCH_SETTINGS, return_value=_settings()), \
             patch(_PATCH_FETCH_PROJECTS, AsyncMock(side_effect=_http_status_error(401))):
            with self.assertRaises(HTTPException) as exc_ctx:
                await require_project_access_scope(ctx)

        self.assertEqual(exc_ctx.exception.status_code, 401)
        self.assertIn("refresh is unavailable", exc_ctx.exception.detail)

    async def test_cold_cache_500_raises_502(self) -> None:
        """Lines 148-151: Cold cache → non-401/403 HTTPStatusError → 502."""
        ctx = _make_auth_context(session_id="sess-500")

        with patch(_PATCH_SETTINGS, return_value=_settings()), \
             patch(_PATCH_FETCH_PROJECTS, AsyncMock(side_effect=_http_status_error(500))):
            with self.assertRaises(HTTPException) as exc_ctx:
                await require_project_access_scope(ctx)

        self.assertEqual(exc_ctx.exception.status_code, 502)
        self.assertIn("Failed to resolve", exc_ctx.exception.detail)

    async def test_cold_cache_network_error_raises_502(self) -> None:
        """Lines 152-156: Cold cache → generic HTTPError → 502."""
        ctx = _make_auth_context(session_id="sess-net-err")

        with patch(_PATCH_SETTINGS, return_value=_settings()), \
             patch(_PATCH_FETCH_PROJECTS, AsyncMock(side_effect=httpx.ConnectError("timeout"))):
            with self.assertRaises(HTTPException) as exc_ctx:
                await require_project_access_scope(ctx)

        self.assertEqual(exc_ctx.exception.status_code, 502)
        self.assertIn("Failed to reach GitLab", exc_ctx.exception.detail)


class TestRequireProjectAccessScopeSlowLogging(unittest.IsolatedAsyncioTestCase):
    """Cover the slow-request warning log (line 160)."""

    def setUp(self) -> None:
        _project_access_cache.clear()

    def tearDown(self) -> None:
        _project_access_cache.clear()

    async def test_slow_request_logs_warning(self) -> None:
        """Line 160: When elapsed > 1.0s, a warning is logged."""
        ctx = _make_auth_context(session_id="sess-slow")
        projects = [{"id": 1}]


        call_count = 0

        def fake_time() -> float:
            nonlocal call_count
            call_count += 1
            # First call (t_start) returns 0, subsequent calls return 2.0+
            if call_count == 1:
                return 1000.0
            return 1002.0  # 2 seconds later

        with patch(_PATCH_SETTINGS, return_value=_settings()), \
             patch(_PATCH_FETCH_PROJECTS, AsyncMock(return_value=projects)), \
             patch("app.dependencies.project_access.time") as mock_time_mod, \
             self.assertLogs("app.dependencies.project_access", level="WARNING") as log:
            mock_time_mod.time = fake_time
            scope = await require_project_access_scope(ctx)

        self.assertFalse(scope.is_unrestricted)
        self.assertTrue(any("SLOW" in msg for msg in log.output))


class TestRefreshAuthContextTokens(unittest.IsolatedAsyncioTestCase):
    """Cover _refresh_auth_context_tokens paths (lines 203-246)."""

    def setUp(self) -> None:
        _project_access_cache.clear()

    def tearDown(self) -> None:
        _project_access_cache.clear()

    async def test_no_refresh_token_returns_false(self) -> None:
        """Line 181-187: If no refresh token is available, return False early."""
        ctx = _make_auth_context(refresh_token=None)
        result = await _refresh_auth_context_tokens(ctx)
        self.assertFalse(result)

    async def test_unexpected_http_status_error_is_reraised(self) -> None:
        """Lines 203-209: HTTPStatusError with non-400/401/403 status is reraised."""
        ctx = _make_auth_context(session_id="sess-reraise", refresh_token="rt")
        error = _http_status_error(500)

        with patch(_PATCH_EXCHANGE_REFRESH, AsyncMock(side_effect=error)):
            with self.assertRaises(httpx.HTTPStatusError) as exc_ctx:
                await _refresh_auth_context_tokens(ctx)

        self.assertEqual(exc_ctx.exception.response.status_code, 500)

    async def test_generic_http_error_is_reraised(self) -> None:
        """Lines 210-216: Generic HTTPError (network error) is reraised."""
        ctx = _make_auth_context(session_id="sess-http-err", refresh_token="rt")

        with patch(_PATCH_EXCHANGE_REFRESH, AsyncMock(side_effect=httpx.ConnectError("DNS failure"))):
            with self.assertRaises(httpx.ConnectError):
                await _refresh_auth_context_tokens(ctx)

    async def test_exchange_returns_no_access_token_revokes_session(self) -> None:
        """Lines 218-228: Exchange succeeds but returns no access_token → revoke session."""
        ctx = _make_auth_context(session_id="sess-no-at", refresh_token="rt")
        mock_asl, mock_db = _make_mock_db_session()

        # Seed cache to verify it gets cleared
        _project_access_cache["sess-no-at"] = (time.time() + 600, [{"id": 1}])

        with patch(_PATCH_EXCHANGE_REFRESH, AsyncMock(return_value={"refresh_token": "rt2"})), \
             patch(_PATCH_ASYNC_SESSION, mock_asl):
            result = await _refresh_auth_context_tokens(ctx)

        self.assertFalse(result)
        self.assertIsNotNone(ctx.session.revoked_at)
        mock_db.commit.assert_awaited_once()
        self.assertNotIn("sess-no-at", _project_access_cache)

    async def test_successful_refresh_updates_tokens_and_clears_cache(self) -> None:
        """Lines 230-246: Successful token refresh updates context and session."""
        ctx = _make_auth_context(session_id="sess-ok", refresh_token="old-rt")
        mock_asl, mock_db = _make_mock_db_session()

        # Seed cache to verify it gets cleared
        _project_access_cache["sess-ok"] = (time.time() + 600, [{"id": 1}])

        tokens_response = {
            "access_token": "new-at",
            "refresh_token": "new-rt",
            "expires_in": "7200",
        }

        with patch(_PATCH_EXCHANGE_REFRESH, AsyncMock(return_value=tokens_response)), \
             patch(_PATCH_UPDATE_SESSION, AsyncMock()) as mock_update, \
             patch(_PATCH_ASYNC_SESSION, mock_asl):
            result = await _refresh_auth_context_tokens(ctx)

        self.assertTrue(result)
        self.assertEqual(ctx.gitlab_access_token, "new-at")
        self.assertEqual(ctx.gitlab_refresh_token, "new-rt")
        self.assertNotIn("sess-ok", _project_access_cache)

        # Verify update_session_gitlab_tokens was called correctly
        mock_update.assert_awaited_once()
        call_kwargs = mock_update.call_args
        self.assertEqual(call_kwargs.kwargs["gitlab_access_token"], "new-at")
        self.assertEqual(call_kwargs.kwargs["gitlab_refresh_token"], "new-rt")
        self.assertNotIn("max_expires_at", call_kwargs.kwargs)

    async def test_successful_refresh_without_new_refresh_token_keeps_old(self) -> None:
        """Line 230: When exchange doesn't return refresh_token, keep old one."""
        ctx = _make_auth_context(session_id="sess-keep-rt", refresh_token="old-rt")
        mock_asl, mock_db = _make_mock_db_session()

        tokens_response = {
            "access_token": "new-at",
            # No refresh_token returned
            "expires_in": "3600",
        }

        with patch(_PATCH_EXCHANGE_REFRESH, AsyncMock(return_value=tokens_response)), \
             patch(_PATCH_UPDATE_SESSION, AsyncMock()) as mock_update, \
             patch(_PATCH_ASYNC_SESSION, mock_asl):
            result = await _refresh_auth_context_tokens(ctx)

        self.assertTrue(result)
        # Should keep old refresh token
        self.assertEqual(ctx.gitlab_refresh_token, "old-rt")
        mock_update.assert_awaited_once()
        self.assertEqual(mock_update.call_args.kwargs["gitlab_refresh_token"], "old-rt")

    async def test_successful_refresh_without_expires_in(self) -> None:
        """Successful token refresh without expires_in should still update tokens."""
        ctx = _make_auth_context(session_id="sess-no-exp", refresh_token="rt")
        mock_asl, mock_db = _make_mock_db_session()

        tokens_response = {
            "access_token": "new-at",
            # No expires_in
        }

        with patch(_PATCH_EXCHANGE_REFRESH, AsyncMock(return_value=tokens_response)), \
             patch(_PATCH_UPDATE_SESSION, AsyncMock()) as mock_update, \
             patch(_PATCH_ASYNC_SESSION, mock_asl):
            result = await _refresh_auth_context_tokens(ctx)

        self.assertTrue(result)
        mock_update.assert_awaited_once()
        self.assertNotIn("max_expires_at", mock_update.call_args.kwargs)

    async def test_refresh_on_400_revokes_session(self) -> None:
        """Lines 191-201: HTTPStatusError with 400 status revokes session."""
        ctx = _make_auth_context(session_id="sess-400", refresh_token="rt")
        mock_asl, mock_db = _make_mock_db_session()
        error = _http_status_error(400)

        with patch(_PATCH_EXCHANGE_REFRESH, AsyncMock(side_effect=error)), \
             patch(_PATCH_ASYNC_SESSION, mock_asl):
            result = await _refresh_auth_context_tokens(ctx)

        self.assertFalse(result)
        self.assertIsNotNone(ctx.session.revoked_at)
        mock_db.commit.assert_awaited_once()

    async def test_refresh_on_403_revokes_session(self) -> None:
        """Lines 191-201: HTTPStatusError with 403 status revokes session."""
        ctx = _make_auth_context(session_id="sess-403", refresh_token="rt")
        mock_asl, mock_db = _make_mock_db_session()
        error = _http_status_error(403)

        _project_access_cache["sess-403"] = (time.time() + 600, [{"id": 1}])

        with patch(_PATCH_EXCHANGE_REFRESH, AsyncMock(side_effect=error)), \
             patch(_PATCH_ASYNC_SESSION, mock_asl):
            result = await _refresh_auth_context_tokens(ctx)

        self.assertFalse(result)
        self.assertIsNotNone(ctx.session.revoked_at)
        self.assertNotIn("sess-403", _project_access_cache)


class TestRequireProjectAccessScopeOidcDisabled(unittest.IsolatedAsyncioTestCase):
    """Cover the OIDC-disabled path (line 73)."""

    async def test_oidc_disabled_returns_unrestricted(self) -> None:
        """Line 72-73: When OIDC is disabled, scope is unrestricted."""
        ctx = _make_auth_context()
        with patch(_PATCH_SETTINGS, return_value=_settings(oidc_enabled=False)):
            scope = await require_project_access_scope(ctx)
        self.assertTrue(scope.is_unrestricted)

    async def test_no_auth_context_returns_unrestricted(self) -> None:
        """Line 72-73: When auth_context is None, scope is unrestricted."""
        with patch(_PATCH_SETTINGS, return_value=_settings(oidc_enabled=True)):
            scope = await require_project_access_scope(auth_context=None)
        self.assertTrue(scope.is_unrestricted)


class TestRequireProjectAccessScopeTokenRefreshOnMissing(unittest.IsolatedAsyncioTestCase):
    """Cover the missing-token refresh attempt (lines 78-84)."""

    def setUp(self) -> None:
        _project_access_cache.clear()

    def tearDown(self) -> None:
        _project_access_cache.clear()

    async def test_missing_token_refreshed_successfully_continues(self) -> None:
        """Lines 78-80: When access token is missing but refresh succeeds, proceed."""
        ctx = _make_auth_context(session_id="sess-refresh-ok", access_token=None, refresh_token="rt")

        async def mock_refresh(auth_ctx) -> bool:
            auth_ctx.gitlab_access_token = "refreshed-token"
            return True

        projects = [{"id": 99}]

        with patch(_PATCH_SETTINGS, return_value=_settings()), \
             patch("app.dependencies.project_access._refresh_auth_context_tokens",
                   AsyncMock(side_effect=mock_refresh)), \
             patch(_PATCH_FETCH_PROJECTS, AsyncMock(return_value=projects)):
            scope = await require_project_access_scope(ctx)

        self.assertEqual(scope.accessible_project_ids, {99})


if __name__ == "__main__":
    unittest.main()
