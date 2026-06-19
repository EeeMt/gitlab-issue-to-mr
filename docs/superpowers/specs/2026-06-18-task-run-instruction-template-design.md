# Task Run Instruction Template Design

**Date:** 2026-06-18
**Status:** Draft

## Context

Codify currently stores the user's task request in `tasks.user_prompt`, passes it into the
worker container as `USER_PROMPT`, and lets `deploy/entrypoint.worker.sh` build the main
Claude prompt from hardcoded plan/execute shell templates.

CI auto-repair is a third prompt path: `backend/app/core/ci_failure_collector.py` creates an
execute task with a hardcoded repair request. Its run instruction also needs to be managed by
the application instead of being coupled to Python or worker code.

That means the main task prompt is split across product code and worker image code:

```text
Task.user_prompt
-> worker env USER_PROMPT
-> entrypoint.worker.sh plan/execute template
-> /tmp/claude_prompt.txt
-> ci-claude.sh
-> claude -p
```

This is hard to preview, audit, customize per task, or evolve without changing the worker
image. The desired direction is to move main task prompt assembly into the application layer
and let the worker consume a fully rendered prompt artifact.

System prompts are intentionally out of scope for this design. Provider-level system prompt
handling stays separate.

## Terminology

### Requirement Prompt

The user's business request for the task. This is the existing `tasks.user_prompt` and is what
the user sees as the task's request content.

UI label recommendation:

```text
需求
```

The existing reusable prompt templates in Config are used to fill this content. To avoid
confusion with the new feature, the product should gradually call them:

```text
需求模板
```

The backend table can remain `prompt_templates`.

### Run Instruction Template

The task-level template that wraps the requirement prompt and other context into the full
Claude user prompt for one run.

UI label recommendation:

```text
运行指令模板
```

This template is different from the existing requirement templates:

- Requirement templates help users write `user_prompt`.
- Run instruction templates tell Claude how to execute, plan, constrain output, and use context.

### Rendered Prompt

The final main prompt content passed to `claude -p` through stdin by `ci-claude.sh`.

```text
rendered_prompt = render(run_instruction_template_snapshot, task_context)
```

## Goals

1. Move main plan/execute prompt assembly out of `entrypoint.worker.sh`.
2. Make the default `execute`, default `plan`, and CI auto-repair run instruction templates
   editable in System Config.
3. Add task-level editing of the run instruction template anywhere the requirement prompt can
   be edited.
4. Let users fully control the final prompt by editing the template, including deleting all
   placeholders.
5. Persist a task-level template snapshot so later global default changes do not rewrite
   queued or historical task intent.
6. Persist the final rendered prompt, materialize it in the task runtime directory, and expose it
   to every user who can view the task.
7. Make the worker fail clearly if the rendered prompt artifact is missing, instead of falling
   back to a shell-side template.

## Non-Goals

- Changing provider-level system prompts or `APPEND_SYSTEM_PROMPT`.
- Moving commit-message, delivery-summary repair, or MR overall-summary prompts in the first
  implementation. Those are post-processing prompts, not the main task prompt.
- Creating a broad prompt-template marketplace.
- Adding arbitrary code execution in templates.
- Inlining large CI logs or previous task artifacts into the prompt by default.

## Product Design

### System Config

The Worker tab in System Config must expose a dedicated Run Instructions section with three
independent multiline editors:

```text
默认执行模式运行指令
默认规划模式运行指令
CI 自动修复运行指令
```

They are persisted through the existing runtime `system_config` mechanism as:

```text
default_execute_run_instruction_template
default_plan_run_instruction_template
ci_auto_repair_run_instruction_template
```

Only administrators can change these values. Each editor provides the same placeholder reference,
validation, and built-in-default reset action as the task editor. Updating System Config affects
only tasks created afterward; every task stores its own template snapshot.

The task drawer defaults endpoint remains readable by normal task operators because they must see
and edit the selected template. It exposes only the run instruction defaults, not unrelated System
Config values.

### Create Task Advanced Section

`TaskFormDrawer.vue` should add a collapsed advanced section after task mode selection.

Default collapsed state:

```text
高级
```

Inside it:

```text
运行指令模板
```

