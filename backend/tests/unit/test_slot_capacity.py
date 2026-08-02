#!/usr/bin/env python3
"""Comprehensive unit tests for the slot capacity feature.

Covers:
  A. _get_slot_boundaries() — boundary calculations
  B. check_slot_capacity() — async capacity checking logic
  C. format_slot_rejection_message() — message formatting
  D. GET /tasks/slot-capacity — API endpoint
  E. POST /tasks — create_task slot enforcement
  F. POST /tasks/{id}/retry — retry slot enforcement
  G. PATCH /tasks/{id}/schedule — reschedule slot enforcement
"""

import asyncio
import os
import sys
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient

from app.core.slot_capacity import (
    SlotCapacityInfo,
    _get_slot_boundaries,
    check_slot_capacity,
    format_slot_rejection_message,
)
from app.models import TaskStatus

# ---------------------------------------------------------------------------
# Helpers (matching project conventions from test_tasks_api.py)
# ---------------------------------------------------------------------------

def _make_serializable_task(task_status=TaskStatus.PENDING, task_id=1, project_id=1):
    """Create a mock task with all attributes needed for _serialize_task."""
    task = MagicMock()
    task.id = task_id
    task.project_id = project_id
    task.issue_id = 1
    task.user_prompt = "Test prompt"
    task.initiator_user_id = None
    task.initiator_gitlab_user_id = None
    task.initiator_username = None
    task.is_retry = False
    task.retry_source_task_id = None
    task.status = task_status
    task.priority = 0
    task.scheduled_at = None
    task.container_id = None
    task.commit_sha = None
    task.error_message = None
    task.additions = 0
    task.deletions = 0
    task.total_changes = 0
    task.input_tokens = 0
    task.output_tokens = 0
    task.model_name = None
    task.commit_message = None
    task.issue = None
    now = datetime(2024, 1, 1, 12, 0, 0)
    task.worker_profile_snapshot = MagicMock(
        worker_profile_id=1,
        skill_references=[],
        skill_selection_source="profile",
    )
    task.provider_runtime_snapshot = {}
    task.rendered_prompt = "Rendered prompt"
    task.rendered_prompt_at = now
    task.run_instruction_template = "Execute {{user_prompt}}"
    task.runtime_bundle_id = 1
    task.created_at = now
    task.updated_at = now
    task.started_at = None
    task.completed_at = None
    return task


def _make_app_client_with_db(mock_db, extra_overrides=None):
    """Build a TestClient with DB, access scope, and auth overridden."""
    from app.database import get_db
    from app.dependencies.auth import get_optional_current_user, require_authenticated_user
    from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
    from app.main import app

    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_optional_current_user] = lambda: None
    app.dependency_overrides[require_authenticated_user] = lambda: MagicMock()
    app.dependency_overrides[require_project_access_scope] = lambda: access_scope
    if extra_overrides:
        app.dependency_overrides.update(extra_overrides)

    return TestClient(app, raise_server_exceptions=False), app


def _make_slot_info(
    count=3,
    max_tasks=5,
    is_full=False,
    enforce=True,
    hour_start=None,
    hour_end=None,
):
    """Create a SlotCapacityInfo with sensible defaults."""
    if hour_start is None:
        hour_start = datetime(2025, 1, 15, 14, 0, 0)
    if hour_end is None:
        hour_end = datetime(2025, 1, 15, 15, 0, 0)
    return SlotCapacityInfo(
        hour_start=hour_start,
        hour_end=hour_end,
        count=count,
        max=max_tasks,
        is_full=is_full,
        enforce=enforce,
    )


@contextmanager
def _mock_task_runtime_dependencies():
    """Isolate slot-capacity API tests from worker/provider snapshot setup."""
    worker_profile = MagicMock(id=1)
    provider = MagicMock(id=1)
    with (
        patch(
            "app.api.tasks.resolve_worker_profile_for_issue",
            new=AsyncMock(return_value=worker_profile),
        ),
        patch(
            "app.api.tasks.resolve_provider_for_issue",
            new=AsyncMock(return_value=provider),
        ),
        patch(
            "app.api.tasks.prepare_task_runtime_snapshot",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.api.tasks.get_project_metadata",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "app.api.tasks.clone_task_worker_snapshot",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "app.api.tasks.bind_runtime_bundle",
            new=AsyncMock(return_value=MagicMock(id=1)),
        ),
    ):
        yield


# ===========================================================================
# A. Unit tests for _get_slot_boundaries()
# ===========================================================================

