# Open-Harness V2 当前遗留项与验收计划

**更新：** 2026-08-28

**本次复核基线：** `1cc7c764`（控制面 Backend/Scheduler；Nginx 使用 `94ac94fc`）

**状态：** Internal Preview。`linux/amd64` 的不可变 Kit、Project Runtime Image、官方 Host 安装、
当前控制面、DB-bound Profile/Bundle 和 readiness 已形成一套可复核的 dual-canary candidate；L3 与
Host/运行时部分的 L4 证据已闭环，Task38、Task41、Task42 与 Task43 均验证了 quota failure 后的自动 close/清理。`65395609f70c`
进一步将冻结的 `model_protocol` 纳入 Task runtime-summary API 与 Task 详情弹窗，`d0e2a07b` 又修复控制面
读取已打包 Runtime Bundle manifest 的路径，恢复 current `/harness-catalog`；这些只加强诊断/目录证据，不改变
真实成功/MR 门槛。`14127ec4` 为 Task 详情页增加切回标签页后的即时状态刷新，降低浏览器保留旧 Task 状态的窗口；
`94ac94fc` 将同一语义覆盖到共享轮询、Dashboard、Issue 和 Schedule 工作台。
真实模型成功与 Git/MR 交付已在用户明确授权的 `openrouter-free` 调试 Provider 上取得首组证据：
Task 44（OpenCode freeform）、Task 46（Pi fresh execute）、Task 47（Pi continue execute）和 Task 48
（OpenCode execute）均进入真实 Worker；四者均完成真实终态/归档对账并有 commit/MR，Task 47 复用了
Task 46 的 session。随后 `1cc7c764` 修复 OpenCode 1.18.19 实际 `info.tokens`/`part.tokens` 的 usage 映射并补齐
`usage.final`，Task 52 在同一 Profile 上验证了 OpenCode usage `117/170` 的真实落库。N3 仍未闭环：三协议成功矩阵、
四 Harness/20-task 与 N4 安全评审仍是独立门槛。随后 Task 53 完成了 OpenCode `continue`，复用了 Task 52
的 session，并验证了 usage `125/172` 与跨 Task lineage 对账。
近期仍只推进默认 `pi+opencode` 的
`dual_canary`；`arm64` 仅在目标 Host 清单出现该架构时补证，四 Harness/20-task 继续作为未来
`v2_only` 硬切门槛。当前不切全局 Pi 默认，不启用 `v2_only`。

本文只维护当前剩余工作和退出条件。已完成且已验收的工作不再保留为待办流水账；架构约束以
[Open-Harness V2 架构方案](../../architecture/open-harness-v2.md) 为准，发布操作以
[dual-canary 与生产验收 Runbook](../../runbooks/multi-harness-rollout.md) 为准。
历史制品 digest、Task ID 和逐次测试结果保留在 Git 历史中，不在本文重复。

## 0. `dual_canary` 的准确含义

`dual_canary` 是 V1/V2 两种执行合同在受控验证期内并存的门禁模式，不是把同一个 Task 同时交给
V1 和 V2 双跑，也不是复制流量、影子执行或自动 A/B：

- 每个 Task 创建时只冻结一个明确的 Runtime contract、Worker Profile、Harness、Runtime Bundle 和
  制品 identity；一次 attempt 只按这一个冻结组合执行。
- 明确的 V1 Profile/cohort 只能创建和执行 V1 Task；明确的 V2 Profile/cohort 只能创建和执行 V2
  Task。系统不得自动升级、降级或把一个 generation 的 Session/Task 转成另一个 generation。
- V1 保留执行能力是为了在 V2 canary 尚未验收时维持现有内部任务；V2 只通过显式 Profile/cohort
  承接受控测试。两边共享 Scheduler/数据库并不等于共享执行合同或同一 attempt。
- `dual_canary` 期间仍必须在 create、execute/schedule/retry/resume、Scheduler claim/promotion、Worker
  start 和 recovery 使用中央 execution policy；它不是绕过 Snapshot、Bundle 或 identity 校验的宽松模式。
