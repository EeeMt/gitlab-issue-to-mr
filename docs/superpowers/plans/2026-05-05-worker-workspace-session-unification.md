# Worker Workspace Session Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make persistent issue workspaces default and store Claude session files under the same issue workspace root as repo and runtime files.

**Architecture:** Extend the existing `IssueWorkspacePaths` value object with `claude_path`, make runtime volume construction prefer workspace-local Claude sessions, and keep legacy `session_storage_path` only as the fallback when workspace persistence is explicitly disabled. Issue creation writes the unified path for new issues when workspace persistence is enabled.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy models, Pydantic settings, unittest/pytest.

---

## File Structure

- Modify `backend/app/config.py`
  - Change `Settings.worker_workspace_host_path` default from `""` to `"/opt/codify-workspaces"`.
- Modify `backend/app/core/worker_workspace.py`
  - Add `claude_path` to `IssueWorkspacePaths`.
  - Return `issue_root/claude` from `build_issue_workspace_paths()`.
- Modify `backend/app/core/worker_runtime.py`
  - Introduce a named `_CLAUDE_CONTAINER_PATH`.
  - Mount `workspace_paths.claude_path` to `/home/codify/.claude` when workspace is enabled.
  - Fall back to `issue.session_storage_path` only when workspace is disabled.
- Modify `backend/app/api/issues.py`
  - Set new issue `session_storage_path` to workspace-local `claude_path` when `WORKER_WORKSPACE_HOST_PATH` is enabled.
  - Preserve legacy `SESSION_STORAGE_ROOT/{issue_id}/claude` when workspace is disabled.
- Modify `backend/tests/unit/test_worker_workspace.py`
  - Cover `claude_path`.
- Modify `backend/tests/unit/test_worker_coverage.py`
  - Cover workspace Claude mount and legacy fallback behavior.
- Modify `backend/tests/unit/test_issues_api.py`
  - Cover new issue path selection for enabled and disabled workspace roots.
- Modify `backend/tests/unit/test_config_runtime_api.py`
  - Cover the new default setting.
- Modify `docs/worker-volume-mounts.md`
  - Document default-enabled workspace and unified `claude/` layout.

## Task 1: Default Workspace Configuration

**Files:**
- Modify: `backend/app/config.py`
- Test: `backend/tests/unit/test_config_runtime_api.py`

- [ ] **Step 1: Write the failing default settings test**

Add this test method to `ConfigRuntimeAPITests` in `backend/tests/unit/test_config_runtime_api.py` after `test_get_runtime_config_includes_worker_workspace_settings`:

```python
    def test_worker_workspace_host_path_defaults_to_issue_workspace_root(self):
        """Persistent issue workspace should be enabled by default."""
        from app.config import Settings

        settings = Settings()

        self.assertEqual(settings.worker_workspace_host_path, "/opt/codify-workspaces")
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
cd backend
pytest tests/unit/test_config_runtime_api.py::ConfigRuntimeAPITests::test_worker_workspace_host_path_defaults_to_issue_workspace_root -v
```

Expected: FAIL because `settings.worker_workspace_host_path` is currently `""`.

- [ ] **Step 3: Change the default setting**

In `backend/app/config.py`, replace:

```python
    worker_workspace_host_path: str = Field(default="")
```

with:

```python
    worker_workspace_host_path: str = Field(default="/opt/codify-workspaces")
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```bash
cd backend
pytest tests/unit/test_config_runtime_api.py::ConfigRuntimeAPITests::test_worker_workspace_host_path_defaults_to_issue_workspace_root -v
```

Expected: PASS.

- [ ] **Step 5: Run nearby runtime config tests**

Run:

```bash
cd backend
pytest tests/unit/test_config_runtime_api.py::ConfigRuntimeAPITests::test_get_runtime_config_includes_worker_workspace_settings tests/unit/test_config_runtime_api.py::ConfigRuntimeAPITests::test_validate_worker_workspace_host_path_allows_empty_or_absolute -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add backend/app/config.py backend/tests/unit/test_config_runtime_api.py
git commit -m "feat: enable issue workspace by default"
```

## Task 2: Workspace Path Model Includes Claude State

**Files:**
- Modify: `backend/app/core/worker_workspace.py`
- Test: `backend/tests/unit/test_worker_workspace.py`

- [ ] **Step 1: Write the failing path test assertion**

Update `test_build_issue_workspace_paths` in `backend/tests/unit/test_worker_workspace.py` to include:

```python
    assert paths.claude_path == "/opt/codify-workspaces/project-123/issue-456/claude"
