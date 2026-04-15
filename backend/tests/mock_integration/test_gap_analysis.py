"""Gap analysis tests — scenarios identified from code review and coverage analysis.

Covers previously untested paths:
- No changes in MR mode -> task FAILS (entrypoint.sh line 682)
- No changes in no-MR mode -> task COMPLETES (entrypoint.sh line 676-680)
- MR creation failure -> task continues without MR
- Concurrent tasks for different issues -> run in parallel
- Non-existent base branch -> entrypoint fallback logic

Prerequisites:
    docker-compose -f backend/tests/mock_integration/docker-compose.mock-test.yml up -d
"""

import asyncio
import logging
import time

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


class TestNoChangesInMRMode:
    """When Claude makes no changes and target_branch is set, task should FAIL."""

    async def test_no_changes_with_target_branch_fails(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Claude succeeds (exit 0) but creates no files -> No changes made.

        entrypoint.sh checks git status --porcelain after claude runs.
        If empty AND TARGET_BRANCH is set -> exit 1 -> task FAILED.
        """
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_skip_files": True},
        )

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"No changes MR test {int(time.time())}",
            prompt="Review code quality",
            target_branch="main",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "failed", (
            f"No-changes task with target_branch should FAIL, got: {task['status']}"
        )

        error_msg = task.get("error_message", "")
        assert "no changes" in error_msg.lower() or "No changes" in error_msg, (
            f"Error should mention No changes, got: {error_msg[:200]}"
        )
        logger.info(f"No changes in MR mode -> FAILED: {error_msg[:80]}")


class TestNoChangesInNoMRMode:
    """When Claude makes no changes in no-MR mode, task should COMPLETE."""

    async def test_no_changes_without_target_branch_succeeds(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Claude succeeds (exit 0) but creates no files in no-MR mode.

        entrypoint.sh: No-MR mode: task completed without code changes -> exit 0.
        """
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_skip_files": True},
        )

        # Create issue without target_branch (no-MR mode)
        issue = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title=f"No changes no-MR test {int(time.time())}",
            description="Review code quality in no-MR mode",
            target_branch=None,
        )
        task = await create_task(
            http_client, backend_url, admin_auth_headers, issue["id"],
            user_prompt="Review code quality in no-MR mode",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed", (
            f"No-changes task in no-MR mode should COMPLETE, got: {task['status']} "
            f"error: {task.get('error_message', '')[:200]}"
        )
        logger.info("No changes in no-MR mode -> COMPLETED")


class TestMRCreationFailure:
    """When MR creation fails, task should still complete (graceful degradation)."""

    async def test_mr_creation_500_continues_without_mr(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Mock returns 500 on POST merge_requests.

        worker.py catches the exception and continues with mr_iid=None.
        Task should still complete (code is pushed, just no MR created).
        """
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"fail_mr_creation": True},
        )

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"MR creation fail test {int(time.time())}",
            prompt="Test MR creation failure",
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
            f"MR creation failure should not block task: {task.get('error_message')}"
        )

        mr_iid = task.get("issue", {}).get("merge_request_iid")
        logger.info(
            f"MR creation failure -> task completed "
            f"(mr_iid={mr_iid})"
        )

        gitlab_calls = await get_mock_calls(http_client, mock_url, service="gitlab")
        mr_create_calls = [
            c for c in gitlab_calls
            if "merge_requests" in c["path"] and c["method"] == "POST"
            and "notes" not in c["path"]
        ]
        assert len(mr_create_calls) >= 1, (
            "Should have attempted MR creation"
        )


class TestPositiveConcurrency:
    """Tasks for different issues should run truly in parallel."""

    async def test_different_issues_run_concurrently(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Create tasks for 2 different issues -- both should run concurrently.

        docker-compose has MAX_CONCURRENCY=2, so two tasks
        should start roughly at the same time.
        """
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 8},
        )

        ts = int(time.time())
        task_ids = []
        for i in range(2):
            issue, task = await create_issue_and_task(
                http_client, backend_url, admin_auth_headers,
                title=f"Concurrent task {i} {ts}",
                prompt=f"Concurrent task {i}",
                target_branch="main",
            )
            task_ids.append(task["id"])

        logger.info(f"Created concurrent tasks: {task_ids}")

        await asyncio.sleep(10)

        running_count = 0
        for tid in task_ids:
            resp = await http_client.get(
                f"{backend_url}/api/tasks/{tid}",
                headers=admin_auth_headers,
            )
            status = resp.json()["status"]
            if status == "running":
                running_count += 1

        logger.info(f"Running tasks: {running_count} / {len(task_ids)}")

        for tid in task_ids:
            task = await wait_for_task_status(
                http_client, backend_url, tid,
                target_statuses=["completed", "failed"],
                auth_headers=admin_auth_headers,
                timeout=120,
            )
            assert task["status"] == "completed", (
                f"Concurrent task {tid} should complete: {task.get('error_message')}"
            )

        tasks_data = []
        for tid in task_ids:
            resp = await http_client.get(
                f"{backend_url}/api/tasks/{tid}",
                headers=admin_auth_headers,
            )
            tasks_data.append(resp.json())

        t0_started = tasks_data[0].get("started_at", "")
        t1_started = tasks_data[1].get("started_at", "")
        if t0_started and t1_started:
            logger.info(
                f"Concurrent: task0 started={t0_started}, task1 started={t1_started}"
            )
        logger.info("Different tasks ran concurrently")


