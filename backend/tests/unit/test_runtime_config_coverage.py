"""Additional coverage tests for runtime_config.py.

Targets missed lines: 38, 51, 59-60, 68-69, 72-73, 99-104.
"""

import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import get_effective_settings, get_settings, reset_runtime_config
from app.models import SystemConfig
from app.runtime_config import (
    _deserialize_runtime_value,
    _serialize_runtime_value,
    load_runtime_config_from_db,
    reset_runtime_config_override,
    reset_runtime_config_sync_state,
    save_runtime_config_override,
)


class RuntimeConfigCoverageTests(unittest.IsolatedAsyncioTestCase):
    """Tests that fill coverage gaps in runtime_config.py."""

    def setUp(self) -> None:
        self._original_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-config-key"
        get_settings.cache_clear()
        reset_runtime_config_sync_state()

    def tearDown(self) -> None:
        reset_runtime_config()
        reset_runtime_config_sync_state()
        if self._original_key is None:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        else:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._original_key
        get_settings.cache_clear()

    # ------------------------------------------------------------------
    # _serialize_runtime_value – bool branch  (line 38)
    # ------------------------------------------------------------------

    def test_serialize_bool_true(self) -> None:
        """Bool True serialises to ('true', 'bool') (line 38)."""
        value, vtype = _serialize_runtime_value("alert_on_failure", True)
        self.assertEqual(value, "true")
        self.assertEqual(vtype, "bool")

    def test_serialize_bool_false(self) -> None:
        """Bool False serialises to ('false', 'bool') (line 38)."""
        value, vtype = _serialize_runtime_value("alert_on_failure", False)
        self.assertEqual(value, "false")
        self.assertEqual(vtype, "bool")

    def test_serialize_bool_oidc_enabled(self) -> None:
        """Another bool key round-trips correctly."""
        value, vtype = _serialize_runtime_value("oidc_enabled", True)
        self.assertEqual(value, "true")
        self.assertEqual(vtype, "bool")

    # ------------------------------------------------------------------
    # _deserialize_runtime_value – bool branch  (line 51)
    # ------------------------------------------------------------------

    def test_deserialize_bool_true_values(self) -> None:
        """Various truthy string representations deserialise to True (line 51)."""
        for raw in ("true", "True", "TRUE", "1", "yes", "on"):
            result = _deserialize_runtime_value("alert_on_failure", raw, "bool")
            self.assertTrue(result, f"Expected True for '{raw}'")

    def test_deserialize_bool_false_values(self) -> None:
        """Non-truthy strings deserialise to False (line 51)."""
        for raw in ("false", "0", "no", "off", ""):
            result = _deserialize_runtime_value("alert_on_failure", raw, "bool")
            self.assertFalse(result, f"Expected False for '{raw}'")

    def test_deserialize_bool_by_expected_type(self) -> None:
        """Bool deserialization triggered by expected_type (not value_type)."""
        # Even if value_type is 'str', if the key's expected type is bool it returns bool
        result = _deserialize_runtime_value("cookie_secure", "true", "str")
        self.assertTrue(result)

    # ------------------------------------------------------------------
    # Bool round-trip
    # ------------------------------------------------------------------

    def test_bool_round_trip(self) -> None:
        """Serialize then deserialize preserves bool semantics."""
        for original in (True, False):
            raw, vtype = _serialize_runtime_value("alert_on_failure", original)
            restored = _deserialize_runtime_value("alert_on_failure", raw, vtype)
            self.assertEqual(restored, original)

    # ------------------------------------------------------------------
    # load_runtime_config_from_db – db=None creates own session  (lines 59-60)
    # ------------------------------------------------------------------

    async def test_load_config_creates_session_when_db_is_none(self) -> None:
        """When db=None the function opens its own AsyncSession (lines 58-60)."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            SystemConfig(key="max_concurrency", value="10", value_type="int"),
        ]
        handoff_result = MagicMock()
        handoff_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[handoff_result, mock_result])

        # AsyncSessionLocal() returns an async context manager
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.runtime_config.AsyncSessionLocal", return_value=mock_session_ctx):
            overrides = await load_runtime_config_from_db(db=None)

        self.assertEqual(overrides["max_concurrency"], 10)

    # ------------------------------------------------------------------
    # load_runtime_config_from_db – unsupported key  (lines 68-69)
    # ------------------------------------------------------------------

    async def test_load_config_skips_unsupported_keys(self) -> None:
        """Unsupported keys emit a warning and are excluded (lines 67-69)."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            SystemConfig(key="max_concurrency", value="3", value_type="int"),
            SystemConfig(key="totally_unknown_key", value="x", value_type="str"),
        ]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.runtime_config.logger") as mock_logger:
            overrides = await load_runtime_config_from_db(mock_db)

        self.assertIn("max_concurrency", overrides)
        self.assertNotIn("totally_unknown_key", overrides)
        mock_logger.warning.assert_called_once()
        self.assertIn("totally_unknown_key", mock_logger.warning.call_args[0][1])

    # ------------------------------------------------------------------
    # load_runtime_config_from_db – deserialization errors  (lines 72-73)
    # ------------------------------------------------------------------

    async def test_load_config_handles_deserialization_value_error(self) -> None:
        """ValueError during deserialization is logged and skipped (lines 70-73)."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            # "not-a-number" will raise ValueError when int() is called
            SystemConfig(key="max_concurrency", value="not-a-number", value_type="int"),
            SystemConfig(key="task_timeout", value="300", value_type="int"),
        ]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.runtime_config.logger") as mock_logger:
            overrides = await load_runtime_config_from_db(mock_db)

        self.assertNotIn("max_concurrency", overrides)
        self.assertIn("task_timeout", overrides)
        self.assertEqual(overrides["task_timeout"], 300)
        mock_logger.warning.assert_called_once()

    async def test_load_config_handles_config_encryption_error(self) -> None:
        """ConfigEncryptionError during deserialization is logged and skipped (lines 70-73)."""

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            # A secret key with corrupt ciphertext
            SystemConfig(key="oidc_client_secret", value="corrupted-ciphertext", value_type="secret_str"),
        ]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.runtime_config.logger") as mock_logger:
            overrides = await load_runtime_config_from_db(mock_db)

        self.assertNotIn("oidc_client_secret", overrides)
        mock_logger.warning.assert_called_once()

    async def test_load_config_handles_type_error(self) -> None:
        """TypeError during deserialization is logged and skipped (lines 70-73)."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            SystemConfig(key="max_concurrency", value="5", value_type="int"),
        ]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.runtime_config._deserialize_runtime_value",
            side_effect=TypeError("unexpected type"),
        ):
            with patch("app.runtime_config.logger") as mock_logger:
                overrides = await load_runtime_config_from_db(mock_db)

        self.assertNotIn("max_concurrency", overrides)
        mock_logger.warning.assert_called_once()

    # ------------------------------------------------------------------
    # reset_runtime_config_override  (lines 97-104)
    # ------------------------------------------------------------------

    async def test_reset_override_deletes_existing_record(self) -> None:
        """Existing record is deleted and runtime config is reset (lines 99-104)."""
        existing = SystemConfig(key="task_timeout", value="600", value_type="int")
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=existing)
        mock_db.delete = AsyncMock()
        mock_db.flush = AsyncMock()

        from app.config import update_runtime_config

        update_runtime_config("task_timeout", 600)

        await reset_runtime_config_override(mock_db, "task_timeout")

        mock_db.delete.assert_awaited_once_with(existing)
        mock_db.flush.assert_awaited_once()
        # After reset, the override should be gone
        effective = get_effective_settings()
        self.assertEqual(effective.task_timeout, get_settings().task_timeout)

    async def test_reset_override_nonexistent_key(self) -> None:
        """Non-existent key skips delete but still flushes and resets (lines 99-104)."""
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=None)
        mock_db.delete = AsyncMock()
        mock_db.flush = AsyncMock()

        await reset_runtime_config_override(mock_db, "task_timeout")

        mock_db.delete.assert_not_awaited()
        mock_db.flush.assert_awaited_once()

    # ------------------------------------------------------------------
    # save_runtime_config_override – insert path (existing=None)
    # ------------------------------------------------------------------

    async def test_save_override_inserts_new_record(self) -> None:
        """When no existing record, a new SystemConfig is added."""
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=None)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        await save_runtime_config_override(mock_db, "max_concurrency", 12)

        mock_db.add.assert_called_once()
        added_obj = mock_db.add.call_args[0][0]
        self.assertEqual(added_obj.key, "max_concurrency")
        self.assertEqual(added_obj.value, "12")
        self.assertEqual(added_obj.value_type, "int")
        mock_db.flush.assert_awaited_once()

    async def test_save_override_bool_value(self) -> None:
        """Saving a bool override persists 'true'/'false' with value_type='bool'."""
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=None)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        await save_runtime_config_override(mock_db, "alert_on_failure", True)

        added_obj = mock_db.add.call_args[0][0]
        self.assertEqual(added_obj.value, "true")
        self.assertEqual(added_obj.value_type, "bool")


if __name__ == "__main__":
    unittest.main()
