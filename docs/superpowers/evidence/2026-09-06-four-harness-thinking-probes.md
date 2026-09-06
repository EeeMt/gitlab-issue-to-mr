# 四 Harness 思考生命周期：原生信号探针与运行路径决策

日期：2026-09-06
关联：[2026-09-04-thinking-event-placeholder-plan.md](../plans/2026-09-04-thinking-event-placeholder-plan.md)（rev2 四 Harness 版）

## 探针方法与边界

按方案 §4.3，Codex 先做真实 CLI 原生探针再冻结唯一运行路径。本环境可用：
- 冻结制品：npm `@openai/codex@0.146.0-alpha.3.1`（manifest 冻结代际 `0.146.0`），Claude Code 宿主 `2.1.220`（在冻结范围 `>=2.1.33 <3.0.0` 内）。
- Provider：OpenRouter（anthropic / responses / chat 三类 wire，`z-ai/glm-5.2:free`、`minimax/minimax-m3:free`）、opencode zen（`/zen/go` 与 `/zen/go/v1`，deepseek/minimax/luna/mimo）。

## 尝试与结果（原始记录在 /tmp/codex-probe/*.jsonl，密钥经后端解密进程内注入，未落盘）

1. `codex exec --json`（0.146.0-alpha.3.1 + responses wire → OpenRouter GLM-5.2:free）
   - 结果：持续 `429 Too Many Requests`（请求 id `a369…-HKG`），失败重试后 `turn.failed`。另有 `Model metadata for z-ai/glm-5.2:free not found`（free tier 元数据缺失）警告。
   - 结论：**无法在本环境获得成功的思考期输出**，exec 路径 reasoning `item.started` 是否早于 `item.completed` 无法实测。
2. `codex exec --json`（0.146.0-alpha.3.1 + zen `/zen/go/v1` luna）
   - 结果：`403 unsupported_country_region_territory`（地区限制）。
   - 结论：zen 网关对本机出口地区不可用。
3. 宿主 `codex-cli 0.130.0`（exec 参数语义与冻结代际不同）仅用于排除 CLI 用法问题，不作为证据。

## 冻结决策（方案 §4.3 出口）

- **exec `--json` 保持为 Codex 唯一主任务运行路径**（不新增 App Server 双路径、不自动回退）。
- exec 路径的 reasoning 映射已按文档化 `item.started/item.completed`（`item.type=reasoning`）落地并单测覆盖（空完成、重复快照去重、`turn.failed` 中断）；若冻结 CLI 在真实运行中不输出早期开始信号，该映射不会误造占位（开始事件缺失时完成只落 `reasoning_completed_without_start` 诊断）。
- **真实思考时序（开始先于结束、≥30s 长思考）未经验证**：受 429/403 限制，本会话无法证明 exec 在思考期间发出 `item.started`。§8.2 Codex 行保持「待完成」；若后续探针证明 exec 无早期信号，则按方案 §4.3.3 转入 App Server stdio Bridge 并更新 transport 元数据。

## 各 Harness 状态快照（实施后）

| Harness | 开始/结束信号接入 | 中断 | 真实验收（§8.2） |
|---|---|---|---|
| Pi | started/completed（既有）+ 显式按块 interrupted | 下块开始未结束、message abort/error、EOF 失败 | 上一版已完成页面链路；rev2 公共链路改动后需重验 |
| Claude | `--include-partial-messages` + content_block_start/stop 映射 | message 关闭、流错误、失败 result、EOF | 待真实 Provider 任务 |
| Codex | exec reasoning item 映射（加性） | turn.failed / turn.completed 收尾、重复静默 | **待验证**（见上） |
| OpenCode | durable `session.next.reasoning.*` 主 + part 快照回退 | step failed、session error、message error、终态兜底 | 待真实 Provider 任务 |

## 已知未关闭项（不满足不整体关闭）

- [ ] 8.2 全部 8 个 Harness×协议组合的真实长思考验收（本会话仅有 Pi 的 UI 链路真实验收；Provider 免费额度 429/地区 403 阻止其余组合）
- [ ] Codex 开始信号时序的原生证明（冻结决策见上）
- [ ] 新 Runtime Bundle（含四个 Adapter 改动）冻结并发布
- [ ] 浏览器页面证据：每个 Harness 至少一条真实运行（结束前可见占位、同一行定稿、取消/刷新/重连）
