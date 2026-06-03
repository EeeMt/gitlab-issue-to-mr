#!/usr/bin/env python3
"""Unit tests for PATCH /tasks/{task_id} (update_task endpoint)."""

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

def _make_task(task_id=1, project_id=1, status=TaskStatus.PENDING):
    """Build a fully mocked Task with all attributes required by _serialize_task."""
    task = MagicMock()
    task.id = task_id
    task.project_id = project_id
    task.issue_id = 100
    task.issue_iid = 10
    task.note_id = 1000
    task.user_prompt = "Original prompt"
    task.priority = 1
    task.require_changes = True
    task.provider_id = None
    task.status = status
    task.initiator_user_id = None
    task.initiator_gitlab_user_id = None
    task.initiator_username = None
    task.branch_name = "codify/issue-10"
    task.merge_request_iid = None
    task.merge_request_url = None
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
    task.is_retry = False
    task.retry_source_task_id = None
    task.is_manual = False
    task.is_manually_overridden = False
    task.override_reason = None
    now = datetime(2024, 1, 1, 12, 0, 0)
    task.created_at = now
    task.updated_at = now
    task.started_at = None
    task.completed_at = None
    return task


def _make_client(mock_db):
    """Build a TestClient with all auth and DB dependencies overridden."""
    from app.main import app
    from app.database import get_db
    from app.dependencies.auth import get_optional_current_user, require_authenticated_user
    from app.dependencies.project_access import require_project_access_scope, ProjectAccessScope

    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_optional_current_user] = lambda: None
    app.dependency_overrides[require_authenticated_user] = lambda: MagicMock()
    app.dependency_overrides[require_project_access_scope] = lambda: access_scope

    return TestClient(app, raise_server_exceptions=False), app


def _mock_db_for_task(task):
    """Build a mock DB session that returns the given task from any execute call."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = task

    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.get = AsyncMock(return_value=None)   # default: provider not found
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    return mock_db


# ---------------------------------------------------------------------------
# Happy path: each field updated independently
# ---------------------------------------------------------------------------

class UpdateTaskHappyPathTests(unittest.TestCase):
    """PATCH /tasks/{id} applies only the fields present in the request body."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def _patch(self, task_id, payload, task=None):
        t = task or _make_task()
        mock_db = _mock_db_for_task(t)
        client, app = _make_client(mock_db)
        with patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})):
            resp = client.patch(f"/api/tasks/{task_id}", json=payload)
        app.dependency_overrides.clear()
        return resp, t

    def test_update_user_prompt(self):
        resp, task = self._patch(1, {"user_prompt": "New prompt"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(task.user_prompt, "New prompt")

    def test_update_priority(self):
        resp, task = self._patch(1, {"priority": 2})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(task.priority, 2)

    def test_update_require_changes_false(self):
        resp, task = self._patch(1, {"require_changes": False})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(task.require_changes)

    def test_update_provider_id_to_null_clears_provider(self):
        """provider_id: null removes the provider assignment."""
        task = _make_task()
        task.provider_id = 5
        resp, _ = self._patch(1, {"provider_id": None}, task=task)
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(task.provider_id)

    def test_update_provider_id_to_valid_sets_provider(self):
        """provider_id: <int> sets the provider after existence check passes."""
        task = _make_task()
        mock_db = _mock_db_for_task(task)
        mock_provider = MagicMock()
        mock_db.get = AsyncMock(return_value=mock_provider)   # provider found

        client, app = _make_client(mock_db)
        with patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})):
            resp = client.patch("/api/tasks/1", json={"provider_id": 7})
        app.dependency_overrides.clear()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(task.provider_id, 7)

    def test_queued_task_can_be_edited(self):
        task = _make_task(status=TaskStatus.QUEUED)
        resp, _ = self._patch(1, {"priority": 0}, task=task)
        self.assertEqual(resp.status_code, 200)

    def test_omitted_fields_are_not_modified(self):
        """Only fields included in the JSON body are written to the task."""
        task = _make_task()
        task.priority = 2
        resp, _ = self._patch(1, {"user_prompt": "Changed only"}, task=task)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(task.priority, 2)   # unchanged


# ---------------------------------------------------------------------------
# Status guard: non-editable statuses return 409
# ---------------------------------------------------------------------------

class UpdateTaskStatusGuardTests(unittest.TestCase):
    """PATCH /tasks/{id} returns 409 for tasks that are not PENDING or QUEUED."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def _patch_for_status(self, task_status):
        task = _make_task(status=task_status)
        mock_db = _mock_db_for_task(task)
        client, app = _make_client(mock_db)
        resp = client.patch("/api/tasks/1", json={"priority": 0})
        app.dependency_overrides.clear()
        return resp

    def test_running_task_returns_409(self):
        self.assertEqual(self._patch_for_status(TaskStatus.RUNNING).status_code, 409)

    def test_completed_task_returns_409(self):
        self.assertEqual(self._patch_for_status(TaskStatus.COMPLETED).status_code, 409)

    def test_failed_task_returns_409(self):
        self.assertEqual(self._patch_for_status(TaskStatus.FAILED).status_code, 409)

    def test_cancelled_task_returns_409(self):
        self.assertEqual(self._patch_for_status(TaskStatus.CANCELLED).status_code, 409)


# ---------------------------------------------------------------------------
# Field-level validation errors return 422
# ---------------------------------------------------------------------------

class UpdateTaskValidationTests(unittest.TestCase):
    """PATCH /tasks/{id} validates each field and returns 422 on bad input."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def _patch(self, payload):
        task = _make_task()
        mock_db = _mock_db_for_task(task)
        client, app = _make_client(mock_db)
        resp = client.patch("/api/tasks/1", json=payload)
        app.dependency_overrides.clear()
        return resp

    def test_empty_user_prompt_returns_422(self):
        resp = self._patch({"user_prompt": ""})
        self.assertEqual(resp.status_code, 422)

    def test_whitespace_only_prompt_returns_422(self):
        resp = self._patch({"user_prompt": "   "})
        self.assertEqual(resp.status_code, 422)

    def test_null_user_prompt_returns_422(self):
        resp = self._patch({"user_prompt": None})
        self.assertEqual(resp.status_code, 422)

    def test_invalid_priority_returns_422(self):
        resp = self._patch({"priority": 5})
        self.assertEqual(resp.status_code, 422)

    def test_negative_priority_returns_422(self):
        resp = self._patch({"priority": -1})
        self.assertEqual(resp.status_code, 422)

    def test_null_require_changes_returns_422(self):
        resp = self._patch({"require_changes": None})
        self.assertEqual(resp.status_code, 422)


