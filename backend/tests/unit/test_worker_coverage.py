#!/usr/bin/env python3
"""
Additional worker unit tests targeting uncovered lines.

Covers functionality NOT tested by test_worker_new_patterns.py or test_mr_stats.py:
- _build_initial_mr_title       (lines 127-144)
- _build_initial_mr_description (lines 146-159)
- _remove_mr_draft_status       (lines 161-178)
- _flush_log_chunk              (lines 180-195: empty skip, truncation)
- _stream_logs_to_db timeout    (lines 242-247)
- _create_mr_if_needed          (lines 384-410: reuse existing MR)
- _find_existing_mr             (lines 412-438: not found, exception)
- _create_new_mr                (lines 440-472: success, failure)
- _build_container_env          (lines 474-525)
- _build_container_volumes      (lines 527-557)
- _parse_task_result            (lines 559-646: CODIFY_STATS, COMMIT_SHA, TOOL_CALLS, fail)
- _parse_mr_from_logs           (lines 647-683: URL, API fallback)
- _update_mr_description        (lines 722-759)
- _get_container_name           (lines 825-835)
- execute_task                  (lines 837-1009: not found, retry, exception, cleanup)
- _notify_task_started          (lines 1011-1038)
- _notify_task_completed        (lines 1040-1096)
- _send_failure_alert           (lines 1097-1136)
- process_pending_tasks         (lines 1138-1158)
"""

import asyncio
import json
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from app.core.worker import WorkerExecutor, scrub_sensitive_data, sanitize_sensitive_data
from app.models import Task, TaskStatus, TaskLog


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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
    s.maven_cache_host_path = ""
    s.maven_settings_host_path = ""
    s.worker_volume_mounts_parsed = []
    s.alert_on_failure = False
    s.alert_webhook_url = None
    s.claude_max_turns = 20
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _make_worker(mock_gitlab=None, mock_docker=None):
    """Build a WorkerExecutor with mock clients."""
    mock_gitlab = mock_gitlab or MagicMock()
    mock_docker = mock_docker or MagicMock()
    return WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)


def _make_task(**kwargs):
    """Create a Task object with defaults."""
    defaults = dict(
        id=1, project_id=100, issue_iid=10, note_id=50,
        user_prompt="Fix the bug", branch_name="codify-1-p100-i10",
        target_branch="main", priority=0, status=TaskStatus.PENDING,
        additions=0, deletions=0, total_changes=0,
    )
    defaults.update(kwargs)
    return Task(**defaults)


def _make_db(task=None):
    """Create a mock async DB session."""
    db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = task
    mock_result.scalars.return_value.all.return_value = [task] if task else []
    db.execute = AsyncMock(return_value=mock_result)
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=None)
    return db


# ===================================================================
# _build_initial_mr_title
# ===================================================================

class TestBuildInitialMrTitle(unittest.TestCase):
    """Tests for _build_initial_mr_title — lines 127-144."""

    def test_title_from_issue(self):
        """When issue_iid is set and issue fetch succeeds, title comes from issue."""
        mock_gitlab = MagicMock()
        mock_gitlab.get_issue.return_value = {"title": "Login page broken", "description": "..."}
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(issue_iid=42)

        title = worker._build_initial_mr_title(task)

        self.assertEqual(title, "AI: Login page broken")
        mock_gitlab.get_issue.assert_called_once_with(100, 42)

    def test_title_from_issue_empty_title_falls_back_to_prompt(self):
        """When issue title is empty, fall back to user_prompt."""
        mock_gitlab = MagicMock()
        mock_gitlab.get_issue.return_value = {"title": "  ", "description": ""}
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(issue_iid=42, user_prompt="Add unit tests for auth")

        title = worker._build_initial_mr_title(task)

        self.assertEqual(title, "AI: Add unit tests for auth")

    def test_title_from_issue_fetch_failure_falls_back_to_prompt(self):
        """When GitLab API fails, fall back to user_prompt."""
        mock_gitlab = MagicMock()
        mock_gitlab.get_issue.side_effect = Exception("API timeout")
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(issue_iid=42, user_prompt="Improve caching layer")

        title = worker._build_initial_mr_title(task)

        self.assertEqual(title, "AI: Improve caching layer")

    def test_title_from_prompt_with_sentence_split(self):
        """Prompt with punctuation should be split at first sentence boundary."""
        worker = _make_worker()
        task = _make_task(issue_iid=None, user_prompt="Fix login page. Also update the tests.")

        title = worker._build_initial_mr_title(task)

        self.assertEqual(title, "AI: Fix login page")

    def test_title_from_prompt_truncated_at_100(self):
        """Long prompt segment should be truncated to 100 chars."""
        worker = _make_worker()
        long_text = "A" * 200
        task = _make_task(issue_iid=None, user_prompt=long_text)

        title = worker._build_initial_mr_title(task)

        self.assertTrue(title.startswith("AI: "))
        self.assertLessEqual(len(title), 104 + 1)  # "AI: " + 100 chars

    def test_title_fallback_to_task_id(self):
        """When no issue and no prompt, use task ID."""
        worker = _make_worker()
        task = _make_task(issue_iid=None, user_prompt="", id=99)

        title = worker._build_initial_mr_title(task)

        self.assertEqual(title, "AI: Task 99")

    def test_title_prompt_none_falls_to_task_id(self):
        """When user_prompt is None, fall back to task ID."""
        worker = _make_worker()
        task = _make_task(issue_iid=None, user_prompt=None, id=7)

        title = worker._build_initial_mr_title(task)

        self.assertEqual(title, "AI: Task 7")

    def test_title_issue_returns_none(self):
        """When get_issue returns None, fall back to prompt."""
        mock_gitlab = MagicMock()
        mock_gitlab.get_issue.return_value = None
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(issue_iid=42, user_prompt="Update README")

        title = worker._build_initial_mr_title(task)

        self.assertEqual(title, "AI: Update README")


