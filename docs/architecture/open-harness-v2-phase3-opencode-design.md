# Open-Harness V2 — Phase 3 技术方案：OpenCode 一级 Harness

**日期：** 2026-08-21 · **状态：** 方案定稿，待方案审查 · **成熟度：** Internal Preview
**依据：** [open-harness-v2.md](open-harness-v2.md) §6/§8.2 | [冻结 Schema](open-harness-v2-schemas.md) | [实施计划](../superpowers/plans/2026-08-21-open-harness-v2-implementation-plan.md) §6
**证据：** Phase 0 OpenCode probe（`docs/harness-probes/v2/opencode/`）、已验收 Phase 2 Pi 适配器（`deploy/worker-entrypoint/harness/adapters/pi*.py`、`manifest.json`、`worker_event_projector.py`）

**交付结论：** 用 Task-scoped Server/SDK 边界交付 OpenCode 一级 Harness，首发不开放 live steering/follow-up，但控制面保留 capability negotiation + deterministic reject（证明公共 command plane 未来无需改造）。生产路径选官方 `@opencode-ai/sdk`，HTTP 直连仅诊断备援。

---

## 0. 与 Phase 2 Pi 的复用点与差异（总览）

| 维度 | Phase 2 (Pi, 已验收) | Phase 3 (OpenCode, 本方案) | 复用 | 差异 |
|---|---|---|---|---|
| 控制传输 | `rpc_stdio`（Pi RPC JSONL over stdio） | `server_http`（每 Task `opencode serve`，loopback 显式端口） | 无 | **架构分界**：stdio 单进程 vs 独立 Server + HTTP/SDK 客户端 |
| 适配器骨架 | `pi.sh` + `pi_bridge.py` + `pi_events.py` | `opencode.sh` + `opencode_bridge.py` + `opencode_events.py` | 同一 `adapter_{}` 合同、`_emit`/`_write_result`/`_usage` 归一化范式 | Server 生命周期、事件订阅、settled 判定 |
| 事件归一化 | 单 streaming 进程读 stdin→`_emit` canonical | Server 事件订阅（SSE）+ 最终消息拉取 | `_emit`、`sanitize`、`_failure_kind`、`_usage` | 事件来源是 HTTP/SSE 而非流 |
| control gate | `accepting→closing→drain` + `agent_settled` | `disabled`（首发无 command）+ **capability negotiation + deterministic reject** | Phase-1 `bridge.try_dispatch` / `control_client.py` 的 outcome 合同 | Pi 是 `accepting` 真接收；OpenCode 是 `disabled` 但谈判+拒绝 |
| manifest 能力 | `steering=true/follow_up=true` | `steering=false/follow_up=false` | manifest `capabilities` + `model_protocols` | 首发不开 command |
| settled | `agent_settled` = 权威 | `session.idle`(SSE) **或** status 非 busy + 最终 assistant message | 单 Harness terminal 收敛规则 | 需多信号共同判定 |
| crash 分类 | `_failure_kind(text)` | `crash` / `http_timeout` / `session_missing` / `invalid_agent_command` | `_failure_kind` 兜底 | 新增 Server/HTTP 层分类 |
| 退出清理 | SIGTERM → native abort → grace KILL | Server、Bridge、subprocess 进公共 Runner 信号树 | `adapter_terminate` | Server 属长期 daemon，需确定性收敛 |

**约束（同 Phase 2，全周期遵守）**：不改 V2 schema；Endpoint（Snapshot 的 model/base/credential）唯一事实源；每 Task Server 不跨 Task/Issue 泄漏；退出不遗留 daemon。

---

## 1. §6.1 Task-scoped Server 边界

### 1.1 启动与生命周期

- 每 Task 启动**一个** `opencode serve --hostname 127.0.0.1 --port <n>`。**端口交接方式（冻结，无竞态）**：不依赖 OpenCode 自分配随机端口后的“发现通道”（不存在该实体），而是由 Runner/`opencode.sh` 在启动前**先探测一个空闲 loopback 端口**并**显式 `--port <n>` 传入**（probe 已证实“可显式 `--port` 或默认随机”）。桥接无需发现即可用同一 `$OPENCODE_PORT` 直连，消除“Server 已绑某随机端口而 Bridge 不知”的竞态/不可达。
  - 探测：绑定 `127.0.0.1:0` 取内核分配的临时端口后立即释放，随即用于 `--port`；探测与 Server 绑定之间存在微小窗口，readiness 超时（§1.1）内对 `connection_refused` 重试即可覆盖（Server 尚未监听，非端口被占错误）。
  - `OPENCODE_PORT` 只经容器内环境注入给 `opencode.sh` 与 Bridge；不进用户日志/raw archive（同凭据规则）。