- L1–L5 全部通过后才可切换 `v2_only`。切换后 V1 只读：历史 Task、日志、归档和统计可查，但 V1
  create、execute、retry、resume/continue 与 recovery 必须明确拒绝。

## 1. 已验收基线

以下能力已经完成源码、单测或受控 dev 验证，不再作为独立待办；相关代码发生变化时仍须按影响面
重跑验证：

- Project Runtime Image、Worker Kit、Runtime Bundle 的 ownership 已拆分；旧 image-owned CLI
  lock/identity 链已从主要构建和执行路径移除。
- Worker Kit 已具备四 Harness inventory、`present|absent`、`not_selected|missing_payload`、
  content-addressed 安装目录、root-owned、atomic no-replace 和安装回执的基础机制。
- migration `077_v2_worker_kit_identity` 已建立 Profile/Readiness 的 Kit identity 与 inventory 字段；
  dev PostgreSQL 上的 revision、锁顺序、CAS/generation 验证已经通过。真实部署升级仍是发布动作。
- Registry 已禁止隐式 image/`PATH` 回退；create、retry、scheduler 和 lifecycle 已具备
  `harness_cli_unavailable` 基础门禁；Worker Settings 与 current/frozen `/harness-catalog` 已展示逐
  Harness availability/reason。
- Compatibility baseline 差异已改为 advisory warning；present payload 完整性和 functionality
  gate 的主体逻辑已存在。
- 既有全量 L1/L2 回归和 Linux 原子安装原语验证可作为基础证据，但不能替代 immutable release、
  真实 Host、真实 Task、canary 或 hard cut 证据。

`host_mount` 只保留为显式、逐 Harness 授权的 break-glass 来源。它可以验证执行链，不得替代
Kit-owned present CLI 的 release evidence。

协议现状必须单独标记：源码 correction 已让 Pi/OpenCode 的 Runtime manifest、Backend upper bound、
Bundle-authoritative catalog、Task snapshot、两个 Adapter 和前端筛选一致声明并处理
`anthropic_messages`、`openai_responses`、`openai_chat_completions`；Claude 仍只允许 Anthropic，Codex
仍只允许 Responses。该状态只表示源码退出条件，不等于三协议真实 Endpoint/Task、完整 Kit 矩阵或发布
验收已经完成。

## 2. Source/L2 已验收基线

本节只记录当前结论。官方安装、目标 Host、DB 绑定与真实 Task 分别归 L3/L4，不能反向冒充或阻塞
源码验收。

- [x] **S1 — Worker Kit build/archive 路径。** 当前目标 `linux/amd64` 已覆盖默认
  `pi+opencode`、四个单项、显式子集、四项 present 和空选择；manifest、archive 与 runtime path
  一致。官方安装与 atomic/no-replace/recovery 归 N1，DB-bound composition 归 N2；`arm64` 仅在目标
  Host 清单出现时补证。
- [x] **S2 — 整 Kit content identity。** Canonical content inventory/digest 已贯穿 manifest、安装
  回执、readiness、Profile snapshot 和 Runtime Bundle；tamper、链接链、长路径及大小写路径均
  fail closed。真实 Host 安装仍归 N1。
- [x] **S3 — V1 lifecycle。** `dual_canary` 下 V1 frozen Task 可沿原合同创建容器，V2 identity/CLI
  注入不受影响；部署后的复验归 N2。
- [x] **S4 — Task-scoped command pump。** claim、队列头、dispatch/close、lease 与 recovery 都按
  `task_id` 隔离，跨 Task attempt 不会误领；并发与严格顺序已通过 PostgreSQL 回归。
- [x] **S5 — availability catalog。** current catalog 使用所选 Profile 的 readiness，frozen catalog
  只认 Snapshot/Bundle；前端阻止提交 unavailable Harness，同时允许历史 Task 修改非运行时字段，且
  不暴露 Host path 或敏感 evidence。
- [x] **S6 — Harness × Model Protocol 合同。** Pi/OpenCode 支持
  `anthropic_messages`、`openai_responses`、`openai_chat_completions`；Claude 只支持 Anthropic，
  Codex 只支持 Responses。Runtime Bundle manifest 是已绑定 Task 的能力权威。
