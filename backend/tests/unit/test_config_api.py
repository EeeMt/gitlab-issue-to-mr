#!/usr/bin/env python3
"""Unit tests for configuration API helpers."""

import os
import sys
import unittest

from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.api.config import _normalize_updates, _serialize_effective_config, _validate_config_value
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

    def test_normalize_updates_handles_runtime_clear_flags(self) -> None:
        normalized = _normalize_updates({
            "clear_alert_webhook_url": 1,
            "clear_anthropic_api_key": 0,
            "clear_gitlab_bot_token": 1,
        })

        self.assertEqual(
            normalized,
            {
                "clear_alert_webhook_url": True,
                "clear_anthropic_api_key": False,
                "clear_gitlab_bot_token": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
