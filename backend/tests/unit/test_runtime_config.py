#!/usr/bin/env python3
"""Unit tests for runtime configuration persistence helpers."""

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import get_effective_settings, get_settings, reset_runtime_config, set_runtime_config
from app.models import SystemConfig
from app.runtime_config import (
    _deserialize_runtime_value,
    _serialize_runtime_value,
    load_runtime_config_from_db,
    reset_all_runtime_config_overrides,
    save_runtime_config_override,
)


class RuntimeConfigTests(unittest.IsolatedAsyncioTestCase):
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

    def test_effective_settings_use_runtime_overrides(self) -> None:
        set_runtime_config({
            "max_concurrency": 7,
            "task_timeout": 900,
            "scheduler_interval": 9,
            "default_target_branch": "develop",
        })

        settings = get_effective_settings()

        self.assertEqual(settings.max_concurrency, 7)
        self.assertEqual(settings.task_timeout, 900)
        self.assertEqual(settings.scheduler_interval, 9)
        self.assertEqual(settings.default_target_branch, "develop")

    def test_runtime_values_round_trip_by_type(self) -> None:
        serialized_int = _serialize_runtime_value("max_concurrency", 5)
        serialized_str = _serialize_runtime_value("default_target_branch", "release")
        serialized_secret = _serialize_runtime_value("oidc_client_secret", "super-secret")

        self.assertEqual(serialized_int, ("5", "int"))
        self.assertEqual(serialized_str, ("release", "str"))
        self.assertEqual(serialized_secret[1], "secret_str")
        self.assertEqual(_deserialize_runtime_value("max_concurrency", "5", "int"), 5)
        self.assertEqual(
            _deserialize_runtime_value("default_target_branch", "release", "str"),
            "release",
        )
        self.assertEqual(
            _deserialize_runtime_value("oidc_client_secret", serialized_secret[0], serialized_secret[1]),
            "super-secret",
        )

    async def test_load_runtime_config_from_db_refreshes_cache(self) -> None:
        serialized_secret, secret_type = _serialize_runtime_value("oidc_client_secret", "stored-secret")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            SystemConfig(key="max_concurrency", value="4", value_type="int"),
            SystemConfig(key="default_target_branch", value="release", value_type="str"),
            SystemConfig(key="oidc_client_secret", value=serialized_secret, value_type=secret_type),
        ]
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        overrides = await load_runtime_config_from_db(mock_db)

        self.assertEqual(overrides["max_concurrency"], 4)
        self.assertEqual(overrides["default_target_branch"], "release")
        self.assertEqual(overrides["oidc_client_secret"], "stored-secret")
        self.assertEqual(get_effective_settings().max_concurrency, 4)

    def test_effective_settings_include_auth_overrides(self) -> None:
        set_runtime_config({
            "oidc_enabled": True,
            "oidc_issuer_url": "https://gitlab.example.com",
            "oidc_client_id": "gimr",
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