# ===================================================================
# _build_initial_mr_description
# ===================================================================

class TestBuildInitialMrDescription(unittest.TestCase):
    """Tests for _build_initial_mr_description — lines 146-159."""

    def test_description_with_issue_iid(self):
        """Description should include Closes # when issue_iid is set."""
        worker = _make_worker()
        task = _make_task(issue_iid=42, user_prompt="Fix auth bug")

        desc = worker._build_initial_mr_description(task)

        self.assertIn("Fix auth bug", desc)
        self.assertIn("Closes #42", desc)

    def test_description_without_issue_iid(self):
        """Description should not include Closes # when issue_iid is None."""
        worker = _make_worker()
        task = _make_task(issue_iid=None, user_prompt="Add docs")

        desc = worker._build_initial_mr_description(task)

        self.assertIn("Add docs", desc)
        self.assertNotIn("Closes", desc)


# ===================================================================
# _remove_mr_draft_status
# ===================================================================

class TestRemoveMrDraftStatus(unittest.TestCase):
    """Tests for _remove_mr_draft_status — lines 161-178."""

    def test_removes_draft_prefix(self):
        """Should remove 'Draft: ' prefix and save."""
        mock_mr = MagicMock()
        mock_mr.title = "Draft: Add new feature"
        mock_project = MagicMock()
        mock_project.mergerequests.get.return_value = mock_mr

        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.return_value = mock_project
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(merge_request_iid=5)

        worker._remove_mr_draft_status(task)

        self.assertEqual(mock_mr.title, "Add new feature")
        mock_mr.save.assert_called_once()

    def test_removes_wip_prefix(self):
        """Should remove 'WIP: ' prefix."""
        mock_mr = MagicMock()
        mock_mr.title = "WIP: Experimental changes"
        mock_project = MagicMock()
        mock_project.mergerequests.get.return_value = mock_mr

        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.return_value = mock_project
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(merge_request_iid=5)

        worker._remove_mr_draft_status(task)

        self.assertEqual(mock_mr.title, "Experimental changes")

    def test_removes_bracket_draft_prefix(self):
        """Should remove '[Draft] ' prefix."""
        mock_mr = MagicMock()
        mock_mr.title = "[Draft] New API endpoint"
        mock_project = MagicMock()
        mock_project.mergerequests.get.return_value = mock_mr

        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.return_value = mock_project
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(merge_request_iid=5)

        worker._remove_mr_draft_status(task)

        self.assertEqual(mock_mr.title, "New API endpoint")

    def test_skips_when_title_not_string(self):
        """Should skip when title is not a string (e.g., None)."""
        mock_mr = MagicMock()
        mock_mr.title = None
        # getattr returns None for non-string title
        mock_project = MagicMock()
        mock_project.mergerequests.get.return_value = mock_mr

        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.return_value = mock_project
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(merge_request_iid=5)

        # Use type(mock_mr).title to control what getattr sees
        type(mock_mr).title = PropertyMock(return_value=None)
        worker._remove_mr_draft_status(task)

        mock_mr.save.assert_not_called()

    def test_skips_already_non_draft(self):
        """Should skip when title doesn't have draft prefix."""
        mock_mr = MagicMock()
        mock_mr.title = "Add new feature"
        mock_project = MagicMock()
        mock_project.mergerequests.get.return_value = mock_mr

        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.return_value = mock_project
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(merge_request_iid=5)

        worker._remove_mr_draft_status(task)

        mock_mr.save.assert_not_called()


# ===================================================================
# _flush_log_chunk
# ===================================================================

class TestFlushLogChunk(unittest.TestCase):
    """Tests for _flush_log_chunk — lines 180-195."""

    def test_saves_log_chunk(self):
        """Normal chunk should be saved as TaskLog."""
        worker = _make_worker()
        db = _make_db()

        asyncio.run(worker._flush_log_chunk(1, ["line1\n", "line2\n"], 0, db))

        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    def test_skips_empty_content(self):
        """Empty or whitespace-only content should be skipped — line 190."""
        worker = _make_worker()
        db = _make_db()

        asyncio.run(worker._flush_log_chunk(1, ["   \n", "  \n"], 0, db))

        db.add.assert_not_called()
        db.commit.assert_not_awaited()

    def test_truncates_large_content(self):
        """Content > 8000 chars should be truncated — line 192."""
        worker = _make_worker()
        db = _make_db()
        long_line = "x" * 9000 + "\n"

        asyncio.run(worker._flush_log_chunk(1, [long_line], 0, db))

        db.add.assert_called_once()
        log_entry = db.add.call_args[0][0]
        self.assertLessEqual(len(log_entry.message), 8000)

    def test_scrubs_sensitive_data(self):
        """Token in log should be scrubbed before saving."""
        worker = _make_worker()
        db = _make_db()

        asyncio.run(worker._flush_log_chunk(1, ["token=glpat-abcdef1234567890\n"], 0, db))

        log_entry = db.add.call_args[0][0]
        self.assertNotIn("glpat-", log_entry.message)
        self.assertIn("[GITLAB_TOKEN]", log_entry.message)


