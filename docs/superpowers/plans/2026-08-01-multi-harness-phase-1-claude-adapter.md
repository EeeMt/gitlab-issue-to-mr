# Phase 1：Claude Adapter 无回归抽取实施计划

> 上级计划：[Codify 多 Harness 引擎分阶段实施总计划](2026-08-01-multi-harness-engine-roadmap.md)
> 前置产物：[Phase 0 协议探针与样本采集](2026-08-01-multi-harness-phase-0-protocol-probes.md)

**目标：** 将现有 Claude Code 命令、事件、session、权限、Skills、usage 和进程管理逻辑封装进 Claude Adapter；Worker Entrypoint 和 Backend 只依赖 Harness 合同与 Canonical Event，同时保持现有 Claude 行为不变。

**周期：** Phase 0 后增量 4–6 人日。

**核心约束：** 这是协议替换，不是功能改写。除事件文件从 raw 变为 canonical、raw 输出另行归档外，Claude 新任务、resume、Git/MR、Skills、CodeGraph、取消、timeout 和 UI 时间线必须无回归。

---

## 1. 实现选择

本计划固定以下落地方式，避免在实施中反复摇摆：

- Worker 公共编排继续使用 Bash；每个 Adapter 使用独立目录和脚本，复杂事件转换使用独立 Python translator。
- `event.jsonl` 改为 Canonical Event；Claude 原始 `stream-json` 原样清洗后写入 `harness-events/claude.jsonl`。
- 公共 runner 只调用 Adapter 合同，不检查 Harness 名称；Claude 专有环境变量和参数只存在于 Claude Adapter。
- 编排脚本、Adapter、协议文件组成内容寻址的 Runtime Bundle。新 Task 创建时冻结并绑定 bundle digest，执行、scheduler 重启和 retry 复用相同 bundle；仅迁移前遗留 Task 允许首次执行时兼容冻结一次。
- Runtime Bundle manifest 是实际执行的 Adapter version/digest、event schema 和 orchestration version 的唯一事实源；Worker Kit manifest 只声明 bootstrap、Runtime Bundle 合同和 CLI runtime 的兼容范围。
- Worker Kit launcher 仍提供可信工具和最小 bootstrap；实际任务编排从已冻结的 `/tmp/codify-runtime/orchestration/` 启动。
- 当前一个 Task 对应一个执行 attempt；scheduler 对同一容器的 crash resume 继续使用同一 `attempt_id`，retry 创建新 Task 和新 attempt，但复用原 Runtime Bundle 与 Task Snapshot。

---

## 2. 文件规划

### 数据模型与 Backend

- Create: `backend/alembic/versions/063_harness_attempts_and_runtime_bundles.py` — attempt、bundle 及 ingest 幂等字段。
- Modify: `backend/app/models.py` — `WorkerRuntimeBundle`、`TaskHarnessAttempt` 及 Task bundle 关系。
- Create: `backend/app/core/worker_runtime_bundle.py` — 确定性打包、digest 去重、首次冻结和 retry 复用。
- Modify: `backend/app/core/harness_protocol.py` — 使用 Phase 0 的可执行协议。
- Create: `backend/app/core/harness_attempts.py` — attempt 创建、seq/terminal 幂等门禁。
- Rewrite: `backend/app/core/worker_event_projector.py` — 仅投影 Canonical Event。
- Modify: `backend/app/core/task_event_archive.py` — canonical 与 raw artifact 路径。
- Modify: `backend/app/core/worker_runtime.py` — Runtime Bundle 和 task input 分层打包。
- Modify: `backend/app/core/worker_task_lifecycle.py` — 冻结/注入 bundle、复用 attempt。
- Modify: `backend/app/core/worker_results.py` — 从 Canonical Result 读取 session/model/usage/failure。
- Modify: `backend/app/api/task_creation_service.py` — 新 Task 创建时绑定 bundle；retry 复制原 Worker Snapshot 并复用 bundle 引用。
- Modify: `deploy/Dockerfile.backend` — 将受控 runtime source 放入 scheduler/backend 镜像。

### Worker 公共层与 Claude Adapter

