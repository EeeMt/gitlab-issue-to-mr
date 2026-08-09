#!/usr/bin/env python3
"""Unit tests for task API helpers and status-transition validators."""

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
from app.core.worker_profiles import WorkerProfileValidationError
from app.models import Task, TaskSkillVersionReference, TaskStatus, TaskWorkerProfileSnapshot


@pytest.fixture(autouse=True)
def _stub_runtime_bundle_binding():
    async def bind(_db, task, *, source_task=None):
        source_id = getattr(source_task, "runtime_bundle_id", None) if source_task else None
        task.runtime_bundle_id = source_id if isinstance(source_id, int) else 9001
        return SimpleNamespace(id=task.runtime_bundle_id, digest="d" * 64)

    with patch("app.api.tasks.bind_runtime_bundle", new=AsyncMock(side_effect=bind)):
        yield


def _make_task(status: TaskStatus, scheduled_at=None) -> MagicMock:
    """Helper: build a MagicMock Task with the given status."""
    task = MagicMock()
    task.status = status
    task.scheduled_at = scheduled_at
    return task


def _added_task(mock_db) -> Task:
    return next(
        call.args[0]
        for call in mock_db.add.call_args_list
        if call.args and isinstance(call.args[0], Task)
    )


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
        for status in [
            TaskStatus.PENDING,
            TaskStatus.RUNNING,
            TaskStatus.QUEUED,
            TaskStatus.COMPLETED,
        ]:
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
        """PENDING and QUEUED tasks can be executed immediately."""
        validate_task_status_for_execute(_make_task(TaskStatus.PENDING))
        validate_task_status_for_execute(_make_task(TaskStatus.QUEUED))

    def test_execute_invalid_statuses(self) -> None:
        """Non-PENDING/QUEUED tasks cannot be executed immediately."""
        for status in [
            TaskStatus.RUNNING,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.COMPLETED,
        ]:
            with self.subTest(status=status):
                with self.assertRaises(HTTPException) as ctx:
                    validate_task_status_for_execute(_make_task(status))
                self.assertEqual(ctx.exception.status_code, 400)


# ---------------------------------------------------------------------------
# validate_task_status_for_reschedule
# ---------------------------------------------------------------------------


class ValidateRescheduleTests(unittest.TestCase):
    """Tests for validate_task_status_for_reschedule."""

    def test_reschedule_valid_pending(self) -> None:
        """PENDING task with a scheduled_at can be rescheduled."""
        future = datetime.now(UTC) + timedelta(hours=1)
        validate_task_status_for_reschedule(_make_task(TaskStatus.PENDING, scheduled_at=future))

    def test_reschedule_valid_queued(self) -> None:
        """QUEUED task can be rescheduled (pushes it back to PENDING)."""
        validate_task_status_for_reschedule(_make_task(TaskStatus.QUEUED))

    def test_reschedule_invalid_status(self) -> None:
        """Non-PENDING/QUEUED tasks cannot be rescheduled."""
        future = datetime.now(UTC) + timedelta(hours=1)
        for status in [TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.COMPLETED]:
            with self.subTest(status=status):
                with self.assertRaises(HTTPException) as ctx:
                    validate_task_status_for_reschedule(_make_task(status, scheduled_at=future))
                self.assertEqual(ctx.exception.status_code, 400)

    def test_reschedule_raises_when_pending_no_scheduled_at(self) -> None:
        """PENDING task without scheduled_at (immediate task) cannot be rescheduled."""
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
        from app.database import get_db
        from app.dependencies.auth import get_optional_current_user, require_authenticated_user
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.main import app

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        mock_db = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.get = AsyncMock(return_value=getattr(task, "issue", None))

        if task is not None:
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = task
            mock_result.scalar_one.return_value = 0
            mock_db.execute = AsyncMock(return_value=mock_result)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_optional_current_user] = lambda: None
        app.dependency_overrides[require_authenticated_user] = lambda: MagicMock()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        client = TestClient(app, raise_server_exceptions=False)
        return client, app, mock_db

    def test_cancel_changes_status_to_cancelled(self) -> None:
        """POST /api/tasks/{id}/cancel should set task status to CANCELLED and return 200."""
        task = MagicMock()
        task.id = 1
        task.project_id = 1
        task.status = TaskStatus.PENDING
        task.scheduled_at = None
        task.container_id = None

        client, app, _mock_db = self._get_client(task)

        with patch("app.api.task_action_routes.notify_task_cancelled", new=AsyncMock()):
            with patch("app.core.task_helpers._require_task_operator", return_value=None):
                response = client.post("/api/tasks/1/cancel")

        # Clean up overrides
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(task.status, TaskStatus.CANCELLED)

    def test_cancel_running_task_keeps_lock_until_converged(self) -> None:
        """A RUNNING cancel records intent and keeps the Issue lock; the worker
        finalizer converges the terminal and releases it (spec §6.7)."""
        from app.core.worker_docker_targets import TaskContainerNotFoundError

        task = MagicMock()
        task.id = 2
        task.project_id = 1
        task.issue_id = 33
        task.status = TaskStatus.RUNNING
        task.scheduled_at = None
        task.container_id = "gone-container-2"
        task.cancel_requested_at = None
        task.raw_logs_finalized_at = None

        client, app, _mock_db = self._get_client(task)

        with (
            patch("app.api.task_action_routes.notify_task_cancelled", new=AsyncMock()),
            patch("app.core.task_helpers._require_task_operator", return_value=None),
            patch(
                "app.api.task_action_routes.find_task_container",
                new=AsyncMock(side_effect=TaskContainerNotFoundError("missing")),
            ),
            patch(
                "app.api.task_action_routes.release_issue_execution_lock", new=AsyncMock()
            ) as mock_release,
        ):
            response = client.post("/api/tasks/2/cancel")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(task.status, TaskStatus.RUNNING)
        self.assertIsNotNone(task.cancel_requested_at)
        mock_release.assert_not_awaited()

    def test_cancel_running_task_does_not_downgrade_completed(self) -> None:
        """Cancel of a RUNNING task must not downgrade a run the finalizer
        already converged to COMPLETED while the cancel was in flight."""
        from app.core.worker_docker_targets import TaskContainerNotFoundError

        task = MagicMock()
        task.id = 3
        task.project_id = 1
        task.issue_id = 33
        task.status = TaskStatus.RUNNING
        task.scheduled_at = None
        task.container_id = "ctr-3"
        task.cancel_requested_at = None

        client, app, mock_db = self._get_client(task)

        async def converge_to_completed(*_args, **_kwargs):
            # Simulate the scheduler finalizer converging the run to COMPLETED
            # while this cancel was stopping the container / draining logs.
            task.status = TaskStatus.COMPLETED

        mock_db.refresh = AsyncMock(side_effect=converge_to_completed)

        with (
            patch("app.api.task_action_routes.notify_task_cancelled", new=AsyncMock()),
            patch("app.core.task_helpers._require_task_operator", return_value=None),
            patch(
                "app.api.task_action_routes.find_task_container",
                new=AsyncMock(side_effect=TaskContainerNotFoundError("missing")),
            ),
            patch("app.api.task_action_routes.release_issue_execution_lock", new=AsyncMock()),
        ):
            response = client.post("/api/tasks/3/cancel")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(task.status, TaskStatus.COMPLETED)

    def test_cancel_task_404_when_not_found(self) -> None:
        """POST /api/tasks/{id}/cancel should return 404 when task not found."""
        from app.database import get_db
        from app.dependencies.auth import get_optional_current_user, require_authenticated_user
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.main import app

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

    def test_get_task_workspace_status_returns_disabled_when_not_configured(self) -> None:
        """GET /workspace returns disabled when workspace root is empty."""
        task = MagicMock()
        task.id = 3
        task.project_id = 100
        task.issue_id = 1
        task.issue = MagicMock(id=1, project_id=100)
        task.status = TaskStatus.FAILED

        client, app, mock_db = self._get_client(task)

        with patch(
            "app.api.tasks.get_effective_settings",
            return_value=MagicMock(worker_workspace_host_path=""),
        ):
            response = client.get("/api/tasks/3/workspace")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()["enabled"], False)
        mock_db.get.assert_awaited_once()

    def test_delete_task_workspace_calls_remote_worker_helper(self) -> None:
        """DELETE /workspace removes the directory on the issue's worker daemon."""
        task = MagicMock()
        task.id = 4
        task.project_id = 100
        task.issue_id = 1
        task.issue = MagicMock(id=1, project_id=100, worker_profile_id=7)
        task.status = TaskStatus.FAILED

        client, app, mock_db = self._get_client(task)
        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task
        issue_result = MagicMock()
        issue_result.scalar_one_or_none.return_value = task.issue
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        mock_db.execute = AsyncMock(side_effect=[task_result, issue_result, count_result])

        with patch(
            "app.api.tasks.get_effective_settings",
            return_value=MagicMock(worker_workspace_host_path="/opt/codify-workspaces"),
        ):
            with patch(
                "app.api.tasks.remove_issue_workspace_remote",
                new=AsyncMock(return_value=True),
            ) as mock_remove:
                response = client.delete("/api/tasks/4/workspace")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        mock_remove.assert_awaited_once()
        self.assertIs(response.json()["removed"], True)
        self.assertEqual(response.json()["worker_profile_id"], 7)

    def test_delete_task_workspace_counts_retained_containers_as_active(self) -> None:
        """Workspace deletion must retain mounts needed by unfinished log collection."""
        task = MagicMock(id=5, project_id=100, issue_id=1, status=TaskStatus.FAILED)
        task.issue = MagicMock(id=1, project_id=100, worker_profile_id=7)
        client, app, mock_db = self._get_client(task)
        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task
        issue_result = MagicMock()
        issue_result.scalar_one_or_none.return_value = task.issue
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        mock_db.execute = AsyncMock(side_effect=[task_result, issue_result, count_result])

        response = client.delete("/api/tasks/5/workspace")

        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 400)
        self.assertIn("active or retained", response.json()["detail"])
        count_query = mock_db.execute.await_args_list[2].args[0]
        self.assertIn("container_id IS NOT NULL", str(count_query))


