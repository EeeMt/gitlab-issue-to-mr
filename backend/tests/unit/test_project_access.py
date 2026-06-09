#!/usr/bin/env python3
"""Unit tests for project-scoped access helpers."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import HTTPException

from app.dependencies.auth import AuthContext
from app.dependencies.project_access import (
    ProjectAccessScope,
    _refresh_auth_context_tokens,
    require_project_access,
    require_project_access_scope,
)
from app.models import User, UserSession


class ProjectAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_scope_is_unrestricted(self) -> None:
        context = AuthContext(
            user=User(id=1, oidc_sub="1", gitlab_user_id=1, username="admin", platform_role="platform_admin"),
            session=UserSession(id="session-1", user_id=1, session_token_hash="hash"),
            gitlab_access_token=None,
            gitlab_refresh_token=None,
        )

        with patch(
            "app.dependencies.project_access.get_effective_settings",
            return_value=SimpleNamespace(oidc_enabled=True),
        ):
            scope = await require_project_access_scope(context)

        self.assertTrue(scope.is_unrestricted)
        self.assertTrue(scope.allows(123))

    async def test_user_scope_fetches_accessible_projects(self) -> None:
        context = AuthContext(
            user=User(id=2, oidc_sub="2", gitlab_user_id=2, username="alice", platform_role="platform_user"),
            session=UserSession(id="session-2", user_id=2, session_token_hash="hash"),
            gitlab_access_token="token-123",
            gitlab_refresh_token=None,
        )

        with patch(
            "app.dependencies.project_access.get_effective_settings",
            return_value=SimpleNamespace(oidc_enabled=True),
        ), patch(
            "app.dependencies.project_access.get_accessible_projects_for_oauth_token",
            AsyncMock(return_value=[{"id": 11, "name": "proj", "path_with_namespace": "group/proj"}]),
        ):
            scope = await require_project_access_scope(context)

        self.assertFalse(scope.is_unrestricted)
        self.assertEqual(scope.accessible_project_ids, {11})
        self.assertTrue(scope.allows(11))
        self.assertFalse(scope.allows(12))

    async def test_user_scope_requires_gitlab_token(self) -> None:
        context = AuthContext(
            user=User(id=3, oidc_sub="3", gitlab_user_id=3, username="bob", platform_role="platform_user"),
            session=UserSession(id="session-3", user_id=3, session_token_hash="hash"),
            gitlab_access_token=None,
            gitlab_refresh_token=None,
        )

        with patch(
            "app.dependencies.project_access.get_effective_settings",
            return_value=SimpleNamespace(oidc_enabled=True),
        ):
            with self.assertRaises(HTTPException) as exc:
                await require_project_access_scope(context)

        self.assertEqual(exc.exception.status_code, 401)

    async def test_refresh_logs_and_revokes_on_invalid_refresh_token(self) -> None:
        context = AuthContext(
            user=User(id=4, oidc_sub="4", gitlab_user_id=4, username="carol", platform_role="platform_user"),
            session=UserSession(id="session-4", user_id=4, session_token_hash="hash"),
            gitlab_access_token=None,
            gitlab_refresh_token="refresh-token",
        )
        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()
        response = httpx.Response(status_code=401, request=httpx.Request("POST", "https://gitlab.example.com/oauth/token"))
        error = httpx.HTTPStatusError("unauthorized", request=response.request, response=response)

        with patch(
            "app.dependencies.project_access.exchange_refresh_token",
            AsyncMock(side_effect=error),
        ), patch(
            "app.dependencies.project_access.AsyncSessionLocal",
            MagicMock(return_value=mock_db),
        ), self.assertLogs("app.dependencies.project_access", level="WARNING") as captured:
            refreshed = await _refresh_auth_context_tokens(context)

        self.assertFalse(refreshed)
        self.assertIsNotNone(context.session.revoked_at)
        mock_db.commit.assert_awaited_once()
        self.assertIn("GitLab token refresh rejected for session session-4", captured.output[0])

    def test_require_project_access_rejects_inaccessible_project(self) -> None:
        scope = ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[{"id": 7, "name": "proj", "path_with_namespace": "group/proj"}],
        )

        with self.assertRaises(HTTPException) as exc:
            require_project_access(8, scope)

        self.assertEqual(exc.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
