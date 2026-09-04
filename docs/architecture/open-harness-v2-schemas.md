# Open-Harness V2 冻结 Schema 与合同 (Phase 0 收尾)

**日期：** 2026-08-21 · **最近实施对齐：** 2026-08-28 · **状态：** 已冻结，供实现引用 · **成熟度：** Internal Preview

**依据：** [open-harness-v2.md](open-harness-v2.md) §6 | [2026-08-21-open-harness-v2-implementation-plan.md](../superpowers/plans/2026-08-21-open-harness-v2-implementation-plan.md) §3.5 / §4
**证据：** [Phase 0 probe fixtures](../harness-probes/v2/README.md)（Pi `steer.raw.jsonl` / `followup.raw.jsonl` / `abort.raw.jsonl` / `success.raw.jsonl`、OpenCode `events.observed.jsonl`、Claude/Codex `success.v2.jsonl`）

**约定：** V2 是 V1 的超集。本文件冻结的每个字段都必须 `fail closed`——未知枚举值拒绝、未知 `type` 降级为可审计 `diagnostic`（与 V1 一致）。实施修改必须回到 Phase 1 共享合同提交并更新四 Harness fixtures，禁止各 Harness 私下漂移。

---

## 1. 总览：五个冻结 schema

| Schema | 标识 | 方向 | 生产者 → 消费者 |
|---|---|---|---|
| Harness Contract | `codify.worker.harness/v2` | Runner ↔ Adapter/Bridge 生命周期 | 公共 Runner ⇆ Harness Adapter/Bridge |
| Canonical Event | `codify.worker.event/v2` | Worker → Backend 业务事件 | Worker events.py → Backend projector |
| Harness Command | `codify.worker.command/v2` | Backend → 运行中 Harness | Backend pump → Bridge |
| Canonical Result | `codify.worker.result/v2` | Worker → Backend 结果+交付前状态 | 公共 Runner → Backend |
| Runtime Manifest | `codify.worker.runtime-manifest/v2` | 构建产物 → Backend/Registry/Worker | Bundle manifest 驱动内置目录 |

`wire_protocol` 在 V2 数据库/API 中破坏性重命名为 `model_protocol`；`control_transport` 只存在于 Harness manifest，不属于 Model Endpoint。V2 只允许三种 `model_protocol`：`anthropic_messages` / `openai_responses` / `openai_chat_completions`。

---

## 2. `codify.worker.harness/v2` — Harness Contract

Runner 与 Adapter/Bridge 之间的双向运行期生命周期。继承 V1 的 metadata / verify / config / Skills / event / result / terminate 语义，新增双向 control（`start` 返回本地控制端点、`send_command`、`wait` 的 settled 语义）。Adapter 的 `wait()` 只返回 Harness settled，不能直接标记 Task 成功——Task terminal 与 Git/MR delivery 始终由公共 Runner 持有。

```
metadata()
verify_runtime()
detect_capabilities()
prepare_config(snapshot)
materialize_skills(skills)
start(request)            # 启动 Bridge；Pi 返回本地 command control endpoint
send_command(command)     # 可选：按 capability 接受或拒绝；Pi 支持 steer/follow_up
wait()                    # 阻塞直到 Harness settled/failed（Pi agent_settled / OpenCode session.idle）
normalize_result()        # 产出 codify.worker.result/v2
terminate()
run_text()?               # 可选，Claude/Codex 兼容路径
```

**冻结要点**
- Pi 的 `start` 必须返回本地 command control endpoint（`rpc_stdio` 的 stdin/stdout 句柄）；OpenCode 的 Task-local Server 端口与私有认证值仅供其执行 Bridge 使用，不是 public command endpoint。端口/认证只保存在容器内，不进入用户日志。
- `send_command` 对未声明 capability 的 Harness 确定性拒绝（OpenCode/Claude/Codex）。
- `wait()` 必须结合事件与最终状态，不能以单一 busy/idle 轮询判定 settled（OpenCode 以 `session.idle` + 最终 assistant message + session status 共同判定；Pi 以 `agent_settled` 为准）。
- `normalize_result()` 产出 §5 的 result v2；失败必须带 `failure.kind` 与 raw archive locator。

---

## 3. `codify.worker.event/v2` — Canonical Event