- **认证**：`opencode serve` 在未设 `OPENCODE_SERVER_PASSWORD` 时**未受保护**（probe 事实），因此**必须**设 `OPENCODE_SERVER_PASSWORD` 为 Task 私有随机值，用户名默认 `opencode`（`OPENCODE_SERVER_USERNAME` 可改）。Basic 认证：`Authorization: Basic opencode:<pw>`；校验以 401/200 区分。
- **端口/凭据只保存在容器内**，不进入用户日志、`event.jsonl`、raw archive 或诊断输出。密码不写盘（或写入 0600 Task 私有文件），只通过环境注入给 Bridge。
- **readiness 超时（冻结）**：`start()` 后必须等待 Server readiness（health/`/session` 可达），超时（默认 30s，profile `harness_options` 可调）则 `adapter_verify_runtime`/启动失败 → attempt 收敛为 `failed`（`failure.kind=engine_error` 或 `crash`），不进入 run。readiness 失败不重试启动。

### 1.2 退出与 daemon 收敛

- Server、Bridge、子进程都挂入公共 Runner 信号树：`adapter_terminate` 先尝试原生 `POST /session/{id}/abort`（若在途）→ 再收 Server 进程（SIGTERM）→ 公共 Runner grace 后 KILL。
- Server 属长期 daemon：退出时必须验证 Server 进程与监听 socket 均已消失，**不遗留 daemon**。可用同一个进程组 `kill -TERM -<pgid>` + 轮询消失；超时则 KILL。
- Scheduler 崩溃恢复识别 V2 RUNNING 容器后，重建日志 ingest + command pump；若 Server 已死而容器仍在，按 failure policy 通知 Runner 收敛（不进“半死”假 RUNNING）。

---

## 2. §6.1/§6.2 官方 SDK/HTTP client 选择（复用 Phase 0 判定）

**生产路径（冻结）**：官方 `@opencode-ai/sdk`（Node SDK，由 Server `/doc` 的 OpenAPI 3.1 规范生成，162 paths）。
**备援/诊断**：HTTP 直连 + 自维护 SSE 解析（仅在 Node 依赖不可接受时启用）。

- **选 SDK 的理由（probe 结论）**：稳定 OpenAPI 3.1 是唯一事实协议源；SDK 由该 spec 生成，类型与运行时一致，避免 hand-rolled 代理漂移；SDK 对 SSE 流式事件有封装，比裸 curl 订阅稳；`abort` 返回类型化 `true`，方法签名与 spec 对齐。
- **成本/风险（评审裁决 ②：实现前置 gate，非后置）**：SDK 冻结为正确生产路径，但整条 Phase 3 都建在 Node runtime 上——若 Node bundle 成本在实现后才被否，需整段重写 HTTP 退化路径。因此 **Node bundle 成本（Node runtime + SDK 版本冻结 + Worker 镜像离线安装体积）必须在编写 `opencode.sh`/Bridge **之前**以成本估算定案**（与 Phase 2 已核算的 Node bundle 叠加）；不满足 → **立即切 HTTP 直连**（诊断路径升级为生产路径，自维护 SSE 解析），避免在可逆转假设上开工。该门禁项前置到实现起步，见 §10 交付切分。

**SDK 使用边界**
- 每 Task 一个 Server，Bridge 只连本 Task 的 `127.0.0.1:${OPENCODE_PORT}`（显式传入，§1.1），不连外部/共享 Server。
- `model`/`baseURL`/`apiKey` 全部来自**冻结 Snapshot**（经 env `{env:...}` 插值注入），OpenCode 原生 Agent/Command/model variant 只能改变 Snapshot 允许的变体，**不能覆盖冻结 Endpoint**。
- OpenCode env 插值语法为 **`{env:VAR}`**（非 `$VAR`，probe 关键事实）；`compat_profile`（如 `deepseek-anthropic`）在 Endpoint 声明，不从 provider 层新增协议名。

---

## 3. §6.2 Session、能力与事件

### 3.1 Session 创建/恢复与事件订阅顺序（防漏首事件）