class GetSlotBoundariesTests(unittest.TestCase):
    """Tests for _get_slot_boundaries — 1-hour slot boundary computation."""

    def test_normal_time_mid_hour(self) -> None:
        """14:30 should produce a slot from 14:00 to 15:00."""
        dt = datetime(2025, 1, 15, 14, 30, 0)
        start, end = _get_slot_boundaries(dt)
        self.assertEqual(start, datetime(2025, 1, 15, 14, 0, 0))
        self.assertEqual(end, datetime(2025, 1, 15, 15, 0, 0))

    def test_exactly_on_the_hour(self) -> None:
        """14:00:00 should produce a slot from 14:00 to 15:00."""
        dt = datetime(2025, 1, 15, 14, 0, 0)
        start, end = _get_slot_boundaries(dt)
        self.assertEqual(start, datetime(2025, 1, 15, 14, 0, 0))
        self.assertEqual(end, datetime(2025, 1, 15, 15, 0, 0))

    def test_hour_23_crosses_midnight(self) -> None:
        """23:45 should produce a slot from 23:00 to 00:00 next day."""
        dt = datetime(2025, 1, 15, 23, 45, 0)
        start, end = _get_slot_boundaries(dt)
        self.assertEqual(start, datetime(2025, 1, 15, 23, 0, 0))
        self.assertEqual(end, datetime(2025, 1, 16, 0, 0, 0))

    def test_microseconds_are_stripped(self) -> None:
        """Microseconds should be zeroed out in the hour_start."""
        dt = datetime(2025, 1, 15, 14, 30, 45, 123456)
        start, end = _get_slot_boundaries(dt)
        self.assertEqual(start.microsecond, 0)
        self.assertEqual(start.second, 0)
        self.assertEqual(start.minute, 0)
        self.assertEqual(end, datetime(2025, 1, 15, 15, 0, 0))

    def test_seconds_are_stripped(self) -> None:
        """Seconds should be zeroed out in the hour_start."""
        dt = datetime(2025, 1, 15, 14, 30, 59)
        start, _ = _get_slot_boundaries(dt)
        self.assertEqual(start.second, 0)

    def test_minute_59_still_in_same_slot(self) -> None:
        """14:59:59 should still be in the 14:00–15:00 slot."""
        dt = datetime(2025, 1, 15, 14, 59, 59)
        start, end = _get_slot_boundaries(dt)
        self.assertEqual(start, datetime(2025, 1, 15, 14, 0, 0))
        self.assertEqual(end, datetime(2025, 1, 15, 15, 0, 0))

    def test_midnight_boundary(self) -> None:
        """00:00 should produce a slot from 00:00 to 01:00."""
        dt = datetime(2025, 1, 15, 0, 0, 0)
        start, end = _get_slot_boundaries(dt)
        self.assertEqual(start, datetime(2025, 1, 15, 0, 0, 0))
        self.assertEqual(end, datetime(2025, 1, 15, 1, 0, 0))

    def test_slot_duration_is_one_hour(self) -> None:
        """The slot should always span exactly one hour."""
        dt = datetime(2025, 6, 20, 10, 15, 30)
        start, end = _get_slot_boundaries(dt)
        self.assertEqual((end - start).total_seconds(), 3600)


# ===========================================================================
# B. Unit tests for check_slot_capacity()
# ===========================================================================

