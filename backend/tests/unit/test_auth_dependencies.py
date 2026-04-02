#!/usr/bin/env python3
"""Unit tests for auth dependency helpers."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.requests import Request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.dependencies.auth import get_optional_auth_context


class AuthDependencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_optional_auth_context_refreshes_runtime_config_before_reading_settings(self) -> None:
        request = Request({"type": "http", "headers": [], "query_string": b""})
        mock_db = MagicMock()
        mock_db.execute = AsyncMock()

        user = SimpleNamespace(id=1, platform_role="platform_user")
        session = SimpleNamespace(id="session-1")

        with patch(
            "app.dependencies.auth.load_runtime_config_from_db",
            new=AsyncMock(),
        ) as load_runtime_config_mock, patch(
            "app.dependencies.auth.get_effective_settings",
            return_value=SimpleNamespace(oidc_enabled=True, session_cookie_name="codify_session"),
        ), patch(
            "app.dependencies.auth.resolve_session_authentication",
            new=AsyncMock(return_value=SimpleNamespace(user=user, session=session, failure_detail=None)),
        ), patch(
            "app.dependencies.auth.get_gitlab_access_token_from_session",
            return_value=None,
        ), patch(
            "app.dependencies.auth.get_gitlab_refresh_token_from_session",
            return_value=None,
        ):
            request._cookies = {"codify_session": "token-123"}
            result = await get_optional_auth_context(request=request, db=mock_db)

        load_runtime_config_mock.assert_awaited_once_with(mock_db)
        self.assertIsNotNone(result)
        self.assertEqual(result.user, user)
        self.assertEqual(result.session, session)


if __name__ == "__main__":
    unittest.main()
