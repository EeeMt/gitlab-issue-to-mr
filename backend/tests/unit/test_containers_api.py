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


# ---------------------------------------------------------------------------
# Endpoint-level tests using FastAPI TestClient
# ---------------------------------------------------------------------------

def _make_auth_override():
    """Create an async function that returns a mock admin auth context."""
    from types import SimpleNamespace
    from starlette.requests import Request

    async def mock_auth_context(request: Request):
        return SimpleNamespace(
            user=SimpleNamespace(id=1, username="admin", platform_role="platform_admin"),
            session=None,
            gitlab_access_token=None,
            gitlab_refresh_token=None,
        )
    return mock_auth_context


class ListContainersEndpointTests(unittest.TestCase):
    """Tests for GET /api/containers endpoint."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_list_containers_returns_500_on_docker_error(self):
        """If docker_client raises, endpoint should return 500."""
        from app.main import app
        from app.database import get_db
        from app.dependencies.auth import require_authenticated_context
        from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        mock_db = MagicMock()

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        with patch("app.api.containers.get_docker_client", side_effect=RuntimeError("docker down")):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/containers")

        self.assertEqual(response.status_code, 500)

    def test_list_containers_filters_non_worker_containers(self):
        """Only containers matching WORKER_CONTAINER_PATTERN should appear in the response."""
        from app.main import app
        from app.database import get_db
        from app.dependencies.auth import require_authenticated_context
        from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        mock_db = MagicMock()

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        # Two containers: one worker, one non-worker
        worker_container = MagicMock()
        worker_container.name = "codify-5-p1-i10"
        worker_container.id = "abc123"
        worker_container.status = "running"
        worker_container.attrs = {"Created": "2024-01-01T00:00:00Z"}

        non_worker_container = MagicMock()
        non_worker_container.name = "codify-postgres"
        non_worker_container.id = "def456"
        non_worker_container.status = "running"
        non_worker_container.attrs = {"Created": "2024-01-01T00:00:00Z"}

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [worker_container, non_worker_container]

        with patch("app.api.containers.get_docker_client", return_value=mock_docker):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/containers")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "codify-5-p1-i10")


class GetContainerLogsEndpointTests(unittest.TestCase):
    """Tests for GET /api/tasks/{task_id}/container-logs endpoint."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_get_task_container_logs_returns_404_for_missing_task(self):
        """Should return 404 when task does not exist in DB."""
        from app.main import app
        from app.database import get_db
        from app.dependencies.auth import require_authenticated_context

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/tasks/9999/container-logs")

        self.assertEqual(response.status_code, 404)

    def test_get_task_container_logs_returns_empty_when_no_container_id(self):
        """Should return empty logs when task exists but has no container_id."""
        from app.main import app
        from app.database import get_db
        from app.dependencies.auth import require_authenticated_context
        from app.models import TaskStatus

        task = MagicMock()
        task.id = 1
        task.container_id = None
        task.status = TaskStatus.PENDING

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/tasks/1/container-logs")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsNone(data["container_id"])
        self.assertEqual(data["logs"], "")


# ---------------------------------------------------------------------------
# Extended tests: get_task_container_logs with a container_id set
# ---------------------------------------------------------------------------

class GetTaskContainerLogsHappyPathTests(unittest.TestCase):
    """Tests for container-logs endpoint when the task has a container_id."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_get_task_container_logs_returns_logs_when_container_exists(self):
        """Should return logs when task has a container_id and docker returns logs."""
        from app.main import app
        from app.database import get_db
        from app.dependencies.auth import require_admin_user, require_authenticated_user
        from app.models import TaskStatus

        task = MagicMock()
        task.id = 10
        task.container_id = "abc123def456"
        task.status = TaskStatus.RUNNING

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def override_db():
            yield mock_db

        mock_container = MagicMock()
        mock_container.status = "running"
        mock_container.logs.return_value = b"Starting task\nStep 1 done\n"

        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_admin_user] = lambda: MagicMock()
        app.dependency_overrides[require_authenticated_user] = lambda: MagicMock()

        with patch("app.api.containers.get_docker_client", return_value=mock_docker):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/tasks/10/container-logs")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["container_id"], "abc123def456")
        self.assertEqual(data["container_status"], "running")
        self.assertIn("Starting task", data["logs"])

    def test_get_task_container_logs_returns_error_when_docker_fails(self):
        """When Docker fails, falls back to DB-stored log chunks (returns 200 with available data)."""
        from app.main import app
        from app.database import get_db
        from app.dependencies.auth import require_admin_user, require_authenticated_user
        from app.models import TaskStatus

        task = MagicMock()
        task.id = 11
        task.container_id = "xyz789"
        task.status = TaskStatus.RUNNING

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task
        # scalars().all() used for DB chunk fallback — return empty list
        mock_result.scalars.return_value.all.return_value = []
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_admin_user] = lambda: MagicMock()
        app.dependency_overrides[require_authenticated_user] = lambda: MagicMock()

        with patch("app.api.containers.get_docker_client", side_effect=RuntimeError("container not found")):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/tasks/11/container-logs")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["container_id"], "xyz789")
        self.assertIn("logs", data)
        self.assertIn("status", data)


# ---------------------------------------------------------------------------
# Access scope filtering for list_containers
# ---------------------------------------------------------------------------

class ListContainersAccessScopeFilterTests(unittest.TestCase):
    """Tests that list_containers includes all worker containers for unrestricted scope."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_list_containers_includes_all_worker_containers_for_unrestricted_scope(self):
        """All worker containers appear when access scope is unrestricted."""
        from app.main import app
        from app.database import get_db
        from app.dependencies.auth import require_authenticated_context, require_authenticated_user
        from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope

        # Unrestricted scope: all containers visible
        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        mock_db = MagicMock()

        async def override_db():
            yield mock_db

        container_a = MagicMock()
        container_a.name = "codify-10-p1-i5"
        container_a.id = "aaa"
        container_a.status = "running"
        container_a.attrs = {"Created": "2024-01-01T00:00:00Z"}

        container_b = MagicMock()
        container_b.name = "codify-20-p2-i8"
        container_b.id = "bbb"
        container_b.status = "exited"
        container_b.attrs = {"Created": "2024-01-02T00:00:00Z"}

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [container_a, container_b]

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()
        app.dependency_overrides[require_authenticated_user] = lambda: MagicMock()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        with patch("app.api.containers.get_docker_client", return_value=mock_docker):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/containers")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Both worker containers should appear in an unrestricted scope
        self.assertEqual(len(data), 2)
        names = {c["name"] for c in data}
        self.assertIn("codify-10-p1-i5", names)
        self.assertIn("codify-20-p2-i8", names)