class CheckSlotCapacityTests(unittest.TestCase):
    """Tests for check_slot_capacity — async capacity checking against DB."""

    def _run(self, coro):
        """Helper to run an async coroutine in sync context."""
        return asyncio.run(coro)

    def _make_mock_db(self, count: int):
        """Create a mock AsyncSession that returns *count* from the query."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = count
        mock_db.execute = AsyncMock(return_value=mock_result)
        return mock_db

    @patch("app.core.slot_capacity.get_effective_settings")
    def test_slot_max_tasks_zero_means_disabled(self, mock_settings) -> None:
        """When slot_max_tasks=0 (disabled), is_full should always be False."""
        mock_settings.return_value = MagicMock(slot_max_tasks=0, slot_max_tasks_enforce=True)
        mock_db = self._make_mock_db(count=100)

        info = self._run(check_slot_capacity(mock_db, datetime(2025, 1, 15, 14, 30)))

        self.assertFalse(info.is_full)
        self.assertEqual(info.max, 0)
        self.assertEqual(info.count, 100)

    @patch("app.core.slot_capacity.get_effective_settings")
    def test_count_below_max_is_not_full(self, mock_settings) -> None:
        """When count < max, is_full should be False."""
        mock_settings.return_value = MagicMock(slot_max_tasks=5, slot_max_tasks_enforce=True)
        mock_db = self._make_mock_db(count=3)

        info = self._run(check_slot_capacity(mock_db, datetime(2025, 1, 15, 14, 30)))

        self.assertFalse(info.is_full)
        self.assertEqual(info.count, 3)
        self.assertEqual(info.max, 5)

    @patch("app.core.slot_capacity.get_effective_settings")
    def test_count_equals_max_is_full(self, mock_settings) -> None:
        """When count == max, is_full should be True."""
        mock_settings.return_value = MagicMock(slot_max_tasks=5, slot_max_tasks_enforce=True)
        mock_db = self._make_mock_db(count=5)

        info = self._run(check_slot_capacity(mock_db, datetime(2025, 1, 15, 14, 30)))

        self.assertTrue(info.is_full)
        self.assertEqual(info.count, 5)
        self.assertEqual(info.max, 5)

    @patch("app.core.slot_capacity.get_effective_settings")
    def test_count_exceeds_max_is_full(self, mock_settings) -> None:
        """When count > max, is_full should be True."""
        mock_settings.return_value = MagicMock(slot_max_tasks=5, slot_max_tasks_enforce=True)
        mock_db = self._make_mock_db(count=8)

        info = self._run(check_slot_capacity(mock_db, datetime(2025, 1, 15, 14, 30)))

        self.assertTrue(info.is_full)
        self.assertEqual(info.count, 8)

    @patch("app.core.slot_capacity.get_effective_settings")
    def test_enforce_flag_passed_through_true(self, mock_settings) -> None:
        """When settings.slot_max_tasks_enforce=True, enforce should be True."""
        mock_settings.return_value = MagicMock(slot_max_tasks=5, slot_max_tasks_enforce=True)
        mock_db = self._make_mock_db(count=0)

        info = self._run(check_slot_capacity(mock_db, datetime(2025, 1, 15, 14, 30)))

        self.assertTrue(info.enforce)

    @patch("app.core.slot_capacity.get_effective_settings")
    def test_enforce_flag_passed_through_false(self, mock_settings) -> None:
        """When settings.slot_max_tasks_enforce=False, enforce should be False."""
        mock_settings.return_value = MagicMock(slot_max_tasks=5, slot_max_tasks_enforce=False)
        mock_db = self._make_mock_db(count=0)

        info = self._run(check_slot_capacity(mock_db, datetime(2025, 1, 15, 14, 30)))

        self.assertFalse(info.enforce)

    @patch("app.core.slot_capacity.get_effective_settings")
    def test_hour_boundaries_in_result(self, mock_settings) -> None:
        """Returned hour_start/hour_end should match _get_slot_boundaries."""
        mock_settings.return_value = MagicMock(slot_max_tasks=5, slot_max_tasks_enforce=True)
        mock_db = self._make_mock_db(count=0)

        dt = datetime(2025, 1, 15, 14, 45, 30)
        info = self._run(check_slot_capacity(mock_db, dt))

        self.assertEqual(info.hour_start, datetime(2025, 1, 15, 14, 0, 0))
        self.assertEqual(info.hour_end, datetime(2025, 1, 15, 15, 0, 0))

    @patch("app.core.slot_capacity.get_effective_settings")
    def test_null_scalar_treated_as_zero(self, mock_settings) -> None:
        """When DB returns None for count, it should be treated as 0."""
        mock_settings.return_value = MagicMock(slot_max_tasks=5, slot_max_tasks_enforce=True)
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        info = self._run(check_slot_capacity(mock_db, datetime(2025, 1, 15, 14, 30)))

        self.assertEqual(info.count, 0)
        self.assertFalse(info.is_full)

    @patch("app.core.slot_capacity.get_effective_settings")
    def test_exclude_task_id_adds_filter(self, mock_settings) -> None:
        """When exclude_task_id is passed, db.execute should still be called (query modified)."""
        mock_settings.return_value = MagicMock(slot_max_tasks=5, slot_max_tasks_enforce=True)
        mock_db = self._make_mock_db(count=4)

        info = self._run(
            check_slot_capacity(mock_db, datetime(2025, 1, 15, 14, 30), exclude_task_id=42)
        )

        # db.execute should have been called exactly once (with the modified query)
        mock_db.execute.assert_called_once()
        self.assertEqual(info.count, 4)

    @patch("app.core.slot_capacity.get_effective_settings")
    def test_without_exclude_task_id(self, mock_settings) -> None:
        """When exclude_task_id is None, query should not include task exclusion."""
        mock_settings.return_value = MagicMock(slot_max_tasks=5, slot_max_tasks_enforce=True)
        mock_db = self._make_mock_db(count=2)

        info = self._run(
            check_slot_capacity(mock_db, datetime(2025, 1, 15, 14, 30), exclude_task_id=None)
        )

        mock_db.execute.assert_called_once()
        self.assertEqual(info.count, 2)


# ===========================================================================
# C. Unit tests for format_slot_rejection_message()
# ===========================================================================

class FormatSlotRejectionMessageTests(unittest.TestCase):
    """Tests for format_slot_rejection_message — user-facing rejection text."""

    def test_contains_date_time_format(self) -> None:
        """Message should contain the start time in YYYY-MM-DD HH:MM format."""
        info = _make_slot_info(count=5, max_tasks=5, is_full=True)
        msg = format_slot_rejection_message(info)
        self.assertIn("2025-01-15 14:00", msg)

    def test_contains_end_time(self) -> None:
        """Message should contain the end time (HH:MM only)."""
        info = _make_slot_info(count=5, max_tasks=5, is_full=True)
        msg = format_slot_rejection_message(info)
        self.assertIn("15:00", msg)

    def test_contains_count_and_max(self) -> None:
        """Message should include the count/max ratio."""
        info = _make_slot_info(count=5, max_tasks=5, is_full=True)
        msg = format_slot_rejection_message(info)
        self.assertIn("5/5 tasks", msg)

    def test_contains_settings_reference(self) -> None:
        """Message should reference the slot_max_tasks setting name."""
        info = _make_slot_info(count=5, max_tasks=5, is_full=True)
        msg = format_slot_rejection_message(info)
        self.assertIn("slot_max_tasks", msg)

    def test_contains_warning_emoji(self) -> None:
        """Message should contain the warning emoji."""
        info = _make_slot_info(count=5, max_tasks=5, is_full=True)
        msg = format_slot_rejection_message(info)
        self.assertIn("⚠️", msg)

    def test_contains_full_capacity_wording(self) -> None:
        """Message should contain 'full capacity' wording."""
        info = _make_slot_info(count=5, max_tasks=5, is_full=True)
        msg = format_slot_rejection_message(info)
        self.assertIn("full capacity", msg)

    def test_contains_rejection_wording(self) -> None:
        """Message should state that task creation was rejected."""
        info = _make_slot_info(count=5, max_tasks=5, is_full=True)
        msg = format_slot_rejection_message(info)
        self.assertIn("rejected", msg)

    def test_different_count_max_values(self) -> None:
        """Message should reflect the actual count/max from info."""
        info = _make_slot_info(
            count=10,
            max_tasks=10,
            is_full=True,
            hour_start=datetime(2025, 6, 20, 9, 0, 0),
            hour_end=datetime(2025, 6, 20, 10, 0, 0),
        )
        msg = format_slot_rejection_message(info)
        self.assertIn("10/10 tasks", msg)
        self.assertIn("2025-06-20 09:00", msg)
        self.assertIn("10:00", msg)


# ===========================================================================
# D. API tests — GET /tasks/slot-capacity
# ===========================================================================

class GetSlotCapacityEndpointTests(unittest.TestCase):
    """Tests for GET /api/tasks/slot-capacity."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    @patch("app.core.slot_capacity.check_slot_capacity", new_callable=AsyncMock)
    def test_valid_request_returns_capacity_info(self, mock_check) -> None:
        """GET /tasks/slot-capacity with valid scheduled_at returns capacity JSON."""
        mock_check.return_value = _make_slot_info(count=3, max_tasks=5, is_full=False, enforce=True)

        mock_db = MagicMock()
        mock_db.execute = AsyncMock()
        client, app = _make_app_client_with_db(mock_db)

        response = client.get("/api/tasks/slot-capacity", params={
            "scheduled_at": "2025-01-15T14:30:00"
        })
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("hour_start", data)
        self.assertIn("hour_end", data)
        self.assertEqual(data["count"], 3)
        self.assertEqual(data["max"], 5)
        self.assertFalse(data["is_full"])
        self.assertTrue(data["enforce"])

    def test_missing_scheduled_at_returns_422(self) -> None:
        """GET /tasks/slot-capacity without scheduled_at should return 422."""
        mock_db = MagicMock()
        client, app = _make_app_client_with_db(mock_db)

        response = client.get("/api/tasks/slot-capacity")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 422)

    @patch("app.core.slot_capacity.check_slot_capacity", new_callable=AsyncMock)
    def test_full_slot_returns_is_full_true(self, mock_check) -> None:
        """GET /tasks/slot-capacity when slot is full should return is_full=True."""
        mock_check.return_value = _make_slot_info(count=5, max_tasks=5, is_full=True, enforce=True)

        mock_db = MagicMock()
        client, app = _make_app_client_with_db(mock_db)

        response = client.get("/api/tasks/slot-capacity", params={
            "scheduled_at": "2025-01-15T14:30:00"
        })
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["is_full"])

    @patch("app.core.slot_capacity.check_slot_capacity", new_callable=AsyncMock)
    def test_enforce_false_returned_correctly(self, mock_check) -> None:
        """GET /tasks/slot-capacity should return enforce=False when not enforced."""
        mock_check.return_value = _make_slot_info(count=5, max_tasks=5, is_full=True, enforce=False)

        mock_db = MagicMock()
        client, app = _make_app_client_with_db(mock_db)

        response = client.get("/api/tasks/slot-capacity", params={
            "scheduled_at": "2025-01-15T14:30:00"
        })
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["enforce"])