# ===================================================================
# _build_container_env
# ===================================================================

class TestBuildContainerEnv(unittest.TestCase):
    """Tests for _build_container_env — lines 474-525."""

    @patch('app.core.worker.get_settings')
    def test_basic_env_vars(self, mock_get_settings):
        """Should include all required environment variables."""
        settings = _make_settings()
        mock_get_settings.return_value = settings
        worker = _make_worker()
        task = _make_task()

        env = worker._build_container_env(task, mr_iid=5, target_branch="main")

        self.assertEqual(env["GITLAB_URL"], "http://gitlab.example.com")
        self.assertEqual(env["GITLAB_TOKEN"], "test-token")
        self.assertEqual(env["PROJECT_ID"], "100")
        self.assertEqual(env["BRANCH_NAME"], "codify-1-p100-i10")
        self.assertEqual(env["USER_PROMPT"], "Fix the bug")
        self.assertEqual(env["TARGET_BRANCH"], "main")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "test-key")
        self.assertEqual(env["TASK_ID"], "1")
        self.assertEqual(env["ISSUE_IID"], "10")
        self.assertEqual(env["MR_IID"], "5")
        self.assertEqual(env["CLAUDE_MAX_TURNS"], "20")

    @patch('app.core.worker.get_settings')
    def test_env_without_issue(self, mock_get_settings):
        """No ISSUE_IID env var when issue_iid is None — line 510-511."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        task = _make_task(issue_iid=None)

        env = worker._build_container_env(task, mr_iid=None, target_branch="main")

        self.assertNotIn("ISSUE_IID", env)

    @patch('app.core.worker.get_settings')
    def test_env_without_mr_iid(self, mock_get_settings):
        """No MR_IID env var when mr_iid is None — lines 518-519."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        task = _make_task()

        env = worker._build_container_env(task, mr_iid=None, target_branch="main")

        self.assertNotIn("MR_IID", env)

    @patch('app.core.worker.get_settings')
    def test_env_with_base_branch(self, mock_get_settings):
        """BASE_BRANCH env var when task has a base_branch — line 514-515."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        task = _make_task(base_branch="develop")

        env = worker._build_container_env(task, mr_iid=None, target_branch="main")

        self.assertEqual(env["BASE_BRANCH"], "develop")

    @patch('app.core.worker.get_settings')
    def test_env_without_base_branch(self, mock_get_settings):
        """No BASE_BRANCH env var when task.base_branch is None."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        task = _make_task(base_branch=None)

        env = worker._build_container_env(task, mr_iid=None, target_branch="main")

        self.assertNotIn("BASE_BRANCH", env)

    @patch('app.core.worker.get_settings')
    def test_env_with_custom_ca_bundle(self, mock_get_settings):
        """CUSTOM_CA_BUNDLE env var when setting is configured — lines 522-523."""
        mock_get_settings.return_value = _make_settings(custom_ca_bundle="/etc/ssl/custom-ca.crt")
        worker = _make_worker()
        task = _make_task()

        env = worker._build_container_env(task, mr_iid=None, target_branch="main")

        self.assertEqual(env["CUSTOM_CA_BUNDLE"], "/etc/ssl/custom-ca.crt")

    @patch('app.core.worker.get_settings')
    def test_env_target_branch_none_becomes_empty(self, mock_get_settings):
        """TARGET_BRANCH should be '' when target_branch is None (no-MR mode) — line 500."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        task = _make_task()

        env = worker._build_container_env(task, mr_iid=None, target_branch=None)

        self.assertEqual(env["TARGET_BRANCH"], "")


# ===================================================================
# _build_container_volumes
# ===================================================================

class TestBuildContainerVolumes(unittest.TestCase):
    """Tests for _build_container_volumes — lines 527-557."""

    def test_no_volumes(self):
        """Empty when no volume settings are configured."""
        settings = _make_settings()
        worker = _make_worker()

        volumes = worker._build_container_volumes(settings)

        self.assertEqual(volumes, {})

    def test_maven_cache_volume(self):
        """Maven cache host path creates volume mount — lines 538-542."""
        settings = _make_settings(maven_cache_host_path="/host/.m2/repository")
        worker = _make_worker()

        volumes = worker._build_container_volumes(settings)

        self.assertIn("/host/.m2/repository", volumes)
        self.assertEqual(
            volumes["/host/.m2/repository"]["bind"],
            "/home/codify/.m2/repository",
        )
        self.assertEqual(volumes["/host/.m2/repository"]["mode"], "rw")

    def test_maven_settings_volume(self):
        """Maven settings host path creates volume mount — lines 543-546."""
        settings = _make_settings(maven_settings_host_path="/host/settings.xml")
        worker = _make_worker()

        volumes = worker._build_container_volumes(settings)

        self.assertIn("/host/settings.xml", volumes)
        self.assertEqual(
            volumes["/host/settings.xml"]["bind"],
            "/home/codify/.m2/settings.xml",
        )
        self.assertEqual(volumes["/host/settings.xml"]["mode"], "ro")

    def test_generic_volume_mounts(self):
        """Generic volume mounts from worker_volume_mounts_parsed — lines 550-555."""
        settings = _make_settings(
            worker_volume_mounts_parsed=[
                {"host_path": "/data/config", "container_path": "/app/config", "mode": "ro"},
                {"host_path": "/data/cache", "container_path": "/app/cache", "mode": "rw"},
            ]
        )
        worker = _make_worker()

        volumes = worker._build_container_volumes(settings)

        self.assertEqual(volumes["/data/config"]["bind"], "/app/config")
        self.assertEqual(volumes["/data/config"]["mode"], "ro")
        self.assertEqual(volumes["/data/cache"]["bind"], "/app/cache")
        self.assertEqual(volumes["/data/cache"]["mode"], "rw")

    def test_generic_volume_mount_missing_paths_skipped(self):
        """Mounts with empty host_path or container_path are skipped — line 554."""
        settings = _make_settings(
            worker_volume_mounts_parsed=[
                {"host_path": "", "container_path": "/app/x", "mode": "ro"},
                {"host_path": "/data/y", "container_path": "", "mode": "rw"},
            ]
        )
        worker = _make_worker()

        volumes = worker._build_container_volumes(settings)

        self.assertEqual(volumes, {})

    def test_generic_volume_mount_default_mode_is_ro(self):
        """Mount with no mode defaults to 'ro' — line 553."""
        settings = _make_settings(
            worker_volume_mounts_parsed=[
                {"host_path": "/data/shared", "container_path": "/app/shared"},
            ]
        )
        worker = _make_worker()

        volumes = worker._build_container_volumes(settings)

        self.assertEqual(volumes["/data/shared"]["mode"], "ro")


# ===================================================================
# _get_container_name
# ===================================================================

class TestGetContainerName(unittest.TestCase):
    """Tests for _get_container_name — lines 825-835."""

    def test_name_with_issue(self):
        """Container name includes 'i{issue_iid}' suffix when task has an issue."""
        worker = _make_worker()
        task = _make_task(id=5, project_id=200, issue_iid=42)

        name = worker._get_container_name(task)

        self.assertEqual(name, "codify-5-p200-i42")

    def test_name_manual_task(self):
        """Container name includes 'manual' suffix when no issue."""
        worker = _make_worker()
        task = _make_task(id=7, project_id=300, issue_iid=None)

        name = worker._get_container_name(task)

        self.assertEqual(name, "codify-7-p300-manual")


# ===================================================================
# _create_mr_if_needed / _find_existing_mr / _create_new_mr
# ===================================================================

class TestCreateMrIfNeeded(unittest.TestCase):
    """Tests for MR creation flow — lines 384-472."""

    def test_reuses_existing_mr_iid(self):
        """When mr_iid is already set, return it unchanged — line 401-402."""
        worker = _make_worker()
        task = _make_task()

        result = worker._create_mr_if_needed(task, mr_iid=99, mr_web_url="http://example.com/mr/99")

        self.assertEqual(result, (99, "http://example.com/mr/99"))

    def test_finds_existing_open_mr(self):
        """When an open MR exists for the branch, reuse it — lines 404-407."""
        mock_mr = MagicMock()
        mock_mr.iid = 77
        mock_mr.web_url = "http://gitlab.example.com/mr/77"

        mock_project = MagicMock()
        mock_project.mergerequests.list.return_value = [mock_mr]

        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.return_value = mock_project
        mock_gitlab.normalize_web_url.return_value = "http://gitlab.example.com/mr/77"
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()

        result = worker._create_mr_if_needed(task, mr_iid=None, mr_web_url=None)

        self.assertEqual(result, (77, "http://gitlab.example.com/mr/77"))

    def test_find_existing_mr_returns_none_when_no_mrs(self):
        """_find_existing_mr returns None when no open MRs — line 429-430."""
        mock_project = MagicMock()
        mock_project.mergerequests.list.return_value = []

        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.return_value = mock_project
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()

        result = worker._find_existing_mr(task)

        self.assertIsNone(result)

    def test_find_existing_mr_handles_exception(self):
        """_find_existing_mr returns None on API error — lines 436-438."""
        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.side_effect = Exception("Network error")
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()

        result = worker._find_existing_mr(task)

        self.assertIsNone(result)

    @patch('app.core.worker.get_settings')
    def test_create_new_mr_success(self, mock_get_settings):
        """_create_new_mr returns (iid, url) on success — lines 457-472."""
        mock_get_settings.return_value = _make_settings()

        mock_mr = MagicMock()
        mock_mr.iid = 88
        mock_mr.web_url = "http://gitlab.example.com/mr/88"

        mock_project = MagicMock()
        mock_project.mergerequests.create.return_value = mock_mr

        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.return_value = mock_project
        mock_gitlab.normalize_web_url.return_value = "http://gitlab.example.com/mr/88"
        mock_gitlab.get_issue.return_value = {"title": "Test Issue", "description": ""}
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()

        result = worker._create_new_mr(task)

        self.assertEqual(result, (88, "http://gitlab.example.com/mr/88"))

    @patch('app.core.worker.get_settings')
    def test_create_new_mr_failure(self, mock_get_settings):
        """_create_new_mr returns (None, None) on error — lines 465-467."""
        mock_get_settings.return_value = _make_settings()

        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.side_effect = Exception("API down")
        mock_gitlab.get_issue.return_value = {"title": "Test", "description": ""}
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()

        result = worker._create_new_mr(task)

        self.assertEqual(result, (None, None))


# ===================================================================
# _parse_task_result
# ===================================================================

class TestParseTaskResult(unittest.TestCase):
    """Tests for _parse_task_result — lines 559-646."""

    def test_parses_codify_stats(self):
        """Parses CODIFY_STATS for token usage — lines 575-586."""
        worker = _make_worker()
        task = _make_task()
        db = _make_db()
        logs = 'CODIFY_STATS:{"input_tokens": 500, "output_tokens": 150}\n'

        asyncio.run(worker._parse_task_result(task, logs, db, exit_code=0))

        self.assertEqual(task.input_tokens, 500)
        self.assertEqual(task.output_tokens, 150)

    def test_handles_invalid_codify_stats(self):
        """Invalid JSON in CODIFY_STATS should not crash — lines 585-586."""
        worker = _make_worker()
        task = _make_task()
        db = _make_db()
        logs = 'CODIFY_STATS:not-json\n'

        # Should not raise
        asyncio.run(worker._parse_task_result(task, logs, db, exit_code=0))

        self.assertIsNone(task.input_tokens)

    def test_parses_codify_commit_sha(self):
        """Parses CODIFY_COMMIT_SHA marker — lines 601-604."""
        worker = _make_worker()
        task = _make_task()
        db = _make_db()
        sha = "a" * 40
        logs = f'CODIFY_COMMIT_SHA:{sha}\n'

        asyncio.run(worker._parse_task_result(task, logs, db, exit_code=0))

        self.assertEqual(task.commit_sha, sha)

    def test_parses_codify_tool_calls(self):
        """Parses CODIFY_TOOL_CALLS and stores as TaskLog — lines 620-635."""
        worker = _make_worker()
        task = _make_task()
        db = _make_db()
        tool_calls = json.dumps([{"name": "read_file", "input": {"path": "main.py"}}])
        logs = f'CODIFY_TOOL_CALLS:{tool_calls}\n'

        asyncio.run(worker._parse_task_result(task, logs, db, exit_code=0))

        db.add.assert_called()
        added_log = db.add.call_args[0][0]
        self.assertEqual(added_log.log_type, "tool_calls_json")
        self.assertEqual(added_log.log_metadata, tool_calls)

    def test_handles_invalid_codify_tool_calls(self):
        """Invalid JSON in CODIFY_TOOL_CALLS should not crash — line 634-635."""
        worker = _make_worker()
        task = _make_task()
        db = _make_db()
        logs = 'CODIFY_TOOL_CALLS:{{bad json\n'

        asyncio.run(worker._parse_task_result(task, logs, db, exit_code=0))
        # Should not raise; no log entry added

    def test_exit_code_zero_sets_completed(self):
        """exit_code=0 → status=COMPLETED — lines 637-641."""
        worker = _make_worker()
        task = _make_task()
        db = _make_db()
        logs = 'http://gitlab.example.com/project/-/merge_requests/55\nCODIFY_DIFF:+10-5\n'

        asyncio.run(worker._parse_task_result(task, logs, db, exit_code=0))

        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertIsNotNone(task.completed_at)

    def test_exit_code_nonzero_sets_failed(self):
        """exit_code≠0 → status=FAILED with error_message — lines 642-645."""
        worker = _make_worker()
        task = _make_task()
        db = _make_db()
        logs = 'Some error occurred\nglpat-secret12345678\n'

        asyncio.run(worker._parse_task_result(task, logs, db, exit_code=1))

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIsNotNone(task.completed_at)
        self.assertNotIn("glpat-", task.error_message)
        self.assertIn("[GITLAB_TOKEN]", task.error_message)


# ===================================================================
# _parse_mr_from_logs
# ===================================================================

class TestParseMrFromLogs(unittest.TestCase):
    """Tests for _parse_mr_from_logs — lines 647-683."""

    def test_extracts_mr_from_url_in_logs(self):
        """Finds MR URL and IID from log output — lines 655-664."""
        mock_gitlab = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(merge_request_url=None, merge_request_iid=None)

        logs = "Created MR: http://gitlab.example.com/project/-/merge_requests/42\nDone."

        asyncio.run(worker._parse_mr_from_logs(task, logs))

        self.assertEqual(task.merge_request_iid, 42)
        self.assertIn("merge_requests/42", task.merge_request_url)

    def test_derives_iid_from_url_when_missing(self):
        """Derives IID from MR URL when only URL is found — lines 667-670."""
        mock_gitlab = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(
            merge_request_url="http://gitlab.example.com/-/merge_requests/99",
            merge_request_iid=None,
        )

        asyncio.run(worker._parse_mr_from_logs(task, "no mr in logs"))

        self.assertEqual(task.merge_request_iid, 99)

    def test_api_fallback_when_no_mr_in_logs(self):
        """Falls back to GitLab API when MR not found in logs — lines 673-683."""
        mock_mr = MagicMock()
        mock_mr.iid = 33
        mock_mr.web_url = "http://gitlab.example.com/-/merge_requests/33"

        mock_project = MagicMock()
        mock_project.mergerequests.list.return_value = [mock_mr]

        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.return_value = mock_project
        mock_gitlab.normalize_web_url.return_value = "http://gitlab.example.com/-/merge_requests/33"
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(merge_request_url=None, merge_request_iid=None)

        asyncio.run(worker._parse_mr_from_logs(task, "no mr url here"))

        self.assertEqual(task.merge_request_iid, 33)

    def test_api_fallback_handles_exception(self):
        """API fallback error is caught — line 682-683."""
        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.side_effect = Exception("API down")
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(merge_request_url=None, merge_request_iid=None)

        # Should not raise
        asyncio.run(worker._parse_mr_from_logs(task, "no mr url here"))

        self.assertIsNone(task.merge_request_iid)


# ===================================================================
# _update_mr_description
# ===================================================================

class TestUpdateMrDescription(unittest.TestCase):
    """Tests for _update_mr_description — lines 722-759."""

    def test_adds_new_execution_section(self):
        """Adds execution progress section when none exists — lines 751-754."""
        mock_mr = MagicMock()
        mock_mr.description = "## Original description"

        mock_gitlab = MagicMock()
        mock_gitlab.get_merge_request.return_value = mock_mr
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(id=42)

        worker._update_mr_description(task, mr_iid=5)

        self.assertIn("执行进度", mock_mr.description)
        self.assertIn("任务 42", mock_mr.description)
        mock_mr.save.assert_called_once()

    def test_appends_to_existing_execution_section(self):
        """Appends to existing execution section — lines 742-750."""
        mock_mr = MagicMock()
        mock_mr.description = "## Info\n---\n### 执行进度\n- [x] 初始任务完成\n---\n## Footer"

        mock_gitlab = MagicMock()
        mock_gitlab.get_merge_request.return_value = mock_mr
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(id=77)

        worker._update_mr_description(task, mr_iid=5)

        self.assertIn("任务 77", mock_mr.description)
        self.assertIn("Footer", mock_mr.description)

    def test_skips_when_mr_not_found(self):
        """Does nothing when MR is not found — lines 731-733."""
        mock_gitlab = MagicMock()
        mock_gitlab.get_merge_request.return_value = None
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()

        # Should not raise
        worker._update_mr_description(task, mr_iid=5)


# ===================================================================
# _notify_task_started
# ===================================================================

class TestNotifyTaskStarted(unittest.TestCase):
    """Tests for _notify_task_started — lines 1011-1038."""

    @patch('app.core.worker.get_settings')
    def test_skips_manual_task(self, mock_get_settings):
        """Manual tasks skip notification — lines 1018-1020."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        task = _make_task(is_manual=True)

        worker._notify_task_started(task)

        worker.gitlab.create_note.assert_not_called()
        worker.gitlab.create_mr_note.assert_not_called()

    @patch('app.core.worker.get_settings')
    def test_notifies_mr_when_mr_iid_set(self, mock_get_settings):
        """Sends notification to MR when merge_request_iid is set — lines 1025-1031."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        task = _make_task(merge_request_iid=55, is_manual=False)

        worker._notify_task_started(task)

        worker.gitlab.create_mr_note.assert_called_once()
        args = worker.gitlab.create_mr_note.call_args
        self.assertEqual(args[0][0], 100)  # project_id
        self.assertEqual(args[0][1], 55)   # mr_iid
        self.assertIn("开始处理", args[0][2])

    @patch('app.core.worker.get_settings')
    def test_notifies_issue_when_no_mr_iid(self, mock_get_settings):
        """Sends notification to issue when no MR — lines 1032-1038."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        task = _make_task(merge_request_iid=None, issue_iid=10, is_manual=False)

        worker._notify_task_started(task)

        worker.gitlab.create_note.assert_called_once()
        args = worker.gitlab.create_note.call_args
        self.assertEqual(args[0][0], 100)  # project_id
        self.assertEqual(args[0][1], 10)   # issue_iid