- [x] **S7 — Pi 三协议 Adapter。** 三种协议均按冻结 Endpoint 生成 Task-private 配置，禁止 URL 推断、
  协议转换、跨协议回退或读取用户配置；Session、steering/follow-up、usage 和 terminal 语义保留。
- [x] **S8 — OpenCode 三协议 Adapter。** Task-private `opencode.json` 固定 Provider/model pair，
  credential 只通过私有环境变量引用；事件、tool/reasoning、usage、Abort、settled、terminal 与 Session
  resume 已纳入合同，禁止项目/用户配置覆盖 Snapshot。
- [x] **S9 — 当前 L2 证据。** V2 runtime-summary 基线提交 `65395609f70c` 的全量 backend unit 为
  `3156 passed, 4 skipped, 96 subtests` 且无 warning；其中包含控制面基线 `eea817f5` 的
  `3155 passed, 4 skipped, 96 subtests` 和运行时基线 `6b4f1056` 的
  `3150 passed, 4 skipped, 96 subtests`；其后 `4dca29d6` 对齐契约文档，
  `25ee198f` 修复 OpenCode quota reason taxonomy，`eea817f5` 补充协议化 Worker 启动摘要；当前提交
  `65395609f70c` 的受影响 backend regression 为 `45 passed`，frontend Task runtime-summary 变化面为
  `122 passed`；`d0e2a07b` 的 harness catalog regression 为 `16 passed`；其中包含 `c5e0ecf5` 的
  `OpenCode suite 35 passed`、`command-pump/control-client/Pi owner 46 passed`、`94ac94fc` 后 frontend
  `1675 passed`、mock E2E `378 passed`、`npm run build`、Ruff、`py_compile` 和 `git diff --check` 均通过；
  Scheduler/runtime-config focused regression 另为 `140 passed`，并已部署验证。root-only 安装用例已在 N1
  真实 Host 重跑；`5090b3ce` 补齐了脱敏 benchmark metadata 摘要工具，但它只记录 Harness lifecycle，
  不产生 Task/MR acceptance 证据；当前源码无已知 P0/P1，外部 Provider 额度限制不归入源码失败。

## 3. Release、L3 与 L4

证据层级固定如下，不能跨层替代：

| 层级 | 证明内容 | 当前状态 |
| --- | --- | --- |
| L1 | 架构、schema、Runbook 与安全边界一致 | 当前合同已对齐；未来 hard cut 的四 Harness 门槛保持不变 |
| L2 | 源码、单测、集成测试和并发合同 | 通过；全量 backend unit 基线与当前 HEAD 变化面测试、PostgreSQL focused regression、frontend、mock E2E 和 Ruff 已通过；root-only 安装用例转入 L3 |
| L3 | 同一不可变 image + Kit + Bundle 的构建、安装、DB 绑定与 digest 对账 | 通过；`0.6.6` Kit、Project Runtime Image、官方安装回执、Profile 3、Runtime Bundle 58–74 已完成 identity 对账 |
| L4 | 真实 Linux Host、remote Docker、Provider、仓库和真实 Task/MR | 部分通过；Host、Docker、Profile/readiness、Task lifecycle、quota failure、自动 close/清理，以及 `openrouter-free` 下 Pi/OpenCode 的成功模型与 Git/MR 已验证；三协议完整矩阵、四 Harness 与规模化验收仍未完成 |
| L5 | 四 Harness canary、Pi 20-task 与质量/性能验收 | 未完成；尚未具备完整四 Harness/20-task 证据，不能进入 `v2_only` hard cut |
| L6 | 维护窗口 hard cut、Pi 默认和 `v2_only` | 未执行 |

### 当前最小下一步：一个 `pi+opencode` dual-canary candidate

当前目标是把已有源码变成一套可复现、可运行的 `linux/amd64` dual-canary candidate，不是立即 hard cut。
只执行以下四步，不增加新 schema、回退状态、撤销/denylist 或额外平台机制：

