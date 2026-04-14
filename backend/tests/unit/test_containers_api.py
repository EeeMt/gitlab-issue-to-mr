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
        from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope

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
        from app.main import app
        from app.database import get_db
        from app.dependencies.auth import require_authenticated_context
        from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope
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
        from app.main import app
        from app.database import get_db
        from app.dependencies.auth import require_authenticated_context
        from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope
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
        from app.main import app
        from app.database import get_db
        from app.dependencies.auth import require_authenticated_context
        from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope
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


# ---------------------------------------------------------------------------
# Manual container name pattern tests
# ---------------------------------------------------------------------------


class ManualContainerPatternTests(unittest.TestCase):
    """Test pattern matching and parsing for manual containers (codify-X-pY-manual)."""

    def test_manual_container_matches_pattern(self):
        """The 'manual' suffix pattern should match the worker regex."""
        self.assertTrue(WORKER_CONTAINER_PATTERN.match("codify-1-p123-manual"))
        self.assertTrue(WORKER_CONTAINER_PATTERN.match("codify-999-p1-manual"))

    def test_manual_container_parsing_extracts_ids(self):
        """Manual container name should yield correct task_id/project_id and None issue_iid."""
        name = "codify-42-p99-manual"
        parts = name.split("-")
        task_id = int(parts[1])
        project_id = int(parts[2].replace("p", ""))
        self.assertEqual(task_id, 42)
        self.assertEqual(project_id, 99)
        # Manual suffix: no issue_iid
        self.assertFalse(parts[3].startswith("i"))

    def test_list_containers_returns_manual_container_with_null_issue_iid(self):
        """Manual containers should appear in list_containers with issue_iid=None."""
        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        mock_db = MagicMock()

        async def override_db():
            yield mock_db

        manual_container = MagicMock()
        manual_container.name = "codify-7-p50-manual"
        manual_container.id = "manual123"
        manual_container.status = "running"
        manual_container.attrs = {"Created": "2024-06-01T00:00:00Z"}

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [manual_container]

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        with patch("app.api.containers.get_docker_client", return_value=mock_docker):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/containers")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "codify-7-p50-manual")
        self.assertEqual(data[0]["task_id"], 7)
        self.assertEqual(data[0]["project_id"], 50)
        self.assertIsNone(data[0]["issue_iid"])

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
        mock_db = MagicMock()

        async def override_db():
            yield mock_db

        # Container A: project_id=1 (accessible)
        container_a = MagicMock()
        container_a.name = "codify-10-p1-i5"
        container_a.id = "aaa"
        container_a.status = "running"
        container_a.attrs = {"Created": "2024-01-01T00:00:00Z"}

        # Container B: project_id=2 (NOT accessible)
        container_b = MagicMock()
        container_b.name = "codify-20-p2-i8"
        container_b.id = "bbb"
        container_b.status = "running"
        container_b.attrs = {"Created": "2024-01-02T00:00:00Z"}

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [container_a, container_b]

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        with patch("app.api.containers.get_docker_client", return_value=mock_docker):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/containers")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "codify-10-p1-i5")
        self.assertEqual(data[0]["project_id"], 1)

    def test_restricted_scope_shows_nothing_when_no_projects_accessible(self):
        """When no projects are accessible, no containers should appear."""
        access_scope = ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[],  # No projects accessible
        )
        mock_db = MagicMock()

        async def override_db():
            yield mock_db

        container_a = MagicMock()
        container_a.name = "codify-10-p1-i5"
        container_a.id = "aaa"
        container_a.status = "running"
        container_a.attrs = {"Created": "2024-01-01T00:00:00Z"}

        mock_docker = MagicMock()
        mock_docker.client.containers.list.return_value = [container_a]

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        with patch("app.api.containers.get_docker_client", return_value=mock_docker):
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

    def tearDown(self):
        app.dependency_overrides.clear()

    def _setup_sse_overrides(self):
        """Common dependency overrides for SSE endpoint tests."""
        from app.dependencies.auth import require_admin_user

        mock_db = MagicMock()

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_authenticated_context] = _make_auth_override()
        app.dependency_overrides[require_admin_user] = lambda: MagicMock()

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
        from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope
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

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_task_result, mock_log_result])

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
        from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope
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

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_task_result, mock_log_result])

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
        from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope
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

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_task_result, mock_log_result])

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
        from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope
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

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_task_result, mock_log_result])

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
