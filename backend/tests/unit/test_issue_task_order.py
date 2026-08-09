#!/usr/bin/env python3
"""Unit tests for the Issue input-stream ordering domain service.

Covers ``app.core.issue_task_order``: batch queue-context computation, schedule
window derivation, locked schedule-time validation, active-successor blast
radius, tail-lineage projection, and fail-closed integrity checks. Also covers
the API surface the ordering model introduced: the static ``GET
/tasks/schedule-constraints`` route, execute-now non-head semantics, and the
structured 409 conflict envelope.
"""

import os
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient

from app.models import IssueExecutionLock, TaskStatus


def _make_task(task_id, *, issue_sequence, status, scheduled_at=None, issue_id=1) -> MagicMock:
    task = MagicMock()
    task.id = task_id
    task.issue_id = issue_id
    task.issue_sequence = issue_sequence
    task.status = status
    task.scheduled_at = scheduled_at
    return task


def _make_scalars_all_result(rows):
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _make_rows_all_result(rows):
    result = MagicMock()
    result.all.return_value = rows
    return result


def _make_scalar_one_or_none_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_scalar_result(value):
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _sn_task(task_id, *, issue_sequence, status, session_mode="continue", full_projection=False):
    return SimpleNamespace(
        id=task_id,
        issue_id=1,
        issue_sequence=issue_sequence,
        status=status,
        session_mode=session_mode,
        created_at=datetime(2026, 1, 1, 12, 0, 0),
        projected_harness_key="claude" if full_projection else None,
        projected_session_namespace="ns" if full_projection else None,
        projected_lineage_generation=0 if full_projection else None,
        projected_reset_task_id=None,
        lineage_projection_reason="initial" if full_projection else None,
        input_lineage_reason=None,
    )


# ---------------------------------------------------------------------------
# compute_queue_context
# ---------------------------------------------------------------------------


class ComputeQueueContextTests(unittest.IsolatedAsyncioTestCase):
    """Batch queue-context computation for an Issue's Tasks."""

    async def _compute(self, tasks, lock=None):
        from app.core.issue_task_order import compute_queue_context

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _make_scalars_all_result(tasks),
                _make_scalar_one_or_none_result(lock),
            ]
        )
        return await compute_queue_context(db, issue_id=1)

    async def test_head_ready_task_gets_queue_position_one(self):
        ctx = await self._compute(
            [_make_task(1, issue_sequence=1, status=TaskStatus.QUEUED)]
        )
        self.assertEqual(ctx[1]["queue_position"], 1)
        self.assertIsNone(ctx[1]["waiting_reason"])
        self.assertIsNone(ctx[1]["blocked_by_task_id"])

    async def test_non_head_task_is_blocked_by_head(self):
        head = _make_task(1, issue_sequence=1, status=TaskStatus.RUNNING)
        tail = _make_task(2, issue_sequence=2, status=TaskStatus.PENDING)
        ctx = await self._compute([head, tail])
        self.assertEqual(ctx[2]["queue_position"], 2)
        self.assertEqual(ctx[2]["blocked_by_task_id"], 1)
        self.assertEqual(ctx[2]["waiting_reason"], "predecessor")

    async def test_scheduled_head_reports_waiting(self):
        future = datetime(2099, 1, 1, 12, 0, 0)
        ctx = await self._compute(
            [_make_task(1, issue_sequence=1, status=TaskStatus.QUEUED, scheduled_at=future)]
        )
        self.assertEqual(ctx[1]["queue_position"], 1)
        self.assertEqual(ctx[1]["waiting_reason"], "scheduled")

    async def test_terminal_task_has_no_queue_position(self):
        ctx = await self._compute(
            [_make_task(1, issue_sequence=1, status=TaskStatus.COMPLETED)]
        )
        self.assertIsNone(ctx[1]["queue_position"])
        self.assertIsNone(ctx[1]["waiting_reason"])

    async def test_active_task_with_null_sequence_requires_repair(self):
        ctx = await self._compute(
            [_make_task(1, issue_sequence=None, status=TaskStatus.PENDING)]
        )
        self.assertEqual(ctx[1]["waiting_reason"], "sequence_repair_required")
        self.assertIsNone(ctx[1]["queue_position"])

    async def test_head_waits_for_terminal_owner_workspace_cleanup(self):
        terminal = _make_task(1, issue_sequence=1, status=TaskStatus.COMPLETED)
        head = _make_task(2, issue_sequence=2, status=TaskStatus.PENDING)
        lock = IssueExecutionLock(
            issue_id=1,
            task_id=1,
            acquired_at=datetime(2026, 8, 8, 12, 0, 0),
        )
        ctx = await self._compute([terminal, head], lock=lock)
        self.assertEqual(ctx[2]["waiting_reason"], "workspace_cleanup")
        self.assertEqual(ctx[2]["lock_owner_task_id"], 1)
        self.assertEqual(ctx[2]["waiting_since"], "2026-08-08T12:00:00")
        self.assertIsNone(ctx[1]["queue_position"])


