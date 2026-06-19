# Task Run Instruction Template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将主任务提示词的组装从 worker shell 移到应用层，让普通任务、规划任务和 CI 自动修复任务都保存运行指令模板快照与最终渲染提示词，并在任务执行时只消费持久化的提示词文件。

**Architecture:** 新增 `task_prompt` 领域模块，集中管理内置模板、有效配置、占位符校验、上下文构建和渲染。任务创建、允许的编辑、重试和 CI 自动修复都在同一数据库事务内保存模板快照与最终提示词；scheduler 启动前只回填历史 pending/queued 任务，terminal 历史任务保持空值。worker 启动前把持久化结果写到 issue workspace 的 `runtime/task-{id}/task-prompt.md`，shell 只校验并复制该文件，不再根据 `USER_PROMPT` 或 `TASK_MODE` 拼接主提示词。

**Tech Stack:** Python 3.11, FastAPI, async SQLAlchemy, Alembic, Pydantic, Vue 3, TypeScript, Naive UI, vue-i18n, Vitest, pytest, Bash.

---

## Implementation Constraints

- Provider `system_prompt`、`APPEND_SYSTEM_PROMPT` 及提交说明、交付摘要修复、MR 总结提示词不在本次改造范围内。
- `tasks.user_prompt` 继续作为“需求”保存和展示；`run_instruction_template` 是独立的运行指令模板快照。
- 全局默认值只能影响后续新建任务；任务一旦保存，后续渲染必须基于任务快照。
- 新任务必须同时保存非空模板快照、非空 `rendered_prompt` 和 `rendered_prompt_at`。
- 历史 terminal 任务不伪造模板或最终提示词；历史 pending/queued 任务必须在 scheduler 启动前回填。
- 未知占位符返回 422；删除 `{{user_prompt}}` 合法；无占位符模板合法；渲染后的空白内容不合法。
- `run_instruction_template` 最大 50,000 字符，`rendered_prompt` 最大 100,000 字符，换行统一为 `\n`。
- 不通过环境变量传递最终提示词，不在普通日志中输出完整模板或最终提示词。
- `USER_PROMPT` 保留给任务元数据、MR 描述和后处理逻辑，但不再参与主提示词组装。
- backend 与 worker 需要作为一个兼容发布部署；新 worker 不提供 shell fallback。

## File Structure

### New files

- `backend/app/core/task_prompt.py`
  - 内置 execute、plan、CI auto-repair 模板。
  - 占位符提取、校验、上下文构建、渲染、模板选择和活动任务回填。
- `backend/alembic/versions/047_run_instruction_prompts.py`
  - 新增三个可空任务字段。
- `backend/tests/unit/test_task_prompt.py`
  - 渲染器、模板选择、限制与回填单元测试。
- `backend/tests/unit/test_task_prompt_api.py`
  - defaults、preview、create、detail、update 与权限 API 测试。
- `frontend/src/components/RunInstructionTemplateEditor.vue`
  - 运行指令编辑器、占位符插入、恢复默认、校验提示和可选预览区。
- `frontend/src/components/RunInstructionTemplateEditor.spec.ts`
  - 编辑器交互测试。

### Modified files

- `backend/app/config.py`
- `backend/app/api/config.py`
- `backend/app/api/config_runtime.py`
- `backend/app/api/task_schemas.py`
- `backend/app/api/tasks.py`
- `backend/app/core/task_helpers.py`
- `backend/app/core/ci_failure_collector.py`
- `backend/app/core/worker_runtime.py`
- `backend/app/core/worker_task_lifecycle.py`
- `backend/app/models.py`
- `backend/app/scheduler_service.py`
- `backend/tests/unit/test_config_runtime_api.py`
- `backend/tests/unit/test_scheduler_split.py`
- `backend/tests/unit/test_tasks_api.py`
- `backend/tests/unit/test_update_task_api.py`
- `backend/tests/unit/test_ci_failure_collector.py`
- `backend/tests/unit/test_worker_environment_variables.py`
- `backend/tests/unit/test_worker_coverage.py`
- `deploy/entrypoint.worker.sh`
- `frontend/src/api/index.ts`
- `frontend/src/components/config/WorkerSettingsPanel.vue`
- `frontend/src/components/config/WorkerSettingsPanel.spec.ts`
- `frontend/src/components/TaskFormDrawer.vue`
- `frontend/src/components/TaskFormDrawer.spec.ts`
- `frontend/src/views/TaskView.vue`
- `frontend/src/views/TaskView.spec.ts`
- `frontend/src/i18n/messages/en.ts`
- `frontend/src/i18n/messages/zh-CN.ts`
- `docs/worker-volume-mounts.md`

