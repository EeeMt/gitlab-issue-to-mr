# Open-Harness V2 当前进展与剩余验收计划

**复核日期：** 2026-09-01

> 本文件只保留当前判断、证据边界、剩余退出条件和停止规则。历史 Task 编号、逐次构建日志、镜像
> digest、generation、时间戳和 Docker 磁盘统计不在正文重复；需要复核具体值时，以 Git history、数据库
> 快照、runtime archive 和独立 release evidence 为准。

## 1. 当前结论

Open-Harness V2 已形成可继续验证的 Internal Preview candidate，但尚未达到发布或 hard-cut 条件。

当前已经具备：

- V2 公共合同、数据模型、Runtime Bundle、Worker Kit identity、中央 execution policy、command plane、
  manifest/catalog、四 Harness Adapter，以及 OpenCode `Agent`/`Command`/`model_variant` options 的主要源码路径；
- `linux/amd64` 目标 Host 上的四 Harness Kit/Profile composition、Runtime Bundle 绑定和 readiness 验证；
- Pi 与 OpenCode 的真实 Host/Task 成功、失败、timeout、取消/abort、usage、Session、工具调用、archive、
  delivery 和 Git/MR 代表性证据；
- Pi/OpenCode 的显式 OpenRouter 三协议成功样本，以及 OpenCode options 的 Snapshot freeze、Adapter wiring、
  task-scoped config 和真实成功样本；
- 目标 Host 上 Linux/PostgreSQL/AF_UNIX 隔离 composition 的 mock-integration 全量验证，以及 scheduler
  recovery、command、并发、取消和归档等相关路径的覆盖；
- Pi 失败投影已统一做 sanitized/bounded message 处理，并避免把上游 HTML 中孤立的
  `authentication` 文字误判为认证失败；这项适配器安全性已有回归和目标 Host 部署后 disposable probe 证据；
- 失败详情的安全展示路径：Task Result 和 Full output 可从结构化归档中展示可操作的上游错误；历史原始
  console archive 保持不可变，不被事后改写。
- OpenCode `APIError` 的真实 `error.data.statusCode/message` 结构已纳入归一化，避免 Provider HTTP 429/401
  退化为 `engine_error`/`APIError`；本地 OpenCode/failure-detail 聚焦回归 80 条通过，完整 backend unit
  为 `3233 passed / 4 skipped`。目标 Host backend 已部署该修复并重新完成 Profile 4 四 Harness
  verify-runtime/readiness。新的真实 Task 仍须绑定新 Bundle 验证，不能用历史 Task 137 的 canonical 结果
  追认当前 taxonomy。
- OpenCode Bridge 已补齐 Task-local 的逐请求 HTTP audit artifact，并把冻结 endpoint fingerprint、协议和
  `opencode.json` 路径/哈希绑定进记录；建 Session、prompt 和 command 的 HTTP 非 2xx 已统一转成 bounded /
  sanitized 的结构化失败事件，且目标 Host 的真实 Task 170 已归档 3 条 audit 记录并证明一个 task-local
  namespace，仍不替代跨 endpoint/config 的隔离证据。

当前仍未具备：

- Claude/Codex 在兼容 Provider 额度恢复后的真实成功矩阵；
- Pi/OpenCode 按 Harness、协议、模型、失败类型和恢复动作组织的完整 conformance 矩阵；
- 不同 endpoint/config 下 namespace 不会未声明串线的真实 Host/Task 证明；当前只有一个真实 OpenCode Task
  的逐请求 HTTP audit 和 task-local namespace 样本，尚不足以证明跨配置隔离；
- 冻结的 20-task benchmark、Pi 非劣性结论、完整 UI/运维验收和发布签署；
- L6 hard cut。

因此当前必须保持 `HARNESS_EXECUTION_MODE=dual_canary`：不把 Profile 4 提升为系统全局默认，不提前执行
Pi 默认值迁移，不启用 `v2_only`。普通 canary、故障定位 Task 和修复验证 Task 不自动计入冻结 benchmark。

当前运行态：

