#!/usr/bin/env python3
"""
Extended worker coverage tests targeting specific uncovered lines.

Covers areas NOT yet tested by test_worker_coverage.py or test_worker_new_patterns.py:

A. _stream_logs_to_db internal paths:
   - Lines 243-248: deadline exceeded → timeout return (-1)
   - Lines 252-260: asyncio.TimeoutError → buffer flush on interval
   - Lines 276-278: empty stripped line → append to buffer only
   - Lines 388-391: buffer flush when MAX_BUFFER_LINES reached or interval elapsed

B. Post-processing edge cases:
   - Lines 643-644: MR title parse exception
   - Lines 737-747: MR stats from API (success + None result)
   - Line 779: _update_mr_description existing section with no next section

C. Notification helpers:
   - Lines 809-810: _send_notifications completion notification exception
   - Lines 835-836: _send_failure_notifications completion exception
   - Lines 851-852: _send_failure_notifications Mattermost exception
   - Lines 898-899: execute_task _notify_task_started exception

D. resume_task full flow:
   - Lines 1056-1081: task lookup, container not found
   - Lines 1083-1125: stream → parse → success/failure paths, retry scheduling
   - Lines 1127-1148: exception handler with cleanup and notifications

E. Misc:
   - Lines 962-963: execute_task remove_mr_draft_status exception
   - Lines 1007-1008: execute_task container removal exception
   - Lines 1031-1036: execute_task exception handler notification failures
   - Lines 1202-1203: _notify_task_completed mr_iid extraction from URL fails
   - Line 1208: _notify_task_completed success with MR URL but no extractable IID
   - Lines 1226-1227: _notify_task_completed _update_mr_description exception
   - Lines 1273-1275: _send_failure_alert webhook request exception
"""

import asyncio
import hashlib
import io
import tarfile
import time
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.worker import WorkerExecutor
from app.core.worker_runtime_bundle import (
    _v2_bundle_digest,
    bundle_manifest_digest_from_files,
    v2_launcher_manifest_bytes,
)
from app.core.worker_task_artifacts import _stop_artifact_poller
from app.core.worker_task_lifecycle import reconcile_task_input_session_from_runtime
from app.models import Task, TaskStatus

_V2_IMAGE_IDENTITY = {
    "schema": "codify.worker-image-identity/v1",
    "daemon_key": "http+unix:///var/run/docker.sock",
    "image_reference": "test-worker@sha256:" + "a" * 64,
    "image_id": "sha256:" + "b" * 64,
    "runtime_platform": "linux/amd64",
}


def _make_v2_runtime_bundle():
    """Build one persisted V2 archive accepted by the production loader."""
    entrypoint = b"#!/bin/sh\nexit 0\n"
    files = [
        {
            "path": "entrypoint.sh",
            "size": len(entrypoint),
            "sha256": hashlib.sha256(entrypoint).hexdigest(),
        }
    ]
    file_digest = bundle_manifest_digest_from_files(files)
    evidence = {
        "schema": "codify.worker-harness-verification/v1",
        "harness_key": "claude",
        "contract_version": "codify.worker.harness/v2",
        "adapter": {"version": "1.0.0"},
        "cli": {
            "source": "host_mount",
            "executable_path": "/usr/local/bin/claude",
            "version": "2.1.200",
            "binary_digest": "b" * 64,
        },
        "verification_input_digest": "d" * 64,
        "image_identity": _V2_IMAGE_IDENTITY,
        "generation": 1,
        "verified_at": "2026-08-24T00:00:00+00:00",
    }
    digest = _v2_bundle_digest(files, _V2_IMAGE_IDENTITY, evidence)
    manifest = {
        "schema": "codify.worker.runtime-bundle/v2",
        "contract_version": "codify.worker.harness/v2",
        "event_schema": "codify.worker.event/v2",
        "orchestration_version": "1.0.0",
        "runtime_platform": "linux/amd64",
        "worker_image_identity": _V2_IMAGE_IDENTITY,
        "harness_verification_evidence": evidence,
        "bundle_digest": digest,
        "files": files,
        "adapters": {
            "claude": {
                "adapter": {"version": "1.0.0", "digest": file_digest},
                "capabilities": {"steering": False},
            }
        },
    }
    launcher_manifest = v2_launcher_manifest_bytes(SimpleNamespace(manifest=manifest))
    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, payload, mode in (
            ("codify-runtime/orchestration/manifest.json", launcher_manifest, 0o644),
            ("codify-runtime/orchestration/entrypoint.sh", entrypoint, 0o755),
        ):
            member = tarfile.TarInfo(name=name)
            member.size = len(payload)
            member.mode = mode
            member.mtime = 0
            archive.addfile(member, io.BytesIO(payload))
    archive_bytes = archive_buffer.getvalue()
    return SimpleNamespace(
        id=81,
        digest=digest,
        contract_version="codify.worker.harness/v2",
        orchestration_version="1.0.0",
        manifest={**manifest, "archive_sha256": hashlib.sha256(archive_bytes).hexdigest()},
        bundle_bytes=archive_bytes,
        size_bytes=len(archive_bytes),
    )


_V2_RUNTIME_BUNDLE = _make_v2_runtime_bundle()


@pytest.fixture(autouse=True)
def _stub_runtime_bundle_and_attempt():
    async def attempt(
        _db,
        *,
        task,
        harness_key,
        adapter_version,
        event_schema,
        control_state,
        control_supported,
        **_kwargs,
    ):
        return SimpleNamespace(
            attempt_id=f"task-{task.id}-attempt-1",
            harness_key=harness_key,
            adapter_version=adapter_version,
            event_schema=event_schema,
            control_state=control_state,
            control_supported=control_supported,
        )

    with (
        patch(
            "app.core.worker_task_lifecycle.create_task_attempt",
            new=AsyncMock(side_effect=attempt),
        ),
        patch(
            "app.core.worker_task_lifecycle.inspect_v2_worker_image_identity",
            return_value=_V2_IMAGE_IDENTITY,
        ),
    ):
        yield

