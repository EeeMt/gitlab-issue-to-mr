#!/usr/bin/env python3
"""
Additional worker unit tests targeting uncovered lines.

Covers functionality NOT tested by test_worker_new_patterns.py or test_mr_stats.py:
- _build_initial_mr_title       (lines 127-144)
- _build_initial_mr_description (lines 146-159)
- _remove_mr_draft_status       (lines 161-178)
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
import io
import os
import re
import subprocess
import tarfile
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from app.core.worker import WorkerExecutor
from app.models import Task, TaskLog, TaskStatus

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_WORKER_ENTRYPOINT_MODULES = (
    "bootstrap",
    "repository-helpers",
    "repository",
    "gitlab",
    "delivery",
    "task-environment",
    "codegraph",
    "runtime",
    "main",
)


def _read_worker_entrypoint_sources(entrypoint: Path) -> str:
    """Return the deployed entrypoint and its sourced modules as one test surface."""
    module_dir = entrypoint.parent / "worker-entrypoint"
    return "\n".join(
        [
            entrypoint.read_text(),
            *(
                module_dir.joinpath(f"{name}.sh").read_text()
                for name in _WORKER_ENTRYPOINT_MODULES
            ),
        ]
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
    s.worker_volume_mounts_parsed = []
    s.worker_workspace_host_path = "/tmp/codify-worker-tests"
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
    created_container = mock_docker.create_container.return_value
    if not isinstance(getattr(created_container, "status", None), str):
        created_container.status = "exited"
    # Return valid bytes from read_file_from_container to avoid retry sleeps
    mock_docker.read_file_from_container.return_value = b"console log content"
    return WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)


def _make_task(**kwargs):
    """Create a Task object with defaults."""
    from unittest.mock import MagicMock

    from app.models import AIProvider, TaskWorkerProfileSnapshot

    # Separate issue-level kwargs
    issue_overrides = {}
    for key in ['branch_name', 'base_branch', 'target_branch', 'merge_request_iid', 'merge_request_url', 'title', 'description']:
        if key in kwargs:
            issue_overrides[key] = kwargs.pop(key)

    provider = kwargs.pop('provider', None)

    defaults = dict(
        id=1, project_id=100, issue_id=1,
        user_prompt="Fix the bug",
        rendered_prompt="Persisted task prompt",
        priority=0, status=TaskStatus.PENDING,
        is_retry=False, retry_source_task_id=None,
        additions=0, deletions=0, total_changes=0,
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
        mock_issue.branch_name = issue_overrides.get(
            'branch_name',
            f"codify-{defaults['id']}-p{defaults['project_id']}-i{defaults.get('issue_id', 1)}",
        )
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


def _make_db(task=None):
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
        elif 'FROM worker_environment_variables' in statement_str:
            mock_result.scalar_one_or_none.return_value = None
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

    # Support db.get(Issue, issue_id) for loading issue from task
    async def _mock_get(model_cls, id_val):
        if model_cls is AIProvider:
            provider = getattr(task, 'provider', None) if task else None
            if provider is not None and getattr(provider, 'id', None) == id_val:
                return provider
            return None
        if task and model_cls is Issue and hasattr(task, 'issue') and task.issue is not None:
            if hasattr(task.issue, 'id') and task.issue.id == id_val:
                return task.issue
        if task and model_cls is TaskWorkerProfileSnapshot:
            snapshot = getattr(task, "worker_profile_snapshot", None)
            if snapshot is not None and getattr(snapshot, "task_id", None) == id_val:
                return snapshot
        return None

    db.get = AsyncMock(side_effect=_mock_get)
    return db


# ===================================================================
# _build_initial_mr_title
# ===================================================================

class TestBuildInitialMrTitle(unittest.TestCase):
    """Tests for _build_initial_mr_title — issue title preferred, prompt fallback."""

    def test_title_from_issue_title(self):
        """When issue has a title, MR title uses it."""
        worker = _make_worker()
        task = _make_task(user_prompt="Fix the bug", title="Login page broken")

        title = worker._build_initial_mr_title(task)

        self.assertEqual(title, "Draft: Login page broken")

    def test_title_from_issue_title_truncated(self):
        """Long issue title is truncated to 120 chars."""
        worker = _make_worker()
        long_title = "A" * 200
        task = _make_task(user_prompt="Fix it", title=long_title)

        title = worker._build_initial_mr_title(task)

        self.assertTrue(title.startswith("Draft: "))
        self.assertLessEqual(len(title), 127)  # "Draft: " + 120 chars

    def test_title_fallback_to_prompt_when_no_issue_title(self):
        """When issue has no title, fall back to prompt."""
        worker = _make_worker()
        task = _make_task(user_prompt="Fix login page. Also update the tests.")

        title = worker._build_initial_mr_title(task)

        self.assertEqual(title, "AI: Fix login page")

    def test_title_from_prompt_strips_whitespace(self):
        """Whitespace in prompt is collapsed."""
        worker = _make_worker()
        task = _make_task(user_prompt="Add  unit  tests  for  auth")

        title = worker._build_initial_mr_title(task)

        self.assertEqual(title, "AI: Add unit tests for auth")

    def test_title_from_prompt_truncated_at_100(self):
        """Long prompt segment should be truncated to 100 chars."""
        worker = _make_worker()
        long_text = "A" * 200
        task = _make_task(user_prompt=long_text)

        title = worker._build_initial_mr_title(task)

        self.assertTrue(title.startswith("AI: "))
        self.assertLessEqual(len(title), 104 + 1)  # "AI: " + 100 chars

    def test_title_fallback_to_task_id(self):
        """When no prompt and no issue title, use task ID."""
        worker = _make_worker()
        task = _make_task(user_prompt="", id=99)

        title = worker._build_initial_mr_title(task)

        self.assertEqual(title, "AI: Task 99")

    def test_title_prompt_none_falls_to_task_id(self):
        """When user_prompt is None and no issue title, fall back to task ID."""
        worker = _make_worker()
        task = _make_task(user_prompt=None, id=7)

        title = worker._build_initial_mr_title(task)

        self.assertEqual(title, "AI: Task 7")

    def test_title_from_multiword_prompt(self):
        """Title uses prompt content when no issue title."""
        worker = _make_worker()
        task = _make_task(user_prompt="Update README")

        title = worker._build_initial_mr_title(task)

        self.assertEqual(title, "AI: Update README")


# ===================================================================
# _build_initial_mr_description
# ===================================================================

class TestBuildInitialMrDescription(unittest.TestCase):
    """Tests for _build_initial_mr_description — prompt-based only."""

    def test_description_includes_prompt(self):
        """Description should include the user prompt."""
        worker = _make_worker()
        task = _make_task(user_prompt="Fix auth bug")

        desc = worker._build_initial_mr_description(task)

        self.assertIn("Fix auth bug", desc)
        self.assertNotIn("Closes", desc)

    def test_description_format(self):
        """Description should have the expected format without Closes line."""
        worker = _make_worker()
        task = _make_task(user_prompt="Add docs")

        desc = worker._build_initial_mr_description(task)

        self.assertIn("Add docs", desc)
        self.assertNotIn("Closes", desc)
        self.assertIn("AI 正在执行", desc)


# ===================================================================
# _remove_mr_draft_status
# ===================================================================

class TestRemoveMrDraftStatus(unittest.TestCase):
    """Tests for _remove_mr_draft_status_for_issue and legacy _remove_mr_draft_status."""

    def test_marks_ready_and_removes_draft_prefix(self):
        """Should explicitly mark ready, remove 'Draft: ' prefix, and save."""
        mock_mr = MagicMock()
        mock_mr.title = "Draft: Add new feature"
        mock_project = MagicMock()
        mock_project.mergerequests.get.return_value = mock_mr

        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.return_value = mock_project
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(merge_request_iid=5)

        worker._remove_mr_draft_status_for_issue(task, task.issue)

        self.assertFalse(mock_mr.draft)
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

        worker._remove_mr_draft_status_for_issue(task, task.issue)

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

        worker._remove_mr_draft_status_for_issue(task, task.issue)

        self.assertEqual(mock_mr.title, "New API endpoint")

    def test_marks_ready_without_title_prefix(self):
        """Should still set draft=False even when title has no draft prefix."""
        mock_mr = MagicMock()
        mock_mr.title = "Add new feature"
        mock_project = MagicMock()
        mock_project.mergerequests.get.return_value = mock_mr

        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.return_value = mock_project
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(merge_request_iid=5)

        worker._remove_mr_draft_status_for_issue(task, task.issue)

        self.assertFalse(mock_mr.draft)
        self.assertEqual(mock_mr.title, "Add new feature")
        mock_mr.save.assert_called_once()

        mock_mr = MagicMock()
        mock_project = MagicMock()
        mock_project.mergerequests.get.return_value = mock_mr

        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.return_value = mock_project
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(merge_request_iid=5)

        # Use type(mock_mr).title to control what getattr sees
        type(mock_mr).title = PropertyMock(return_value=None)
        worker._remove_mr_draft_status_for_issue(task, task.issue)

        mock_mr.save.assert_not_called()

    def test_marks_ready_for_already_non_draft(self):
        """Should still mark ready and save when title has no draft prefix."""
        mock_mr = MagicMock()
        mock_mr.title = "Add new feature"
        mock_project = MagicMock()
        mock_project.mergerequests.get.return_value = mock_mr

        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.return_value = mock_project
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(merge_request_iid=5)

        worker._remove_mr_draft_status_for_issue(task, task.issue)

        self.assertFalse(mock_mr.draft)
        mock_mr.save.assert_called_once()

    def test_legacy_method_is_noop(self):
        """The legacy _remove_mr_draft_status(task) does nothing."""
        mock_gitlab = MagicMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task(merge_request_iid=5)

        worker._remove_mr_draft_status(task)

        mock_gitlab.gl.projects.get.assert_not_called()


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
        issue = task.issue

        env = worker._build_container_env(task, issue, mr_iid=5, target_branch="main")

        self.assertEqual(env["GITLAB_URL"], "http://gitlab.example.com")
        self.assertEqual(env["GITLAB_TOKEN"], "test-token")
        self.assertEqual(env["PROJECT_ID"], "100")
        self.assertEqual(env["BRANCH_NAME"], issue.branch_name)
        self.assertEqual(env["USER_PROMPT"], "Fix the bug")
        self.assertEqual(env["TARGET_BRANCH"], "main")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "test-key")
        self.assertEqual(env["TASK_ID"], "1")
        self.assertEqual(env["ISSUE_ID"], "1")
        self.assertEqual(env["MR_IID"], "5")
        self.assertEqual(env["CLAUDE_MAX_TURNS"], "20")

    @patch('app.core.worker.get_settings')
    def test_env_without_mr_iid(self, mock_get_settings):
        """No MR_IID env var when mr_iid is None — lines 518-519."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        task = _make_task()
        issue = task.issue

        env = worker._build_container_env(task, issue, mr_iid=None, target_branch="main")

        self.assertNotIn("MR_IID", env)

    @patch('app.core.worker.get_settings')
    def test_env_with_base_branch(self, mock_get_settings):
        """BASE_BRANCH env var when issue has a base_branch — line 514-515."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        task = _make_task(base_branch="develop")
        issue = task.issue

        env = worker._build_container_env(task, issue, mr_iid=None, target_branch="main")

        self.assertEqual(env["BASE_BRANCH"], "develop")

    @patch('app.core.worker.get_settings')
    def test_env_without_base_branch(self, mock_get_settings):
        """No BASE_BRANCH env var when issue.base_branch is None."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        task = _make_task(base_branch=None)
        issue = task.issue

        env = worker._build_container_env(task, issue, mr_iid=None, target_branch="main")

        self.assertNotIn("BASE_BRANCH", env)

    @patch('app.core.worker.get_settings')
    def test_env_with_custom_ca_bundle(self, mock_get_settings):
        """CUSTOM_CA_BUNDLE env var when setting is configured — lines 522-523."""
        mock_get_settings.return_value = _make_settings(custom_ca_bundle="/etc/ssl/custom-ca.crt")
        worker = _make_worker()
        task = _make_task()
        issue = task.issue

        env = worker._build_container_env(task, issue, mr_iid=None, target_branch="main")

        self.assertEqual(env["CUSTOM_CA_BUNDLE"], "/etc/ssl/custom-ca.crt")

    @patch('app.core.worker.get_settings')
    def test_env_does_not_inline_worker_custom_script_content(self, mock_get_settings):
        """Worker scripts are materialized as files instead of inlined into env."""
        mock_get_settings.return_value = _make_settings(
            worker_pre_script="echo pre\nnpm ci",
            worker_post_script="npm test\necho post",
        )
        worker = _make_worker()
        task = _make_task()
        issue = task.issue

        env = worker._build_container_env(task, issue, mr_iid=None, target_branch="main")

        self.assertNotIn("CODIFY_WORKER_PRE_SCRIPT", env)
        self.assertNotIn("CODIFY_WORKER_POST_SCRIPT", env)

    def test_materialize_worker_custom_scripts_writes_runtime_files(self):
        from app.core.worker_runtime import materialize_worker_custom_scripts

        settings = _make_settings(
            worker_pre_script="echo pre\nnpm ci",
            worker_post_script="npm test\necho post",
        )

        with tempfile.TemporaryDirectory() as runtime_dir:
            materialize_worker_custom_scripts(settings, runtime_dir)

            pre_script = Path(runtime_dir) / "worker-pre-script.sh"
            post_script = Path(runtime_dir) / "worker-post-script.sh"
            self.assertEqual(pre_script.read_text(), "echo pre\nnpm ci\n")
            self.assertEqual(post_script.read_text(), "npm test\necho post\n")
            self.assertEqual(oct(pre_script.stat().st_mode & 0o777), "0o700")
            self.assertEqual(oct(post_script.stat().st_mode & 0o777), "0o700")

    @patch('app.core.worker.get_settings')
    def test_env_merges_custom_environment_values(self, mock_get_settings):
        """Custom environment values are validated and merged, including empty strings."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        task = _make_task()
        issue = task.issue

        env = worker._build_container_env(
            task,
            issue,
            mr_iid=None,
            target_branch="main",
            custom_environment={
                "FEATURE_FLAG": "enabled",
                "EMPTY_ALLOWED": "",
            },
        )

        self.assertEqual(env["FEATURE_FLAG"], "enabled")
        self.assertEqual(env["EMPTY_ALLOWED"], "")
        self.assertEqual(env["TASK_ID"], "1")

    @patch('app.core.worker.get_settings')
    def test_env_rejects_reserved_custom_environment_key(self, mock_get_settings):
        """Reserved custom environment keys raise ValueError."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        task = _make_task()
        issue = task.issue

        with self.assertRaisesRegex(ValueError, "reserved"):
            worker._build_container_env(
                task,
                issue,
                mr_iid=None,
                target_branch="main",
                custom_environment={"TASK_ID": "999"},
            )

    @patch('app.core.worker.get_settings')
    def test_env_includes_commit_author_metadata(self, mock_get_settings):
        """Should pass initiator author identity and fixed Codify co-author into the worker env."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        task = _make_task(
            initiator_display_name="Alice Zhang",
            initiator_email="alice@example.com",
            initiator_username="alice",
        )
        issue = task.issue

        env = worker._build_container_env(task, issue, mr_iid=None, target_branch="main")

        self.assertEqual(env["GIT_AUTHOR_NAME"], "Alice Zhang")
        self.assertEqual(env["GIT_AUTHOR_EMAIL"], "alice@example.com")
        self.assertEqual(env["CODIFY_COAUTHOR_NAME"], "Codify")

    @patch('app.core.worker.get_settings')
    def test_env_falls_back_to_username_and_service_email(self, mock_get_settings):
        """Should fall back when task has no display name or email snapshot."""
        mock_get_settings.return_value = _make_settings()
        worker = _make_worker()
        task = _make_task(initiator_username="alice")
        issue = task.issue

        env = worker._build_container_env(task, issue, mr_iid=None, target_branch="main")

        self.assertEqual(env["GIT_AUTHOR_NAME"], "alice")
        self.assertEqual(env["GIT_AUTHOR_EMAIL"], "codify-task@codify.local")



class TestResolveCommitAuthor(unittest.IsolatedAsyncioTestCase):
    """Tests for _resolve_commit_author."""

    async def test_uses_user_record_when_task_snapshot_missing(self):
        worker = _make_worker()
        task = _make_task(initiator_user_id=7, initiator_username="alice")
        task.initiator_display_name = None
        task.initiator_email = None

        db = MagicMock()
        db.get = AsyncMock(return_value=MagicMock(display_name="Alice Zhang", username="alice", email="alice@example.com"))

        name, email = await worker._resolve_commit_author(db, task)

        self.assertEqual(name, "Alice Zhang")
        self.assertEqual(email, "alice@example.com")


class TestEntrypointCommitAttribution(unittest.TestCase):
    """Regression tests for commit attribution shell logic."""

    @staticmethod
    def _run_entrypoint_loader(*, failing_module: str | None = None):
        root = Path(__file__).resolve().parents[3]
        entrypoint = root / "deploy" / "entrypoint.worker.sh"
        production_assignment = 'ENTRYPOINT_LIB_DIR="/opt/codify/worker-entrypoint"'
        test_assignment = 'ENTRYPOINT_LIB_DIR="${ENTRYPOINT_TEST_LIB_DIR:?}"'
        source = entrypoint.read_text()
        test_source = source.replace(production_assignment, test_assignment, 1)
        if test_source == source:
            raise AssertionError("entrypoint library directory assignment not found")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            module_dir = temp_path / "worker-entrypoint"
            module_dir.mkdir()
            log_path = temp_path / "loaded-modules.log"

            for module_name in _WORKER_ENTRYPOINT_MODULES:
                module_lines = [
                    f'printf "%s\\n" "{module_name}" >> "${{ENTRYPOINT_TEST_LOG}}"',
                ]
                if module_name == failing_module:
                    module_lines.append("return 23")
                (module_dir / f"{module_name}.sh").write_text(
                    "\n".join(module_lines) + "\n"
                )

            test_entrypoint = temp_path / "entrypoint.sh"
            test_entrypoint.write_text(test_source)
            env = {
                **os.environ,
                "ENTRYPOINT_TEST_LIB_DIR": str(module_dir),
                "ENTRYPOINT_TEST_LOG": str(log_path),
            }
            result = subprocess.run(
                ["bash", str(test_entrypoint)],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            loaded_modules = log_path.read_text().splitlines() if log_path.exists() else []
            return result, loaded_modules

    @staticmethod
    def _extract_shell_function(content, name):
        match = re.search(rf"(?ms)^{re.escape(name)}\(\) \{{\n.*?^\}}\n", content)
        if match is None:
            raise AssertionError(f"{name} shell function not found")
        return match.group(0)

    def test_entrypoint_loads_bounded_modules_in_lifecycle_order(self):
        root = Path(__file__).resolve().parents[3]
        entrypoint = root / "deploy" / "entrypoint.worker.sh"
        module_dir = root / "deploy" / "worker-entrypoint"

        content = entrypoint.read_text()
        self.assertLessEqual(len(content.splitlines()), 120)
        module_list = content.split("for module in", 1)[1].split("do", 1)[0]
        listed_modules = []
        for line in module_list.splitlines():
            module_name = line.strip().removesuffix("\\").strip()
            if module_name:
                listed_modules.append(module_name)
        self.assertEqual(listed_modules, list(_WORKER_ENTRYPOINT_MODULES))
        for module_name in _WORKER_ENTRYPOINT_MODULES:
            module_path = module_dir / f"{module_name}.sh"
            self.assertTrue(module_path.is_file(), f"missing entrypoint module: {module_path}")
            self.assertLessEqual(
                len(module_path.read_text().splitlines()),
                450,
                f"entrypoint module grew too large: {module_path}",
            )

        dockerfile = (root / "deploy" / "Dockerfile.worker-java21-maven").read_text()
        test_dockerfile = (
            root / "backend" / "tests" / "mock_integration" / "fake_claude" / "Dockerfile.worker-test"
        ).read_text()
        copy_instruction = "COPY deploy/worker-entrypoint/ /opt/codify/worker-entrypoint/"
        self.assertNotIn(copy_instruction, dockerfile)
        self.assertIn(copy_instruction, test_dockerfile)

    def test_entrypoint_sources_every_module_in_lifecycle_order(self):
        result, loaded_modules = self._run_entrypoint_loader()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(loaded_modules, list(_WORKER_ENTRYPOINT_MODULES))

    def test_mounted_entrypoint_allows_explicit_claude_binary_override(self):
        root = Path(__file__).resolve().parents[3]
        content = (root / "deploy" / "entrypoint.worker.sh").read_text()

        self.assertIn(
            'CODIFY_CLAUDE_BIN="${CODIFY_CLAUDE_BIN:-/usr/local/bin/claude}"',
            content,
        )
        self.assertIn('CODIFY_CLAUDE_BIN must be an absolute path', content)
        self.assertIn(
            'claude_version="$(codify_run_shell \'"${CODIFY_CLAUDE_BIN}" --version\')"',
            content,
        )
        self.assertIn(
            "codify_run_shell 'touch /workspace/.codify-worker-kit-write-test",
            content,
        )
        self.assertNotIn("CODIFY_KIT_CLAUDE_BIN", content)

    def test_worker_kit_launcher_preserves_runtime_path_and_stable_locale(self):
        root = Path(__file__).resolve().parents[3]
        content = (root / "deploy" / "worker-kit" / "launcher" / "main.go").read_text()

        self.assertIn('path := os.Getenv("PATH")', content)
        self.assertIn('os.Setenv("CODIFY_RUNTIME_PATH", runtimePath+":"+m.RuntimeBin)', content)
        self.assertIn('os.Setenv("PATH", m.RuntimeBin+":"+runtimePath)', content)
        self.assertIn('os.Setenv("LC_ALL", "C.UTF-8")', content)
        self.assertIn('os.Setenv("LANG", "C.UTF-8")', content)
        self.assertIn('os.Unsetenv("LANGUAGE")', content)
        self.assertNotIn(
            'runtimePath := "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"',
            content,
        )

    def test_entrypoint_propagates_module_failure_and_stops_loading(self):
        result, loaded_modules = self._run_entrypoint_loader(failing_module="delivery")

        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(
            loaded_modules,
            ["bootstrap", "repository-helpers", "repository", "gitlab", "delivery"],
        )

    def test_runtime_worker_image_delegates_codify_tools_to_worker_kit(self):
        root = Path(__file__).resolve().parents[3]
        dockerfile = (root / "deploy" / "Dockerfile.worker-java21-maven").read_text()

        self.assertIn("Java 21 + Maven project runtime image", dockerfile)
        self.assertIn("FROM maven:3.9.9-eclipse-temurin-21", dockerfile)
        self.assertIn("MAVEN_CONFIG=/home/codify/.m2", dockerfile)
        self.assertIn("ln -sf /opt/java/openjdk/bin/java /usr/local/bin/java", dockerfile)
        self.assertIn("ln -sf /opt/java/openjdk/bin/keytool /usr/local/bin/keytool", dockerfile)
        self.assertIn("mkdir -p /workspace /home/codify/.m2/repository", dockerfile)
        self.assertIn("chown -R 1000:1000 /workspace /home/codify", dockerfile)
        self.assertIn("keytool -help >/dev/null", dockerfile)
        self.assertNotIn("FROM python:", dockerfile)
        self.assertNotIn("python3", dockerfile)
        self.assertNotIn("openjdk-21-jdk", dockerfile)
        self.assertNotIn("apt-get install", dockerfile)
        self.assertNotIn("useradd --create-home --shell /bin/bash --uid 1000 codify", dockerfile)
        self.assertNotIn("claude.ai/install.sh", dockerfile)
        self.assertNotIn("COPY --from=claude-installer", dockerfile)
        self.assertNotIn("COPY deploy/entrypoint.worker.sh", dockerfile)
        self.assertNotIn("COPY deploy/worker-entrypoint/", dockerfile)
        self.assertNotIn("COPY deploy/ci-claude.sh", dockerfile)
        self.assertNotIn("@colbymchenry/codegraph", dockerfile)
        self.assertNotIn("mermaid@", dockerfile)
        self.assertNotIn("nodesource.com/setup_22.x", dockerfile)
        self.assertNotIn("ENTRYPOINT", dockerfile)

    def test_mock_worker_image_keeps_ssh_client_for_baked_entrypoint_tests(self):
        root = Path(__file__).resolve().parents[3]
        dockerfile = (
            root
            / "backend"
            / "tests"
            / "mock_integration"
            / "fake_claude"
            / "Dockerfile.worker-test"
        )

        content = dockerfile.read_text()
        self.assertIn("openssh-client \\", content)
        self.assertIn("&& ssh -V \\", content)

    def test_entrypoint_uses_codify_coauthor_and_git_author_env(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)

        self.assertIn('GIT_AUTHOR_NAME_VALUE', content)
        self.assertIn('GIT_AUTHOR_EMAIL_VALUE', content)
        self.assertIn('Co-authored-by: %s <%s>', content)
        self.assertIn('CODIFY_COAUTHOR_NAME_VALUE', content)
        self.assertIn('CODIFY_COAUTHOR_EMAIL_VALUE', content)
        self.assertNotIn('Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>', content)

    def test_entrypoint_configures_git_for_codify_runtime_user(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)

        self.assertIn('CODIFY_GIT_CONFIG="/home/codify/.gitconfig"', content)
        self.assertIn('/home/codify/.git-credentials', content)
        self.assertIn('git config --file "${CODIFY_GIT_CONFIG}" credential.helper store', content)
        self.assertIn('git config --file "${CODIFY_GIT_CONFIG}" user.email "bot@codify.local"', content)
        self.assertIn('git config --file "${CODIFY_GIT_CONFIG}" user.name "Codify Bot"', content)
        self.assertIn('git config --file "${CODIFY_GIT_CONFIG}" --add safe.directory /workspace', content)
        self.assertIn('codify_chown /home/codify/.git-credentials', content)
        self.assertIn('codify_chown "${CODIFY_GIT_CONFIG}"', content)
        self.assertIn('chown "${CODIFY_RUN_UID}:${CODIFY_RUN_GID}" "$@"', content)

    def test_entrypoint_includes_commit_message_in_finalization(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)

        self.assertIn('commit_message:$commit_message', content)
        self.assertIn('--arg commit_message "${FINAL_COMMIT_MESSAGE:-}"', content)

    def test_entrypoint_consumes_persisted_main_prompt(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)

        self.assertIn('CODIFY_TASK_PROMPT_FILE="${CODIFY_TASK_PROMPT_FILE:?Missing CODIFY_TASK_PROMPT_FILE}"', content)
        self.assertIn('cp "${CODIFY_TASK_PROMPT_FILE}" /tmp/claude_prompt.txt', content)
        self.assertNotIn("请直接完成下面的需求", content)

    def test_entrypoint_has_no_plan_main_prompt_fallback(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)
        self.assertNotIn("请分析下面的需求，给出详细的实施方案", content)
        self.assertIn('Task prompt file does not exist', content)
        self.assertIn('Task prompt file is empty', content)

    def test_entrypoint_validates_and_persists_delivery_summary(self):
        root = Path(__file__).resolve().parents[3]
        script = root / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)

        self.assertIn('DELIVERY_SUMMARY_FILE="${CODIFY_RUNTIME_DIR}/delivery-summary.md"', content)
        self.assertIn('DELIVERY_SUMMARY_VALIDATION_FILE="${CODIFY_RUNTIME_DIR}/delivery-summary-validation.json"', content)
        self.assertIn('prepare_delivery_summary "${FINAL_SUMMARY_CONTENT}"', content)
        self.assertIn('write_delivery_summary_artifacts "${FINAL_SUMMARY_CONTENT}"', content)
        self.assertIn('/opt/codify-mermaid/validate_mermaid_summary.mjs', content)
        self.assertIn('reason: "validator_unavailable"', content)
        self.assertIn('ok: false, diagramCount: 0', content)
        self.assertIn('cd /tmp && timeout 60 "${CODIFY_CLAUDE_BIN}" -p --bare --tools "" --permission-mode plan', content)
        self.assertNotIn("cd /workspace && /usr/local/bin/claude -p --dangerously-skip-permissions --no-session-persistence --output-format text --max-turns 3 --model \"${ANTHROPIC_MODEL}\" < /tmp/delivery-summary-repair-prompt.md", content)
        self.assertIn('delivery-summary.md', content)
        self.assertIn('delivery-summary-validation.json', content)
        self.assertIn('CODIFY_CODEGRAPH_ENABLED', content)
        self.assertIn('prepare_codegraph', content)
        self.assertIn('export PATH="${CODIFY_RUNTIME_PATH}" && codegraph init /workspace', content)
        self.assertIn('export PATH="${CODIFY_RUNTIME_PATH}" && codegraph sync /workspace', content)
        self.assertIn(
            'export PATH="${CODIFY_RUNTIME_PATH}" && codegraph install --target=claude --location=global --yes',
            content,
        )
        self.assertIn(
            'export PATH="${CODIFY_RUNTIME_PATH}" && codegraph uninstall --target=claude --location=global --yes',
            content,
        )
        self.assertNotIn('del(.mcpServers.codegraph)', content)
        self.assertNotIn('<!-- CODEGRAPH_START -->', content)

        worker_kit_dockerfile = (root / "deploy" / "Dockerfile.worker-kit").read_text()
        worker_kit_nix = (root / "deploy" / "worker-kit" / "default.nix").read_text()
        self.assertIn("COPY deploy/scripts/validate_mermaid_summary.mjs", worker_kit_dockerfile)
        self.assertIn("codify-worker-kit-node-tools", worker_kit_nix)

        runtime_dockerfile = (root / "deploy" / "Dockerfile.worker-java21-maven").read_text()
        self.assertNotIn("npm install --omit=dev mermaid", runtime_dockerfile)
        self.assertNotIn("deploy/scripts/validate_mermaid_summary.mjs", runtime_dockerfile)
        self.assertNotIn("@colbymchenry/codegraph", runtime_dockerfile)

        lifecycle = (root / "backend" / "app" / "core" / "worker_task_lifecycle.py").read_text()
        artifacts = (root / "backend" / "app" / "core" / "worker_task_artifacts.py").read_text()
        self.assertIn(
            '_CONTAINER_DELIVERY_SUMMARY_PATH = "/tmp/codify-runtime/delivery-summary.md"',
            artifacts,
        )
        self.assertIn('payload_kind="delivery_summary"', artifacts)
        self.assertIn('log_type="delivery_summary"', artifacts)
        self.assertIn('await _save_delivery_summary_from_container(worker, container, task, db)', lifecycle)

    def test_entrypoint_writes_plan_task_metadata_for_previous_summaries(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)
        function_definition = self._extract_shell_function(content, "write_plan_task_metadata")
        plan_exit_block = content.split('if [ "${TASK_MODE}" = "plan" ]; then', 1)[1].split(
            "fi",
            1,
        )[0]

        self.assertIn('printf \'%s\\n\' "${task_metadata}" > "${CODIFY_RUNTIME_DIR}/task-metadata.json"', function_definition)
        self.assertIn('execution_summary: $execution_summary', function_definition)
        self.assertIn('commit_sha: ""', function_definition)
        self.assertIn('commit_message: ""', function_definition)
        self.assertIn('new_files: []', function_definition)
        self.assertIn('write_plan_task_metadata "${FINAL_SUMMARY_CONTENT}"', plan_exit_block)
        self.assertLess(
            plan_exit_block.index('write_plan_task_metadata "${FINAL_SUMMARY_CONTENT}"'),
            plan_exit_block.index("create_runtime_archive"),
        )

    def test_entrypoint_generates_overall_summary_with_claude_cli(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)

        self.assertIn('FINAL_OVERALL_SUMMARY=""', content)
        self.assertIn('PREVIOUS_SUMMARY_FILE="${CODIFY_RUNTIME_DIR}/previous-task-summaries.md"', content)
        self.assertIn(
            'build_overall_summary_prompt "${PREVIOUS_SUMMARY_FILE}"',
            content,
        )
        self.assertIn('echo "Previous task summaries found:', content)
        self.assertIn('echo "Previous task summaries not found at', content)
        self.assertIn("< /tmp/overall_summary_prompt.txt", content)
        self.assertIn('echo "Claude overall summary generation succeeded"', content)
        self.assertIn('echo "Overall MR summary generated (${#FINAL_OVERALL_SUMMARY} chars)"', content)
        self.assertIn('echo "Claude overall summary normalized to empty; keeping previous MR summary"', content)
        self.assertIn('overall_summary_chars=${#FINAL_OVERALL_SUMMARY}', content)
        self.assertIn('--arg overall_summary "${FINAL_OVERALL_SUMMARY:-}"', content)
        self.assertIn('overall_summary: $overall_summary', content)
        self.assertNotIn("/messages", content)

    def test_entrypoint_sanitizes_generated_commit_message(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)
        function_definition = self._extract_shell_function(content, "normalize_model_commit_message")
        raw_message = textwrap.dedent(
            """
            <think>
            选择 docs 类型，因为 joke.md 是文档文件。
            </think>

            docs: 新增程序员笑话文件

            - 添加 joke.md

            AI-Generated: true

            docs: 后续说明不应被截断
            """
        ).strip()

        result = subprocess.run(
            ["bash", "-c", f"{function_definition}\nnormalize_model_commit_message \"$(cat)\""],
            input=raw_message,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertEqual(
            result.stdout,
            "docs: 新增程序员笑话文件\n\n- 添加 joke.md\n\nAI-Generated: true\n\ndocs: 后续说明不应被截断",
        )

    def test_entrypoint_does_not_clear_commit_message_for_unclosed_think_tag(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)
        function_definition = self._extract_shell_function(content, "normalize_model_commit_message")
        raw_message = "<think>\ndocs: 新增程序员笑话文件\n\nAI-Generated: true"

        result = subprocess.run(
            ["bash", "-c", f"{function_definition}\nnormalize_model_commit_message \"$(cat)\""],
            input=raw_message,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertEqual(
            result.stdout,
            "docs: 新增程序员笑话文件\n\nAI-Generated: true",
        )

    def test_entrypoint_logs_commit_message_generation_steps(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)

        self.assertIn('echo "Generating commit message with Claude..."', content)
        self.assertIn('echo "Commit message prompt written to /tmp/commit_message_prompt.txt"', content)
        self.assertIn('echo "Claude commit message generation succeeded"', content)
        self.assertIn('echo "Claude raw commit message response:"', content)
        self.assertIn("printf '%s\\n' \"${GENERATED_COMMIT_MESSAGE}\" | sed 's/^/  /'", content)
        self.assertIn('echo "Claude commit message generation failed with exit code ${COMMIT_MESSAGE_RESULT}; using fallback"', content)
        self.assertIn('echo "Generated commit message was empty after normalization; using fallback"', content)
        self.assertIn('echo "Commit message written to /tmp/commit_message.txt"', content)
        self.assertIn('echo "Final commit message:"', content)
        self.assertIn("sed 's/^/  /' /tmp/commit_message.txt", content)

    def test_entrypoint_pipes_commit_message_prompt_to_claude_stdin(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)

        self.assertIn("< /tmp/commit_message_prompt.txt", content)
        self.assertNotIn('"$(cat /tmp/commit_message_prompt.txt)"', content)

    def test_entrypoint_writes_system_prompt_file_for_ci_claude(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)

        self.assertIn('CLAUDE_SYSTEM_PROMPT_FILE="/tmp/claude_system_prompt.txt"', content)
        self.assertIn('printf \'%s\' "${APPEND_SYSTEM_PROMPT}" > "${CLAUDE_SYSTEM_PROMPT_FILE}"', content)
        self.assertIn('APPEND_SYSTEM_PROMPT_FILE="${CLAUDE_SYSTEM_PROMPT_FILE}"', content)

    def test_entrypoint_makes_issue_shared_dir_writable_without_traversing_cache_contents(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)

        self.assertIn('if [ -d /opt/codify-issue-shared ]; then', content)
        self.assertIn('codify_chown /opt/codify-issue-shared', content)
        self.assertNotIn('codify_chown -R /opt/codify-issue-shared', content)

    def test_entrypoint_does_not_recursively_chown_home_with_read_only_mounts(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)

        self.assertIn(
            'codify_chown /workspace /home/codify', content
        )
        self.assertIn('codify_chown -R "${CODIFY_RUNTIME_DIR}"', content)
        self.assertIn('codify_chown /home/codify/.m2/repository 2>/dev/null || true', content)
        self.assertNotIn('codify_chown -R /home/codify "${CODIFY_RUNTIME_DIR}"', content)

    def test_entrypoint_keeps_runtime_artifacts_outside_worktree_until_after_commit(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)

        self.assertIn('CODIFY_RUNTIME_DIR="${CODIFY_RUNTIME_DIR:-/tmp/codify-runtime}"', content)
        self.assertIn('CONSOLE_LOG="${CODIFY_RUNTIME_DIR}/console.log"', content)
        self.assertIn('tee -a "${CONSOLE_LOG}"', content)
        self.assertIn('exec > "${CONSOLE_TEE_PIPE}" 2>&1', content)
        self.assertIn('CI_CLAUDE_DISABLE_CONSOLE_TEE=1', content)
        self.assertIn('ARTIFACT_DIR="${CODIFY_RUNTIME_DIR}" CI_CLAUDE_DISABLE_CONSOLE_TEE=1 PROMPT_FILE=/tmp/claude_prompt.txt', content)
        self.assertIn('local archive_path="${CODIFY_RUNTIME_DIR}/${archive_name}"', content)
        self.assertIn('local archive_files=()', content)
        self.assertIn('repository-preparation.json', content)
        self.assertIn('tar -czf "${archive_path}" -C "${CODIFY_RUNTIME_DIR}" "${archive_files[@]}"', content)
        self.assertNotIn('[ -f "/workspace/event.jsonl" ]', content)
        self.assertNotIn('/workspace/.codify-archive', content)

        tee_index = content.index('exec > "${CONSOLE_TEE_PIPE}" 2>&1')
        banner_index = content.index('echo "Codify Worker"')
        self.assertLess(tee_index, banner_index)

        git_add_index = content.index('git add -A')
        archive_success_index = content.index('    create_runtime_archive\n\n    echo "========================================"')
        self.assertGreater(archive_success_index, git_add_index)

    def test_entrypoint_silences_update_ca_certificate_noise(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)

        self.assertIn('update-ca-certificates --fresh >/dev/null 2>&1 || true', content)
        self.assertNotIn('update-ca-certificates --fresh 2>/dev/null || true', content)

    def test_entrypoint_does_not_emit_legacy_codify_markers_to_console(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)

        for marker in [
            "CODIFY_STATS",
            "CODIFY_TOOL_CALLS",
            "CODIFY_SESSION_ID",
            "CODIFY_DIFF",
            "CODIFY_COMMIT_SHA",
            "CODIFY_MR_TITLE",
        ]:
            self.assertNotIn(f'echo "{marker}:', content)

    def test_entrypoint_reuses_existing_git_workspace_safely(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)

        self.assertIn('if [ -d /workspace/.git ]; then', content)
        self.assertIn(
            "codify_run_shell 'cd /workspace && git remote set-url origin \"${GIT_REPO_URL}\"'",
            content,
        )

    def test_entrypoint_supports_observable_shallow_partial_clone(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)

        self.assertIn('--depth "${CODIFY_GIT_CLONE_DEPTH}"', content)
        self.assertIn('--filter="${CODIFY_GIT_CLONE_FILTER}"', content)
        self.assertIn('--single-branch --branch "${BASE_BRANCH}"', content)
        self.assertIn(
            '"+refs/heads/${BRANCH_NAME}:refs/remotes/origin/${BRANCH_NAME}"',
            content,
        )
        self.assertIn(
            'git checkout --no-track -b "${BRANCH_NAME}" "origin/${BRANCH_NAME}"',
            content,
        )
        self.assertIn(
            'git ls-remote --symref "${GIT_REPO_URL}" HEAD '
            '"refs/heads/${BASE_BRANCH}" "refs/heads/${BRANCH_NAME}"',
            content,
        )
        self.assertIn(
            'git merge --ff-only "refs/remotes/origin/${BRANCH_NAME}"',
            content,
        )
        self.assertIn('relation=diverged', content)
        self.assertIn('reason=remote_changed', content)
        self.assertIn('reason=local_history_rewritten', content)
        self.assertIn('push_recovered result=remote_matches_local', content)
        self.assertIn('elif repo_has_unpublished_local_head; then', content)
        self.assertIn('action=push_existing_head', content)
        self.assertIn('write_existing_commit_delivery_metadata', content)
        self.assertIn(
            '--force-with-lease="refs/heads/${BRANCH_NAME}:${REPO_REMOTE_WORK_SHA}"',
            content,
        )
        self.assertIn(
            "export REPO_REMOTE_WORK_SHA REPO_PREVIOUS_REMOTE_WORK_SHA",
            content,
        )
        self.assertNotIn('git pull origin "${BRANCH_NAME}"', content)
        self.assertNotIn('git pull --depth "${CODIFY_GIT_CLONE_DEPTH}"', content)
        self.assertIn("workspace=nonempty git_metadata=missing; refusing clone", content)
        self.assertIn("ignored_by_server; continuing with full objects", content)
        self.assertIn("git config --unset-all remote.origin.promisor", content)
        self.assertIn("fallback retrying clone without object filter", content)
        self.assertIn("[repo] %s", content)
        self.assertIn("repository-preparation.json", content)
        self.assertIn('status: $status', content)
        self.assertIn('phase: $phase', content)
        self.assertIn('exit_code: $exit_code', content)
        self.assertIn(
            'git fetch origin "+refs/heads/${BASE_BRANCH}:refs/remotes/origin/${BASE_BRANCH}"',
            content,
        )
        self.assertIn(
            "WORKSPACE_CURRENT_BRANCH=$(codify_run_shell 'cd /workspace && git rev-parse --abbrev-ref HEAD'",
            content,
        )
        self.assertIn('Workspace has uncommitted changes on branch', content)
        self.assertIn(
            "codify_run_shell 'git clone \"${GIT_REPO_URL}\" /workspace'", content
        )
        self.assertIn('WORKSPACE_OWNERSHIP_MARKER="/opt/codify-issue-meta/ownership"', content)
        self.assertIn(
            'for persistent_path in /workspace /home/codify/.claude /opt/codify-issue-shared; do',
            content,
        )
        self.assertIn('codify_chown -R "${persistent_path}"', content)
        self.assertIn(
            "codify_run_shell 'cd /workspace && git remote set-url origin \"${GIT_REPO_URL}\"'",
            content,
        )
        self.assertNotIn(
            'codify_run_shell \'cd /workspace && git remote set-url origin "${GITLAB_SCHEME}://${GITLAB_HOST}/${PROJECT_PATH}.git"\'',
            content,
        )

    def test_entrypoint_runs_worker_custom_scripts_around_claude(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)

        self.assertIn('CODIFY_WORKER_PRE_SCRIPT_FILE="${CODIFY_RUNTIME_DIR}/worker-pre-script.sh"', content)
        self.assertIn('CODIFY_WORKER_POST_SCRIPT_FILE="${CODIFY_RUNTIME_DIR}/worker-post-script.sh"', content)
        self.assertIn('prepare_worker_script_file "${CODIFY_WORKER_PRE_SCRIPT_FILE}"', content)
        self.assertIn('prepare_worker_script_file "${CODIFY_WORKER_POST_SCRIPT_FILE}"', content)
        self.assertIn('chmod 700 "${script_path}"', content)
        self.assertIn('chmod 755 "${script_path}"', content)
        self.assertIn('run_worker_script "pre" "${CODIFY_WORKER_PRE_SCRIPT_FILE}"', content)
        self.assertIn('run_worker_script "post" "${CODIFY_WORKER_POST_SCRIPT_FILE}"', content)
        self.assertIn('codify_run_shell "cd /workspace && export PATH=', content)
        self.assertIn(r'\"${CODIFY_BASH}\" \"${script_path}\"', content)
        self.assertNotIn('echo "${CODIFY_WORKER_PRE_SCRIPT}"', content)
        self.assertNotIn('echo "${CODIFY_WORKER_POST_SCRIPT}"', content)

        pre_index = content.index('run_worker_script "pre" "${CODIFY_WORKER_PRE_SCRIPT_FILE}"')
        claude_index = content.index('echo "Starting Claude CLI (streaming mode)..."')
        post_index = content.index('run_worker_script "post" "${CODIFY_WORKER_POST_SCRIPT_FILE}"')
        changes_index = content.index(
            "CHANGES=$(codify_run_shell 'cd /workspace && git status --porcelain' || true)"
        )

        self.assertLess(pre_index, claude_index)
        self.assertGreater(post_index, claude_index)
        self.assertLess(post_index, changes_index)


    def test_entrypoint_no_changes_uses_require_changes_not_target_branch(self):
        script = Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.worker.sh"
        content = _read_worker_entrypoint_sources(script)

        self.assertIn('REQUIRE_CHANGES', content)
        self.assertIn('[ "${REQUIRE_CHANGES:-true}" = "false" ]', content)
        self.assertIn('require_changes disabled: task completed without code changes', content)


class TestBuildContainerVolumes(unittest.TestCase):
    """Tests for _build_container_volumes — lines 527-557."""

    def test_no_volumes(self):
        """Empty when no volume settings are configured."""
        settings = _make_settings()
        worker = _make_worker()

        volumes = worker._build_container_volumes(settings)

        self.assertEqual(volumes, {})

    def test_generic_volume_mounts_cover_maven_paths(self):
        """Maven paths can be mounted through generic worker volume mounts."""
        settings = _make_settings(
            worker_volume_mounts_parsed=[
                {
                    "host_path": "/host/.m2/repository",
                    "container_path": "/home/codify/.m2/repository",
                    "mode": "rw",
                },
                {
                    "host_path": "/host/settings.xml",
                    "container_path": "/home/codify/.m2/settings.xml",
                    "mode": "ro",
                },
            ]
        )
        worker = _make_worker()

        volumes = worker._build_container_volumes(settings)

        self.assertEqual(volumes["/host/.m2/repository"]["bind"], "/home/codify/.m2/repository")
        self.assertEqual(volumes["/host/.m2/repository"]["mode"], "rw")
        self.assertEqual(volumes["/host/settings.xml"]["bind"], "/home/codify/.m2/settings.xml")
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

    def test_issue_workspace_volumes_are_daemon_local(self):
        """Runtime input is uploaded, while persistent issue paths stay daemon-local."""
        settings = _make_settings(worker_workspace_host_path="/opt/codify-workspaces")
        worker = _make_worker()
        issue = MagicMock()
        issue.project_id = 123
        issue.id = 456
        issue.session_storage_path = "/var/codify/sessions/456/claude"
        task = MagicMock()
        task.id = 789

        repo_path = "/opt/codify-workspaces/project-123/issue-456/repo"
        claude_path = "/opt/codify-workspaces/project-123/issue-456/claude"
        shared_path = "/opt/codify-workspaces/project-123/issue-456/shared"
        meta_path = "/opt/codify-workspaces/project-123/issue-456/meta"

        volumes = worker._build_container_volumes(settings, issue, task=task)

        self.assertEqual(volumes[repo_path]["bind"], "/workspace")
        self.assertEqual(volumes[repo_path]["mode"], "rw")
        self.assertEqual(volumes[claude_path]["bind"], "/home/codify/.claude")
        self.assertEqual(volumes[claude_path]["mode"], "rw")
        self.assertEqual(volumes[shared_path]["bind"], "/opt/codify-issue-shared")
        self.assertEqual(volumes[shared_path]["mode"], "rw")
        self.assertEqual(volumes[meta_path]["bind"], "/opt/codify-issue-meta")
        self.assertEqual(volumes[meta_path]["mode"], "rw")
        self.assertNotIn("/var/codify/sessions/456/claude", volumes)
        self.assertNotIn("/tmp/codify-runtime", [v["bind"] for v in volumes.values()])

    def test_issue_workspace_volumes_disabled_when_setting_empty(self):
        settings = _make_settings(worker_workspace_host_path="")
        worker = _make_worker()
        issue = MagicMock(project_id=123, id=456)
        issue.session_storage_path = None
        task = MagicMock(id=789)

        volumes = worker._build_container_volumes(settings, issue, task=task)

        self.assertEqual(volumes, {})
        self.assertNotIn("/workspace", [v["bind"] for v in volumes.values()])
        self.assertNotIn("/tmp/codify-runtime", [v["bind"] for v in volumes.values()])
        self.assertNotIn("/opt/codify-issue-shared", [v["bind"] for v in volumes.values()])

    def test_legacy_session_storage_mount_skips_non_string_path(self):
        settings = _make_settings(worker_workspace_host_path="")
        worker = _make_worker()
        issue = MagicMock(project_id=123, id=456)
        issue.session_storage_path = MagicMock()
        task = MagicMock(id=789)

        volumes = worker._build_container_volumes(settings, issue, task=task)

        self.assertEqual(volumes, {})

    def test_legacy_session_storage_mount_used_when_workspace_disabled(self):
        settings = _make_settings(worker_workspace_host_path="")
        worker = _make_worker()
        issue = MagicMock(project_id=123, id=456)
        issue.session_storage_path = "/var/codify/sessions/456/claude"
        task = MagicMock(id=789)

        with patch("app.core.worker_runtime.os.makedirs"):
            volumes = worker._build_container_volumes(settings, issue, task=task)

        self.assertEqual(
            volumes["/var/codify/sessions/456/claude"],
            {"bind": "/home/codify/.claude", "mode": "rw"},
        )

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
        """Container name includes 'issue{issue_id}' suffix when task has an issue."""
        worker = _make_worker()
        task = _make_task(id=5, project_id=200, issue_id=42)

        name = worker._get_container_name(task)

        self.assertEqual(name, "codify-5-issue42")

    def test_name_with_different_issue_id(self):
        """Container name uses issue_id from task."""
        worker = _make_worker()
        task = _make_task(id=7, project_id=300, issue_id=99)

        name = worker._get_container_name(task)

        self.assertEqual(name, "codify-7-issue99")


# ===================================================================
# _create_mr_if_needed / _find_existing_mr / _create_new_mr
# ===================================================================

class TestCreateMrIfNeeded(unittest.TestCase):
    """Tests for MR creation flow — lines 384-472."""

    def test_reuses_existing_mr_iid(self):
        """When mr_iid is already set, return it unchanged — line 401-402."""
        worker = _make_worker()
        task = _make_task()
        issue = task.issue

        result = worker._create_mr_if_needed(task, issue, mr_iid=99, mr_web_url="http://example.com/mr/99")

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
        issue = task.issue

        result = worker._create_mr_if_needed(task, issue, mr_iid=None, mr_web_url=None)

        self.assertEqual(result, (77, "http://gitlab.example.com/mr/77"))

    def test_find_existing_mr_returns_none_when_no_mrs(self):
        """_find_existing_mr returns None when no open MRs — line 429-430."""
        mock_project = MagicMock()
        mock_project.mergerequests.list.return_value = []

        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.return_value = mock_project
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()
        issue = task.issue

        result = worker._find_existing_mr(task, issue)

        self.assertIsNone(result)

    def test_find_existing_mr_handles_exception(self):
        """_find_existing_mr returns None on API error — lines 436-438."""
        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.side_effect = Exception("Network error")
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()
        issue = task.issue

        result = worker._find_existing_mr(task, issue)

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
        issue = task.issue

        result = worker._create_new_mr(task, issue)

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
        issue = task.issue

        result = worker._create_new_mr(task, issue)

        self.assertEqual(result, (None, None))


# ===================================================================
# _parse_task_result
# ===================================================================

class TestParseTaskResult(unittest.TestCase):
    """Tests for _parse_task_result."""

    def test_ignores_codify_stats_marker(self):
        """Legacy CODIFY_STATS marker no longer sets token usage."""
        worker = _make_worker()
        task = _make_task()
        db = _make_db()
        logs = 'CODIFY_STATS:{"input_tokens": 500, "output_tokens": 150}\n'

        asyncio.run(worker._parse_task_result(task, logs, db, exit_code=0))

        self.assertIsNone(task.input_tokens)
        self.assertIsNone(task.output_tokens)

    def test_invalid_codify_stats_marker_is_ignored(self):
        """Invalid legacy CODIFY_STATS marker should not crash."""
        worker = _make_worker()
        task = _make_task()
        db = _make_db()
        logs = 'CODIFY_STATS:not-json\n'

        # Should not raise
        asyncio.run(worker._parse_task_result(task, logs, db, exit_code=0))

        self.assertIsNone(task.input_tokens)

    def test_ignores_codify_commit_sha_marker(self):
        """Legacy CODIFY_COMMIT_SHA marker no longer sets commit_sha."""
        worker = _make_worker()
        task = _make_task()
        db = _make_db()
        sha = "a" * 40
        logs = f'CODIFY_COMMIT_SHA:{sha}\n'

        asyncio.run(worker._parse_task_result(task, logs, db, exit_code=0))

        self.assertIsNone(task.commit_sha)

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
    """Tests for _parse_mr_from_logs — parses MR URL/IID to temp attributes."""

    def test_extracts_mr_from_url_in_logs(self):
        """Finds MR URL and IID from log output, stores as _parsed_* attrs."""
        mock_gitlab = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()

        logs = "Created MR: http://gitlab.example.com/project/-/merge_requests/42\nDone."

        asyncio.run(worker._parse_mr_from_logs(task, logs))

        self.assertEqual(task._parsed_mr_iid, 42)
        self.assertIn("merge_requests/42", task._parsed_mr_url)

    def test_derives_iid_from_url_when_missing(self):
        """Derives IID from MR URL when only URL is found."""
        mock_gitlab = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()

        logs = "http://gitlab.example.com/-/merge_requests/99\n"

        asyncio.run(worker._parse_mr_from_logs(task, logs))

        self.assertEqual(task._parsed_mr_iid, 99)

    def test_no_mr_in_logs_leaves_no_parsed_attrs(self):
        """No MR URL in logs → no _parsed_* attributes set."""
        mock_gitlab = MagicMock()
        worker = _make_worker(mock_gitlab=mock_gitlab)
        task = _make_task()

        asyncio.run(worker._parse_mr_from_logs(task, "no mr url here"))

        self.assertFalse(hasattr(task, '_parsed_mr_iid'))
        self.assertFalse(hasattr(task, '_parsed_mr_url'))


# ===================================================================
# _update_mr_description_for_issue
# ===================================================================

class TestUpdateMrDescriptionForIssue(IsolatedAsyncioTestCase):
    """Tests for _update_mr_description_for_issue — comprehensive MR description."""

    def _make_issue(self, **kwargs):
        issue = MagicMock()
        issue.id = kwargs.get("id", 10)
        issue.title = kwargs.get("title", "Test Issue")
        issue.description = kwargs.get("description", "Some description")
        issue.merge_request_iid = kwargs.get("merge_request_iid", 5)
        issue.gitlab_issue_iid = None
        issue.project_id = kwargs.get("project_id", 100)
        return issue

    async def test_builds_description_with_all_tasks(self):
        """Builds MR description from issue + all tasks (no metadata)."""
        mock_mr = MagicMock()
        mock_mr.description = ""

        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.return_value.mergerequests.get.return_value = mock_mr
        worker = _make_worker(mock_gitlab=mock_gitlab)

        issue = self._make_issue()

        task1 = _make_task(id=1)
        task1.user_prompt = "Prompt 1"
        task1.status = TaskStatus.COMPLETED
        task1.issue_id = 10

        task2 = _make_task(id=2)
        task2.user_prompt = "Prompt 2"
        task2.status = TaskStatus.FAILED
        task2.issue_id = 10

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [task1, task2]
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.core.worker_gitlab.load_task_metadata", return_value={}):
            with patch("app.core.worker_gitlab.get_settings") as mock_settings:
                mock_settings.return_value = _make_settings(
                    dashboard_url="http://codify.example.com"
                )
                await worker._update_mr_description_for_issue(task1, issue, mock_db)

        desc = mock_mr.description
        self.assertNotIn("## Test Issue", desc)  # title not repeated in description body
        self.assertIn("Some description", desc)
        self.assertIn("✅", desc)
        self.assertIn("❌", desc)
        self.assertIn("http://codify.example.com/issues/10", desc)
        mock_mr.save.assert_called_once()

    async def test_builds_description_with_metadata(self):
        """Builds enriched MR description when task-metadata.json files are present."""
        mock_mr = MagicMock()
        mock_mr.description = ""

        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.return_value.mergerequests.get.return_value = mock_mr
        worker = _make_worker(mock_gitlab=mock_gitlab)

        issue = self._make_issue()

        task1 = _make_task(id=1)
        task1.user_prompt = "Add JWT auth"
        task1.status = TaskStatus.COMPLETED
        task1.issue_id = 10
        task1.additions = 120
        task1.deletions = 45
        task1.commit_message = "feat: add JWT auth"

        task2 = _make_task(id=2)
        task2.user_prompt = "Fix token expiry"
        task2.status = TaskStatus.COMPLETED
        task2.issue_id = 10
        task2.additions = 15
        task2.deletions = 3
        task2.commit_message = "fix: token expiry"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [task1, task2]
        mock_db.execute = AsyncMock(return_value=mock_result)

        metadata_map = {
            1: {
                "task_id": 1,
                "prompt": "Add JWT auth",
                "commit_sha": "abc1234567890",
                "commit_message": "feat: add JWT auth\n\nAI-Generated: true",
                "execution_summary": "Implemented JWT authentication using RS256.",
                "new_files": ["src/auth.py", "tests/test_auth.py"],
                "modified_files": ["src/main.py"],
                "deleted_files": [],
                "additions": 120,
                "deletions": 45,
            },
            2: {
                "task_id": 2,
                "prompt": "Fix token expiry",
                "commit_sha": "def5678901234",
                "commit_message": "fix: token expiry\n\nAI-Generated: true",
                "overall_summary": (
                    "- 认证能力已完成并覆盖令牌过期处理。\n"
                    "- 相关验证已补充。"
                ),
                "execution_summary": "Fixed token expiry handling.",
                "new_files": [],
                "modified_files": ["src/main.py", "src/config.py"],
                "deleted_files": [],
                "additions": 15,
                "deletions": 3,
            },
        }

        with patch(
            "app.core.worker_gitlab.load_task_metadata", return_value=metadata_map
        ):
            with patch("app.core.worker_gitlab.get_settings") as mock_settings:
                mock_settings.return_value = _make_settings(
                    dashboard_url="http://codify.example.com"
                )
                await worker._update_mr_description_for_issue(task1, issue, mock_db)

        desc = mock_mr.description
        # Codify issue link
        self.assertIn("http://codify.example.com/issues/10", desc)
        # AI-generated cross-task summary section
        self.assertIn("📋 总体总结", desc)
        self.assertIn("认证能力已完成并覆盖令牌过期处理", desc)
        self.assertIn("相关验证已补充", desc)
        self.assertNotIn("Task #1 - feat: add JWT auth", desc)
        self.assertNotIn("整体变更", desc)
        self.assertNotIn("新增文件", desc)
        self.assertNotIn("修改文件", desc)
        # Execution record table
        self.assertIn("🔖 执行记录", desc)
        self.assertIn("feat: add JWT auth", desc)
        self.assertIn("fix: token expiry", desc)
        # Per-task details
        self.assertIn("<details>", desc)
        self.assertIn("Implemented JWT authentication", desc)
        self.assertIn("abc1234567890"[:12], desc)
        mock_mr.save.assert_called_once()

    async def test_skips_when_no_mr_iid(self):
        """Does nothing when issue has no MR."""
        worker = _make_worker()
        issue = MagicMock()
        issue.merge_request_iid = None
        mock_db = AsyncMock()

        await worker._update_mr_description_for_issue(_make_task(), issue, mock_db)
        mock_db.execute.assert_not_called()

    async def test_skips_when_mr_not_found(self):
        """Returns early when project.mergerequests.get raises (MR not found in GitLab)."""
        mock_mr = MagicMock()
        mock_project = MagicMock()
        mock_project.mergerequests.get.side_effect = Exception("404 MR not found")
        mock_project.mergerequests.get.return_value = mock_mr  # never reached
        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.return_value = mock_project
        worker = _make_worker(mock_gitlab=mock_gitlab)

        issue = self._make_issue()

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.core.worker_gitlab.load_task_metadata", return_value={}):
            with patch("app.core.worker_gitlab.get_settings") as mock_settings:
                mock_settings.return_value = _make_settings()
                await worker._update_mr_description_for_issue(_make_task(), issue, mock_db)

        # Verify get() was invoked (correct code path) but save() was never called
        mock_project.mergerequests.get.assert_called_once()
        mock_mr.save.assert_not_called()

    async def test_preserves_existing_overall_summary_when_metadata_has_no_summary(self):
        """Keeps the previous overall summary if task metadata has no new summary."""
        mock_mr = MagicMock()
        mock_mr.description = """Some description

