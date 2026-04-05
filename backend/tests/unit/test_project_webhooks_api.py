#!/usr/bin/env python3
"""Unit tests for project webhook configuration API endpoints.

Tests cover:
- _is_valid_http_url helper
- _build_gitlab_webhook_target_url edge cases (invalid/empty URL)
- _validate_gitlab_webhook_ready edge cases (missing gitlab_url)
- _build_gitlab_project_webhook_status_response edge cases (SSL disabled)
- setup_gitlab_project_webhook endpoint (POST)
- get_gitlab_project_webhook_status endpoint (GET single)
- list_gitlab_project_webhook_statuses endpoint (GET all)
"""

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import HTTPException
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

def _make_mock_settings(
    backend_url="https://backend.example.com",
    gitlab_url="https://gitlab.example.com",
    gitlab_admin_token="glpat-test-token",
    gitlab_webhook_secret="test-webhook-secret",
):
    """Build a mock Settings object with the given fields."""
    settings = MagicMock()
    settings.backend_url = backend_url
    settings.gitlab_url = gitlab_url
    settings.gitlab_admin_token = gitlab_admin_token
    settings.gitlab_webhook_secret = gitlab_webhook_secret
    return settings


def _make_db_override():
    """Build a mock DB that works as an async generator override for get_db."""
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=MagicMock())
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.get = AsyncMock(return_value=None)

    async def override_db():
        yield mock_db

    return override_db, mock_db


def _make_mock_project(name="test-project", path="group/test-project"):
    """Build a mock GitLab project object."""
    project = MagicMock()
    project.name = name
    project.path_with_namespace = path
    return project


def _get_test_client():
    """Build TestClient with dependency overrides for admin auth and DB."""
    from app.main import app
    from app.database import get_db
    from app.dependencies.auth import require_admin_user, require_authenticated_user

    override_db, mock_db = _make_db_override()

    mock_admin = MagicMock()
    mock_admin.id = 1
    mock_admin.platform_role = "platform_admin"

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin_user] = lambda: mock_admin
    app.dependency_overrides[require_authenticated_user] = lambda: mock_admin

    return TestClient(app, raise_server_exceptions=False), app, mock_db


# ---------------------------------------------------------------------------
# _is_valid_http_url
# ---------------------------------------------------------------------------

class IsValidHttpUrlTests(unittest.TestCase):
    """Tests for the _is_valid_http_url helper function."""

    def _check(self, url: str) -> bool:
        from app.api.project_webhooks import _is_valid_http_url
        return _is_valid_http_url(url)

    def test_valid_http_url(self):
        """Standard http URL should be valid."""
        self.assertTrue(self._check("http://example.com"))

    def test_valid_https_url(self):
        """Standard https URL with path should be valid."""
        self.assertTrue(self._check("https://example.com/path"))

    def test_invalid_scheme_ftp(self):
        """FTP scheme should be rejected."""
        self.assertFalse(self._check("ftp://example.com"))

    def test_no_netloc_is_invalid(self):
        """Bare string without scheme/netloc should be rejected."""
        self.assertFalse(self._check("not-a-url"))

    def test_empty_string_is_invalid(self):
        """Empty string should be rejected."""
        self.assertFalse(self._check(""))


# ---------------------------------------------------------------------------
# _build_gitlab_webhook_target_url — uncovered branches
# ---------------------------------------------------------------------------