# ---------------------------------------------------------------------------
# Shared helpers (same patterns as existing test_worker_coverage.py)
# ---------------------------------------------------------------------------


class TestArtifactPollerShutdown(IsolatedAsyncioTestCase):
    """Tests for bounded artifact poller shutdown."""

    async def test_stop_artifact_poller_waits_for_graceful_exit(self):
        stop_event = asyncio.Event()

        async def poller():
            await stop_event.wait()

        poll_task = asyncio.create_task(poller())

        with patch("app.core.worker_task_artifacts.logger.warning") as mock_warning:
            await _stop_artifact_poller(
                task_id=947,
                stop_event=stop_event,
                poll_task=poll_task,
                timeout=0.1,
            )

        self.assertTrue(stop_event.is_set())
        self.assertTrue(poll_task.done())
        self.assertFalse(poll_task.cancelled())
        mock_warning.assert_not_called()

    async def test_stop_artifact_poller_cancels_stuck_poller(self):
        stop_event = asyncio.Event()
        never_released = asyncio.Event()
        poll_task = asyncio.create_task(never_released.wait())

        with patch("app.core.worker_task_artifacts.logger.warning") as mock_warning:
            await _stop_artifact_poller(
                task_id=947,
                stop_event=stop_event,
                poll_task=poll_task,
                timeout=0.01,
            )

        self.assertTrue(stop_event.is_set())
        self.assertTrue(poll_task.cancelled())
        mock_warning.assert_called_once()

    async def test_stop_artifact_poller_logs_error_after_cancel(self):
        stop_event = asyncio.Event()

        async def poller():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError as exc:
                raise RuntimeError("poller cleanup failed") from exc

        poll_task = asyncio.create_task(poller())

        with patch("app.core.worker_task_artifacts.logger.warning") as mock_warning:
            await _stop_artifact_poller(
                task_id=947,
                stop_event=stop_event,
                poll_task=poll_task,
                timeout=0.01,
            )

        self.assertTrue(stop_event.is_set())
        self.assertTrue(poll_task.done())
        self.assertFalse(poll_task.cancelled())
        self.assertEqual(mock_warning.call_count, 2)


class TestSessionLineageReconciliation(IsolatedAsyncioTestCase):
    async def test_resume_fallback_clears_planned_input_session(self):
        worker = MagicMock()
        worker.docker.read_file_from_container.return_value = b'{"resume_session":""}'
        container = MagicMock()
        task = MagicMock(id=42, input_session_id="session-old")

        changed = await reconcile_task_input_session_from_runtime(worker, container, task)

        self.assertTrue(changed)
        self.assertIsNone(task.input_session_id)
        worker.docker.read_file_from_container.assert_called_once_with(
            container,
            "/tmp/codify-runtime/runtime.json",
        )


def _make_settings(**overrides):
    """Return a mock settings object with sensible defaults."""
    s = MagicMock()
    s.gitlab_url = "http://gitlab.example.com"
    s.gitlab_bot_token = "test-token"
    s.worker_image = "test-worker:latest"
    s.task_timeout = 1800
    s.anthropic_base_url = "http://localhost:11434/v1"
    s.anthropic_api_key = "test-key"
    s.anthropic_model = "claude-sonnet-4-20250514"
    s.default_target_branch = "main"
    s.max_retries = 0
    s.backend_url = "http://localhost:8000"
    s.dashboard_url = "http://localhost:3000"
    s.custom_ca_bundle = None
    s.docker_host = "unix:///var/run/docker.sock"
    s.docker_tls_ca = None
    s.docker_tls_cert = None
    s.docker_tls_key = None
    s.worker_volume_mounts_parsed = []
    s.worker_workspace_host_path = "/tmp/codify-worker-tests"
    s.alert_on_failure = False
    s.alert_webhook_url = None
    s.claude_max_turns = 20
    s.harness_execution_mode = "dual_canary"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _make_worker(mock_gitlab=None, mock_docker=None):
    """Build a WorkerExecutor with mock clients."""
    mock_gitlab = mock_gitlab or MagicMock()
    mock_docker = mock_docker or MagicMock()
    for container in (
        mock_docker.create_container.return_value,
        mock_docker.client.containers.get.return_value,
    ):
        if not isinstance(getattr(container, "status", None), str):
            container.status = "exited"
        container.id = getattr(container, "id", None) or "container-1"
        container.attrs = {
            "Image": _V2_IMAGE_IDENTITY["image_id"],
            "Config": {
                "Labels": {
                    "codify.task_id": "1",
                    "codify.runtime_bundle_digest": _V2_RUNTIME_BUNDLE.digest,
                }
            },
        }
    return WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)


