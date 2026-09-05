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
Provider 上完成 OpenCode/`anthropic_messages` 的 Task 390 成功复验；尚未完成的
是 L5 正式发布验收与 hard cut。2026-09-03 已接受
[Worker Kit 可信安装与 Task 启动校验边界设计](../specs/2026-09-03-worker-kit-validation-boundary-design.md)，
它不重新打开 R1–R3 的历史结论；本轮已生成当前 candidate Kit identity，并在 R4 内补齐受影响的 L2/L3/L4
启动证据。当前运行模式继续保持 `dual_canary`，Pi 的 Profile-local 选择不等于系统全局默认，也不等于
`v2_only`。

当前唯一执行顺序为：

1. 完成 R4/L5 发布评审；
2. 形成独立 go/no-go 结论；
3. 获得单独批准后，在维护窗口执行 R5/L6。

## 2. 当前证据边界

| 层级 | 状态 | 已证明 | 未证明或待办 |
| --- | --- | --- | --- |
| L1 架构/合同 | **通过（已更新）** | ownership、schema、协议矩阵、identity、roll-forward-only 与可信 Kit 校验边界已冻结 | 合同变化时重新评审 |
| L2 源码/测试 | **当前 exact candidate 通过，发布审计仍开放** | Kit provenance、Snapshot CLI identity、Scheduler/Worker/launcher 热路径边界与聚焦回归已证明；全量单元测试有 3247 passed 基线；`8110afa0` 的 Codex `OPENAI_MODEL` 投影与 `810f9fcb` 的 Pi active-session 投影已通过受影响 Bundle/Profile/Scheduler/notification/freeform 回归 227 passed、Pi Adapter 54 passed、focused ruff、lint/secret scan；structured SSE source-identity 防护与移动安全区修复后前端全量回归 80 files/1692 tests、production build 通过；`48b16fdc` 的 Scheduler 取消日志分类修复通过 `test_scheduler_coverage.py` 64 passed、focused ruff 与 `make lint-backend`；Backend/Scheduler 已由该提交重建并部署为 `sha256:334c674d…` | 若 R4.3–R4.5 发现新的 runtime 源码变化，按影响面重开；release package、权限与 owner sign-off 仍属发布审计 |
| L3 不可变 composition | **当前 candidate 通过** | 新 Kit 已完整安装，Profile 4 generation 74 管理员 Verify 四 Harness；Bundle 170/171/172 分别为 exact composition 下的 Pi/Claude/OpenCode selected-Harness variants，Image/Kit/Profile/Adapter identity 可追溯 | R4 签署前保持 identity 不漂移；Codex 当前代成功仍受 Provider 可用性边界限制 |
| L4 真实 Host/Task | **R4.1 scope 通过** | 新 Kit、四 Harness admin/launcher smoke、5 条 warm-start 成功 Task、TTL 过期后的成功路径、受控 selected-CLI 失败、exact Worker/Kit/Bundle composition 下的 Pi/Claude/OpenCode Tasks 380–383、旧 Backend image 上的 OpenCode/Pi/Claude cancellation Tasks 384–386、修复后 Backend image 上的 Claude Tasks 387–389（取消与两次成功）及 OpenCode Task 390（成功）、preceding-generation Codex Task 368，以及真实 OpenCode Task 371 均有证据；旧 generation-73 Codex Tasks 377–379 的 Provider 失败已分类并归档 | 各 Harness 的正式 L5 交互/运维审阅与签署；当前 exact composition 的 Codex success 或明确接受其 Provider 边界 |
| L5 发布验收 | **未完成** | 已补充 390×844 创建/详情、长文本、编辑器焦点、底部操作区、创建表单与已有 Issue 的四 Harness 选择、真实运行态 command/ACK/刷新连续性与模式显示修复；structured SSE stale-source 生命周期防护、`viewport-fit=cover` 与移动 shell/drawer 安全区避让均已通过前端全量回归与 production build，并完成目标 Host nginx-only 静态产物复核；Task 371 又完成一次真实 nginx-only 前端入口断线/重连 spot-check；见 [R4.3/R4.4 live Host evidence](../evidence/2026-09-04-open-harness-v2-r4.3-r4.4-live-host.md) | 真实移动设备键盘/IME 与刘海/手势区验收已按用户指示暂缓；仍需 Host 上 `v2_only` V1 只读展示、完整交互/运维/安全阻断清单与签署 |
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
| R4.2 | **当前 exact candidate artifact 已冻结，发布签署仍开放**：完成 R3 后源码/组合影响面审计，生成新 Kit/Bundle，并在目标 Host 完整 Verify；初始 Backend/Scheduler image 来自 committed tree `40235196`，随后 `48b16fdc` 的 Scheduler 取消日志分类修复以 `sha256:334c674d…` 重建部署；该修复不改变 Worker/Kit/Profile/Bundle/Adapter/Provider protocol identity，Profile 4 generation 74 仍有效 | 当前 exact Worker/Kit/Profile/Adapter/Host identity 与 Bundle 170/171/172 可追溯；Pi/Claude/OpenCode 的 Task 380/381/382、复用 Pi Bundle 170 的 Task 383，以及修复后 Claude Tasks 387/388/389、OpenCode Task 390 均有对应 evidence。旧 Backend image 与 generation-73 Bundle 166–169 仍保留为历史 evidence，不能与当前 exact image 混称；R4 release-owner sign-off、签名包与维护窗口仍未完成 |
| R4.3 | **部分 evidence，未签署**：已覆盖 390×844 与桌面真实交互、长文本、编辑器焦点、底部操作区、创建表单与已有 Issue 的四 Harness 选择、实时 command/ACK、刷新连续性、运行完成过渡与 `freeform` 模式显示；两次 remote backend-only restart probe（Tasks 369/370）仍保留为上游 `rate_limited` 负向样本；Task 371 使用既有成功 Provider 7/OpenCode，在 `sleep 180` 期间完成一次仅 nginx 的真实前端入口断线/重连，页面保持挂载并以连续事件完成；已补充 structured SSE stale-source 生命周期防护及 3 个竞态回归测试，并在 `a6be3f8b` 中启用 `viewport-fit=cover`、补齐移动 shell/drawer 安全区避让；前端全量回归 80 files/1692 tests、production build 与目标 Host nginx-only 产物复核通过；同时补跑 `v2_only` V1 只读源码边界（后端 9 tests、TaskView 4 tests 通过），并完成一次 Host `v2_only` 临时 mode-health/V2-detail preflight 后恢复 `dual_canary`；目标数据库没有 V1 Task，因此未声称 live V1 read-only acceptance；见 live Host evidence | 真实移动设备键盘/IME 与刘海/手势区验收已按用户指示暂缓，不进入本轮远端执行；仍需有真实 V1 Task 数据时再完成 Host 上 `v2_only` 下的 V1 只读展示及完整交互/运维审阅，并由验收人确认无阻断交互缺陷 |
| R4.4 | **部分 evidence，未签署**：旧 cohort 已覆盖 Tasks 357–379 的四 Harness 成功/失败、startup/失败分类、command latency、usage、canonical terminal、archive、raw-log、delivery、seq 连续性，以及当前活跃队列/Issue lock/secret-like 扫描快照；exact Worker/Kit/Bundle composition 的成功 cohort 现为 Tasks 380/381/382/383/388/389/390：Pi/Claude/OpenCode/Pi/Claude/Claude/OpenCode，Bundle 170/171/172 共 7 个成功 attempt、652 条唯一且连续 receipt，均为 `run.completed`；Tasks 383/389/390 使用 Provider 6 `opencode-pi` / `deepseek-v4-flash` 的 `anthropic_messages`，早期 Task 383 的两次 `control_owner_unreachable` gate-probe 警告自动恢复且未改变终态；旧 Backend image 上的 OpenCode/Pi/Claude Tasks 384/385/386 分别以 15/40/8 条 receipt 的取消链收束，修复后 Backend image 上的 Claude Task 387 以 9 条唯一连续 receipt、4594-byte archive、6 chunks/5117 bytes raw-log 和已清理容器收束，Tasks 388/389/390 又分别以 19/20/216 条唯一连续 receipt、`run.completed`、零变更和已清理容器完成 success smoke；Task 387 的 Scheduler 日志为一次 `Task 387 cancelled` INFO 且没有 `Task 387 failed`，Tasks 388/389/390 均为成功 INFO 且没有失败终态，证明 `48b16fdc` 的取消告警分类与成功路径在真实 Provider 任务上均已复验；Codex Tasks 377–379 仍是正确分类的 Provider `rate_limited`/region-blocked `engine_error` 负向样本，Task 368 保留为 preceding-generation Codex success；本地 Mattermost mock E2E 96 项通过，目标 Host 内网 mock Mattermost 探针产生过 1 次 HTTP post/1 条 success delivery 后已清理 | 仍需在当前 exact composition 上取得 Codex success 或由发布评审明确接受 Provider 可用性边界，并按 Harness/Profile/Host 完整审阅告警行为与阻断指标，正式确认错误成功、串线、凭据泄漏、无法取消、重复 terminal/seq 缺口均为 0；开发 Host 当前未配置通知 profile，真实 Mattermost 告警投递尚未实测；全库更早历史仍有 12 个未 terminal attempt，未回填且不计入当前 candidate 通过，见 evidence |
| R4.5 | **部分 evidence，未签署**：secret scan、源码/前端验证、GitLab 有效配置的只读连接测试、远端磁盘与 `dual_canary` 状态已记录；当前只读权限复核确认 `ai-bot` 为 `Maintainer`、允许创建顶层组，GIMR OAuth 具有 `write_repository`/`write_virtual_registry`，启用 Provider 的 credential records 缺少 `version_metadata`；远端数据库仍在 077，而 Backend/Scheduler image 已包含 078 且 `AUTO_MIGRATE=false`，唯一待由维护 owner 处理的 legacy Provider 是 Provider 11，关联 23 个 Task/Snapshot（含当前 Task 388）；078 专门测试 16 passed、focused Ruff passed，事务回滚审计确认迁移会删除 Provider 11 并将 23 个 Task 的 `provider_id` 置空；当前 Backend/Scheduler 已由 `48b16fdc` 重建为 `sha256:334c674d…` 并在 remote 运行（无 Git revision OCI label），Worker/Kit/Bundle identity 保持不变；当前 Kit 已被流式重建为临时 content-addressed archive 并通过目标 daemon 的 V2 release preflight，但未形成 release-owner 签名包 | 必须先由 owner 收敛 GitLab/OAuth 最小授权、有效凭据来源与轮换/撤销记录；备份并执行已评审的 078 后重做受影响历史 Snapshot、Profile/Bundle/Task 验证；另需 release notes/签名包、旧 Kit/Image 退役时点、维护窗口/责任人、P0/P1 零阻断与发布例外确认 |
| R4.6 | 汇总 R1–R4 evidence，记录已知上游能力边界和停止条件，召开独立 hard-cut go/no-go | 明确签署 `GO` 或 `NO-GO`；`GO` 必须绑定 exact identity、目标 Host、R5 窗口与 owner |

**R4 退出条件：** R4.1–R4.6 全部有当前 evidence，阻断项为零，并由独立发布评审明确批准进入 R5。
当前 R4.1/R4.2 有 candidate evidence，R4.3/R4.4 仍只有部分 evidence；没有签署即保持
`dual_canary`，不以“测试大多通过”代替批准。

最新 exact-composition integrity recheck（Tasks 380–390）共 11 个 attempt、724 条
唯一连续 receipt；每个 attempt 恰有一个 Harness terminal 和一个 Task terminal，完成/取消
终态映射、序列/ID 不变量以及 canonical event/raw-log 的 constrained token-like scan 均为零失败。
该结果补强 R4.4 evidence，但不替代 Codex Provider 边界、真实告警、发布 owner 签署或独立 GO/NO-GO。

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