- 目标 Host `192.168.50.129` 的 backend、scheduler、nginx 和数据库运行正常，服务仍报告 `dual_canary`；
- 当前 candidate 使用 `linux/amd64`、Kit `0.6.11`、Profile 4，并已在 runner 修复后重新完成 Profile/runtime
  verify 和 readiness 对账；readiness 为短 TTL，下一轮 canary 开始前必须再次 verify；
- 当前 candidate 已在目标 Host 部署并通过健康检查；Profile 4 已在最新 parser/Bridge 修复后再次完成四 Harness
  verify-runtime/readiness，generation 为 `42`。该验证生成的是四 Harness 的候选验证归档，不会直接持久化
  `worker_runtime_bundles`；下一条真实 Task 创建时必须从当前 source 绑定新的不可变 Bundle，既有 Task 170 的
  Bundle `118` 保持不变。
- 当前远端没有遗留 Codify Task worker 容器，磁盘未满，本轮未执行镜像清理；满盘时只按名称核对并清理
  Codify 调试镜像，不执行 broad prune；
- 当前 Open-Harness V2 实现已提交为 `ab869c67c22bbcea33cefc4dbc034060e73a4a1f`；本轮 audit 增量后的 backend unit 为
  `3233 passed / 4 skipped`，OpenCode/
  failure-detail 聚焦 suite 为 `80 passed`，Pi adapter/owner/protocol focused suite
  为 `112 passed`，frontend unit 为 `79 files / 1683 passed`；目标 Host 上已有 mock-integration 全量为
  `246 passed / 2 deselected`，本轮 audit 相关 mock lifecycle subset 为 `26 passed`；frontend production
  build、Ruff、Shell syntax 和 `git diff --check` 通过；
  目标 Host 上的 disposable probe 验证了 2000 字符上限、`engine_error` 分类和 result/event 一致性。该
  probe 只属于 L2/部署核对，不等同于真实 Provider failure、最终 release regression 或 L5 验收；此前更大
  范围的通过结果也不因本次变更自动继承。

架构约束以[Open-Harness V2 架构方案](../../architecture/open-harness-v2.md)为准，冻结 schema 与 benchmark
以 [V2 schema](../../architecture/open-harness-v2-schemas.md) 为准，发布操作以
[dual-canary 与生产验收 Runbook](../../runbooks/multi-harness-rollout.md) 为准。

## 2. `dual_canary` 的准确边界

`dual_canary` 是 V1/V2 执行合同受控并存，不是同一 Task 双跑、影子流量或自动 A/B：

- 一个 Task/attempt 只执行创建时冻结的一个 contract、Profile、Harness、Runtime Bundle 和制品 identity；
- V1/V2 Profile、Task、Session lineage 和 attempt 不自动升级、降级或跨 generation 复用；
- create、execute/schedule/retry/resume、Scheduler claim/recovery 和 Worker start 都必须经过中央 execution
  policy；
- V2 只向显式选择并完成 verify-runtime 的 Profile/cohort 开放，V1 继续按自己的冻结合同执行；
- 只有 L1–L5 全部通过并获得独立 hard-cut 批准，才可在维护窗口切换 `v2_only`。

## 3. 证据层级