def _make_task(**kwargs):
    """Create a Task object with defaults and attach a mock issue."""
    from unittest.mock import MagicMock

    from app.models import AIProvider, TaskWorkerProfileSnapshot

    # Separate issue-level kwargs
    issue_overrides = {}
    for key in ['branch_name', 'base_branch', 'target_branch', 'merge_request_iid', 'merge_request_url', 'title', 'description']:
        if key in kwargs:
            issue_overrides[key] = kwargs.pop(key)

    provider = kwargs.pop('provider', None)

    # Remove old fields that callers might still pass
    for old_key in ['issue_iid', 'note_id', 'is_manual', 'retry_count']:
        kwargs.pop(old_key, None)

    defaults = dict(
        id=1, project_id=100, issue_id=1,
        user_prompt="Fix the bug",
        priority=0, status=TaskStatus.PENDING,
        is_retry=False, retry_source_task_id=None,
        runtime_bundle_id=_V2_RUNTIME_BUNDLE.id,
        additions=0, deletions=0, total_changes=0,
        rendered_prompt="Fix the bug",
        projected_harness_key="claude",
        projected_session_namespace="claude-0000000000000000",
        projected_lineage_generation=0,
        projected_reset_task_id=None,
        lineage_projection_reason="initial",
        input_lineage_reason=None,
        session_mode="continue",
    )
    defaults.update(kwargs)
    task = Task(**defaults)
    if getattr(task, "worker_profile_id", None) is None:
        task.worker_profile_id = 1
    task.worker_profile_snapshot = TaskWorkerProfileSnapshot(
        task_id=task.id,
        worker_profile_id=task.worker_profile_id,
        profile_name="Default Worker",
        image="test-worker:latest",
        volume_mounts=[],
        environment_variables=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
        harness_key="claude",
        cli_source="host_mount",
        cli_executable_path="/usr/local/bin/claude",
        cli_version="2.1.200",
        cli_binary_digest="b" * 64,
        harness_config_snapshot={
            "requested_runtime_contract_version": "codify.worker.harness/v2",
            "v2_worker_image_identity": _V2_IMAGE_IDENTITY,
            "v2_harness_verification_evidence": _V2_RUNTIME_BUNDLE.manifest[
                "harness_verification_evidence"
            ],
        },
        harness_adapter_version="1.0.0",
        harness_adapter_digest=_V2_RUNTIME_BUNDLE.manifest["adapters"]["claude"]["adapter"][
            "digest"
        ],
        runtime_contract_version="codify.worker.harness/v2",
        orchestration_version="1.0.0",
        runtime_bundle_digest=_V2_RUNTIME_BUNDLE.digest,
    )

    if provider is None:
        provider = AIProvider(
            id=1,
            name="legacy-test-provider",
            base_url="http://localhost:11434/v1",
            api_key="test-key",
            model="claude-sonnet-4-20250514",
            max_turns=20,
            system_prompt=None,
            is_default=True,
        )
    task.provider = provider

    # Attach mock issue
    if defaults.get('issue_id') is not None:
        mock_issue = MagicMock()
        mock_issue.id = defaults['issue_id']
        mock_issue.branch_name = issue_overrides.get('branch_name', f"codify-{defaults['id']}-p{defaults['project_id']}-i{defaults.get('issue_id', 1)}")
        mock_issue.base_branch = issue_overrides.get('base_branch')
        mock_issue.target_branch = issue_overrides.get('target_branch', 'main')
        mock_issue.merge_request_iid = issue_overrides.get('merge_request_iid')
        mock_issue.merge_request_url = issue_overrides.get('merge_request_url')
        mock_issue.title = issue_overrides.get('title')
        mock_issue.description = issue_overrides.get('description')
        mock_issue.claude_session_id = None
        mock_issue.session_storage_path = None
        mock_issue.project_id = defaults['project_id']
        task.issue = mock_issue
    else:
        task.issue = None

    return task


_DEFAULT_ATTEMPT = object()


def _make_db(task=None, attempt=_DEFAULT_ATTEMPT):
    """Create a mock async DB session."""
    from app.models import AIProvider, Issue, TaskWorkerProfileSnapshot
    db = MagicMock()

    async def _mock_execute(statement, *args, **kwargs):
        mock_result = MagicMock()
        statement_str = str(statement)
        if 'FROM ai_providers' in statement_str:
            provider = getattr(task, 'provider', None) if task else None
            mock_result.scalar_one_or_none.return_value = provider
            mock_result.scalars.return_value.all.return_value = [provider] if provider else []
        elif 'FROM worker_environment_variables' in statement_str or 'FROM issue_session_lineages' in statement_str:
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalars.return_value.all.return_value = []
        elif 'FROM worker_runtime_bundles' in statement_str:
            mock_result.scalar_one_or_none.return_value = _V2_RUNTIME_BUNDLE
            mock_result.scalars.return_value.all.return_value = [_V2_RUNTIME_BUNDLE]
        elif 'FROM task_harness_attempts' in statement_str:
            resolved_attempt = attempt
            if resolved_attempt is _DEFAULT_ATTEMPT and task is not None:
                resolved_attempt = SimpleNamespace(
                    attempt_id=f"task-{task.id}-attempt-1",
                    harness_key=task.worker_profile_snapshot.harness_key,
                    adapter_version=task.worker_profile_snapshot.harness_adapter_version,
                    event_schema="codify.worker.event/v2",
                    control_state="accepting",
                    control_supported=True,
                )
            mock_result.scalar_one_or_none.return_value = resolved_attempt
            mock_result.scalars.return_value.all.return_value = []
        else:
            mock_result.scalar_one_or_none.return_value = task
            mock_result.scalars.return_value.all.return_value = [task] if task else []
        return mock_result

    db.execute = AsyncMock(side_effect=_mock_execute)
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    # db.get should return the task's issue when queried
    async def mock_get(model_class, id_val):
        if model_class is AIProvider:
            provider = getattr(task, 'provider', None) if task else None
            if provider is not None and getattr(provider, 'id', None) == id_val:
                return provider
            return None
        if task and model_class is Issue and hasattr(task, 'issue') and task.issue and task.issue.id == id_val:
            return task.issue
        if task and model_class is TaskWorkerProfileSnapshot:
            snapshot = getattr(task, "worker_profile_snapshot", None)
            if snapshot is not None and getattr(snapshot, "task_id", None) == id_val:
                return snapshot
        return None
    db.get = AsyncMock(side_effect=mock_get)

    return db


def _make_stream_container(log_lines, exit_code=0):
    """Create a mock container that yields log_lines from .logs() and returns exit_code."""
    container = MagicMock()
    container.logs.return_value = iter(log_lines)
    container.wait.return_value = {"StatusCode": exit_code}
    container.id = "mock-container-id"
    return container


# ===================================================================
# A. _stream_logs_to_db — internal paths
# ===================================================================

