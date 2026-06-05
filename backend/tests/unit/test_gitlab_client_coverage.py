#!/usr/bin/env python3
"""
Additional GitLab client unit tests targeting uncovered lines.

Covers functionality NOT tested by test_gitlab_client_access.py:
- __init__                      (lines 30-45)
- _normalize_hook_url           (lines 47-49)
- get_project                   (lines 51-61)
- get_or_create_branch          (lines 63-93)
- create_merge_request          (lines 95-135)
- normalize_web_url             (lines 137-154)
- get_merge_request             (lines 156-175)
- get_mr_by_iid                 (lines 177-198)
- get_merge_request_stats       (lines 200-244)
- create_note                   (lines 246-267)
- create_mr_note                (lines 269-290)
- update_note                   (lines 292-313)
- get_file_content              (lines 315-334)
- get_issue                     (lines 336-355)
- get_projects                  (lines 357-376)
- get_branches                  (lines 378-394)
- get_project_hooks             (lines 396-399)
- ensure_project_webhook        (lines 401-451)
- close                         (lines 453-456)
- Module functions: reset_gitlab_client, get_gitlab_client,
  get_cached_projects, invalidate_project_list_cache
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from gitlab.exceptions import GitlabGetError

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_settings(**overrides):
    """Create a mock Settings object."""
    s = MagicMock()
    s.gitlab_url = "http://gitlab.example.com/"
    s.gitlab_bot_token = "glpat-test-bot-token"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _make_client(settings=None, private_token=None):
    """Create a GitLabClient with mock Gitlab backend."""
    with patch('app.core.gitlab_client.gitlab.Gitlab') as MockGitlab, \
         patch('app.core.gitlab_client.get_ssl_verify', return_value=True):
        from app.core.gitlab_client import GitLabClient
        settings = settings or _make_settings()
        client = GitLabClient(settings=settings, private_token=private_token)
        client.gl = MockGitlab.return_value
    return client


# ===================================================================
# __init__
# ===================================================================

class TestGitLabClientInit(unittest.TestCase):
    """Tests for GitLabClient.__init__ — lines 30-45."""

    def test_init_with_settings(self):
        """Client initializes with provided settings — line 37-38."""
        settings = _make_settings(gitlab_url="http://my-gitlab.test/")
        client = _make_client(settings=settings)

        self.assertEqual(client.base_url, "http://my-gitlab.test")
        self.assertEqual(client.private_token, "glpat-test-bot-token")

    def test_init_strips_trailing_slash(self):
        """base_url should have trailing slash stripped — line 38."""
        settings = _make_settings(gitlab_url="http://gitlab.example.com///")
        client = _make_client(settings=settings)

        self.assertFalse(client.base_url.endswith("/"))

    def test_init_with_custom_private_token(self):
        """Custom private_token overrides settings — line 39."""
        settings = _make_settings()
        client = _make_client(settings=settings, private_token="custom-token-123")

        self.assertEqual(client.private_token, "custom-token-123")

    def test_init_uses_default_settings_when_none(self):
        """When settings is None, get_effective_settings is called — line 37."""
        with patch('app.core.gitlab_client.get_effective_settings') as mock_get, \
             patch('app.core.gitlab_client.gitlab.Gitlab'), \
             patch('app.core.gitlab_client.get_ssl_verify', return_value=True):
            mock_get.return_value = _make_settings()
            from app.core.gitlab_client import GitLabClient
            GitLabClient(settings=None)
            mock_get.assert_called_once()


# ===================================================================
# _normalize_hook_url
# ===================================================================

class TestNormalizeHookUrl(unittest.TestCase):
    """Tests for _normalize_hook_url — lines 47-49."""

    def test_strips_whitespace_and_trailing_slash(self):
        """URL is stripped and trailing slash removed."""
        from app.core.gitlab_client import GitLabClient
        self.assertEqual(
            GitLabClient._normalize_hook_url("  http://example.com/hook/  "),
            "http://example.com/hook",
        )

    def test_no_trailing_slash(self):
        """URL without trailing slash is unchanged."""
        from app.core.gitlab_client import GitLabClient
        self.assertEqual(
            GitLabClient._normalize_hook_url("http://example.com/hook"),
            "http://example.com/hook",
        )


# ===================================================================
# get_project
# ===================================================================

class TestGetProject(unittest.TestCase):
    """Tests for get_project — lines 51-61."""

    def test_get_project_success(self):
        """Returns project object — line 61."""
        client = _make_client()
        mock_project = MagicMock()
        client.gl.projects.get.return_value = mock_project

        result = client.get_project(42)

        client.gl.projects.get.assert_called_once_with(42)
        self.assertEqual(result, mock_project)

    def test_get_project_raises_on_not_found(self):
        """Propagates exception when project not found."""
        client = _make_client()
        client.gl.projects.get.side_effect = GitlabGetError("404 Not Found")

        with self.assertRaises(GitlabGetError):
            client.get_project(999)


# ===================================================================
# get_or_create_branch
# ===================================================================

class TestGetOrCreateBranch(unittest.TestCase):
    """Tests for get_or_create_branch — lines 63-93."""

    def test_returns_existing_branch(self):
        """Returns existing branch when it exists — lines 82-85."""
        client = _make_client()

        fake_branch = object.__new__(type('FakeBranch', (), {}))
        fake_branch.__dict__["_attrs"] = {"name": "feature-1", "commit": {}}

        mock_project = MagicMock()
        mock_project.branches.get.return_value = fake_branch
        client.gl.projects.get.return_value = mock_project

        result = client.get_or_create_branch(42, "feature-1")

        mock_project.branches.get.assert_called_once_with("feature-1")
        self.assertEqual(result["name"], "feature-1")

    def test_creates_branch_when_not_exists(self):
        """Creates branch when GitlabGetError is raised — lines 86-93."""
        client = _make_client()

        fake_branch = object.__new__(type('FakeBranch', (), {}))
        fake_branch.__dict__["_attrs"] = {"name": "new-branch", "commit": {}}

        mock_project = MagicMock()
        mock_project.branches.get.side_effect = GitlabGetError("404 Not Found")
        mock_project.branches.create.return_value = fake_branch
        client.gl.projects.get.return_value = mock_project

        result = client.get_or_create_branch(42, "new-branch", ref="develop")

        mock_project.branches.create.assert_called_once_with({
            "name": "new-branch",
            "ref": "develop",
        })
        self.assertEqual(result["name"], "new-branch")

    def test_default_ref_is_main(self):
        """Default ref for new branch is 'main' — line 64."""
        client = _make_client()

        fake_branch = object.__new__(type('FakeBranch', (), {}))
        fake_branch.__dict__["_attrs"] = {"name": "test-branch"}

        mock_project = MagicMock()
        mock_project.branches.get.side_effect = GitlabGetError("Not found")
        mock_project.branches.create.return_value = fake_branch
        client.gl.projects.get.return_value = mock_project

        client.get_or_create_branch(42, "test-branch")

        create_args = mock_project.branches.create.call_args[0][0]
        self.assertEqual(create_args["ref"], "main")


# ===================================================================
# create_merge_request
# ===================================================================

class TestCreateMergeRequest(unittest.TestCase):
    """Tests for create_merge_request — lines 95-135."""

    def test_creates_mr_without_issue(self):
        """Creates MR without issue reference — lines 117-132."""
        client = _make_client()
        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.web_url = "http://gitlab.example.com/project/-/merge_requests/1"
        mock_project.mergerequests.create.return_value = mock_mr
        client.gl.projects.get.return_value = mock_project

        result = client.create_merge_request(
            project_id=42,
            source_branch="feature",
            target_branch="main",
            title="Add feature",
            description="Description here",
        )

        self.assertEqual(result, mock_mr)
        call_args = mock_project.mergerequests.create.call_args[0][0]
        self.assertEqual(call_args["source_branch"], "feature")
        self.assertEqual(call_args["target_branch"], "main")
        self.assertTrue(call_args["remove_source_branch"])
        self.assertNotIn("Closes", call_args["description"])

    def test_creates_mr_with_issue_reference(self):
        """Creates MR with issue closing reference — lines 127-129."""
        client = _make_client()
        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.web_url = "http://gitlab.example.com/project/-/merge_requests/2"
        mock_project.mergerequests.create.return_value = mock_mr
        client.gl.projects.get.return_value = mock_project

        client.create_merge_request(
            project_id=42,
            source_branch="fix",
            target_branch="main",
            title="Fix bug",
            description="Bug fix",
            issue_iid=55,
        )

        call_args = mock_project.mergerequests.create.call_args[0][0]
        self.assertIn("Closes #55", call_args["description"])


# ===================================================================
# normalize_web_url
# ===================================================================

class TestNormalizeWebUrl(unittest.TestCase):
    """Tests for normalize_web_url — lines 137-154."""

    def test_normalizes_url(self):
        """Replaces host with configured base URL — lines 142-154."""
        client = _make_client(settings=_make_settings(gitlab_url="https://gitlab.corp.com/"))

        result = client.normalize_web_url("http://internal:8080/project/-/merge_requests/1")

        self.assertTrue(result.startswith("https://gitlab.corp.com"))
        self.assertIn("/project/-/merge_requests/1", result)

    def test_returns_none_for_none(self):
        """Returns None for None input — line 139."""
        client = _make_client()
        self.assertIsNone(client.normalize_web_url(None))

    def test_returns_empty_for_empty(self):
        """Returns empty string for empty input — line 140."""
        client = _make_client()
        self.assertEqual(client.normalize_web_url(""), "")

    def test_returns_original_when_no_scheme(self):
        """Returns original URL if configured base has no scheme — line 145."""
        # Create client with a base_url that would make urlsplit have no scheme
        client = _make_client()
        # Force a weird base_url
        client.base_url = "no-scheme-url"

        result = client.normalize_web_url("http://gitlab.example.com/project/-/merge_requests/1")

        # Should return original since configured has no scheme
        self.assertEqual(result, "http://gitlab.example.com/project/-/merge_requests/1")


# ===================================================================
# get_merge_request
# ===================================================================

class TestGetMergeRequest(unittest.TestCase):
    """Tests for get_merge_request — lines 156-175."""

    def test_returns_mr_on_success(self):
        """Returns MR object — lines 170-172."""
        client = _make_client()
        mock_mr = MagicMock()
        mock_project = MagicMock()
        mock_project.mergerequests.get.return_value = mock_mr
        client.gl.projects.get.return_value = mock_project

        result = client.get_merge_request(42, 5)

        self.assertEqual(result, mock_mr)

    def test_returns_none_on_not_found(self):
        """Returns None when MR not found — lines 173-175."""
        client = _make_client()
        mock_project = MagicMock()
        mock_project.mergerequests.get.side_effect = GitlabGetError("404 Not Found")
        client.gl.projects.get.return_value = mock_project

        result = client.get_merge_request(42, 999)

        self.assertIsNone(result)


# ===================================================================
# get_mr_by_iid
# ===================================================================

class TestGetMrByIid(unittest.TestCase):
    """Tests for get_mr_by_iid — lines 177-198."""

    def test_returns_dict_on_success(self):
        """Returns dict with MR details — lines 191-198."""
        client = _make_client()
        mock_mr = MagicMock()
        mock_mr.source_branch = "feature"
        mock_mr.target_branch = "main"
        mock_mr.title = "Add feature"
        mock_mr.state = "merged"
        mock_project = MagicMock()
        mock_project.mergerequests.get.return_value = mock_mr
        client.gl.projects.get.return_value = mock_project

        result = client.get_mr_by_iid(42, 5)

        self.assertIsNotNone(result)
        self.assertEqual(result["source_branch"], "feature")
        self.assertEqual(result["target_branch"], "main")
        self.assertEqual(result["title"], "Add feature")
        self.assertEqual(result["state"], "merged")

    def test_returns_none_when_mr_not_found(self):
        """Returns None when MR doesn't exist — lines 188-189."""
        client = _make_client()
        mock_project = MagicMock()
        mock_project.mergerequests.get.side_effect = GitlabGetError("Not found")
        client.gl.projects.get.return_value = mock_project

        result = client.get_mr_by_iid(42, 999)

        self.assertIsNone(result)