The editor loads the default run instruction template for the selected task mode:

- `execute` mode uses the execute default.
- `plan` mode uses the plan default.

The section should provide:

- a multiline editor for the current task's run instruction template
- compact, clickable placeholder chips that insert at the cursor
- a reset action: `恢复默认运行指令`
- a preview action or inline collapsed preview: `最终提示词预览`
- a neutral note when `{{user_prompt}}` is absent: `当前运行指令不会自动包含需求内容。`

The default task-creation path remains simple: if the user does not open or edit advanced
settings, Codify still sends the default run instruction template snapshot with the task.

The same editor is present when editing a pending or queued task. The authorization and lifecycle
rule is deliberately identical to `user_prompt`: if a user can edit the requirement prompt, they
can edit the run instruction template; otherwise both are read-only.

### Task Mode Switching

When the user switches task mode in either the create or edit drawer:

1. If the run instruction template has not been edited, replace it with the new mode's default.
2. If it has been edited, ask before replacing:

```text
切换任务模式会替换当前运行指令模板，是否使用新模式的默认模板？
```

If the user declines, keep the edited template and only change `task_mode`.

This lets advanced users intentionally run an execute-style instruction under plan mode, or
the reverse, while making accidental overwrites explicit.

Dirty state is frontend-only and means the template was edited in the current drawer session:

- Create mode starts from the effective default for the selected mode.
- Edit mode starts from the task's stored snapshot, so later System Config changes do not
  incorrectly label an older snapshot as custom.
- `恢复默认运行指令` loads the current effective default and marks the form as changed.

### Full Prompt Control

There is no separate `full_prompt_override` switch.

Full control is achieved naturally:

```text
User edits run instruction template
-> deletes {{user_prompt}} or any other placeholder
-> rendered prompt contains exactly what remains after placeholder rendering
```

Deleting `{{user_prompt}}` is valid. It means the final prompt no longer includes the
requirement prompt.

### Task Detail Display

Keep the existing prompt card and add a compact switch in its header:

```text
用户提示词 | 最终运行提示词
```

`用户提示词` shows `user_prompt`; `最终运行提示词` shows the persisted `rendered_prompt`. The
switch is a viewing control, not an authorization control.

Task detail is readable by every user with project access, while task mutations are restricted to
the administrator or task initiator. `rendered_prompt` follows the same visibility rule as
`user_prompt`: every user who can view the task can view the final prompt. Do not redact or hide it
only because the viewer cannot operate on the task.

New tasks have `rendered_prompt` generated during creation, so pending tasks also show the exact
content that will be materialized for execution. Historical tasks with no stored rendered prompt
show `暂无最终运行提示词` rather than reconstructing an unverifiable value from current defaults.

## Built-In Default Template Content

System Config reset actions restore the following application-owned defaults.

Built-in execute default:

```md
请直接完成下面的需求，不要先输出规划或步骤清单。

需求:
{{user_prompt}}

上下文:
- 仓库路径: {{project_path}}

要求:
1. 直接检查代码库并实施修改。
2. 仅在当前仓库内工作，优先做精确修改，不要引入无关改动。
3. 完成后运行相关验证命令；如果仓库里没有对应命令，就明确说明。
4. 最终输出简短执行摘要，至少包含：
    - 做了什么，为什么这么做
    - 运行了哪些验证
5. 如果执行摘要需要表达流程、架构、时序、状态转换等图表，必须使用 Markdown 的 mermaid fenced code block（语言标记为 mermaid），不要使用 ASCII 图、图片链接或其它图表格式。
6. 不要描述"未跟踪文件""待提交""可按需提交"这类提交前状态，默认以已经完成并准备提交的口吻总结结果。
7. 不要要求人工确认，除非你真的被阻塞。
```

Built-in plan default:

```md
请分析下面的需求，给出详细的实施方案。不要修改任何文件，不要执行任何写操作（包括 git commit、git push、创建 MR）。

需求:
{{user_prompt}}

上下文:
- 仓库路径: {{project_path}}

要求:
1. 检查代码库，理解现有结构和约束。
2. 给出清晰、可操作的实施方案，包含：
    - 需要新增或修改哪些文件，以及具体的改动思路
    - 为什么这么设计
    - 潜在风险或需要注意的地方
3. 不要修改任何文件，不要执行任何写操作。
4. 如果方案需要表达流程、架构、时序、状态转换等图表，必须使用 Markdown 的 mermaid fenced code block（语言标记为 mermaid），不要使用 ASCII 图、图片链接或其它图表格式。
5. 不要要求人工确认。
```

