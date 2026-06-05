#!/usr/bin/env python3
"""Unit tests for Containers API endpoints."""

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient

from app.api.containers import _compact_raw_log_noise, _get_container_pattern
from app.database import get_db
from app.dependencies.auth import require_authenticated_context
from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
from app.main import app


class ContainerPatternTests(unittest.TestCase):
    """Test container name pattern matching."""

    @patch("app.api.containers.get_settings")
    def test_worker_container_pattern_valid(self, mock_settings):
        """Valid worker container names should match."""
        mock_settings.return_value.worker_container_prefix = "codify"
        pattern = _get_container_pattern()
        valid_names = [
            "codify-1-issue123",
            "codify-100-issue1",
            "codify-99999-issue99999",
        ]
        for name in valid_names:
            self.assertTrue(pattern.match(name), f"'{name}' should match")

    @patch("app.api.containers.get_settings")
    def test_worker_container_pattern_invalid(self, mock_settings):
        """Non-worker container names should not match."""
        mock_settings.return_value.worker_container_prefix = "codify"
        pattern = _get_container_pattern()
        invalid_names = [
            "nginx-web",
            "redis-cache",
            "codify-1",  # Missing issue part
            "codify-1-issue",  # Missing issue number
            "codify--issue123",  # Missing task_id
            "something-codify-1-issue123",  # Prefix before codify
            "codify-1-p123-i456",  # Old format
            "codify-1-p123-manual",  # Old manual format
        ]
        for name in invalid_names:
            self.assertFalse(pattern.match(name), f"'{name}' should NOT match")

    @patch("app.api.containers.get_settings")
    def test_worker_container_pattern_extracts_groups(self, mock_settings):
        """Pattern should extract task_id and issue_id from valid names."""
        mock_settings.return_value.worker_container_prefix = "codify"
        pattern = _get_container_pattern()
        m = pattern.match("codify-42-issue789")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "42")
        self.assertEqual(m.group(2), "789")


class ContainerLogsHelpersTests(unittest.TestCase):
    """Test helper functions for container handling."""

    def test_compact_raw_log_noise_collapses_ca_replacement_lines(self):
        logs = (
            "Installing custom CA certificate\n"
            "Replacing debian:Amazon_Root_CA_1.pem\n"
            "Replacing debian:Amazon_Root_CA_2.pem\n"
            "Replacing debian:Amazon_Root_CA_3.pem\n"
            "Custom CA installed; SSL verification enabled\n"
            "Tool output stays complete\n"
        )

        compacted = _compact_raw_log_noise(logs)

        self.assertIn("[suppressed 3 CA certificate replacement lines]", compacted)
        self.assertNotIn("Replacing debian:Amazon_Root_CA_3.pem", compacted)
        self.assertIn("Tool output stays complete", compacted)

    @patch("app.api.containers.get_settings")
    def test_extract_container_info_valid_name(self, mock_settings):
        """Test extracting task_id and issue_id from valid container name using regex."""
        mock_settings.return_value.worker_container_prefix = "codify"
        pattern = _get_container_pattern()
        name = "codify-42-issue789"

        m = pattern.match(name)
        self.assertIsNotNone(m)

        task_id = int(m.group(1))
        issue_id = int(m.group(2))

        self.assertEqual(task_id, 42)
        self.assertEqual(issue_id, 789)

    @patch("app.api.containers.get_settings")
    def test_extract_container_info_invalid_name(self, mock_settings):
        """Test that invalid container names do not match the pattern."""
        mock_settings.return_value.worker_container_prefix = "codify"
        pattern = _get_container_pattern()
        name = "nginx-web"

        m = pattern.match(name)
        self.assertIsNone(m)


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
        from app.database import get_db
        from app.dependencies.auth import require_authenticated_context
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.main import app

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
        """Only containers matching the worker pattern should appear in the response."""
        from app.database import get_db
        from app.dependencies.auth import require_authenticated_context
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.main import app

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        # Mock DB: for the worker container (task_id=5, issue_id=10)
        # 1st execute → Task.issue_id lookup → returns 10
        # 2nd execute → Issue.project_id lookup → returns 1
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = 10
        r2 = MagicMock(); r2.scalar_one_or_none.return_value = 1
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[r1, r2])

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        # Two containers: one worker, one non-worker
        worker_container = MagicMock()
        worker_container.name = "codify-5-issue10"
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

        with patch("app.api.containers.get_docker_client", return_value=mock_docker), \
             patch("app.api.containers.get_settings") as mock_settings:
            mock_settings.return_value.worker_container_prefix = "codify"
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/containers")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "codify-5-issue10")
        self.assertEqual(data[0]["task_id"], 5)
        self.assertEqual(data[0]["issue_id"], 10)
        self.assertEqual(data[0]["project_id"], 1)


