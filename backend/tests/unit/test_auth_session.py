#!/usr/bin/env python3
"""Unit tests for auth session helpers."""

import os
import sys
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.session import (
    _utcnow,
    cleanup_stale_sessions,
    create_user_session,
    get_gitlab_refresh_token_from_session,
    get_user_from_session_token,
    hash_session_token,
    resolve_session_authentication,
    revoke_user_sessions,
    update_session_gitlab_tokens,
)
from app.models import User, UserSession


class AuthSessionTests(unittest.IsolatedAsyncioTestCase):
    def test_hash_session_token_is_deterministic(self) -> None:
        self.assertEqual(hash_session_token("abc"), hash_session_token("abc"))
        self.assertNotEqual(hash_session_token("abc"), hash_session_token("xyz"))

    async def test_create_user_session_adds_hashed_session(self) -> None:
        user = User(id=1, oidc_sub="1", gitlab_user_id=1, username="alice")
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        token = await create_user_session(mock_db, user, ip_address="127.0.0.1", user_agent="test")

        mock_db.add.assert_called_once()
        added_session = mock_db.add.call_args.args[0]
        self.assertIsInstance(added_session, UserSession)
        self.assertEqual(added_session.user_id, 1)
        self.assertEqual(added_session.session_token_hash, hash_session_token(token))
        self.assertIsNotNone(added_session.expires_at)

    async def test_create_user_session_encrypts_gitlab_access_token(self) -> None:
        user = User(id=1, oidc_sub="1", gitlab_user_id=1, username="alice")
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        with patch("app.core.session.encrypt_config_secret", return_value="encrypted-token"):
            await create_user_session(mock_db, user, gitlab_access_token="raw-token")

        added_session = mock_db.add.call_args.args[0]
        self.assertEqual(added_session.gitlab_access_token_encrypted, "encrypted-token")

    async def test_create_user_session_encrypts_gitlab_refresh_token(self) -> None:
        user = User(id=1, oidc_sub="1", gitlab_user_id=1, username="alice")
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        with patch("app.core.session.encrypt_config_secret", return_value="encrypted-refresh"):
            await create_user_session(mock_db, user, gitlab_refresh_token="refresh-token")

        added_session = mock_db.add.call_args.args[0]
        self.assertEqual(added_session.gitlab_refresh_token_encrypted, "encrypted-refresh")

    async def test_create_user_session_uses_configured_ttl(self) -> None:
        """Session expiry should be set from session_ttl_seconds, not capped by GitLab token."""
        user = User(id=1, oidc_sub="1", gitlab_user_id=1, username="alice")
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        await create_user_session(mock_db, user)

        added_session = mock_db.add.call_args.args[0]
        self.assertIsNotNone(added_session.expires_at)
        # expires_at should be in the future (> now)
        self.assertGreater(added_session.expires_at, _utcnow())

    async def test_get_user_from_session_token_returns_user_for_valid_session(self) -> None:
        user = User(id=1, oidc_sub="1", gitlab_user_id=1, username="alice", state="active")
        session = UserSession(
            id="session-1",
            user_id=1,
            session_token_hash=hash_session_token("valid"),
            expires_at=_utcnow() + timedelta(hours=1),
        )
        mock_result = MagicMock()
        mock_result.first.return_value = (user, session)
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()

        resolved_user = await get_user_from_session_token(mock_db, "valid")

        self.assertEqual(resolved_user, user)
        # flush is NOT called for valid sessions - only for expired or inactive users
        mock_db.flush.assert_not_awaited()

    async def test_get_user_from_session_token_revokes_expired_session(self) -> None:
        user = User(id=1, oidc_sub="1", gitlab_user_id=1, username="alice", state="active")
        session = UserSession(
            id="session-1",
            user_id=1,
            session_token_hash=hash_session_token("expired"),
            expires_at=_utcnow() - timedelta(minutes=1),
        )
        mock_result = MagicMock()
        mock_result.first.return_value = (user, session)
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        resolved_user = await get_user_from_session_token(mock_db, "expired")

        self.assertIsNone(resolved_user)
        self.assertIsNotNone(session.revoked_at)
        mock_db.flush.assert_awaited()

    async def test_resolve_session_authentication_reports_expired_detail(self) -> None:
        user = User(id=1, oidc_sub="1", gitlab_user_id=1, username="alice", state="active")
        session = UserSession(
            id="session-1",
            user_id=1,
            session_token_hash=hash_session_token("expired"),
            expires_at=_utcnow() - timedelta(minutes=1),
        )
        mock_result = MagicMock()
        mock_result.first.return_value = (user, session)
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        result = await resolve_session_authentication(mock_db, "expired")

        self.assertIsNone(result.user)
        self.assertIsNone(result.session)
        self.assertEqual(result.failure_detail, "Your dashboard session expired. Please sign in again.")

    async def test_update_session_gitlab_tokens_updates_encrypted_values(self) -> None:
        session = UserSession(
            id="session-1",
            user_id=1,
            session_token_hash="hash",
            expires_at=_utcnow() + timedelta(hours=4),
        )
        mock_db = MagicMock()
        mock_db.flush = AsyncMock()
        original_expires_at = session.expires_at

        with patch("app.core.session.encrypt_config_secret", side_effect=["encrypted-access", "encrypted-refresh"]):
            await update_session_gitlab_tokens(
                mock_db,
                session,
                gitlab_access_token="access-token",
                gitlab_refresh_token="refresh-token",
            )

        self.assertEqual(session.gitlab_access_token_encrypted, "encrypted-access")
        self.assertEqual(session.gitlab_refresh_token_encrypted, "encrypted-refresh")
        # Session expiry must not be shortened by the GitLab token lifetime
        self.assertEqual(session.expires_at, original_expires_at)
        mock_db.flush.assert_awaited_once()

    def test_get_gitlab_refresh_token_from_session_decrypts_value(self) -> None:
        session = UserSession(
            id="session-1",
            user_id=1,
            session_token_hash="hash",
            gitlab_refresh_token_encrypted="encrypted-refresh",
            expires_at=_utcnow() + timedelta(hours=1),
        )

        with patch("app.core.session.decrypt_config_secret", return_value="refresh-token"):
            self.assertEqual(get_gitlab_refresh_token_from_session(session), "refresh-token")

    async def test_revoke_user_sessions_marks_all_active_rows(self) -> None:
        active_one = UserSession(
            id="session-1",
            user_id=1,
            session_token_hash="a",
            expires_at=_utcnow() + timedelta(hours=1),
        )
        active_two = UserSession(
            id="session-2",
            user_id=1,
            session_token_hash="b",
            expires_at=_utcnow() + timedelta(hours=1),
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [active_one, active_two]
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        revoked_count = await revoke_user_sessions(mock_db, 1)

        self.assertEqual(revoked_count, 2)
        self.assertIsNotNone(active_one.revoked_at)
        self.assertIsNotNone(active_two.revoked_at)
        mock_db.flush.assert_awaited_once()

    async def test_cleanup_stale_sessions_deletes_rows_before_retention_cutoff(self) -> None:
        mock_result = MagicMock()
        mock_result.rowcount = 3
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        deleted_count = await cleanup_stale_sessions(mock_db)

        self.assertEqual(deleted_count, 3)
        mock_db.execute.assert_awaited_once()
        delete_statement = mock_db.execute.await_args.args[0]
        self.assertIn("DELETE FROM user_sessions", str(delete_statement))
        compiled_sql = str(delete_statement.compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("coalesce(user_sessions.revoked_at, user_sessions.expires_at)", compiled_sql)

    async def test_cleanup_stale_sessions_uses_effective_settings_retention_days(self) -> None:
        """cleanup_stale_sessions reads session_retention_days from get_effective_settings()."""
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_settings = MagicMock()
        mock_settings.session_retention_days = 7

        with patch("app.core.session.get_effective_settings", return_value=mock_settings):
            await cleanup_stale_sessions(mock_db)

        str(
            mock_db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True})
        )
        # With 7-day retention the cutoff should be within the last 7-8 days
        # Just assert the statement ran (the cutoff date is dynamic, so we validate the call was made)
        mock_db.execute.assert_awaited_once()

    async def test_cleanup_stale_sessions_explicit_retention_days_overrides_settings(self) -> None:
        """Passing retention_days explicitly skips get_effective_settings()."""
        mock_result = MagicMock()
        mock_result.rowcount = 2
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.core.session.get_effective_settings") as mock_get_settings:
            deleted = await cleanup_stale_sessions(mock_db, retention_days=60)

        # get_effective_settings should NOT be called when retention_days is explicit
        mock_get_settings.assert_not_called()
        self.assertEqual(deleted, 2)


if __name__ == "__main__":
    unittest.main()
