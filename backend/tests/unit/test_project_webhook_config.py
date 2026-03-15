#!/usr/bin/env python3
"""Unit tests for project webhook secret persistence."""

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import get_settings
from app.models import ProjectWebhookConfig
from app.project_webhook_config import (
    get_project_webhook_secret,
    has_project_webhook_secret,
    save_project_webhook_secret,
)


class ProjectWebhookConfigTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_save_and_load_project_webhook_secret(self) -> None:
        mock_db = MagicMock()
        mock_db.get = AsyncMock(side_effect=[None, ProjectWebhookConfig(project_id=9, secret_encrypted="")])
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        await save_project_webhook_secret(mock_db, 9, "secret-123")

        added_record = mock_db.add.call_args.args[0]
        self.assertEqual(added_record.project_id, 9)
        self.assertNotEqual(added_record.secret_encrypted, "secret-123")

        mock_db.get = AsyncMock(return_value=added_record)
        self.assertEqual(await get_project_webhook_secret(mock_db, 9), "secret-123")
        self.assertTrue(await has_project_webhook_secret(mock_db, 9))

    async def test_get_project_webhook_secret_returns_none_when_missing(self) -> None:
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=None)

        self.assertIsNone(await get_project_webhook_secret(mock_db, 404))
        self.assertFalse(await has_project_webhook_secret(mock_db, 404))


if __name__ == "__main__":
    unittest.main()
