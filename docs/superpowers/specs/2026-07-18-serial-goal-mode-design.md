# Serial Goal Mode Design

**Date:** 2026-07-18

**Status:** Draft

## Summary

Codify currently uses an Issue as the requirement and delivery boundary, while each Task is one
worker execution. Users can create multiple Tasks under the same Issue, but they must decide when
to add each follow-up Task and what the next prompt should contain.

This design adds an opt-in serial Goal mode. A GoalRun belongs to one Issue and automatically
advances through one Task at a time until it:

- reaches a verifiable stopping condition;
- needs approval for a risky operation;
- needs approval to expand the agreed scope;
- becomes blocked;
- is paused or cancelled by a user; or
- reaches a system safety limit.

Goal mode does not replace Issue or Task:

```text
Issue   = requirement, branch, MR, workspace, and delivery lifecycle
GoalRun = one durable automatic execution loop under an Issue
Task    = one persisted execution step in that loop
```

The first version is strictly serial. It continues to use the existing Issue workspace, Claude
session, branch, MR, Worker affinity, Task scheduler, and Issue execution lock.

## Context

Codify already provides most of the execution foundation required by a durable Goal loop:

- `Issue` groups Tasks and owns one branch and one MR.
- Every Task belongs to an Issue and represents one worker/CLI execution.
- Tasks under the same Issue reuse the persistent repository workspace.
- Claude session state is persisted at Issue scope.
- Previous Task summaries are included when preparing later Task runtime context.
- The scheduler and `IssueExecutionLock` ensure that Tasks for one Issue execute serially.
- Task runtime configuration and rendered prompts are persisted as execution-time facts.
- Task token usage is recorded by the existing usage ledger and enforced by existing user quotas.

The missing layer is a durable coordinator that can interpret a completed Goal Task, decide whether
the Goal should continue, create the next Task exactly once, and stop safely when user input is
required.

## Goals

1. Let an Issue operator start a durable GoalRun with an explicit objective, scope, success
   criteria, and verification commands.
2. Automatically create one Goal Task at a time and reuse the Issue workspace, branch, MR, and
   Claude session.
3. Require every successful Goal completion to pass configured verification commands.
4. Persist a structured decision after every Goal Task: `complete`, `continue`, `blocked`, or
   `approval_required`.
5. Support approval only for risky operations and scope expansion.
6. Support pause, resume, and cancel without losing Task history or workspace state.
7. Recover safely after backend, scheduler, worker, or container restarts without creating
   duplicate continuation Tasks.
8. Keep GoalRun status separate from Issue delivery status and Task execution status.
9. Preserve existing manual Issue/Task behavior when Goal mode is not active.

## Non-Goals

- Parallel subgoals.
- Git worktrees or multiple concurrent Tasks under one Issue.
- A generic DAG or dependency scheduler.
- Token budgets, per-Goal monetary budgets, or budget approval.
- Recursive subgoal planning.
- Multiple unfinished GoalRuns under one Issue.
- Scheduled Goal start or recurring Goals.
- Automatic MR merge, production deployment, or branch deletion.
- Waiting for GitLab CI as a Goal completion condition in the first version.
- Live interception and approval of individual model tool calls.
- Replacing the existing Task retry, CI auto-repair, or manual follow-up flows.
- Allowing the Goal objective or scope snapshot to mutate after the GoalRun starts.

---

## Terminology

### Goal contract

The immutable user-approved contract captured when a GoalRun starts:

- objective;
- allowed scope;
- success criteria;
- constraints;
- verification commands.

### Goal step

One Task created for a GoalRun. Goal steps are numbered from `1` and execute strictly in sequence.

### Goal decision

The structured result produced by a Goal Task and persisted before the container is removed.

### Goal coordinator

A durable backend loop that processes completed Goal Tasks and advances GoalRun state. It is
separate from `TaskScheduler`; the scheduler continues to schedule ordinary Tasks without needing
Goal-specific ordering logic.

### Approval request

A persisted request to approve either:

- `risk_operation`; or
- `scope_expansion`.

Approval is a workflow control, not a replacement for container isolation, project authorization,
or tool-level security.

---

## Product Decisions

### GoalRun is an Issue child, not a new top-level delivery entity

An Issue already owns the repository, branch, MR, Worker affinity, workspace, and execution
history. Creating a separate top-level Goal entity would duplicate those responsibilities.

A GoalRun therefore belongs to one Issue:

```text
Issue 1
├── ordinary Task 1
├── ordinary Task 2
├── GoalRun 1
│   ├── Goal Task step 1
│   ├── Goal Task step 2
│   └── Goal Task step 3
└── GoalRun 2 (allowed only after GoalRun 1 is terminal)
```

Historical GoalRuns remain visible after completion. Only one unfinished GoalRun may exist for an
Issue.

### Goal mode is explicitly started

Creating an Issue does not automatically create a GoalRun. Goal mode is an explicit action on the
Issue detail page.

Starting a GoalRun requires:

- Goal mode is enabled by runtime configuration.
- The Issue is not closed.
- The user can manage the Issue.
- The Issue has no active `pending`, `queued`, or `running` Task.
- The Issue has no unfinished GoalRun.
- The pinned Worker Profile and selected provider are available.
- Objective, scope, success criteria, and at least one verification command are non-empty.