- [x] **N1 — 冻结并官方安装一个 candidate。** 已在 remote Docker 的 `linux/amd64` Host 构建并安装
  `0.6.6` `pi+opencode` Kit：manifest `48f07e92…`、content inventory `f6c4e18e…`、archive
  `a1b921f5…`，安装目录为 `/opt/codify/worker-kits/0.6.6-linux-amd64-48f07e92a994`。Pi `0.84.2`
  与 OpenCode `1.18.19` 的 SHA、root ownership、preflight、两 Harness `--verify` 均通过；4 个
  root-only 安装用例（成功、冲突不替换、校验失败恢复、atomic race publish）均通过。Project Runtime
  Image 使用 registry digest `sha256:234582c6…`、image ID `sha256:b07ac48b…`。后续控制面修复未改变
  该 Kit/image bytes；`25ee198f` 更新了 OpenCode Adapter source，因此在新 canary 前通过官方
  verify-runtime 重新冻结了 Profile Adapter evidence；本轮 `1cc7c764` 再次更新真实 usage 映射，
  随后以同一 Profile 重新 verify-runtime 并生成 Bundle `74`。
- [x] **N2 — 部署当前控制面并完成 DB 绑定。** Backend/Scheduler 已部署 `1cc7c764`（image ID
  `sha256:183a9b78a9ccde3ad605772fe4c17aa17e15d3416b1853800d770cf90f29951a`，registry digest
  `sha256:0291a4c3ac90258751456b01cd84e72c67e1439c2049dcddd5bf9ae1be3104bc`），Nginx 已部署
  `2026.08-v2-94ac94fc`（registry digest `sha256:240b272bd4be6e3ca42cb7aca542314a93d3231dea0701f743685b16cca30dc0`）；两服务
  保持 `HARNESS_EXECUTION_MODE=dual_canary`、`AUTO_MIGRATE=false`，health/database/docker 均为
  healthy，schema 为 `077_v2_worker_kit_identity`。Profile 3 `v2-canary-528ef37a` 当前为 mounted-kit、
  Kit `0.6.6`、enabled/default `pi+opencode`；`eea817f5` 更新了 Worker 启动诊断 source，
  本轮 `1cc7c764` 部署后于 2026-08-28 14:28:17 通过官方 verify-runtime 重新冻结两项 Adapter evidence，
  readiness 为 `ready`。
  Profile image/Kit identity generation 均为 `18`，config digest 为
  `014591ba4b6e2b79068006d088b493a147b7fe6c07469ec3824a37b72f8319f6`。Task 20–28 使用 Bundle 58–62，
  Task 30/32/35–38 使用 Bundle 63/64–68，Task 41/42 使用 Bundle 69，Task 43 使用 Bundle 70；均为
  `codify.worker.harness/v2` / orchestration `1.0.0`。随后 Task 44/48 绑定 Bundle `71`，Task 46/47 绑定 Bundle
  `72`；Task 52 绑定 Bundle `74`，均沿用同一 Profile 3 / Kit `0.6.6` composition。部署后脱敏 API 确认 Task 43 的
  `model_protocol=openai_responses` 可从 execution/frozen snapshot 读出；Task 详情弹窗显示相同协议且只显示
  API key 状态，不显示密钥。`1cc7c764` 部署后 current `/harness-catalog` 已返回
  `current_runtime_manifest` / `codify.worker.harness/v2`，不再是 503；Profile 3 参数化 catalog
  已确认 Pi/OpenCode 为 `present/selectable`。
