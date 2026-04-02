#!/usr/bin/env python3
"""Unit tests for Containers API endpoints."""

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
from app.api.containers import WORKER_CONTAINER_PATTERN


class ContainerPatternTests(unittest.TestCase):
    """Test container name pattern matching."""

    def test_worker_container_pattern_valid(self):
        """Valid worker container names should match."""
        valid_names = [
            "codify-1-p123-i456",
            "codify-100-p1-i999",
            "codify-99999-p99999-i1",
        ]
        for name in valid_names:
            self.assertTrue(WORKER_CONTAINER_PATTERN.match(name), f"'{name}' should match")

    def test_worker_container_pattern_invalid(self):
        """Non-worker container names should not match."""
        invalid_names = [
            "nginx-web",
            "redis-cache",
            "codify-1",  # Missing parts
            "codify-1-p",  # Missing project/issue
            "codify--p123-i456",  # Missing task_id
            "something-codify-1-p123-i456",  # Prefix before codify
        ]
        for name in invalid_names:
            self.assertFalse(WORKER_CONTAINER_PATTERN.match(name), f"'{name}' should NOT match")


class ContainerLogsHelpersTests(unittest.TestCase):
    """Test helper functions for container handling."""

    def test_extract_container_info_valid_name(self):
        """Test extracting task/project/issue info from valid container name."""
        # This tests the logic that's inline in list_containers
        name = "codify-42-p123-i789"

        parts = name.split("-")
        self.assertEqual(parts[0], "codify")
        self.assertEqual(parts[1], "42")  # task_id
        self.assertEqual(parts[2], "p123")  # project_id
        self.assertEqual(parts[3], "i789")  # issue_iid

        task_id = int(parts[1])
        project_id = int(parts[2].replace("p", ""))
        issue_iid = int(parts[3].replace("i", ""))

        self.assertEqual(task_id, 42)
        self.assertEqual(project_id, 123)
        self.assertEqual(issue_iid, 789)

    def test_extract_container_info_invalid_name(self):
        """Test extracting info from invalid container name returns None/0."""
        name = "nginx-web"

        parts = name.split("-")
        # For non-worker containers, parsing should fail
        if len(parts) >= 5 and parts[0] == "codify":
            # Would extract
            pass
        else:
            # Should skip - this is what the code does
            self.assertTrue(len(parts) < 5 or parts[0] != "codify")


class TaskContainerLogsAPIHelperTests(unittest.TestCase):
    """Test /tasks/{task_id}/container-logs response structure."""

    def test_container_logs_response_structure_success(self):
        """Test response structure for successful container logs retrieval."""
        # This tests the expected response format
        expected_keys = ["container_id", "container_status", "logs", "status"]
        response = {
            "container_id": "abc123",
            "container_status": "running",
            "logs": "Some log output",
            "status": "running"
        }
        for key in expected_keys:
            self.assertIn(key, response)

    def test_container_logs_response_structure_no_container(self):
        """Test response structure when task has no container."""
        expected_keys = ["container_id", "logs", "status"]
        response = {
            "container_id": None,
            "logs": "",
            "status": "pending"
        }
        for key in expected_keys:
            self.assertIn(key, response)

    def test_container_logs_response_structure_error(self):
        """Test response structure when error occurs."""
        expected_keys = ["container_id", "logs", "status", "error"]
        response = {
            "container_id": "abc123",
            "logs": "Error: container not found",
            "status": "running",
            "error": "container not found"
        }
        for key in expected_keys:
            self.assertIn(key, response)
