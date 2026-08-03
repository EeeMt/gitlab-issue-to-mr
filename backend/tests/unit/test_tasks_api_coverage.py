#!/usr/bin/env python3
"""Additional unit tests for app/api/tasks.py to improve coverage.

Targets missed lines:
- 71-72: invalid status values in comma-separated list_tasks filter
- 75-76: multiple valid statuses → Task.status.in_(valid_statuses)
- 166-167, 171: list_scheduled_tasks project_id + restricted scope
- 244: slow get_task warning (> 1s)
- 314-370: stream_task_logs SSE endpoint
- 418-430: get_task_stats GitLab API fallback
- 502-504: cancel_task docker container stop
"""

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient

from app.models import TaskStatus

# ---------------------------------------------------------------------------
# Helpers (reused patterns from test_tasks_api.py)
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
    task.model_name = None
    task.commit_message = None
    task.is_manual = False
    now = datetime(2024, 1, 1, 12, 0, 0)
    task.created_at = now
    task.updated_at = now
    task.started_at = None
    task.completed_at = None
    task.cancel_requested_at = None
    task.raw_logs_finalized_at = None
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


# ---------------------------------------------------------------------------
# Lines 71-72, 75-76: list_tasks with comma-separated status filter
# ---------------------------------------------------------------------------


class ListTasksStatusFilterTests(unittest.TestCase):
    """Tests for GET /api/tasks with comma-separated status values."""

    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    def test_invalid_status_values_return_400(self):
        """Invalid status values in comma-separated list now return 400."""
        mock_db = MagicMock()
        mock_db.execute = AsyncMock()

        client, app = _make_app_client_with_db(mock_db)

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            response = client.get("/api/tasks?status=invalid_xyz,also_bad")

        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid_xyz", response.json()["detail"])

    def test_mixed_valid_and_invalid_statuses_return_400(self):
        """Mixed valid/invalid statuses return 400 due to invalid part."""
        mock_db = MagicMock()
        mock_db.execute = AsyncMock()

        client, app = _make_app_client_with_db(mock_db)

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            response = client.get("/api/tasks?status=running,bogus_status")

        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 400)
        self.assertIn("bogus_status", response.json()["detail"])

    def test_multiple_valid_statuses_uses_in_filter(self):
        """Lines 75-76: multiple valid statuses produce Task.status.in_() filter."""
        task1 = _make_serializable_task(task_status=TaskStatus.RUNNING, task_id=1)
        task2 = _make_serializable_task(task_status=TaskStatus.PENDING, task_id=2)

        mock_data_result = MagicMock()
        mock_data_result.scalars.return_value.all.return_value = [task1, task2]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_data_result)

        client, app = _make_app_client_with_db(mock_db)

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            response = client.get("/api/tasks?status=running,pending")

        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)

    def test_all_invalid_statuses_returns_400(self):
        """All-invalid statuses return 400."""
        mock_db = MagicMock()
        mock_db.execute = AsyncMock()

        client, app = _make_app_client_with_db(mock_db)

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            response = client.get("/api/tasks?status=foo,bar")

        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 400)


# ---------------------------------------------------------------------------
# Lines 166-167, 171: list_scheduled_tasks with project_id + restricted scope
# ---------------------------------------------------------------------------


