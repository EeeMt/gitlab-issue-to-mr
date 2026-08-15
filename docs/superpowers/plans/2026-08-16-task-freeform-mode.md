# Task 自由模式与模式优先创建流程实施计划

> 对应设计：[Task 自由模式与模式优先创建流程设计](../specs/2026-08-14-task-freeform-mode-design.md)

**目标：** 新增正式的 `freeform` Task 模式，让服务端保证“仅使用用户提示词、允许无代码变更”的运行语义；将新建 Task 抽屉改为先选模式再展示完整表单，并让 Worker 交付、Issue 状态、CI 自动修复和系统统计正确识别自由模式。

**架构：** `task_mode`、提示词模板和 `require_changes` 继续是三个独立字段，但自由模式由服务端施加 canonical 不变量：`task_mode=freeform`、`run_instruction_template={{user_prompt}}`、`require_changes=false`。Worker 对自由模式延迟 MR 交付，只有 canonical finalization 已持久化非空 `commit_sha` 后才允许创建、Ready 或改写 MR。前端只表达用户选择，不复制自由模板业务真值。

**技术栈：** Python 3.11、FastAPI、Pydantic、async SQLAlchemy、Alembic、pytest、Vue 3、TypeScript、Naive UI、vue-i18n、Vitest、Playwright、Docker Worker Runtime Bundle。

---

## 实施约束

- Create API 省略 `task_mode` 时继续默认 `execute`；只有新建 Task UI 不预选模式。
- 自由模式模板只有应用内 `FREEFORM_RUN_INSTRUCTION_TEMPLATE` 一份业务真值；不得新增 System Config 或 Worker Profile 的自由模板字段。
- 自由模式显式提交非 canonical 模板必须返回 `422`；不得静默接受“自由模式 + 自定义包装”。
- 自由模式无论请求如何传递 `require_changes`，最终持久化和预览上下文都必须为 `false`。
- Retry 继承源 Task 的模式和提示词快照；CI 自动修复自身继续固定为 `execute`。
- `execute` 的既有交付资格不能被收紧为“必须有 `commit_sha`”；新增提交条件只适用于 `freeform`。
- 活动自由 Task 在执行前按潜在分支写入者处理，不能与 CI 自动修复并发修改同一 Issue 分支。
- 自由模式不能在容器启动前创建 MR，也不能把已有 MR IID 传入容器触发“运行中”描述更新。
- 自由模式的 MR 门禁是“canonical 结果成功且 `commit_sha` 非空”，不是单独检查 `exit_code == 0`。
- 无提交自由 Task 不创建 MR，也不改变已有 MR 的标题、描述和 Draft/Ready 状态。
- 不从历史 `run_instruction_template={{user_prompt}}` 反推或回填 `freeform`。
- Claude 与 Codex Adapter 不增加自由模式专用分支；两者继续消费同一个持久化 Prompt 和交付合同。
- Backend、Frontend 和 Worker 需要在同一发布窗口部署，并在冻结 Runtime Bundle 上完成真实 smoke。

## 顺序与并行边界

```text
Task 1 migration/domain
  -> Task 2 create/defaults/preview
  -> Task 3 update/retry
       -> Task 4 Issue/CI lifecycle
       -> Task 5 Worker delayed MR delivery
       -> Task 6 statistics backend
       -> Task 7 frontend types/form model
            -> Task 8 mode-first drawer UX
            -> Task 9 task displays/statistics UI
  -> Task 10 integration, real Worker smoke, release gate
```

- Task 4、5、6 在 Task 3 的服务端三值契约稳定后可并行开发。
- Task 7 依赖 Task 2、3 的 API 契约；Task 8、9 在 Task 7 后可并行。
- Task 10 必须在所有代码路径合并后执行，真实 Worker smoke 不能用源代码检查或 mock 代替。
- 每个 Task 的提交命令表示建议提交边界；工作区存在无关改动时使用显式路径或 `git commit --only`，不得把无关文件带入提交。

---

## Task 1：扩展数据库约束并建立 canonical 自由模式领域规则

**Files:**

- Create: `backend/alembic/versions/<next_revision>_task_freeform_mode.py`
- Create: `backend/tests/unit/test_task_freeform_mode_migration.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/core/task_prompt.py`
- Modify: `backend/app/core/worker_profiles.py`
- Modify: `backend/app/api/task_schemas.py`
- Modify: `backend/tests/unit/test_task_prompt.py`
- Modify: `backend/tests/unit/test_task_api_contract.py`

- [ ] **Step 1：确认迁移拓扑只有一个 head**

```bash
cd backend
.venv/bin/alembic heads
```

Expected: 只有一个 head。计划编写时为 `072_shared_per_item_inheritance`；实施时必须以命令结果为准，并据此分配新 revision 和 `down_revision`。

若出现多个 head，停止本 Task，先独立修复迁移拓扑；不要把历史分支修复混入自由模式迁移。

- [ ] **Step 2：先写失败的迁移和领域测试**

覆盖：

- 迁移从实施时唯一 head 延伸；
- upgrade 将 `ck_tasks_task_mode` 扩展为 `execute/freeform/plan`；
- downgrade 先把 `freeform` 映射为 `execute`、强制 `require_changes=false`，再恢复二值约束；
- server default 仍为 `execute`；
- `FREEFORM_RUN_INSTRUCTION_TEMPLATE` 精确等于 `{{user_prompt}}`；
- 普通模板选择优先级为 retry → CI → freeform → plan → execute；
- Worker Profile Snapshot 选择自由模式时返回 canonical 常量，不读取实施模板；
- Create、Update 和 Preview schema 接受三值，仍拒绝其他值；
- Create 的 `effective_require_changes` 对 `freeform` 和 `plan` 都返回 `false`。

- [ ] **Step 3：运行失败测试**

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_task_freeform_mode_migration.py \
  tests/unit/test_task_prompt.py \
  tests/unit/test_task_api_contract.py -q
