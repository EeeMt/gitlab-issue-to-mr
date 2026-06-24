# Worker Profiles Design

**Date:** 2026-06-24
**Status:** Draft

## Context

Codify currently has one global worker runtime configuration. The Worker settings page controls
container image, custom mounts, custom environment variables, custom pre/post scripts, and the
default run-instruction templates used to render `tasks.rendered_prompt`.

That model is too coarse for teams that need different execution environments. A Java service may
need a worker image with JDK/Maven tooling and Maven cache mounts, while a frontend project may
need a different Node image and npm cache settings. CI auto-repair also needs to run with the same
worker and AI provider defaults chosen for the issue, not with a hidden system-wide default.

The existing prompt design already established an important rule: task execution should use a
task-level snapshot for mutable runtime intent. Worker profile selection should follow the same
rule. Profiles are editable configuration; a task snapshot is the execution fact.

## Goals

1. Support multiple configurable worker profiles.
2. Let each issue define its default worker profile and default AI provider.
3. Let each task use the issue defaults or explicitly override worker/provider.
4. Make CI auto-repair tasks use the issue default worker and issue default AI provider.
5. Snapshot worker runtime configuration onto each new task so queued and historical tasks are
   reproducible even if a profile is later edited.
6. Keep workspace path, workspace retention, Docker network, container prefix, image pull policy,
   and scheduler concurrency as global settings in the first version.
7. Preserve the existing runtime contract: the worker consumes a persisted prompt file under
   `/tmp/codify-runtime/task-prompt.md`, and custom scripts are materialized as runtime files.

## Non-Goals

- Adding automatic routing rules by project, labels, task mode, repository language, or CI failure
  type.
- Versioning worker profiles as first-class append-only records.
- Moving AI provider configuration into worker profiles.
- Making workspace roots or retention policies profile-specific.
- Adding a full historical diff UI for profile edits.
- Rebuilding historical completed tasks with synthetic worker snapshots.

## Terminology

### Worker Profile

An editable administrator-owned runtime configuration for worker containers. It includes:

- display metadata: name, description, enabled, default marker
- container image
- custom volume mounts
- custom environment variables
- pre/post scripts
- execute, plan, and CI auto-repair run-instruction templates

### Task Worker Snapshot

An immutable task-level copy of the effective worker profile fields used by the task. Runtime code
reads this snapshot, not the current worker profile row.

### Issue Defaults

Two issue-level defaults:

- `default_worker_profile_id`
- `default_provider_id`

These provide the normal choice for tasks created under that issue. They are explicit issue
settings, not dynamic references to whatever system defaults happen to be current later.

## Product Rules

### Default Resolution

Task creation resolves worker and provider in this order:

```text
explicit task selection
-> issue default
-> system default
```

When an issue is created, Codify writes the current system default worker profile and current
system default AI provider into the issue. Later changes to the system defaults do not silently
change existing issues.

Tasks persist the resolved `worker_profile_id`, `provider_id`, rendered prompt, and worker snapshot
at creation time. Later changes to the issue defaults do not affect existing tasks.

### CI Auto-Repair

CI auto-repair tasks use the issue default worker profile and issue default AI provider.

If either issue default is missing, disabled, or points to a deleted configuration, CI auto-repair
fails closed with a clear error. It must not silently fall back to the system default, because that
would hide the actual runtime environment used to repair CI.

### Task Editing

Only `PENDING` and `QUEUED` tasks can change `worker_profile_id`, `provider_id`, prompt, task mode,
require-changes, or run-instruction template. Editing any field that affects prompt or worker
runtime rebuilds the task worker snapshot and the rendered prompt in the same transaction.

Once a task starts running, it uses its stored snapshot. Profile edits made by administrators after
that point only affect future task snapshots.

## Data Model

### `worker_profiles`

Stores the current editable profile configuration.

Fields:

- `id`
- `name`
- `description`
- `enabled`
- `is_default`
- `image`
- `volume_mounts` as JSON text or JSON column, using the existing mount shape:
  `{host_path, container_path, mode}`
- `pre_script`
- `post_script`
- `default_execute_run_instruction_template`
- `default_plan_run_instruction_template`
- `ci_auto_repair_run_instruction_template`
- `created_at`
- `updated_at`

Constraints:

- exactly one profile should be default
- the default profile cannot be disabled
- referenced profiles are disabled rather than physically deleted
- profile names are unique so operators can distinguish profiles in task and issue selectors

### `worker_profile_environment_variables`

Stores environment variables per profile.

Fields:

- `id`
- `worker_profile_id`
- `key`
- `value`
- `is_secret`
- `created_at`
- `updated_at`

Rules:

