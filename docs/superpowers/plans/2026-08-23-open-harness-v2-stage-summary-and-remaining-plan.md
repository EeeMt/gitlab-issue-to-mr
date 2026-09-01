# Open-Harness V2 阶段结论与剩余验收计划

**复核日期：** 2026-09-01

> 本文件只保留当前结论、证据边界、剩余退出条件和停止规则。历史 Task 编号、构建日志、镜像 digest、
> generation、测试计数和 Host 运行快照不在正文重复；需要复核时，以 Git history、runtime archive、数据库
> 快照和独立 evidence 为准。

## 1. 当前结论

Open-Harness V2 需要按两个不同里程碑判断，不能把它们混成一个“始终未完成”的大列表：

| 里程碑 | 当前状态 | 准确边界 |
| --- | --- | --- |
| A. Pi + OpenCode `dual_canary` Internal Preview | **已完成** | 公共 V2 合同、Kit/Profile/Bundle composition、Pi/OpenCode 主要执行链路和代表性真实证据已经形成可用 candidate |
| B. 四 Harness、Pi 全局默认、`v2_only` hard cut | **未完成** | 仍需关闭适用协议矩阵、Claude/Codex 当前 candidate 成功证据、正式 benchmark、L5 发布评审和 L6 维护窗口 |

因此，项目不是“没有推进”，而是此前文档把已经完成的实现、历史证据、每轮 readiness 预检和最终 hard-cut
门禁反复列为“剩余工作”，造成了进度失真。

当前应采用以下判断：

- V2 公共地基、中央 execution policy、command plane、Runtime Bundle、Worker Kit identity、四 Harness
  Adapter/fixture，以及 Pi/OpenCode 的主要 Adapter/Bridge 路径已经落地；
- `linux/amd64` 四 Harness candidate 已有不可变 Image/Kit/Profile/Bundle identity 和独立
  [R1 candidate evidence](../evidence/2026-08-31-open-harness-v2-r1-candidate.md)；
- Pi/OpenCode 已有真实成功、失败、timeout/cancel、usage、Session、工具调用、archive 和 delivery 的代表性
  证据，历史上也已覆盖各自声明的三种协议；本轮 [R2 candidate evidence](../evidence/2026-09-01-open-harness-v2-r2-candidate.md)
  又补齐了当前 Bundle 的 OpenCode 两种 endpoint/config 隔离成功链路、Codex Responses 成功链路，以及 Pi 当前 Bundle
  的 command delivery/cancel、Worker 缺失后 live rejection/recovery 和 dispatcher crash-recovery unknown outcome；后续仍只按源码变更影响面补跑，不重新清零全部已冻结证据；
- 当前运行模式仍应保持 `dual_canary`。Profile-local 的 Pi 选择不等于系统全局默认，也不等于
  `v2_only`；
- readiness 是短 TTL 的逐次 canary 预检。过期时必须在下一次执行前重新 verify，但它不是一个永久未完成的
  项目工作包，也不会因此重新打开 R1；
- 未跟踪的测试缓存或文档提交不改变已提交的 runtime source/composition；只有源码、Kit、Image、Bundle、
  Profile 或目标平台发生实质变化时，才按影响面更新 release evidence。

从现在起只保留四个剩余工作包：R2 关闭 hard-cut conformance、R3 执行正式 20-task benchmark、R4 完成
L5 发布评审、R5 在维护窗口执行 L6。执行顺序为 **R2 → R3 → R4 → R5**。

## 2. `dual_canary` 的准确边界

`dual_canary` 是 V1/V2 执行合同受控并存，不是同一 Task 双跑、影子流量或自动 A/B：

- 一个 Task/attempt 只执行创建时冻结的一个 contract、Profile、Harness、Runtime Bundle 和制品 identity；
- V1/V2 Profile、Task、Session lineage 和 attempt 不自动升级、降级或跨 generation 复用；
- create、execute/schedule/retry/resume、Scheduler claim/recovery 和 Worker start 都必须经过中央 execution
  policy；
