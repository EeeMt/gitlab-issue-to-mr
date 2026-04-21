#!/usr/bin/env python3
"""Additional unit tests for core/session.py to improve coverage.

Targets missed lines:
- 105: resolve_session_authentication — session not found (row is None)
- 123-125: resolve_session_authentication — user.state != "active"
- 160-162: get_gitlab_access_token_from_session (both branches)
- 168: get_gitlab_refresh_token_from_session — no encrypted token
- 196-206: revoke_session_token (all branches)
- 230-236: revoke_session_by_id (all branches)
"""

import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.session import (
    _utcnow,
    get_gitlab_access_token_from_session,
    get_gitlab_refresh_token_from_session,
    hash_session_token,
    resolve_session_authentication,
    revoke_session_by_id,
    revoke_session_token,
)
from app.models import User, UserSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(user_id: int = 1, state: str = "active") -> User:
    return User(
        id=user_id,
        oidc_sub=str(user_id),
        gitlab_user_id=user_id,
        username=f"user-{user_id}",
        state=state,
    )


def _make_session(
    session_id: str = "sess-1",
    user_id: int = 1,
    token: str = "tok",
    hours_until_expiry: float = 1.0,
    revoked: bool = False,
    gitlab_access_token_encrypted: str | None = None,
    gitlab_refresh_token_encrypted: str | None = None,
) -> UserSession:
    return UserSession(
        id=session_id,
        user_id=user_id,
        session_token_hash=hash_session_token(token),
        expires_at=_utcnow() + timedelta(hours=hours_until_expiry),
        revoked_at=_utcnow() if revoked else None,
        gitlab_access_token_encrypted=gitlab_access_token_encrypted,
        gitlab_refresh_token_encrypted=gitlab_refresh_token_encrypted,
    )


# ---------------------------------------------------------------------------
# resolve_session_authentication — line 105 (session not found)
# ---------------------------------------------------------------------------

class TestResolveSessionNotFound(unittest.IsolatedAsyncioTestCase):
    """Line 105: when DB query returns no matching (user, session) row."""

    async def test_returns_failure_when_session_not_found(self) -> None:
        """Should return failure_detail about signing in again."""
        mock_result = MagicMock()
        mock_result.first.return_value = None  # no row

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await resolve_session_authentication(mock_db, "nonexistent-token")

        self.assertIsNone(result.user)
        self.assertIsNone(result.session)
        self.assertIn("not found", result.failure_detail)


# ---------------------------------------------------------------------------
# resolve_session_authentication — lines 123-125 (inactive user)
# ---------------------------------------------------------------------------

class TestResolveSessionInactiveUser(unittest.IsolatedAsyncioTestCase):
    """Lines 123-125: when user.state != 'active'."""

    async def test_revokes_session_and_reports_disabled_account(self) -> None:
        """Inactive user should trigger session revocation + appropriate failure_detail."""
        user = _make_user(state="blocked")
        session = _make_session(token="valid")

        mock_result = MagicMock()
        mock_result.first.return_value = (user, session)

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        result = await resolve_session_authentication(mock_db, "valid")

        self.assertIsNone(result.user)
        self.assertIsNone(result.session)
        self.assertIn("disabled", result.failure_detail)
        self.assertIsNotNone(session.revoked_at)
        mock_db.flush.assert_awaited()

    async def test_inactive_user_with_deactivated_state(self) -> None:
        """Any non-'active' state should be treated as disabled."""
        user = _make_user(state="deactivated")
        session = _make_session(token="t2")

        mock_result = MagicMock()
        mock_result.first.return_value = (user, session)

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        result = await resolve_session_authentication(mock_db, "t2")

        self.assertIsNone(result.user)
        self.assertIn("disabled", result.failure_detail)


# ---------------------------------------------------------------------------
# get_gitlab_access_token_from_session — lines 160-162
# ---------------------------------------------------------------------------

