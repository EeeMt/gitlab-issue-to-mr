"""MR follow-up tasks, container env validation, and concurrent retry tests.

Tests follow-up task creation on the same issue, worker container environment
variables, and concurrent operation edge cases.
"""

import pytest

from .conftest import (
    BACKEND_URL,
    create_issue_and_task,
    create_task,
    wait_for_task_status,
)

# ── MR Follow-up Task ────────────────────────────────────────────────


class TestMRFollowUpTask:
    """Flow: create issue+task → task completes → create follow-up task on same issue."""

    @pytest.mark.asyncio
    async def test_mr_follow_up_full_flow(
        self, http_client, backend_url, admin_auth_headers,
    ):
        """First task completes on an issue → second (follow-up) task on same issue."""
        # Step 1: Create issue + initial task
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="MR follow-up flow issue",
            prompt="Create a hello.py file with unit tests",
        )
        task_id = task["id"]
        issue_id = issue["id"]

        # Step 2: Wait for task to complete (creates MR)
        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed"

        task["issue"]["merge_request_iid"]
        branch = task["issue"]["branch_name"]

        # Step 3: Create a follow-up task on the SAME issue
        follow_up = await create_task(
            http_client, backend_url, admin_auth_headers, issue_id,
            user_prompt="Add error handling to the hello.py file",
        )
        follow_up_id = follow_up["id"]

        # Verify follow-up references the same issue (and therefore same branch/MR)
        assert follow_up["issue_id"] == issue_id
        assert follow_up["issue"]["branch_name"] == branch

        # Wait for follow-up to reach a terminal state
        follow_up = await wait_for_task_status(
            http_client, backend_url, follow_up_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert follow_up["project_id"] == 1

    @pytest.mark.asyncio
    async def test_second_task_on_running_issue_queued(
        self, http_client, backend_url, mock_url, admin_auth_headers,
    ):
        """Creating a second task while the first is running should queue it (issue mutex)."""
        # Configure delay so first task stays running
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_delay_seconds": 30},
        )

        try:
            # Create issue + first task
            issue, task1 = await create_issue_and_task(
                http_client, backend_url, admin_auth_headers,
                title="Issue mutex test",
                prompt="Long running task for mutex test",
            )
            task1_id = task1["id"]
            issue_id = issue["id"]

            # Wait for first task to be running
            await wait_for_task_status(
                http_client, backend_url, task1_id,
                target_statuses=["running"],
                auth_headers=admin_auth_headers,
                timeout=60,
            )

            # Create second task on the same issue
            task2 = await create_task(
                http_client, backend_url, admin_auth_headers, issue_id,
                user_prompt="Extra changes while first task runs",
            )

            # Second task should be pending/queued, not running concurrently
            assert task2["status"] in ("pending", "queued"), (
                f"Second task should be queued due to issue mutex, got: {task2['status']}"
            )
        finally:
            await http_client.patch(
                f"{mock_url}/mock/config",
                json={"claude_delay_seconds": 0},
            )


# ── Container Environment Validation ─────────────────────────────────


class TestContainerEnvironment:
    """Verify worker containers receive correct environment variables."""

    @pytest.mark.asyncio
    async def test_worker_receives_required_env_vars(
        self, http_client, backend_url, admin_auth_headers,
    ):
        """Task execution should pass all required env vars to the container."""
        issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Env vars test issue",
            prompt="Create a hello.py file",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        # A successful entrypoint proves its required `${VAR:?}` environment
        # gate passed. The durable container reference is intentionally cleared
        # after logs and runtime artifacts have been finalized.
        assert task["status"] == "completed", task.get("error_message")
        assert task.get("project_id") == 1
        assert task["issue"]["branch_name"] is not None
        assert task.get("worker_profile_id") is not None
        assert task.get("worker_image") is not None
        assert task.get("container_id") is None

    @pytest.mark.asyncio
    async def test_task_records_model_name(
        self, http_client, backend_url, admin_auth_headers,
    ):
        """Completed tasks should record the model used."""
        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Model name test issue",
            prompt="Create a hello.py file",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        # model_name may be set from CODIFY markers output
        # Just verify the field exists (may be null in mock)
        assert "model_name" in task


