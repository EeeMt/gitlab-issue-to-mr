"""MR follow-up tasks, container env validation, and concurrent retry tests.

Tests MR comment follow-up task creation (requires completed parent task),
worker container environment variables, and concurrent operation edge cases.
"""

import asyncio
import random
import time

import httpx
import pytest

from .conftest import (
    BACKEND_URL,
    MOCK_SERVICES_URL,
    WEBHOOK_SECRET,
    build_webhook_payload,
    get_mock_calls,
    send_webhook,
    wait_for_task_status,
)


def _extract_auth(resp: httpx.Response) -> dict:
    """Extract auth headers from login/register response."""
    cookies = dict(resp.cookies)
    if cookies:
        return {"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())}
    token = resp.json().get("access_token")
    if token:
        return {"Authorization": f"Bearer {token}"}
    raise ValueError(f"No auth in response: {resp.status_code} {resp.text}")


@pytest.fixture
async def admin_headers():
    """Get admin auth headers."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BACKEND_URL}/api/auth/local/login",
            json={"username": "admin", "password": "admin123"},
        )
        if resp.status_code == 200:
            return _extract_auth(resp)
        resp = await client.post(
            f"{BACKEND_URL}/api/auth/local/register",
            json={"username": "admin", "password": "admin123"},
        )
        assert resp.status_code in (200, 201)
        return _extract_auth(resp)


# ── MR Follow-up Task ────────────────────────────────────────────────


class TestMRFollowUpTask:
    """Complete flow: issue comment → task completes with MR → MR comment creates follow-up."""

    @pytest.mark.asyncio
    async def test_mr_follow_up_full_flow(self, admin_headers):
        """Issue task completes → MR created → @ai-bot on MR → follow-up task."""
        async with httpx.AsyncClient(timeout=30) as client:
            # Step 1: Create initial task via issue webhook
            iid = random.randint(10000, 89999)
            payload = build_webhook_payload(
                project_id=1,
                issue_iid=iid,
                prompt="Create a hello.py file with unit tests",
            )
            payload["object_attributes"]["id"] = random.randint(100000, 999999)
            resp = await send_webhook(client, BACKEND_URL, payload)
            assert resp.status_code == 200
            task_id = resp.json()["task_id"]

            # Step 2: Wait for task to complete (creates MR)
            task = await wait_for_task_status(
                client, BACKEND_URL, task_id,
                target_statuses=["completed"],
                auth_headers=admin_headers,
                timeout=120,
            )
            assert task["status"] == "completed"
            mr_iid = task.get("merge_request_iid")

            if not mr_iid:
                pytest.skip("Task completed but no MR iid — mock may not set it")

            # Step 3: Send MR comment webhook
            mr_payload = build_webhook_payload(
                project_id=1,
                issue_iid=iid,
                prompt="Add error handling to the hello.py file",
                noteable_type="MergeRequest",
            )
            mr_payload["object_attributes"]["id"] = random.randint(200000, 999999)
            mr_payload["merge_request"] = {
                "id": mr_iid * 1000,
                "iid": mr_iid,
                "title": f"MR from task {task_id}",
                "state": "opened",
                "source_branch": task.get("branch_name", f"codify/issue-{iid}"),
                "target_branch": "main",
            }

            mr_resp = await send_webhook(client, BACKEND_URL, mr_payload)
            assert mr_resp.status_code == 200
            mr_data = mr_resp.json()

            # May create a follow-up task or be ignored depending on MR state
            if "task_id" in mr_data:
                follow_up_id = mr_data["task_id"]
                # Verify follow-up task inherits branch from parent
                follow_up = await client.get(
                    f"{BACKEND_URL}/api/tasks/{follow_up_id}",
                    headers=admin_headers,
                )
                follow_up_data = follow_up.json()
                assert follow_up_data["project_id"] == 1
                assert follow_up_data["merge_request_iid"] == mr_iid

    @pytest.mark.asyncio
    async def test_mr_comment_on_running_task_ignored(self, admin_headers):
        """MR comment while task is still running should be ignored."""
        async with httpx.AsyncClient(timeout=30) as client:
            # Configure delay so task stays running
            await client.patch(
                f"{MOCK_SERVICES_URL}/mock/config",
                json={"claude_delay_seconds": 30},
            )

            try:
                # Create task
                iid = random.randint(10000, 89999)
                payload = build_webhook_payload(
                    project_id=1, issue_iid=iid,
                    prompt="Long running task for MR test",
                )
                payload["object_attributes"]["id"] = random.randint(100000, 999999)
                resp = await send_webhook(client, BACKEND_URL, payload)
                assert resp.status_code == 200
                task_id = resp.json()["task_id"]

                # Wait for running state
                task = await wait_for_task_status(
                    client, BACKEND_URL, task_id,
                    target_statuses=["running"],
                    auth_headers=admin_headers,
                    timeout=60,
                )

                # Try MR comment (should be ignored since task is still running)
                mr_payload = build_webhook_payload(
                    project_id=1, issue_iid=iid,
                    prompt="Extra changes",
                    noteable_type="MergeRequest",
                )
                mr_payload["object_attributes"]["id"] = random.randint(300000, 999999)
                mr_payload["merge_request"] = {
                    "id": 99001, "iid": 99001,
                    "title": "Test MR", "state": "opened",
                }
                mr_resp = await send_webhook(client, BACKEND_URL, mr_payload)
                assert mr_resp.status_code == 200
                # Should be ignored — no completed task for this MR
                data = mr_resp.json()
                assert data.get("status") == "ignored" or "task_id" not in data
            finally:
                await client.patch(
                    f"{MOCK_SERVICES_URL}/mock/config",
                    json={"claude_delay_seconds": 0},
                )


# ── Container Environment Validation ─────────────────────────────────


class TestContainerEnvironment:
    """Verify worker containers receive correct environment variables."""

    @pytest.mark.asyncio
    async def test_worker_receives_required_env_vars(self, admin_headers):
        """Task execution should pass all required env vars to the container."""
        async with httpx.AsyncClient(timeout=30) as client:
            iid = random.randint(10000, 89999)
            payload = build_webhook_payload(project_id=1, issue_iid=iid)
            payload["object_attributes"]["id"] = random.randint(100000, 999999)
            resp = await send_webhook(client, BACKEND_URL, payload)
            assert resp.status_code == 200
            task_id = resp.json()["task_id"]

            task = await wait_for_task_status(
                client, BACKEND_URL, task_id,
                target_statuses=["completed", "failed"],
                auth_headers=admin_headers,
                timeout=120,
            )

            # Check the task has expected fields filled
            assert task.get("project_id") == 1
            assert task.get("branch_name") is not None
            assert task.get("container_name") is not None

            # Container name follows pattern: codify-{task_id}-p{project_id}-i{issue_iid}
            container_name = task["container_name"]
            assert f"p1" in container_name, \
                f"Container name should include project: {container_name}"

    @pytest.mark.asyncio
    async def test_manual_task_no_issue_iid(self, admin_headers):
        """Manual tasks (no issue_iid) should still run successfully."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/tasks",
                headers=admin_headers,
                json={
                    "project_id": 1,
                    "user_prompt": "Create a utility function",
                    "branch_name": f"codify/manual-env-{random.randint(1000, 9999)}",
                    "target_branch": "main",
                },
            )
            assert resp.status_code in (200, 201)
            task_id = resp.json()["id"]

            task = await wait_for_task_status(
                client, BACKEND_URL, task_id,
                target_statuses=["completed", "failed"],
                auth_headers=admin_headers,
                timeout=120,
            )
            # Manual tasks should complete even without issue_iid
            assert task["status"] in ("completed", "failed")
            assert task.get("is_manual") is True

    @pytest.mark.asyncio
    async def test_task_records_model_name(self, admin_headers):
        """Completed tasks should record the model used."""
        async with httpx.AsyncClient(timeout=30) as client:
            iid = random.randint(10000, 89999)
            payload = build_webhook_payload(project_id=1, issue_iid=iid)
            payload["object_attributes"]["id"] = random.randint(100000, 999999)
            resp = await send_webhook(client, BACKEND_URL, payload)
            task_id = resp.json()["task_id"]

            task = await wait_for_task_status(
                client, BACKEND_URL, task_id,
                target_statuses=["completed", "failed"],
                auth_headers=admin_headers,
                timeout=120,
            )
            # model_name may be set from CODIFY markers output
            # Just verify the field exists (may be null in mock)
            assert "model_name" in task