# ---------------------------------------------------------------------------
# compute_schedule_window
# ---------------------------------------------------------------------------


class ComputeScheduleWindowTests(unittest.IsolatedAsyncioTestCase):
    """Schedule-window derivation for append and reschedule modes."""

    async def _window(self, tasks, *, exclude_task_id=None):
        from app.core.issue_task_order import compute_schedule_window

        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_make_scalars_all_result(tasks)])
        return await compute_schedule_window(db, issue_id=1, exclude_task_id=exclude_task_id)

    async def test_append_mode_floor_is_latest_active_scheduled_at(self):
        t1 = _make_task(1, issue_sequence=1, status=TaskStatus.PENDING, scheduled_at=datetime(2026, 8, 8, 10, 0, 0))
        t2 = _make_task(2, issue_sequence=2, status=TaskStatus.PENDING, scheduled_at=datetime(2026, 8, 8, 11, 0, 0))
        win = await self._window([t1, t2])
        self.assertTrue(win["has_valid_window"])
        self.assertEqual(win["min_scheduled_at"], "2026-08-08T11:00:00")
        self.assertEqual(win["min_source_task_id"], 2)
        self.assertIsNone(win["max_scheduled_at"])

    async def test_reschedule_floor_from_earlier_ceiling_from_later(self):
        t1 = _make_task(1, issue_sequence=1, status=TaskStatus.PENDING, scheduled_at=datetime(2026, 8, 8, 10, 0, 0))
        t2 = _make_task(2, issue_sequence=2, status=TaskStatus.PENDING, scheduled_at=datetime(2026, 8, 8, 12, 0, 0))
        t3 = _make_task(3, issue_sequence=3, status=TaskStatus.PENDING, scheduled_at=datetime(2026, 8, 8, 14, 0, 0))
        win = await self._window([t1, t2, t3], exclude_task_id=2)
        self.assertEqual(win["min_scheduled_at"], "2026-08-08T10:00:00")
        self.assertEqual(win["min_source_task_id"], 1)
        self.assertEqual(win["max_scheduled_at"], "2026-08-08T14:00:00")
        self.assertEqual(win["max_source_task_id"], 3)
        self.assertTrue(win["has_valid_window"])

    async def test_empty_queue_has_valid_window_with_no_constraints(self):
        win = await self._window([])
        self.assertTrue(win["has_valid_window"])
        self.assertIsNone(win["min_scheduled_at"])
        self.assertIsNone(win["max_scheduled_at"])

    async def test_floor_after_ceiling_marks_window_invalid(self):
        t1 = _make_task(1, issue_sequence=1, status=TaskStatus.PENDING, scheduled_at=datetime(2026, 8, 8, 14, 0, 0))
        t2 = _make_task(2, issue_sequence=2, status=TaskStatus.PENDING, scheduled_at=datetime(2026, 8, 8, 12, 0, 0))
        t3 = _make_task(3, issue_sequence=3, status=TaskStatus.PENDING, scheduled_at=datetime(2026, 8, 8, 10, 0, 0))
        win = await self._window([t1, t2, t3], exclude_task_id=2)
        self.assertFalse(win["has_valid_window"])