```

Expected: FAIL，当前约束、常量和 schema 仍是二值。

- [ ] **Step 4：实现迁移**

迁移要求：

```text
upgrade:
  drop ck_tasks_task_mode
  create ck_tasks_task_mode for execute/freeform/plan

downgrade:
  update freeform rows to execute
  set require_changes=false for mapped rows
  drop three-value constraint
  restore execute/plan constraint
```

不要新增列，不要回填历史任务，也不要修改 `deleted_task_statistics.task_mode`。

- [ ] **Step 5：增加 canonical 常量并扩展模板选择**

在 `task_prompt.py` 定义：

```python
FREEFORM_RUN_INSTRUCTION_TEMPLATE = "{{user_prompt}}"
```

让 `select_run_instruction_template()` 和 `select_snapshot_run_instruction_template()` 在 CI 分支之后、plan/execute 默认分支之前识别 `freeform`。不要给 `WorkerProfile` 或 `TaskWorkerProfileSnapshot` 增加自由模板字段。

- [ ] **Step 6：扩展请求 schema**

- `CreateTaskRequest.task_mode`、`UpdateTaskRequest.task_mode`、`RunInstructionTemplatePreviewRequest.task_mode` 接受 `freeform`；
- Preview 的 `run_instruction_template` 改为可省略，但只有 `freeform` 允许实际省略；
- 更新字段说明和模型注释，不再描述为 execute/plan 二值；
- 保持 Create API 默认 `execute`。

- [ ] **Step 7：运行聚焦测试**

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_task_freeform_mode_migration.py \
  tests/unit/test_task_prompt.py \
  tests/unit/test_task_api_contract.py -q
```

Expected: PASS。

- [ ] **Step 8：提交**

```bash
git add \
  backend/alembic/versions/<allocated_revision>_task_freeform_mode.py \
  backend/tests/unit/test_task_freeform_mode_migration.py \
  backend/app/models.py \
  backend/app/core/task_prompt.py \
  backend/app/core/worker_profiles.py \
  backend/app/api/task_schemas.py \
  backend/tests/unit/test_task_prompt.py \
  backend/tests/unit/test_task_api_contract.py
git commit -m "feat(tasks): add freeform task mode domain"
```

---

## Task 2：实现创建、默认模板和 Prompt 预览的不变量

**Files:**

- Modify: `backend/app/core/task_prompt.py`
- Modify: `backend/app/api/task_creation_service.py`
- Modify: `backend/app/core/task_creation.py`
- Modify: `backend/app/api/tasks.py`
- Modify: `backend/tests/unit/test_task_prompt_api.py`
- Modify: `backend/tests/unit/test_tasks_api.py`
- Modify: `backend/tests/unit/test_task_api_contract.py`

- [ ] **Step 1：增加失败的创建 API 测试**

覆盖：

- 创建自由 Task 时省略模板，服务端保存 canonical 模板和只含用户提示词的 `rendered_prompt`；
- `require_changes` 省略、传 `false`、传 `true` 时最终都保存为 `false`；
- 显式 canonical 模板允许，其他模板返回稳定的 `422`；
- 创建失败时模板、Prompt、Task、Snapshot 不发生部分提交；
- 省略 `task_mode` 仍创建 `execute`；
- `execute` 和 `plan` 原有模板选择与校验不变；
- `GET /tasks/run-instruction-template-defaults` 返回只读 `freeform` 元数据，内容来自 canonical 常量；
- 响应始终序列化真实 `task_mode=freeform`。

- [ ] **Step 2：增加失败的预览 API 测试**

覆盖：

- 自由模式省略模板或显式传 canonical 模板都成功；
- 自由模式显式传其他模板返回与 Create 相同的 `422`；
- 自由模式即使传 `require_changes=true`，渲染上下文中的值仍为 `false`；
- 预览正文只表示 Task 主提示词，不包含 Provider system prompt；
- execute/plan 省略模板仍返回 `422`；
- Preview 不写数据库。

- [ ] **Step 3：运行失败测试**

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_task_prompt_api.py \
  tests/unit/test_tasks_api.py \
  tests/unit/test_task_api_contract.py -q
```

- [ ] **Step 4：集中实现自由模式模板规范化**

在进入 `prepare_task_runtime_snapshot()` 之前或其内部建立单一服务端决策：

```text
freeform + omitted template      -> canonical
freeform + canonical template    -> canonical
freeform + any other template    -> 422
freeform + any require_changes   -> false
```

把模板解析和错误语义集中在 `task_prompt.py` 的共享 helper 中，供 Create、Update 和 Preview 复用；非 canonical 模板的 detail 固定为 `freeform mode only accepts the canonical user-prompt template`。规范化后的 Task 字段、Worker Snapshot 选择和 Prompt 渲染必须处于现有创建事务中。不要依赖前端主动发送 canonical 字符串。

- [ ] **Step 5：扩展默认模板 API**

新增 `freeform` 响应项：

- `content` 来自 `FREEFORM_RUN_INSTRUCTION_TEMPLATE`；
- `available_placeholders` 只包含 `user_prompt`；
- `known_placeholders` 继续返回服务端统一清单；
- 不读取 System Config 或 Worker Profile。

- [ ] **Step 6：实现 Preview 的模式分支**

先按模式解析有效模板，再调用现有 renderer：

- freeform 强制使用 canonical 模板；
- execute/plan 保留显式模板要求；
- freeform 构造 prospective Task 时强制 `require_changes=false`。

- [ ] **Step 7：运行聚焦测试**

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_task_prompt.py \
  tests/unit/test_task_prompt_api.py \
  tests/unit/test_tasks_api.py \
  tests/unit/test_task_api_contract.py -q
```

Expected: PASS。

- [ ] **Step 8：提交**

```bash
git add \
  backend/app/core/task_prompt.py \
  backend/app/api/task_creation_service.py \
  backend/app/core/task_creation.py \
  backend/app/api/tasks.py \
  backend/tests/unit/test_task_prompt_api.py \
  backend/tests/unit/test_tasks_api.py \
  backend/tests/unit/test_task_api_contract.py
git commit -m "feat(tasks): enforce freeform prompt invariants"
```