An Issue in either `open` or `in_review` may start a GoalRun. Starting from `in_review` supports a
new automated follow-up loop on the existing branch and MR.

### The Goal contract is immutable

The GoalRun stores a snapshot of the objective, scope, success criteria, constraints, and
verification commands. Later edits to `Issue.title` or `Issue.description` do not change the active
Goal.

Changing the objective or agreed scope requires cancelling the current GoalRun and starting a new
one. Pause/resume guidance may clarify the next step but must not silently replace the Goal
contract.

### Goal-created Tasks are serial execute Tasks

Every Goal step:

- uses `task_mode="execute"`;
- uses `session_mode="continue"` after the first step;
- sets `require_changes=false`, because a valid verification or diagnosis step may complete
  without producing a new diff;
- uses the GoalRun creator as the Task initiator for authorization, attribution, quotas, and
  audit;
- uses the GoalRun priority;
- runs on the Issue-pinned Worker;
- reuses the same Issue branch, MR, workspace, and shared directory.

The first step may start with either `session_mode="continue"` or `session_mode="fresh"`, chosen
when the GoalRun starts. A successful first fresh step updates the Issue session pointer normally;
later steps continue from the resulting session.

### Runtime and provider behavior is pinned for the whole GoalRun

Long-running Goals must not drift because a Worker Profile or default provider changes between
steps.

At Goal start:

- resolve and store the provider ID;
- create the first Task and its `TaskWorkerProfileSnapshot`;
- persist the selected run-instruction template.

Continuation Tasks:

- reuse the pinned provider ID;
- clone the first Goal Task's Worker snapshot into a new per-Task snapshot;
- reuse the first Goal Task's run-instruction template;
- render a new prompt containing the immutable Goal contract and current progress.

The snapshot remains a per-Task execution fact, but all Tasks in one GoalRun are derived from the
same Goal-start runtime snapshot.

### No Goal budget in the first version

The first version does not expose:

- token budget;
- cost budget;
- remaining budget;
- budget increase approval; or
- budget exhaustion status.

Goal Tasks continue to count toward the existing daily/weekly Task and token quotas. Existing
creation-time and pre-execution quota checks remain authoritative.

The system still needs an anti-loop safety limit. Add one global runtime setting:

```text
goal_max_auto_steps = 10
```

This is a platform safety fuse, not a user-allocated budget. Reaching it moves the GoalRun to
`blocked` with `blocked_reason="safety_step_limit_reached"`. It does not create an approval
request.

### Only two approval gates

#### Risky operation

`risk_operation` applies when the Agent determines that completion requires an operation outside
ordinary Codify code-delivery behavior, for example:

- destructive database or data migration;
- deleting branches, tags, environments, or external artifacts;
- changing secrets, access control, authentication, or security policy;
- production deployment;
- merging an MR;
- writing to an external system beyond the integrations already authorized by the Goal contract.

Normal repository edits, tests, commits, pushes, and creation/update of the Issue MR are part of
Codify's existing delivery contract and do not require Goal approval.

#### Scope expansion

`scope_expansion` applies when the Agent believes the Goal cannot be completed without changing
the approved scope. The approval payload must identify:

- the current scope;
- the requested additional scope;
- why the current scope is insufficient;
- the proposed changes;
- expected impact.

#### Approval behavior

The Agent must stop before the proposed operation, leave the workspace in a consistent state, and
write `decision="approval_required"`.

Approving creates the next Goal step with explicit authorization for the proposed operation.
Rejecting also creates the next Goal step, but injects the rejection and requires the Agent to seek
an in-scope/non-risky alternative. If no alternative exists, the next step should return
`blocked`.

An approval applies only to the described action. It does not grant a reusable permission for
later steps.

The first version does not intercept individual shell/tool calls. These approval gates are
therefore application-level workflow controls. Container permissions, credentials, project access,
and future tool hooks remain the hard security boundaries.

### Manual Task mutation is restricted while a GoalRun is unfinished

While a GoalRun is `active`, `waiting_approval`, `paused`, or `blocked`:

- users cannot create a new ordinary Task under the Issue;
- users cannot retry or reschedule an existing Task under the Issue;
- users cannot edit a pending/queued ordinary Task under the Issue;
- a second GoalRun cannot start.

These operations return HTTP `409` with the active GoalRun ID and status.

Users can still:

- inspect all Tasks and logs;
- cancel the currently running Goal Task;
- pause, resume, or cancel the GoalRun;
- resolve a pending approval.

Cancelling the current Goal Task directly pauses the GoalRun with
`blocked_reason="current_task_cancelled"` so that it cannot silently create another step.

### Intermediate Goal steps are not final delivery

Each successful execute Task may commit and push to the shared Issue branch, but the MR remains in
Draft while the GoalRun is unfinished.

Existing finalization behavior must be adjusted:

- do not remove MR Draft status after an intermediate Goal step;
- do not transition the Issue to `in_review` between Goal steps;
- do not emit ordinary final-delivery success notification for every intermediate step;
- remove MR Draft status and emit Goal completion only after the GoalRun reaches `completed`.

Task detail still shows each step as `completed`; Goal completion is a separate lifecycle fact.

---

## GoalRun State Machine

### Status values