- [ ] **N3 — 跑最小真实 canary（部分完成）。** 已覆盖 OpenCode 三协议和 Pi 的真实 Host lifecycle
  尝试：Task 20 的 upstream retry/额度限制已可取消并释放容器；Tasks 23–25 收敛为 typed
  `rate_limited`；Tasks 26–28、30、32、35–37 均已收敛为 terminal/取消并清理容器。期间发现并修复
  OpenCode account-limit retry、translator pipe close、Pi owner ACK、远程 control exec/container lookup
  的无界等待，以及固定 outcome 文件不可覆盖的问题。Task38 在 `47a27cad` 部署后未人工干预即完成
  `agent_settled → close → run.failed`，attempt 为 `closed`、`last_seq=10`、container 已清理；当前
  受影响 focused regression 为 `46 passed`。`25ee198f` 又修复了 OpenCode action/status quota reason
  的显式 `rate_limited` 归类与 result 保留，新增变化面为 `37 passed`。首次重试因 Profile 仍冻结旧
  Adapter digest 被 Bundle 门禁正确拒绝；完成官方 verify-runtime 后，Task 41 以 generation `14`、
  Bundle `69` 成功创建并实际运行，约 90 秒后收敛为 `failed/rate_limited`，attempt `closed`、`last_seq=58`、
  `queue_position/container_id` 清空且无残留容器。这补齐了当前 Adapter 修复后的真实
  create→claim→run→typed failure→cleanup 证据。随后 Task 42 使用同一 generation `14`/Bundle `69` 和
  正确冻结的 `openai_responses` Provider，约 96 秒后同样收敛为 `failed/rate_limited`，attempt `closed`、
  `last_seq=58`、`queue_position/container_id` 清空；这确认备用 Responses Endpoint 也确实进入了当前
  Adapter，而不是沿用 Anthropic 配置。`eea817f5` 部署后，Task 43 使用 generation `15`/Bundle `70`
  实际输出协议化启动摘要（`openai_responses`、对应 model/endpoint），随后同样收敛为
  `failed/rate_limited`，attempt `closed`、`last_seq=58`、容器清理；这补齐了新诊断 source 的真实 Worker
  证据。`65395609f70c` 又将该冻结协议下沉到 Task runtime-summary API/UI，部署后 Task 43 API 与页面均显示
  `openai_responses`；这属于可审计的配置诊断。

  本轮在用户明确授权后启用远端 `openrouter-free`（Provider 7，`openai_responses`），同一 Profile 3 / Kit
  `0.6.6` 上完成了四条真实成功证据：Task 44 为 OpenCode `freeform`，Task 46 为 Pi `execute/fresh`，
  Task 47 为 Pi `execute/continue`，Task 48 为 OpenCode `execute`；四者均有 canonical `run.completed`、
  attempt `closed`、archive、commit/MR，Task 46/47 另产生 usage `272/250`、`223/194`，且
  `input_session_id == Task 46.output_session_id`。两条 Pi 任务的 archive 均为 `codify.worker.result/v2`、
  Pi Adapter `2.0.0`、CLI `0.84.2`，唯一 `run.completed` 位于末尾，包含 `worker.finalization` 与 delivery；
  两条 OpenCode 任务同样完成 V2 archive、delivery 和 MR 对账；Task 46/47/48/52/53 后活动队列均回到 0。
  这组证据解除“尚无成功模型/commit/MR”的旧阻塞，但不等于 N3 完成：仍需按原矩阵补齐
  `openai_chat_completions` 的真实成功 Task、其余适用协议/Harness 的真实 Endpoint conformance，以及
  Session/usage/archive/Git/MR 的跨协议对账和 Pi/OpenCode 主 lifecycle 规模化验证。

  本轮首次真实 OpenCode usage 复核发现旧 Adapter 只读取 `info.usage`，而 OpenCode `1.18.19` 实际成功 wire
  使用 `message.updated.info.tokens` / `message.part.updated.part.tokens`，并在同级 `cost` 提供费用。`1cc7c764`
  补齐了 `input/output/reasoning/cache.read`、nested cost total 到 canonical usage 的映射，并发出 `usage.final`；
  Profile 3 在 generation `18` 重新 verify-runtime 后，Task 52 使用 Bundle `74` 成功完成 OpenCode
  `execute/fresh`，真实 API/DB usage 为 `117/170`，usage ledger 为 `117/170/287`，archive 为 V2，attempt
  `closed`、`last_seq=81`、唯一 Task terminal 为 `run.completed`，并有 commit/MR。Task 52 的结果说明该 usage
  修复已跨过 Worker、archive、projector 和 ledger；随后 Task 53 使用同一 Bundle 完成 OpenCode
  `execute/continue`，usage 为 `125/172`，`input_session_id == Task 52.output_session_id`，attempt `closed`、
  `last_seq=78`，同样有 V2 archive、commit/MR。OpenCode fresh→continue 的 session lineage 现已有真实证据；
  这仍不替代未完成的三协议、四 Harness 与规模化门槛。