### 3.1 信封（冻结）

事件信封在 V1 基础上只做最小演进，**唯一新增的必填字段是 `harness.control_transport` 与 `harness.model_protocols`**；V1 的全部不变量保持（`(attempt_id, seq)` 幂等且从 1 连续递增、`event_id` 唯一、attempt 内 Harness identity 不可变、raw 独立清洗归档、唯一 Task terminal）。

```json
{
  "schema": "codify.worker.event/v2",
  "event_id": "…-event-N-v2",
  "attempt_id": "task-123-attempt-1",
  "seq": 1,
  "occurred_at": "2026-08-21T10:00:00Z",
  "type": "run.started",
  "task_id": 123,
  "harness": {
    "key": "pi",
    "adapter_version": "2.0.0",
    "cli_version": "0.84.2",
    "control_transport": { "kind": "rpc_stdio", "protocol": "pi-rpc" },
    "model_protocols": ["anthropic_messages", "openai_responses", "openai_chat_completions"]
  },
  "payload": { … },
  "raw_ref": { "stream": "harness-events/pi/…", "line": 12 }
}
```

**必填字段（冻结）**：`schema`、`event_id`、`attempt_id`、`seq`、`occurred_at`、`type`、`task_id`、`harness{key, adapter_version, cli_version, control_transport}`、`harness.model_protocols`、`payload`。`raw_ref` 可选。

**`control_transport` 与 `model_protocols`（每 Harness 冻结）**

| Harness | `control_transport.kind` | `control_transport.protocol` | `model_protocols` |
|---|---|---|---|
| Pi | `rpc_stdio` | `pi-rpc` | `[anthropic_messages, openai_responses, openai_chat_completions]` |
| OpenCode | `server_http` | `opencode-server` | `[anthropic_messages, openai_responses, openai_chat_completions]` |
| Claude | `cli_stream_json` | `claude-json` | `[anthropic_messages]` |
| Codex | `cli_jsonl` | `codex-jsonl` | `[openai_responses]` |

> `cli_version` 以二进制实际报告为准（Codex `0.146.0`，与 `0.146.0-alpha.3.1` 属同一发布代际，取 `0.146.0`）。

### 3.2 Event type 词汇（冻结）

**V1 继承类型（行为不变）**：`run.started`、`model.resolved`、`message.delta`、`message.completed`、`reasoning_summary.delta`、`reasoning_summary.completed`、`reasoning_summary.started`、`tool.started`、`tool.completed`、`context.compacted`、`provider.retry`、`usage.updated`、`usage.final`、`harness.completed`、`harness.failed`、`delivery.started`、`delivery.completed`、`delivery.failed`、`worker.finalization`、`run.completed`、`run.failed`、`diagnostic`。

**V2 新增控制事件（3 个，冻结）**

| Type | 必填字段 | 语义 | 关联 command_id |
|---|---|---|---|
| `control.command.delivered` | `command_id`、`payload_digest`、`sequence_no`、`delivered_at` | Pi 原生 `steer` / `follow_up` 返回 `success:true` ACK | **必须** |
| `control.command.rejected` | `command_id`、`payload_digest`、`sequence_no`、`rejection_code`、`rejection_message` | 原生拒绝 / Task 已 closing / 确定性 transport 错误 | **必须** |
| `control.queue.updated` | `queue`（内容数组） | attempt 级审计事件，Pi 原生 `queue_update` 的投影 | **不强制**（见 3.4 审计边界） |

**唯一终态规则（冻结，与 V1 一致）**
- 一个 attempt 有**且仅有一个** Harness terminal（`harness.completed`/`harness.failed`）。
- `worker.finalization` 之后**只能**出现唯一的 `run.completed` 或 `run.failed`。
- 若上游 probe 证明有多 turn terminal，Bridge 必须把多个原生 settled 收敛为**一个** Harness terminal。

**序列规则（冻结）**
- `seq` 从 1 连续递增；`run.started` 必须是 `seq=1`。
- attempt 内 Harness identity（`key`/`adapter_version`/`cli_version`/`control_transport`）不可改变。
- 重放/乱序 control event **不得**改变 `task_harness_commands` 行；projector 只做审计/日志展示，绝不反向写 command 状态。