Built-in CI auto-repair default:

```md
请直接修复「{{issue_title}}」当前 MR 的 GitLab CI 失败，不要先输出规划或步骤清单。

上下文:
- 仓库路径: {{project_path}}
- CI 失败上下文目录: {{ci_failure_context_path}}
- Pipeline: {{ci_failure_context_path}}/pipeline.json
- 失败 Jobs: {{ci_failure_context_path}}/failed-jobs.json
- Job 日志目录: {{ci_failure_context_path}}/jobs/

要求:
1. 先读取 pipeline、失败 job 元数据和根因 job 日志，再修改代码。
2. 只修复当前 CI 失败，不要扩大原始需求范围，不要修改无关文件。
3. 仅在当前仓库内工作，优先做精确修改，不要引入无关改动。
4. 完成后运行与失败项直接相关的验证；如果仓库里没有对应命令，就明确说明。
5. 不要执行 git commit 或 git push，提交和推送由 worker 收尾流程处理。
6. 最终输出简短执行摘要，至少包含：
    - 修复了什么，为什么这么修复
    - 运行了哪些验证
7. 如果执行摘要需要表达流程、架构、时序、状态转换等图表，必须使用 Markdown 的 mermaid fenced code block（语言标记为 mermaid），不要使用 ASCII 图、图片链接或其它图表格式。
8. 不要描述"未跟踪文件""待提交""可按需提交"这类提交前状态，默认以已经完成并准备提交的口吻总结结果。
9. 不要要求人工确认，除非你真的被阻塞。
```

CI auto-repair tasks always snapshot `ci_auto_repair_run_instruction_template`, regardless of the
normal execute default. They still use `task_mode=execute` and `trigger_source=ci_auto_repair`.
This built-in default preserves the current generic execute constraints and the existing
`REPAIR_PROMPT` semantics in one complete prompt. The task's `user_prompt` is not a template input
because no user fills it during automatic task creation.

`tasks.user_prompt` is currently non-null and is reused by task lists and detail UI. CI task
creation can therefore keep a fixed, system-generated summary such as `修复当前 MR 的 CI 失败` for
compatibility, but the CI run instruction template must not include `{{user_prompt}}`. The complete
operational instruction lives in the CI template only.

## Placeholder Model

Use a small allowlist renderer. Do not introduce Jinja, JavaScript evaluation, conditionals, or
loops.

Supported syntax:

```text
{{name}}
{{ name }}
```

The canonical UI insertion format should be `{{name}}`.

MVP placeholders:

| Placeholder | Meaning |
|-------------|---------|
| `{{user_prompt}}` | The task requirement prompt saved in `tasks.user_prompt` |
| `{{issue_title}}` | Parent Issue title |
| `{{project_path}}` | GitLab namespace/project path |
| `{{branch_name}}` | Working branch name |
| `{{base_branch}}` | Issue base branch, empty when not set |
| `{{target_branch}}` | MR target branch, empty in no-MR mode |
| `{{task_mode}}` | `execute` or `plan` |
| `{{require_changes}}` | `true` or `false` |

File-backed context placeholders use stable container paths instead of inlining large bodies:

| Placeholder | Meaning |
|-------------|---------|
| `{{previous_task_summaries_path}}` | Path to `previous-task-summaries.md` if present |
| `{{ci_failure_context_path}}` | `/tmp/codify-runtime/ci-failure` for CI auto-repair tasks |

Rendering rules:

- Unknown placeholders are rejected with a validation error.
- Known placeholders with no value render as an empty string.
- A template with no placeholders is valid.
- A template that omits `{{user_prompt}}` is valid.
- The renderer preserves all non-placeholder text exactly.

## Data Model

Add task-level prompt assembly fields.

