# Task Run Instruction Template Design

**Date:** 2026-06-18
**Status:** Draft

## Context

Codify currently stores the user's task request in `tasks.user_prompt`, passes it into the
worker container as `USER_PROMPT`, and lets `deploy/entrypoint.worker.sh` build the main
Claude prompt from hardcoded plan/execute shell templates.

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
2. Add task-level editing of the run instruction template in the create-task advanced section.
3. Keep separate default templates for `execute` and `plan` modes.
4. Let users fully control the final prompt by editing the template, including deleting all
   placeholders.
5. Persist a task-level template snapshot so later global default changes do not rewrite
   queued or historical task intent.
6. Persist or expose the final rendered prompt for debugging and audit.
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
- a small placeholder reference list
- a reset action: `恢复默认运行指令`
- a preview action or inline collapsed preview: `最终提示词预览`

The default task-creation path remains simple: if the user does not open or edit advanced
settings, Codify still sends the default run instruction template snapshot with the task.

### Task Mode Switching

When the user switches task mode:

1. If the run instruction template has not been edited, replace it with the new mode's default.
2. If it has been edited, ask before replacing:

```text
切换任务模式会替换当前运行指令模板，是否使用新模式的默认模板？
```

If the user declines, keep the edited template and only change `task_mode`.

This lets advanced users intentionally run an execute-style instruction under plan mode, or
the reverse, while making accidental overwrites explicit.

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

Task detail should continue showing `user_prompt` as the task request.

For operators or users with task access, add a collapsed section:

```text
最终运行提示词
```

This section shows `rendered_prompt` after it has been generated. Pending tasks that have not
started yet can show a server-rendered preview from the template snapshot.

## Default Templates

Default templates should be owned by the application, not the worker image.

First implementation can seed two defaults from the current shell templates:

```text
default_execute_run_instruction_template
default_plan_run_instruction_template
```

Recommended execute default:

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

Recommended plan default:

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

Admin-level editing of these defaults can be added later under Config. The task-level snapshot
design does not depend on whether defaults are code constants or runtime config values.

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
| `{{issue_title}}` | Issue title, empty for manual tasks without an issue |
| `{{project_path}}` | GitLab namespace/project path |
| `{{branch_name}}` | Working branch name |
| `{{base_branch}}` | Issue base branch, empty when not set |
| `{{target_branch}}` | MR target branch, empty in no-MR mode |
| `{{task_mode}}` | `execute` or `plan` |
| `{{require_changes}}` | `true` or `false` |

Future placeholders can point to files instead of inlining large bodies:

| Placeholder | Meaning |
|-------------|---------|
| `{{previous_task_summaries_path}}` | Path to `previous-task-summaries.md` if present |
| `{{ci_failure_context_path}}` | Path to the materialized CI failure bundle |

Rendering rules:

- Unknown placeholders are rejected with a validation error.
- Known placeholders with no value render as an empty string.
- A template with no placeholders is valid.
- A template that omits `{{user_prompt}}` is valid.
- The renderer preserves all non-placeholder text exactly.

## Data Model

Add task-level prompt assembly fields.

```text
tasks.run_instruction_template        TEXT
tasks.run_instruction_template_source VARCHAR(32)
tasks.rendered_prompt                 TEXT NULL
tasks.rendered_prompt_at              DATETIME NULL
```

`run_instruction_template` is the task-level snapshot. It should be created with every new task.

`run_instruction_template_source` describes how the snapshot was produced:

```text
default_execute
default_plan
custom_execute
custom_plan
retry_inherited
system_generated
```

`rendered_prompt` is the final prompt content generated from the snapshot. It can be null before
execution, then populated during worker preparation.

Migration behavior:

- Existing historical tasks can keep `rendered_prompt = NULL`.
- Existing pending or queued tasks should receive a snapshot based on their `task_mode`.
- New task creation must always set `run_instruction_template`.
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
    "source": "default_execute",
    "available_placeholders": ["user_prompt", "project_path"]
  },
  "plan": {
    "content": "...",
    "source": "default_plan",
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
  "run_instruction_template": "请完成：{{user_prompt}}",
  "run_instruction_template_source": "custom_execute"
}
```

Server behavior:

- If `run_instruction_template` is omitted, use the default for `task_mode`.
- If provided, validate unknown placeholders.
- Persist the exact submitted template as the task snapshot.
- Derive `run_instruction_template_source` server-side if the client omits it.

### Task Response

Task detail responses should include:

```ts
run_instruction_template?: string
run_instruction_template_source?: string
rendered_prompt?: string | null
rendered_prompt_at?: string | null
```

List responses can omit `run_instruction_template` and `rendered_prompt` to avoid large payloads.

### Preview Render

For the advanced editor, add:

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

The preview endpoint should use the same renderer as worker preparation.

## Backend Execution Flow

Add a focused prompt-rendering module:

```text
backend/app/core/task_prompt.py
```

Responsibilities:

1. Provide execute/plan default templates.
2. Extract placeholders.
3. Validate placeholders against the allowlist.
4. Build render context from task, issue, project metadata, provider-independent settings, and
   worker preparation data.
5. Render the final prompt.

Worker preparation flow changes:

```text
load task + issue
-> ensure task.run_instruction_template exists
-> render prompt from task snapshot
-> persist tasks.rendered_prompt + rendered_prompt_at
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