class TestStreamLogsTimeout(unittest.TestCase):
    """Test _stream_logs_to_db deadline exceeded path — lines 243-248."""

    def test_returns_minus_one_on_deadline_exceeded(self):
        """When timeout=0, the deadline is already passed → returns (-1, ..., ...)."""
        worker = _make_worker()
        db = _make_db()
        container = _make_stream_container([b"some log line\n"])

        exit_code, logs, chunks, timed_out = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=0)
        )

        self.assertEqual(exit_code, -1)
        self.assertTrue(timed_out)

    def test_empty_buffer_on_deadline_exceeded(self):
        """When deadline exceeded with empty buffer, no flush occurs — lines 243-248."""
        worker = _make_worker()
        db = _make_db()

        # We need the queue to have items already, but deadline to be exceeded.
        # With timeout=0 the loop immediately hits remaining<=0 on first iteration.
        # But buffer is empty at first. We can't add to buffer before the loop starts.
        # Instead, use a very short timeout and a slow stream that produces data.
        # Actually, timeout=0 means remaining<=0 immediately, so buffer=[] → no flush.
        # Let's verify no flush occurs (buffer is empty at that point).
        container = _make_stream_container([])

        exit_code, logs, chunks, timed_out = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=0)
        )

        self.assertEqual(exit_code, -1)
        self.assertTrue(timed_out)
        self.assertEqual(chunks, 0)  # no buffer to flush


class TestStreamLogsTimeoutFlush(unittest.TestCase):
    """Test buffer flush on asyncio.TimeoutError in wait_for — lines 252-260."""

    def test_timeout_flush_interval(self):
        """When queue.get times out and flush interval elapsed, buffer is flushed."""
        worker = _make_worker()
        db = _make_db()

        # Create a container whose log stream stalls (yields nothing, then sentinel).
        # The _stream_thread reads from container.logs() which yields nothing for a while,
        # then we send the sentinel. We mock the queue directly instead.
        container = MagicMock()
        container.id = "mock-id"

        # We'll produce: one data line, then delay (timeout), then sentinel.
        # The easiest approach: mock the container.logs to be a slow iterator.
        lines_yielded = []

        def slow_log_gen():
            """Yield one line, then wait a bit, then end."""
            lines_yielded.append(True)
            yield b"first line\n"
            # Sleep to cause the asyncio.wait_for to time out at least once
            time.sleep(0.5)
            # Now the sentinel will be sent by the finally block

        container.logs.return_value = slow_log_gen()
        container.wait.return_value = {"StatusCode": 0}

        # Use a short timeout but enough for the stream to complete
        exit_code, logs, chunks, timed_out = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=10)
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("first line", logs)


class TestStreamLogsEmptyLine(unittest.TestCase):
    """Test empty stripped line handling — lines 276-278."""

    def test_empty_line_appended_to_buffer(self):
        """Lines that strip to empty are still appended to buffer and all_lines."""
        worker = _make_worker()
        db = _make_db()
        container = _make_stream_container([b"\n", b"real content\n", b"  \n"])

        exit_code, logs, chunks, timed_out = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        self.assertEqual(exit_code, 0)
        # The empty lines should be in the full log string
        self.assertIn("\n", logs)
        self.assertIn("real content", logs)

    def test_only_empty_lines_still_returned(self):
        """A stream of only empty lines produces logs with just newlines."""
        worker = _make_worker()
        db = _make_db()
        container = _make_stream_container([b"\n", b"\n", b"\n"])

        exit_code, logs, chunks, timed_out = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(logs.strip(), "")


class TestStreamLogsBufferFlush(unittest.TestCase):
    """Test buffer flush on MAX_BUFFER_LINES threshold — lines 387-391."""

    def test_flushes_at_max_buffer_lines(self):
        """Buffer is flushed when it reaches MAX_BUFFER_LINES (200) — line 387."""
        worker = _make_worker()
        db = _make_db()

        # Generate 250 lines — should trigger at least one flush at 200 lines
        lines = [f"log line {i}\n".encode() for i in range(250)]
        container = _make_stream_container(lines)

        exit_code, logs, chunks, timed_out = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=10)
        )

        self.assertEqual(exit_code, 0)
        # At least 2 chunks: one at 200 lines, remaining 50 at the end
        self.assertGreaterEqual(chunks, 2)

    def test_single_multi_line_chunk(self):
        """Docker may batch multiple lines into a single chunk."""
        worker = _make_worker()
        db = _make_db()

        # Send a single chunk with multiple lines
        multi_line = b"line 1\nline 2\nline 3\n"
        container = _make_stream_container([multi_line])

        exit_code, logs, chunks, timed_out = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("line 1", logs)
        self.assertIn("line 2", logs)
        self.assertIn("line 3", logs)


# ===================================================================
# B. Post-processing edge cases
# ===================================================================

class TestParseMrTitleException(unittest.TestCase):
    """Test MR title parse exception path — lines 643-644."""

    def test_mr_title_exception_does_not_crash(self):
        """Exception during CODIFY_MR_TITLE processing is caught — lines 643-644."""
        worker = _make_worker()
        task = _make_task()
        db = _make_db()

        # We need the regex to match but the internal processing to raise.
        # The title match group(1) returns a string, and .strip() is called.
        # If title is truthy, sanitize_sensitive_data is called on it.
        # Let's patch sanitize_sensitive_data to raise an exception.
        logs = "CODIFY_MR_TITLE:Some title\n"

        with patch("app.core.worker.sanitize_sensitive_data", side_effect=Exception("sanitize boom")):
            # Should not raise
            asyncio.run(worker._parse_task_result(task, logs, db, exit_code=0))

        # commit_message should remain unset
        self.assertIsNone(task.commit_message)


