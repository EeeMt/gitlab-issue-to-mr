"""Unit tests for projects API endpoints (backend/app/api/projects.py).

Targets all lines, specifically missed lines: 25, 28-31, 47-50.
"""

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from app.config import get_settings, reset_runtime_config

# ── Env helpers ─────────────────────────────────────────────────────
_ORIG_ENC_KEY = os.environ.get("CONFIG_ENCRYPTION_KEY")


def _ensure_env():
    os.environ.setdefault("CONFIG_ENCRYPTION_KEY", "unit-test-config-key")
    get_settings.cache_clear()
    reset_runtime_config()


def _restore_env():
    reset_runtime_config()
    if _ORIG_ENC_KEY is None:
        os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
    else:
        os.environ["CONFIG_ENCRYPTION_KEY"] = _ORIG_ENC_KEY
    get_settings.cache_clear()


# ── Mock helpers ────────────────────────────────────────────────────

SAMPLE_PROJECTS = [
    {"id": 1, "name": "project-alpha", "path_with_namespace": "group/project-alpha"},
    {"id": 2, "name": "project-beta", "path_with_namespace": "group/project-beta"},
]


def _make_test_client(*, is_unrestricted=True, accessible_projects=None):
    """Build a TestClient with dependency overrides for projects endpoints."""
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.dependencies.auth import require_authenticated_context
    from app.dependencies.project_access import (
        ProjectAccessScope,
        require_project_access_scope,
    )
    from app.main import app

    mock_db = MagicMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(all=MagicMock(return_value=[]))
        )
    )
    mock_db.get = AsyncMock(return_value=None)
    mock_db.commit = AsyncMock()

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db

    # Auth context - override require_authenticated_context
    async def mock_auth_context(request=None, auth_context=None):
        return SimpleNamespace(
            user=SimpleNamespace(
                id=1, username="alice", platform_role="platform_admin"
            ),
            session=None,
            gitlab_access_token=None,
            gitlab_refresh_token=None,
        )

    app.dependency_overrides[require_authenticated_context] = mock_auth_context

    # Project access scope - use constructor args
    scope = ProjectAccessScope(
        is_unrestricted=is_unrestricted,
        accessible_projects=accessible_projects or [],
    )
    app.dependency_overrides[require_project_access_scope] = lambda: scope

    client = TestClient(app, raise_server_exceptions=False)
    return client, app, mock_db


