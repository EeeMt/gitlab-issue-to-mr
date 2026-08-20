# Open-Harness V2 — 074 Migration 设计与 Phase 1 接口骨架

**日期：** 2026-08-21 · **状态：** 设计定稿，供开发委派输入 · **依据：** [open-harness-v2.md](open-harness-v2.md) §9 | [实施计划](../superpowers/plans/2026-08-21-open-harness-v2-implementation-plan.md) §4 | [冻结 Schema](open-harness-v2-schemas.md)

本文件是 Phase 1 开发的**输入契约**，不是实现本身。开发按本骨架实现，评审据此核对。

---

## 1. Migration 074_open_harness_v2

**基线与编号**：以当前 Alembic head `073_task_freeform_mode` 为基线（`down_revision = "072_shared_per_item_inheritance"`）。实施时若 head 已变化必须顺延编号。
**执行约束**：物理列重命名 + roll-forward-only，只按实施计划 §8.6 的首次 V2 控制面维护窗口由唯一 migration owner 执行；`AUTO_MIGRATE=false`。

### 1.1 `ai_providers`（破坏性重命名 + 新列）

| 变更 | DDL 语义 |
|---|---|
| `wire_protocol` → `model_protocol` | `RENAME COLUMN`，保留 String(32)/not null/default `anthropic_messages`；**不改现有 Provider 数据值，不加旧 API alias** |
| 新增 `compat_profile` | `nullable String(64)`；描述 OpenAI-compatible 服务的已知差异；后端 allowlist，未知值 Task 创建时拒绝 |

历史 V1 Snapshot 内旧字段保持原样；V2 控制面仅在 `dual_canary` V1 compatibility reader 与历史展示读取。

### 1.2 `worker_profiles`（新增列）

| 变更 | DDL 语义 |
|---|---|
| 新增 `harness_options` | `JSON NOT NULL DEFAULT '{}'`；namespaced（`{"pi":{…},"opencode":{…}}`） |

> 不改 `enabled_harnesses` / `default_harness_key` 默认值（仍 claude）；V2 canary 只使用显式创建的 Profile。现有 Profile/Issue 不迁移默认值。

### 1.3 `task_harness_attempts`（新增 control/sequence/lease 列）

| 列 | 类型 | 默认 | 约束 |
|---|---|---|---|
| `control_state` | String(16) NOT NULL | `disabled`（历史 V1 attempt 回填） | `IN ('disabled','starting','accepting','closing','closed')` check |
| `next_command_sequence` | Integer NOT NULL | `1` | `>= 1` check |
| `command_dispatch_owner` | String(64) NULL | — | dispatcher lease owner（如 worker/container id） |
| `command_dispatch_expires_at` | DateTime NULL | — | lease 到期时间 |

### 1.4 新建 `task_harness_commands` 表

```text
command_id           String(64)  PK              # ULID/UUID，客户端生成，全局唯一
task_id              Integer     NOT NULL FK tasks(id) ON DELETE CASCADE, index
attempt_id           String(64)  NOT NULL FK task_harness_attempts(attempt_id) ON DELETE CASCADE
sequence_no          Integer     NOT NULL        # >= 1，attempt 内唯一、单调
command_type         String(16)  NOT NULL        # steer | follow_up
payload              JSON        NOT NULL        # 首版仅 {text}
payload_digest       String(64)  NOT NULL        # sha256(canonical{task_id,attempt_id,type,payload})
status               String(16)  NOT NULL        # queued | delivered | rejected
created_by           String(64)  NOT NULL        # API 调用者 / subject
created_at           DateTime    NOT NULL
delivery_attempts    Integer     NOT NULL DEFAULT 0
last_attempt_at      DateTime    NULL
delivered_at         DateTime    NULL
rejected_at          DateTime    NULL
rejection_code       String(64)  NULL
rejection_message    Text        NULL
```

**约束与索引**
- `command_id` 全局唯一（PK）。
- `payload_digest` 非空。
- `UNIQUE (attempt_id, sequence_no)`；`sequence_no >= 1`；sequence 只在 attempt 行锁内分配。
- `CHECK command_type IN ('steer','follow_up')`。
- `CHECK status IN ('queued','delivered','rejected')`。
- delivered/rejected 字段与状态一致（`CHECK (status='delivered') = (delivered_at IS NOT NULL)` 等）。
- 索引：`(task_id)`、`(attempt_id, sequence_no)` unique、`(attempt_id, status)`（pump 队首查询）。
- Task/attempt 删除时 command 级联删除；Issue 生命周期统计**不依赖** command 明细。

