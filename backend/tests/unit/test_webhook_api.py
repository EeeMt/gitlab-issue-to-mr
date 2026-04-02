#!/usr/bin/env python3
"""Unit tests for GitLab webhook API handler logic.

Tests cover:
- is_generic_prompt helper
- _coerce_int / _coerce_str helpers
- gitlab_webhook endpoint dispatching
- _handle_issue_comment logic
- _handle_cancel_command logic
- _handle_generate_command duplicate detection
- _resolve_initiator_user_id helper
"""

import os
import sys
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# is_generic_prompt
# ---------------------------------------------------------------------------

class IsGenericPromptTests(unittest.TestCase):
    """Tests for the is_generic_prompt helper function."""

    def _check(self, prompt: str) -> bool:
        from app.api.webhook import is_generic_prompt
        return is_generic_prompt(prompt)

    def test_generic_start_command(self):
        """'start' should be detected as a generic prompt."""
        self.assertTrue(self._check("start"))

    def test_generic_do_this(self):
        """'do this' should be detected as a generic prompt."""
        self.assertTrue(self._check("do this"))

    def test_generic_implement_this(self):
        """'implement this' should be detected as a generic prompt."""
        self.assertTrue(self._check("Implement this"))

    def test_generic_fix_this(self):
        """'fix this' should be detected as a generic prompt."""
        self.assertTrue(self._check("fix this"))

    def test_specific_prompt_not_generic(self):
        """A specific task description should not be detected as generic."""
        self.assertFalse(self._check("Add pagination to the user list endpoint"))

    def test_empty_string_is_generic(self):
        """Empty string is treated as a generic (no-prompt) request and returns True."""
        self.assertTrue(self._check(""))

    def test_long_specific_prompt_not_generic(self):
        """A detailed multi-word prompt is not generic."""
        self.assertFalse(self._check("Refactor the authentication module to support OAuth 2.0"))

    def test_generic_chinese_implement_issue(self):
        """Chinese '实现这个issue' should be detected as a generic prompt."""
        self.assertTrue(self._check("实现这个issue"))

    def test_generic_this_issue_english(self):
        """'this issue' should be detected as a generic prompt."""
        self.assertTrue(self._check("this issue"))


# ---------------------------------------------------------------------------
# _coerce_int / _coerce_str
# ---------------------------------------------------------------------------

class CoerceHelperTests(unittest.TestCase):
    """Tests for _coerce_int and _coerce_str helpers."""

    def test_coerce_int_with_integer(self):
        from app.api.webhook import _coerce_int
        self.assertEqual(_coerce_int(42), 42)

    def test_coerce_int_with_string_number(self):
        from app.api.webhook import _coerce_int
        self.assertEqual(_coerce_int("99"), 99)

    def test_coerce_int_with_none(self):
        from app.api.webhook import _coerce_int
        self.assertIsNone(_coerce_int(None))

    def test_coerce_int_with_invalid_string(self):
        from app.api.webhook import _coerce_int
        self.assertIsNone(_coerce_int("not-a-number"))

    def test_coerce_str_with_string(self):
        from app.api.webhook import _coerce_str
        self.assertEqual(_coerce_str("alice"), "alice")

    def test_coerce_str_with_none(self):
        from app.api.webhook import _coerce_str
        self.assertIsNone(_coerce_str(None))

    def test_coerce_str_with_whitespace_only(self):
        from app.api.webhook import _coerce_str
        self.assertIsNone(_coerce_str("   "))

    def test_coerce_str_strips_whitespace(self):
        from app.api.webhook import _coerce_str
        self.assertEqual(_coerce_str("  bob  "), "bob")


# ---------------------------------------------------------------------------
# gitlab_webhook endpoint — dispatching
# ---------------------------------------------------------------------------

def _make_db_override():
    """Build a mock DB that works as an async context manager."""
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=MagicMock())
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    async def override_db():
        yield mock_db

    return override_db, mock_db


