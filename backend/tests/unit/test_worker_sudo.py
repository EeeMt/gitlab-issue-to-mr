"""Unit tests for MR sudo impersonation in WorkerExecutor."""

import unittest
from unittest.mock import MagicMock, patch


class TestWorkerSudoMrCreation(unittest.TestCase):
    """Tests for sudo GL usage in _create_new_mr."""

    def _make_worker(self, admin_token="glpat-admin"):
        """Create a WorkerExecutor with mocked clients."""
        with patch('app.core.worker.get_docker_client'), \
             patch('app.core.worker.get_gitlab_client') as mock_get_gl:
            mock_gl_client = MagicMock()
            mock_gl_client.settings = MagicMock()
            mock_gl_client.settings.gitlab_admin_token = admin_token
            mock_gl_client.gl = MagicMock()
            mock_gl_client.normalize_web_url.return_value = "http://gitlab.test/mr/1"
            mock_get_gl.return_value = mock_gl_client
            from app.core.worker import WorkerExecutor
            worker = WorkerExecutor()
        return worker

    def _make_task(self, initiator_gitlab_user_id=None):
        """Create a mock Task."""
        task = MagicMock()
        task.id = 1
        task.project_id = 10
        task.initiator_gitlab_user_id = initiator_gitlab_user_id
        task.issue = MagicMock()
        task.issue.title = "Test issue"
        return task

    def _make_issue(self):
        """Create a mock Issue."""
        issue = MagicMock()
        issue.branch_name = "feature-branch"
        issue.target_branch = "main"
        issue.merge_request_iid = None
        issue.merge_request_url = None
        return issue

    def test_create_mr_uses_sudo_gl_when_provided(self):
        """MR should be created using sudo GL instance."""
        worker = self._make_worker()
        task = self._make_task()
        issue = self._make_issue()

        sudo_gl = MagicMock()
        mock_mr = MagicMock()
        mock_mr.iid = 42
        mock_mr.web_url = "http://gitlab.test/mr/42"
        sudo_gl.projects.get.return_value.mergerequests.create.return_value = mock_mr

        mr_iid, mr_url = worker._create_new_mr(task, issue, sudo_gl=sudo_gl)

        self.assertEqual(mr_iid, 42)
        sudo_gl.projects.get.assert_called_once_with(10)
        create_call = sudo_gl.projects.get.return_value.mergerequests.create
        create_call.assert_called_once()
        call_data = create_call.call_args[0][0]
        self.assertEqual(call_data["labels"], ["Codify"])

    def test_create_mr_uses_bot_when_no_sudo_gl(self):
        """MR should use bot GL when sudo_gl is None."""
        worker = self._make_worker()
        task = self._make_task()
        issue = self._make_issue()

        mock_mr = MagicMock()
        mock_mr.iid = 7
        mock_mr.web_url = "http://gitlab.test/mr/7"
        worker.gitlab.gl.projects.get.return_value.mergerequests.create.return_value = mock_mr

        mr_iid, mr_url = worker._create_new_mr(task, issue, sudo_gl=None)

        self.assertEqual(mr_iid, 7)
        worker.gitlab.gl.projects.get.assert_called_once_with(10)

    def test_create_mr_falls_back_on_sudo_failure(self):
        """When sudo MR creation fails, should retry with bot token."""
        worker = self._make_worker()
        task = self._make_task()
        issue = self._make_issue()

        sudo_gl = MagicMock()
        sudo_gl.projects.get.return_value.mergerequests.create.side_effect = Exception("403 Forbidden")

        mock_mr = MagicMock()
        mock_mr.iid = 99
        mock_mr.web_url = "http://gitlab.test/mr/99"
        worker.gitlab.gl.projects.get.return_value.mergerequests.create.return_value = mock_mr

        mr_iid, mr_url = worker._create_new_mr(task, issue, sudo_gl=sudo_gl)

        self.assertEqual(mr_iid, 99)
        worker.gitlab.gl.projects.get.assert_called_once()

    def test_create_mr_includes_codify_label(self):
        """MR creation data should include Codify label."""
        worker = self._make_worker()
        task = self._make_task()
        issue = self._make_issue()

        mock_mr = MagicMock()
        mock_mr.iid = 1
        mock_mr.web_url = "http://gitlab.test/mr/1"
        worker.gitlab.gl.projects.get.return_value.mergerequests.create.return_value = mock_mr

        worker._create_new_mr(task, issue)

        call_data = worker.gitlab.gl.projects.get.return_value.mergerequests.create.call_args[0][0]
        self.assertIn("labels", call_data)
        self.assertEqual(call_data["labels"], ["Codify"])

    def test_create_mr_returns_none_when_both_fail(self):
        """Should return (None, None) when both sudo and bot fail."""
        worker = self._make_worker()
        task = self._make_task()
        issue = self._make_issue()

        sudo_gl = MagicMock()
        sudo_gl.projects.get.return_value.mergerequests.create.side_effect = Exception("sudo fail")
        worker.gitlab.gl.projects.get.return_value.mergerequests.create.side_effect = Exception("bot fail")

        mr_iid, mr_url = worker._create_new_mr(task, issue, sudo_gl=sudo_gl)

        self.assertIsNone(mr_iid)
        self.assertIsNone(mr_url)


