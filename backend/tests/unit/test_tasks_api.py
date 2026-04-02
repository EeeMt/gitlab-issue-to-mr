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