---

## Task 1: Build The Prompt Rendering Domain Module

**Files:**
- Create: `backend/app/core/task_prompt.py`
- Create: `backend/tests/unit/test_task_prompt.py`

- [ ] **Step 1: Add failing tests for placeholder extraction and exact rendering**

Cover both `{{name}}` and `{{ name }}`, duplicate placeholders, appearance-order de-duplication, empty known values, and preservation of all non-placeholder text.

- [ ] **Step 2: Add failing validation tests**

Cover:

- unknown placeholder rejection
- a template without placeholders
- a template without `{{user_prompt}}`
- a rendered result containing only whitespace
- 50,000/100,000 character boundaries
- CRLF and CR normalization to LF
- malformed text that does not match the supported placeholder syntax remaining literal text

- [ ] **Step 3: Run the focused tests and verify failure**

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_task_prompt.py -q
```

Expected: FAIL because `app.core.task_prompt` does not exist.

- [ ] **Step 4: Implement immutable built-in templates and the allowlist**

Add the three templates verbatim from the design spec and define the MVP placeholders in one canonical mapping. Keep user-facing insertion names separate from value resolution so UI endpoints can expose a stable ordered list.

- [ ] **Step 5: Implement normalization, extraction, validation and rendering**

Use a small regular-expression renderer only. Do not add Jinja or evaluation. Return structured metadata containing `rendered_prompt`, `used_placeholders`, and `unused_known_placeholders` so preview and persistence share the same code.

- [ ] **Step 6: Implement template selection helpers**

Selection order must be:

```text
retry snapshot supplied by caller
-> trigger_source == ci_auto_repair
-> task_mode == plan
-> execute default
```

Expose separate placeholder lists for normal execute/plan editors and the CI editor, while validating every submitted template against the same global allowlist.

- [ ] **Step 7: Run the renderer tests**

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_task_prompt.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/core/task_prompt.py backend/tests/unit/test_task_prompt.py
git commit -m "feat: add task prompt renderer"
```

---

## Task 2: Add Runtime Configuration For Three Defaults

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/api/config.py`
- Modify: `backend/app/api/config_runtime.py`
- Modify: `backend/tests/unit/test_config_runtime_api.py`
- Test: `backend/tests/unit/test_task_prompt.py`

- [ ] **Step 1: Add failing Settings and persistence tests**

Assert that these fields exist, default to the built-in content, serialize through runtime config, and can be PATCHed independently:

```text
default_execute_run_instruction_template
default_plan_run_instruction_template
ci_auto_repair_run_instruction_template
```

- [ ] **Step 2: Add failing validation tests**

Assert runtime config rejects unknown placeholders, blank templates and templates over 50,000 characters without persisting partial updates.

- [ ] **Step 3: Add an admin-only built-in metadata response test**

Add `GET /api/config/run-instruction-template-built-ins`. It returns the immutable built-in content and relevant placeholder lists for execute, plan and CI auto-repair. This endpoint is the source for System Config's “restore built-in” buttons; it must not derive values from current runtime overrides.

- [ ] **Step 4: Run focused config tests and verify failure**

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_config_runtime_api.py tests/unit/test_task_prompt.py -q
```

- [ ] **Step 5: Add settings and persisted config types**

Import the built-in string constants from `task_prompt.py` for `Settings` defaults. Add all three keys to `PERSISTED_CONFIG_TYPES`; do not mark them secret.

- [ ] **Step 6: Extend runtime config schemas and serialization**

Add the three editable strings to `RuntimeConfigSection` and `RuntimeConfigUpdate`. Validate each through the shared template validator before saving any override.

- [ ] **Step 7: Add the admin-only built-in metadata endpoint**

