#!/usr/bin/env python3
"""Unit tests for project-scoped access helpers."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import HTTPException

from app.dependencies.auth import AuthContext
from app.dependencies.project_access import (
    ProjectAccessScope,
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
