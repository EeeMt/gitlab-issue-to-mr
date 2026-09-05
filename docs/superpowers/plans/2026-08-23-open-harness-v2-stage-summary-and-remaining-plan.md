# Open-Harness V2 阶段结论与剩余验收计划

**复核日期：** 2026-09-05

> 本文件是状态与退出条件 tracker，不是运行日志。正文只保留当前结论、证据索引、未完成门禁、
> 失效规则和停止条件。Task/Issue 编号、Bundle/Kit digest、generation、逐次测试计数和 Host 快照统一留在
> 独立 evidence、runtime archive、数据库与 Git history 中。

## 1. 推进结论

| 工作包 | 状态 | 当前结论 |
| --- | --- | --- |
| R1：Internal Preview candidate | **完成** | 四 Harness 的 `linux/amd64` Image、Kit、Profile、Bundle 与真实 Host identity 已形成可追溯 candidate |
| R2：四 Harness hard-cut conformance | **完成** | 8 个适用 Harness×protocol 行及 fresh/continue/cancel/timeout、command/recovery、隔离与失败分类已闭合 |
| R3：正式 20-scenario benchmark | **完成** | Pi/OpenCode 20/20 formal pair 通过，失败样本保留，Pi 非劣性门槛通过 |
| R4：L5 UI、运维与发布评审 | **未完成** | R4.1 已实现并通过当前 Host 验收，R4.2 exact committed candidate 已重建并复验；R4.3–R4.6 的正式交互、运维、安全与 go/no-go 尚未签署 |
| R5：L6 `v2_only` hard cut | **未执行** | 只有 R4 批准后才可进入独立维护窗口 |

因此，Open-Harness V2 的原 candidate、适用协议 conformance 和正式 benchmark 已经完成；当前 R4
candidate 的 Kit/CLI 启动边界也已实现并完成 Host evidence。本轮 Codex/Pi Adapter 修复之后，已从
提交 `40235196` 的干净 committed tree 重建并部署 Backend/Scheduler image，完成 Profile 4 generation 74
的四 Harness Verify，并在同一 Worker/Kit/Bundle exact composition 上完成 Pi/Claude/OpenCode 的真实
Task 380–383 复验。随后提交 `48b16fdc` 修复 Scheduler 对取消终态的日志分类，并在远端以新 image
`sha256:334c674d…` 重建部署后，用 Claude/Provider 11 完成 Task 387 的 post-fix 取消复验，再用同一
Provider/Harness 完成 Task 388 的 post-fix 成功复验，随后用合法的 Provider 6
`opencode-pi/deepseek-v4-flash` 在 Claude/`anthropic_messages` 路径完成 Task 389 的成功复验，并在同一
Provider 上完成 OpenCode/`anthropic_messages` 的 Task 390 成功复验；随后以 Provider 4
`opencode-luna/gpt-5.6-luna` 在 Codex/`openai_responses` 路径完成 Task 391 的当前 exact
Provider-boundary 负向复验（403 `unsupported_country_region_territory`），随后以 Provider 12
`openrouter-minimax-responses/minimax/minimax-m3:free` 完成 Task 392 的当前 exact Codex
成功复验（14 条连续 receipt，`run.completed`，零变更），随后用同一 Provider 在 Pi/
`openai_responses` 路径完成 Task 394 的当前 exact 成功复验（74 条连续 receipt，
`run.completed`，零变更）；尚未完成的
是 L5 正式发布验收与 hard cut。2026-09-03 已接受
[Worker Kit 可信安装与 Task 启动校验边界设计](../specs/2026-09-03-worker-kit-validation-boundary-design.md)，
它不重新打开 R1–R3 的历史结论；本轮已生成当前 candidate Kit identity，并在 R4 内补齐受影响的 L2/L3/L4
启动证据。当前运行模式继续保持 `dual_canary`，Pi 的 Profile-local 选择不等于系统全局默认，也不等于
`v2_only`。随后在不绕过 Profile 校验的前提下创建了独立的 V1-only Profile 5，并用新建的
V1-compatible Kit 完成真实 Codex/Provider 12 只读 Task 399；该 V1 证据和后续 `v2_only` 只读展示预检
已补入 R4，但不改变 V2 exact cohort 或 R5 hard-cut 状态。当前远端仍恢复为 `dual_canary`。

OpenCode framing fix 之后，Task 417 暴露了 canonical receipt ingest 在长流归档回补阶段的 O(n²)
回放延迟；提交 `e0d487ec` 将在线 ingest/archive backfill 改为 attempt 内增量校验，同时保留完整
replay 作为终态完整性断言。聚焦相关回归（105 个 attempt/protocol/archive 测试、68 个
Worker/Scheduler 测试）与 Ruff/diff check 通过，Backend/Scheduler 已用新 image
`sha256:2cff3fd7…` 重建。Task 418 在同一 Profile 4 generation 75 / Bundle 175、OpenCode /
`anthropic_messages`、Provider 6 的真实复测完成；Task 417/418 是受影响 runtime 持久化路径的
补充证据，不加入冻结的 Task-ID 380–394 cohort，也不改变 Harness 协议矩阵或 R2/R3 的合同结论。

随后在真实 Mattermost 取消通知复验中，Task 408 暴露了运行中取消在 Worker 终态收敛之后未发送
`task_cancelled` 的生命周期缺口；提交 `594bf67a` 将运行中取消通知收敛到 Worker finalizer，并保留
PENDING/QUEUED 的 API 直接取消通知，避免竞态重复投递。Backend/Scheduler 以该提交重建为 image
`sha256:92321ff20bda74088b44a9c1410d5688399c44f15d78007b58e0068aaf07d7a3` 后，Task 409 使用合法
Provider 12/OpenCode 在真实 `sleep 180` 期间取消，Mattermost `task_cancelled` delivery 与频道消息均为
成功；随后 Task 410 使用合法的 Provider 4/Codex/`openai_responses` 组合，真实上游 403
`unsupported_country_region_territory` 以 `run.failed` 收敛，并完成 Mattermost `task_failed` delivery
与频道消息。这补齐了当前真实完成、取消和失败告警路径的 Host evidence，但不等于 L5 签署或 R4.6 批准。

Task 420 的真实 Pi/Provider 12 只读复测又暴露了交付摘要 Mermaid 规范化缺口：模型输出中的
`@{u}` 被 Mermaid parser 当作不完整的图形语法，任务本身仍成功但摘要校验为 `ok=false`，并进行了两次
无效修复尝试。提交 `59d55585` 将仅限 Mermaid fenced block 的无冒号 Git-ref 形式转义，同时保留合法
`@{ shape: ... }` 语法，并补充回归测试（delivery/worker focused set `136 passed`）。随后在本机
`desktop-linux` 构建并在目标 Host 安装 Worker Kit `0.6.14-linux-amd64-d461d040694b`，Profile 4
重新 Verify 为 generation 77；Task 421 在该 Kit 上以真实 Provider 12/Pi 成功复测，摘要校验恢复为
`ok=true`。这是一轮当前 candidate 的 L2/L3/L4 补强，不改变冻结 cohort 或 R4 签署边界。

随后通过正常管理员 Verify 将 Profile 4 从 generation 77 更新为 generation 78；Kit、Worker image、
运行模式与协议矩阵未改变。Task 425–428 在该新 generation 上分别完成 Pi/OpenCode/Claude/Codex 的真实
Provider 只读 smoke、canonical archive、Mattermost `task_completed/success` 与 served desktop detail
复核。Task 425 的模型 Mermaid 输出仍使摘要 validation 为 `ok=false`，Task 426 未写入独立
`delivery_summary` payload；两者均不影响 Worker、Task、archive 或通知成功，详见
[Profile 4 generation 78 evidence](../evidence/2026-09-05-open-harness-v2-generation-78-four-harness-smoke.md)。
该 readiness 只在 Verify 记录的 TTL 窗口内有效，过期后按合同派生为 `unknown`，不把短期 `ready` 写成永久
发布许可。

当前唯一执行顺序为：

1. 完成 R4/L5 发布评审；
2. 形成独立 go/no-go 结论；
3. 获得单独批准后，在维护窗口执行 R5/L6。

## 2. 当前证据边界