Keep task-operator defaults separate from this endpoint. System Config needs all three immutable built-ins; normal task operators only need effective execute and plan defaults.

- [ ] **Step 8: Run config tests**

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_config_runtime_api.py tests/unit/test_task_prompt.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/config.py backend/app/api/config.py backend/app/api/config_runtime.py backend/tests/unit/test_config_runtime_api.py backend/tests/unit/test_task_prompt.py
git commit -m "feat: configure task run instructions"
```

---

## Task 3: Add Task Snapshot Fields And Startup Backfill

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/047_run_instruction_prompts.py`
- Modify: `backend/app/core/task_prompt.py`
- Modify: `backend/app/scheduler_service.py`
- Modify: `backend/tests/unit/test_task_prompt.py`
- Modify: `backend/tests/unit/test_scheduler_split.py`

- [ ] **Step 1: Add failing model and backfill tests**

Cover:

- terminal historical tasks stay null
- pending/queued manual execute tasks receive execute snapshots
- pending/queued plan tasks receive plan snapshots
- `trigger_source=ci_auto_repair` wins over `task_mode`
- existing non-null snapshots are never replaced
- rendered values and timestamps are persisted together
- unavailable project metadata becomes an empty known value rather than an unknown-placeholder failure

- [ ] **Step 2: Add a failing scheduler startup ordering test**

Assert startup order is:

```text
run migrations
-> initialize DB
-> load runtime config
-> backfill active task prompts
-> start scheduler and CI collector
```

If backfill raises, neither scheduler nor CI collector may start.

- [ ] **Step 3: Run focused tests and verify failure**

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_task_prompt.py tests/unit/test_scheduler_split.py -q
```

- [ ] **Step 4: Add nullable model fields and migration**

Add:

```python
run_instruction_template: Mapped[str | None]
rendered_prompt: Mapped[str | None]
rendered_prompt_at: Mapped[datetime | None]
```

The Alembic revision must remain within the repository's effective 32-character revision limit and use `046_ci_failure_auto_repair` as `down_revision`. Upgrade adds nullable columns; downgrade removes them. Do not add a source/provenance column.

- [ ] **Step 5: Implement active-task backfill**

Load pending and queued tasks with their Issues, resolve effective settings once, build project metadata through the existing cached project lookup, select templates by trigger source then mode, and render through the shared service. Commit only after the full batch succeeds so scheduler never starts with a partial backfill.

- [ ] **Step 6: Call backfill before scheduler startup**

Place the call in `scheduler_service.py` after runtime overrides are loaded and before either background service is created. A failed backfill is fatal startup behavior, not a warning-only path.

- [ ] **Step 7: Run focused tests and inspect the migration**

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_task_prompt.py tests/unit/test_scheduler_split.py -q
alembic heads
alembic current
```

Expected: tests pass and there is one head at revision 047.

- [ ] **Step 8: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/047_run_instruction_prompts.py backend/app/core/task_prompt.py backend/app/scheduler_service.py backend/tests/unit/test_task_prompt.py backend/tests/unit/test_scheduler_split.py
git commit -m "feat: persist task prompt snapshots"
```

---

## Task 4: Add Operator Defaults And Preview APIs

**Files:**
- Modify: `backend/app/api/task_schemas.py`
- Modify: `backend/app/api/tasks.py`
- Create: `backend/tests/unit/test_task_prompt_api.py`

- [ ] **Step 1: Add failing defaults endpoint tests**

Test `GET /api/tasks/run-instruction-template-defaults` returns only effective execute and plan defaults plus their placeholder lists. Confirm a normal authenticated task operator can read it and unrelated System Config values are absent.

Declare this static GET route before `GET /tasks/{task_id}` so FastAPI does not attempt to parse `run-instruction-template-defaults` as an integer task ID.

- [ ] **Step 2: Add failing preview endpoint tests**

For `POST /api/tasks/render-run-instruction-template-preview`, cover:

- current issue/project/branch context
- custom content with and without `{{user_prompt}}`
- used and unused placeholder lists
- unknown placeholder 422
- empty rendered result 422
- issue-not-found, project access and issue-operator authorization
- no database mutation

- [ ] **Step 3: Run API tests and verify failure**

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_task_prompt_api.py -q
```