| Status | Meaning | Terminal |
|--------|---------|----------|
| `active` | Goal may run or create the next step | No |
| `waiting_approval` | A risk/scope approval request is pending | No |
| `paused` | User stopped automatic advancement | No |
| `blocked` | External input, failed execution, invalid result, or safety intervention is required | No |
| `completed` | Stopping condition is verified | Yes |
| `failed` | Goal orchestration failed irrecoverably | Yes |
| `cancelled` | User cancelled the GoalRun | Yes |

`blocked` remains resumable. A user must cancel a blocked GoalRun before starting a different Goal.

### Transition diagram

```mermaid
stateDiagram-v2
    [*] --> active: start GoalRun and create step 1
    active --> active: continue and create next step
    active --> completed: decision complete and verification passes
    active --> waiting_approval: risk or scope approval requested
    waiting_approval --> active: approve or reject and create next step
    active --> blocked: task failure, invalid decision, failed safety check, or explicit blocker
    blocked --> active: resume with guidance
    active --> paused: user pauses
    waiting_approval --> paused: user pauses
    blocked --> paused: user pauses
    paused --> active: user resumes
    active --> cancelled: user cancels
    waiting_approval --> cancelled: user cancels
    blocked --> cancelled: user cancels
    paused --> cancelled: user cancels
    active --> failed: unrecoverable coordinator failure
```

### Pause semantics

Pause prevents future automatic advancement; it does not terminate a running container.

- If the current Task is still active, it finishes normally.
- The coordinator persists its result but creates no continuation while the GoalRun is paused.
- Resume processes the persisted result exactly once and either advances or stops.

Cancel requests cancellation of the current Goal Task, if any, and permanently marks the GoalRun
`cancelled`.

### Blocked semantics

The GoalRun becomes `blocked` when:

- a Goal Task fails or is cancelled;
- a successful Task has a missing or invalid Goal decision;
- the Agent returns `blocked`;
- the system safety step limit is reached;
- existing usage limits prevent execution;
- the coordinator detects inconsistent Goal/Task state;
- verification cannot be executed reliably.

Resuming a blocked GoalRun requires a user guidance message. The guidance is appended to the next
step but cannot alter the immutable objective or scope.

---

## Relationship to Issue Status

GoalRun status must not be stored in `issues.status`.

Existing Issue status remains:

```text
open | in_progress | in_review | closed
```

Required behavior:

| GoalRun state | Issue status behavior |
|---------------|-----------------------|
| `active` | `in_progress` |
| `waiting_approval` | remain `in_progress` |
| `paused` | remain `in_progress` |
| `blocked` | remain `in_progress` |
| `completed` | `in_review` after verified execute delivery |
| `failed` or `cancelled` | existing no-active-task rule: `in_review` if an execute Task delivered, otherwise `open` |

`maybe_update_issue_status()` must check for an unfinished GoalRun before transitioning an Issue
after a terminal Task. This prevents a completed intermediate step from moving the Issue to
`in_review`.

Closing an Issue with an unfinished GoalRun is rejected with HTTP `409`; the GoalRun must be
cancelled first.

---

## Execution Flow

### Starting a GoalRun

```text
POST /api/issues/{issue_id}/goal-runs
-> lock Issue row
-> validate Issue, permissions, active Tasks, and active GoalRuns
-> resolve provider and Worker Profile
-> create GoalRun with immutable contract
-> create Task step 1
-> create Task Worker snapshot
-> render and persist Goal prompt
-> set GoalRun.current_task_id and current_step_index=1
-> set Issue status to in_progress
-> commit atomically
```

The GoalRun and first Task must be visible together or not at all.

### Running a Goal step

The Task follows the existing Task scheduler and Worker lifecycle:

1. Scheduler queues and runs the Task.
2. Worker reuses the Issue workspace and branch.
3. Worker materializes Goal context under `/tmp/codify-runtime`.
4. The Agent executes the current step.
5. The Agent writes a structured Goal decision.
6. Worker runs the configured verification commands and records their results.
7. Worker commits and pushes ordinary code changes.
8. Backend persists Task results, Goal artifacts, and raw logs.
9. Goal coordinator processes the terminal Task.

### Decision processing

The coordinator accepts a Goal Task only after:

- the Task is terminal;
- raw log finalization is complete, or terminal failure has no container;
- Goal decision artifact processing is finalized;
- no newer Goal Task exists.

Decision rules:

| Task/result | Coordinator behavior |
|-------------|----------------------|
| Task failed/cancelled | Goal becomes `blocked` |
| Decision missing/invalid | Goal becomes `blocked` |
| `continue` | Create the next step if safety checks pass |
| `blocked` | Persist blocker and set Goal `blocked` |
| `approval_required` | Create approval request and set `waiting_approval` |
| `complete` + all verification passed | Set Goal `completed` |
| `complete` + verification failed | Convert to continuation with failed verification evidence |

Verification failure overrides an Agent claim of completion.

### Completion

When a GoalRun completes:

1. Persist final progress summary and completion timestamp.
2. Transition the Issue to `in_review`.
3. Remove MR Draft status using the existing Issue/MR delivery path.
4. Emit Goal completion notification.
5. Leave all Goal Tasks, commits, logs, decisions, and verification artifacts available for audit.

---

## Runtime Artifact Contract

