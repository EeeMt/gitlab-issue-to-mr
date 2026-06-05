#!/usr/bin/env python3
"""Unit tests for runtime configuration persistence helpers."""

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import (
    get_effective_settings,
    get_settings,
    reset_runtime_config,
    set_runtime_config,
)
from app.models import SystemConfig
from app.runtime_config import (
    _deserialize_runtime_value,
    _serialize_runtime_value,
    load_runtime_config_from_db,
    refresh_runtime_config_if_stale,
    reset_all_runtime_config_overrides,
    reset_runtime_config_sync_state,
    save_runtime_config_override,
)


class RuntimeConfigTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._original_config_encryption_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-config-key"
        get_settings.cache_clear()
        reset_runtime_config_sync_state()

    def tearDown(self) -> None:
        reset_runtime_config()
        reset_runtime_config_sync_state()
        if self._original_config_encryption_key is None:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        else:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._original_config_encryption_key
        get_settings.cache_clear()

    def test_effective_settings_use_runtime_overrides(self) -> None:
        set_runtime_config({
            "max_concurrency": 7,
            "task_timeout": 900,
            "scheduler_interval": 9,
            "default_target_branch": "develop",
            "max_retries": 2,
            "retry_delay": 120,
            "alert_on_failure": True,
            "anthropic_base_url": "https://llm.example.com/v1",
            "anthropic_model": "claude-override",
        })

        settings = get_effective_settings()

        self.assertEqual(settings.max_concurrency, 7)
        self.assertEqual(settings.task_timeout, 900)
        self.assertEqual(settings.scheduler_interval, 9)
        self.assertEqual(settings.default_target_branch, "develop")
        self.assertEqual(settings.max_retries, 2)
        self.assertEqual(settings.retry_delay, 120)
        self.assertTrue(settings.alert_on_failure)
        self.assertEqual(settings.anthropic_base_url, "https://llm.example.com/v1")
        self.assertEqual(settings.anthropic_model, "claude-override")

    def test_runtime_values_round_trip_by_type(self) -> None:
        serialized_int = _serialize_runtime_value("max_concurrency", 5)
        serialized_str = _serialize_runtime_value("default_target_branch", "release")
        serialized_secret = _serialize_runtime_value("oidc_client_secret", "super-secret")
        serialized_api_key = _serialize_runtime_value("anthropic_api_key", "api-key")
        serialized_webhook = _serialize_runtime_value("alert_webhook_url", "https://hooks.example.com/a")
        serialized_mattermost_token = _serialize_runtime_value("mattermost_bot_token", "mm-token")
        serialized_gitlab_admin = _serialize_runtime_value("gitlab_admin_token", "glpat-admin")
        serialized_gitlab_webhook_secret = _serialize_runtime_value("gitlab_webhook_secret", "webhook-secret")

        self.assertEqual(serialized_int, ("5", "int"))
        self.assertEqual(serialized_str, ("release", "str"))
        self.assertEqual(serialized_secret[1], "secret_str")
        self.assertEqual(serialized_api_key[1], "secret_str")
        self.assertEqual(serialized_webhook[1], "secret_str")
        self.assertEqual(serialized_mattermost_token[1], "secret_str")
        self.assertEqual(serialized_gitlab_admin[1], "secret_str")
        self.assertEqual(serialized_gitlab_webhook_secret[1], "secret_str")
        self.assertEqual(_deserialize_runtime_value("max_concurrency", "5", "int"), 5)
        self.assertEqual(
            _deserialize_runtime_value("default_target_branch", "release", "str"),
            "release",
        )
        self.assertEqual(
            _deserialize_runtime_value("oidc_client_secret", serialized_secret[0], serialized_secret[1]),
            "super-secret",
        )
        self.assertEqual(
            _deserialize_runtime_value("anthropic_api_key", serialized_api_key[0], serialized_api_key[1]),
            "api-key",
        )
        self.assertEqual(
            _deserialize_runtime_value("alert_webhook_url", serialized_webhook[0], serialized_webhook[1]),
            "https://hooks.example.com/a",
        )
        self.assertEqual(
            _deserialize_runtime_value(
                "mattermost_bot_token",
                serialized_mattermost_token[0],
                serialized_mattermost_token[1],
            ),
            "mm-token",
        )
        self.assertEqual(
            _deserialize_runtime_value("gitlab_admin_token", serialized_gitlab_admin[0], serialized_gitlab_admin[1]),
            "glpat-admin",
        )
        self.assertEqual(
            _deserialize_runtime_value(
                "gitlab_webhook_secret",
                serialized_gitlab_webhook_secret[0],
                serialized_gitlab_webhook_secret[1],
            ),
            "webhook-secret",
        )

    async def test_load_runtime_config_from_db_refreshes_cache(self) -> None:
        serialized_secret, secret_type = _serialize_runtime_value("oidc_client_secret", "stored-secret")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            SystemConfig(key="max_concurrency", value="4", value_type="int"),
            SystemConfig(key="default_target_branch", value="release", value_type="str"),
            SystemConfig(key="max_retries", value="3", value_type="int"),
            SystemConfig(key="oidc_client_secret", value=serialized_secret, value_type=secret_type),
        ]
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        overrides = await load_runtime_config_from_db(mock_db)

        self.assertEqual(overrides["max_concurrency"], 4)
        self.assertEqual(overrides["default_target_branch"], "release")
        self.assertEqual(overrides["max_retries"], 3)
        self.assertEqual(overrides["oidc_client_secret"], "stored-secret")
        self.assertEqual(get_effective_settings().max_concurrency, 4)

    def test_effective_settings_include_auth_overrides(self) -> None:
        set_runtime_config({
            "oidc_enabled": True,
            "oidc_issuer_url": "https://gitlab.example.com",
            "oidc_client_id": "codify",
            "oidc_client_secret": "stored-secret",
            "oidc_redirect_uri": "https://bot.example.com/api/auth/callback",
        })

        settings = get_effective_settings()

        self.assertTrue(settings.oidc_enabled)
        self.assertEqual(settings.oidc_client_secret, "stored-secret")
        self.assertEqual(settings.oidc_redirect_uri, "https://bot.example.com/api/auth/callback")

    async def test_save_runtime_config_override_updates_existing_record(self) -> None:
        existing = SystemConfig(key="task_timeout", value="1800", value_type="int")
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=existing)
        mock_db.flush = AsyncMock()

        await save_runtime_config_override(mock_db, "task_timeout", 600)

        self.assertEqual(existing.value, "600")
        self.assertEqual(existing.value_type, "int")
        self.assertEqual(get_effective_settings().task_timeout, 600)

    async def test_refresh_runtime_config_if_stale_skips_reload_when_timestamp_unchanged(self) -> None:
        timestamp = datetime(2024, 1, 1, 12, 0, 0)

        max_result_first = MagicMock()
        max_result_first.one.return_value = (1, timestamp)
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [
            SystemConfig(
                key="max_concurrency",
                value="4",
                value_type="int",
                updated_at=timestamp,
            )
        ]
        max_result_second = MagicMock()
        max_result_second.one.return_value = (1, timestamp)

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[max_result_first, rows_result, max_result_second])

        refreshed_first = await refresh_runtime_config_if_stale(mock_db, min_check_interval=0.0)
        refreshed_second = await refresh_runtime_config_if_stale(mock_db, min_check_interval=0.0)

        self.assertTrue(refreshed_first)
        self.assertFalse(refreshed_second)
        self.assertEqual(get_effective_settings().max_concurrency, 4)
        self.assertEqual(mock_db.execute.await_count, 3)

    async def test_refresh_runtime_config_if_stale_reloads_when_timestamp_changes(self) -> None:
        timestamp_first = datetime(2024, 1, 1, 12, 0, 0)
        timestamp_second = datetime(2024, 1, 1, 12, 0, 5)

        max_result_first = MagicMock()
        max_result_first.one.return_value = (1, timestamp_first)
        rows_result_first = MagicMock()
        rows_result_first.scalars.return_value.all.return_value = [
            SystemConfig(
                key="max_concurrency",
                value="4",
                value_type="int",
                updated_at=timestamp_first,
            )
        ]
        max_result_second = MagicMock()
        max_result_second.one.return_value = (1, timestamp_second)
        rows_result_second = MagicMock()
        rows_result_second.scalars.return_value.all.return_value = [
            SystemConfig(
                key="max_concurrency",
                value="6",
                value_type="int",
                updated_at=timestamp_second,
            )
        ]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                max_result_first,
                rows_result_first,
                max_result_second,
                rows_result_second,
            ]
        )

        await refresh_runtime_config_if_stale(mock_db, min_check_interval=0.0)
        refreshed_second = await refresh_runtime_config_if_stale(mock_db, min_check_interval=0.0)

        self.assertTrue(refreshed_second)
        self.assertEqual(get_effective_settings().max_concurrency, 6)

    async def test_refresh_runtime_config_if_stale_reloads_when_row_count_changes(self) -> None:
        timestamp = datetime(2024, 1, 1, 12, 0, 5)

        max_result_first = MagicMock()
        max_result_first.one.return_value = (2, timestamp)
        rows_result_first = MagicMock()
        rows_result_first.scalars.return_value.all.return_value = [
            SystemConfig(
                key="max_concurrency",
                value="4",
                value_type="int",
                updated_at=datetime(2024, 1, 1, 12, 0, 0),
            ),
            SystemConfig(
                key="task_timeout",
                value="600",
                value_type="int",
                updated_at=timestamp,
            ),
        ]
        max_result_second = MagicMock()
        max_result_second.one.return_value = (1, timestamp)
        rows_result_second = MagicMock()
        rows_result_second.scalars.return_value.all.return_value = [
            SystemConfig(
                key="task_timeout",
                value="600",
                value_type="int",
                updated_at=timestamp,
            )
        ]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                max_result_first,
                rows_result_first,
                max_result_second,
                rows_result_second,
            ]
        )

        await refresh_runtime_config_if_stale(mock_db, min_check_interval=0.0)
        self.assertEqual(get_effective_settings().max_concurrency, 4)

        refreshed_second = await refresh_runtime_config_if_stale(mock_db, min_check_interval=0.0)

        self.assertTrue(refreshed_second)
        self.assertEqual(get_effective_settings().max_concurrency, get_settings().max_concurrency)
        self.assertEqual(get_effective_settings().task_timeout, 600)

    async def test_reset_all_runtime_config_overrides_clears_cache(self) -> None:
        set_runtime_config({"max_concurrency": 8})
        mock_result = MagicMock()
        rows = [SystemConfig(key="max_concurrency", value="8", value_type="int")]
        mock_result.scalars.return_value.all.return_value = rows
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.delete = AsyncMock()
        mock_db.flush = AsyncMock()

        await reset_all_runtime_config_overrides(mock_db)

        mock_db.delete.assert_awaited_once_with(rows[0])
        self.assertEqual(
            get_effective_settings().max_concurrency,
            get_settings().max_concurrency,
        )


if __name__ == "__main__":
    unittest.main()
