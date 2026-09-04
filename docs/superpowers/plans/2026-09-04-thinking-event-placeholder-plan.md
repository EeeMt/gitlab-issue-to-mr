# 四 Harness 思考占位与耗时展示实施方案

日期：2026-09-04

状态：Pi 与公共展示链路已实现；四 Harness 完整覆盖待实施、待验收。本文修订原方案，在现有实现上补齐 Claude、Codex、OpenCode，并修正公共链路中的单思考块假设。

## 1. 目标与完成边界

**Claude、Codex、Pi、OpenCode 四个 Harness 都必须正确支持「开始占位＋本地耗时＋完成原位更新」。** 最小版本限定交互复杂度，覆盖范围包含全部四个 Harness。

正确占位同时满足：

- 已观测到本次执行中真实的思考开始信号，页面在该段思考结束前出现记录。
- 一段思考对应一个稳定 ID 和一条 `TaskLog`，完成后更新原行，不追加第二条。
- 等待期间前端本地计时；完整内容可选，空内容也能正常完成并停止计时。
- 思考中断、任务取消或进程异常结束后不持续转圈；刷新和重连可以恢复状态。
- 不把 `run.started`、`turn.started`、session busy、SSE 心跳或一段静默直接标为思考；不在收到完成时补发一个虚假的开始事件。

**没有正文不等于没有思考状态。** 各 Harness 保持既有内容处理边界；本期可以只上报开始和结束，完成卡片没有全文按钮。模型没有产生思考块时不生成占位，但验收必须使用能触发真实思考的模型，不能以无思考响应代替覆盖证明。

本期复用现有 `TaskLog`、`TaskPayload`、canonical event 和 SSE `batch/update`。不做正文增量展示，不逐秒写库，不新增数据库字段、配置开关或通用活动状态服务。获取正确原生信号所必需的 Adapter、Runner 或 Bridge 改动属于本期范围。

## 2. 当前实现基线与缺口

已核对实现提交 `03a7ae2c` 和当前源码。该提交落地了 Pi 开始事件、占位投影、SSE 更新、重连合并和前端计时；以下是需要继续完成的工作，不再重复按“全部尚未实现”规划。

| 范围 | 当前事实 | 本次工作 |
|---|---|---|
| [Pi Adapter](../../../deploy/worker-entrypoint/harness/adapters/pi_events.py) | 已发出配对的 `reasoning_summary.started/completed` | 保留能力，补齐独立中断与多块回归 |
| [Claude Runner](../../../deploy/ci-claude.sh) 与 [Adapter](../../../deploy/worker-entrypoint/harness/adapters/claude_events.py) | Runner 未启用 `--include-partial-messages`；Adapter 忽略 thinking delta，完整 thinking 只发诊断 | 开启部分消息输出，按思考块映射生命周期 |
| [Codex Runner](../../../deploy/worker-entrypoint/legacy/codex-run.sh) 与 [Adapter](../../../deploy/worker-entrypoint/harness/adapters/codex_events.py) | 使用 `exec --json`；未映射 reasoning item | 验证冻结 CLI 的早期信号，按第 4.3 节选择并完成唯一运行路径 |
| [OpenCode Adapter](../../../deploy/worker-entrypoint/harness/adapters/opencode_events.py) | 原生 reasoning 生命周期和 reasoning part 目前都只生成诊断 | 在现有 HTTP/SSE Bridge 上补齐生命周期映射与重复快照去重 |
| [后端投影](../../../backend/app/core/worker_event_projector.py) | 已能原位完成；但每次开始都会中断同一 attempt 的全部未完成思考 | 按思考 ID 配对、去重和中断，支持交错块 |
| [SSE](../../../backend/app/api/task_log_stream.py) 与 [前端流合并](../../../frontend/src/features/tasks/useTaskLogStreams.ts) | 已支持思考状态更新、补读和合并 | 回归多个待完成 ID、空完成、重复和终态顺序 |
| [思考卡片](../../../frontend/src/components/task-process/TaskProcessTextRow.vue) | 已支持计时、完成和中断 | 四 Harness 复用同一展示，不增加 Harness 分支 |