### Goal context

Backend materializes:

```text
/tmp/codify-runtime/goal-context.json
```

Example:

```json
{
  "schema_version": 1,
  "goal_run_id": 42,
  "step_index": 3,
  "objective": "Migrate the authentication client to the new API.",
  "scope": "backend/app/auth and its focused tests only.",
  "success_criteria": [
    "The new client path is used in production code.",
    "Legacy behavior remains covered by regression tests."
  ],
  "constraints": [
    "Do not change external API response shapes."
  ],
  "verification_commands": [
    "backend/.venv/bin/python -m pytest backend/tests/unit/test_auth.py",
    "git diff --check"
  ],
  "previous_progress_summary": "Steps 1-2 migrated token refresh and added compatibility tests.",
  "resume_guidance": null,
  "approval_resolution": null
}
```

The rendered Task prompt includes the same immutable contract plus an instruction to write the Goal
decision artifact. The persisted `rendered_prompt` remains the authoritative input for that Task.

### Goal decision

The Agent writes:

```text
/tmp/codify-runtime/goal-decision.json
```

Schema:

```json
{
  "schema_version": 1,
  "decision": "complete | continue | blocked | approval_required",
  "summary": "What this step changed or verified.",
  "evidence": [
    "Focused backend tests pass."
  ],
  "remaining_work": [
    "Migrate the final compatibility adapter."
  ],
  "next_prompt": "Migrate the compatibility adapter and rerun the focused suite.",
  "blocker": null,
  "user_action_required": null,
  "approval": null
}
```

For `approval_required`, `approval` is:

```json
{
  "kind": "risk_operation | scope_expansion",
  "title": "Short approval title",
  "reason": "Why the action is required",
  "proposed_action": "The exact action to approve",
  "current_scope": "Current approved scope",
  "requested_scope": "Additional scope, for scope expansion",
  "risk_detail": "Risk and reversibility, for risky operations"
}
```

Validation requirements:

- reject unknown decision values;
- require decision-specific fields;
- cap string and list sizes;
- sanitize sensitive values before persistence;
- archive the original JSON with the Task runtime archive;
- persist a normalized copy on the Task for coordinator queries;
- never infer `complete` from prose when the artifact is missing.

### Verification results

Worker writes:

```text
/tmp/codify-runtime/goal-verification.json
```

Example:

```json
{
  "schema_version": 1,
  "commands": [
    {
      "command": "backend/.venv/bin/python -m pytest backend/tests/unit/test_auth.py",
      "exit_code": 0,
      "duration_ms": 12430,
      "output_tail": "18 passed"
    }
  ],
  "all_passed": true
}
```

Rules:

- commands run in `/workspace` after the Agent step and before final Goal decision processing;
- commands execute in the order stored in the Goal contract;
- each command has a timeout;
- output persisted in the JSON is bounded to a sanitized tail;
- command failure does not erase Task changes;
- a `complete` decision is rejected unless every command exits `0`;
- an empty verification command list is invalid when starting a GoalRun.

`goal-decision.json` and `goal-verification.json` are added to the existing runtime archive file
list when present.

---

## Architecture

```mermaid
flowchart TD
    A["User starts GoalRun"] --> B["Goal API validates and creates step 1 atomically"]
    B --> C["Existing TaskScheduler runs Goal Task"]
    C --> D["Worker executes in Issue workspace"]
    D --> E["Persist Goal decision and verification artifacts"]
    E --> F["GoalCoordinator claims completed step"]
    F --> G{"Decision"}
    G -->|continue| H["Create next Goal Task exactly once"]
    H --> C
    G -->|approval_required| I["Persist approval and wait"]
    I -->|approve or reject| H
    G -->|blocked| J["Wait for resume guidance"]
    J --> H
    G -->|complete + verification passed| K["Complete Goal and move Issue to review"]
```

### Component responsibilities

| Component | Responsibility |
|-----------|----------------|
| Goal API | Start, read, pause, resume, cancel, and resolve approvals |
| Goal creation service | Validate invariants and create GoalRun/Task/snapshots atomically |
| TaskScheduler | Schedule Goal Tasks exactly like ordinary Tasks |
| Worker runtime | Materialize Goal context and persist decision/verification artifacts |
| GoalCoordinator | Durably process terminal steps and advance Goal state |
| Task status helper | Preserve Issue `in_progress` while Goal is unfinished |
| Notification service | Notify only on approval, block, failure, cancellation, and completion |
| Frontend | Goal start form, status card, approval panel, controls, and history labels |

The GoalCoordinator runs in the scheduler service process but remains a separate module and loop.
It must not add Goal-specific branching to the Task priority queue.

---

## Data Model

