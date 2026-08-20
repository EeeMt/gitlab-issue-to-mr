# Claude / Codex V2 回放 fixture 与字段映射 (§3.4)

**范围：** 从 V1 已冻结的 raw 捕获（`backend/tests/fixtures/harness_events/{claude,codex}/*/stdout.jsonl`）确定性重导出 V2 canonical（`codify.worker.event/v2`），并记录 V1→V2 字段映射。**不重新跑 CLI** —— raw 事件流不变，只改 canonical 信封与版本 pin。

## 生成器

`scripts/harness-probes/v2/replay_v2.py`（幂等；`--check` 防漂移）。

```bash
# 生成 Claude / Codex success 的 V2 canonical
python3 scripts/harness-probes/v2/replay_v2.py claude backend/tests/fixtures/harness_events/claude/success --write-to docs/harness-probes/v2/claude/success.v2.jsonl
python3 scripts/harness-probes/v2/replay_v2.py codex  backend/tests/fixtures/harness_events/codex/success  --write-to docs/harness-probes/v2/codex/success.v2.jsonl
```

## V1 → V2 canonical 字段映射

| 字段 | V1 | V2 | 说明 |
|---|---|---|---|
| `schema` | `codify.worker.event/v1` | `codify.worker.event/v2` | 信封版本 |
| `harness.adapter_version` | `1.0.0(-candidate)` | `2.0.0` | V2 Bridge/Adapter |
| `harness.cli_version` | codex `0.146.0-alpha.3.1` / claude `2.1.152` | codex `0.146.0` / claude `2.1.152` | 对齐 §3.1 固定版本；codex 以二进制报告 `0.146.0` 为准 |
| `harness.control_transport` | （无） | `{kind,protocol}` | 新增：claude=`cli_stream_json/claude-json`、codex=`cli_jsonl/codex-jsonl`、pi=`rpc_stdio/pi-rpc`、opencode=`server_http/opencode-server` |
| `harness.model_protocols` | （无） | `[...]` | 新增：claude=`[anthropic_messages]`、codex=`[openai_responses]`、pi/opencode=三协议 |
| `event_id` | `…-event-N` | `…-event-N-v2` | V1/V2 fixture 不冲突 |
| **不变** | 事件类型词汇（run/model/tool/message/harness/worker）、`(attempt_id,seq)` 幂等、`worker.finalization` 后唯一 task terminal、单 harness terminal | 同左 | V2 继承 V1 不变量（§6.2） |

## 新增 V2 控制事件（不反向合成）

`control.command.delivered` / `control.command.rejected` / `control.queue.updated` 只由 Pi/OpenCode 这类**运行中可被指挥**的 harness 在真正投递/拒绝命令时发出；它们是审计事件，**不能从 V1 CLI 捕获反向合成**。其证据来自本目录 [pi/](../pi/)（steer/follow_up ACK + queue_update）与 [opencode/](../opencode/)（abort/event）的独立 probe。

- `delivered` = Harness 原生接口返回成功 ACK（`steer success:true` / `follow_up success:true` / OpenCode 204），**不保证模型已消费/执行**（§6.2）。
- `rejected` = 原生接口拒绝、Task 已关闭控制入口、或确定性 transport 错误。
- Pi 的 `queue_update` 无 command_id；Bridge 仅在能证明关联时才附带 ID，不按文本猜测。

## Claude / Codex 回放 fixture

- `claude/success.v2.jsonl` — Claude success 场景的 V2 canonical（11 事件）
- `codex/success.v2.jsonl` — Codex success 场景的 V2 canonical（9 事件）

> 完整的 V1 场景矩阵（tool_success/tool_failure/rate_limited/network_interruption/timeout/sigterm/sigkill/cancelled/context_compaction/usage_model/resume/new_session/invalid_session 等）现成存在于 `backend/tests/fixtures/harness_events/{claude,codex}/`；V2 实施阶段可对整矩阵批量跑 `replay_v2.py --write`。本轮以 success 为代表样本完成字段映射回放，其余场景为纯信封变换，确定性等价。
