# Open-Harness V2 当前进展与剩余验收计划

**复核日期：** 2026-08-30

**本地源码基线：** `dev` 当前已将本轮 Harness Adapter、catalog、command、sanitizer、前端 API 和
entrypoint 测试修复冻结为本地提交 `e4b9b59e`，并在其上追加前端 V2 lineage 会话提示修复提交
`5ef8ddd3`，均尚未推送。backend/full mock E2E/build、Ruff 和 Shell/Python 检查在前一提交通过；当前
revision 的完整 frontend suite/build 也已通过。远端 backend/scheduler 保持前一提交的同一源码基础，
nginx 已从当前 checkout 重建并核对。
镜像没有自定义 Git revision label，因此只把容器内源码标记、前端 footer 和运行时行为作为来源交叉证据，
不把不存在的 label 当作 provenance。

**运行边界：** Backend/Scheduler 仍为 `HARNESS_EXECUTION_MODE=dual_canary`、
`AUTO_MIGRATE=false`，数据库 revision 为 `077_v2_worker_kit_identity`。

**当前 candidate：** 目标 `linux/amd64` Host 已安装 Kit `0.6.11`；Profile 4 启用 Pi、OpenCode、
Claude、Codex，Profile 内默认 Harness 为 Pi，但该 Profile 不是系统全局默认。Profile 4 的 runtime
verify 已于 DB 时间 `2026-08-30 11:21:42` 返回成功，`image/Kit/Harness` evidence 与 generation `22`
已持久化。由于 readiness TTL 较短，下一轮 canary 仍须在执行前重新 verify。

**本轮推进记录（2026-08-30）：**

- 远端 `192.168.50.129` 的 Profile 4 verify-runtime 已重新完成；Kit `0.6.11`、四 Harness identity
  evidence 和 DB 绑定保持一致，`v2_worker_image_identity_generation`、`worker_kit_identity_generation`
  均为 `22`。
- R1 已在 `e4b9b59e` backend 基础上完成 backend/scheduler/nginx composition 重建：backend healthy、
  scheduler/nginx 正常运行并报告 `dual_canary`；数据库仍为 `077_v2_worker_kit_identity`，任务历史和
  Profile 4 的验证字段未丢失。随后 `5ef8ddd3` 的前端变更单独重建 nginx，远端镜像 digest 为
  `sha256:46ae8679ae816d18236007023b109e1caa6c1b6a0ed1bb882a6765b62558e580`；镜像 provenance 不依赖
  不存在的自定义 revision label，页面 footer 显示 `5ef8ddd`。
- 通过已登录 UI 显式选择 Pi 创建 fresh execute、无代码变更 Task #118（Provider 7 / `openrouter-free`）；
  DB 记录为 `completed`、Harness `pi`、`require_changes=false`、Runtime Bundle `100`，提交统计为
  `+0/-0`。attempt 以 `run.completed`、`control_state=closed` 收口，canonical cursor 为 `267`，归档
  为 `task-118-runtime-archive.tar.gz`（26,380 bytes），包含 `event.jsonl`、`harness-result.json`、
  `harness-events/pi.jsonl`、`delivery-summary.md` 等。
- 为容器已创建后才落库的取消请求补上收口：Runner 在创建容器后重新读取 Task 的持久化取消意图，
  对已启动容器执行有界 graceful stop，并在 stop 失败时仅对该容器 fallback 到 kill；新增焦点单测。
  当前工作树的相关聚焦 suite 为 `109 passed`，Ruff 与 `git diff --check` 通过；backend/scheduler
  已在远端重建，运行中的 backend、scheduler 均使用新镜像并保持 `dual_canary`。
- 修复后在 `192.168.50.129` 通过 UI 创建 Pi fresh execute Task #115（Provider 7）和 OpenCode
  fresh freeform Task #116；两者均 `completed`、无取消意图、容器无残留，各自保存独立 runtime archive，
  attempt 分别以 `pi`/`opencode` 的 `run.completed` 和 `control_state=closed` 收口。Task #115 的
  交付摘要验证单一 canary 文件及字节内容；Task #116 的任务详情、工具卡片、提交记录和交付摘要验证
  OpenCode 文件交付。两次正常收口都观察到停止后 canonical tail 的 Docker 409，随后 archive fallback
  保留了 `event.jsonl`、对应 Harness 原始事件和终态；该告警不作为 Harness 成功失败的替代判据。