```

The full test should be:

```python
def test_build_issue_workspace_paths():
    settings = SimpleNamespace(worker_workspace_host_path="/opt/codify-workspaces")
    issue = SimpleNamespace(id=456, project_id=123)
    task = SimpleNamespace(id=789)

    paths = build_issue_workspace_paths(settings, issue, task)

    assert paths.issue_root == "/opt/codify-workspaces/project-123/issue-456"
    assert paths.repo_path == "/opt/codify-workspaces/project-123/issue-456/repo"
    assert paths.claude_path == "/opt/codify-workspaces/project-123/issue-456/claude"
    assert paths.runtime_path == "/opt/codify-workspaces/project-123/issue-456/runtime/task-789"
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
cd backend
pytest tests/unit/test_worker_workspace.py::test_build_issue_workspace_paths -v
```

Expected: FAIL with an attribute error for `claude_path`.

- [ ] **Step 3: Add `claude_path` to the dataclass and builder**

In `backend/app/core/worker_workspace.py`, replace:

```python
@dataclass(frozen=True, slots=True)
class IssueWorkspacePaths:
    issue_root: str
    repo_path: str
    runtime_path: str
```

with:

```python
@dataclass(frozen=True, slots=True)
class IssueWorkspacePaths:
    issue_root: str
    repo_path: str
    claude_path: str
    runtime_path: str
```

Then replace the return block in `build_issue_workspace_paths()` with:

```python
    return IssueWorkspacePaths(
        issue_root=issue_root,
        repo_path=os.path.join(issue_root, "repo"),
        claude_path=os.path.join(issue_root, "claude"),
        runtime_path=os.path.join(issue_root, "runtime", f"task-{task.id}"),
    )
```

- [ ] **Step 4: Run workspace path tests**

Run:

```bash
cd backend
pytest tests/unit/test_worker_workspace.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add backend/app/core/worker_workspace.py backend/tests/unit/test_worker_workspace.py
git commit -m "feat: add claude path to issue workspace"
```

## Task 3: Worker Volumes Prefer Workspace-Local Claude Sessions

**Files:**
- Modify: `backend/app/core/worker_runtime.py`
- Test: `backend/tests/unit/test_worker_coverage.py`

- [ ] **Step 1: Update the workspace volume test to require Claude mount**

In `TestBuildContainerVolumes.test_issue_workspace_and_task_runtime_volumes_enabled`, set a legacy session path and assert the workspace-local Claude path is mounted:

```python
    def test_issue_workspace_and_task_runtime_volumes_enabled(self):
        """Persistent workspace mounts issue repo, Claude state, and task runtime."""
        settings = _make_settings(worker_workspace_host_path="/opt/codify-workspaces")
        worker = _make_worker()
        issue = MagicMock()
        issue.project_id = 123
        issue.id = 456
        issue.session_storage_path = "/var/codify/sessions/456/claude"
        task = MagicMock()
        task.id = 789

        volumes = worker._build_container_volumes(settings, issue, task=task)

        repo_path = "/opt/codify-workspaces/project-123/issue-456/repo"
        claude_path = "/opt/codify-workspaces/project-123/issue-456/claude"
        runtime_path = "/opt/codify-workspaces/project-123/issue-456/runtime/task-789"
        self.assertEqual(volumes[repo_path]["bind"], "/workspace")
        self.assertEqual(volumes[repo_path]["mode"], "rw")
        self.assertEqual(volumes[claude_path]["bind"], "/home/codify/.claude")
        self.assertEqual(volumes[claude_path]["mode"], "rw")
        self.assertEqual(volumes[runtime_path]["bind"], "/tmp/codify-runtime")
        self.assertEqual(volumes[runtime_path]["mode"], "rw")
        self.assertNotIn("/var/codify/sessions/456/claude", volumes)
