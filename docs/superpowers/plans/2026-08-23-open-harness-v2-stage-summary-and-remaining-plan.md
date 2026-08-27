# Open-Harness V2 当前遗留项与验收计划

**更新：** 2026-08-27

**源码审计基线（S5 增量前）：** `79bd530e`（本轮 S5 实现与证据见下文）

**文档复核基线：** `96eb2462`（本次更新前的本地 `HEAD`）

**状态：** Internal Preview；Kit-owned 基础改造、S5–S8 源码 correction 和远端 `linux/amd64` Kit
smoke 已落地，但 L2 仍为红灯：S1 尚未完成完整真实构建矩阵，S9 完整证据仍未闭环。补齐
S1/S9、重建制品并补齐 L3–L6 证据前，保持 `dual_canary`，
不切 Pi 默认，不启用 `v2_only`。

本文只维护当前剩余工作和退出条件。已完成且已验收的工作不再保留为待办流水账；架构约束以
[Open-Harness V2 架构方案](../../architecture/open-harness-v2.md) 为准，发布操作以
[dual-canary 与生产验收 Runbook](../../runbooks/multi-harness-rollout.md) 为准。

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
- 既有全量 L1/L2 回归和 Linux 原子安装原语验证可作为基础证据，但不能覆盖下文新发现的分支，
  也不能替代 immutable release、真实 Host、真实 Task、canary 或 hard cut 证据。

`host_mount` 只保留为显式、逐 Harness 授权的 break-glass 来源。它可以验证执行链，不得替代
Kit-owned present CLI 的 release evidence。

协议现状必须单独标记：源码 correction 已让 Pi/OpenCode 的 Runtime manifest、Backend upper bound、
Bundle-authoritative catalog、Task snapshot、两个 Adapter 和前端筛选一致声明并处理
`anthropic_messages`、`openai_responses`、`openai_chat_completions`；Claude 仍只允许 Anthropic，Codex
仍只允许 Responses。该状态只表示源码退出条件，不等于三协议真实 Endpoint/Task、完整 Kit 矩阵或发布
验收已经完成。

## 2. Source correction：当前必须修复

以下项目全部完成前，L2 不得重新标绿，也不得生成 release candidate。

- [ ] **S1 / P1 — 完成 present CLI Kit 路径的真实构建矩阵验收。**
  `4c223d1c` 已修复源码路径：生成的 manifest path 现在包含 Harness key，Dockerfile 也按同一
  `harness/<key>/<relative-path>` 布局复制和检查；`b54f3267` 又修复了跨主机导出时的 Linux
  大小写路径、PAX 长路径和 `/nix/store` 逻辑链接校验。当前已在远端 Docker 的 `linux/amd64` 上
  真实构建并通过内容/归档校验：四个单项和默认 `pi+opencode`；但显式子集、四项 Kit、Linux Host
  安装/真实 bind-mount 以及 arm64 尚未形成证据。四项 Kit 已发起构建，但因远端磁盘不足失败，
  不能计入成功矩阵。
  退出条件：使用生成器真实构建并安装默认 `pi+opencode`、各单项、显式子集和四项 present Kit；
  manifest path、archive path、容器挂载 path 与实际可执行文件完全一致，并记录精确 source commit、
  Kit identity 和 Host 证据。

- [x] **S2 / P1 — 让 Kit identity 覆盖整 Kit 内容。**
  `1905abda` 已将 canonical content inventory/digest 接入 manifest、安装回执、readiness、Profile
  snapshot 和 Runtime Bundle；`b54f3267` 保证导出的 archive 不因 Host 文件系统而改变该 identity，并
  让 archive/安装前后的 content verifier 对同一组 bytes fail closed。整 Kit tamper、链接链、PAX
  长路径和大小写路径回归已由聚焦测试覆盖；当前只剩 S1 的真实发布矩阵与 L3 Host 证据，不再把 S2
  记为源码缺口。

- [x] **S3 / P1 — 修复 dual-canary 的 V1 lifecycle。**
  `worker_task_lifecycle.create_execute_container()` 已在进入 V1/V2 公共路径前初始化
  `frozen_snapshot`；V1 frozen Task 的实际容器创建回归通过，V2 identity/CLI 注入既有回归仍通过。
  当前工作区证据已满足源码退出条件；尚未形成新的部署或 release composition 证据。