| 层级 | 当前状态 | 已证明 | 尚未证明 |
| --- | --- | --- | --- |
| L1 架构/合同 | 通过 | ownership、schema、协议、identity、roll-forward-only 和 Runbook 边界已对齐 | 后续合同变化仍须回到共享 schema 评审 |
| L2 源码/测试 | 当前通过 | V2 公共地基、四 Harness fixture、Pi/OpenCode Adapter、command plane、catalog、execution policy、options freeze、归档错误详情、OpenCode HTTP audit 和相关回归已落地；当前工作树的 backend/frontend/mock/build 检查通过 | 当前工作树尚未形成唯一 release revision；任何后续源码或 composition 变化都必须重新生成完整 release evidence |
| L3 不可变 composition | 部分通过 | `linux/amd64` Image、Kit、Profile、Adapter、Runtime Bundle 和 DB identity 已绑定；当前 candidate 服务与四个新 Bundle 已吸收并核对本轮 audit source；Profile 4 readiness 可供短窗口 canary 使用 | readiness 会过期；最终 release revision、独立 release evidence 以及 Claude/Codex 的真实成功 Bundle 证据尚未冻结 |
| L4 真实 Host/Task | 部分通过 | Pi/OpenCode 已有真实模型、协议、工具、Session、终态、usage、archive、delivery 和 Git/MR；Pi 的 timeout、native terminate、真实 OpenRouter Provider failure、steering/follow-up、command、scheduler recovery 和 fail-closed 分支已有代表性证据；OpenCode 的 fresh/continue、Skills/config 隔离、crash/no-change、server close、timeout、namespace、options，以及 Task 170 的真实 server HTTP audit 已有代表性证据 | Claude/Codex 成功路径、Pi/OpenCode 完整协议异常/恢复矩阵、OpenCode 非 timeout Provider failure、幂等重投、不同 endpoint/config namespace 的跨 Task 真实证明、完整 recovery/concurrency 和四 Harness 交叉验收尚未完成 |
| L5 发布验收 | 未完成 | 场景、统计口径和 UI/运维检查项已定义 | 四 Harness 功能矩阵、20-task、Pi 非劣性、完整 UI/交互、授权/凭据和发布评审未通过 |
| L6 hard cut | 未执行 | `v2_only` 与 V1 只读路径存在 | 未切全局 Pi 默认，未进入维护窗口，未执行 hard-cut smoke |

证据不能跨层替代：单测不能证明 Host 安装，Kit verify 不能证明真实模型与 Git/MR，单个成功 Task 不能证明
协议矩阵或 benchmark，Pi/OpenCode candidate 不能证明四 Harness release readiness。`host_mount` 只允许作为
逐 Harness 授权的 break-glass 来源，不得充当 Kit-owned release evidence。

## 4. 与原实施方案的对照

| 原方案阶段 | 当前状态 | 剩余退出条件 |
| --- | --- | --- |
| Phase 0：协议探针与接口冻结 | 部分完成 | V2 schema、四 Harness fixture 和 20-task 定义已冻结；Pi/OpenCode 有三协议成功样本，双向细节、异常和恢复 probe 尚未齐全 |
| Phase 1：V2 公共地基与 command plane | 当前 revision 已完成主要复核 | 最终唯一 revision 的完整 regression 和远端 composition 仍需重新冻结；`v2_only` 属于 L6，不能用源码测试替代 |
| Phase 2：Pi 默认 Harness | 部分完成 | 已有代表性功能、Skills、execute/no-change、三协议成功、timeout、native terminate、command、steering/follow-up、scheduler recovery、取消竞态和 fail-closed recovery 证据；仍缺完整三协议 conformance、真实非 timeout failure、幂等重投、完整 recovery/concurrency 和 20-task 非劣性 |
| Phase 3：OpenCode 一级 Harness | 部分完成 | 已有 fresh/continue、task-private Skills/config、usage/tool、Git delivery、abort、crash/no-change、server close、正常 session close、namespace、timeout、options 和 Task 170 真实 HTTP audit 样本；仍缺完整三协议异常/恢复 conformance、不同 endpoint/config 的跨 Task namespace 隔离证明 |
| Phase 4：Claude/Codex V2 | 部分完成 | Adapter、协议声明、fixture/replay 和失败收口已落地；额度可用后仍须完成成功、fresh/continue、Skills、取消/timeout、usage、archive 和 Git/MR 矩阵 |
| Phase 5：产品、制品、Canary 与 hard cut | 部分完成 | Kit/Profile/catalog/readiness 和部分 UI 已落地；四 Harness L4、20-task、完整 UI、release review、Pi 默认迁移和 `v2_only` 均未完成 |
| Phase 6：OMP | 未开始 | 仅在 V2 hard cut 后独立评估，不修改 V2 公共合同来迁就 OMP |

