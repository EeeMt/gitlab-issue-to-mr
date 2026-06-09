"""Entrypoint.sh logic tests — MR updates, event projection, no-MR mode, git ops.

Tests specific behaviors of the real entrypoint.sh that runs inside worker
containers with mock external services. Uses the Issue → Task flow.

Prerequisites:
    docker-compose -f backend/tests/mock_integration/docker-compose.mock-test.yml up -d
"""

import json
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
        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="MR description update test",
            prompt="Create a utility function",
        )
        task_id = task["id"]

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
    """Verify structured event records are projected to task logs."""

    async def test_commit_sha_parsed(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """CODIFY_COMMIT_SHA should be parsed into task.commit_sha."""
        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Commit SHA test",
            prompt="Create a file for commit SHA test",
        )
        task_id = task["id"]

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
        """merge_request_url should be parsed from container logs (on Issue, not Task)."""
        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="MR URL test",
            prompt="Create a file for MR URL test",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed"
        # merge_request_url is now on the nested issue object
        issue_data = task.get("issue", {})
        assert issue_data.get("merge_request_url"), "issue.merge_request_url should be set"
        assert "/merge_requests/" in issue_data["merge_request_url"]
        logger.info(f"✅ MR URL: {issue_data['merge_request_url']}")

    async def test_task_logs_recorded(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Task execution should produce log entries."""
        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Logs recording test",
            prompt="Create a file for logs test",
        )
        task_id = task["id"]

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


class TestClaudeOutputTypes:
    """Verify all Claude output types (thinking/tool calls/text) are parsed and stored."""

    async def test_thinking_logs_created(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Stream event thinking blocks should create 'thinking' log entries."""
        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Thinking output test",
            prompt="Create files to test thinking output",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed"

        resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}/logs",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        logs = resp.json()

        thinking_logs = [l for l in logs if l.get("log_type") == "thinking"]
        assert len(thinking_logs) >= 2, (
            f"Expected at least 2 thinking entries, got {len(thinking_logs)}. "
            f"Log types: {[l.get('log_type') for l in logs]}"
        )

        # Verify thinking metadata references a payload (text stored separately)
        for tl in thinking_logs:
            meta = json.loads(tl["metadata"]) if isinstance(tl["metadata"], str) else tl["metadata"]
            assert "payload_id" in meta, f"Thinking log should have 'payload_id' field: {meta}"
            assert meta["char_count"] > 0, "Thinking char_count should be positive"

        logger.info(f"✅ {len(thinking_logs)} thinking entries verified for task {task_id}")

    async def test_tool_call_logs_with_results(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Assistant tool_use + user tool_result events should create tool_call logs with output."""
        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Tool call output test",
            prompt="Create files to test tool call output",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed"

        resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}/logs",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        logs = resp.json()

        tool_call_logs = [l for l in logs if l.get("log_type") == "tool_call"]
        assert len(tool_call_logs) >= 3, (
            f"Expected at least 3 tool_call entries (Read + 2x Write), got {len(tool_call_logs)}. "
            f"Log types: {[l.get('log_type') for l in logs]}"
        )

        # Verify tool call metadata structure
        tool_names = []
        for tc in tool_call_logs:
            meta = json.loads(tc["metadata"]) if isinstance(tc["metadata"], str) else tc["metadata"]
            assert "name" in meta, f"Tool call should have 'name': {meta}"
            assert "input_payload_id" in meta, f"Tool call should have 'input_payload_id': {meta}"
            # Output is stored as a referenced payload (output_payload_id)
            assert meta.get("output_payload_id") is not None, (
                f"Tool call output_payload_id should be populated: {meta}"
            )
            assert meta.get("error") is False, f"Tool call should not have error: {meta}"
            tool_names.append(meta["name"])

        # Verify we have the expected tool types
        assert "Read" in tool_names, f"Expected Read tool call, got: {tool_names}"
        assert tool_names.count("Write") >= 2, f"Expected 2+ Write calls, got: {tool_names}"

        logger.info(f"✅ {len(tool_call_logs)} tool_call entries verified: {tool_names}")

    async def test_assistant_text_logs_created(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Stream event text blocks should create 'assistant_text' log entries."""
        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Assistant text output test",
            prompt="Create files to test assistant text output",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed"

        resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}/logs",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        logs = resp.json()

        text_logs = [l for l in logs if l.get("log_type") == "assistant_text"]
        assert len(text_logs) >= 2, (
            f"Expected at least 2 assistant_text entries, got {len(text_logs)}. "
            f"Log types: {[l.get('log_type') for l in logs]}"
        )

        for tl in text_logs:
            meta = json.loads(tl["metadata"]) if isinstance(tl["metadata"], str) else tl["metadata"]
            assert "payload_id" in meta, f"Assistant text log should have 'payload_id' field: {meta}"

        logger.info(f"✅ {len(text_logs)} assistant_text entries verified")

    async def test_system_init_log_created(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """System init event should create 'system_init' log entry with model name."""
        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="System init test",
            prompt="Create a file for system init test",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed"

        resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}/logs",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        logs = resp.json()

        init_logs = [l for l in logs if l.get("log_type") == "system_init"]
        assert len(init_logs) >= 1, (
            f"Expected at least 1 system_init entry, got {len(init_logs)}. "
            f"Log types: {[l.get('log_type') for l in logs]}"
        )

        meta = json.loads(init_logs[0]["metadata"]) if isinstance(init_logs[0]["metadata"], str) else init_logs[0]["metadata"]
        assert meta.get("model") == "fake-claude-1.0", f"Expected model 'fake-claude-1.0', got: {meta}"

        # Also verify model_name is set on the task
        assert task.get("model_name") == "fake-claude-1.0", (
            f"Task model_name should be 'fake-claude-1.0', got: {task.get('model_name')}"
        )

        logger.info(f"✅ system_init verified: model={meta.get('model')}")

    async def test_all_output_types_in_correct_order(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        admin_auth_headers: dict,
    ):
        """Verify the complete sequence of Claude output types appears in order."""
        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Output sequence test",
            prompt="Create files for full output sequence test",
        )
        task_id = task["id"]

        task = await wait_for_task_status(
            http_client, backend_url, task_id,
            target_statuses=["completed"],
            auth_headers=admin_auth_headers,
            timeout=120,
        )
        assert task["status"] == "completed"

        resp = await http_client.get(
            f"{backend_url}/api/tasks/{task_id}/logs",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        logs = resp.json()

        # Extract typed log entries (exclude raw log chunks)
        typed_logs = [l for l in logs if l.get("log_type") in (
            "system_init", "thinking", "assistant_text", "tool_call"
        )]

        # Extract sequence of types
        type_sequence = [l["log_type"] for l in typed_logs]
        logger.info(f"Log type sequence: {type_sequence}")

        # system_init should come first among typed entries
        assert type_sequence[0] == "system_init", (
            f"First typed entry should be system_init, got: {type_sequence[0]}"
        )

        # Should have all expected types
        type_set = set(type_sequence)
        assert "thinking" in type_set, f"Missing 'thinking' in log types: {type_set}"
        assert "tool_call" in type_set, f"Missing 'tool_call' in log types: {type_set}"
        assert "assistant_text" in type_set, f"Missing 'assistant_text' in log types: {type_set}"

        # Verify counts
        assert type_sequence.count("thinking") >= 2, f"Expected 2+ thinking, got {type_sequence.count('thinking')}"
        assert type_sequence.count("tool_call") >= 3, f"Expected 3+ tool_call, got {type_sequence.count('tool_call')}"
        assert type_sequence.count("assistant_text") >= 2, f"Expected 2+ assistant_text, got {type_sequence.count('assistant_text')}"

        logger.info(
            f"✅ Full output sequence verified: "
            f"{type_sequence.count('thinking')} thinking, "
            f"{type_sequence.count('tool_call')} tool_call, "
            f"{type_sequence.count('assistant_text')} assistant_text"
        )


class TestNoMRMode:
    """Verify no-MR mode: target_branch=None skips MR creation."""

    async def test_no_mr_mode_completes(
        self,
        http_client: httpx.AsyncClient,
        backend_url: str,
        mock_url: str,
        admin_auth_headers: dict,
    ):
        """Issue with target_branch=None should complete task without creating an MR."""
        issue = await create_issue(
            http_client, backend_url, admin_auth_headers,
            title="No-MR mode test",
            description="Create a file in no-MR mode",
            target_branch=None,
        )
        task = await create_task(
            http_client, backend_url, admin_auth_headers, issue["id"],
            user_prompt="Create a file in no-MR mode",
        )
        task_id = task["id"]

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

        # In no-MR mode, merge_request_url on the issue should NOT be set
        # (entrypoint.sh skips MR creation when TARGET_BRANCH is empty)
        # Note: commit_sha should still be set since code was pushed
        assert task.get("commit_sha"), "commit_sha should still be set in no-MR mode"
        issue_data = task.get("issue", {})
        assert not issue_data.get("merge_request_url"), (
            "issue.merge_request_url should not be set in no-MR mode"
        )

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
        _issue, task = await create_issue_and_task(
            http_client, backend_url, admin_auth_headers,
            title="Git operations test",
            prompt="Create a file to verify git operations",
        )
        task_id = task["id"]

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