```text
tasks.run_instruction_template        TEXT NULL
tasks.rendered_prompt                 TEXT NULL
tasks.rendered_prompt_at              DATETIME NULL
```

`run_instruction_template` is the task-level snapshot. It is nullable only for migration
compatibility with historical terminal tasks. Application code must create every new task with a
non-null snapshot.

Do not add `run_instruction_template_source`. The exact snapshot is authoritative, while a source
enum is redundant and can drift from the actual content. Existing fields already describe the
selection path where it matters:

- `task_mode` distinguishes normal plan and execute tasks.
- `trigger_source=ci_auto_repair` identifies the dedicated CI template path.
- `retry_source_task_id` identifies inherited retry snapshots.
- UI dirty state is derived from the editor's initial snapshot, not persisted provenance.

If strict template provenance or revision reporting is needed later, add a versioned template
entity and store its revision ID. A free-form or enum source field is not a reliable substitute.

`rendered_prompt` is the exact final prompt content generated from the snapshot during task
creation or an allowed task edit. Worker preparation materializes this persisted value without
rendering it again. `rendered_prompt_at` records the latest successful render time.

Migration behavior:

- Existing terminal tasks can keep both `run_instruction_template = NULL` and
  `rendered_prompt = NULL`; do not manufacture an unverifiable historical snapshot.
- Existing pending or queued tasks should receive a snapshot based on `trigger_source` first, then
  `task_mode`, and should be rendered during migration or before the scheduler is resumed.
- New task creation must enforce non-null `run_instruction_template` in application code.
- New task creation and permitted edits must atomically persist the corresponding
  `rendered_prompt`.
- Worker launch must require a rendered prompt file; no shell-side fallback template is allowed.

## API Contract

### Get Defaults

Add an endpoint for the task drawer:

```http
GET /api/tasks/run-instruction-template-defaults
```

Response:

```json
{
  "execute": {
    "content": "...",
    "available_placeholders": ["user_prompt", "project_path"]
  },
  "plan": {
    "content": "...",
    "available_placeholders": ["user_prompt", "project_path"]
  }
}
```

### Create Task

Extend `POST /api/tasks`:

```json
{
  "issue_id": 5,
  "user_prompt": "实现登录页",
  "provider_id": 2,
  "task_mode": "execute",
  "run_instruction_template": "请完成：{{user_prompt}}"
}
```

Server behavior:

- If `run_instruction_template` is omitted, use the default for `task_mode`.
- If provided, validate unknown placeholders.
- Persist the exact submitted template as the task snapshot.
- Render and persist `rendered_prompt` in the same creation transaction.

CI auto-repair creation is server-owned and does not accept a client template or user-authored
prompt. It snapshots the effective `ci_auto_repair_run_instruction_template` and renders it through
the same service used by normal task creation. Its system-generated `user_prompt` is display
metadata and is not interpolated into the CI template.

### Update Task

Extend `PATCH /api/tasks/{task_id}` with:

```json
{
  "user_prompt": "更新后的需求",
  "run_instruction_template": "请完成：{{user_prompt}}"
}
```

The existing pending/queued status and operator authorization checks apply to both fields. If
either `user_prompt`, `run_instruction_template`, `task_mode`, or another render-context field
changes, validate and regenerate `rendered_prompt` atomically. There must not be a state where the
saved requirement and final prompt represent different edits.

### Task Response

Task detail responses should include:

```ts
run_instruction_template?: string
rendered_prompt?: string | null
rendered_prompt_at?: string | null
```

List responses can omit `run_instruction_template` and `rendered_prompt` to avoid large payloads.

### Preview Render

For unsaved advanced-editor changes, add:

```http
POST /api/tasks/render-run-instruction-template-preview
```

Request:

```json
{
  "issue_id": 5,
  "task_mode": "execute",
  "user_prompt": "实现登录页",
  "run_instruction_template": "请完成：{{user_prompt}}"
}
```

Response:

```json
{
  "rendered_prompt": "请完成：实现登录页",
  "used_placeholders": ["user_prompt"],
  "unused_known_placeholders": ["issue_title", "project_path"]
}
```

The preview endpoint should use the same renderer as task creation and update. It is only a preview
of unsaved edits; saved tasks use their persisted `rendered_prompt` in task detail and at runtime.

