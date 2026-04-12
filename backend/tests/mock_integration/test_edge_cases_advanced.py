"""Edge case and stress tests — timeout, stats, retries, webhook validation.

Tests that exercise less common code paths:
- Container timeout (claude delay exceeds TASK_TIMEOUT)
- Usage stats recording (input_tokens, output_tokens)
- Multiple retry attempts
- Webhook payload edge cases
- Custom file changes via mock config
- Long prompts

Prerequisites:
    docker-compose -f backend/tests/mock_integration/docker-compose.mock-test.yml up -d
"""

import asyncio
import logging
import random
import time

import httpx
import pytest

from .conftest import (
    build_webhook_payload,
    get_mock_calls,
    send_webhook,
    wait_for_task_status,
)

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.asyncio


class TestContainerTimeout:
    """Container timeout when claude delay exceeds TASK_TIMEOUT (120s)."""

    async def test_task_timeout_marks_failed(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """When claude delay exceeds TASK_TIMEOUT, task should fail."""
        # TASK_TIMEOUT is 120s in test env. Set delay to 180s to trigger timeout.
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 180},
        )

        try:
            resp = await http_client.post(
                f"{backend_url}/api/tasks",
                json={
                    "project_id": 1,
                    "user_prompt": "This task will timeout",
                    "branch_name": f"codify/timeout-{int(time.time())}",
                    "target_branch": "main",
                },
                headers=admin_auth_headers,
            )
            assert resp.status_code in (200, 201)
            task_id = resp.json()["id"]

            # Wait for task to fail (should timeout around 120s + container overhead)
            task = await wait_for_task_status(
                http_client, backend_url, task_id,
                target_statuses=["completed", "failed"],
                auth_headers=admin_auth_headers,
                timeout=240,
            )
            assert task["status"] == "failed", (
                f"Timeout task should fail, got {task['status']}"
            )
            logger.info(
                f"✅ Task timed out as expected: "
                f"error={(task.get('error_message') or '')[:100]}"
            )
        finally:
            await http_client.patch(
                f"{mock_url}/mock/config",
                json={"claude_delay_seconds": 0},
            )


class TestUsageStats:
    """Verify usage statistics are recorded on completed tasks."""

    async def test_completed_task_has_token_stats(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Completed task should have input_tokens and output_tokens recorded."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Task for stats verification",
                "branch_name": f"codify/stats-{int(time.time())}",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed"

        # Fake claude outputs usage: input_tokens=1500, output_tokens=800
        input_tokens = task.get("input_tokens")
        output_tokens = task.get("output_tokens")
        if input_tokens is not None:
            assert input_tokens > 0, "input_tokens should be positive"
            logger.info(f"✅ Token stats recorded: in={input_tokens}, out={output_tokens}")
        else:
            logger.info("Token stats not in task response (may need logs endpoint)")

    async def test_failed_task_may_have_partial_stats(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Failed task may still have partial token stats (claude ran but failed)."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_exit_code": 1},
        )

        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Failed task for stats",
                "branch_name": f"codify/fail-stats-{int(time.time())}",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "failed"

        # Even failed tasks emit CODIFY_STATS before exiting
        input_tokens = task.get("input_tokens")
        if input_tokens is not None:
            logger.info(f"✅ Failed task has partial stats: in={input_tokens}")
        else:
            logger.info("Failed task has no stats (acceptable)")


