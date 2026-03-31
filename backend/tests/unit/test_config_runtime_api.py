#!/usr/bin/env python3
"""Unit tests for Config Runtime API endpoints."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from starlette.requests import Request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db
from app.config import get_settings, reset_runtime_config
from app.dependencies.auth import require_authenticated_context


class ConfigRuntimeAPITests(unittest.TestCase):
    """Test /config/runtime API endpoints."""

    def setUp(self):
        self._original_config_encryption_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-config-key"
        get_settings.cache_clear()
        reset_runtime_config()

        self.client = TestClient(app)
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(all=MagicMock(return_value=[]))))
        self.mock_db.get = AsyncMock(return_value=None)
        self.mock_db.commit = AsyncMock()
        self.mock_db.flush = AsyncMock()
        self.mock_db.add = MagicMock()
        app.dependency_overrides[get_db] = lambda: self.mock_db

        # Override require_authenticated_context to return a mock auth context
        async def mock_auth_context(request: Request, auth_context=None):
            return SimpleNamespace(
                user=SimpleNamespace(id=1, username="admin", platform_role="platform_admin"),
                session=None,
                gitlab_access_token=None,
                gitlab_refresh_token=None,
            )
        app.dependency_overrides[require_authenticated_context] = mock_auth_context

    def tearDown(self):
        app.dependency_overrides.clear()
        reset_runtime_config()
        if self._original_config_encryption_key is None:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        else:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._original_config_encryption_key
        get_settings.cache_clear()

    def test_get_runtime_config_returns_current_settings(self):
        """GET /config/runtime should return current runtime configuration."""
        response = self.client.get("/api/config/runtime")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("max_concurrency", data)
        self.assertIn("task_timeout", data)
        self.assertIn("scheduler_interval", data)
        self.assertIn("default_target_branch", data)
        self.assertIn("max_retries", data)
        self.assertIn("retry_delay", data)
        self.assertIn("alert_on_failure", data)
        self.assertIn("anthropic_base_url", data)
        self.assertIn("anthropic_model", data)
        self.assertIn("claude_max_turns", data)

    def test_patch_runtime_config_updates_max_concurrency(self):
        """PATCH /config/runtime should accept valid max_concurrency update.

        Note: Full persistence testing is done in test_runtime_config.py.
        This test verifies the endpoint accepts and validates the input.
        """
        response = self.client.patch(
            "/api/config/runtime",
            json={"max_concurrency": 5},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Verify response contains expected fields
        self.assertIn("max_concurrency", data)

    def test_patch_runtime_config_updates_multiple_fields(self):
        """PATCH /config/runtime should accept multiple field updates.

        Note: Full persistence testing is done in test_runtime_config.py.
        This test verifies the endpoint accepts and validates all inputs.
        """
        response = self.client.patch(
            "/api/config/runtime",
            json={
                "max_concurrency": 10,
                "task_timeout": 3600,
                "default_target_branch": "develop",
                "anthropic_model": "claude-3-5-sonnet",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Verify response contains expected fields
        self.assertIn("max_concurrency", data)
        self.assertIn("task_timeout", data)
        self.assertIn("default_target_branch", data)
        self.assertIn("anthropic_model", data)

    def test_patch_runtime_config_rejects_invalid_max_concurrency(self):
        """PATCH /config/runtime should reject invalid max_concurrency."""
        response = self.client.patch(
            "/api/config/runtime",
            json={"max_concurrency": 100},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("max_concurrency", response.json()["detail"].lower())

    def test_patch_runtime_config_rejects_invalid_task_timeout(self):
        """PATCH /config/runtime should reject invalid task_timeout."""
        response = self.client.patch(
            "/api/config/runtime",
            json={"task_timeout": 30},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("task_timeout", response.json()["detail"].lower())

    def test_patch_runtime_config_rejects_invalid_url(self):
        """PATCH /config/runtime should reject invalid URL format."""
        response = self.client.patch(
            "/api/config/runtime",
            json={"anthropic_base_url": "not-a-valid-url"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("url", response.json()["detail"].lower())

    def test_patch_runtime_config_rejects_empty_model(self):
        """PATCH /config/runtime should reject empty anthropic_model."""
        response = self.client.patch(
            "/api/config/runtime",
            json={"anthropic_model": "  "},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("anthropic_model", response.json()["detail"].lower())


if __name__ == "__main__":
    unittest.main()