本次文档核对不是对已有部署的重新验收；四 Harness 的真实覆盖以第 8 节矩阵为准。

## 3. 统一事件与展示合同

### 3.1 事件类型

沿用 `reasoning_summary.started` 和 `reasoning_summary.completed`，增加按块关闭的非终态事件 `reasoning_summary.interrupted`。三者使用同一 `reasoning_id`：

| 事件 | payload | 含义 |
|---|---|---|
| `reasoning_summary.started` | 非空 `reasoning_id` | 本次执行的原生思考块已开始 |
| `reasoning_summary.completed` | `reasoning_id`，可选 `text` | 该块正常结束，允许没有可展示内容 |
| `reasoning_summary.interrupted` | `reasoning_id`，简短 `reason` | 已开始的该块被取消，或其原生消息/turn 已结束而没有正常块结束信号 |

新增类型同步注册到 Worker `events.py::KNOWN_TYPES`、后端 `harness_protocol.py::KNOWN_EVENT_TYPES`，并更新 canonical v1 与 V2 schema 文档。保持 envelope、schema 标识、连续序号和 Task 终态规则；这些事件都不决定 Task 成败。

无正文的正常完成示例：

```json
{
  "type": "reasoning_summary.completed",
  "payload": {
    "reasoning_id": "opaque-block-id"
  }
}
```

### 3.2 ID、时间与重放

- 持久化关联键为 `task_id + attempt_id + reasoning_id`，前端 key 为 `TaskLog.id`。
- Adapter 根据原生 session/thread、message/turn 和 block/item 身份构造稳定的不透明 ID。不能单独使用会在下一条消息重复的块索引，也不能只用 Harness 名称。
- 去重依据包括原生事件/块身份；脱敏前后的映射必须稳定。重连重复事件不得获得新的思考 ID。
- 开始与完成时间沿用 canonical `occurred_at`，表示实时桥接器观测到原生边界的时间；不是模型内部计算的精确计量。完成耗时由服务端计算，未知值为 `null`。
- 接收到已结束块的历史快照时不生成活动占位。恢复同一 attempt 的事件应使用原有收据与记录；历史会话导入、resume 返回的既有 items 不作为新开始。
- 如果没有观测到开始，只能保存静态完成内容或诊断，不能补造开始时间。这种路径不满足本期的思考占位验收。

### 3.3 UI 语义

| 状态 | 展示 |
|---|---|
| `in_progress` | “正在思考 · 12 秒”，轻量动画，本地每秒计时 |
| `completed` | “思考完成 · 耗时 48 秒”，有最终内容时出现预览与全文入口 |
| 空内容 `completed` | 同样停止计时并展示已知耗时，没有全文入口 |
| `interrupted` | “思考记录已中断”，停止计时，不将 Harness/Task 结束时间充作精确思考耗时 |
| Task 已终止但记录仍未结束 | 前端派生为中断展示；后续真实完成记录仍可纠正这项展示兜底 |

本地计时只用于运行反馈，完成以服务端耗时为准；`0` 是有效值，`null` 表示未知。保持日志 ID、创建时间和位置，避免完成时重复计数或跳动。没有正文不能影响状态闭合。

## 4. 四个 Harness 的原生接入

### 4.1 Claude：启用部分消息并跟踪块边界