- [ ] **Step 4: Add request/response schemas**

Add focused Pydantic schemas for defaults and preview. Reuse the same 50,000-character input limit and shared renderer; do not duplicate placeholder parsing inside the route.

- [ ] **Step 5: Implement defaults and preview routes**

Preview must load the Issue, enforce the same operator/project rules as task creation, resolve project metadata, build the prospective task context from submitted mode/prompt, and call the shared renderer.

- [ ] **Step 6: Run API tests**

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_task_prompt_api.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/task_schemas.py backend/app/api/tasks.py backend/tests/unit/test_task_prompt_api.py
git commit -m "feat: preview task run instructions"
```

---

## Task 5: Render Prompts During Task Creation And Detail Serialization

**Files:**
- Modify: `backend/app/api/task_schemas.py`
- Modify: `backend/app/api/tasks.py`
- Modify: `backend/app/core/task_helpers.py`
- Modify: `backend/tests/unit/test_task_prompt_api.py`
- Modify: `backend/tests/unit/test_tasks_api.py`

- [ ] **Step 1: Add failing create tests**

Cover default execute, default plan, custom template, omitted `{{user_prompt}}`, unknown placeholder, empty rendered result and oversize rendered result.

Assert `run_instruction_template`, `rendered_prompt` and `rendered_prompt_at` are saved in the same creation transaction.

- [ ] **Step 2: Add failing detail serialization tests**

Assert task detail includes all three fields for every project reader, while list endpoints omit the two large text fields. Historical tasks return null fields rather than reconstructing from current defaults.

- [ ] **Step 3: Run focused tests and verify failure**

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_task_prompt_api.py tests/unit/test_tasks_api.py -q
```

- [ ] **Step 4: Extend `CreateTaskRequest`**

Add optional `run_instruction_template`. If omitted, server-side selection uses the effective default for `task_mode`; client-submitted content remains byte-for-byte authoritative after line-ending normalization.

- [ ] **Step 5: Render inside the create transaction**

Add the task and `flush()` to obtain its ID, build context from the task/Issue/project metadata, validate and render, set all prompt fields, then commit once. Do not commit an unrendered task and patch it afterward.

- [ ] **Step 6: Add explicit detail serialization**

Extend `_serialize_task` with an opt-in `include_prompt_details` flag. Use it for task detail and mutation responses, not task list/schedule/dashboard responses.

- [ ] **Step 7: Run focused tests**

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_task_prompt_api.py tests/unit/test_tasks_api.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/task_schemas.py backend/app/api/tasks.py backend/app/core/task_helpers.py backend/tests/unit/test_task_prompt_api.py backend/tests/unit/test_tasks_api.py
git commit -m "feat: render prompts when tasks are created"
```

---

## Task 6: Keep Edits And Retries Atomically Rendered

**Files:**
- Modify: `backend/app/api/task_schemas.py`
- Modify: `backend/app/api/tasks.py`
- Modify: `backend/tests/unit/test_task_prompt_api.py`
- Modify: `backend/tests/unit/test_update_task_api.py`
- Modify: `backend/tests/unit/test_tasks_api.py`

- [ ] **Step 1: Add failing update tests**

Cover:

- editing only `user_prompt` regenerates `rendered_prompt`
- editing only the run instruction template regenerates it
- switching `task_mode` regenerates context while preserving the explicitly submitted snapshot
- changing `require_changes` regenerates `{{require_changes}}`
- user prompt and template updates commit atomically
- invalid rendering leaves every original field unchanged
- existing pending/queued, administrator/initiator authorization applies to both prompt fields
- running/terminal tasks reject both fields with the existing 409 lifecycle rule

- [ ] **Step 2: Add failing retry tests**

Assert retries copy the original snapshot and render again against the retry task context. For a legacy historical source whose snapshot is null, use the current effective mode/trigger default as the only compatibility fallback so the newly created task still satisfies the non-null invariant.

- [ ] **Step 3: Run focused tests and verify failure**

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_update_task_api.py tests/unit/test_tasks_api.py tests/unit/test_task_prompt_api.py -q
```