- [x] **S4 / P1 — command pump 必须按 Task 隔离 attempt。**
  `run_pump_cycle()` 现在必须接收 `task_id`；claim、starting promotion、队列头、dispatch/close frame
  和 transport guard 全链绑定同一 Task，跨 Task attempt 不再先领取后以 `wrong_attempt` 收尾。退出条件
  已由 PostgreSQL 回归覆盖：两个以上并发 Task 的 queued、starting、closing、dispatching recovery，
  以及既有严格队列顺序、lease/recovery 语义均通过；当前工作区修复尚未形成新的部署或 release
  composition 证据。

- [x] **S5 / P2 — 补齐 availability catalog。**
  `/harness-catalog` 与 Task frozen catalog 现在按每个 Harness 分别投影 `enabled`、`availability`、
  `selectable` 和稳定、脱敏的 reason；current catalog 使用所选 Worker Profile 的逐 Harness readiness，
  frozen catalog 以不可变 Snapshot/Bundle 为权威，V1/V2 readiness scope 不交叉污染。前端新建 Task
  在 catalog 未就绪或所选 Harness 不可用时阻止提交，历史 Task 即使 frozen runtime 当前不可用仍可
  修改非运行时字段；不得泄露 host path 或敏感 evidence。源码和 focused/full frontend 证据见下文，
  真实 Kit/Host 证据仍归 S1/L3–L4。

- [x] **S6 / P1 — 扩展中央 Harness × Model Protocol 合同。**
  扩展编译期 `HARNESS_PROTOCOL_MATRIX` upper bound，并让 Runtime manifest、catalog、Task
  create/retry/resume、Profile verify、Worker 启动和前端 Provider 筛选一致声明：Pi/OpenCode 支持
  三种协议，Claude 只支持 `anthropic_messages`，Codex 只支持 `openai_responses`。Runtime Bundle
  manifest 是唯一能力源；
  Backend/Frontend 不得另复制会漂移的业务矩阵。AI Provider 新建/编辑 UI 已重新开放合法的
  `openai_chat_completions` Endpoint。`90a2593d` 完成源码退出条件；历史 Bundle 的协议子集、真实
  Endpoint Conformance 和完整 L2 重跑仍归 S9/L4。

- [x] **S7 / P1 — 实现 Pi 三协议 Adapter。**
  按冻结 Snapshot 将 `anthropic_messages`、`openai_responses`、`openai_chat_completions` 分别映射为 Pi
  `anthropic-messages`、`openai-responses`、`openai-completions`；生成 Task-private Provider 配置，
  使用协议对应的 model/Base URL/credential，禁止读取已有用户配置、按 URL 猜测、跨协议回退或转换。
  三条路径都保留 RPC Session、steering/follow-up、usage 和 terminal 语义；`90a2593d` 的源码和聚焦
  测试满足本项源码退出条件，真实三协议 Task 仍待 R6/R7。

- [x] **S8 / P1 — 实现 OpenCode 三协议 Adapter。**
  Task-private `opencode.json` 分别使用 `@ai-sdk/anthropic`、`@ai-sdk/openai`、
  `@ai-sdk/openai-compatible`；credential 仅通过 Task-private 环境变量引用，不内联到配置/日志/归档。
  Bridge 创建和恢复 Session 时固定 Provider/model pair，三条路径都要归一化事件、tool/reasoning、usage、
  Abort、settled 和 terminal；禁止加载用户级 auth/Provider 或仓库配置覆盖 Snapshot。源码退出条件和
  固定 OpenCode 1.18.19 的真实隔离 smoke 已在本轮完成；真实三协议 Task、完整 Conformance 和 Host
  证据仍待 R6/R7。

- [ ] **S9 — 补齐测试并重新建立 L2 证据。**
  至少新增：present payload 生成器/真实 build、整 Kit tamper、V1 lifecycle、并发 task-scoped pump、
  current/frozen catalog availability，以及 Pi/OpenCode 三协议的 manifest/Backend/Adapter/Frontend 矩阵测试；
  每条协议覆盖 config 生成、credential 不落盘、tool call、reasoning、usage、取消、错误和禁止回退。
  本轮已新增协议矩阵、冻结 Endpoint、Provider drift、Task-private OpenCode config/Skill discovery、
  current/frozen catalog 和 fail-closed 前端测试；scheduler gate 的未 await `AsyncMock` warning 已由
  `79bd530e` 修复。仍需在可用环境完成全量 backend unit、mock E2E、真实 PostgreSQL 并发/migration、
  frontend type-check/build/vitest 的统一重跑，并记录精确命令、结果和 source commit。