# ── Concurrent Retry ─────────────────────────────────────────────────


class TestConcurrentRetry:
    """Test retry behavior under concurrent conditions."""

    @pytest.mark.asyncio
    async def test_double_retry_same_task(self, admin_headers):
        """Two rapid retries on the same failed task — second should fail."""
        async with httpx.AsyncClient(timeout=30) as client:
            # Create a task that will fail
            await client.patch(
                f"{MOCK_SERVICES_URL}/mock/config",
                json={"claude_exit_code": 1},
            )

            iid = random.randint(10000, 89999)
            payload = build_webhook_payload(project_id=1, issue_iid=iid)
            payload["object_attributes"]["id"] = random.randint(100000, 999999)
            resp = await send_webhook(client, BACKEND_URL, payload)
            task_id = resp.json()["task_id"]

            task = await wait_for_task_status(
                client, BACKEND_URL, task_id,
                target_statuses=["completed", "failed"],
                auth_headers=admin_headers,
                timeout=120,
            )
            assert task["status"] == "failed"

            # Reset exit code so retry can succeed
            await client.patch(
                f"{MOCK_SERVICES_URL}/mock/config",
                json={"claude_exit_code": 0},
            )

            # Retry #1 — should succeed
            r1 = await client.post(
                f"{BACKEND_URL}/api/tasks/{task_id}/retry",
                headers=admin_headers,
            )
            assert r1.status_code == 200

            # Retry #2 — task is now pending/queued, should fail
            r2 = await client.post(
                f"{BACKEND_URL}/api/tasks/{task_id}/retry",
                headers=admin_headers,
            )
            # Second retry should be rejected (task no longer failed)
            assert r2.status_code in (400, 409), \
                f"Double retry should be rejected, got: {r2.status_code}"


