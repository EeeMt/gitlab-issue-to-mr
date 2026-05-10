# System Data Cleanup Design

## Goal

Add a Maintenance page operation that lets platform admins clean system data by issue. The operation removes selected issues and their related task data, with an optional retention filter for data older than N days.

## Context

The Configuration page already has a Maintenance tab implemented by `frontend/src/views/config/MaintenancePanel.vue`. Today it only exposes configuration reload/reset actions.

Issues are the grouping boundary for work. Tasks belong to issues through `Task.issue_id`, while task logs, payloads, raw log chunks, runtime archive metadata, usage ledger rows, Mattermost delivery rows, ingest cursors, and issue execution locks reference tasks or issues. Existing single-issue deletion rejects issues with active tasks. This new operation is an admin maintenance function and needs a controlled force path for stale or inconsistent task state.

## Requirements

- Add a Maintenance panel action named "Clean system data".
- Clean data by issue, not by individual task.
- Support optional `older_than_days`; when set, only issues with `Issue.created_at` before `now - older_than_days` are eligible.
- If `older_than_days` is omitted, all issues are eligible.
- Default behavior skips issues containing `pending`, `queued`, or `running` tasks.
- Provide an explicit `force` option that also cleans issues containing active tasks.
- When force-cleaning running tasks, attempt to stop their Docker containers before deleting database rows.
- Return a detailed result with deleted issue/task counts, skipped active counts, file/workspace cleanup counts, container cleanup errors, and file cleanup errors.
- Restrict the operation to platform admins.

## Non-Goals

- No scheduled automatic cleanup policy.
- No GitLab-side issue, branch, or merge request deletion.
- No per-project or per-user filters in the first version.
- No dry-run endpoint in the first version.

## API

Add an admin-only endpoint:

`POST /api/config/maintenance/cleanup-system-data`

Request:

```json
{
  "older_than_days": 30,
  "force": false
}
```

`older_than_days` is optional and must be a positive integer when present. `force` defaults to `false`.

Response:

```json
{
  "deleted_issues": 12,
  "deleted_tasks": 48,
  "skipped_active_issues": 2,
  "skipped_active_tasks": 3,
  "deleted_archives": 40,
  "missing_archives": 8,
  "deleted_workspaces": 10,
  "container_cleanup_errors": [],
  "file_cleanup_errors": []
}
```

Container cleanup errors include the task id, container name, and error message. A container cleanup error does not abort database cleanup because this operation is meant to recover from inconsistent state.
File cleanup errors include the path, cleanup kind, and error message.

## Backend Design

Add a focused backend service, for example `app.core.system_data_cleanup`, with one public async function that accepts the database session, optional retention days, and force flag.

Selection:

- Query eligible issues by `Issue.created_at`.
- Load task ids and task statuses for those issues.
- If `force` is false, exclude any issue with `TaskStatus.PENDING`, `TaskStatus.QUEUED`, or `TaskStatus.RUNNING`.
- If `force` is true, include active issues and collect running task container names for best-effort stop.

Deletion:

- Delete task-related tables before deleting tasks and issues so behavior is database-portable even where cascade enforcement differs.
- Delete rows from task logs, payloads, raw log chunks, ingest cursors, runtime archive metadata, usage ledger, Mattermost delivery logs, and issue execution locks for selected task/issue ids.
- Delete tasks for selected issues.
- Delete webhook event issue references by setting `WebhookEvent.issue_id` to null for selected issues.
- Delete selected issues.
- Commit the database transaction.

File cleanup:

- Record archive paths and issue workspace paths before deleting database rows.
- After a successful commit, delete archive files whose paths exist.
- Delete issue workspaces under `worker_workspace_host_path/project-{project_id}/issue-{issue_id}`.
- File deletion failures are reported in the response but do not roll back the already-committed database cleanup.

Force cleanup:

- For each selected running task, attempt to stop Docker container `codify-{task_id}-issue{issue_id}` using the existing Docker client pattern.
- Stop failures are collected in `container_cleanup_errors`.
- Pending and queued tasks do not have containers and are just deleted with the issue data.

## Frontend Design

Extend `MaintenancePanel.vue` with a second card for system data cleanup:

- Numeric input for "Clean data older than N days"; empty means all data.
- Switch or checkbox for "Force cleanup active tasks", default off.
- Button for "Clean system data".
- Confirmation dialog before submitting.
- Confirmation copy changes when force is enabled and warns that pending, queued, and running tasks will be deleted and running containers will be stopped best-effort.
- On success, show a concise summary using the returned counts.
- On failure, show the server error detail.

Add typed API helpers and response types in `frontend/src/api/index.ts`.

Add English and Chinese i18n strings for labels, confirmation text, success summary, and error fallback.

## Error Handling

- Invalid `older_than_days` returns HTTP 422.
- Non-admin users receive the existing admin authorization failure.
- Empty result is successful and returns zero counts.
- Database failures abort and roll back the cleanup.
- Docker/file cleanup failures are reported in the response because they occur outside the core database transaction or are best-effort recovery steps.

## Testing

Backend unit tests:

- Default cleanup deletes only inactive eligible issues and related task data.
- Default cleanup skips issues with pending, queued, or running tasks and reports skipped counts.
- Force cleanup includes active issues.
- Force cleanup attempts to stop running task containers and records stop errors without aborting cleanup.
- Retention filter excludes issues newer than `older_than_days`.

Frontend tests:

- Maintenance panel renders cleanup controls.
- API helper posts `older_than_days` and `force` to the maintenance endpoint.
- Cleanup submit uses confirmation, calls the API, and displays the returned summary.
- Force option changes the submitted payload and warning text.
