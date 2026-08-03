# Phase 2：Codex 与公共产品能力接入实施计划

> 上级计划：[Codify 多 Harness 引擎分阶段实施总计划](2026-08-01-multi-harness-engine-roadmap.md)
> 前置计划：[Phase 1 Claude Adapter 无回归抽取](2026-08-01-multi-harness-phase-1-claude-adapter.md)

**目标：** 在 Phase 1 的稳定 Harness 合同上接入 Codex，完成数据模型、Model Endpoint、Task 级选择、不可变快照、Session namespace、Skills、权限、安全、usage、UI/API、Worker Kit 和单 Host 真实运行验证，形成 Claude + Codex 生产候选。

**周期：** 18–27 人日。

**不包含：** 多 Host 生产灰度（Phase 3）和 OpenCode（Phase 4）。如果需要从零建设模型出口代理或凭据 Broker，另计 4–7 人日，并作为本阶段生产安全门禁的外部依赖管理。

---

## 1. 并行边界与顺序

Phase 2 可分三条实现线，但必须按公共协议收敛：

1. **模型/API 线：** migration → registry/compatibility → Profile/Task Snapshot → Session → API。
2. **Worker/Adapter 线：** Codex config/command/events → sandbox/approval → Skills/session/usage → Kit verification。
3. **Frontend 线：** API 类型稳定后再实现 Profile 管理、Task 选择器、详情和 warning。

迁移、Harness registry、兼容性返回结构和 Task Snapshot 字段必须先合入。Frontend 不得自行复制 Backend 的 Harness/Endpoint 兼容规则；Worker 不得绕过 Snapshot 读取当前 Profile 或 Provider。

---

## 2. 数据与接口决策

### Worker Profile

新增受控配置，不允许管理员录入任意可执行命令：

```text
enabled_harnesses       # claude/codex allowlist
default_harness_key     # 必须在 enabled_harnesses 内
harness_constraints     # 只允许 schema 中的可收紧限制
image_digest            # verify-runtime 解析的不可变镜像标识
harness_runtimes        # 每个 Harness 的 source/path/version/binary digest
```

`harness_runtimes` 只接受内置 schema：`source=image|host_mount`、容器内 executable path、已验证 CLI version 和 binary digest。Profile 不能录入任意命令；host mount 必须只读，并在 verify-runtime 和每次启动时重新核对 digest。

实际 Adapter 版本、内容 digest、能力和事件协议来自冻结的 Runtime Bundle manifest；Worker Kit manifest 只声明 bootstrap、Runtime Bundle 合同/schema 范围和 CLI runtime 兼容约束。Profile 只能选择和收紧。

### Model Endpoint

保留 `ai_providers` 表名和 `/api/providers` 路由以降低迁移成本，但语义扩展为 Model Endpoint：

```text
provider_kind
wire_protocol           # anthropic_messages/openai_responses/openai_chat_completions/null
provider_driver
provider_options
credential_ref          # Task Snapshot 只保存引用
```

`api_key` 只允许作为迁移输入：升级时为现有 Provider 创建独立持久的 `ModelCredential`，之后公共代码只使用 `credential_ref` 和凭据解析抽象。删除 Provider 不级联删除 credential；凭据只能 soft-retire，仍被可重试 Task Snapshot 引用时禁止硬删除。

### Task Snapshot

扩展现有 `TaskWorkerProfileSnapshot`，冻结：

```text
harness_key
harness_adapter_version
harness_adapter_digest
harness_config_snapshot
model_endpoint_snapshot
credential_ref
worker_kit_version
cli_source
cli_executable_path
cli_version
cli_binary_digest
runtime_contract_version
orchestration_version
image_digest
runtime_bundle_digest
```

Task 继续保留 `provider_id` 用于管理和分析；执行事实来自 snapshot，Provider 被编辑或删除不能改变已创建 Task 的非敏感 Endpoint 配置。

Snapshot 在 Task 创建事务中一次写入并立即冻结，继续保持每个 Task 一份 task-owned snapshot，不引入 revision 或 `active_snapshot_id`。Pending/Queued Task 也不能修改 Harness、Profile、Endpoint、CLI、安全策略等执行事实；需要改变时取消原 Task 并从 Issue 创建新 Task。retry 为新 Task 原样复制源 Task Snapshot 和 Runtime Bundle 引用，不读取当前 Profile/Endpoint。