# ===========================================================================
# E. API tests — POST /tasks (create_task) slot capacity enforcement
# ===========================================================================

class CreateTaskSlotCapacityTests(unittest.TestCase):
    """Tests for slot capacity enforcement in POST /api/tasks."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def _make_create_payload(self, scheduled_datetime=None):
        """Build a valid task creation payload."""
        payload = {
            "issue_id": 1,
            "user_prompt": "Fix the login bug",
            "priority": 0,
            "provider_id": 1,
        }
        if scheduled_datetime is not None:
            payload["scheduled_datetime"] = scheduled_datetime
        return payload

    @patch("app.core.slot_capacity.check_slot_capacity", new_callable=AsyncMock)
    def test_scheduled_task_full_enforce_returns_409(self, mock_check) -> None:
        """POST /tasks with scheduled_at + full + enforce should return 409 Conflict."""
        mock_check.return_value = _make_slot_info(count=5, max_tasks=5, is_full=True, enforce=True)

        async def fake_refresh(task, attribute_names=None):
            task.id = 99
            if task.status is None:
                task.status = TaskStatus.PENDING
            if task.created_at is None:
                task.created_at = datetime(2024, 1, 1, 12, 0, 0)
            if task.updated_at is None:
                task.updated_at = datetime(2024, 1, 1, 12, 0, 0)

        mock_issue = MagicMock()
        mock_issue.id = 1
        mock_issue.project_id = 1
        mock_issue.description = "Fix the login bug"

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=fake_refresh)
        mock_db.get = AsyncMock(return_value=mock_issue)

        client, app = _make_app_client_with_db(mock_db)

        future_dt = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
        with _mock_task_runtime_dependencies():
            response = client.post("/api/tasks", json=self._make_create_payload(scheduled_datetime=future_dt))
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertEqual(data["detail"]["code"], "SLOT_FULL")
        self.assertEqual(data["detail"]["count"], 5)
        self.assertEqual(data["detail"]["max"], 5)

    @patch("app.core.slot_capacity.check_slot_capacity", new_callable=AsyncMock)
    def test_scheduled_task_full_no_enforce_returns_200_with_warning(self, mock_check) -> None:
        """POST /tasks with scheduled_at + full + !enforce → 200 with slot_warning."""
        mock_check.return_value = _make_slot_info(count=5, max_tasks=5, is_full=True, enforce=False)

        async def fake_refresh(task, attribute_names=None):
            task.id = 99
            if task.status is None:
                task.status = TaskStatus.PENDING
            if task.created_at is None:
                task.created_at = datetime(2024, 1, 1, 12, 0, 0)
            if task.updated_at is None:
                task.updated_at = datetime(2024, 1, 1, 12, 0, 0)

        mock_issue = MagicMock()
        mock_issue.id = 1
        mock_issue.project_id = 1
        mock_issue.description = "Fix the login bug"

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=fake_refresh)
        mock_db.get = AsyncMock(return_value=mock_issue)

        client, app = _make_app_client_with_db(mock_db)

        future_dt = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
        with _mock_task_runtime_dependencies():
            response = client.post("/api/tasks", json=self._make_create_payload(scheduled_datetime=future_dt))
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("slot_warning", data)
        self.assertEqual(data["slot_warning"]["code"], "SLOT_FULL")

    @patch("app.core.slot_capacity.check_slot_capacity", new_callable=AsyncMock)
    def test_scheduled_task_not_full_returns_200_without_warning(self, mock_check) -> None:
        """POST /tasks with scheduled_at + not full → 200 without slot_warning."""
        mock_check.return_value = _make_slot_info(count=2, max_tasks=5, is_full=False, enforce=True)

        async def fake_refresh(task, attribute_names=None):
            task.id = 99
            if task.status is None:
                task.status = TaskStatus.PENDING
            if task.created_at is None:
                task.created_at = datetime(2024, 1, 1, 12, 0, 0)
            if task.updated_at is None:
                task.updated_at = datetime(2024, 1, 1, 12, 0, 0)

        mock_issue = MagicMock()
        mock_issue.id = 1
        mock_issue.project_id = 1
        mock_issue.description = "Fix the login bug"

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=fake_refresh)
        mock_db.get = AsyncMock(return_value=mock_issue)

        client, app = _make_app_client_with_db(mock_db)

        future_dt = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
        with _mock_task_runtime_dependencies():
            response = client.post("/api/tasks", json=self._make_create_payload(scheduled_datetime=future_dt))
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotIn("slot_warning", data)

    def test_unscheduled_task_no_capacity_check(self) -> None:
        """POST /tasks without scheduled_datetime should not check slot capacity."""
        async def fake_refresh(task, attribute_names=None):
            task.id = 99
            if task.status is None:
                task.status = TaskStatus.PENDING
            if task.created_at is None:
                task.created_at = datetime(2024, 1, 1, 12, 0, 0)
            if task.updated_at is None:
                task.updated_at = datetime(2024, 1, 1, 12, 0, 0)

        mock_issue = MagicMock()
        mock_issue.id = 1
        mock_issue.project_id = 1
        mock_issue.description = "Fix the login bug"

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=fake_refresh)
        mock_db.get = AsyncMock(return_value=mock_issue)

        client, app = _make_app_client_with_db(mock_db)

        with patch("app.core.slot_capacity.check_slot_capacity", new_callable=AsyncMock) as mock_check:
            with _mock_task_runtime_dependencies():
                response = client.post("/api/tasks", json=self._make_create_payload())
            mock_check.assert_not_called()

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotIn("slot_warning", data)


# ===========================================================================
# F. API tests — POST /tasks/{id}/retry slot capacity enforcement
# ===========================================================================

class RetryTaskSlotCapacityTests(unittest.TestCase):
    """Tests for slot capacity enforcement in POST /api/tasks/{id}/retry."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    @patch("app.core.slot_capacity.check_slot_capacity", new_callable=AsyncMock)
    def test_scheduled_retry_full_enforce_returns_409(self, mock_check) -> None:
        """POST /tasks/{id}/retry with scheduled_at + full + enforce → 409 Conflict."""
        mock_check.return_value = _make_slot_info(count=5, max_tasks=5, is_full=True, enforce=True)

        task = _make_serializable_task(task_status=TaskStatus.FAILED, task_id=80)
        task.project_id = 1

        # First execute returns the task; second returns None (no existing retry)
        mock_result_task = MagicMock()
        mock_result_task.scalar_one_or_none.return_value = task
        mock_result_no_retry = MagicMock()
        mock_result_no_retry.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_result_task, mock_result_no_retry])
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        client, app = _make_app_client_with_db(mock_db)

        future_dt = (datetime.now(UTC) + timedelta(hours=2)).isoformat()

        with patch("app.core.task_helpers._require_task_operator", return_value=None):
            response = client.post("/api/tasks/80/retry", json={
                "scheduled_datetime": future_dt
            })

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertEqual(data["detail"]["code"], "SLOT_FULL")

    @patch("app.core.slot_capacity.check_slot_capacity", new_callable=AsyncMock)
    def test_scheduled_retry_not_full_returns_success(self, mock_check) -> None:
        """POST /tasks/{id}/retry with scheduled_at + not full → 200 success."""
        from app.models import Task as TaskModel
        mock_check.return_value = _make_slot_info(count=2, max_tasks=5, is_full=False, enforce=True)

        task = _make_serializable_task(task_status=TaskStatus.FAILED, task_id=81)
        task.project_id = 1

        # First execute returns the task; second returns None (no existing retry);
        # third fetches the Issue for serialization
        mock_result_task = MagicMock()
        mock_result_task.scalar_one_or_none.return_value = task
        mock_result_no_retry = MagicMock()
        mock_result_no_retry.scalar_one_or_none.return_value = None
        mock_issue = MagicMock()
        mock_issue.id = 1
        mock_issue.project_id = 1
        mock_issue.description = "Fix the login bug"
        mock_result_issue = MagicMock()
        mock_result_issue.scalar_one_or_none.return_value = mock_issue

        now = datetime(2024, 1, 1, 12, 0, 0)

        async def fake_refresh(obj, attribute_names=None):
            if isinstance(obj, TaskModel):
                obj.id = 200
                obj.status = TaskStatus.PENDING
                obj.created_at = now
                obj.updated_at = now

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_result_task, mock_result_no_retry, mock_result_issue])
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=fake_refresh)
        mock_db.get = AsyncMock(return_value=MagicMock(is_disabled=False))

        client, app = _make_app_client_with_db(mock_db)

        future_dt = (datetime.now(UTC) + timedelta(hours=2)).isoformat()

        with patch("app.api.tasks.notify_task_retried", new=AsyncMock()):
            with patch("app.core.task_helpers._require_task_operator", return_value=None):
                with _mock_task_runtime_dependencies():
                    response = client.post("/api/tasks/81/retry", json={
                        "scheduled_datetime": future_dt
                    })

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)

    def test_retry_without_schedule_no_capacity_check(self) -> None:
        """POST /tasks/{id}/retry without scheduled_datetime should not check capacity."""
        from app.models import Task as TaskModel
        task = _make_serializable_task(task_status=TaskStatus.FAILED, task_id=82)
        task.project_id = 1

        # First execute returns the task; second returns None (no existing retry);
        # third fetches the Issue for serialization
        mock_result_task = MagicMock()
        mock_result_task.scalar_one_or_none.return_value = task
        mock_result_no_retry = MagicMock()
        mock_result_no_retry.scalar_one_or_none.return_value = None
        mock_issue = MagicMock()
        mock_issue.id = 1
        mock_issue.project_id = 1
        mock_issue.description = "Fix the login bug"
        mock_result_issue = MagicMock()
        mock_result_issue.scalar_one_or_none.return_value = mock_issue

        now = datetime(2024, 1, 1, 12, 0, 0)

        async def fake_refresh(obj, attribute_names=None):
            if isinstance(obj, TaskModel):
                obj.id = 201
                obj.status = TaskStatus.PENDING
                obj.created_at = now
                obj.updated_at = now

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_result_task, mock_result_no_retry, mock_result_issue])
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=fake_refresh)
        mock_db.get = AsyncMock(return_value=MagicMock(is_disabled=False))

        client, app = _make_app_client_with_db(mock_db)

        with patch("app.core.slot_capacity.check_slot_capacity", new_callable=AsyncMock) as mock_check:
            with patch("app.api.tasks.notify_task_retried", new=AsyncMock()):
                with patch("app.core.task_helpers._require_task_operator", return_value=None):
                    with _mock_task_runtime_dependencies():
                        response = client.post("/api/tasks/82/retry")
            mock_check.assert_not_called()

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)

    @patch("app.core.slot_capacity.check_slot_capacity", new_callable=AsyncMock)
    def test_retry_uses_exclude_task_id(self, mock_check) -> None:
        """POST /tasks/{id}/retry should pass exclude_task_id to check_slot_capacity."""
        mock_check.return_value = _make_slot_info(count=2, max_tasks=5, is_full=False, enforce=True)

        task = _make_serializable_task(task_status=TaskStatus.FAILED, task_id=83)
        task.project_id = 1

        # First execute returns the task; second returns None (no existing retry)
        mock_result_task = MagicMock()
        mock_result_task.scalar_one_or_none.return_value = task
        mock_result_no_retry = MagicMock()
        mock_result_no_retry.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_result_task, mock_result_no_retry])
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        client, app = _make_app_client_with_db(mock_db)

        future_dt = (datetime.now(UTC) + timedelta(hours=2)).isoformat()

        with patch("app.api.tasks.notify_task_retried", new=AsyncMock()):
            with patch("app.core.task_helpers._require_task_operator", return_value=None):
                client.post("/api/tasks/83/retry", json={
                    "scheduled_datetime": future_dt
                })

        app.dependency_overrides.clear()

        # Verify check_slot_capacity was called with exclude_task_id=83
        mock_check.assert_called_once()
        call_kwargs = mock_check.call_args
        self.assertEqual(call_kwargs.kwargs.get("exclude_task_id"), 83)


