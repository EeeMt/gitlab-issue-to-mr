# Open-Harness V2 当前进展与剩余验收计划

**复核日期：** 2026-08-30

**本地源码基线：** `dev` 当前已将本轮 Harness Adapter、catalog、command、sanitizer、前端 API 和
entrypoint 测试修复冻结为一个本地提交，尚未推送。该 revision 的完整 backend/frontend/mock E2E/build、
Ruff 和 Shell/Python 检查已通过；远端 backend/scheduler/nginx 已用当前 `HEAD` 的 revision label
重建并核对。

**运行边界：** Backend/Scheduler 仍为 `HARNESS_EXECUTION_MODE=dual_canary`、
`AUTO_MIGRATE=false`，数据库 revision 为 `077_v2_worker_kit_identity`。

**当前 candidate：** 目标 `linux/amd64` Host 已安装 Kit `0.6.11`；Profile 4 启用 Pi、OpenCode、
Claude、Codex，Profile 内默认 Harness 为 Pi，但该 Profile 不是系统全局默认。当前 composition 上的
runtime verify 已重新执行并返回 `ready`；Task #103 在有效 readiness 窗口内完成。由于 readiness TTL
较短，下一轮 canary 仍须在执行前重新 verify。

**本轮推进记录（2026-08-30）：**

- 远端 `192.168.50.129` 的 Profile 4 verify-runtime 已重新完成；Kit `0.6.11`、四 Harness identity
  evidence 和 DB 绑定保持一致，Task #103 执行时 readiness 为 `ready`（check generation `83`）。
- R1 已在当前 `HEAD` 上完成 backend/scheduler/nginx composition 重建：三项运行容器均使用带当前
  revision label 的镜像，backend health、scheduler health 均通过并报告 `dual_canary`；数据库仍为
  `077_v2_worker_kit_identity`，任务历史和 Profile 4 的验证字段未丢失。
- 重启后的 backend 成功校验并导出 Task #103 的 DB-bound Runtime Bundle：Bundle
  `4e606a31b61469ef3a2ff048edf8c05b6c8050e41e9a11020d1014f36457c016`，archive SHA-256
  `fa9b548c2d388e0c58c7de7dcec95ca168b12d7941d8dee344a2cd5ebe81bf45`，manifest SHA-256
  `b4b2687d6694b62b24294490cda2f4f463a7151ff2f959063d695434baf79503`。
- nginx 首次构建曾因 Docker daemon 拉取基础层阻塞；随后通过 OCI 客户端导入明确的 `linux/amd64`
  `nginx:alpine`/`node:22-alpine` 基础镜像完成 Vite 构建。运行中的 nginx 已核对当前 revision marker
  和 UUID command-id 修复；本地 Node 25 与镜像 Node 22 的产物 chunk hash 不作为相同构建的证据。
- 通过已登录 UI 显式选择 Pi 创建 fresh execute Task #103（Provider 7 / `openrouter-free`）；DB 记录为
  `completed`、Harness `pi`、Runtime Bundle `95`。该 Task 产生 182 条规范事件（含 4 个工具调用）、
  214 条 Pi 原始 Harness 事件、TaskLog、运行归档和 Git delivery；归档包含 `event.jsonl`、
  `harness-result.json`、`harness-events/pi.jsonl` 等。Task #102 因首次沿用需求默认 OpenCode 而取消，
  不计入 Pi 证据。
- GitLab 提交 `91aab46e` 只包含目标 canary 文件（1 addition、0 deletions）；字节级内容以提交页面为准，
  不以 AI 交付摘要中的换行描述替代。Task #103 结束后没有 `codify-103` 容器残留。
- 远端 Docker `system df` 显示磁盘未满，本轮没有清理镜像；只保留“满盘时清理已确认的 Codify 调试镜像”
  这一边界。
- 本轮提交 revision 已完成聚焦后端 202 tests、完整后端 3,193 passed / 4 skipped / 96 subtests、完整
  mock E2E 378 tests、完整前端 1,677 tests、前端 production build、Ruff、Shell/Python 静态检查；完整
  后端服务/迁移 fixture 在受控权限下重跑通过。提交未推送，R1 的当前 composition、Bundle 导出和
  Profile verify 已完成；后续仍须满足 R2–R5 才能进入发布或 hard cut。

## 1. 当前结论

Open-Harness V2 已形成一个可继续验证的 Internal Preview candidate，但尚未达到发布或 hard-cut 条件：