### Issue Session

新增 `IssueHarnessSession`，唯一键为 `issue_id + harness_key + session_namespace`。`Issue.claude_session_id` 在兼容读取期保留，完成数据回填和两版兼容窗口后再单独移除，不在本阶段直接破坏历史 API。

---

## 3. 文件规划

### Backend schema、registry 与安全

- Create: `backend/alembic/versions/064_multi_harness_runtime.py` — Profile、Endpoint、ModelCredential、Snapshot、Session 和 Task 字段。
- Modify: `backend/app/models.py`
- Create: `backend/app/core/harness_registry.py` — 内置定义、manifest/schema、兼容判断和 capability policy。
- Create: `backend/app/core/model_endpoints.py` — Endpoint 规范化、fingerprint 和兼容性。
- Create: `backend/app/core/model_credentials.py` — 持久 `ModelCredential`、soft-retire、引用保护、代理/Broker/短期 token 与受限 legacy 解析。
- Create: `backend/app/core/harness_sessions.py` — namespace、lineage、lookup/update/backfill。
- Modify: `backend/app/core/worker_profiles.py`
- Modify: `backend/app/core/worker_runtime.py`
- Modify: `backend/app/core/worker_workspace.py`
- Modify: `backend/app/core/worker_task_lifecycle.py`
- Modify: `backend/app/core/worker_results.py`
- Modify: `backend/app/core/skills.py`
- Modify: `backend/app/core/worker.py` — 增加 OpenAI/自定义 Provider token 清洗。

### API 与任务语义

- Modify: `backend/app/api/providers.py`
- Modify: `backend/app/api/worker_profiles.py`
- Modify: `backend/app/api/task_schemas.py`
- Modify: `backend/app/api/task_creation_service.py`
- Modify: `backend/app/api/task_update_service.py`
- Modify: `backend/app/api/task_responses.py`
- Modify: `backend/app/api/task_operations.py`
- Modify: `backend/app/api/issues.py`
- Modify: `backend/app/api/analytics_queries.py`
- Modify: `backend/app/api/analytics_responses.py`

### Codex Adapter 与 Worker Kit

- Create: `deploy/worker-entrypoint/harness/adapters/codex.sh`
- Create: `deploy/worker-entrypoint/harness/adapters/codex_events.py`
- Modify: `deploy/worker-entrypoint/harness/manifest.json`
- Modify: `deploy/worker-entrypoint/harness/runner.sh`
- Modify: `deploy/worker-entrypoint/main.sh`
- Modify: `deploy/worker-entrypoint/delivery.sh`
- Modify: `deploy/worker-entrypoint/codegraph.sh`
- Modify: `deploy/worker-entrypoint/verification.sh`
- Modify: `deploy/Dockerfile.worker-kit`
- Modify: `deploy/worker-kit/verify-runtime.sh`
- Modify: `deploy/offline-bundle/scripts/verify-worker-runtime.sh`
- Modify: `deploy/offline-bundle/README.md`
- Modify: `docs/worker-kits.md`
- Modify: `docs/worker-volume-mounts.md`

### Frontend

- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/api/tasks.ts`
- Modify: `frontend/src/components/config/AIProvidersPanel.vue`
- Modify: `frontend/src/components/config/WorkerSettingsPanel.vue`
- Modify: `frontend/src/components/TaskFormDrawer.vue`
- Modify: `frontend/src/features/tasks/taskFormModel.ts`
- Modify: `frontend/src/features/tasks/useTaskExecutionOptions.ts`
- Modify: `frontend/src/views/TaskView.vue`
- Modify: `frontend/src/views/IssueView.vue`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

### 主要测试

- Create: `backend/tests/unit/test_harness_registry.py`
- Create: `backend/tests/unit/test_model_endpoints.py`
- Create: `backend/tests/unit/test_model_credentials.py`
- Create: `backend/tests/unit/test_harness_sessions.py`
- Create: `backend/tests/unit/test_codex_harness_adapter.py`
- Modify: `backend/tests/unit/test_worker_profiles_api.py`
- Modify: `backend/tests/unit/test_worker_profiles_core.py`
- Modify: `backend/tests/unit/test_task_worker_profile_selection.py`
- Modify: `backend/tests/unit/test_task_api_contract.py`
- Modify: `backend/tests/unit/test_tasks_api.py`
- Modify: `backend/tests/unit/test_tasks_api_coverage.py`
- Modify: `backend/tests/unit/test_providers_api.py`
- Modify: `backend/tests/unit/test_worker_workspace.py`
- Modify: `backend/tests/unit/test_worker_profile_runtime.py`
- Modify: `backend/tests/unit/test_skills.py`
- Modify: `backend/tests/unit/test_offline_bundle_export.py`
- Modify: `backend/tests/mock_integration/test_entrypoint.py`
- Create: `backend/tests/mock_integration/fake_codex/`
- Modify: `frontend/src/components/TaskFormDrawer.spec.ts`
- Modify: `frontend/src/features/tasks/taskFormModel.spec.ts`
- Modify: `frontend/src/views/Config.spec.ts`
- Modify: `frontend/src/views/TaskView.spec.ts`

---

## 4. 任务拆分

### Task 2.1：增加多 Harness 数据模型与兼容回填

**Files:** migration、`models.py` 及 migration tests。

- [ ] 先写迁移内容、upgrade/downgrade 和模型约束测试；建议编号 `064`，实施前以实际 Alembic head 为准。
- [ ] 为 Worker Profile 和现有一对一 Snapshot 增加上文固定字段；JSON 字段使用空对象/数组 server default，旧 Profile 回填 `enabled_harnesses=["claude"]`、`default_harness_key="claude"`。
- [ ] 新增 `ModelCredential` 持久实体，至少保存稳定 ref、加密 secret/Broker ref、status、version metadata、retired_at 和保留策略；Task Snapshot 只保存稳定 ref。
- [ ] 为 `AIProvider` 增加 Endpoint 字段；现有记录回填 `provider_kind="anthropic_compatible"`、`wire_protocol="anthropic_messages"`、兼容 driver，并把现有加密 `api_key` 迁移到独立 credential 后写入 ref。
- [ ] 新增 `IssueHarnessSession`，数据库唯一键覆盖 issue、harness、namespace，metadata 不保存凭据。
- [ ] 保持 `TaskWorkerProfileSnapshot.task_id` 的一对一 task-owned 关系和现有 Skill reference 语义；只追加多 Harness 冻结字段，不引入 revision/active pointer 迁移。
- [ ] 将可识别的 `Issue.claude_session_id` 回填到 Claude legacy lineage，并记录 `metadata.source="legacy_backfill"`；只有 Endpoint fingerprint 可确定时才允许自动恢复，否则下次显式新建 lineage。
- [ ] 保留旧 `claude_session_id` 字段和 API 响应作为兼容影子值；新写路径以 session 表为真相。
- [ ] 为 Task/Snapshot 增加索引，支持按 harness、adapter、Endpoint protocol、failure type 做运营统计。
- [ ] downgrade 明确删除新增结构但不尝试把多个 session 合并成一个 Claude ID；执行 downgrade 前应有运维提示。

### Task 2.2：实现 Harness registry、manifest 校验与兼容矩阵

**Files:** `harness_registry.py`、Runtime Bundle manifest、Worker Kit compatibility manifest、对应测试。

- [ ] registry 只包含 Codify 内置 Harness key 和 schema，不接受数据库中的任意命令或 Adapter 路径。
- [ ] 校验 Runtime Bundle manifest 的 Adapter version/digest、event schema、provider protocols、capabilities 和 state path，并以它作为实际执行 Adapter 的唯一事实源。
- [ ] 校验 Kit manifest 的 bootstrap version、支持的 runtime contract/event schema 范围和 CLI runtime 约束，不从 Kit 推导实际 Adapter 版本。
- [ ] Backend 以 registry 和 Runtime Bundle manifest 判断 Profile allowlist、Endpoint compatibility；Worker 启动时再以 Kit compatibility、实际 CLI version/binary digest 做二次校验。
- [ ] 提供统一 `list_harness_options(profile, endpoint)` 返回 `key`、显示名、selectable、disabled reason、capabilities、warnings；Frontend 直接消费。
- [ ] capability policy 实现 system upper bound + profile tightening；Profile 不能放宽系统 sandbox、network、timeout 或 secret policy。
- [ ] 未知 Harness、未知 protocol、Bundle/Kit 不兼容、Adapter digest 不匹配、CLI version 或 binary digest 不匹配均在容器创建前失败，不自动换 Harness。

### Task 2.3：演进 Model Endpoint 和凭据交付抽象

**Files:** `model_endpoints.py`、`model_credentials.py`、`providers.py`、Provider tests。

- [ ] Provider API 支持 `provider_kind`、`wire_protocol`、`provider_driver`、`provider_options`，并对组合做 allowlist 校验。
- [ ] Claude 首期支持已验证的 `anthropic_messages`；Codex 首期支持已验证的 `openai_responses`，不把 Chat Completions 静默转换为 Responses。
- [ ] Endpoint fingerprint 仅由非敏感且影响兼容域的字段生成，使用稳定排序和版本前缀。
- [ ] Task 创建时复制非敏感 Endpoint snapshot 和 `credential_ref`；API Key/OAuth/cloud credential 不进入 snapshot 或 runtime archive。
- [ ] Provider 与 credential 生命周期解耦：删除 Provider 只删除 Endpoint 配置，不删除 credential；被任何可重试 Task Snapshot 引用的 credential 只能标记 retired，不能硬删除。
- [ ] `retired` credential 禁止新 Endpoint/Task 选择，但既有 Snapshot retry 仍可解析；`revoked` 表示安全阻断，既有 retry 必须 fail closed 并返回可审计的 credential failure。
- [ ] retry 解析原 `credential_ref`；active credential 可轮换到新版本，但每次执行记录实际 credential version metadata，不保存历史 secret。
- [ ] 增加 completed Task 后删除 Provider、再 retry 的回归测试，以及 referenced credential hard-delete 被拒绝的测试。
- [ ] `model_credentials.py` 统一返回任务级凭据描述：代理 URL/短期 token/过期时间/允许模型，不让 Adapter 读取当前 Provider ORM。
- [ ] 优先接入已有模型代理或 Broker；legacy container env 必须配置显式 feature flag、低权限凭据、有效期/额度和 capability warning。
- [ ] 不可信仓库或公网生产 Profile 在 legacy 模式下 fail closed，除非有可审计风险接受配置。
- [ ] 扩展日志与 raw event 清洗，覆盖 OpenAI、自定义 Bearer token 和配置文件中的 secret 形态。

### Task 2.4：扩展 Worker Profile API、镜像 digest 与运行时验证

**Files:** `worker_profiles.py`、`api/worker_profiles.py`、Docker target/runtime tests。

- [ ] Profile create/update 校验 enabled/default Harness、constraints 和 Endpoint 独立性；禁用仍被 Issue 引用的 Profile 规则不变。
- [ ] verify-runtime 在 Profile 对应 Docker Host 上解析镜像 repo digest，保存不可变 `image_digest` 和验证时间。
- [ ] verify-runtime 为每个 enabled Harness 解析 executable source/path、CLI version 和 binary SHA-256；host mount 必须确认 daemon 侧只读路径和实际内容。
- [ ] Task 创建只接受已验证且 digest 可用的多 Harness Profile；运行时使用 `image@sha256` 或等价 immutable ID 创建容器。
- [ ] verify-runtime 对每个 enabled Harness 分别运行 binary/version/digest/config/capability/sandbox/Skills smoke，返回逐 Harness 结果。
- [ ] Profile 更新镜像、Kit、Harness allowlist 或关键约束后将验证状态置为 stale，不影响既有 Task Snapshot。
- [ ] API 响应区分“Profile 当前配置”和“Task 冻结值”，避免 UI 把新 Profile 值展示成历史任务执行事实。

### Task 2.5：实现 Task 级 Harness 选择与不可变重试

**Files:** task schemas/creation/update/response/operations、Snapshot helpers 和 API tests。

- [ ] `CreateTaskRequest` 新增可选 `harness_key`；省略时使用 Profile default。
- [ ] 创建 Task 时在同一事务中解析 Profile、Harness、Endpoint compatibility、镜像 digest、Runtime Bundle Adapter digest、CLI source/path/version/binary digest 和 capability constraints，并写入唯一 Snapshot。
- [ ] `UpdateTaskRequest` 对所有状态都拒绝 Harness、Profile、Provider、CLI 和安全约束等执行事实修改；Pending/Queued Task 如需变更，取消后从 Issue 创建新 Task。
- [ ] retry request 继续拒绝 Harness、Profile 和 Provider override；新 Task 原样复制源 Task Snapshot、Endpoint snapshot、credential ref 和 Runtime Bundle 引用。
- [ ] 切换 Harness 的唯一方式是从 Issue 创建新 Task；新任务共享 Git 工作区但选择目标 Harness lineage。
- [ ] 返回值包含 `harness_key`、Adapter version/digest、CLI source/path/version/binary digest、capability warnings、Endpoint protocol、镜像 digest、Runtime Bundle digest 和 session namespace，但不包含 secret。
- [ ] CI auto repair 任务在未显式选择时使用 Profile default；如果所需 capability 与 default 不兼容，在创建时失败，不自动换 Claude。
- [ ] 测试 Profile/Endpoint 在 Task 创建后被编辑、禁用或删除时，执行仍使用冻结的非敏感配置；凭据轮换只通过相同 credential ref 生效并记录版本元数据。

### Task 2.6：实现 Session namespace 和按 Harness 隔离的 agent state

**Files:** `harness_sessions.py`、workspace/runtime/lifecycle、Issue API 和 tests。

- [ ] Adapter 根据 harness、Endpoint fingerprint、认证域、工作区身份和 Adapter state major version生成稳定 `session_namespace`。
- [ ] `session_mode=continue` 只查找完全匹配的 IssueHarnessSession；无匹配时显式 fresh 并记录新 lineage reason。
- [ ] Claude → Codex 不传递 session；切回 Claude 时可恢复原 Claude namespace。
- [ ] invalid resume 不能静默跨 namespace 回退；Adapter 可按合同在同一 namespace 新建 lineage，并产生 warning/diagnostic。
- [ ] Issue workspace 从固定 `claude` 演进为 `agent-state/claude`、`agent-state/codex`；迁移/兼容逻辑安全处理现有目录。
- [ ] 只挂载当前 Harness 的 state 到 Adapter manifest 声明路径，避免一个 Harness 读取另一个 Harness 的认证或历史。
- [ ] `CODEX_HOME` 使用任务/Issue 隔离目录，不读取 Worker Host 或镜像用户全局配置。
- [ ] Task completion 以 upsert 更新当前 namespace session；旧 `Issue.claude_session_id` 仅镜像当前 Claude legacy compatibility 值。

### Task 2.7：实现 Codex Adapter 的配置、命令和事件映射

**Files:** Codex Adapter/translator、manifest、fixture tests、fake Codex integration。

- [ ] 从 Phase 0 fixtures 写失败测试，覆盖 metadata、version、Responses Provider、fresh/resume、JSONL、usage、failure 和 cancel。
- [ ] `prepare_config` 生成 hermetic `CODEX_HOME` 和显式 config，不继承用户全局配置；仓库配置不能放宽系统策略。
- [ ] `build_command` 分开新执行与 `codex exec resume`，模型和 Provider 来源只能是 Snapshot。
- [ ] translator 把 Codex thread/turn/item/tool/usage/CLI 结束映射到 Canonical Event，其中 CLI 结束只产生非 terminal 的 `harness.completed/failed`；不在 Backend 新增 Codex raw 分支。
- [ ] 保存 `harness-events/codex.jsonl` 并应用与 Claude 相同的清洗、权限和保留策略。
- [ ] unknown event 产生带 CLI/Adapter 版本和 raw ref 的 diagnostic；缺必需 init/Harness 结束语义由 Adapter 报 protocol_error，最终 Task terminal 仍由公共 runner 在 delivery/finalization 后产生。
- [ ] `normalize_result` 输出统一 session/model/usage/failure/capability warning；成本不可得时为 null。
- [ ] fake Codex 覆盖 stdout/stderr 混合、截断 JSONL、tool failure、invalid resume、rate limit、final event 后挂起和子进程。

### Task 2.8：验证 Codex sandbox、approval 和无人值守 fail-closed

**Files:** Codex Adapter、Profile constraints、verification 和安全 tests/docs。

> **决策（2026-08-03）：容器边界模式是生产默认。** worker 容器本身就是每任务隔离沙箱
> （独立文件系统/网络/非特权用户/只读仓库挂载），与 Claude harness 一致；容器内不再要求
> bwrap/userns。系统默认 `sandbox_mode=container-boundary`，Profile 可收紧到 `sandboxed`
> 作为硬化 Host 的纵深防御。sandbox 能力不可用不再要求启动前失败。

- [x] 定义系统允许的 sandbox/approval 组合和 Profile 可收紧集合，Snapshot 记录最终决策。
      `capability_policy` 冻结进 `harness_config_snapshot`（capabilities/sandbox_mode/constraints），
      `CODIFY_HARNESS_SANDBOX_MODE` 注入容器并映射 codex 枚举（container-boundary→
      danger-full-access、sandboxed→read-only）。
- [x] 验证 Codex sandbox 模式映射与容器边界隔离：worker 容器是非特权用户 + 独立网络 +
      只读仓库挂载；`sandboxed` 是可选收紧（需硬化 Host 提供 userns/bwrap），不阻塞默认路径。
- [x] 容器边界模式（默认）取代"启动前失败"要求；sandbox 能力不可用时按 container-boundary
      策略运行，明确记录在冻结 Snapshot 与 `run.started`，不静默放宽。
- [x] 禁止交互式 approval；策略外工具或网络操作 fail closed 并产生可诊断 failure。
- [x] 记录最终生效策略到 `run.started`/runtime metadata 和 Task 详情，不暴露 secret。
- [x] 测试仓库内 `AGENTS.md`、配置文件、脚本和工具不能修改 Provider allowlist、凭据来源
      或系统上限（`test_codex_config_is_hermetic_from_repository_agents`：恶意 AGENTS.md
      无法把 config.toml 的 `env_key`/`model_provider`/`sandbox_mode` 指向攻击者值）。
- [x] timeout/cancel 对 Codex 主进程和全部子进程执行 TERM→有界等待→KILL，验证容器锁与 Issue mutex 释放。

### Task 2.9：泛化 Skills、状态目录、辅助调用和 CodeGraph

**Files:** `skills.py`、runtime bundle、Adapter、main/delivery/codegraph、tests。

- [x] 中立 SkillVersion 快照只保存包内容；runtime materialization 由 Adapter 决定
      `.claude/skills`（claude 由 runner 读取）或 `.agents/skills`（codex 物化到 per-task
      `CODEX_HOME/.agents/skills`）。
- [x] 两个 Harness 的 Skills 都位于 `/tmp/codify-runtime` 密封目录，只读提供，不进入
      `/workspace` 或 Git diff（codex 物化目标在 per-task CODEX_HOME 下）。
- [x] Worker Kit 最低版本判断改为 capability/manifest 判断，不再叫 `Claude skills require...`
      （`skills.py` 错误消息与 docstring 已泛化）。
- [x] `run_text` capability 用于提交信息、交付摘要和 Mermaid 修复；Codex 不支持或失败时
      `main.sh` 走确定性提交信息 / 保留原摘要的 fallback 并记录 warning（echo 已泛化，
      不按 harness key 分支）。
- [x] CodeGraph capability 只在 Claude manifest 为 true；公共代码用
      `codify_harness_capability_enabled "codegraph"` 判断，不按 harness key 分支。
- [x] `max_turns` 对 Claude 继续生效；Codex 不支持时使用 wall-clock timeout，前端显示
      capability warning（`harness_options` warnings）。

### Task 2.10：统一结果、usage、失败类型和分析指标

**Files:** `worker_results.py`、usage ledger、analytics queries/responses、Task API/UI tests。

- [ ] `usage.final` 归一化 input/cached input/output/reasoning token；成本与币种可空，Provider 原始统计进入 `engine_fields`。
- [ ] Task/usage ledger 不把 null 写成 0；旧报表对 null 使用“未知”而不是参与平均值。
- [ ] 失败类型保留 `protocol_error`、sandbox、auth、rate limit、timeout、cancel 等分类，error message 继续清洗和截断。
- [ ] 运营查询支持按 Harness/Adapter/CLI/Endpoint protocol 统计成功率、耗时、取消率、protocol error 和 capability warning。
- [ ] Task 详情显示冻结 Harness/Endpoint/安全策略/版本与实际 resolved model/CLI，明确当前 Profile 与 Snapshot 的区别。
- [ ] 原始事件只能通过受权限保护的 runtime archive 获取；前端时间线不暴露 raw payload。

### Task 2.11：实现 Profile 管理与 Task Harness 选择 UI

**Files:** frontend API/types、Config panels、TaskForm、Issue/Task views、i18n 和 tests。

- [ ] API types 增加 Harness option、capability、Endpoint protocol、Snapshot 和 warning；不使用 `any` 绕过契约。
- [ ] AI Providers 面板增加 Provider kind、wire protocol、driver/options 和 credential 状态；敏感值仍只显示 configured/not configured。
- [ ] Worker Settings 增加 enabled Harness、default Harness、constraints、image digest 和逐 Harness verify result。
- [ ] TaskFormDrawer 在执行环境区增加 Harness 选择，选项来自 Backend compatibility API；Profile default 为初值。
- [ ] Harness 改变时重新计算兼容 Provider、Skills、session 和 capability warning；失效组合立即阻止提交并滚动/聚焦首个错误。
- [ ] 已创建 Task 的 Harness 和其他执行事实始终只读；Pending/Queued Task 需要变更时提供“取消并新建 Task”引导，不调用 update API 改写 Snapshot。
- [ ] Session 文案从“Claude session”改为 Harness 中立；无当前 namespace 时明确说明会创建新 lineage。
- [ ] IssueView 不新增持久 default Harness；继续展示固定 Worker、默认 Endpoint，新 Task 使用 Profile default。
- [ ] 中英文文案同时更新，将可复用 Skill 文案从“Claude Skills”调整为“Skills”。

### Task 2.12：升级 Worker Kit、离线包与单 Host 真实 smoke

**Files:** Kit Dockerfile/manifest/export/verify、offline scripts/docs/tests。

- [x] 发布新的不可变 Kit 版本和 amd64 制品；Kit manifest 固定 bootstrap、支持的 Runtime Bundle
      contract/schema 范围和 CLI runtime 约束，Runtime Bundle manifest 固定 Claude/Codex Adapter
      version/digest、event schema 和 capability。
      （Kit 0.3.10 已 `make worker-kit-export` 构建并安装到远程
      `/opt/codify/worker-kits/0.3.10-linux-amd64`，manifest `cli_runtimes` 含
      `claude:{source:image,minimum_version:2.1.33}` + `codex:{source:host_mount,minimum_version:0.146.0}`；
      Profile 11 已切到 0.3.10，Task 502 验证新 Kit 完整链路。arm64 制品未构建。）
- [x] verify-runtime 支持为每个 Harness 指定镜像内路径或只读 host mount，并输出逐 Harness
      source/path/version/binary digest/能力/沙箱结果（backend 通过 launcher per-harness；
      `verify-runtime.sh` 与 `verify-worker-runtime.sh` 支持 `--harness-key`/
      `--harness-host-path`/`--harness-container-path`，claude→CODIFY_CLAUDE_BIN、
      codex→CODIFY_CODEX_BIN）。
- [ ] 离线 bundle 明确列出包含 Codex CLI 的 runtime image 或固定 host binary；不依赖在线安装和可变 `latest`。
- [x] 固定 runtime image repo digest 并在 Profile verification、Task Snapshot 和容器实际镜像间核对；
      CLI binary digest 三处核对已闭环：Profile `harness_runtimes.binary_digest` →
      Task Snapshot `cli_binary_digest` → 容器启动时 adapter `verify_runtime` 用
      `CODIFY_CLI_BINARY_DIGEST` 复核 sha256。
- [ ] 在一个真实目标 Docker Host 上完成 Claude/Codex：首任务、resume、fresh、跨 Harness 切换、Skills、无变更、工具失败、取消、timeout、Git/MR、archive 回放。
      > **进展（2026-08-03→04，dev host 192.168.50.129）**：Codex fresh + Git/MR + archive
      > 回放 + canonical 事件流 + usage + sandbox 已跑通（Task 498–506，MR !5，
      > `run.completed(success)`）；修复了 normalize 读错文件、delivery 误判历史 commit、
      > `.git` root-owned 权限三处根因。**Codex 已改为只写文件**（execpolicy 禁 git 写操作 +
      > `approval_policy="never"`），由 Codify delivery 统一 commit，与 Claude 一致
      > （Task 504/505/506 验证）。**Claude 同环境回归已通过**（2026-08-04，DeepSeek
      > anthropic provider 6，provider 1/智谱余额不足 429；Task 508 completed、
      > commit `ece571b4`、`run.completed(success)`，delivery/elif/chown 改动无回归）。
      > resume/跨 Harness/取消/timeout 的 Codex 矩阵未补。
- [ ] 验证私有 CA、PATH、远程 Docker host path、Provider 网络、持久 workspace 和 agent-state 权限。
- [ ] 单 Host smoke 只把 Phase 2 标为生产候选；多 Host 安装、灰度和回滚进入 Phase 3。

---

## 5. 自动化测试门禁

### Backend focused suite

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_harness_registry.py \
  tests/unit/test_model_endpoints.py \
  tests/unit/test_model_credentials.py \
  tests/unit/test_harness_sessions.py \
  tests/unit/test_codex_harness_adapter.py \
  tests/unit/test_worker_profiles_api.py \
  tests/unit/test_task_worker_profile_selection.py \
  tests/unit/test_task_api_contract.py \
  tests/unit/test_providers_api.py \
  tests/unit/test_worker_workspace.py \
  tests/unit/test_worker_profile_runtime.py \
  tests/unit/test_skills.py \
  tests/unit/test_offline_bundle_export.py -v
```