class BuildWebhookTargetUrlTests(unittest.TestCase):
    """Tests for _build_gitlab_webhook_target_url edge cases."""

    def test_valid_url_returns_webhook_path(self):
        """Valid backend_url should return the webhook callback URL."""
        from app.api.project_webhooks import _build_gitlab_webhook_target_url
        settings = MagicMock()
        settings.backend_url = "https://backend.example.com"
        result = _build_gitlab_webhook_target_url(settings)
        self.assertEqual(result, "https://backend.example.com/api/webhook/gitlab")

    def test_strips_trailing_slash(self):
        """Trailing slash on backend_url should be stripped."""
        from app.api.project_webhooks import _build_gitlab_webhook_target_url
        settings = MagicMock()
        settings.backend_url = "https://backend.example.com/"
        result = _build_gitlab_webhook_target_url(settings)
        self.assertEqual(result, "https://backend.example.com/api/webhook/gitlab")

    def test_empty_backend_url_raises_400(self):
        """Line 66: whitespace-only backend_url should raise HTTPException 400."""
        from app.api.project_webhooks import _build_gitlab_webhook_target_url
        settings = MagicMock()
        settings.backend_url = "   "
        with self.assertRaises(HTTPException) as ctx:
            _build_gitlab_webhook_target_url(settings)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("backend_url", ctx.exception.detail)

    def test_invalid_url_scheme_raises_400(self):
        """Line 66: non-http URL should raise HTTPException 400."""
        from app.api.project_webhooks import _build_gitlab_webhook_target_url
        settings = MagicMock()
        settings.backend_url = "ftp://files.example.com"
        with self.assertRaises(HTTPException) as ctx:
            _build_gitlab_webhook_target_url(settings)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_nonsense_string_raises_400(self):
        """Line 66: non-URL string should raise HTTPException 400."""
        from app.api.project_webhooks import _build_gitlab_webhook_target_url
        settings = MagicMock()
        settings.backend_url = "not-a-valid-url"
        with self.assertRaises(HTTPException) as ctx:
            _build_gitlab_webhook_target_url(settings)
        self.assertEqual(ctx.exception.status_code, 400)


# ---------------------------------------------------------------------------
# _validate_gitlab_webhook_ready — uncovered branches
# ---------------------------------------------------------------------------

class ValidateGitlabWebhookReadyTests(unittest.TestCase):
    """Tests for _validate_gitlab_webhook_ready edge cases."""

    def test_missing_gitlab_url_raises_400(self):
        """Line 76: empty gitlab_url should raise HTTPException listing the missing field."""
        from app.api.project_webhooks import _validate_gitlab_webhook_ready
        settings = MagicMock()
        settings.gitlab_url = ""
        settings.gitlab_admin_token = "glpat-test"
        settings.backend_url = "https://backend.example.com"
        with self.assertRaises(HTTPException) as ctx:
            _validate_gitlab_webhook_ready(settings)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("gitlab_url", ctx.exception.detail)

    def test_missing_admin_token_raises_400(self):
        """Empty gitlab_admin_token should raise HTTPException."""
        from app.api.project_webhooks import _validate_gitlab_webhook_ready
        settings = MagicMock()
        settings.gitlab_url = "https://gitlab.example.com"
        settings.gitlab_admin_token = "   "
        settings.backend_url = "https://backend.example.com"
        with self.assertRaises(HTTPException) as ctx:
            _validate_gitlab_webhook_ready(settings)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("gitlab_admin_token", ctx.exception.detail)

    def test_both_missing_lists_both_fields(self):
        """Both missing fields should appear in the error detail."""
        from app.api.project_webhooks import _validate_gitlab_webhook_ready
        settings = MagicMock()
        settings.gitlab_url = ""
        settings.gitlab_admin_token = ""
        settings.backend_url = "https://backend.example.com"
        with self.assertRaises(HTTPException) as ctx:
            _validate_gitlab_webhook_ready(settings)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("gitlab_url", ctx.exception.detail)
        self.assertIn("gitlab_admin_token", ctx.exception.detail)

    def test_valid_settings_returns_target_url(self):
        """Valid settings should return the webhook target URL."""
        from app.api.project_webhooks import _validate_gitlab_webhook_ready
        settings = MagicMock()
        settings.gitlab_url = "https://gitlab.example.com"
        settings.gitlab_admin_token = "glpat-test"
        settings.backend_url = "https://backend.example.com"
        result = _validate_gitlab_webhook_ready(settings)
        self.assertEqual(result, "https://backend.example.com/api/webhook/gitlab")


# ---------------------------------------------------------------------------
# _build_gitlab_project_webhook_status_response — uncovered branches
# ---------------------------------------------------------------------------