---

## Task 3：实现待执行 Task 更新和 Retry 的原子三值语义

**Files:**

- Modify: `backend/app/api/task_update_service.py`
- Modify: `backend/app/api/task_creation_service.py`
- Modify: `backend/tests/unit/test_update_task_api.py`
- Modify: `backend/tests/unit/test_task_prompt_api.py`
- Modify: `backend/tests/unit/test_tasks_api.py`

- [ ] **Step 1：增加失败的 Update 测试**

覆盖：

- execute/plan 切到 freeform 时，同时覆盖 canonical 模板、`require_changes=false` 并重新渲染；
- 自由 Task 只修改 `user_prompt` 时原子更新 `rendered_prompt`；
- 自由 Task 显式提交非 canonical 模板返回 `422` 且不部分保存；
- freeform 切回 execute/plan 且请求未带模板时，使用冻结 Worker Profile Snapshot 的目标模式默认模板；
- 模式切换时不把 `{{user_prompt}}` 静默沿用为 execute/plan 默认模板；
- 显式合法模板仍优先于目标模式默认模板；
- Scheduler claim 导致状态离开 pending/queued 时继续返回 `409`，不保存半成品。

- [ ] **Step 2：增加失败的 Retry 测试**

覆盖：

- 自由 Task Retry 保留 `task_mode=freeform`、`require_changes=false`、canonical 模板和持久化 Prompt 快照；
- Retry 不读取当前 Worker Profile 的 execute 模板；
- execute/plan Retry 行为不变；
- Retry API 不允许顺便切换模式。

- [ ] **Step 3：运行失败测试**

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_update_task_api.py \
  tests/unit/test_task_prompt_api.py \
  tests/unit/test_tasks_api.py -q
```

- [ ] **Step 4：按最终目标模式解析模板**

更新路径不要先无条件复用 `task.run_instruction_template`。按以下优先级选择本次渲染模板：

```text
target mode is freeform
  -> reject explicit non-canonical template
  -> canonical template

explicit template supplied
  -> submitted template

mode changed to execute/plan without explicit template
  -> target-mode template from frozen TaskWorkerProfileSnapshot

mode unchanged without explicit template
  -> existing task snapshot
```

最终 `task_mode`、`require_changes`、模板和 `rendered_prompt` 必须在同一锁定事务中校验和保存。

- [ ] **Step 5：保留 Retry 的不可变快照语义**

Retry 继续复制源 Task 的提示词和 Worker/Provider/Harness/Runtime Bundle 快照。只补足三值验证和回归测试，不把 Retry 改成从当前 Profile 重新解析自由模板。

- [ ] **Step 6：运行聚焦测试**

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_update_task_api.py \
  tests/unit/test_task_prompt_api.py \
  tests/unit/test_tasks_api.py -q
```

Expected: PASS。

- [ ] **Step 7：提交**

```bash
git add \
  backend/app/api/task_update_service.py \
  backend/app/api/task_creation_service.py \
  backend/tests/unit/test_update_task_api.py \
  backend/tests/unit/test_task_prompt_api.py \
  backend/tests/unit/test_tasks_api.py
git commit -m "feat(tasks): update and retry freeform tasks"
```

---

## Task 4：修正 Issue 状态与 CI 自动修复关联

**Files:**

- Modify: `backend/app/core/task_helpers.py`
- Modify: `backend/app/core/ci_failure_collector.py`
- Modify: `backend/tests/unit/test_tasks_api.py`
- Modify: `backend/tests/unit/test_ci_failure_collector.py`

- [ ] **Step 1：增加失败的 Issue 状态测试**

在没有活动 Task、Issue 当前为 `in_progress` 的条件下覆盖：

- 只有 completed 且无提交的 freeform → `open`；
- completed freeform 且 `commit_sha` 非空 → `in_review`；
- 先前 completed execute、之后无提交 freeform → 仍为 `in_review`；
- completed execute 即使 `commit_sha` 为空 → 保持既有 `in_review`；
- 只有 plan 或全部失败/取消 → `open`；
- pending/queued/running 任一存在时不提前收敛状态。

- [ ] **Step 2：增加失败的 CI 关联测试**

覆盖 `ci_failure_collector.py` 中三个语义点：

- 最近手动交付：completed execute 始终有资格；completed freeform 只有 `commit_sha` 非空才有资格；
- 活动分支写入者：pending/queued/running 的 execute 和 freeform 都阻止新 CI 修复，plan 不阻止；
- 最近任务优先级：无提交 freeform 不遮蔽前一个符合资格的 execute/freeform；
- 新建 CI auto-repair Task 仍是 `task_mode=execute`、`require_changes=true`。

- [ ] **Step 3：运行失败测试**

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_tasks_api.py \
  tests/unit/test_ci_failure_collector.py -q
```

- [ ] **Step 4：替换二元 SQL 条件**

Issue 交付资格使用：

```text
task_mode = execute
OR (task_mode = freeform AND commit_sha IS NOT NULL)
```

CI 最近手动交付使用相同模式条件并保留 `trigger_source=manual`、`status=completed`。活动写入者改为 `task_mode IN (execute, freeform)`。

不要使用 `task_mode != plan`，也不要把 `commit_sha IS NOT NULL` 泛化到 execute。

- [ ] **Step 5：运行聚焦测试**

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_tasks_api.py \
  tests/unit/test_ci_failure_collector.py -q
```

Expected: PASS。

- [ ] **Step 6：提交**

```bash
git add \
  backend/app/core/task_helpers.py \
  backend/app/core/ci_failure_collector.py \
  backend/tests/unit/test_tasks_api.py \
  backend/tests/unit/test_ci_failure_collector.py
git commit -m "fix(tasks): align freeform delivery lifecycle"
```

---

## Task 5：为自由模式实现延迟 MR 交付

**Files:**

