# Worker Custom Environment Variables — Design Spec

## Problem Statement

Codify workers already support custom volume mounts through runtime configuration, but they do not support user-managed custom environment variables.

The new capability should let administrators define **global worker environment variables** in the Config page, with support for both:

- normal string values
- secret values that are stored securely and never echoed back to the browser

This feature must also prevent users from overriding worker-managed built-in variables such as `GITLAB_TOKEN`, `PROJECT_ID`, `TASK_ID`, and the existing `ANTHROPIC_*` settings.

## Goal

Add a global worker environment variable editor that:

1. stores variables outside `system_config` in a dedicated table
2. supports mixed normal + secret entries
3. injects validated custom variables into worker containers
4. rejects reserved keys and malformed variable names
5. allows empty-string values (`KEY=`)

## Scope

### In Scope

- Add a dedicated database table for global worker environment variables
- Extend `/api/config/runtime` to read and write the env var list
- Add env var editing UI to `WorkerSettingsPanel.vue`
- Support secret entries without returning secret values to the browser
- Reject duplicate keys, invalid variable names, and reserved keys
- Inject validated custom variables during worker container creation
- Add backend and frontend tests for the new flow

### Out of Scope

- Task-level or issue-level environment variable overrides
- Per-project environment variable scopes
- Import/export tooling
- Reworking existing volume mount behavior
- Generic secret-management abstractions beyond this worker env var feature

## Chosen Approach

Use a **dedicated `worker_environment_variables` table** instead of storing the list in `system_config`.

This is heavier than a config-key approach, but it cleanly models mixed normal/secret rows and avoids overloading the existing scalar runtime override system with list semantics and partial secret redaction rules.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Persistence model | Dedicated table | Better fit for mixed normal/secret rows than a scalar config store |
| Key uniqueness | Unique by `key` | Prevents ambiguous merge behavior |
| Secret storage | Encrypt `value` when `is_secret = true` | Reuses existing crypto helpers and keeps one row format |
| Secret readback | Return `value_configured`, not plaintext | Matches current secret-handling expectations in config UI |
| Update model | Full-list replacement in one PATCH | Simpler client contract and transactional server logic |
| Delete behavior | Omit row from submitted list | Natural for list-editing UI |
| Empty values | Allowed | Explicit user requirement: inject `KEY=` |
| Reserved keys | Reject on save, re-check at runtime | Strong validation with runtime defense in depth |
| Injection order | Built-in env first, custom env second | Keeps system behavior stable; reserved-key validation prevents override |

## Data Model

Add a new table named `worker_environment_variables`.

### Columns

- `id` — integer primary key
- `key` — string, unique, not null
- `value` — text, not null
- `is_secret` — boolean, not null, default false
- `created_at` — datetime, not null
- `updated_at` — datetime, not null

### Storage Rules

- For normal rows, `value` is stored as plain text
- For secret rows, `value` is stored as encrypted text using the existing config crypto helpers
- `key` must match `^[A-Z_][A-Z0-9_]*$`
- `key` must not be one of the reserved worker-managed names

### Reserved Key Policy

Reserved keys include all environment variables currently owned by `WorkerExecutor._build_container_env()`, including:

- GitLab/auth fields
- task/issue metadata fields
- AI provider fields
- author/co-author fields
- session/resume fields
- custom CA bundle fields

The implementation should centralize this list in one backend helper so both API validation and runtime validation use the same source of truth.

## API Contract

The Config page should continue using `/api/config/runtime` as the integration point.

### Response shape

Extend the runtime config section with:

```ts
worker_environment_variables: WorkerEnvironmentVariable[]
```

Response item shape:

```ts
type WorkerEnvironmentVariable = {
  id: number
  key: string
  value: string
  is_secret: boolean
  value_configured: boolean
}
```

### GET behavior

- Normal rows return their actual `value`
- Secret rows return:
  - `is_secret: true`
  - `value_configured: true`
  - `value: ""`

This gives the UI enough information to show “configured” state without exposing the secret.

### PATCH behavior

`PATCH /api/config/runtime` accepts the full env var list as part of the runtime payload.

Request semantics:

- submitted list replaces the stored list transactionally
- existing rows can be matched by `id`
- secret rows with blank `value` and an existing `id` keep their current stored secret
- removing an entry from the submitted list deletes it
- changing a secret row to a normal row rewrites `value` as plain text
- changing a normal row to a secret row encrypts `value`

### Validation behavior

Reject the request with `400` when:

- a key is empty
- a key fails the env var naming regex
- two submitted rows use the same key
- a key is reserved
- a new secret row is submitted without a value

The response should identify the offending key so the UI can present a specific error.

## Frontend Design

Add a new **Environment Variables** section to `frontend/src/components/config/WorkerSettingsPanel.vue`.

### Row UI

Each row contains:

- `key` input
- `value` input
- `is_secret` toggle
- remove button

### Secret row UX

- Secret rows use a password input
- Existing configured secrets do not display their stored value
- A configured secret row shows a “configured” indicator
- Leaving the secret input blank during edit preserves the existing stored value
- Entering a new value replaces it

### Save flow

The panel submits the complete env var list together with the existing worker settings save action.

The existing dirty-state model can remain panel-local, but it must compare structured env var rows instead of only the current mount JSON.

### i18n

Add new labels and feedback strings to:

- `frontend/src/i18n/messages/en.ts`
- `frontend/src/i18n/messages/zh-CN.ts`

## Worker Injection Flow

`WorkerExecutor._build_container_env()` remains the point where container environment variables are assembled.

### Injection steps

1. Build the existing built-in environment dictionary
2. Load validated custom worker env var rows
3. Decrypt secret rows as needed
4. Re-check reserved key and name validity defensively
5. Append custom keys to the environment dict

### Failure behavior

- Invalid configuration detected at save time → reject the config update with `400`
- Invalid configuration detected at runtime despite persisted data → fail the task explicitly with a clear error

The runtime path must not silently skip invalid entries, because that would hide configuration mistakes.

## Migration and Backend Change Surface

### Migration

Add a new Alembic revision to create the table and unique index.

### Backend files likely affected

- `backend/alembic/versions/...`
- `backend/app/models.py`
- `backend/app/api/config_runtime.py`
- `backend/app/api/config.py` if the aggregate config endpoint needs matching support
- `backend/app/core/worker.py`

If shared validation helpers make the implementation cleaner, they should be introduced in a focused backend helper module rather than duplicated across API and worker code.

## Testing

### Backend

- API tests for runtime config GET/PATCH with:
  - normal rows
  - secret rows
  - reserved key rejection
  - invalid name rejection
  - duplicate key rejection
  - secret-preserve-on-blank-update semantics
- Worker unit tests for:
  - successful env merge
  - empty-string values
  - runtime defensive rejection of invalid/reserved keys

### Frontend

- `WorkerSettingsPanel` tests for:
  - add/remove rows
  - secret toggle behavior
  - configured-secret display state
  - payload shape on save
- Update config view tests/types where the runtime config contract changes

## Rollout Notes

- The feature is backward-compatible because no existing worker env var editor exists
- Existing volume mounts remain unchanged
- Runtime behavior stays global-only for this iteration
