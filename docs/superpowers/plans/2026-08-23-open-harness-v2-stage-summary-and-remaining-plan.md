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

随后在真实 Mattermost 取消通知复验中，Task 408 暴露了运行中取消在 Worker 终态收敛之后未发送
`task_cancelled` 的生命周期缺口；提交 `594bf67a` 将运行中取消通知收敛到 Worker finalizer，并保留
PENDING/QUEUED 的 API 直接取消通知，避免竞态重复投递。Backend/Scheduler 以该提交重建为 image
`sha256:92321ff20bda74088b44a9c1410d5688399c44f15d78007b58e0068aaf07d7a3` 后，Task 409 使用合法
Provider 12/OpenCode 在真实 `sleep 180` 期间取消，Mattermost `task_cancelled` delivery 与频道消息均为
成功；随后 Task 410 使用合法的 Provider 4/Codex/`openai_responses` 组合，真实上游 403
`unsupported_country_region_territory` 以 `run.failed` 收敛，并完成 Mattermost `task_failed` delivery
与频道消息。这补齐了当前真实完成、取消和失败告警路径的 Host evidence，但不等于 L5 签署或 R4.6 批准。

当前唯一执行顺序为：

1. 完成 R4/L5 发布评审；
2. 形成独立 go/no-go 结论；
3. 获得单独批准后，在维护窗口执行 R5/L6。

## 2. 当前证据边界