### 3.3 `delivered` = Harness 原生 ACK 的精确语义（冻结）

`delivered`（以及 command API 的 `delivered` 状态）**精确定义为**：当前唯一 command-capable
Harness Pi 的原生接口已返回成功 ACK（`steer success:true` / `follow_up success:true`）。它**不保证**该文本已被模型消费、执行或改变结果。

- UI 对 `delivered` 显示 **“Harness 已接收”**，不显示“已执行”。
- 真正的 settled 是 Pi `agent_settled` / OpenCode `session.idle`；`delivered` 从未等于 settled。
- 原生确定性拒绝或 Task 已关闭控制入口 → `rejected`。跨 native-send 边界的未知结果不是拒绝，必须成为 `outcome_unknown`。

### 3.4 queue update 无 command_id 时的审计边界（冻结）

Pi 原生 `queue_update`（`steering[]` / `followUp[]`）**只携带队列内容，没有任何 Codify command/sequence ID**（probe `steer.raw.jsonl` 与 `followup.raw.jsonl` 均证实）。因此：

- Bridge **只有在能证明关联时才**可附带 `command_id` 或顺序（例如紧邻本次已投递、尚未 delivered 的 command——由 pump 写入的 dispatching journal 提供关联依据）；
- **禁止按消息文本猜测** command_id；
- `control.queue.updated` 是 attempt 级审计事件，`command_id` 可为 null；command API/数据库仍是 UI 恢复的唯一事实源。

---

## 4. `codify.worker.command/v2` — Harness Command

Backend → 运行中 Harness 的控制命令。首发仅文本；只支持 `steer` 与 `follow_up`，且只有 Pi manifest 声明支持（OpenCode/Claude/Codex 均不声明）。

```json
{
  "schema": "codify.worker.command/v2",
  "command_id": "01K…",
  "task_id": 123,
  "attempt_id": "task-123-attempt-1",
  "sequence_no": 7,
  "type": "steer",
  "payload": { "text": "先修复并发问题，再继续原计划" },
  "created_at": "2026-08-21T10:00:00Z"
}
```

**冻结字段与约束**

| 字段 | 约束 |
|---|---|
| `schema` | `codify.worker.command/v2` |
| `command_id` | 客户端生成 ULID/UUID，**全局唯一**；path 是事实源，若请求 schema 同时携带必须与 path 一致 |
| `task_id` | 正整数 |
| `attempt_id` | 指向当前 RUNNING attempt |
| `sequence_no` | attempt 内单调递增、`>= 1`，只能在锁定 attempt 的事务内分配 |
| `type` | `steer` 或 `follow_up`（`steer`=工具调用后、下一次模型调用前送达；`follow_up`=当前工作结束后继续处理） |
| `payload` | JSON，首版仅 `{ "text": "<最大文本长度内的字符串>" }` |
| `created_at` | RFC3339 |

**`payload_digest`（冻结）**：对规范化 `{task_id, attempt_id, type, payload}`（canonical JSON，sort_keys）计算 SHA-256。同一 `command_id` + 同一 digest 重放返回已有行（首次 `201`、重放 `200`）；同一 `command_id` + 不同 digest → `409 Conflict`。唯一键竞争后重读并执行同一判断。

**幂等查重优先于新建资格检查（冻结）**：ID 已存在的 command 即使 Task 随后 closing/terminal 也返回原状态；只有新 ID 才继续检查 RUNNING、精确 V2、capability、Issue 权限与 `control_state=accepting`。

### 4.1 Command 状态机（冻结）

```
queued --(pump claim/CAS)--> dispatching
dispatching --(native ACK)--> delivered
dispatching --(native deterministic reject)--> rejected
dispatching --(proven pre-send failure)--> queued
dispatching --(cross-send result unknown/recovery)--> outcome_unknown
```

- `queued` 是 API 接受并写库后的控制面状态，只由 API 创建；`dispatching` 是 pump 在 native send 前的持久化 crash boundary。
- command pump 是唯一状态 writer。它只在 Bridge 能证明尚未 native send 时允许 `dispatching -> queued`；普通 transport exception 不能推断 pre-send，必须 fail closed。
- `delivered`、`rejected` 和 `outcome_unknown` 是**不可变终态**，不可重开；恢复 owner 遇到 `dispatching` 必须进入 `outcome_unknown`，不得重放。
- Canonical control event、projector、SSE 日志**不参与** command 行状态写入。
- 同一 `command_id` 重投不得产生两条用户消息。