# ---------------------------------------------------------------------------
# validate_schedule_time_locked
# ---------------------------------------------------------------------------


class ValidateScheduleTimeLockedTests(unittest.IsolatedAsyncioTestCase):
    """Locked schedule-time validation raises structured ScheduleWindowConflict."""

    def _window(self, *, has_valid_window=True, min_time=None, max_time=None):
        return {
            "has_valid_window": has_valid_window,
            "min_scheduled_at": min_time,
            "min_source_task_id": 1,
            "max_scheduled_at": max_time,
            "max_source_task_id": 3,
        }

    async def test_accepts_time_inside_window(self):
        from app.core.issue_task_order import validate_schedule_time_locked

        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_make_scalars_all_result([])])
        window = self._window(min_time="2026-08-08T10:00:00", max_time="2026-08-08T20:00:00")
        with patch(
            "app.core.issue_task_order.compute_schedule_window",
            new=AsyncMock(return_value=window),
        ):
            result = await validate_schedule_time_locked(
                db, issue_id=1, scheduled_at=datetime(2026, 8, 8, 12, 0, 0)
            )
        self.assertEqual(result, window)

    async def test_time_below_floor_raises_structured_conflict(self):
        from app.core.issue_task_order import ScheduleWindowConflict, validate_schedule_time_locked

        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_make_scalars_all_result([])])
        window = self._window(min_time="2026-08-08T10:00:00")
        with patch(
            "app.core.issue_task_order.compute_schedule_window",
            new=AsyncMock(return_value=window),
        ):
            with self.assertRaises(ScheduleWindowConflict) as ctx:
                await validate_schedule_time_locked(
                    db, issue_id=1, scheduled_at=datetime(2026, 8, 8, 9, 0, 0)
                )
        self.assertEqual(ctx.exception.detail["code"], "issue_schedule_order_conflict")
        self.assertIn("floor", ctx.exception.detail["message"])

    async def test_time_after_ceiling_raises_structured_conflict(self):
        from app.core.issue_task_order import ScheduleWindowConflict, validate_schedule_time_locked

        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_make_scalars_all_result([])])
        window = self._window(min_time="2026-08-08T10:00:00", max_time="2026-08-08T12:00:00")
        with patch(
            "app.core.issue_task_order.compute_schedule_window",
            new=AsyncMock(return_value=window),
        ):
            with self.assertRaises(ScheduleWindowConflict) as ctx:
                await validate_schedule_time_locked(
                    db, issue_id=1, scheduled_at=datetime(2026, 8, 8, 14, 0, 0)
                )
        self.assertIn("ceiling", ctx.exception.detail["message"])

    async def test_no_valid_window_raises_conflict(self):
        from app.core.issue_task_order import ScheduleWindowConflict, validate_schedule_time_locked

        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_make_scalars_all_result([])])
        window = self._window(has_valid_window=False, min_time="2026-08-08T14:00:00", max_time="2026-08-08T10:00:00")
        with patch(
            "app.core.issue_task_order.compute_schedule_window",
            new=AsyncMock(return_value=window),
        ):
            with self.assertRaises(ScheduleWindowConflict) as ctx:
                await validate_schedule_time_locked(
                    db, issue_id=1, scheduled_at=datetime(2026, 8, 8, 12, 0, 0)
                )
        self.assertFalse(ctx.exception.detail["has_valid_window"])
        self.assertIn("No valid schedule window", ctx.exception.detail["message"])


# ---------------------------------------------------------------------------
# count_active_successors
# ---------------------------------------------------------------------------


