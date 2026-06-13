#!/usr/bin/env python3
"""Unit tests for configuration API helpers."""

import os
import sys
import unittest

from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.api._validators import _normalize_updates, _validate_config_value
from app.api.config import _serialize_effective_config
from app.api.mattermost import MattermostNotificationProfileInput
from app.api.project_webhooks import (
    _build_gitlab_project_webhook_status_response,
    _build_gitlab_webhook_target_url,
    _validate_gitlab_webhook_ready,
)
from app.config import get_settings, reset_runtime_config, set_runtime_config


class ConfigApiHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_config_encryption_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-config-key"
        get_settings.cache_clear()

    def tearDown(self) -> None:
        reset_runtime_config()
        if self._original_config_encryption_key is None:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        else:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._original_config_encryption_key
        get_settings.cache_clear()

    def test_serialize_effective_config_includes_runtime_fields_and_secret_status(self) -> None:
        set_runtime_config({
            "max_retries": 3,
            "retry_delay": 180,
            "alert_on_failure": True,
            "alert_webhook_url": "https://hooks.example.com/task-alerts",
            "anthropic_base_url": "https://llm.example.com/v1",
            "anthropic_api_key": "stored-api-key",
            "anthropic_model": "claude-sonnet-4.5",
            "gitlab_url": "https://gitlab-configured.example.com",
            "gitlab_bot_token": "stored-gitlab-token",
            "gitlab_admin_token": "stored-admin-token",
            "gitlab_webhook_secret": "stored-webhook-secret",
        })

        response = _serialize_effective_config()

        self.assertEqual(response.runtime.max_retries, 3)
        self.assertEqual(response.runtime.retry_delay, 180)
        self.assertTrue(response.runtime.alert_on_failure)
        self.assertTrue(response.runtime.alert_webhook_url_configured)
        self.assertEqual(response.runtime.anthropic_base_url, "https://llm.example.com/v1")
        self.assertTrue(response.runtime.anthropic_api_key_configured)
        self.assertEqual(response.runtime.anthropic_model, "claude-sonnet-4.5")
        self.assertEqual(response.integration.gitlab_url, "https://gitlab-configured.example.com")
        self.assertTrue(response.integration.gitlab_bot_token_configured)
        self.assertTrue(response.integration.gitlab_admin_token_configured)
        self.assertTrue(response.integration.gitlab_webhook_secret_configured)

    def test_validate_config_value_accepts_new_runtime_fields(self) -> None:
        self.assertEqual(_validate_config_value("max_retries", 2), 2)
        self.assertEqual(_validate_config_value("retry_delay", 90), 90)
        self.assertTrue(_validate_config_value("alert_on_failure", True))
        self.assertEqual(
            _validate_config_value("alert_webhook_url", "https://hooks.example.com/a"),
            "https://hooks.example.com/a",
        )
        self.assertEqual(
            _validate_config_value("anthropic_base_url", "https://llm.example.com/v1"),
            "https://llm.example.com/v1",
        )
        self.assertEqual(_validate_config_value("anthropic_model", "claude-3"), "claude-3")
        self.assertEqual(_validate_config_value("anthropic_api_key", "sk-test"), "sk-test")
        self.assertEqual(
            _validate_config_value("gitlab_url", "https://gitlab.example.com"),
            "https://gitlab.example.com",
        )
        self.assertEqual(_validate_config_value("gitlab_bot_token", "glpat-test"), "glpat-test")
        self.assertEqual(_validate_config_value("gitlab_admin_token", "glpat-admin"), "glpat-admin")
        self.assertEqual(_validate_config_value("gitlab_webhook_secret", "secret-123"), "secret-123")
        self.assertEqual(
            _validate_config_value("mattermost_server_url", "https://mattermost.example.com"),
            "https://mattermost.example.com",
        )
        self.assertEqual(_validate_config_value("mattermost_bot_token", "mm-token"), "mm-token")

    def test_validate_config_value_rejects_invalid_retry_and_url_values(self) -> None:
        with self.assertRaises(HTTPException):
            _validate_config_value("max_retries", 11)

        with self.assertRaises(HTTPException):
            _validate_config_value("retry_delay", 0)

        with self.assertRaises(HTTPException):
            _validate_config_value("alert_webhook_url", "not-a-url")

        with self.assertRaises(HTTPException):
            _validate_config_value("anthropic_base_url", "not-a-url")

        with self.assertRaises(HTTPException):
            _validate_config_value("gitlab_url", "not-a-url")

        with self.assertRaises(HTTPException):
            _validate_config_value("gitlab_bot_token", " ")

        with self.assertRaises(HTTPException):
            _validate_config_value("gitlab_admin_token", " ")

        with self.assertRaises(HTTPException):
            _validate_config_value("gitlab_webhook_secret", " ")

        with self.assertRaises(HTTPException):
            _validate_config_value("mattermost_server_url", "not-a-url")

        with self.assertRaises(HTTPException):
            _validate_config_value("mattermost_bot_token", " ")

    def test_normalize_updates_handles_runtime_clear_flags(self) -> None:
        normalized = _normalize_updates({
            "clear_alert_webhook_url": 1,
            "clear_anthropic_api_key": 0,
            "clear_gitlab_bot_token": 1,
            "clear_gitlab_admin_token": 1,
            "clear_gitlab_webhook_secret": 0,
            "clear_mattermost_bot_token": 0,
        })

        self.assertEqual(
            normalized,
            {
                "clear_alert_webhook_url": True,
                "clear_anthropic_api_key": False,
                "clear_gitlab_bot_token": True,
                "clear_gitlab_admin_token": True,
                "clear_gitlab_webhook_secret": False,
                "clear_mattermost_bot_token": False,
            },
        )

    def test_mattermost_profile_validation(self) -> None:
        payload = MattermostNotificationProfileInput(
            name=" Team Alerts ",
            target_type="channel",
            channel_id=" engineering__ai-bot ",
            mention_in_channel=True,
            event_types=["task_completed", "task_completed", "task_failed"],
            field_keys=["task_id", "status", "status"],
        )

        self.assertEqual(payload.name, "Team Alerts")
        self.assertEqual(payload.channel_id, "engineering__ai-bot")
        self.assertTrue(payload.mention_in_channel)
        self.assertEqual(payload.event_types, ["task_completed", "task_failed"])
        self.assertEqual(payload.field_keys, ["task_id", "status"])

    def test_validate_gitlab_webhook_ready_builds_target_url(self) -> None:
        set_runtime_config({
            "gitlab_url": "https://gitlab.example.com",
            "gitlab_admin_token": "glpat-admin",
        })
        settings = get_settings().model_copy(update={
            "backend_url": "https://bot.example.com/",
            "gitlab_url": "https://gitlab.example.com",
            "gitlab_admin_token": "glpat-admin",
        })

        self.assertEqual(
            _validate_gitlab_webhook_ready(settings),
            "https://bot.example.com/api/webhook/gitlab",
        )
        self.assertEqual(
            _build_gitlab_webhook_target_url(settings),
            "https://bot.example.com/api/webhook/gitlab",
        )

    def test_validate_gitlab_webhook_ready_rejects_missing_fields(self) -> None:
        settings = get_settings().model_copy(update={
            "backend_url": "https://bot.example.com",
            "gitlab_url": "https://gitlab.example.com",
            "gitlab_admin_token": "",
        })

        with self.assertRaises(HTTPException):
            _validate_gitlab_webhook_ready(settings)

    def test_build_gitlab_project_webhook_status_response_marks_configured(self) -> None:
        response = _build_gitlab_project_webhook_status_response(
            project_id=1,
            project_name="Demo",
            project_path_with_namespace="group/demo",
            target_webhook_url="https://bot.example.com/api/webhook/gitlab",
            managed_secret_configured=True,
            global_secret_fallback_configured=False,
	            matched_hook={
	                "id": 12,
	                "url": "https://bot.example.com/api/webhook/gitlab",
	                "note_events": True,
	                "enable_ssl_verification": True,
	                "merge_requests_events": True,
	                "pipeline_events": True,
	            },
	        )

        self.assertEqual(response.status, "configured")
        self.assertIsNone(response.status_detail)
        self.assertEqual(response.secret_mode, "project")
        self.assertTrue(response.hook_found)

    def test_build_gitlab_project_webhook_status_response_marks_attention_needed(self) -> None:
        response = _build_gitlab_project_webhook_status_response(
            project_id=1,
            project_name="Demo",
            project_path_with_namespace="group/demo",
            target_webhook_url="https://bot.example.com/api/webhook/gitlab",
            managed_secret_configured=False,
            global_secret_fallback_configured=True,
            matched_hook={
                "id": 12,
	                "url": "https://bot.example.com/api/webhook/gitlab",
	                "enable_ssl_verification": False,
	                "merge_requests_events": True,
	                "pipeline_events": True,
	            },
	        )

        self.assertEqual(response.status, "needs_attention")
        self.assertEqual(response.status_detail, "SSL verification disabled")
        self.assertEqual(response.secret_mode, "global_fallback")

    def test_build_gitlab_project_webhook_status_response_marks_missing_and_error(self) -> None:
        missing_response = _build_gitlab_project_webhook_status_response(
            project_id=1,
            project_name="Demo",
            project_path_with_namespace="group/demo",
            target_webhook_url="https://bot.example.com/api/webhook/gitlab",
            managed_secret_configured=False,
            global_secret_fallback_configured=False,
        )
        error_response = _build_gitlab_project_webhook_status_response(
            project_id=1,
            project_name="Demo",
            project_path_with_namespace="group/demo",
            target_webhook_url="https://bot.example.com/api/webhook/gitlab",
            managed_secret_configured=False,
            global_secret_fallback_configured=False,
            inspection_error="forbidden",
        )

        self.assertEqual(missing_response.status, "missing")
        self.assertEqual(missing_response.secret_mode, "none")
        self.assertEqual(error_response.status, "error")
        self.assertEqual(error_response.status_detail, "forbidden")


