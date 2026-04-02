#!/usr/bin/env python3
"""Unit tests for task API helpers and status-transition validators."""

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.task_operations import (
    validate_scheduled_datetime_in_future,
    validate_task_status_for_cancel,
    validate_task_status_for_execute,
    validate_task_status_for_reschedule,
    validate_task_status_for_retry,
)
from app.models import TaskStatus


def _make_task(status: TaskStatus, scheduled_at=None) -> MagicMock:
    """Helper: build a MagicMock Task with the given status."""
    task = MagicMock()
    task.status = status
    task.scheduled_at = scheduled_at
    return task


# ---------------------------------------------------------------------------
# validate_task_status_for_cancel
# ---------------------------------------------------------------------------

class ValidateCancelTests(unittest.TestCase):
    """Tests for validate_task_status_for_cancel."""

    def test_cancel_valid_statuses(self) -> None:
        """PENDING, QUEUED and RUNNING tasks can be cancelled without error."""
        for status in [TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING]:
            with self.subTest(status=status):
                validate_task_status_for_cancel(_make_task(status))  # should not raise

    def test_cancel_invalid_statuses(self) -> None:
        """FAILED, CANCELLED and COMPLETED tasks cannot be cancelled."""
        for status in [TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.COMPLETED]:
            with self.subTest(status=status):
                with self.assertRaises(HTTPException) as ctx:
                    validate_task_status_for_cancel(_make_task(status))
                self.assertEqual(ctx.exception.status_code, 400)


# ---------------------------------------------------------------------------
# validate_task_status_for_retry
# ---------------------------------------------------------------------------

class ValidateRetryTests(unittest.TestCase):
    """Tests for validate_task_status_for_retry."""

    def test_retry_valid_statuses(self) -> None:
        """FAILED and CANCELLED tasks can be retried."""
        for status in [TaskStatus.FAILED, TaskStatus.CANCELLED]:
            with self.subTest(status=status):
                validate_task_status_for_retry(_make_task(status))  # should not raise

    def test_retry_invalid_statuses(self) -> None:
        """PENDING, RUNNING, QUEUED and COMPLETED tasks cannot be retried."""
        for status in [TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.QUEUED, TaskStatus.COMPLETED]:
            with self.subTest(status=status):
                with self.assertRaises(HTTPException) as ctx:
                    validate_task_status_for_retry(_make_task(status))
                self.assertEqual(ctx.exception.status_code, 400)


# ---------------------------------------------------------------------------
# validate_task_status_for_execute
# ---------------------------------------------------------------------------

class ValidateExecuteTests(unittest.TestCase):
    """Tests for validate_task_status_for_execute."""

    def test_execute_valid_status(self) -> None:
        """PENDING task can be executed immediately."""
        validate_task_status_for_execute(_make_task(TaskStatus.PENDING))

    def test_execute_invalid_statuses(self) -> None:
        """Non-PENDING tasks cannot be executed immediately."""
        for status in [TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.FAILED,
                       TaskStatus.CANCELLED, TaskStatus.COMPLETED]:
            with self.subTest(status=status):
                with self.assertRaises(HTTPException) as ctx:
                    validate_task_status_for_execute(_make_task(status))
                self.assertEqual(ctx.exception.status_code, 400)


# ---------------------------------------------------------------------------
# validate_task_status_for_reschedule
# ---------------------------------------------------------------------------

class ValidateRescheduleTests(unittest.TestCase):
    """Tests for validate_task_status_for_reschedule."""

    def test_reschedule_valid(self) -> None:
        """PENDING task with a scheduled_at can be rescheduled."""
        future = datetime.now(UTC) + timedelta(hours=1)
        validate_task_status_for_reschedule(_make_task(TaskStatus.PENDING, scheduled_at=future))

    def test_reschedule_invalid_status(self) -> None:
        """Non-PENDING tasks cannot be rescheduled."""
        future = datetime.now(UTC) + timedelta(hours=1)
        for status in [TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.COMPLETED]:
            with self.subTest(status=status):
                with self.assertRaises(HTTPException) as ctx:
                    validate_task_status_for_reschedule(_make_task(status, scheduled_at=future))
                self.assertEqual(ctx.exception.status_code, 400)

    def test_reschedule_raises_when_scheduled_at_is_none(self) -> None:
        """PENDING task without scheduled_at (manual task) cannot be rescheduled."""
        with self.assertRaises(HTTPException) as ctx:
            validate_task_status_for_reschedule(_make_task(TaskStatus.PENDING, scheduled_at=None))
        self.assertEqual(ctx.exception.status_code, 400)