class BuildStatusResponseEdgeCaseTests(unittest.TestCase):
    """Tests for _build_gitlab_project_webhook_status_response uncovered branches."""

    def _build(self, **overrides):
        from app.api.project_webhooks import _build_gitlab_project_webhook_status_response
        defaults = dict(
            project_id=1,
            project_name="test",
            project_path_with_namespace="group/test",
            target_webhook_url="https://url.example.com/api/webhook/gitlab",
            managed_secret_configured=False,
            global_secret_fallback_configured=False,
        )
        defaults.update(overrides)
        return _build_gitlab_project_webhook_status_response(**defaults)

    def test_ssl_verification_disabled_only(self):
        """Line 118: SSL verification disabled with note_events enabled shows needs_attention."""
        resp = self._build(
            managed_secret_configured=True,
            matched_hook={
                "id": 1,
                "url": "https://url.example.com/api/webhook/gitlab",
                "note_events": True,
                "enable_ssl_verification": False,
            },
        )
        self.assertEqual(resp.status, "needs_attention")
        self.assertIn("SSL verification disabled", resp.status_detail)
        self.assertNotIn("note events", resp.status_detail)

    def test_both_note_events_and_ssl_disabled(self):
        """Both issues flagged when note_events and SSL verification are off."""
        resp = self._build(
            matched_hook={
                "id": 1,
                "url": "https://url.example.com/api/webhook/gitlab",
                "note_events": False,
                "enable_ssl_verification": False,
            },
        )
        self.assertEqual(resp.status, "needs_attention")
        self.assertIn("note events disabled", resp.status_detail)
        self.assertIn("SSL verification disabled", resp.status_detail)
        self.assertEqual(resp.secret_mode, "none")

    def test_global_secret_fallback_mode(self):
        """Secret mode should be global_fallback when only global secret is configured."""
        resp = self._build(
            managed_secret_configured=False,
            global_secret_fallback_configured=True,
            matched_hook=None,
        )
        self.assertEqual(resp.secret_mode, "global_fallback")
        self.assertEqual(resp.status, "missing")

    def test_inspection_error_takes_precedence(self):
        """Inspection error should result in 'error' status even with no matched hook."""
        resp = self._build(
            inspection_error="Connection timed out",
            matched_hook=None,
        )
        self.assertEqual(resp.status, "error")
        self.assertIn("Connection timed out", resp.status_detail)
        self.assertFalse(resp.hook_found)


# ---------------------------------------------------------------------------
# setup_gitlab_project_webhook endpoint (POST)
# ---------------------------------------------------------------------------