## Backend Execution Flow

Add a focused prompt-rendering module:

```text
backend/app/core/task_prompt.py
```

Responsibilities:

1. Provide built-in execute, plan, and CI auto-repair templates and resolve effective configured
   values.
2. Extract placeholders.
3. Validate placeholders against the allowlist.
4. Build render context from task, Issue, project metadata, and stable container artifact paths.
5. Render the final prompt.

Template selection is centralized in the same module or adjacent service:

```text
retry -> inherit source task snapshot
else trigger_source == ci_auto_repair -> effective CI auto-repair template
else task_mode == plan -> effective plan template
else -> effective execute template
```

Task creation/update flow:

```text
load task + issue + project context
-> select or validate task.run_instruction_template
-> render prompt
-> persist template snapshot + rendered_prompt + rendered_prompt_at atomically
```

Worker preparation flow changes:

```text
load task + issue
-> require task.rendered_prompt
-> write runtime/task-prompt.md
-> create worker container
```

The runtime file should live in the task runtime directory that is already mounted into the
container as `/tmp/codify-runtime`.

Recommended file:

```text
{runtime_path}/task-prompt.md
```

Container path:

```text
/tmp/codify-runtime/task-prompt.md
```

The container env should include:

```text
CODIFY_TASK_PROMPT_FILE=/tmp/codify-runtime/task-prompt.md
```

Keep `USER_PROMPT` available for metadata, MR descriptions, commit-message prompts, and existing
post-processing paths. It is no longer used to build the main Claude prompt in the worker.

`task-prompt.md` is therefore a runtime artifact containing the exact persisted final prompt. It
lives beside `console.log`, `task-metadata.json`, and other per-task artifacts under:

```text
{worker_workspace_host_path}/project-{project_id}/issue-{issue_id}/runtime/task-{task_id}/task-prompt.md
```

The precise host prefix follows `build_issue_workspace_paths`; code should use its returned
`runtime_path` rather than reconstructing the path.

## Worker Changes

`deploy/entrypoint.worker.sh` should stop containing the main execute/plan prompt templates.

Required behavior:

```bash
CODIFY_TASK_PROMPT_FILE="${CODIFY_TASK_PROMPT_FILE:?Missing CODIFY_TASK_PROMPT_FILE}"

if [ ! -s "${CODIFY_TASK_PROMPT_FILE}" ]; then
    echo "Rendered task prompt file is missing or empty: ${CODIFY_TASK_PROMPT_FILE}"
    exit 1
fi

cp "${CODIFY_TASK_PROMPT_FILE}" /tmp/claude_prompt.txt
```

Then keep the existing `ci-claude.sh` invocation:

```text
PROMPT_FILE=/tmp/claude_prompt.txt /usr/local/bin/ci-claude.sh
```

There is intentionally no fallback to `USER_PROMPT` and no shell-side plan/execute template.

The worker can still use `TASK_MODE` for mode-specific post-processing behavior, such as plan
metadata handling and change requirements.

## Retry And Follow-Up Behavior

Retry should inherit the source task's `run_instruction_template` snapshot and render a new final
prompt for the new task's context.

```text
original task -> retry task
copy run_instruction_template
render and persist a new rendered_prompt during retry creation
```

Rationale:

- The retry should reproduce the user's original instruction intent.
- The rendered prompt may legitimately change for dynamic placeholders such as branch or context
  paths.

Follow-up task creation should use the current default template unless the UI explicitly supports
copying the previous run instruction template.

## Validation And Limits

Recommended limits:

```text
run_instruction_template <= 50000 chars
rendered_prompt <= 100000 chars
```

Validation:

- Reject unknown placeholders.
- Reject empty final rendered prompt.
- Accept a template without placeholders.
- Accept deletion of `{{user_prompt}}`.
- Normalize line endings to `\n`.
- Do not log full rendered prompts by default.

If preview rendering fails, show the validation error in the advanced section without blocking
editing until submit.

If submit rendering fails, return `422`.

If persisted `rendered_prompt` is missing or empty, or `task-prompt.md` cannot be materialized,
mark the task failed before container creation with a clear error message.

## Security And Audit