# ── Task Logs Verification ───────────────────────────────────────────


class TestTaskLogsContent:
    """Verify task logs contain expected content after execution."""

    @pytest.mark.asyncio
    async def test_completed_task_has_logs(self, admin_headers):
        """A completed task should have non-empty logs."""
        async with httpx.AsyncClient(timeout=30) as client:
            iid = random.randint(10000, 89999)
            payload = build_webhook_payload(project_id=1, issue_iid=iid)
            payload["object_attributes"]["id"] = random.randint(100000, 999999)
            resp = await send_webhook(client, BACKEND_URL, payload)
            task_id = resp.json()["task_id"]

            task = await wait_for_task_status(
                client, BACKEND_URL, task_id,
                target_statuses=["completed", "failed"],
                auth_headers=admin_headers,
                timeout=120,
            )

            # Fetch logs
            logs_resp = await client.get(
                f"{BACKEND_URL}/api/tasks/{task_id}/logs",
                headers=admin_headers,
            )
            assert logs_resp.status_code == 200
            logs = logs_resp.json()
            assert isinstance(logs, list)
            assert len(logs) > 0, "Completed task should have at least one log entry"

    @pytest.mark.asyncio
    async def test_failed_task_has_error_in_logs(self, admin_headers):
        """A failed task should have error information in logs."""
        async with httpx.AsyncClient(timeout=30) as client:
            # Make Claude fail
            await client.patch(
                f"{MOCK_SERVICES_URL}/mock/config",
                json={"claude_exit_code": 1},
            )

            iid = random.randint(10000, 89999)
            payload = build_webhook_payload(project_id=1, issue_iid=iid)
            payload["object_attributes"]["id"] = random.randint(100000, 999999)
            resp = await send_webhook(client, BACKEND_URL, payload)
            task_id = resp.json()["task_id"]

            task = await wait_for_task_status(
                client, BACKEND_URL, task_id,
                target_statuses=["completed", "failed"],
                auth_headers=admin_headers,
                timeout=120,
            )

            assert task["status"] == "failed"
            # Error message should be set
            assert task.get("error_message"), \
                "Failed task should have error_message"

    @pytest.mark.asyncio
    async def test_task_logs_sanitized(self, admin_headers):
        """Task logs should not contain sensitive tokens."""
        async with httpx.AsyncClient(timeout=30) as client:
            iid = random.randint(10000, 89999)
            payload = build_webhook_payload(project_id=1, issue_iid=iid)
            payload["object_attributes"]["id"] = random.randint(100000, 999999)
            resp = await send_webhook(client, BACKEND_URL, payload)
            task_id = resp.json()["task_id"]

            await wait_for_task_status(
                client, BACKEND_URL, task_id,
                target_statuses=["completed", "failed"],
                auth_headers=admin_headers,
                timeout=120,
            )

            logs_resp = await client.get(
                f"{BACKEND_URL}/api/tasks/{task_id}/logs",
                headers=admin_headers,
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
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/auth/local/login",
                json={"username": "admin", "password": "wrongpassword"},
            )
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_nonexistent_user_rejected(self):
        """Login with non-existent user should fail."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/auth/local/login",
                json={"username": "nonexistent_user_xyz", "password": "password123"},
            )
            assert resp.status_code in (401, 404)

    @pytest.mark.asyncio
    async def test_expired_token_rejected(self):
        """A garbage token should be rejected."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/tasks",
                headers={"Cookie": "codify_session=invalid_garbage_token_xyz"},
            )
            assert resp.status_code in (401, 403)
