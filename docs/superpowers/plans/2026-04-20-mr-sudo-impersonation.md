# MR Sudo Impersonation + Codify Label — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create MRs as the task initiator (via admin sudo) and label them "Codify" for identification.

**Architecture:** Add `create_sudo_gl()` to GitLabClient for impersonation, `ensure_project_label()` for label management. Worker creates one sudo GL per task execution and passes it to MR create/update/draft-removal methods. Falls back to bot token when no `initiator_gitlab_user_id`.

**Tech Stack:** python-gitlab (sudo parameter), SQLAlchemy async, pytest

---

### Task 1: GitLabClient — add `create_sudo_gl()` method

**Files:**
- Modify: `backend/app/core/gitlab_client.py:27-45` (class body, after `__init__`)
- Test: `backend/tests/unit/test_gitlab_client_coverage.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_gitlab_client_coverage.py`:

```python
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

        result = client.create_sudo_gl(42)

        MockGitlab.assert_called_with(
            "http://gitlab.example.com",
            private_token="glpat-admin-token",
            sudo="42",
            ssl_verify=True,
            keep_base_url=True,
        )
        self.assertEqual(result, MockGitlab.return_value)

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_gitlab_client_coverage.py::TestCreateSudoGl -v`
Expected: FAIL with "AttributeError: 'GitLabClient' object has no attribute 'create_sudo_gl'"

- [ ] **Step 3: Implement `create_sudo_gl()`**

Add method to `GitLabClient` class in `backend/app/core/gitlab_client.py`, after `__init__` (after line 46):