---

## 📋 总体总结

- 旧的总体总结

---

## 🔖 执行记录
"""

        mock_gitlab = MagicMock()
        mock_gitlab.gl.projects.get.return_value.mergerequests.get.return_value = mock_mr
        worker = _make_worker(mock_gitlab=mock_gitlab)

        issue = self._make_issue()
        task1 = _make_task(id=1)
        task1.user_prompt = "Add JWT auth"
        task1.status = TaskStatus.COMPLETED
        task1.issue_id = 10
        task1.commit_message = "feat: add JWT auth"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [task1]
        mock_db.execute = AsyncMock(return_value=mock_result)

        metadata_map = {
            1: {
                "task_id": 1,
                "prompt": "Add JWT auth",
                "commit_message": "feat: add JWT auth",
                "execution_summary": "Implemented JWT authentication.",
            },
        }

        with patch(
            "app.core.worker_gitlab.load_task_metadata", return_value=metadata_map
        ):
            with patch("app.core.worker_gitlab.get_settings") as mock_settings:
                mock_settings.return_value = _make_settings(
                    dashboard_url="http://codify.example.com"
                )
                await worker._update_mr_description_for_issue(task1, issue, mock_db)

        self.assertIn("📋 总体总结", mock_mr.description)
        self.assertIn("旧的总体总结", mock_mr.description)


# ===================================================================
# load_task_metadata_files
# ===================================================================

class TestLoadTaskMetadata(unittest.TestCase):
    """Tests for task metadata persisted in the database."""

    def test_returns_empty_without_persisted_metadata(self):
        from app.core.worker_gitlab import load_task_metadata

        tasks = [_make_task(id=1), _make_task(id=2)]
        tasks[0].worker_metadata = None
        tasks[1].worker_metadata = "not-an-object"

        self.assertEqual(load_task_metadata(tasks), {})

    def test_reads_metadata_from_task_rows(self):
        from app.core.worker_gitlab import load_task_metadata

        task = _make_task(id=42)
        task.worker_metadata = {
            "task_id": 42,
            "commit_sha": "abc1234",
            "new_files": ["src/foo.py"],
        }

        result = load_task_metadata([task])

        self.assertEqual(result[42]["commit_sha"], "abc1234")
        self.assertEqual(result[42]["new_files"], ["src/foo.py"])


# ===================================================================
# overall MR summary helpers
# ===================================================================

class TestOverallMrSummaryHelpers(unittest.TestCase):
    """Tests for overall MR summary helpers."""

    def test_latest_overall_summary_uses_newest_metadata(self):
        from app.core.worker_gitlab import _latest_overall_summary

        task1 = _make_task(id=1)
        task2 = _make_task(id=2)
        result = _latest_overall_summary(
            [task1, task2],
            {
                1: {"overall_summary": "- 旧总结"},
                2: {"overall_summary": "- 新总结</details>"},
            },
        )

        self.assertEqual(result, "- 新总结&lt;/details&gt;")

    def test_latest_overall_summary_returns_none_without_metadata_summary(self):
        from app.core.worker_gitlab import _latest_overall_summary

        result = _latest_overall_summary(
            [_make_task(id=1)],
            {1: {"execution_summary": "任务摘要"}},
        )

        self.assertIsNone(result)

    def test_extracts_existing_overall_summary(self):
        """Extracts the existing overall summary block from an MR description."""
        from app.core.worker_gitlab import _extract_existing_overall_summary

        result = _extract_existing_overall_summary("""Intro