### 4.2 ACK / reject code（冻结）

`rejection_code` 首版枚举（均为确定性拒绝，不创建 queued 假象）：

| code | 场景 |
|---|---|
| `task_not_running` | Task 非 RUNNING |
| `attempt_mismatch` | attempt 不匹配当前 RUNNING attempt |
| `unsupported_harness` | Harness 不声明对应 command capability |
| `control_gate_closed` | `control_state` 非 `accepting`（starting/closing/closed/disabled） |
| `not_authorized` | Issue 访问权限不足 |
| `payload_too_large` | 文本超过最大长度 |
| `invalid_command_type` | type 非 `steer`/`follow_up` |
| `delivery_outcome_unknown` | 跨 native-send 边界后 ACK/拒绝结果不确定；状态为 `outcome_unknown`，拒绝再次注入 |

`delivery_outcome_unknown`（冻结）：pump 在原生发送前持久化 `command_id -> dispatching`。若能证明 native send 尚未发生，才允许回到 `queued`；若发送后崩溃或发送边界无法证明，写入**终态** `outcome_unknown`，其 public rejection code 为 `delivery_outcome_unknown`——**不得冒险再次注入**。

`outcome_unknown` 是 command 行终态及 TaskLog 审计 metadata，不是第四个 Canonical Event v2 type；因此
它不能被 projector 用来回写 command 行。

**持久化时间与 public projection（与 migration 075 一致）**：command 行保留
`created_at`、`last_attempt_at`、`dispatch_started_at`、`native_request_id`、`native_sent_at`、`native_ack_at`、
`outcome_unknown_at`、`delivered_at`、`rejected_at`。`native_request_id` 与 `native_sent_at` 是内部诊断/恢复
证据，不进入 public projection。列表/单项 API 固定投影 `command_id`、`sequence_no`、`type`、`status`、
`created_at`、`dispatch_started_at`、`native_ack_at`、`outcome_unknown_at`、`delivered_at`、`rejected_at`、
`rejection_code`、`rejection_message`；对 `outcome_unknown` 强制公开安全 code
`delivery_outcome_unknown`，不暴露容器 Bridge 的原始诊断文字。

### 4.3 Bridge control endpoint framing 与最大文本长度（冻结）

- **传输 framing**：Worker 通过 `docker exec` 调用镜像内**固定的** `control_client.py`（绝不拼接用户文本到 shell 命令）；文本经 **stdin JSON** 传输，client 连接 **Task 私有 Unix socket** 并等待 Bridge ACK。
- **Bridge 控制端点**：协议与 §6.3 一致。请求体为 `codify.worker.command/v2` 信封，响应为 `{accepted:true}` 表示原生 ACK 已收到（→ delivered）或 `{rejected:true, code, message}`。
- **最大文本长度（冻结）**：`payload.text` 最大 **4,000 字符**（UTF-16 code units）。超长在 API 层确定性 `payload_too_large` 拒绝。该上限满足当前 Pi steer/follow-up 文本需求，且避免控制端点帧过大。
- **attempt 内严格顺序（冻结）**：同一 attempt 任一时刻只有一个 dispatcher 处理队首；前一条未进入 `delivered|rejected|outcome_unknown` 终态时**不得**领取后一条。不能用 command 行级 `SKIP LOCKED` 越过队首。

---

## 5. `codify.worker.result/v2` — Canonical Result

继承 V1 result，显式携带 Session、usage、model、outcome、failure category 与 raw archive locator。公共 Runner 生成**且仅生成一个** Task terminal；delivery 在 Harness settled 之后。

```json
{
  "schema": "codify.worker.result/v2",
  "status": "completed",
  "success": true,
  "result": { "text": "…", "files_changed": ["…"] },
  "harness": {
    "key": "pi",
    "adapter_version": "2.0.0",
    "cli_version": "0.84.2",
    "control_transport": { "kind": "rpc_stdio", "protocol": "pi-rpc" },
    "model_protocols": ["anthropic_messages", "openai_responses", "openai_chat_completions"]
  },
  "session_id": "…",
  "model": "deepseek-v4-flash",
  "usage": { "input_tokens": 1553, "cached_input_tokens": 1536, "output_tokens": 40, "reasoning_tokens": 40, "cost": 0, "currency": null, "engine_fields": {} },
  "failure": null,
  "capability_warnings": [],
  "raw_archive": { "stream": "harness-events/pi/…", "attempt_id": "…" }
}
```

