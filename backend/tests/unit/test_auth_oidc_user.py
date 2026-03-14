#!/usr/bin/env python3
"""Unit tests for OIDC user upsert behavior."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.api.auth import _upsert_user
from app.models import User


class OIDCUserUpsertTests(unittest.IsolatedAsyncioTestCase):
    async def test_upsert_user_warns_when_group_bootstrap_is_configured_but_groups_missing(self) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        settings = SimpleNamespace(
            admin_usernames=set(),
            admin_gitlab_groups={"platform-team"},
        )

        with patch("app.api.auth.get_effective_settings", return_value=settings), self.assertLogs(
            "app.api.auth", level="WARNING"
        ) as captured:
            user = await _upsert_user(
                mock_db,
                claims={"sub": "42", "preferred_username": "alice"},
                userinfo={"name": "Alice"},
            )

        self.assertIsInstance(user, User)
        self.assertEqual(user.username, "alice")
        self.assertIn("did not include usable GitLab groups", captured.output[0])
        mock_db.flush.assert_awaited_once()

    async def test_upsert_user_does_not_warn_when_groups_are_present(self) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        settings = SimpleNamespace(
            admin_usernames=set(),
            admin_gitlab_groups={"platform-team"},
        )

        with patch("app.api.auth.get_effective_settings", return_value=settings), self.assertLogs(
            "app.api.auth", level="INFO"
        ) as captured:
            user = await _upsert_user(
                mock_db,
                claims={"sub": "43", "preferred_username": "bob", "groups": ["platform-team"]},
                userinfo={"name": "Bob"},
            )

        self.assertIsInstance(user, User)
        self.assertEqual(user.platform_role, "platform_admin")
        self.assertTrue(any("included GitLab groups" in line for line in captured.output))


if __name__ == "__main__":
    unittest.main()
