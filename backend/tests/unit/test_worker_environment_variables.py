#!/usr/bin/env python3
"""Unit tests for worker environment variable helpers."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.worker_environment_variables import (  # noqa: E402
    build_worker_environment_map,
    serialize_worker_environment_variable_for_api,
    validate_worker_environment_variable_key,
)
from app.core.config_crypto import encrypt_config_secret  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.models import WorkerEnvironmentVariable  # noqa: E402


class WorkerEnvironmentVariableHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_config_encryption_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-config-key"
        get_settings.cache_clear()

    def tearDown(self) -> None:
        if self._original_config_encryption_key is None:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        else:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._original_config_encryption_key
        get_settings.cache_clear()

    def test_validate_worker_environment_variable_key_accepts_uppercase_keys(self) -> None:
        self.assertEqual(
            validate_worker_environment_variable_key("CUSTOM_FLAG_1"),
            "CUSTOM_FLAG_1",
        )

    def test_validate_worker_environment_variable_key_rejects_reserved_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "reserved"):
            validate_worker_environment_variable_key("TASK_ID")

    def test_secret_api_serialization_hides_value(self) -> None:
        row = WorkerEnvironmentVariable(
            key="CUSTOM_SECRET",
            value="encrypted-value",
            is_secret=True,
        )

        serialized = serialize_worker_environment_variable_for_api(row)

        self.assertEqual(serialized["key"], "CUSTOM_SECRET")
        self.assertIsNone(serialized["value"])
        self.assertTrue(serialized["is_secret"])
        self.assertTrue(serialized["value_configured"])

    def test_runtime_map_decrypts_secret_values_and_preserves_empty_plain_values(self) -> None:
        secret_row = WorkerEnvironmentVariable(
            key="SECRET_TOKEN",
            value=encrypt_config_secret("super-secret"),
            is_secret=True,
        )
        empty_plain_row = WorkerEnvironmentVariable(
            key="EMPTY_VALUE",
            value="",
            is_secret=False,
        )

        runtime_map = build_worker_environment_map([secret_row, empty_plain_row])

        self.assertEqual(runtime_map["SECRET_TOKEN"], "super-secret")
        self.assertEqual(runtime_map["EMPTY_VALUE"], "")


if __name__ == "__main__":
    unittest.main()