**冻结要点**
- `harness` 块与 event v2 信封的 `harness` 块结构一致（含新增 `control_transport` / `model_protocols`）。
- `session_id`、`model`、`usage` **显式携带**；usage 缺失时 `engine_fields` 标记 `unavailable`，**不用估算值冒充上游值**。
- `failure.kind` 沿用 V1 的 `FailureKind` 枚举，并新增 V2 分类：`crash`（OpenCode Server 崩溃 / Bridge 进程异常）、`settled_race`(可选，Pi closing/drain 竞争无 continuation)。`raw_archive` 定位原始事件供回放。

---

## 6. `codify.worker.runtime-manifest/v2` — Runtime Manifest

内置运行时事实，不是第三方插件契约。后端只接受编译期批准 key：`pi`、`opencode`、`claude`、`codex`（`omp` 后续单列）。

```json
{
  "schema": "codify.worker.runtime-manifest/v2",
  "maturity": "internal_preview",
  "contract_version": "codify.worker.harness/v2",
  "event_schema": "codify.worker.event/v2",
  "command_schema": "codify.worker.command/v2",
  "result_schema": "codify.worker.result/v2",
  "adapters": {
    "pi": {
      "support_tier": "default",
      "source": { "repository": "https://github.com/earendil-works/pi", "license": "MIT",
                  "artifact_version": "0.84.2", "artifact_sha256": "906fbe78…" },
      "adapter": { "version": "2.0.0", "digest": "<sha256>" },
      "control_transport": { "kind": "rpc_stdio", "protocol": "pi-rpc" },
      "model_protocols": ["anthropic_messages", "openai_responses", "openai_chat_completions"],
      "capabilities": { "resume": true, "task_skills": true, "usage_tokens": true,
                        "steering": true, "follow_up": true },
      "options_schema": "pi/v1"
    }
  },
  "files": [ { "path": "…", "size": 123, "sha256": "…" } ]
}
```

**冻结要点**
- `model_protocols` 与事件/结果/矩阵一致；矩阵由 manifest 能力与 Endpoint 求交集，Task 创建与 verify-runtime 都验证，未知组合 **fail closed**。
- OpenCode 能力：`steering=false`、`follow_up=false`；当前不启动可投递 command 的 control endpoint，也不产生 `control.command.delivered`。
- 每个 Adapter 有独立 digest，共享库变更会改变所有引用它的 Adapter digest；Runtime Bundle digest 从 manifest `files` 递归计算。
- `verify-runtime.sh` 不再写死 claude/codex case；逐 manifest Adapter 验证官方制品、版本、摘要与 Bridge self-check。
- Registry API 只返回可展示 schema，不暴露启动命令、宿主路径或任意插件入口。

---

## 7. §3.5 冻结清单汇总

以下为本轮**冻结**的决策项（全部已由 probe 或既有 V1 语义支撑）：

| # | 冻结项 | 结论 | 依据 |
|---|---|---|---|
| 1 | event type / 必填 / 唯一终态 / 序列 | §3.1–3.3 | V1 harness_protocol.py + replay 语义 |
| 2 | command client ID / payload digest / attempt 内 sequence / 状态机 / ACK–reject | §4 | plan §4.6–4.7 + Pi/OpenCode probe |
| 3 | Bridge control endpoint framing / 最大文本长度 | §4.3（stdin JSON + Unix socket，4000 字符） | plan §4.7 + runner harness 结构 |
| 4 | `delivered`=原生 ACK 精确语义 | §3.3 | 当前仅 Pi `steer success:true` / `follow_up success:true` |
| 5 | queue update 无 command_id 审计边界 | §3.4 | Pi `queue_update` 无 ID |
| 6 | attempt control gate / 单 dispatcher 严格顺序 / settled/closing/drain 竞争 | §8 | plan §4.3 / §4.7 / §5.3 |
| 7 | OpenCode settled 判定与 crash 分类 | §8 + §5 | OpenCode `session.idle` + `abort` probe |
| 8 | 当前 Harness 协议兼容矩阵 | §10 | manifest + protocol-specific tests |
| 9 | 20 个 benchmark 任务/统计方法 | §11 | plan §8.5 / 架构 §13 |