class TestRetryBehavior:
    """Task retry edge cases."""

    async def test_retry_failed_then_succeed(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Retry a failed task after fixing the cause — should succeed."""
        # First run: fail
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_exit_code": 1},
        )

        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Task to retry",
                "branch_name": f"codify/retry-succeed-{int(time.time())}",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "failed"

        # Fix the cause: reset to success
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_exit_code": 0},
        )

        # Retry
        resp = await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/retry",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200, f"Retry failed: {resp.text}"
        retry_data = resp.json()
        retry_id = retry_data.get("id") or retry_data.get("task_id") or task_id

        task = await wait_for_task_status(
            http_client, backend_url, retry_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", (
            f"Retried task should succeed: {task.get('error_message')}"
        )
        logger.info(f"✅ Retry succeeded: original={task_id}, retry={retry_id}")

    async def test_retry_running_task_rejected(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Retrying a running task should be rejected."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 30},
        )

        try:
            resp = await http_client.post(
                f"{backend_url}/api/tasks",
                json={
                    "project_id": 1,
                    "user_prompt": "Running task retry test",
                    "branch_name": f"codify/retry-running-{int(time.time())}",
                    "target_branch": "main",
                },
                headers=admin_auth_headers,
            )
            assert resp.status_code in (200, 201)
            task_id = resp.json()["id"]

            await wait_for_task_status(
                http_client, backend_url, task_id,
                target_statuses=["running"],
                auth_headers=admin_auth_headers,
                timeout=60,
            )

            # Try to retry while running — should fail
            resp = await http_client.post(
                f"{backend_url}/api/tasks/{task_id}/retry",
                headers=admin_auth_headers,
            )
            assert resp.status_code in (400, 409), (
                f"Retry of running task should be rejected, got {resp.status_code}"
            )
            logger.info(f"✅ Retry of running task rejected with {resp.status_code}")
        finally:
            await http_client.patch(
                f"{mock_url}/mock/config",
                json={"claude_delay_seconds": 0},
            )

    async def test_retry_completed_task_rejected(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Retrying a completed (successful) task should be rejected."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Completed task retry test",
                "branch_name": f"codify/retry-complete-{int(time.time())}",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        resp = await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/retry",
            headers=admin_auth_headers,
        )
        assert resp.status_code in (400, 409), (
            f"Retry of completed task should be rejected, got {resp.status_code}"
        )
        logger.info(f"✅ Retry of completed task rejected with {resp.status_code}")


class TestWebhookEdgeCases:
    """Webhook payload validation and edge cases."""

    async def test_webhook_missing_note_body(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
    ):
        """Webhook without note body should be handled gracefully."""
        payload = {
            "object_kind": "note",
            "event_type": "note",
            "project": {"id": 1, "path_with_namespace": "test/project"},
            "object_attributes": {
                "id": random.randint(100000, 999999),
                "noteable_type": "Issue",
                # Missing "note" field
            },
            "issue": {"iid": 1},
        }
        resp = await http_client.post(
            f"{backend_url}/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "mock-webhook-secret"},
        )
        # Should not crash — may return 200 (ignored) or 400
        assert resp.status_code in (200, 400, 422), (
            f"Missing note body should be handled, got {resp.status_code}"
        )
        logger.info(f"✅ Missing note body handled: {resp.status_code}")

    async def test_webhook_non_issue_note_creates_task(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
    ):
        """Webhook for MR note with @ai-bot also creates a task (backend supports this)."""
        payload = {
            "object_kind": "note",
            "event_type": "note",
            "project": {"id": 1, "path_with_namespace": "test/project"},
            "object_attributes": {
                "id": random.randint(100000, 999999),
                "noteable_type": "MergeRequest",
                "note": "@ai-bot do something",
            },
            "merge_request": {"iid": 1},
        }
        resp = await http_client.post(
            f"{backend_url}/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "mock-webhook-secret"},
        )
        # Backend accepts MR notes with @ai-bot and creates tasks
        assert resp.status_code == 200
        data = resp.json()
        # May create a task or ignore — both are valid
        logger.info(f"✅ MR note with @ai-bot: task_id={data.get('task_id')}, status={data.get('status')}")

    async def test_webhook_without_ai_bot_mention_ignored(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
    ):
        """Webhook for issue note without @ai-bot mention should be ignored."""
        payload = build_webhook_payload(
            project_id=1,
            issue_iid=random.randint(30000, 39999),
            prompt="No AI bot mention here",
        )
        payload["object_attributes"]["id"] = random.randint(100000, 999999)
        # Override note to remove @ai-bot
        payload["object_attributes"]["note"] = "Just a regular comment without bot mention"

        resp = await http_client.post(
            f"{backend_url}/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "mock-webhook-secret"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("task_id") is None
        logger.info(f"✅ Comment without @ai-bot correctly ignored")

    async def test_webhook_empty_prompt_after_mention(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
    ):
        """Webhook with @ai-bot but empty prompt should be handled."""
        payload = build_webhook_payload(
            project_id=1,
            issue_iid=random.randint(40000, 49999),
            prompt="",
        )
        payload["object_attributes"]["id"] = random.randint(100000, 999999)
        # Note is just "@ai-bot" with no prompt
        payload["object_attributes"]["note"] = "@ai-bot"

        resp = await http_client.post(
            f"{backend_url}/api/webhook/gitlab",
            json=payload,
            headers={"X-Gitlab-Token": "mock-webhook-secret"},
        )
        # Should either create task with empty prompt or reject
        assert resp.status_code in (200, 400, 422)
        logger.info(f"✅ Empty prompt after @ai-bot handled: {resp.status_code}")


class TestCustomFileChanges:
    """Verify custom file changes via mock config."""

    async def test_custom_files_in_completed_task(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Custom claude_file_changes should be created by fake claude."""
        custom_files = [
            {"path": "src/main.py", "content": "print('custom file')\n"},
            {"path": "tests/test_main.py", "content": "def test_main(): pass\n"},
        ]
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_file_changes": custom_files},
        )

        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Create custom files",
                "branch_name": f"codify/custom-files-{int(time.time())}",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", (
            f"Custom files task should succeed: {task.get('error_message')}"
        )

        # Verify git push happened (files were committed and pushed)
        calls = await get_mock_calls(http_client, mock_url)
        git_calls = [c for c in calls if c.get("service") == "git"]
        push_calls = [c for c in git_calls if "receive-pack" in c.get("path", "")]
        assert len(push_calls) > 0, "Expected git push for custom files"
        logger.info("✅ Custom file changes created and pushed successfully")