class GitlabWebhookDispatchTests(unittest.TestCase):
    """Tests for the gitlab_webhook endpoint routing."""

    def tearDown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def _get_client(self):
        from app.main import app
        from app.database import get_db
        override_db, mock_db = _make_db_override()
        app.dependency_overrides[get_db] = override_db
        return TestClient(app, raise_server_exceptions=False), app, mock_db

    def _post_webhook(self, payload: dict, client=None, mock_db=None):
        """Helper: POST a webhook payload, bypassing verify_gitlab_webhook."""
        if client is None:
            client, app, mock_db = self._get_client()
        with patch("app.api.webhook.verify_gitlab_webhook", new=AsyncMock(return_value=payload)):
            response = client.post(
                "/api/webhook/gitlab",
                json=payload,
                headers={"X-Gitlab-Token": "test-secret"},
            )
        return response

    def test_webhook_ignores_push_event(self):
        """Webhook should return ignored for non-note events (e.g. push)."""
        payload = {"object_kind": "push", "project": {"id": 1}}
        client, app, _ = self._get_client()
        response = self._post_webhook(payload, client=client)
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ignored")

    def test_webhook_ignores_system_note(self):
        """Webhook should ignore system-generated notes."""
        payload = {
            "object_kind": "note",
            "object_attributes": {
                "id": 1,
                "noteable_type": "Issue",
                "note": "closed",
                "system": True,
            },
            "issue": {"id": 100, "iid": 10},
            "project": {"id": 1},
            "user": {"id": 5, "username": "system"},
        }
        client, app, _ = self._get_client()
        response = self._post_webhook(payload, client=client)
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ignored")
        self.assertIn("system", data.get("reason", ""))

    def test_webhook_ignores_unsupported_noteable_type(self):
        """Webhook should ignore notes on unsupported noteable types (e.g. Snippet)."""
        payload = {
            "object_kind": "note",
            "object_attributes": {
                "id": 2,
                "noteable_type": "Snippet",
                "note": "@ai-bot generate something",
                "system": False,
            },
            "project": {"id": 1},
            "user": {},
        }
        client, app, _ = self._get_client()
        response = self._post_webhook(payload, client=client)
        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ignored")

    def test_webhook_dispatches_issue_comment(self):
        """Webhook dispatches note on Issue to _handle_issue_comment."""
        payload = {
            "object_kind": "note",
            "object_attributes": {
                "id": 3,
                "noteable_type": "Issue",
                "note": "@ai-bot generate fix the login bug",
                "system": False,
            },
            "issue": {"id": 100, "iid": 10},
            "project": {"id": 1},
            "user": {"id": 5, "username": "alice"},
            "merge_request": {},
        }
        client, app, _ = self._get_client()

        with patch(
            "app.api.webhook.verify_gitlab_webhook",
            new=AsyncMock(return_value=payload)
        ):
            with patch(
                "app.api.webhook._handle_issue_comment",
                new=AsyncMock(return_value={"status": "success", "task_id": 42}),
            ) as mock_handler:
                response = client.post(
                    "/api/webhook/gitlab",
                    json=payload,
                    headers={"X-Gitlab-Token": "test-secret"},
                )

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        mock_handler.assert_awaited_once()
        data = response.json()
        self.assertEqual(data["status"], "success")


# ---------------------------------------------------------------------------
# _handle_issue_comment logic
# ---------------------------------------------------------------------------

class HandleIssueCommentTests(unittest.IsolatedAsyncioTestCase):
    """Tests for _handle_issue_comment."""

    async def test_returns_ignored_when_no_ai_bot_command(self) -> None:
        """Should return ignored when comment has no @ai-bot command."""
        from app.api.webhook import _handle_issue_comment

        mock_db = AsyncMock()
        project = {"id": 1}
        issue = {"id": 100, "iid": 10}
        result = await _handle_issue_comment(
            db=mock_db,
            project=project,
            issue=issue,
            note_id=999,
            comment_body="Great work!",
        )

        self.assertEqual(result["status"], "ignored")
        self.assertIn("no @ai-bot command", result.get("reason", ""))

    async def test_raises_400_when_missing_required_fields(self) -> None:
        """Should raise 400 when project/issue fields are missing."""
        from fastapi import HTTPException
        from app.api.webhook import _handle_issue_comment

        mock_db = AsyncMock()
        project = {}  # Missing 'id'
        issue = {}    # Missing 'id' and 'iid'

        with self.assertRaises(HTTPException) as ctx:
            await _handle_issue_comment(
                db=mock_db,
                project=project,
                issue=issue,
                note_id=None,  # Missing note_id
                comment_body="@ai-bot generate fix the bug",
            )

        self.assertEqual(ctx.exception.status_code, 400)


# ---------------------------------------------------------------------------
# _handle_cancel_command
# ---------------------------------------------------------------------------