class TestWorkerSudoDraftRemoval(unittest.TestCase):
    """Tests for sudo GL usage in _remove_mr_draft_status_for_issue."""

    def _make_worker(self):
        with patch('app.core.worker.get_docker_client'), \
             patch('app.core.worker.get_gitlab_client') as mock_get_gl:
            mock_gl_client = MagicMock()
            mock_gl_client.settings = MagicMock()
            mock_gl_client.gl = MagicMock()
            mock_get_gl.return_value = mock_gl_client
            from app.core.worker import WorkerExecutor
            worker = WorkerExecutor()
        return worker

    def test_draft_removal_uses_sudo_gl(self):
        """Should use sudo GL to get MR, mark it ready, and save."""
        worker = self._make_worker()
        task = MagicMock()
        task.id = 1
        task.project_id = 10
        issue = MagicMock()
        issue.merge_request_iid = 5

        sudo_gl = MagicMock()
        mock_mr = MagicMock()
        mock_mr.title = "Draft: My Feature"
        sudo_gl.projects.get.return_value.mergerequests.get.return_value = mock_mr

        worker._remove_mr_draft_status_for_issue(task, issue, sudo_gl=sudo_gl)

        sudo_gl.projects.get.assert_called_once_with(10)
        self.assertFalse(mock_mr.draft)
        self.assertEqual(mock_mr.title, "My Feature")
        mock_mr.save.assert_called_once()

    def test_draft_removal_uses_bot_when_no_sudo(self):
        """Should use bot GL when sudo_gl is None."""
        worker = self._make_worker()
        task = MagicMock()
        task.id = 1
        task.project_id = 10
        issue = MagicMock()
        issue.merge_request_iid = 5

        mock_mr = MagicMock()
        mock_mr.title = "Draft: My Feature"
        worker.gitlab.gl.projects.get.return_value.mergerequests.get.return_value = mock_mr

        worker._remove_mr_draft_status_for_issue(task, issue)

        worker.gitlab.gl.projects.get.assert_called_once_with(10)
        mock_mr.save.assert_called_once()

    def test_draft_removal_marks_ready_without_title_prefix(self):
        """Should still mark ready when MR title has no draft prefix."""
        worker = self._make_worker()
        task = MagicMock()
        task.id = 1
        task.project_id = 10
        issue = MagicMock()
        issue.merge_request_iid = 5

        mock_mr = MagicMock()
        mock_mr.title = "My Feature"
        worker.gitlab.gl.projects.get.return_value.mergerequests.get.return_value = mock_mr

        worker._remove_mr_draft_status_for_issue(task, issue)

        self.assertFalse(mock_mr.draft)
        mock_mr.save.assert_called_once()