- **fresh**：`POST /session`（需 `model:{id,providerID}`，probe 事实）→ 返回 `ses_…` + `version` + `directory`；记录 `session_id` 到 `_STATE`（供 result v2 携带）。
- **continue / resume**：同一 Session ID 恢复既有会话（同 `issue_id + harness_key + session_namespace`）；`input_session_id` 存在时用既有 `ses_…` 恢复，否则 fresh。**禁止跨 Harness Session**（V1 lineage 不允许 V2 continue，首 Task 必须 fresh）。
- **事件订阅顺序（关键，防漏首事件，冻结）**：**先建立 `/event`(SSE) 订阅，再发 `prompt_async`**。否则 prompt 的早期事件（`session.status(busy)`、首 `message.part.*`）可能在订阅建立前被吞。订阅就绪信号 = 收到 `server.connected` 后再发 prompt。事件通过 SDK 的 SSE 封装订阅，缓冲到本地队列，由 `opencode_events.py` 归一化。
- 事件消费与 `/session/status` 轮询**互补**：SSE 作为主事件源；`session.idle` 是 settled 信号；`GET /session/status` 作为恢复/兜底（断线后重连请求最终状态）。

### 3.2 能力模型（§6.2，冻结）

| 能力 | 支持 | 说明 |
|---|---|---|
| `resume` | 是 | 同 Session 恢复（fresh/continue） |
| `task_skills` | 是 | OpenCode 官方加载路径物化 Managed Skills |
| `usage_tokens` / `usage_cost` | 是 | message 事件携带 usage → 归一化 |
| `steering` / `follow_up` | **否**（首发） | manifest `capabilities.steering=false/follow_up=false` |
| `run_text` | 否 | 一致（与 Pi 相同，走公共 delivery） |
| Agent / Command / model variant | 是 | 原生能力，但只允许 Snapshot 允许的变体 |
| Abort | 是 | `POST /session/{id}/abort`（200 `true`，已实测） |

### 3.3 事件 → V2 canonical 映射（新增 3 控制事件仍保留，但 OpenCode 首发只发 queue/审计与诊断）

新增 `opencode_events.py`，归一化以下 SSE 事件（probe `events.observed.jsonl`）：
- `session.created/updated`、`session.status(busy)` → 诊断/Session 状态（不直接发 canonical）
- `message.updated`、`message.part.updated`、`message.part.delta`（流式 token）→ `message.delta`/`message.completed`
- `session.diff` → 诊断（工具变更投影）
- **`session.idle` → 触发 settled 判定**（§4）
- `session.error`、permission/question 阻塞 → 诊断 + `failure.kind` 分类（未触发场景列实机项）

**事件归一化复用 Pi 范式**：`_emit`（调用 `CODIFY_CANONICAL_EVENT_WRITER`）、`_usage`（归一化，missing→`engine_fields.unavailable`）、`_failure_kind`（文本兜底）、`sanitize`（投影前清洗）。SSE `message.part.delta` 的文本与 Pi `message_update.text_delta` 在同一 `message.delta` canonical 下收敛。

### 3.4 `control_transport` / `model_protocols`（冻结值）

- `control_transport = {kind:"server_http", protocol:"opencode-server"}`
- `model_protocols = ["anthropic_messages","openai_responses","openai_chat_completions"]`（矩阵同 Pi，行为正确性列实机项）

---

## 4. §6.2 settled 判定（冻结）

**settled 判定 = 多信号共同，不以单一 busy/idle 字段决定**：

1. **`session.idle`（SSE）出现**，或
2. `/session/status` 返回不再 `{type:busy}`（断线恢复/兜底），且
3. **最终 assistant message 已到达**（message 流收尾，无未消费 part），且
4. Session 状态非 error。

三者满足 → attempt 进入 settled → 公共 Runner 决定 Harness terminal（剥离开 command gate——OpenCode 首发无命令，故 `agent_settled` 等价物直接收敛单 Harness terminal，**不进入 accepting→closing→drain**）。若 probe 证明上游有多 turn terminal，Bridge 收敛为一个 Harness terminal（与冻结规则一致）。

> **与 Pi 的差异（关键）**：Pi 的 settled 是唯一 `agent_settled`，逻辑简单；OpenCode 的 `session.idle` + 最终消息 + session status 需**组合判定**，不能只轮询 status。这是 `opencode_events.py` 状态机的核心复杂性。

---

## 5. §6.3 首发 command 边界（control endpoint 谈判 + 确定性拒绝）