- [ ] **Step 4: Extend `UpdateTaskRequest` and update flow**

Add nullable-by-omission/non-null-when-present `run_instruction_template`. After applying all submitted context fields in memory, render once and commit once. Preserve the existing row lock, final status refresh and plan-mode `require_changes=False` invariant.

- [ ] **Step 5: Update retry creation**

Flush the retry task, render from the inherited snapshot, and commit once. Do not copy the source task's old `rendered_prompt`, because branch/path/context placeholders may differ.

- [ ] **Step 6: Run focused tests**

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_update_task_api.py tests/unit/test_tasks_api.py tests/unit/test_task_prompt_api.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/task_schemas.py backend/app/api/tasks.py backend/tests/unit/test_task_prompt_api.py backend/tests/unit/test_update_task_api.py backend/tests/unit/test_tasks_api.py
git commit -m "feat: refresh prompts on task edits and retries"
```

---

## Task 7: Move CI Auto-Repair Onto The Shared Prompt Service

**Files:**
- Modify: `backend/app/core/ci_failure_collector.py`
- Modify: `backend/tests/unit/test_ci_failure_collector.py`
- Test: `backend/tests/unit/test_task_prompt.py`

- [ ] **Step 1: Replace current CI assertions with failing snapshot assertions**

Assert a repair task:

- keeps `task_mode=execute` and `trigger_source=ci_auto_repair`
- stores the effective CI template, not the default execute template
- renders issue title, project path and `/tmp/codify-runtime/ci-failure`
- uses fixed display metadata such as `修复当前 MR 的 CI 失败` for `user_prompt`
- does not require or interpolate `{{user_prompt}}` in the built-in CI template
- respects an administrator-customized CI template
- rejects creation atomically if configured content cannot render

- [ ] **Step 2: Run the focused collector test and verify failure**

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_ci_failure_collector.py -q
```

- [ ] **Step 3: Remove the operational `REPAIR_PROMPT` from task creation**

Keep only a concise system-generated `user_prompt` for existing list/detail compatibility. Select and render the dedicated configured CI template through `task_prompt.py` in the same transaction that creates the repair task and links it to the CI failure run.

- [ ] **Step 4: Run CI prompt tests**

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_ci_failure_collector.py tests/unit/test_task_prompt.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/ci_failure_collector.py backend/tests/unit/test_ci_failure_collector.py backend/tests/unit/test_task_prompt.py
git commit -m "feat: render CI repair task prompts"
```

---

## Task 8: Materialize The Persisted Prompt Before Container Creation

**Files:**
- Modify: `backend/app/core/worker_runtime.py`
- Modify: `backend/app/core/worker_task_lifecycle.py`
- Modify: `backend/tests/unit/test_worker_environment_variables.py`
- Modify: `backend/tests/unit/test_worker_coverage.py`

- [ ] **Step 1: Add failing materialization tests**

Cover:

- exact `rendered_prompt` bytes are written to `{runtime_path}/task-prompt.md`
- the runtime directory is created first
- missing/blank persisted prompt raises before container creation
- unavailable workspace/runtime path raises before container creation
- write failures raise a clear error and do not call Docker
- logs include task ID/path/character count but never full prompt content

- [ ] **Step 2: Add a failing environment test**

Assert the worker environment includes:

```text
CODIFY_TASK_PROMPT_FILE=/tmp/codify-runtime/task-prompt.md
```

and still includes `USER_PROMPT` and `TASK_MODE` for existing metadata/post-processing behavior.

- [ ] **Step 3: Run focused worker tests and verify failure**

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_worker_environment_variables.py tests/unit/test_worker_coverage.py -q
```

- [ ] **Step 4: Implement prompt file materialization**

Add a focused helper in `worker_runtime.py`. Use `build_issue_workspace_paths(...).runtime_path`; do not reconstruct the host path. Write the persisted value without rendering it again.

- [ ] **Step 5: Integrate it into container preparation**

Materialize after the issue workspace is resolved and before environment construction/Docker creation. Let the existing lifecycle failure handler mark the task failed, but ensure no container exists when materialization fails.

- [ ] **Step 6: Add the stable container path to worker env**