---

## 8. settled / closing / drain 竞争（冻结）

attempt control gate 状态机（持久化在 `task_harness_attempts`）：

```
disabled → starting → accepting ⇄ closing → closed
```

- **不支持的 Harness（Claude/Codex/OpenCode 首发）**：从创建起保持 `disabled`。
- **Pi（支持 command）**：`starting` 开始 → Bridge control endpoint ready 后 `accepting` → 启动失败直接 `closed`。
- **正常 settled**：Bridge 收到 upstream settled candidate 时，在 attempt 行锁内 `accepting -> closing`，**停止接受新 command**；pump 继续按序排空 closing 前已分配的命令。
  - 若其中**已 ACK 的 follow-up** 让 Harness 开始下一轮 → gate 重开 `accepting`；
  - 否则队列排空后进入 `closed`，**才发出唯一 Harness terminal** 并允许公共 finalization。
- **cancel/timeout/强制终止**：`closing`，pump 确定性拒绝剩余 queued command，再 `closed`/终止 Bridge。
- **竞争线性化（冻结）**：`PUT` 与 `accepting->closing` 竞争的线性化结果只能是“已入库并被 drain”或“未入库且被拒绝”，**不能**留下 closing 后永远 queued 的 command。
- project 不使用 projector 参与这些状态迁移；gate 迁移由 Worker/pump 在 attempt 行锁内进行。

---

## 9. OpenCode settled 判定与 crash 分类（冻结）

- **settled 判定**：`session.idle`（SSE）**或** `GET /session/status` 不再 `{type:busy}`，须结合**最终 assistant message** 与 Session 状态共同判定，不以单一 busy/idle 字段决定（probe `events.observed.jsonl` 证实 idle 是 settled 信号；`abort` 后 assistant 消息带 `error:true` 进入错误态）。
- **crash 分类（V2 新增 `failure.kind`）**：
  - `crash`：Server 进程消失（`kill -9` 或异常退出）、HTTP 断线/Session missing——作为设备级异常由公共 Runner 的进程级 TERM/KILL 兜底；
  - `authentication_error` / `rate_limited` / `protocol_error` / `timeout` / `cancelled` 沿用 V1 分类。
- Server 崩溃与 Bridge 子进程都在公共 Runner 信号树中；退出时不遗留 daemon。

---

## 10. 当前 Harness 协议兼容矩阵（冻结）

| Harness | Anthropic Messages | OpenAI Responses | OpenAI Chat Completions |
|---|---:|---:|---:|
| Pi | 是 | 是 | 是 |
| OpenCode | 是 | 是 | 是 |
| Claude | 是 | 否 | 否 |
| Codex | 否 | 是 | 否 |

矩阵由 Runtime Bundle manifest 能力与 Endpoint `model_protocol` 求交集，Task 创建与 verify-runtime 都要验证；未知组合 fail closed。Backend/Frontend 不再维护两份不同矩阵。

> **实施与验收边界（冻结）**：Pi/OpenCode 的 V2 manifest、Backend upper bound、Task snapshot 和
> Adapter 已声明并处理三种协议。每种协议仍必须在真实 Endpoint/Task 上分别完成 conformance；不能以
> Anthropic-compatible probe 或源码声明替代真实成功/失败语义与 delivery 证据。

---

## 11. 20 个 benchmark 任务与统计方法（冻结）

### 11.1 任务集（沿用架构 §13 与 plan §8.5）