## 3. Release、L3 与 L4

证据层级固定如下，不能跨层替代：

| 层级 | 证明内容 | 当前状态 |
| --- | --- | --- |
| L1 | 架构、schema、Runbook 与安全边界一致 | 目标合同已修订；实现和证据不得冒充完成 |
| L2 | 源码、单测、集成测试和并发合同 | 未通过；S5 源码与 focused evidence 已完成，但 S1 仍待完整真实构建矩阵，S9 仍待全量/集成/真实 PostgreSQL 证据闭环 |
| L3 | 同一不可变 image + Kit + Bundle 的构建、安装、DB 绑定与 digest 对账 | 未完成；已有远端 `linux/amd64` 单项与 `pi+opencode` Kit/archive smoke，尚未完成显式子集、四项 Kit、Host 安装和 DB-bound composition |
| L4 | 真实 Linux Host、remote Docker、Provider、仓库和真实 Task/MR | 部分完成；仅覆盖 Pi×Anthropic 与 Codex×Responses 的 dev Task，非完整发布矩阵 |
| L5 | 四 Harness canary、Pi 20-task 与质量/性能验收 | 未完成 |
| L6 | 维护窗口 hard cut、Pi 默认和 `v2_only` | 未执行 |

L2 重新通过后，按顺序完成：

- [ ] **R1 — 生成不可变 release composition。** 固定 Project Runtime Image digest、Kit version/platform、
  构建选择集、四 key inventory、present CLI 精确版本/SHA、Kit content identity、Adapter digest、
  Runtime Bundle digest、Profile generation 和 Harness × Model Protocol matrix。迭代 Kit 可携带 0–4 个
  payload，但首轮 hard-cut candidate 必须让 Pi、OpenCode、Claude、Codex 全部 present/available；
  Pi/OpenCode 的 Bundle 必须声明三种协议，`host_mount` 不计入该证明。
- [ ] **R2 — 在目标 Linux Host 安装和验证。** 验证 root ownership、权限、atomic no-replace、重装冲突、
  崩溃恢复、platform、整 Kit integrity、逐 present Harness functionality gate 和实际挂载路径。
- [ ] **R3 — 执行真实部署 migration。** 在维护窗口由唯一 migration owner 从实际 current revision
  升级到精确 `077_v2_worker_kit_identity`；长驻 Backend/Scheduler 使用 `AUTO_MIGRATE=false`，
  不使用漂移的 `head`。
- [ ] **R4 — 完成 DB-bound Profile/Bundle 对账。** 每个 enabled 且 present/available Harness 都要在目标
  Host verify；Pi/OpenCode 还要逐一绑定三种协议。每个组合冻结同一
  `image_identity + kit_identity + bundle_digest + model_protocol` 并完成 L3 Bundle export；absent Harness
  只记录稳定 `harness_cli_unavailable`，不得伪造 export。
- [ ] **R5 — 补齐外部授权与安全准备。** 提供真实 Anthropic Messages、OpenAI Responses、OpenAI-compatible
  Chat Completions Endpoint，以及 GitLab smart-HTTP clone/push/MR 链路；修复 CA/URL 问题，轮换曾用于
  调试的凭据并执行 secret scan；证据只保存脱敏路径和摘要。
- [ ] **R6 — 完成受支持 Harness × Protocol 的真实 Task 矩阵。** 至少覆盖 Pi×三协议、OpenCode×三协议、
  Claude×Anthropic、Codex×Responses；每个组合覆盖 fresh、retry、resume/continue、failure、cancel、
  timeout、scheduler recovery、Session、Skills、usage、archive、Git commit/push/MR 和 terminal 对账，
  并绑定 Host/daemon、Profile generation、attempt、Endpoint fingerprint 和全部制品 identity。
- [ ] **R7 — 完成 Harness 专项能力。** OpenCode 覆盖 Server、Session、Agent、Command、Abort、事件和
  usage，并证明三种协议下 settled/Abort 一致；Pi 在三种协议下覆盖原生 ACK、严格顺序、steering、
  follow-up、close、`outcome_unknown` 不重放和 scheduler 恢复；Claude/Codex 证明现有核心能力无回退。