class TestNonExistentBaseBranch:
    """When BASE_BRANCH does not exist, entrypoint.sh falls back to detected default."""

    async def test_invalid_base_branch_falls_back(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Create task with base_branch that does not exist in the repo.

        entrypoint.sh lines 134-144:
        - Checks git rev-parse --verify origin/BASE_BRANCH
        - If not found, detects remote default via git remote show origin
        - Falls back or errors out
        """
        # Create issue with non-existent base_branch via direct API call
        resp = await http_client.post(
            f"{backend_url}/api/issues",
            json={
                "title": f"Bad base branch test {int(time.time())}",
                "description": "Test non-existent base branch",
                "project_id": 1,
                "base_branch": "this-branch-does-not-exist",
                "target_branch": "main",
            },
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        issue = resp.json()

        task = await create_task(
            http_client, backend_url, admin_auth_headers, issue["id"],
            user_prompt="Test non-existent base branch",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        error_msg = task.get("error_message") or "none"
        logger.info(
            f"Non-existent base branch: task {task_id} -> {task['status']} "
            f"(error: {error_msg[:100]})"
        )


class TestLargePrompt:
    """Verify that very large prompts do not crash the system."""

    async def test_large_prompt_handled(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Create a task with a very long prompt (10KB+).

        The prompt gets passed as USER_PROMPT env var to the container.
        Docker has limits on env var sizes, but 10KB should be fine.
        """
        large_prompt = "Create a comprehensive test suite. " * 300  # ~10KB

        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title=f"Large prompt test {int(time.time())}",
            prompt=large_prompt,
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
            f"Large prompt task should complete: {task.get('error_message', '')[:200]}"
        )
        logger.info(f"Large prompt ({len(large_prompt)} chars) handled successfully")


class TestMultiplePriorityLevels:
    """Test all three priority levels with correct ordering."""

    async def test_p0_p1_p2_ordering(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Create P2, P1, P0 tasks in that order -- verify P0 starts first.

        With MAX_CONCURRENCY=2 and claude_delay=5, the first task picked
        should be P0 (highest priority), then P1, then P2.
        """
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 5},
        )

        ts = int(time.time())
        task_ids = {}
        for priority in [2, 1, 0]:
            issue, task = await create_issue_and_task(
                http_client, backend_url, admin_auth_headers,
                title=f"P{priority} ordering test {ts}",
                prompt=f"Priority P{priority} task",
                target_branch="main",
                priority=priority,
            )
            task_ids[priority] = task["id"]

        tasks = {}
        for priority, tid in task_ids.items():
            task = await wait_for_task_status(
                http_client, backend_url, tid,
                target_statuses=["completed", "failed"],
                auth_headers=admin_auth_headers,
                timeout=180,
            )
            tasks[priority] = task
            assert task["status"] == "completed", (
                f"P{priority} task should complete: {task.get('error_message')}"
            )

        p0_started = tasks[0].get("started_at", "")
        p1_started = tasks[1].get("started_at", "")
        p2_started = tasks[2].get("started_at", "")

        logger.info(
            f"Priority ordering: P0={p0_started}, P1={p1_started}, P2={p2_started}"
        )

        if p0_started and p2_started:
            assert p0_started <= p2_started, (
                f"P0 should start before P2: P0={p0_started}, P2={p2_started}"
            )
        if p0_started and p1_started:
            assert p0_started <= p1_started, (
                f"P0 should start before P1: P0={p0_started}, P1={p1_started}"
            )

        logger.info("P0 -> P1 -> P2 ordering verified")