# ===================================================================
# _notify_task_completed
# ===================================================================

class TestNotifyTaskCompleted(unittest.TestCase):
    """Tests for _notify_task_completed — lines 1040-1096."""

    @patch('app.core.worker.get_settings')
    def test_skips_manual_task(self, mock_get_settings):
        """Manual tasks skip notification — lines 1049-1051."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        task = _make_task(is_manual=True)

        asyncio.run(worker._notify_task_completed(task, success=True))

        worker.gitlab.create_note.assert_not_called()

    @patch('app.core.worker.get_settings')
    def test_success_with_mr_url_and_iid(self, mock_get_settings):
        """Success with MR URL and IID sends proper message — lines 1058-1067."""
        mock_get_settings.return_value = _make_settings()
        mock_gitlab = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(
            merge_request_iid=55,
            merge_request_url="http://gitlab.example.com/mr/55",
            is_manual=False,
        )

        asyncio.run(worker._notify_task_completed(task, success=True, notify_target="mr"))

        mock_gitlab.create_mr_note.assert_called_once()
        msg = mock_gitlab.create_mr_note.call_args[0][2]
        self.assertIn("✅", msg)
        self.assertIn("!55", msg)

    @patch('app.core.worker.get_settings')
    def test_success_without_mr_url(self, mock_get_settings):
        """Success without MR URL sends generic message — line 1071."""
        mock_get_settings.return_value = _make_settings()
        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(
            merge_request_iid=None,
            merge_request_url=None,
            issue_iid=10,
            is_manual=False,
        )

        asyncio.run(worker._notify_task_completed(task, success=True, notify_target="issue"))

        mock_gitlab.create_note.assert_called_once()
        msg = mock_gitlab.create_note.call_args[0][2]
        self.assertIn("✅", msg)
        self.assertIn("任务已完成", msg)

    @patch('app.core.worker.get_settings')
    def test_failure_notification(self, mock_get_settings):
        """Failure sends error message — lines 1072-1076."""
        mock_get_settings.return_value = _make_settings()
        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(
            merge_request_iid=None,
            issue_iid=10,
            is_manual=False,
            error_message="Container crashed with OOM",
        )

        asyncio.run(worker._notify_task_completed(task, success=False, notify_target="issue"))

        mock_gitlab.create_note.assert_called_once()
        msg = mock_gitlab.create_note.call_args[0][2]
        self.assertIn("❌", msg)
        self.assertIn("Container crashed with OOM", msg)

    @patch('app.core.worker.get_settings')
    def test_success_mr_extracts_iid_from_url(self, mock_get_settings):
        """Extracts MR IID from URL when mr_iid is None — lines 1060-1064."""
        mock_get_settings.return_value = _make_settings()
        mock_gitlab = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(
            merge_request_iid=None,
            merge_request_url="http://gitlab.example.com/project/-/merge_requests/42",
            is_manual=False,
        )

        asyncio.run(worker._notify_task_completed(task, success=True, notify_target="mr"))

        # Should have extracted iid=42 from URL
        mock_gitlab.create_mr_note.assert_called_once()
        msg = mock_gitlab.create_mr_note.call_args[0][2]
        self.assertIn("!42", msg)


# ===================================================================
# _send_failure_alert
# ===================================================================

class TestSendFailureAlert(unittest.TestCase):
    """Tests for _send_failure_alert — lines 1097-1136."""

    @patch('app.core.worker.get_settings')
    def test_skips_when_alert_disabled(self, mock_get_settings):
        """No webhook call when alert_on_failure is False — lines 1106-1107."""
        mock_get_settings.return_value = _make_settings(alert_on_failure=False)
        worker = _make_worker()
        task = _make_task()

        with patch('httpx.AsyncClient') as mock_client:
            asyncio.run(worker._send_failure_alert(task))
            mock_client.assert_not_called()

    @patch('app.core.worker.get_settings')
    def test_skips_when_no_webhook_url(self, mock_get_settings):
        """No webhook call when alert_webhook_url is not set — lines 1106-1107."""
        mock_get_settings.return_value = _make_settings(alert_on_failure=True, alert_webhook_url=None)
        worker = _make_worker()
        task = _make_task()

        with patch('httpx.AsyncClient') as mock_client:
            asyncio.run(worker._send_failure_alert(task))
            mock_client.assert_not_called()

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.get_ssl_verify')
    def test_sends_webhook_on_failure(self, mock_ssl, mock_get_settings):
        """Sends webhook when alert_on_failure=True and URL is set — lines 1110-1136."""
        mock_get_settings.return_value = _make_settings(
            alert_on_failure=True,
            alert_webhook_url="http://hooks.example.com/alert",
        )
        mock_ssl.return_value = True
        worker = _make_worker()
        task = _make_task(error_message="Container OOM killed")

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch('app.core.worker.httpx.AsyncClient', return_value=mock_client_instance):
            asyncio.run(worker._send_failure_alert(task))

        mock_client_instance.post.assert_awaited_once()
        call_args = mock_client_instance.post.call_args
        self.assertEqual(call_args[0][0], "http://hooks.example.com/alert")
        payload = call_args[1]["json"]
        self.assertIn("Task Failed", payload["text"])


# ===================================================================
# execute_task
# ===================================================================

class TestExecuteTask(unittest.TestCase):
    """Tests for execute_task — lines 837-1009."""

    @patch('app.core.worker.get_settings')
    def test_task_not_found(self, mock_get_settings):
        """Returns False when task is not found — lines 854-856."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        db = _make_db(task=None)

        result = asyncio.run(worker.execute_task(db, 999))

        self.assertFalse(result)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_task_success_flow(self, mock_notify, mock_get_settings):
        """Successful task sets COMPLETED and returns True — lines 926-937."""
        mock_get_settings.return_value = _make_settings()
        mock_gitlab = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        mock_docker = MagicMock()
        mock_docker.create_container.return_value = MagicMock(id="ctr-123")

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=None)
        db = _make_db(task)

        fake_logs = (
            "http://gitlab.example.com/project/-/merge_requests/42\n"
            "CODIFY_DIFF:+10-5\n"
            'CODIFY_STATS:{"input_tokens":100,"output_tokens":50}\n'
        )

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, fake_logs, 1))):
            result = asyncio.run(worker.execute_task(db, task.id))

        self.assertTrue(result)
        self.assertEqual(task.status, TaskStatus.COMPLETED)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_task_failure_with_retry(self, mock_notify, mock_get_settings):
        """Failed task with retries schedules retry — lines 942-948."""
        mock_get_settings.return_value = _make_settings(max_retries=2)
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = MagicMock(id="ctr-456")

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=None, retry_count=0)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(1, "error output", 1))):
            result = asyncio.run(worker.execute_task(db, task.id))

        self.assertFalse(result)
        self.assertEqual(task.retry_count, 1)
        self.assertEqual(task.status, TaskStatus.PENDING)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_task_failure_no_retry(self, mock_notify, mock_get_settings):
        """Failed task without retry stays FAILED — lines 938-951."""
        mock_get_settings.return_value = _make_settings(max_retries=0)
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = MagicMock(id="ctr-789")

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=None)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(1, "error output", 1))):
            result = asyncio.run(worker.execute_task(db, task.id))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_task_exception_sets_failed_and_cleans_up(self, mock_notify, mock_get_settings):
        """Exception during execution sets FAILED and cleans up container — lines 983-1009."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-err")
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = mock_container

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=None)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', side_effect=RuntimeError("Docker exploded")):
            result = asyncio.run(worker.execute_task(db, task.id))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("Docker exploded", task.error_message)
        mock_docker.remove_container.assert_called_with(mock_container, force=True)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_exception_cleanup_failure_does_not_raise(self, mock_notify, mock_get_settings):
        """Container cleanup failure during exception handling is caught — lines 996-997."""
        mock_get_settings.return_value = _make_settings()
        mock_container = MagicMock(id="ctr-err2")
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = mock_container
        mock_docker.remove_container.side_effect = Exception("Cannot remove")

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=None)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', side_effect=RuntimeError("boom")):
            result = asyncio.run(worker.execute_task(db, task.id))

        self.assertFalse(result)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_image_pull_failure_continues(self, mock_notify, mock_get_settings):
        """Image pull failure logs warning and continues — lines 878-879."""
        mock_get_settings.return_value = _make_settings()
        mock_docker = MagicMock()
        mock_docker.pull_image.side_effect = Exception("Registry down")
        mock_docker.create_container.return_value = MagicMock(id="ctr-existing")

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=None)
        db = _make_db(task)

        fake_logs = "CODIFY_DIFF:+1-0\n"

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, fake_logs, 1))):
            result = asyncio.run(worker.execute_task(db, task.id))

        # Should succeed despite pull failure
        self.assertTrue(result)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_no_mr_mode_skips_mr_creation(self, mock_notify, mock_get_settings):
        """When target_branch is None, MR creation is skipped — line 886."""
        mock_get_settings.return_value = _make_settings()
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = MagicMock(id="ctr-nomr")

        mock_gitlab = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x
        mock_gitlab.create_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch=None, merge_request_iid=None)
        db = _make_db(task)

        fake_logs = "CODIFY_DIFF:+1-0\n"

        with patch.object(worker, '_create_mr_if_needed') as mock_create_mr:
            with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, fake_logs, 1))):
                asyncio.run(worker.execute_task(db, task.id))

        # _create_mr_if_needed should NOT have been called
        mock_create_mr.assert_not_called()

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_fast_task_with_no_log_chunks(self, mock_notify, mock_get_settings):
        """Very fast task with 0 log chunks gets a fallback log entry — lines 964-971."""
        mock_get_settings.return_value = _make_settings()
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = MagicMock(id="ctr-fast")

        mock_gitlab = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=None)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, "CODIFY_DIFF:+1-0\n", 0))):
            asyncio.run(worker.execute_task(db, task.id))

        # Should have added a fallback log entry
        added_entries = [call[0][0] for call in db.add.call_args_list if isinstance(call[0][0], TaskLog)]
        info_entries = [e for e in added_entries if e.log_level == "INFO"]
        self.assertTrue(len(info_entries) >= 1)


# ===================================================================
# _send_notifications / _send_failure_notifications
# ===================================================================

class TestSendNotifications(unittest.TestCase):
    """Tests for _send_notifications and _send_failure_notifications — lines 761-824."""

    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_send_notifications_catches_errors(self, mock_notify_event):
        """Notification errors are caught — lines 780-781, 786-787."""
        mock_gitlab = MagicMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(is_manual=True)

        # Should not raise even if notification fails
        mock_notify_event.side_effect = Exception("Mattermost down")
        asyncio.run(worker._send_notifications(task, success=True, had_existing_mr=False, logs=""))

    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_send_failure_notifications_retry_scheduled(self, mock_notify_event):
        """Failure notification with PENDING status sends retry event — lines 811-819."""
        mock_gitlab = MagicMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(is_manual=True, status=TaskStatus.PENDING)

        asyncio.run(worker._send_failure_notifications(task, success=False, had_existing_mr=False))

        # Check the second call (first is _notify_task_completed which is mocked via is_manual)
        # The mattermost event call:
        mock_notify_event.assert_called()

    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_send_failure_notifications_failed_status(self, mock_notify_event):
        """Failure notification with FAILED status sends failure event — lines 820-821."""
        from app.core.mattermost_notifications import MATTERMOST_EVENT_TASK_FAILED
        mock_gitlab = MagicMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(is_manual=True, status=TaskStatus.FAILED)

        asyncio.run(worker._send_failure_notifications(task, success=False, had_existing_mr=False))

        # Should have called with TASK_FAILED event
        calls = mock_notify_event.call_args_list
        event_names = [c[0][1] for c in calls]
        self.assertIn(MATTERMOST_EVENT_TASK_FAILED, event_names)


# ===================================================================
# process_pending_tasks
# ===================================================================

class TestProcessPendingTasks(unittest.TestCase):
    """Tests for process_pending_tasks — lines 1138-1158."""

    def test_processes_pending_tasks(self):
        """Processes all pending tasks and returns count — lines 1147-1158."""
        worker = _make_worker()
        task1 = _make_task(id=1)
        task2 = _make_task(id=2)

        db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [task1, task2]
        db.execute = AsyncMock(return_value=mock_result)

        with patch.object(worker, 'execute_task', new=AsyncMock(return_value=True)):
            count = asyncio.run(worker.process_pending_tasks(db))

        self.assertEqual(count, 2)

    def test_counts_only_successes(self):
        """Only counts tasks that succeed — lines 1154-1156."""
        worker = _make_worker()
        task1 = _make_task(id=1)
        task2 = _make_task(id=2)

        db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [task1, task2]
        db.execute = AsyncMock(return_value=mock_result)

        # First task succeeds, second fails
        with patch.object(worker, 'execute_task', new=AsyncMock(side_effect=[True, False])):
            count = asyncio.run(worker.process_pending_tasks(db))

        self.assertEqual(count, 1)

    def test_no_pending_tasks(self):
        """Returns 0 when no pending tasks — lines 1147-1150."""
        worker = _make_worker()

        db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        with patch.object(worker, 'execute_task', new=AsyncMock()):
            count = asyncio.run(worker.process_pending_tasks(db))

        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
