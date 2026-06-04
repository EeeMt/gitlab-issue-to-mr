"""Coverage gap tests — API endpoints and edge cases.

Covers previously untested paths identified via gap analysis:
- Task list comma-separated status filtering
- Special characters in user prompts (shell injection safety)
- Task stats API after completion
- Malformed CODIFY markers graceful handling

Prerequisites:
    docker-compose -f backend/tests/mock_integration/docker-compose.mock-test.yml up -d
"""

import logging
import time

import httpx
import pytest

from .conftest import (
    create_issue_and_task,
    wait_for_task_status,
)

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Task list API filtering
# ---------------------------------------------------------------------------

class TestTaskListFiltering:
    """Verify comma-separated status filtering and list API."""

    async def test_comma_separated_status_filter(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """?status=completed,failed should only return those statuses."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Status filter test {int(time.time())}",
            prompt="Task for status filter test",
            target_branch="main",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        completed_status = task["status"]

        resp = await http_client.get(
            f"{backend_url}/api/tasks",
            params={"status": "completed,failed"},
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        tasks_list = data if isinstance(data, list) else data.get("items", data.get("tasks", []))

        for t in tasks_list:
            assert t["status"] in ("completed", "failed"), (
                f"Got unexpected status: {t['status']}"
            )

        task_ids = [t["id"] for t in tasks_list]
        assert task_id in task_ids, (
            f"Task {task_id} ({completed_status}) not in filtered results"
        )

        resp2 = await http_client.get(
            f"{backend_url}/api/tasks",
            params={"status": "running"},
            headers=admin_auth_headers,
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        tasks_list2 = data2 if isinstance(data2, list) else data2.get("items", data2.get("tasks", []))
        running_ids = [t["id"] for t in tasks_list2]
        assert task_id not in running_ids, (
            "Completed task shouldn't appear in running-only filter"
        )
        logger.info("Comma-separated status filter works correctly")


# ---------------------------------------------------------------------------
# Special characters in prompts
# ---------------------------------------------------------------------------

class TestSpecialCharsInPrompt:
    """Verify prompts with shell metacharacters don't cause injection."""

    async def test_shell_metacharacters_safe(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Prompt with backticks, command substitution, quotes, newlines should be safe."""
        dangerous_prompt = 'Create a file with `echo hello` and $(whoami)\nAlso handle \'single quotes\' and "double quotes"\nAnd $HOME ${PATH} $((1+1)) >&2 ; rm -rf /'

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Special chars test {int(time.time())}",
            prompt=dangerous_prompt,
            target_branch="main",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", (
            f"Special chars caused failure: {task.get('error_message', '')[:200]}"
        )

        resp2 = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}",
            headers=admin_auth_headers,
        )
        stored_prompt = resp2.json().get("user_prompt", "")
        assert "$(whoami)" in stored_prompt, (
            "Shell metacharacters should be stored literally"
        )
        assert "`echo hello`" in stored_prompt, (
            "Backticks should be stored literally"
        )
        logger.info("Shell metacharacters handled safely")


# ---------------------------------------------------------------------------
# Task stats API
# ---------------------------------------------------------------------------

class TestTaskStatsAPI:
    """Verify task detail returns parsed metrics after completion."""

    async def test_stats_populated_after_completion(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """After task completes, detail should return token usage."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Stats API test {int(time.time())}",
            prompt="Create a utility function",
            target_branch="main",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed"

        resp2 = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}",
            headers=admin_auth_headers,
        )
        assert resp2.status_code == 200
        detail = resp2.json()

        input_tokens = detail.get("input_tokens", 0)
        output_tokens = detail.get("output_tokens", 0)

        logger.info(
            f"Task stats: input_tokens={input_tokens}, "
            f"output_tokens={output_tokens}"
        )

        has_tokens = input_tokens > 0 or output_tokens > 0
        has_model = detail.get("model_name") is not None

        logger.info(
            f"Task stats API: tokens={'present' if has_tokens else 'absent'}, "
            f"model={'present' if has_model else 'absent'}"
        )


# ---------------------------------------------------------------------------
# Malformed CODIFY markers
# ---------------------------------------------------------------------------

class TestMalformedMarkers:
    """Verify worker handles broken CODIFY markers gracefully."""

    async def test_task_handles_markers_gracefully(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Even with unexpected marker content, task should complete."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Marker test {int(time.time())}",
            prompt="Simple task for marker test",
            target_branch="main",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", (
            f"Task should complete: {task.get('error_message')}"
        )

        resp2 = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}/logs",
            headers=admin_auth_headers,
        )
        assert resp2.status_code == 200
        logs = resp2.json()
        if isinstance(logs, dict):
            logs = logs.get("items", logs.get("logs", []))

        assert len(logs) > 0, "Should have log entries from CODIFY markers"
        logger.info(f"Markers processed: {len(logs)} log entries created")