# ===================================================================
# get_merge_request_stats
# ===================================================================

class TestGetMergeRequestStats(unittest.TestCase):
    """Tests for get_merge_request_stats — lines 200-244."""

    @patch('app.core.gitlab_client.get_ssl_verify', return_value=True)
    def test_counts_additions_and_deletions_from_diff(self, mock_ssl):
        """Parses diff content to count additions/deletions — lines 224-237."""
        client = _make_client()

        # Mock HTTP response with changes
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "changes": [
                {
                    "diff": (
                        "@@ -1,3 +1,5 @@\n"
                        "+added line 1\n"
                        "+added line 2\n"
                        "-removed line 1\n"
                        " unchanged\n"
                        "--- a/old\n"
                        "+++ b/new\n"
                    )
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('app.core.gitlab_client.httpx.AsyncClient', return_value=mock_client):
            result = asyncio.run(client.get_merge_request_stats(42, 5))

        self.assertIsNotNone(result)
        self.assertEqual(result["additions"], 2)   # +added line 1, +added line 2
        self.assertEqual(result["deletions"], 1)   # -removed line 1
        self.assertEqual(result["total"], 3)

    @patch('app.core.gitlab_client.get_ssl_verify', return_value=True)
    def test_returns_none_on_api_error(self, mock_ssl):
        """Returns None when API call fails — lines 242-244."""
        client = _make_client()

        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Network error")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('app.core.gitlab_client.httpx.AsyncClient', return_value=mock_client):
            result = asyncio.run(client.get_merge_request_stats(42, 5))

        self.assertIsNone(result)

    @patch('app.core.gitlab_client.get_ssl_verify', return_value=True)
    def test_empty_changes_returns_zeros(self, mock_ssl):
        """Empty changes list returns zeros — lines 226-227."""
        client = _make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"changes": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('app.core.gitlab_client.httpx.AsyncClient', return_value=mock_client):
            result = asyncio.run(client.get_merge_request_stats(42, 5))

        self.assertIsNotNone(result)
        self.assertEqual(result["additions"], 0)
        self.assertEqual(result["deletions"], 0)
        self.assertEqual(result["total"], 0)


# ===================================================================
# create_note
# ===================================================================

class TestCreateNote(unittest.TestCase):
    """Tests for create_note — lines 246-267."""

    def test_creates_issue_note(self):
        """Creates note on issue — lines 259-267."""
        client = _make_client()

        fake_note = object.__new__(type('FakeNote', (), {}))
        fake_note.__dict__["_attrs"] = {"id": 1, "body": "Hello"}

        mock_issue = MagicMock()
        mock_issue.notes.create.return_value = fake_note
        mock_project = MagicMock()
        mock_project.issues.get.return_value = mock_issue
        client.gl.projects.get.return_value = mock_project

        result = client.create_note(42, 10, "Hello world")

        mock_issue.notes.create.assert_called_once_with({"body": "Hello world"})
        self.assertEqual(result["body"], "Hello")


# ===================================================================
# create_mr_note
# ===================================================================

class TestCreateMrNote(unittest.TestCase):
    """Tests for create_mr_note — lines 269-290."""

    def test_creates_mr_note(self):
        """Creates note on merge request — lines 282-290."""
        client = _make_client()

        fake_note = object.__new__(type('FakeNote', (), {}))
        fake_note.__dict__["_attrs"] = {"id": 2, "body": "Review comment"}

        mock_mr = MagicMock()
        mock_mr.notes.create.return_value = fake_note
        mock_project = MagicMock()
        mock_project.mergerequests.get.return_value = mock_mr
        client.gl.projects.get.return_value = mock_project

        result = client.create_mr_note(42, 5, "Looks good!")

        mock_mr.notes.create.assert_called_once_with({"body": "Looks good!"})
        self.assertEqual(result["body"], "Review comment")


# ===================================================================
# update_note
# ===================================================================

class TestUpdateNote(unittest.TestCase):
    """Tests for update_note — lines 292-313."""

    def test_updates_issue_note(self):
        """Updates existing note on issue — lines 306-313."""
        client = _make_client()

        # Use a real object with _attrs in __dict__ (as python-gitlab does)
        fake_note = type('FakeNote', (), {'save': lambda self: None})()
        fake_note.__dict__["_attrs"] = {"id": 5, "body": "Updated text"}
        fake_note.body = "old text"

        mock_issue = MagicMock()
        mock_issue.notes.get.return_value = fake_note
        mock_project = MagicMock()
        mock_project.issues.get.return_value = mock_issue
        client.gl.projects.get.return_value = mock_project

        result = client.update_note(42, 10, 5, "New body text")

        self.assertEqual(fake_note.body, "New body text")
        self.assertEqual(result["body"], "Updated text")


# ===================================================================
# get_file_content
# ===================================================================

class TestGetFileContent(unittest.TestCase):
    """Tests for get_file_content — lines 315-334."""

    def test_returns_file_content(self):
        """Returns decoded file content — lines 328-331."""
        client = _make_client()
        mock_project = MagicMock()
        mock_project.files.raw.return_value = b"print('hello world')"
        client.gl.projects.get.return_value = mock_project

        result = client.get_file_content(42, "main.py", ref="main")

        self.assertEqual(result, "print('hello world')")
        mock_project.files.raw.assert_called_once_with("main.py", ref="main")

    def test_returns_empty_when_not_found(self):
        """Returns empty string when file not found — lines 332-334."""
        client = _make_client()
        mock_project = MagicMock()
        mock_project.files.raw.side_effect = GitlabGetError("404 Not Found")
        client.gl.projects.get.return_value = mock_project

        result = client.get_file_content(42, "missing.py")

        self.assertEqual(result, "")


# ===================================================================
# get_issue
# ===================================================================

class TestGetIssue(unittest.TestCase):
    """Tests for get_issue — lines 336-355."""

    def test_returns_issue_dict(self):
        """Returns dict with title and description — lines 348-352."""
        client = _make_client()
        mock_issue = MagicMock()
        mock_issue.title = "Bug: Login broken"
        mock_issue.description = "When I try to login..."
        mock_project = MagicMock()
        mock_project.issues.get.return_value = mock_issue
        client.gl.projects.get.return_value = mock_project

        result = client.get_issue(42, 10)

        self.assertEqual(result["title"], "Bug: Login broken")
        self.assertEqual(result["description"], "When I try to login...")

    def test_returns_none_when_not_found(self):
        """Returns None when issue not found — lines 353-355."""
        client = _make_client()
        mock_project = MagicMock()
        mock_project.issues.get.side_effect = GitlabGetError("404 Not Found")
        client.gl.projects.get.return_value = mock_project

        result = client.get_issue(42, 999)

        self.assertIsNone(result)


# ===================================================================
# get_projects
# ===================================================================

class TestGetProjects(unittest.TestCase):
    """Tests for get_projects — lines 357-376."""

    def test_returns_project_list(self):
        """Returns list of project dicts — lines 367-376."""
        client = _make_client()
        mock_p1 = MagicMock()
        mock_p1.id = 1
        mock_p1.name = "project-a"
        mock_p1.path_with_namespace = "group/project-a"
        mock_p1.default_branch = "main"
        mock_p1.marked_for_deletion_at = None

        mock_p2 = MagicMock()
        mock_p2.id = 2
        mock_p2.name = "project-b"
        mock_p2.path_with_namespace = "group/project-b"
        mock_p2.default_branch = None
        mock_p2.marked_for_deletion_at = None

        client.gl.projects.list.return_value = [mock_p1, mock_p2]

        result = client.get_projects()

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], 1)
        self.assertEqual(result[0]["name"], "project-a")
        self.assertEqual(result[0]["default_branch"], "main")
        self.assertIsNone(result[1]["default_branch"])

    def test_filters_deletion_pending_projects(self):
        """Projects with marked_for_deletion_at are excluded from results."""
        client = _make_client()
        mock_active = MagicMock()
        mock_active.id = 1
        mock_active.name = "active"
        mock_active.path_with_namespace = "group/active"
        mock_active.default_branch = "main"
        mock_active.marked_for_deletion_at = None

        mock_pending = MagicMock()
        mock_pending.id = 2
        mock_pending.name = "deleted"
        mock_pending.path_with_namespace = "group/deleted-deletion_scheduled-1"
        mock_pending.default_branch = "main"
        mock_pending.marked_for_deletion_at = "2026-05-15T00:00:00.000Z"

        client.gl.projects.list.return_value = [mock_active, mock_pending]

        result = client.get_projects()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 1)

    def test_custom_per_page(self):
        """Passes per_page to all three queries — membership, internal, public."""
        client = _make_client()
        client.gl.projects.list.return_value = []

        client.get_projects(per_page=50)

        self.assertEqual(client.gl.projects.list.call_count, 3)
        calls = client.gl.projects.list.call_args_list
        self.assertIn({"per_page": 50, "all": True, "membership": True}, [c.kwargs for c in calls])
        self.assertIn({"per_page": 50, "all": True, "visibility": "internal"}, [c.kwargs for c in calls])
        self.assertIn({"per_page": 50, "all": True, "visibility": "public"}, [c.kwargs for c in calls])