- Create: `backend/tests/unit/test_worker_freeform_delivery.py`
- Modify: `backend/app/core/worker_task_lifecycle.py`
- Verify/Modify: `backend/app/core/worker_gitlab.py`
- Verify/Modify: `backend/app/core/worker_runtime.py`
- Modify: `backend/tests/unit/test_worker_profile_runtime.py`
- Modify: `backend/tests/unit/test_worker_coverage.py`
- Modify: `backend/tests/unit/test_worker_environment_variables.py`
- Verify: `deploy/worker-entrypoint/main.sh`
- Verify: `deploy/worker-entrypoint/gitlab.sh`

- [ ] **Step 1：增加容器启动前 MR 隔离测试**

覆盖：

- execute 保持现有预创建/复用 MR 和 `MR_IID` 注入；
- freeform 即使 Issue 已有 MR，也不在启动前调用 `_create_mr_if_needed()`；
- freeform 向 `_prepare_container_inputs()` 传递空 MR 上下文，因此 worker entrypoint 的运行中描述更新会跳过；
- 容器环境保留 `TASK_MODE=freeform`、`REQUIRE_CHANGES=false` 和持久化 Prompt 文件路径，但不含 `MR_IID`；
- `had_existing_mr` 仍保留为运行前通知事实，不通过清空 Issue 字段伪造状态；
- 无 target branch 的 no-MR 模式保持不变。

- [ ] **Step 2：增加收尾交付矩阵测试**

至少覆盖：

| 模式/结果 | 预期 MR 行为 |
|---|---|
| freeform completed，`commit_sha=NULL`，Issue 无 MR | 不创建、不 Ready、不更新描述 |
| freeform completed，`commit_sha=NULL`，Issue 有 MR | 标题、描述、Draft/Ready 均不变 |
| freeform completed，`commit_sha` 非空，已有 MR | push 后复用并持久化关联，再更新描述/Ready |
| freeform completed，`commit_sha` 非空，无 MR | push 后创建 MR，再持久化关联并更新描述/Ready |
| freeform failed/cancelled/timeout | 不因进程退出路径触发 MR 交付 |
| execute completed | 既有时序和通知行为不变 |
| resume freeform | 与正常执行使用同一提交门禁 |

另覆盖 MR API 失败时：保留已保存的 `commit_sha`，不伪造 `Issue.merge_request_iid/url`，并保留可诊断日志。

- [ ] **Step 3：运行失败测试**

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_worker_freeform_delivery.py \
  tests/unit/test_worker_profile_runtime.py \
  tests/unit/test_worker_environment_variables.py \
  tests/unit/test_worker_coverage.py -q
```

- [ ] **Step 4：分离“运行成功”和“存在代码交付”**

在 `create_execute_container()` 中：

- 对 freeform 跳过启动前 MR create/reuse；
- 即使 Issue 已有关联 MR，也不把其 IID 传入容器；
- 不修改数据库中的 Issue MR 字段。

在 `monitor_container_run()` 中：

1. 先解析 canonical terminal/finalization，使 `task.status` 和 `task.commit_sha` 成为持久化真值；
2. 只有 `task_mode=freeform`、Task 成功完成且 `commit_sha` 非空时，才执行 post-push MR create/reuse；
3. 持久化真实 `Issue.merge_request_iid/url` 后，才更新 MR 描述和移除 Draft；
4. 无提交自由 Task 跳过 Ready、描述更新和 MR 交付型通知动作；
5. execute/plan 继续沿用现有分支，不把延迟时序泛化到旧模式。

- [ ] **Step 5：复用 GitLab helper，不复制 MR API 逻辑**

如有必要，将 create/reuse + persist + Ready/description 组合成小型 helper，但继续复用 `create_mr_if_needed()`、`persist_issue_mr_if_changed()`、`remove_mr_draft_status_for_issue()` 和 `update_mr_description_for_issue()`。不要在 lifecycle 中再实现一套 GitLab 请求。

- [ ] **Step 6：验证 Worker shell 的既有兼容路径**

确认 `main.sh` 在 freeform 未注入 `MR_IID` 时：

- Harness 运行前 `update_mr_description` 安全跳过；
- 有提交时先 commit/push，再查找已有 MR；
- 无已有 MR 时由 Backend post-push 创建；
- 无变化且 `REQUIRE_CHANGES=false` 正常退出。

只有发现实际合同缺口时才修改 shell，并为修改增加 `backend/tests/mock_integration/test_entrypoint.py` 回归测试。

- [ ] **Step 7：运行聚焦测试**

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_worker_freeform_delivery.py \
  tests/unit/test_worker_profile_runtime.py \
  tests/unit/test_worker_environment_variables.py \
  tests/unit/test_worker_coverage.py \
  tests/unit/test_worker_coverage_ext.py -q
```

Expected: PASS。

- [ ] **Step 8：提交**

```bash
git add \
  backend/app/core/worker_task_lifecycle.py \
  backend/app/core/worker_gitlab.py \
  backend/app/core/worker_runtime.py \
  backend/tests/unit/test_worker_freeform_delivery.py \
  backend/tests/unit/test_worker_profile_runtime.py \
  backend/tests/unit/test_worker_environment_variables.py \
  backend/tests/unit/test_worker_coverage.py
git commit -m "feat(worker): delay freeform merge request delivery"
```

若 shell 或额外测试确有修改，将其显式加入提交；不要预先制造无意义改动。

---

## Task 6：增加 Task Mode Breakdown 并扩展代码统计样本

**Files:**

- Modify: `backend/app/api/system_statistics_queries.py`
- Modify: `backend/app/api/system_statistics.py`
- Verify/Modify: `backend/app/core/system_statistics_deletion.py`
- Modify: `backend/tests/unit/test_system_lifecycle_statistics.py`
- Modify: `backend/tests/unit/test_system_lifecycle_statistics_pg.py`

- [ ] **Step 1：增加失败的查询层测试**

覆盖：

- 新 `build_task_mode_breakdown()` 按真实 `task_mode` 分组；
- `freeform`、`execute`、`plan` 分别返回，历史 NULL 保持 Unknown；
- 使用现有 `all_tasks` CTE，因此 retained/deleted、project/provider/harness/data_state 筛选全部生效；
- Task Mode 行复用现有 completed/failed/cancelled/success/deleted/token/change 指标；
- 该有界枚举不使用 Top N 截断；
- 删除归档原样保存 `freeform`。