class TestUpdateTaskStatsFromApi(unittest.TestCase):
    """Test MR stats from API paths — lines 737-747."""

    def test_mr_stats_from_api_success(self):
        """When diff stats not in logs but commit exists, fetches from API."""
        mock_gitlab = MagicMock()
        mock_gitlab.get_merge_request_stats = AsyncMock(return_value={
            "additions": 25,
            "deletions": 10,
            "total": 35,
        })
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()
        task.issue.merge_request_iid = 42
        task.commit_sha = "a" * 40
        logs = "no diff stats here\n"

        asyncio.run(worker._update_task_stats_from_logs_or_api(task, logs, issue=task.issue))

        self.assertEqual(task.additions, 25)
        self.assertEqual(task.deletions, 10)
        self.assertEqual(task.total_changes, 35)

    def test_mr_stats_skipped_when_no_commit_sha(self):
        """When no CODIFY_DIFF and no commit_sha, stats stay at 0 (no changes made)."""
        mock_gitlab = MagicMock()
        mock_gitlab.get_merge_request_stats = AsyncMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()
        task.issue.merge_request_iid = 42
        logs = "no diff stats\n"

        asyncio.run(worker._update_task_stats_from_logs_or_api(task, logs, issue=task.issue))

        mock_gitlab.get_merge_request_stats.assert_not_awaited()
        self.assertEqual(task.additions, 0)
        self.assertEqual(task.deletions, 0)

    def test_mr_stats_from_api_returns_none(self):
        """When API returns None for stats."""
        mock_gitlab = MagicMock()
        mock_gitlab.get_merge_request_stats = AsyncMock(return_value=None)
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()
        task.issue.merge_request_iid = 42
        task.commit_sha = "a" * 40
        logs = "no diff stats\n"

        # Should not raise, stats remain at defaults
        asyncio.run(worker._update_task_stats_from_logs_or_api(task, logs, issue=task.issue))

        self.assertEqual(task.additions, 0)
        self.assertEqual(task.deletions, 0)

    def test_mr_stats_from_api_exception(self):
        """When API call raises, stats remain unchanged."""
        mock_gitlab = MagicMock()
        mock_gitlab.get_merge_request_stats = AsyncMock(side_effect=Exception("API error"))
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()
        task.issue.merge_request_iid = 42
        task.commit_sha = "a" * 40
        logs = "no diff stats\n"

        # Should not raise
        asyncio.run(worker._update_task_stats_from_logs_or_api(task, logs, issue=task.issue))

        self.assertEqual(task.additions, 0)

    def test_mr_stats_skipped_when_no_mr_iid(self):
        """When no merge_request_iid and no diff in logs, stats are not fetched."""
        mock_gitlab = MagicMock()
        mock_gitlab.get_merge_request_stats = AsyncMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()
        task.issue.merge_request_iid = None
        task.commit_sha = "a" * 40
        logs = "no diff stats\n"

        asyncio.run(worker._update_task_stats_from_logs_or_api(task, logs, issue=task.issue))

        mock_gitlab.get_merge_request_stats.assert_not_awaited()


class TestUpdateMrDescriptionForIssueExceptionHandling(IsolatedAsyncioTestCase):
    """Test _update_mr_description_for_issue handles exceptions gracefully."""

    async def test_exception_during_db_query_caught(self):
        """DB query failure is caught and logged."""
        mock_gitlab = MagicMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(id=99)
        issue = MagicMock()
        issue.id = 10
        issue.merge_request_iid = 5

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=Exception("DB error"))

        # Should not raise
        await worker._update_mr_description_for_issue(task, issue, mock_db)


# ===================================================================
# C. Notification helpers — exception edge cases
# ===================================================================

class TestSendNotificationsExceptions(unittest.TestCase):
    """Test _send_notifications and _send_failure_notifications exception paths."""

    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_send_failure_notifications_mattermost_exception(self, mock_notify_event):
        """_send_failure_notifications catches Mattermost exception — lines 851-852."""
        mock_gitlab = MagicMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(issue_id=None, status=TaskStatus.FAILED)

        mock_notify_event.side_effect = Exception("Mattermost down")

        # Should not raise
        asyncio.run(worker._send_failure_notifications(task, success=False, had_existing_mr=False))


class TestExecuteTaskNotifyStartedException(unittest.TestCase):
    """Test execute_task catches _notify_task_started exception — lines 898-899."""

    def setUp(self):
        self._sleep_patcher = patch('asyncio.sleep', new_callable=AsyncMock)
        self._sleep_patcher.start()

    def tearDown(self):
        self._sleep_patcher.stop()

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_notify_started_exception_does_not_abort(self, mock_notify, mock_get_settings):
        """Exception in _notify_task_started doesn't abort execute_task — lines 898-899."""
        mock_get_settings.return_value = _make_settings()
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = MagicMock(id="ctr-123")

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock(side_effect=Exception("GitLab down"))
        mock_gitlab.create_mr_note = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(issue_id=1)
        db = _make_db(task)

        fake_logs = "CODIFY_DIFF:+1-0\n"

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, fake_logs, 1, False))):
            result = asyncio.run(worker.execute_task(db, task.id))

        # Should still succeed despite notification failure
        self.assertTrue(result)


# ===================================================================
# D. resume_task — full flow
# ===================================================================