# ===================================================================
# get_branches
# ===================================================================

class TestGetBranches(unittest.TestCase):
    """Tests for get_branches — lines 378-394."""

    def test_returns_branch_list(self):
        """Returns list of branch dicts with name — lines 387-394."""
        client = _make_client()
        client.gl.http_list.return_value = [
            {"name": "main", "commit": {}},
            {"name": "develop", "commit": {}},
        ]

        result = client.get_branches(42)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "main")
        self.assertEqual(result[1]["name"], "develop")
        client.gl.http_list.assert_called_once_with(
            "/projects/42/repository/branches",
            per_page=100,
            get_all=True,
        )


# ===================================================================
# get_project_hooks
# ===================================================================

class TestGetProjectHooks(unittest.TestCase):
    """Tests for get_project_hooks — lines 396-399."""

    def test_returns_hooks_list(self):
        """Returns list of hook dicts — line 399."""
        client = _make_client()
        client.gl.http_list.return_value = [
            {"id": 1, "url": "http://example.com/hook1"},
            {"id": 2, "url": "http://example.com/hook2"},
        ]

        result = client.get_project_hooks(42)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["url"], "http://example.com/hook1")


# ===================================================================
# ensure_project_webhook
# ===================================================================

class TestEnsureProjectWebhook(unittest.TestCase):
    """Tests for ensure_project_webhook — lines 401-451."""

    def test_creates_new_webhook(self):
        """Creates webhook when none exists — lines 443-451."""
        client = _make_client()
        client.gl.http_list.return_value = []  # no existing hooks
        mock_created = {"id": 99, "url": "http://codify.example.com/webhook"}
        client.gl.http_post.return_value = mock_created

        result = client.ensure_project_webhook(
            42, "http://codify.example.com/webhook", "secret123"
        )

        self.assertEqual(result["action"], "created")
        self.assertEqual(result["hook"], mock_created)
        client.gl.http_post.assert_called_once()

    def test_updates_existing_webhook(self):
        """Updates webhook when matching URL exists — lines 431-441."""
        client = _make_client()
        client.gl.http_list.return_value = [
            {"id": 55, "url": "http://codify.example.com/webhook"},
        ]
        mock_updated = {"id": 55, "url": "http://codify.example.com/webhook"}
        client.gl.http_put.return_value = mock_updated

        result = client.ensure_project_webhook(
            42, "http://codify.example.com/webhook", "new-secret"
        )

        self.assertEqual(result["action"], "updated")
        self.assertEqual(result["hook"], mock_updated)
        client.gl.http_put.assert_called_once()

    def test_normalizes_urls_for_matching(self):
        """Trailing slashes are normalized for URL comparison — line 426."""
        client = _make_client()
        # Existing hook has trailing slash
        client.gl.http_list.return_value = [
            {"id": 55, "url": "http://codify.example.com/webhook/"},
        ]
        mock_updated = {"id": 55, "url": "http://codify.example.com/webhook"}
        client.gl.http_put.return_value = mock_updated

        result = client.ensure_project_webhook(
            42, "http://codify.example.com/webhook", "secret"
        )

        # Should match and update (not create)
        self.assertEqual(result["action"], "updated")


