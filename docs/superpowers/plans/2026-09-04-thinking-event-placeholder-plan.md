# 长思考事件占位与耗时展示实施方案

日期：2026-09-04

状态：待实施。本文件仅描述方案，功能、测试和部署尚未完成。

## 1. 目标与范围

将页面上的一段思考改成同一条记录的生命周期：收到真实开始信号后显示「正在思考」，前端本地计时，收到完成事件后原位展示完整内容和固定耗时。

本期先覆盖 **Pi**。当前 Pi Adapter 已识别 `thinking_start/thinking_delta/thinking_end`，并将完成内容投影成页面的 `thinking` 记录，问题发生在这条现有链路上。后端和前端按统一事件处理，不根据 Harness 名称推断状态。

范围固定为：

- 新增思考开始事件，沿用思考完成事件；中间片段继续只在 Adapter 缓存。
- 复用 `TaskLog`、`TaskPayload` 和已有 SSE `batch/update` 通道。
- 同一段思考只创建一条 `TaskLog`；正常情况下仅开始、完成各写入一次状态。
- 计时由前端本地完成，不逐秒写库或发送计时事件。
- 完成内容继续使用现有脱敏和按需加载机制；没有内容时只显示状态与耗时。
- 处理取消、异常结束、页面刷新、断线重连和事件重放。

本期不接入摘要增量展示、不调整其他 Harness 的内容策略、不改变 Task 执行状态机，不新增数据库字段、配置项、推送服务或通用活动状态系统。未收到思考开始信号时保留现有任务运行展示，不根据静默时长生成思考记录。

## 2. 当前代码依据

| 位置 | 当前行为 | 本期改动 |
|---|---|---|
| [pi_events.py](../../../deploy/worker-entrypoint/harness/adapters/pi_events.py) 的 `_handle_message_update` | 开始时清空缓存，结束时才发出 `reasoning_summary.completed`，空内容不发出完成事件 | 开始即发事件，开始和完成关联同一个思考 ID，空内容也能结束占位 |
| [worker_event_projector.py](../../../backend/app/core/worker_event_projector.py) | 收到完成事件才创建 `TaskLog` 和 `TaskPayload` | 开始创建占位，完成更新原行 |
| [task_log_stream.py](../../../backend/app/api/task_log_stream.py) | 按 `id > since_id` 获取新行，仅追踪工具调用的原位更新 | 追踪进行中的思考行，发送结束状态 |
| [useTaskLogStreams.ts](../../../frontend/src/features/tasks/useTaskLogStreams.ts) | 已有按日志 ID 合并更新；重连只使用最大日志 ID | 重连补读未完成思考记录，保持按 ID 合并 |
| [TaskProcessTextRow.vue](../../../frontend/src/components/task-process/TaskProcessTextRow.vue) | 只有静态标题、预览和全文按钮 | 增加进行中、完成、中断展示 |
| [worker_task_artifacts.py](../../../backend/app/core/worker_task_artifacts.py) 与 SSE 生成器 | 采集循环间隔为 2 秒，SSE 轮询间隔为 1.5 秒 | 保持现有间隔，首期目标为秒级反馈 |

现有 Task 日志 HTTP 接口已将 `log_metadata` 解析为 `metadata` 返回，不需要增加顶层响应字段或路由。`TaskLog.log_metadata` 为 JSON 文本，可容纳本期状态字段。

## 3. 页面行为

| 事实 | 页面展示 | 全文与计时 |
|---|---|---|
| 收到思考开始事件 | `正在思考 · 12 秒`，轻量动画 | 暂不显示全文按钮；本地计时 |
| 思考仍在进行 | 保持同一条记录 | 中间文本不展示，事件数量不增加 |
| 收到思考完成事件 | `思考完成 · 耗时 48 秒`，显示最终预览 | 停止计时；有内容时出现全文按钮，默认折叠 |
| 收到空内容的完成事件 | `思考完成 · 耗时 48 秒` | 停止计时；不出现无内容的全文按钮 |
| 未收到完成事件，Harness 已结束 | `思考记录已中断` | 停止计时；不把 Harness 结束时间当成精确思考耗时 |
| 没有可用 Harness 结束事件，但 Task 已进入终态 | 同样展示 `思考记录已中断` | 使用任务终态作为展示兜底，不持续转圈 |

