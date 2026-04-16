#!/usr/bin/env python3
"""Unit tests for AI Provider CRUD API endpoints.

Tests cover:
- list_providers empty and with data
- create_provider validation (name, URL, max_turns) and duplicate-name 409
- delete_provider 404 when missing and 409 when last provider
- set_default_provider 404 when missing
"""

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.dependencies.auth import require_authenticated_user, require_admin_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(
    id=1,
    name="test-provider",
    base_url="http://localhost:11434/v1",
    api_key=None,
    model="claude-sonnet-4-20250514",
    max_turns=20,
    system_prompt=None,
    is_default=False,
):
    """Build a mock AIProvider ORM object."""
    from app.models import AIProvider

    p = AIProvider(
        name=name,
        base_url=base_url,
        api_key=api_key,
        model=model,
        max_turns=max_turns,
        system_prompt=system_prompt,
        is_default=is_default,
    )
    p.id = id
    p.created_at = datetime(2026, 1, 1)
    p.updated_at = datetime(2026, 1, 1)
    return p


# ---------------------------------------------------------------------------
# List providers
# ---------------------------------------------------------------------------


class ProviderListTests(unittest.TestCase):
    """Tests for GET /api/providers."""

    def setUp(self):
        self._original_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-config-key"

        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock()
        self.mock_db.get = AsyncMock()
        self.mock_db.commit = AsyncMock()
        self.mock_db.flush = AsyncMock()
        self.mock_db.add = MagicMock()
        self.mock_db.refresh = AsyncMock()
        self.mock_db.delete = AsyncMock()

        app.dependency_overrides[get_db] = lambda: self.mock_db
        app.dependency_overrides[require_admin_user] = lambda: MagicMock()

        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        app.dependency_overrides.clear()
        if self._original_key is None:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        else:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._original_key

    def test_list_providers_empty(self):
        """GET /api/providers with no providers returns 200 and an empty list."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        response = self.client.get("/api/providers")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_providers_returns_serialized(self):
        """GET /api/providers returns serialized provider with api_key_configured flag."""
        provider = _make_provider(
            id=5,
            name="my-llm",
            base_url="https://api.openai.com/v1",
            api_key="enc:secret-key",
            model="gpt-4o",
            max_turns=30,
            system_prompt="You are helpful.",
            is_default=True,
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [provider]
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        response = self.client.get("/api/providers")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)

        item = data[0]
        self.assertEqual(item["id"], 5)
        self.assertEqual(item["name"], "my-llm")
        self.assertEqual(item["base_url"], "https://api.openai.com/v1")
        self.assertTrue(item["api_key_configured"])
        self.assertEqual(item["model"], "gpt-4o")
        self.assertEqual(item["max_turns"], 30)
        self.assertEqual(item["system_prompt"], "You are helpful.")
        self.assertTrue(item["is_default"])
        self.assertEqual(item["created_at"], "2026-01-01T00:00:00")
        self.assertEqual(item["updated_at"], "2026-01-01T00:00:00")

        # Raw api_key must NEVER leak into the response
        self.assertNotIn("api_key", item)


# ---------------------------------------------------------------------------
# Create provider — validation
# ---------------------------------------------------------------------------


class ProviderCreateTests(unittest.TestCase):
    """Tests for POST /api/providers validation."""

    def setUp(self):
        self._original_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-config-key"

        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock()
        self.mock_db.get = AsyncMock()
        self.mock_db.commit = AsyncMock()
        self.mock_db.flush = AsyncMock()
        self.mock_db.add = MagicMock()
        self.mock_db.refresh = AsyncMock()
        self.mock_db.delete = AsyncMock()

        app.dependency_overrides[get_db] = lambda: self.mock_db
        app.dependency_overrides[require_admin_user] = lambda: MagicMock()

        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        app.dependency_overrides.clear()
        if self._original_key is None:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        else:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._original_key

    def test_create_provider_invalid_name(self):
        """POST /api/providers with spaces in name returns 422."""
        payload = {
            "name": "has spaces",
            "base_url": "http://localhost:11434/v1",
            "model": "claude-sonnet-4-20250514",
        }
        response = self.client.post("/api/providers", json=payload)

        self.assertEqual(response.status_code, 422)

    def test_create_provider_invalid_base_url(self):
        """POST /api/providers with ftp:// URL returns 422."""
        payload = {
            "name": "my-provider",
            "base_url": "ftp://files.example.com",
            "model": "claude-sonnet-4-20250514",
        }
        response = self.client.post("/api/providers", json=payload)

        self.assertEqual(response.status_code, 422)

    def test_create_provider_max_turns_out_of_range(self):
        """POST /api/providers with max_turns=0 returns 422."""
        payload = {
            "name": "my-provider",
            "base_url": "http://localhost:11434/v1",
            "model": "claude-sonnet-4-20250514",
            "max_turns": 0,
        }
        response = self.client.post("/api/providers", json=payload)

        self.assertEqual(response.status_code, 422)

    def test_create_provider_duplicate_name_409(self):
        """POST /api/providers with an existing name returns 409."""
        existing = _make_provider(id=1, name="duplicate-name")

        # First execute() call: check for existing provider by name -> found
        name_check_result = MagicMock()
        name_check_result.scalar_one_or_none.return_value = existing
        self.mock_db.execute = AsyncMock(return_value=name_check_result)

        payload = {
            "name": "duplicate-name",
            "base_url": "http://localhost:11434/v1",
            "model": "claude-sonnet-4-20250514",
        }
        response = self.client.post("/api/providers", json=payload)

        self.assertEqual(response.status_code, 409)
        self.assertIn("already exists", response.json()["detail"])