# ---------------------------------------------------------------------------
# validate_scheduled_datetime_in_future
# ---------------------------------------------------------------------------

class ValidateScheduledDatetimeTests(unittest.TestCase):
    """Tests for validate_scheduled_datetime_in_future."""

    def test_future_date_passes(self) -> None:
        """A datetime in the future should be returned without error."""
        future = datetime.now(UTC) + timedelta(hours=1)
        result = validate_scheduled_datetime_in_future(future)
        self.assertIsNotNone(result)

    def test_past_date_raises_http_exception(self) -> None:
        """A datetime in the past should raise HTTPException."""
        past = datetime.now(UTC) - timedelta(hours=1)
        with self.assertRaises(HTTPException) as ctx:
            validate_scheduled_datetime_in_future(past)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_returns_naive_utc_datetime(self) -> None:
        """The returned datetime should have no timezone info (naive UTC)."""
        future = datetime.now(UTC) + timedelta(hours=1)
        result = validate_scheduled_datetime_in_future(future)
        self.assertIsNone(result.tzinfo)


# ---------------------------------------------------------------------------
# cancel_task endpoint via FastAPI TestClient
# ---------------------------------------------------------------------------

class CancelTaskEndpointTests(unittest.TestCase):
    """Integration-style tests for the POST /api/tasks/{task_id}/cancel endpoint."""

    def _get_client(self, task=None):
        """Build a TestClient with all dependencies overridden."""
        from app.main import app
        from app.database import get_db
        from app.dependencies.auth import get_optional_current_user, require_authenticated_user
        from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        mock_db = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        if task is not None:
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = task
            mock_db.execute = AsyncMock(return_value=mock_result)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_optional_current_user] = lambda: None
        app.dependency_overrides[require_authenticated_user] = lambda: MagicMock()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        client = TestClient(app, raise_server_exceptions=False)
        return client, app

    def test_cancel_changes_status_to_cancelled(self) -> None:
        """POST /api/tasks/{id}/cancel should set task status to CANCELLED and return 200."""
        task = MagicMock()
        task.id = 1
        task.project_id = 1
        task.issue_iid = 10
        task.status = TaskStatus.PENDING
        task.scheduled_at = None

        client, app = self._get_client(task)

        with patch("app.api.task_operations.notify_task_cancelled", new=AsyncMock()):
            with patch("app.core.task_helpers._require_task_operator", return_value=None):
                response = client.post("/api/tasks/1/cancel")

        # Clean up overrides
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(task.status, TaskStatus.CANCELLED)

    def test_cancel_task_404_when_not_found(self) -> None:
        """POST /api/tasks/{id}/cancel should return 404 when task not found."""
        from app.main import app
        from app.database import get_db
        from app.dependencies.auth import get_optional_current_user, require_authenticated_user
        from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_optional_current_user] = lambda: None
        app.dependency_overrides[require_authenticated_user] = lambda: MagicMock()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/api/tasks/9999/cancel")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Helper: make a serializable mock task (all attributes _serialize_task needs)
# ---------------------------------------------------------------------------

def _make_serializable_task(task_status=TaskStatus.PENDING, task_id=1, project_id=1):
    """Create a mock task with all attributes needed for _serialize_task."""
    task = MagicMock()
    task.id = task_id
    task.project_id = project_id
    task.issue_iid = 10
    task.issue_id = 100
    task.note_id = 1000
    task.user_prompt = "Test prompt"
    task.initiator_user_id = None
    task.initiator_gitlab_user_id = None
    task.initiator_username = None
    task.branch_name = "codify/issue-10"
    task.merge_request_iid = None
    task.merge_request_url = None
    task.status = task_status
    task.priority = 0
    task.scheduled_at = None
    task.container_id = None
    task.target_branch = "main"
    task.base_branch = None
    task.commit_sha = None
    task.error_message = None
    task.additions = 0
    task.deletions = 0
    task.total_changes = 0
    task.input_tokens = 0
    task.output_tokens = 0
    task.is_manual = False
    now = datetime(2024, 1, 1, 12, 0, 0)
    task.created_at = now
    task.updated_at = now
    task.started_at = None
    task.completed_at = None
    return task


def _make_app_client_with_db(mock_db, extra_overrides=None):
    """Build a TestClient with DB and access scope overridden."""
    from app.main import app
    from app.database import get_db
    from app.dependencies.auth import get_optional_current_user
    from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope

    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_optional_current_user] = lambda: None
    app.dependency_overrides[require_project_access_scope] = lambda: access_scope
    if extra_overrides:
        app.dependency_overrides.update(extra_overrides)

    return TestClient(app, raise_server_exceptions=False), app