**开局（冻结）**：OpenCode 首发 `manifest.capabilities.steering=false/follow_up=false`，attempt `control_state=disabled`（进入 `backend/bridge.negotiate_capabilities` 后 `steering/follow_up=False`，控制面不产生可投递队列）。

**但 Bridge 仍实现 control endpoint 的 capability negotiation + deterministic reject**（证明公共 command plane 未来无需改）：

- `opencode_bridge.py` 实现 `try_dispatch`（frame_version=1、outcome `ack|reject|unknown`，与 `control_client.py`/`pi_bridge.py` 同一 contract）。
- 当 pump/API 尝试向 OpenCode 投递 `steer|follow_up` 时：
  - capability 层 → `negotiate_capabilities(harness_key="opencode")` 返回 `steering=False/follow_up=False` → control gate 置 `disabled`；
  - `try_dispatch` 在 disabled gate 下**确定性 reject**：`status:"reject", rejection_code:"control_gate_closed", rejection_message:"opencode: steering/follow_up not supported in first release"`。`command_id`/sequence 不回写。
- **不做“再发一条 prompt”模拟已承诺的 steering 语义**（plan §6.3 明确禁止）。控制端点保留在未来把通用 command 映射为 OpenCode 原生运行中消息的位置，但首发只有 reject 路径可达。
- 因此**不发** `control.command.delivered/rejected`（无 command 可送达）；若异常收到命令帧，发 `control.command.rejected`（rejection_code=control_gate_closed）用于审计。

---

## 6. 错误分类（§6.2 crash 分类，冻结）

在冻结 `failure.kind`（V1 分类 + `crash`）内，新增 OpenCode 特定分类（经 `_failure_kind`/错误路径映射）：

| 场景 | `failure.kind` | 判定 |
|---|---|---|
| Server 进程消失 / 主动崩溃 | `crash` | SSE 断开 + 连接 ECONNREFUSED / 进程不在；公共 Runner TERM/KILL 兜底 |
| HTTP 断线 / 超时（非 crash） | `timeout` / `engine_error` | 请求超时、重连接失败；区分 Server 死 vs 网络瞬断 |
| Session missing / 无效 | `engine_error`（消息 `session_missing`） | `GET /session`/`POST` 404/不存在；fresh 失败重试受限 |
| Agent / Command 非法 | `engine_error`（`invalid_agent_command`） | Agent/Command/variant 不在 manifest/Snapshot allowlist；**不尝试运行非法值**（fail closed） |
| 401/429/网络 | `authentication_error` / `rate_limited` | 沿用 V1 分类 |
| provider 错误 | `engine_error` | 上游异常，`_failure_kind` 兜底 |

**fail-closed 原则**：未知 Agent/Command/model variant 在 Task 创建或 `prepare_config` 阶段拒绝，不拖到运行中；权限/question 阻塞（需工具场景）与 `session.error` 未触发场景列实机项（§9）。

---

## 7. 数据模型 / 接口骨架

### 7.1 复用的公共接口（Phase 2 已验收，不改）

- `adapter_{metadata, verify_runtime, detect_capabilities, prepare_config, build_command, materialize_skills, stream_events, normalize_result, terminate, run}`（`runner.sh` 生命周期，逐 op 存在性检查）。
- `bridge.try_dispatch` / `control_client.py` / `negotiate_capabilities`（frame_version=1、outcome `ack|reject|unknown`）——OpenCode 只改 `negotiate_capabilities` 的 harness_key 分支，不新增 frame contract。
- `worker_event_projector.py` 的 V2 审计分支（已在 Phase 2 增加 `agent_settled`/`control.*` 投影与 `_sanitize_sensitive_data` 清洗）——OpenCode 的事件经同一 projector，除无 command 外无需新分支。
- `manifest.json` 的 `capabilities`/`options_schema`/`model_protocols` 投影。

### 7.2 新增模块（建议，Phase 3 开发委派）

```
deploy/worker-entrypoint/harness/adapters/opencode.sh          # adapter_* 骨架（Server 启动/readiness/auth/terminate）
deploy/worker-entrypoint/harness/adapters/opencode_bridge.py   # SDK/HTTP client + session + prompt + abort + dispatch(reject)
deploy/worker-entrypoint/harness/adapters/opencode_events.py   # SSE→V2 canonical 归一化 + settled 组合判定
backend/tests/fixtures/harness_events_v2/opencode/             # 离线 fixture（success/abort/session_missing/crash）
backend/tests/unit/test_opencode_harness_adapter.py
```