| 层级 | 状态 | 已证明 | 未证明或待办 |
| --- | --- | --- | --- |
| L1 架构/合同 | **通过（已更新）** | ownership、schema、协议矩阵、identity、roll-forward-only 与可信 Kit 校验边界已冻结 | 合同变化时重新评审 |
| L2 源码/测试 | **当前 exact candidate 通过，发布审计仍开放** | Kit provenance、Snapshot CLI identity、Scheduler/Worker/launcher 热路径边界与聚焦回归已证明；全量单元测试有 3247 passed 基线；`8110afa0` 的 Codex `OPENAI_MODEL` 投影与 `810f9fcb` 的 Pi active-session 投影已通过受影响 Bundle/Profile/Scheduler/notification/freeform 回归 227 passed、Pi Adapter 54 passed、focused ruff、lint/secret scan；structured SSE source-identity 防护与移动安全区修复后前端全量回归 80 files/1692 tests、production build 通过；`48b16fdc` 的 Scheduler 取消日志分类修复通过 `test_scheduler_coverage.py` 64 passed、focused ruff 与 `make lint-backend`；`594bf67a` 的取消通知生命周期修复通过 114 个相关单测（含 19 个子测试）与 focused Ruff；取消通知候选曾以 `sha256:92321ff2…` 部署，随后 `e0d487ec` 的增量 receipt ingest 修复以当前 remote image `sha256:2cff3fd7…` 重建并完成 Task 418/419 真实复核 | 若 R4.3–R4.5 发现新的 runtime 源码变化，按影响面重开；release package、权限与 owner sign-off 仍属发布审计 |
| L3 不可变 composition | **当前 candidate 通过** | Worker Kit `0.6.14` 已完整安装并通过 Profile 4 generation 78 的管理员四 Harness Verify；Bundle 181/182/183/184 与 Task 425–428 的 snapshot 记录了 Kit manifest `d461d040694b…`、`linux/amd64`、Adapter/CLI identity，Bundle 177–180 的历史证据仍可追溯 | R4 签署前保持 identity 不漂移；Codex 当前代成功仍受 Provider 可用性边界限制 |
| L4 真实 Host/Task | **R4.1 scope 通过** | 新 Kit、四 Harness admin/launcher smoke、5 条 warm-start 成功 Task、TTL 过期后的成功路径、受控 selected-CLI 失败、exact Worker/Kit/Bundle composition 下的 Pi/Claude/OpenCode Tasks 380–383、旧 Backend image 上的 OpenCode/Pi/Claude cancellation Tasks 384–386、修复后 Backend image 上的 Claude Tasks 387–389（取消与两次成功）及 OpenCode Task 390（成功）、Codex Task 391（当前 exact Provider-boundary 负向）、Task 392（当前 exact Codex success）与 Task 394（当前 exact Pi success）、真实 V1 Task 399、preceding-generation Codex Task 368，以及真实 OpenCode Task 371 均有证据；Task 409 又在当前修复 image 上完成真实 OpenCode/Provider 12 取消与 Mattermost `task_cancelled` success delivery；Task 410 又完成真实 Codex/Provider 4 上游失败与 Mattermost `task_failed` success delivery；Task 421 在 Kit 0.6.14 / Bundle 177 上完成真实 Pi/Provider 12 只读复测，Task 422/423/424 又在 Bundle 178/179/180 上分别完成真实 OpenCode/Claude/Codex 只读复测；Task 425–428 又在 generation 78 / Bundle 181/182/183/184 上分别完成真实 Pi/OpenCode/Claude/Codex 只读复测；旧 generation-73 Codex Tasks 377–379 的 Provider 失败已分类并归档；395–398 是创建/兼容性调试失败或取消样本，不计入 V2 cohort | 各 Harness 的正式 L5 交互/运维审阅与签署；当前 exact composition 的四 Harness success 与 V1 live read-only 已补齐，仍需完整 L5/运维/发布签署 |
| L5 发布验收 | **未完成** | 已补充 390×844 创建/详情、长文本、编辑器焦点、底部操作区、创建表单与已有 Issue 的四 Harness 选择、真实运行态 command/ACK/刷新连续性与模式显示修复；structured SSE stale-source 生命周期防护、`viewport-fit=cover` 与移动 shell/drawer 安全区避让均已通过前端全量回归与 production build，并完成目标 Host nginx-only 静态产物复核；Task 371 又完成一次真实 nginx-only 前端入口断线/重连 spot-check；Task 399 在 `v2_only` 下实际显示为“Legacy V1 · 只读”，完整摘要、事件流和运行统计可读，之后已恢复 `dual_canary`；Task 421 的 served `/tasks/421` 桌面详情已显示 Provider/Worker/Pi、plan/fresh、摘要、事件流、0 变更和 Kit `0.6.14` 路径；Task 422/423/424 的 served `/tasks/...` 页面又分别显示 OpenCode/Claude/Codex、Provider、plan/fresh、分支和 `+0/-0`，原始日志显示三条合法协议且仓库 URL token 为 `[TOKEN]`；Task 425/426/427/428 的 served 页面又显示 generation 78 下的 Pi/OpenCode/Claude/Codex、Provider/Worker/Harness、`+0/-0`、合法协议与 `[TOKEN]` 脱敏；见 [R4.3/R4.4 live Host evidence](../evidence/2026-09-04-open-harness-v2-r4.3-r4.4-live-host.md) 与 [generation 78 evidence](../evidence/2026-09-05-open-harness-v2-generation-78-four-harness-smoke.md) | 真实移动设备键盘/IME 与刘海/手势区验收已按用户指示暂缓；仍需完整交互/运维/安全阻断清单、release-owner 与独立签署 |
| L6 hard cut | **未执行** | `v2_only`、Pi 默认值和 V1 只读已有实现与 Runbook 路径 | R5 维护窗口及切换后 evidence |

正式 benchmark 的当前汇总如下；详细任务与失败链只在 R3 evidence 中维护：

冻结的适用协议矩阵保持不变；未声明的组合不进入发布门禁，也不得通过代理或隐式转换冒充通过：

| Harness | `anthropic_messages` | `openai_responses` | `openai_chat_completions` |
| --- | ---: | ---: | ---: |
| Pi | 是 | 是 | 是 |
| OpenCode | 是 | 是 | 是 |
| Claude | 是 | 否 | 否 |
| Codex | 否 | 是 | 否 |

| 指标 | 结果 |
| --- | ---: |
| formal Pi/OpenCode pair | 20/20 |
| 场景级通过 | 20/20 |
| 普通工作量配对终态人工验收 | Pi 14/14；OpenCode 14/14 |
| 中位耗时 | Pi 170.185s；OpenCode 160.491s（Pi +6.0%） |
| 中位 processed tokens | Pi 4,494.5；OpenCode 10,555.5（Pi -57.4%） |
| Pi 非劣性门槛 | **通过** |

证据索引：