class ConfigSerializationTests(unittest.TestCase):
    """Tests for _serialize_auth_config and OIDC serialization."""

    def setUp(self) -> None:
        self._original_config_encryption_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-config-key"
        get_settings.cache_clear()

    def tearDown(self) -> None:
        reset_runtime_config()
        if self._original_config_encryption_key is None:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        else:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._original_config_encryption_key
        get_settings.cache_clear()

    def test_serialize_auth_config_redacts_oidc_secret(self) -> None:
        """When oidc_client_secret is set, oidc_client_secret_configured should be True."""
        from app.api.config import _serialize_auth_config

        settings = get_settings().model_copy(update={"oidc_client_secret": "my-secret"})
        auth_section = _serialize_auth_config(settings)

        self.assertTrue(auth_section.oidc_client_secret_configured)
        # The actual secret must NOT be present in the section
        self.assertFalse(hasattr(auth_section, "oidc_client_secret"))

    def test_serialize_auth_config_without_oidc_secret(self) -> None:
        """When oidc_client_secret is empty, oidc_client_secret_configured should be False."""
        from app.api.config import _serialize_auth_config

        settings = get_settings().model_copy(update={"oidc_client_secret": ""})
        auth_section = _serialize_auth_config(settings)

        self.assertFalse(auth_section.oidc_client_secret_configured)

    def test_validate_oidc_ready_raises_when_missing_fields(self) -> None:
        """_validate_oidc_ready should raise HTTPException when required OIDC fields are missing."""
        from app.api.config import _validate_oidc_ready

        # Empty settings — all OIDC fields are blank
        settings = get_settings().model_copy(update={
            "oidc_issuer_url": "",
            "oidc_client_id": "",
            "oidc_redirect_uri": "",
            "oidc_client_secret": "",
        })

        with self.assertRaises(HTTPException) as ctx:
            _validate_oidc_ready(settings)

        self.assertEqual(ctx.exception.status_code, 400)

    def test_validate_oidc_ready_succeeds_when_all_fields_set(self) -> None:
        """_validate_oidc_ready should not raise when all required OIDC fields are set."""
        from app.api.config import _validate_oidc_ready

        settings = get_settings().model_copy(update={
            "oidc_issuer_url": "https://idp.example.com",
            "oidc_client_id": "my-client-id",
            "oidc_redirect_uri": "https://app.example.com/callback",
            "oidc_client_secret": "my-secret",
        })

        _validate_oidc_ready(settings)  # should not raise


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Config API endpoints — GET /config, PATCH /config, POST /config/reset
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def _make_config_admin_client():
    """Build a TestClient with admin auth and DB overridden for config endpoints."""
    from app.database import get_db
    from app.dependencies.auth import require_admin_user, require_authenticated_user
    from app.main import app

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.delete = AsyncMock()

    async def override_db():
        yield mock_db

    # require_admin_user returns a User with platform_admin role
    mock_admin = MagicMock()
    mock_admin.platform_role = "platform_admin"

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin_user] = lambda: mock_admin
    app.dependency_overrides[require_authenticated_user] = lambda: mock_admin

    return TestClient(app, raise_server_exceptions=False), app, mock_db