class TestGetGitlabAccessToken(unittest.TestCase):
    """Lines 160-162: both branches of get_gitlab_access_token_from_session."""

    def test_returns_none_when_no_encrypted_token(self) -> None:
        """Line 161: None encrypted token → return None."""
        session = _make_session(gitlab_access_token_encrypted=None)
        self.assertIsNone(get_gitlab_access_token_from_session(session))

    def test_decrypts_and_returns_token(self) -> None:
        """Line 162: encrypted token present → decrypt and return."""
        session = _make_session(gitlab_access_token_encrypted="enc-access")

        with patch("app.core.session.decrypt_config_secret", return_value="raw-access"):
            result = get_gitlab_access_token_from_session(session)

        self.assertEqual(result, "raw-access")


# ---------------------------------------------------------------------------
# get_gitlab_refresh_token_from_session — line 168
# ---------------------------------------------------------------------------

class TestGetGitlabRefreshTokenNone(unittest.TestCase):
    """Line 168: returns None when no encrypted refresh token."""

    def test_returns_none_when_no_encrypted_refresh_token(self) -> None:
        session = _make_session(gitlab_refresh_token_encrypted=None)
        self.assertIsNone(get_gitlab_refresh_token_from_session(session))


# ---------------------------------------------------------------------------
# revoke_session_token — lines 196-206
# ---------------------------------------------------------------------------

class TestRevokeSessionToken(unittest.IsolatedAsyncioTestCase):
    """Lines 196-206: revoke_session_token all branches."""

    async def test_noop_when_token_is_none(self) -> None:
        """Line 196-197: early return for None token."""
        mock_db = MagicMock()
        mock_db.execute = AsyncMock()
        await revoke_session_token(mock_db, None)
        mock_db.execute.assert_not_awaited()

    async def test_noop_when_token_is_empty(self) -> None:
        """Line 196-197: early return for empty string token."""
        mock_db = MagicMock()
        mock_db.execute = AsyncMock()
        await revoke_session_token(mock_db, "")
        mock_db.execute.assert_not_awaited()

    async def test_revokes_existing_unrevoked_session(self) -> None:
        """Lines 199-206: finds session, sets revoked_at, flushes."""
        session = _make_session(token="revoke-me", revoked=False)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = session

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        await revoke_session_token(mock_db, "revoke-me")

        self.assertIsNotNone(session.revoked_at)
        mock_db.flush.assert_awaited_once()

    async def test_noop_when_session_not_found(self) -> None:
        """Lines 203-204: no session found → no flush."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        await revoke_session_token(mock_db, "ghost-token")

        mock_db.flush.assert_not_awaited()

    async def test_noop_when_session_already_revoked(self) -> None:
        """Lines 204: session exists but already revoked → no flush."""
        session = _make_session(token="already-revoked", revoked=True)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = session

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        await revoke_session_token(mock_db, "already-revoked")

        mock_db.flush.assert_not_awaited()


# ---------------------------------------------------------------------------
# revoke_session_by_id — lines 230-236
# ---------------------------------------------------------------------------

class TestRevokeSessionById(unittest.IsolatedAsyncioTestCase):
    """Lines 230-236: revoke_session_by_id all branches."""

    async def test_returns_false_when_session_not_found(self) -> None:
        """Line 232-233: no session → return False."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        result = await revoke_session_by_id(mock_db, "nonexistent-id")

        self.assertFalse(result)
        mock_db.flush.assert_not_awaited()

    async def test_returns_false_when_session_already_revoked(self) -> None:
        """Line 232: session exists but already has revoked_at → return False."""
        session = _make_session(session_id="sess-old", revoked=True)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = session

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        result = await revoke_session_by_id(mock_db, "sess-old")

        self.assertFalse(result)
        mock_db.flush.assert_not_awaited()

    async def test_revokes_and_returns_true_for_active_session(self) -> None:
        """Lines 234-236: sets revoked_at, flushes, returns True."""
        session = _make_session(session_id="sess-active", revoked=False)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = session

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        result = await revoke_session_by_id(mock_db, "sess-active")

        self.assertTrue(result)
        self.assertIsNotNone(session.revoked_at)
        mock_db.flush.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