- reuse the current worker environment key validation
- secrets are encrypted at rest
- profile environment variables cannot use reserved runtime keys such as `TASK_ID`,
  `GITLAB_TOKEN`, `ANTHROPIC_API_KEY`, `RESUME_SESSION`, `CODIFY_TASK_PROMPT_FILE`, or
  `USER_PROMPT`
- duplicate keys within one profile are rejected

The existing global `worker_environment_variables` table becomes a migration source and deprecated
compatibility surface, not the runtime source for new tasks.

### `issues`

Add:

- `default_worker_profile_id`
- `default_provider_id`

Issue creation fills both fields from the current system defaults. Issue update APIs allow changing
them later for future tasks.

### `tasks`

Add:

- `worker_profile_id`

This records the profile chosen for the task and supports display, filtering, and edit form
round-trips. Runtime does not read the current profile row through this field.

### `task_worker_profile_snapshots`

Stores the effective runtime worker configuration for one task.

Fields:

- `task_id`
- `worker_profile_id`
- `profile_name`
- `image`
- `volume_mounts`
- `environment_variables`
- `pre_script`
- `post_script`
- `default_execute_run_instruction_template`
- `default_plan_run_instruction_template`
- `ci_auto_repair_run_instruction_template`
- `created_at`
- `updated_at`

Secret environment values in the snapshot remain encrypted at rest and are decrypted only when
building the worker container environment.

There is one snapshot per task. Editing a `PENDING` or `QUEUED` task replaces the snapshot contents
for that task.

## Backend Design

### Profile API

Add worker profile management endpoints:

- `GET /api/worker-profiles`
- `POST /api/worker-profiles`
- `PATCH /api/worker-profiles/{id}`
- `POST /api/worker-profiles/{id}/set-default`
- `POST /api/worker-profiles/{id}/disable`
- `POST /api/worker-profiles/{id}/duplicate`

Responses expose secret environment variables in the same style as the current Worker settings
API: no plaintext secret value, but include `value_configured`.

Profile writes validate:

- nonblank name
- enabled/default invariants
- valid image string
- valid mount entries
- valid environment keys
- nonblank run-instruction templates
- known run-instruction placeholders

### Issue API

Issue create and update payloads gain:

- `default_worker_profile_id`
- `default_provider_id`

If omitted on create, the backend fills current system defaults. If provided, the backend validates
that the worker profile and provider exist and are enabled.

Issue detail responses include default worker/provider display metadata so task creation UI can
start from the issue defaults without extra lookups.

### Task API

Task create and update payloads gain:

- `worker_profile_id`

Create behavior:

1. Resolve worker profile from explicit request, issue default, then system default.
2. Resolve provider from explicit request, issue default, then system default.
3. Validate both resolved records are enabled.
4. Create the task with resolved `worker_profile_id` and `provider_id`.
5. Build and store the worker snapshot from the resolved profile.
6. Select the run-instruction template:
   - explicit `run_instruction_template` wins
   - otherwise use the snapshot template for task mode or CI auto-repair
7. Render and store `tasks.rendered_prompt`.

Update behavior for `PENDING` and `QUEUED` tasks:

1. If `worker_profile_id` is present, resolve and validate it. `null` means use the issue default.
2. If `provider_id` is present, resolve and validate it. `null` means use the issue default.
3. Rebuild the worker snapshot whenever worker selection changes.
4. Re-render the prompt whenever worker selection, task mode, user prompt, require-changes, or
   run-instruction template changes.
5. Reject edits once status is no longer `PENDING` or `QUEUED`.

Task responses include:

- `worker_profile_id`
- `worker_profile_name`
- `worker_image`
- `worker_snapshot_created_at`

The response does not expose secret environment values.

### Worker Runtime

Introduce a small resolved-runtime object used by `create_execute_container()`:

```text
TaskWorkerRuntime(
  image,
  volume_mounts,
  environment_variables,
  pre_script,
  post_script,
  run_instruction_templates
)
```

`create_execute_container()` loads this from `task_worker_profile_snapshots`.

Runtime changes:

- `pull_image()` uses `snapshot.image`
- `create_container(image=...)` uses `snapshot.image`
- `build_container_env()` receives decrypted snapshot environment variables as custom env
- `build_container_volumes()` receives snapshot mounts
- workspace, runtime, Claude session, and shared mounts are still added before custom mounts
- custom mounts remain last and can override system subpaths as they can today
- pre/post scripts are materialized from snapshot fields into the task runtime directory
- `Task.rendered_prompt` remains the source for `task-prompt.md`

If a new task has no worker snapshot, execution fails clearly. There is no implicit fallback to the
current default profile at runtime.

## Frontend Design

### Worker Settings

The System Config Worker page becomes a profile manager.