# ===================================================================
# close
# ===================================================================

class TestClose(unittest.TestCase):
    """Tests for close — lines 453-456."""

    def test_close_succeeds(self):
        """Close doesn't raise — line 455."""
        client = _make_client()
        client.close()  # Should not raise


# ===================================================================
# Module-level: reset_gitlab_client
# ===================================================================

class TestResetGitlabClient(unittest.TestCase):
    """Tests for reset_gitlab_client — lines 472-478."""

    def test_reset_clears_singleton(self):
        """Resets cached client and config — lines 474-478."""
        import app.core.gitlab_client as mod

        # Set up a mock client
        mock_client = MagicMock()
        mod._gitlab_client = mock_client
        mod._gitlab_client_config = ("http://old.example.com", "old-token")

        mod.reset_gitlab_client()

        self.assertIsNone(mod._gitlab_client)
        self.assertIsNone(mod._gitlab_client_config)
        mock_client.close.assert_called_once()

    def test_reset_when_no_client(self):
        """Reset is safe when no client exists — line 475."""
        import app.core.gitlab_client as mod

        mod._gitlab_client = None
        mod._gitlab_client_config = None

        mod.reset_gitlab_client()  # Should not raise

        self.assertIsNone(mod._gitlab_client)


# ===================================================================
# Module-level: get_gitlab_client
# ===================================================================

