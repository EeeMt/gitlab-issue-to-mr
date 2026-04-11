#!/usr/bin/env python3
"""Additional unit tests for webhook.py — targeting uncovered lines.

Raises coverage from ~70 % to 85 %+ by exercising:
- _resolve_initiator_user_id edge case (line 120)
- verify_gitlab_webhook edge cases (lines 157-158, 174, 188)
- gitlab_webhook MR dispatch (line 247)
- _handle_issue_comment cancel/status/generate dispatch (lines 286-294)
- _handle_status_command full function (lines 362-404)
- _handle_generate_command additional paths (lines 435-496)
- _handle_mr_comment all paths (lines 545-672)
"""

import os
import sys
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _no_dup_db():
    """Mock DB where the first execute (duplicate check) returns nothing."""
    no_dup = MagicMock()
    no_dup.scalar_one_or_none.return_value = None

    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=no_dup)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    def _set_id(obj):
        obj.id = 1

    mock_db.refresh = AsyncMock(side_effect=_set_id)
    return mock_db


def _bot_cmd(args="fix the bug", **kw):
    from app.core.parser import BotCommand

    return BotCommand(
        command="generate",
        args=args,
        raw_mention=f"@ai-bot {args}",
        **kw,
    )


_SETTINGS = SimpleNamespace(default_target_branch="main")


# ── _resolve_initiator_user_id — no username edge case (line 120) ────────────

class ResolveInitiatorNoUsernameTests(unittest.IsolatedAsyncioTestCase):
    """Cover line 120 — auto-generated username when none provided."""

    async def test_generates_username_from_gitlab_id(self) -> None:
        """Should generate 'gitlab_user_{id}' when username is missing."""
        from app.api.webhook import _resolve_initiator_user_id

        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = None

        captured = []

        def capture(user):
            user.id = 77
            captured.append(user)

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=user_result)
        mock_db.add = MagicMock(side_effect=capture)
        mock_db.flush = AsyncMock()

        result = await _resolve_initiator_user_id(mock_db, {"id": 999})

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].username, "gitlab_user_999")
        self.assertEqual(result, 77)


# ── verify_gitlab_webhook — edge cases (lines 157-158, 174, 188) ────────────