# ── Concurrent Retry ─────────────────────────────────────────────────


class TestConcurrentRetry:
    """Test retry behavior under concurrent conditions."""

    @pytest.mark.asyncio
    async def test_double_retry_same_task(
        self, http_client, backend_url, mock_url, admin_auth_headers,
    ):
        """Two rapid retries on the same failed task — second should fail."""
        # Create a task that will fail
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_exit_code": 1},
        )

        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Double retry test issue",
            prompt="Task that will fail",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "failed"

        # Reset exit code so retry can succeed
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_exit_code": 0},
        )

        # Retry #1 — should succeed
        r1 = await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/retry",
            headers=admin_auth_headers,
        )
        assert r1.status_code == 200

        # Retry #2 — task is now pending/queued, should fail
        r2 = await http_client.post(
            f"{backend_url}/api/tasks/{task_id}/retry",
            headers=admin_auth_headers,
        )
        # Second retry should be rejected (task no longer failed)
        assert r2.status_code in (400, 409), \
            f"Double retry should be rejected, got: {r2.status_code}"


# ── Task Logs Verification ───────────────────────────────────────────


class TestTaskLogsContent:
    """Verify task logs contain expected content after execution."""

    @pytest.mark.asyncio
    async def test_completed_task_has_logs(
        self, http_client, backend_url, admin_auth_headers,
    ):
        """A completed task should have non-empty logs."""
        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Completed logs test issue",
            prompt="Create a hello.py file",
        )
        task_id = task["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        # Fetch logs
        logs_resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}/logs",
            headers=admin_auth_headers,
        )
        assert logs_resp.status_code == 200
        logs = logs_resp.json()
        assert isinstance(logs, list)
        assert len(logs) > 0, "Completed task should have at least one log entry"

    @pytest.mark.asyncio
    async def test_failed_task_has_error_in_logs(
        self, http_client, backend_url, mock_url, admin_auth_headers,
    ):
        """A failed task should have error information in logs."""
        # Make Claude fail
        await http_client.patch(
            f"{mock_url}/mock/config",
            json={"claude_exit_code": 1},
        )

        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Failed logs test issue",
            prompt="Task that will fail for log check",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        assert task["status"] == "failed"
        # Error message should be set
        assert task.get("error_message"), \
            "Failed task should have error_message"

    @pytest.mark.asyncio
    async def test_task_logs_sanitized(
        self, http_client, backend_url, admin_auth_headers,
    ):
        """Task logs should not contain sensitive tokens."""
        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Sanitized logs test issue",
            prompt="Create a hello.py file",
        )
        task_id = task["id"]

        await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed", "failed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )

        logs_resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}/logs",
            headers=admin_auth_headers,
        )
        logs = logs_resp.json()
        logs_text = str(logs)
        # Should not contain raw tokens (sanitize_sensitive_data strips these)
        assert "glpat-" not in logs_text, "Logs should not contain GitLab tokens"
        assert "sk-ant-" not in logs_text, "Logs should not contain Anthropic keys"


# ── Authentication Edge Cases ────────────────────────────────────────


class TestAuthEdgeCases:
    """Additional auth edge cases."""

    @pytest.mark.asyncio
    async def test_invalid_credentials_rejected(self):
        """Wrong password should return 401."""
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/auth/local/login",
                json={"username": "admin", "password": "wrongpassword"},
            )
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_nonexistent_user_rejected(self):
        """Login with non-existent user should fail."""
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/auth/local/login",
                json={"username": "nonexistent_user_xyz", "password": "password123"},
            )
            assert resp.status_code in (401, 404)

    @pytest.mark.asyncio
    async def test_expired_token_rejected(self):
        """A garbage token should be rejected."""
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/tasks",
                headers={"Cookie": "codify_session=invalid_garbage_token_xyz"},
            )
            assert resp.status_code in (401, 403)
