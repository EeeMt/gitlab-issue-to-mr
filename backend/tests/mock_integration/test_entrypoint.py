"""Entrypoint.sh logic tests — MR updates, CODIFY markers, no-MR mode, base branch.

Tests specific behaviors of the real entrypoint.sh (683 lines) that runs
inside worker containers with mock external services.

Prerequisites:
    docker-compose -f backend/tests/mock_integration/docker-compose.mock-test.yml up -d
"""

import logging

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


class TestMRDescription:
    """Verify entrypoint.sh updates MR description during execution."""

    async def test_mr_description_updated_on_completion(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """MR description should be updated at least once during task execution."""
        payload = build_webhook_payload(
            project_id=1,
            issue_iid=200,
            prompt="Create a utility function",
        )
        resp = await send_webhook(http_client, backend_url, payload)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed"

        # Check that MR was updated (PUT /merge_requests/:iid called)
        gitlab_calls = await get_mock_calls(http_client, mock_url, service="gitlab")
        mr_update_calls = [
            c for c in gitlab_calls
            if c["method"] == "PUT" and "/merge_requests/" in c["path"]
        ]
        assert len(mr_update_calls) >= 1, (
            f"Expected at least 1 MR update call, got {len(mr_update_calls)}. "
            f"All calls: {[c['path'] for c in gitlab_calls]}"
        )
        logger.info(f"✅ MR updated {len(mr_update_calls)} time(s) during task {task_id}")


class TestCODIFYMarkersDetailed:
    """Verify specific CODIFY markers are emitted and parsed."""

    async def test_commit_sha_parsed(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """CODIFY_COMMIT_SHA should be parsed into task.commit_sha."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Create a file for commit SHA test",
                "branch_name": "codify/commit-sha-test",
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
        # commit_sha comes from entrypoint.sh running git rev-parse HEAD
        assert task.get("commit_sha"), "commit_sha should be set from CODIFY_COMMIT_SHA"
        assert len(task["commit_sha"]) == 40, f"commit_sha should be 40 chars, got: {task['commit_sha']}"
        logger.info(f"✅ commit_sha: {task['commit_sha']}")

    async def test_mr_url_parsed(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """merge_request_url should be parsed from container logs."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Create a file for MR URL test",
                "branch_name": "codify/mr-url-test",
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
        assert task.get("merge_request_url"), "merge_request_url should be set"
        assert "/merge_requests/" in task["merge_request_url"]
        logger.info(f"✅ MR URL: {task['merge_request_url']}")

    async def test_task_logs_recorded(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Task execution should produce log entries."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Create a file for logs test",
                "branch_name": "codify/logs-test",
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

        # Fetch logs
        resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}/logs",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        logs = resp.json()
        assert len(logs) > 0, "Expected task logs to be recorded"
        logger.info(f"✅ {len(logs)} log entries recorded for task {task_id}")


class TestNoMRMode:
    """Verify no-MR mode: target_branch=None skips MR creation."""

    async def test_no_mr_mode_completes(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Task with target_branch=None should complete without creating an MR."""
        resp = await http_client.post(
            f"{backend_url}/api/tasks",
            json={
                "project_id": 1,
                "user_prompt": "Create a file in no-MR mode",
                "branch_name": "codify/no-mr-test",
                # target_branch intentionally omitted (None → no-MR mode)
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
            f"No-MR mode task should complete but got: {task['status']} - "
            f"{task.get('error_message', '')}"
        )

        # In no-MR mode, merge_request_url should NOT be set
        # (entrypoint.sh skips MR creation when TARGET_BRANCH is empty)
        # Note: commit_sha should still be set since code was pushed
        assert task.get("commit_sha"), "commit_sha should still be set in no-MR mode"

        # Verify no MR was created in mock GitLab
        gitlab_calls = await get_mock_calls(http_client, mock_url, service="gitlab")
        mr_create_calls = [
            c for c in gitlab_calls
            if c["method"] == "POST" and "/merge_requests" in c["path"]
            and "notes" not in c["path"]
        ]
        assert len(mr_create_calls) == 0, (
            f"No MR should be created in no-MR mode, but found: {mr_create_calls}"
        )
        logger.info(f"✅ No-MR mode completed: task {task_id}, no MR created")


class TestGitOperations:
    """Verify git clone/push operations go through mock server."""

    async def test_git_clone_and_push(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Verify both git clone and push operations are recorded."""
        payload = build_webhook_payload(
            project_id=1,
            issue_iid=201,
            prompt="Create a file to verify git operations",
        )
        resp = await send_webhook(http_client, backend_url, payload)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed"

        # Verify git operations
        git_calls = await get_mock_calls(http_client, mock_url, service="git")
        git_paths = [c["path"] for c in git_calls]

        # Should have both clone (info/refs + upload-pack) and push (receive-pack)
        has_info_refs = any("info/refs" in p for p in git_paths)
        has_receive_pack = any("receive-pack" in p for p in git_paths)
        has_upload_pack = any("upload-pack" in p for p in git_paths)

        assert has_info_refs, f"Expected info/refs call, got: {git_paths}"
        assert has_upload_pack, f"Expected upload-pack call (clone), got: {git_paths}"
        assert has_receive_pack, f"Expected receive-pack call (push), got: {git_paths}"

        logger.info(f"✅ Git clone+push verified: {len(git_calls)} git operations")