class SetupGitlabProjectWebhookTests(unittest.TestCase):
    """Tests for POST /api/config/gitlab/projects/{project_id}/webhook endpoint.

    Covers lines 146-172.
    """

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_setup_creates_new_secret_and_webhook(self):
        """Successfully creates a new managed secret and GitLab webhook."""
        client, app, mock_db = _get_test_client()

        mock_settings = _make_mock_settings()
        mock_project = _make_mock_project()
        mock_client_instance = MagicMock()
        mock_client_instance.get_project.return_value = mock_project
        mock_client_instance.ensure_project_webhook.return_value = {
            "action": "created",
            "hook": {"id": 123, "url": "https://backend.example.com/api/webhook/gitlab"},
        }

        with patch("app.api.project_webhooks.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.api.project_webhooks.get_effective_settings", return_value=mock_settings):
                with patch("app.api.project_webhooks.GitLabClient", return_value=mock_client_instance):
                    with patch("app.api.project_webhooks.get_project_webhook_secret", new=AsyncMock(return_value=None)):
                        with patch("app.api.project_webhooks.save_project_webhook_secret", new=AsyncMock()) as mock_save:
                            response = client.post("/api/config/gitlab/projects/42/webhook")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["action"], "created")
        self.assertEqual(data["project_id"], 42)
        self.assertEqual(data["hook_id"], 123)
        self.assertEqual(data["project_name"], "test-project")
        self.assertEqual(data["project_path_with_namespace"], "group/test-project")
        # A new secret was generated and saved
        mock_save.assert_awaited_once()
        mock_client_instance.close.assert_called_once()

    def test_setup_reuses_existing_secret(self):
        """When a managed secret already exists it should be reused, not overwritten."""
        client, app, mock_db = _get_test_client()

        mock_settings = _make_mock_settings()
        mock_project = _make_mock_project()
        mock_client_instance = MagicMock()
        mock_client_instance.get_project.return_value = mock_project
        mock_client_instance.ensure_project_webhook.return_value = {
            "action": "updated",
            "hook": {"id": 456, "url": "https://backend.example.com/api/webhook/gitlab"},
        }

        with patch("app.api.project_webhooks.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.api.project_webhooks.get_effective_settings", return_value=mock_settings):
                with patch("app.api.project_webhooks.GitLabClient", return_value=mock_client_instance):
                    with patch("app.api.project_webhooks.get_project_webhook_secret", new=AsyncMock(return_value="existing-secret")):
                        with patch("app.api.project_webhooks.save_project_webhook_secret", new=AsyncMock()) as mock_save:
                            response = client.post("/api/config/gitlab/projects/42/webhook")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["action"], "updated")
        mock_save.assert_not_awaited()

    def test_setup_gitlab_error_returns_400(self):
        """GitLab API error during setup should return 400 and close the client."""
        from gitlab.exceptions import GitlabError

        client, app, mock_db = _get_test_client()

        mock_settings = _make_mock_settings()
        mock_client_instance = MagicMock()
        mock_client_instance.get_project.side_effect = GitlabError("Project not found")

        with patch("app.api.project_webhooks.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.api.project_webhooks.get_effective_settings", return_value=mock_settings):
                with patch("app.api.project_webhooks.GitLabClient", return_value=mock_client_instance):
                    with patch("app.api.project_webhooks.get_project_webhook_secret", new=AsyncMock(return_value="secret")):
                        response = client.post("/api/config/gitlab/projects/999/webhook")

        self.assertEqual(response.status_code, 400)
        self.assertIn("GitLab webhook setup failed", response.json()["detail"])
        mock_client_instance.close.assert_called_once()

    def test_setup_httpx_error_returns_400(self):
        """httpx.HTTPError during setup should also return 400."""
        import httpx

        client, app, mock_db = _get_test_client()

        mock_settings = _make_mock_settings()
        mock_client_instance = MagicMock()
        mock_client_instance.get_project.side_effect = httpx.HTTPError("Connection refused")

        with patch("app.api.project_webhooks.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.api.project_webhooks.get_effective_settings", return_value=mock_settings):
                with patch("app.api.project_webhooks.GitLabClient", return_value=mock_client_instance):
                    with patch("app.api.project_webhooks.get_project_webhook_secret", new=AsyncMock(return_value="secret")):
                        response = client.post("/api/config/gitlab/projects/42/webhook")

        self.assertEqual(response.status_code, 400)
        self.assertIn("GitLab webhook setup failed", response.json()["detail"])

    def test_setup_ensure_webhook_error_returns_400(self):
        """Error during ensure_project_webhook should return 400."""
        from gitlab.exceptions import GitlabError

        client, app, mock_db = _get_test_client()

        mock_settings = _make_mock_settings()
        mock_project = _make_mock_project()
        mock_client_instance = MagicMock()
        mock_client_instance.get_project.return_value = mock_project
        mock_client_instance.ensure_project_webhook.side_effect = GitlabError("Hook creation failed")

        with patch("app.api.project_webhooks.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.api.project_webhooks.get_effective_settings", return_value=mock_settings):
                with patch("app.api.project_webhooks.GitLabClient", return_value=mock_client_instance):
                    with patch("app.api.project_webhooks.get_project_webhook_secret", new=AsyncMock(return_value="secret")):
                        response = client.post("/api/config/gitlab/projects/42/webhook")

        self.assertEqual(response.status_code, 400)
        mock_client_instance.close.assert_called_once()


# ---------------------------------------------------------------------------
# get_gitlab_project_webhook_status endpoint (GET single)
# ---------------------------------------------------------------------------

