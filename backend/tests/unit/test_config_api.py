#!/usr/bin/env python3
"""Unit tests for configuration API helpers."""

import os
import sys
import unittest

from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.api.config import (
    _normalize_updates,
    _serialize_effective_config,
    _validate_config_value,
)
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
            team_name=" engineering ",
            channel_name=" ai-bot ",
            mention_in_channel=True,
            event_types=["task_completed", "task_completed", "task_failed"],
            field_keys=["task_id", "status", "status"],
        )

        self.assertEqual(payload.name, "Team Alerts")
        self.assertEqual(payload.team_name, "engineering")
        self.assertEqual(payload.channel_name, "ai-bot")
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
                "note_events": False,
                "enable_ssl_verification": True,
            },
        )

        self.assertEqual(response.status, "needs_attention")
        self.assertEqual(response.status_detail, "note events disabled")
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


if __name__ == "__main__":
    unittest.main()