```

- [ ] **Step 2: Add the legacy fallback test**

Add this method to `TestBuildContainerVolumes` in `backend/tests/unit/test_worker_coverage.py` after `test_issue_workspace_volumes_disabled_when_setting_empty`:

```python
    def test_legacy_session_storage_mount_used_when_workspace_disabled(self):
        settings = _make_settings(worker_workspace_host_path="")
        worker = _make_worker()
        issue = MagicMock(project_id=123, id=456)
        issue.session_storage_path = "/var/codify/sessions/456/claude"
        task = MagicMock(id=789)

        volumes = worker._build_container_volumes(settings, issue, task=task)

        self.assertEqual(
            volumes["/var/codify/sessions/456/claude"],
            {"bind": "/home/codify/.claude", "mode": "rw"},
        )
```

- [ ] **Step 3: Run the focused tests and verify the workspace test fails**

Run:

```bash
cd backend
pytest tests/unit/test_worker_coverage.py::TestBuildContainerVolumes::test_issue_workspace_and_task_runtime_volumes_enabled tests/unit/test_worker_coverage.py::TestBuildContainerVolumes::test_legacy_session_storage_mount_used_when_workspace_disabled -v
```

Expected: FAIL because workspace mode does not yet mount `.../issue-456/claude`.

- [ ] **Step 4: Implement workspace-local Claude mount**

In `backend/app/core/worker_runtime.py`, add this constant below `_RUNTIME_CONTAINER_PATH`:

```python
_CLAUDE_CONTAINER_PATH = "/home/codify/.claude"
```

Then replace the workspace and session volume block:

```python
    if workspace_paths is not None:
        try:
            os.makedirs(workspace_paths.repo_path, exist_ok=True)
            os.makedirs(workspace_paths.runtime_path, exist_ok=True)
        except OSError:
            pass
        volumes[workspace_paths.repo_path] = {"bind": _WORKSPACE_CONTAINER_PATH, "mode": "rw"}
        volumes[workspace_paths.runtime_path] = {"bind": _RUNTIME_CONTAINER_PATH, "mode": "rw"}

    if issue and issue.session_storage_path:
        os.makedirs(issue.session_storage_path, exist_ok=True)
        volumes[issue.session_storage_path] = {
            "bind": "/home/codify/.claude",
            "mode": "rw",
        }
```

with:

```python
    if workspace_paths is not None:
        try:
            os.makedirs(workspace_paths.repo_path, exist_ok=True)
            os.makedirs(workspace_paths.claude_path, exist_ok=True)
            os.makedirs(workspace_paths.runtime_path, exist_ok=True)
        except OSError:
            pass
        volumes[workspace_paths.repo_path] = {"bind": _WORKSPACE_CONTAINER_PATH, "mode": "rw"}
        volumes[workspace_paths.claude_path] = {"bind": _CLAUDE_CONTAINER_PATH, "mode": "rw"}
        volumes[workspace_paths.runtime_path] = {"bind": _RUNTIME_CONTAINER_PATH, "mode": "rw"}
    elif issue and issue.session_storage_path:
        os.makedirs(issue.session_storage_path, exist_ok=True)
        volumes[issue.session_storage_path] = {
            "bind": _CLAUDE_CONTAINER_PATH,
            "mode": "rw",
        }
```

- [ ] **Step 5: Run focused worker volume tests**

Run:

```bash
cd backend
pytest tests/unit/test_worker_coverage.py::TestBuildContainerVolumes -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add backend/app/core/worker_runtime.py backend/tests/unit/test_worker_coverage.py
git commit -m "feat: mount claude session inside issue workspace"
```

## Task 4: New Issues Store Unified Session Path

**Files:**
- Modify: `backend/app/api/issues.py`
- Test: `backend/tests/unit/test_issues_api.py`

- [ ] **Step 1: Update the existing create issue test for enabled workspace**

In `backend/tests/unit/test_issues_api.py`, update the settings patch in `test_create_issue_success` from:

```python
        with patch("app.api.issues.get_effective_settings") as mock_settings:
            mock_settings.return_value.session_storage_root = "/var/codify/sessions"
            result = await create_issue(body=body, db=mock_db, current_user=mock_user)