- V2 只向显式选择并通过 verify-runtime 的 Profile/cohort 开放，V1 继续按自己的冻结合同执行；
- 只有 L1–L5 全部通过并获得独立 hard-cut 批准，才可在维护窗口切换 `v2_only`。

普通 canary、故障定位 Task 和修复验证 Task 不自动计入冻结 benchmark。

## 3. 证据层级

| 层级 | 当前状态 | 已证明 | 尚未证明 |
| --- | --- | --- | --- |
| L1 架构/合同 | **通过** | ownership、schema、协议矩阵、identity、roll-forward-only 和 Runbook 边界已冻结 | 后续合同变化仍须回到共享 schema 评审 |
| L2 源码/测试 | **当前 candidate 通过** | V2 公共地基、四 Harness fixture、Pi/OpenCode Adapter、command、catalog、execution policy、options freeze、错误归档/展示和相关回归已形成唯一实现 revision | 后续源码变更须按影响面重跑并更新 evidence |
| L3 不可变 composition | **Internal Preview candidate 通过** | 目标平台的 Image、Kit、Profile、Adapter、Bundle 和数据库 identity 可追溯 | hard-cut 前仍须对最终 candidate 再做一次逐次 readiness 预检 |
| L4 真实 Host/Task | **部分通过** | Pi/OpenCode 的主要成功、失败、Session、usage、terminal、archive、delivery、command/recovery 和协议样本已有代表性证据；当前 Bundle 的 OpenCode 跨 endpoint/config 隔离、Codex Responses 成功和 Pi command delivery/cancel、Worker 缺失后的 live rejection/recovery、dispatcher crash-recovery unknown outcome 已补证 | Claude 支持协议成功、适用协议矩阵的完整当前-candidate 收口仍须关闭 |
| L5 发布验收 | **未完成** | 场景、统计口径和 UI/运维检查面已经定义 | 正式 20-task、Pi 非劣性、剩余 UI/运维检查和 go/no-go 签署 |
| L6 hard cut | **未执行** | `v2_only`、Pi 默认值和 V1 只读边界已有实现路径 | 尚未进入独立维护窗口执行和验证 |

证据不能跨层替代：单测不能证明 Host 安装，Kit verify 不能证明真实模型与 Git/MR，单个成功 Task 不能证明
协议矩阵或 benchmark，Pi/OpenCode candidate 也不能证明四 Harness hard-cut readiness。
`host_mount` 只允许作为逐 Harness 授权的 break-glass 来源，不得充当 Kit-owned release evidence。

## 4. 与原实施阶段的对照

| 原方案阶段 | 当前状态 | 后续归属 |
| --- | --- | --- |
| Phase 0：协议探针与接口冻结 | **完成** | 真实 Endpoint 的发布 conformance 归入 R2，不再把它算作接口设计未完成 |
| Phase 1：V2 公共地基与 command plane | **完成** | 后续只在相关源码变化时做影响面回归 |
| Phase 2：Pi 默认 Harness | **实现与 dual-canary 完成；发布门禁未过** | 受影响 conformance、幂等/恢复归入 R2；非劣性归入 R3；全局默认切换归入 R5 |
| Phase 3：OpenCode 一级 Harness | **实现与 dual-canary 完成；发布门禁未过** | 受影响 conformance、跨 endpoint/config 隔离归入 R2 |
| Phase 4：Claude/Codex V2 | **源码/fixture 完成；L4 部分完成** | 各自支持协议的当前 candidate 成功证据归入 R2 |
| Phase 5：产品、制品、Canary 与 hard cut | **Internal Preview 完成；发布验收未完成** | benchmark、L5、L6 分别归入 R3、R4、R5 |
| Phase 6：OMP | **未开始且不在本轮范围** | 只在 V2 hard cut 后独立评估 |