- [ ] **Step 2：增加失败的代码样本测试**

将 `_code_eligible()` 的期望扩展为 completed `execute/freeform`，同时覆盖：

- plan 不 eligible；
- deleted-before-terminal 不 eligible；
- freeform 有已知变更数据时计入 additions/deletions/total；
- freeform 无可靠数据时增加 eligible 分母但不伪造已知 0；
- available/eligible 覆盖率分子不超过分母。

- [ ] **Step 3：增加失败的 API 测试**

`GET /api/admin/system-statistics/breakdowns` 新增 `task_modes`，既有 `projects/providers/harnesses` 不变。验证：

- key 为 `freeform/execute/plan/null`；
- label 使用后端中立原值或 Unknown，不固化中文；
- 所有过滤参数继续生效；
- Unknown 的 aggregate NULL 语义不退化为精确 0。

- [ ] **Step 4：运行失败测试**

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_system_lifecycle_statistics.py \
  tests/unit/test_system_lifecycle_statistics_pg.py -q
```

- [ ] **Step 5：实现查询和 API 响应扩展**

- 复用 `_breakdown_select()` 构建 `build_task_mode_breakdown()`；
- API 与其他三类 Breakdown 使用同一个 `all_tasks` CTE；
- `task_modes` 返回全部枚举行，不调用 `_top_n_with_unknown()`；
- `_code_eligible()` 改为 `task_mode IN (execute, freeform)`；
- 删除归档如果已经原样写入字符串，只补测试，不做无意义代码改动。

- [ ] **Step 6：运行聚焦测试**

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_system_lifecycle_statistics.py \
  tests/unit/test_system_lifecycle_statistics_pg.py -q
```

Expected: PASS。

- [ ] **Step 7：提交**

```bash
git add \
  backend/app/api/system_statistics_queries.py \
  backend/app/api/system_statistics.py \
  backend/tests/unit/test_system_lifecycle_statistics.py \
  backend/tests/unit/test_system_lifecycle_statistics_pg.py
git commit -m "feat(stats): add task mode lifecycle breakdown"
```

仅在归档代码实际需要修改时加入 `backend/app/core/system_statistics_deletion.py`。

---

## Task 7：扩展前端类型、请求构建和 Preview 合同

**Files:**

- Modify: `frontend/src/api/tasks.ts`
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/api/tasks.contract.spec.ts`
- Modify: `frontend/src/features/tasks/taskFormModel.ts`
- Modify: `frontend/src/features/tasks/taskFormModel.spec.ts`
- Modify: `frontend/src/features/tasks/useTaskFormSubmission.ts`
- Modify: `frontend/src/features/tasks/useRunInstructionPreview.ts`
- Modify: `frontend/src/test/mocks/api.ts`
- Modify: `frontend/src/components/TaskFormDrawer.spec.ts`

- [ ] **Step 1：增加失败的类型与请求构建测试**

覆盖：

- `TaskMode`、Task response、Create/Update/Preview 请求都接受 `freeform`；
- `RunInstructionTemplateDefaults` 包含只读 `freeform`；
- 共享 mocks/fixtures 能表达 `task_mode=freeform`，且不会把未知非 plan 值默认为 execute；
- Preview 请求的模板字段对 freeform 可省略；
- 创建自由 Task 固定发送 `task_mode=freeform`、`require_changes=false`；
- 创建自由 Task 不发送前端复制的 canonical 模板；
- execute/plan 仍按 dirty 状态发送自定义模板；
- 更新切到 freeform 时可只发送模式，由后端规范化；
- 从 freeform 切到 execute/plan 且模板未编辑时不发送旧 canonical 模板。

- [ ] **Step 2：增加失败的 submission/preview 测试**

覆盖：

- 自由模式不因本地 `runInstructionTemplate` 为空阻止提交；
- execute/plan 缺失有效默认模板仍显示错误并阻止提交；
- 自由模式 Preview 省略模板并把 `require_changes` 发送为 `false`；
- execute/plan Preview 继续发送当前未保存模板；
- 默认模板 API 中的 `freeform` 不会被 Worker Profile execute 默认模板覆盖。

- [ ] **Step 3：运行失败测试**

```bash
cd frontend
npx vitest run --config vitest.config.ts \
  src/api/tasks.contract.spec.ts \
  src/features/tasks/taskFormModel.spec.ts \
  src/components/TaskFormDrawer.spec.ts
```

- [ ] **Step 4：建立三值前端合同**

统一使用：

```ts
export type TaskMode = 'execute' | 'freeform' | 'plan'
```

避免在 `api/tasks.ts`、表单和组件中各自维持不一致的 inline union；如当前模块边界不允许直接复用，至少由 contract tests 锁定三处完全一致。

- [ ] **Step 5：按模式构建 payload**

- freeform：`require_changes=false`，不发送 `run_instruction_template`；
- execute：发送当前 requirement，模板仅按现有 dirty/更新规则发送；
- plan：`require_changes=false`，模板仍可编辑；
- 更新时把“模式切换”和“模板编辑”分开判断，避免把自由模板带回 execute/plan。

- [ ] **Step 6：调整 Preview composable**

自由模式请求省略模板，其他模式保留模板。Preview 错误、竞态 generation 和取消旧响应的现有行为不变。

- [ ] **Step 7：运行聚焦测试和类型检查**

```bash
cd frontend
npx vitest run --config vitest.config.ts \
  src/api/tasks.contract.spec.ts \
  src/features/tasks/taskFormModel.spec.ts \
  src/components/TaskFormDrawer.spec.ts