class CountActiveSuccessorsTests(unittest.IsolatedAsyncioTestCase):
    async def test_counts_active_tasks_after_given_sequence(self):
        from app.core.issue_task_order import count_active_successors

        task = _make_task(2, issue_sequence=2, status=TaskStatus.PENDING)
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _make_scalar_one_or_none_result(task),
                _make_scalar_result(3),
            ]
        )
        count = await count_active_successors(db, issue_id=1, task_id=2)
        self.assertEqual(count, 3)

    async def test_missing_task_returns_zero_without_count_query(self):
        from app.core.issue_task_order import count_active_successors

        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_make_scalar_one_or_none_result(None)])
        count = await count_active_successors(db, issue_id=1, task_id=2)
        self.assertEqual(count, 0)
        db.execute.assert_awaited_once()

    async def test_task_without_sequence_returns_zero(self):
        from app.core.issue_task_order import count_active_successors

        task = _make_task(2, issue_sequence=None, status=TaskStatus.PENDING)
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_make_scalar_one_or_none_result(task)])
        count = await count_active_successors(db, issue_id=1, task_id=2)
        self.assertEqual(count, 0)
        db.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# project_tail_lineage
# ---------------------------------------------------------------------------


class ProjectTailLineageTests(unittest.TestCase):
    def setUp(self):
        self.issue_id = 5

    def test_initial_continue_starts_generation_zero(self):
        from app.core.issue_task_order import project_tail_lineage

        result = project_tail_lineage(
            None,
            issue_id=self.issue_id,
            harness_key="claude",
            session_namespace="ns-1",
            session_mode="continue",
        )
        self.assertEqual(result["generation"], 0)
        self.assertIsNone(result["reset_task_id"])
        self.assertEqual(result["reason"], "initial")

    def test_initial_fresh_starts_generation_one(self):
        from app.core.issue_task_order import project_tail_lineage

        result = project_tail_lineage(
            None,
            issue_id=self.issue_id,
            harness_key="claude",
            session_namespace="ns-1",
            session_mode="fresh",
        )
        self.assertEqual(result["generation"], 1)
        self.assertIsNone(result["reset_task_id"])
        self.assertEqual(result["reason"], "initial")

    def test_fresh_increments_generation_and_resets(self):
        from app.core.issue_task_order import project_tail_lineage

        tail = {"harness_key": "claude", "session_namespace": "ns-1", "generation": 1, "reset_task_id": 7}
        result = project_tail_lineage(
            tail,
            issue_id=self.issue_id,
            harness_key="claude",
            session_namespace="ns-2",
            session_mode="fresh",
        )
        self.assertEqual(result["generation"], 2)
        self.assertIsNone(result["reset_task_id"])
        self.assertEqual(result["reason"], "fresh")

    def test_matching_continue_inherits_generation_and_reset(self):
        from app.core.issue_task_order import project_tail_lineage

        tail = {"harness_key": "claude", "session_namespace": "ns-1", "generation": 1, "reset_task_id": 7}
        result = project_tail_lineage(
            tail,
            issue_id=self.issue_id,
            harness_key="claude",
            session_namespace="ns-1",
            session_mode="continue",
        )
        self.assertEqual(result["generation"], 1)
        self.assertEqual(result["reset_task_id"], 7)
        self.assertEqual(result["reason"], "inherited")

    def test_mismatched_continue_raises_lineage_conflict(self):
        from app.core.issue_task_order import LineageConflict, project_tail_lineage

        tail = {"harness_key": "claude", "session_namespace": "ns-1", "generation": 1, "reset_task_id": 7}
        with self.assertRaises(LineageConflict) as ctx:
            project_tail_lineage(
                tail,
                issue_id=self.issue_id,
                harness_key="codex",
                session_namespace="ns-1",
                session_mode="continue",
            )
        self.assertEqual(ctx.exception.detail["code"], "issue_lineage_conflict")
        self.assertEqual(ctx.exception.detail["issue_id"], 5)


# ---------------------------------------------------------------------------
# ensure_issue_order_integrity_locked
# ---------------------------------------------------------------------------


class EnsureIssueOrderIntegrityLockedTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_issue_returns_clean_report(self):
        from app.core.issue_task_order import ensure_issue_order_integrity_locked

        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_make_scalars_all_result([])])
        report = await ensure_issue_order_integrity_locked(db, issue_id=1, repair_nulls=True)
        self.assertEqual(report["repaired_sequences"], 0)
        self.assertEqual(report["max_sequence"], 0)
        self.assertIsNone(report["tail_projection"])

    async def test_backfills_null_sequences_when_repair_enabled(self):
        from app.core.issue_task_order import ensure_issue_order_integrity_locked

        t1 = _sn_task(1, issue_sequence=None, status=TaskStatus.COMPLETED)
        t2 = _sn_task(2, issue_sequence=None, status=TaskStatus.COMPLETED)
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _make_scalars_all_result([t1, t2]),
                _make_rows_all_result([]),
            ]
        )
        report = await ensure_issue_order_integrity_locked(db, issue_id=1, repair_nulls=True)
        self.assertEqual(report["repaired_sequences"], 2)
        self.assertEqual(t1.issue_sequence, 1)
        self.assertEqual(t2.issue_sequence, 2)
        self.assertEqual(report["max_sequence"], 2)
        self.assertIsNotNone(report["tail_projection"])

    async def test_sequence_mismatch_fails_closed(self):
        from app.core.issue_task_order import (
            IssueOrderIntegrityError,
            ensure_issue_order_integrity_locked,
        )

        t1 = _sn_task(1, issue_sequence=5, status=TaskStatus.COMPLETED, full_projection=True)
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_make_scalars_all_result([t1])])
        with self.assertRaises(IssueOrderIntegrityError) as ctx:
            await ensure_issue_order_integrity_locked(db, issue_id=1, repair_nulls=False)
        self.assertEqual(ctx.exception.detail["code"], "issue_sequence_repair_required")
        self.assertEqual(ctx.exception.detail["reason"], "sequence_mismatch")

    async def test_active_null_sequence_blocks_without_repair(self):
        from app.core.issue_task_order import (
            IssueOrderIntegrityError,
            ensure_issue_order_integrity_locked,
        )

        t1 = _sn_task(1, issue_sequence=None, status=TaskStatus.PENDING)
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_make_scalars_all_result([t1])])
        with self.assertRaises(IssueOrderIntegrityError) as ctx:
            await ensure_issue_order_integrity_locked(db, issue_id=1, repair_nulls=False)
        self.assertEqual(ctx.exception.detail["reason"], "active_null_sequence")

    async def test_full_projection_issue_requires_no_repair(self):
        from app.core.issue_task_order import ensure_issue_order_integrity_locked

        t1 = _sn_task(1, issue_sequence=1, status=TaskStatus.QUEUED, full_projection=True)
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _make_scalars_all_result([t1]),
                _make_rows_all_result([]),
            ]
        )
        report = await ensure_issue_order_integrity_locked(db, issue_id=1, repair_nulls=False)
        self.assertEqual(report["repaired_sequences"], 0)
        self.assertEqual(report["max_sequence"], 1)
        self.assertEqual(report["tail_projection"]["harness_key"], "claude")


# ---------------------------------------------------------------------------
# API: GET /tasks/schedule-constraints
# ---------------------------------------------------------------------------


def _make_app_client_with_db(mock_db):
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
    return TestClient(app, raise_server_exceptions=False), app


class ScheduleConstraintsAPITests(unittest.TestCase):
    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    def test_route_resolves_for_task_id(self):
        task = _make_task(7, issue_sequence=2, status=TaskStatus.QUEUED)
        task.project_id = 1
        earlier = _make_task(
            1,
            issue_sequence=1,
            status=TaskStatus.PENDING,
            scheduled_at=datetime(2026, 8, 8, 10, 0, 0),
        )
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                _make_scalar_one_or_none_result(task),
                _make_scalars_all_result([earlier]),
            ]
        )
        client, app = _make_app_client_with_db(mock_db)
        with patch("app.core.task_helpers._require_task_operator", return_value=None):
            response = client.get("/api/tasks/schedule-constraints?task_id=7")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["has_valid_window"])
        self.assertEqual(data["min_source_task_id"], 1)
        self.assertEqual(data["min_scheduled_at"], "2026-08-08T10:00:00")

    def test_route_resolves_for_issue_id(self):
        issue = MagicMock()
        issue.id = 1
        issue.project_id = 1
        earlier = _make_task(
            1,
            issue_sequence=1,
            status=TaskStatus.PENDING,
            scheduled_at=datetime(2026, 8, 8, 10, 0, 0),
        )
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=issue)
        mock_db.execute = AsyncMock(side_effect=[_make_scalars_all_result([earlier])])
        client, app = _make_app_client_with_db(mock_db)
        response = client.get("/api/tasks/schedule-constraints?issue_id=1")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["has_valid_window"])
        self.assertEqual(data["min_source_task_id"], 1)

    def test_route_requires_a_parameter(self):
        mock_db = MagicMock()
        client, app = _make_app_client_with_db(mock_db)
        response = client.get("/api/tasks/schedule-constraints")
        self.assertEqual(response.status_code, 400)

    def test_route_returns_404_when_issue_missing(self):
        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=None)
        client, app = _make_app_client_with_db(mock_db)
        response = client.get("/api/tasks/schedule-constraints?issue_id=999")
        self.assertEqual(response.status_code, 404)