class ListScheduledTasksTests(unittest.TestCase):
    """Tests for GET /api/tasks/scheduled with various filters."""

    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    def _setup_scheduled_client(self, tasks_list, access_scope=None):
        """Build a TestClient with auth + page access overrides for scheduled endpoint."""
        from app.database import get_db
        from app.dependencies.auth import (
            get_optional_current_user,
            require_authenticated_context,
            require_authenticated_user,
        )
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.main import app

        if access_scope is None:
            access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        mock_data_result = MagicMock()
        mock_data_result.scalars.return_value.all.return_value = tasks_list

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_data_result)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_optional_current_user] = lambda: None
        app.dependency_overrides[require_authenticated_user] = lambda: MagicMock()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope
        # require_page_access("schedule_overview") returns a function — we
        # override the *inner* dependency (require_authenticated_context) so that
        # the page-access check passes without a real session/token.
        app.dependency_overrides[require_authenticated_context] = lambda: MagicMock()

        return TestClient(app, raise_server_exceptions=False), app

    def test_scheduled_tasks_with_project_id_filter(self):
        """Lines 166-167: project_id filter on scheduled tasks applies correctly."""
        task = _make_serializable_task(task_status=TaskStatus.PENDING, project_id=101)
        task.scheduled_at = datetime(2024, 6, 1, 12, 0, 0)

        client, app = self._setup_scheduled_client([task])

        with (
            patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})),
            patch("app.dependencies.auth.can_access_page", return_value=True),
        ):
            response = client.get("/api/tasks/scheduled?project_id=101")

        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 200)

    def test_scheduled_tasks_restricted_scope_no_projects(self):
        """Line 171: restricted scope with empty allowed projects returns empty."""
        from app.dependencies.project_access import ProjectAccessScope

        scope = ProjectAccessScope(is_unrestricted=False, accessible_projects=[])
        client, app = self._setup_scheduled_client([], access_scope=scope)

        with (
            patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})),
            patch("app.dependencies.auth.can_access_page", return_value=True),
        ):
            response = client.get("/api/tasks/scheduled")

        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_scheduled_tasks_restricted_scope_with_projects(self):
        """Lines 166-167: restricted scope with accessible projects applies IN filter."""
        from app.dependencies.project_access import ProjectAccessScope

        scope = ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[{"id": 101, "name": "Project 101"}],
        )
        task = _make_serializable_task(task_status=TaskStatus.PENDING, project_id=101)
        task.scheduled_at = datetime(2024, 6, 1, 12, 0, 0)

        client, app = self._setup_scheduled_client([task], access_scope=scope)

        with (
            patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})),
            patch("app.dependencies.auth.can_access_page", return_value=True),
        ):
            response = client.get("/api/tasks/scheduled")

        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# Line 244: get_task slow-path warning
# ---------------------------------------------------------------------------


class GetTaskSlowPathTests(unittest.TestCase):
    """Tests for GET /api/tasks/{id} slow query warning."""

    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    def test_get_task_slow_response_emits_warning(self):
        """Line 244: when total time > 1.0s, a warning should be logged."""
        task = _make_serializable_task(task_status=TaskStatus.RUNNING, task_id=42)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        client, app = _make_app_client_with_db(mock_db)

        # Make time.time() artificially return values that create > 1s gap
        call_count = 0

        def slow_time():
            nonlocal call_count
            call_count += 1
            # First call returns 0, subsequent calls create large gaps
            return 0.0 + (call_count * 0.3)

        with (
            patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
            patch("app.api.tasks.time.time", side_effect=slow_time),
            patch("app.api.tasks.logger") as mock_logger,
        ):
            response = client.get("/api/tasks/42")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        # The warning should have been triggered since total time is artificial > 1s
        # (5 calls × 0.3 = 1.5s gap between first and last)
        mock_logger.warning.assert_called()
        warning_msg = mock_logger.warning.call_args[0][0]
        self.assertIn("SLOW", warning_msg)


# ---------------------------------------------------------------------------
# Lines 314-370: stream_task_logs SSE endpoint
# ---------------------------------------------------------------------------