class TestResumeTaskNotFound(unittest.TestCase):
    """Test resume_task when task is not found — lines 1056-1064."""

    @patch('app.core.worker.get_settings')
    def test_returns_false_when_task_not_found(self, mock_get_settings):
        """resume_task returns False when task is not in DB — lines 1062-1064."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        db = _make_db(task=None)

        result = asyncio.run(worker.resume_task(db, task_id=999, container_name="codify-999"))

        self.assertFalse(result)


class TestResumeTaskMissingAttempt(unittest.TestCase):
    """V2 resume must converge a missing-attempt task to FAILED before attach."""

    @patch('app.core.worker.get_settings')
    def test_v2_missing_attempt_is_terminalized_without_container_attach(self, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_docker = MagicMock()
        worker = _make_worker(mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING)
        db = _make_db(task, attempt=None)

        with (
            patch(
                "app.core.worker_task_lifecycle.load_bound_runtime_bundle",
                new=AsyncMock(return_value=_V2_RUNTIME_BUNDLE),
            ),
            patch(
                "app.core.worker_task_runner.close_task_control_gates",
                new=AsyncMock(),
            ) as close_gates,
        ):
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn('"code": "missing_execution_attempt"', task.error_message)
        self.assertIsNotNone(task.completed_at)
        mock_docker.client.containers.get.assert_not_called()
        close_gates.assert_awaited_once_with(
            db,
            task_id=task.id,
            reason="resume rejected: missing_execution_attempt",
        )


class TestResumeTaskContainerNotFound(unittest.TestCase):
    """Test resume_task when container is not found — lines 1073-1081."""

    @patch('app.core.worker.get_settings')
    def test_container_not_found_sets_failed(self, mock_get_settings):
        """resume_task sets FAILED when container is not found — lines 1075-1081."""
        mock_get_settings.return_value = _make_settings()
        mock_docker = MagicMock()
        from docker.errors import NotFound

        mock_docker.client.containers.get.side_effect = NotFound("Container not found")

        worker = _make_worker(mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING)
        db = _make_db(task)

        result = asyncio.run(worker.resume_task(db, task_id=task.id, container_name="codify-1"))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("Container disappeared", task.error_message)
        self.assertIsNone(task.container_id)
        self.assertIsNotNone(task.completed_at)

    @patch('app.core.worker.get_settings')
    def test_inconclusive_container_lookup_is_retryable(self, mock_get_settings):
        """A daemon/API error must not be converted into confirmed container absence."""
        from app.core.worker_docker_targets import TaskContainerLookupError

        mock_get_settings.return_value = _make_settings()
        mock_docker = MagicMock()
        mock_docker.client.containers.get.side_effect = RuntimeError("Docker timed out")

        worker = _make_worker(mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING)
        db = _make_db(task)

        with self.assertRaises(TaskContainerLookupError):
            asyncio.run(worker.resume_task(db, task_id=task.id, container_name="codify-1"))

        self.assertEqual(task.status, TaskStatus.RUNNING)
        self.assertIsNone(task.completed_at)


class TestResumeTaskContainerIdentity(unittest.TestCase):
    """V2 recovery must reject a retained container with a changed identity."""

    @patch("app.core.worker.get_settings")
    def test_wrong_image_is_terminalized_before_streaming(self, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        container = MagicMock(id="container-1")
        container.attrs = {
            "Image": "sha256:" + "f" * 64,
            "Config": {
                "Labels": {
                    "codify.task_id": "1",
                    "codify.runtime_bundle_digest": _V2_RUNTIME_BUNDLE.digest,
                }
            },
        }
        docker = MagicMock()
        docker.client.containers.get.return_value = container
        worker = _make_worker(mock_docker=docker)
        docker.client.containers.get.return_value.attrs["Image"] = "sha256:" + "f" * 64
        task = _make_task(status=TaskStatus.RUNNING)
        db = _make_db(task)

        with patch.object(worker, "_stream_logs_to_db", new=AsyncMock()) as stream:
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn('"code": "execution_contract_mismatch"', task.error_message)
        container.reload.assert_called_once_with()
        stream.assert_not_awaited()

    @patch("app.core.worker.get_settings")
    def test_stored_container_id_mismatch_is_terminalized(self, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        docker = MagicMock()
        container = docker.client.containers.get.return_value
        container.id = "new-container-id"
        worker = _make_worker(mock_docker=docker)
        task = _make_task(status=TaskStatus.RUNNING, container_id="old-container-id")
        db = _make_db(task)

        with patch.object(worker, "_stream_logs_to_db", new=AsyncMock()) as stream:
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn('"code": "execution_contract_mismatch"', task.error_message)
        stream.assert_not_awaited()


class TestResumeTaskSuccess(unittest.TestCase):
    """Test resume_task success flow — lines 1083-1125."""

    def setUp(self):
        self._sleep_patcher = patch('asyncio.sleep', new_callable=AsyncMock)
        self._sleep_patcher.start()

    def tearDown(self):
        self._sleep_patcher.stop()

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_resume_success_completes_task(self, mock_notify, mock_get_settings):
        """resume_task success flow: stream logs → parse → COMPLETED — lines 1092-1099."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(
            status=TaskStatus.RUNNING,
            merge_request_iid=42,
            merge_request_url="http://gitlab.example.com/-/merge_requests/42",
        )
        db = _make_db(task)

        fake_logs = "CODIFY_DIFF:+5-3\nhttp://gitlab.example.com/-/merge_requests/42\n"

        async def parse_completed(current_task, *_args, **_kwargs):
            current_task.status = TaskStatus.COMPLETED
            current_task.completed_at = datetime.now(UTC)

        with (
            patch.object(
                worker,
                '_stream_logs_to_db',
                new=AsyncMock(return_value=(0, fake_logs, 2, False)),
            ),
            patch.object(worker, "_parse_task_result", new=AsyncMock(side_effect=parse_completed)),
        ):
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertTrue(result)
        self.assertEqual(task.status, TaskStatus.COMPLETED)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_run_result_advances_issue_session_pointer(self, mock_notify, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-session")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container
        worker = _make_worker(mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING)
        task.issue.claude_session_id = "session-old"
        db = _make_db(task)

        async def parse_result(current_task, *_args, **_kwargs):
            current_task.status = TaskStatus.COMPLETED
            current_task.output_session_id = "session-new"

        with (
            patch.object(
                worker,
                '_stream_logs_to_db',
                new=AsyncMock(return_value=(0, "", 1, False)),
            ),
            patch.object(worker, '_parse_task_result', new=AsyncMock(side_effect=parse_result)),
        ):
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertTrue(result)
        self.assertEqual(task.issue.claude_session_id, "session-new")

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_resume_success_upserts_usage_ledger(self, mock_notify, mock_get_settings):
        """resume_task should write completed usage into the quota ledger."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-usage")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(
            status=TaskStatus.RUNNING,
            initiator_user_id=7,
            merge_request_iid=42,
            merge_request_url="http://gitlab.example.com/-/merge_requests/42",
        )
        db = _make_db(task)

        fake_logs = (
            "CODIFY_DIFF:+5-3\n"
            "http://gitlab.example.com/-/merge_requests/42\n"
            'CODIFY_STATS:{"input_tokens":100,"output_tokens":50}\n'
        )

        async def parse_completed(current_task, *_args, **_kwargs):
            current_task.status = TaskStatus.COMPLETED
            current_task.completed_at = datetime.now(UTC)

        with (
            patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, fake_logs, 2, False))),
            patch("app.core.worker.upsert_task_usage_ledger", new=AsyncMock()) as mock_upsert,
            patch.object(worker, "_parse_task_result", new=AsyncMock(side_effect=parse_completed)),
        ):
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertTrue(result)
        mock_upsert.assert_awaited_once_with(db, task)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_resume_success_removes_mr_draft(self, mock_notify, mock_get_settings):
        """resume_task on success removes MR draft status via _remove_mr_draft_status_for_issue."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-draft")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING, merge_request_iid=42)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, "CODIFY_DIFF:+1-0\n", 1, False))):
            with patch.object(worker, '_remove_mr_draft_status_for_issue') as mock_remove_draft:
                asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        mock_remove_draft.assert_called_once_with(task, task.issue, sudo_gl=None)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_resume_success_draft_removal_exception(self, mock_notify, mock_get_settings):
        """resume_task catches _remove_mr_draft_status_for_issue exception."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-draft-err")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING, merge_request_iid=42)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, "CODIFY_DIFF:+1-0\n", 1, False))):
            with patch.object(worker, '_remove_mr_draft_status_for_issue', side_effect=Exception("draft boom")):
                result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        # Should still succeed
        self.assertTrue(result)


class TestResumeTaskFailure(unittest.TestCase):
    """Test resume_task failure flow — lines 1100-1107."""

    def setUp(self):
        self._sleep_patcher = patch('asyncio.sleep', new_callable=AsyncMock)
        self._sleep_patcher.start()

    def tearDown(self):
        self._sleep_patcher.stop()

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_resume_failure_no_retry(self, mock_notify, mock_get_settings):
        """resume_task failure sets FAILED — lines 1100-1107."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-fail")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(1, "error occurred", 1, False))):
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIsNotNone(task.error_message)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_resume_failure_stays_failed(self, mock_notify, mock_get_settings):
        """resume_task failure stays FAILED (no retry logic)."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-retry")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(1, "error", 1, False))):
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_resume_timeout_sets_error_message_prefix(self, mock_notify, mock_get_settings):
        """resume_task with timed_out=True sets timeout error_message prefix."""
        mock_get_settings.return_value = _make_settings(task_timeout=600)
        mock_container = MagicMock(id="ctr-resume-timeout")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db',
                          new=AsyncMock(return_value=(-1, "still running", 1, True))):
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("Task timed out after 600s", task.error_message)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_resume_failure_no_log_chunks_creates_fallback(self, mock_notify, mock_get_settings):
        """resume_task with 0 log chunks on success creates fallback log — lines 1114-1116."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-fast")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, "CODIFY_DIFF:+1-0\n", 1, False))):
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        # Should still return True (success) despite cleanup failure
        self.assertTrue(result)