- V2 公共合同、数据模型、Runtime Bundle、Worker Kit identity、中央 execution policy、command plane、
  manifest/catalog 和四 Harness Adapter 的主要源码路径已落地；
- 同一四 Harness Kit/Profile composition 已完成安装和 DB 绑定，Pi/OpenCode 已有真实成功 Task；
- Pi 已有 execute、plan、freeform、fresh/continue、steering、follow-up、取消收口、usage、tool、Session
  和 Git/MR 的代表性真实证据；
- OpenCode 已有 fresh/continue、Task Skill、usage、tool、Session、Git/MR，以及 native abort 后单一终态和
  archive 收口的代表性真实证据；
- Claude/Codex 已证明 V2 启动、失败分类和收口，但兼容 Provider 的额度限制仍阻塞真实成功 canary；
- Pi/OpenCode 三协议完整 Endpoint 矩阵、四 Harness 完整真实矩阵、冻结 20-task benchmark、完整移动端/
  交互验收和发布签署均未完成。

因此当前只能保持 `dual_canary`：不得把 Profile 4 提升为系统全局默认，不得提前执行 Pi 默认值迁移，
不得启用 `v2_only`。现有普通 canary、故障定位和修复 Task 不能自动计入冻结 20-task benchmark。

架构约束以 [Open-Harness V2 架构方案](../../architecture/open-harness-v2.md) 为准，冻结 schema 与
benchmark 以 [V2 schema](../../architecture/open-harness-v2-schemas.md) 为准，发布操作以
[dual-canary 与生产验收 Runbook](../../runbooks/multi-harness-rollout.md) 为准。

## 2. `dual_canary` 的准确边界

`dual_canary` 是 V1/V2 执行合同受控并存，不是同一 Task 双跑、影子流量或自动 A/B：

- 一个 Task/attempt 只执行创建时冻结的一个 contract、Profile、Harness、Runtime Bundle 和制品 identity；
- V1/V2 Profile、Task、Session lineage 和 attempt 不自动升级、降级或跨 generation 复用；
- create、execute/schedule/retry/resume、Scheduler claim/recovery 和 Worker start 都必须经过中央
  execution policy；
- V2 只向显式选择并完成 verify-runtime 的 Profile/cohort 开放；V1 继续按自己的冻结合同执行；
- 只有 L1–L5 全部通过并获得独立 hard-cut 批准，才可在维护窗口切换 `v2_only`。

## 3. 证据层级

| 层级 | 当前状态 | 已证明 | 尚未证明 |
| --- | --- | --- | --- |
| L1 架构/合同 | 通过 | ownership、schema、协议、identity、roll-forward-only 和 Runbook 已对齐 | 后续合同变化仍须回到共享 schema 评审 |
| L2 源码/测试 | 已实现，release recheck 待做 | V2 公共地基、Pi/OpenCode Adapter、四 Harness fixture、command plane、catalog 和 execution policy 已落地；本轮提交 revision 与 mock E2E/build 等验证通过 | 远端 release composition 仍未绑定到该 revision；最终 release recheck 仍需在 composition 更新后完成 |
| L3 不可变 composition | 部分通过 | `linux/amd64` Image + Kit `0.6.11` + Profile 4 已安装并完成 identity/DB 绑定；Pi/OpenCode 有 DB-bound Bundle 证据，Task #103 在有效 readiness 窗口内完成 | readiness TTL 较短且会再次过期；四 Harness 各自基于成功 Task 的独立 Bundle 导出与最终 release freeze 尚未齐全 |
| L4 真实 Host/Task | 部分通过 | Pi/OpenCode 有真实模型、工具、Session、终态、archive 和 Git/MR；本轮新增 Pi fresh execute Task #103；取消/abort 与 live command 有代表性证据 | Claude/Codex 成功路径、三协议完整矩阵、真实 recovery/concurrency 和完整异常矩阵未完成 |
| L5 发布验收 | 未完成 | 验收场景和统计方法已冻结 | 四 Harness 功能矩阵、20-task、Pi 非劣性、完整 UI/交互和发布评审未通过 |
| L6 hard cut | 未执行 | `v2_only` 与 V1 只读的源码路径存在 | 未切全局 Pi 默认，未进入维护窗口，未执行 hard-cut smoke |