class GetConfigEndpointTests(unittest.TestCase):
    """Tests for GET /api/config endpoint."""

    def setUp(self):
        self._original_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "test-encryption-key"
        get_settings.cache_clear()

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()
        reset_runtime_config()
        if self._original_key is None:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        else:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._original_key
        get_settings.cache_clear()

    def test_get_config_returns_200_and_config_structure(self):
        """GET /api/config should return 200 with the full config response."""
        from unittest.mock import AsyncMock, patch
        client, app, mock_db = _make_config_admin_client()

        with patch("app.api.config.load_runtime_config_from_db", new=AsyncMock()):
            response = client.get("/api/config")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("runtime", data)
        self.assertIn("auth", data)
        self.assertIn("integration", data)


class ResetConfigEndpointTests(unittest.TestCase):
    """Tests for POST /api/config/reset endpoint."""

    def setUp(self):
        self._original_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "test-encryption-key"
        get_settings.cache_clear()

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()
        reset_runtime_config()
        if self._original_key is None:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        else:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._original_key
        get_settings.cache_clear()

    def test_reset_config_returns_200(self):
        """POST /api/config/reset should return 200 and the reset config."""
        from unittest.mock import AsyncMock, patch
        client, app, mock_db = _make_config_admin_client()

        with patch("app.api.config.reset_all_runtime_config_overrides", new=AsyncMock()):
            with patch("app.api.config.load_runtime_config_from_db", new=AsyncMock()):
                response = client.post("/api/config/reset")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("runtime", data)


