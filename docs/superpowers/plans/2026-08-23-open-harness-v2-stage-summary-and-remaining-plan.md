# Open-Harness V2 当前遗留项与验收计划

**更新：** 2026-08-25

**实现审计基线：** `74a1493d`

**状态：** Internal Preview；Kit-owned 基础改造已落地，但 source correction 因已确认的 P1
重新打开。修复、重建制品并补齐 L3–L6 证据前，保持 `dual_canary`，不切 Pi 默认，
不启用 `v2_only`。

本文只维护当前剩余工作和退出条件。已完成且已验收的工作不再保留为待办流水账；架构约束以
[Open-Harness V2 架构方案](../../architecture/open-harness-v2.md) 为准，发布操作以
[dual-canary 与生产验收 Runbook](../../runbooks/multi-harness-rollout.md) 为准。

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
  `harness_cli_unavailable` 基础门禁；Worker Settings 已展示逐 Harness availability/reason。
- Compatibility baseline 差异已改为 advisory warning；present payload 完整性和 functionality
  gate 的主体逻辑已存在。
- 既有全量 L1/L2 回归和 Linux 原子安装原语验证可作为基础证据，但不能覆盖下文新发现的分支，
  也不能替代 immutable release、真实 Host、真实 Task、canary 或 hard cut 证据。

`host_mount` 只保留为显式、逐 Harness 授权的 break-glass 来源。它可以验证执行链，不得替代
Kit-owned present CLI 的 release evidence。

## 2. Source correction：当前必须修复

以下项目全部完成前，L2 不得重新标绿，也不得生成 release candidate。

- [ ] **S1 / P1 — 修复 present CLI 的 Kit 路径生成。**
  `deploy/worker-kit/verify-cli-payloads.sh` 生成的 manifest path 缺少 Harness key，
  `Dockerfile.worker-kit` 随后又重复拼接目录；当前带任意 present CLI 的构建无法通过最终路径检查。
  退出条件：使用生成器真实构建并安装默认 `pi+opencode`、单项、显式子集和四项 present Kit；
  manifest path、archive path、容器挂载 path 与实际可执行文件完全一致。

- [ ] **S2 / P1 — 让 Kit identity 覆盖整 Kit 内容。**
  当前 identity 只绑定 `manifest.json` SHA；launcher、entrypoint、Adapter/Bridge、编排脚本和 Nix
  closure 的 bytes 变化可能不改变 identity。退出条件：定义唯一 canonical content identity，覆盖
  archive/manifest 及所有执行相关 bytes；安装回执、readiness、Profile snapshot 和 Runtime Bundle
  使用同一 identity；任一文件篡改或混搭都 fail closed，并有测试证明。

- [ ] **S3 / P1 — 修复 dual-canary 的 V1 lifecycle。**
  `worker_task_lifecycle.create_execute_container()` 在 V2 分支内才赋值 `frozen_snapshot`，随后却在
  V1/V2 公共路径无条件读取。退出条件：真实执行 V1 frozen Task 的容器创建路径不再抛出
  `UnboundLocalError`，V1 dual-canary 与 V2 identity/CLI 注入分别有回归测试。

- [ ] **S4 / P1 — command pump 必须按 Task 隔离 attempt。**
  scheduler 为每个 Task 启动 task-scoped pump，但 `_claim_next_attempt()` 和
  `_promote_starting_attempt()` 当前从全局 attempt 集合领取；并发时可能领取其他 Task 的 command，
  再以 `wrong_attempt` 终结为 `outcome_unknown`。退出条件：claim、promote、lease、transport 全链使用
  同一 `task_id` 边界；两个以上并发 Pi Task 的 queued/starting/closing/recovery 测试证明无串领、
  无误终结且保持严格队列顺序。

- [ ] **S5 / P2 — 补齐 availability catalog。**
  Worker Settings 已展示 Kit inventory，但 `/harness-catalog` 与 Task frozen catalog 仍只投影 Runtime
  Bundle Adapter 能力。退出条件：新建 Task 选择器和历史 Task catalog 都能区分 enabled、disabled、
  present、unavailable，并显示稳定、脱敏的 reason；不得泄露 host path 或敏感 evidence。

- [ ] **S6 / P2 — 同步剩余合同表述。**
  修正架构摘要中“所有 Harness 随 Worker 镜像和 Runtime Bundle 发布”的旧描述，使其与 §11 的
  Kit-owned ownership 一致；继续禁止在 Git 文档中记录真实 Host 名称、内部地址、凭据、私有仓库
  URL 或敏感日志。

