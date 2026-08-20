# Pi RPC 探针证据 (§3.2)

**制品：** Pi `0.84.2` linux-x64 · **传输：** RPC stdio (JSONL, LF-only framing) · **模型协议：** anthropic-messages / openai-responses / openai-chat-completions（Pi `agent` 声明支持三协议）

**probe 环境：** 远端 `v2probe` 容器（ubuntu 22.04 x86_64，即目标 Worker 架构）。凭据经 host env `$DEEPSEEK_ANTHROPIC_KEY` 注入 `~/.pi/agent/models.json` 的自定义 provider（`apiKey:"$ENV_VAR"` 插值），**key 从未进入命令参数、fixture、shell history 或终端输出**。本目录 raw fixture 已脱敏（session 路径 → `<PROBE_DIR>`、session UUID → `<SESSION_UUID>`、其余 UUID → `<UUID>`，无任何凭据）。

## Probe 矩阵结果

| 场景 | fixture | 结果 | 关键证据 |
|---|---|---|---|
| init / version / clean shutdown / fresh session | `success.raw.jsonl` | ✅ | `get_state` 返回真实模型/会话；`prompt success:true` 仅代表**接口 ACK**（非模型消费）；`agent_settled` 是真正的 settled 终态；流末干净关闭（无残留进程） |
| fresh / resume 会话 | `success.raw.jsonl` | ✅ | 每次 probe 以 `--session-dir` 新会话启动；`get_state` 反映 `messageCount:0`；可 resume 同一 sessionId |
| steer（工具调用后、下次模型调用前送达） | `steer.raw.jsonl` | ✅ | `queue_update` 的 `steering` 数组列出排队消息；**`steer success:true` 为原生 ACK（`delivered`），无 command_id**；steer 在 turn 边界送达，队列随后排空；两轮 turn 均完成 |
| follow-up（当前工作结束后继续处理） | `followup.raw.jsonl` | ✅ | `follow_up success:true` ACK；`queue_update.followUp` 记录排队文本；follow_up 成为第二轮独立 user turn，代理按新指令输出；`followUpMode: one-at-a-time` 生效 |
| settled / closing / drain 竞争 | `success/steer/followup` | ✅ | `agent_settled` 是 attempt 级 settled 判定；settled 前队列已排空 |
| abort / signal 清理 | `abort.raw.jsonl` | ✅ | 在 `agent_start` 后发 `abort`；assistant 消息 `stopReason: aborted`、`message_end`/`turn_end`/`agent_end(aborted)` 后 `agent_settled`；无残留进程（`pkill` 后干净） |

## 关键协议事实（V2 事件映射输入）

1. **`delivered` = 原生接口 ACK，不是模型消费。** `prompt`/`steer`/`follow_up` 返回的 `success:true` 只证明命令被接口接受/排队；真正的 settled 信号是 `agent_settled`。这与 §6.2 "delivered 精确定义为 Harness 原生接口已返回成功 ACK" 完全一致。
2. **Pi 原生 queue update 无 command_id。** `queue_update` 只携带队列内容（`steering[]` / `followUp[]`），不携带任何 Codify command/sequence ID。Bridge 只有在能证明关联时才可附带 ID 或顺序，**不能按文本猜测**（§6.2 明确要求）。
3. **控制事件词汇可用：** `control.command.delivered` / `control.command.rejected` / `control.queue.updated` 三个 V2 新增控制事件，与 Pi 的 steer/follow_up ACK + queue_update 一一对应。
4. **命令类型**：`steer`（工具调用后、下一模型调用前送达）、`follow_up`（当前工作结束后继续）。与 §6.3 首发命令类型一致。
5. **Pi 无显式协议版本号**：RPC 事件不带 schema/version 字段；协议版本由 Pi CLI 版本 (`0.84.2`) 隐式承载，V2 固定该版本。
6. **`followUpMode: one-at-a-time`** 与 `steeringMode: one-at-a-time` 为 get_state 暴露的控制面状态，映射到 V2 command 队列约束。

## 事件类型清单（Observed）

`response`(get_state/prompt/steer/follow_up/abort) · `agent_start` · `agent_end` · `agent_settled` · `turn_start` · `turn_end` · `message_start` · `message_update`(thinking/text/toolcall deltas) · `message_end` · `queue_update` · `tool_execution_*` · `compaction_*` · `auto_retry_*`（后三者未在本轮触发的长会话/重试场景中复现，列入待测：长上下文 compaction、provider retry）。