`manifest.json` 新增 `opencode` 块。**该块按冻结 `runtime-manifest/v2` 的字段命名与结构落地（v2-ready），不沿用 V1 风格 `provider_protocols`**——使后续 v2 升级只是纯机械 rename/补字段，不重塑 opencode 条目：

```json
"opencode": {
  "support_tier": "first-class",
  "source": {
    "repository": "https://github.com/sst/opencode",
    "license": "Apache-2.0",
    "artifact_version": "1.18.19",
    "artifact_sha256": "7bb35487…"
  },
  "adapter": { "version": "2.0.0", "digest": "<sha256>" },
  "control_transport": { "kind": "server_http", "protocol": "opencode-server" },
  "model_protocols": ["anthropic_messages", "openai_responses", "openai_chat_completions"],
  "cli_version": "1.18.19",
  "cli_version_range": ">=1.18.19 <1.19.0",
  "options_schema": "opencode/v1",
  "capabilities": {
    "resume": true, "task_skills": true, "max_turns": false,
    "usage_tokens": true, "usage_cost": true, "run_text": false,
    "steering": false, "follow_up": false,
    "sandbox_mode": "container-boundary"
  },
  "files": []
}
```

> **manifest schema 决策点（评审裁决 ①）**：`runtime-manifest/v1`→`v2` **不并入 Phase 3**，拆为独立委派（属跨全量 Harness claude/codex/pi + bundle/verify/build 路径的横切变更，与“交付 OpenCode 一级 Harness”正交，捆绑会扩大波及/审查面、复杂化回滚——§8.2“移除即回滚”只对新增 Harness 成立，不覆盖 manifest 整体迁移）。**叠加 Finding 2**：opencode 块按上表 v2-ready 字段书写（`model_protocols`/`control_transport`/`source`/`adapter.digest`/`support_tier`），使后续 v2 升级只是 rename/补字段、可机械完成；代价是 opencode 条目后续随 v2 升级做一次有界调整，属可接受单一权衡。当前 `manifest.json` 仍为 `runtime-manifest/v1`，因 opencode 块 v2-ready，即使宿主文件仍 v1 也**不会**污染 registry/verify 消费面（消费端按 `model_protocols` 读取）。

### 7.3 options schema（`opencode/v1`，非 JSON 编辑器）

首版仅暴露 Task override 的**高频字段**（独立于 profile 默认）：

```json
{ "agent": "build", "command": null, "model_variant": null }
```

- `agent`/`command`/`model_variant` 只允许 manifest/Snapshot allowlist 值；未知值 Task 创建拒绝。
- Profile 默认与 Task override deterministic deep merge → 冻结到 `harness_config_snapshot`；Snapshot fingerprint 纳入 options。
- 低频设置（插件/MCP/project config）由可信仓库提供，但 Endpoint 模型字段始终由 Snapshot 强制覆盖。

---

## 8. 迁移 / 回滚 / 风险

### 8.1 迁移与部署

- **DB migration**：Phase 3 本身**无需新 migration**（复用 074 的 `model_protocol`/`harness_options`/`task_harness_commands`）。`opencode` 只是 manifest/registry 新 key + 新建 Options validator + adapter，无表结构变更。若已到 074 之后且需补充（如 options 校验器枚举），顺延新 migration，编号不复用。
- **Server/Host**：Worker 镜像需安装 Node runtime + 冻结 `@opencode-ai/sdk` + OpenCode `1.18.19`（离线）；`verify-runtime.sh` 逐 manifest Adapter 实际启动最小 Server probe（不只 `--version`）。OpenCode 块无 command → attempt `control_state=disabled`。
- **接线**：`harness_registry.py` allowlist 增加 `opencode`；Task 创建/verify-runtime 校验 OpenCode×Endpoint 的 `model_protocols` 交集。
- **Session**：fresh/continue 不串 Session；同一 Task Server 不泄漏到下一 Task。

### 8.2 回滚

- **应用层回滚**：OpenCode 是新增 Harness，不进默认；回滚=从 manifest/registry allowlist 移除 `opencode`，`opencode.sh`/Bridge 不注册。不触碰其他 Harness 与已冻结 schema。
- **数据**：不产生新表；已有 OpenCode Task 的 V2 attempt/event/result 按既有读取路径只读。无 command 行。
- **V2 schema**：Phase 3 不新增 schema 字段；若 manifest→v2 升级独立委派，其回滚是 manifest 版本回退（不涉及 DB）。
- **实机门禁**：OpenCode 需真实 Worker canary（Server/Session/Agent/Command/Abort/usage/delivery）通过才晋级；不通过或 P0/P1 缺陷 → 保持 canary/不启用（§13 架构验收）。