class TestGetGitlabClient(unittest.TestCase):
    """Tests for get_gitlab_client — lines 481-491."""

    def setUp(self):
        """Clean up module state before each test."""
        import app.core.gitlab_client as mod
        mod._gitlab_client = None
        mod._gitlab_client_config = None

    def tearDown(self):
        """Clean up module state after each test."""
        import app.core.gitlab_client as mod
        mod._gitlab_client = None
        mod._gitlab_client_config = None

    @patch('app.core.gitlab_client.get_effective_settings')
    @patch('app.core.gitlab_client.GitLabClient')
    def test_creates_new_client(self, MockClient, mock_get_settings):
        """Creates new client on first call — lines 486-490."""
        import app.core.gitlab_client as mod
        settings = _make_settings()
        mock_get_settings.return_value = settings

        mod.get_gitlab_client()

        MockClient.assert_called_once_with(settings=settings)

    @patch('app.core.gitlab_client.get_effective_settings')
    @patch('app.core.gitlab_client.GitLabClient')
    def test_reuses_existing_client(self, MockClient, mock_get_settings):
        """Returns cached client when config unchanged — line 486."""
        import app.core.gitlab_client as mod
        settings = _make_settings()
        mock_get_settings.return_value = settings

        client1 = mod.get_gitlab_client()
        client2 = mod.get_gitlab_client()

        # Should only create once
        MockClient.assert_called_once()
        self.assertEqual(client1, client2)

    @patch('app.core.gitlab_client.get_effective_settings')
    @patch('app.core.gitlab_client.GitLabClient')
    def test_recreates_client_on_config_change(self, MockClient, mock_get_settings):
        """Recreates client when config changes — lines 487-490."""
        import app.core.gitlab_client as mod

        settings1 = _make_settings(gitlab_url="http://old.example.com/", gitlab_bot_token="token-1")
        settings2 = _make_settings(gitlab_url="http://new.example.com/", gitlab_bot_token="token-2")

        mock_get_settings.return_value = settings1
        mod.get_gitlab_client()

        mock_get_settings.return_value = settings2
        mod.get_gitlab_client()

        # Should have created two different clients
        self.assertEqual(MockClient.call_count, 2)