- [R1 candidate evidence](../evidence/2026-08-31-open-harness-v2-r1-candidate.md)
- [R2 conformance evidence](../evidence/2026-09-01-open-harness-v2-r2-candidate.md)
- [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)
- [Task #348 启动延迟 evidence](../evidence/2026-09-02-task-348-startup-delay.md)
- [R4.1/R4.2 Kit boundary candidate evidence](../evidence/2026-09-03-open-harness-v2-r4.1-kit-boundary.md)
- [R4.3/R4.4 live Host evidence](../evidence/2026-09-04-open-harness-v2-r4.3-r4.4-live-host.md)
- [Profile 4 generation 78 four-Harness smoke evidence](../evidence/2026-09-05-open-harness-v2-generation-78-four-harness-smoke.md)
- [R4.5 security/release audit](../evidence/2026-09-04-open-harness-v2-r4.5-security-release-audit.md)
- [Worker Kit 校验边界设计决策](../specs/2026-09-03-worker-kit-validation-boundary-design.md)
- [V2 schema 与 benchmark 口径](../../architecture/open-harness-v2-schemas.md)
- [dual-canary 与生产验收 Runbook](../../runbooks/multi-harness-rollout.md)

上述层级不能互相替代：单测不能证明 Host 安装，Kit verify 不能证明真实模型与 Git/MR，普通 canary
不能回填 formal benchmark，R1–R3 也不能替代 L5 签署或 L6 切换证据。

运行时 ownership 保持不变：Worker Kit 拥有 Harness CLI payload，Project Runtime Image 拥有项目工具，
Runtime Bundle 拥有 Adapter/Bridge/orchestration bytes；实际执行不得从 image、`PATH` 或其他 Harness 回退。
Kit 完整内容权威位于构建、安装和管理员 Verify；Task 热路径只认冻结的 manifest 与所选 Harness identity。

## 3. `dual_canary` 的发布边界

`dual_canary` 是 V1/V2 执行合同受控并存，不是同一 Task 双跑、影子流量或自动 A/B：

- 每个 Task/attempt 只执行创建时冻结的一个 contract、Profile、Harness、Runtime Bundle 和制品 identity；
- V1/V2 Task、Session lineage、attempt 和 generation 不自动升级、降级或跨 cohort 复用；
- V2 只向显式选择且已通过管理员完整 verify-runtime 的 Profile 开放；
- create、execute/schedule/retry/resume、Scheduler claim/recovery 和 Worker start 都受中央 policy 约束；
- 只有 R4/L5 明确批准后，才可在独立维护窗口切换 `v2_only`。

readiness 是目标 Host 的运维观察和已知失败门禁，不再是逐 Task 完整内容证明。`unavailable` 继续阻止
创建/重试和调度；`ready` 过期派生为 `unknown` 并提示管理员重新 Verify，但完整、有效的 V2 Task Snapshot
可以进入真实容器的轻量 manifest/selected-Harness 校验，不得因此在 Task 热路径重新扫描完整 Kit。

## 4. 剩余工作

### R4 — 完成 L5 发布评审

R4 是当前唯一可推进工作包。以下六项必须在同一最终 candidate 上闭合。

| 编号 | 工作项 | 必须形成的结果 |
| --- | --- | --- |
| R4.1 | **完成（当前 candidate）**：V2 只接受 installer-managed content-addressed 路径；完整校验留在 build/install/admin Verify；Snapshot 冻结 selected-Harness identity；Scheduler/Worker/launcher 成功热路径不扫描完整 Kit | 聚焦回归、Kit 0.6.14、新 Kit 安装与四 Harness Verify/smoke、5 条 warm-start（中位 1.834s、最大 4.137s）、TTL 过期成功路径与 selected-CLI digest 受控失败；Task 421 还通过了正确挂载 Nix closure 与 `/workspace` tmpfs 后的 launcher/content Verify；见 [R4.1/R4.2 evidence](../evidence/2026-09-03-open-harness-v2-r4.1-kit-boundary.md) |
| R4.2 | **当前 exact candidate artifact 已冻结，发布签署仍开放**：完成 R3 后源码/组合影响面审计，生成新 Kit/Bundle，并在目标 Host 完整 Verify；初始 Backend/Scheduler image 来自 committed tree `40235196`，随后 `48b16fdc` 的 Scheduler 取消日志分类修复以 `sha256:334c674d…` 重建部署；`594bf67a` 的取消通知生命周期修复曾以 `sha256:92321ff2…` 重建 Backend/Scheduler，Profile 4 generation 74 是当时有效的前一候选；随后 `e0d487ec` 的增量 receipt ingest 修复以当前 remote image `sha256:2cff3fd7…` 重建，当前 Backend/Scheduler 仍保持该 image，Profile 4 先更新为 generation 77 并重新 Verify Kit `0.6.14`，Task 421 绑定 Bundle 177；`59d55585` 的 Mermaid 摘要规范化修复随 Kit `0.6.14-linux-amd64-d461d040694b` 安装并由真实 Task 421 复核；随后正常管理员 Verify 将 Profile 4 更新为 generation 78，Tasks 425–428 分别绑定 Bundle 181/182/183/184 并完成新 generation 的四 Harness 真实复核；另以本轮 launcher 兼容性修复构建并安装了独立 V1-compatible Kit `0.6.13-v1-compat2` | 冻结 V2 exact cohort 的 Worker/Kit/Profile/Adapter/Host identity 与 Bundle 170/171/172/173 可追溯；Pi/Claude/OpenCode 的 Task 380/381/382、复用 Pi Bundle 170 的 Task 383，以及修复后 Claude Tasks 387/388/389、OpenCode Task 390、Codex Task 391/392/394 均有对应 evidence。Task 391 是 Provider 4 的当前 exact `403 unsupported_country_region_territory` 负向样本，Tasks 392/394 则是 Provider 12 的当前 exact Codex/Pi success；Task 419 是 generation 75 / Bundle 175、Task 421 是 generation 77 / Bundle 177、Tasks 425–428 是 generation 78 / Bundle 181–184 的额外真实 Provider 复核，均不加入冻结 cohort；V1 Profile 5 / Bundle 174 / Task 399 是独立 legacy evidence，不并入 V2 exact cohort。旧 Backend image 与 generation-73 Bundle 166–169 仍保留为历史 evidence，不能与当前 exact image 混称；R4 release-owner sign-off、签名包与维护窗口仍未完成 |
| R4.3 | **部分 evidence，未签署**：已覆盖 390×844 与桌面真实交互、长文本、编辑器焦点、底部操作区、创建表单与已有 Issue 的四 Harness 选择、实时 command/ACK、刷新连续性、运行完成过渡与 `freeform` 模式显示；两次 remote backend-only restart probe（Tasks 369/370）仍保留为上游 `rate_limited` 负向样本；Task 371 使用既有成功 Provider 7/OpenCode，在 `sleep 180` 期间完成一次仅 nginx 的真实前端入口断线/重连，页面保持挂载并以连续事件完成；已补充 structured SSE stale-source 生命周期防护及 3 个竞态回归测试，并在 `a6be3f8b` 中启用 `viewport-fit=cover`、补齐移动 shell/drawer 安全区避让；前端全量回归 80 files/1692 tests、production build 与目标 Host nginx-only 产物复核通过；Task 399 在 Profile 5/Bundle 174 上以 V1 合同成功完成，随后临时 `v2_only` 下真实 Task detail 显示 `Legacy V1 · 只读`，摘要、事件流和统计可读；Task 400 又在清理后的 Host 上以 Profile 4/Bundle 170、Pi、Provider 12 完成独立 V2 只读 smoke，真实 `/tasks/400` 桌面详情页显示 Provider/Worker/Harness 上下文、摘要、事件流、原始日志和运行统计；Task 410 的失败详情修复后，已在实际服务的 `/tasks/410` 页面复核 canonical 上游 403 文案；Task 421 的实际 `/tasks/421` 桌面详情又显示了完成状态、Provider/Worker/Pi、plan/fresh、0 变更、摘要和事件流；Task 422/423/424 的 served `/tasks/...` 页面又显示了当前四 Harness 补强中的 OpenCode/Claude/Codex 上下文、合法协议原始日志、`+0/-0` 与 token 脱敏；服务保持 `dual_canary`；见 live Host evidence | 真实移动设备键盘/IME 与刘海/手势区验收已按用户指示暂缓，不进入本轮远端执行；仍需完整交互/运维/安全阻断清单、release-owner 与独立签署 |
| R4.4 | **部分 evidence，未签署**：旧 cohort 已覆盖 Tasks 357–379 的四 Harness 成功/失败、startup/失败分类、command latency、usage、canonical terminal、archive、raw-log、delivery、seq 连续性，以及当前活跃队列/Issue lock/secret-like 扫描快照；exact Worker/Kit/Bundle composition 的 V2 成功 cohort 仍为 Tasks 380/381/382/383/388/389/390/392/394：Pi/Claude/OpenCode/Pi/Claude/Claude/OpenCode/Codex/Pi，Bundle 170/171/172/173，共 9 个成功 attempt、740 条唯一且连续 receipt，均为 `run.completed`；Task 399 是独立 V1 Codex/Provider 12 success（14 条 `codify.worker.event/v1` receipt，seq 1–14，raw-log 5 chunks/2289 bytes，归档 3796 bytes，零变更），不加入 V2 integrity cohort；清理后核心合法 Provider 矩阵为 Task 400 Pi/Provider12、Task 403 OpenCode/Provider12、Task 404 Claude/Provider6、Task 405 Codex/Provider12，分别为 Bundle 170/172/171/173、42/44/22/18 条连续且唯一 receipt，均为零变更 `run.completed`；Task 401 是额外 Pi 重复样本，Task 402 是 Provider7 的 OpenCode alternate，均不加入冻结的 380–394 cohort；Task 406 和 Task 407 在独立 Mattermost 10.9.1 上完成真实 `task_completed` 投递，Task 407 验证了目标 Host URL；Task 409 在当前取消通知修复 image 上完成真实 OpenCode/Provider 12 `task_cancelled` 投递，Task 410 又完成真实 Codex/Provider 4 `task_failed` 投递，Task 419 又完成当前 generation 75 / Bundle 175 的真实 OpenCode completion 与归档完整性复核，Task 421 又完成 current generation 77 / Bundle 177 的真实 Pi completion、1158 contiguous receipt 与摘要校验复核；Task 422/423/424 又在 Bundle 178/179/180 上分别完成真实 OpenCode/Claude/Codex completion，123/48/19 条 receipt 与 Mattermost `task_completed/success`；这些额外 Task 的 delivery row 与频道消息均为单条 `success`，均不加入冻结 cohort；395–398 的旧镜像缺失、V1 manifest/digest 边界失败已保留为调试边界证据 | V2 exact Task-ID 380–394 仍为 14 attempts/824 receipts/824 distinct event IDs，完整性和 token-like scan 结果不变；Task 400–410、419、421–424 只补强 post-cleanup runtime/cleanup/real-notification evidence，不改变 exact cohort、Provider 边界或发布结论；Task 407 的 Mattermost completion message 使用 `http://192.168.50.129:8880/tasks/407`，Task 409 的 cancellation message 使用 `http://192.168.50.129:8880/tasks/409`，Task 410 的 failure message 使用 `http://192.168.50.129:8880/tasks/410`，Task 419 的 delivery row 为 `mattermost_notification_deliveries.id=12`，Task 421 的 delivery row 为 `mattermost_notification_deliveries.id=14`，Task 422/423/424 的 delivery row 为 `mattermost_notification_deliveries.id=15/16/17`；完整阻断指标审阅与正式零 P0/P1 签署仍开放 |
| R4.5 | **部分 evidence，未签署**：secret scan、源码/前端验证、GitLab 有效配置的只读连接测试、远端磁盘与 `dual_canary` 状态已记录；当前只读权限复核确认 `ai-bot` 为 `Maintainer`、允许创建顶层组，GIMR OAuth 具有 `write_repository`/`write_virtual_registry`，启用 Provider 的 credential records 缺少 `version_metadata`；远端数据库仍在 077，而 Backend/Scheduler image 已包含 078 且 `AUTO_MIGRATE=false`，唯一待由维护 owner 处理的 legacy Provider 是 Provider 11，关联 23 个 Task/Snapshot（含当前 Task 388）；078 专门测试 16 passed、focused Ruff passed，事务回滚审计确认迁移会删除 Provider 11 并将 23 个 Task 的 `provider_id` 置空；`594bf67a` 的前一候选 image 为 `sha256:92321ff2…`，随后 `e0d487ec` 重建了当前 Backend/Scheduler image `sha256:2cff3fd7…`（无 Git revision OCI label），`59d55585` 的 delivery-summary Mermaid 修复通过 focused set `136 passed` 并随 Kit `0.6.14` 在真实 Task 421 上复核；V1 Profile 5 使用已验证 Kit `0.6.13-v1-compat2`/manifest `d97f2157bbe7…`；Mattermost 10.9.1 已作为独立 debug 服务部署并完成连接、completion、cancellation、failure、Task 419 与 Task 421 completion 的真实投递 smoke，凭据只保存在远端受限文件中；Task 421 后根文件系统约 2.0GB 可用（97%），Docker BuildKit cache 为 0，前序满盘处置仅清理已核验的 Codify debug build artifacts/cache，未触碰 Mattermost/GitLab/数据库/卷或 active/unknown Worker（`quirky_allen` 保留）；未形成 release-owner 签名包 | 必须先由 owner 收敛 GitLab/OAuth 最小授权、有效凭据来源与轮换/撤销记录；备份并执行已评审的 078 后重做受影响历史 Snapshot、Profile/Bundle/Task 验证；当前 Host 的 `FRONTEND_URL` 已通过临时 Compose override 修正并由 Tasks 407/409/410 实投验证，但仓库通用模板仍不绑定具体 Host，后续部署必须显式提供正确 URL；另需 release notes/签名包、旧 Kit/Image 退役时点、维护窗口/责任人、P0/P1 零阻断与发布例外确认 |
| R4.6 | 汇总 R1–R4 evidence，记录已知上游能力边界和停止条件，召开独立 hard-cut go/no-go | 明确签署 `GO` 或 `NO-GO`；`GO` 必须绑定 exact identity、目标 Host、R5 窗口与 owner |

**R4.3/R4.4 current-generation amendment:** Profile 4 generation 78 的 Tasks
425–428 已补齐当前 Kit 的 Pi/OpenCode/Claude/Codex 真实 Provider completion、
canonical archive、协议/脱敏扫描、Mattermost success delivery 和 served desktop
detail；它们仍只是补充 evidence。Task 425 的摘要 validation 为 `ok=false`，Task 426
没有独立 `delivery_summary` payload，因此不能作为“交付摘要全绿”或正式 L5 交互/运维签署。
R4.3–R4.6、release-owner、安全/权限/轮换、签名包与独立 go/no-go 仍开放。

**R4.3/R4.4 post-TTL amendment:** readiness 过期后，Tasks 429/430 在完整 generation 78
snapshot 上分别完成 OpenCode/Pi 的 `plan/fresh` 真实执行，但模型忽略了 `sleep 180`，不计作取消证据。
Task 431 改用 Pi/Provider 12 的 `freeform/fresh`，在远端确认真实 `sleep 180` 进程后通过 served
`/tasks/431` 取消；容器清理、`cancelled` 状态、14 条连续 canonical receipt、archive 和 Mattermost
`task_cancelled/success` 均闭合。该补充只加强当前 generation 的桌面 L4/L5 evidence，不替代正式交互/运维
审阅、R4.5 安全签署或 R4.6 独立 go/no-go。

注：R4.5 行中的 1.4GB/“尚未触发清理”是 Task 410 通知复核时点的历史快照；随后 nginx 构建实际触发满盘处置，最终状态与清理范围以本节后面的 `served failure-summary visibility and disk recovery` 记录为准。

补充：R4.2 表中的 `sha256:92321ff2…` / Profile 4 generation 74 是
Task 410–412 所在的前一候选快照；OpenCode 脱敏 framing 修复后，当前
Backend/Scheduler 曾为 `sha256:d73018a4…`，随后 `e0d487ec` 的增量 receipt
ingest 修复将当前 image 更新为 `sha256:2cff3fd7…`。Profile 4 已重新验证为
generation 75，Task 415–418 的不可变 snapshot 与后续 continuation 记录该
Worker/Kit/Bundle identity。

当前 candidate 以 Profile 4 generation 78、Kit `0.6.14`（manifest SHA-256
`d461d040694b20b88944a88de47b5ad78188f91d74d528421cdef44b68274035`）和
Bundle 181/182/183/184 为准；前一 generation 77 / Bundle 177–180 的 Task 421–424
记录保留为历史补充 evidence，不与当前 identity 混称。Tasks 425–428 已在 generation 78
上完成真实 Pi/OpenCode/Claude/Codex 只读复测；readiness 仅在 Verify 记录的
`2026-09-05 12:03:31.418387` 至 `12:18:31.417926` TTL 窗口内为 `ready`，过期后按合同为
`unknown`，不能作为持续发布许可。

**R4 退出条件：** R4.1–R4.6 全部有当前 evidence，阻断项为零，并由独立发布评审明确批准进入 R5。
当前 R4.1/R4.2 有 candidate evidence，R4.3/R4.4 仍只有部分 evidence；没有签署即保持
`dual_canary`，不以“测试大多通过”代替批准。

最新 exact-composition integrity recheck（Task-ID 380–394 范围内，Task 393 无 Task row）共 14 个 attempt、824 条
唯一连续 receipt；每个 attempt 恰有一个 Harness terminal 和一个 Task terminal，完成/取消
终态映射、序列/ID 不变量以及 canonical event/raw-log 的 constrained token-like scan 均为零失败。
该结果补强 R4.4 evidence；Task 399 的 5 个 V1 Snapshot/1 个 V1 attempt 明确排除在该 V2 统计之外。该结果不替代已知
Provider 可用性边界、真实告警、发布 owner 签署或独立 GO/NO-GO。

### 2026-09-05 post-cleanup V2 smoke

Task 400 was created from Issue #99 with a fresh session, Profile 4,
Provider 12 `openrouter-minimax-responses` (`minimax/minimax-m3:free`), and
the Pi Harness. It completed as a real V2 freeform read-only task with zero
changes and 130/136 input/output tokens. Its Profile snapshot froze Bundle
170, Kit `0.6.12`, Pi CLI `0.84.2`, Adapter `2.1.0`, the current Worker image
digest, and `codify.worker.harness/v2`.

The attempt `task-400-attempt-1-96d0bad6b487` closed with `run.completed` at
seq 42. It persisted 42 contiguous receipts with 42 distinct event IDs, five
raw-log chunks / 2680 bytes, and a 6905-byte runtime archive whose SHA-256 is
`eae25e8e14f181ef626dc766816f578e660c399b82b4766db08c9bde65f4d1ab`.
`docker ps -a --filter name=codify-400` returned no container; the Task has no
Issue lock and the post-run active-task query returned zero. The authenticated
desktop detail page displayed the completed V2 Provider/Worker/Pi context,
delivery summary, events, raw logs, and runtime statistics.

This is a separate post-cleanup smoke, not an extension of the frozen
380–394 integrity cohort. The real mobile keyboard/IME/notch/gesture-area
acceptance remains explicitly deferred; no L5 device acceptance is claimed.
The Host remains in `dual_canary`, and R4.3–R4.6/R5 sign-off conditions remain
open.

### 2026-09-05 post-cleanup protocol matrix follow-up

The post-cleanup follow-up completed the current legal V2 protocol matrix on
Profile 4 using the existing configured Providers: Task 400 Pi with Provider
12, Task 403 OpenCode with Provider 12, Task 404 Claude with Provider 6, and
Task 405 Codex with Provider 12. All four completed read-only with zero changes,
one `run.completed` terminal, contiguous unique V2 receipts, and the expected
Bundle 170/172/171/173 identities. Task 401 is an additional successful Pi
repeat; Task 402 is a successful Provider 7 OpenCode alternate created while
validating the selector and is kept outside the Provider 12 core matrix.

The current database recheck at this stage reported 373 Tasks, 368 V2
snapshots, and 5 V1 snapshots, with zero active Tasks and zero Issue locks.
These samples do not extend the frozen Task-ID 380–394 integrity cohort. Real
mobile-device keyboard/IME/notch/gesture-area acceptance remains explicitly
deferred; the subsequent real Mattermost completion, cancellation, and failure
delivery checks are additional R4.4 evidence, while R4.5 owner/security/release
sign-off, R4.6 independent go/no-go, and R5/L6 remain open.

The current R4.5 recheck also found 349 database-referenced Task archives
(Task IDs 1–405) plus 176 unreferenced filesystem archives for later parallel
debug Task IDs, totaling 4,109,381 bytes. They were not deleted on the shared
Host; archive ownership/retention classification remains an explicit owner
gate before cleanup.

### 2026-09-05 Mattermost 10.9.1 real-delivery continuation

To close the previously missing real-notification evidence, the development
Host now runs an independent `mattermost/mattermost-team-edition:10.9.1`
container (`sha256:445ef983…`) with a separate `postgres:16-alpine` database,
network, and named volumes. The server is healthy on `192.168.50.129:8065`;
the Codify backend reached its `/api/v4/system/ping` endpoint, the authenticated
admin UI connection test passed, and the `V2 live notifications` profile was
created for `codifydebug/notifications` with only `task_completed` enabled.
The Bot token and admin/database credentials remain only on the remote Host in
mode-600 files and are not recorded here.

Real Task 406 was created from Issue #99 with Profile 4, Provider 12
`openrouter-minimax-responses`, the OpenCode Harness and `openai_responses`
protocol in fresh-session `plan` mode. It completed with zero changes and
`run.completed`; the closed V2 attempt `task-406-attempt-1-6ae3171267eb`
persisted 82 contiguous unique receipts, 5 raw-log chunks / 2772 bytes, and a
23219-byte runtime archive. Codify recorded delivery row 2 as
`task_completed=success`, and Mattermost returned a real Bot post for Task 406
in the target channel.

At the Task 406 checkpoint, the notification payload still rendered the task
URL from the generic remote `FRONTEND_URL=http://frontend.example.test:8880`,
while the target Host URL was `http://192.168.50.129:8880`. The follow-up
section below records the deployment override and Task 407 recheck. The real
mobile-device keyboard/IME/notch/gesture-area acceptance remains explicitly
deferred. The Host remains in `dual_canary`; migration 078,
release-owner/security sign-off, R4.6, and R5/L6 remain open.

### 2026-09-05 continuation: development URL rebind and Task 407

The current remote Backend/Scheduler deployment was recreated with a temporary
Compose override that set `FRONTEND_URL=http://192.168.50.129:8880` only for
those two services. The repository's generic `deploy/.env.test` template was
not changed, the database remained on `077_v2_worker_kit_identity`,
`AUTO_MIGRATE=false`, `dual_canary` remained enabled, and no task or Issue lock
was active during the recreation.

Task 407 was then created from Issue #99 using Profile 4, Provider 12
`openrouter-minimax-responses`, OpenCode with `openai_responses`, fresh-session
`plan` mode, and a read-only prompt. It completed with zero changes. The V2
attempt `task-407-attempt-1-65dc647fb191` closed with `run.completed`, 472
contiguous unique receipts, 5 raw-log chunks / 2725 bytes, and a 50223-byte
runtime archive. Codify recorded delivery row 3 as
`task_completed=success`; the real Mattermost message rendered
`http://192.168.50.129:8880/tasks/407`.

This resolves the current Host's notification-link defect without changing the
portable repository template. Future remote recreations must provide the
deployment's real frontend URL explicitly. Formal zero-P0/P1 review, R4.5
owner/security/release evidence, R4.6 independent go/no-go, migration 078,
R5/L6, and real mobile-device acceptance remain open.

### 2026-09-05 continuation: direct remote four-Harness verify

The exact installed `0.6.12-linux-amd64-c33dbf86951b` Kit was independently
verified on the target Docker daemon against the frozen Worker image digest.
The all-present Kit path passed for Claude `2.1.153`, Codex `0.146.0`, OpenCode
`1.18.19`, and Pi `0.84.2`; every run reported the expected content inventory
`7630f086800c95f851db8c9351638868ab60ac33fb3bfe22f9f2f5c8dcdc98a1` and the
single invocation exited 0. This adds direct current L3/R4.2 evidence only;
it does not alter the frozen V2 cohort or close release-owner/R4.6/R5 gates.

### 2026-09-05 continuation: real failure notification

Task 410 was created from Issue #99 using the existing Provider 4
`opencode-luna` (`gpt-5.6-luna`), the Codex Harness, and the legal
`openai_responses` protocol. The prompt was deliberately read-only and asked
the task to preserve an upstream provider failure without repository changes,
retry, commit, push, or merge-request activity. The existing
`V2 failure/cancel notifications` profile (profile 3) was enabled for
`codifydebug/notifications` with `task_failed` and `task_cancelled` events.

The real Provider request failed as expected with HTTP 403
`unsupported_country_region_territory`:

| Item | Result |
| --- | --- |
| Task/runtime | Task 410, `failed`; canonical failure kind `engine_error` |
| Attempt | `task-410-attempt-1-54e3bd239521`, `codify.worker.event/v2`, Codex Adapter `1.0.0`, CLI `0.146.0`, `last_seq=12`, terminal `run.failed`, `control_state=closed` |
| Canonical failure | seq 10 `harness.failed`, seq 12 `run.failed`; message included the upstream 403 and `unsupported_country_region_territory` |
| Persistence | 12 contiguous unique receipts, 5 raw-log chunks / 2458 bytes, runtime archive `3335` bytes; post-run active Tasks and Issue locks were zero |
| Codify delivery row | `mattermost_notification_deliveries.id=5`, `event_type=task_failed`, `status=success`, target `channel:aaz68niiuff3txfot5wjrgj33e` |
| Mattermost delivery | Bot post `4bw9czpbpfbuznzuj33ftj6ara` rendered `@root ❌ 任务失败 · [任务 410](http://192.168.50.129:8880/tasks/410)` |

This closes the previously missing real `task_failed` notification sample and,
together with Tasks 406/407/409, proves the completion, cancellation, and
failure delivery paths through Codify's delivery log into Mattermost 10.9.1.
Task 410 is an additional R4.4 operational sample and is not added to the
frozen Task-ID 380–394 integrity cohort. The final recheck reported 378 total
Tasks, zero pending/queued/running Tasks, zero Issue locks, healthy Backend and
Scheduler services, database revision `077_v2_worker_kit_identity`, and
`dual_canary`. The Host remains high-pressure (the latest direct check was
approximately `61G` total / `60G` used / `1.4G` available, `98%`); Docker's
current system report has 27 images, 11 containers, and 6.992GB reclaimable
BuildKit cache. The full-disk cleanup trigger was not reached, so no Codify
image/cache cleanup was performed.

Real mobile-device keyboard/IME/notch/gesture-area acceptance remains
explicitly deferred. Formal R4.4 sign-off, R4.5 owner/security/release checks,
R4.6 independent go/no-go, migration 078, and R5/L6 remain open; the Host stays
in `dual_canary`.

### 2026-09-05 continuation: served failure-summary visibility and disk recovery

The first authenticated browser check of Task 410 exposed a separate L5
visibility defect: the Backend had persisted the canonical `engine_error`
`failure_message` with the upstream 403 detail, but the served
`TaskResultPanel` preferred the first non-empty line of the generic
`error_message`, so the page displayed only `================`. The frontend
now prefers a trimmed canonical `failure_message` for `engine_error` and keeps
the generic first-line fallback for older rows without that field.

The focused component suite passed 25 tests, and the frontend production build
passed (`vue-tsc` plus Vite; 3496 modules, with only the existing chunk-size
warnings). The remote nginx build initially failed during `COPY frontend/`
with `no space left on device`. Before cleanup, Docker reported 27 images,
11 containers, 18 volumes, and 6.992GB of BuildKit cache. After checking every
Codify/container ancestor reference, only the unreferenced dangling Codify
Backend image `sha256:334c674db035…` was removed, followed by private
BuildKit cache pruning; GitLab, databases, Redis, Mattermost, active Worker
containers/images, and volumes were not touched. The rebuilt nginx image is
`sha256:8b6fbfb939a598678ef0d3e9c263c0a89d8f22fc90a283b3f890046071712c76`.

`compose up nginx` recreated Backend as a Compose dependency and temporarily
restored the generic `FRONTEND_URL`, so an untracked temporary override was
applied to Backend/Scheduler. Both now report
`FRONTEND_URL=http://192.168.50.129:8880`, `dual_canary`, and
`AUTO_MIGRATE=false`; Backend is healthy, the Scheduler process is running,
the database remains at `077_v2_worker_kit_identity`, and Mattermost remains
healthy. The final Host check reports 378 Tasks, zero pending/queued/running
Tasks, zero `issue_execution_locks`, 2.0GB available on `/` (97%), and the
served Task 410 page now renders the full canonical 403 detail including
`unsupported_country_region_territory`.

This is a focused L5 visibility and operational recovery improvement, not a
formal R4.3/R4.4 sign-off. Real mobile-device keyboard/IME/notch/gesture-area
acceptance remains explicitly deferred; R4.5 owner/security/release checks,
R4.6 independent go/no-go, migration 078, and R5/L6 remain open.

### 2026-09-05 continuation: Provider protocol boundary smoke (Tasks 411–412)

A post-deploy read-only analysis task was run twice against the current Host to
separate the existing OpenCode Provider/protocol behavior from a deployment
regression. Task 411 used Provider 7 `openrouter-free` with
`openai_chat_completions`; the OpenCode Adapter emitted a bounded
`protocol_error` at `session.idle with active tool parts`. It persisted 1134
contiguous, unique V2 receipts (`harness.failed` seq 1132 and `run.failed`
seq 1134), zero changes, a 107313-byte runtime archive, and a successful
`task_failed` Mattermost delivery. The served Task 411 page rendered the
canonical protocol error. The task had no remaining container or Issue lock.

Task 412 repeated the same read-only analysis shape with Provider 12
`openrouter-minimax-responses` and `openai_responses`. It completed with zero
changes, 885 contiguous unique V2 receipts, OpenCode Adapter `2.0.0` / CLI
`1.18.19`, a 84474-byte archive, and a successful `task_completed` Mattermost
delivery. The served Task 412 page showed the completed analysis result,
Provider 12 context, six process records, and the corrected development Host
URL. This pair adds real post-restart Provider/protocol evidence and keeps the
known Provider 7 protocol failure bounded as a failure; it does not extend the
frozen Task-ID 380–394 integrity cohort or provide R4.4/R4.6 approval.

The final Host check reported 380 total Tasks, zero pending/queued/running
Tasks, zero `issue_execution_locks`, healthy Backend and Mattermost 10.9.1,
`dual_canary`, and 2.0GB available on `/` (97%). Real mobile-device
keyboard/IME/notch/gesture-area acceptance remains explicitly deferred;
R4.5 owner/security/release checks, R4.6 independent go/no-go, migration 078,
and R5/L6 remain open.

### 2026-09-05 continuation: OpenCode redaction framing fix and Task 415

The Task 411 archive exposed a Codify-side defect in the OpenCode Adapter:
the serialized JSONL record was passed through the string-oriented secret
sanitizer before `json.loads`. An `API_KEY` value could consume escaped
newlines and quotes while matching the redaction expression, turning an
otherwise valid `running`/`completed` tool snapshot into malformed JSON. The
Adapter then dropped those snapshots and correctly failed closed on
`session.idle with active tool parts`, but the failure was caused by Codify's
archive/parse boundary rather than by a proven incomplete Provider lifecycle.

The smallest fix parses valid JSON first and recursively sanitizes only its
string values, while retaining the old sanitized raw-line fallback for input
that is genuinely non-JSON. A focused regression now covers an OpenCode tool
output containing an API key and embedded JSON; the completed tool snapshot is
preserved, the secret is absent, and no `non_json_raw_line` diagnostic is
emitted. The OpenCode Adapter unit suite passed 77 tests. Backend was rebuilt
on the remote Docker context as image
`sha256:d73018a40507ae08e20f1cc1944a428c370bc8d56377cf4e9410dd764cc5fb5e`
and Backend/Scheduler were recreated without touching Mattermost, Postgres,
Redis, or existing Workers.

After Profile 4 (`v2-canary-0.6.11-four-harness`) was re-verified, generation
75 / Kit `0.6.12` / Bundle 175 (`532c4a410962433c…`) was used to run a fresh
real read-only OpenCode task. Task 415 used existing Provider 7
`openrouter-free` / `openai_chat_completions`, fresh session, analysis (`plan`)
mode, and completed with zero changes in 49 seconds. Its V2 attempt
`task-415-attempt-1-9879f988dcb5` persisted 96 unique contiguous receipts
(seq 1–96), OpenCode Adapter `2.0.0` / CLI `1.18.19`, and `run.completed`.
The 25,988-byte runtime archive (`ce2b21ef…`) contained 183 parseable
OpenCode JSONL records, 13 tool parts and 3 completed tool parts; the archive
had zero `non_json_raw_line` matches and zero secret-like matches. Raw logs
were 5 chunks / 2,723 bytes. The Codify delivery row 8 was
`task_completed/success` to the independent Mattermost 10.9.1 service, and
the served Issue #99 page showed Task 415 as completed.

The post-run Host check reported zero pending/queued/running Tasks and zero
Issue locks, healthy Backend/Scheduler/Mattermost, `dual_canary`, and about
1.9GB free on `/` (97%). Docker reported 4.424GB reclaimable images and
1.796GB private BuildKit cache; no cleanup was needed for this run. This is
additional post-fix R4.4/R4.5 candidate evidence, not a new member of the
frozen Task-ID 380–394 integrity cohort and not formal R4.4/R4.5, R4.6, or
R5 approval. Credential/least-privilege and rotation evidence, migration 078,
release package and owner sign-off, independent go/no-go, and R5/L6 remain
open. Real mobile-device keyboard/IME/notch/gesture-area acceptance remains
explicitly deferred by the user.

### 2026-09-05 continuation: OpenCode Responses post-fix recheck (Task 416)

Task 416 repeated the post-redaction-fix read-only smoke with the same current
Profile 4 / generation 75 / Bundle 175 composition, but used existing Provider
12 `openrouter-minimax-responses` and the legal `openai_responses` protocol.
It ran as a fresh-session OpenCode analysis task and completed with zero
repository changes. The V2 attempt
`task-416-attempt-1-f6529450b7d4` persisted 121 contiguous receipts (seq 1–121,
121 distinct event IDs), OpenCode Adapter `2.0.0` / CLI `1.18.19`, and
`run.completed`; the Task detail page showed the same Provider, Profile,
OpenCode Harness, fresh-session mode, completed state, and 1m36s runtime.

The five raw-log chunks totaled 2,716 bytes. The runtime archive was
`task-416-runtime-archive.tar.gz`, 31,767 bytes, SHA-256
`c38bfe79648337abbc9491739c0e07d9b271b7cbdcbbb89e6f6ba3313f865183`.
Its OpenCode stream contained 211 parseable records with 211 distinct event
IDs, 19 tool updates / 4 completed tools, zero `non_json_raw_line` records,
and zero matches in the targeted secret scan. Codify recorded delivery row 9
as `task_completed/success` to the independent Mattermost 10.9.1 channel.

The final Host check remained clean for execution state: zero active Tasks,
zero Issue locks, healthy Backend/Scheduler/Mattermost, `dual_canary`, and no
additional cleanup was needed. This is complementary post-fix real-provider
evidence for the Responses side of the OpenCode boundary; it is not added to
the frozen Task-ID 380–394 integrity cohort and does not sign R4.3/R4.4,
R4.5, R4.6, or R5. Credential/least-privilege and rotation evidence, release
package/owner approval, migration 078, independent go/no-go, R5/L6, and the
user-deferred real-mobile-device acceptance remain open.

### 2026-09-05 continuation: canonical receipt ingest recheck (Tasks 417–418)

Task 417 是在 OpenCode framing fix image `sha256:d73018a4…` 上运行的真实
Provider 6 / OpenCode / `anthropic_messages` read-only analysis task。它最终
成功且零变更，但长流结束时 Worker 实际运行约 535 秒，Task 总耗时约 944 秒；
archive backfill 约占剩余 409 秒。该 attempt
`task-417-attempt-1-3a766b74a5b4` 最终有 4726 条连续唯一 V2 receipt，
archive 为 334078 bytes、SHA-256
`9a996950417dbe5225e717c5975efab8bc6c8f79d57cc12bd568903ddfb04b48`。
这条证据暴露了 `ingest_canonical_event()` 对每个新事件重复加载全量 receipt
replay 的 O(n²) 尾延迟，而不是 Provider 失败。

提交 `e0d487ec` 将在线 ingest 与 archive backfill 改成 attempt 内的增量
identity/order/finalization 校验，并保留完整 replay 作为终态
`assert_attempt_complete()` 断言。相关回归为 105 个 attempt/protocol/archive
测试、68 个 Worker/Scheduler 测试，Ruff 与 diff check 通过；协议事件语义、
Provider 合法矩阵和 Worker/Kit/Profile/Bundle identity 未改变。

Backend/Scheduler 以 `sha256:2cff3fd7eb27d21625614785cf6d5f37bc538f6851775253a9a379b6b6360161`
重建后，Task 418 用同一 Profile 4 generation 75 / Bundle 175、Provider 6
`opencode-pi` / `deepseek-v4-flash`、OpenCode、`anthropic_messages`、fresh
session 和 `plan` mode 复测。Task 418 于 `2026-09-05 09:30:06Z` 开始、
`09:44:25Z` 完成，Worker/stream 于 `09:44:23Z` 退出，Task 总耗时 860 秒，
其中 Worker 857 秒，archive/backfill/finalization 约 3 秒；Task 零变更，
input/output tokens 为 51/3018。

| Item | Result |
| --- | --- |
| Attempt | `task-418-attempt-1-499b67aed48a`, `codify.worker.event/v2`, OpenCode Adapter `2.0.0`, CLI `1.18.19`, `last_seq=6612`, terminal `run.completed`, `control_state=closed` |
| Persistence | 6612 receipts / 6612 distinct event IDs; raw logs 5 chunks / 2710 bytes; runtime archive `task-418-runtime-archive.tar.gz`, 477600 bytes, SHA-256 `e6379c3c2ca63a3366fb13eba6c0c51fbc5289ece38227fd5a7f3ae9587a9843` |
| Archive safety | 6758 OpenCode JSONL records all parseable; canonical archive 6612 records / 6612 unique event IDs; one each of `harness.completed`, `worker.finalization`, `run.completed`; 11 `tool.started` / 11 `tool.completed`; targeted secret-pattern scan 0 |
| Delivery | Mattermost delivery row 11, `task_completed/success`, target `channel:aaz68niiuff3txfot5wjrgj33e`; Mattermost 10.9.1 and its Postgres were healthy |
| Host convergence | Worker container removed; zero active Tasks and zero `issue_execution_locks`; database `077_v2_worker_kit_identity`; `dual_canary`; root filesystem 2.1GB available / 97% |

Task 418 is a post-fix persistence/finalization recheck, not a new formal
benchmark cohort member and not R4.3/R4.4/R4.5/R4.6 approval. The affected L2/L4
evidence is updated; because the fix does not change CLI payload, protocol
semantics, Provider legality, or immutable Worker composition, the frozen R2/R3
conformance and benchmark conclusions remain unchanged. Mattermost 10.9.1 is
available as the development debug/test service and was not recreated during
the Backend/Scheduler deployment. After the Task 418 run, a final remote
inspection found the generic template URL had been restored by Compose; a
temporary override was reapplied and verified so the current Backend/Scheduler
environment uses `FRONTEND_URL=http://192.168.50.129:8880`. This correction was
not retroactively counted as Task 418 link evidence. Real mobile-device keyboard/IME/notch/
gesture-area acceptance remains explicitly deferred; credential/least-
privilege and rotation evidence, release package/owner sign-off, migration 078,
independent go/no-go, R5/L6, and formal R4 gates remain open.

At the subsequent `remote` Docker recheck, Backend remained healthy on the
post-fix image, Scheduler remained in `dual_canary`, Mattermost 10.9.1 and its
Postgres remained healthy, and the database still reported zero active Tasks,
zero Issue locks, and revision `077_v2_worker_kit_identity`. The Host had
`2.1GB` available (`97%`) with `4.76GB` reclaimable images and `1.796GB`
reclaimable BuildKit cache, so the full-disk cleanup trigger was not reached.
One unrelated-looking long-running `quirky_allen` container was identified as
an unlabelled OpenCode API-schema probe using an active/unknown Worker image;
it was retained and is not counted as a Codify Task. If cleanup is later
required, recheck this container separately before touching it. This recheck
adds operational evidence only; it does not close R4.5/R4.6 or authorize
migration 078/R5, and real mobile-device acceptance remains deferred.

### 2026-09-05 continuation: Task 419 real OpenCode Responses smoke

通过已登录的目标 Host Dashboard `/issues/99` 创建并观察了一条新的真实只读
analysis Task。Task 419 使用现有 Provider 12
`openrouter-minimax-responses` / `minimax/minimax-m3:free`、合法的
`openai_responses`、Worker Profile 4
`v2-canary-0.6.11-four-harness`（generation 75，Worker Kit `0.6.12`，
`mounted_kit`）、OpenCode、fresh session 和 `plan` mode。任务于
`2026-09-05T10:11:34Z` 开始，`10:13:09Z` 完成，零仓库变更；浏览器页面随后
显示 `Task #419 已完成`，Issue 总任务数变为 47。
随后在目标 Host 的 `/tasks/419` 详情页实际切换事件流与原始日志视图，复核
Provider/Worker/Harness、fresh/plan 上下文、完成统计和 `[TOKEN]` 脱敏；这是
当前桌面 served-browser 的补充 L5 evidence，详见 [R4.3/R4.4 live Host evidence](../evidence/2026-09-04-open-harness-v2-r4.3-r4.4-live-host.md)。

| Item | Result |
| --- | --- |
| Attempt | `task-419-attempt-1-aaced1cae60a`, `codify.worker.event/v2`, OpenCode Adapter `2.0.0`, CLI `1.18.19`, `last_seq=820`, terminal `run.completed`, `control_state=closed` |
| Persistence | 820 receipts / 820 distinct event IDs, contiguous seq 1–820; raw logs 5 chunks / 2,716 bytes |
| Archive safety | `task-419-runtime-archive.tar.gz`, 79,490 bytes, SHA-256 `d009a8600a3612b6857ff83b1d24a6853def97f56c7fc448d6a27362d40dd37c`; 820 parseable canonical records / 820 unique IDs; one each of `harness.completed`, `worker.finalization`, `run.completed`; 4 `tool.started` / 4 `tool.completed`; targeted scan across 9 archive files returned 0 credential-like matches |
| Delivery | Mattermost delivery row 12, `task_completed/success`, target `channel:aaz68niiuff3txfot5wjrgj33e`; Mattermost 10.9.1 and its Postgres were healthy |
| Host convergence | zero active Tasks and Issue locks; database `077_v2_worker_kit_identity`; Backend healthy, Scheduler `dual_canary`; root filesystem 2.1GB available / 97%; no cleanup triggered |

Task 419 is additional post-restart real-provider and Mattermost evidence. It is
not added to the frozen Task-ID 380–394 integrity cohort and does not sign
R4.3/R4.4/R4.5/R4.6 or authorize migration 078/R5/L6. Credential/least-
privilege and rotation ownership, release package/owner approval, independent
go/no-go, and the user-deferred real-mobile-device acceptance remain open. The
unlabelled `quirky_allen` OpenCode schema probe and its active/unknown Worker
image were retained because the Host was not full; if cleanup is later needed,
recheck it separately before touching it.

### R5 — 在独立维护窗口执行 L6

R5 不是 R4 的默认延续，必须获得单独执行批准。批准后按 Runbook：

1. 复核 R4 签署绑定的 exact identity 未漂移，并在所有目标 Host 执行管理员完整 Verify；
2. 暂停创建/调度，逐项排空或处理在途任务，备份数据库并确认恢复点；
3. 保持长驻服务 `AUTO_MIGRATE=false`，由唯一 owner 执行已评审的精确 migration（如仍需要）；
4. 启用 Pi 作为新建 Profile 的全局默认，并以 `HARNESS_EXECUTION_MODE=v2_only` 启动 V2 服务；
5. 对 Pi、OpenCode、Claude、Codex 执行最小 release smoke，并复核启动时延、Scheduler recovery、
   command plane、cancel/timeout、usage、archive、delivery 与告警；
6. 确认 API/UI 拒绝 V1 execute/retry/schedule/resume，同时 V1 Task detail、日志、archive 和统计仍可只读；
7. 记录切换 identity、结果和观察指标。失败时保持维护状态并 roll forward，不重启旧 V1 应用写入新 schema。

**R5 退出条件：** hard-cut smoke、V1 只读边界和运行态指标全部通过，并形成独立 L6 evidence；否则保持
维护状态并继续修复，不宣称完成。

## 5. 证据失效与重开规则

| 变化 | 处理 |
| --- | --- |
| 仅文档或不进入 runtime 的测试缓存变化 | 不重开 R1–R3 |
| 仅前端交互变化 | 重跑受影响前端测试与 R4.3，不重跑协议矩阵或 benchmark |
| 仅实现已接受的 Kit 校验边界，CLI payload、Adapter、Bundle、Provider 和事件语义不变 | 生成新 Kit identity；更新 L2/L3；执行 R4.1 warm-start、四 Harness smoke 和 Kit 失败样本；不重开 R2/R3 |
| 除上述校验边界外的 Scheduler、command、Adapter、Bridge、terminal、archive 或 delivery 源码变化 | 更新 L2/L3，并补跑受影响的 R2 行或 R3 场景 |
| Harness CLI payload、Image、Bundle、Provider protocol/model 或 Profile execution options 变化 | 生成新 immutable identity；重做受影响的 L3/L4/R2/R3 evidence |
| 新增目标 Host/platform | 只为新增目标补 L3/L4 与 R4 运维证据 |
| readiness TTL 过期 | 展示为 `unknown` 并建议管理员重新 Verify；不触发逐 Task full probe，也不重开已冻结里程碑 |

已关闭工作包不因普通预检、重复 canary 或文档更新而回到“进行中”；只有其证明对象发生实质变化时，
才按上表重开受影响部分。

## 6. 不进入本轮

- 不增加撤销、denylist、任务迁移、紧急回退状态或新的过渡 schema；
- 不为 Kit 校验边界增加数据库字段、`strict/trusted` 双模式或后台周期性全盘审计；
- 真实移动设备的键盘/IME、刘海与手势区验收按用户指示暂时搁置；本轮只保留桌面浏览器、已服务 safe-area 产物与源码回归证据，恢复 L5 时再单独补做设备验收；
- `linux/arm64` 只在目标 Host 清单真实出现该架构时增加；
- OMP 保持独立实验，只有 V2 hard cut 稳定后才用同一 benchmark 评估；
- 不重复消耗已知受限 Provider，不用不支持的协议组合或另一 Harness 的成功结果冒充 evidence；
- [现有 benchmark shell](../../../scripts/harness-probes/v2/benchmark.sh) 仍只是生命周期诊断，不代替正式 cohort。

## 7. 停止条件

出现以下任一情况，立即停止当前层级并保留证据：

- 实际 Image、Kit、Bundle、Adapter、Profile、Provider snapshot、Host platform 或 attempt identity 与冻结值不一致；
- 使用 mutable tag、非 installer-managed Kit 路径、缺失有效 Profile/Kit/Harness 验证证据、`host_mount` 或 image/`PATH` 隐式回退冒充 release evidence；
- 成功 Task 热路径仍扫描完整 Kit，或 R4.1 warm-start 性能门槛未通过；
- 出现协议推断/转换、跨 Task 配置或 Session 串线、command 顺序/幂等/recovery 破坏、重复 terminal 或 seq 缺口；
- 发现凭据泄漏、错误成功判定、无法取消、P0/P1 或未接受的发布例外；
- R4/L5 未签署，或签署绑定的 identity 已变化，却准备进入 R5/L6。

数据库继续保持 roll-forward-only；不得改写历史 Snapshot、Issue、attempt、archive、benchmark 或发布证据。

## 2026-09-05 continuation: Mermaid 摘要修复与 Kit 0.6.14 / Task 421

Task 420 的真实 Pi/Provider 12 只读任务本身成功，但其交付摘要包含 Mermaid
parser 不接受的 `@{u}`，导致 `delivery-summary-validation.json` 为 `ok=false`，并触发两次
无效修复尝试。提交 `59d55585` 将规范化限制在 Mermaid fenced block，并只转义无冒号 Git-ref
形式；合法 `@{ shape: ... }` 与 Mermaid 外部文本保持不变。相关 delivery/worker focused
tests 共 `136 passed`。

该修复之后在本机 `desktop-linux` 构建了 `linux/amd64` Kit `0.6.14`，manifest SHA-256 为
`d461d040694b20b88944a88de47b5ad78188f91d74d528421cdef44b68274035`，导出归档 SHA-256 为
`bd6debd99c411cb6a50d1628f09d1fbe3127fffac11038ea8d58f5b512668251`（543487461 bytes），并通过 installer-managed
路径安装到目标 Host `/opt/codify/worker-kits/0.6.14-linux-amd64-d461d040694b`。Profile 4 的
管理员四 Harness Verify 产生 generation 77；Bundle 177 digest 为
`20634962827d632e003fe0d5b87b974af22b66c0ad7c785ac6c407dfb60d51e1`。

Task 421 使用现有 Provider 12 `openrouter-minimax-responses` /
`minimax/minimax-m3:free`、合法 `openai_responses`、Pi、`plan`、fresh session，完成于
`2026-09-05T11:18:13Z`，`total_changes=0`，输入/输出 token 为 `917/2393`。其 attempt
`task-421-attempt-1-39ec65925f1d` 使用 Adapter `2.1.0`、Pi CLI `0.84.2`，以
`codify.worker.event/v2`、`run.completed`、`control_state=closed` 收尾；1158 条 receipt
和 event ID 连续且唯一。5 个 raw-log chunks 共 2713 bytes；归档
`task-421-runtime-archive.tar.gz` 为 87419 bytes，SHA-256 为
`c3d30a461b035db790c9755261a48af3364da15a803588c1d6e643a3c7744819`。归档中的摘要校验为
`ok=true`、2 个图、0 个错误、0 次 repair；目标 secret-pattern scan 为 0。Mattermost
delivery row `14` 为 `task_completed/success`。

已登录的目标 Host `/tasks/421` 桌面页面显示完成状态、Provider/Worker/Pi、分析/plan、全新会话、
0 变更、摘要、事件流和运行统计；Worker modal 显示 Kit `0.6.14` 与安装路径。任务完成后远端
服务保持健康和 `dual_canary`，Docker BuildKit cache 为 0，根文件系统约 `2.0GB` 可用（97%）。
此前满盘处置仅清理已逐项核验的 Codify debug build artifacts/cache；Mattermost/GitLab/数据库/卷与
active/unknown Worker（包括 `quirky_allen`）均保留。

Task 421 是当前 candidate 的补强 evidence，不加入冻结 Task-ID 380–394 cohort，也不签署 R4.3、
R4.4、R4.5、R4.6 或授权 migration 078、`v2_only`、R5/L6。真实移动设备键盘/IME/刘海/手势区验收
继续按用户指示暂缓；release-owner、安全/权限/轮换、release package、维护窗口和独立 go/no-go
仍是剩余项。

## 2026-09-05 continuation: Kit 0.6.14 four-Harness real-provider smoke Tasks 422–424

在同一 Profile 4 generation 77 / Kit `0.6.14` / current Bundle lineage 上，使用现有 Provider
完成了当前 candidate 的补充四 Harness 真实只读回归。三条任务均为 `plan`、fresh session、零代码变更，
均以 `codify.worker.event/v2`、`run.completed` 和闭合的 `control_state=closed` 收尾；不是冻结的
Task-ID 380–394 cohort 的重写。

| Task | 真实组合与结果 | 完整性/交付 |
| --- | --- | --- |
| 422 | Provider 12 `openrouter-minimax-responses` / `minimax/minimax-m3:free`，OpenCode / `openai_responses`，Bundle 178，输入/输出 `1664/1809`，Adapter `2.0.0` / CLI `1.18.19`，0 变更 | 123/123 receipt 与 event ID，seq 1–123 连续；5 raw-log chunks / 2716 bytes；归档 32790 bytes，摘要校验 `ok=true`、0 图、0 次 repair；Mattermost delivery 15 为 `task_completed/success` |
| 423 | Provider 6 `opencode-pi` / `deepseek-v4-flash`，Claude / `anthropic_messages`，Bundle 179，输入/输出 `26500/9339`，Adapter `1.0.1` / CLI `2.1.153`，0 变更 | 48/48 receipt 与 event ID，seq 1–48 连续；17 raw-log chunks / 52302 bytes；归档 81963 bytes，摘要校验 `ok=true`、1 图、0 次 repair；Mattermost delivery 16 为 `task_completed/success` |
| 424 | Provider 12 `openrouter-minimax-responses` / `minimax/minimax-m3:free`，Codex / `openai_responses`，Bundle 180，输入/输出 `46774/1536`，Adapter `1.0.0` / CLI `0.146.0`，0 变更 | 19/19 receipt 与 event ID，seq 1–19 连续；6 raw-log chunks / 2716 bytes；归档 14382 bytes，摘要校验 `ok=true`、1 图、0 次 repair；Mattermost delivery 17 为 `task_completed/success` |

三条归档的 targeted secret-pattern scan 均未命中 `glpat-*`、`sk-ant-*`、
`ANTHROPIC_API_KEY=` 或 `OPENAI_API_KEY=`。这组结果补齐了当前 Kit 的真实 OpenCode、Claude、Codex
Provider 路径，并与 Task 421 的 Pi 结果共同形成当前 candidate 的四 Harness 补强证据；不改变冻结
cohort、协议矩阵或 Provider 可用性边界。它不签署 R4.3/R4.4/R4.5/R4.6，也不授权 migration 078、
`v2_only` 或 R5/L6。真实移动设备键盘/IME/刘海/手势区验收继续按用户指示暂缓；release-owner、安全/权限/
轮换、release package、维护窗口和独立 go/no-go 仍是剩余项。

三条任务完成后的远端 Host 仍为 Backend/Scheduler/nginx、Mattermost 10.9.1、GitLab、数据库与 Redis
健康，根文件系统约 `2.0GB` 可用（97%），Docker BuildKit cache 为 0；未达到满盘处置条件，因此没有执行
新的清理，`quirky_allen` active/unknown Worker 也继续保留。

本轮 served 页面与 Host 运维复核还确认：Task 424 的 Worker modal 显示 Profile 4、挂载 Kit
`0.6.14`、路径 `/opt/codify/worker-kits/0.6.14-linux-amd64-d461d040694b`、`/opt/codify-kit` 与
`/nix/store` 为只读挂载；Host 仍为 `dual_canary`、`AUTO_MIGRATE=false`、无 execution lock，数据库
revision 仍为 `077_v2_worker_kit_identity`。当前 `0.6.14` readiness 记录的 `ready_until` 已过期，
按既定语义只能派生为 `unknown`；未为刷新 readiness 重新 Verify，以避免无必要地改变 Profile generation/
identity。Task 424 的 Scheduler 日志显示已完成 archive fallback、receipt 持久化与成功 delivery；容器退出
后的 canonical-tail 409 属于已有的非阻断 warning，不改变 `run.completed` 或归档结果。

## 2026-09-05 continuation: Profile 4 generation 78 / Tasks 425–428

按“ready 只在 TTL 窗口内有效”的语义，先通过正常管理员 Verify 将 Profile 4 从 generation 77
更新为 generation 78；随后使用现有 Provider 完成四个合法 Harness×protocol 组合的真实只读 smoke：
Pi/Provider 12、OpenCode/Provider 12、Claude/Provider 6、Codex/Provider 12，分别对应
`openai_responses`、`openai_responses`、`anthropic_messages`、`openai_responses`。四个 Task
均以 `run.completed`、闭合 `control_state`、零代码变更、canonical archive 连续唯一 receipt 和
Mattermost `task_completed/success` 收尾；Bundle 为 181/182/183/184，完整归档与扫描数据见
[generation 78 evidence](../evidence/2026-09-05-open-harness-v2-generation-78-four-harness-smoke.md)。

本轮还完成了 `/tasks/425`–`/tasks/428` 的 served desktop detail 核对，以及目标 Host 的
服务、数据库、队列锁、Mattermost 10.9.1 和磁盘状态复核。Task 425 的模型 Mermaid 输出仍使
delivery-summary validation 为 `ok=false`，Task 426 未写入独立 `delivery_summary` payload；这两项
被保留为交付摘要边界，不改写为执行失败或“摘要全绿”。目标 Host 仍保持 `dual_canary`，未执行
migration 078、`v2_only` 或 R5/L6；磁盘约 97% 使用但尚未达到满盘清理触发条件，未执行新的清理。
真实移动设备键盘/IME/刘海/手势区验收继续按用户指示暂缓；R4.3–R4.6 与 release-owner/安全/权限/
轮换/签名包/独立 go/no-go 仍是剩余项。

## 2026-09-05 continuation: expired-readiness execution and Task 431 cancellation

generation 78 的 readiness `ready_until=2026-09-05 12:18:31Z` 在后续任务创建前已经过期；按既定语义该行派生为
`unknown`。本轮没有再次 Verify，因此没有无必要地改变 Profile generation 或 exact identity。Task 429/430/431
都沿用了完整的 generation 78 / Kit `0.6.14` / Worker image snapshot，证明了 V2 在过期 readiness 下仍可基于冻结
snapshot 进入轻量执行校验路径；这不表示 readiness 仍为当前 `ready`，也不表示 Scheduler 重新执行了完整 Kit probe。

Task 429 使用 OpenCode、Provider 12、`openai_responses`、`plan/fresh`，Bundle 182，`run.completed`，742 条
连续唯一 receipt，Mattermost delivery 22 成功；Task 430 使用 Pi、Provider 12、`openai_responses`、`plan/fresh`，
Bundle 181，`run.completed`，116 条连续唯一 receipt，Mattermost delivery 23 成功。两条任务中的模型都忽略了
`sleep 180` 并完成仓库检查，因此不作为取消证据。

为补齐当前代的真实取消路径，Task 431 改用同一合法 Pi/Provider 12/Bundle 181 组合，但使用 `freeform/fresh`。
在远端 `docker top codify-431-issue99` 明确看到 `/bin/... sleep 180` 后，通过已认证的 `/tasks/431` 页面点击取消。
容器随后消失，页面显示 `任务已取消`，数据库状态为 `cancelled`，`cancel_requested_at` 与完成时间均已记录。
Attempt `task-431-attempt-1-5e2884bb12e1` 以 `run.failed` 作为 canonical stop record 收尾，14 条 receipt 的 seq
为 1–14 且 event ID 唯一，archive 为 4122 bytes，SHA-256 为
`e257e2e1e7a55a92715603a1cac6606a2de1e4b84eea4a0d43d4a083e9006a37`，Mattermost delivery 24 为
`task_cancelled/success`。429–431 三个归档的 targeted secret-pattern scan 均为 0。

本轮结果详见 [generation 78 evidence](../evidence/2026-09-05-open-harness-v2-generation-78-four-harness-smoke.md)。
远端 Backend/Scheduler/nginx、Mattermost `10.9.1`、Mattermost Postgres、GitLab、Redis 和 Codify Postgres 仍健康，
无 active Task、无 Issue lock；根盘约 97% 使用、可用 2.0GB，未达到满盘清理条件，未执行新的 image/volume 清理，
`quirky_allen` active/unknown Worker 继续保留。该结果只关闭当前 generation 的桌面取消 smoke，不关闭 R4.3–R4.6、
release-owner/安全/权限/轮换/签名包/独立 go/no-go，也不授权 migration 078、`v2_only`、R5/L6；真实移动设备验收
继续按用户指示暂缓。

Task 432 继续在 readiness 已过 TTL 的 generation 78 exact snapshot 上验证 OpenCode 取消路径：Provider 12、
`openai_responses`、Bundle 182、`freeform/fresh`。远端进程树先确认真实 `sleep 180`，随后通过 served `/tasks/432`
取消；容器消失，页面显示 `任务已取消`，Attempt 以 `run.failed`/9 条连续唯一 receipt 收尾，archive 为 5878
bytes，Mattermost delivery 25 为 `task_cancelled/success`，归档 secret-pattern scan 为 0。Task 432 与 Task 431
共同补强当前代 Pi/OpenCode 取消证据，但仍不替代 R4.3/R4.4 正式审阅、R4.5 安全/owner 签署或 R4.6 go/no-go。

随后补齐了当前代剩余两条 Harness：Task 433 使用 Claude/Provider 6、`anthropic_messages`、Bundle 183，
Task 434 使用 Codex/Provider 12、`openai_responses`、Bundle 184；两条均为 `freeform/fresh`，均在远端确认
真实 `sleep 180` 后通过 served task detail 取消。Task 433 为 8 条连续唯一 receipt、Mattermost delivery 26，
Task 434 为 9 条连续唯一 receipt、Mattermost delivery 27；两份归档的 targeted secret-pattern scan 均为 0。
至此 generation 78 的 Pi/OpenCode/Claude/Codex 四 Harness 桌面取消 smoke 均有当前 exact snapshot 证据，
但仍不等于 R4.3/R4.4 正式签署或 R4.5/R4.6 owner/go-no-go 结论。

## 2026-09-05 continuation: current candidate release preflight

针对当前 Profile 4 generation 78 / Kit `0.6.14` exact candidate，使用仓库脚本
`deploy/scripts/preflight-v2-release.sh` 对临时 Kit 归档及目标 Host Worker image 做了只读复核。
归档与 sidecar SHA-256 均为
`bd6debd99c411cb6a50d1628f09d1fbe3127fffac11038ea8d58f5b512668251`；远端 image 为
`127.0.0.1:5000/codify-worker/java21-maven@sha256:234582c692d1ebb00ba8e882160618c2258463149d968009ac81c545e63a538b`；
脚本返回 `V2 release preflight OK`，manifest SHA-256 为
`d461d040694b20b88944a88de47b5ad78188f91d74d528421cdef44b68274035`，content inventory
SHA-256 为
`3be8e2272dbc1f4e6d645bfa3403657e3986bcbbdb5f0fb278fee735b079d5f2`，退出码 `0`。

这关闭了当前 candidate 的一项技术可复现性/完整性检查，但不把临时归档当作签名 release package，
也不替代 release-owner 的权限/轮换、release notes、维护窗口、独立 P0/P1 与 R4.6 go/no-go 签署。
本次没有改动远端服务、切换 `dual_canary`、执行 migration 078/`v2_only` 或运行 R5/L6；根盘约 97%
使用且未触发满盘清理。真实移动设备键盘/IME/刘海/手势区验收继续按用户指示暂缓。

## 2026-09-05 continuation: served desktop L5 boundary recheck

在目标 Host 的已认证浏览器中复核了 `/tasks/434` 与 `/issues/99`：取消态页面显示了 Codex、
Provider 12、Worker image digest、freeform/fresh、分支和无 MR；Issue 页面显示最新 Task #434、
62 条执行记录与 0 变更。打开 Issue 的创建任务抽屉、选择自由模式后，Worker/Profile 仍为需求固定
且不可改，Claude/Codex/OpenCode/Pi 四个 Harness 均显示 `未验证` / `运行时未验证`，与
0.6.14 readiness 过 TTL 后派生 `unknown` 的合同一致；抽屉随后关闭，未创建新任务。

这补强了当前桌面 L5 的真实 served UI 边界，但不把过期 readiness 解释为发布许可；真实移动设备验收、
R4.3/R4.4 正式审阅、R4.5 owner 材料、R4.6 go/no-go、migration 078、`v2_only` 与 R5/L6 仍保持开放。

## 2026-09-05 continuation: generation 78 database and delivery convergence

对目标 Host 的当前数据库做了 schema-aligned 只读复核：Tasks 425–430 均为
`run.completed`，Tasks 431–434 均为取消后的 `run.failed` canonical stop；10 个 attempt 全部
`control_state=closed`，`codify.worker.event/v2`，receipt 数与 `last_seq` 相等，seq 从 1 连续且
event ID 唯一。Mattermost delivery 18–27 全部为 `success`，其中 18/19/20/21/22/23 为
`task_completed`，24/25/26/27 为 `task_cancelled`。当前启用的 Mattermost profiles 仍为
`task_completed` 与 `task_failed`/`task_cancelled` 两组。

数据库仍为 `077_v2_worker_kit_identity`，active Task 与 `issue_execution_locks` 均为 0；
`0.6.14` readiness 的存储状态仍为 `ready`、generation 2，但 `ready_until` 已过期，实际派生为
`unknown`。远端 Backend/Scheduler/nginx、Mattermost `10.9.1`、两套 Postgres、GitLab 与 Redis
仍健康；根盘约 97% 使用、可用 2.0GB，未触发新的清理。这补强 R4.4 的当前 generation 数据库、
通知和队列收敛证据，但不替代 R4.3–R4.6 正式签署、release-owner 材料、migration 078、
`v2_only`、R5/L6 或用户暂缓的真实移动设备验收。

本轮还将当前 R4.5 owner handoff snapshot 固化到审计文档：绑定目标 Host、Profile 4 generation 78、
Kit/Worker/Backend identity、数据库 revision 和 preflight 结果，并把凭据最小权限/轮换、078 迁移 owner、
签名 package/release notes、retention/maintenance owner 及独立 R4.6 `GO`/`NO-GO` 作为待填写字段。
该 snapshot 明确是 unsigned handoff，不改变 `dual_canary`，也不把过期 readiness 当作发布许可。