- Task #118 进一步完成 Pi `execute` no-change 边界：fresh、`require_changes=false`、`+0/-0`，成功收口
  且 archive/attempt/canonical cursor 完整；Task #119 完成 OpenCode fresh 配置隔离边界，成功记录
  task-scoped `HOME`、XDG roots、`OPENCODE_CONFIG_DIR`，并确认 project/external Skills/Claude Skills/
  models fetch 均被禁用。#119 的原始 OpenCode 事件包含该 shell 输出，未出现受禁止的 key/token/password
  变量；两项均没有容器残留。
- Task #119 启动前由目标 Profile 的 readiness gate 重新完成严格 Kit inventory probe：DB row 为 `ready`、
  Kit `0.6.11`、check generation `120`，`ready_until` 为 `2026-08-30 11:51:28`；这证明 canary 使用了
  有效的短 TTL readiness，而不是沿用 Profile verify 的旧时间戳。
- 在同一 Issue 上显式选择 OpenCode、Provider 7、`freeform`、`continue` 创建 Task #120；Worker 启动时
  重新通过 readiness gate（Kit `0.6.11`、check generation `122`），并将 #119 的
  `output_session_id` 作为本代 lineage 的 `input_session_id`，`input_lineage_reason=resumed`。Task #120
  绑定 Bundle `99`，最终 `run.completed`、`control_state=closed`、`61` 个 canonical events、usage
  `237/162`、`+0/-0`，归档 `task-120-runtime-archive.tar.gz`（10,606 bytes，SHA-256
  `dcbe9c44a7fb0f7fe98b1f1037f8cf607675dbc60cf0b9cd585e75c4e362ad3f`），无容器残留；这补齐了当前
  Bundle 下 OpenCode 的真实 continue/session-resume 样本。
- 远端 UI 实证显示 Issue #22 已有 OpenCode V2 lineage，但旧前端只读取 `claude_session_id`，曾误显示
  “当前需求没有已记录的会话”。`5ef8ddd3` 将 TaskFormDrawer 的语义改为 `hasCurrentSession`，IssueView
  和 TaskView 同时识别 legacy session 与 `current_harness`；相关 3 个入口测试 335 passed，完整前端
  suite 为 79 files / 1,678 passed，production build 通过。当前远端任务表单已显示“不继承当前对话上下文；
  保留工作区、Git 分支和旧会话记录”，且未创建额外 canary task。
- 远端非机密 provider 配置当前只有 Provider 3/6 的 Anthropic、Provider 4 的 Responses、Provider 5/7
  的 Chat；已知受限 provider 的真实请求仍返回额度限制，因此本轮不重复消耗它们，也不把 Provider 7
  的 Chat 成功冒充 Claude/Codex 成功。Claude/Codex 的真实成功矩阵仍待兼容额度恢复。
- 当前真实协议证据边界可精确对账：Pi #115/#118 与 OpenCode #116/#119 均为 Provider 7、模型
  `minimax/minimax-m3:free`、`openai_chat_completions`，分别绑定独立 Bundle；OpenCode #106 为
  `openai_responses`、#107 为 `openai_chat_completions`、Pi #111 为 `anthropic_messages`，三者均在
  真实请求前后落为额度限制且 input/output token 为 0。三协议 conformance 因 Provider 容量仍未闭合，
  不重试这些已确认受限组合。
- 误配置的 Task #117 曾在稳定容器 ID 发布前收到取消请求，API 返回 503 并保留 pending cancellation；
  随后任务自动以 `cancelled` 收口，未留下容器。该 Task 不计入任何 R2 成功证据；它同时保留了“创建后取消
  请求”边界的真实日志，不能与正常 canary 混为一谈。
- 远端 Docker `system df` 显示磁盘未满，本轮没有清理镜像；只保留“满盘时清理已确认的 Codify 调试镜像”
  这一边界。