官方 [CLI 流式输出说明](https://code.claude.com/docs/en/headless#stream-responses) 要求配合 `--output-format stream-json --verbose --include-partial-messages`。官方 [流式 thinking 事件说明](https://platform.claude.com/docs/en/build-with-claude/streaming#thinking-delta) 区分块边界与 thinking delta；因此状态映射不以正文是否可见为条件。实际 CLI 转发行为仍须在冻结版本上验证。

实施：

1. 在 `deploy/ci-claude.sh` 主任务的参数中加入 `--include-partial-messages`，确保开始消息经过现有输出管道及时到达 Adapter。
2. 从 `stream_event` 的 `message_start` 记录消息 ID；根据当前会话、`parent_tool_use_id`（存在时）和消息 ID 维护块索引的归属。
3. `content_block_start` 且块类型为 `thinking` 时发开始；对应索引的 `content_block_stop` 发无正文完成。实际版本若有其他思考块类型，仅在原生探针证实其语义后纳入映射。
4. `thinking_delta/signature_delta` 不向页面输出正文，但不能令已识别的块边界丢失。后续完整 `assistant` 消息不能再生成第二条占位或完成。
5. 消息结束、原生取消/错误时，只中断该消息中缺少结束的活动块；正常结束的块保持完成。

必须用实际 `claude -p` 输出验证，而不能仅向 `translate()` 手工投递开始事件。若冻结 CLI 仍把思考边界延迟到结束，本期必须修正运行入口或采用经验证的版本；不将其标成已覆盖。

### 4.2 Pi：保留现有功能，使用统一的按块中断

- 保留 `thinking_start → started`、`thinking_end → completed` 和空内容完成。
- 现有 `pi-thinking-<raw-line>` ID 可继续用于同一原生流；跨 turn 不复用，重放仍依赖原有 canonical 收据。
- 若同一原生消息流出现下一段 start，且前一段没有 end，由 Pi Adapter 显式发出前一段 ID 的 `interrupted`；公共投影不再替所有 Harness 推断这件事。
- 原生 abort/error 和消息/turn 关闭只清理相应活动块。保留已有正文处理策略与最终内容展示。
- 回归连续块、空块、多 turn、取消和 Projector 恢复。

### 4.3 Codex：先验证 exec 信号，不满足就完成 App Server 接入

当前 Runner 使用 `codex exec --json`，当前 Adapter 没有 reasoning 映射。不能根据它存在 `item.started` 这个事件名称，就认定冻结版本会在思考期间输出 reasoning 的开始。

**本期前置决策，必须有明确出口：**

1. 对将要发布的 Kit/授权挂载中的实际 Codex CLI 做一次原生探针，记录版本、二进制摘要、模型协议和带接收时间的 JSONL。
2. 若 `exec --json` 确实在思考期间发出 `item.started` 且 `item.type=reasoning`，并有同 ID 的 `item.completed`：保留 Runner，只补 Adapter 映射、去重和取消处理。
3. 若只有完成事件，或开始实际直到结束才输出：**本期将 Codex 主任务 Runner 改为该 CLI 的 App Server stdio Bridge，不能把 Codex 留作后续工作。**
4. 探针后将选定路径、CLI 版本和证据冻结到 Runtime Bundle。每个 Bundle 只有一条主任务运行路径，不在执行失败时自动切换 transport。

官方 [Codex App Server 协议](https://learn.chatgpt.com/docs/app-server#protocol) 提供 stdio JSON-RPC；[item 生命周期](https://learn.chatgpt.com/docs/app-server#items) 包含 reasoning item 的 `item/started` 与 `item/completed`，并区分可读摘要和原始内容。这证明有可选原生接口，不代替冻结 CLI 的实测。

若采用 App Server，必须一并完成以下集成，不能只另开一个观察进程：

- 由 Task 容器中的单个 Bridge 启动 Codex 子进程，完成初始化、`thread/start` 或 `thread/resume`、`turn/start`，持续消费同一执行实例的通知。
- 仅将当前任务 thread/turn 的实时 reasoning item 映射为占位，使用包含 thread、turn、item 身份的 ID。resume 响应中的历史 items 不重复投影。
- 以 reasoning 的 `item/completed` 关闭思考块；`turn/completed` 只用于整轮结果及剩余块收尾。取消经 `turn/interrupt` 和既有进程 TERM/KILL 兜底，失败与超时按原有失败分类处理。
- 同时接回助手最终回复、工具调用、usage、上下文压缩、session ID 和结果文件，使现有共享交付仍有完整输入。EOF 或启动成功均不能代替成功终态。
- 保持冻结的 Provider/模型/认证配置、运行用户、任务 Skills、工作目录、sandbox 与审批策略、Git 写入限制，以及 session 保存/恢复边界。权限请求不得因更换 transport 被无条件放行。
- 更新 Codex manifest 的 `control_transport`、Adapter 版本及 Bundle 摘要；同步被该元数据变更影响的合同、目录和测试。使用现有 `rpc_stdio` 类别表达本地协议，并记录 Codex App Server 协议名。
- Bridge 封装在 Runtime Bundle 内，CLI 来自 Kit 或授权挂载。若冻结 CLI 不具备所需接口，选择并验证可用制品后更新冻结身份；不能只改版本标签。
- 本期不顺带开放 Codex steering、follow-up 或其他控制能力；transport 的功能范围仍由现有能力声明约束。

### 4.4 OpenCode：接回 reasoning 生命周期与活动 part

保留现有 Task-scoped HTTP/SSE Bridge。当前 Adapter 已识别 `session.next.reasoning.*`，但统一降为诊断；上游 [事件 schema 记录](https://github.com/anomalyco/opencode/blob/dev/specs/v2/schema-changelog.md#2026-06-03-durable-reasoning-and-hosted-tool-replay-metadata) 也列出 started/ended。具体字段和运行中的事件族以冻结 Server 的 `/doc` 与原生探针为准，不照搬 dev 分支作为发布证据。

两类现有输入按实际事件族处理：

| 原生输入 | 映射规则 |
|---|---|
| `session.next.reasoning.started` | 使用 session、assistant message、reasoning 身份发开始 |
| `session.next.reasoning.ended` | 同 ID 正常完成；原生失败/中断信息按其已验证语义映射为中断 |
| `message.part.updated`，reasoning part 正在进行 | 首次观测该活动 part 时发一次开始 |
| 同一 reasoning part 的结束快照 | 发一次完成，不受正文是否为空影响 |
| 首次见到的快照已经结束 | 不补发活动占位；作为完成快照处理 |
| reasoning delta | 本期不展示增量正文，也不反复创建或延长占位 |

补齐要求：

- part 身份包含 session、message、part ID；过滤其他 session 的全局 SSE 消息，复用现有所属 Task 校验。
- 活动与结束判定依据当前版本实际 schema，例如 part 的时间/状态字段；不能仅因出现 `type=reasoning` 就认定它正在运行。
- 同一块若同时有 durable 生命周期与 part 快照，必须关联去重；在冻结版本不能证明二者对应时，选定该运行路径的权威事件族，禁止双重投影。
- 保留“订阅建立后再提交 prompt”的顺序，防止开始消息在订阅前丢失。
- 对当前 message/step 的错误、abort、关闭事件按块收尾；`session.idle` 不直接充当所有块的正常完成。
- 思考正文继续按当前内容边界处理，状态事件不再因为正文被省略而一并变成诊断。

## 5. 修正公共投影、去重与中断

沿用现有 metadata：`attempt_id`、`reasoning_id`、`status`、`started_at`、`ended_at`、`duration_ms` 和 payload/预览字段，无需数据库迁移。

### 5.1 按 ID 更新，去除单活动块假设

当前 `reasoning_summary.started` 分支先调用 attempt 级 `_interrupt_thinking_rows()`，该行为必须删除。改为：

1. started：按关联键查询；不存在才创建无 payload 的占位，重复开始保持原行和原开始时间。
2. completed：仅更新对应块。无正文照常完成；重复完成不创建第二份 payload，不重置时间。
3. interrupted：仅关闭指定的未完成块，`duration_ms=null`；该动作不影响其他块或已经完成的记录。
4. Harness 最终结束时，保留 attempt 级中断作为统一兜底；Task 终态展示兜底继续保留。
5. 各 Adapter 在其原生消息/turn 生命周期内决定缺失 end 的块何时中断，公共投影不靠“另一块开始”猜测。
6. 没有开始的结束事件不创建活动记录；空内容孤立结束只记必要诊断，有内容时沿用静态展示。

必须通过交错序列：`A.start → B.start → A.complete → B.complete`。A、B 均只出现一次，B 的开始不能中断 A。跨 attempt 的同名 ID 也不能互相更新。

### 5.2 恢复与数据一致性

- 数据库是配对的恢复依据，Projector 重建后仍能定位原行；不依赖仅存在内存中的关联。
- 同一事务提交 canonical 收据与投影，继续执行连续序号和重复冲突校验。
- 除 `(attempt_id, seq)` 去重外，还必须处理原生流用不同事件序号重复发送同一块快照的情况。
- 对同一块的过时开始/进行中快照保持最终状态；有冲突的不同终态按原生序号和事实处理并保留诊断，不能按 HTTP/SSE 到达先后覆盖。
- 正常完成耗时取可信的配对时间差，时间异常或没有开始时留空；Task/Harness 终态时间不冒充块正常结束时间。
- 完成卡片不会因为 Task 随后失败而变成中断。前端派生的 Task 终态兜底不改变 canonical 事实。

## 6. 复用 SSE 与前端展示

已有能力继续保留，并增加多块回归：

- SSE 追踪所有进行中思考 ID，状态变为 completed/interrupted 时发原 ID 的 `update`；空完成也发送。
- 最终更新先于 `done`，快速开始/结束允许一次发送最终行，不制造占位闪烁。
- 重连仍从前端最早未完成记录之前补读：有 pending 时 `since_id=max(0,min(pending_ids)-1)`，否则使用最大已加载 ID。
- HTTP 快照、SSE batch/update 共用按 ID 合并规则。重复消息不增加数量，过时进行中快照不覆盖最终状态。
- 多个思考卡片共用一个本地时钟；计时 tick 不增加 API 调用、数据库写入、日志行或全文渲染。
- 四个 Harness 使用同一 UI，不根据 Harness 名称、正文非空或模型名决定是否展示占位。
- 完成前无全文入口，完成后按现有内容加载；用户阅读历史时不强制滚动。完成更新保留已有展开状态。
- 桌面、360px 窄屏、中英文和减少动画偏好均纳入回归。

## 7. 实施步骤与文件范围

| 步骤 | 必须交付 | 主要文件 |
|---|---|---|
| A. 原生协议探针 | 四 Harness 开始/结束时序；冻结 Codex 的唯一运行路径和 OpenCode 的权威事件族 | 复用 `scripts/harness-probes/`，新增本功能 fixture 与对应证据 |
| B. 公共按块生命周期 | interrupted 事件、重复开始/完成幂等、交错块正确配对 | `backend/app/core/harness_protocol.py`、`worker_event_projector.py`；`deploy/worker-entrypoint/harness/events.py` |
| C. 四 Adapter 接入 | Claude 部分消息；Codex 选定 transport 的完整运行；Pi 独立中断；OpenCode reasoning 映射 | 四个 `*_events.py`、`deploy/ci-claude.sh`；必要的 Runner/Bridge |
| D. 公共展示回归 | 多 pending ID 重连、空内容完成、最终状态不回退、同一行更新 | `backend/app/api/task_log_stream.py`；现有前端流合并、卡片和 TaskView |
| E. 冻结发布与验收 | 新 Bundle、全部合法协议组合真实任务和页面证据 | manifest、Runtime Bundle、事件合同文档及验收记录 |

A 完成后冻结选择，不让“还需验证信号”成为跳过某个 Harness 的出口。B、C、D 完成后才能进入 E；实现顺序允许分步落地，最终完成标准始终包含四个 Harness。

主要修改文件清单：

- `deploy/worker-entrypoint/harness/adapters/claude_events.py`
- `deploy/worker-entrypoint/harness/adapters/codex_events.py`
- `deploy/worker-entrypoint/harness/adapters/pi_events.py`
- `deploy/worker-entrypoint/harness/adapters/opencode_events.py`
- `deploy/ci-claude.sh`
- `deploy/worker-entrypoint/harness/adapters/codex.sh`
- `deploy/worker-entrypoint/legacy/codex-run.sh`
- 如选择 App Server，新增 `deploy/worker-entrypoint/harness/adapters/codex_bridge.py`，接入现有 Runner；旧 Bundle 保持冻结，新 Bundle 主任务不保留自动回退双路径。
- `deploy/worker-entrypoint/harness/adapters/opencode_bridge.py`：仅在探针证实订阅、过滤或传输丢失思考边界时修改。
- `deploy/worker-entrypoint/harness/manifest.json`
- `deploy/worker-entrypoint/harness/events.py`
- `backend/app/core/harness_protocol.py`
- `backend/app/core/worker_event_projector.py`
- `backend/app/api/task_log_stream.py`
- `frontend/src/features/tasks/useTaskLogStreams.ts`
- `frontend/src/components/task-process/taskProcessUtils.ts`
- `frontend/src/components/task-process/TaskProcessTextRow.vue`
- `frontend/src/components/TaskProcessPanel.vue`
- `frontend/src/views/TaskView.vue`
- `docs/architecture/worker-canonical-event-v1.md`
- `docs/architecture/open-harness-v2-schemas.md`
- `docs/architecture/open-harness-v2.md`：若改变 Codex transport，同步当前架构说明。

公共 SSE/前端文件以第 6 节的实际缺口为修改依据，已经通过的既有能力保留。App Server 路径另外检查 `harness_registry.py`、`worker_runtime_bundle.py` 和 `harness_sessions.py` 的 transport、版本及 session 合同，按实际影响更新，不另建一套 Task 生命周期。

## 8. 验证与验收矩阵

### 8.1 每个 Harness 都要具备的用例

| 场景 | 验收结果 |
|---|---|
| 长思考，开始与结束间隔至少 30 秒 | 结束前已显示活动占位；最终同一行完成 |
| 正常空内容完成 | 停止计时、显示已知耗时，无全文按钮 |
| 连续两段、跨 turn | 各自 ID、各自耗时，不串行覆盖 |
| 相同索引属于不同消息/原生流 | 不误配；允许来源范围内实际存在的交错 |
| 重复开始、重复完成、重复 part 快照 | 一条记录、最多一份最终 payload，时间不重置 |
| 只有完成/历史已结束快照 | 不补造活动占位，不伪造开始时间 |
| 取消、原生错误、缺少结束、进程强杀 | 对应块中断或终态兜底，其他已完成块保持原状 |
| 开始后刷新、断线期间完成、恢复 Projector | 原 ID 最终完成，不重复、不悬挂 |
| 正文省略、脱敏 | 生命周期仍有效，敏感正文不进入新增事件 |

长思考时序测试同时覆盖：可控上游/原生接口的持续等待，用于确定性验证链路；以及真实 Provider 的实际长思考任务。仅直接调用 Adapter 翻译函数、或一次思考很短的成功任务，不足以证明开始信号实时可用。

### 8.2 全部合法 Harness × 模型协议组合

沿用冻结的合法协议矩阵；每行都需有实际思考开始早于结束、最终状态正确和页面显示的证据。

| Harness | 模型协议 | 本功能验收 |
|---|---|---|
| Claude | `anthropic_messages` | 待完成 |
| Codex | `openai_responses` | 待完成 |
| Pi | `anthropic_messages` | 在修订后的公共链路上重新验收 |
| Pi | `openai_responses` | 在修订后的公共链路上重新验收 |
| Pi | `openai_chat_completions` | 在修订后的公共链路上重新验收 |
| OpenCode | `anthropic_messages` | 待完成 |
| OpenCode | `openai_responses` | 待完成 |
| OpenCode | `openai_chat_completions` | 待完成 |

每行使用该组合下支持思考的真实模型。记录 CLI、Kit、Bundle、Provider 协议及模型身份、原生事件接收时间、canonical 序号/ID、TaskLog ID 和浏览器证据。至少每个 Harness 的一条真实运行还要覆盖取消与刷新/重连，纯状态卡片也属于正式验收对象。

源代码单元测试覆盖全部边缘序列；浏览器交互回归可以共用组件测试，但每个 Harness 的真实页面映射不能由 Pi 的成功代替。尚无原生信号或尚无可运行 Provider 的行保持未完成，整个四 Harness 覆盖不得关闭。

### 8.3 测试文件与命令

修改四个 Adapter 单测及 `test_ci_claude_script.py`、`test_harness_protocol.py`、`test_harness_events_v2.py`、`test_worker_payload_storage.py`、`test_task_log_stream.py`。App Server 路径新增 `test_codex_app_server_bridge.py`，并回归现有 Codex runtime/session/执行策略测试；更新受影响的原生 fixture，不能篡改既有历史证据。

按 [测试指南](../../TESTING.md)，在 `backend/` 运行以下聚焦测试（实施时执行）：

```bash
.venv/bin/python -m pytest \
  tests/unit/test_claude_harness_adapter.py \
  tests/unit/test_codex_harness_adapter.py \
  tests/unit/test_pi_harness_adapter.py \
  tests/unit/test_opencode_harness_adapter.py \
  tests/unit/test_ci_claude_script.py \
  tests/unit/test_harness_protocol.py \
  tests/unit/test_harness_events_v2.py \
  tests/unit/test_worker_payload_storage.py \
  tests/unit/test_task_log_stream.py -q
```

若选择 App Server，还需运行新增 Bridge 测试，以及受 transport/Bundle/session 改动影响的 `test_harness_registry.py`、`test_worker_runtime_bundle_v2.py`、`test_harness_sessions.py` 和 `test_harness_execution_policy.py`。

在 `frontend/` 运行：

```bash
npx vitest run \
  src/features/tasks/useTaskLogStreams.spec.ts \
  src/views/TaskView.spec.ts \
  src/components/task-process/taskProcessUtils.spec.ts \
  src/components/task-process/TaskProcessTextRow.spec.ts \
  src/components/TaskProcessPanel.spec.ts
npm run build
```

## 9. 发布与完成标准

保持现有 2 秒事件采集、1.5 秒 SSE 轮询间隔。正常环境中，以 **实时 canonical 开始事件写出后约 5 秒内出现占位** 为验收目标；另须证明这个开始本身发生于原生思考结束前，不能只测最后一段传输。

部署组成必须匹配：Backend/Scheduler、Frontend、新 Runtime Bundle 中的 writer/Adapter/Bridge，以及冻结的 CLI/Kit 身份。CLI 若需升级，真实验证后一起更新；单改源码或 manifest 版本标签不算完成。使用冻结新 Bundle 的新 Task 验收，旧快照和旧 Bundle 保持不变。

关闭本方案前必须满足：

- [ ] Claude、Codex、Pi、OpenCode 四者均实际发出可用于提前展示的开始和结束信号。
- [ ] 第 8.2 节全部 8 个合法协议组合完成真实验收，包含只有状态而没有正文的情况。
- [ ] 公共投影支持按 ID 配对、重复去重与交错块，不再用新块开始中断整个 attempt。
- [ ] 正常完成、空完成、取消/异常、刷新/重连均保持同一条记录的正确状态。
- [ ] 每个 Harness 至少一条真实长思考页面证据，开始占位先于完成出现，计时停止正确。
- [ ] 若 Codex 更换 transport，原有 session、权限、工具、usage、最终结果和共享交付回归完成。
- [ ] 源码/测试、Bundle 组成、真实任务、浏览器验收分别记录，并同步本文件进度。

**四个 Harness 全部完成是本方案的交付条件。任何一个仍然只有完成后展示、只显示通用等待状态或尚未验证原生信号，都不能标记整体完成。**