class UpdateConfigEndpointTests(unittest.TestCase):
    """Tests for PATCH /api/config endpoint."""

    def setUp(self):
        self._original_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "test-encryption-key"
        get_settings.cache_clear()

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()
        reset_runtime_config()
        if self._original_key is None:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        else:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._original_key
        get_settings.cache_clear()

    def test_update_config_with_empty_payload_returns_200(self):
        """PATCH /api/config with empty payload should return 200."""
        from unittest.mock import AsyncMock, patch
        client, app, mock_db = _make_config_admin_client()

        with patch("app.api.config.load_runtime_config_from_db", new=AsyncMock()):
            response = client.patch("/api/config", json={})

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)

    def test_update_config_with_runtime_update(self):
        """PATCH /api/config with runtime changes should save overrides and return config."""
        from unittest.mock import AsyncMock, patch
        client, app, mock_db = _make_config_admin_client()

        with patch("app.api.config.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.api.config_runtime.save_runtime_config_override", new=AsyncMock()):
                response = client.patch("/api/config", json={
                    "runtime": {
                        "max_concurrency": 3,
                        "scheduler_interval": 10,
                    }
                })

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("runtime", data)

    def test_update_config_with_runtime_null_worker_environment_variables_is_noop(self):
        """PATCH /api/config should treat null runtime worker env vars as a no-op."""
        client, app, mock_db = _make_config_admin_client()

        with patch("app.api.config.load_runtime_config_from_db", new=AsyncMock()):
            with patch(
                "app.api.config_runtime.replace_worker_environment_variables",
                new=AsyncMock(),
            ) as mock_replace:
                response = client.patch("/api/config", json={
                    "runtime": {
                        "worker_environment_variables": None,
                    }
                })

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        mock_replace.assert_not_awaited()

    def test_update_config_with_runtime_internal_value_error_returns_500(self):
        """PATCH /api/config should not report unrelated runtime ValueErrors as 400."""
        client, app, mock_db = _make_config_admin_client()

        with patch("app.api.config.load_runtime_config_from_db", new=AsyncMock()):
            with patch(
                "app.api.config_runtime.save_runtime_config_override",
                new=AsyncMock(side_effect=ValueError("unexpected failure")),
            ):
                response = client.patch("/api/config", json={
                    "runtime": {
                        "max_concurrency": 3,
                    }
                })

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 500)

    def test_update_config_with_auth_update(self):
        """PATCH /api/config with auth changes should save overrides and return config."""
        from unittest.mock import AsyncMock, patch
        client, app, mock_db = _make_config_admin_client()

        with patch("app.api.config.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.runtime_config.save_runtime_config_override", new=AsyncMock()):
                response = client.patch("/api/config", json={
                    "auth": {
                        "session_ttl_seconds": 3600,
                    }
                })

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)


