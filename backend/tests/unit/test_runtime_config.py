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
    def tearDown(self) -> None:
        reset_runtime_config()

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

        self.assertEqual(serialized_int, ("5", "int"))
        self.assertEqual(serialized_str, ("release", "str"))
        self.assertEqual(_deserialize_runtime_value("max_concurrency", "5", "int"), 5)
        self.assertEqual(
            _deserialize_runtime_value("default_target_branch", "release", "str"),
            "release",
        )

    async def test_load_runtime_config_from_db_refreshes_cache(self) -> None:
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            SystemConfig(key="max_concurrency", value="4", value_type="int"),
            SystemConfig(key="default_target_branch", value="release", value_type="str"),
        ]
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        overrides = await load_runtime_config_from_db(mock_db)

        self.assertEqual(overrides["max_concurrency"], 4)
        self.assertEqual(overrides["default_target_branch"], "release")
        self.assertEqual(get_effective_settings().max_concurrency, 4)

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