「思考完成」仅说明该思考块结束，不代表 Task 成功。某段思考已经完成后，即使 Task 后续失败，其完成状态和耗时也保持不变。

完成更新保留原 `TaskLog.id`、`created_at` 和列表位置。用户向上阅读时不跳到底部；用户本来停留在底部时继续沿用现有自动跟随行为。状态和耗时在窄屏上允许换行，不能挤掉正文预览。

## 4. 事件合同

### 4.1 开始与完成

新增非终态事件 `reasoning_summary.started`，完成继续使用 `reasoning_summary.completed`。以下为省略 envelope 的事件片段：

```json
{
  "type": "reasoning_summary.started",
  "payload": {
    "reasoning_id": "pi-thinking-42"
  }
}
```

```json
{
  "type": "reasoning_summary.completed",
  "payload": {
    "reasoning_id": "pi-thinking-42",
    "text": "已完成的可展示内容",
    "client": "pi"
  }
}
```

约束：

- 关联键为 `(attempt_id, reasoning_id)`；前端使用投影后的 `TaskLog.id`。
- Pi 可以用开始事件在当前 raw 流中的行号生成 `pi-thinking-<line>`，同一段的结束事件复用该值。行号随整个流递增，不能只用每条消息内会重复的 `contentIndex`。
- `started` 必须包含非空 `reasoning_id`，不携带内容。开始时间使用该 canonical 事件的 `occurred_at`。
- 新 Pi Adapter 的配对完成事件必须携带相同 ID；结束时间使用完成事件的 `occurred_at`。
- `thinking_delta` 保持现有缓存处理，本期不新增增量投影。
- `thinking_end` 即使内容为空，也要发出完成事件，确保占位可以结束。
- 没有观测到开始时，不补造开始时间。已有独立完成事件仍可按静态内容展示，耗时留空。
- 保持现有脱敏和可展示内容边界，不新增原始内部推理输出。

### 4.2 注册与重放

在 Worker 的 `events.py::KNOWN_TYPES` 和后端 `harness_protocol.py::KNOWN_EVENT_TYPES` 同步注册开始事件，并同步 canonical v1 文档与 V2 schema 文档的事件列表。否则开始事件会被归一化成 `diagnostic`，页面仍收不到占位。

这是可选的非终态扩展，保持现有 schema 标识、envelope、序号和任务终态规则。首期由 Pi V2 发出；读取器识别该类型不意味着其他 Harness 已接入开始信号。

沿用 `(attempt_id, seq)` 事务去重。开始事件收据与占位行、完成事件收据与最终 payload/原行更新必须在各自同一个数据库事务中提交；事务失败后可以重新摄取，不能留下「收据成功但页面记录未更新」的状态。

## 5. 后端投影

### 5.1 占位元数据

开始时创建 `log_type=thinking` 的 `TaskLog`，不创建空 `TaskPayload`：

```json
{
  "attempt_id": "task-123-attempt-1-example",
  "reasoning_id": "pi-thinking-42",
  "status": "in_progress",
  "started_at": "2026-09-04T01:00:00Z",
  "ended_at": null,
  "duration_ms": null,
  "payload_id": null,
  "preview": "",
  "char_count": 0,
  "truncated": false
}
```

时间以 UTC 保存。`created_at` 继续表示日志创建时间且不再修改，思考耗时单独使用元数据中的事件时间。

### 5.2 完成更新

收到配对完成事件后：