### 1.5 顺延/附带项（本 migration 内）

- 不改写 V1 Snapshot、attempt、receipt、raw archive 或统计行。
- V1 PENDING/QUEUED 幂等拒绝由 §3 execution policy 在运行期处理，**不在** migration 内转换数据。
- 不建立第二套 Bundle 机制；OMP 不混入 074（后续独立迁移）。

**测试**：`test_074_migration.py`（RENAME 后 V1 只读 reader 仍可读、V1 数据逐行不变、control_state 回填 disabled）；`test_task_harness_commands.py`（唯一键、约束、级联）。

---

## 2. Phase 1 公共契约 / 接口骨架

以下为建议新增/修改模块与其最小公开接口。开发委派按此责任区拆包。

### 2.1 `backend/app/core/harness_protocol.py`（扩展，不覆盖 V1）

- 保留 V1 全部常量与函数。
- 新增 V2 常量：`CANONICAL_EVENT_SCHEMA_V2`、`HARNESS_CONTRACT_VERSION_V2`、`CANONICAL_RESULT_SCHEMA_V2`、`COMMAND_SCHEMA_V2`、`RUNTIME_MANIFEST_SCHEMA_V2`。
- 新增 V2 校验：`validate_event_v2(event)`（在 V1 校验基础上强制 `harness.control_transport` / `harness.model_protocols`）；`validate_command(command)`；`validate_manifest(manifest)`。
- 新增控制事件类型集：`CONTROL_EVENT_TYPES = {"control.command.delivered","control.command.rejected","control.queue.updated"}`。
- Projector 按 attempt `event_schema` 选择 `validate_event_v1` / `validate_event_v2`；V1 只读投影保持可用。

### 2.2 command plane（新增）

**`backend/app/core/task_harness_commands.py`**
- `payload_digest(task_id, attempt_id, command_type, payload) -> str`（canonical JSON + sha256）。
- `create_command(db, task_id, command_id, type, payload, created_by) -> CommandCreateResult`
  - 幂等查重优先：同 ID/同 digest → `{status:'existing', created:bool}`；同 ID/不同 digest → `409`。
  - 新 ID：同一事务锁 Task、当前 attempt、Issue access；校验 RUNNING、精确 V2、capability、`control_state=accepting`；从 `next_command_sequence` 分配 sequence。
- `write_command_delivery(...)` / `write_command_rejection(...)`：仅 pump 调用，CAS `queued -> delivered|rejected`；终态不可重开。

**`backend/app/api/task_command_routes.py`**
- `PUT /api/tasks/{task_id}/commands/{command_id}`（幂等创建，body 仅 text `steer|follow_up`）。
- `GET  /api/tasks/{task_id}/commands`（按 sequence 排序恢复）。
- `GET  /api/tasks/{task_id}/commands/{command_id}`。
- 首版不提供 update/delete/reorder。

**`backend/app/core/worker_command_pump.py`**
- 独立 AsyncSession；attempt 级 lease（`command_dispatch_owner`/`_expires_at`，`SKIP LOCKED` 并行不同 attempt，同一 attempt 单 dispatcher）。
- 严格按最小非终态 `sequence_no` 处理队首；前一条未终态不得领取后一条。
- Docker exec 只调用镜像内固定 `control_client.py`；文本经 stdin JSON + Task 私有 Unix socket。
- journal：发送前 fsync `dispatching`，ACK 后写结果；不确定 → `delivery_outcome_unknown`。

**`deploy/worker-entrypoint/harness/control_client.py`**（容器内固定入口）与 **`bridge.py`**（Bridge 控制端点，capability negotiation + 确定性 reject）。

### 2.3 执行合同策略（新增）