| 层级 | 状态 | 已证明 | 未证明或待办 |
| --- | --- | --- | --- |
| L1 架构/合同 | **通过（已更新）** | ownership、schema、协议矩阵、identity、roll-forward-only 与可信 Kit 校验边界已冻结 | 合同变化时重新评审 |
| L2 源码/测试 | **当前 exact candidate 通过，发布审计仍开放** | Kit provenance、Snapshot CLI identity、Scheduler/Worker/launcher 热路径边界与聚焦回归已证明；全量单元测试有 3247 passed 基线；`8110afa0` 的 Codex `OPENAI_MODEL` 投影与 `810f9fcb` 的 Pi active-session 投影已通过受影响 Bundle/Profile/Scheduler/notification/freeform 回归 227 passed、Pi Adapter 54 passed、focused ruff、lint/secret scan；structured SSE source-identity 防护与移动安全区修复后前端全量回归 80 files/1692 tests、production build 通过；`48b16fdc` 的 Scheduler 取消日志分类修复通过 `test_scheduler_coverage.py` 64 passed、focused ruff 与 `make lint-backend`；`594bf67a` 的取消通知生命周期修复通过 114 个相关单测（含 19 个子测试）与 focused Ruff；Backend/Scheduler 已由该提交重建并部署为 `sha256:92321ff2…` | 若 R4.3–R4.5 发现新的 runtime 源码变化，按影响面重开；release package、权限与 owner sign-off 仍属发布审计 |
| L3 不可变 composition | **当前 candidate 通过** | 新 Kit 已完整安装，Profile 4 generation 74 管理员 Verify 四 Harness；Bundle 170/171/172/173 分别为 exact composition 下的 Pi/Claude/OpenCode/Codex selected-Harness variants，Image/Kit/Profile/Adapter identity 可追溯 | R4 签署前保持 identity 不漂移；Codex 当前代成功仍受 Provider 可用性边界限制 |
| L4 真实 Host/Task | **R4.1 scope 通过** | 新 Kit、四 Harness admin/launcher smoke、5 条 warm-start 成功 Task、TTL 过期后的成功路径、受控 selected-CLI 失败、exact Worker/Kit/Bundle composition 下的 Pi/Claude/OpenCode Tasks 380–383、旧 Backend image 上的 OpenCode/Pi/Claude cancellation Tasks 384–386、修复后 Backend image 上的 Claude Tasks 387–389（取消与两次成功）及 OpenCode Task 390（成功）、Codex Task 391（当前 exact Provider-boundary 负向）、Task 392（当前 exact Codex success）与 Task 394（当前 exact Pi success）、真实 V1 Task 399、preceding-generation Codex Task 368，以及真实 OpenCode Task 371 均有证据；Task 409 又在当前修复 image 上完成真实 OpenCode/Provider 12 取消与 Mattermost `task_cancelled` success delivery；Task 410 又完成真实 Codex/Provider 4 上游失败与 Mattermost `task_failed` success delivery；旧 generation-73 Codex Tasks 377–379 的 Provider 失败已分类并归档；395–398 是创建/兼容性调试失败或取消样本，不计入 V2 cohort | 各 Harness 的正式 L5 交互/运维审阅与签署；当前 exact composition 的 Codex/Pi success 与 V1 live read-only 已补齐，仍需完整 L5/运维/发布签署 |
| L5 发布验收 | **未完成** | 已补充 390×844 创建/详情、长文本、编辑器焦点、底部操作区、创建表单与已有 Issue 的四 Harness 选择、真实运行态 command/ACK/刷新连续性与模式显示修复；structured SSE stale-source 生命周期防护、`viewport-fit=cover` 与移动 shell/drawer 安全区避让均已通过前端全量回归与 production build，并完成目标 Host nginx-only 静态产物复核；Task 371 又完成一次真实 nginx-only 前端入口断线/重连 spot-check；Task 399 在 `v2_only` 下实际显示为“Legacy V1 · 只读”，完整摘要、事件流和运行统计可读，之后已恢复 `dual_canary`；见 [R4.3/R4.4 live Host evidence](../evidence/2026-09-04-open-harness-v2-r4.3-r4.4-live-host.md) | 真实移动设备键盘/IME 与刘海/手势区验收已按用户指示暂缓；仍需完整交互/运维/安全阻断清单、release-owner 与独立签署 |
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
| R4.1 | **完成（当前 candidate）**：V2 只接受 installer-managed content-addressed 路径；完整校验留在 build/install/admin Verify；Snapshot 冻结 selected-Harness identity；Scheduler/Worker/launcher 成功热路径不扫描完整 Kit | 聚焦回归、Kit 0.6.12、新 Kit 安装与四 Harness Verify/smoke、5 条 warm-start（中位 1.834s、最大 4.137s）、TTL 过期成功路径与 selected-CLI digest 受控失败；见 [R4.1/R4.2 evidence](../evidence/2026-09-03-open-harness-v2-r4.1-kit-boundary.md) |
| R4.2 | **当前 exact candidate artifact 已冻结，发布签署仍开放**：完成 R3 后源码/组合影响面审计，生成新 Kit/Bundle，并在目标 Host 完整 Verify；初始 Backend/Scheduler image 来自 committed tree `40235196`，随后 `48b16fdc` 的 Scheduler 取消日志分类修复以 `sha256:334c674d…` 重建部署；本轮 `594bf67a` 的取消通知生命周期修复又以 `sha256:92321ff2…` 重建 Backend/Scheduler，该修复不改变 Worker/Kit/Profile/Bundle/Adapter/Provider protocol identity，Profile 4 generation 74 仍有效；另以本轮 launcher 兼容性修复构建并安装了独立 V1-compatible Kit `0.6.13-v1-compat2` | 当前 exact Worker/Kit/Profile/Adapter/Host identity 与 Bundle 170/171/172/173 可追溯；Pi/Claude/OpenCode 的 Task 380/381/382、复用 Pi Bundle 170 的 Task 383，以及修复后 Claude Tasks 387/388/389、OpenCode Task 390、Codex Task 391/392/394 均有对应 evidence。Task 391 是 Provider 4 的当前 exact `403 unsupported_country_region_territory` 负向样本，Tasks 392/394 则是 Provider 12 的当前 exact Codex/Pi success；V1 Profile 5 / Bundle 174 / Task 399 是独立 legacy evidence，不并入 V2 exact cohort。旧 Backend image 与 generation-73 Bundle 166–169 仍保留为历史 evidence，不能与当前 exact image 混称；R4 release-owner sign-off、签名包与维护窗口仍未完成 |
| R4.3 | **部分 evidence，未签署**：已覆盖 390×844 与桌面真实交互、长文本、编辑器焦点、底部操作区、创建表单与已有 Issue 的四 Harness 选择、实时 command/ACK、刷新连续性、运行完成过渡与 `freeform` 模式显示；两次 remote backend-only restart probe（Tasks 369/370）仍保留为上游 `rate_limited` 负向样本；Task 371 使用既有成功 Provider 7/OpenCode，在 `sleep 180` 期间完成一次仅 nginx 的真实前端入口断线/重连，页面保持挂载并以连续事件完成；已补充 structured SSE stale-source 生命周期防护及 3 个竞态回归测试，并在 `a6be3f8b` 中启用 `viewport-fit=cover`、补齐移动 shell/drawer 安全区避让；前端全量回归 80 files/1692 tests、production build 与目标 Host nginx-only 产物复核通过；Task 399 在 Profile 5/Bundle 174 上以 V1 合同成功完成，随后临时 `v2_only` 下真实 Task detail 显示 `Legacy V1 · 只读`，摘要、事件流和统计可读；Task 400 又在清理后的 Host 上以 Profile 4/Bundle 170、Pi、Provider 12 完成独立 V2 只读 smoke，真实 `/tasks/400` 桌面详情页显示 Provider/Worker/Harness 上下文、摘要、事件流、原始日志和运行统计；服务保持 `dual_canary`；见 live Host evidence | 真实移动设备键盘/IME 与刘海/手势区验收已按用户指示暂缓，不进入本轮远端执行；仍需完整交互/运维/安全阻断清单、release-owner 与独立签署 |
| R4.4 | **部分 evidence，未签署**：旧 cohort 已覆盖 Tasks 357–379 的四 Harness 成功/失败、startup/失败分类、command latency、usage、canonical terminal、archive、raw-log、delivery、seq 连续性，以及当前活跃队列/Issue lock/secret-like 扫描快照；exact Worker/Kit/Bundle composition 的 V2 成功 cohort 仍为 Tasks 380/381/382/383/388/389/390/392/394：Pi/Claude/OpenCode/Pi/Claude/Claude/OpenCode/Codex/Pi，Bundle 170/171/172/173，共 9 个成功 attempt、740 条唯一且连续 receipt，均为 `run.completed`；Task 399 是独立 V1 Codex/Provider 12 success（14 条 `codify.worker.event/v1` receipt，seq 1–14，raw-log 5 chunks/2289 bytes，归档 3796 bytes，零变更），不加入 V2 integrity cohort；清理后核心合法 Provider 矩阵为 Task 400 Pi/Provider12、Task 403 OpenCode/Provider12、Task 404 Claude/Provider6、Task 405 Codex/Provider12，分别为 Bundle 170/172/171/173、42/44/22/18 条连续且唯一 receipt，均为零变更 `run.completed`；Task 401 是额外 Pi 重复样本，Task 402 是 Provider7 的 OpenCode alternate，均不加入冻结的 380–394 cohort；Task 406 和 Task 407 在独立 Mattermost 10.9.1 上完成真实 `task_completed` 投递，Task 407 验证了目标 Host URL；Task 409 在当前取消通知修复 image 上完成真实 OpenCode/Provider 12 `task_cancelled` 投递，Task 410 又完成真实 Codex/Provider 4 `task_failed` 投递，两个 delivery row 与频道消息均为单条 `success`，均不加入冻结 cohort；395–398 的旧镜像缺失、V1 manifest/digest 边界失败已保留为调试边界证据 | V2 exact Task-ID 380–394 仍为 14 attempts/824 receipts/824 distinct event IDs，完整性和 token-like scan 结果不变；Task 400–410 只补强 post-cleanup runtime/cleanup/real-notification evidence，不改变 exact cohort、Provider 边界或发布结论；Task 407 的 Mattermost completion message 使用 `http://192.168.50.129:8880/tasks/407`，Task 409 的 cancellation message 使用 `http://192.168.50.129:8880/tasks/409`，Task 410 的 failure message 使用 `http://192.168.50.129:8880/tasks/410`；完整阻断指标审阅与正式零 P0/P1 签署仍开放 |
| R4.5 | **部分 evidence，未签署**：secret scan、源码/前端验证、GitLab 有效配置的只读连接测试、远端磁盘与 `dual_canary` 状态已记录；当前只读权限复核确认 `ai-bot` 为 `Maintainer`、允许创建顶层组，GIMR OAuth 具有 `write_repository`/`write_virtual_registry`，启用 Provider 的 credential records 缺少 `version_metadata`；远端数据库仍在 077，而 Backend/Scheduler image 已包含 078 且 `AUTO_MIGRATE=false`，唯一待由维护 owner 处理的 legacy Provider 是 Provider 11，关联 23 个 Task/Snapshot（含当前 Task 388）；078 专门测试 16 passed、focused Ruff passed，事务回滚审计确认迁移会删除 Provider 11 并将 23 个 Task 的 `provider_id` 置空；当前 Backend/Scheduler 先后由 `48b16fdc`、`594bf67a` 重建，当前 remote image 为 `sha256:92321ff2…`（无 Git revision OCI label），V1 Profile 5 使用已验证 Kit `0.6.13-v1-compat2`/manifest `d97f2157bbe7…`；Mattermost 10.9.1 已作为独立 debug 服务部署并完成连接、completion、cancellation 与 failure 真实投递 smoke，凭据只保存在远端受限文件中；当前根文件系统约 1.4GB 可用（98%），尚未触发“满盘”清理，未触碰 active/未知 Codify Worker 镜像；未形成 release-owner 签名包 | 必须先由 owner 收敛 GitLab/OAuth 最小授权、有效凭据来源与轮换/撤销记录；备份并执行已评审的 078 后重做受影响历史 Snapshot、Profile/Bundle/Task 验证；当前 Host 的 `FRONTEND_URL` 已通过临时 Compose override 修正并由 Tasks 407/409/410 实投验证，但仓库通用模板仍不绑定具体 Host，后续部署必须显式提供正确 URL；另需 release notes/签名包、旧 Kit/Image 退役时点、维护窗口/责任人、P0/P1 零阻断与发布例外确认 |
| R4.6 | 汇总 R1–R4 evidence，记录已知上游能力边界和停止条件，召开独立 hard-cut go/no-go | 明确签署 `GO` 或 `NO-GO`；`GO` 必须绑定 exact identity、目标 Host、R5 窗口与 owner |

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
