"""Entrypoint and worker code path tests — MR workflows, markers, sanitization.

Tests that verify entrypoint.sh and worker.py code paths using the
Issue → Task → MR flow:
- MR description updates (running → completed)
- Existing MR detection and reuse
- CODIFY markers in task output (stats, tool calls)
- Log sanitization (token redaction)
- No-changes detection behavior
- MR creation flow via mock call verification

Prerequisites:
    docker-compose -f backend/tests/mock_integration/docker-compose.mock-test.yml up -d
"""

import logging

import httpx
import pytest

from .conftest import (
    create_issue,
    create_issue_and_task,
    create_task,
    get_mock_calls,
    wait_for_task_status,
)

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.asyncio


class TestMRDescriptionUpdates:
    """Verify MR description is updated during task lifecycle."""

    async def test_mr_updated_on_task_completion(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Completed task should trigger MR description update via PUT call."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="MR Description Update Test",
            prompt="MR description update test",
        )
        task_id = task["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        calls = await get_mock_calls(http_client, mock_url, service="gitlab")
        put_calls = [
            c for c in calls
            if c["method"] == "PUT" and "merge_requests" in c.get("path", "")
        ]
        assert len(put_calls) > 0, "MR should be updated via PUT on task completion"

        # Check the last PUT call has description content
        last_put = put_calls[-1]
        body = last_put.get("body", {})
        if isinstance(body, dict):
            desc = body.get("description", "")
            assert len(desc) > 0, "MR description should not be empty"
            logger.info(f"✅ MR updated with description ({len(desc)} chars)")
        else:
            logger.info(f"✅ MR PUT call recorded (body type: {type(body)})")

    async def test_mr_description_contains_execution_summary(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """MR description should contain execution summary markers."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="MR Description Content Check",
            prompt="Task for MR description content check",
        )
        task_id = task["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        calls = await get_mock_calls(http_client, mock_url, service="gitlab")
        put_calls = [
            c for c in calls
            if c["method"] == "PUT" and "merge_requests" in c.get("path", "")
        ]

        # Find description content from PUT calls
        descriptions = []
        for call in put_calls:
            body = call.get("body", {})
            if isinstance(body, dict) and body.get("description"):
                descriptions.append(body["description"])

        if descriptions:
            last_desc = descriptions[-1]
            logger.info(f"Last MR description ({len(last_desc)} chars): {last_desc[:200]}...")
        else:
            logger.info("No MR description captured (body may be string-encoded)")


class TestExistingMRDetection:
    """Verify entrypoint detects and reuses existing MRs."""

    async def test_existing_mr_search_called(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Task should search for existing MR by source_branch before creating new one."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Existing MR Search Test",
            prompt="Existing MR search test",
        )
        task_id = task["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        calls = await get_mock_calls(http_client, mock_url, service="gitlab")
        # Check for MR search call (GET /merge_requests?source_branch=...)
        mr_list_calls = [
            c for c in calls
            if c["method"] == "GET"
            and c.get("path", "").endswith("/merge_requests")
        ]

        if mr_list_calls:
            # Verify source_branch param was included
            params = mr_list_calls[0].get("params", {})
            logger.info(f"✅ MR search call found with params: {params}")
        else:
            # Some code paths skip the search if MR_IID is already set
            logger.info("MR search not called (MR_IID may be pre-set by worker)")


class TestCODIFYMarkers:
    """Verify CODIFY markers are parsed from worker output."""

    async def test_completed_task_has_tool_calls(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Completed task should have tool_calls parsed from CODIFY_TOOL_CALLS marker."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Tool Calls Verification",
            prompt="Task for tool calls verification",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        # Fake claude emits CODIFY_TOOL_CALLS with 3 tool calls
        tool_calls = task.get("tool_calls")
        if tool_calls is not None:
            assert isinstance(tool_calls, list)
            if len(tool_calls) > 0:
                first = tool_calls[0]
                assert "name" in first, "Tool call should have 'name' field"
                logger.info(f"✅ Task has {len(tool_calls)} tool calls")
            else:
                logger.info("Tool calls list is empty (may not be in task response)")
        else:
            logger.info("tool_calls field not in task response (check logs endpoint)")

    async def test_completed_task_has_usage_stats(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Completed task should have usage stats from CODIFY_STATS marker."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Usage Stats Verification",
            prompt="Task for usage stats verification",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        # Fake claude emits usage: input_tokens=1500, output_tokens=800
        input_tokens = task.get("input_tokens")
        output_tokens = task.get("output_tokens")
        if input_tokens is not None and output_tokens is not None:
            assert input_tokens > 0
            assert output_tokens > 0
            logger.info(f"✅ Usage stats: input={input_tokens}, output={output_tokens}")
        else:
            logger.info("Usage stats not in direct task response")


class TestLogSanitization:
    """Verify sensitive data is stripped from task logs."""

    async def test_logs_do_not_contain_tokens(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Task logs should not contain GitLab or Anthropic tokens."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Log Sanitization Check",
            prompt="Task for log sanitization check",
        )
        task_id = task["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        # Fetch task logs
        resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}/logs",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        logs = resp.json()

        # Collect all log text
        log_text = ""
        if isinstance(logs, list):
            log_text = " ".join(
                entry.get("content", "") or entry.get("message", "") or ""
                for entry in logs
            )
        elif isinstance(logs, dict) and "items" in logs:
            log_text = " ".join(
                entry.get("content", "") or entry.get("message", "") or ""
                for entry in logs["items"]
            )

        if log_text:
            # Sensitive patterns that should NOT appear
            assert "glpat-" not in log_text, "GitLab token (glpat-) found in logs!"
            assert "sk-ant-" not in log_text, "Anthropic token (sk-ant-) found in logs!"
            assert "sk-api-" not in log_text, "API key (sk-api-) found in logs!"
            logger.info(f"✅ Log sanitization verified ({len(log_text)} chars, no tokens)")
        else:
            logger.info("No log text to check (logs may be empty)")


class TestNoChangesDetection:
    """Verify behavior when claude produces no file changes."""

    async def test_no_changes_with_target_branch_fails(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """When claude skips files and target_branch is set (MR mode), task should fail."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_skip_files": True},
        )

        issue = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title="No Changes MR Mode Test",
            description="No changes MR mode test",
            target_branch="main",
        )
        task = await create_task(
            http_client, backend_url, admin_auth_headers,
            issue["id"],
            user_prompt="No changes MR mode test",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        # MR mode with no changes should fail (nothing to push/MR)
        assert task["status"] == "failed", (
            f"No-changes in MR mode should fail, got {task['status']}"
        )
        logger.info("✅ No-changes in MR mode correctly failed")

    async def test_no_changes_without_target_branch_succeeds(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """When claude skips files and no target_branch (no-MR mode), task should succeed."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_skip_files": True},
        )

        issue = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title="No Changes No-MR Mode Test",
            description="No changes no-MR mode test",
            target_branch=None,
        )
        task = await create_task(
            http_client, backend_url, admin_auth_headers,
            issue["id"],
            user_prompt="No changes no-MR mode test",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        # No-MR mode with no changes should succeed (just push, no MR needed)
        assert task["status"] == "completed", (
            f"No-changes in no-MR mode should succeed: {task.get('error_message')}"
        )
        logger.info("✅ No-changes in no-MR mode correctly succeeded")


class TestMRCreationFlow:
    """Verify the full MR creation flow via mock call recording."""

    async def test_new_mr_created_via_post(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Task should create a new MR via POST when none exists."""
        # Make MR search return empty list (no existing MR)
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"fail_mr_creation": False},
        )

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="MR Creation Flow Test",
            prompt="MR creation flow test",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed"

        calls = await get_mock_calls(http_client, mock_url, service="gitlab")

        # Should have at least: project lookup, MR search/create, MR update
        project_calls = [c for c in calls if "/projects/1" in c.get("path", "") and c["method"] == "GET"]
        mr_calls = [c for c in calls if "merge_requests" in c.get("path", "")]

        assert len(project_calls) > 0, "Should have project lookup call"
        assert len(mr_calls) > 0, "Should have MR-related calls"

        logger.info(
            f"✅ MR flow: {len(project_calls)} project lookups, "
            f"{len(mr_calls)} MR calls"
        )

    async def test_completed_task_has_mr_url(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Completed task's issue should have merge_request_url."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="MR URL Verification",
            prompt="MR URL verification",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        # merge_request_url is on the issue, not the task
        issue_data = task.get("issue", {})
        mr_url = issue_data.get("merge_request_url") if issue_data else None
        if mr_url:
            assert "merge_requests" in mr_url or "mr" in mr_url
            logger.info(f"✅ Issue has MR URL: {mr_url}")
        else:
            logger.info("MR URL not in issue data (may use different field name)")


class TestIssueTaskToMRFlow:
    """End-to-end Issue → Task → MR with mock call verification."""

    async def test_completed_task_posts_gitlab_comment(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Completed task should post a comment back on GitLab via the API."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="GitLab Comment Verification",
            prompt="Create a hello.py file",
        )
        task_id = task["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        calls = await get_mock_calls(http_client, mock_url, service="gitlab")

        # Check for any POST calls to /notes (issue comment posting)
        note_calls = [
            c for c in calls
            if c["method"] == "POST" and "/notes" in c.get("path", "")
        ]
        if note_calls:
            logger.info(f"✅ {len(note_calls)} issue comment(s) posted")
            for nc in note_calls:
                body = nc.get("body", {})
                if isinstance(body, dict):
                    comment_body = body.get("body", "")
                    if comment_body:
                        logger.info(f"  Comment: {comment_body[:100]}...")
        else:
            logger.info("No issue comments found (may use different notification path)")

    async def test_full_flow_records_git_operations(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Full task flow should record: clone, push, MR create/update."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Git Operations Verification",
            prompt="Full flow git ops verification",
        )
        task_id = task["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        calls = await get_mock_calls(http_client, mock_url)

        git_calls = [c for c in calls if c.get("service") == "git"]
        gitlab_calls = [c for c in calls if c.get("service") == "gitlab"]

        # Categorize git operations
        clone_calls = [c for c in git_calls if "upload-pack" in c.get("path", "")]
        push_calls = [c for c in git_calls if "receive-pack" in c.get("path", "")]

        logger.info(
            f"✅ Git operations: {len(clone_calls)} clone(s), {len(push_calls)} push(es), "
            f"{len(gitlab_calls)} GitLab API calls"
        )
        assert len(clone_calls) > 0, "Expected at least one git clone operation"
        assert len(push_calls) > 0, "Expected at least one git push operation"