class UpdateConfigIntegrationTests(unittest.TestCase):
    """Tests for PATCH /api/config with integration section."""

    def setUp(self):
        self._original_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "test-encryption-key"
        get_settings.cache_clear()

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()
        reset_runtime_config()
        if self._original_key is None:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        else:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._original_key
        get_settings.cache_clear()

    def test_update_config_with_integration_gitlab_url(self):
        """PATCH /api/config with integration section updates GitLab URL."""
        client, app, mock_db = _make_config_admin_client()

        with patch("app.api.config.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.runtime_config.save_runtime_config_override", new=AsyncMock()):
                response = client.patch("/api/config", json={
                    "integration": {
                        "gitlab_url": "https://gitlab.example.com",
                    }
                })

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("integration", data)

    def test_update_config_with_integration_clear_bot_token(self):
        """PATCH /api/config with clear_gitlab_bot_token clears stored token."""
        client, app, mock_db = _make_config_admin_client()

        with patch("app.api.config.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.runtime_config.save_runtime_config_override", new=AsyncMock()):
                with patch("app.runtime_config.reset_runtime_config_override", new=AsyncMock()) as mock_reset:
                    response = client.patch("/api/config", json={
                        "integration": {
                            "clear_gitlab_bot_token": True,
                        }
                    })

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        mock_reset.assert_awaited()

    def test_update_config_with_auth_and_integration(self):
        """PATCH /api/config with both auth and integration sections."""
        client, app, mock_db = _make_config_admin_client()

        with patch("app.api.config.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.runtime_config.save_runtime_config_override", new=AsyncMock()):
                response = client.patch("/api/config", json={
                    "auth": {
                        "session_ttl_seconds": 7200,
                    },
                    "integration": {
                        "gitlab_url": "https://gitlab.example.com",
                    }
                })

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)

    def test_update_config_with_runtime_clear_alert_webhook(self):
        """PATCH /api/config clears alert webhook when clear_alert_webhook_url set."""
        client, app, mock_db = _make_config_admin_client()

        with patch("app.api.config.load_runtime_config_from_db", new=AsyncMock()):
            with patch("app.api.config_runtime.save_runtime_config_override", new=AsyncMock()):
                with patch("app.api.config_runtime.reset_runtime_config_override", new=AsyncMock()):
                    response = client.patch("/api/config", json={
                        "runtime": {
                            "clear_alert_webhook_url": True,
                        }
                    })

        app.dependency_overrides.clear()

        # Should succeed (200)
        self.assertEqual(response.status_code, 200)