## 📋 总体总结

- 已完成主要能力
- 验证通过

---

## 🔖 执行记录
""")

        self.assertEqual(result, "- 已完成主要能力\n- 验证通过")

    def test_builds_previous_task_summaries_content(self):
        from app.core.worker_gitlab import _build_previous_task_summaries_content

        issue = MagicMock()
        issue.title = "Auth Issue"
        issue.description = "Implement authentication"
        task1 = _make_task(id=1)
        task1.status = TaskStatus.COMPLETED
        task2 = _make_task(id=2)
        task2.status = TaskStatus.FAILED
        metadata_map = {
            1: {
                "prompt": "Add JWT auth",
                "commit_message": "feat: add auth",
                "execution_summary": "Implemented JWT authentication.\nAdded tests.",
            },
            2: {
                "prompt": "Fix token expiry",
                "commit_message": "fix: token expiry",
                "execution_summary": "Fixed token expiry handling.</details>",
            },
        }

        result = _build_previous_task_summaries_content(issue, [task1, task2], metadata_map)

        self.assertIn("# Previous Task Summaries", result)
        self.assertIn("Task #1", result)
        self.assertIn("Implemented JWT authentication. Added tests.", result)
        self.assertIn("Fixed token expiry handling.&lt;/details&gt;", result)

    def test_builds_empty_previous_task_summaries_content(self):
        from app.core.worker_gitlab import _build_previous_task_summaries_content

        issue = MagicMock()
        issue.title = "Issue title"
        issue.description = ""

        result = _build_previous_task_summaries_content(issue, [], {})

        self.assertIn("暂无前序任务摘要。", result)


class TestBuildPreviousTaskSummaries(IsolatedAsyncioTestCase):
    """Tests for previous task summaries uploaded in the runtime bundle."""

    async def test_returns_empty_when_database_query_fails(self):
        from app.core.worker_gitlab import build_previous_task_summaries

        issue = MagicMock(id=10, project_id=100)
        current_task = _make_task(id=3, issue_id=10, project_id=100)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=RuntimeError("database unavailable"))

        content = await build_previous_task_summaries(mock_db, issue, current_task)

        self.assertEqual(content, "")

    async def test_builds_previous_task_summaries_from_database_metadata(self):
        from app.core.worker_gitlab import build_previous_task_summaries

        issue = MagicMock()
        issue.id = 10
        issue.project_id = 100
        issue.title = "Auth Issue"
        issue.description = "Implement auth"
        current_task = _make_task(id=3, issue_id=10, project_id=100)
        previous_task = _make_task(id=2, issue_id=10, project_id=100)
        previous_task.status = TaskStatus.COMPLETED
        previous_task.worker_metadata = {
            "task_id": 2,
            "prompt": "Add JWT auth",
            "commit_message": "feat: add auth",
            "execution_summary": "Implemented JWT authentication.",
        }

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [previous_task]
        mock_db.execute = AsyncMock(return_value=mock_result)

        content = await build_previous_task_summaries(mock_db, issue, current_task)

        self.assertIn("Task #2", content)
        self.assertIn("Implemented JWT authentication.", content)
        self.assertIn("Auth Issue", content)




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

    def setUp(self):
        self._sleep_patcher = patch('asyncio.sleep', new_callable=AsyncMock)
        self._sleep_patcher.start()

    def tearDown(self):
        self._sleep_patcher.stop()

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

        with (
            patch.object(
                worker,
                '_stream_logs_to_db',
                new=AsyncMock(return_value=(0, fake_logs, 1, False)),
            ),
            patch(
                "app.core.worker_task_lifecycle.finalize_task_raw_logs",
                new=AsyncMock(),
            ),
        ):
            result = asyncio.run(worker.execute_task(db, task.id))

        self.assertTrue(result)
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertIsNone(task.container_id)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_execute_task_upserts_usage_ledger_for_finished_task(self, mock_notify, mock_get_settings):
        """Finished tasks with parsed usage should be written to the quota ledger."""
        mock_get_settings.return_value = _make_settings()
        mock_gitlab = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        mock_docker = MagicMock()
        mock_docker.create_container.return_value = MagicMock(id="ctr-usage")

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=None, initiator_user_id=7)
        db = _make_db(task)

        fake_logs = (
            "http://gitlab.example.com/project/-/merge_requests/42\n"
            "CODIFY_DIFF:+10-5\n"
            'CODIFY_STATS:{"input_tokens":100,"output_tokens":50}\n'
        )

        with (
            patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, fake_logs, 1, False))),
            patch("app.core.worker.upsert_task_usage_ledger", new=AsyncMock()) as mock_upsert,
        ):
            result = asyncio.run(worker.execute_task(db, task.id))

        self.assertTrue(result)
        mock_upsert.assert_awaited_once_with(db, task)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_fresh_task_snapshots_empty_input_and_disables_resume(
        self,
        mock_notify,
        mock_get_settings,
    ):
        mock_get_settings.return_value = _make_settings()
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = MagicMock(id="ctr-fresh-session")
        worker = _make_worker(mock_docker=mock_docker)
        task = _make_task(target_branch=None, session_mode="fresh")
        task.issue.claude_session_id = "session-old"
        db = _make_db(task)

        with patch.object(
            worker,
            '_stream_logs_to_db',
            new=AsyncMock(return_value=(0, "", 1, False)),
        ):
            result = asyncio.run(worker.execute_task(db, task.id))

        self.assertTrue(result)
        self.assertIsNone(task.input_session_id)
        environment = mock_docker.create_container.call_args.kwargs["environment"]
        self.assertEqual(environment["START_FRESH_SESSION"], "1")
        self.assertNotIn("RESUME_SESSION", environment)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_execute_task_upserts_usage_ledger_when_post_parse_commit_fails(
        self,
        mock_notify,
        mock_get_settings,
    ):
        """Post-parse failures should still attempt quota ledger persistence."""
        mock_get_settings.return_value = _make_settings()
        mock_gitlab = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        mock_docker = MagicMock()
        mock_docker.create_container.return_value = MagicMock(id="ctr-usage-fail")

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch=None, merge_request_iid=None, initiator_user_id=7)
        db = _make_db(task)
        post_parse_commit_failed = False

        async def fail_first_post_parse_commit():
            nonlocal post_parse_commit_failed
            if (
                not post_parse_commit_failed
                and task.status == TaskStatus.COMPLETED
                and task.completed_at is not None
            ):
                post_parse_commit_failed = True
                raise RuntimeError("post-parse commit failed")

        db.commit = AsyncMock(side_effect=fail_first_post_parse_commit)

        fake_logs = (
            "http://gitlab.example.com/project/-/merge_requests/42\n"
            "CODIFY_DIFF:+10-5\n"
            'CODIFY_STATS:{"input_tokens":100,"output_tokens":50}\n'
        )

        with (
            patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, fake_logs, 1, False))),
            patch("app.core.worker.upsert_task_usage_ledger", new=AsyncMock()) as mock_upsert,
        ):
            result = asyncio.run(worker.execute_task(db, task.id))

        self.assertFalse(result)
        self.assertTrue(post_parse_commit_failed)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.error_message, "post-parse commit failed")
        mock_upsert.assert_awaited_once_with(db, task)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_execute_task_loads_snapshot_custom_environment(
        self,
        mock_notify,
        mock_get_settings,
    ):
        """execute_task loads snapshot worker env vars and passes them into container env building."""
        mock_get_settings.return_value = _make_settings()

        mock_gitlab = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        mock_docker = MagicMock()
        mock_docker.create_container.return_value = MagicMock(id="ctr-custom-env")

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=None)
        task.worker_profile_snapshot.environment_variables = [
            {"key": "FEATURE_FLAG", "value": "enabled", "is_secret": False},
            {"key": "EMPTY_ALLOWED", "value": "", "is_secret": False},
        ]
        db = _make_db(task)

        with (
            patch.object(worker, '_build_container_env', return_value={"TASK_ID": "1"}) as mock_build_container_env,
            patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, "CODIFY_DIFF:+1-0\n", 1, False))),
        ):
            result = asyncio.run(worker.execute_task(db, task.id))

        self.assertTrue(result)
        self.assertEqual(
            mock_build_container_env.call_args.kwargs["custom_environment"],
            {"FEATURE_FLAG": "enabled", "EMPTY_ALLOWED": ""},
        )

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_execute_task_uploads_snapshot_custom_scripts_before_container_start(
        self,
        mock_notify,
        mock_get_settings,
    ):
        with tempfile.TemporaryDirectory() as workspace_root:
            mock_get_settings.return_value = _make_settings(
                worker_workspace_host_path=workspace_root,
                worker_pre_script="echo legacy-pre",
                worker_post_script="echo legacy-post",
            )
            mock_gitlab = MagicMock()
            mock_gitlab.normalize_web_url.side_effect = lambda x: x
            mock_gitlab.create_note = MagicMock()
            mock_gitlab.create_mr_note = MagicMock()

            mock_docker = MagicMock()
            mock_docker.create_container.return_value = MagicMock(id="ctr-custom-scripts")

            worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
            task = _make_task(target_branch="main", merge_request_iid=None)
            task.worker_profile_snapshot.pre_script = "echo snapshot-pre"
            task.worker_profile_snapshot.post_script = "echo snapshot-post"
            db = _make_db(task)

            with patch.object(
                worker,
                '_stream_logs_to_db',
                new=AsyncMock(return_value=(0, "CODIFY_DIFF:+1-0\n", 1, False)),
            ):
                result = asyncio.run(worker.execute_task(db, task.id))

            self.assertTrue(result)
            runtime_archive = mock_docker.put_archive.call_args.args[2]
            with tarfile.open(fileobj=io.BytesIO(runtime_archive)) as archive:
                pre_script = archive.extractfile(
                    "codify-runtime/worker-pre-script.sh"
                ).read()
                post_script = archive.extractfile(
                    "codify-runtime/worker-post-script.sh"
                ).read()
            self.assertEqual(pre_script, b"echo snapshot-pre\n")
            self.assertEqual(post_script, b"echo snapshot-post\n")
            self.assertTrue(
                mock_docker.create_container.call_args.kwargs["start"] is False
            )
            self.assertIsNone(
                mock_docker.create_container.call_args.kwargs.get("tmpfs"),
                "runtime uploads to a created container must not be hidden by a startup tmpfs",
            )
            mock_docker.start_container.assert_called_once()
            container_env = mock_docker.create_container.call_args.kwargs["environment"]
            self.assertNotIn("CODIFY_WORKER_PRE_SCRIPT", container_env)
            self.assertNotIn("CODIFY_WORKER_POST_SCRIPT", container_env)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_execute_task_persists_failure_for_invalid_snapshot_custom_environment_key(
        self,
        mock_notify,
        mock_get_settings,
    ):
        """execute_task persists failure state for invalid snapshot custom env keys."""
        mock_get_settings.return_value = _make_settings()

        mock_gitlab = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        mock_docker = MagicMock()
        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch=None, merge_request_iid=None)
        task.worker_profile_snapshot.environment_variables = [
            {"key": "TASK_ID", "value": "reserved", "is_secret": False},
        ]
        db = _make_db(task)

        with (
            patch('app.core.worker_task_runner.logger') as mock_logger,
        ):
            result = asyncio.run(worker.execute_task(db, task.id))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIsNotNone(task.completed_at)
        self.assertIn("TASK_ID", task.error_message)
        self.assertIn("reserved", task.error_message)
        mock_logger.error.assert_called_once()
        self.assertIn(
            "Failed while building worker environment",
            mock_logger.error.call_args.args[0],
        )
        mock_logger.exception.assert_not_called()
        mock_notify.assert_awaited_once()
        mock_docker.create_container.assert_not_called()

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_task_failure_sets_failed_status(self, mock_notify, mock_get_settings):
        """Failed task sets status to FAILED."""
        mock_get_settings.return_value = _make_settings()
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = MagicMock(id="ctr-456")

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=None)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(1, "error output", 1, False))):
            result = asyncio.run(worker.execute_task(db, task.id))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)

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

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(1, "error output", 1, False))):
            result = asyncio.run(worker.execute_task(db, task.id))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_task_exception_sets_failed_and_retains_logs(self, mock_notify, mock_get_settings):
        """Execution exceptions retain the stopped container until raw logs are finalized."""
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
        mock_docker.remove_container.assert_not_called()
        self.assertEqual(task.container_id, "ctr-err")

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

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, fake_logs, 1, False))):
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
            with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, fake_logs, 1, False))):
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

        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, "CODIFY_DIFF:+1-0\n", 0, False))):
            asyncio.run(worker.execute_task(db, task.id))

        # Should have added a fallback log entry
        added_entries = [call[0][0] for call in db.add.call_args_list if isinstance(call[0][0], TaskLog)]
        info_entries = [e for e in added_entries if e.log_level == "INFO"]
        self.assertTrue(len(info_entries) >= 1)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_execute_task_clears_old_logs(self, mock_notify, mock_get_settings):
        """execute_task() deletes previous TaskLog entries before starting."""
        mock_get_settings.return_value = _make_settings()
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = MagicMock(id="ctr-clear")

        mock_gitlab = MagicMock()
        mock_gitlab.normalize_web_url.side_effect = lambda x: x
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=None)
        db = _make_db(task)

        # Track execute calls to verify DELETE happens before anything else
        execute_calls = []
        original_execute = db.execute

        async def tracking_execute(stmt, *args, **kwargs):
            execute_calls.append(str(stmt))
            return await original_execute(stmt, *args, **kwargs)

        db.execute = AsyncMock(side_effect=tracking_execute)

        fake_logs = "CODIFY_DIFF:+1-0\n"
        with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, fake_logs, 1, False))):
            asyncio.run(worker.execute_task(db, task.id))

        # The first execute call should be the DELETE for TaskLog
        self.assertTrue(len(execute_calls) >= 2, "Expected at least 2 db.execute calls")
        # First call: SELECT task; second call: DELETE logs
        delete_found = any('task_logs' in call.lower() or 'DELETE' in call for call in execute_calls[:3])
        self.assertTrue(delete_found, f"Expected DELETE on task_logs in early calls: {execute_calls[:3]}")

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_task_timeout_sets_error_message_prefix(self, mock_notify, mock_get_settings):
        """When timed_out=True, error_message starts with timeout prefix."""
        mock_get_settings.return_value = _make_settings(task_timeout=1800)
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = MagicMock(id="ctr-timeout")

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=None)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db',
                          new=AsyncMock(return_value=(-1, "running...", 1, True))):
            result = asyncio.run(worker.execute_task(db, task.id))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("Task timed out after 1800s", task.error_message)

    @patch('app.core.worker.get_settings')
    @patch('app.core.worker.notify_task_event', new_callable=AsyncMock)
    def test_task_non_timeout_failure_regular_error_message(self, mock_notify, mock_get_settings):
        """When timed_out=False and exit_code!=0, error_message is log tail without timeout prefix."""
        mock_get_settings.return_value = _make_settings(task_timeout=1800)
        mock_docker = MagicMock()
        mock_docker.create_container.return_value = MagicMock(id="ctr-regular-fail")

        mock_gitlab = MagicMock()
        mock_gitlab.create_note = MagicMock()
        mock_gitlab.create_mr_note = MagicMock()

        worker = _make_worker(mock_gitlab=mock_gitlab, mock_docker=mock_docker)
        task = _make_task(target_branch="main", merge_request_iid=None)
        db = _make_db(task)

        with patch.object(worker, '_stream_logs_to_db',
                          new=AsyncMock(return_value=(1, "claude error occurred", 1, False))):
            result = asyncio.run(worker.execute_task(db, task.id))

        self.assertFalse(result)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertNotIn("Task timed out", task.error_message)
        self.assertIn("claude error occurred", task.error_message)


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


class TestDeployComposeWorkspaceMounts(unittest.TestCase):
    def test_backend_compose_only_mounts_local_ci_bundle_directory(self):
        compose = Path(__file__).resolve().parents[3] / "deploy" / "docker-compose.yml"
        content = compose.read_text()

        workspace_path = "${WORKER_WORKSPACE_HOST_PATH:-/opt/codify-workspaces}"
        ci_bundle_path = "${CI_FAILURE_BUNDLE_HOST_PATH:-/opt/codify-ci-failures}"
        self.assertEqual(content.count(f"source: {workspace_path}"), 0)
        self.assertGreaterEqual(content.count(f"source: {ci_bundle_path}"), 2)
        self.assertGreaterEqual(content.count(f"target: {workspace_path}/ci-failures"), 2)
        self.assertGreaterEqual(
            content.count(f"WORKER_WORKSPACE_HOST_PATH={workspace_path}"),
            2,
        )
        makefile = Path(__file__).resolve().parents[3] / "Makefile"
        self.assertIn("docker-compose --env-file .env.test up -d --build", makefile.read_text())

    def test_offline_compose_only_mounts_local_ci_bundle_directory(self):
        compose = Path(__file__).resolve().parents[3] / "deploy" / "offline-bundle" / "docker-compose.yml"
        content = compose.read_text()

        workspace_path = "${WORKER_WORKSPACE_HOST_PATH:-/opt/codify-workspaces}"
        ci_bundle_path = "${CI_FAILURE_BUNDLE_HOST_PATH:-/opt/codify-ci-failures}"
        self.assertEqual(content.count(f"source: {workspace_path}"), 0)
        self.assertGreaterEqual(content.count(f"source: {ci_bundle_path}"), 2)
        self.assertGreaterEqual(content.count(f"target: {workspace_path}/ci-failures"), 2)
        self.assertGreaterEqual(
            content.count(f"WORKER_WORKSPACE_HOST_PATH={workspace_path}"),
            2,
        )


class TestRequireChangesEnvVar(unittest.TestCase):
    def test_build_container_env_includes_require_changes(self):
        from app.core.worker_runtime import build_container_env

        task = MagicMock()
        task.id = 1
        task.issue_id = 1
        task.project_id = 1
        task.user_prompt = "test"
        task.require_changes = True

        issue = MagicMock()
        issue.id = 1
        issue.branch_name = "codify/issue-1"
        issue.title = "Test"
        issue.claude_session_id = None
        issue.base_branch = None

        with patch("app.core.worker_runtime.get_settings") as mock_settings:
            settings = MagicMock()
            settings.gitlab_url = "http://gitlab.example.com"
            settings.gitlab_bot_token = "token"
            settings.anthropic_api_key = "key"
            settings.anthropic_base_url = "http://api.example.com"
            settings.anthropic_model = "claude"
            settings.claude_max_turns = 10
            settings.task_timeout = 1800
            settings.custom_ca_bundle = ""
            mock_settings.return_value = settings

            env = build_container_env(task, issue, mr_iid=None, target_branch="main")

        self.assertIn("REQUIRE_CHANGES", env)
        self.assertEqual(env["REQUIRE_CHANGES"], "true")

    def test_build_container_env_require_changes_false(self):
        from app.core.worker_runtime import build_container_env

        task = MagicMock()
        task.id = 1
        task.issue_id = 1
        task.project_id = 1
        task.user_prompt = "test"
        task.require_changes = False

        issue = MagicMock()
        issue.id = 1
        issue.branch_name = "codify/issue-1"
        issue.title = "Test"
        issue.claude_session_id = None
        issue.base_branch = None

        with patch("app.core.worker_runtime.get_settings") as mock_settings:
            settings = MagicMock()
            settings.gitlab_url = "http://gitlab.example.com"
            settings.gitlab_bot_token = "token"
            settings.anthropic_api_key = "key"
            settings.anthropic_base_url = "http://api.example.com"
            settings.anthropic_model = "claude"
            settings.claude_max_turns = 10
            settings.task_timeout = 1800
            settings.custom_ca_bundle = ""
            mock_settings.return_value = settings

            env = build_container_env(task, issue, mr_iid=None, target_branch="main")

        self.assertEqual(env["REQUIRE_CHANGES"], "false")


if __name__ == "__main__":
    unittest.main()