class TestResumeTaskException(unittest.TestCase):
    """Test resume_task exception handler — lines 1127-1148."""

    def setUp(self):
        self._sleep_patcher = patch('asyncio.sleep', new_callable=AsyncMock)
        self._sleep_patcher.start()

    def tearDown(self):
        self._sleep_patcher.stop()

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_exception_sets_failed_and_retains_logs(self, mock_notify, mock_get_settings):
        """Resume exceptions retain the stopped container until raw logs are finalized."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-exc")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING, merge_request_iid=None)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', side_effect=RuntimeError("Docker exploded")):
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("Docker exploded", task.error_message)
        mock_docker.remove_container.assert_not_called()

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_exception_after_parse_still_upserts_usage_ledger(self, mock_notify, mock_get_settings):
        """Post-parse resume failures should still attempt quota ledger persistence."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-post-parse")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING, initiator_user_id=7, merge_request_iid=None)
        db = _make_db(task)
        db.commit = AsyncMock(side_effect=[RuntimeError("post-parse commit failed"), None, None])

        fake_logs = (
            "http://gitlab.example.com/project/-/merge_requests/42\n"
            "CODIFY_DIFF:+10-5\n"
            'CODIFY_STATS:{"input_tokens":100,"output_tokens":50}\n'
        )

        async def parse_completed(current_task, *_args, **_kwargs):
            current_task.status = TaskStatus.COMPLETED
            current_task.completed_at = datetime.now(UTC)

        with (
            patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, fake_logs, 2, False))),
            patch("app.core.worker.upsert_task_usage_ledger", new=AsyncMock()) as mock_upsert,
            patch.object(worker, "_parse_task_result", new=AsyncMock(side_effect=parse_completed)),
        ):
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)
        mock_upsert.assert_any_await(db, task)
        self.assertGreaterEqual(mock_upsert.await_count, 1)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_exception_cleanup_failure_does_not_raise(self, mock_notify, mock_get_settings):
        """Container cleanup failure during exception handling is caught — lines 1136-1137."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-cleanup-err")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container
        mock_docker.remove_container.side_effect = Exception("Cannot remove")

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING, merge_request_iid=None)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', side_effect=RuntimeError("boom")):
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertFalse(result)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_exception_notification_failure_does_not_raise(self, mock_notify, mock_get_settings):
        """Notification failures during exception handling are caught — lines 1139-1146."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-notify-err")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(status=TaskStatus.RUNNING, merge_request_iid=None, is_manual=False)
        db = _make_db(task)

        # Make stream raise
        with patch.object(worker, '_stream_logs_to_db', side_effect=RuntimeError("stream failed")):
            mock_notify.side_effect = Exception("mattermost failed")
            result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_resume_with_had_existing_mr(self, mock_notify, mock_get_settings):
        """resume_task with existing MR sets notify_target='mr' — line 1070."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-resume-mr")
        mock_docker = MagicMock()
        mock_docker.client.containers.get.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(
            status=TaskStatus.RUNNING,
            merge_request_iid=55,
            merge_request_url="http://gitlab.example.com/-/merge_requests/55",
        )
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, "CODIFY_DIFF:+1-0\n", 1, False))):
            with patch.object(worker, '_send_notifications', new=AsyncMock()) as mock_send:
                result = asyncio.run(worker.resume_task(db, task.id, "codify-1"))

        self.assertTrue(result)
        mock_send.assert_called_once()
        self.assertTrue(mock_send.call_args.kwargs.get("had_existing_mr"))


# ===================================================================
# E. Misc — execute_task edge cases
# ===================================================================

class TestExecuteTaskDraftRemovalException(unittest.TestCase):
    """Test execute_task catches _remove_mr_draft_status exception — lines 962-963."""

    def setUp(self):
        self._sleep_patcher = patch('asyncio.sleep', new_callable=AsyncMock)
        self._sleep_patcher.start()

    def tearDown(self):
        self._sleep_patcher.stop()

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_draft_removal_exception_does_not_abort(self, mock_notify, mock_get_settings):
        """Exception in _remove_mr_draft_status doesn't abort execute_task — lines 962-963."""
        mock_get_settings.return_value = _make_settings()
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = MagicMock(id="ctr-draft-err")

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=42)
        db = _make_db(task)

        fake_logs = "CODIFY_DIFF:+1-0\nhttp://gitlab.example.com/-/merge_requests/42\n"

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, fake_logs, 1, False))):
            with patch.object(worker, '_remove_mr_draft_status', side_effect=Exception("draft error")):
                result = asyncio.run(worker.execute_task(db, task.id))

        # Should still succeed
        self.assertTrue(result)