# ===========================================================================
# G. API tests — PATCH /tasks/{id}/schedule (reschedule) slot enforcement
# ===========================================================================

class RescheduleTaskSlotCapacityTests(unittest.TestCase):
    """Tests for slot capacity enforcement in PATCH /api/tasks/{id}/schedule."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    @patch("app.core.slot_capacity.check_slot_capacity", new_callable=AsyncMock)
    def test_reschedule_full_enforce_returns_409(self, mock_check) -> None:
        """PATCH /tasks/{id}/schedule + full + enforce → 409 Conflict."""
        mock_check.return_value = _make_slot_info(count=5, max_tasks=5, is_full=True, enforce=True)

        task = _make_serializable_task(task_status=TaskStatus.PENDING, task_id=90)
        task.project_id = 1
        task.scheduled_at = datetime(2025, 1, 15, 14, 0, 0)  # Already scheduled

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        client, app = _make_app_client_with_db(mock_db)

        future_dt = (datetime.now(UTC) + timedelta(hours=3)).isoformat()

        with patch("app.core.task_helpers._require_task_operator", return_value=None):
            response = client.patch("/api/tasks/90/schedule", json={
                "scheduled_datetime": future_dt
            })

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertEqual(data["detail"]["code"], "SLOT_FULL")

    @patch("app.core.slot_capacity.check_slot_capacity", new_callable=AsyncMock)
    def test_reschedule_not_full_returns_success(self, mock_check) -> None:
        """PATCH /tasks/{id}/schedule + not full → 200 success."""
        mock_check.return_value = _make_slot_info(count=2, max_tasks=5, is_full=False, enforce=True)

        task = _make_serializable_task(task_status=TaskStatus.PENDING, task_id=91)
        task.project_id = 1
        task.scheduled_at = datetime(2025, 1, 15, 14, 0, 0)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        client, app = _make_app_client_with_db(mock_db)

        future_dt = (datetime.now(UTC) + timedelta(hours=3)).isoformat()

        with patch("app.api.task_action_routes.notify_task_rescheduled", new=AsyncMock()):
            with patch("app.core.task_helpers._require_task_operator", return_value=None):
                with patch("app.api.tasks.get_project_metadata", new_callable=AsyncMock, return_value={}):
                    response = client.patch("/api/tasks/91/schedule", json={
                        "scheduled_datetime": future_dt
                    })

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)

    @patch("app.core.slot_capacity.check_slot_capacity", new_callable=AsyncMock)
    def test_reschedule_uses_exclude_task_id(self, mock_check) -> None:
        """PATCH /tasks/{id}/schedule should pass exclude_task_id to check_slot_capacity."""
        mock_check.return_value = _make_slot_info(count=2, max_tasks=5, is_full=False, enforce=True)

        task = _make_serializable_task(task_status=TaskStatus.PENDING, task_id=92)
        task.project_id = 1
        task.scheduled_at = datetime(2025, 1, 15, 14, 0, 0)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        client, app = _make_app_client_with_db(mock_db)

        future_dt = (datetime.now(UTC) + timedelta(hours=3)).isoformat()

        with patch("app.api.task_action_routes.notify_task_rescheduled", new=AsyncMock()):
            with patch("app.core.task_helpers._require_task_operator", return_value=None):
                with patch("app.api.tasks.get_project_metadata", new_callable=AsyncMock, return_value={}):
                    client.patch("/api/tasks/92/schedule", json={
                        "scheduled_datetime": future_dt
                    })

        app.dependency_overrides.clear()

        # Verify check_slot_capacity was called with exclude_task_id=92
        mock_check.assert_called_once()
        call_kwargs = mock_check.call_args
        self.assertEqual(call_kwargs.kwargs.get("exclude_task_id"), 92)

    @patch("app.core.slot_capacity.check_slot_capacity", new_callable=AsyncMock)
    def test_reschedule_full_no_enforce_returns_success(self, mock_check) -> None:
        """PATCH /tasks/{id}/schedule + full + !enforce → 200 (reschedule proceeds)."""
        mock_check.return_value = _make_slot_info(count=5, max_tasks=5, is_full=True, enforce=False)

        task = _make_serializable_task(task_status=TaskStatus.PENDING, task_id=93)
        task.project_id = 1
        task.scheduled_at = datetime(2025, 1, 15, 14, 0, 0)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        client, app = _make_app_client_with_db(mock_db)

        future_dt = (datetime.now(UTC) + timedelta(hours=3)).isoformat()

        with patch("app.api.task_action_routes.notify_task_rescheduled", new=AsyncMock()):
            with patch("app.core.task_helpers._require_task_operator", return_value=None):
                with patch("app.api.tasks.get_project_metadata", new_callable=AsyncMock, return_value={}):
                    response = client.patch("/api/tasks/93/schedule", json={
                        "scheduled_datetime": future_dt
                    })

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)


# ===========================================================================
# H. SlotCapacityInfo dataclass tests
# ===========================================================================

class SlotCapacityInfoTests(unittest.TestCase):
    """Tests for the SlotCapacityInfo dataclass attributes."""

    def test_dataclass_creation(self) -> None:
        """SlotCapacityInfo should store all fields correctly."""
        info = SlotCapacityInfo(
            hour_start=datetime(2025, 1, 15, 14, 0, 0),
            hour_end=datetime(2025, 1, 15, 15, 0, 0),
            count=3,
            max=5,
            is_full=False,
            enforce=True,
        )
        self.assertEqual(info.hour_start, datetime(2025, 1, 15, 14, 0, 0))
        self.assertEqual(info.hour_end, datetime(2025, 1, 15, 15, 0, 0))
        self.assertEqual(info.count, 3)
        self.assertEqual(info.max, 5)
        self.assertFalse(info.is_full)
        self.assertTrue(info.enforce)

    def test_dataclass_equality(self) -> None:
        """Two SlotCapacityInfo with same values should be equal."""
        info1 = _make_slot_info(count=3, max_tasks=5, is_full=False)
        info2 = _make_slot_info(count=3, max_tasks=5, is_full=False)
        self.assertEqual(info1, info2)


if __name__ == "__main__":
    unittest.main()
