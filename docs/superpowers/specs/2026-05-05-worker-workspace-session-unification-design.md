# Worker Workspace Session Unification Design

## Context

Worker execution currently uses two issue-scoped persistence roots:

- Persistent workspace, configured by `WORKER_WORKSPACE_HOST_PATH`, stores the issue repo and per-task runtime directories.
- Session storage, configured by `SESSION_STORAGE_ROOT`, stores Claude CLI state under `issue.session_storage_path`.

Both lifecycles are issue scoped. Keeping them as separate host roots makes cleanup, debugging, and deployment configuration harder than necessary.

## Goals

- Enable persistent issue workspaces by default.
- Store Claude session state inside the same issue workspace root as repo and runtime files.
- Keep existing `session_storage_path` data compatible during rollout.
- Preserve a fallback path for deployments that explicitly disable persistent workspaces.

## Non-Goals

- Do not remove the `session_storage_path` database column in this change.
- Do not migrate existing host files automatically.
- Do not change Claude resume behavior or the container path `/home/codify/.claude`.
- Do not move task runtime archives from the existing archive store.

## Directory Layout

Default host root:

```text
/opt/codify-workspaces/
  project-{project_id}/
    issue-{issue_id}/
      repo/
      claude/
      runtime/
        task-{task_id}/
```

Container mounts:

```text
.../issue-{issue_id}/repo              -> /workspace
.../issue-{issue_id}/claude            -> /home/codify/.claude
.../issue-{issue_id}/runtime/task-{id} -> /tmp/codify-runtime
```

## Configuration

`WORKER_WORKSPACE_HOST_PATH` changes from opt-in to default enabled:

```text
WORKER_WORKSPACE_HOST_PATH=/opt/codify-workspaces
```

Operators can still disable persistent issue workspaces by setting it to an empty string. When disabled, worker execution falls back to the existing temporary container workspace behavior and mounts Claude state from `issue.session_storage_path` if present.

`SESSION_STORAGE_ROOT` remains for compatibility. It is only used as the session mount source when persistent issue workspaces are disabled or when code needs to populate legacy `session_storage_path` values.

## Path Resolution

`build_issue_workspace_paths()` should return all issue workspace paths:

```text
issue_root
repo_path
claude_path
runtime_path
```

`build_container_volumes()` should resolve mounts in this order:

1. Add static/custom mounts as it does today.
2. If issue workspace paths exist, create and mount `repo_path`, `runtime_path`, and `claude_path`.
3. If issue workspace paths do not exist, keep the legacy session mount from `issue.session_storage_path`.

When workspace paths exist, the worker must not also mount `issue.session_storage_path` to `/home/codify/.claude`, because Docker volume binds cannot safely have two sources for one container path.

## Issue Creation And Compatibility

New issues may store `session_storage_path` as the unified `claude_path` when `WORKER_WORKSPACE_HOST_PATH` is configured. This keeps the serialized API field meaningful without making it the primary runtime source.

Existing issues continue to work:

- With workspace enabled, runtime session state uses the unified issue workspace path regardless of old `session_storage_path`.
- With workspace disabled, runtime session state uses the legacy `session_storage_path`.

## Cleanup Semantics

The workspace cleanup API deletes the whole issue workspace root. After this change that includes:

- repo state
- per-task runtime files under the issue root
- Claude session files

This is intentional because all three are issue-scoped runtime state. UI and docs should make clear that cleaning an issue workspace also removes Claude resume context for that issue.

TTL cleanup follows the same rule: deleting an expired issue workspace deletes its session files too.

## Tests

Focused tests should cover:

- `worker_workspace_host_path` defaults to `/opt/codify-workspaces`.
- `build_issue_workspace_paths()` includes `claude_path`.
- Worker volumes mount repo, runtime, and Claude paths when workspace is enabled.
- Worker volumes do not mount legacy `session_storage_path` when workspace is enabled.
- Worker volumes still mount legacy `session_storage_path` when workspace is disabled.
- Issue creation stores the unified `claude_path` when workspace is enabled.

## Risks

- Operators may expect workspace cleanup to preserve Claude conversation history. Documentation and API descriptions should call out the new unified cleanup behavior.
- Existing issue `session_storage_path` values can differ from the actual runtime path after enabling workspace. This is acceptable during compatibility rollout because runtime path resolution is authoritative.