```

to:

```python
        with patch("app.api.issues.get_effective_settings") as mock_settings:
            mock_settings.return_value.session_storage_root = "/var/codify/sessions"
            mock_settings.return_value.worker_workspace_host_path = "/opt/codify-workspaces"
            result = await create_issue(body=body, db=mock_db, current_user=mock_user)
```

Then update the assertion from:

```python
        self.assertEqual(created.session_storage_path, "/var/codify/sessions/42/claude")
```

to:

```python
        self.assertEqual(
            created.session_storage_path,
            "/opt/codify-workspaces/project-10/issue-42/claude",
        )
```

- [ ] **Step 2: Add the disabled workspace fallback test**

Add this async test method to the same test class near `test_create_issue_success`:

```python
    async def test_create_issue_uses_legacy_session_path_when_workspace_disabled(self):
        """Should keep legacy session path when persistent workspace is disabled."""
        from app.api.issues import create_issue, CreateIssueRequest

        mock_db = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        captured_issues = []

        def capture_add(obj):
            obj.id = 42
            obj.created_at = datetime(2025, 1, 1, 12, 0, 0)
            obj.updated_at = datetime(2025, 1, 1, 12, 0, 0)
            captured_issues.append(obj)

        mock_db.add = MagicMock(side_effect=capture_add)

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "alice"

        body = CreateIssueRequest(
            title="Implement feature X",
            description="Add feature X to the system",
            project_id=10,
            base_branch="main",
        )

        with patch("app.api.issues.get_effective_settings") as mock_settings:
            mock_settings.return_value.session_storage_root = "/var/codify/sessions"
            mock_settings.return_value.worker_workspace_host_path = ""
            await create_issue(body=body, db=mock_db, current_user=mock_user)

        created = captured_issues[0]
        self.assertEqual(created.session_storage_path, "/var/codify/sessions/42/claude")
```

- [ ] **Step 3: Run the focused tests and verify enabled workspace test fails**

Run:

```bash
cd backend
pytest tests/unit/test_issues_api.py::CreateIssueTests::test_create_issue_success tests/unit/test_issues_api.py::CreateIssueTests::test_create_issue_uses_legacy_session_path_when_workspace_disabled -v
```

Expected: FAIL because create issue still always uses `session_storage_root`.

- [ ] **Step 4: Implement issue session path resolution**

In `backend/app/api/issues.py`, add this import near the other core imports:

```python
from app.core.worker_workspace import build_issue_workspace_paths
```

Then replace:

```python
    issue.session_storage_path = f"{settings.session_storage_root}/{issue.id}/claude"
```

with:

```python
    workspace_paths = build_issue_workspace_paths(settings, issue, type("TaskPathSeed", (), {"id": 0})())
    issue.session_storage_path = (
        workspace_paths.claude_path
        if workspace_paths is not None
        else f"{settings.session_storage_root}/{issue.id}/claude"
    )
```

This uses the existing workspace path helper while avoiding a real task dependency. The task id is irrelevant for `claude_path`.

- [ ] **Step 5: Run the focused issue tests**

Run:

```bash
cd backend
pytest tests/unit/test_issues_api.py::CreateIssueTests::test_create_issue_success tests/unit/test_issues_api.py::CreateIssueTests::test_create_issue_uses_legacy_session_path_when_workspace_disabled -v
```

Expected: PASS.

- [ ] **Step 6: Run the full issue API unit test file**

Run:

```bash
cd backend
pytest tests/unit/test_issues_api.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add backend/app/api/issues.py backend/tests/unit/test_issues_api.py
git commit -m "feat: store issue sessions in workspace root"
```

## Task 5: Documentation Update

**Files:**
- Modify: `docs/worker-volume-mounts.md`

- [ ] **Step 1: Update Persistent Workspace layout**

In `docs/worker-volume-mounts.md`, replace the workspace directory tree under "路径构建" with:

````markdown
`build_issue_workspace_paths()`（`worker_workspace.py`）基于 `{host_path}/project-{project_id}/issue-{issue_id}` 生成：

```text
/opt/codify-workspaces/
└── project-{project_id}/
    └── issue-{issue_id}/
        ├── repo/                  → 容器内 /workspace
        ├── claude/                → 容器内 /home/codify/.claude
        └── runtime/
            └── task-{task_id}/    → 容器内 /tmp/codify-runtime