class ExecuteNowAPITests(unittest.TestCase):
    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    def test_non_head_execute_reports_predecessor_block(self):
        task = _make_task(9, issue_sequence=2, status=TaskStatus.PENDING)
        task.project_id = 1
        head = _make_task(1, issue_sequence=1, status=TaskStatus.RUNNING)
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                _make_scalar_one_or_none_result(task),
                _make_scalars_all_result([head, task]),
                _make_scalar_one_or_none_result(None),
            ]
        )
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        client, app = _make_app_client_with_db(mock_db)
        with patch("app.api.task_action_routes.notify_task_execute_now", new=AsyncMock()):
            with patch("app.core.task_helpers._require_task_operator", return_value=None):
                response = client.post("/api/tasks/9/execute")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["message"], "Task will run after its predecessors complete")
        self.assertEqual(data["queue_position"], 2)
        self.assertEqual(data["blocked_by_task_id"], 1)

    def test_head_execute_returns_immediate_message(self):
        task = _make_task(10, issue_sequence=1, status=TaskStatus.PENDING)
        task.project_id = 1
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                _make_scalar_one_or_none_result(task),
                _make_scalars_all_result([task]),
                _make_scalar_one_or_none_result(None),
            ]
        )
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        client, app = _make_app_client_with_db(mock_db)
        with patch("app.api.task_action_routes.notify_task_execute_now", new=AsyncMock()):
            with patch("app.core.task_helpers._require_task_operator", return_value=None):
                response = client.post("/api/tasks/10/execute")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["message"], "Task 10 scheduled for immediate execution")
        self.assertEqual(data["queue_position"], 1)


class RescheduleConflictAPITests(unittest.TestCase):
    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    def test_reschedule_window_conflict_returns_structured_409(self):
        from app.core.issue_task_order import ScheduleWindowConflict

        task = _make_task(
            3,
            issue_sequence=2,
            status=TaskStatus.PENDING,
            scheduled_at=datetime(2099, 1, 1, 12, 0, 0),
        )
        task.project_id = 1
        issue = MagicMock()
        issue.id = 1
        issue.project_id = 1
        conflict = ScheduleWindowConflict(
            {
                "code": "issue_schedule_order_conflict",
                "message": "Scheduled time is before this Issue's queue floor",
                "has_valid_window": True,
                "min_scheduled_at": "2099-01-01T10:00:00",
                "min_source_task_id": 1,
                "max_scheduled_at": None,
                "max_source_task_id": None,
            }
        )
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                _make_scalar_one_or_none_result(task),
                _make_scalar_one_or_none_result(issue),
            ]
        )
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        client, app = _make_app_client_with_db(mock_db)
        with patch(
            "app.core.issue_task_order.validate_schedule_time_locked",
            new=AsyncMock(side_effect=conflict),
        ):
            with patch("app.core.task_helpers._require_task_operator", return_value=None):
                response = client.patch(
                    "/api/tasks/3/schedule",
                    json={"scheduled_datetime": "2099-01-01T09:00:00"},
                )
        self.assertEqual(response.status_code, 409)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "issue_schedule_order_conflict")
        self.assertIn("floor", detail["message"])


if __name__ == "__main__":
    unittest.main()