## 3.5 本轮 dev 环境已完成证据（2026-08-26—2026-08-27）

> 以下为 dev 环境（192.168.50.129）真实执行证据，供 R1–R7 复核；未替代目标 Host 与发布窗口动作。

### 再次复核结果

- **部署门禁与 schema：** dev Backend/Scheduler 当前均为 `HARNESS_EXECUTION_MODE=dual_canary`、
  `AUTO_MIGRATE=false`；数据库 revision 为 `077_v2_worker_kit_identity`。三个执行关键文件
  `task_harness_commands.py`、`worker_command_pump.py`、`worker_task_lifecycle.py` 的部署 SHA-256 与
  `5dc3a312` checkout 完全一致，因此下述源码缺口也存在于当前 dev 部署，不只是本地静态推断。
- **Kit/Readiness：** Kit `0.5.0` 为 ready，但 inventory 只有 Pi `present`，OpenCode、Claude、Codex
  均为 `absent`；Kit `0.4.0` 为 0 present。它们都不是首轮四 Harness hard-cut candidate。
- **真实 Task 覆盖：** 当前 dev DB 中 Codex 为 1 completed / 3 failed，Pi 为 5 completed / 8 failed /
  1 cancelled；没有 OpenCode 或 Claude 真实 Task。完成任务只覆盖 Pi×`anthropic_messages` 和
  Codex×`openai_responses`，command 表只有 1 条 `delivered`，不能外推为三协议或四 Harness 验收。
- **当前聚焦验证：** Backend 相关聚焦集为 224 passed / 15 PostgreSQL tests skipped / 1 warning；
  warning 仍是 scheduler gate 路径未 await `AsyncMock`。Frontend `AIProvidersPanel`、`TaskFormDrawer`、
  `TaskView` 共 227 tests passed，`vue-tsc --noEmit` 通过。聚焦 Ruff 因
  `task_harness_commands.py` import 顺序失败。PG skip、warning 和 Ruff failure 都必须在 S9 清零，
  历史绿灯不能替代本轮重跑。
- **再次确认的源码缺口（S5 增量前）：** S1 完整真实构建/Host 证据和 S9 完整重跑仍未闭环；
  S2–S4、S6–S8 已在本轮源码 correction 中完成并通过聚焦证据。本轮未把任何一项误标为 release
  完成；S5 的后续增量结果见下文。
- **本轮 S3/S4 工作区证据：** `backend/.venv/bin/python -m pytest
  backend/tests/unit/test_worker_command_pump.py -q` 在 PostgreSQL 测试库中 `20 passed`，包含同一
  attempt 锁住 seq1 时不得跳过队头派发 seq2 的回归；V1 lifecycle 与既有 V2 runtime 聚焦集
  `28 passed`，Ruff 与 `git diff --check` 通过。该证据只证明当前源码 correction，不代表 dev
  部署 SHA、Kit/Bundle 重建或 L3–L6 release 验收。