class ListProjectsTests(unittest.TestCase):
    """Tests for GET /projects endpoint."""

    def setUp(self):
        _ensure_env()

    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()
        _restore_env()

    # ── Unrestricted user – uses cached projects (line 27) ──────────

    @patch(
        "app.api.projects._get_cached_projects",
        new_callable=AsyncMock,
        return_value=SAMPLE_PROJECTS,
    )
    def test_list_projects_unrestricted_returns_cached(self, mock_cached):
        """Unrestricted user gets projects from cache (line 27)."""
        client, app, _ = _make_test_client(is_unrestricted=True)

        response = client.get("/api/projects")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["name"], "project-alpha")
        mock_cached.assert_awaited_once()

    # ── Restricted user – returns accessible_projects (line 25) ─────

    def test_list_projects_restricted_returns_scope_projects(self):
        """Restricted user gets only their accessible projects (line 25)."""
        restricted_projects = [
            {"id": 2, "name": "project-beta", "path_with_namespace": "group/project-beta"}
        ]
        client, app, _ = _make_test_client(
            is_unrestricted=False, accessible_projects=restricted_projects
        )

        response = client.get("/api/projects")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], 2)

    # ── Cache failure – falls back to gitlab client (lines 28-31) ───

    @patch("app.api.projects.get_gitlab_client")
    @patch(
        "app.api.projects._get_cached_projects",
        new_callable=AsyncMock,
        side_effect=RuntimeError("cache miss"),
    )
    def test_list_projects_cache_failure_falls_back(
        self, mock_cached, mock_get_client
    ):
        """Cache failure falls back to direct GitLab client call (lines 28-31)."""
        mock_gitlab = MagicMock()
        mock_gitlab.get_projects.return_value = SAMPLE_PROJECTS
        mock_get_client.return_value = mock_gitlab

        client, app, _ = _make_test_client(is_unrestricted=True)

        response = client.get("/api/projects")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        mock_get_client.assert_called_once()
        mock_gitlab.get_projects.assert_called_once()

    def test_project_ci_auto_repair_availability_configured(self):
        """The selected-project endpoint reports a configured webhook."""
        client, app, mock_db = _make_test_client(is_unrestricted=True)

        settings = MagicMock(
            backend_url="https://backend.example.com",
            gitlab_url="https://gitlab.example.com",
            gitlab_admin_token="glpat-test",
        )
        target_url = "https://backend.example.com/api/webhook/gitlab"
        mock_gitlab = MagicMock()

        def get_project_hooks(project_id):
            self.assertEqual(mock_db.commit.await_count, 1)
            return [
                {
                    "id": 10,
                    "url": target_url,
                    "enable_ssl_verification": True,
                    "merge_requests_events": True,
                    "pipeline_events": True,
                }
            ]

        mock_gitlab.get_project_hooks.side_effect = get_project_hooks

        with patch(
            "app.api.projects.load_runtime_config_from_db",
            new=AsyncMock(),
        ):
            with patch(
                "app.api.projects.get_effective_settings",
                return_value=settings,
            ):
                with patch(
                    "app.api.projects.has_project_webhook_secret",
                    new=AsyncMock(return_value=True),
                ):
                    with patch("app.api.projects.GitLabClient") as mock_client_class:
                        mock_client_class.return_value = mock_gitlab
                        mock_client_class._normalize_hook_url = lambda url: url.rstrip("/")
                        response = client.get(
                            "/api/projects/1/ci-auto-repair-availability"
                        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["project_id"], 1)
        self.assertTrue(data["ci_auto_repair_available"])
        self.assertEqual(data["webhook_status"], "configured")
        self.assertEqual(data["webhook_status_issues"], [])
        mock_gitlab.get_project_hooks.assert_called_once_with(1)
        mock_db.commit.assert_awaited_once()
        mock_gitlab.close.assert_called_once()

    def test_project_ci_auto_repair_availability_needs_attention(self):
        """Missing pipeline events disable CI auto-repair for the selected project."""
        client, app, mock_db = _make_test_client(is_unrestricted=True)

        settings = MagicMock(
            backend_url="https://backend.example.com",
            gitlab_url="https://gitlab.example.com",
            gitlab_admin_token="glpat-test",
        )
        target_url = "https://backend.example.com/api/webhook/gitlab"
        mock_gitlab = MagicMock()
        mock_gitlab.get_project_hooks.return_value = [
            {
                "id": 20,
                "url": target_url,
                "enable_ssl_verification": True,
                "merge_requests_events": True,
                "pipeline_events": False,
            }
        ]

        with patch(
            "app.api.projects.load_runtime_config_from_db",
            new=AsyncMock(),
        ):
            with patch(
                "app.api.projects.get_effective_settings",
                return_value=settings,
            ):
                with patch(
                    "app.api.projects.has_project_webhook_secret",
                    new=AsyncMock(return_value=True),
                ):
                    with patch("app.api.projects.GitLabClient") as mock_client_class:
                        mock_client_class.return_value = mock_gitlab
                        mock_client_class._normalize_hook_url = lambda url: url.rstrip("/")
                        response = client.get(
                            "/api/projects/2/ci-auto-repair-availability"
                        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["ci_auto_repair_available"])
        self.assertEqual(data["webhook_status"], "needs_attention")
        self.assertEqual(
            data["webhook_status_issues"],
            ["pipeline_events_disabled"],
        )
        mock_gitlab.close.assert_called_once()

    def test_project_ci_auto_repair_availability_unavailable(self):
        """Invalid system webhook settings fail closed."""
        client, app, _ = _make_test_client(is_unrestricted=True)
        settings = MagicMock(
            backend_url="",
            gitlab_url="",
            gitlab_admin_token="",
        )

        with patch(
            "app.api.projects.load_runtime_config_from_db",
            new=AsyncMock(),
        ):
            with patch(
                "app.api.projects.get_effective_settings",
                return_value=settings,
            ):
                response = client.get(
                    "/api/projects/1/ci-auto-repair-availability"
                )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["ci_auto_repair_available"])
        self.assertEqual(data["webhook_status"], "error")
        self.assertEqual(
            data["webhook_status_issues"],
            ["webhook_status_unavailable"],
        )

    def test_project_ci_auto_repair_availability_requires_project_access(self):
        """Users cannot inspect webhook status for inaccessible projects."""
        client, app, _ = _make_test_client(
            is_unrestricted=False,
            accessible_projects=[
                {"id": 99, "name": "other", "path_with_namespace": "group/other"}
            ],
        )

        response = client.get("/api/projects/1/ci-auto-repair-availability")

        self.assertEqual(response.status_code, 403)


class ListBranchesTests(unittest.TestCase):
    """Tests for GET /projects/{project_id}/branches endpoint."""

    def setUp(self):
        _ensure_env()

    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()
        _restore_env()

    # ── Successful branch listing (lines 47-50) ────────────────────

    @patch("app.api.projects.get_gitlab_client")
    def test_list_branches_success(self, mock_get_client):
        """GET /projects/1/branches returns branch list (lines 47-50)."""
        mock_gitlab = MagicMock()
        mock_gitlab.get_branches.return_value = [
            {"name": "main"},
            {"name": "develop"},
        ]
        mock_get_client.return_value = mock_gitlab

        # Unrestricted scope allows any project
        client, app, _ = _make_test_client(is_unrestricted=True)

        response = client.get("/api/projects/1/branches")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        mock_gitlab.get_branches.assert_called_once_with(1)

    # ── Restricted user with access (lines 47-50) ──────────────────

    @patch("app.api.projects.get_gitlab_client")
    def test_list_branches_restricted_with_access(self, mock_get_client):
        """Restricted user with project access can list branches (lines 47-50)."""
        mock_gitlab = MagicMock()
        mock_gitlab.get_branches.return_value = [{"name": "main"}]
        mock_get_client.return_value = mock_gitlab

        client, app, _ = _make_test_client(
            is_unrestricted=False,
            accessible_projects=[
                {"id": 42, "name": "proj", "path_with_namespace": "g/proj"}
            ],
        )

        response = client.get("/api/projects/42/branches")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)

    # ── Restricted user without access (line 47 – require_project_access) ─

    def test_list_branches_restricted_without_access(self):
        """Restricted user without project access gets 403 (line 47)."""
        client, app, _ = _make_test_client(
            is_unrestricted=False,
            accessible_projects=[
                {"id": 99, "name": "other", "path_with_namespace": "g/other"}
            ],
        )

        response = client.get("/api/projects/1/branches")

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