# ---------------------------------------------------------------------------
# require_changes: CreateTaskRequest schema and serialization
# ---------------------------------------------------------------------------


class TestRequireChangesSchema(unittest.TestCase):
    def test_create_task_request_defaults_require_changes_to_false(self):
        from app.api.task_schemas import CreateTaskRequest

        req = CreateTaskRequest(issue_id=1, provider_id=1)
        self.assertFalse(req.require_changes)

    def test_create_task_request_accepts_explicit_false(self):
        from app.api.task_schemas import CreateTaskRequest

        req = CreateTaskRequest(issue_id=1, provider_id=1, require_changes=False)
        self.assertFalse(req.require_changes)


class TestRequireChangesSerialization(unittest.TestCase):
    def test_serialize_task_includes_require_changes(self):
        from app.core.task_helpers import _serialize_task

        task = MagicMock()
        task.id = 1
        task.issue_id = None
        task.project_id = 1
        task.user_prompt = "x"
        task.initiator_user_id = None
        task.initiator_gitlab_user_id = None
        task.initiator_username = None
        task.is_retry = False
        task.retry_source_task_id = None
        task.status = TaskStatus.PENDING
        task.priority = 0
        task.scheduled_at = None
        task.container_id = None
        task.commit_sha = None
        task.error_message = None
        task.additions = 0
        task.deletions = 0
        task.total_changes = 0
        task.input_tokens = None
        task.output_tokens = None
        task.model_name = None
        task.commit_message = None
        task.provider_id = None
        task.provider_name = None
        task.created_at = datetime(2026, 5, 5, 12, 0, 0)
        task.updated_at = datetime(2026, 5, 5, 12, 0, 0)
        task.started_at = None
        task.completed_at = None
        task.require_changes = True

        with patch(
            "app.core.task_helpers.get_effective_settings",
            return_value=MagicMock(gitlab_url="http://gitlab.example.com"),
        ):
            with patch("app.core.task_helpers.sa_inspect") as mock_inspect:
                mock_insp = MagicMock()
                mock_insp.unloaded = {"issue", "provider"}
                mock_inspect.return_value = mock_insp
                data = _serialize_task(task)

        self.assertIn("require_changes", data)
        self.assertTrue(data["require_changes"])


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
    task.issue_id = 1
    task.user_prompt = "Test prompt"
    task.run_instruction_template = None
    task.rendered_prompt = "Execute Test prompt"
    task.rendered_prompt_at = datetime(2024, 1, 1, 11, 59, 0)
    task.trigger_source = "manual"
    task.ci_failure_run_id = None
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
    task.change_stats_recorded_at = None
    task.input_tokens = 0
    task.output_tokens = 0
    task.model_name = None
    task.commit_message = None
    task.provider_id = None
    task.provider = None
    task.worker_profile_id = 12
    task.worker_profile = None
    task.worker_profile_snapshot = _make_worker_snapshot(
        task_id=task_id,
        worker_profile_id=task.worker_profile_id,
    )
    task.runtime_bundle_id = 41
    task.provider_runtime_snapshot = {
        "provider_id": None,
        "provider_name": "snapshot",
        "base_url": "https://provider.example.test",
    }
    task.issue = None
    now = datetime(2024, 1, 1, 12, 0, 0)
    task.created_at = now
    task.updated_at = now
    task.started_at = None
    task.completed_at = None
    # Issue input-stream ordering / projected lineage (nullable compat fields).
    task.issue_sequence = None
    task.projected_harness_key = None
    task.projected_session_namespace = None
    task.projected_lineage_generation = None
    task.projected_reset_task_id = None
    task.lineage_projection_reason = None
    task.input_lineage_reason = None
    return task