当前实现与方案的核心边界一致：Worker Kit 拥有 Harness CLI payload，Project Runtime Image 拥有项目工具，
Runtime Bundle 拥有 Adapter/Bridge/orchestration bytes；实际执行只认冻结 Snapshot/Bundle/Kit identity，不
从 image、`PATH`、用户配置或另一 Harness 的成功结果隐式回退。

## 5. 剩余工作与执行顺序

### R1 — 冻结当前 release candidate

在继续收集 L4/L5 证据前，先把当前工作树收敛为唯一可追溯的 release candidate：

- 确定唯一源码 revision，纳入当前 runner、Pi JSONL reader、Anthropic endpoint 归一化、OpenCode options、
  HTTP audit、failure-detail、command/recovery 和相关测试增量；
- 在该 revision 上重跑 backend/frontend/mock/build、Ruff、Shell/Python 静态检查和 `git diff --check`；
- 从同一 revision 重新生成 Runtime Bundle，核对 Image、Kit、Bundle、Adapter、Profile generation、manifest
  和 Host platform identity；
- 在下一轮 canary 前重新执行 Profile 4 verify-runtime/readiness，不使用过期 readiness、旧 Bundle、mutable
  tag、placeholder digest 或未提交 source rebuild；
- 保存一份独立 release evidence，明确当前可证明的 Harness、协议、模型、Host、Bundle 和 attempt 范围；当前
  候选快照见 [R1 candidate evidence](../evidence/2026-08-31-open-harness-v2-r1-candidate.md)。

**退出证据：** 唯一 revision 与不可变 composition 可追溯，完整 regression 通过，readiness 在下一轮执行时
有效，且无已知 P0/P1。此前历史 Task 的成功或失败不因换 revision 自动继承为新证据。

### R2 — 关闭四 Harness 功能与协议矩阵

- Pi、OpenCode、Claude、Codex 分别对 `anthropic_messages`、`openai_responses`、`openai_chat_completions`
  使用真实兼容 Endpoint/Task 对账 config、model、usage、terminal、archive 和 delivery；禁止协议代理、
  URL 推断、隐式转换或回退冒充通过；
- 对 Pi/OpenCode 补齐真实 Provider failure（包含非 timeout failure）、retry/recovery、取消/abort、command
  replay/rejection/idempotency、Session lineage 和 namespace 证据；Pi 已有真实 OpenRouter failure probe，仍需
  补齐 OpenCode 的真实 Provider failure；不把 Adapter 层合成错误、disposable probe 或历史限流样本直接当成
  真实 Provider failure；
- OpenCode Bridge/归档路径已补齐逐请求 HTTP endpoint/config path 审计；Task 170 已在真实 Host/Task 核对每条
  请求的 route/status/config hash 与冻结 Snapshot，并验证一个 task-private namespace；仍须用不同 endpoint/config
  的真实 Task 证明 namespace 不会未声明串线，同时验证完整 task-private Skills/config、工作区交付和协议矩阵；
- 在兼容 Provider 容量可用后，完成 Claude/Codex 的成功、fresh/continue、Skills、取消/timeout、usage、
  archive 和 Git/MR 组合；保留限流失败证据，但不以不兼容协议替代成功证据；
- 在目标 Linux/PostgreSQL/AF_UNIX 环境重跑适用的 Scheduler、command、concurrency、cancel 和 recovery
  场景，不以本地 skip 作为通过证据；隔离 mock-integration 只能证明平台和生命周期路径，不替代真实
  Provider/Harness L4；
- 每个真实样本都要能从冻结 Profile/Snapshot/Bundle 追溯到单一 terminal、usage、archive、delivery 和
  Git 结果；失败样本不得改写或追认成成功样本。

**退出证据：** 四 Harness 各自的 conformance、真实成功 Task、异常/恢复矩阵、Bundle、Session、terminal、
usage、archive 和 Git/MR 均可追溯，且无 P0/P1。

### R3 — 执行冻结 20-task benchmark