### 8.3 风险与缓解

| 风险 | 缓解 |
|---|---|
| Server busy/queue 语义演进（上游活跃） | 固定版本 `1.18.19`；settled 组合判定不依赖单一字段；首发不开 command |
| SDK/HTTP 依赖新增 Node bundle | **实现前置 gate**（评审裁决 ②）：编写 adapter 前以成本估算（Node runtime + SDK 冻结 + Worker 镜像离线安装体积）定案；不满足立即切 HTTP 直连（诊断路径升级为生产路径，自维护 SSE 解析），不在可逆转假设上开工 |
| 事件订阅首漏（订阅晚于 prompt） | 先订阅 `server.connected` 再 `prompt_async`（§3.1） |
| Server daemon 泄漏 | 公共信号树 + 进程组收敛 + 退出后验证（§1.2） |
| 未触发 SSE 场景（session.error/权限阻塞/自发崩溃） | 镜像内完成，列实机项（§9），Probe README 待决 3 |
| 三模型协议实机正确性 | 矩阵已冻结；anthropic 端点已测，openai 双协议列实机项（§9，probe 待决 4） |
| Node SDK 版本冻结 | 随 Server 版本页固定并用 npm 包元数据二次固定（probe 待决 1 的 OpenCode 侧） |

---

## 9. 不可复现/需实机的项（如实列出，不阻塞方案）

以下需在**已装 OpenCode + Node SDK 的远端 Worker** 上验证，本环境不可复现，由成员在此完成不了的列为硬切前真人/远端验证项：

1. **Server 实机生命周期**：真实 `opencode serve` 启动/readiness/随机端口认证/退出收敛（§1）。
2. **settled 组合判定实机**：SSE `session.idle` + 最终消息 + status 在真实 prompt 的多轮/长话/工具调用下的收敛（§4）。
3. **未触发 SSE 场景**：`session.error`、permission/question 阻塞（需工具场景）、Server 主动崩溃注入（`kill -9`）分类（§6）。
4. **三模型协议实机**：openai_responses / openai_chat_completions 用对应端点验证（仅 anthropic 端点已实测）。
5. **Abort 实机**：thinking/tool/idle 三阶段 abort + 后续消息错误态收敛。
6. **§6.4 OpenCode 完成门槛**：Server 启动/Session/Agent/Command/variant/Abort/crash/usage/Git delivery 全覆盖真实 Host canary；fresh/continue 不串 Session。
7. **manifest→v2 升级 + verify-runtime**（独立委派，评审裁决 ①）：逐 manifest Adapter 实际启动最小 Server probe（§8.1）；opencode 块已按 v2-ready 书写，升级为纯机械 rename/补字段。

以上与 Phase 2 的实机门禁（§5.2/§5.3/§5.5）同属硬切前远端验证清单，统一收口。

---

## 10. 交付切分建议（交 Leader/方案审查）

| 委派 | 责任区 |
|---|---|
| OpenCode adapter（`opencode.sh`/`opencode_bridge.py`/`opencode_events.py`） | §1–§6 全部行为。**前置条件（评审裁决 ②）**：先完成 Node bundle 成本估算并定案 SDK 或 HTTP 直连（实现前置 gate），再写 adapter，避免在可逆转假设上开工 |
| OpenCode fixture + unit | `harness_events_v2/opencode/` + `test_opencode_harness_adapter.py`（settled/abort/crash/session_missing/invalid） |
| manifest/registry/options | manifest →`opencode` 块（按 v2-ready 结构，见 §7.2）、`harness_registry.py` allowlist、`opencode/v1` Options validator |
| Backend registry API 投影 | 四 Harness 展示、OpenCode×Endpoint 矩阵交集 |

**方案审查退出条件**：§1–§9 冻结点可审核、约束满足（不改 V2 schema / Endpoint 唯一事实源 / 每 Task Server 不泄漏 / 无 daemon 遗留）；**Finding 1（无竞态端口交接，§1.1）与 Finding 2（manifest 块 v2-ready 字段，§7.2）已修订满足**；Node bundle 实现前置 gate 已列入；实机项如实分离。据此可分派 OpenCode 开发与审查复验。
