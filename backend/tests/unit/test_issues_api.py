#!/usr/bin/env python3
"""Unit tests for Issue CRUD API endpoints.

Tests cover:
- create_issue success
- list_issues default pagination
- get_issue detail with tasks
- update_issue with status validation
- close_issue success
- delete_issue with active tasks (409)
- delete_issue success
"""

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_issue(
    id=1,
    title="Test issue",
    description="A description",
    project_id=10,
    status="open",
    branch_name="codify/issue-1",
    base_branch=None,
    target_branch=None,
    merge_request_iid=None,
    merge_request_url=None,
    claude_session_id=None,
    session_storage_path="/var/codify/sessions/1/claude",
    initiator_user_id=1,
    initiator_username="testuser",
    created_at=None,
    updated_at=None,
    tasks=None,
):
    """Build a mock Issue ORM object."""
    issue = MagicMock()
    issue.id = id
    issue.title = title
    issue.description = description
    issue.project_id = project_id
    issue.status = status
    issue.branch_name = branch_name
    issue.base_branch = base_branch
    issue.target_branch = target_branch
    issue.merge_request_iid = merge_request_iid
    issue.merge_request_url = merge_request_url
    issue.claude_session_id = claude_session_id
    issue.session_storage_path = session_storage_path
    issue.initiator_user_id = initiator_user_id
    issue.initiator_username = initiator_username
    issue.created_at = created_at or datetime(2025, 1, 1, 12, 0, 0)
    issue.updated_at = updated_at or datetime(2025, 1, 1, 12, 0, 0)
    issue.tasks = tasks or []
    return issue


def _make_task(
    id=100,
    user_prompt="Fix the bug",
    status=None,
    is_retry=False,
    retry_source_task_id=None,
    container_id=None,
    commit_sha=None,
    error_message=None,
    additions=0,
    deletions=0,
    total_changes=0,
    input_tokens=None,
    output_tokens=None,
    model_name=None,
    commit_message=None,
    created_at=None,
    updated_at=None,
    started_at=None,
    completed_at=None,
):
    """Build a mock Task ORM object."""
    from app.models import TaskStatus

    task = MagicMock()
    task.id = id
    task.user_prompt = user_prompt
    task.status = status or TaskStatus.COMPLETED
    task.is_retry = is_retry
    task.retry_source_task_id = retry_source_task_id
    task.container_id = container_id
    task.commit_sha = commit_sha
    task.error_message = error_message
    task.additions = additions
    task.deletions = deletions
    task.total_changes = total_changes
    task.input_tokens = input_tokens
    task.output_tokens = output_tokens
    task.model_name = model_name
    task.commit_message = commit_message
    task.created_at = created_at or datetime(2025, 1, 1, 13, 0, 0)
    task.updated_at = updated_at or datetime(2025, 1, 1, 13, 0, 0)
    task.started_at = started_at
    task.completed_at = completed_at
    return task


# ---------------------------------------------------------------------------
# Create issue
# ---------------------------------------------------------------------------