- [ ] **N4 — 评审并停在 dual-canary。** 清零本 candidate 的 P0/P1，完成 secret scan 和调试凭据轮换，
  将 candidate 仅开放给显式 V2 Profile；不改变全局 Profile 默认、不切 `v2_only`。本轮
  `secret-scan=passed findings=0`，但远端仍有 3 个历史 unsupported `system_config` key
  （`gitlab_webhook_secret`、`maven_cache_host_path`、`maven_settings_host_path`）和 1 个
  无法用当前加密密钥解密的 `oidc_client_secret`；已通过 `6b4f1056` 将重复告警降为启动时一次，
  且源码审计确认前 3 个 key 在当前应用中已无引用，属于可清理的历史行；但未擅自删除/覆盖配置，
  需由部署负责人确认清理，`oidc_client_secret` 则需正确加密密钥重新录入或明确清除后才可关闭该 N4 项。
  通过后再单独决定是否进入
  hard-cut 准备；若决定进入，才补四 Harness 同一 composition、Claude/Codex canary、20-task benchmark
  与 L5/L6。

`linux/arm64` 只在目标 Host 清单出现该平台时新增 N1 分支；纯文档/证据变化不触发全量测试重跑。
这两个条件用于控制当前范围，不修改架构文档对最终 V2 hard cut 的既定门槛。

### 当前 dev/remote 快照（2026-08-28）

- **门禁与 schema：** 只读检查确认 remote daemon 为 `linux/x86_64`（制品平台 `linux/amd64`），
  Backend/Scheduler 都是 `dual_canary`、`AUTO_MIGRATE=false`，数据库 revision 是
  `077_v2_worker_kit_identity`。
- **部署与身份：** backend/scheduler 当前镜像为 `2026.08-v2-1cc7c764`，image ID 为
  `sha256:183a9b78a9ccde3ad605772fe4c17aa17e15d3416b1853800d770cf90f29951a`，registry digest 为
  `sha256:0291a4c3ac90258751456b01cd84e72c67e1439c2049dcddd5bf9ae1be3104bc`；Nginx 为
  `2026.08-v2-94ac94fc`，registry digest 为
  `sha256:240b272bd4be6e3ca42cb7aca542314a93d3231dea0701f743685b16cca30dc0`；backend `/health` 报告
  database/docker 均为 `ok` 且执行模式为 `dual_canary`。远程页面 footer 已显示 `94ac94fc`，Task 20
  详情页显示 `Cancelled`，页面布尔检查确认没有 `Queue head`、`Waiting for Worker` 或“队首 · 等待 Worker”
  文案。2026-08-28 06:49 UTC 的实时复核进一步确认 Task 20 为 `cancelled`、`container_id` 为空、
  `queue_position` 为空，且远端 `pending/queued/running` 查询为 0；本轮 Task 52 完成后再次确认远端活动队列为
  0、Task 20 仍为 `cancelled` 且无 container；若用户仍看到旧的 `running`/队首提示，属于浏览器未刷新后的旧状态。
  该提示的根因是 backend 对运行中的队首 Task 合法返回
  `queue_position=1`，三个前端队列上下文视图现已对 `running` 隐藏等待文案。
- **Kit/Profile：** Profile 3 `v2-canary-528ef37a` 绑定 mounted Kit `0.6.6`，路径为
  `/opt/codify/worker-kits/0.6.6-linux-amd64-48f07e92a994`，enabled/default 为 `pi+opencode`；
  2026-08-28 14:28:17 的官方 verify-runtime 对 Pi/OpenCode 均成功，readiness 为 `ready`。Profile 持久化
  image identity `sha256:234582c6…`、Kit manifest `48f07e92…`、image/Kit identity generation `18` 和
  verification config digest `014591ba…`；本次冻结的 OpenCode Adapter digest 为 `cd9d167a…`，Pi 为
  `9c29bad8…`。