npx vue-tsc --noEmit
```

Expected: PASS。

- [ ] **Step 8：提交**

```bash
git add \
  frontend/src/api/tasks.ts \
  frontend/src/api/index.ts \
  frontend/src/api/tasks.contract.spec.ts \
  frontend/src/features/tasks/taskFormModel.ts \
  frontend/src/features/tasks/taskFormModel.spec.ts \
  frontend/src/features/tasks/useTaskFormSubmission.ts \
  frontend/src/features/tasks/useRunInstructionPreview.ts \
  frontend/src/test/mocks/api.ts \
  frontend/src/components/TaskFormDrawer.spec.ts
git commit -m "feat(frontend): add freeform task contracts"
```

---

## Task 8：实现模式优先的新建 Task 抽屉

**Files:**

- Modify: `frontend/src/components/TaskFormDrawer.vue`
- Modify: `frontend/src/components/TaskFormDrawer.spec.ts`
- Modify: `frontend/src/features/tasks/taskFormModel.ts`
- Modify: `frontend/src/features/tasks/taskFormModel.spec.ts`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`
- Modify: `frontend/src/i18n/messages/taskModeCopy.spec.ts`

- [ ] **Step 1：增加失败的入口状态测试**

覆盖：

- 新建抽屉首次打开只显示模式列表，不显示完整表单和 footer；
- 顺序固定为 Freeform → Implementation → Analysis；
- 三种模式都未默认选中；
- 模式默认值、Provider、Worker、Skills 可后台加载但不阻塞列表；
- 点击整行或使用键盘 Enter/Space 立即进入完整表单，没有“下一步”；
- 进入表单后焦点移动到提示词或第一个可编辑控件；
- 关闭再打开时重新要求选择模式。

- [ ] **Step 2：增加失败的完整表单和切换测试**

覆盖：

- 顶部显示当前模式摘要和“更改”；
- “更改”返回模式列表并把焦点移到当前选项；
- 公共字段、Provider/Harness/Skills、调度、会话和滚动位置保持；
- execute 与 plan 的模板和 dirty 状态分别缓存，切回时恢复；
- freeform 不保存可编辑模板草稿，也不误取 execute 默认模板；
- freeform 隐藏要求代码变更和高级运行指令；
- execute 显示 requirement 和高级模板；plan 隐藏 requirement、显示高级模板；
- 编辑 pending/queued Task 直接进入完整表单，不先显示入口；
- 完整表单创建失败时仍停留在表单并保留当前模式。

- [ ] **Step 3：增加失败的清理与可访问性测试**

覆盖：

- 删除“仅用提示词”按钮、`usePromptOnly()` handler 和 Task 表单专用 i18n key；
- 模式列表使用 `radiogroup/radio` 或语义等价控件；
- 每个选项有 `aria-checked`、focus-visible；
- 隐藏界面不会进入 tab 顺序，使用受控 `inert`/`aria-hidden`；
- `prefers-reduced-motion` 下入口/表单和选择动画关闭；
- 390px 下描述自然换行、触摸目标至少 44px、无横向滚动；
- footer 保留现有 safe-area 间距。

- [ ] **Step 4：运行失败测试**

```bash
cd frontend
npx vitest run --config vitest.config.ts \
  src/components/TaskFormDrawer.spec.ts \
  src/features/tasks/taskFormModel.spec.ts \
  src/i18n/messages/taskModeCopy.spec.ts
```

- [ ] **Step 5：实现显式抽屉界面状态**

建立清晰状态，而不是用“taskMode 是否为空”散落推导所有显示行为：

```text
create + mode-choice
create + full-form
edit + full-form
```

完整表单的 refs 和子状态在返回模式入口时保持；不要通过重新创建整个 Drawer 丢失公共字段。footer 只在 full-form 状态挂载。

- [ ] **Step 6：实现每模式草稿**

至少维护：

```text
executeDraft: template + dirty + require_changes
planDraft: template + dirty
freeform: no editable template; require_changes=false
```

切换函数先保存离开模式的专属草稿，再恢复目标模式草稿；公共字段不参与模式切换。提交层只读取当前模式有效字段。

- [ ] **Step 7：重构模式列表与摘要**

- 自由模式排第一并使用独立图标；
- 描述使用设计文档确认的中英文语义；
- 完整表单不再重复展示三张选择卡，只显示紧凑摘要和“更改”；
- 移除 `usePromptOnly()`；System Config 中实施/分析模板编辑器的同名动作不属于本 Task，不要误删。

- [ ] **Step 8：实现焦点、滚动和移动端行为**

使用元素 ref + `nextTick()` 管理进入/返回焦点；保存完整表单滚动位置并在重新选择后恢复。过渡保持单次、轻量，并在 reduced motion 下关闭。

- [ ] **Step 9：运行聚焦测试和构建**

```bash
cd frontend
npx vitest run --config vitest.config.ts \
  src/components/TaskFormDrawer.spec.ts \
  src/features/tasks/taskFormModel.spec.ts \
  src/i18n/messages/taskModeCopy.spec.ts
npm run build
```

Expected: PASS。

- [ ] **Step 10：提交**

```bash
git add \
  frontend/src/components/TaskFormDrawer.vue \
  frontend/src/components/TaskFormDrawer.spec.ts \
  frontend/src/features/tasks/taskFormModel.ts \
  frontend/src/features/tasks/taskFormModel.spec.ts \
  frontend/src/i18n/messages/en.ts \
  frontend/src/i18n/messages/zh-CN.ts \
  frontend/src/i18n/messages/taskModeCopy.spec.ts
git commit -m "feat(frontend): add mode-first task creation"
```

---

## Task 9：补齐自由模式展示和系统统计 UI

**Files:**

- Create: `frontend/src/features/tasks/taskModePresentation.ts`
- Create: `frontend/src/features/tasks/taskModePresentation.spec.ts`
- Modify: `frontend/src/components/TaskMetadataPanel.vue`
- Modify: `frontend/src/components/TaskMetadataPanel.spec.ts`
- Modify: `frontend/src/components/issue-detail/IssueCurrentExecution.vue`
- Modify: `frontend/src/components/issue-detail/IssueCurrentExecution.spec.ts`
- Modify: `frontend/src/views/TaskView.vue`
- Modify: `frontend/src/views/TaskView.spec.ts`
- Modify: `frontend/src/views/SystemStatistics.vue`
- Modify: `frontend/src/views/SystemStatistics.spec.ts`
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1：增加失败的模式展示映射测试**