证据不能跨层替代：单测不能证明 Host 安装，Kit verify 不能证明真实模型与 Git/MR，单个成功 Task
不能证明协议矩阵或 benchmark，Pi/OpenCode candidate 不能证明四 Harness release readiness。
`host_mount` 只允许作为逐 Harness 授权的 break-glass 来源，不得充当 Kit-owned release evidence。

## 4. 与原实施方案的对照

| 原方案阶段 | 当前状态 | 剩余退出条件 |
| --- | --- | --- |
| Phase 0：协议探针与接口冻结 | 部分完成 | 四 Harness fixture、V2 schema 和 20-task 定义已冻结；Pi/OpenCode 三协议真实 Endpoint 的双向、异常和恢复 probe 尚未齐全 |
| Phase 1：V2 公共地基与 command plane | 源码实现完成 | 冻结当前 revision 后重跑完整 release regression；`v2_only` 生产切换属于 L6，不能用源码测试代替 |
| Phase 2：Pi 默认 Harness | 部分完成 | 代表性真实功能已覆盖；仍缺三协议完整 conformance、Skills、timeout/failure/execute-no-change、native terminate 边界，以及 rejected、重投、settled race、Scheduler recovery 的真实矩阵和 20-task 非劣性门槛 |
| Phase 3：OpenCode 一级 Harness | 部分完成 | fresh/continue、Skill、usage/tool、Git delivery 和 abort 收口已有样本；仍缺三协议完整 conformance、Agent/Command/variant、crash/close、timeout/no-change，以及 fresh/continue/namespace 的跨 Task 隔离证明 |
| Phase 4：Claude/Codex V2 | 部分完成 | Adapter、协议声明、fixture/replay 和失败收口已落地；兼容 Provider 额度恢复后仍须完成两者的真实成功、Session、Skills、取消/timeout、usage、archive 和 Git/MR 矩阵 |
| Phase 5：产品、制品、Canary 与 hard cut | 部分完成 | Kit/Profile/catalog/readiness 和部分 UI 已落地；四 Harness L4、20-task、完整 UI、release review、Pi 默认迁移和 `v2_only` 均未完成 |
| Phase 6：OMP | 未开始 | 仅在 V2 hard cut 后独立评估，不进入当前 release candidate |

当前实现与方案的核心边界一致：Worker Kit 拥有 Harness CLI payload，Project Runtime Image 拥有项目
工具，Runtime Bundle 拥有 Adapter/Bridge/orchestration bytes；实际执行只认冻结 Snapshot/Bundle/Kit
identity，不从 image、`PATH`、用户配置或另一 Harness 的成功结果隐式回退。

## 5. 剩余工作与执行顺序

### R1 — 冻结当前 release candidate

这是继续收集 L4/L5 证据前的第一步。

- 评审并提交当前 dirty worktree 中的 Adapter、catalog、command、sanitizer 和前端修复，明确唯一源码 revision；
- 在该 revision 上运行完整 backend unit、frontend unit/build、mock E2E、Ruff、shell/Python 静态检查；
- 由同一 revision 重新生成 Runtime Bundle，核对 Image、Kit、Bundle、Adapter、Profile generation 和
  manifest identity；
- 重新执行 Profile 4 verify-runtime，使 readiness 在下一轮 canary 开始时有效；
- 不使用 mutable tag、过期 readiness、旧 Bundle 或未提交 source rebuild 继续累计 release evidence。

**退出证据：** 唯一可追溯 revision 与不可变 composition；当前 readiness 有效；完整回归通过；无已知 P0/P1。

### R2 — 关闭四 Harness 功能与协议矩阵

- Pi/OpenCode 分别对 `anthropic_messages`、`openai_responses`、`openai_chat_completions` 使用真实兼容
  Endpoint/Task 完成 config、model、usage、terminal 和 delivery 对账；禁止协议代理或 URL 推断冒充通过；
- Pi 补齐 Skills、timeout/failure/execute-no-change、native terminate，以及 steering/follow-up 的
  rejected、幂等重投、settled race 和 Scheduler recovery；
- OpenCode 补齐 Agent、Command、variant、crash/close、timeout/no-change，并验证 fresh、continue、
  namespace、Task-private Skills/配置和工作区交付不会发生未声明串线；
- 在兼容 Provider 容量可用后，完成 Claude/Codex 的成功 Task、fresh/continue、Skills、取消/timeout、
  usage、archive 和 Git/MR；保留现有限流失败证据，不以不兼容协议替代；
