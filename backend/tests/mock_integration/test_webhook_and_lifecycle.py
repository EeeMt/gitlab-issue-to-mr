"""Webhook advanced scenarios and task lifecycle edge cases.

Tests generic prompt handling, additional event filtering,
config reset, network isolation, and task state transitions.
"""

import asyncio
import json
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
        assert resp.status_code in (200, 201), f"Register failed: {resp.text}"
        return _extract_auth(resp)


# ── Generic Prompt Handling ──────────────────────────────────────────


class TestGenericPromptHandling:
    """When user sends a generic prompt like '@ai-bot 实现这个',
    webhook should use issue title+description as the full prompt."""

    @pytest.mark.asyncio
    async def test_generic_prompt_start(self, admin_headers):
        """'start' is a generic prompt — should include issue context."""
        async with httpx.AsyncClient(timeout=30) as client:
            payload = build_webhook_payload(
                project_id=1,
                issue_iid=random.randint(10000, 89999) + 5000,
                prompt="start",
            )
            payload["object_attributes"]["id"] = random.randint(100000, 999999)
            resp = await send_webhook(client, BACKEND_URL, payload)
            assert resp.status_code == 200
            task_id = resp.json()["task_id"]

            task_resp = await client.get(
                f"{BACKEND_URL}/api/tasks/{task_id}",
                headers=admin_headers,
            )
            task = task_resp.json()
            prompt = task.get("user_prompt", "")
            assert "Test Issue" in prompt or "test issue" in prompt.lower() or len(prompt) > len("start"), \
                f"Generic prompt 'start' should be expanded with issue context, got: {prompt[:200]}"

    @pytest.mark.asyncio
    async def test_generic_prompt_implement_this(self, admin_headers):
        """'implement this' is generic — should fetch issue details."""
        async with httpx.AsyncClient(timeout=30) as client:
            iid = random.randint(10000, 89999) + 6000
            payload = build_webhook_payload(
                project_id=1,
                issue_iid=iid,
                prompt="implement this",
            )
            payload["object_attributes"]["id"] = random.randint(100000, 999999)
            resp = await send_webhook(client, BACKEND_URL, payload)
            assert resp.status_code == 200
            task_id = resp.json()["task_id"]

            task_resp = await client.get(
                f"{BACKEND_URL}/api/tasks/{task_id}",
                headers=admin_headers,
            )
            task = task_resp.json()
            prompt = task.get("user_prompt", "")
            assert len(prompt) > len("implement this"), \
                f"Generic prompt should be expanded, got: {prompt[:200]}"

    @pytest.mark.asyncio
    async def test_specific_prompt_preserved(self, admin_headers):
        """A specific prompt should be preserved (not replaced by issue context)."""
        async with httpx.AsyncClient(timeout=30) as client:
            specific_prompt = "Create a REST API endpoint for user authentication with JWT tokens"
            iid = random.randint(10000, 89999) + 7000
            payload = build_webhook_payload(
                project_id=1,
                issue_iid=iid,
                prompt=specific_prompt,
            )
            # Ensure unique note_id to avoid dedup
            payload["object_attributes"]["id"] = random.randint(100000, 999999)
            resp = await send_webhook(client, BACKEND_URL, payload)
            assert resp.status_code == 200
            data = resp.json()
            assert "task_id" in data, f"Webhook should create task: {data}"
            task_id = data["task_id"]

            task_resp = await client.get(
                f"{BACKEND_URL}/api/tasks/{task_id}",
                headers=admin_headers,
            )
            task = task_resp.json()
            prompt = task.get("user_prompt", "")
            # Specific prompt should be preserved (may have issue context appended)
            assert "REST API endpoint" in prompt or "user authentication" in prompt, \
                f"Specific prompt should be preserved, got: {prompt[:200]}"


# ── Additional Webhook Event Filtering ───────────────────────────────