**`backend/app/core/harness_execution_policy.py`**
- `require_executable_contract(task, attempt, bundle, settings) -> None`（同时核对 Snapshot、attempt schema、Bundle contract/version/digest）。
- `require_executable_contract_v2(...)`（要求精确 V2，不只判断有 Bundle）。
- 必填 `HARNESS_EXECUTION_MODE in {dual_canary, v2_only}`；Backend/Scheduler 启动各自校验，readiness/health 显示，部署 preflight 比较一致。
- `v2_only` 下：残留 V1 PENDING/QUEUED 幂等转 CANCELLED；恢复发现 V1 RUNNING 不恢复、终止容器并 FAILED，统一 `legacy_contract_not_executable`。
- 接入点：`task_creation_service.py`、`tasks.py`、`scheduler.py`、`worker_runtime_bundle.py`、`worker_task_lifecycle.py`、crash recovery。

### 2.4 manifest 驱动内置目录（修改）

- `harness_registry.py`：编译期 allowlist `{pi, opencode, claude, codex}`；display name / support tier / control transport / model_protocols / capability / options schema 从 manifest projection 读取；系统 capability upper bound 仍在代码内，manifest 只能收紧。
- `worker_runtime_bundle.py`：Bundle digest 从 manifest `files` 递归计算；每 Adapter 独立 digest。
- `deploy/worker-entrypoint/harness/manifest.json`：按 §6 冻结结构落地四 Adapter。
- `verify-runtime.sh` / `worker_runtime_readiness.py`：逐 manifest Adapter 验证制品/版本/摘要 + Bridge self-check。

### 2.5 `model_protocol` 重命名与 `harness_options`

- `backend/app/models.py`、`api/providers.py`、`core/model_endpoints.py`、`api/task_responses.py`、`api/task_creation_service.py`、`core/worker_runtime.py`、`frontend/src/api/index.ts` 全部改用 `model_protocol`；全仓 `rg wire_protocol` 最终只允许在 migration、`dual_canary` V1 reader、V1 历史读取与旧文档。
- Provider secret-free fingerprint 纳入 `model_protocol` 与 `compat_profile`；环境变量注入从 `model_protocol` 决定，不从 harness key 猜测。
- Profile `harness_options`：`pi/v1` 与 `opencode/v1` 有类型 Pydantic 校验器；Task override 只接受 manifest `task_override=true` 的字段；Profile 默认与 Task override deterministic deep merge 后冻结到 `harness_config_snapshot`；Snapshot fingerprint 纳入 options。

### 2.6 测试建议

```text
backend/tests/unit/test_074_migration.py
backend/tests/unit/test_harness_protocol.py        # V1/V2 双校验 + 控制事件
backend/tests/unit/test_harness_event_fixtures.py  # V2 fixtures 离线回放
backend/tests/unit/test_task_harness_commands.py   # 幂等/409/sequence/CAS
backend/tests/unit/test_task_command_routes.py
backend/tests/unit/test_worker_command_pump.py     # 队首阻塞/lease/journal
backend/tests/unit/test_harness_execution_policy.py
backend/tests/fixtures/harness_events_v2/          # 四 Harness V2 fixture
```

**Phase 1 退出条件**：四个 stub Adapter 均可通过 V2 fixture；V1 Task 仍可读取；命令可在 fake Bridge 完成 queued→delivered/rejected、重复投递、Worker 重启与 settled race；没有真实 Pi/OpenCode 也能验证全部公共状态机。

---

## 3. 委派切分建议（供 Leader 分派）

| 开发委派 | 责任区 |
|---|---|
| 074 migration + 数据模型 | §1 全量；`models.py`、`alembic/versions/074_open_harness_v2.py` |
| V2 协议 / projector / fixtures | §2.1；`harness_protocol.py`、`worker_event_projector.py`、`harness_attempts.py`、四 Harness `harness_events_v2/` |
| Command plane | §2.2；`task_harness_commands.py`、`task_command_routes.py`、`worker_command_pump.py`、`control_client.py`、`bridge.py` |
| Execution policy | §2.3；`harness_execution_policy.py` + 全部接入点 |
| Manifest / registry / runtime | §2.4；`harness_registry.py`、`worker_runtime_bundle.py`、`manifest.json`、`verify-runtime.sh` |
| `model_protocol` 重命名 + options | §2.5 |

Pi / OpenCode / Claude / Codex Adapter 开发（Phase 2–4）**不得**各自修改 V2 schema；协议变更必须回到 Phase 1 共享合同提交并更新四 Harness fixtures 后再继续。