- [ ] **S7 — 补齐测试并重新建立 L2 证据。**
  至少新增：present payload 生成器/真实 build、整 Kit tamper、V1 lifecycle、并发 task-scoped pump、
  current/frozen catalog availability 测试；修复 scheduler gate 测试中的未 await `AsyncMock` warning。
  然后重跑 backend unit、mock E2E、真实 PostgreSQL 并发/migration、frontend type-check/build/vitest，
  记录精确命令、结果和 source commit。

## 3. Release、L3 与 L4

证据层级固定如下，不能跨层替代：

| 层级 | 证明内容 | 当前状态 |
| --- | --- | --- |
| L1 | 架构、schema、Runbook 与安全边界一致 | 部分完成；S6 待修 |
| L2 | 源码、单测、集成测试和并发合同 | 未通过；S1–S5 有已知缺口 |
| L3 | 同一不可变 image + Kit + Bundle 的构建、安装、DB 绑定与 digest 对账 | 未完成；现有 Kit 为 0 present |
| L4 | 真实 Linux Host、remote Docker、Provider、仓库和真实 Task/MR | 未完成；仅有 break-glass/失败路径局部证据 |
| L5 | 四 Harness canary、Pi 20-task 与质量/性能验收 | 未完成 |
| L6 | 维护窗口 hard cut、Pi 默认和 `v2_only` | 未执行 |

L2 重新通过后，按顺序完成：

- [ ] **R1 — 生成不可变 release composition。** 固定 Project Runtime Image digest、Kit version/platform、
  构建选择集、四 key inventory、present CLI 精确版本/SHA、Kit content identity、Adapter digest、
  Runtime Bundle digest 和 Profile generation。迭代 Kit 可携带 0–4 个 payload，但首轮 hard-cut
  candidate 必须让 Pi、OpenCode、Claude、Codex 全部 present/available；`host_mount` 不计入该证明。
- [ ] **R2 — 在目标 Linux Host 安装和验证。** 验证 root ownership、权限、atomic no-replace、重装冲突、
  崩溃恢复、platform、整 Kit integrity、逐 present Harness functionality gate 和实际挂载路径。
- [ ] **R3 — 执行真实部署 migration。** 在维护窗口由唯一 migration owner 从实际 current revision
  升级到精确 `077_v2_worker_kit_identity`；长驻 Backend/Scheduler 使用 `AUTO_MIGRATE=false`，
  不使用漂移的 `head`。
- [ ] **R4 — 完成 DB-bound Profile/Bundle 对账。** 每个 enabled 且 present/available Harness 都要在目标
  Host verify，冻结同一 `image_identity + kit_identity + bundle_digest`，完成 L3 Bundle export；
  absent Harness 只记录稳定 `harness_cli_unavailable`，不得伪造 export。
- [ ] **R5 — 补齐外部授权与安全准备。** 提供真实 Provider 与 GitLab smart-HTTP clone/push/MR 链路，
  修复 CA/URL 问题，轮换曾用于调试的凭据并执行 secret scan；证据只保存脱敏路径和摘要。
- [ ] **R6 — 完成四 Harness 的真实 Task 矩阵。** 覆盖 fresh、retry、resume/continue、failure、cancel、
  timeout、scheduler recovery、Session、Skills、usage、archive、Git commit/push/MR 和 terminal 对账；
  每个 Task 绑定 Host/daemon、Profile generation、attempt 和全部制品 identity。
- [ ] **R7 — 完成 Harness 专项能力。** OpenCode 覆盖 Server、Session、Agent、Command、Abort、事件和
  usage；Pi 覆盖原生 ACK、严格顺序、steering、follow-up、close、`outcome_unknown` 不重放和
  scheduler 恢复；Claude/Codex 证明现有核心能力无回退。

## 3.5 本轮 dev 环境已完成证据（2026-08-26）

> 以下为 dev 环境（192.168.50.129）真实执行证据，供 R1–R7 复核；未替代目标 Host 与发布窗口动作。