### `goal_runs`

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer PK | GoalRun ID |
| `issue_id` | Integer FK | Parent Issue, cascade on Issue deletion |
| `status` | String(32) | GoalRun lifecycle status |
| `objective` | Text | Immutable objective snapshot |
| `scope` | Text | Immutable allowed-scope snapshot |
| `success_criteria` | JSON list | Immutable success conditions |
| `constraints` | JSON list | Immutable constraints |
| `verification_commands` | JSON list | Immutable shell verification commands |
| `provider_id` | Integer nullable FK | Provider pinned at Goal start |
| `worker_profile_id` | Integer nullable FK | Worker Profile identity pinned at Goal start |
| `initial_task_id` | Integer nullable FK | First Goal Task |
| `current_task_id` | Integer nullable FK | Current/latest Goal Task |
| `last_processed_task_id` | Integer nullable FK | Idempotency checkpoint |
| `current_step_index` | Integer | Current Goal step |
| `priority` | Integer | Priority used by every Goal Task |
| `initial_session_mode` | String(16) | `continue` or `fresh` for step 1 |
| `progress_summary` | Text nullable | Bounded cumulative progress |
| `last_decision` | String nullable | Last normalized decision |
| `blocked_reason` | String nullable | Stable machine-readable reason |
| `blocked_detail` | Text nullable | User-readable blocker |
| `resume_guidance` | Text nullable | One-shot guidance for next step |
| `initiator_user_id` | Integer nullable FK | Goal creator |
| `initiator_username` | String nullable | Audit/display fallback |
| `started_at` | DateTime | Start time |
| `completed_at` | DateTime nullable | Terminal completion time |
| `cancelled_at` | DateTime nullable | Cancellation time |
| `created_at` | DateTime | Creation time |
| `updated_at` | DateTime | Last update time |

Partial unique index:

```text
unique(issue_id)
where status in ('active', 'waiting_approval', 'paused', 'blocked')
```

This is the authoritative one-unfinished-Goal-per-Issue invariant.

### `goal_approval_requests`

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer PK | Approval request ID |
| `goal_run_id` | Integer FK | Parent GoalRun |
| `task_id` | Integer FK | Goal Task that requested approval |
| `kind` | String(32) | `risk_operation` or `scope_expansion` |
| `status` | String(16) | `pending`, `approved`, `rejected`, or `cancelled` |
| `title` | String(255) | Short title |
| `reason` | Text | Why approval is needed |
| `proposed_action` | Text | Exact proposed action |
| `current_scope` | Text nullable | Current scope |
| `requested_scope` | Text nullable | Requested additional scope |
| `risk_detail` | Text nullable | Risk/reversibility details |
| `resolution_comment` | Text nullable | User response |
| `requested_at` | DateTime | Request time |
| `resolved_at` | DateTime nullable | Resolution time |
| `resolved_by_user_id` | Integer nullable FK | Resolving operator |

Only one `pending` approval may exist for one GoalRun.

### `tasks` additions

| Column | Type | Description |
|--------|------|-------------|
| `goal_run_id` | Integer nullable FK | Owning GoalRun |
| `goal_step_index` | Integer nullable | One-based serial step |
| `goal_outcome` | String nullable | Normalized Goal decision |
| `goal_decision` | JSON nullable | Sanitized normalized decision |
| `goal_verification` | JSON nullable | Sanitized bounded verification result |
| `goal_artifacts_finalized_at` | DateTime nullable | Coordinator readiness marker |

Unique constraint:

```text
unique(goal_run_id, goal_step_index)
```

Multiple ordinary Tasks remain valid because both values are null.

Goal Task trigger sources:

```text
goal_initial
goal_continue
goal_resume
goal_approval
```

The trigger source describes why the Task was created; `goal_run_id` and `goal_step_index` provide
the durable lineage.

### Migration

Add one migration after the current Alembic head:

```text
059_serial_goal_mode.py
```

The migration creates Goal tables, Task columns, foreign keys, indexes, and constraints. Existing
Issues and Tasks require no backfill.

---

## Coordinator and Idempotency

### Durable scan

The GoalCoordinator periodically selects GoalRuns that:

- are `active`;
- have a terminal current Task;
- have finalized Goal artifacts or a terminal pre-container failure;
- have `current_task_id != last_processed_task_id`.

Rows are claimed with `SELECT ... FOR UPDATE SKIP LOCKED`.

### Atomic continuation

For `continue`, one transaction:

1. Revalidates Goal status and current Task.
2. Checks there is no active Task for the Issue.
3. Checks the system step limit.
4. Creates Task at `current_step_index + 1`.
5. Clones the pinned Goal runtime snapshot.
6. Renders and stores the continuation prompt.
7. Updates `current_task_id`, `current_step_index`, progress, and `last_processed_task_id`.
8. Commits.

The `(goal_run_id, goal_step_index)` unique constraint is the final duplicate-creation guard.

### Crash cases

| Crash point | Recovery |
|-------------|----------|
| Before terminal Task result commit | Existing Worker/scheduler recovery owns the Task |
| After Task terminal commit, before Goal processing | Coordinator finds the unprocessed Task |
| During Goal processing before commit | Transaction rolls back; coordinator retries |
| After continuation commit | `last_processed_task_id` and unique step constraint prevent duplicate Task |
| After approval request commit | Goal remains `waiting_approval`; no Task is created |
| After approval resolution, before next Task commit | Resolution/continuation transaction rolls back together |

The coordinator must never depend on an in-memory timer or FastAPI background task for correctness.

---

## API Design

### Start GoalRun

```text
POST /api/issues/{issue_id}/goal-runs
```

Request:

```json
{
  "objective": "Migrate the authentication client to the new API.",
  "scope": "backend/app/auth and focused backend tests.",
  "success_criteria": [
    "Production code uses the new client.",
    "Focused regression tests pass."
  ],
  "constraints": [
    "Do not change external response shapes."
  ],
  "verification_commands": [
    "backend/.venv/bin/python -m pytest backend/tests/unit/test_auth.py",
    "git diff --check"
  ],
  "provider_id": null,
  "priority": 1,
  "session_mode": "continue"
}
```

Response includes the GoalRun and first Task summary.

### List Issue GoalRuns

```text
GET /api/issues/{issue_id}/goal-runs
```

Returns active and historical GoalRuns ordered newest first.

### Get GoalRun

```text
GET /api/goal-runs/{goal_run_id}
```

Returns:

- Goal contract;
- status and progress;
- current Task;
- ordered Goal Tasks;
- pending/latest approval;
- latest verification summary;
- available user actions.

### Pause

```text
POST /api/goal-runs/{goal_run_id}/pause
```

Pause does not cancel the current Task.

### Resume

```text
POST /api/goal-runs/{goal_run_id}/resume
```

Request:

```json
{
  "guidance": "Use the existing compatibility adapter; do not add a new dependency."
}
```

Guidance is required when resuming `blocked` and optional when resuming `paused`.

### Cancel

```text
POST /api/goal-runs/{goal_run_id}/cancel
```

Requests cancellation of the current Goal Task and prevents any later continuation.

### Resolve approval

```text
POST /api/goal-runs/{goal_run_id}/approvals/{approval_id}/resolve
```

Request:

```json
{
  "decision": "approved | rejected",
  "comment": "Approved only for the described migration."
}
```

Resolution and creation of the next Goal Task occur atomically.

No endpoint allows directly setting arbitrary GoalRun status.

---

## Authorization, Attribution, and Quotas

- Starting, pausing, resuming, cancelling, or resolving approval requires Issue operator
  permission.
- Read access follows existing project access.
- Automatically created Tasks use the GoalRun initiator for `initiator_user_id`, GitLab sudo
  attribution, notifications, and usage ledger ownership.
- Existing user Task/token quotas apply at Goal start, continuation creation, and scheduler
  pre-execution checks.
- If quota enforcement prevents a Goal Task from running, the Goal becomes `blocked` with the
  existing structured usage-limit detail.
- Approval resolution records the acting user even when they differ from the Goal initiator.
- Public Task creation APIs must reject client-supplied `goal_run_id`, step index, Goal outcome, or
  Goal trigger source. Only the Goal creation/coordinator services may set them.

---

## Frontend Design

### Issue detail placement

Add a compact Goal card above `IssueCurrentExecution`.

When no GoalRun is unfinished, the Issue header shows:

```text
Start Goal
```

The start drawer contains:

- objective;
- allowed scope;
- success criteria list;
- constraints list;
- verification command list;
- provider;
- priority;
- continue/fresh session choice.

The form explains that Goal mode runs serial Tasks automatically and requires verification commands.

### Active Goal card

Show:

- status;
- current step number;
- compact objective;
- progress summary;
- current Task link and status;
- latest verification result;
- started time;
- primary action required.

Actions:

| Status | Actions |
|--------|---------|
| `active` | Pause, Cancel |
| `waiting_approval` | Approve, Reject, Cancel |
| `paused` | Resume, Cancel |
| `blocked` | Resume with guidance, Cancel |
| terminal | View history |

Approval UI shows proposed action, reason, risk/scope detail, and a required confirmation before
approval.

### Manual Task controls

While a GoalRun is unfinished:

- disable the Issue "Create Task" action;
- explain which GoalRun currently owns automatic execution;
- keep Task history and current Task navigation available.

Task detail and Issue execution history show:

```text
Goal #42 · Step 3
```

and map the Goal trigger source to a localized label.

### Copy and density

The Goal card should be operational and compact. Do not duplicate the full Issue description or
full Task logs. Long objective, scope, and approval details use explicit expand/collapse or a detail
drawer.

Add keys to both English and Chinese locale files.

---

## Notifications

Intermediate Goal Task success should not emit the ordinary "delivery complete" notification.

Add Goal-level events:

```text
goal_waiting_approval
goal_blocked
goal_completed
goal_failed
goal_cancelled
```

`goal_waiting_approval` and `goal_blocked` are action-oriented and include a link to the Issue.
Goal completion includes final step count, verification summary, and MR link when available.

Existing Task failure logs and Task detail remain available even when the user receives only the
Goal-level notification.

---

## Compatibility with Existing Features

### Manual Tasks and retries

No behavior changes when an Issue has no unfinished GoalRun. Generic retry is unavailable for a
Goal Task; users resume the Goal instead so lineage and state remain consistent.

### CI auto-repair

CI auto-repair does not create a repair Task while a GoalRun is unfinished. It records/ignores the
event using an explicit reason such as:

```text
active_goal_run_exists
```

Goal completion does not wait for GitLab CI in the first version. Existing CI auto-repair may act
after the Goal becomes terminal and the Issue enters review.

### Workspace and Claude session

No workspace layout change is required. Goal Tasks reuse:

```text
issue repo   -> /workspace
issue Claude -> /home/codify/.claude
issue shared -> /opt/codify-issue-shared
```

Serial execution preserves the current single Issue session pointer.

### Worker Profile snapshots