def _make_mock_provider(id=1):
    """Create a mock AIProvider with minimal attributes."""
    provider = MagicMock()
    provider.id = id
    provider.name = "Test Provider"
    provider.model = "test-model"
    provider.is_default = True
    provider.is_disabled = False
    return provider


def _make_mock_worker_profile(id=12):
    """Create a mock WorkerProfile with minimal attributes."""
    profile = MagicMock()
    profile.id = id
    profile.name = "Default Worker"
    profile.enabled = True
    profile.runtime_mode = "mounted_kit"
    profile.worker_kit_version = "0.3.5"
    profile.worker_kit_path = "/opt/codify/worker-kits/0.3.5-linux-amd64"
    return profile


def _make_worker_snapshot(task_id=101, worker_profile_id=12):
    """Create a real task worker snapshot for task API serialization/rendering."""
    return TaskWorkerProfileSnapshot(
        task_id=task_id,
        worker_profile_id=worker_profile_id,
        profile_name="Default Worker",
        image="codify-worker/java21-maven:2026.07",
        volume_mounts=[],
        environment_variables=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
        created_at=datetime(2024, 1, 1, 12, 0, 0),
    )


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


def _make_scalars_all_result(rows):
    """Mock db.execute result whose ``.scalars().all()`` yields ``rows``."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _make_rows_all_result(rows):
    """Mock db.execute result whose ``.all()`` yields ``rows``."""
    result = MagicMock()
    result.all.return_value = rows
    return result


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
        log1.log_metadata = None

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

    def test_get_task_logs_returns_log_type_field(self):
        """GET /api/tasks/{id}/logs response includes log_type field for each entry."""
        task = _make_serializable_task()

        log1 = MagicMock()
        log1.id = 1
        log1.task_id = 1
        log1.log_level = "INFO"
        log1.log_type = None
        log1.log_metadata = None
        log1.message = "Plain log line"
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
        self.assertIn("log_type", data[0])
        self.assertIsNone(data[0]["log_type"])

    def test_get_task_logs_returns_thinking_log_type(self):
        """GET /api/tasks/{id}/logs should return thinking log entries with log_type='thinking'."""
        task = _make_serializable_task()

        thinking_log = MagicMock()
        thinking_log.id = 2
        thinking_log.task_id = 1
        thinking_log.log_level = "INFO"
        thinking_log.log_type = "thinking"
        thinking_log.log_metadata = '{"text":"I need to think about this problem"}'
        thinking_log.message = ""
        thinking_log.created_at = datetime(2024, 1, 1, 12, 0, 1)

        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task

        logs_result = MagicMock()
        logs_result.scalars.return_value.all.return_value = [thinking_log]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[task_result, logs_result])

        client, app = _make_app_client_with_db(mock_db)
        response = client.get("/api/tasks/1/logs")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["log_type"], "thinking")
        self.assertEqual(data[0]["metadata"], {"text": "I need to think about this problem"})
        self.assertEqual(data[0]["message"], "")

    def test_get_task_logs_returns_assistant_text_log_type(self):
        """GET /api/tasks/{id}/logs should return assistant_text log entries."""
        task = _make_serializable_task()

        assistant_log = MagicMock()
        assistant_log.id = 3
        assistant_log.task_id = 1
        assistant_log.log_level = "INFO"
        assistant_log.log_type = "assistant_text"
        assistant_log.log_metadata = '{"text":"Here is my response to your request"}'
        assistant_log.message = ""
        assistant_log.created_at = datetime(2024, 1, 1, 12, 0, 2)

        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task

        logs_result = MagicMock()
        logs_result.scalars.return_value.all.return_value = [assistant_log]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[task_result, logs_result])

        client, app = _make_app_client_with_db(mock_db)
        response = client.get("/api/tasks/1/logs")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["log_type"], "assistant_text")
        self.assertEqual(data[0]["metadata"], {"text": "Here is my response to your request"})

    def test_get_task_logs_returns_tool_call_log_type(self):
        """GET /api/tasks/{id}/logs should return tool_call log entries with log_type='tool_call'."""
        task = _make_serializable_task()

        tool_log = MagicMock()
        tool_log.id = 4
        tool_log.task_id = 1
        tool_log.log_level = "INFO"
        tool_log.log_type = "tool_call"
        tool_log.log_metadata = '{"name":"bash","input":{"command":"ls"},"output":"file1.py"}'
        tool_log.message = ""
        tool_log.created_at = datetime(2024, 1, 1, 12, 0, 3)

        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task

        logs_result = MagicMock()
        logs_result.scalars.return_value.all.return_value = [tool_log]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[task_result, logs_result])

        client, app = _make_app_client_with_db(mock_db)
        response = client.get("/api/tasks/1/logs")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["log_type"], "tool_call")

    def test_get_task_logs_returns_mixed_log_types(self):
        """GET /api/tasks/{id}/logs should return multiple log entries with different log_types."""
        task = _make_serializable_task()

        plain_log = MagicMock()
        plain_log.id = 1
        plain_log.task_id = 1
        plain_log.log_level = "INFO"
        plain_log.log_type = None
        plain_log.log_metadata = None
        plain_log.message = "Starting container"
        plain_log.created_at = datetime(2024, 1, 1, 12, 0, 0)

        thinking_log = MagicMock()
        thinking_log.id = 2
        thinking_log.task_id = 1
        thinking_log.log_level = "INFO"
        thinking_log.log_type = "thinking"
        thinking_log.log_metadata = '{"text":"Let me analyze"}'
        thinking_log.message = ""
        thinking_log.created_at = datetime(2024, 1, 1, 12, 0, 1)

        assistant_log = MagicMock()
        assistant_log.id = 3
        assistant_log.task_id = 1
        assistant_log.log_level = "INFO"
        assistant_log.log_type = "assistant_text"
        assistant_log.log_metadata = '{"text":"I will fix the bug"}'
        assistant_log.message = ""
        assistant_log.created_at = datetime(2024, 1, 1, 12, 0, 2)

        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task

        logs_result = MagicMock()
        logs_result.scalars.return_value.all.return_value = [plain_log, thinking_log, assistant_log]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[task_result, logs_result])

        client, app = _make_app_client_with_db(mock_db)
        response = client.get("/api/tasks/1/logs")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 3)
        self.assertIsNone(data[0]["log_type"])
        self.assertEqual(data[1]["log_type"], "thinking")
        self.assertEqual(data[2]["log_type"], "assistant_text")


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/retry — retry endpoint
# ---------------------------------------------------------------------------


class RetryTaskAPITests(unittest.TestCase):
    """Tests for POST /api/tasks/{task_id}/retry."""

    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    def test_retry_task_success_for_failed_task(self):
        """POST /api/tasks/{id}/retry should create a new retry task from a FAILED task."""
        from app.models import Task

        task = _make_serializable_task(task_status=TaskStatus.FAILED)
        task.id = 5
        task.project_id = 1
        task.session_mode = "fresh"
        task.output_session_id = None
        task.worker_profile_snapshot = _make_worker_snapshot(task_id=5)
        task.worker_profile_snapshot.skill_references = [
            TaskSkillVersionReference(
                task_id=5,
                position=0,
                skill_id=17,
                name="review-changes",
                description="Review changes before delivery.",
                skill_version_id=71,
            )
        ]
        task.worker_profile_snapshot.skill_selection_source = "task"

        # First execute returns the task; second returns None (no existing retry);
        # third fetches the Issue used for worker/provider resolution and serialization.
        mock_result_task = MagicMock()
        mock_result_task.scalar_one_or_none.return_value = task
        mock_result_no_retry = MagicMock()
        mock_result_no_retry.scalar_one_or_none.return_value = None
        mock_result_issue = MagicMock()
        mock_result_issue.scalar_one_or_none.return_value = MagicMock(id=1, project_id=1)

        now = datetime(2024, 1, 1, 12, 0, 0)

        async def fake_refresh(obj, attribute_names=None):
            if isinstance(obj, Task):
                obj.id = 100
                obj.status = TaskStatus.PENDING
                obj.created_at = now
                obj.updated_at = now

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[mock_result_task, mock_result_no_retry, mock_result_issue, _make_scalars_all_result([task]), _make_rows_all_result([]), _make_scalars_all_result([]), MagicMock()]
        )
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        client, app = _make_app_client_with_db(mock_db)

        with (
            patch("app.api.tasks.notify_task_retried", new=AsyncMock()),
            patch("app.core.task_helpers._require_task_operator", return_value=None),
            patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
            patch(
                "app.api.tasks.resolve_worker_profile_for_issue",
                new=AsyncMock(return_value=_make_mock_worker_profile()),
            ),
            patch(
                "app.api.tasks.resolve_provider_for_issue",
                new=AsyncMock(return_value=_make_mock_provider(id=1)),
            ),
            patch(
                "app.api.tasks.replace_task_worker_snapshot",
                new=AsyncMock(return_value=_make_worker_snapshot(task_id=100)),
            ),
        ):
            response = client.post("/api/tasks/5/retry")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["is_retry"])
        self.assertEqual(data["retry_source_task_id"], 5)
        self.assertEqual(data["skill_names"], ["review-changes"])
        self.assertEqual(data["skill_selection_source"], "task")
        created_task = mock_db.add.call_args_list[0].args[0]
        self.assertEqual(created_task.session_mode, "fresh")

    def test_retry_task_rejects_closed_issue(self):
        task = _make_serializable_task(task_status=TaskStatus.FAILED)
        task.id = 51
        task.issue_id = 1
        mock_result_task = MagicMock()
        mock_result_task.scalar_one_or_none.return_value = task
        mock_result_no_retry = MagicMock()
        mock_result_no_retry.scalar_one_or_none.return_value = None
        mock_result_issue = MagicMock()
        mock_result_issue.scalar_one_or_none.return_value = MagicMock(
            id=1,
            project_id=1,
            status="closed",
        )
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[mock_result_task, mock_result_no_retry, mock_result_issue, _make_scalars_all_result([task]), _make_rows_all_result([]), _make_scalars_all_result([]), MagicMock()]
        )
        mock_db.add = MagicMock()

        client, app = _make_app_client_with_db(mock_db)
        with patch("app.core.task_helpers._require_task_operator", return_value=None):
            response = client.post("/api/tasks/51/retry")

        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 400)
        self.assertIn("closed issue", response.json()["detail"])
        mock_db.add.assert_not_called()

    def test_retry_task_success_for_cancelled_task(self):
        """POST /api/tasks/{id}/retry should create a new retry task from a CANCELLED task."""
        from app.models import Task

        task = _make_serializable_task(task_status=TaskStatus.CANCELLED)
        task.id = 6
        task.project_id = 1
        task.session_mode = "fresh"
        task.output_session_id = "session-created-by-source"

        # First execute returns the task; second returns None (no existing retry);
        # third is the Issue row lock (returns a provider-shaped mock whose id is
        # used as the issue id); fourth is the new ordering query; fifth is the
        # lineage snapshot query.
        mock_result_task = MagicMock()
        mock_result_task.scalar_one_or_none.return_value = task
        mock_result_no_retry = MagicMock()
        mock_result_no_retry.scalar_one_or_none.return_value = None
        mock_result_default_provider = MagicMock()
        mock_result_default_provider.scalar_one_or_none.return_value = _make_mock_provider(id=1)

        now = datetime(2024, 1, 1, 12, 0, 0)

        async def fake_refresh(obj, attribute_names=None):
            if isinstance(obj, Task):
                obj.id = 101
                obj.status = TaskStatus.PENDING
                obj.created_at = now
                obj.updated_at = now

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                mock_result_task,
                mock_result_no_retry,
                mock_result_default_provider,
                _make_scalars_all_result([task]),
                _make_rows_all_result([]),
                _make_scalars_all_result([]),
                MagicMock(),
            ]
        )
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        client, app = _make_app_client_with_db(mock_db)

        with (
            patch("app.api.tasks.notify_task_retried", new=AsyncMock()),
            patch("app.core.task_helpers._require_task_operator", return_value=None),
            patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
            patch(
                "app.api.tasks.resolve_worker_profile_for_issue",
                new=AsyncMock(return_value=_make_mock_worker_profile()),
            ),
            patch(
                "app.api.tasks.resolve_provider_for_issue",
                new=AsyncMock(return_value=_make_mock_provider(id=1)),
            ),
            patch(
                "app.api.tasks.replace_task_worker_snapshot",
                new=AsyncMock(return_value=_make_worker_snapshot(task_id=101)),
            ),
        ):
            response = client.post("/api/tasks/6/retry")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["is_retry"])
        self.assertEqual(data["retry_source_task_id"], 6)
        created_task = mock_db.add.call_args_list[0].args[0]
        self.assertEqual(created_task.session_mode, "continue")

    def test_retry_task_preserves_provider_id(self):
        """POST /api/tasks/{id}/retry should keep the original provider_id."""
        from app.models import Task

        task = _make_serializable_task(task_status=TaskStatus.FAILED)
        task.id = 7
        task.project_id = 1
        task.provider_id = 23

        mock_result_task = MagicMock()
        mock_result_task.scalar_one_or_none.return_value = task
        mock_result_no_retry = MagicMock()
        mock_result_no_retry.scalar_one_or_none.return_value = None
        mock_result_issue = MagicMock()
        mock_result_issue.scalar_one_or_none.return_value = MagicMock(id=1, project_id=1)

        now = datetime(2024, 1, 1, 12, 0, 0)

        async def fake_refresh(obj, attribute_names=None):
            if isinstance(obj, Task):
                obj.id = 107
                obj.status = TaskStatus.PENDING
                obj.created_at = now
                obj.updated_at = now

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[mock_result_task, mock_result_no_retry, mock_result_issue, _make_scalars_all_result([task]), _make_rows_all_result([]), _make_scalars_all_result([]), MagicMock()]
        )
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        client, app = _make_app_client_with_db(mock_db)

        with (
            patch("app.api.tasks.notify_task_retried", new=AsyncMock()),
            patch("app.core.task_helpers._require_task_operator", return_value=None),
            patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
            patch(
                "app.api.tasks.resolve_worker_profile_for_issue",
                new=AsyncMock(return_value=_make_mock_worker_profile(id=12)),
            ),
            patch(
                "app.api.tasks.resolve_provider_for_issue",
                new=AsyncMock(return_value=_make_mock_provider(id=23)),
            ),
            patch(
                "app.api.tasks.replace_task_worker_snapshot",
                new=AsyncMock(return_value=_make_worker_snapshot(task_id=107)),
            ) as mock_replace_snapshot,
        ):
            response = client.post("/api/tasks/7/retry")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        created_task = _added_task(mock_db)
        self.assertEqual(created_task.provider_id, 23)
        self.assertEqual(created_task.worker_profile_id, 12)
        mock_replace_snapshot.assert_not_awaited()

    def test_retry_task_preserves_ci_failure_context(self):
        """Retrying a CI repair keeps the bundle provenance and renders its stable path."""
        from app.core.task_prompt import BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE
        from app.models import Issue, Task

        task = _make_serializable_task(task_status=TaskStatus.FAILED)
        task.id = 8
        task.project_id = 42
        task.provider_id = 23
        task.task_mode = "execute"
        task.require_changes = True
        task.trigger_source = "ci_auto_repair"
        task.ci_failure_run_id = 91
        task.run_instruction_template = BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE
        task.rendered_prompt = "Repair using /tmp/codify-runtime/ci-failure without re-rendering"

        issue = Issue(id=1, title="Repair CI", project_id=42, status="in_review")
        mock_result_task = MagicMock()
        mock_result_task.scalar_one_or_none.return_value = task
        mock_result_no_retry = MagicMock()
        mock_result_no_retry.scalar_one_or_none.return_value = None
        mock_result_issue = MagicMock()
        mock_result_issue.scalar_one_or_none.return_value = issue

        now = datetime(2024, 1, 1, 12, 0, 0)

        async def fake_refresh(obj, attribute_names=None):
            if isinstance(obj, Task):
                obj.id = 108
                obj.status = TaskStatus.PENDING
                obj.created_at = now
                obj.updated_at = now

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[mock_result_task, mock_result_no_retry, mock_result_issue, _make_scalars_all_result([task]), _make_rows_all_result([]), _make_scalars_all_result([]), MagicMock()]
        )
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        client, app = _make_app_client_with_db(mock_db)
        with (
            patch("app.api.tasks.notify_task_retried", new=AsyncMock()),
            patch("app.core.task_helpers._require_task_operator", return_value=None),
            patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
            patch(
                "app.api.tasks.resolve_worker_profile_for_issue",
                new=AsyncMock(return_value=_make_mock_worker_profile()),
            ),
            patch(
                "app.api.tasks.resolve_provider_for_issue",
                new=AsyncMock(return_value=_make_mock_provider(id=23)),
            ),
            patch(
                "app.api.tasks.replace_task_worker_snapshot",
                new=AsyncMock(return_value=_make_worker_snapshot(task_id=108)),
            ),
        ):
            response = client.post("/api/tasks/8/retry")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        created_task = _added_task(mock_db)
        self.assertEqual(created_task.trigger_source, "retry")
        self.assertEqual(created_task.ci_failure_run_id, 91)
        self.assertEqual(created_task.rendered_prompt, task.rendered_prompt)

    def test_retry_task_does_not_re_resolve_disabled_original_provider(self):
        """Retry uses the frozen provider reference instead of editable provider state."""
        task = _make_serializable_task(task_status=TaskStatus.FAILED)
        task.id = 71
        task.project_id = 1
        task.provider_id = 23

        mock_result_task = MagicMock()
        mock_result_task.scalar_one_or_none.return_value = task
        mock_result_no_retry = MagicMock()
        mock_result_no_retry.scalar_one_or_none.return_value = None
        mock_result_issue = MagicMock()
        mock_result_issue.scalar_one_or_none.return_value = MagicMock(id=1, project_id=1)

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[mock_result_task, mock_result_no_retry, mock_result_issue, _make_scalars_all_result([task]), _make_rows_all_result([]), _make_scalars_all_result([]), MagicMock()]
        )
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        async def fake_refresh(obj, attribute_names=None):
            if isinstance(obj, Task):
                obj.id = 171
                obj.status = TaskStatus.PENDING
                obj.created_at = datetime(2024, 1, 1, 12, 0, 0)
                obj.updated_at = datetime(2024, 1, 1, 12, 0, 0)

        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        client, app = _make_app_client_with_db(mock_db)

        with (
            patch("app.core.task_helpers._require_task_operator", return_value=None),
            patch("app.api.tasks.notify_task_retried", new=AsyncMock()),
            patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
            patch(
                "app.api.tasks.resolve_provider_for_issue",
                new=AsyncMock(
                    side_effect=WorkerProfileValidationError(
                        "AI provider 'Test Provider' is disabled"
                    )
                ),
            ) as provider_resolver,
        ):
            response = client.post("/api/tasks/71/retry")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(_added_task(mock_db).provider_id, 23)
        provider_resolver.assert_not_awaited()

    def test_retry_task_does_not_fall_back_to_current_default_provider(self):
        """A null frozen provider stays null; retry never consults the new default."""
        task = _make_serializable_task(task_status=TaskStatus.FAILED)
        task.id = 72
        task.project_id = 1
        task.provider_id = None

        mock_result_task = MagicMock()
        mock_result_task.scalar_one_or_none.return_value = task
        mock_result_no_retry = MagicMock()
        mock_result_no_retry.scalar_one_or_none.return_value = None
        mock_result_issue = MagicMock()
        mock_result_issue.scalar_one_or_none.return_value = MagicMock(id=1, project_id=1)

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[mock_result_task, mock_result_no_retry, mock_result_issue, _make_scalars_all_result([task]), _make_rows_all_result([]), _make_scalars_all_result([]), MagicMock()]
        )
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        async def fake_refresh(obj, attribute_names=None):
            if isinstance(obj, Task):
                obj.id = 172
                obj.status = TaskStatus.PENDING
                obj.created_at = datetime(2024, 1, 1, 12, 0, 0)
                obj.updated_at = datetime(2024, 1, 1, 12, 0, 0)

        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        client, app = _make_app_client_with_db(mock_db)

        with (
            patch("app.core.task_helpers._require_task_operator", return_value=None),
            patch("app.api.tasks.notify_task_retried", new=AsyncMock()),
            patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
            patch(
                "app.api.tasks.resolve_provider_for_issue",
                new=AsyncMock(
                    side_effect=WorkerProfileValidationError(
                        "AI provider 'Test Provider' is disabled"
                    )
                ),
            ) as provider_resolver,
        ):
            response = client.post("/api/tasks/72/retry")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(_added_task(mock_db).provider_id)
        provider_resolver.assert_not_awaited()

    def test_retry_task_returns_409_when_usage_limit_exceeded(self):
        """POST /api/tasks/{id}/retry should enforce create quota limits."""
        from app.core.usage_limits import UsageLimitExceeded
        from app.dependencies.auth import get_optional_current_user, require_authenticated_user

        task = _make_serializable_task(task_status=TaskStatus.FAILED)
        task.id = 70
        task.project_id = 1

        mock_result_task = MagicMock()
        mock_result_task.scalar_one_or_none.return_value = task
        mock_result_no_retry = MagicMock()
        mock_result_no_retry.scalar_one_or_none.return_value = None
        mock_result_issue = MagicMock()
        mock_result_issue.scalar_one_or_none.return_value = MagicMock(id=1, project_id=1)

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[mock_result_task, mock_result_no_retry, mock_result_issue, _make_scalars_all_result([task]), _make_rows_all_result([]), _make_scalars_all_result([]), MagicMock()]
        )
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        current_user = MagicMock()
        current_user.id = 7
        current_user.gitlab_user_id = 17
        current_user.username = "alice"
        current_user.display_name = "Alice"
        current_user.email = "alice@example.com"

        client, app = _make_app_client_with_db(
            mock_db,
            extra_overrides={
                get_optional_current_user: lambda: current_user,
                require_authenticated_user: lambda: current_user,
            },
        )

        with (
            patch("app.core.task_helpers._require_task_operator", return_value=None),
            patch(
                "app.api.tasks.get_usage_quota_service",
                return_value=MagicMock(
                    raise_if_over_limit=AsyncMock(
                        side_effect=UsageLimitExceeded(
                            scope="create",
                            exceeded_items=[
                                {
                                    "field": "daily_tasks",
                                    "window": "daily",
                                    "metric": "tasks",
                                    "used": 6,
                                    "limit": 5,
                                    "reset_at": "2026-04-28T00:00:00+00:00",
                                }
                            ],
                        )
                    )
                ),
            ),
        ):
            response = client.post("/api/tasks/70/retry")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["reason"], "usage_limit_exceeded")

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

        with patch("app.api.task_action_routes.notify_task_execute_now", new=AsyncMock()):
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

    def test_get_task_stats_returns_zeros_when_no_changes(self):
        """GET /api/tasks/{id}/stats returns zeros when no changes recorded."""
        task = _make_serializable_task()
        task.id = 21
        task.project_id = 1
        task.additions = 0
        task.deletions = 0
        task.total_changes = 0
        task.merge_request_iid = None  # no MR, take early return path

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
        from app.database import get_db
        from app.dependencies.auth import get_optional_current_user, require_authenticated_user
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.main import app

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        async def fake_refresh(task, attribute_names=None):
            """Simulate DB commit by setting required fields."""
            if isinstance(task, TaskWorkerProfileSnapshot):
                return
            task.id = 99
            if task.status is None:
                task.status = TaskStatus.PENDING
            if task.created_at is None:
                task.created_at = datetime(2024, 1, 1, 12, 0, 0)
            if task.updated_at is None:
                task.updated_at = datetime(2024, 1, 1, 12, 0, 0)

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=fake_refresh)
        mock_db.execute = AsyncMock(return_value=_make_scalars_all_result([]))

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_optional_current_user] = lambda: None
        app.dependency_overrides[require_authenticated_user] = lambda: MagicMock()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        mock_issue = MagicMock()
        mock_issue.id = 1
        mock_issue.project_id = 1
        mock_issue.description = "Fix the login bug"
        mock_db.get = AsyncMock(return_value=mock_issue)

        client = TestClient(app, raise_server_exceptions=False)
        with (
            patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
            patch(
                "app.api.tasks.resolve_worker_profile_for_issue",
                new=AsyncMock(return_value=_make_mock_worker_profile()),
            ),
            patch(
                "app.api.tasks.resolve_provider_for_issue",
                new=AsyncMock(return_value=_make_mock_provider(id=1)),
            ),
            patch(
                "app.api.tasks.replace_task_worker_snapshot",
                new=AsyncMock(return_value=_make_worker_snapshot(task_id=99)),
            ),
        ):
            response = client.post(
                "/api/tasks",
                json={
                    "issue_id": 1,
                    "user_prompt": "Fix the login bug",
                    "priority": 0,
                    "provider_id": 1,
                    "session_mode": "fresh",
                },
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("id", data)
        self.assertEqual(data["project_id"], 1)
        self.assertEqual(data["user_prompt"], "Fix the login bug")
        self.assertEqual(data["session_mode"], "fresh")
        created_task = mock_db.add.call_args_list[0].args[0]
        self.assertEqual(created_task.session_mode, "fresh")

    def test_create_task_returns_409_when_usage_limit_exceeded(self):
        """POST /api/tasks returns structured 409 when quota is already exceeded."""
        from app.core.usage_limits import UsageLimitExceeded
        from app.database import get_db
        from app.dependencies.auth import get_optional_current_user, require_authenticated_user
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.main import app

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        async def override_db():
            yield mock_db

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        no_lineage = MagicMock()
        no_lineage.scalar_one_or_none.return_value = None
        no_lineage.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=no_lineage)

        current_user = MagicMock()
        current_user.id = 7
        current_user.gitlab_user_id = 17
        current_user.username = "alice"
        current_user.display_name = "Alice"
        current_user.email = "alice@example.com"

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_optional_current_user] = lambda: current_user
        app.dependency_overrides[require_authenticated_user] = lambda: current_user
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        mock_issue = MagicMock()
        mock_issue.id = 1
        mock_issue.project_id = 1
        mock_issue.description = "Ship it"
        mock_issue.status = "open"
        mock_db.get = AsyncMock(return_value=mock_issue)

        client = TestClient(app, raise_server_exceptions=False)
        with (
            patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
            patch("app.core.task_helpers._require_issue_operator", return_value=None),
            patch(
                "app.api.tasks.resolve_worker_profile_for_issue",
                new=AsyncMock(return_value=_make_mock_worker_profile()),
            ),
            patch(
                "app.api.tasks.resolve_provider_for_issue",
                new=AsyncMock(return_value=_make_mock_provider(id=1)),
            ),
            patch(
                "app.api.tasks.replace_task_worker_snapshot",
                new=AsyncMock(return_value=_make_worker_snapshot(task_id=99)),
            ),
            patch(
                "app.api.tasks.get_usage_quota_service",
                return_value=MagicMock(
                    raise_if_over_limit=AsyncMock(
                        side_effect=UsageLimitExceeded(
                            scope="create",
                            exceeded_items=[
                                {
                                    "metric": "tokens",
                                    "window": "daily",
                                    "used": 120000,
                                    "limit": 100000,
                                    "reset_at": "2026-04-28T00:00:00+08:00",
                                }
                            ],
                        )
                    )
                ),
            ),
        ):
            response = client.post(
                "/api/tasks",
                json={
                    "issue_id": 1,
                    "user_prompt": "Ship it",
                    "priority": 0,
                    "provider_id": 1,
                },
            )
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["reason"], "usage_limit_exceeded")


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


# ---------------------------------------------------------------------------
# GET /tasks/{task_id} — get single task endpoint
# ---------------------------------------------------------------------------


class GetTaskEndpointTests(unittest.TestCase):
    """Tests for GET /api/tasks/{task_id} endpoint."""

    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    def test_get_task_returns_serialized_task(self):
        """GET /api/tasks/{id} should return the serialized task."""
        task = _make_serializable_task(task_status=TaskStatus.RUNNING, task_id=42)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        client, app = _make_app_client_with_db(mock_db)

        with patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})):
            response = client.get("/api/tasks/42")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], 42)
        self.assertEqual(data["status"], "running")

    def test_get_task_returns_404_when_not_found(self):
        """GET /api/tasks/{id} should return 404 when task does not exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        client, app = _make_app_client_with_db(mock_db)
        response = client.get("/api/tasks/9999")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 404)

    def test_get_task_response_includes_model_name_field(self):
        """GET /api/tasks/{id} response should include model_name field (None when not set)."""
        task = _make_serializable_task(task_status=TaskStatus.COMPLETED, task_id=55)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        client, app = _make_app_client_with_db(mock_db)

        with patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})):
            response = client.get("/api/tasks/55")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("model_name", data)
        self.assertIsNone(data["model_name"])

    def test_get_task_response_includes_commit_message_field(self):
        """GET /api/tasks/{id} response should include commit_message field (None when not set)."""
        task = _make_serializable_task(task_status=TaskStatus.COMPLETED, task_id=56)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        client, app = _make_app_client_with_db(mock_db)

        with patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})):
            response = client.get("/api/tasks/56")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("commit_message", data)
        self.assertIsNone(data["commit_message"])