Retry should inherit the source task's `run_instruction_template` snapshot by default.

```text
original task -> retry task
copy run_instruction_template
copy source as retry_inherited or preserve original source with retry metadata
render again at execution time
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

If execution-time rendering fails, mark the task failed before container creation with a clear
error message.

## UI Details

### Avoid Naming Collision

Use separate labels:

| Concept | Suggested Chinese UI Label |
|---------|----------------------------|
| Existing reusable prompt templates | 需求模板 |
| Requirement prompt editor | 需求 |
| New advanced wrapper template | 运行指令模板 |
| Final rendered prompt | 最终运行提示词 |

### Placeholder Reference

The advanced editor should show compact placeholder chips or a small reference table.

Clicking a placeholder inserts it at the cursor position.

The UI should not require `{{user_prompt}}` to be present. Instead, if the template does not
include it, show a neutral note:

```text
当前运行指令不会自动包含需求内容。
```

This is informational, not an error.

### Dirty State

Track whether the run instruction template has diverged from the current mode default.

Use that dirty state for:

- task mode switching confirmation
- showing `已自定义`
- enabling `恢复默认运行指令`

## Security And Audit

- Do not place the rendered prompt in environment variables.
- Do not print the full rendered prompt in worker logs.
- Store the rendered prompt only where existing task access rules already allow viewing task
  content.
- Future placeholders for CI or task artifacts should prefer paths over raw inlined logs.
- Sanitization remains required for runtime logs and task logs, but prompt rendering should not
  rely on log sanitization as a safety mechanism.

## Migration Plan

1. Add backend renderer and unit tests.
2. Add task columns and migration.
3. Seed default execute/plan templates from current `entrypoint.worker.sh` content.
4. Extend create/retry task APIs to snapshot `run_instruction_template`.
5. Render and write `task-prompt.md` during worker preparation.
6. Change `entrypoint.worker.sh` to require `CODIFY_TASK_PROMPT_FILE` and remove main prompt
   template generation.
7. Add advanced editor and preview support to `TaskFormDrawer.vue`.
8. Add task detail display for `rendered_prompt`.
9. Remove frontend/backend assumptions that the worker owns main prompt text.

Because there is no worker fallback, deploy backend and worker changes as one compatible release.
The scheduler should not start tasks with the new worker image unless backend rendering and
runtime file materialization are deployed.

## Test Plan

Backend:

- Unit tests for placeholder extraction and rendering.
- Unit tests that unknown placeholders return validation errors.
- Unit tests that templates without `{{user_prompt}}` are accepted.
- API tests for create task with default, custom, and invalid run instruction templates.
- Retry tests verifying template snapshot inheritance.
- Worker preparation tests verifying `task-prompt.md` is written before container creation.

Worker:

- `bash -n deploy/entrypoint.worker.sh`
- Unit coverage that `entrypoint.worker.sh` no longer contains the main plan/execute prompt text.
- Unit coverage that missing or empty `CODIFY_TASK_PROMPT_FILE` fails clearly.
- Unit coverage that `PROMPT_FILE=/tmp/claude_prompt.txt` still reaches `ci-claude.sh`.

Frontend:

- `TaskFormDrawer.vue` tests for advanced collapsed state.
- Mode switch tests for untouched vs edited run instruction template.
- Placeholder insertion tests.
- Preview render success/error tests.
- i18n coverage for both `en.ts` and `zh-CN.ts`.

Integration:

- Create execute task with default template and verify the runtime prompt file content.
- Create plan task with custom template and no `{{user_prompt}}`, verify Claude receives only the
  rendered custom content.
- Retry a task and verify the retry inherits the original template snapshot.

## Open Questions

1. Should global default run instruction templates be editable in Config in the first release, or
   only moved from worker shell to backend constants first?
2. Should `rendered_prompt` be visible to all users who can view the task, or only operators/admins?
3. Should editing a pending task allow editing its run instruction template, or only its
   requirement prompt and schedule?
4. Should manual tasks without an issue support the same placeholder set with empty issue values,
   or should the UI hide issue-specific placeholders?