class GetGitlabProjectWebhookStatusTests(unittest.TestCase):
    """Tests for GET /api/config/gitlab/projects/{project_id}/webhook endpoint.

    Covers lines 189-214.
    """

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_status_hook_found_and_configured(self):
        """Hook found with note_events and SSL enabled should show 'configured'."""
        client, app, mock_db = _get_test_client()

        mock_settings = _make_mock_settings()
        mock_project = _make_mock_project()
        target_url = "https://backend.example.com/api/webhook/gitlab"

        mock_client_instance = MagicMock()
        mock_client_instance.get_project.return_value = mock_project
        mock_client_instance.get_project_hooks.return_value = [
            {"id": 10, "url": target_url, "note_events": True, "enable_ssl_verification": True},
        ]

        with patch("app.api.project_webhooks.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.api.project_webhooks.get_effective_settings", return_value=mock_settings):
                with patch("app.api.project_webhooks.GitLabClient") as MockClientClass:
                    MockClientClass.return_value = mock_client_instance
                    MockClientClass._normalize_hook_url = lambda url: url.rstrip("/")
                    with patch("app.api.project_webhooks.has_project_webhook_secret", new=AsyncMock(return_value=True)):
                        response = client.get("/api/config/gitlab/projects/42/webhook")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["project_id"], 42)
        self.assertEqual(data["status"], "configured")
        self.assertTrue(data["hook_found"])
        self.assertTrue(data["managed_secret_configured"])
        self.assertEqual(data["hook_id"], 10)
        self.assertEqual(data["project_name"], "test-project")

    def test_status_hook_not_found(self):
        """No matching hook should show 'missing' status."""
        client, app, mock_db = _get_test_client()

        mock_settings = _make_mock_settings()
        mock_project = _make_mock_project()

        mock_client_instance = MagicMock()
        mock_client_instance.get_project.return_value = mock_project
        mock_client_instance.get_project_hooks.return_value = [
            {"id": 10, "url": "https://other.example.com/webhook", "note_events": True, "enable_ssl_verification": True},
        ]

        with patch("app.api.project_webhooks.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.api.project_webhooks.get_effective_settings", return_value=mock_settings):
                with patch("app.api.project_webhooks.GitLabClient") as MockClientClass:
                    MockClientClass.return_value = mock_client_instance
                    MockClientClass._normalize_hook_url = lambda url: url.rstrip("/")
                    with patch("app.api.project_webhooks.has_project_webhook_secret", new=AsyncMock(return_value=False)):
                        response = client.get("/api/config/gitlab/projects/42/webhook")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "missing")
        self.assertFalse(data["hook_found"])
        self.assertIsNone(data["hook_id"])

    def test_status_hook_empty_list(self):
        """No hooks at all should show 'missing' status."""
        client, app, mock_db = _get_test_client()

        mock_settings = _make_mock_settings()
        mock_project = _make_mock_project()

        mock_client_instance = MagicMock()
        mock_client_instance.get_project.return_value = mock_project
        mock_client_instance.get_project_hooks.return_value = []

        with patch("app.api.project_webhooks.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.api.project_webhooks.get_effective_settings", return_value=mock_settings):
                with patch("app.api.project_webhooks.GitLabClient") as MockClientClass:
                    MockClientClass.return_value = mock_client_instance
                    MockClientClass._normalize_hook_url = lambda url: url.rstrip("/")
                    with patch("app.api.project_webhooks.has_project_webhook_secret", new=AsyncMock(return_value=False)):
                        response = client.get("/api/config/gitlab/projects/42/webhook")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "missing")

    def test_status_hook_needs_attention(self):
        """Hook with note_events disabled should show 'needs_attention'."""
        client, app, mock_db = _get_test_client()

        mock_settings = _make_mock_settings()
        mock_project = _make_mock_project()
        target_url = "https://backend.example.com/api/webhook/gitlab"

        mock_client_instance = MagicMock()
        mock_client_instance.get_project.return_value = mock_project
        mock_client_instance.get_project_hooks.return_value = [
            {"id": 10, "url": target_url, "note_events": False, "enable_ssl_verification": True},
        ]

        with patch("app.api.project_webhooks.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.api.project_webhooks.get_effective_settings", return_value=mock_settings):
                with patch("app.api.project_webhooks.GitLabClient") as MockClientClass:
                    MockClientClass.return_value = mock_client_instance
                    MockClientClass._normalize_hook_url = lambda url: url.rstrip("/")
                    with patch("app.api.project_webhooks.has_project_webhook_secret", new=AsyncMock(return_value=False)):
                        response = client.get("/api/config/gitlab/projects/42/webhook")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "needs_attention")
        self.assertIn("note events disabled", data["status_detail"])

    def test_status_gitlab_error_returns_400(self):
        """GitLab API error during status check should return 400."""
        from gitlab.exceptions import GitlabError

        client, app, mock_db = _get_test_client()

        mock_settings = _make_mock_settings()
        mock_client_instance = MagicMock()
        mock_client_instance.get_project.side_effect = GitlabError("API error")

        with patch("app.api.project_webhooks.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.api.project_webhooks.get_effective_settings", return_value=mock_settings):
                with patch("app.api.project_webhooks.GitLabClient", return_value=mock_client_instance):
                    response = client.get("/api/config/gitlab/projects/42/webhook")

        self.assertEqual(response.status_code, 400)
        self.assertIn("GitLab webhook status lookup failed", response.json()["detail"])
        mock_client_instance.close.assert_called_once()

    def test_status_global_fallback_secret_mode(self):
        """No managed secret but global secret should show secret_mode=global_fallback."""
        client, app, mock_db = _get_test_client()

        mock_settings = _make_mock_settings(gitlab_webhook_secret="global-secret")
        mock_project = _make_mock_project()
        target_url = "https://backend.example.com/api/webhook/gitlab"

        mock_client_instance = MagicMock()
        mock_client_instance.get_project.return_value = mock_project
        mock_client_instance.get_project_hooks.return_value = [
            {"id": 10, "url": target_url, "note_events": True, "enable_ssl_verification": True},
        ]

        with patch("app.api.project_webhooks.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.api.project_webhooks.get_effective_settings", return_value=mock_settings):
                with patch("app.api.project_webhooks.GitLabClient") as MockClientClass:
                    MockClientClass.return_value = mock_client_instance
                    MockClientClass._normalize_hook_url = lambda url: url.rstrip("/")
                    with patch("app.api.project_webhooks.has_project_webhook_secret", new=AsyncMock(return_value=False)):
                        response = client.get("/api/config/gitlab/projects/42/webhook")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["secret_mode"], "global_fallback")