Layout:

- profile list: name, default marker, enabled state, image, mount count, env count
- editor panel for the selected profile

Editor sections:

- image
- volume mounts
- environment variables
- pre/post scripts
- execute, plan, and CI auto-repair run-instruction templates

The current compact mount/env row design remains. New mount and env rows are inserted at the top.

Actions:

- create profile
- duplicate profile
- set default
- disable profile
- save changes
- revert changes

The default profile cannot be disabled.

### Issue Create and Detail

Issue create includes default Worker and default AI Provider controls. They are initialized from
the current system defaults.

Issue detail exposes a compact settings area for the issue defaults. Changing these defaults only
affects future tasks and future CI auto-repair tasks.

### Task Drawer

The task create/edit drawer adds Worker selection near AI Provider selection.

Create mode:

- defaults to the issue default worker/provider
- allows explicit per-task override

Edit mode:

- `PENDING` and `QUEUED` tasks can change worker/provider
- terminal or running tasks show the actual worker/provider but do not allow edits

Run-instruction behavior:

- if the user has not manually edited the run-instruction template, switching worker or task mode
  loads the selected worker snapshot/default template for the selected mode
- if the user has manually edited it, switching worker keeps the edited content
- provide an explicit action to restore the selected worker's default run instruction

### Task Detail

Task metadata shows:

- worker profile name
- worker image from snapshot
- AI provider name

The task detail page continues to show `用户提示词 / 最终运行提示词` as already designed. It does
not show secret env values. Full snapshot expansion can be added later as an admin debugging view.

## Migration

Use Alembic revision `052_worker_profiles.py`.

The production upgrade process will wait for all existing `PENDING` and `QUEUED` tasks to finish
before deploying this migration. Therefore the migration does not need to generate runtime
snapshots for old queued work.

Migration steps:

1. Create worker profile tables and task snapshot table.
2. Add `issues.default_worker_profile_id`, `issues.default_provider_id`, and
   `tasks.worker_profile_id`.
3. Create one `Default Worker` profile from existing global worker settings:
   - `worker_image`
   - `worker_volume_mounts`
   - `worker_pre_script`
   - `worker_post_script`
   - `default_execute_run_instruction_template`
   - `default_plan_run_instruction_template`
   - `ci_auto_repair_run_instruction_template`
   - existing global worker environment variables
4. Mark `Default Worker` as default and enabled.
5. Fill existing issues with `default_worker_profile_id = Default Worker`.
6. Fill existing issues with the current default AI provider when one exists. If no default provider
   exists, leave `default_provider_id` empty and let new task creation fail clearly until an
   administrator configures a default provider or edits the issue default.
7. Do not create synthetic snapshots for historical terminal tasks.

The old global Worker config fields remain for one release as migration source and compatibility
surface. New runtime code should use worker profiles and task snapshots.

## Error Handling

- Creating a task without a resolvable worker profile returns `422` or `409` with a clear message.
- Creating a task without a resolvable enabled provider returns the existing provider validation
  error style.
- CI auto-repair fails closed if issue default worker/provider is missing or disabled.
- Running a task without a snapshot fails before container creation.
- Invalid mount JSON or invalid env keys are rejected at profile save time.
- Secret env values are never returned in API responses.

## Testing

Backend tests:

- migration creates `Default Worker` from legacy settings
- migration fills issue default worker/provider
- profile CRUD validates names, default invariants, disabled profiles, mounts, env keys, and secret
  env behavior
- task create uses explicit worker/provider over issue defaults
- task create uses issue defaults when explicit values are omitted
- task create falls back to system defaults only when issue defaults are absent
- CI auto-repair uses issue default worker/provider and fails closed when they are invalid
- editing `PENDING` or `QUEUED` task rebuilds snapshot and rendered prompt
- editing running or terminal task rejects worker/provider changes
- worker execution uses snapshot image/env/mounts/scripts, not current profile values
- run-instruction template rendering uses explicit template first, otherwise snapshot template

Frontend tests:

- Worker settings lists and edits profiles
- duplicate, set default, disable, and save actions call the expected APIs
- secret env fields keep configured state without exposing values
- issue create initializes worker/provider from system defaults
- issue detail updates issue defaults
- task drawer initializes worker/provider from issue defaults
- switching worker refreshes run instruction only when it has not been manually edited
- editing existing pending task sends worker/provider changes
- non-editable task states render worker/provider as read-only metadata

Closeout commands:

```bash
backend/.venv/bin/python -m pytest <targeted backend tests>
cd frontend && npx vitest run --config vitest.config.ts <targeted frontend tests>
cd frontend && npx vue-tsc --noEmit
cd frontend && npm run build
git diff --check
```