class StreamTaskLogsTests(unittest.TestCase):
    """Tests for GET /api/tasks/{task_id}/log-stream SSE endpoint."""

    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    def test_stream_task_logs_returns_404_for_missing_task(self):
        """Lines 314-320: stream returns 404 when task does not exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        client, app = _make_app_client_with_db(mock_db)
        with patch("app.api.task_log_routes.AsyncSessionLocal", MagicMock(return_value=mock_db)):
            response = client.get("/api/tasks/9999/log-stream")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 404)

    def test_stream_task_logs_completed_task_returns_events(self):
        """Lines 323-370: streaming a completed task emits logs then 'done' event."""
        task = _make_serializable_task(task_status=TaskStatus.COMPLETED, task_id=5)

        # Mock a log entry
        log1 = MagicMock()
        log1.id = 1
        log1.log_type = "assistant_text"
        log1.log_metadata = '{"text":"Hello"}'
        log1.message = "test message"
        log1.created_at = datetime(2024, 1, 1, 12, 0, 0)

        # First execute: task lookup (via get_db)
        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task

        # Second execute (inside generator / poll session): log query — return one log
        log_result = MagicMock()
        log_result.scalars.return_value.all.return_value = [log1]

        # Third execute (inside generator): task status recheck
        status_result = MagicMock()
        status_result.scalar_one_or_none.return_value = TaskStatus.COMPLETED

        # Fourth execute (inside generator): log query — no new logs
        empty_log_result = MagicMock()
        empty_log_result.scalars.return_value.all.return_value = []

        # Fifth execute (inside generator): task status recheck again
        status_result2 = MagicMock()
        status_result2.scalar_one_or_none.return_value = TaskStatus.COMPLETED

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[task_result, log_result, status_result, empty_log_result, status_result2]
        )
        # Allow mock_db to act as an async context manager (for AsyncSessionLocal())
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        client, app = _make_app_client_with_db(mock_db)

        mock_session_local = MagicMock(return_value=mock_db)
        with (
            patch("app.api.task_log_routes.AsyncSessionLocal", mock_session_local),
            patch("app.api.task_log_routes.asyncio.sleep", new_callable=AsyncMock),
        ):
            response = client.get("/api/tasks/5/log-stream?since_id=0")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/event-stream; charset=utf-8")

        # Parse SSE events from the response
        body = response.text
        # Logs are now delivered as a single named "batch" event with a JSON array.
        self.assertIn("event: batch\n", body)
        import json as _json_mod
        import re

        match = re.search(r"event: batch\ndata: (.+)\n", body)
        self.assertIsNotNone(match, "batch event data line not found")
        batch_payload = _json_mod.loads(match.group(1))
        self.assertIsInstance(batch_payload, list, "batch event data must be a JSON array")
        self.assertTrue(any(e.get("log_type") == "assistant_text" for e in batch_payload))
        # Regular log entries must NOT appear as unnamed data: events
        for line in body.splitlines():
            if line.startswith("data:") and '"log_type"' in line:
                try:
                    obj = _json_mod.loads(line[len("data:") :].strip())
                    if isinstance(obj, dict) and not obj.get("error"):
                        self.fail(f"log entry leaked into unnamed data: event: {line[:120]}")
                except _json_mod.JSONDecodeError:
                    pass
        self.assertIn("event: done", body)

    def test_stream_task_logs_running_task_emits_logs(self):
        """Lines 325-361: running task streams logs until it becomes terminal."""
        task = _make_serializable_task(task_status=TaskStatus.RUNNING, task_id=6)

        log1 = MagicMock()
        log1.id = 10
        log1.log_type = None
        log1.log_metadata = None
        log1.message = "Step 1 done"
        log1.created_at = datetime(2024, 1, 1, 12, 0, 0)

        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task

        # First poll: one log, task still running
        log_result1 = MagicMock()
        log_result1.scalars.return_value.all.return_value = [log1]
        running_status = MagicMock()
        running_status.scalar_one_or_none.return_value = TaskStatus.RUNNING

        # Second poll: no new logs, task completed
        empty_log_result = MagicMock()
        empty_log_result.scalars.return_value.all.return_value = []
        completed_status = MagicMock()
        completed_status.scalar_one_or_none.return_value = TaskStatus.COMPLETED

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                task_result,
                log_result1,
                running_status,
                empty_log_result,
                completed_status,
            ]
        )
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        client, app = _make_app_client_with_db(mock_db)

        mock_session_local = MagicMock(return_value=mock_db)
        with (
            patch("app.api.task_log_routes.AsyncSessionLocal", mock_session_local),
            patch("app.api.task_log_routes.asyncio.sleep", new_callable=AsyncMock),
        ):
            response = client.get("/api/tasks/6/log-stream")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        body = response.text
        # Logs are delivered as a named "batch" event — the message text
        # appears inside the JSON array, not as an unnamed data: event.
        self.assertIn("event: batch\n", body)
        self.assertIn("Step 1 done", body)
        self.assertIn("event: done", body)

    def test_stream_task_logs_error_during_streaming(self):
        """Lines 366-368: exception during streaming emits error event."""
        task = _make_serializable_task(task_status=TaskStatus.RUNNING, task_id=7)

        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[task_result, RuntimeError("DB connection dropped")]
        )
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        client, app = _make_app_client_with_db(mock_db)

        mock_session_local = MagicMock(return_value=mock_db)
        with (
            patch("app.api.task_log_routes.AsyncSessionLocal", mock_session_local),
            patch("app.api.task_log_routes.asyncio.sleep", new_callable=AsyncMock),
        ):
            response = client.get("/api/tasks/7/log-stream")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn("error", body)
        self.assertIn("DB connection dropped", body)


# ---------------------------------------------------------------------------
# Lines 418-430: get_task_stats GitLab API fallback
# ---------------------------------------------------------------------------


class GetTaskStatsGitLabFallbackTests(unittest.TestCase):
    """Tests for GET /api/tasks/{task_id}/stats with GitLab API fallback."""

    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    def test_stats_fallback_to_gitlab_returns_stats(self):
        """Lines 418-430: when DB stats are zero + MR exists, query GitLab API."""
        task = _make_serializable_task()
        task.id = 30
        task.project_id = 1
        task.additions = 0
        task.deletions = 0
        task.total_changes = 0
        task.merge_request_iid = 42  # Has an MR → should fallback to GitLab

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        client, app = _make_app_client_with_db(mock_db)

        fake_stats = {"additions": 25, "deletions": 5, "total": 30}
        mock_gitlab = MagicMock()
        mock_gitlab.get_merge_request_stats.return_value = fake_stats

        # get_gitlab_client is imported locally inside get_task_stats, so patch at source
        with (
            patch("app.core.gitlab_client.get_gitlab_client", return_value=mock_gitlab),
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value=fake_stats),
        ):
            response = client.get("/api/tasks/30/stats")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["additions"], 25)
        self.assertEqual(data["deletions"], 5)
        self.assertEqual(data["total"], 30)

    def test_stats_fallback_to_gitlab_returns_none(self):
        """Lines 427-428: when GitLab API returns None, endpoint returns zeros."""
        task = _make_serializable_task()
        task.id = 31
        task.project_id = 1
        task.additions = 0
        task.deletions = 0
        task.total_changes = 0
        task.merge_request_iid = 43

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        client, app = _make_app_client_with_db(mock_db)

        mock_gitlab = MagicMock()
        mock_gitlab.get_merge_request_stats.return_value = None

        with (
            patch("app.core.gitlab_client.get_gitlab_client", return_value=mock_gitlab),
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value=None),
        ):
            response = client.get("/api/tasks/31/stats")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data, {"additions": 0, "deletions": 0, "total": 0})


# ---------------------------------------------------------------------------
# Lines 502-504: cancel_task docker container stop
# ---------------------------------------------------------------------------


class CancelTaskDockerStopTests(unittest.TestCase):
    """Tests for cancel_task Docker container stop logic."""

    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    def test_cancel_task_stops_docker_container(self):
        """Lines 502-504: cancel should attempt to stop the Docker container."""
        task = _make_serializable_task(task_status=TaskStatus.RUNNING)
        task.id = 40
        task.project_id = 1
        task.issue_id = 100

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        mock_container = MagicMock()
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container
        mock_docker.read_file_from_container.return_value = b""

        client, app = _make_app_client_with_db(mock_db)

        with (
            patch("app.api.task_action_routes.notify_task_cancelled", new=AsyncMock()),
            patch("app.core.task_helpers._require_task_operator", return_value=None),
            patch("app.api.task_action_routes.get_docker_client_async", return_value=mock_docker),
            patch(
                "app.api.task_action_routes.persist_raw_log_snapshot", new=AsyncMock()
            ),
            patch(
                "app.api.task_action_routes.asyncio.to_thread", new_callable=AsyncMock
            ) as mock_to_thread,
        ):
            # Mock asyncio.to_thread to call the function synchronously
            mock_to_thread.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
            response = client.post("/api/tasks/40/cancel")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        # Docker should have tried to get container "codify-40-issue100"
        mock_docker.client.containers.get.assert_called_once_with("codify-40-issue100")
        mock_container.stop.assert_called_once_with(timeout=10)
        # Removal is deferred to the scheduler's worker finalization so it can
        # drain the log stream and ingest the cancelled canonical terminal.
        mock_container.remove.assert_not_called()
        self.assertIsNotNone(task.raw_logs_finalized_at)

    def test_cancel_task_with_different_issue_id(self):
        """Cancel task builds container name from issue_id."""
        task = _make_serializable_task(task_status=TaskStatus.RUNNING)
        task.id = 41
        task.project_id = 2
        task.issue_id = 200

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        mock_container = MagicMock()
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container
        mock_docker.read_file_from_container.return_value = b""

        client, app = _make_app_client_with_db(mock_db)

        with (
            patch("app.api.task_action_routes.notify_task_cancelled", new=AsyncMock()),
            patch("app.core.task_helpers._require_task_operator", return_value=None),
            patch("app.api.task_action_routes.get_docker_client_async", return_value=mock_docker),
            patch(
                "app.api.task_action_routes.persist_raw_log_snapshot", new=AsyncMock()
            ),
            patch(
                "app.api.task_action_routes.asyncio.to_thread", new_callable=AsyncMock
            ) as mock_to_thread,
        ):
            mock_to_thread.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
            response = client.post("/api/tasks/41/cancel")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        mock_docker.client.containers.get.assert_called_once_with("codify-41-issue200")

    def test_cancel_task_persists_stable_console_snapshot(self):
        """Cancel should persist console.log after stopping and before removal."""
        task = _make_serializable_task(task_status=TaskStatus.RUNNING)
        task.id = 43
        task.project_id = 1
        task.issue_id = 100

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        mock_container = MagicMock()
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container
        mock_docker.read_file_from_container.return_value = b"complete console\n"
        client, app = _make_app_client_with_db(mock_db)

        with (
            patch("app.api.task_action_routes.notify_task_cancelled", new=AsyncMock()),
            patch("app.core.task_helpers._require_task_operator", return_value=None),
            patch("app.api.task_action_routes.get_docker_client_async", return_value=mock_docker),
            patch(
                "app.api.task_action_routes.persist_raw_log_snapshot", new=AsyncMock()
            ) as persist_snapshot,
            patch(
                "app.api.task_action_routes.asyncio.to_thread", new_callable=AsyncMock
            ) as mock_to_thread,
        ):
            mock_to_thread.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
            response = client.post("/api/tasks/43/cancel")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        persist_snapshot.assert_awaited_once_with(
            mock_db,
            task_id=43,
            content=b"complete console\n",
        )
        mock_container.stop.assert_called_once_with(timeout=10)
        mock_container.remove.assert_not_called()
        self.assertIsNotNone(task.raw_logs_finalized_at)
        self.assertIsNone(task.container_id)

    def test_cancel_task_retains_container_when_console_snapshot_fails(self):
        """A failed console.log read must not be reported as finalized."""
        task = _make_serializable_task(task_status=TaskStatus.RUNNING)
        task.id = 44
        task.project_id = 1
        task.issue_id = 100
        task.container_id = "container-44"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        mock_container = MagicMock()
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container
        mock_docker.read_file_from_container.return_value = None
        client, app = _make_app_client_with_db(mock_db)

        with (
            patch("app.api.task_action_routes.notify_task_cancelled", new=AsyncMock()),
            patch("app.core.task_helpers._require_task_operator", return_value=None),
            patch("app.api.task_action_routes.get_docker_client_async", return_value=mock_docker),
            patch(
                "app.api.task_action_routes.release_issue_execution_lock",
                new=AsyncMock(),
            ) as release_lock,
            patch(
                "app.api.task_action_routes.asyncio.to_thread", new_callable=AsyncMock
            ) as mock_to_thread,
        ):
            mock_to_thread.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
            response = client.post("/api/tasks/44/cancel")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(task.raw_logs_finalized_at)
        mock_container.stop.assert_called_once_with(timeout=10)
        mock_container.remove.assert_not_called()
        release_lock.assert_not_awaited()

    def test_cancel_task_docker_failure_defers_cancellation(self):
        """Unknown remote container state must keep the task active and locked."""
        task = _make_serializable_task(task_status=TaskStatus.RUNNING)
        task.id = 42
        task.project_id = 1
        task.issue_id = 50

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        client, app = _make_app_client_with_db(mock_db)

        with (
            patch("app.api.task_action_routes.notify_task_cancelled", new=AsyncMock()),
            patch("app.core.task_helpers._require_task_operator", return_value=None),
            patch(
                "app.api.task_action_routes.get_docker_client_async",
                side_effect=RuntimeError("Docker not running"),
            ),
        ):
            response = client.post("/api/tasks/42/cancel")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(task.status, TaskStatus.RUNNING)
        self.assertIsNotNone(task.cancel_requested_at)
        mock_db.commit.assert_awaited_once()

    def test_cancel_task_uses_stable_container_id(self):
        """A deployment-time container prefix change must not break cancellation."""
        task = _make_serializable_task(task_status=TaskStatus.RUNNING)
        task.id = 45
        task.project_id = 1
        task.issue_id = 100
        task.container_id = "stable-container-45"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        mock_container = MagicMock()
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container
        mock_docker.read_file_from_container.return_value = b"final\n"
        client, app = _make_app_client_with_db(mock_db)

        with (
            patch("app.api.task_action_routes.notify_task_cancelled", new=AsyncMock()),
            patch("app.core.task_helpers._require_task_operator", return_value=None),
            patch("app.api.task_action_routes.get_docker_client_async", return_value=mock_docker),
            patch(
                "app.api.task_action_routes.persist_raw_log_snapshot", new=AsyncMock()
            ),
            patch(
                "app.api.task_action_routes.asyncio.to_thread", new_callable=AsyncMock
            ) as mock_to_thread,
        ):
            mock_to_thread.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
            response = client.post("/api/tasks/45/cancel")

        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 200)
        mock_docker.client.containers.get.assert_called_once_with("stable-container-45")
        # container_id is retained until the scheduler removes the container.
        self.assertEqual(task.container_id, "stable-container-45")

    def test_cancel_task_defers_when_running_container_has_no_stable_id(self):
        """NotFound during worker bootstrap must not release the issue lock."""
        from app.core.worker_docker_targets import TaskContainerNotFoundError

        task = _make_serializable_task(task_status=TaskStatus.RUNNING)
        task.id = 46
        task.project_id = 1
        task.issue_id = 100
        task.container_id = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        client, app = _make_app_client_with_db(mock_db)

        with (
            patch("app.api.task_action_routes.notify_task_cancelled", new=AsyncMock()),
            patch("app.core.task_helpers._require_task_operator", return_value=None),
            patch(
                "app.api.task_action_routes.find_task_container",
                new=AsyncMock(side_effect=TaskContainerNotFoundError("not created yet")),
            ),
            patch(
                "app.api.task_action_routes.release_issue_execution_lock", new=AsyncMock()
            ) as release_lock,
        ):
            response = client.post("/api/tasks/46/cancel")

        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(task.status, TaskStatus.RUNNING)
        self.assertIsNotNone(task.cancel_requested_at)
        release_lock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
