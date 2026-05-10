import unittest
from unittest.mock import MagicMock, patch
from gitlab.exceptions import GitlabGetError


class DeleteBranchTests(unittest.TestCase):
    def _get_client(self):
        from app.core.gitlab_client import GitLabClient
        client = GitLabClient.__new__(GitLabClient)
        client.gl = MagicMock()
        client._url = "https://gitlab.example.com"
        return client

    def test_delete_branch_success(self):
        """Returns True when branch exists and is deleted."""
        client = self._get_client()
        mock_project = MagicMock()
        mock_branch = MagicMock()
        mock_project.branches.get.return_value = mock_branch
        with patch.object(client, "get_project", return_value=mock_project):
            result = client.delete_branch(42, "codify/issue-1")
        self.assertTrue(result)
        mock_branch.delete.assert_called_once()

    def test_delete_branch_not_found_returns_true(self):
        """Returns True (treat as already deleted) when branch not found (404)."""
        client = self._get_client()
        mock_project = MagicMock()
        err = GitlabGetError("Not Found", 404)
        mock_project.branches.get.side_effect = err
        with patch.object(client, "get_project", return_value=mock_project):
            result = client.delete_branch(42, "codify/issue-1")
        self.assertTrue(result)

    def test_delete_branch_other_error_returns_false(self):
        """Returns False when GitLab returns a non-404 error."""
        client = self._get_client()
        mock_project = MagicMock()
        err = GitlabGetError("Internal Server Error", 500)
        mock_project.branches.get.side_effect = err
        with patch.object(client, "get_project", return_value=mock_project):
            result = client.delete_branch(42, "codify/issue-1")
        self.assertFalse(result)

    def test_delete_branch_unexpected_exception_returns_false(self):
        """Returns False on unexpected exceptions."""
        client = self._get_client()
        mock_project = MagicMock()
        mock_project.branches.get.side_effect = RuntimeError("timeout")
        with patch.object(client, "get_project", return_value=mock_project):
            result = client.delete_branch(42, "codify/issue-1")
        self.assertFalse(result)