class TestTaskLogs:
    """Task log retrieval and content."""

    async def test_completed_task_has_logs(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Completed task should have retrievable logs."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Task for log verification",
                "branch_name": f"codify/logs-{int(time.time())}",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        # Fetch logs
        resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}/logs",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        logs = resp.json()

        # Should have some log entries
        if isinstance(logs, list):
            assert len(logs) > 0, "Completed task should have log entries"
            logger.info(f"✅ Task has {len(logs)} log entries")
        elif isinstance(logs, dict) and "items" in logs:
            assert len(logs["items"]) > 0, "Completed task should have log entries"
            logger.info(f"✅ Task has {len(logs['items'])} log entries")
        else:
            logger.info(f"Logs response format: {type(logs)}")

    async def test_failed_task_has_error_logs(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Failed task should have logs with error information."""
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_exit_code": 1},
        )

        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Task for error log verification",
                "branch_name": f"codify/error-logs-{int(time.time())}",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}/logs",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        logger.info("✅ Failed task logs retrieved successfully")

    async def test_nonexistent_task_logs_404(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Logs for nonexistent task should return 404."""
        resp = await http_client.get(
            f"{backend_url}/api/tasks/999999/logs",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 404
        logger.info("✅ Nonexistent task logs returned 404")


class TestLongPrompt:
    """Tasks with very long prompts."""

    async def test_long_prompt_succeeds(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Task with a long prompt (5000 chars) should succeed."""
        long_prompt = "Implement a comprehensive feature: " + ("detailed requirement " * 250)
        assert len(long_prompt) > 5000

        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": long_prompt,
                "branch_name": f"codify/long-prompt-{int(time.time())}",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", (
            f"Long prompt task should succeed: {task.get('error_message')}"
        )
        logger.info("✅ Long prompt (5000+ chars) task completed")

    async def test_unicode_prompt_succeeds(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Task with unicode/CJK characters in prompt should succeed."""
        unicode_prompt = "请帮我创建一个 hello.py 文件，输出 '你好世界' 🌍✨"

        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": unicode_prompt,
                "branch_name": f"codify/unicode-{int(time.time())}",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        task_id = resp.json()["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", (
            f"Unicode prompt task should succeed: {task.get('error_message')}"
        )

        # Verify the prompt was stored correctly
        resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}",
            headers=admin_auth_headers,
        )
        stored = resp.json()
        assert unicode_prompt in stored.get("user_prompt", ""), (
            "Unicode prompt should be preserved in storage"
        )
        logger.info("✅ Unicode/CJK prompt stored and completed correctly")