class TestWebhookEventFiltering:
    """Verify non-note events are silently ignored."""

    @pytest.mark.asyncio
    async def test_pipeline_event_ignored(self):
        """Pipeline events should be ignored."""
        async with httpx.AsyncClient(timeout=10) as client:
            payload = {
                "object_kind": "pipeline",
                "object_attributes": {
                    "id": 12345,
                    "status": "success",
                },
                "project": {
                    "id": 1,
                    "name": "test-project",
                },
            }
            resp = await client.post(
                f"{BACKEND_URL}/api/webhook/gitlab",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Gitlab-Token": WEBHOOK_SECRET,
                    "X-Gitlab-Event": "Pipeline Hook",
                },
            )
            # Should return 200 with ignored status (not create a task)
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("status") in ("ignored", "skipped") or "task_id" not in data

    @pytest.mark.asyncio
    async def test_issue_event_ignored(self):
        """Issue state change events (open/close) should not create tasks."""
        async with httpx.AsyncClient(timeout=10) as client:
            payload = {
                "object_kind": "issue",
                "event_type": "issue",
                "object_attributes": {
                    "id": 1001,
                    "iid": 100,
                    "title": "Some issue",
                    "state": "opened",
                    "action": "open",
                },
                "project": {
                    "id": 1,
                    "name": "test-project",
                },
            }
            resp = await client.post(
                f"{BACKEND_URL}/api/webhook/gitlab",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Gitlab-Token": WEBHOOK_SECRET,
                    "X-Gitlab-Event": "Issue Hook",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("status") in ("ignored", "skipped") or "task_id" not in data

    @pytest.mark.asyncio
    async def test_merge_request_event_ignored(self):
        """MR state change events (open/merge/close) without @ai-bot should be ignored."""
        async with httpx.AsyncClient(timeout=10) as client:
            payload = {
                "object_kind": "merge_request",
                "event_type": "merge_request",
                "object_attributes": {
                    "id": 2001,
                    "iid": 200,
                    "title": "Some MR",
                    "state": "opened",
                    "action": "open",
                },
                "project": {
                    "id": 1,
                    "name": "test-project",
                },
            }
            resp = await client.post(
                f"{BACKEND_URL}/api/webhook/gitlab",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Gitlab-Token": WEBHOOK_SECRET,
                    "X-Gitlab-Event": "Merge Request Hook",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("status") in ("ignored", "skipped") or "task_id" not in data


# ── Runtime Config API ───────────────────────────────────────────────


class TestRuntimeConfigEndpoint:
    """Test /config/runtime GET, PATCH, DELETE endpoints."""

    @pytest.mark.asyncio
    async def test_get_runtime_config(self, admin_headers):
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/config/runtime",
                headers=admin_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, dict)

    @pytest.mark.asyncio
    async def test_patch_runtime_config(self, admin_headers):
        """Set a runtime config value and verify it persists."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.patch(
                f"{BACKEND_URL}/api/config/runtime",
                headers=admin_headers,
                json={"max_concurrency": "5"},
            )
            assert resp.status_code == 200

            # Read back
            get_resp = await client.get(
                f"{BACKEND_URL}/api/config/runtime",
                headers=admin_headers,
            )
            data = get_resp.json()
            assert data.get("max_concurrency") == "5" or data.get("max_concurrency") == 5

    @pytest.mark.asyncio
    async def test_delete_runtime_config_key(self, admin_headers):
        """Reset a specific runtime config key."""
        async with httpx.AsyncClient(timeout=10) as client:
            # Set first
            await client.patch(
                f"{BACKEND_URL}/api/config/runtime",
                headers=admin_headers,
                json={"max_concurrency": "99"},
            )

            # Delete/reset
            resp = await client.delete(
                f"{BACKEND_URL}/api/config/runtime/max_concurrency",
                headers=admin_headers,
            )
            # Should succeed (200 or 204)
            assert resp.status_code in (200, 204)

    @pytest.mark.asyncio
    async def test_runtime_config_requires_auth(self):
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BACKEND_URL}/api/config/runtime")
            assert resp.status_code in (401, 403)


# ── Webhook with MR Comment ─────────────────────────────────────────


class TestMRCommentWebhookTaskCreation:
    """MR comment webhook creates a follow-up task when a completed task exists."""

    @pytest.mark.asyncio
    async def test_mr_comment_requires_prior_task(self):
        """@ai-bot on MR without prior completed task should be ignored."""
        async with httpx.AsyncClient(timeout=10) as client:
            iid = random.randint(10000, 89999) + 8000
            payload = build_webhook_payload(
                project_id=1,
                issue_iid=iid,
                prompt="Fix the failing test",
                noteable_type="MergeRequest",
            )
            payload["merge_request"] = {
                "id": iid * 1000,
                "iid": iid,
                "title": f"MR #{iid}",
                "state": "opened",
                "source_branch": f"feature/mr-{iid}",
                "target_branch": "main",
            }

            resp = await send_webhook(client, BACKEND_URL, payload)
            assert resp.status_code == 200
            data = resp.json()
            # Should be ignored because no prior task exists for this MR
            assert data.get("status") == "ignored"
            assert "task_id" not in data


# ── Task State Transition Verification ───────────────────────────────


class TestTaskStateTransitions:
    """Verify tasks go through correct state transitions."""

    @pytest.mark.asyncio
    async def test_task_passes_through_queued_and_running(self, admin_headers):
        """A task should transition through multiple states to completed."""
        async with httpx.AsyncClient(timeout=30) as client:
            # Configure delay so we can observe intermediate states
            await client.post(
                f"{MOCK_SERVICES_URL}/mock/config",
                json={"claude_delay_seconds": 5},
            )

            try:
                iid = random.randint(10000, 89999) + 9000
                payload = build_webhook_payload(project_id=1, issue_iid=iid)
                payload["object_attributes"]["id"] = random.randint(100000, 999999)
                resp = await send_webhook(client, BACKEND_URL, payload)
                task_id = resp.json()["task_id"]

                observed_states = set()
                for _ in range(60):
                    task_resp = await client.get(
                        f"{BACKEND_URL}/api/tasks/{task_id}",
                        headers=admin_headers,
                    )
                    if task_resp.status_code == 200:
                        state = task_resp.json()["status"]
                        observed_states.add(state)
                        if state in ("completed", "failed"):
                            break
                    await asyncio.sleep(2)

                assert "completed" in observed_states or "failed" in observed_states, \
                    f"Task should complete, observed: {observed_states}"
                assert len(observed_states) >= 2, \
                    f"Should observe multiple states, got: {observed_states}"
            finally:
                await client.post(
                    f"{MOCK_SERVICES_URL}/mock/config",
                    json={"claude_delay_seconds": 0},
                )

    @pytest.mark.asyncio
    async def test_completed_task_has_timestamps(self, admin_headers):
        """Completed tasks should have created_at, updated_at, and started_at."""
        async with httpx.AsyncClient(timeout=30) as client:
            iid = random.randint(10000, 89999) + 9100
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
            assert task.get("created_at") is not None
            assert task.get("updated_at") is not None
            if task["status"] == "completed":
                assert task.get("started_at") is not None, "Completed task should have started_at"


# ── Logout ───────────────────────────────────────────────────────────


class TestLogout:
    """Test logout endpoint."""

    @pytest.mark.asyncio
    async def test_logout_invalidates_session(self):
        """After logout, the session token should no longer work."""
        async with httpx.AsyncClient(timeout=10) as client:
            # Login
            login_resp = await client.post(
                f"{BACKEND_URL}/api/auth/local/login",
                json={"username": "admin", "password": "admin123"},
            )
            headers = _extract_auth(login_resp)

            # Verify session works
            me_resp = await client.get(
                f"{BACKEND_URL}/api/auth/me",
                headers=headers,
            )
            assert me_resp.status_code == 200
            assert me_resp.json().get("authenticated") is True

            # Logout
            logout_resp = await client.post(
                f"{BACKEND_URL}/api/auth/logout",
                headers=headers,
            )
            assert logout_resp.status_code == 200

            # Verify session is invalidated
            me_resp2 = await client.get(
                f"{BACKEND_URL}/api/auth/me",
                headers=headers,
            )
            # Should be unauthenticated or return 401
            if me_resp2.status_code == 200:
                assert me_resp2.json().get("authenticated") is False
            else:
                assert me_resp2.status_code in (401, 403)