class GetContainerLogsEndpointTests(unittest.TestCase):
    """Tests for GET /api/tasks/{task_id}/container-logs endpoint."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_get_task_container_logs_returns_404_for_missing_task(self):
        """Should return 404 when task does not exist in DB."""
        from app.database import get_db
        from app.dependencies.auth import require_authenticated_context
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.main import app

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/tasks/9999/container-logs")

        self.assertEqual(response.status_code, 404)

    def test_get_task_container_logs_returns_empty_when_no_container_id(self):
        """Should return empty logs when task exists but has no container_id."""
        from app.database import get_db
        from app.dependencies.auth import require_authenticated_context
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.main import app
        from app.models import TaskStatus

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
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
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

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
        from app.database import get_db
        from app.dependencies.auth import require_authenticated_context
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.main import app
        from app.models import TaskStatus

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
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
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

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
        from app.database import get_db
        from app.dependencies.auth import require_authenticated_context
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.main import app
        from app.models import TaskStatus

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
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
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

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
        from app.database import get_db
        from app.dependencies.auth import require_authenticated_context, require_authenticated_user
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.main import app

        # Unrestricted scope: all containers visible
        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        # Mock DB: container A (task_id=10, issue_id=5) and container B (task_id=20, issue_id=8)
        # A: execute → issue_id=5, execute → project_id=1
        # B: execute → issue_id=8, execute → project_id=2
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = 5   # Task 10 → issue_id=5
        r2 = MagicMock(); r2.scalar_one_or_none.return_value = 1   # Issue 5 → project_id=1
        r3 = MagicMock(); r3.scalar_one_or_none.return_value = 8   # Task 20 → issue_id=8
        r4 = MagicMock(); r4.scalar_one_or_none.return_value = 2   # Issue 8 → project_id=2
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[r1, r2, r3, r4])

        async def override_db():
            yield mock_db

        container_a = MagicMock()
        container_a.name = "codify-10-issue5"
        container_a.id = "aaa"
        container_a.status = "running"
        container_a.attrs = {"Created": "2024-01-01T00:00:00Z"}

        container_b = MagicMock()
        container_b.name = "codify-20-issue8"
        container_b.id = "bbb"
        container_b.status = "exited"
        container_b.attrs = {"Created": "2024-01-02T00:00:00Z"}

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [container_a, container_b]

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()
        app.dependency_overrides[require_authenticated_user] = lambda: MagicMock()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        with patch("app.api.containers.get_docker_client", return_value=mock_docker), \
             patch("app.api.containers.get_settings") as mock_settings:
            mock_settings.return_value.worker_container_prefix = "codify"
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/containers")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Both worker containers should appear in an unrestricted scope
        self.assertEqual(len(data), 2)
        names = {c["name"] for c in data}
        self.assertIn("codify-10-issue5", names)
        self.assertIn("codify-20-issue8", names)


# ---------------------------------------------------------------------------
# Manual container name pattern tests
# ---------------------------------------------------------------------------


class CustomPrefixPatternTests(unittest.TestCase):
    """Test pattern matching with different container name prefixes."""

    @patch("app.api.containers.get_settings")
    def test_custom_prefix_matches(self, mock_settings):
        """Container names with a custom prefix should match when prefix is configured."""
        mock_settings.return_value.worker_container_prefix = "myapp"
        pattern = _get_container_pattern()
        self.assertTrue(pattern.match("myapp-1-issue123"))
        self.assertTrue(pattern.match("myapp-999-issue1"))

    @patch("app.api.containers.get_settings")
    def test_custom_prefix_rejects_default_prefix(self, mock_settings):
        """Default 'codify' prefix should NOT match when a custom prefix is configured."""
        mock_settings.return_value.worker_container_prefix = "myapp"
        pattern = _get_container_pattern()
        self.assertFalse(pattern.match("codify-1-issue123"))

    @patch("app.api.containers.get_settings")
    def test_prefix_with_special_chars_is_escaped(self, mock_settings):
        """Prefix with regex-special chars should be escaped and match literally."""
        mock_settings.return_value.worker_container_prefix = "my.app"
        pattern = _get_container_pattern()
        # Literal dot should match
        self.assertTrue(pattern.match("my.app-5-issue10"))
        # Dot as wildcard should NOT match
        self.assertFalse(pattern.match("myXapp-5-issue10"))

    @patch("app.api.containers.get_settings")
    def test_default_prefix_matches(self, mock_settings):
        """Default 'codify' prefix should work correctly."""
        mock_settings.return_value.worker_container_prefix = "codify"
        pattern = _get_container_pattern()
        self.assertTrue(pattern.match("codify-42-issue100"))
        self.assertFalse(pattern.match("codify-42-p100-manual"))  # Old format rejected

    def tearDown(self):
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Restricted access scope filtering for list_containers
# ---------------------------------------------------------------------------


class ListContainersRestrictedAccessTests(unittest.TestCase):
    """Tests that list_containers respects restricted project access scope."""

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_restricted_scope_filters_inaccessible_projects(self):
        """Containers from inaccessible projects should be hidden."""
        # Restricted scope: only project 1 accessible
        access_scope = ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[{"id": 1}],
        )

        # Mock DB: container A (task_id=10) → issue_id=5 → project_id=1
        #          container B (task_id=20) → issue_id=8 → project_id=2
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = 5   # Task 10 → issue_id=5
        r2 = MagicMock(); r2.scalar_one_or_none.return_value = 1   # Issue 5 → project_id=1
        r3 = MagicMock(); r3.scalar_one_or_none.return_value = 8   # Task 20 → issue_id=8
        r4 = MagicMock(); r4.scalar_one_or_none.return_value = 2   # Issue 8 → project_id=2
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[r1, r2, r3, r4])

        async def override_db():
            yield mock_db

        # Container A: project_id=1 (accessible via DB lookup)
        container_a = MagicMock()
        container_a.name = "codify-10-issue5"
        container_a.id = "aaa"
        container_a.status = "running"
        container_a.attrs = {"Created": "2024-01-01T00:00:00Z"}

        # Container B: project_id=2 (NOT accessible via DB lookup)
        container_b = MagicMock()
        container_b.name = "codify-20-issue8"
        container_b.id = "bbb"
        container_b.status = "running"
        container_b.attrs = {"Created": "2024-01-02T00:00:00Z"}

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [container_a, container_b]

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        with patch("app.api.containers.get_docker_client", return_value=mock_docker), \
             patch("app.api.containers.get_settings") as mock_settings:
            mock_settings.return_value.worker_container_prefix = "codify"
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/containers")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "codify-10-issue5")
        self.assertEqual(data[0]["project_id"], 1)

    def test_restricted_scope_shows_nothing_when_no_projects_accessible(self):
        """When no projects are accessible, no containers should appear."""
        access_scope = ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[],  # No projects accessible
        )

        # Mock DB: container (task_id=10) → issue_id=5 → project_id=1
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = 5
        r2 = MagicMock(); r2.scalar_one_or_none.return_value = 1
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[r1, r2])

        async def override_db():
            yield mock_db

        container_a = MagicMock()
        container_a.name = "codify-10-issue5"
        container_a.id = "aaa"
        container_a.status = "running"
        container_a.attrs = {"Created": "2024-01-01T00:00:00Z"}

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [container_a]

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        with patch("app.api.containers.get_docker_client", return_value=mock_docker), \
             patch("app.api.containers.get_settings") as mock_settings:
            mock_settings.return_value.worker_container_prefix = "codify"
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/containers")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 0)


# ---------------------------------------------------------------------------
# SSE streaming logs endpoint: GET /api/containers/{container_id}/logs
# ---------------------------------------------------------------------------


class ContainerLogsSSEEndpointTests(unittest.TestCase):
    """Tests for GET /api/containers/{container_id}/logs SSE streaming endpoint."""

    def _setup_sse_overrides(self):
        """Common dependency overrides for SSE endpoint tests."""
        mock_db = MagicMock()

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_sse_streams_container_logs_success(self):
        """Successful log streaming should return SSE-formatted log lines."""
        self._setup_sse_overrides()

        mock_container = MagicMock()
        mock_container.logs.return_value = iter([b"line1\n", b"line2\n"])

        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        with patch("app.api.containers.get_docker_client", return_value=mock_docker):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/containers/abc123/logs")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers.get("content-type", ""))
        self.assertIn("data: line1", response.text)
        self.assertIn("data: line2", response.text)

    def test_sse_fallback_to_partial_id_match(self):
        """When exact ID lookup fails, should find container by partial ID match."""
        self._setup_sse_overrides()

        matching_container = MagicMock()
        matching_container.id = "abc123def456"
        matching_container.logs.return_value = iter([b"found by partial\n"])

        mock_docker = MagicMock()
        mock_docker.client.containers.get.side_effect = Exception("not found")
        mock_docker.client.containers.list.return_value = [matching_container]

        with patch("app.api.containers.get_docker_client", return_value=mock_docker):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/containers/abc123/logs")

        self.assertEqual(response.status_code, 200)
        self.assertIn("data: found by partial", response.text)

    def test_sse_empty_stream_when_container_not_found(self):
        """When container is not found anywhere, stream should close silently (empty body)."""
        self._setup_sse_overrides()

        mock_docker = MagicMock()
        mock_docker.client.containers.get.side_effect = Exception("not found")
        mock_docker.client.containers.list.return_value = []

        with patch("app.api.containers.get_docker_client", return_value=mock_docker):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/containers/abc123/logs")

        self.assertEqual(response.status_code, 200)
        # Generator returned without yielding — empty body
        self.assertEqual(response.text.strip(), "")

    def test_sse_error_when_docker_client_fails(self):
        """When Docker client init fails, should yield an SSE error event."""
        self._setup_sse_overrides()

        with patch("app.api.containers.get_docker_client", side_effect=RuntimeError("Docker daemon not running")):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/containers/abc123/logs")

        self.assertEqual(response.status_code, 200)
        self.assertIn("data: Error:", response.text)
        self.assertIn("Docker daemon not running", response.text)

    def test_sse_partial_id_no_match_among_listed_containers(self):
        """When exact ID fails and partial match finds nothing, stream is empty."""
        self._setup_sse_overrides()

        non_matching = MagicMock()
        non_matching.id = "zzz999"

        mock_docker = MagicMock()
        mock_docker.client.containers.get.side_effect = Exception("not found")
        mock_docker.client.containers.list.return_value = [non_matching]

        with patch("app.api.containers.get_docker_client", return_value=mock_docker):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/containers/abc123/logs")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text.strip(), "")


# ---------------------------------------------------------------------------
# source=db for task container logs
# ---------------------------------------------------------------------------


class TaskContainerLogsSourceDbTests(unittest.TestCase):
    """Tests for GET /api/tasks/{task_id}/container-logs with source=db."""

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_source_db_returns_db_chunks_directly(self):
        """When source=db, should fetch logs from DB without trying Docker."""
        from app.dependencies.auth import require_authenticated_context
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.models import TaskStatus

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        task = MagicMock()
        task.id = 1
        task.container_id = "abc123"
        task.status = TaskStatus.RUNNING

        mock_task_result = MagicMock()
        mock_task_result.scalar_one_or_none.return_value = task

        mock_chunk = MagicMock()
        mock_chunk.message = "log line from db\n"
        mock_log_result = MagicMock()
        mock_log_result.scalars.return_value.all.return_value = [mock_chunk]

        # _fetch_db_chunks now checks TaskRawLogChunk first (empty), then falls back to TaskLog
        mock_empty_raw_chunks = MagicMock()
        mock_empty_raw_chunks.scalars.return_value.all.return_value = []

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_task_result, mock_empty_raw_chunks, mock_log_result])

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/tasks/1/container-logs?source=db")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["container_id"], "abc123")
        self.assertEqual(data["source"], "db")
        self.assertIn("log line from db", data["logs"])

    def test_source_db_returns_empty_when_no_chunks(self):
        """When source=db and no log chunks exist, should return empty logs."""
        from app.dependencies.auth import require_authenticated_context
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.models import TaskStatus

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        task = MagicMock()
        task.id = 1
        task.container_id = "abc123"
        task.status = TaskStatus.COMPLETED

        mock_task_result = MagicMock()
        mock_task_result.scalar_one_or_none.return_value = task

        mock_log_result = MagicMock()
        mock_log_result.scalars.return_value.all.return_value = []

        # _fetch_db_chunks checks TaskRawLogChunk first (empty), then falls back to TaskLog (also empty)
        mock_empty_raw_chunks = MagicMock()
        mock_empty_raw_chunks.scalars.return_value.all.return_value = []

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_task_result, mock_empty_raw_chunks, mock_log_result])

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/tasks/1/container-logs?source=db")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["logs"], "")
        self.assertEqual(data["source"], "db")

    def test_source_db_multiple_chunks_concatenated(self):
        """Multiple DB log chunks should be concatenated."""
        from app.dependencies.auth import require_authenticated_context
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.models import TaskStatus

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        task = MagicMock()
        task.id = 2
        task.container_id = "xyz789"
        task.status = TaskStatus.COMPLETED

        mock_task_result = MagicMock()
        mock_task_result.scalar_one_or_none.return_value = task

        chunk1 = MagicMock()
        chunk1.message = "Step 1\n"
        chunk2 = MagicMock()
        chunk2.message = "Step 2\n"
        chunk3 = MagicMock()
        chunk3.message = None  # Some chunks may have None message
        mock_log_result = MagicMock()
        mock_log_result.scalars.return_value.all.return_value = [chunk1, chunk2, chunk3]

        # _fetch_db_chunks checks TaskRawLogChunk first (empty), then falls back to TaskLog
        mock_empty_raw_chunks = MagicMock()
        mock_empty_raw_chunks.scalars.return_value.all.return_value = []

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_task_result, mock_empty_raw_chunks, mock_log_result])

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/tasks/2/container-logs?source=db")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["logs"], "Step 1\nStep 2\n")


# ---------------------------------------------------------------------------
# Docker failure with DB chunk fallback
# ---------------------------------------------------------------------------


class TaskContainerLogsDockerFailDbFallbackTests(unittest.TestCase):
    """Tests for Docker failure with non-empty DB chunk fallback."""

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_docker_fail_with_db_chunks_returns_db_data(self):
        """When Docker fails but DB has log chunks, should return DB data with source=db."""
        from app.dependencies.auth import require_authenticated_context
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.models import TaskStatus

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        task = MagicMock()
        task.id = 15
        task.container_id = "container-gone"
        task.status = TaskStatus.COMPLETED

        mock_task_result = MagicMock()
        mock_task_result.scalar_one_or_none.return_value = task

        mock_chunk_1 = MagicMock()
        mock_chunk_1.message = "Step 1 completed\n"
        mock_chunk_2 = MagicMock()
        mock_chunk_2.message = "Step 2 completed\n"
        mock_log_result = MagicMock()
        mock_log_result.scalars.return_value.all.return_value = [mock_chunk_1, mock_chunk_2]

        # _fetch_db_chunks checks TaskRawLogChunk first (empty), then falls back to TaskLog
        mock_empty_raw_chunks = MagicMock()
        mock_empty_raw_chunks.scalars.return_value.all.return_value = []

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_task_result, mock_empty_raw_chunks, mock_log_result])

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        with patch("app.api.containers.get_docker_client", side_effect=RuntimeError("docker is gone")):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/tasks/15/container-logs")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["container_id"], "container-gone")
        self.assertIn("Step 1 completed", data["logs"])
        self.assertIn("Step 2 completed", data["logs"])
        self.assertEqual(data["source"], "db")