- **R5（外部授权，dev 完成）：** GitLab admin/bot token 与 opencode.ai Provider key 已录入 dev 后端 DB `system_config`（加密；原始值仅存于 gitignored `deploy/dev-env-info.md`）；`/api/config/gitlab/test` 通过（18.5.5-ee，ai-bot）；bot clone/push/MR 实测全通；Provider 三端点实测（minimax-m2.7 messages / gpt-5.6-luna responses / mimo-v2.5 chat / deepseek-v4-flash messages）；secret scan 无泄漏。
- **R6（codex，host_mount 0.146.0）：** Task 4 COMPLETED，commit `188331f29c`，MR !1，usage 76237/1252，runtime archive + 25 canonical events；失败路径（Task 2/3）正常收尾。codex 端点语义实测：`base_url` 被 codex 追加 `/responses`，provider 需配 `https://opencode.ai/zen/go/v1`。
- **R6/R7（Pi，Kit 0.5.0 present payload 0.84.2，digest `6c68c5f5f6bf…`）：** 真实 Task 13/16/17/18/19 COMPLETED（deepseek-v4-flash），MR !2/!4/!6 等；覆盖创建（fresh+skill）、continue 追加（会话恢复 `<UUID:377a0db8…>`）、运行中 follow_up **delivered** 且内容落地（commit `4a2023d6`）、steer gate 关闭时正确拒绝、取消（Task 15）、cancel→retry 成功（Task 16）、retry 冻结快照语义（Task 14 复用旧 bundle 同因失败）、Skills（codify-marker 精确落地）、工具事件（`tool.started/completed` → `tool_call` 日志：write/read/bash 含路径/脱敏命令/output payload）；事件流全类型覆盖（0 unknown_raw_event）。
- **源码修复链（commit `4c223d1c`/`e4361d7a`/`c5661619`）：** ① Kit 构建：目录 payload（pi 完整资源）、glibc loader 回退（Alpine 构建阶段）、smoke ABI shim、manifest path 统一；这关闭了 S1 的已知源码缺陷，但未完成 S1 真实构建矩阵退出条件；② `pi_events.py`：lenient JSON 修复 + agent_end 定向提取（pi 0.84.2 未转义引号破坏整行）；③ `task_harness_commands.py`：bundle 能力判定从 archive 解 harness manifest + undefer，修复 steer/follow_up 此前被 `unsupported_harness` 拒绝的问题；此前它不关闭 S4 的跨 Task claim 缺口，该缺口已由本轮 task-scoped pump 修复并以 PostgreSQL 并发测试验证；④ `repository-helpers.sh`：work 分支远端不存在时 ahead-of-base 回退 origin/base（Pi 自 commit/push 后误报 "No changes made"）；⑤ 当时的单测证据：`test_pi_harness_adapter.py` 34、`test_task_harness_commands.py` 18、`test_worker_kit.py` 54、全量 unit 3065+1 passed。
- **S1/S2 当前工作区证据（commit `b54f3267`）：** `deploy/worker-kit/export-archive.py` 直接把
  Docker Kit tar stream 写入最终 archive，保留 Linux case-distinct paths 和 PAX path/linkpath；
  内容 verifier 与 offline archive validator 对 `/nix/store`、嵌套 symlink、循环和 hardlink 均做
  逻辑解析。远端 Docker `linux/amd64` 真实构建并校验的 Kit identity 为：Pi `4448ad3d50b9…`、
  OpenCode `8cdb0b4860ec…`、Claude `4d612d783e49…`、默认 `pi+opencode` `4a0b9981524c…`；四个
  archive 均通过 content verifier 和 archive validator，聚焦测试为 `83 passed, 4 skipped`，Ruff、
  `bash -n` 与 `git diff --check` 通过。Codex 单项继续构建时远端 Docker 因 `No space left on device`
  停止；清理广泛 BuildKit cache 未获授权，因此未伪造 Codex/子集/四项或 Host 安装证据。
- **已知边界：** S1 仍缺完整选择矩阵、Linux Host 安装及真实 Kit + `nix/store` bind-mount；S5
  availability catalog 和 Pi/OpenCode 三协议真实 Endpoint/Task 仍未完成；Pi `--exclude-tools` 在 rpc
  模式触发 pi 0.84.2 自身 bug（无输出退出），未采用工具禁用，依赖 delivery 修复。

### 本轮 S6–S8 源码与远端 Kit 证据（2026-08-27）

- **源码 correction（commit `90a2593d`）：** Bundle manifest 成为已绑定 Task 的协议能力权威；Pi/OpenCode
  三协议映射、Claude/Codex 限制、Provider UI、current/frozen catalog、Task snapshot endpoint
  immutability、credential 不后取和 OpenCode Task-private config/Skill discovery 均已接入。两轮独立
  subagent review 的最终结论均为 **P0=0、P1=0**；第二轮仅保留 P2（真实 OpenAI protocol Task smoke 和
  malformed `max_turns` 单测建议）。
- **远端 Kit smoke：** 远端 Docker context `remote`（`192.168.50.129`，`linux/amd64`）用源码构建
  `WORKER_KIT_VERSION=0.6.1`、`WORKER_KIT_CLI_SELECTION=pi,opencode`，归档
  `/private/tmp/open-harness-v2-s6-kits/codify-worker-kit-0.6.1-linux-amd64-bdc3408c86f6.tar.gz`，
  archive SHA-256 `7096c78d6f75d7dc934e94daf2783d62c5b775ae77bc2fd1bfd18a6d697a54f4`，Kit manifest
  identity `bdc3408c86f603401a42191318311107f45c59eb81a8ec411be9c6502ecb5d6e`；构建 image digest
  `sha256:772e331f68204ddf434d8aefcfa9929e4a52bdcee0be629e29e0a2b888348675`。`export.sh`、archive content
  verifier 和 runtime smoke 均通过，证明固定 Pi 0.84.2/OpenCode 1.18.19 的当前 `pi+opencode` Kit
  payload；不证明显式子集、四项 Kit、Host 安装或 arm64。
