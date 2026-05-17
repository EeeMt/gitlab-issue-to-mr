#!/usr/bin/env python3
"""Unit tests for POST /tasks/{task_id}/override-status endpoint."""

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient

from app.models import TaskStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(status: TaskStatus, task_id: int = 1, issue_id: int | None = 100) -> MagicMock:
    """Build a minimal mock Task for override endpoint tests."""
    task = MagicMock()
    task.id = task_id
    task.project_id = 1
    task.issue_id = issue_id
    task.status = status
    task.is_manually_overridden = False
    task.override_reason = None
    task.overridden_by_user_id = None
    task.overridden_at = None
    now = datetime(2024, 1, 1, 12, 0, 0)
    task.created_at = now
    task.updated_at = now
    return task


def _make_client_with_task(task: MagicMock):
    """Set up a TestClient with mocked DB returning the given task."""
    from app.main import app
    from app.database import get_db
    from app.dependencies.auth import get_optional_current_user, require_authenticated_user
    from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope

    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = task

    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_optional_current_user] = lambda: None
    app.dependency_overrides[require_authenticated_user] = lambda: MagicMock()
    app.dependency_overrides[require_project_access_scope] = lambda: access_scope

    return TestClient(app, raise_server_exceptions=False), app, mock_db


# ---------------------------------------------------------------------------
# Override status endpoint tests
# ---------------------------------------------------------------------------

class OverrideTaskStatusTests(unittest.TestCase):
    """Tests for POST /api/tasks/{task_id}/override-status."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_completed_to_failed_succeeds(self):
        """A completed task can be marked as failed."""
        task = _make_task(TaskStatus.COMPLETED, task_id=10)
        client, app, mock_db = _make_client_with_task(task)

        with patch("app.core.task_helpers._require_task_operator", return_value=None), \
             patch("app.api.tasks.maybe_update_issue_status", new=AsyncMock()):
            response = client.post("/api/tasks/10/override-status", json={"status": "failed"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertTrue(task.is_manually_overridden)
        mock_db.commit.assert_called_once()

    def test_failed_to_completed_succeeds(self):
        """A failed task can be marked as completed."""
        task = _make_task(TaskStatus.FAILED, task_id=11)
        client, app, mock_db = _make_client_with_task(task)

        with patch("app.core.task_helpers._require_task_operator", return_value=None), \
             patch("app.api.tasks.maybe_update_issue_status", new=AsyncMock()):
            response = client.post("/api/tasks/11/override-status", json={"status": "completed"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertTrue(task.is_manually_overridden)

    def test_override_with_reason_stores_reason(self):
        """Reason is stored on the task when provided."""
        task = _make_task(TaskStatus.COMPLETED, task_id=12)
        client, app, _ = _make_client_with_task(task)

        with patch("app.core.task_helpers._require_task_operator", return_value=None), \
             patch("app.api.tasks.maybe_update_issue_status", new=AsyncMock()):
            response = client.post(
                "/api/tasks/12/override-status",
                json={"status": "failed", "reason": "Output was wrong"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(task.override_reason, "Output was wrong")

    def test_override_without_reason_sets_none(self):
        """override_reason is None when no reason is given."""
        task = _make_task(TaskStatus.FAILED, task_id=13)
        client, app, _ = _make_client_with_task(task)

        with patch("app.core.task_helpers._require_task_operator", return_value=None), \
             patch("app.api.tasks.maybe_update_issue_status", new=AsyncMock()):
            response = client.post("/api/tasks/13/override-status", json={"status": "completed"})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(task.override_reason)

    def test_invalid_status_value_returns_400(self):
        """An invalid status string returns HTTP 400."""
        task = _make_task(TaskStatus.COMPLETED, task_id=14)
        client, app, _ = _make_client_with_task(task)

        with patch("app.core.task_helpers._require_task_operator", return_value=None):
            response = client.post("/api/tasks/14/override-status", json={"status": "running"})

        self.assertEqual(response.status_code, 400)

    def test_non_terminal_task_returns_400(self):
        """Running tasks cannot be overridden."""
        task = _make_task(TaskStatus.RUNNING, task_id=15)
        client, app, _ = _make_client_with_task(task)

        with patch("app.core.task_helpers._require_task_operator", return_value=None):
            response = client.post("/api/tasks/15/override-status", json={"status": "failed"})

        self.assertEqual(response.status_code, 400)

    def test_cancelled_task_returns_400(self):
        """Cancelled tasks cannot be overridden (only completed/failed)."""
        task = _make_task(TaskStatus.CANCELLED, task_id=16)
        client, app, _ = _make_client_with_task(task)

        with patch("app.core.task_helpers._require_task_operator", return_value=None):
            response = client.post("/api/tasks/16/override-status", json={"status": "completed"})

        self.assertEqual(response.status_code, 400)

    def test_same_status_returns_400(self):
        """Overriding a task to its current status returns HTTP 400."""
        task = _make_task(TaskStatus.FAILED, task_id=17)
        client, app, _ = _make_client_with_task(task)

        with patch("app.core.task_helpers._require_task_operator", return_value=None):
            response = client.post("/api/tasks/17/override-status", json={"status": "failed"})

        self.assertEqual(response.status_code, 400)

    def test_maybe_update_issue_status_called_when_issue_present(self):
        """maybe_update_issue_status is called when task has an issue_id."""
        task = _make_task(TaskStatus.COMPLETED, task_id=18, issue_id=55)
        client, app, _ = _make_client_with_task(task)

        mock_update = AsyncMock()
        with patch("app.core.task_helpers._require_task_operator", return_value=None), \
             patch("app.api.tasks.maybe_update_issue_status", new=mock_update):
            response = client.post("/api/tasks/18/override-status", json={"status": "failed"})

        self.assertEqual(response.status_code, 200)
        mock_update.assert_called_once()

    def test_maybe_update_issue_status_not_called_without_issue(self):
        """maybe_update_issue_status is not called when task has no issue_id."""
        task = _make_task(TaskStatus.COMPLETED, task_id=19, issue_id=None)
        client, app, _ = _make_client_with_task(task)

        mock_update = AsyncMock()
        with patch("app.core.task_helpers._require_task_operator", return_value=None), \
             patch("app.api.tasks.maybe_update_issue_status", new=mock_update):
            response = client.post("/api/tasks/19/override-status", json={"status": "failed"})

        self.assertEqual(response.status_code, 200)
        mock_update.assert_not_called()

    def test_override_sets_overridden_at_timestamp(self):
        """overridden_at is set to a datetime after a successful override."""
        task = _make_task(TaskStatus.FAILED, task_id=20)
        client, app, _ = _make_client_with_task(task)

        with patch("app.core.task_helpers._require_task_operator", return_value=None), \
             patch("app.api.tasks.maybe_update_issue_status", new=AsyncMock()):
            response = client.post("/api/tasks/20/override-status", json={"status": "completed"})

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(task.overridden_at)

    def test_missing_task_returns_404(self):
        """Requesting override for a non-existent task returns 404."""
        from app.main import app
        from app.database import get_db
        from app.dependencies.auth import get_optional_current_user, require_authenticated_user
        from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # task not found

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_optional_current_user] = lambda: None
        app.dependency_overrides[require_authenticated_user] = lambda: MagicMock()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/api/tasks/9999/override-status", json={"status": "failed"})

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