Keep prompt contents out of environment variables. The only new env value is the mounted file path.

- [ ] **Step 7: Run focused worker tests**

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_worker_environment_variables.py tests/unit/test_worker_coverage.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/core/worker_runtime.py backend/app/core/worker_task_lifecycle.py backend/tests/unit/test_worker_environment_variables.py backend/tests/unit/test_worker_coverage.py
git commit -m "feat: materialize rendered task prompts"
```

---

## Task 9: Remove Main Prompt Assembly From The Worker Shell

**Files:**
- Modify: `deploy/entrypoint.worker.sh`
- Modify: `backend/tests/unit/test_worker_coverage.py`

- [ ] **Step 1: Add failing shell contract tests**

Assert:

- execute/plan main-template text no longer exists in `entrypoint.worker.sh`
- `CODIFY_TASK_PROMPT_FILE` is required
- missing, nonexistent or empty files fail with a clear message
- valid input is copied to `/tmp/claude_prompt.txt`
- `PROMPT_FILE=/tmp/claude_prompt.txt` still reaches `ci-claude.sh`
- `TASK_MODE` remains available for plan-specific finalization behavior

- [ ] **Step 2: Run focused tests and verify failure**

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_worker_coverage.py -q
```

- [ ] **Step 3: Replace shell-side assembly with file validation and copy**

Implement the exact no-fallback contract from the spec. Do not fall back to `USER_PROMPT`, and do not log file contents.

- [ ] **Step 4: Validate Bash and worker contracts**

```bash
bash -n deploy/entrypoint.worker.sh
cd backend
.venv/bin/python -m pytest tests/unit/test_worker_coverage.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add deploy/entrypoint.worker.sh backend/tests/unit/test_worker_coverage.py
git commit -m "feat: consume persisted task prompt files"
```

---

## Task 10: Add Frontend API Types And A Shared Template Editor

**Files:**
- Modify: `frontend/src/api/index.ts`
- Create: `frontend/src/components/RunInstructionTemplateEditor.vue`
- Create: `frontend/src/components/RunInstructionTemplateEditor.spec.ts`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1: Add failing editor tests**

Cover:

- multiline value editing
- compact placeholder chips
- insertion at the current textarea cursor and selection replacement
- canonical inserted syntax `{{name}}`
- restore-default event
- unknown-placeholder feedback
- neutral warning when `{{user_prompt}}` is absent
- optional collapsed preview and preview error display

- [ ] **Step 2: Add failing API type tests or compile assertions**

Extend `Task`, `CreateTaskRequest`, and `UpdateTaskRequest` with prompt fields. Add types/functions for operator defaults, preview, and admin built-ins.

- [ ] **Step 3: Run focused frontend tests and verify failure**

```bash
cd frontend
npx vitest run --config vitest.config.ts src/components/RunInstructionTemplateEditor.spec.ts src/api/api.spec.ts
```

- [ ] **Step 4: Implement API contracts**

Add:

```text
getRunInstructionTemplateDefaults()
previewRunInstructionTemplate()
getRunInstructionTemplateBuiltIns()
```

Keep task detail fields optional/null-compatible so list responses and historical tasks remain valid.

- [ ] **Step 5: Implement the shared editor**

The component owns presentation and cursor insertion only. Parent forms own dirty-state, mode-switch decisions, persistence and preview requests.

- [ ] **Step 6: Add bilingual copy**

Use “Requirement/需求” for `user_prompt`, “Requirement Templates/需求模板” for the existing reusable templates, and “Run Instruction Template/运行指令模板” for the new feature.

- [ ] **Step 7: Run focused tests and type-check**

```bash
cd frontend
npx vitest run --config vitest.config.ts src/components/RunInstructionTemplateEditor.spec.ts src/api/api.spec.ts
npm run build
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/index.ts frontend/src/components/RunInstructionTemplateEditor.vue frontend/src/components/RunInstructionTemplateEditor.spec.ts frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: add run instruction editor"
```

---

## Task 11: Add Run Instructions To System Config

**Files:**
- Modify: `frontend/src/components/config/WorkerSettingsPanel.vue`
- Modify: `frontend/src/components/config/WorkerSettingsPanel.spec.ts`
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1: Add failing Worker Settings tests**