```python
    def create_sudo_gl(self, gitlab_user_id: int) -> Gitlab:
        """Create a Gitlab instance with admin token + sudo for impersonation.

        Args:
            gitlab_user_id: The GitLab user ID to impersonate.

        Returns:
            A Gitlab instance configured with sudo.

        Raises:
            ValueError: If gitlab_admin_token is not configured.
        """
        admin_token = self.settings.gitlab_admin_token.strip() if self.settings.gitlab_admin_token else ""
        if not admin_token:
            raise ValueError("gitlab_admin_token is required for sudo operations")
        return gitlab.Gitlab(
            self.base_url,
            private_token=admin_token,
            sudo=str(gitlab_user_id),
            ssl_verify=get_ssl_verify(self.settings),
            keep_base_url=True,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/test_gitlab_client_coverage.py::TestCreateSudoGl -v`
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/gitlab_client.py backend/tests/unit/test_gitlab_client_coverage.py
git commit -m "feat: add create_sudo_gl() for MR impersonation"
```

---

### Task 2: GitLabClient — add `ensure_project_label()` method

**Files:**
- Modify: `backend/app/core/gitlab_client.py` (add method after `create_sudo_gl`)
- Test: `backend/tests/unit/test_gitlab_client_coverage.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_gitlab_client_coverage.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_gitlab_client_coverage.py::TestEnsureProjectLabel -v`
Expected: FAIL with "AttributeError: 'GitLabClient' object has no attribute 'ensure_project_label'"

- [ ] **Step 3: Implement `ensure_project_label()`**

Add method to `GitLabClient` class in `backend/app/core/gitlab_client.py`, after `create_sudo_gl`:

```python
    def ensure_project_label(self, project_id: int, label_name: str, color: str) -> None:
        """Ensure a label exists in the project, creating it if necessary.

        Uses the bot token (not sudo) to ensure label exists regardless of
        impersonated user's permissions.

        Args:
            project_id: GitLab project ID
            label_name: Label name (e.g., "Codify")
            color: Label color hex (e.g., "#6699cc")
        """
        project = self.get_project(project_id)
        try:
            project.labels.get(label_name)
        except GitlabGetError:
            try:
                project.labels.create({"name": label_name, "color": color})
                logger.info(f"Created label '{label_name}' in project {project_id}")
            except Exception as e:
                logger.warning(f"Failed to create label '{label_name}' in project {project_id}: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/test_gitlab_client_coverage.py::TestEnsureProjectLabel -v`
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/gitlab_client.py backend/tests/unit/test_gitlab_client_coverage.py
git commit -m "feat: add ensure_project_label() for auto-creating labels"
```

---

### Task 3: Worker — modify `_create_new_mr()` to accept sudo GL and add labels

**Files:**
- Modify: `backend/app/core/worker.py:449-475` (`_create_new_mr` method)
- Modify: `backend/app/core/worker.py:410-425` (`_create_mr_if_needed` signature)

- [ ] **Step 1: Modify `_create_new_mr()` to accept and use `sudo_gl`**

Replace the `_create_new_mr` method in `backend/app/core/worker.py`:

```python
    def _create_new_mr(
        self,
        task: Task,
        issue: Issue,
        *,
        sudo_gl: Optional["Gitlab"] = None,
    ) -> tuple[Optional[int], Optional[str]]:
        """Create a new draft MR for the task's issue."""
        settings = get_settings()
        target_branch = issue.target_branch or settings.default_target_branch
        mr_title = self._build_initial_mr_title(task)
        initial_mr_desc = self._build_initial_mr_description(task)

        try:
            gl = sudo_gl or self.gitlab.gl
            mr_response = gl.projects.get(task.project_id).mergerequests.create({
                "source_branch": issue.branch_name,
                "target_branch": target_branch,
                "title": mr_title,
                "description": initial_mr_desc,
                "draft": True,
                "labels": ["Codify"],
            })
        except Exception as e:
            if sudo_gl:
                logger.warning(
                    f"[Task {task.id}] Sudo MR creation failed: {e}, retrying with bot token"
                )
                try:
                    mr_response = self.gitlab.gl.projects.get(task.project_id).mergerequests.create({
                        "source_branch": issue.branch_name,
                        "target_branch": target_branch,
                        "title": mr_title,
                        "description": initial_mr_desc,
                        "draft": True,
                        "labels": ["Codify"],
                    })
                except Exception as e2:
                    logger.warning(f"[Task {task.id}] Bot token MR creation also failed: {e2}")
                    return None, None
            else:
                logger.warning(f"[Task {task.id}] Failed to create initial MR: {e}, continuing without MR")
                return None, None

        mr_iid = mr_response.iid
        mr_web_url = self.gitlab.normalize_web_url(mr_response.web_url)
        logger.info(f"[Task {task.id}] Created initial draft MR !{mr_iid}")
        return mr_iid, mr_web_url
```

- [ ] **Step 2: Update `_create_mr_if_needed()` to pass `sudo_gl` through**

Replace in `backend/app/core/worker.py`:

```python
    def _create_mr_if_needed(
        self,
        task: Task,
        issue: Issue,
        mr_iid: Optional[int],
        mr_web_url: Optional[str],
        *,
        sudo_gl: Optional["Gitlab"] = None,
    ) -> tuple[Optional[int], Optional[str]]:
        """Create or reuse MR for the task's issue."""
        if mr_iid:
            return mr_iid, mr_web_url

        existing = self._find_existing_mr(task, issue)
        if existing:
            return existing

        return self._create_new_mr(task, issue, sudo_gl=sudo_gl)
```

- [ ] **Step 3: Add `Gitlab` type import to worker.py**

Add to the imports in `backend/app/core/worker.py` (near the top, with existing imports):

```python
from gitlab import Gitlab
```

- [ ] **Step 4: Run existing tests to verify nothing is broken**

Run: `cd backend && python -m pytest tests/unit/ -v --timeout=60 -q`
Expected: All existing tests PASS (the `sudo_gl` parameter defaults to None, preserving behavior)

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/worker.py
git commit -m "feat: _create_new_mr supports sudo GL and Codify label"
```

---

### Task 4: Worker — modify `_remove_mr_draft_status_for_issue()` to accept sudo GL

**Files:**
- Modify: `backend/app/core/worker.py:159-176` (`_remove_mr_draft_status_for_issue` method)

- [ ] **Step 1: Update method to accept and use `sudo_gl`**

Replace the method in `backend/app/core/worker.py`:

```python
    def _remove_mr_draft_status_for_issue(
        self, task: Task, issue: Issue, *, sudo_gl: Optional["Gitlab"] = None
    ) -> None:
        """Remove draft status from an MR by normalizing its title."""
        gl = sudo_gl or self.gitlab.gl
        project = gl.projects.get(task.project_id)
        mr = project.mergerequests.get(issue.merge_request_iid)

        title = getattr(mr, "title", "")
        if not isinstance(title, str):
            logger.info(f"[Task {task.id}] Skipping draft removal because MR title is unavailable")
            return

        updated_title = re.sub(r"^(?:\[Draft\]\s*|Draft:\s*|WIP:\s*)", "", title, count=1, flags=re.IGNORECASE).strip()
        if not updated_title or updated_title == title:
            logger.info(f"[Task {task.id}] MR !{issue.merge_request_iid} is already non-draft")
            return

        mr.title = updated_title
        mr.save()
        logger.info(f"[Task {task.id}] Removed draft status from MR !{issue.merge_request_iid}")
```

- [ ] **Step 2: Run existing tests**

Run: `cd backend && python -m pytest tests/unit/ -q --timeout=60`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/core/worker.py
git commit -m "feat: _remove_mr_draft_status_for_issue supports sudo GL"
```

---

### Task 5: Worker — modify `_update_mr_description_for_issue()` to accept sudo GL

**Files:**
- Modify: `backend/app/core/worker.py:754-830` (`_update_mr_description_for_issue` method)

- [ ] **Step 1: Update method signature and MR retrieval**

Replace the method signature and the MR retrieval part (keep the description-building logic intact):

```python
    async def _update_mr_description_for_issue(
        self,
        task: Task,
        issue: Issue,
        db: AsyncSession,
        *,
        sudo_gl: Optional["Gitlab"] = None,
    ) -> None:
        """Rebuild MR description from issue context + all tasks.

        Replaces the entire MR description with a comprehensive view:
        - Issue title and description
        - Table of all tasks with status and prompt summary
        - Issue reference (Closes #N)
        """
        mr_iid = issue.merge_request_iid
        if not mr_iid:
            return

        try:
            all_tasks = (await db.execute(
                select(Task)
                .where(Task.issue_id == issue.id)
                .order_by(Task.id)
            )).scalars().all()

            status_icons = {
                TaskStatus.PENDING: "⏳",
                TaskStatus.QUEUED: "📋",
                TaskStatus.RUNNING: "🔄",
                TaskStatus.COMPLETED: "✅",
                TaskStatus.FAILED: "❌",
                TaskStatus.CANCELLED: "🚫",
            }

            lines = []
            lines.append(f"## {issue.title or 'Untitled Issue'}")
            lines.append("")
            if issue.description:
                lines.append(issue.description)
                lines.append("")

            lines.append("---")
            lines.append("")
            lines.append("### 任务执行记录")
            lines.append("")
            lines.append("| # | 状态 | 提示 |")
            lines.append("|---|------|------|")

            for t in all_tasks:
                icon = status_icons.get(t.status, "❓")
                status_label = t.status.value if t.status else "unknown"
                prompt_short = (t.user_prompt or "")[:80]
                if len(t.user_prompt or "") > 80:
                    prompt_short += "..."
                prompt_short = prompt_short.replace("|", "\\|").replace("\n", " ")
                lines.append(f"| {t.id} | {icon} {status_label} | {prompt_short} |")

            lines.append("")

            description = "\n".join(lines)

            # Use sudo GL if available for MR update
            gl = sudo_gl or self.gitlab.gl
            project = gl.projects.get(task.project_id)
            try:
                mr = project.mergerequests.get(mr_iid)
            except Exception:
                logger.warning(f"Could not find MR !{mr_iid} to update description")
                return

            mr.description = description
            if issue.title:
                mr.title = issue.title
            mr.save()
            logger.info(
                f"[Task {task.id}] Updated MR !{mr_iid} title+description "
                f"with issue #{issue.id} context ({len(all_tasks)} tasks)"
            )

        except Exception as e:
            logger.warning(f"[Task {task.id}] Failed to update MR description: {e}")
```

- [ ] **Step 2: Run existing tests**

Run: `cd backend && python -m pytest tests/unit/ -q --timeout=60`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/core/worker.py
git commit -m "feat: _update_mr_description_for_issue supports sudo GL"
```

---

### Task 6: Worker — wire sudo GL into `execute_task()` and `_execute_resume_task()`

**Files:**
- Modify: `backend/app/core/worker.py:900-955` (execute_task MR creation section)
- Modify: `backend/app/core/worker.py:1012-1050` (execute_task post-completion section)
- Modify: `backend/app/core/worker.py:1157-1183` (_execute_resume_task post-completion section)

- [ ] **Step 1: Add sudo GL creation in `execute_task()` before MR creation**

In `backend/app/core/worker.py`, after line 908 (`had_existing_mr = ...`) and before the log-clearing block, add sudo GL creation. Insert after `had_existing_mr` assignment:

```python
        # Create sudo GL for MR operations if initiator has a GitLab user ID
        sudo_gl: Optional[Gitlab] = None
        if task.initiator_gitlab_user_id and self.gitlab.settings.gitlab_admin_token:
            try:
                sudo_gl = self.gitlab.create_sudo_gl(task.initiator_gitlab_user_id)
                logger.info(
                    f"[Task {task_id}] Using sudo impersonation for GitLab user {task.initiator_gitlab_user_id}"
                )
            except ValueError as e:
                logger.warning(f"[Task {task_id}] Cannot use sudo: {e}, falling back to bot token")
```

- [ ] **Step 2: Pass `sudo_gl` to `_create_mr_if_needed()`**

Change the call at line 947 from:
```python
                mr_iid, mr_web_url = self._create_mr_if_needed(task, issue, mr_iid, mr_web_url)
```
to:
```python
                mr_iid, mr_web_url = self._create_mr_if_needed(task, issue, mr_iid, mr_web_url, sudo_gl=sudo_gl)
```

- [ ] **Step 3: Ensure label before MR creation**

Insert before the `_create_mr_if_needed` call (inside the `if issue and issue.target_branch:` block):

```python
            if issue and issue.target_branch:
                # Ensure "Codify" label exists in the project
                try:
                    self.gitlab.ensure_project_label(task.project_id, "Codify", "#6699cc")
                except Exception as e:
                    logger.warning(f"[Task {task_id}] Failed to ensure Codify label: {e}")

                mr_iid, mr_web_url = self._create_mr_if_needed(task, issue, mr_iid, mr_web_url, sudo_gl=sudo_gl)
```

- [ ] **Step 4: Pass `sudo_gl` to `_remove_mr_draft_status_for_issue()` in execute_task**

Change line 1016 from:
```python
                        self._remove_mr_draft_status_for_issue(task, issue)
```
to:
```python
                        self._remove_mr_draft_status_for_issue(task, issue, sudo_gl=sudo_gl)
```

- [ ] **Step 5: Pass `sudo_gl` to `_update_mr_description_for_issue()` in execute_task**

Change line 1050 from:
```python
                await self._update_mr_description_for_issue(task, issue, db)
```
to:
```python
                await self._update_mr_description_for_issue(task, issue, db, sudo_gl=sudo_gl)
```

- [ ] **Step 6: Add sudo GL creation in `_execute_resume_task()`**

In `_execute_resume_task()`, after `had_existing_mr` assignment (line 1109), add:

```python
        # Create sudo GL for MR operations if initiator has a GitLab user ID
        sudo_gl: Optional[Gitlab] = None
        if task.initiator_gitlab_user_id and self.gitlab.settings.gitlab_admin_token:
            try:
                sudo_gl = self.gitlab.create_sudo_gl(task.initiator_gitlab_user_id)
            except ValueError:
                pass  # Fall back to bot token silently
```

- [ ] **Step 7: Pass `sudo_gl` to `_remove_mr_draft_status_for_issue()` in _execute_resume_task**

Change line 1161 from:
```python
                        self._remove_mr_draft_status_for_issue(task, issue)
```
to:
```python
                        self._remove_mr_draft_status_for_issue(task, issue, sudo_gl=sudo_gl)
```

- [ ] **Step 8: Pass `sudo_gl` to `_update_mr_description_for_issue()` in _execute_resume_task**

Change line 1183 from:
```python
                await self._update_mr_description_for_issue(task, issue, db)
```
to:
```python
                await self._update_mr_description_for_issue(task, issue, db, sudo_gl=sudo_gl)
```

- [ ] **Step 9: Run all tests**

Run: `cd backend && python -m pytest tests/unit/ -q --timeout=60`
Expected: All PASS

- [ ] **Step 10: Commit**

```bash
git add backend/app/core/worker.py
git commit -m "feat: wire sudo GL and ensure_label into task execution"
```

---

### Task 7: Unit tests for sudo integration in worker

**Files:**
- Create: `backend/tests/unit/test_worker_sudo.py`

- [ ] **Step 1: Write worker sudo unit tests**

Create `backend/tests/unit/test_worker_sudo.py`:

```python
"""Unit tests for MR sudo impersonation in WorkerExecutor."""

import unittest
from unittest.mock import MagicMock, patch, AsyncMock

from gitlab import Gitlab


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
        """Should use sudo GL to get and save MR."""
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
```

- [ ] **Step 2: Run tests**

Run: `cd backend && python -m pytest tests/unit/test_worker_sudo.py -v`
Expected: All 6 tests PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_worker_sudo.py
git commit -m "test: add unit tests for MR sudo impersonation in worker"
```

---

### Task 8: Run full test suite and verify

**Files:** None (verification only)

- [ ] **Step 1: Run full backend test suite**

Run: `cd backend && python -m pytest tests/unit/ -v --timeout=60`
Expected: All tests PASS

- [ ] **Step 2: Run frontend build to check for type errors**

Run: `cd frontend && npx vite build`
Expected: Build succeeds (no frontend changes in this feature)

- [ ] **Step 3: Final commit if any fixups needed**

If tests reveal issues, fix and commit with:
```bash
git commit -m "fix: address test failures in sudo impersonation"
```