当前实现继续遵守既定 ownership：Worker Kit 拥有 Harness CLI payload，Project Runtime Image 拥有项目工具，
Runtime Bundle 拥有 Adapter/Bridge/orchestration bytes；实际执行只认冻结 Snapshot/Bundle/Kit identity，
不得从 image、`PATH`、用户配置或另一 Harness 的成功结果隐式回退。

## 5. 剩余工作与退出条件

### R1 — 冻结 Internal Preview candidate（已完成）

- [x] 唯一实现 revision 已提交，相关 backend/frontend/mock/build 与静态检查已有独立记录；
- [x] 四 Harness 的 Image、Kit、Profile、Adapter、Bundle 和目标平台 identity 可追溯；
- [x] Pi/OpenCode 代表性真实 Task 与归档链路已经建立；
- [x] candidate evidence 已单独保存，不再由本跟踪文件重复抄录逐次数字。

**关闭规则：** 下一轮 canary 前重新 verify readiness 是执行预检，不重新打开 R1。只有 runtime source 或
composition identity 实质变化时，才按影响面补充 evidence。

### R2 — 关闭四 Harness hard-cut conformance（剩余工程主线）

按[冻结 schema](../../architecture/open-harness-v2-schemas.md)执行的适用协议矩阵如下：

| Harness | `anthropic_messages` | `openai_responses` | `openai_chat_completions` |
| --- | ---: | ---: | ---: |
| Pi | 是 | 是 | 是 |
| OpenCode | 是 | 是 | 是 |
| Claude | 是 | 否 | 否 |
| Codex | 否 | 是 | 否 |

不得要求 Claude/Codex 执行其未声明的协议，也不得用协议代理、URL 推断、隐式转换或其他 Harness 的成功结果
冒充通过。Pi/OpenCode 已冻结且未受后续变更影响的证据继续有效，只补跑变更实际影响的行。

R2 只剩以下闭环项：

1. **部分完成：** 当前 candidate 的 OpenCode Chat/Responses 成功和真实 Anthropic failure 已对账
   config、protocol、usage、唯一 terminal、archive 和 delivery；仍须按影响面收口其余适用协议行。
2. **部分完成：** Codex `openai_responses` 的当前 Profile 成功链路已补齐；Claude
   `anthropic_messages` 仍等待实际可用且兼容的 Provider，且 fresh/continue、取消/timeout、usage、
   archive 和 Git delivery 的完整矩阵尚未关闭。
3. **本轮已完成：** 当前 Bundle 已有 Pi 正常运行和控制端点启动；幂等 replay、closed gate 和 Scheduler
   recovery 的聚焦套件已通过；Task `181` 完成了 queued command 在 Worker 缺失后的
   `control_gate_closed` live rejection/recovery，Task `182` 完成了实际 command delivery 与取消收敛，Task
   `184` 完成了持久化 `dispatching` 命令在 dispatcher crash/recovery 后的 `outcome_unknown` 收敛。
4. **本轮已完成：** 不同 endpoint/config 的真实 OpenCode Task 已证明 task-private namespace、endpoint
   fingerprint 和 task-local config 不会未声明串线；详见独立 evidence 文件。
5. **本轮已执行受影响聚焦回归：** Linux/PostgreSQL 的 Scheduler、command、attempt、terminal、archive
   和 recovery 相关 suite 已通过；源码或 composition 后续再变更时，只按实际影响面重跑，不清零既有 green evidence。

**退出条件：** 所有适用协议行和上述闭环项均可追溯，无隐式回退、跨 Task 污染、重复 terminal 或
P0/P1。失败样本保留原样，不得事后追认为成功。

### R3 — 执行正式 20-task benchmark（下一主里程碑）