| # | 场景 | 覆盖 |
|---|---|---|
| 1–3 | plan / execute / freeform 模板任务 | 三种正式任务模式 |
| 4–5 | 工具成功 / 工具失败 | tool 生命周期、settled 后 delivery |
| 6 | 修复失败测试并重跑 CI | CI 修复闭环 |
| 7 | 无改动任务（`require_changes=false` 判定） | deliver 无改动路径 |
| 8 | resume / continue 同 lineage | Session 恢复、不跨 Harness |
| 9 | 取消（取消后 canceled 终态） | cancel/timeout/SIGTERM |
| 10 | 超时 / SIGKILL | Runner 兜底、子进程收敛 |
| 11 | context compaction | `context.compacted` 事件 |
| 12 | rate limit / provider retry | `provider.retry` / `rate_limited` |
| 13 | 认证失败 | `authentication_error` |
| 14 | 网络中断 / invalid session | 断线恢复、非法 Session |
| 15 | longest-context 长任务 | usage 上限、compaction 边界 |
| 16 | 多文件重构（小型 repo） | commit/push/MR |
| 17 | 单文件 bug fix | 最小改动 + MR |
| 18 | 纯分析无写任务 | 只读、无 changes |
| 19 | 失败后公共 delivery | delivery 在 settled 之后 |
| 20 | 高 token 生成任务 | usage/model、性能基线 |

### 11.2 统计方法（冻结）

- **每次采样记录**：成功/失败分类（`success` / `failure.kind`）、人工验收结果、耗时（中位/分位）、input/cached/output/reasoning Token、工具调用计数、delivery 结果。
- **对比基准**：与“当前较优兼容 Harness”做**同任务**对比（同一组 Endpoint/model 参数）。
- **硬指标**：成功率下降 ≤ 10 个百分点；中位耗时与 Token 不得同时恶化 > 25%。
- **样本治理**：修复后重跑受影响矩阵；**不把失败样本从 benchmark 删除**。
- Pi 额外跑命令投递、重复投递、断线、Scheduler 重启与 settled race；OpenCode 额外跑 Server crash、Abort、Agent、Command 与 Session 泄漏检查。

---

## 12. Phase 0 五风险评审

Phase 0 待决 5 项逐一裁量：可冻结的纳入 schema（本次已落地），需真实 V2 集成才可验的列入**后置依赖，不阻塞冻结**。

| # | 风险 | 裁决 | 去向 |
|---|---|---|---|
| 1 | **OpenCode 无独立 SHA256SUMS**（仅字节数 60,474,448 + release URL 对齐） | 运行可用已实测；可冻结版本 `1.18.19` 与字节数。但**校验证据薄弱** | **纳入 schema 冻结**（`artifact_version`/`artifact_sha256`），并列为**后置**：实施阶段以 npm 包元数据或镜像 digest 二次固定（`verify-runtime` 增加强校验项） |
| 2 | **Claude 2.1.152 SHA-256 未在 linux/amd64 重算**（V1 为 macOS Operator CLI） | Worker 侧为镜像注入，版本沿用 V1；**不阻塞 schema 冻结** | 后置依赖：实施阶段以 Worker-kit image digest 固定并写入 manifest `source` |
| 3 | **未触发场景**（Pi compaction/auto_retry；OpenCode `session.error`/权限阻塞/主动 crash 注入） | 不改变已冻结信封/类型；事件词汇已预留 `context.compacted`、`provider.retry`、`diagnostic`、`failure.kind=crash` | 后置依赖：V2 集成阶段补 probe，作为 Phase 2/3 的 conformance 输入 |
| 4 | **openai 双协议真实 Task 待验**（源码和 Bundle 已声明三协议） | 矩阵与 fail-closed 合同已冻结；真实 Endpoint/Task 行为仍不以源码声明代替 | 后置依赖：N3/L5 对 Pi/OpenCode 分别完成对应端点 conformance、usage、terminal 与 delivery 验证 |
| 5 | **OpenCode Node SDK 依赖**（`@opencode-ai/sdk`，新增 Node runtime） | Phase 0 probe 倾向 SDK；Phase 3 实现前置 gate 已将当前生产路径冻结为 Python HTTP/SSE Bridge，Node 成本不纳入当前 Bundle | 后置依赖：若未来重新引入 SDK，需单独核算 Node bundle 体积/离线可安装性并重新生成 composition evidence；当前不把 SDK 作为执行路径 |

**结论**：5 项均**不阻塞 schema 冻结**。FREEZE-ABLE 已纳入本文件（OpenCode 版本/字节数、crash 分类、3 控制事件）；需真实 V2 集成才可验的列入 Phase 2–4 依赖清单。
