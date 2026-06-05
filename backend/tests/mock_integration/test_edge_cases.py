"""Edge case integration tests — git push failure, MR update failure, API degradation.

Tests how the system handles partial failures in external services while
keeping the overall task lifecycle intact.

Key behaviors tested:
- git push failure → task FAILED (set -e in entrypoint.sh)
- MR update failure → task still COMPLETES (entrypoint.sh uses || true)
- GitLab issue comment failure → task still COMPLETES (non-fatal)
- Token usage and diff stats parsing from CODIFY markers

Prerequisites:
    docker-compose -f backend/tests/mock_integration/docker-compose.mock-test.yml up -d
"""

import logging

import httpx
import pytest

from .conftest import (
    create_issue_and_task,
    get_mock_calls,
    wait_for_task_status,
)

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.asyncio


class TestGitPushFailure:
    """Git push failure causes task to FAIL (set -e in entrypoint.sh)."""

    async def test_git_push_rejected_fails_task(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """When git push is rejected, the task should end up FAILED."""
        # Enable git push failure
        resp = await http_client.patch(
            f"{mock_url}/mock/config",
            json={"fail_git_push": True},
        )
        assert resp.status_code == 200

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Git push failure test",
            prompt="This should fail because git push is rejected",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "failed", (
            f"Expected FAILED due to git push rejection, got {task['status']}"
        )
        assert task.get("error_message"), "Should have error_message when git push fails"
        logger.info(f"✅ Git push failure → task FAILED: {task['error_message'][:80]}")


class TestMRUpdateFailure:
    """MR update failure is non-fatal — task should still COMPLETE."""

    async def test_mr_update_failure_still_completes(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """When MR update returns 500, task should still complete (|| true in entrypoint.sh)."""
        # Enable MR update failure
        resp = await http_client.patch(
            f"{mock_url}/mock/config",
            json={"fail_mr_update": True},
        )
        assert resp.status_code == 200

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="MR update failure test",
            prompt="Task should complete even though MR update fails",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        # entrypoint.sh calls update_mr ... || true, so failure is non-fatal
        assert task["status"] == "completed", (
            f"MR update failure should be non-fatal, but task got: {task['status']} - "
            f"{task.get('error_message', '')}"
        )
        assert task.get("commit_sha"), "commit_sha should still be set"

        # Verify MR update was attempted (the call was made, but server returned 500)
        gitlab_calls = await get_mock_calls(http_client, mock_url, service="gitlab")
        mr_update_calls = [
            c for c in gitlab_calls
            if c["method"] == "PUT" and "/merge_requests/" in c["path"]
        ]
        assert len(mr_update_calls) >= 1, "MR update should have been attempted"
        logger.info(f"✅ MR update failed but task completed: {task_id}")


class TestIssueCommentFailure:
    """GitLab issue comment API failure is non-fatal."""

    async def test_issue_comment_failure_still_completes(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """When issue note creation returns 403, task should still complete."""
        resp = await http_client.patch(
            f"{mock_url}/mock/config",
            json={"fail_issue_notes": True},
        )
        assert resp.status_code == 200

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Issue comment failure test",
            prompt="Task should complete even when comments fail",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        # Issue comment failures are non-fatal — task should still complete
        assert task["status"] == "completed", (
            f"Issue comment failure should be non-fatal, got: {task['status']} - "
            f"{task.get('error_message', '')}"
        )
        logger.info(f"✅ Issue comment failed but task completed: {task_id}")


class TestTokenUsageStats:
    """Verify CODIFY_STATS token usage is captured in task record."""

    async def test_token_usage_parsed(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """input_tokens and output_tokens should be parsed from CODIFY_STATS."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Token usage stats test",
            prompt="Create a file for token stats test",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed"

        # fake ci-claude.sh outputs usage: {input_tokens: 1500, output_tokens: 800}
        # entrypoint.sh emits this as CODIFY_STATS
        # worker.py parses it into task.input_tokens / task.output_tokens
        assert task.get("input_tokens") is not None, (
            f"input_tokens should be parsed from CODIFY_STATS, got: {task.get('input_tokens')}"
        )
        assert task.get("output_tokens") is not None, (
            f"output_tokens should be parsed from CODIFY_STATS, got: {task.get('output_tokens')}"
        )
        assert task["input_tokens"] > 0, f"input_tokens should be > 0: {task['input_tokens']}"
        assert task["output_tokens"] > 0, f"output_tokens should be > 0: {task['output_tokens']}"

        logger.info(
            f"✅ Token usage: input={task['input_tokens']}, output={task['output_tokens']}"
        )


class TestDiffStats:
    """Verify CODIFY_DIFF change statistics are captured."""

    async def test_diff_stats_parsed(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """additions/deletions/total_changes should be parsed from CODIFY_DIFF."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Diff stats test",
            prompt="Create files for diff stats test",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed"

        # entrypoint.sh computes git diff --stat and emits CODIFY_DIFF:+N-M
        # The fake-claude creates hello.py (additions > 0)
        additions = task.get("additions", 0)
        deletions = task.get("deletions", 0)
        total = task.get("total_changes", 0)

        assert additions > 0, f"additions should be > 0 (hello.py was created): {additions}"
        assert total > 0, f"total_changes should be > 0: {total}"
        assert total == additions + deletions, (
            f"total_changes ({total}) should equal additions ({additions}) + deletions ({deletions})"
        )

        logger.info(f"✅ Diff stats: +{additions} -{deletions} ({total} total)")


class TestMRTitleParsing:
    """Verify CODIFY_MR_TITLE is captured from AI-generated commit message."""

    async def test_mr_title_parsed(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """commit_message should be parsed from CODIFY_MR_TITLE marker."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="MR title parsing test",
            prompt="Create a file for MR title test",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed"

        # entrypoint.sh calls `claude -p` to generate MR title, emits as CODIFY_MR_TITLE
        # fake-claude-binary outputs "chore: AI-generated code changes..."
        mr_title = task.get("commit_message")
        assert mr_title is not None, "commit_message should be parsed from CODIFY_MR_TITLE"
        assert len(mr_title) > 0, "commit_message should not be empty"

        logger.info(f"✅ MR title: {mr_title}")