class HandleCancelCommandTests(unittest.IsolatedAsyncioTestCase):
    """Tests for _handle_cancel_command."""

    async def test_cancels_running_task(self) -> None:
        """Should cancel a running task and return success."""
        from app.api.webhook import _handle_cancel_command
        from app.models import TaskStatus

        running_task = MagicMock()
        running_task.id = 10
        running_task.status = TaskStatus.RUNNING

        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = running_task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=task_result)
        mock_db.commit = AsyncMock()

        result = await _handle_cancel_command(mock_db, project_id=1, issue_iid=5)

        self.assertEqual(result["status"], "success")
        self.assertEqual(running_task.status, TaskStatus.CANCELLED)
        mock_db.commit.assert_awaited_once()

    async def test_cancels_pending_tasks_when_no_running_task(self) -> None:
        """Should cancel pending tasks if no running task exists."""
        from app.api.webhook import _handle_cancel_command
        from app.models import TaskStatus

        pending_task1 = MagicMock()
        pending_task1.id = 20
        pending_task1.status = TaskStatus.PENDING

        pending_task2 = MagicMock()
        pending_task2.id = 21
        pending_task2.status = TaskStatus.QUEUED

        # First execute: no running task
        running_result = MagicMock()
        running_result.scalar_one_or_none.return_value = None

        # Second execute: pending tasks
        pending_result = MagicMock()
        pending_result.scalars.return_value.all.return_value = [pending_task1, pending_task2]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[running_result, pending_result])
        mock_db.commit = AsyncMock()

        result = await _handle_cancel_command(mock_db, project_id=1, issue_iid=6)

        self.assertEqual(result["status"], "success")
        self.assertIn("2", result["message"])
        self.assertEqual(pending_task1.status, TaskStatus.CANCELLED)
        self.assertEqual(pending_task2.status, TaskStatus.CANCELLED)

    async def test_returns_ignored_when_no_tasks_found(self) -> None:
        """Should return ignored when no running or pending tasks exist."""
        from app.api.webhook import _handle_cancel_command

        no_task_result = MagicMock()
        no_task_result.scalar_one_or_none.return_value = None

        no_pending_result = MagicMock()
        no_pending_result.scalars.return_value.all.return_value = []

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[no_task_result, no_pending_result])
        mock_db.commit = AsyncMock()

        result = await _handle_cancel_command(mock_db, project_id=1, issue_iid=7)

        self.assertEqual(result["status"], "ignored")


# ---------------------------------------------------------------------------
# _handle_generate_command — duplicate detection
# ---------------------------------------------------------------------------

class HandleGenerateCommandDuplicateTests(unittest.IsolatedAsyncioTestCase):
    """Tests for duplicate task prevention in _handle_generate_command."""

    async def test_returns_duplicate_when_task_already_exists_for_note(self) -> None:
        """Should return duplicate status when a task with the same note_id exists."""
        from app.api.webhook import _handle_generate_command
        from app.core.parser import BotCommand

        existing_task = MagicMock()
        existing_task.id = 5

        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = existing_task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=existing_result)

        command = BotCommand(command="generate", args="fix the bug", raw_mention="@ai-bot generate fix the bug")

        result = await _handle_generate_command(
            db=mock_db,
            project_id=1,
            issue_id=100,
            issue_iid=10,
            note_id=999,
            command=command,
        )

        self.assertEqual(result["status"], "duplicate")
        self.assertIn("already", result["message"].lower())


# ---------------------------------------------------------------------------
# _resolve_initiator_user_id
# ---------------------------------------------------------------------------

class ResolveInitiatorUserIdTests(unittest.IsolatedAsyncioTestCase):
    """Tests for _resolve_initiator_user_id helper."""

    async def test_returns_none_when_no_initiator(self) -> None:
        """Should return None when initiator is None."""
        from app.api.webhook import _resolve_initiator_user_id

        mock_db = MagicMock()
        result = await _resolve_initiator_user_id(mock_db, None)
        self.assertIsNone(result)

    async def test_returns_none_when_initiator_has_no_id(self) -> None:
        """Should return None when initiator dict has no 'id' key."""
        from app.api.webhook import _resolve_initiator_user_id

        mock_db = MagicMock()
        result = await _resolve_initiator_user_id(mock_db, {"username": "alice"})
        self.assertIsNone(result)

    async def test_returns_existing_user_id_when_user_found(self) -> None:
        """Should return the existing user's DB id when found by gitlab_user_id."""
        from app.api.webhook import _resolve_initiator_user_id

        existing_user = MagicMock()
        existing_user.id = 42

        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = existing_user

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=user_result)

        result = await _resolve_initiator_user_id(
            mock_db,
            {"id": 123, "username": "alice", "email": "alice@example.com"},
        )

        self.assertEqual(result, 42)

    async def test_creates_new_user_when_not_found(self) -> None:
        """Should create a new user record when gitlab_user_id is not in DB."""
        from app.api.webhook import _resolve_initiator_user_id

        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = None  # No existing user

        captured_users = []

        def capture_add(user):
            user.id = 99  # Simulate DB auto-assign
            captured_users.append(user)

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=user_result)
        mock_db.add = MagicMock(side_effect=capture_add)
        mock_db.flush = AsyncMock()

        result = await _resolve_initiator_user_id(
            mock_db,
            {"id": 456, "username": "bob", "email": "bob@example.com"},
        )

        self.assertEqual(len(captured_users), 1)
        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()
        self.assertEqual(result, 99)


if __name__ == "__main__":
    unittest.main()