- 在目标 Linux/PostgreSQL/AF_UNIX 环境重跑适用的 Scheduler、command、concurrency、cancel 和 recovery
  测试，不以本地 skip 作为通过证据；
- 为 Pi、OpenCode、Claude、Codex 各保留一个成功 Task 的独立 DB-bound Runtime Bundle 导出。

**退出证据：** 四 Harness 各自的 conformance、真实成功 Task、Bundle、Session、terminal、usage、archive
和 Git/MR 可追溯；完整异常/恢复矩阵无 P0/P1。

### R3 — 执行冻结 20-task benchmark

- 严格使用 [V2 schema §11](../../architecture/open-harness-v2-schemas.md#11-20-%E4%B8%AA-benchmark-%E4%BB%BB%E5%8A%A1%E4%B8%8E%E7%BB%9F%E8%AE%A1%E6%96%B9%E6%B3%95)
  已冻结的场景、成功标准、可比 Endpoint/model 和统计方法；
- 每个样本记录人工验收、failure taxonomy、耗时、input/cached/output/reasoning Token、工具调用和 delivery；
- 修复后重跑受影响场景，但不删除失败样本，也不把此前的探索性 canary 追认成 benchmark；
- Pi 与当前较优兼容 Harness 做同任务对比：成功率下降不超过 10 个百分点，中位耗时和 Token 不得
  同时恶化超过 25%。

**退出证据：** 不少于 20 个冻结样本完整可追溯，统计口径一致，Pi 质量和性能门槛同时通过。

### R4 — 完成 UI、运维与发布评审

- 在 390×844、768px 和桌面视口完成真实交互验证：命令发送、键盘遮挡、安全区、44px 触摸目标、
  长文本/状态换行、断线重连和 command history；
- 审阅四 Harness 的 success/failure taxonomy、protocol error、command latency、usage、terminal、archive
  和 delivery 指标；
- 在最终 composition 上完成 secret scan、凭据轮换核对、release note、旧 Kit 退役计划和发布签署；
- 清零 hard-cut candidate 的 P0/P1。

**退出证据：** L5 全部通过，并形成单独的 hard-cut go/no-go 评审记录。

### R5 — 在独立维护窗口执行 L6

R1–R4 未全部通过前不安排 L6。获得单独批准后，按 Runbook 排空在途任务、备份数据库、冻结 V1
只读边界、切换新建 Profile 的 Pi 默认值和 `HARNESS_EXECUTION_MODE=v2_only`，再执行四 Harness smoke、
Scheduler recovery、command plane、统计和历史只读检查。失败时保持维护状态并 roll forward，不启动旧 V1
应用回滚。

## 6. 明确不进入本轮的工作

- 不增加撤销、denylist、任务迁移、紧急回退状态或新的 schema；没有真实需求时不建设过渡机制；
- `linux/arm64` 只在目标 Host 清单实际出现该架构时增加，不为假设平台提前扩张矩阵；
- OMP 保持独立实验，只有 V2 hard cut 后才用同一 benchmark 评估，不修改 V2 公共合同来迁就 OMP；
- 不重复消耗已知受限 Provider，也不使用协议不兼容的 Provider 冒充 Claude/Codex 成功。

## 7. 停止条件

出现以下任一情况，立即停止当前层级并保留证据：

- 实际执行 bytes 与冻结的 Image、Kit、Bundle、Adapter、Profile generation、Host 或 attempt identity 不一致；
- 使用 mutable tag、placeholder digest、未验证 Kit、过期 readiness、`host_mount` 或旧 image CLI lock
  冒充 release evidence；
- V1/V2 cohort 隔离、command 顺序/幂等、PostgreSQL/AF_UNIX/concurrency/recovery 出现失败或必要
  skip 未补跑；
- Pi/OpenCode 发生协议推断、转换或回退，或任一目标协议缺少真实 Endpoint conformance；
- 任一 hard-cut Harness 缺少真实 Task、terminal、usage、archive、Git delivery 或独立 Bundle，或存在 P0/P1；
- 20-task、Pi 非劣性、UI 交互、Provider/GitLab 授权、凭据轮换、secret scan 或发布签署未完成。

单个 Harness 的 functionality gate 失败只能把该 Harness 标为 unavailable，不能借用其他 Harness 的成功
结果；但 hard-cut candidate 缺少四 Harness 任一项时，不得进入 L6。数据库继续保持 roll-forward-only，
不得改写历史 Snapshot、Issue、attempt、archive 或验收证据。