# ---------------------------------------------------------------------------
# PATCH /tasks/{task_id}/stats — update task stats endpoint
# ---------------------------------------------------------------------------


class UpdateTaskStatsAPITests(unittest.TestCase):
    """Tests for PATCH /api/tasks/{task_id}/stats endpoint."""

    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    def test_update_task_stats_success(self):
        """PATCH /api/tasks/{id}/stats should update stats and return success."""
        task = _make_serializable_task()
        task.id = 30
        task.project_id = 1

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        client, app = _make_app_client_with_db(mock_db)
        response = client.patch("/api/tasks/30/stats?additions=100&deletions=20&total=120")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["additions"], 100)
        self.assertEqual(data["deletions"], 20)
        self.assertEqual(data["total"], 120)
        self.assertEqual(task.additions, 100)
        self.assertEqual(task.deletions, 20)

    def test_update_task_stats_returns_404_when_not_found(self):
        """PATCH /api/tasks/{id}/stats returns 404 when task not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        client, app = _make_app_client_with_db(mock_db)
        response = client.patch("/api/tasks/9999/stats?additions=0&deletions=0&total=0")
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/retry — with scheduled_datetime
# ---------------------------------------------------------------------------


class RetryTaskWithScheduleTests(unittest.TestCase):
    """Tests for retry task with a scheduled_datetime in request body."""

    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    def test_retry_task_with_future_scheduled_datetime(self):
        """POST /api/tasks/{id}/retry with future scheduled_datetime schedules retry."""
        from app.models import Task

        task = _make_serializable_task(task_status=TaskStatus.FAILED)
        task.id = 80
        task.project_id = 1
        # A continue retry must match the tail lineage tuple (§4.6); pin the
        # source projection to the tail projection used below.
        task.projected_harness_key = "claude"
        task.projected_session_namespace = "claude-ns"
        task.projected_lineage_generation = 0
        task.projected_reset_task_id = None
        task.lineage_projection_reason = "initial"

        # First execute returns the task; second returns None (no existing retry);
        # third fetches the Issue under its row lock.
        mock_result_task = MagicMock()
        mock_result_task.scalar_one_or_none.return_value = task
        mock_result_no_retry = MagicMock()
        mock_result_no_retry.scalar_one_or_none.return_value = None
        mock_result_issue = MagicMock()
        mock_result_issue.scalar_one_or_none.return_value = MagicMock(id=1, project_id=1)

        now = datetime(2024, 1, 1, 12, 0, 0)

        async def fake_refresh(obj, attribute_names=None):
            if isinstance(obj, Task):
                obj.id = 102
                obj.status = TaskStatus.PENDING
                obj.created_at = now
                obj.updated_at = now

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                mock_result_task,
                mock_result_no_retry,
                mock_result_issue,
                _make_scalars_all_result([task]),
                _make_rows_all_result([]),
                _make_scalars_all_result([]),
                _make_scalars_all_result([]),
                MagicMock(),
            ]
        )
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        client, app = _make_app_client_with_db(mock_db)

        future_dt = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
        tail_projection = {
            "harness_key": "claude",
            "session_namespace": "claude-ns",
            "generation": 0,
            "reset_task_id": None,
        }

        with (
            patch("app.api.tasks.notify_task_retried", new=AsyncMock()),
            patch("app.core.task_helpers._require_task_operator", return_value=None),
            patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})),
            patch(
                "app.api.tasks.resolve_worker_profile_for_issue",
                new=AsyncMock(return_value=_make_mock_worker_profile()),
            ),
            patch(
                "app.api.tasks.resolve_provider_for_issue",
                new=AsyncMock(return_value=_make_mock_provider(id=1)),
            ),
            patch(
                "app.api.tasks.replace_task_worker_snapshot",
                new=AsyncMock(return_value=_make_worker_snapshot(task_id=102)),
            ),
            patch(
                "app.api.task_creation_service.ensure_issue_order_integrity_locked",
                new=AsyncMock(
                    return_value={
                        "max_sequence": 1,
                        "tail_projection": tail_projection,
                        "repaired_sequences": 0,
                        "repaired_projections": 0,
                        "blocked": False,
                    }
                ),
            ),
            patch(
                "app.api.task_creation_service.validate_schedule_time_locked",
                new=AsyncMock(),
            ),
            patch(
                "app.api.task_creation_service.compute_task_queue_contexts",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.core.slot_capacity.check_slot_capacity",
                new=AsyncMock(return_value=MagicMock(is_full=False, enforce=True)),
            ),
        ):
            response = client.post("/api/tasks/80/retry", json={"scheduled_datetime": future_dt})

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["is_retry"])
        self.assertEqual(data["retry_source_task_id"], 80)
        self.assertIsNotNone(data["scheduled_at"])


class ListTasksProviderTests(unittest.TestCase):
    """Tests for provider data in GET /api/tasks responses."""

    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    def test_list_tasks_includes_provider_name_when_loaded(self):
        """GET /api/tasks should serialize provider_name when provider is loaded."""
        task = _make_serializable_task(project_id=1)
        task.provider_id = 9
        task.provider = MagicMock(name="provider")
        task.provider.name = "OpenAI Prod"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [task]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        client, app = _make_app_client_with_db(mock_db)

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            response = client.get("/api/tasks")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data[0]["provider_id"], 9)
        self.assertEqual(data[0]["provider_name"], "OpenAI Prod")

        executed_query = mock_db.execute.await_args_list[0].args[0]
        self.assertIn("provider", str(executed_query))


# ---------------------------------------------------------------------------
# GET /tasks — list tasks with restricted access scope
# ---------------------------------------------------------------------------


class ListTasksRestrictedScopeTests(unittest.TestCase):
    """Tests for GET /api/tasks with restricted access scope."""

    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    def _setup_restricted_client(self, tasks_list, accessible_project_ids):
        from app.database import get_db
        from app.dependencies.auth import get_optional_current_user, require_authenticated_user
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.main import app

        accessible_projects = [
            {"id": pid, "name": f"Project {pid}"} for pid in accessible_project_ids
        ]
        access_scope = ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=accessible_projects,
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = tasks_list
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_optional_current_user] = lambda: None
        app.dependency_overrides[require_authenticated_user] = lambda: MagicMock()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        return TestClient(app, raise_server_exceptions=False), app

    def test_list_tasks_with_accessible_projects_uses_filter(self):
        """GET /api/tasks with restricted scope queries only accessible projects."""
        task = _make_serializable_task(project_id=1)
        client, app = self._setup_restricted_client([task], accessible_project_ids=[1])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            response = client.get("/api/tasks")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)

    def test_list_tasks_with_no_accessible_projects_returns_empty(self):
        """GET /api/tasks with restricted scope and no projects returns empty."""
        client, app = self._setup_restricted_client([], accessible_project_ids=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            response = client.get("/api/tasks")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_tasks_with_project_id_filter_and_restricted_scope(self):
        """GET /api/tasks?project_id=1 with restricted scope applies project filter."""
        task = _make_serializable_task(project_id=1)
        client, app = self._setup_restricted_client([task], accessible_project_ids=[1])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            response = client.get("/api/tasks?project_id=1")

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# GET /tasks — pagination support
# ---------------------------------------------------------------------------


class PaginationTests(unittest.TestCase):
    """Tests for GET /api/tasks hybrid pagination (legacy array vs paginated dict)."""

    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    def _setup_paginated_client(self, tasks_list, total_count=None):
        """Build a TestClient with mocked DB supporting pagination.

        When *total_count* is provided the mock handles the two ``db.execute``
        calls made in paginated mode (COUNT then data).  When *total_count* is
        ``None`` only a single data result is returned (legacy mode).
        """
        from app.database import get_db
        from app.dependencies.auth import get_optional_current_user, require_authenticated_user
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.main import app

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        mock_data_result = MagicMock()
        mock_data_result.scalars.return_value.all.return_value = tasks_list

        mock_db = MagicMock()

        if total_count is not None:
            # Paginated mode: count, data, then per-Issue queue context (tasks +
            # lock). Empty task sets do not reach the queue-context queries, so the
            # extra entries are simply left unconsumed.
            mock_count_result = MagicMock()
            mock_count_result.scalar.return_value = total_count
            mock_db.execute = AsyncMock(
                side_effect=[
                    mock_count_result,
                    mock_data_result,
                    _make_scalars_all_result(tasks_list),
                    MagicMock(),
                ]
            )
        else:
            # Legacy mode: single execute → data
            mock_db.execute = AsyncMock(return_value=mock_data_result)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_optional_current_user] = lambda: None
        app.dependency_overrides[require_authenticated_user] = lambda: MagicMock()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope

        return TestClient(app, raise_server_exceptions=False), app

    # -- Test cases ----------------------------------------------------------

    def test_list_tasks_without_page_returns_array(self):
        """GET /api/tasks without page param returns a plain list (backward compat)."""
        task = _make_serializable_task(project_id=1)
        client, app = self._setup_paginated_client([task])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            response = client.get("/api/tasks")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_list_tasks_with_page_returns_paginated_response(self):
        """GET /api/tasks?page=1 returns dict with items, total, page, page_size."""
        task = _make_serializable_task(project_id=1)
        client, app = self._setup_paginated_client([task], total_count=1)

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            response = client.get("/api/tasks?page=1")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, dict)
        self.assertIn("items", data)
        self.assertIn("total", data)
        self.assertIn("page", data)
        self.assertIn("page_size", data)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["total"], 1)

    def test_list_tasks_pagination_defaults(self):
        """GET /api/tasks?page=1 defaults to page_size=20."""
        client, app = self._setup_paginated_client([], total_count=0)

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            response = client.get("/api/tasks?page=1")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 20)
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["items"], [])

    def test_list_tasks_custom_page_size(self):
        """GET /api/tasks?page=1&page_size=50 uses the requested page_size."""
        client, app = self._setup_paginated_client([], total_count=0)

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            response = client.get("/api/tasks?page=1&page_size=50")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["page_size"], 50)

    def test_list_tasks_page_size_clamped_to_100(self):
        """GET /api/tasks?page=1&page_size=200 clamps page_size to 100."""
        client, app = self._setup_paginated_client([], total_count=0)

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            response = client.get("/api/tasks?page=1&page_size=200")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["page_size"], 100)

    def test_list_tasks_page_min_1(self):
        """GET /api/tasks?page=0 or page=-1 gets clamped to page 1."""
        for page_val in [0, -1]:
            client, app = self._setup_paginated_client([], total_count=0)

            with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
                response = client.get(f"/api/tasks?page={page_val}")

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["page"], 1, f"page={page_val} should be clamped to 1")

            app.dependency_overrides.clear()

    def test_list_tasks_pagination_with_filters(self):
        """GET /api/tasks?page=1&status=pending applies both pagination and filter."""
        task = _make_serializable_task(task_status=TaskStatus.PENDING, project_id=1)
        client, app = self._setup_paginated_client([task], total_count=1)

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            response = client.get("/api/tasks?page=1&status=pending")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, dict)
        self.assertEqual(data["total"], 1)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["page"], 1)