# ---------------------------------------------------------------------------
# list_gitlab_project_webhook_statuses endpoint (GET all)
# ---------------------------------------------------------------------------

class ListGitlabProjectWebhookStatusesTests(unittest.TestCase):
    """Tests for GET /api/config/gitlab/webhooks endpoint.

    Covers lines 231-299.
    """

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_list_multiple_projects(self):
        """Returns statuses for multiple projects sorted alphabetically."""
        client, app, mock_db = _get_test_client()

        mock_settings = _make_mock_settings()
        target_url = "https://backend.example.com/api/webhook/gitlab"

        mock_client_instance = MagicMock()
        mock_client_instance.get_projects.return_value = [
            {"id": 1, "name": "project-a", "path_with_namespace": "group/project-a"},
            {"id": 2, "name": "project-b", "path_with_namespace": "group/project-b"},
        ]
        mock_client_instance.get_project_hooks.side_effect = [
            [{"id": 10, "url": target_url, "note_events": True, "enable_ssl_verification": True}],
            [],  # project-b has no hooks
        ]

        with patch("app.api.project_webhooks.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.api.project_webhooks.get_effective_settings", return_value=mock_settings):
                with patch("app.api.project_webhooks.GitLabClient") as MockClientClass:
                    MockClientClass.return_value = mock_client_instance
                    MockClientClass._normalize_hook_url = lambda url: url.rstrip("/")
                    with patch("app.api.project_webhooks.has_project_webhook_secret", new=AsyncMock(return_value=False)):
                        response = client.get("/api/config/gitlab/webhooks")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)

        pa = next(p for p in data if p["project_id"] == 1)
        pb = next(p for p in data if p["project_id"] == 2)
        self.assertEqual(pa["status"], "configured")
        self.assertEqual(pa["project_name"], "project-a")
        self.assertEqual(pb["status"], "missing")
        self.assertEqual(pb["project_name"], "project-b")
        mock_client_instance.close.assert_called_once()

    def test_list_empty_projects(self):
        """Empty project list returns empty array."""
        client, app, mock_db = _get_test_client()

        mock_settings = _make_mock_settings()

        mock_client_instance = MagicMock()
        mock_client_instance.get_projects.return_value = []

        with patch("app.api.project_webhooks.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.api.project_webhooks.get_effective_settings", return_value=mock_settings):
                with patch("app.api.project_webhooks.GitLabClient") as MockClientClass:
                    MockClientClass.return_value = mock_client_instance
                    MockClientClass._normalize_hook_url = lambda url: url.rstrip("/")
                    response = client.get("/api/config/gitlab/webhooks")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
        mock_client_instance.close.assert_called_once()

    def test_list_with_per_project_hook_inspection_error(self):
        """Per-project hook inspection error should show 'error' status for that project."""
        from gitlab.exceptions import GitlabError

        client, app, mock_db = _get_test_client()

        mock_settings = _make_mock_settings()

        mock_client_instance = MagicMock()
        mock_client_instance.get_projects.return_value = [
            {"id": 1, "name": "project-a", "path_with_namespace": "group/project-a"},
        ]
        mock_client_instance.get_project_hooks.side_effect = GitlabError("Forbidden")

        with patch("app.api.project_webhooks.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.api.project_webhooks.get_effective_settings", return_value=mock_settings):
                with patch("app.api.project_webhooks.GitLabClient") as MockClientClass:
                    MockClientClass.return_value = mock_client_instance
                    MockClientClass._normalize_hook_url = lambda url: url.rstrip("/")
                    with patch("app.api.project_webhooks.has_project_webhook_secret", new=AsyncMock(return_value=False)):
                        response = client.get("/api/config/gitlab/webhooks")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["status"], "error")
        self.assertIn("Forbidden", data[0]["status_detail"])

    def test_list_gitlab_get_projects_error_returns_400(self):
        """GitLab error when fetching projects should return 400."""
        from gitlab.exceptions import GitlabError

        client, app, mock_db = _get_test_client()

        mock_settings = _make_mock_settings()

        mock_client_instance = MagicMock()
        mock_client_instance.get_projects.side_effect = GitlabError("Connection refused")

        with patch("app.api.project_webhooks.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.api.project_webhooks.get_effective_settings", return_value=mock_settings):
                with patch("app.api.project_webhooks.GitLabClient") as MockClientClass:
                    MockClientClass.return_value = mock_client_instance
                    MockClientClass._normalize_hook_url = lambda url: url.rstrip("/")
                    response = client.get("/api/config/gitlab/webhooks")

        self.assertEqual(response.status_code, 400)
        self.assertIn("GitLab webhook status lookup failed", response.json()["detail"])
        mock_client_instance.close.assert_called_once()

    def test_list_with_managed_secret_configured(self):
        """Project with managed secret should show secret_mode=project."""
        client, app, mock_db = _get_test_client()

        mock_settings = _make_mock_settings(gitlab_webhook_secret="")
        target_url = "https://backend.example.com/api/webhook/gitlab"

        mock_client_instance = MagicMock()
        mock_client_instance.get_projects.return_value = [
            {"id": 1, "name": "project-a", "path_with_namespace": "group/project-a"},
        ]
        mock_client_instance.get_project_hooks.return_value = [
            {"id": 10, "url": target_url, "note_events": True, "enable_ssl_verification": True},
        ]

        with patch("app.api.project_webhooks.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.api.project_webhooks.get_effective_settings", return_value=mock_settings):
                with patch("app.api.project_webhooks.GitLabClient") as MockClientClass:
                    MockClientClass.return_value = mock_client_instance
                    MockClientClass._normalize_hook_url = lambda url: url.rstrip("/")
                    with patch("app.api.project_webhooks.has_project_webhook_secret", new=AsyncMock(return_value=True)):
                        response = client.get("/api/config/gitlab/webhooks")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["secret_mode"], "project")
        self.assertTrue(data[0]["managed_secret_configured"])


if __name__ == "__main__":
    unittest.main()