```
````

- [ ] **Step 2: Update Persistent Workspace config text**

In the Persistent Workspace config table, change the `worker_workspace_host_path` default row to:

```markdown
| `worker_workspace_host_path` | `/opt/codify-workspaces` | 宿主机根路径；设为空字符串可关闭持久 workspace |
```

- [ ] **Step 3: Update Session Storage section**

Replace the "路径生成" and "与 Workspace 的关系" parts of Session Storage with:

````markdown
### 路径生成

启用 `worker_workspace_host_path` 时，Claude session 与 repo/runtime 同属 issue workspace：

```text
/opt/codify-workspaces/project-{project_id}/issue-{issue_id}/claude
```

关闭 `worker_workspace_host_path` 时，系统回退到 legacy session 路径：

```text
{session_storage_root}/{issue_id}/claude
```

### 与 Workspace 的关系

Session Storage 现在是 issue workspace 的一部分：

- `repo/` 存 Git 仓库和未提交现场
- `runtime/task-{task_id}/` 存单次 task 的运行时文件
- `claude/` 存 Claude CLI 会话状态

清理 issue workspace 会同时删除这三类 issue-scoped runtime state，包括 Claude resume 上下文。
````

- [ ] **Step 4: Verify markdown contains unified layout**

Run:

```bash
rg -n "claude/|/home/codify/.claude|/opt/codify-workspaces|session_storage_root" docs/worker-volume-mounts.md
```

Expected: Output includes the unified `claude/` path and the legacy fallback description.

- [ ] **Step 5: Commit**

Run:

```bash
git add docs/worker-volume-mounts.md
git commit -m "docs: document unified worker session workspace"
```

## Task 6: Final Verification

**Files:**
- Verify only.

- [ ] **Step 1: Run focused backend unit tests**

Run:

```bash
cd backend
pytest tests/unit/test_config_runtime_api.py::ConfigRuntimeAPITests::test_worker_workspace_host_path_defaults_to_issue_workspace_root tests/unit/test_worker_workspace.py tests/unit/test_worker_coverage.py::TestBuildContainerVolumes tests/unit/test_issues_api.py -v
```

Expected: PASS.

- [ ] **Step 2: Run a wider worker/config regression set**

Run:

```bash
cd backend
pytest tests/unit/test_worker_workspace.py tests/unit/test_worker_coverage.py::TestBuildContainerVolumes tests/unit/test_config_runtime_api.py tests/unit/test_issues_api.py -v
```

Expected: PASS.

- [ ] **Step 3: Check git status for unrelated changes**

Run:

```bash
git status --short
```

Expected: Only files intentionally changed by this plan are shown, plus any pre-existing unrelated user changes that must not be reverted.

- [ ] **Step 4: Commit any final verification-only doc/test adjustments**

If Task 6 required small corrections, commit them:

```bash
git add backend/app/config.py backend/app/core/worker_workspace.py backend/app/core/worker_runtime.py backend/app/api/issues.py backend/tests/unit/test_config_runtime_api.py backend/tests/unit/test_worker_workspace.py backend/tests/unit/test_worker_coverage.py backend/tests/unit/test_issues_api.py docs/worker-volume-mounts.md
git commit -m "test: verify worker workspace session unification"
```

If no corrections were needed, do not create an empty commit.

## Self-Review

- Spec coverage:
  - Default-enabled workspace is covered by Task 1.
  - `claude_path` under issue root is covered by Task 2.
  - Workspace-local session volume and legacy fallback are covered by Task 3.
  - New issue `session_storage_path` compatibility is covered by Task 4.
  - Cleanup/documentation semantics are covered by Task 5.
  - Focused regression commands are covered by Task 6.
- Placeholder scan:
  - No placeholder markers or vague test-writing steps remain.
- Type consistency:
  - `IssueWorkspacePaths.claude_path` is introduced before use in `worker_runtime.py` and `issues.py`.
  - `_CLAUDE_CONTAINER_PATH` is introduced before use in both workspace and fallback mounts.
  - Existing `build_issue_workspace_paths(settings, issue, task)` signature remains unchanged.