Ordinary Tasks continue snapshotting the current Issue Worker Profile at Task creation. Goal
continuations instead clone the snapshot captured by the first Goal Task.

### Issue close and branch cleanup

Issue close is blocked while a GoalRun is unfinished. Cancelling the GoalRun does not automatically
close the Issue or delete its branch.

### Raw logs and archives

Goal artifacts are included in the existing Task runtime archive. Existing raw-log finalization
remains authoritative before the coordinator processes a terminal Task.

---

## Failure Handling

| Failure | Goal behavior |
|---------|---------------|
| Worker/container failure | `blocked`, retain Task error and workspace |
| Task cancelled | `paused`, require explicit resume |
| Missing Goal decision | `blocked`, do not infer continuation |
| Invalid Goal decision schema | `blocked`, show validation error |
| Verification command timeout | treat command as failed |
| Verification fails after `complete` | create continuation with failure evidence |
| Provider/Worker snapshot unavailable | `failed` before creating next Task |
| Usage limit exceeded | `blocked` with usage detail |
| Step safety limit reached | `blocked` with safety-limit reason |
| Duplicate coordinator processing | unique step constraint prevents duplicate Task |
| Approval rejected | create next step with rejection constraint |
| Notification failure | log and continue; state transition remains authoritative |

Repeated failed verification should not create unbounded Tasks. The system step limit is the final
fuse. A later version may add explicit no-progress detection.

---

## Testing

### Backend model and migration tests

- Alembic upgrade/downgrade succeeds from the current head.
- Existing Issues/Tasks require no backfill.
- Partial unique index prevents two unfinished GoalRuns for one Issue.
- Unique `(goal_run_id, goal_step_index)` prevents duplicate steps.
- Approval kind/status constraints reject unknown values.

### Goal API tests

- Start validates permissions, Issue status, active Tasks, active GoalRun, provider, Worker, and
  contract fields.
- Start creates GoalRun, first Task, snapshot, prompt, and Issue status atomically.
- Pause does not cancel a running Task.
- Resume requires guidance for blocked Goals.
- Cancel prevents later continuation and requests current Task cancellation.
- Approval approve/reject creates exactly one next step.
- Manual Task creation/retry/update is rejected while Goal is unfinished.
- Goal metadata cannot be injected through public Task APIs.

### Coordinator tests

- `continue` creates the next Task with the next step index.
- Continuation reuses provider, Worker snapshot, template, workspace, branch, and session.
- `complete` requires all verification commands to pass.
- Failed verification overrides `complete` and generates a continuation.
- `blocked` and `approval_required` create no next Task.
- Task failure, cancellation, invalid artifact, usage limit, and safety limit stop the loop.
- Reprocessing the same Task is idempotent.
- Concurrent coordinator instances cannot create duplicate Tasks.
- Crash/restart between Task completion and Goal processing resumes correctly.

### Worker/runtime tests

- Goal context is materialized only for Goal Tasks.
- Decision and verification artifacts are archived and sanitized.
- Verification commands execute in order with timeouts and bounded output.
- Missing/invalid decision is finalized explicitly.
- Intermediate Goal steps keep the MR in Draft.
- Final Goal completion removes Draft status through the existing delivery path.

### Issue status tests

- Intermediate Goal Task completion keeps Issue `in_progress`.
- Waiting approval, paused, and blocked Goal remain `in_progress`.
- Completed Goal moves Issue to `in_review`.
- Failed/cancelled Goal falls back to existing delivered/no-delivery behavior.
- Issue close rejects an unfinished Goal.

### Frontend tests

- Goal start form validates objective, scope, criteria, and verification commands.
- Goal card renders every status and primary action.
- Approval details and approve/reject flows are visible and permission-gated.
- Manual Task creation is disabled with a useful explanation.
- Task history displays Goal and step identity.
- Resume guidance is required for blocked Goals.
- English and Chinese copy stays aligned.

### End-to-end scenarios

1. Start Goal -> step 1 continues -> step 2 completes -> verification passes -> Issue enters review.
2. Step requests risky-operation approval -> approve -> next step completes.
3. Step requests scope expansion -> reject -> next step seeks in-scope alternative.
4. Step claims complete -> verification fails -> continuation fixes failure -> verification passes.
5. Scheduler restarts after step completion -> coordinator creates only one continuation.
6. User pauses during a running step -> step finishes -> no continuation until resume.
7. User cancels Goal -> current Task is cancelled -> no later Task is created.

---

## Rollout Plan

1. Add `goal_mode_enabled=false` and `goal_max_auto_steps=10` runtime settings.
2. Add migration, models, constraints, and serializers.
3. Add Goal APIs and creation service behind the feature flag.
4. Add Goal prompt/context and decision artifact persistence.
5. Add verification command execution and artifact persistence.
6. Add durable GoalCoordinator and idempotent continuation creation.
7. Integrate Issue status, MR Draft, Task mutation, CI auto-repair, and notification gates.
8. Add the compact Issue Goal card and start/approval/resume flows.
9. Enable internally and exercise restart, cancellation, malformed-artifact, and quota failures.
10. Review Goal completion accuracy and operational logs before enabling by default.

No parallel workspace or scheduler changes are included in this rollout.

---

## Expected Affected Files

Backend:

- `backend/alembic/versions/059_serial_goal_mode.py`
- `backend/app/models.py`
- `backend/app/config.py`
- `backend/app/api/config_runtime.py`
- `backend/app/api/goal_runs.py`
- `backend/app/api/goal_schemas.py`
- `backend/app/api/task_creation_service.py`
- `backend/app/api/task_action_routes.py`
- `backend/app/api/issues.py`
- `backend/app/core/goal_coordinator.py`
- `backend/app/core/goal_creation.py`
- `backend/app/core/goal_prompt.py`
- `backend/app/core/task_helpers.py`
- `backend/app/core/worker_runtime.py`
- `backend/app/core/worker_task_lifecycle.py`
- `backend/app/core/worker_task_artifacts.py`
- `backend/app/scheduler_service.py`
- Goal, scheduler, task, worker, notification, and migration tests

Worker:

- `deploy/worker-entrypoint/runtime.sh`
- `deploy/worker-entrypoint/main.sh`
- a focused Goal artifact/verification helper under `deploy/worker-entrypoint/`
- `backend/tests/unit/test_worker_coverage.py`

Frontend:

- `frontend/src/api/goalRuns.ts`
- `frontend/src/api/tasks.ts`
- `frontend/src/views/IssueView.vue`
- focused components under `frontend/src/components/issue-detail/`
- the existing runtime-settings panel for the feature flag and safety fuse
- `frontend/src/components/TaskMetadataPanel.vue`
- `frontend/src/i18n/messages/en.ts`
- `frontend/src/i18n/messages/zh-CN.ts`
- focused Vitest suites

The exact module split may change during implementation, but Goal coordination must remain
separate from the core Task scheduler.

---

## Cost Estimate

Assuming one active serial GoalRun per Issue, no parallelism, no Goal budget, and only the two
approval kinds in this document:

| Area | Estimate |
|------|---------:|
| Data model, migration, API, authorization | 2-3 person-days |
| Goal coordinator, state machine, and idempotency | 3-4 person-days |
| Prompt, decision artifact, and verification execution | 2-3 person-days |
| Issue status, MR, quota, CI, and notification integration | 1-2 person-days |
| Frontend Goal card, forms, approval, and controls | 2-3 person-days |
| Recovery, backend/frontend tests, and rollout hardening | 2-3 person-days |
| **Total** | **12-18 person-days** |

The main uncertainty is not Task creation; it is reliable artifact finalization, restart recovery,
and preventing existing Issue/MR completion behavior from firing between Goal steps.

---

## Risks and Mitigations

### Risk: Agent incorrectly claims completion

Mitigation: require verification commands and allow verification failure to override
`decision="complete"`.

### Risk: duplicate continuation after restart

Mitigation: row locking, `last_processed_task_id`, one transaction, and a unique Goal step
constraint.

### Risk: Issue or MR appears complete between Goal steps

Mitigation: make Issue status and MR Draft logic explicitly aware of unfinished GoalRuns.

### Risk: approval happens after the risky action

Mitigation: Goal prompt requires the Agent to stop before the action and describes approval as
single-use. Clearly document that v1 is a workflow gate rather than a tool-call security boundary.
Keep true authority constrained by container credentials and project access.

### Risk: Goal runs indefinitely without a budget

Mitigation: existing usage quotas plus the global `goal_max_auto_steps` safety fuse. Do not add
per-Goal budget UI or budget approval.

### Risk: runtime/profile edits change later steps

Mitigation: pin provider, Worker snapshot, and run-instruction template at Goal start, then clone
that snapshot for every continuation.

### Risk: manual Tasks race with Goal advancement

Mitigation: reject manual Task creation/mutation while a GoalRun is unfinished and preserve the
existing Issue execution lock.

### Risk: verification commands are expensive or unsafe

Mitigation: only Issue operators can start Goals; commands execute in the same authorized worker
boundary as normal Task commands, with timeouts and bounded persisted output.

---

## Acceptance Criteria

The first serial Goal mode is complete when:

1. An authorized user can start one GoalRun on an eligible Issue.
2. Goal contract fields are immutable and every Goal has at least one verification command.
3. Goal Tasks execute one at a time in the existing Issue workspace and branch.
4. A `continue` result creates exactly one next Task, including after service restart.
5. A Goal cannot complete until every verification command passes.
6. Only risky operations and scope expansion produce approval requests.
7. Approving or rejecting creates one audited continuation with the resolution context.
8. Pause stops future advancement without killing the current step; resume continues safely.
9. Cancel prevents all later continuation and requests cancellation of the current step.
10. Intermediate steps keep the Issue `in_progress` and MR in Draft.
11. Final completion moves the Issue to `in_review` and finalizes MR readiness.
12. Manual Tasks, retries, and CI auto-repair cannot race with an unfinished GoalRun.
13. Existing Issues without a GoalRun behave exactly as before.
14. No parallel subgoal, worktree, DAG, or Goal budget behavior is present.

## Deferred Follow-Ups

- Parallel subgoals using Git worktrees.
- Goal dependency DAGs and integration steps.
- Tool-call interception for hard approval enforcement.
- CI pipeline state as a completion verifier.
- Per-Goal token/cost budgets.
- Dynamic scope amendments without starting a new GoalRun.
- No-progress similarity detection beyond the step safety limit.
- Project-level Goal templates and default verification commands.