- **R5（外部授权，dev 完成）：** GitLab admin/bot token 与 opencode.ai Provider key 已录入 dev 后端 DB `system_config`（加密；原始值仅存于 gitignored `deploy/dev-env-info.md`）；`/api/config/gitlab/test` 通过（18.5.5-ee，ai-bot）；bot clone/push/MR 实测全通；Provider 三端点实测（minimax-m2.7 messages / gpt-5.6-luna responses / mimo-v2.5 chat / deepseek-v4-flash messages）；secret scan 无泄漏。
- **R6（codex，host_mount 0.146.0）：** Task 4 COMPLETED，commit `188331f29c`，MR !1，usage 76237/1252，runtime archive + 25 canonical events；失败路径（Task 2/3）正常收尾。codex 端点语义实测：`base_url` 被 codex 追加 `/responses`，provider 需配 `https://opencode.ai/zen/go/v1`。
- **R6/R7（Pi，Kit 0.5.0 present payload 0.84.2，digest `6c68c5f5f6bf…`）：** 真实 Task 13/16/17/18/19 COMPLETED（deepseek-v4-flash），MR !2/!4/!6 等；覆盖创建（fresh+skill）、continue 追加（会话恢复 `<UUID:377a0db8…>`）、运行中 follow_up **delivered** 且内容落地（commit `4a2023d6`）、steer gate 关闭时正确拒绝、取消（Task 15）、cancel→retry 成功（Task 16）、retry 冻结快照语义（Task 14 复用旧 bundle 同因失败）、Skills（codify-marker 精确落地）、工具事件（`tool.started/completed` → `tool_call` 日志：write/read/bash 含路径/脱敏命令/output payload）；事件流全类型覆盖（0 unknown_raw_event）。
- **源码修复链（commit `4c223d1c`/`e4361d7a`/`c5661619`）：** ① Kit 构建：目录 payload（pi 完整资源）、glibc loader 回退（Alpine 构建阶段）、smoke ABI shim、manifest path 统一（S1 对应项）；② `pi_events.py`：lenient JSON 修复 + agent_end 定向提取（pi 0.84.2 未转义引号破坏整行）；③ `task_harness_commands.py`：bundle 能力判定从 archive 解 harness manifest + undefer（S4 相关，steer/follow_up 此前全被 `unsupported_harness` 拒绝）；④ `repository-helpers.sh`：work 分支远端不存在时 ahead-of-base 回退 origin/base（Pi 自 commit/push 后误报 "No changes made"）；⑤ 单测：`test_pi_harness_adapter.py` 34、`test_task_harness_commands.py` 18、`test_worker_kit.py` 54、全量 unit 3065+1 passed。
- **已知边界：** Kit manifest 不覆盖 payload sidecar（theme/assets/package.json）——S2 未闭环；Pi `--exclude-tools` 在 rpc 模式触发 pi 0.84.2 自身 bug（无输出退出），未采用工具禁用，依赖 delivery 修复。

## 4. L5 Acceptance

- [ ] 冻结不少于 20 个内部代表性 Task，覆盖 plan、execute、freeform、修复测试、无改动、Session、
  失败和取消；记录可比模型、输入、成功标准和统计方法。
- [ ] Pi 与当前较优兼容 Harness 做同任务对比：成功率下降不超过 10 个百分点；中位耗时和 Token
  不得同时恶化超过 25%。
- [ ] Pi 完成 390×844、768px 和桌面浏览器验证，包括命令输入安全区、键盘遮挡、触摸面积、长文本、
  状态换行和恢复后的 command history。
- [ ] Pi、OpenCode、Claude、Codex 的 Contract/Event/Result Conformance 和真实 Worker Host canary
  全部通过；所有适用的 Linux、PostgreSQL、AF_UNIX、scheduler skip 均在可用环境重跑。
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

1. S1–S7 清零并重新建立 L1/L2；
2. R1–R5 生成、安装并绑定同一个 immutable release composition；
3. R6–R7 完成 L4 真实 Task 与专项能力；
4. 完成 L5 acceptance；
5. 独立维护窗口执行 L6 hard cut。

出现以下任一情况立即停止当前层级：

- present path/bytes 与 inventory 不一致，或 Kit identity 未覆盖实际执行 bytes；
- image、Kit、Bundle、Adapter、Profile generation、Host/daemon 或 Task attempt 来自不同冻结组合；
- 使用 mutable tag、placeholder digest、未核验 Kit、`host_mount` 或旧 image CLI lock 冒充 release evidence；
- V1 dual-canary、command pump 隔离、PG/AF_UNIX/concurrency 存在失败或必要 skip 未重跑；
- 任一 enabled 且 present/available Harness 缺少真实 Task/MR/terminal/usage/archive 对账；
- Provider/GitLab 授权、凭据轮换、secret scan 或唯一 migration owner 未完成；
- 任一首发 Harness 存在 P0/P1。

单个 present CLI 的 functionality 失败只将该 Harness 标为 unavailable，不得清空其他 Harness；
但首轮 hard-cut candidate 因此缺少四 Harness 任一项时，不得进入 L5/L6。数据库只 roll-forward，
不修改历史 Snapshot、Issue、attempt、archive 或证据。