# ===================================================================
# Module-level: invalidate_project_list_cache
# ===================================================================

class TestInvalidateProjectListCache(unittest.TestCase):
    """Tests for invalidate_project_list_cache — lines 535-546."""

    def test_invalidates_cache(self):
        """Clears cache data and expiry — lines 541-546."""
        import app.core.gitlab_client as mod

        mod._project_list_cache = [{"id": 1}]
        mod._project_list_cache_expires_at = 999999.0
        mod._project_list_refresh_task = None

        mod.invalidate_project_list_cache()

        self.assertEqual(mod._project_list_cache, [])
        self.assertEqual(mod._project_list_cache_expires_at, 0.0)

    def test_cancels_running_refresh_task(self):
        """Cancels in-flight refresh task — lines 543-544."""
        import app.core.gitlab_client as mod

        mock_task = MagicMock()
        mock_task.done.return_value = False
        mod._project_list_refresh_task = mock_task
        mod._project_list_cache = [{"id": 1}]
        mod._project_list_cache_expires_at = 999.0

        mod.invalidate_project_list_cache()

        mock_task.cancel.assert_called_once()
        self.assertIsNone(mod._project_list_refresh_task)


# ===================================================================
# Module-level: get_cached_projects
# ===================================================================

class TestGetCachedProjects(unittest.TestCase):
    """Tests for get_cached_projects — lines 511-532."""

    def setUp(self):
        """Reset cache state."""
        import app.core.gitlab_client as mod
        mod._project_list_cache = []
        mod._project_list_cache_expires_at = 0.0
        mod._project_list_refresh_task = None

    def tearDown(self):
        """Reset cache state."""
        import app.core.gitlab_client as mod
        mod._project_list_cache = []
        mod._project_list_cache_expires_at = 0.0
        mod._project_list_refresh_task = None

    @patch('app.core.gitlab_client._refresh_project_list_cache')
    def test_cold_cache_fetches_data(self, mock_refresh):
        """Cold cache (empty) blocks on first fetch — line 532."""
        import app.core.gitlab_client as mod
        mock_refresh.return_value = [{"id": 1, "name": "proj"}]

        result = asyncio.run(mod.get_cached_projects())

        mock_refresh.assert_awaited_once()
        self.assertEqual(result, [{"id": 1, "name": "proj"}])

    def test_fresh_cache_returns_immediately(self):
        """Fresh cache returns without refresh — lines 521-523."""
        import time

        import app.core.gitlab_client as mod

        mod._project_list_cache = [{"id": 1}]
        mod._project_list_cache_expires_at = time.time() + 300  # far future

        with patch('app.core.gitlab_client._refresh_project_list_cache') as mock_refresh:
            result = asyncio.run(mod.get_cached_projects())

        mock_refresh.assert_not_called()
        self.assertEqual(result, [{"id": 1}])

    def test_stale_cache_returns_stale_and_triggers_refresh(self):
        """Stale cache returns old data and kicks off background refresh — lines 525-529."""
        import time

        import app.core.gitlab_client as mod

        mod._project_list_cache = [{"id": 99}]
        mod._project_list_cache_expires_at = time.time() - 10  # expired

        # We need to run in an event loop context to test asyncio.create_task
        async def run_test():
            with patch('app.core.gitlab_client._refresh_project_list_cache', new_callable=AsyncMock) as mock_refresh:
                mock_refresh.return_value = [{"id": 100}]
                result = await mod.get_cached_projects()
                # Should return stale data
                self.assertEqual(result, [{"id": 99}])
                # A refresh task should have been created (indirectly)

        asyncio.run(run_test())