- **真实 Task：** Task 20、23–28、30、32、35–38、41–43 均已终态且 container_id 为空；Task 20/28 为
  cancelled，其余列出的 canary 为 failed。Tasks 23–25、30、32、35–38、41–43 的 provider terminal failure
  为月度 `rate_limited`；Pi Tasks 26–27 暴露旧 close/ACK 收敛问题，Task 38 验证了最新独立 outcome
  路径下的自动 close，Task 41–43 验证了当前 Adapter taxonomy 修复后的真实执行和清理。新增 Task 44、46–48、52、53
  均已 completed 且 container_id 为空：Task 44/48 为 OpenCode freeform/execute，Task 46/47 为 Pi fresh/continue，
  Task 52 为 OpenCode execute/fresh，Task 53 为 OpenCode execute/continue；均有 commit/MR。Task 46/47 还分别产生
  usage `272/250`、`223/194`，Task 52/53 分别产生 usage `117/170`、`125/172` 与连续 V2 archive。当前代码已加上
  30 秒 control exec/lookup 边界，且终止路径会移除容器、释放 Issue execution lock。
- **Provider gate：** 远端只读元数据确认现有 5 个 Provider 覆盖三种协议；Provider 7 `openrouter-free` 为
  active 的 `openai_responses` 调试入口。用户已明确授权将测试项目 16 的最小 canary 上下文发送到该
  Provider，本轮 Task 44/46/47/52/53 的真实成功结果已完成脱敏对账；其它 Provider 仍按各自额度与授权单独验收。
- **Bundle 对账：** Task 20、23、24/25、26、27/28、30、32、35、36、37、38、41/42、43 分别绑定 Runtime
  Bundle 58、59、60、61、62、63、64、65、66、67、68、69、70；新增 Task 44/48 绑定 Bundle 71，Task 46/47
  绑定 Bundle 72，Task 52/53 绑定 Bundle 74。所有这些 Bundle 的 contract 为 `codify.worker.harness/v2`、
  orchestration 为 `1.0.0`。
- **当前源码验证：** Backend 基线提交 `65395609f70c` 的全量 unit 为 `3156 passed, 4 skipped, 96 subtests`
  且无 warning；其中控制面基线 `eea817f5` 为 `3155 passed, 4 skipped, 96 subtests`，运行时基线
  `6b4f1056` 为 `3150 passed, 4 skipped, 96 subtests`，其后
  `4dca29d6` 对齐契约文档并补充测试，`25ee198f` 修复 OpenCode quota reason taxonomy，`eea817f5`
  补充协议化 Worker 启动摘要，`65395609f70c` 补充 Task runtime-summary 的冻结协议诊断；本次受影响 backend
  regression 为 `45 passed`，frontend 变化面为 `122 passed`；`d0e2a07b` 修复 packaged Runtime Bundle manifest
  路径，harness catalog regression 为 `16 passed`；此前 OpenCode/event/result focused regression
  为 `56 passed`（其中 OpenCode suite `37 passed`），本轮 OpenCode usage/event/result suite 为 `39 passed`，diagnostics 为 `3 passed`；此前 command-pump/control-client/Pi owner `46 passed`、frontend
  `94ac94fc` 后 frontend 全量 `1675 passed`、mock E2E `378 passed`，`npm run build`、Ruff、`py_compile` 与
  `git diff --check` 均通过；
  本次针对 Task 20 队列上下文的 backend issue-order/task-response/catalog 回归为 `56 passed`，frontend
  `TaskView.spec.ts` 为 `112 passed`（包含标签页恢复即时刷新回归），任务工作台/共享轮询变化面为 `300 passed`；
  Scheduler/runtime-config focused regression 为 `140 passed`。本轮 secret scan 为
  `passed/findings=0`；部署后 Scheduler 只在启动时输出一次既有配置告警（上述三个 unsupported key 与
  `oidc_client_secret`），90 秒观察窗口内未重复；远端活动 Task 查询为空。4 个需要 root 安装 Worker Kit
  的 skip 已在 N1 目标 Host 用例中重跑，不再作为当前 N1 阻塞。

## 4. L5 Acceptance