class VerifyWebhookEdgeCaseTests(unittest.IsolatedAsyncioTestCase):
    """Cover verify_gitlab_webhook error / edge branches."""

    async def test_bad_json_raises_400(self) -> None:
        """Should raise 400 for unparseable JSON body (lines 157-158)."""
        from fastapi import HTTPException

        from app.api.webhook import verify_gitlab_webhook

        request = MagicMock()
        request.json = AsyncMock(side_effect=ValueError("bad json"))

        with self.assertRaises(HTTPException) as ctx:
            await verify_gitlab_webhook(request, MagicMock(), None)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Invalid JSON", ctx.exception.detail)

    async def test_missing_token_header_raises_401(self) -> None:
        """Should raise 401 when secret is configured but header absent (line 174)."""
        from fastapi import HTTPException

        from app.api.webhook import verify_gitlab_webhook

        payload = {"project": {"id": 1}, "object_kind": "note"}
        request = MagicMock()
        request.json = AsyncMock(return_value=payload)

        with (
            patch(
                "app.api.webhook.get_project_webhook_secret",
                AsyncMock(return_value="secret"),
            ),
            patch(
                "app.api.webhook.get_effective_settings",
                return_value=SimpleNamespace(gitlab_webhook_secret=None),
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await verify_gitlab_webhook(request, MagicMock(), None)

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("Missing", ctx.exception.detail)

    async def test_payload_with_object_attributes_succeeds(self) -> None:
        """Should log object_attributes keys when present (line 188)."""
        from app.api.webhook import verify_gitlab_webhook

        payload = {
            "project": {"id": 1},
            "object_kind": "note",
            "object_attributes": {"id": 10, "note": "hello"},
        }
        request = MagicMock()
        request.json = AsyncMock(return_value=payload)

        with (
            patch(
                "app.api.webhook.get_project_webhook_secret",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.api.webhook.get_effective_settings",
                return_value=SimpleNamespace(gitlab_webhook_secret=None),
            ),
        ):
            result = await verify_gitlab_webhook(request, MagicMock(), None)

        self.assertEqual(result, payload)


# ── gitlab_webhook — MR dispatch (line 247) ─────────────────────────────────

class WebhookMrDispatchTests(unittest.TestCase):
    """Cover line 247 — webhook dispatches MergeRequest notes."""

    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    def test_dispatches_merge_request_note(self) -> None:
        """Should dispatch MergeRequest note to _handle_mr_comment."""
        from fastapi.testclient import TestClient

        from app.database import get_db
        from app.main import app

        mock_db = MagicMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db

        payload = {
            "object_kind": "note",
            "object_attributes": {
                "id": 100,
                "noteable_type": "MergeRequest",
                "note": "@ai-bot fix the bug",
                "system": False,
            },
            "merge_request": {"iid": 5},
            "project": {"id": 1},
            "user": {"id": 5, "username": "alice"},
        }

        client = TestClient(app, raise_server_exceptions=False)

        with (
            patch(
                "app.api.webhook.verify_gitlab_webhook",
                new=AsyncMock(return_value=payload),
            ),
            patch(
                "app.api.webhook._handle_mr_comment",
                new=AsyncMock(return_value={"status": "success"}),
            ) as mock_mr,
        ):
            response = client.post(
                "/api/webhook/gitlab",
                json=payload,
                headers={"X-Gitlab-Token": "t"},
            )

        self.assertEqual(response.status_code, 200)
        mock_mr.assert_awaited_once()
        self.assertEqual(response.json()["status"], "success")


# ── _handle_issue_comment — dispatch branches (lines 286-294) ───────────────

class HandleIssueCommentDispatchTests(unittest.IsolatedAsyncioTestCase):
    """Cover the cancel / status / generate dispatch in _handle_issue_comment."""

    async def test_dispatches_cancel(self) -> None:
        """Should call _handle_cancel_command for '@ai-bot cancel' (line 287)."""
        from app.api.webhook import _handle_issue_comment

        mock_db = MagicMock()

        with patch(
            "app.api.webhook._handle_cancel_command",
            new=AsyncMock(return_value={"status": "success", "message": "Cancelled"}),
        ) as m:
            result = await _handle_issue_comment(
                db=mock_db,
                project={"id": 1},
                issue={"id": 100, "iid": 10},
                note_id=999,
                comment_body="@ai-bot cancel",
            )

        m.assert_awaited_once_with(mock_db, 1, 10)
        self.assertEqual(result["status"], "success")

    async def test_dispatches_status(self) -> None:
        """Should call _handle_status_command for '@ai-bot status' (line 291)."""
        from app.api.webhook import _handle_issue_comment

        mock_db = MagicMock()

        with patch(
            "app.api.webhook._handle_status_command",
            new=AsyncMock(return_value={"status": "success"}),
        ) as m:
            result = await _handle_issue_comment(
                db=mock_db,
                project={"id": 1},
                issue={"id": 100, "iid": 10},
                note_id=999,
                comment_body="@ai-bot status",
            )

        m.assert_awaited_once_with(mock_db, 1, 10)
        self.assertEqual(result["status"], "success")

    async def test_dispatches_generate(self) -> None:
        """Should call _handle_generate_command for normal prompts (lines 294-296)."""
        from app.api.webhook import _handle_issue_comment

        mock_db = MagicMock()
        initiator = {"id": 5, "username": "alice"}

        with patch(
            "app.api.webhook._handle_generate_command",
            new=AsyncMock(return_value={"status": "success", "task_id": 1}),
        ) as m:
            result = await _handle_issue_comment(
                db=mock_db,
                project={"id": 1},
                issue={"id": 100, "iid": 10},
                note_id=999,
                comment_body="@ai-bot fix the login bug",
                initiator=initiator,
            )

        m.assert_awaited_once()
        self.assertEqual(result["status"], "success")


# ── _handle_status_command (lines 362-404) ───────────────────────────────────

class HandleStatusCommandTests(unittest.IsolatedAsyncioTestCase):
    """Cover all paths through _handle_status_command."""

    async def test_no_task_returns_ignored(self) -> None:
        """Should return ignored when no task exists (lines 370-374)."""
        from app.api.webhook import _handle_status_command

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)

        result = await _handle_status_command(mock_db, project_id=1, issue_iid=10)

        self.assertEqual(result["status"], "ignored")
        self.assertIn("No tasks", result["message"])

    async def test_running_task_with_mr_url(self) -> None:
        """Should return status and post GitLab note (lines 376-400)."""
        from app.api.webhook import _handle_status_command
        from app.models import TaskStatus

        task = MagicMock()
        task.id = 42
        task.status = TaskStatus.RUNNING
        task.created_at = datetime(2024, 1, 1, tzinfo=UTC)
        task.branch_name = "codify/issue-10"
        task.merge_request_url = "https://gitlab.com/mr/1"
        task.error_message = None

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)

        mock_gl = MagicMock()
        mock_gl.create_note = MagicMock()

        with patch("app.api.webhook.get_gitlab_client", return_value=mock_gl):
            result = await _handle_status_command(mock_db, project_id=1, issue_iid=10)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task"]["id"], 42)
        self.assertEqual(result["task"]["status"], "running")
        self.assertEqual(result["task"]["mr_url"], "https://gitlab.com/mr/1")
        mock_gl.create_note.assert_called_once()
        # MR URL should appear in the posted note
        note_text = mock_gl.create_note.call_args[0][2]
        self.assertIn("MR:", note_text)

    async def test_failed_task_includes_error(self) -> None:
        """Should include error in response and GitLab note (lines 388-389, 397-398)."""
        from app.api.webhook import _handle_status_command
        from app.models import TaskStatus

        task = MagicMock()
        task.id = 43
        task.status = TaskStatus.FAILED
        task.created_at = datetime(2024, 1, 1, tzinfo=UTC)
        task.branch_name = "codify/issue-11"
        task.merge_request_url = None
        task.error_message = "Docker container OOM killed"

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)

        mock_gl = MagicMock()
        mock_gl.create_note = MagicMock()

        with patch("app.api.webhook.get_gitlab_client", return_value=mock_gl):
            result = await _handle_status_command(mock_db, project_id=1, issue_iid=11)

        self.assertEqual(result["task"]["error"], "Docker container OOM killed")
        note_text = mock_gl.create_note.call_args[0][2]
        self.assertIn("Error:", note_text)

    async def test_gitlab_note_failure_still_returns_status(self) -> None:
        """Should return status even when GitLab note posting fails (lines 401-402)."""
        from app.api.webhook import _handle_status_command
        from app.models import TaskStatus

        task = MagicMock()
        task.id = 44
        task.status = TaskStatus.COMPLETED
        task.created_at = datetime(2024, 1, 1, tzinfo=UTC)
        task.branch_name = "codify/issue-12"
        task.merge_request_url = "https://gitlab.com/mr/2"
        task.error_message = None

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)

        mock_gl = MagicMock()
        mock_gl.create_note = MagicMock(side_effect=Exception("API down"))

        with patch("app.api.webhook.get_gitlab_client", return_value=mock_gl):
            result = await _handle_status_command(mock_db, project_id=1, issue_iid=12)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task"]["id"], 44)