1. 按 `task_id + attempt_id + reasoning_id` 找到占位行。
2. 脱敏最终内容；非空时创建一次 `TaskPayload`，填入现有预览和引用字段。
3. 更新原行的 `status=completed`、`ended_at`、`duration_ms`。正常耗时为两个 canonical 事件时间之差；无可信开始时间或时间顺序异常时留空，不伪造为零。
4. 空内容也更新状态，`payload_id` 保持空值，`char_count=0`。

查找允许使用内存索引加速，但数据库是恢复依据。Projector 重建后，须能从当前任务的思考行元数据恢复匹配；不得只查「最近 100 条」而遗漏尚未完成的记录。无需新增全局索引或迁移。

重复摄取同一 canonical 事件不得创建第二行或第二份 payload。多个连续思考块、多个原生 turn 必须使用不同 ID；不得把上一段的完成内容写入下一段。

### 5.3 缺少结束事件

- 收到 `harness.completed/harness.failed` 时，将当前 attempt 尚未完成的思考行更新为 `interrupted`；`ended_at` 记录观测到的结束时间，`duration_ms` 留空。
- 若 Pi 开始了下一段思考，但前一段没有完成信号，应结束前一段占位为 `interrupted`，避免旧记录持续计时。
- 已经 `completed` 的记录不因上述事件改变。
- 容器被强制终止且没有 canonical 结束事件时，由现有 Task 终态驱动前端停止占位。这是展示兜底，不补造 canonical 事件，也不为本功能扩展 Scheduler 的各个失败写入路径。
- 展示兜底不抢占后续有效完成记录：若归档补读拿到真实完成事件，按完成事实展示其内容和耗时。

## 6. SSE 与重连

### 6.1 结束状态推送

在 `generate_task_log_events` 中增加进行中思考行的追踪，与现有工具调用更新共用轮询周期：

- 从新日志批次识别 `thinking + status=in_progress`，记录待追踪日志 ID。
- 每轮查询待追踪行；当状态变成 `completed/interrupted` 时发送现有 `event: update`，然后移出集合。
- 查询同时限定 `task_id`，只推送当前任务的日志。
- **使用状态判断结束，不使用 `payload_id` 判断**，因为空思考也会正常完成。
- 进行中没有变化时不重复发送；本地计时不依赖重复 SSE 消息。
- 最终更新先于 `done` 发出，避免客户端提前关闭连接。
- 开始和完成都发生在一次采集或轮询窗口内时，可以直接发送最终行，不强制闪现占位。

### 6.2 从未完成记录之前补读

当前重连使用最大日志 ID，会漏掉断线期间被原位更新的旧行。本期复用现有 `since_id`，不增加接口参数：

```text
max_id = 已加载日志中的最大 ID，空列表时为 0
pending_ids = 已加载思考日志中 status=in_progress 的 ID

没有 pending_ids：since_id = max_id
存在 pending_ids：since_id = max(0, min(pending_ids) - 1)
```

这样首次 HTTP 加载后建立 SSE、以及断线重连时，都会重新读到尚未完成记录的最新快照。即使它已在断线期间完成，也不会被 `id > max_id` 跳过。

前端 `batch/update` 继续按 ID 合并，不追加重复行。同一记录的更新按到达顺序处理；已完成记录不能被较旧的 `in_progress` 快照覆盖。将这项合并规则同时用于 `TaskView.fetchLogs()`，避免较慢的 HTTP 快照覆盖较新的 SSE 完成状态；任务切换时仍按现有逻辑清空旧任务状态。

Task 已终止时，沿用已有终态触发的 `fetchLogs()` 和 `onStructuredDone` 刷新，补齐最终内容；未配对的开始记录依照第 5.3 节停止展示计时。

## 7. 前端实现

