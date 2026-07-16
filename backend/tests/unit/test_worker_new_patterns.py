#!/usr/bin/env python3
"""
Test: structured worker result parsing features.

Covers:
- model_name / commit_message included in _serialize_task output
- Legacy CODIFY_* text markers are correctly ignored by parse_task_result
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers shared across all test classes
# ---------------------------------------------------------------------------

def _make_mock_settings():
    """Return a fully-populated mock settings object."""
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
    return s


def create_mock_db(task):
    """Create a properly configured mock database session."""
    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = task
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db


def _make_worker():
    """Instantiate WorkerExecutor with mock docker/gitlab clients."""
    mock_gitlab = MagicMock()
    mock_docker = MagicMock()
    mock_docker.create_container.return_value = MagicMock(id="mock-container-id")

    from app.core.worker import WorkerExecutor
    return WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)


def _make_task(**kwargs):
    """Return a minimal Task instance with a mock issue attached."""
    from app.models import Task, TaskStatus
    defaults = dict(
        id=1,
        project_id=123,
        issue_id=1,
        user_prompt="Test prompt",
        priority=0,
        status=TaskStatus.PENDING,
        is_retry=False,
        retry_source_task_id=None,
        additions=0,
        deletions=0,
        total_changes=0,
    )
    defaults.update(kwargs)
    task = Task(**defaults)
    mock_issue = MagicMock()
    mock_issue.id = defaults.get('issue_id', 1)
    mock_issue.branch_name = "test-branch"
    mock_issue.base_branch = None
    mock_issue.target_branch = "main"
    mock_issue.merge_request_iid = None
    mock_issue.merge_request_url = None
    mock_issue.claude_session_id = None
    mock_issue.session_storage_path = None
    mock_issue.project_id = defaults['project_id']
    task.issue = mock_issue
    return task


# ---------------------------------------------------------------------------
# TestCodifySystemInitParsing
# ---------------------------------------------------------------------------

class TestCodifySystemInitParsing(unittest.TestCase):
    """Tests for model extraction from the structured system_init TaskLog entry."""

    def setUp(self):
        self.mock_settings = _make_mock_settings()
        self.patcher = patch('app.core.worker.get_settings', return_value=self.mock_settings)
        self.patcher.start()
        self.worker = _make_worker()

    def tearDown(self):
        self.patcher.stop()

    def _run_parse(
        self,
        task,
        logs,
        *,
        system_init_metadata=None,
        run_result_metadata=None,
        worker_finalization_metadata=None,
        exit_code=0,
    ):
        async def run():
            with patch.object(self.worker, '_parse_mr_from_logs', new=AsyncMock()):
                with patch.object(self.worker, '_update_task_stats_from_logs_or_api', new=AsyncMock()):
                    mock_db = create_mock_db(task)

                    metadata_by_type = {
                        "system_init": system_init_metadata,
                        "run_result": run_result_metadata,
                        "worker_finalization": worker_finalization_metadata,
                    }

                    async def mock_execute(stmt, *args, **kwargs):
                        try:
                            stmt_str = str(stmt.compile(compile_kwargs={"literal_binds": True}))
                        except Exception:
                            stmt_str = str(stmt)

                        result = MagicMock()
                        for log_type, metadata in metadata_by_type.items():
                            if log_type in stmt_str:
                                if metadata is None:
                                    result.scalar_one_or_none.return_value = None
                                else:
                                    log_entry = MagicMock()
                                    log_entry.log_metadata = metadata
                                    result.scalar_one_or_none.return_value = log_entry
                                return result

                        result.scalar_one_or_none.return_value = task
                        return result

                    mock_db.execute = mock_execute
                    await self.worker._parse_task_result(task, logs, mock_db, exit_code=exit_code)
        asyncio.run(run())

    def test_updates_model_name_from_structured_entry(self):
        """Structured system_init entry with model key sets task.model_name."""
        task = _make_task()
        self._run_parse(task, '', system_init_metadata='{"model":"claude-sonnet-4-20250514","cwd":"/workspace"}')
        self.assertEqual(task.model_name, "claude-sonnet-4-20250514")

    def test_does_not_update_model_name_when_model_is_empty(self):
        """Structured entry with empty model string leaves task.model_name as None."""
        task = _make_task()
        self._run_parse(task, '', system_init_metadata='{"model":"","cwd":"/workspace"}')
        self.assertIsNone(task.model_name)

    def test_does_not_update_model_name_when_model_missing_from_json(self):
        """Structured entry without 'model' key leaves task.model_name as None."""
        task = _make_task()
        self._run_parse(task, '', system_init_metadata='{"cwd":"/workspace"}')
        self.assertIsNone(task.model_name)

    def test_no_crash_when_system_init_missing(self):
        """No system_init entry in DB does not crash and leaves model_name None."""
        task = _make_task()
        self._run_parse(task, '')
        self.assertIsNone(task.model_name)

    def test_no_crash_when_metadata_is_invalid_json(self):
        """Invalid JSON in log_metadata does not crash and leaves model_name None."""
        task = _make_task()
        self._run_parse(task, '', system_init_metadata='not-valid-json')
        self.assertIsNone(task.model_name)

    def test_updates_token_usage_from_structured_run_result(self):
        """Structured run_result usage sets task token counts without CODIFY_STATS."""
        task = _make_task()
        self._run_parse(
            task,
            '',
            run_result_metadata='{"subtype":"success","session_id":"session-123","usage":{"input_tokens":1500,"output_tokens":800}}',
        )
        self.assertEqual(task.input_tokens, 1500)
        self.assertEqual(task.output_tokens, 800)

    def test_extracts_session_id_from_structured_run_result(self):
        """Structured run_result session_id sets the transient extracted session id."""
        task = _make_task()
        self._run_parse(
            task,
            '',
            run_result_metadata='{"subtype":"success","session_id":"session-123","usage":{}}',
        )
        self.assertEqual(task._extracted_session_id, "session-123")
        self.assertEqual(task.output_session_id, "session-123")

    def test_updates_commit_diff_and_mr_title_from_worker_finalization(self):
        """Structured finalization sets commit SHA, diff stats, and MR title without markers."""
        task = _make_task()
        self._run_parse(
            task,
            '',
            worker_finalization_metadata=(
                '{"commit_sha":"0123456789abcdef0123456789abcdef01234567",'
                '"diff":{"additions":12,"deletions":3,"total":15},'
                '"commit_message":"Fix worker result parsing"}'
            ),
        )
        self.assertEqual(task.commit_sha, "0123456789abcdef0123456789abcdef01234567")
        self.assertEqual(task.additions, 12)
        self.assertEqual(task.deletions, 3)
        self.assertEqual(task.total_changes, 15)
        self.assertEqual(task.commit_message, "Fix worker result parsing")

    def test_ignores_codify_stats_marker_when_structured_usage_missing(self):
        task = _make_task()
        self._run_parse(task, 'CODIFY_STATS:{"input_tokens":100,"output_tokens":50}\n')
        self.assertIsNone(task.input_tokens)
        self.assertIsNone(task.output_tokens)

    def test_ignores_legacy_commit_diff_title_and_session_markers(self):
        task = _make_task()
        logs = (
            'CODIFY_DIFF:+5-2\n'
            'CODIFY_COMMIT_SHA:fedcba9876543210fedcba9876543210fedcba98\n'
            'CODIFY_MR_TITLE:Fallback marker title\n'
            'CODIFY_SESSION_ID:fallback-session\n'
        )
        self._run_parse(task, logs)
        self.assertIsNone(task.commit_sha)
        self.assertEqual(task.additions, 0)
        self.assertEqual(task.deletions, 0)
        self.assertEqual(task.total_changes, 0)
        self.assertIsNone(task.commit_message)
        self.assertFalse(hasattr(task, "_extracted_session_id"))


# ---------------------------------------------------------------------------
# TestCodifyMrTitleParsing
# ---------------------------------------------------------------------------

class TestStructuredMrTitleParsing(unittest.TestCase):
    """Tests for structured worker_finalization MR title parsing inside _parse_task_result."""

    def setUp(self):
        self.mock_settings = _make_mock_settings()
        self.patcher = patch('app.core.worker.get_settings', return_value=self.mock_settings)
        self.patcher.start()
        self.worker = _make_worker()

    def tearDown(self):
        self.patcher.stop()

    def _run_parse(self, task, logs, exit_code=0, worker_finalization_metadata=None):
        async def run():
            with patch.object(self.worker, '_parse_mr_from_logs', new=AsyncMock()):
                with patch.object(self.worker, '_update_task_stats_from_logs_or_api', new=AsyncMock()):
                    mock_db = create_mock_db(task)

                    async def mock_execute(stmt, *args, **kwargs):
                        try:
                            stmt_str = str(stmt.compile(compile_kwargs={"literal_binds": True}))
                        except Exception:
                            stmt_str = str(stmt)

                        result = MagicMock()
                        if "worker_finalization" in stmt_str:
                            if worker_finalization_metadata is None:
                                result.scalar_one_or_none.return_value = None
                            else:
                                log_entry = MagicMock()
                                log_entry.log_metadata = worker_finalization_metadata
                                result.scalar_one_or_none.return_value = log_entry
                            return result
                        result.scalar_one_or_none.return_value = None
                        return result

                    mock_db.execute = mock_execute
                    await self.worker._parse_task_result(task, logs, mock_db, exit_code=exit_code)
        asyncio.run(run())

    def test_updates_commit_message_from_structured_finalization(self):
        """worker_finalization metadata sets task.commit_message."""
        task = _make_task()
        self._run_parse(task, '', worker_finalization_metadata='{"commit_message":"Fix the login bug"}')
        self.assertEqual(task.commit_message, "Fix the login bug")

    def test_ignores_empty_title(self):
        """Structured title with only whitespace leaves commit_message as None."""
        task = _make_task()
        self._run_parse(task, '', worker_finalization_metadata='{"commit_message":"   "}')
        self.assertIsNone(task.commit_message)

    def test_truncates_title_to_512_characters(self):
        """Structured title with a very long title is truncated to 512 characters."""
        task = _make_task()
        long_title = "A" * 600
        self._run_parse(task, '', worker_finalization_metadata=f'{{"commit_message":"{long_title}"}}')
        self.assertIsNotNone(task.commit_message)
        self.assertLessEqual(len(task.commit_message), 512)
        # First 512 characters of the title should be stored
        self.assertTrue(task.commit_message.startswith("A" * 10))

    def test_sanitizes_gitlab_token_from_title(self):
        """Structured title containing a GitLab token has it redacted."""
        task = _make_task()
        self._run_parse(
            task,
            '',
            worker_finalization_metadata='{"commit_message":"Fix auth glpat-abcdefghijklmnopqrst issue"}',
        )
        self.assertIsNotNone(task.commit_message)
        self.assertNotIn("glpat-abcdefghijklmnopqrst", task.commit_message)
        self.assertIn("[GITLAB_TOKEN]", task.commit_message)

    def test_strips_completed_think_block_from_title(self):
        """Structured title removes model thinking tags before storing."""
        task = _make_task()
        self._run_parse(
            task,
            '',
            worker_finalization_metadata='{"commit_message":"<think>用户要求输出 MR 标题</think>修复 Git 配置"}',
        )
        self.assertEqual(task.commit_message, "修复 Git 配置")

    def test_ignores_unclosed_think_title(self):
        """Structured title with only an unclosed thinking block is not stored."""
        task = _make_task()
        self._run_parse(
            task,
            '',
            worker_finalization_metadata='{"commit_message":"<think>用户要求输出一个 GitLab Merge Request 标题"}',
        )
        self.assertIsNone(task.commit_message)

    def test_preserves_newlines_in_multiline_commit_message(self):
        """Multi-line commit messages retain internal newlines (not collapsed to spaces)."""
        import json
        msg = "feat: 实现用户认证\n\n- 更新 auth 模块\n- 添加 JWT 支持\n\nAI-Generated: true"
        task = _make_task()
        self._run_parse(task, '', worker_finalization_metadata=json.dumps({"commit_message": msg}))
        self.assertIsNotNone(task.commit_message)
        self.assertIn("\n", task.commit_message)
        self.assertTrue(task.commit_message.startswith("feat: 实现用户认证"))


# ---------------------------------------------------------------------------
# TestSerializeTaskNewFields
# ---------------------------------------------------------------------------

class TestSerializeTaskNewFields(unittest.TestCase):
    """Tests verifying model_name and commit_message appear in _serialize_task output."""

    def setUp(self):
        self.mock_settings = _make_mock_settings()
        self.patcher_worker = patch('app.core.worker.get_settings', return_value=self.mock_settings)
        self.patcher_config = patch('app.config.get_effective_settings', return_value=self.mock_settings)
        self.patcher_worker.start()
        self.patcher_config.start()

    def tearDown(self):
        self.patcher_worker.stop()
        self.patcher_config.stop()

    def _make_full_task(self, **kwargs):
        """Return a Task with all fields required by _serialize_task."""
        from app.models import Task, TaskStatus
        defaults = dict(
            id=1,
            project_id=1,
            user_prompt="test",
            status=TaskStatus.PENDING,
            issue_id=1,
            is_retry=False,
            retry_source_task_id=None,
            additions=0,
            deletions=0,
            total_changes=0,
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
        )
        defaults.update(kwargs)
        task = Task(**defaults)
        mock_issue = MagicMock()
        mock_issue.id = defaults.get('issue_id', 1)
        mock_issue.branch_name = "test-branch"
        mock_issue.base_branch = None
        mock_issue.target_branch = "main"
        mock_issue.merge_request_iid = None
        mock_issue.merge_request_url = None
        mock_issue.claude_session_id = None
        mock_issue.session_storage_path = None
        mock_issue.project_id = defaults['project_id']
        task.issue = mock_issue
        return task

    def test_model_name_included_in_serialized_task(self):
        """_serialize_task includes model_name when it is set."""
        from app.core.task_helpers import _serialize_task
        task = self._make_full_task(model_name="claude-3-5-sonnet")
        result = _serialize_task(task)
        self.assertIn("model_name", result)
        self.assertEqual(result["model_name"], "claude-3-5-sonnet")

    def test_commit_message_included_in_serialized_task(self):
        """_serialize_task includes commit_message when it is set."""
        from app.core.task_helpers import _serialize_task
        task = self._make_full_task(commit_message="Fix login bug")
        result = _serialize_task(task)
        self.assertIn("commit_message", result)
        self.assertEqual(result["commit_message"], "Fix login bug")

    def test_model_name_is_none_when_not_set(self):
        """_serialize_task returns None for model_name when it is not set."""
        from app.core.task_helpers import _serialize_task
        task = self._make_full_task(model_name=None)
        result = _serialize_task(task)
        self.assertIn("model_name", result)
        self.assertIsNone(result["model_name"])

    def test_commit_message_is_none_when_not_set(self):
        """_serialize_task returns None for commit_message when it is not set."""
        from app.core.task_helpers import _serialize_task
        task = self._make_full_task(commit_message=None)
        result = _serialize_task(task)
        self.assertIn("commit_message", result)
        self.assertIsNone(result["commit_message"])


# ---------------------------------------------------------------------------
# TestBackfillEventJsonlCommit
# ---------------------------------------------------------------------------

class TestBackfillEventJsonlCommit(unittest.TestCase):
    """Verify backfill_event_jsonl_from_archive commits projected events."""

    def setUp(self):
        from app.core.worker_event_projector import WorkerEventProjector
        self.sanitize = MagicMock(return_value="sanitized")
        self.projector = WorkerEventProjector(sanitize_sensitive_data=self.sanitize)

    def _finalization_event_jsonl(self) -> str:
        import json as _json
        return _json.dumps({
            "type": "codify_worker",
            "subtype": "finalization",
            "commit_sha": "a" * 40,
            "diff": {"additions": 20, "deletions": 7, "total": 27},
            "commit_message": "feat: add tests",
        }) + "\n"

    def test_backfill_commits_after_projecting_finalization_event(self):
        import io
        import tarfile as _tarfile

        archive_buf = io.BytesIO()
        with _tarfile.open(fileobj=archive_buf, mode="w:gz") as tf:
            event_data = self._finalization_event_jsonl().encode("utf-8")
            info = _tarfile.TarInfo(name="event.jsonl")
            info.size = len(event_data)
            tf.addfile(info, io.BytesIO(event_data))

            runtime_data = b'{"resume_session":""}'
            runtime_info = _tarfile.TarInfo(name="runtime.json")
            runtime_info.size = len(runtime_data)
            tf.addfile(runtime_info, io.BytesIO(runtime_data))

        archive_bytes = archive_buf.getvalue()
        mock_db = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        mock_cursor = MagicMock()
        mock_cursor.last_offset = 0
        mock_cursor.last_sequence_no = 0

        with patch(
            "app.core.worker_event_projector._os.path.exists", return_value=True
        ), patch(
            "app.core.worker_event_projector._tarfile.open",
            return_value=_tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz"),
        ), patch(
            "app.core.worker_event_projector.get_or_create_cursor",
            AsyncMock(return_value=mock_cursor),
        ):
            async def run():
                await self.projector.backfill_event_jsonl_from_archive(
                    task_id=1, db=mock_db
                )

            asyncio.run(run())

        mock_db.commit.assert_awaited()
        mock_db.add.assert_called()
        added_log = mock_db.add.call_args[0][0]
        self.assertEqual(added_log.log_type, "worker_finalization")


# ---------------------------------------------------------------------------
# Entry point for direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