# ---------------------------------------------------------------------------
# GET /tasks/{task_id}/logs — log retrieval endpoint
# ---------------------------------------------------------------------------

class GetTaskLogsAPITests(unittest.TestCase):
    """Tests for GET /api/tasks/{task_id}/logs."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_get_task_logs_returns_logs_for_valid_task(self):
        """GET /api/tasks/{id}/logs should return log entries for an existing task."""
        task = _make_serializable_task()

        log1 = MagicMock()
        log1.id = 1
        log1.task_id = 1
        log1.log_level = "INFO"
        log1.message = "Starting task execution"
        log1.created_at = datetime(2024, 1, 1, 12, 0, 0)

        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task

        logs_result = MagicMock()
        logs_result.scalars.return_value.all.return_value = [log1]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[task_result, logs_result])

        client, app = _make_app_client_with_db(mock_db)
        response = client.get("/api/tasks/1/logs")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["message"], "Starting task execution")
        self.assertEqual(data[0]["log_level"], "INFO")
        self.assertEqual(data[0]["task_id"], 1)

    def test_get_task_logs_returns_empty_list_when_no_logs(self):
        """GET /api/tasks/{id}/logs should return empty list when task has no logs."""
        task = _make_serializable_task()

        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task

        logs_result = MagicMock()
        logs_result.scalars.return_value.all.return_value = []

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[task_result, logs_result])

        client, app = _make_app_client_with_db(mock_db)
        response = client.get("/api/tasks/1/logs")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_get_task_logs_returns_404_when_task_not_found(self):
        """GET /api/tasks/{id}/logs should return 404 when task does not exist."""
        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=task_result)

        client, app = _make_app_client_with_db(mock_db)
        response = client.get("/api/tasks/9999/logs")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/retry — retry endpoint
# ---------------------------------------------------------------------------

class RetryTaskAPITests(unittest.TestCase):
    """Tests for POST /api/tasks/{task_id}/retry."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_retry_task_success_for_failed_task(self):
        """POST /api/tasks/{id}/retry should reset a FAILED task to PENDING."""
        task = _make_serializable_task(task_status=TaskStatus.FAILED)
        task.id = 5
        task.project_id = 1

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        client, app = _make_app_client_with_db(mock_db)

        with patch("app.api.task_operations.notify_task_retried", new=AsyncMock()):
            with patch("app.core.task_helpers._require_task_operator", return_value=None):
                response = client.post("/api/tasks/5/retry")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(task.status, TaskStatus.PENDING)
        self.assertIsNone(task.error_message)

    def test_retry_task_success_for_cancelled_task(self):
        """POST /api/tasks/{id}/retry should reset a CANCELLED task to PENDING."""
        task = _make_serializable_task(task_status=TaskStatus.CANCELLED)
        task.id = 6
        task.project_id = 1

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        client, app = _make_app_client_with_db(mock_db)

        with patch("app.api.task_operations.notify_task_retried", new=AsyncMock()):
            with patch("app.core.task_helpers._require_task_operator", return_value=None):
                response = client.post("/api/tasks/6/retry")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(task.status, TaskStatus.PENDING)

    def test_retry_task_returns_404_when_not_found(self):
        """POST /api/tasks/{id}/retry should return 404 when task does not exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        client, app = _make_app_client_with_db(mock_db)
        response = client.post("/api/tasks/9999/retry")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 404)

    def test_retry_task_returns_400_for_running_task(self):
        """POST /api/tasks/{id}/retry should return 400 for a RUNNING task."""
        task = _make_serializable_task(task_status=TaskStatus.RUNNING)
        task.id = 7
        task.project_id = 1

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        client, app = _make_app_client_with_db(mock_db)

        with patch("app.core.task_helpers._require_task_operator", return_value=None):
            response = client.post("/api/tasks/7/retry")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 400)


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/execute — immediate execution endpoint
# ---------------------------------------------------------------------------

class ExecuteTaskAPITests(unittest.TestCase):
    """Tests for POST /api/tasks/{task_id}/execute."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_execute_task_success_for_pending_task(self):
        """POST /api/tasks/{id}/execute should clear scheduled_at for a PENDING task."""
        task = _make_serializable_task(task_status=TaskStatus.PENDING)
        task.id = 10
        task.project_id = 1
        task.scheduled_at = datetime(2024, 6, 1, 12, 0, 0)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        client, app = _make_app_client_with_db(mock_db)

        with patch("app.api.task_operations.notify_task_execute_now", new=AsyncMock()):
            with patch("app.core.task_helpers._require_task_operator", return_value=None):
                response = client.post("/api/tasks/10/execute")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(task.scheduled_at)

    def test_execute_task_returns_404_when_not_found(self):
        """POST /api/tasks/{id}/execute should return 404 when task does not exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        client, app = _make_app_client_with_db(mock_db)
        response = client.post("/api/tasks/9999/execute")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 404)

    def test_execute_task_returns_400_for_running_task(self):
        """POST /api/tasks/{id}/execute should return 400 for a non-PENDING task."""
        task = _make_serializable_task(task_status=TaskStatus.RUNNING)
        task.id = 11
        task.project_id = 1

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        client, app = _make_app_client_with_db(mock_db)

        with patch("app.core.task_helpers._require_task_operator", return_value=None):
            response = client.post("/api/tasks/11/execute")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 400)


# ---------------------------------------------------------------------------
# GET /tasks/{task_id}/stats — task MR stats endpoint
# ---------------------------------------------------------------------------

class GetTaskStatsAPITests(unittest.TestCase):
    """Tests for GET /api/tasks/{task_id}/stats."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_get_task_stats_returns_db_values_when_available(self):
        """GET /api/tasks/{id}/stats returns DB stats when non-zero."""
        task = _make_serializable_task()
        task.id = 20
        task.project_id = 1
        task.additions = 50
        task.deletions = 10
        task.total_changes = 60
        task.merge_request_iid = 5

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        client, app = _make_app_client_with_db(mock_db)
        response = client.get("/api/tasks/20/stats")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["additions"], 50)
        self.assertEqual(data["deletions"], 10)
        self.assertEqual(data["total"], 60)

    def test_get_task_stats_returns_zeros_when_no_mr_iid(self):
        """GET /api/tasks/{id}/stats returns zeros when no merge_request_iid."""
        task = _make_serializable_task()
        task.id = 21
        task.project_id = 1
        task.additions = 0
        task.deletions = 0
        task.total_changes = 0
        task.merge_request_iid = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        client, app = _make_app_client_with_db(mock_db)
        response = client.get("/api/tasks/21/stats")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data, {"additions": 0, "deletions": 0, "total": 0})

    def test_get_task_stats_returns_404_when_task_not_found(self):
        """GET /api/tasks/{id}/stats returns 404 when task does not exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        client, app = _make_app_client_with_db(mock_db)
        response = client.get("/api/tasks/9999/stats")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# POST /tasks — create task endpoint
# ---------------------------------------------------------------------------

class CreateTaskAPITests(unittest.TestCase):
    """Tests for POST /api/tasks endpoint."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_create_task_success(self):
        """POST /api/tasks should create a new task and return its ID."""
        created_task = MagicMock()
        created_task.id = 99
        created_task.project_id = 1
        created_task.user_prompt = "Fix the login bug"
        created_task.branch_name = "fix/login"
        created_task.target_branch = "main"
        created_task.status = TaskStatus.PENDING
        created_task.priority = 0
        created_task.scheduled_at = None
        created_task.is_manual = True
        created_task.created_at = datetime(2024, 1, 1, 12, 0, 0)

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=lambda t: None)

        # Simulate refresh setting id
        async def fake_refresh(task):
            task.id = created_task.id

        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        from app.main import app
        from app.database import get_db
        from app.dependencies.auth import get_optional_current_user
        from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_optional_current_user] = lambda: None
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/api/tasks", json={
            "project_id": 1,
            "user_prompt": "Fix the login bug",
            "branch_name": "fix/login",
            "target_branch": "main",
            "priority": 0,
        })
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("id", data)
        self.assertEqual(data["project_id"], 1)
        self.assertEqual(data["user_prompt"], "Fix the login bug")


# ---------------------------------------------------------------------------
# Additional cancel tests
# ---------------------------------------------------------------------------

class CancelTaskAdditionalTests(unittest.TestCase):
    """Additional tests for the cancel task endpoint."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_cancel_task_returns_400_for_completed_task(self):
        """POST /api/tasks/{id}/cancel returns 400 for an already COMPLETED task."""
        task = _make_serializable_task(task_status=TaskStatus.COMPLETED)
        task.id = 50

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        client, app = _make_app_client_with_db(mock_db)

        with patch("app.core.task_helpers._require_task_operator", return_value=None):
            response = client.post("/api/tasks/50/cancel")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 400)