# ---------------------------------------------------------------------------
# Delete provider
# ---------------------------------------------------------------------------


class ProviderDeleteTests(unittest.TestCase):
    """Tests for DELETE /api/providers/{id}."""

    def setUp(self):
        self._original_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-config-key"

        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock()
        self.mock_db.get = AsyncMock()
        self.mock_db.commit = AsyncMock()
        self.mock_db.flush = AsyncMock()
        self.mock_db.add = MagicMock()
        self.mock_db.refresh = AsyncMock()
        self.mock_db.delete = AsyncMock()

        app.dependency_overrides[get_db] = lambda: self.mock_db
        app.dependency_overrides[require_admin_user] = lambda: MagicMock()

        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        app.dependency_overrides.clear()
        if self._original_key is None:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        else:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._original_key

    def test_delete_nonexistent_404(self):
        """DELETE /api/providers/{id} returns 404 when provider does not exist."""
        self.mock_db.get = AsyncMock(return_value=None)

        response = self.client.delete("/api/providers/9999")

        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"].lower())

    def test_delete_last_provider_409(self):
        """DELETE /api/providers/{id} returns 409 when it is the only provider."""
        provider = _make_provider(id=1, is_default=True)
        self.mock_db.get = AsyncMock(return_value=provider)

        # execute() is called for count query -> returns 1
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        self.mock_db.execute = AsyncMock(return_value=count_result)

        response = self.client.delete("/api/providers/1")

        self.assertEqual(response.status_code, 409)
        self.assertIn("only provider", response.json()["detail"].lower())


# ---------------------------------------------------------------------------
# Set default provider
# ---------------------------------------------------------------------------


class ProviderSetDefaultTests(unittest.TestCase):
    """Tests for POST /api/providers/{id}/set-default."""

    def setUp(self):
        self._original_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-config-key"

        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock()
        self.mock_db.get = AsyncMock()
        self.mock_db.commit = AsyncMock()
        self.mock_db.flush = AsyncMock()
        self.mock_db.add = MagicMock()
        self.mock_db.refresh = AsyncMock()
        self.mock_db.delete = AsyncMock()

        app.dependency_overrides[get_db] = lambda: self.mock_db
        app.dependency_overrides[require_admin_user] = lambda: MagicMock()

        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        app.dependency_overrides.clear()
        if self._original_key is None:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        else:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._original_key

    def test_set_default_nonexistent_404(self):
        """POST /api/providers/{id}/set-default returns 404 for missing provider."""
        self.mock_db.get = AsyncMock(return_value=None)

        response = self.client.post("/api/providers/9999/set-default")

        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"].lower())




class ProviderAuthScopeTests(unittest.TestCase):
    """Tests that provider routes use admin auth scope."""

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_list_providers_uses_admin_dependency(self):
        """GET /api/providers should be gated by require_admin_user."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_user] = lambda: (_ for _ in ()).throw(Exception("wrong dependency"))
        app.dependency_overrides[require_admin_user] = lambda: MagicMock()

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/providers")

        self.assertEqual(response.status_code, 200)