- Create: `deploy/worker-entrypoint/harness/runner.sh` — 公共 Harness 生命周期。
- Create: `deploy/worker-entrypoint/harness/common.sh` — 目录、事件、结果、进程组和 diagnostic 公共函数。
- Create: `deploy/worker-entrypoint/harness/adapters/claude.sh` — Claude metadata/verify/config/command/session/skills/run_text。
- Create: `deploy/worker-entrypoint/harness/adapters/claude_events.py` — raw Claude → Canonical Event/Result。
- Create: `deploy/worker-entrypoint/harness/manifest.json` — Runtime Bundle 中实际 Adapter version/digest、provider protocols、event schema 和 capability。
- Modify: `deploy/worker-entrypoint/main.sh` — 调用公共 runner，不直接运行 Claude。
- Modify: `deploy/worker-entrypoint/bootstrap.sh` — 创建 canonical/raw/result/artifact 目录。
- Modify: `deploy/worker-entrypoint/task-environment.sh` — 将 Claude home 处理移入 Adapter。
- Modify: `deploy/worker-entrypoint/verification.sh` — 委托 Adapter runtime verification。
- Modify: `deploy/entrypoint.worker.sh` — 暴露公共 runner 路径。
- Modify: `deploy/ci-claude.sh` — 先保留为 Claude Adapter 内部兼容实现，移除其公共协议职责。
- Modify: `deploy/Dockerfile.worker-kit` — 只打包 launcher、兼容性 manifest 和验证工具，不复制实际执行的 Adapter。

### 测试

- Create: `backend/tests/unit/test_harness_attempts.py`
- Create: `backend/tests/unit/test_worker_runtime_bundle.py`
- Create: `backend/tests/unit/test_claude_harness_adapter.py`
- Modify: `backend/tests/unit/test_ci_claude_script.py`
- Modify: `backend/tests/unit/test_worker_archive_streaming.py`
- Modify: `backend/tests/unit/test_task_event_archive.py`
- Rewrite/Modify: `backend/tests/unit/test_worker_payload_storage.py`
- Modify: `backend/tests/unit/test_worker_new_patterns.py`
- Modify: `backend/tests/unit/test_worker_coverage.py`
- Modify: `backend/tests/unit/test_worker_coverage_ext.py`
- Modify: `backend/tests/mock_integration/test_entrypoint.py`
- Modify: `backend/tests/mock_integration/test_entrypoint_paths.py`
- Modify: `backend/tests/mock_integration/fake_claude/Dockerfile.worker-test`
- Modify: `frontend/src/components/TaskProcessPanel.spec.ts`
- Modify: `frontend/src/views/TaskView.spec.ts`

---

## 3. 任务拆分

### Task 1.1：增加 attempt 与 Runtime Bundle 持久化原语

**Files:** migration、`models.py`、`harness_attempts.py`、`worker_runtime_bundle.py` 及对应测试。

- [ ] 先写迁移和模型失败测试；建议迁移号基于当前 head 使用 `063`，实施前重新确认 Alembic head。
- [ ] `WorkerRuntimeBundle` 使用 SHA-256 唯一 digest 去重，保存 bundle bytes、contract version、orchestration version、manifest、size 和创建时间；内容不含任务 prompt、Skills 或凭据。
- [ ] Task 保存 bundle 外键；同一代码版本的任务共享 bundle，retry 原样复制源任务引用。
- [ ] `TaskHarnessAttempt` 保存不可变 `attempt_id`、task、attempt number、event schema、harness key、Adapter/CLI 版本、last seq、Task terminal event ID/type 和时间戳。
- [ ] 数据库约束保证 `(task_id, attempt_no)` 唯一、`attempt_id` 唯一、每个 attempt 只有一个 Task terminal 状态。
- [ ] TaskIngestCursor 与 attempt 绑定，不能把旧 attempt offset/seq 用于新 attempt。
- [ ] migration downgrade 不丢失现有 Task/Log/Archive 数据；旧 Task 的新字段可空，兼容历史只读记录。
- [ ] 新增显式的 Worker Snapshot clone helper；retry 不再从当前可编辑 Profile 重建 image、Kit、Docker target、环境变量、脚本或 Skills，只复制源 Task 已冻结值并生成新的 task-owned snapshot rows。

