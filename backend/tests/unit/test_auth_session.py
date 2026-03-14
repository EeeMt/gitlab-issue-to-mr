#!/usr/bin/env python3
"""Unit tests for auth session helpers."""

import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.session import create_user_session, get_user_from_session_token, hash_session_token
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

    async def test_get_user_from_session_token_returns_user_for_valid_session(self) -> None:
        user = User(id=1, oidc_sub="1", gitlab_user_id=1, username="alice", state="active")
        session = UserSession(
            id="session-1",
            user_id=1,
            session_token_hash=hash_session_token("valid"),
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        mock_result = MagicMock()
        mock_result.first.return_value = (user, session)
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        resolved_user = await get_user_from_session_token(mock_db, "valid")

        self.assertEqual(resolved_user, user)
        mock_db.flush.assert_awaited()

    async def test_get_user_from_session_token_revokes_expired_session(self) -> None:
        user = User(id=1, oidc_sub="1", gitlab_user_id=1, username="alice", state="active")
        session = UserSession(
            id="session-1",
            user_id=1,
            session_token_hash=hash_session_token("expired"),
            expires_at=datetime.utcnow() - timedelta(minutes=1),
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


if __name__ == "__main__":
    unittest.main()