- 严格使用 [V2 schema §11](../../architecture/open-harness-v2-schemas.md#11-20-%E4%B8%AA-benchmark-%E4%BB%BB%E5%8A%A1%E4%B8%8E%E7%BB%9F%E8%AE%A1%E6%96%B9%E6%B3%95)
  冻结的 20 个多样化场景、成功标准、可比 Endpoint/model 和统计方法；
- 开始前冻结 candidate、Provider/model、协议映射和人工验收口径；
- 每个样本记录验收结论、failure taxonomy、耗时、token、工具调用、archive 和 delivery；修复后可重跑，
  但不得删除失败样本或把探索性 canary 追认成 benchmark；
- [现有 benchmark shell](../../../scripts/harness-probes/v2/benchmark.sh) 只重复生命周期诊断 prompt，
  不能替代 §11 的正式验收 cohort；
- Pi 与当前较优兼容 Harness 做同任务对比：成功率下降不超过 10 个百分点，中位耗时和 Token 不得同时
  恶化超过 25%。

**退出条件：** 不少于 20 个冻结样本完整可追溯，统计口径一致，Pi 质量和性能门槛同时通过。

### R4 — 完成 UI、运维与发布评审

已完成的部分不再重复列为待办：

- [x] 手机、平板和桌面基础响应式 spot-check；
- [x] 关键任务信息可见性、横向溢出和主要触控尺寸基线；
- [x] 失败详情、Raw Logs、原始 console 与结构化归档的基本展示边界。

剩余检查：

1. 完成移动端键盘/安全区、长文本换行、断线重连和 command history 的真实交互验收；
2. 审阅四 Harness 的 success/failure taxonomy、protocol error、command latency、usage、terminal、
   archive 和 delivery 指标；
3. 在最终 composition 上完成 secret scan、Provider/GitLab 授权与凭据轮换核对、release note、旧 Kit
   退役计划和 P0/P1 清零；
4. 形成独立 hard-cut go/no-go 评审记录并签署。

**退出条件：** L5 检查全部通过，发布评审明确批准进入 L6。

### R5 — 在独立维护窗口执行 L6

R2–R4 未全部通过前不安排 R5。获得单独批准后，按
[dual-canary 与生产验收 Runbook](../../runbooks/multi-harness-rollout.md)：

1. 排空在途任务、备份数据库并冻结 V1 只读边界；
2. 切换新建 Profile 的 Pi 全局默认值和 `HARNESS_EXECUTION_MODE=v2_only`；
3. 执行四 Harness smoke、Scheduler recovery、command plane、统计和历史只读检查；
4. 失败时保持维护状态并 roll forward，不启动旧 V1 应用回滚。

**退出条件：** L6 smoke 与运行态核对全部通过，且 hard-cut 结果形成独立 evidence。

## 6. 明确不进入本轮的工作

- 不增加撤销、denylist、任务迁移、紧急回退状态或新的 schema；没有真实需求时不建设过渡机制；
- `linux/arm64` 只在目标 Host 清单实际出现该架构时增加，不为假设平台提前扩张矩阵；
- OMP 保持独立实验，只有 V2 hard cut 后才用同一 benchmark 评估；
- 不重复消耗已知受限 Provider，也不使用协议不兼容的 Provider 冒充 Claude/Codex 成功。

## 7. 停止条件

出现以下任一情况，立即停止当前层级并保留证据：

- 实际执行 bytes 与冻结的 Image、Kit、Bundle、Adapter、Profile、Host platform 或 attempt identity 不一致；
- 使用 mutable tag、placeholder digest、未验证 Kit、过期 readiness、`host_mount` 或旧 image CLI lock
  冒充 release evidence；
- 出现协议推断/转换/回退、超出冻结矩阵的组合，或适用协议缺少真实 Endpoint conformance；
- V1/V2 cohort、task-private config/namespace、command 顺序/幂等、concurrency 或 recovery 出现隔离失败；
- 任一 hard-cut Harness 缺少当前 candidate 的适用成功证据、唯一 terminal、usage、archive 或 delivery；
- 存在 P0/P1，或正式 benchmark、Pi 非劣性、L5 评审尚未通过却准备进入 L6。

单个 Harness 的 functionality gate 失败只能把该 Harness 标为 unavailable，不能借用其他 Harness 的成功
结果。数据库继续保持 roll-forward-only，不得改写历史 Snapshot、Issue、attempt、archive 或验收证据。
