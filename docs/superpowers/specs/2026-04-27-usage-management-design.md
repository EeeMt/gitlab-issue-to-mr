# Usage Management Design

## Problem

Codify needs user-level usage management for both token consumption and task count. Limits must support daily and weekly windows, system-wide defaults, per-user overrides, and an explicit unlimited mode. The system does not need real-time token accounting; usage is tracked at task granularity after task completion data is available.

The feature must provide:

- A dedicated admin page to view user usage and configure limits
- A top bar usage indicator for the current user
- Friendly over-limit feedback during task creation
- A second quota check immediately before task execution starts

## Accepted Product Decisions

- Limits are enforced on **both** token totals and task counts
- Counted usage includes **all finished tasks with recorded usage data**
- Limits are checked at **task creation time** and **again immediately before execution**
- If execution-time validation fails, the task is marked **FAILED** with a clear quota reason
- Each quota item supports **inherit / custom / unlimited** at the user level
- The management page is **admin-only**
- Over-limit feedback shows the exceeded quota items, current usage, limit value, and next reset time
- Daily and weekly windows use **calendar day** and **calendar week** in the **system timezone**
- The UI includes both:
  - a dedicated admin usage management page
  - a top bar usage icon showing the current user's status on hover

## Goals

1. Keep quota logic isolated from existing user management and analytics concerns
2. Reuse task-level token statistics already captured by the worker
3. Make quota decisions deterministic and explainable
4. Keep the UI consistent with the existing admin and dashboard patterns

## Non-Goals

- Real-time token streaming or live deduction while a task is running
- Token reservation before task completion
- Project-level or group-level quotas
- Monthly quotas or billing workflows

## Proposed Architecture

### Core Components

1. **Usage limit policy storage**
   - Stores the system default quota policy
   - Stores per-user overrides
   - Each quota item is modeled independently so a user can inherit one field while customizing another

2. **Task usage ledger**
   - Stores one usage row per counted task
   - Derived from finished task data, not from live execution events
   - Becomes the source for day/week usage calculations

3. **UsageQuotaService**
   - Resolves effective limits for a user
   - Reads current usage for the active calendar day and calendar week
   - Performs create-time and execute-time quota validation
   - Produces structured over-limit responses for API callers and UI rendering

4. **Admin usage management APIs**
   - Read and update system defaults
   - Read users with effective limits and current usage
   - Read and update per-user overrides

5. **Current-user usage summary API**
   - Feeds the top bar indicator
   - Feeds the create-task page precheck display

### Why a Dedicated Domain Model

This feature should not be layered onto `users`, and it should not reuse analytics as its enforcement source. The existing `users` model is focused on identity and access state, while analytics is optimized for reporting. Usage enforcement needs explicit quota semantics, inheritance rules, reset windows, and stable structured responses. A dedicated quota domain keeps these responsibilities clear and easier to evolve.

## Data Model

### 1. Usage Limit Policy

Create a dedicated table for effective policy definitions.

Suggested shape:

- `id`
- `scope_type` (`system_default`, `user`)
- `user_id` nullable, unique when `scope_type = user`
- For each quota item:
  - `<field>_mode`
  - `<field>_value`
- timestamps

Quota fields:

- `daily_tokens`
- `weekly_tokens`
- `daily_tasks`
- `weekly_tasks`

Mode semantics:

- **system default policy**: `custom` or `unlimited`
- **user policy**: `inherit`, `custom`, or `unlimited`

This gives explicit behavior without abusing nulls to mean several different things.

### 2. Task Usage Ledger

Create a dedicated ledger table with one row per counted task.

Suggested shape:

- `task_id` unique
- `user_id`
- `task_status`
- `completed_at`
- `timezone_day`
- `timezone_week_start`
- `input_tokens`
- `output_tokens`
- `total_tokens`
- `task_count` (always `1`)
- timestamps

This ledger is written only after the task reaches a finished state and usage data is available. It keeps quota math stable even if task querying becomes more complex later.

## Effective Limit Resolution

For each of the four quota items:

1. Start from the system default
2. If the user has no override row, use the system default
3. If the user override mode is:
   - `inherit`: use the system default
   - `custom`: use the user value
   - `unlimited`: treat the quota as unbounded

The resolved output should be normalized into a single structure that all callers consume.

## Usage Accounting Rules

### Counted Tasks

Count a task only when all of the following are true:

- the task is in a terminal state
- the task has usage statistics available
- the task has an initiator user

Included terminal outcomes:

- `COMPLETED`
- `FAILED`
- `CANCELLED`

If a task never produces usage data, it does not create a ledger row and does not count toward quota usage.

### Time Windows

- **Daily usage**: rows whose `timezone_day` matches the current system-local date
- **Weekly usage**: rows whose `timezone_week_start` matches the current system-local week start

The reset timestamp returned to the UI should be the next calendar boundary in the system timezone for the relevant window.

### Idempotency

Ledger writes must be idempotent by `task_id`. Re-processing a task should update or no-op, never double-count.

## Enforcement Flow

### Create-Time Check