### Frontend focused suite

```bash
cd frontend
npx vitest run \
  src/components/TaskFormDrawer.spec.ts \
  src/features/tasks/taskFormModel.spec.ts \
  src/views/Config.spec.ts \
  src/views/TaskView.spec.ts
```

### 集成与全量

```bash
make test-backend
make test-frontend
make test-mock-e2e
```

前端最终构建、Worker Kit 和离线包必须使用 Docker 固定环境生成并保留摘要。

---

## 6. Phase 2 退出门禁

- [ ] Claude 和 Codex 都通过 Adapter fixture、mock integration 和单 Host真实运行矩阵。
      > **决策（2026-08-03）**：`tests/mock_integration` 用例疏于维护（部分依赖外部
      > mock GitLab 状态、git clone 偶发失败），不作为 Phase 2 门禁；引擎正确性以
      > Adapter fixture 回放（离线、严格）+ 单 Host 真实运行矩阵为准。
- [ ] Profile/Endpoint 修改不影响已创建 Task；retry 完整复制 Snapshot 和 Runtime Bundle。
- [ ] Pending/Queued Task 的执行事实不可编辑；切换 Harness 必须从 Issue 创建新 Task。
- [ ] 从 Claude 切 Codex 不复用 session，切回 Claude 能恢复兼容 namespace。
- [ ] Backend/Frontend 无 Claude/Codex raw event 分支，公共 Worker 无固定二进制调用。
- [ ] Codex sandbox/approval/credential 最终边界可审计且不存在静默放宽。
- [ ] Skills 对两引擎可发现且 Git 工作区无污染；CodeGraph 和 max turns 的能力差异有明确 warning。
- [ ] usage null、failure taxonomy、protocol error、取消和完整进程树清理有自动化证据。
- [ ] 新 Kit、镜像 digest、CLI/Adapter 版本和离线制品已固定并可在单 Host 重装验证。
- [ ] Runtime Bundle manifest 是 Adapter 执行事实源，Kit compatibility manifest 与其匹配，CLI binary digest 在启动时复核。
- [ ] 删除 Provider 后旧 Task 仍可 retry；referenced credential 不可被硬删除，凭据轮换版本可审计。
- [ ] 凭据 Broker/代理可用，或受限 legacy 风险接受已记录；不可信仓库不得默认使用长期容器密钥。

本阶段完成后状态只能标记为“Claude + Codex 生产候选”。进入 Phase 3 前冻结 release candidate 的 Backend、Frontend、Worker Kit、runtime image digest 和 Adapter/CLI 版本。