1. 在 `ParsedTextEntry` 中解析新增状态、开始时间、结束时间和耗时。无生命周期字段的已有内容行继续静态展示，不推测开始时间。
2. `TaskProcessPanel` 提供一个共享的当前时间值，可复用现有每秒计时器。只有处于运行中、且记录仍为 `in_progress` 时显示递增耗时，不为每条历史记录创建定时器。
3. `TaskProcessTextRow` 根据真实记录状态显示进行中、完成或中断。Task 已终止而记录仍在进行中时，派生为中断展示；Task 仍运行但连接暂断时，不把断连直接判为思考中断。
4. 进行中只显示标题、动画和耗时，隐藏全文按钮；完成后按现有 payload 加载逻辑展示预览和全文按钮。空内容、无 payload 的完成行没有全文入口。
5. 实际完成耗时以服务端 `duration_ms` 为准，`0` 是有效耗时，`null` 表示未知；本地计时为反馈用途，刷新后根据 `started_at` 恢复，不从零重新开始。
6. 计时 tick 只更新耗时，不重新解析日志、不触发全文 Markdown 渲染、不触发滚动。开始与完成更新遵循现有自动跟随开关。
7. 增加中英文文案，覆盖「正在思考」「思考完成」「思考记录已中断」「耗时」。复用现有视觉样式，并支持减少动画偏好与窄屏换行。

## 8. 实施步骤与文件

按 A → B → C → D → E 顺序完成，每一步以对应验收为结束条件。

### A. 事件合同与 Pi Adapter

修改：

- `deploy/worker-entrypoint/harness/events.py`
- `deploy/worker-entrypoint/harness/adapters/pi_events.py`
- `deploy/worker-entrypoint/harness/manifest.json`：同步 Pi Adapter 版本；具体版本在实施时按当前版本递增。
- `backend/app/core/harness_protocol.py`
- `docs/architecture/worker-canonical-event-v1.md`
- `docs/architecture/open-harness-v2-schemas.md`

验证：

- [ ] `thinking_start` 在 `thinking_end` 之前独立产生开始事件。
- [ ] delta 不产生本期新增的内容事件；空 `thinking_end` 仍产生完成事件。
- [ ] 同一块 ID 配对，多块、跨 turn 不串联。
- [ ] Worker writer 和后端验证器均保留开始类型，既有序号及终态校验继续生效。

### B. 占位与原行完成投影

修改：`backend/app/core/worker_event_projector.py`。

验证：

- [ ] 仅有开始事件时已存在可返回的 `thinking` 行，没有空 payload。
- [ ] 完成后原 ID、创建时间不变；内容、预览与固定耗时正确。
- [ ] 空完成、中断、多个思考块、重复摄取均不产生悬挂或重复记录。
- [ ] 在开始与完成之间重建 Projector，仍更新同一行；事务回滚后重试可恢复。
- [ ] 原有 assistant text、工具调用投影保持通过聚焦回归。

### C. SSE 完成更新与重连补读

修改：

- `backend/app/api/task_log_stream.py`
- `frontend/src/features/tasks/useTaskLogStreams.ts`
- `frontend/src/views/TaskView.vue`：HTTP 快照复用按 ID 合并和终态不回退规则。

验证：

- [ ] 开始通过 `batch` 到达，完成通过同 ID 的 `update` 到达。
- [ ] 空内容完成仍发送更新；最终更新在 `done` 前。
- [ ] 断线期间完成、HTTP 快照与 SSE 建连之间完成，均能补读最终行。
- [ ] 重放批次不重复计数，旧快照不能把最终行变回进行中。
- [ ] 同批快速完成不闪烁；其他任务的日志不会进入追踪结果。

### D. 卡片状态与本地计时

修改：

- `frontend/src/components/task-process/taskProcessUtils.ts`
- `frontend/src/components/task-process/TaskProcessTextRow.vue`
- `frontend/src/components/TaskProcessPanel.vue`
- `frontend/src/i18n/messages/zh-CN.ts`
- `frontend/src/i18n/messages/en.ts`