# ===================================================================
# create_sudo_gl
# ===================================================================

class TestCreateSudoGl(unittest.TestCase):
    """Tests for GitLabClient.create_sudo_gl."""

    @patch('app.core.gitlab_client.get_ssl_verify', return_value=True)
    @patch('app.core.gitlab_client.gitlab.Gitlab')
    def test_creates_gitlab_instance_with_sudo(self, MockGitlab, mock_ssl):
        """Should create Gitlab instance with admin token and sudo user ID."""
        settings = _make_settings(gitlab_admin_token="glpat-admin-token")
        client = _make_client(settings=settings)

        mock_instance = MockGitlab.return_value
        mock_instance.headers = {}
        result = client.create_sudo_gl(42)

        MockGitlab.assert_called_with(
            "http://gitlab.example.com",
            private_token="glpat-admin-token",
            ssl_verify=True,
            keep_base_url=True,
            timeout=30,
        )
        self.assertEqual(mock_instance.headers["Sudo"], "42")
        self.assertEqual(result, mock_instance)

    def test_raises_when_no_admin_token(self):
        """Should raise ValueError when gitlab_admin_token is empty."""
        settings = _make_settings(gitlab_admin_token="")
        client = _make_client(settings=settings)

        with self.assertRaises(ValueError) as ctx:
            client.create_sudo_gl(42)
        self.assertIn("gitlab_admin_token", str(ctx.exception))

    def test_raises_when_admin_token_whitespace(self):
        """Should raise ValueError when gitlab_admin_token is whitespace."""
        settings = _make_settings(gitlab_admin_token="   ")
        client = _make_client(settings=settings)

        with self.assertRaises(ValueError) as ctx:
            client.create_sudo_gl(42)
        self.assertIn("gitlab_admin_token", str(ctx.exception))