本节是未来 `v2_only` hard cut 的既定门槛，不是当前 N1–N4 的工作清单。N4 结束后必须先做一次是否继续
hard cut 的显式决策，不能因为 dual-canary canary 通过就自动进入本节。

- [ ] 冻结不少于 20 个内部代表性 Task，覆盖 plan、execute、freeform、修复测试、无改动、Session、
  失败和取消；记录可比模型、输入、成功标准和统计方法。
- [ ] Pi 与当前较优兼容 Harness 做同任务对比：成功率下降不超过 10 个百分点；中位耗时和 Token
  不得同时恶化超过 25%。
- [ ] Pi 完成 390×844、768px 和桌面浏览器验证，包括命令输入安全区、键盘遮挡、触摸面积、长文本、
  状态换行和恢复后的 command history。
- [ ] Pi、OpenCode、Claude、Codex 的 Contract/Event/Result Conformance 和真实 Worker Host canary
  全部通过；Pi/OpenCode 的三种协议必须分别使用真实 Endpoint/Task 验证，不得用代理把一种协议转换为
  另一种后冒充通过；所有适用的 Linux、PostgreSQL、AF_UNIX、scheduler skip 均在可用环境重跑。
- [ ] 完成发布凭据轮换、secret scan、release note、旧 Kit 退役记录和证据审阅；任一首发 Harness
  仍有 P0/P1 时停止推进。

## 5. L6 Hard cut

只有 L1–L5 全部通过后，才可在独立维护窗口执行：

- [ ] 暂停创建和调度，排空或终止在途任务并备份数据库。
- [ ] 将遗留 `PENDING/QUEUED` V1 Task 置为 `CANCELLED`；停止并清理恢复中的 V1 container，
  将其 Task 收敛为 `FAILED`，不转换历史 Snapshot。
- [ ] 确认 V1 Task/attempt/archive 只读，V1 writer、execute、retry、resume/continue 均明确拒绝。
- [ ] 仅启用已完成 V2 verify-runtime 的 Profile，把新建 Profile 默认值切为 Pi，再原子切换
  `HARNESS_EXECUTION_MODE=v2_only`。
- [ ] 执行切后 smoke、Scheduler recovery、command plane、统计与历史只读检查；失败时保持维护模式，
  只允许 roll-forward 修复，不启动 V1 应用回滚。

## 6. 执行顺序与停止条件

当前允许的推进顺序是：

1. 保持已完成的 S1–S9/L1–L2；相关源码变化时只重跑受影响集合；
2. N1 冻结并官方安装一个 `linux/amd64` `pi+opencode` candidate；
3. N2 部署同 commit 控制面并完成 DB-bound composition；
4. N3 完成最小真实协议与生命周期 canary；
5. N4 评审后停在 `dual_canary`。

只有 N4 后明确决定推进 hard cut，才进入 L5，再在独立维护窗口执行 L6；不把未来 hard-cut 矩阵前置到
当前 candidate。

出现以下任一情况立即停止当前层级：

- present path/bytes 与 inventory 不一致，或 Kit identity 未覆盖实际执行 bytes；
- image、Kit、Bundle、Adapter、Profile generation、Host/daemon 或 Task attempt 来自不同冻结组合；
- 使用 mutable tag、placeholder digest、未核验 Kit、`host_mount` 或旧 image CLI lock 冒充 release evidence；
- V1 dual-canary、command pump 隔离、PG/AF_UNIX/concurrency 存在失败或必要 skip 未重跑；
- Pi/OpenCode 任一协议分支缺少确定性映射、发生协议推断/回退，或缺少真实 Endpoint Conformance；
- 任一 enabled 且 present/available Harness 缺少真实 Task/MR/terminal/usage/archive 对账；
- 当前 candidate 的 Provider/GitLab 授权、凭据轮换或 secret scan 未完成；
- 任一当前 enabled Harness 存在 P0/P1。

单个 present CLI 的 functionality 失败只将该 Harness 标为 unavailable，不得清空其他 Harness；
但首轮 hard-cut candidate 因此缺少四 Harness 任一项时，不得进入 L5/L6。数据库只 roll-forward，
不修改历史 Snapshot、Issue、attempt、archive 或证据。