# ── _handle_generate_command — additional paths (lines 435-496) ──────────────

class HandleGenerateCommandPathTests(unittest.IsolatedAsyncioTestCase):
    """Cover issue-fetch failure, generic prompt, slot capacity, branch logic."""

    async def test_issue_fetch_exception_falls_back(self) -> None:
        """Should use original prompt when get_issue raises (lines 435-436)."""
        from app.api.webhook import _handle_generate_command

        mock_db = _no_dup_db()
        mock_gl = MagicMock()
        mock_gl.get_issue = MagicMock(side_effect=Exception("timeout"))
        mock_gl.get_project = MagicMock(
            return_value=SimpleNamespace(default_branch="main")
        )

        with (
            patch("app.api.webhook.get_gitlab_client", return_value=mock_gl),
            patch("app.api.webhook.get_effective_settings", return_value=_SETTINGS),
            patch(
                "app.api.webhook._resolve_initiator_user_id",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = await _handle_generate_command(
                db=mock_db,
                project_id=1,
                issue_id=100,
                issue_iid=10,
                note_id=999,
                command=_bot_cmd("fix the bug"),
            )

        self.assertEqual(result["status"], "success")
        added_task = mock_db.add.call_args[0][0]
        self.assertEqual(added_task.user_prompt, "fix the bug")

    async def test_generic_prompt_builds_enhanced(self) -> None:
        """Should call build_enhanced_prompt for generic prompts (lines 443-444)."""
        from app.api.webhook import _handle_generate_command

        mock_db = _no_dup_db()
        mock_gl = MagicMock()
        mock_gl.get_issue = MagicMock(
            return_value={"title": "Fix login", "description": "Login page broken"}
        )
        mock_gl.get_project = MagicMock(
            return_value=SimpleNamespace(default_branch="main")
        )

        with (
            patch("app.api.webhook.get_gitlab_client", return_value=mock_gl),
            patch("app.api.webhook.get_effective_settings", return_value=_SETTINGS),
            patch(
                "app.api.webhook._resolve_initiator_user_id",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.api.webhook.build_enhanced_prompt",
                return_value="Enhanced: Fix login",
            ) as mock_build,
        ):
            result = await _handle_generate_command(
                db=mock_db,
                project_id=1,
                issue_id=100,
                issue_iid=10,
                note_id=999,
                command=_bot_cmd("start"),  # "start" is a generic prompt
            )

        mock_build.assert_called_once_with("start", "Fix login", "Login page broken")
        self.assertEqual(result["status"], "success")
        added_task = mock_db.add.call_args[0][0]
        self.assertEqual(added_task.user_prompt, "Enhanced: Fix login")

    async def test_no_issue_details_uses_original(self) -> None:
        """Should use original prompt when get_issue returns None (line 456)."""
        from app.api.webhook import _handle_generate_command

        mock_db = _no_dup_db()
        mock_gl = MagicMock()
        mock_gl.get_issue = MagicMock(return_value=None)
        mock_gl.get_project = MagicMock(
            return_value=SimpleNamespace(default_branch="main")
        )

        with (
            patch("app.api.webhook.get_gitlab_client", return_value=mock_gl),
            patch("app.api.webhook.get_effective_settings", return_value=_SETTINGS),
            patch(
                "app.api.webhook._resolve_initiator_user_id",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = await _handle_generate_command(
                db=mock_db,
                project_id=1,
                issue_id=100,
                issue_iid=10,
                note_id=999,
                command=_bot_cmd("fix the bug"),
            )

        self.assertEqual(result["status"], "success")

    async def test_slot_capacity_rejection(self) -> None:
        """Should return rejected when slot is at full capacity (lines 465-474)."""
        from app.api.webhook import _handle_generate_command

        mock_db = _no_dup_db()
        mock_gl = MagicMock()
        mock_gl.get_issue = MagicMock(
            return_value={"title": "Fix", "description": "Bug"}
        )
        mock_gl.post_issue_comment = MagicMock()

        slot_info = MagicMock()
        slot_info.is_full = True
        slot_info.enforce = True

        scheduled = datetime(2024, 6, 1, 14, 0, tzinfo=UTC)

        with (
            patch("app.api.webhook.get_gitlab_client", return_value=mock_gl),
            patch("app.api.webhook.get_effective_settings", return_value=_SETTINGS),
            patch(
                "app.api.webhook._resolve_initiator_user_id",
                new=AsyncMock(return_value=None),
            ),
            patch("app.api.webhook.resolve_scheduled_at", return_value=scheduled),
            patch(
                "app.core.slot_capacity.check_slot_capacity",
                new=AsyncMock(return_value=slot_info),
            ),
            patch(
                "app.core.slot_capacity.format_slot_rejection_message",
                return_value="⚠️ Slot full",
            ),
        ):
            result = await _handle_generate_command(
                db=mock_db,
                project_id=1,
                issue_id=100,
                issue_iid=10,
                note_id=999,
                command=_bot_cmd("fix bug"),
            )

        self.assertEqual(result["status"], "rejected")
        self.assertIn("full capacity", result["message"])
        mock_gl.post_issue_comment.assert_called_once()

    async def test_slot_capacity_rejection_gitlab_failure(self) -> None:
        """Should still reject even if posting rejection comment fails (line 472-473)."""
        from app.api.webhook import _handle_generate_command

        mock_db = _no_dup_db()
        mock_gl = MagicMock()
        mock_gl.get_issue = MagicMock(
            return_value={"title": "Fix", "description": "Bug"}
        )
        mock_gl.post_issue_comment = MagicMock(side_effect=Exception("API error"))

        slot_info = MagicMock()
        slot_info.is_full = True
        slot_info.enforce = True

        scheduled = datetime(2024, 6, 1, 14, 0, tzinfo=UTC)

        with (
            patch("app.api.webhook.get_gitlab_client", return_value=mock_gl),
            patch("app.api.webhook.get_effective_settings", return_value=_SETTINGS),
            patch(
                "app.api.webhook._resolve_initiator_user_id",
                new=AsyncMock(return_value=None),
            ),
            patch("app.api.webhook.resolve_scheduled_at", return_value=scheduled),
            patch(
                "app.core.slot_capacity.check_slot_capacity",
                new=AsyncMock(return_value=slot_info),
            ),
            patch(
                "app.core.slot_capacity.format_slot_rejection_message",
                return_value="⚠️ Slot full",
            ),
        ):
            result = await _handle_generate_command(
                db=mock_db,
                project_id=1,
                issue_id=100,
                issue_iid=10,
                note_id=999,
                command=_bot_cmd("fix bug"),
            )

        self.assertEqual(result["status"], "rejected")

    async def test_command_target_branch_used(self) -> None:
        """Should use command.target_branch when set (line 483)."""
        from app.api.webhook import _handle_generate_command

        mock_db = _no_dup_db()
        mock_gl = MagicMock()
        mock_gl.get_issue = MagicMock(
            return_value={"title": "Fix", "description": "Bug"}
        )
        # get_project should NOT be called when target_branch is provided

        with (
            patch("app.api.webhook.get_gitlab_client", return_value=mock_gl),
            patch("app.api.webhook.get_effective_settings", return_value=_SETTINGS),
            patch(
                "app.api.webhook._resolve_initiator_user_id",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = await _handle_generate_command(
                db=mock_db,
                project_id=1,
                issue_id=100,
                issue_iid=10,
                note_id=999,
                command=_bot_cmd("fix bug", target_branch="develop"),
            )

        self.assertEqual(result["status"], "success")
        added_task = mock_db.add.call_args[0][0]
        self.assertEqual(added_task.target_branch, "develop")

    async def test_fallback_branch_on_project_fetch_error(self) -> None:
        """Should fall back to default_target_branch when get_project fails (lines 491-496)."""
        from app.api.webhook import _handle_generate_command

        mock_db = _no_dup_db()
        mock_gl = MagicMock()
        mock_gl.get_issue = MagicMock(
            return_value={"title": "Fix", "description": "Bug"}
        )
        mock_gl.get_project = MagicMock(side_effect=Exception("Network error"))

        with (
            patch("app.api.webhook.get_gitlab_client", return_value=mock_gl),
            patch("app.api.webhook.get_effective_settings", return_value=_SETTINGS),
            patch(
                "app.api.webhook._resolve_initiator_user_id",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = await _handle_generate_command(
                db=mock_db,
                project_id=1,
                issue_id=100,
                issue_iid=10,
                note_id=999,
                command=_bot_cmd("fix bug"),
            )

        self.assertEqual(result["status"], "success")
        added_task = mock_db.add.call_args[0][0]
        self.assertEqual(added_task.target_branch, "main")


# ── _handle_mr_comment — all paths (lines 545-672) ──────────────────────────

class HandleMrCommentTests(unittest.IsolatedAsyncioTestCase):
    """Cover every path through _handle_mr_comment."""

    # -- no command (lines 545-546) --

    async def test_no_command_returns_ignored(self) -> None:
        """Should return ignored when no @ai-bot command in MR comment."""
        from app.api.webhook import _handle_mr_comment

        result = await _handle_mr_comment(
            db=MagicMock(),
            project={"id": 1},
            merge_request={"iid": 5},
            note_id=999,
            comment_body="Just a regular comment",
        )

        self.assertEqual(result["status"], "ignored")
        self.assertIn("no @ai-bot command", result["reason"])

    # -- cancel with running task (lines 551-563) --

    async def test_cancel_with_running_task(self) -> None:
        """Should delegate to _handle_cancel_command via MR."""
        from app.api.webhook import _handle_mr_comment
        from app.models import TaskStatus

        running_task = MagicMock()
        running_task.id = 10
        running_task.status = TaskStatus.RUNNING
        running_task.issue_iid = 15

        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = running_task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=task_result)

        with patch(
            "app.api.webhook._handle_cancel_command",
            new=AsyncMock(return_value={"status": "success"}),
        ) as m:
            result = await _handle_mr_comment(
                db=mock_db,
                project={"id": 1},
                merge_request={"iid": 5},
                note_id=999,
                comment_body="@ai-bot cancel",
            )

        m.assert_awaited_once_with(mock_db, 1, 15)
        self.assertEqual(result["status"], "success")

    # -- cancel with no running task (line 564) --

    async def test_cancel_no_running_task(self) -> None:
        """Should return ignored when no running task for MR cancel."""
        from app.api.webhook import _handle_mr_comment

        no_task = MagicMock()
        no_task.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=no_task)

        result = await _handle_mr_comment(
            db=mock_db,
            project={"id": 1},
            merge_request={"iid": 5},
            note_id=999,
            comment_body="@ai-bot cancel",
        )

        self.assertEqual(result["status"], "ignored")
        self.assertIn("no running task", result["reason"])

    # -- status with task found (lines 567-578) --

    async def test_status_with_task(self) -> None:
        """Should delegate to _handle_status_command via MR."""
        from app.api.webhook import _handle_mr_comment
        from app.models import TaskStatus

        task = MagicMock()
        task.id = 20
        task.issue_iid = 15
        task.status = TaskStatus.COMPLETED

        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=task_result)

        with patch(
            "app.api.webhook._handle_status_command",
            new=AsyncMock(return_value={"status": "success"}),
        ) as m:
            result = await _handle_mr_comment(
                db=mock_db,
                project={"id": 1},
                merge_request={"iid": 5},
                note_id=999,
                comment_body="@ai-bot status",
            )

        m.assert_awaited_once_with(mock_db, 1, 15)
        self.assertEqual(result["status"], "success")

    # -- status with no task (line 579) --

    async def test_status_no_task(self) -> None:
        """Should return ignored when no task exists for MR status."""
        from app.api.webhook import _handle_mr_comment

        no_task = MagicMock()
        no_task.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=no_task)

        result = await _handle_mr_comment(
            db=mock_db,
            project={"id": 1},
            merge_request={"iid": 5},
            note_id=999,
            comment_body="@ai-bot status",
        )

        self.assertEqual(result["status"], "ignored")
        self.assertIn("no task found", result["reason"])

    # -- missing required fields (lines 588-589) --

    async def test_missing_fields_raises_400(self) -> None:
        """Should raise 400 when project/MR/note fields are missing."""
        from fastapi import HTTPException

        from app.api.webhook import _handle_mr_comment

        with self.assertRaises(HTTPException) as ctx:
            await _handle_mr_comment(
                db=MagicMock(),
                project={},             # missing id
                merge_request={},       # missing iid
                note_id=None,           # missing
                comment_body="@ai-bot fix the bug",
            )

        self.assertEqual(ctx.exception.status_code, 400)

    # -- duplicate note_id (lines 601-602) --

    async def test_duplicate_returns_duplicate(self) -> None:
        """Should return duplicate when note_id task already exists."""
        from app.api.webhook import _handle_mr_comment

        existing_task = MagicMock()
        existing_task.id = 30

        dup_result = MagicMock()
        dup_result.scalar_one_or_none.return_value = existing_task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=dup_result)

        result = await _handle_mr_comment(
            db=mock_db,
            project={"id": 1},
            merge_request={"iid": 5},
            note_id=999,
            comment_body="@ai-bot fix the bug",
        )

        self.assertEqual(result["status"], "duplicate")
        self.assertIn("already", result["message"].lower())

    # -- parent task still running (line 625) --

    async def test_parent_task_still_running(self) -> None:
        """Should return ignored when parent task is still running."""
        from app.api.webhook import _handle_mr_comment
        from app.models import TaskStatus

        # Query 1: duplicate check → no dup
        no_dup = MagicMock()
        no_dup.scalar_one_or_none.return_value = None

        # Query 2: completed/failed parent → none
        no_completed = MagicMock()
        no_completed.scalar_one_or_none.return_value = None

        # Query 3: any parent → running task
        running_task = MagicMock()
        running_task.id = 40
        running_task.status = TaskStatus.RUNNING

        still_running = MagicMock()
        still_running.scalar_one_or_none.return_value = running_task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[no_dup, no_completed, still_running]
        )

        result = await _handle_mr_comment(
            db=mock_db,
            project={"id": 1},
            merge_request={"iid": 5},
            note_id=999,
            comment_body="@ai-bot fix the bug",
        )

        self.assertEqual(result["status"], "ignored")
        self.assertIn("still", result["reason"])

    # -- no parent task at all (lines 630-633) --

    async def test_no_parent_task_at_all(self) -> None:
        """Should return ignored when no parent task found for MR."""
        from app.api.webhook import _handle_mr_comment

        no_task = MagicMock()
        no_task.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        # All three queries return nothing
        mock_db.execute = AsyncMock(return_value=no_task)

        result = await _handle_mr_comment(
            db=mock_db,
            project={"id": 1},
            merge_request={"iid": 5},
            note_id=999,
            comment_body="@ai-bot fix the bug",
        )

        self.assertEqual(result["status"], "ignored")
        self.assertIn("No completed task", result["reason"])

    # -- MR details not found (line 640) --

    async def test_mr_details_not_found(self) -> None:
        """Should return error when GitLab cannot find MR details."""
        from app.api.webhook import _handle_mr_comment
        from app.models import TaskStatus

        no_dup = MagicMock()
        no_dup.scalar_one_or_none.return_value = None

        parent_task = MagicMock()
        parent_task.id = 50
        parent_task.status = TaskStatus.COMPLETED

        parent_result = MagicMock()
        parent_result.scalar_one_or_none.return_value = parent_task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[no_dup, parent_result])

        mock_gl = MagicMock()
        mock_gl.get_mr_by_iid = MagicMock(return_value=None)

        with patch("app.api.webhook.get_gitlab_client", return_value=mock_gl):
            result = await _handle_mr_comment(
                db=mock_db,
                project={"id": 1},
                merge_request={"iid": 5},
                note_id=999,
                comment_body="@ai-bot fix the bug",
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("MR details", result["message"])

    # -- MR not open (line 645) --

    async def test_mr_not_open(self) -> None:
        """Should return ignored when MR is closed or merged."""
        from app.api.webhook import _handle_mr_comment
        from app.models import TaskStatus

        no_dup = MagicMock()
        no_dup.scalar_one_or_none.return_value = None

        parent_task = MagicMock()
        parent_task.id = 50
        parent_task.status = TaskStatus.COMPLETED

        parent_result = MagicMock()
        parent_result.scalar_one_or_none.return_value = parent_task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[no_dup, parent_result])

        mock_gl = MagicMock()
        mock_gl.get_mr_by_iid = MagicMock(return_value={"state": "merged"})

        with patch("app.api.webhook.get_gitlab_client", return_value=mock_gl):
            result = await _handle_mr_comment(
                db=mock_db,
                project={"id": 1},
                merge_request={"iid": 5},
                note_id=999,
                comment_body="@ai-bot fix the bug",
            )

        self.assertEqual(result["status"], "ignored")
        self.assertIn("not open", result["reason"])

    # -- generic prompt on MR — task creation (line 652) --

    async def test_mr_generic_prompt_creates_task(self) -> None:
        """Should build MR-specific prompt for generic commands and create task."""
        from app.api.webhook import _handle_mr_comment
        from app.models import TaskStatus

        no_dup = MagicMock()
        no_dup.scalar_one_or_none.return_value = None

        parent_task = MagicMock()
        parent_task.id = 50
        parent_task.status = TaskStatus.COMPLETED
        parent_task.issue_id = 100
        parent_task.issue_iid = 10
        parent_task.branch_name = "codify/issue-10"
        parent_task.target_branch = "main"

        parent_result = MagicMock()
        parent_result.scalar_one_or_none.return_value = parent_task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[no_dup, parent_result])
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        def set_id(obj):
            obj.id = 60

        mock_db.refresh = AsyncMock(side_effect=set_id)

        mock_gl = MagicMock()
        mock_gl.get_mr_by_iid = MagicMock(
            return_value={"state": "opened", "title": "Fix login bug"}
        )
        mock_gl.create_mr_note = MagicMock()

        with (
            patch("app.api.webhook.get_gitlab_client", return_value=mock_gl),
            patch(
                "app.api.webhook._resolve_initiator_user_id",
                new=AsyncMock(return_value=None),
            ),
            patch("app.api.webhook.resolve_scheduled_at", return_value=None),
        ):
            result = await _handle_mr_comment(
                db=mock_db,
                project={"id": 1},
                merge_request={"iid": 5},
                note_id=999,
                comment_body="@ai-bot start",  # "start" is generic
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_id"], 60)

        added_task = mock_db.add.call_args[0][0]
        self.assertIn("继续修改", added_task.user_prompt)
        self.assertEqual(added_task.branch_name, "codify/issue-10")
        self.assertEqual(added_task.merge_request_iid, 5)

    # -- explicit prompt on MR (line 654) --

    async def test_mr_explicit_prompt_creates_task(self) -> None:
        """Should build MR-specific prompt with user supplement for explicit commands."""
        from app.api.webhook import _handle_mr_comment
        from app.models import TaskStatus

        no_dup = MagicMock()
        no_dup.scalar_one_or_none.return_value = None

        parent_task = MagicMock()
        parent_task.id = 50
        parent_task.status = TaskStatus.COMPLETED
        parent_task.issue_id = 100
        parent_task.issue_iid = 10
        parent_task.branch_name = "codify/issue-10"
        parent_task.target_branch = "main"

        parent_result = MagicMock()
        parent_result.scalar_one_or_none.return_value = parent_task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[no_dup, parent_result])
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        def set_id(obj):
            obj.id = 61

        mock_db.refresh = AsyncMock(side_effect=set_id)

        mock_gl = MagicMock()
        mock_gl.get_mr_by_iid = MagicMock(
            return_value={"state": "opened", "title": "Fix login bug"}
        )
        mock_gl.create_mr_note = MagicMock()

        with (
            patch("app.api.webhook.get_gitlab_client", return_value=mock_gl),
            patch(
                "app.api.webhook._resolve_initiator_user_id",
                new=AsyncMock(return_value=None),
            ),
            patch("app.api.webhook.resolve_scheduled_at", return_value=None),
        ):
            result = await _handle_mr_comment(
                db=mock_db,
                project={"id": 1},
                merge_request={"iid": 5},
                note_id=1000,
                comment_body="@ai-bot add error handling to the login form",
            )

        self.assertEqual(result["status"], "success")
        added_task = mock_db.add.call_args[0][0]
        self.assertIn("用户补充要求", added_task.user_prompt)

    # -- MR slot capacity rejection (lines 663-672) --

    async def test_mr_slot_capacity_rejection(self) -> None:
        """Should return rejected when MR scheduled task hits capacity."""
        from app.api.webhook import _handle_mr_comment
        from app.models import TaskStatus

        no_dup = MagicMock()
        no_dup.scalar_one_or_none.return_value = None

        parent_task = MagicMock()
        parent_task.id = 50
        parent_task.status = TaskStatus.COMPLETED
        parent_task.issue_id = 100
        parent_task.issue_iid = 10
        parent_task.branch_name = "codify/issue-10"
        parent_task.target_branch = "main"

        parent_result = MagicMock()
        parent_result.scalar_one_or_none.return_value = parent_task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[no_dup, parent_result])

        mock_gl = MagicMock()
        mock_gl.get_mr_by_iid = MagicMock(
            return_value={"state": "opened", "title": "Fix login bug"}
        )
        mock_gl.create_mr_note = MagicMock()

        slot_info = MagicMock()
        slot_info.is_full = True
        slot_info.enforce = True

        scheduled = datetime(2024, 6, 1, 14, 0, tzinfo=UTC)

        with (
            patch("app.api.webhook.get_gitlab_client", return_value=mock_gl),
            patch(
                "app.api.webhook._resolve_initiator_user_id",
                new=AsyncMock(return_value=None),
            ),
            patch("app.api.webhook.resolve_scheduled_at", return_value=scheduled),
            patch(
                "app.core.slot_capacity.check_slot_capacity",
                new=AsyncMock(return_value=slot_info),
            ),
            patch(
                "app.core.slot_capacity.format_slot_rejection_message",
                return_value="⚠️ Slot full",
            ),
        ):
            result = await _handle_mr_comment(
                db=mock_db,
                project={"id": 1},
                merge_request={"iid": 5},
                note_id=999,
                comment_body="@ai-bot fix the bug",
            )

        self.assertEqual(result["status"], "rejected")
        self.assertIn("full capacity", result["message"])
        mock_gl.create_mr_note.assert_called_once()

    # -- MR slot capacity with notification failure (lines 670-671) --

    async def test_mr_slot_rejection_notification_failure(self) -> None:
        """Should still reject even if posting MR note fails."""
        from app.api.webhook import _handle_mr_comment
        from app.models import TaskStatus

        no_dup = MagicMock()
        no_dup.scalar_one_or_none.return_value = None

        parent_task = MagicMock()
        parent_task.id = 50
        parent_task.status = TaskStatus.COMPLETED
        parent_task.issue_id = 100
        parent_task.issue_iid = 10
        parent_task.branch_name = "codify/issue-10"
        parent_task.target_branch = "main"

        parent_result = MagicMock()
        parent_result.scalar_one_or_none.return_value = parent_task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[no_dup, parent_result])

        mock_gl = MagicMock()
        mock_gl.get_mr_by_iid = MagicMock(
            return_value={"state": "opened", "title": "Fix login bug"}
        )
        mock_gl.create_mr_note = MagicMock(side_effect=Exception("API down"))

        slot_info = MagicMock()
        slot_info.is_full = True
        slot_info.enforce = True

        scheduled = datetime(2024, 6, 1, 14, 0, tzinfo=UTC)

        with (
            patch("app.api.webhook.get_gitlab_client", return_value=mock_gl),
            patch(
                "app.api.webhook._resolve_initiator_user_id",
                new=AsyncMock(return_value=None),
            ),
            patch("app.api.webhook.resolve_scheduled_at", return_value=scheduled),
            patch(
                "app.core.slot_capacity.check_slot_capacity",
                new=AsyncMock(return_value=slot_info),
            ),
            patch(
                "app.core.slot_capacity.format_slot_rejection_message",
                return_value="⚠️ Slot full",
            ),
        ):
            result = await _handle_mr_comment(
                db=mock_db,
                project={"id": 1},
                merge_request={"iid": 5},
                note_id=999,
                comment_body="@ai-bot fix the bug",
            )

        self.assertEqual(result["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