**验证：**

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_harness_attempts.py \
  tests/unit/test_worker_runtime_bundle.py -v
```

迁移往返只能在本次测试创建的一次性 PostgreSQL 数据库执行，禁止沿用开发、共享或生产 `DATABASE_URL`：

```bash
cd backend
CODIFY_MIGRATION_TEST_DATABASE_URL='postgresql+asyncpg://codify:codify@127.0.0.1:55432/codify_migration_test'
DATABASE_URL="$CODIFY_MIGRATION_TEST_DATABASE_URL" .venv/bin/alembic upgrade head
DATABASE_URL="$CODIFY_MIGRATION_TEST_DATABASE_URL" .venv/bin/alembic downgrade 062_task_skills
DATABASE_URL="$CODIFY_MIGRATION_TEST_DATABASE_URL" .venv/bin/alembic upgrade head
```

执行前必须由 migration test fixture/container 创建空数据库，执行后销毁；测试脚本应拒绝未显式提供 `CODIFY_MIGRATION_TEST_DATABASE_URL` 的调用。

### Task 1.2：构建确定性 Runtime Bundle

**Files:** `worker_runtime_bundle.py`、`worker_runtime.py`、`worker_task_lifecycle.py`、`Dockerfile.backend`。

- [ ] 将公共 entrypoint、Claude Adapter、translator、Runtime Bundle manifest 和协议版本文件作为受控 runtime source 复制到 Backend/Scheduler 镜像。
- [ ] Runtime Bundle manifest 写入每个受控文件的 SHA-256、实际 Adapter version/digest、event schema 和 orchestration version；bundle digest 覆盖该 manifest。
- [ ] 确定性打包固定文件顺序、mode、uid/gid 和 mtime；相同源码必须产生相同 digest。
- [ ] 创建新 Task 时事务性地 `get-or-create` bundle，并与 Task Snapshot 一起绑定；Task 入队或容器创建失败后仍保留该绑定。
- [ ] task input bundle 继续单独包含 prompt、artifact policy、用户 pre/post script、previous summaries、Skills 和 CI failure bundle。
- [ ] 通过 Docker API 分别注入 orchestration bundle 和 task input，不依赖 Backend 本地 bind path。
- [ ] retry：源 Task 已有 bundle 时直接复用；迁移前源 Task 从未执行且无 bundle 时，创建 retry Task 的事务中冻结当时 bundle，并记录 `legacy_bundle_backfill` 兼容例外。
- [ ] scheduler crash resume 从数据库和容器 runtime manifest 核对 digest，不重新生成或替换 bundle。
- [ ] Worker Kit compatibility manifest 只声明可接受的 runtime contract/event schema 范围和 bootstrap/CLI runtime 能力；不得作为执行 Adapter 版本的事实源。
- [ ] 运行时发现 bundle manifest、Kit compatibility range 或容器中文件 digest 任一不匹配，立即 `protocol_error`，不能退回 Kit 当前脚本。

### Task 1.3：建立公共 runner 与 Claude Adapter 合同

**Files:** `deploy/worker-entrypoint/harness/**`、`entrypoint.worker.sh`、`verification.sh`。

- [ ] 为公共 runner 写 fake Adapter 契约测试，覆盖 metadata、verify、prepare、build、stream、normalize、terminate 和可选 run_text。
- [ ] runner 生成 `attempt_id`/seq 外壳，Adapter translator 只返回事件类型和 payload；`event_id`、时间、task/harness metadata 在统一位置生成。
- [ ] Claude Adapter 从现有 `ci-claude.sh` 迁移命令、`--bare`/settings、权限、model/max turns、resume、Skills `--add-dir` 和 CLI 版本检查。
- [ ] runner 对未知 capability 忽略，对请求但不支持的 capability 按 contract 拒绝或 warning。
- [ ] runner 统一处理 stdout/stderr、进程组、TERM/KILL、timeout 和取消；Claude 专有 final-result stream watchdog 保留在 Adapter hook。
- [ ] `verification.sh` 不再引用 `CODIFY_CLAUDE_BIN` 作为公共必需项，而是调用选中 Adapter 的 `verify_runtime`。
- [ ] `ci-claude.sh` 只作为 Claude 内部兼容层；公共 main/Backend 不得直接调用它。

**验证：**

```bash
bash -n deploy/worker-entrypoint/harness/runner.sh
bash -n deploy/worker-entrypoint/harness/adapters/claude.sh
cd backend
.venv/bin/python -m pytest tests/unit/test_claude_harness_adapter.py -v
```

### Task 1.4：输出 canonical、raw 和统一 result artifacts

**Files:** `bootstrap.sh`、`runtime.sh`、Claude translator、`task_event_archive.py`、archive tests。

- [ ] runtime 目录初始化 `event.jsonl`、`harness-events/claude.jsonl`、`harness-result.json`、`runtime.json` 和 `console.log`。
- [ ] 每个 Claude raw line 先经敏感信息清洗再写 raw archive，并记录可稳定引用的 line number。
- [ ] translator 依据 Phase 0 fixture 产生 Canonical Event；Claude result 只映射为非 terminal 的 `harness.completed/failed`，未知 raw event 产生 diagnostic，不直接失败。
- [ ] 公共交付层在 Harness 成功后输出 `delivery.started` 以及 `delivery.completed/failed`；commit、Push 或 MR 失败必须保留 Harness 成功证据，但最终 Task 失败。
- [ ] `worker.finalization` 记录清理、信号和最终 exit state；公共 runner 在其后输出唯一且最后的 Task terminal `run.completed/run.failed`。
- [ ] EOF 校验缺 init/Task terminal、seq 缺口、双 Task terminal、terminal 后追加；失败按完整 Harness + delivery + finalization 状态输出统一 failure taxonomy。
- [ ] `harness-result.json` 使用统一结果结构；cost/usage 未知值保留 `null`。
- [ ] runtime archive 同时保留 Harness、delivery、finalization 和 Task terminal 证据，离线 replay 必须能还原与数据库一致的最终 Task 状态。
- [ ] runtime archive 同时包含 canonical、raw、result、runtime、console 和现有 artifact；下载权限与保留策略不变。

### Task 1.5：将 Backend Projector 改为 Canonical Event 投影

**Files:** `worker_event_projector.py`、`harness_protocol.py`、`harness_attempts.py` 和投影测试。

- [ ] 删除/迁移 Projector 对 `system`、`assistant`、`user`、`result`、`stream_event` 的分支；这些映射只存在 Claude translator。
- [ ] Projector 先验证 envelope、attempt 和 seq，再投影 `TaskLog`/`TaskPayload`。
- [ ] `message.delta`/`reasoning_summary.delta` 在内存和有界 artifact 中聚合，数据库只存 completed message/summary 或有界更新。
- [ ] `tool.started`/`tool.completed` 按 canonical tool ID 关联，重复投递不重复创建 payload/log。
- [ ] `usage.updated` 可更新临时状态，只有 `usage.final` 进入最终 Task/ledger；缺失字段不写零。
- [ ] unknown diagnostic 只记录版本和 raw ref；协议不变量失败才终止任务。
- [ ] 对同一 fixture 重放两次、scheduler 重启后回放、截断后续写、乱序和 Task terminal 冲突写数据库级测试。

### Task 1.6：统一结果、session 和 UI 时间线，保持 Claude 行为

**Files:** `worker_results.py`、`worker_task_lifecycle.py`、`task_helpers.py`、前端现有 Task Process tests。

- [ ] Task model 现有 `input_session_id`、`output_session_id` 和 `Issue.claude_session_id` 在 Phase 1 保持行为不变；Phase 2 才迁移多 Harness session 表。
- [ ] `parse_task_result` 只从 canonical `run.*`、`harness.*`、`delivery.*`、`model.resolved`、`usage.final`、`worker.finalization` 投影读取数据；最终状态只接受唯一 Task terminal。
- [ ] completed/failed/cancelled/protocol_error、Harness 结果、delivery 结果与进程退出码的优先规则有测试；不能仅以 Harness 成功或 exit code 0 判成功。
- [ ] 前端仍收到现有稳定 `TaskLog` 类型；如 canonical 增加 diagnostic/capability warning，只增加兼容展示，不暴露 raw Claude 结构。
- [ ] 隐藏 thinking/reasoning 内容不进入数据库；仅 reasoning summary 映射到允许展示的现有 UI 类型。
- [ ] Claude usage、model、session、commit、diff、MR 和归档结果与基线 fixture 对比一致。

### Task 1.7：迁移辅助 Claude 调用但不改变输出策略

**Files:** `main.sh`、`delivery.sh`、Claude Adapter 及相关 mock tests。

- [ ] 提交信息、整体交付摘要和 Mermaid 修复不再直接执行 `CODIFY_CLAUDE_BIN`，统一调用 Adapter `run_text`。
- [ ] Phase 1 的 Claude Adapter `run_text` 保留现有模型、timeout、无 session 和结果清洗行为。
- [ ] 公共层实现确定性 fallback，但 Phase 1 基线测试确认 Claude `run_text` 正常时输出路径不变。
- [ ] CodeGraph 继续由 Claude capability 声明为 true，公共 main 不按 Harness 名称判断。

### Task 1.8：Worker Kit、mock integration 与真实 Claude 回归

**Files:** Worker Kit Dockerfile/manifest/export/verify docs 和相关 tests。

- [ ] 发布新的不可变 Worker Kit 版本，不覆盖 `0.3.6`；Kit manifest 写入 bootstrap version、支持的 Runtime Bundle contract/event schema 范围、CLI runtime 约束和 Kit capability，不另行声明“实际执行 Adapter 版本”。
- [ ] verify-runtime 从 Runtime Bundle manifest 读取实际 Adapter version/digest，并校验 Kit compatibility、Claude CLI、translator、canonical fixture replay、Skills 和项目 smoke。
- [ ] fake Claude 覆盖普通成功、工具失败、resume、invalid resume、final-result hang、timeout、SIGTERM/SIGKILL。
- [ ] mock integration 检查 `event.jsonl` 不含 raw Claude type，`harness-events/claude.jsonl` 可审计且已清洗。
- [ ] 在至少一个真实目标 Docker Host 上运行 Claude 新任务、resume、Skills、取消和 Git/MR smoke；这一步是 Phase 2 入口门禁，不等同多 Host 生产灰度。

**阶段测试：**

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_harness_protocol.py \
  tests/unit/test_harness_attempts.py \
  tests/unit/test_worker_runtime_bundle.py \
  tests/unit/test_claude_harness_adapter.py \
  tests/unit/test_ci_claude_script.py \
  tests/unit/test_worker_archive_streaming.py \
  tests/unit/test_task_event_archive.py \
  tests/unit/test_worker_payload_storage.py \
  tests/unit/test_worker_new_patterns.py \
  tests/mock_integration/test_entrypoint.py \
  tests/mock_integration/test_entrypoint_paths.py -v
```

```bash
cd frontend
npx vitest run src/components/TaskProcessPanel.spec.ts src/views/TaskView.spec.ts
```

```bash
make test-mock-e2e
```

```bash
make test-backend
```

---

## 4. Phase 1 退出门禁

- [ ] Backend/Frontend 搜索不到对 Claude raw event type/subtype 的业务分支。
- [ ] 公共 Worker main、delivery 和 verification 不直接执行 Claude 二进制。
- [ ] Claude raw fixture 与 real smoke 均生成合法 Canonical Event/Result。
- [ ] Harness 成功但 Git/MR 交付失败时最终 Task 为 failed；离线 replay 与数据库状态一致。
- [ ] 重复、乱序、缺口、双 Task terminal、terminal 后追加和无 Task terminal 的数据库行为符合合同。
- [ ] Runtime Bundle digest 在 Task 创建、首次运行、scheduler resume 和 retry 中保持正确；新建 Task 不存在未绑定 bundle 的窗口。
- [ ] Runtime Bundle manifest 中的 Adapter digest 是执行事实，Kit compatibility manifest 与其兼容且不存在双重版本事实源。
- [ ] Claude 的新任务、resume、fresh、Skills、CodeGraph、辅助调用、取消、timeout、Git/MR 和 archive 无回归。
- [ ] 新 Kit 已导出、校验并在至少一个真实 Host 安装；源码测试和 Host smoke 证据分别记录。

未通过上述任一项时，不开始 Codex Adapter 或前端 Harness 选择器开发。