# ===================================================================
# ensure_project_label
# ===================================================================

class TestEnsureProjectLabel(unittest.TestCase):
    """Tests for GitLabClient.ensure_project_label."""

    def test_label_already_exists(self):
        """Should not create label if it already exists."""
        client = _make_client()
        mock_project = MagicMock()
        client.gl.projects.get.return_value = mock_project
        mock_project.labels.get.return_value = MagicMock()  # exists

        client.ensure_project_label(1, "Codify", "#6699cc")

        mock_project.labels.get.assert_called_once_with("Codify")
        mock_project.labels.create.assert_not_called()

    def test_label_not_exists_creates_it(self):
        """Should create label when it doesn't exist."""
        client = _make_client()
        mock_project = MagicMock()
        client.gl.projects.get.return_value = mock_project
        mock_project.labels.get.side_effect = GitlabGetError("404")

        client.ensure_project_label(1, "Codify", "#6699cc")

        mock_project.labels.create.assert_called_once_with({
            "name": "Codify",
            "color": "#6699cc",
        })

    def test_label_create_failure_does_not_raise(self):
        """Should log warning but not raise if label creation fails."""
        client = _make_client()
        mock_project = MagicMock()
        client.gl.projects.get.return_value = mock_project
        mock_project.labels.get.side_effect = GitlabGetError("404")
        mock_project.labels.create.side_effect = Exception("forbidden")

        # Should not raise
        client.ensure_project_label(1, "Codify", "#6699cc")

    def test_label_race_condition_handles_conflict(self):
        """Should handle GitlabCreateError (race condition) gracefully."""
        from gitlab.exceptions import GitlabCreateError
        client = _make_client()
        mock_project = MagicMock()
        client.gl.projects.get.return_value = mock_project
        mock_project.labels.get.side_effect = GitlabGetError("404")
        mock_project.labels.create.side_effect = GitlabCreateError("409 Conflict")

        # Should not raise — another task created the label concurrently
        client.ensure_project_label(1, "Codify", "#6699cc")


if __name__ == "__main__":
    unittest.main()