建立共享、穷尽的展示映射，覆盖：

- execute → Implementation/实施模式；
- freeform → Freeform/自由模式；
- plan → Analysis/分析模式；
- 未知/历史空值 → Unknown，而不是回退为 execute；
- Task View、metadata chip 和 Issue current execution 不再使用“plan 否则 execute”的二元条件。

- [ ] **Step 2：增加失败的统计卡片测试**

覆盖：

- `SystemStatisticsBreakdowns` 类型包含 `task_modes`；
- UI 显示第四张 Task Mode Breakdown；
- 顺序固定为 freeform → execute → plan → Unknown，不按 task_count 排序；
- label 由前端 i18n 映射，后端 raw label 不直接显示为产品文案；
- 表格复用现有 task count、success、deleted、token、changes 列；
- API 没有 `task_modes` 的兼容 mock 不导致页面崩溃；正式新后端响应正常展示。

- [ ] **Step 3：增加失败的响应式测试**

验证布局决策：

- `< 768px` 或当前 stack breakpoint：四张卡单列；
- 足够宽桌面：Project 占整行，其余卡片按两列网格排布；
- 390、768、1440 和宽桌面不产生横向裁切；
- Unknown 和较长中英文模式标签不撑破列宽。

- [ ] **Step 4：运行失败测试**

```bash
cd frontend
npx vitest run --config vitest.config.ts \
  src/features/tasks/taskModePresentation.spec.ts \
  src/components/TaskMetadataPanel.spec.ts \
  src/components/issue-detail/IssueCurrentExecution.spec.ts \
  src/views/TaskView.spec.ts \
  src/views/SystemStatistics.spec.ts
```

- [ ] **Step 5：实现共享展示映射**

`taskModePresentation.ts` 只保存稳定的模式顺序、i18n key、图标/样式语义标识；不复制服务端 canonical 模板，也不在这里决定交付资格。

- [ ] **Step 6：替换所有已知二元展示**

更新 Task metadata、Task detail 和 Issue current execution，使用共享映射显示自由模式。新增 modifier 应复用现有颜色变量，保持克制，不增加新的全局颜色体系。

- [ ] **Step 7：实现 Task Mode Breakdown**

- API 类型新增 `task_modes`；
- 前端按固定模式顺序建立展示 rows，Unknown 放最后；
- 新表复用现有 `breakdownColumns()`；
- Project 继续占整行，Provider/Harness/Task Mode 在响应式网格中稳定排布；
- 新增中英文卡片标题和模式文案。

- [ ] **Step 8：运行聚焦测试和构建**

```bash
cd frontend
npx vitest run --config vitest.config.ts \
  src/features/tasks/taskModePresentation.spec.ts \
  src/components/TaskMetadataPanel.spec.ts \
  src/components/issue-detail/IssueCurrentExecution.spec.ts \
  src/views/TaskView.spec.ts \
  src/views/SystemStatistics.spec.ts
npm run build
```

Expected: PASS。

- [ ] **Step 9：提交**

```bash
git add \
  frontend/src/features/tasks/taskModePresentation.ts \
  frontend/src/features/tasks/taskModePresentation.spec.ts \
  frontend/src/components/TaskMetadataPanel.vue \
  frontend/src/components/TaskMetadataPanel.spec.ts \
  frontend/src/components/issue-detail/IssueCurrentExecution.vue \
  frontend/src/components/issue-detail/IssueCurrentExecution.spec.ts \
  frontend/src/views/TaskView.vue \
  frontend/src/views/TaskView.spec.ts \
  frontend/src/views/SystemStatistics.vue \
  frontend/src/views/SystemStatistics.spec.ts \
  frontend/src/api/index.ts \
  frontend/src/i18n/messages/en.ts \
  frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat(frontend): show freeform tasks and statistics"
```

---

## Task 10：完成集成、真实 Worker smoke 与发布门禁

**Files:**

- Modify: `backend/tests/mock_e2e/test_tasks_e2e.py`
- Modify: `backend/tests/e2e/tests/test_issue_view.py`
- Verify/Modify: `backend/tests/gitlab_e2e/test_manual_task.py`
- Verify all files above

- [ ] **Step 1：增加 Mock E2E 创建流程**

覆盖：

- 打开新建 Task 后只看到三种模式；
- 选择自由模式进入完整表单；
- 返回模式列表后公共字段保留；
- 创建请求和详情返回 `task_mode=freeform`；
- execute/plan 旧流程仍可创建和编辑；
- Task Mode Breakdown 能在管理员统计页加载。

- [ ] **Step 2：增加浏览器响应式检查**

至少运行：

```text
390 x 844
768 x 1024
1440 x 900
宽桌面视口
```

确认模式说明完整换行、触摸目标、焦点顺序、底部安全区、返回后的滚动位置，以及四张 Breakdown 不横向裁切。保留必要截图作为本次实施证据，不把临时截图提交到仓库。

- [ ] **Step 3：运行 Backend 聚焦回归**

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_task_freeform_mode_migration.py \
  tests/unit/test_task_prompt.py \
  tests/unit/test_task_prompt_api.py \
  tests/unit/test_task_api_contract.py \
  tests/unit/test_tasks_api.py \
  tests/unit/test_update_task_api.py \
  tests/unit/test_ci_failure_collector.py \
  tests/unit/test_worker_freeform_delivery.py \
  tests/unit/test_worker_profile_runtime.py \
  tests/unit/test_system_lifecycle_statistics.py \
  tests/unit/test_system_lifecycle_statistics_pg.py -q
```

Expected: PASS。

- [ ] **Step 4：运行 Frontend 聚焦回归和构建**

```bash
cd frontend
npx vitest run --config vitest.config.ts \
  src/api/tasks.contract.spec.ts \
  src/features/tasks/taskFormModel.spec.ts \
  src/features/tasks/taskModePresentation.spec.ts \
  src/components/TaskFormDrawer.spec.ts \
  src/components/TaskMetadataPanel.spec.ts \
  src/components/issue-detail/IssueCurrentExecution.spec.ts \
  src/views/TaskView.spec.ts \
  src/views/SystemStatistics.spec.ts \
  src/i18n/messages/taskModeCopy.spec.ts