- **OpenCode boundary probe：** 固定 1.18.19 对恶意 project `opencode.json`、`.opencode/plugins`、
  project/global Claude-compatible Skills 的 probe 在 `OPENCODE_DISABLE_PROJECT_CONFIG=true`、
  `OPENCODE_DISABLE_EXTERNAL_SKILLS=1`、`OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1` 和 `--pure` 下未加载
  attacker provider/permission/plugin；Task-managed Skill 从 `OPENCODE_CONFIG_DIR/skills/<name>/SKILL.md`
  被 `debug skill --pure` 发现。该 probe 是隔离证据，不替代真实模型调用/Task Conformance。
- **本轮验证：** Backend 协议/Bundle/Adapter/Runtime 聚焦集 `392 passed`，CI auto-repair
  `20 passed`，Frontend `120 passed`，`npm run build`、Ruff、`bash -n` 和 `git diff --check` 通过。
  全量 unit 曾因 pytest 临时目录累计约 44GB 导致 12 个 setup errors，并出现 3 个受磁盘影响的失败；
  清理临时目录后 3 个失败用例分别重跑均通过，因此全量 unit 的清洁重跑仍归 S9，不能写成 L2 green。

### 本轮 S1 单项构建补充（2026-08-27）

- **Codex 单项：** 同一远端 Docker context 和源码 commit `90a2593d` 下，以
  `WORKER_KIT_VERSION=0.6.1`、`WORKER_KIT_PLATFORM=linux/amd64`、
  `WORKER_KIT_CLI_SELECTION=codex` 构建。归档
  `/private/tmp/open-harness-v2-s6-kits/codify-worker-kit-0.6.1-linux-amd64-22d5f3dbe84e.tar.gz`；
  archive SHA-256 `e54e33b62b38453464d078a6c85e264aaf51a62cf2da9fef8c88aa55da72277b`，manifest
  identity `22d5f3dbe84e265431167978e66a33c28a00333f3f95f8f36b767f48d7950e58`，content inventory
  `7ea5b9d3eb4302dc78e111b0d5f18ac1fc1d2a343b4a855df1a497a18610ff90`，构建 image digest
  `sha256:460d3587924b81549c47bf6a07348c0a5e94b9dd1e5849b58ee12ffe8fa82716`。archive verifier、
  launcher/runtime smoke 均通过；manifest 的 `codex` 路径为
  `/opt/codify-kit/harness/codex/bin/codex`，版本 `0.146.0`、payload SHA-256
  `2e863156ed35ecc5253b1e2f907a9143077b9f7cb51942070c61996471ff6e04`、大小 `311001136`。
- **Claude 单项：** 使用同一版本/平台和 `WORKER_KIT_CLI_SELECTION=claude` 构建。归档
  `/private/tmp/open-harness-v2-s6-kits/codify-worker-kit-0.6.1-linux-amd64-f2a455b927a6.tar.gz`；
  archive SHA-256 `b23f4faa521284ba80abfcf1956240e4aa09f8fb901715b5ac683b62ad15c72e`，manifest
  identity `f2a455b927a6596ae5be111b1dc9a833d2e729b9748865ec76a2e4748c07fed6`，content inventory
  `2f9ea9b08cdffda2a8cc4104124012c37acd6b57627a1d96d189a7c747e2e77e`，构建 image digest
  `sha256:483cec6ecd72aed1d0f0a462b60a177e76793863bf36216453089c5f90d8e50c`。archive verifier、
  launcher/runtime smoke 均通过；payload 路径为 `/opt/codify-kit/harness/claude/claude`，runtime
  smoke 输出 `2.1.153`、payload SHA-256 `214f603f31942162dac9a65f18d43b3ac646ae215240fad481c4aad6c60f2e38`、
  大小 `239896272`。该归档的 manifest version 字段曾暴露后缀解析错误，已在当前工作区修正为
  提取首个语义版本号；修复后的完整 Kit 重建仍待远端空间恢复。