# ---------------------------------------------------------------------------
# Provider validation: non-existent provider_id returns 404
# ---------------------------------------------------------------------------

class UpdateTaskProviderValidationTests(unittest.TestCase):
    """PATCH /tasks/{id} returns 404 when provider_id does not exist."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_nonexistent_provider_returns_404(self):
        task = _make_task()
        mock_db = _mock_db_for_task(task)
        mock_db.get = AsyncMock(return_value=None)   # provider not found

        client, app = _make_client(mock_db)
        resp = client.patch("/api/tasks/1", json={"provider_id": 9999})
        app.dependency_overrides.clear()

        self.assertEqual(resp.status_code, 404)
        self.assertIn("Provider not found", resp.json()["detail"])

    def test_null_provider_id_skips_existence_check(self):
        """provider_id: null means 'clear provider' — no DB lookup needed."""
        task = _make_task()
        mock_db = _mock_db_for_task(task)
        # db.get should NOT be called for null provider_id
        mock_db.get = AsyncMock(side_effect=AssertionError("db.get called for null provider_id"))

        client, app = _make_client(mock_db)
        with patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})):
            resp = client.patch("/api/tasks/1", json={"provider_id": None})
        app.dependency_overrides.clear()

        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# Task not found
# ---------------------------------------------------------------------------

class UpdateTaskNotFoundTests(unittest.TestCase):
    """PATCH /tasks/{id} returns 404 when the task does not exist."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_missing_task_returns_404(self):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        client, app = _make_client(mock_db)
        resp = client.patch("/api/tasks/999", json={"priority": 0})
        app.dependency_overrides.clear()

        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# Partial update semantics: empty body changes nothing
# ---------------------------------------------------------------------------

class UpdateTaskPartialSemanticsTests(unittest.TestCase):
    """PATCH /tasks/{id} with an empty body is valid and changes no fields."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_empty_body_leaves_task_unchanged(self):
        task = _make_task()
        task.user_prompt = "Original"
        task.priority = 2
        mock_db = _mock_db_for_task(task)

        client, app = _make_client(mock_db)
        with patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})):
            resp = client.patch("/api/tasks/1", json={})
        app.dependency_overrides.clear()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(task.user_prompt, "Original")
        self.assertEqual(task.priority, 2)


# ---------------------------------------------------------------------------
# Plan mode invariant: require_changes must always be False for plan tasks
# ---------------------------------------------------------------------------

class UpdateTaskPlanModeTests(unittest.TestCase):
    """PATCH /tasks/{id} enforces the plan-mode / require_changes invariant."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def _patch(self, payload, task=None):
        t = task or _make_task()
        mock_db = _mock_db_for_task(t)
        client, app = _make_client(mock_db)
        with patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})):
            resp = client.patch("/api/tasks/1", json=payload)
        app.dependency_overrides.clear()
        return resp, t

    def test_switching_to_plan_forces_require_changes_false(self):
        """PATCH task_mode='plan' on an execute task sets require_changes=False."""
        task = _make_task()
        task.task_mode = "execute"
        task.require_changes = True
        resp, t = self._patch({"task_mode": "plan"}, task=task)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(t.task_mode, "plan")
        self.assertFalse(t.require_changes)

    def test_patching_require_changes_true_on_plan_task_is_forced_false(self):
        """PATCH require_changes=True on an already-plan task stays False (invariant guard)."""
        task = _make_task()
        task.task_mode = "plan"
        task.require_changes = False
        resp, t = self._patch({"require_changes": True}, task=task)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(t.require_changes)

    def test_patching_both_plan_and_require_changes_true_forces_false(self):
        """PATCH task_mode='plan' + require_changes=True together: require_changes ends up False."""
        task = _make_task()
        task.task_mode = "execute"
        task.require_changes = True
        resp, t = self._patch({"task_mode": "plan", "require_changes": True}, task=task)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(t.task_mode, "plan")
        self.assertFalse(t.require_changes)

    def test_switching_to_execute_does_not_force_require_changes(self):
        """Switching from plan back to execute leaves require_changes as-is."""
        task = _make_task()
        task.task_mode = "plan"
        task.require_changes = False
        resp, t = self._patch({"task_mode": "execute", "require_changes": True}, task=task)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(t.task_mode, "execute")
        self.assertTrue(t.require_changes)

    def test_invalid_task_mode_returns_422(self):
        """PATCH task_mode with an unknown value returns 422."""
        resp, _ = self._patch({"task_mode": "review"})
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