Assert the Worker tab:

- loads all three effective templates and immutable built-ins
- renders three independent multiline editors in a dedicated Run Instructions section
- exposes relevant placeholder chips for each editor
- restores only the selected editor to its built-in value
- marks the form dirty after edits or restore
- persists all changed fields through the existing runtime config PATCH flow
- surfaces backend validation failures without losing unsaved text
- leaves other worker settings unchanged

- [ ] **Step 2: Run focused tests and verify failure**

```bash
cd frontend
npx vitest run --config vitest.config.ts src/components/config/WorkerSettingsPanel.spec.ts
```

- [ ] **Step 3: Extend worker form state and dirty comparison**

Add the three template fields to the panel's current/saved snapshots. Fetch built-in metadata independently so “restore built-in” is not affected by current runtime overrides.

- [ ] **Step 4: Add the Run Instructions section**

Use the shared editor for:

```text
Default Execute Run Instruction
Default Plan Run Instruction
CI Auto-Repair Run Instruction
```

Keep existing Worker save/revert actions. A built-in reset changes the local form; Save persists it.

- [ ] **Step 5: Run focused tests and build**

```bash
cd frontend
npx vitest run --config vitest.config.ts src/components/config/WorkerSettingsPanel.spec.ts src/components/RunInstructionTemplateEditor.spec.ts
npm run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/config/WorkerSettingsPanel.vue frontend/src/components/config/WorkerSettingsPanel.spec.ts frontend/src/api/index.ts frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: manage run instructions in system config"
```

---

## Task 12: Add Advanced Run Instructions To Task Create/Edit

**Files:**
- Modify: `frontend/src/components/TaskFormDrawer.vue`
- Modify: `frontend/src/components/TaskFormDrawer.spec.ts`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1: Add failing create-mode tests**

Cover:

- Advanced section starts collapsed after task mode
- execute/plan effective defaults load from the operator endpoint
- default snapshot is submitted even if Advanced is never opened
- untouched mode switch silently replaces the template with the new mode default
- edited mode switch asks before replacement
- confirm replaces with new default; decline preserves edited content while changing mode
- restore loads current effective mode default and marks the form changed
- preview sends unsaved mode, requirement and template
- preview success/error stays inside Advanced
- a missing `{{user_prompt}}` shows the neutral note but does not block submit

- [ ] **Step 2: Add failing edit-mode tests**

Cover:

- initial content comes from the task snapshot, not the current global default
- initial dirty state is false even when snapshot differs from current global default
- unchanged prompt/template fields are omitted from PATCH
- changed requirement/template are sent together
- pending/queued lifecycle and current authorization behavior remain unchanged
- a legacy null snapshot falls back to the effective current-mode default only for editing compatibility

- [ ] **Step 3: Run focused tests and verify failure**

```bash
cd frontend
npx vitest run --config vitest.config.ts src/components/TaskFormDrawer.spec.ts
```

- [ ] **Step 4: Add explicit editor state**

Track:

```text
runInstructionTemplate
initialRunInstructionTemplate
runInstructionDirty
defaultsByMode
defaultsLoading/defaultsError
previewLoading/previewResult/previewError
```

Dirty means edited in the current drawer session; it is not a comparison with current global defaults.

- [ ] **Step 5: Implement mode-switch behavior**

Centralize mode changes in one handler so radio/select changes cannot bypass confirmation. If the user declines replacement, apply only `task_mode` and retain the current template.

- [ ] **Step 6: Submit create and edit payloads**

Create always sends the loaded snapshot. Edit sends `run_instruction_template` only when changed, but a mode/requirement change still relies on backend atomic rerendering.

- [ ] **Step 7: Run focused tests and build**

```bash
cd frontend
npx vitest run --config vitest.config.ts src/components/TaskFormDrawer.spec.ts src/components/RunInstructionTemplateEditor.spec.ts
npm run build
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/TaskFormDrawer.vue frontend/src/components/TaskFormDrawer.spec.ts frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: edit task run instructions"
```

---

## Task 13: Add Final Prompt Viewing To Task Detail