class CreateIssueTests(unittest.IsolatedAsyncioTestCase):
    """Tests for POST /api/issues."""

    async def test_create_issue_success(self):
        """Should create an issue and return serialized data."""
        from app.api.issues import create_issue, CreateIssueRequest

        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        captured_issues = []

        def capture_add(obj):
            obj.id = 42
            obj.created_at = datetime(2025, 1, 1, 12, 0, 0)
            obj.updated_at = datetime(2025, 1, 1, 12, 0, 0)
            captured_issues.append(obj)

        mock_db.add = MagicMock(side_effect=capture_add)

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "alice"

        body = CreateIssueRequest(
            title="Implement feature X",
            description="Add feature X to the system",
            project_id=10,
            base_branch="main",
        )

        with patch("app.api.issues.get_effective_settings") as mock_settings:
            mock_settings.return_value.session_storage_root = "/var/codify/sessions"
            mock_settings.return_value.worker_workspace_host_path = "/opt/codify-workspaces"
            result = await create_issue(body=body, db=mock_db, current_user=mock_user)

        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()
        mock_db.commit.assert_awaited_once()

        created = captured_issues[0]
        self.assertEqual(created.title, "Implement feature X")
        self.assertEqual(created.project_id, 10)
        self.assertEqual(created.initiator_user_id, 1)
        self.assertEqual(created.initiator_username, "alice")
        self.assertEqual(created.branch_name, "codify/issue-42")
        self.assertEqual(
            created.session_storage_path,
            "/opt/codify-workspaces/project-10/issue-42/claude",
        )

    async def test_create_issue_uses_legacy_session_path_when_workspace_disabled(self):
        """Should keep legacy session path when persistent workspace is disabled."""
        from app.api.issues import create_issue, CreateIssueRequest

        mock_db = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        captured_issues = []

        def capture_add(obj):
            obj.id = 42
            obj.created_at = datetime(2025, 1, 1, 12, 0, 0)
            obj.updated_at = datetime(2025, 1, 1, 12, 0, 0)
            captured_issues.append(obj)

        mock_db.add = MagicMock(side_effect=capture_add)

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "alice"

        body = CreateIssueRequest(
            title="Implement feature X",
            description="Add feature X to the system",
            project_id=10,
            base_branch="main",
        )

        with patch("app.api.issues.get_effective_settings") as mock_settings:
            mock_settings.return_value.session_storage_root = "/var/codify/sessions"
            mock_settings.return_value.worker_workspace_host_path = ""
            await create_issue(body=body, db=mock_db, current_user=mock_user)

        created = captured_issues[0]
        self.assertEqual(created.session_storage_path, "/var/codify/sessions/42/claude")

    async def test_create_issue_sets_open_status(self):
        """Should default new issue status to OPEN."""
        from app.api.issues import create_issue, CreateIssueRequest
        from app.models import IssueStatus

        mock_db = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        captured = []

        def capture_add(obj):
            obj.id = 1
            obj.created_at = datetime(2025, 1, 1, 12, 0, 0)
            obj.updated_at = datetime(2025, 1, 1, 12, 0, 0)
            captured.append(obj)

        mock_db.add = MagicMock(side_effect=capture_add)
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "bob"

        body = CreateIssueRequest(title="Test", project_id=5)

        with patch("app.api.issues.get_effective_settings") as mock_settings:
            mock_settings.return_value.session_storage_root = "/tmp/sessions"
            await create_issue(body=body, db=mock_db, current_user=mock_user)

        self.assertEqual(captured[0].status, IssueStatus.OPEN.value)


# ---------------------------------------------------------------------------
# List issues
# ---------------------------------------------------------------------------