npm run build
```

Expected: PASS。

- [ ] **Step 5：运行迁移往返验证**

在一次性 PostgreSQL 测试数据库中：

```bash
cd backend
.venv/bin/alembic heads
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1
.venv/bin/alembic upgrade head
```

验证 upgrade 接受三值并拒绝其他值；downgrade 前的自由 Task 被映射为 `execute + require_changes=false`，随后能恢复二值约束。不要在共享或生产数据库上执行 downgrade smoke。

- [ ] **Step 6：运行 Mock E2E 和静态检查**

```bash
make test-mock-e2e
git diff --check
```

如实施修改了 Worker shell，再运行：

```bash
bash -n deploy/worker-entrypoint/main.sh
bash -n deploy/worker-entrypoint/gitlab.sh
```

同时审计所有剩余二值假设：

```bash
rg -n \
  "Literal\[\"execute\", \"plan\"\]|'execute' \| 'plan'|task_mode != \"plan\"|task_mode === 'plan'" \
  backend frontend deploy
```

Expected: 每个命中都被人工分类。允许保留的只能是经过确认的专用分支，例如 Worker 中“只有 plan 丢弃修改”；请求 schema、展示标签、Issue/CI 交付判断不得残留二值回退。

- [ ] **Step 7：冻结 Runtime Bundle 并执行真实 Worker 矩阵**

Claude 和 Codex 各执行以下场景：

1. `freeform + continue + 无文件变化`：Task completed、`commit_sha=NULL`、Issue 状态正确、运行前后 MR 快照完全一致；
2. `freeform + fresh + 有文件变化`：生成 commit 并 push，之后创建/复用 MR、持久化 Issue 关联、更新描述并 Ready；
3. 已有 MR 的无变化自由 Follow-Up：不改 MR 标题、描述或 Draft/Ready；
4. 自由 Task 失败、取消或 timeout：不发生错误的 MR 交付；
5. execute 和 plan 各一条回归，确认旧模式时序没有被延迟 MR 分支影响；
6. 默认 Skills、Task Skills、Provider system prompt、session start/resume 和 canonical events 仍存在。

真实验证必须使用待发布的 Backend、Frontend、Worker image、Worker Kit 和 Runtime Bundle，不得只运行本地 shell 或 Adapter fixture。

- [ ] **Step 8：验证 CI 与统计 canary**

- 活动 freeform 阻止同 Issue CI auto-repair；
- 无提交 freeform 不重置尝试窗口；有提交 freeform 可以成为最近手动交付；
- Task Mode Breakdown 同时出现 retained/deleted 数据并响应 project/provider/harness/data_state 过滤；
- freeform 的代码指标 known/unknown 口径与设计一致。

- [ ] **Step 9：运行全量门禁**

```bash
make test-backend
make test-frontend
```

根据发布环境可用性继续运行：

```bash
make test-e2e-ui
make test-e2e-gitlab
```

- [ ] **Step 10：提交集成测试改动**

```bash
git add \
  backend/tests/mock_e2e/test_tasks_e2e.py \
  backend/tests/e2e/tests/test_issue_view.py
git commit -m "test(tasks): cover freeform task workflows"
```

仅在 GitLab E2E 文件实际增加自动化覆盖时加入 `backend/tests/gitlab_e2e/test_manual_task.py`。

---

## 发布顺序

```text
1. 确认 Alembic 单 head，并备份数据库
2. 部署 task_mode 三值约束迁移
3. 部署 Backend 与 Scheduler
4. 部署匹配的 Worker image / Worker Kit / Runtime Bundle
5. 部署 Frontend
6. 执行 Claude/Codex 有变更与无变更 canary
7. 验证 Issue、CI、MR 和 Task Mode Breakdown
8. 开放给全部用户
```

Backend 与 Frontend 应在同一维护窗口更新；短暂混部期间旧前端可能把 `freeform` 错误显示为 execute，因此不要把混部状态作为稳定运行方式。

## 回滚边界

- 回滚应用前，先停止 Scheduler 接收新自由 Task。
- 数据库 downgrade 会把现有 `freeform` 映射为 `execute + require_changes=false`；这是有意的降级语义损失。
- Backend、Frontend 与 Worker 应成组回滚，避免旧 Worker 获得未知模式或新前端调用旧 Preview 合同。
- 已 push 但尚未创建 MR 的 commit 不得删除；保留 `commit_sha` 和诊断日志，人工或后续重试可恢复 MR 交付。
- 不删除已有自由 Task 的 Prompt、事件、日志、usage、Skill 或 Runtime Snapshot。

## 完成定义

- [ ] 数据库、API 和所有前端类型正式支持 `execute/freeform/plan`。
- [ ] 自由模式的 canonical 模板和 `require_changes=false` 由服务端保证。
- [ ] Create、Update、Retry、Preview 和默认模板 API 的三值契约有自动化测试。
- [ ] 无提交自由 Task 正常完成且没有任何 MR 副作用。
- [ ] 有提交自由 Task 在 push 后完成 MR 交付。
- [ ] Issue 和 CI 规则只对 freeform 增加 `commit_sha` 条件，execute 语义无回归。
- [ ] 系统统计新增 Task Mode Breakdown，并正确处理删除归档、筛选和代码指标已知性。
- [ ] 新建 Task 抽屉先选模式、无默认选择、编辑直达完整表单，移动端与键盘可用。
- [ ] Task 详情、当前执行和统计不再把未知非 plan 模式回退为 execute。
- [ ] Claude 与 Codex 的真实 Worker smoke 覆盖有变更、无变更和已有 MR 场景。
- [ ] 聚焦测试、全量 Backend/Frontend、构建、迁移往返和 `git diff --check` 全部通过。