**Files:**
- Modify: `frontend/src/views/TaskView.vue`
- Modify: `frontend/src/views/TaskView.spec.ts`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1: Add failing task detail tests**

Assert:

- the existing prompt card header has a compact `用户提示词 | 最终运行提示词` viewing switch
- user prompt remains the initial selection
- final selection renders persisted `rendered_prompt` through the existing Markdown renderer
- historical null/empty final prompt shows `暂无最终运行提示词`
- switching does not depend on task mutation permission
- a project reader who cannot operate the task still sees both values
- no client-side reconstruction from current defaults occurs

- [ ] **Step 2: Run focused tests and verify failure**

```bash
cd frontend
npx vitest run --config vitest.config.ts src/views/TaskView.spec.ts
```

- [ ] **Step 3: Add compact viewing state to the existing card**

Reuse the current bounded card and `NScrollbar`. Do not add a second full-size prompt card. Reset the selected view to user prompt when navigating to another task.

- [ ] **Step 4: Run focused tests and build**

```bash
cd frontend
npx vitest run --config vitest.config.ts src/views/TaskView.spec.ts
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/TaskView.vue frontend/src/views/TaskView.spec.ts frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: show final task prompts"
```

---

## Task 14: Document, Integrate And Validate The Compatible Release

**Files:**
- Modify: `docs/worker-volume-mounts.md`
- Verify all files above

- [ ] **Step 1: Document the runtime artifact**

Add `runtime/task-{task_id}/task-prompt.md`, its container path, access characteristics, and the requirement that backend/scheduler and worker image deploy together. State explicitly that `USER_PROMPT` is metadata only for the main run.

- [ ] **Step 2: Run the complete focused backend suite**

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_task_prompt.py \
  tests/unit/test_task_prompt_api.py \
  tests/unit/test_config_runtime_api.py \
  tests/unit/test_scheduler_split.py \
  tests/unit/test_tasks_api.py \
  tests/unit/test_update_task_api.py \
  tests/unit/test_ci_failure_collector.py \
  tests/unit/test_worker_environment_variables.py \
  tests/unit/test_worker_coverage.py -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend focused suites**

```bash
cd frontend
npx vitest run --config vitest.config.ts \
  src/api/api.spec.ts \
  src/components/RunInstructionTemplateEditor.spec.ts \
  src/components/config/WorkerSettingsPanel.spec.ts \
  src/components/TaskFormDrawer.spec.ts \
  src/views/TaskView.spec.ts
npm run build
```

Expected: PASS.

- [ ] **Step 4: Validate shell and repository hygiene**

```bash
bash -n deploy/entrypoint.worker.sh
git diff --check
```

Expected: both commands succeed.

- [ ] **Step 5: Run migration validation in the backend environment**

```bash
cd backend
alembic heads
alembic upgrade head
```

Verify the scheduler startup log reports active-task prompt backfill before scheduler start. Test with one terminal historical task and one pending historical task.

- [ ] **Step 6: Perform integration smoke checks**

Verify:

1. Default execute task writes the same content shown in “最终运行提示词” to `task-prompt.md`.
2. Plan task with a custom no-`{{user_prompt}}` template sends only the custom rendered content.
3. CI auto-repair uses its dedicated configured template and stable CI context path.
4. Editing a pending task's requirement and template updates detail and runtime artifact consistently.
5. Retry inherits the source snapshot but receives a newly rendered prompt and timestamp.
6. Missing/empty persisted prompt fails before Docker container creation with no shell fallback.

- [ ] **Step 7: Commit documentation and any integration-only test fixes**

```bash
git add docs/worker-volume-mounts.md
git commit -m "docs: describe persisted task prompts"
```

---

## Release Order

Deploy the migration, backend API, scheduler backfill, runtime materialization and worker image in one coordinated release:

```text
stop scheduler
-> deploy database migration and backend/scheduler code
-> start scheduler and complete active-task backfill
-> deploy/use the matching worker image
-> resume task execution
```

Do not schedule work onto the new worker image until the scheduler has successfully backfilled every pending/queued historical task. Rollback must restore the previous backend and worker together; the nullable database columns can remain during application rollback.