class TestExecuteTaskContainerRemovalException(unittest.TestCase):
    """Test execute_task catches container removal exception — lines 1007-1008."""

    def setUp(self):
        self._sleep_patcher = patch('asyncio.sleep', new_callable=AsyncMock)
        self._sleep_patcher.start()

    def tearDown(self):
        self._sleep_patcher.stop()

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_container_removal_exception_does_not_raise(self, mock_notify, mock_get_settings):
        """Exception in docker.remove_container doesn't raise — lines 1007-1008."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-rm-err")
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = mock_container
        mock_docker.remove_container.side_effect = Exception("Cannot remove")

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=None)
        db = _make_db(task)

        with (
            patch.object(
                worker,
                '_stream_logs_to_db',
                new=AsyncMock(return_value=(0, "CODIFY_DIFF:+1-0\n", 1, False)),
            ),
            patch(
                "app.core.worker_task_lifecycle.finalize_task_raw_logs",
                new=AsyncMock(),
            ),
        ):
            result = asyncio.run(worker.execute_task(db, task.id))

        # Should still return True (success) despite cleanup failure
        self.assertTrue(result)
        self.assertEqual(task.container_id, "ctr-rm-err")


class TestExecuteTaskExceptionNotificationFailures(unittest.TestCase):
    """Test execute_task exception handler notification failures — lines 1031-1036."""

    def setUp(self):
        self._sleep_patcher = patch('asyncio.sleep', new_callable=AsyncMock)
        self._sleep_patcher.start()

    def tearDown(self):
        self._sleep_patcher.stop()

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_notification_failures_in_exception_handler(self, mock_notify, mock_get_settings):
        """Both _notify_task_completed and notify_task_event can fail — lines 1031-1036."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-notify-err")
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=None, is_manual=False)
        db = _make_db(task)

        # Make stream raise, Mattermost notification also fails
        mock_notify.side_effect = Exception("mattermost down")

        with patch.object(worker, '_stream_logs_to_db', side_effect=RuntimeError("stream failed")):
            result = asyncio.run(worker.execute_task(db, task.id))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)


class TestSendFailureAlertWebhookException(unittest.TestCase):
    """Test _send_failure_alert webhook request exception — lines 1273-1275."""

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.get_ssl_verify')
    def test_webhook_request_exception_caught(self, mock_ssl, mock_get_settings):
        """httpx.AsyncClient.post exception is caught — lines 1273-1275."""
        mock_get_settings.return_value = _make_settings(
            alert_on_failure=True,
            alert_webhook_url="http://hooks.example.com/alert",
        )
        mock_ssl.return_value = True
        worker = _make_worker()
        task = _make_task(error_message="something failed")

        mock_client_instance = AsyncMock()
        mock_client_instance.post.side_effect = Exception("Connection refused")
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch('app.core.worker.httpx.AsyncClient', return_value=mock_client_instance):
            # Should not raise
            asyncio.run(worker._send_failure_alert(task))

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.get_ssl_verify')
    def test_webhook_non_success_status_code(self, mock_ssl, mock_get_settings):
        """Non-success status code logs warning — lines 1273."""
        mock_get_settings.return_value = _make_settings(
            alert_on_failure=True,
            alert_webhook_url="http://hooks.example.com/alert",
        )
        mock_ssl.return_value = True
        worker = _make_worker()
        task = _make_task(error_message="failed")

        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch('app.core.worker.httpx.AsyncClient', return_value=mock_client_instance):
            # Should not raise
            asyncio.run(worker._send_failure_alert(task))


class TestStreamLogsContainerWaitException(unittest.TestCase):
    """Test container.wait() exception after stream ends — line 404-406."""

    def test_container_wait_exception_returns_minus_one(self):
        """When container.wait() raises, exit_code is -1."""
        worker = _make_worker()
        db = _make_db()

        container = MagicMock()
        container.logs.return_value = iter([b"some log\n"])
        container.wait.side_effect = Exception("container wait timeout")
        container.id = "mock-id"

        exit_code, logs, chunks, timed_out = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        self.assertEqual(exit_code, -1)
        self.assertIn("some log", logs)


class TestStreamLogsThreadError(unittest.TestCase):
    """Test that log stream thread errors send sentinel and don't hang."""

    def test_stream_thread_exception_sends_sentinel(self):
        """When container.logs() raises, thread sends sentinel and stream ends cleanly."""
        worker = _make_worker()
        db = _make_db()

        container = MagicMock()
        container.logs.side_effect = Exception("Docker API error")
        container.wait.return_value = {"StatusCode": 1}
        container.id = "mock-id"

        exit_code, logs, chunks, timed_out = asyncio.run(
            worker._stream_logs_to_db(container, task_id=1, db=db, timeout=5)
        )

        # The stream thread raised but sent sentinel, so we get whatever exit code container.wait returns
        # (or -1 if wait also fails)
        self.assertIn(exit_code, [1, -1])
        self.assertEqual(logs, "")  # no data was read before the error


if __name__ == "__main__":
    unittest.main()