验证：

- [ ] 进行中每秒更新耗时，完成、中断后停止；刷新不清零，卸载释放定时器。
- [ ] 空内容无全文入口；正常完成仍能按需展开既有完整内容。
- [ ] Task 终态兜底停止悬挂占位，已完成思考不受 Task 后续失败影响。
- [ ] 每秒计时不增加日志数量、网络请求或 Markdown 渲染次数。
- [ ] 桌面和 360px 窄屏状态、计时、预览可读；阅读历史记录时无强制滚动。

### E. 聚焦验证与真实任务验收

后端修改或增加测试：

- `backend/tests/unit/test_pi_harness_adapter.py`
- `backend/tests/unit/test_harness_protocol.py`
- `backend/tests/unit/test_harness_events_v2.py`
- `backend/tests/unit/test_worker_payload_storage.py`
- 新增 `backend/tests/unit/test_task_log_stream.py`，直接覆盖 SSE 生成器的开始、更新、重连补读与 `done` 顺序。

前端修改测试：

- `frontend/src/features/tasks/useTaskLogStreams.spec.ts`
- `frontend/src/views/TaskView.spec.ts`
- `frontend/src/components/task-process/taskProcessUtils.spec.ts`
- `frontend/src/components/task-process/TaskProcessTextRow.spec.ts`
- `frontend/src/components/TaskProcessPanel.spec.ts`

按 [测试指南](../../TESTING.md) 使用定向测试命令。下列命令是实施后的验收命令，本方案编写时不执行。

在 `backend/` 运行：

```bash
.venv/bin/python -m pytest \
  tests/unit/test_pi_harness_adapter.py \
  tests/unit/test_harness_protocol.py \
  tests/unit/test_harness_events_v2.py \
  tests/unit/test_worker_payload_storage.py \
  tests/unit/test_task_log_stream.py -q
```

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

浏览器与运行环境验收：

- [ ] 用可控事件源在开始与完成之间保留至少 30 秒，验证用户能在结束前看到占位，结束后只有一条记录且耗时固定。
- [ ] 在该等待窗口内测试刷新，以及断线期间完成后重连；另测取消和缺少 canonical 结束事件的 Task 终态展示。
- [ ] 在实际服务页面检查桌面与移动视口、全文展开和滚动行为，不能只以组件测试或构建通过代替页面证据。
- [ ] 发布包含新 Adapter 的 Runtime Bundle 后，新建一个使用 Pi 和实际支持 Provider 协议的任务，确认开始事件、数据库占位、SSE 与页面状态完整衔接。

## 9. 延迟、发布与完成标准

现有 2 秒采集间隔与 1.5 秒 SSE 轮询间隔会叠加，此外还有 Docker 调用、数据库和网络耗时。首期在正常环境中以 **canonical 开始事件写出后约 5 秒内出现占位** 为验收目标，而非亚秒或模型开始计算时刻的保证。若模型直到较晚才提供开始信号，页面也只能从已观测信号反馈。

本期保持轮询间隔，只有实际验收发现额外延迟时再定位采集、提交或传输问题，不同时进行链路性能改造。

发布组成：

- Backend/Scheduler 使用识别新事件并支持占位投影的版本。
- Frontend 使用新状态渲染和重连逻辑的构建。
- Runtime Bundle 包含更新后的事件 writer、Pi Adapter 与对应 manifest/digest。此次不要求升级 Pi CLI 或重建 Worker Kit。
- 按现有发布流程协调上述组成，验收使用冻结了新 Runtime Bundle 的新 Task；不通过修改旧 Bundle 或重试旧快照来验证。

完成标准是 A–E 验收全部满足，并在已部署页面上证实「结束前可见、等待中计时、完成后同一行定稿、刷新与中断不悬挂」。文档完成、源码与测试通过、真实运行验收分别记录，不能相互替代。