- Do not place the rendered prompt in environment variables.
- Do not print the full rendered prompt in worker logs.
- Return `rendered_prompt` under the same project-read access rule as `user_prompt`; all task
  viewers can see both.
- Restrict editing `run_instruction_template` with the same administrator/initiator, pending/queued
  checks used for editing `user_prompt`.
- Store the runtime prompt file only inside the existing per-task runtime directory. Runtime
  archive/download endpoints keep their existing task/project access checks.
- Future placeholders for CI or task artifacts should prefer paths over raw inlined logs.
- Sanitization remains required for runtime logs and task logs, but prompt rendering should not
  rely on log sanitization as a safety mechanism.

## Migration Plan

1. Add the three template settings to `Settings`, `PERSISTED_CONFIG_TYPES`, runtime config API
   schemas, and the administrator System Config UI.
2. Add the backend renderer and unit tests.
3. Add nullable task snapshot/rendered-prompt columns and migration; do not add a source column.
4. Seed built-in execute/plan templates from current `entrypoint.worker.sh` content and seed the CI
   template from the current execute template plus `REPAIR_PROMPT` semantics.
5. Backfill and render pending/queued tasks; leave historical terminal task prompt fields null.
6. Extend create, edit, retry, and CI auto-repair creation to snapshot the selected template and
   persist `rendered_prompt` atomically.
7. Write persisted `rendered_prompt` to `task-prompt.md` during worker preparation.
8. Change `entrypoint.worker.sh` to require `CODIFY_TASK_PROMPT_FILE` and remove main prompt
   template generation.
9. Add advanced editor and preview support to both create and edit modes of
   `TaskFormDrawer.vue`.
10. Add the `用户提示词 | 最终运行提示词` switch to the existing task prompt card.
11. Remove frontend/backend assumptions that the worker owns main prompt text.

Because there is no worker fallback, deploy backend and worker changes as one compatible release.
The scheduler should not start tasks with the new worker image unless backend rendering and
runtime file materialization are deployed.

## Test Plan

Backend:

- Unit tests for placeholder extraction and rendering.
- Unit tests that unknown placeholders return validation errors.
- Unit tests that templates without `{{user_prompt}}` are accepted.
- Runtime config tests for reading, updating, resetting, and validating all three templates.
- API tests for create task with default, custom, and invalid run instruction templates.
- Update tests verifying requirement/template edits atomically regenerate `rendered_prompt` and
  use the existing task edit authorization.
- Retry tests verifying template snapshot inheritance.
- CI auto-repair tests verifying the dedicated configured template is snapshotted instead of the
  normal execute template and does not depend on `user_prompt`.
- Worker preparation tests verifying `task-prompt.md` is written before container creation.
- Migration tests verifying terminal tasks may remain null while pending/queued tasks are
  backfilled.

Worker:

- `bash -n deploy/entrypoint.worker.sh`
- Unit coverage that `entrypoint.worker.sh` no longer contains the main plan/execute prompt text.
- Unit coverage that missing or empty `CODIFY_TASK_PROMPT_FILE` fails clearly.
- Unit coverage that `PROMPT_FILE=/tmp/claude_prompt.txt` still reaches `ci-claude.sh`.

Frontend:

- System Config tests for the execute, plan, and CI auto-repair template editors.
- `TaskFormDrawer.vue` tests for advanced collapsed state in create and edit modes.
- Mode switch tests for untouched vs edited run instruction template.
- Placeholder insertion tests.
- Preview render success/error tests.
- Task detail tests for switching the existing prompt card between user prompt and final prompt.
- Visibility tests proving non-operators with task read access can view `rendered_prompt` but cannot
  edit either prompt.
- i18n coverage for both `en.ts` and `zh-CN.ts`.

Integration:

- Create execute task with default template and verify the runtime prompt file content.
- Create plan task with custom template and no `{{user_prompt}}`, verify Claude receives only the
  rendered custom content.
- Create CI auto-repair task and verify it uses the configured CI template without interpolating
  its system-generated `user_prompt`.
- Edit a pending task's requirement and run instruction together, then verify task detail and the
  runtime file show the newly rendered value.
- Retry a task and verify the retry inherits the original template snapshot.