- **四项 Kit 尝试：** `WORKER_KIT_CLI_SELECTION=pi,opencode,claude,codex` 已完成完整 payload
  staging，但在 Nix npm dependency 阶段因远端根分区耗尽失败，确切错误为
  `codegraph-linux-arm64: No space left on device`。该次没有 archive、manifest 或 smoke 证据，
  因此不计入 S1；显式子集、成功四项 Kit、Linux Host 安装/真实 bind-mount 和 arm64 仍开放。

### 本轮 S5 availability catalog 补充（2026-08-27）

- **Backend projection：** current catalog 根据 Worker Profile 的 enabled Harness 集合和逐 Harness
  readiness scope 投影 `enabled`、`availability`、`selectable`、`disabled_reason`、
  `availability_reason` 与稳定 `reason_code`；frozen task catalog 只使用 immutable Snapshot/Bundle
  绑定的 Harness，不回退到可编辑 Profile。`host_mount` 仅作为显式 break-glass 来源，响应不包含
  executable path、Kit path 或 readiness failure detail；profile/task project access 仍在加载 Bundle
  前校验。
- **Frontend behavior：** 新建 Task 选择器显示 disabled/unavailable/not-verified 状态和脱敏原因，
  catalog 未就绪或所选 Harness 不可用时阻止提交；历史 Task 的 frozen Harness 即使当前不可用仍可
  保存 prompt 等非运行时字段。Task/Issue 异步载入后按 task/profile identity 刷新 catalog，并用
  request generation 防止旧响应覆盖新状态。
- **验证：** `backend/.venv/bin/python -m pytest backend/tests/unit/test_harness_catalog_api.py -q`
  为 `12 passed`；TaskFormDrawer、TaskView、IssueView 聚焦集为 `329 passed`；
  `frontend/npx vitest run` 为 `79 files passed / 1666 tests passed`；`frontend/npm run build`、
  targeted Ruff 和 `git diff --check` 均通过。三轮独立 subagent review 最终均无 P0/P1（本轮最终
  `P0=0, P1=0, P2=0`）。
- **证据边界：** 全量 backend unit 尝试结果为 `3036 passed, 72 skipped, 3 failed, 25 errors`；
  失败/错误由远端 PostgreSQL 与端口权限、以及 pytest 临时目录磁盘耗尽造成，不能写成全量 L2
  green。out-of-order deferred response 的专门前端测试、ASGI 级认证/访问控制测试和真实
  Docker/Kit/Host 验证仍归 S9/S1/L3–L4。

## 4. L5 Acceptance

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

唯一允许的推进顺序是：

1. S1–S9 清零并重新建立 L1/L2；
2. R1–R5 生成、安装并绑定同一个 immutable release composition；
3. R6–R7 完成 L4 真实 Task 与专项能力；
4. 完成 L5 acceptance；
5. 独立维护窗口执行 L6 hard cut。

出现以下任一情况立即停止当前层级：

- present path/bytes 与 inventory 不一致，或 Kit identity 未覆盖实际执行 bytes；
- image、Kit、Bundle、Adapter、Profile generation、Host/daemon 或 Task attempt 来自不同冻结组合；
- 使用 mutable tag、placeholder digest、未核验 Kit、`host_mount` 或旧 image CLI lock 冒充 release evidence；
- V1 dual-canary、command pump 隔离、PG/AF_UNIX/concurrency 存在失败或必要 skip 未重跑；
- Pi/OpenCode 任一协议分支缺少确定性映射、发生协议推断/回退，或缺少真实 Endpoint Conformance；
- 任一 enabled 且 present/available Harness 缺少真实 Task/MR/terminal/usage/archive 对账；
- Provider/GitLab 授权、凭据轮换、secret scan 或唯一 migration owner 未完成；
- 任一首发 Harness 存在 P0/P1。

单个 present CLI 的 functionality 失败只将该 Harness 标为 unavailable，不得清空其他 Harness；
但首轮 hard-cut candidate 因此缺少四 Harness 任一项时，不得进入 L5/L6。数据库只 roll-forward，
不修改历史 Snapshot、Issue、attempt、archive 或证据。