Before `POST /tasks` inserts a new task:

1. Resolve the initiator user
2. Resolve effective limits
3. Read current day/week usage
4. If any quota item is already exceeded, reject the request

Recommended response shape:

```json
{
  "reason": "usage_limit_exceeded",
  "scope": "create",
  "exceeded_items": [
    {
      "metric": "tokens",
      "window": "daily",
      "used": 120000,
      "limit": 100000,
      "reset_at": "2026-04-28T00:00:00+08:00"
    }
  ]
}
```

### Execute-Time Check

Before a task is transitioned to `RUNNING`:

1. Re-run the same quota check
2. If the user is now over quota:
   - do not start the container
   - mark the task as `FAILED`
   - store a clear quota message in `error_message`
   - append a task log entry with the structured reason

This check must be shared by both:

- manual execution entrypoints
- scheduler-driven execution

### Post-Execution Accounting

When a task reaches terminal state and usage statistics are available:

1. compute `total_tokens`
2. compute the calendar day and calendar week keys in system timezone
3. upsert the ledger row for that task

## Important Behavioral Constraint

This design intentionally does **not** reserve quota for pending, queued, or running tasks. Quota checks only consider finished tasks that have already been recorded in the ledger.

As a result, concurrent in-flight tasks can still cause a user to exceed quota after the fact. This is an accepted trade-off for the current scope because the product explicitly does not require real-time accounting and only needs task-granularity tracking.

## API Design

### Admin APIs

Suggested capabilities:

- `GET /admin/usage-limits/default`
- `PATCH /admin/usage-limits/default`
- `GET /admin/usage-limits/users`
- `GET /admin/usage-limits/users/{user_id}`
- `PATCH /admin/usage-limits/users/{user_id}`

User list responses should include:

- identity fields needed for the page
- current day/week usage
- resolved effective limits
- raw override state for editing
- next reset timestamps

### Current User Summary API

Suggested capability:

- `GET /usage/me`

Response should include:

- current day/week usage
- effective limits
- exceeded state
- reset timestamps
- optionally a summarized severity for the top bar indicator

### Unified Error Contract

Quota failures at create time and execute time should share the same structured error model, with only `scope` differing.

## Frontend Design

### Admin Usage Management Page

Add a new admin-only page parallel to existing admin pages such as access management.

Suggested layout:

1. **System default limits panel**
   - Four editable quota items
   - Each item supports numeric value or unlimited

2. **User usage and override table/list**
   - Search/filter by user identity
   - Show current day/week usage
   - Show effective limits
   - Inline edit each quota item with:
     - inherit
     - custom value
     - unlimited

This should follow the interaction style already used by `AccessManagement.vue`: fetch a user list, keep local drafts, save changes explicitly, and avoid modal-heavy editing unless needed.

### Top Bar Usage Indicator

Add a compact icon to the top bar for the current authenticated user.

Hover content should show:

- current day token usage
- current week token usage
- current day task count
- current week task count
- effective limits for each item
- next reset times

The icon can also visually indicate quota health:

- normal
- near limit
- exceeded

### Create Task UX

The create-task page should:

- fetch current-user quota summary during page load or when the relevant context changes
- show a non-blocking status message if the user is near or over a limit
- render friendly structured feedback when the create API rejects due to quota

The existing pattern of disabled actions plus contextual inline warnings is a good fit here.

### Task Failure UX

If execute-time validation fails:

- task list and task detail should show a readable failure reason
- the reason should make clear that the task was blocked before execution because quota was exceeded

## Error Handling

- Missing user identity for a quota-checked task should fail explicitly, not silently bypass quota
- Missing or malformed usage ledger rows should surface operational errors in logs
- Invalid quota values should be rejected at API validation time
- Unlimited fields should never require numeric payload values
- Inherit mode should never persist stale custom numeric values as active data

## Testing Strategy

### Backend Unit Tests

Cover:

- effective-limit resolution for system default and user override combinations
- unlimited handling
- calendar day and calendar week boundary calculations
- create-time over-limit decisions
- execute-time over-limit decisions
- ledger idempotency by `task_id`

### Backend API Tests

Cover:

- admin-only access to management APIs
- successful update of system defaults
- successful update of per-user overrides
- create task rejection with structured quota payload
- execution-time failure path without container start

### Frontend Tests

Cover:

- usage management page rendering and editing
- top bar hover summary rendering
- create-task page over-limit warning and error presentation
- task detail rendering of execution-time quota failure

## Rollout Notes

- Start with the admin page and current-user summary in the UI
- Keep messaging explicit that usage is based on finished tasks, not live running tasks
- Reuse the new quota service everywhere instead of duplicating checks in endpoints or workers

## Recommended Implementation Direction

Implement this as a dedicated quota subsystem centered on:

- a policy table for system default plus per-user overrides
- a task-level usage ledger
- a shared quota service
- one admin management page
- one current-user top bar indicator

This gives the clearest semantics for inheritance, unlimited mode, dual create/execute checks, and user-facing explanations without overloading existing user or analytics code paths.