class ListIssuesTests(unittest.IsolatedAsyncioTestCase):
    """Tests for GET /api/issues."""

    async def test_list_issues_default(self):
        """Should return paginated list of issues with task_count."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        issue = _make_issue(id=1, title="Issue 1")

        # Mock for the main query returning (Issue, task_count, additions, deletions, total_changes, input_tokens, output_tokens) rows
        row = MagicMock()
        row.__getitem__ = lambda self, idx: [issue, 3, 100, 20, 120, 5000, 3000][idx]
        main_result = MagicMock()
        main_result.all.return_value = [row]

        # Mock for count query
        count_result = MagicMock()
        count_result.scalar.return_value = 1

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[count_result, main_result])

        mock_user = MagicMock()
        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status=None,
            project_id=None,
            page=1,
            page_size=20,
            db=mock_db,
            current_user=mock_user,
            access_scope=access_scope,
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["page"], 1)
        self.assertEqual(result["page_size"], 20)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["title"], "Issue 1")
        self.assertEqual(result["items"][0]["task_count"], 3)
        self.assertEqual(result["items"][0]["totals"]["additions"], 100)
        self.assertEqual(result["items"][0]["totals"]["deletions"], 20)
        self.assertEqual(result["items"][0]["totals"]["input_tokens"], 5000)


# ---------------------------------------------------------------------------
# Get issue detail
# ---------------------------------------------------------------------------


class GetIssueTests(unittest.IsolatedAsyncioTestCase):
    """Tests for GET /api/issues/{issue_id}."""

    async def test_get_issue_not_found(self):
        """Should raise 404 when issue does not exist."""
        from fastapi import HTTPException
        from app.api.issues import get_issue
        from app.dependencies.project_access import ProjectAccessScope

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_user = MagicMock()
        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with self.assertRaises(HTTPException) as ctx:
            await get_issue(issue_id=999, db=mock_db, current_user=mock_user, access_scope=access_scope)

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_get_issue_with_tasks(self):
        """Should return issue with serialized tasks list."""
        from app.api.issues import get_issue
        from app.dependencies.project_access import ProjectAccessScope

        task1 = _make_task(id=100, user_prompt="Fix bug")
        task2 = _make_task(id=101, user_prompt="Add tests")
        issue = _make_issue(id=5, title="Feature Y", tasks=[task1, task2])

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = issue

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_user = MagicMock()
        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await get_issue(issue_id=5, db=mock_db, current_user=mock_user, access_scope=access_scope)

        self.assertEqual(result["id"], 5)
        self.assertEqual(result["title"], "Feature Y")
        self.assertEqual(len(result["tasks"]), 2)
        self.assertEqual(result["tasks"][0]["id"], 100)
        self.assertEqual(result["tasks"][1]["id"], 101)


# ---------------------------------------------------------------------------
# Update issue
# ---------------------------------------------------------------------------


class UpdateIssueTests(unittest.IsolatedAsyncioTestCase):
    """Tests for PATCH /api/issues/{issue_id}."""

    async def test_update_issue_title(self):
        """Should update the title field."""
        from app.api.issues import update_issue, UpdateIssueRequest

        issue = _make_issue(id=1, title="Old Title")

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = issue

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_user = MagicMock()

        body = UpdateIssueRequest(title="New Title")
        result = await update_issue(issue_id=1, body=body, db=mock_db, current_user=mock_user)

        self.assertEqual(issue.title, "New Title")
        mock_db.commit.assert_awaited_once()

    async def test_update_issue_invalid_status(self):
        """Should raise 400 for invalid status value."""
        from fastapi import HTTPException
        from app.api.issues import update_issue, UpdateIssueRequest

        issue = _make_issue(id=1)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = issue

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_user = MagicMock()

        body = UpdateIssueRequest(status="invalid_status")
        with self.assertRaises(HTTPException) as ctx:
            await update_issue(issue_id=1, body=body, db=mock_db, current_user=mock_user)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Invalid status", ctx.exception.detail)


# ---------------------------------------------------------------------------
# Close issue
# ---------------------------------------------------------------------------


class CloseIssueTests(unittest.IsolatedAsyncioTestCase):
    """Tests for POST /api/issues/{issue_id}/close."""

    async def test_close_issue_success(self):
        """Should set status to closed."""
        from app.api.issues import close_issue
        from app.models import IssueStatus

        issue = _make_issue(id=1, status=IssueStatus.OPEN.value)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = issue

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_user = MagicMock()

        result = await close_issue(issue_id=1, db=mock_db, current_user=mock_user)

        self.assertEqual(issue.status, IssueStatus.CLOSED.value)
        mock_db.commit.assert_awaited_once()

    async def test_close_issue_not_found(self):
        """Should raise 404 when issue does not exist."""
        from fastapi import HTTPException
        from app.api.issues import close_issue

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_user = MagicMock()

        with self.assertRaises(HTTPException) as ctx:
            await close_issue(issue_id=999, db=mock_db, current_user=mock_user)

        self.assertEqual(ctx.exception.status_code, 404)


# ---------------------------------------------------------------------------
# Delete issue
# ---------------------------------------------------------------------------


class DeleteIssueTests(unittest.IsolatedAsyncioTestCase):
    """Tests for DELETE /api/issues/{issue_id}."""

    async def test_delete_issue_with_active_tasks_fails(self):
        """Should return 409 when issue has active tasks."""
        from fastapi import HTTPException
        from app.api.issues import delete_issue

        issue = _make_issue(id=1)

        issue_result = MagicMock()
        issue_result.scalar_one_or_none.return_value = issue

        # Active task count = 2
        count_result = MagicMock()
        count_result.scalar.return_value = 2

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[issue_result, count_result])
        mock_user = MagicMock()

        with self.assertRaises(HTTPException) as ctx:
            await delete_issue(issue_id=1, db=mock_db, current_user=mock_user)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("active task", ctx.exception.detail)

    async def test_delete_issue_success(self):
        """Should delete issue when no active tasks."""
        from app.api.issues import delete_issue

        issue = _make_issue(id=1)

        issue_result = MagicMock()
        issue_result.scalar_one_or_none.return_value = issue

        # Active task count = 0
        count_result = MagicMock()
        count_result.scalar.return_value = 0

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[issue_result, count_result])
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_user = MagicMock()

        result = await delete_issue(issue_id=1, db=mock_db, current_user=mock_user)

        self.assertEqual(result["status"], "deleted")
        self.assertEqual(result["id"], 1)
        mock_db.delete.assert_awaited_once_with(issue)
        mock_db.commit.assert_awaited_once()

    async def test_delete_issue_not_found(self):
        """Should raise 404 when issue does not exist."""
        from fastapi import HTTPException
        from app.api.issues import delete_issue

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_user = MagicMock()

        with self.assertRaises(HTTPException) as ctx:
            await delete_issue(issue_id=999, db=mock_db, current_user=mock_user)

        self.assertEqual(ctx.exception.status_code, 404)


# ---------------------------------------------------------------------------
# Ownership permission checks (OIDC enabled)
# ---------------------------------------------------------------------------


class IssueOwnershipTests(unittest.IsolatedAsyncioTestCase):
    """Tests for issue ownership enforcement when OIDC is enabled."""

    def _mock_settings(self, oidc_enabled=True):
        settings = MagicMock()
        settings.oidc_enabled = oidc_enabled
        return settings

    def _mock_user(self, id=1, platform_role="platform_user"):
        user = MagicMock()
        user.id = id
        user.platform_role = platform_role
        return user

    async def test_update_issue_forbidden_for_non_owner(self):
        """Should raise 403 when non-owner tries to update issue."""
        from fastapi import HTTPException
        from app.api.issues import update_issue, UpdateIssueRequest

        issue = _make_issue(id=1, initiator_user_id=10)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = issue

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)

        non_owner = self._mock_user(id=99)
        body = UpdateIssueRequest(title="Hacked")

        with patch("app.core.task_helpers.get_effective_settings", return_value=self._mock_settings()):
            with self.assertRaises(HTTPException) as ctx:
                await update_issue(issue_id=1, body=body, db=mock_db, current_user=non_owner)

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_update_issue_allowed_for_owner(self):
        """Should allow owner to update issue."""
        from app.api.issues import update_issue, UpdateIssueRequest

        issue = _make_issue(id=1, initiator_user_id=10)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = issue

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        owner = self._mock_user(id=10)
        body = UpdateIssueRequest(title="Updated")

        with patch("app.core.task_helpers.get_effective_settings", return_value=self._mock_settings()):
            result = await update_issue(issue_id=1, body=body, db=mock_db, current_user=owner)

        self.assertEqual(issue.title, "Updated")

    async def test_update_issue_allowed_for_admin(self):
        """Should allow admin to update any issue."""
        from app.api.issues import update_issue, UpdateIssueRequest

        issue = _make_issue(id=1, initiator_user_id=10)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = issue

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        admin = self._mock_user(id=99, platform_role="platform_admin")
        body = UpdateIssueRequest(title="Admin Update")

        with patch("app.core.task_helpers.get_effective_settings", return_value=self._mock_settings()):
            result = await update_issue(issue_id=1, body=body, db=mock_db, current_user=admin)

        self.assertEqual(issue.title, "Admin Update")

    async def test_close_issue_forbidden_for_non_owner(self):
        """Should raise 403 when non-owner tries to close issue."""
        from fastapi import HTTPException
        from app.api.issues import close_issue

        issue = _make_issue(id=1, initiator_user_id=10)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = issue

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)

        non_owner = self._mock_user(id=99)

        with patch("app.core.task_helpers.get_effective_settings", return_value=self._mock_settings()):
            with self.assertRaises(HTTPException) as ctx:
                await close_issue(issue_id=1, db=mock_db, current_user=non_owner)

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_delete_issue_forbidden_for_non_owner(self):
        """Should raise 403 when non-owner tries to delete issue."""
        from fastapi import HTTPException
        from app.api.issues import delete_issue

        issue = _make_issue(id=1, initiator_user_id=10)

        issue_result = MagicMock()
        issue_result.scalar_one_or_none.return_value = issue

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=issue_result)

        non_owner = self._mock_user(id=99)

        with patch("app.core.task_helpers.get_effective_settings", return_value=self._mock_settings()):
            with self.assertRaises(HTTPException) as ctx:
                await delete_issue(issue_id=1, db=mock_db, current_user=non_owner)

        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