- 严格使用 [V2 schema §11](../../architecture/open-harness-v2-schemas.md#11-20-%E4%B8%AA-benchmark-%E4%BB%BB%E5%8A%A1%E4%B8%8E%E7%BB%9F%E8%AE%A1%E6%96%B9%E6%B3%95)
  冻结的场景、成功标准、可比 Endpoint/model 和统计方法；
- 每个样本记录人工验收、failure taxonomy、耗时、input/cached/output/reasoning token、工具调用和 delivery；
- 修复后重跑受影响场景，但不删除失败样本，也不把此前探索性 canary 追认成 benchmark；
- Pi 与当前较优兼容 Harness 做同任务对比：成功率下降不超过 10 个百分点，中位耗时和 Token 不得同时
  恶化超过 25%。

**退出证据：** 不少于 20 个冻结样本完整可追溯，统计口径一致，Pi 质量和性能门槛同时通过。

### R4 — 完成 UI、运维与发布评审

- 在 390×844、768px 和桌面视口完成真实交互验证：Harness/协议/options 选择、命令发送、键盘遮挡、
  安全区、44px 触摸目标、长文本与状态换行、断线重连和 command history；
- 本轮已在目标 Host 开发环境的 Task 170 页面完成 390×844、768px 和 1440×900 spot-check：各视口无横向溢出，
  关键任务信息可见，并补齐移动/平板断点下关键操作的 44px 触控尺寸；这不替代键盘/安全区、断线重连、command
  history 和其余 R4/L5 交互验收。
- 审阅四 Harness 的 success/failure taxonomy、protocol error、command latency、usage、terminal、archive
  和 delivery 指标；
- 验证失败详情、Raw Logs、原始 console 与结构化归档之间的展示边界，不把安全注入详情误称为原始日志改写；
- 在最终 composition 上完成 secret scan、凭据轮换核对、release note、旧 Kit 退役计划和发布签署；
- 清零 hard-cut candidate 的 P0/P1。

**退出证据：** L5 全部通过，并形成单独的 hard-cut go/no-go 评审记录。

### R5 — 在独立维护窗口执行 L6

R1–R4 未全部通过前不安排 L6。获得单独批准后，按 Runbook 排空在途任务、备份数据库、冻结 V1 只读边界、
切换新建 Profile 的 Pi 默认值和 `HARNESS_EXECUTION_MODE=v2_only`，再执行四 Harness smoke、Scheduler
recovery、command plane、统计和历史只读检查。失败时保持维护状态并 roll forward，不启动旧 V1 应用回滚。

## 6. 明确不进入本轮的工作

- 不增加撤销、denylist、任务迁移、紧急回退状态或新的 schema；没有真实需求时不建设过渡机制；
- `linux/arm64` 只在目标 Host 清单实际出现该架构时增加，不为假设平台提前扩张矩阵；
- OMP 保持独立实验，只有 V2 hard cut 后才用同一 benchmark 评估；
- 不重复消耗已知受限 Provider，也不使用协议不兼容的 Provider 冒充 Claude/Codex 成功。

## 7. 停止条件

出现以下任一情况，立即停止当前层级并保留证据：

- 实际执行 bytes 与冻结的 Image、Kit、Bundle、Adapter、Profile generation、Host 或 attempt identity 不一致；
- 使用 mutable tag、placeholder digest、未验证 Kit、过期 readiness、`host_mount` 或旧 image CLI lock 冒充
  release evidence；
- V1/V2 cohort 隔离、command 顺序/幂等、PostgreSQL/AF_UNIX/concurrency/recovery 出现失败，或必要 skip
  未补跑；
- Pi/OpenCode 发生协议推断、转换或回退，或任一目标协议缺少真实 Endpoint conformance；
- 任一 hard-cut Harness 缺少真实 Task、terminal、usage、archive、Git delivery 或独立 Bundle，或存在 P0/P1；
- 20-task、Pi 非劣性、UI 交互、Provider/GitLab 授权、凭据轮换、secret scan 或发布签署未完成。

单个 Harness 的 functionality gate 失败只能把该 Harness 标为 unavailable，不能借用其他 Harness 的成功
结果；hard-cut candidate 缺少四 Harness 任一项时，不得进入 L6。数据库继续保持 roll-forward-only，不得改写
历史 Snapshot、Issue、attempt、archive 或验收证据。