- 本轮提交 revision 已完成聚焦后端 109 passed、完整后端 3,194 passed / 4 skipped / 96 subtests、完整
  mock E2E 378 tests、完整前端 1,678 tests、前端 production build、Ruff、Shell/Python 静态检查；完整
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
| L2 源码/测试 | 通过（当前 revision） | V2 公共地基、Pi/OpenCode Adapter、四 Harness fixture、command plane、catalog 和 execution policy 已落地；`e4b9b59e` 的完整 backend/mock E2E/build、Ruff 和 Shell/Python 检查，以及 `5ef8ddd3` 的完整 frontend suite/build 通过，远端 composition 以容器源码标记、footer 和运行时行为交叉核对 | 后续若改变源码或 composition，必须重新生成唯一 release evidence；`v2_only` 仍属于 L6 |
| L3 不可变 composition | 部分通过 | `linux/amd64` Image + Kit `0.6.11` + Profile 4 已安装并完成 identity/DB 绑定；Pi/OpenCode 有 DB-bound Bundle 证据，Task #118/#119 启动前通过 generation `120`、Task #120 启动前通过 generation `122` readiness gate | readiness TTL 较短且会再次过期；Claude/Codex 各自基于成功 Task 的独立 Bundle 导出与最终 release freeze 尚未齐全 |
| L4 真实 Host/Task | 部分通过 | Pi/OpenCode 有真实模型、工具、Session、终态、archive 和 Git/MR；Pi 已有 Skills 与 execute-no-change #118，OpenCode 已有 task-private config/Skills isolation #119 和当前 Bundle continue #120；取消/abort 与 live command 有代表性证据 | Claude/Codex 成功路径、三协议完整矩阵、真实 recovery/concurrency 和完整异常矩阵未完成 |
| L5 发布验收 | 未完成 | 验收场景和统计方法已冻结 | 四 Harness 功能矩阵、20-task、Pi 非劣性、完整 UI/交互和发布评审未通过 |
| L6 hard cut | 未执行 | `v2_only` 与 V1 只读的源码路径存在 | 未切全局 Pi 默认，未进入维护窗口，未执行 hard-cut smoke |

证据不能跨层替代：单测不能证明 Host 安装，Kit verify 不能证明真实模型与 Git/MR，单个成功 Task
不能证明协议矩阵或 benchmark，Pi/OpenCode candidate 不能证明四 Harness release readiness。
`host_mount` 只允许作为逐 Harness 授权的 break-glass 来源，不得充当 Kit-owned release evidence。

## 4. 与原实施方案的对照

| 原方案阶段 | 当前状态 | 剩余退出条件 |
| --- | --- | --- |
| Phase 0：协议探针与接口冻结 | 部分完成 | 四 Harness fixture、V2 schema 和 20-task 定义已冻结；Pi/OpenCode 三协议真实 Endpoint 的双向、异常和恢复 probe 尚未齐全 |
| Phase 1：V2 公共地基与 command plane | 已完成当前 revision recheck | 当前 revision 的完整 release regression 与远端 composition 已核对；`v2_only` 生产切换属于 L6，不能用源码测试代替 |
| Phase 2：Pi 默认 Harness | 部分完成 | 代表性真实功能、Skills 和 execute-no-change 已有样本；仍缺三协议完整 conformance、timeout/failure、native terminate 边界，以及 rejected、重投、settled race、Scheduler recovery 的真实矩阵和 20-task 非劣性门槛 |
| Phase 3：OpenCode 一级 Harness | 部分完成 | fresh/continue、Task-private Skills/配置、usage/tool、Git delivery 和 abort 收口已有样本；仍缺三协议完整 conformance、Agent/Command/variant、crash/close、timeout/no-change，以及不同 namespace 的跨 Task 隔离证明 |
| Phase 4：Claude/Codex V2 | 部分完成 | Adapter、协议声明、fixture/replay 和失败收口已落地；兼容 Provider 额度恢复后仍须完成两者的真实成功、Session、Skills、取消/timeout、usage、archive 和 Git/MR 矩阵 |
| Phase 5：产品、制品、Canary 与 hard cut | 部分完成 | Kit/Profile/catalog/readiness 和部分 UI 已落地；四 Harness L4、20-task、完整 UI、release review、Pi 默认迁移和 `v2_only` 均未完成 |
| Phase 6：OMP | 未开始 | 仅在 V2 hard cut 后独立评估，不进入当前 release candidate |

当前实现与方案的核心边界一致：Worker Kit 拥有 Harness CLI payload，Project Runtime Image 拥有项目
工具，Runtime Bundle 拥有 Adapter/Bridge/orchestration bytes；实际执行只认冻结 Snapshot/Bundle/Kit
identity，不从 image、`PATH`、用户配置或另一 Harness 的成功结果隐式回退。

## 5. 剩余工作与执行顺序

### R1 — 冻结当前 release candidate

这是继续收集 L4/L5 证据前的第一步。

- 已评审并提交 Adapter、catalog、command、sanitizer 和 entrypoint 修复为 `e4b9b59e`，再提交 V2
  lineage 会话提示修复为 `5ef8ddd3`，明确唯一当前源码 revision；
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
