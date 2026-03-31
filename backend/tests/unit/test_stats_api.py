#!/usr/bin/env python3
"""Unit tests for Stats API endpoints."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.requests import Request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db
from app.dependencies.auth import require_authenticated_context
from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope


class StatsAPIValidationTests(unittest.TestCase):
    """Test /stats/analytics validation logic."""

    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=0)))
        app.dependency_overrides[get_db] = lambda: self.mock_db

        # Override auth to return admin user
        async def mock_auth_context(request: Request, auth_context=None):
            return SimpleNamespace(
                user=SimpleNamespace(id=1, username="admin", platform_role="platform_admin"),
                session=None,
                gitlab_access_token=None,
                gitlab_refresh_token=None,
            )
        app.dependency_overrides[require_authenticated_context] = mock_auth_context

        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_get_analytics_rejects_invalid_days(self):
        """GET /stats/analytics rejects days values other than 7, 30, 90."""
        # days=10 passes Pydantic validation (>=7 and <=90) but fails custom check
        response = self.client.get("/api/stats/analytics?days=10")
        self.assertEqual(response.status_code, 400)
        self.assertIn("days must be one of", response.json()["detail"])

    def test_get_analytics_rejects_invalid_days_string(self):
        """GET /stats/analytics rejects non-integer days."""
        response = self.client.get("/api/stats/analytics?days=abc")
        self.assertEqual(response.status_code, 422)  # Pydantic validation error


class StatsAPIHelpersTests(unittest.TestCase):
    """Test helper functions in stats module."""

    def test_categorize_error_message_timeout(self):
        """Error categorization: Timeout patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("Task timeout deadline exceeded")
        self.assertEqual(result, "Timeout")

        result = _categorize_error_message("Execution timed out after 1800 seconds")
        self.assertEqual(result, "Timeout")

    def test_categorize_error_message_resource(self):
        """Error categorization: Resource patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("Container out of memory")
        self.assertEqual(result, "Resource")

        result = _categorize_error_message("Disk quota exceeded")
        self.assertEqual(result, "Resource")

    def test_categorize_error_message_docker(self):
        """Error categorization: Docker patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("docker container failed to start")
        self.assertEqual(result, "Docker")

        result = _categorize_error_message("OCI runtime error")
        self.assertEqual(result, "Docker")

    def test_categorize_error_message_auth(self):
        """Error categorization: Authentication patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("GitLab unauthorized access")
        self.assertEqual(result, "Authentication")

        result = _categorize_error_message("Token expired permission denied")
        self.assertEqual(result, "Authentication")

    def test_categorize_error_message_network(self):
        """Error categorization: Network patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("Connection refused to GitLab")
        self.assertEqual(result, "Network")

        result = _categorize_error_message("SSL certificate verify failed")
        self.assertEqual(result, "Network")

    def test_categorize_error_message_git(self):
        """Error categorization: Git patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("Merge conflict in branch")
        self.assertEqual(result, "Git")

        result = _categorize_error_message("git push failed")
        self.assertEqual(result, "Git")

    def test_categorize_error_message_dependencies(self):
        """Error categorization: Dependencies patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("ModuleNotFoundError: No module named 'requests'")
        self.assertEqual(result, "Dependencies")

        result = _categorize_error_message("pip install failed")
        self.assertEqual(result, "Dependencies")

    def test_categorize_error_message_tests(self):
        """Error categorization: Tests patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("pytest test failed")
        self.assertEqual(result, "Tests")

        result = _categorize_error_message("AssertionError: expected 200 got 404")
        self.assertEqual(result, "Tests")

    def test_categorize_error_message_code(self):
        """Error categorization: Code patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("SyntaxError: invalid syntax")
        self.assertEqual(result, "Code")

        result = _categorize_error_message("TypeError: unsupported operand type(s)")
        self.assertEqual(result, "Code")

    def test_categorize_error_message_other(self):
        """Error categorization: Unknown patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("Something completely unexpected happened")
        self.assertEqual(result, "Other")

        result = _categorize_error_message(None)
        self.assertEqual(result, "Other")

    def test_summarize_error_message(self):
        """Test error message summarization."""
        from app.api.stats import _summarize_error_message

        # First 160 chars of first line
        long_message = "This is a very long error message that spans multiple lines\nSecond line here\nThird line here"
        result = _summarize_error_message(long_message)
        self.assertTrue(len(result) <= 160)
        self.assertEqual(result, "This is a very long error message that spans multiple lines")

    def test_summarize_error_message_empty(self):
        """Test summarization of empty/None messages."""
        from app.api.stats import _summarize_error_message

        result = _summarize_error_message(None)
        self.assertIsNone(result)

        result = _summarize_error_message("")
        self.assertIsNone(result)

        result = _summarize_error_message("   \n   \n   ")
        self.assertIsNone(result)
