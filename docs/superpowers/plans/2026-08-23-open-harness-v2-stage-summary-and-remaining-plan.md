# Open-Harness V2 阶段总结与剩余执行计划

**原始日期：** 2026-08-23

**本次更新：** 2026-08-24

**状态：** Implementation in progress / Internal Preview

**代码基线：** `dev`，本次盘点时 `HEAD=5b9ec15e`

**架构依据：** [Open-Harness V2 架构方案](../../architecture/open-harness-v2.md)

**原实施计划：** [Open-Harness V2 分阶段实施计划](2026-08-21-open-harness-v2-implementation-plan.md)

## 1. 当前结论

本轮已经把 WP0–WP7 的主要源码改动拆成可辨识提交，WP6 以独立提交 `5b9ec15e` 完成源码层收口。
当前可以确认的是源码、合同和本地聚焦测试进展，不能据此宣布 Open-Harness V2 已完成或可硬切。

当前状态必须保持以下边界：

- 代码提交不等于已构建、已固定的发布制品。
- 本地单测或 fake Docker 测试不等于真实 Docker Host 的 Profile/Kit 验证。
- 旧 remote image、旧 probe、直接调用 Harness 的诊断结果，都不能替代同一冻结
  Bundle/Image/Kit 上由真实 Worker/Scheduler 执行的 Task/MR 证据。
- Pi 仍只是新建 Profile 默认值的候选；默认值 migration 和 `v2_only` 硬切均未执行。
- OMP Phase 6 不在本轮首发范围内，也不得提前进入关键路径。

## 2. 本轮分阶段提交台账

以下提交按实际历史顺序列出。测试数量来自对应提交时的聚焦验证或本次复核；未登记的真实 Host
字段不能推定为已通过。

| Commit | 工作包 | 已落地的源码/文档事实 | 当前证据边界 |
|---|---|---|---|
| `9cf05ff9` `chore(harness): consolidate sanitized v2 probes` | WP0 | 将 Provider、full-chain、Pi RPC、resume、recall、benchmark 和 secret scan 收敛到统一 V2 探针目录；清理重复迭代脚本与结果导出物；`deploy/.env.test` 只保留安全占位 | L1/L2；真实 Provider 凭据轮换仍是 operator 外部动作 |
| `c50f3cf3` `fix(harness): bind v2 bundle to frozen runtime bytes` | WP1 | 持久化确定性 V2 archive；Bundle/Adapter digest 绑定冻结源码字节；物化不再重新扫描；CLI artifact manifest 缺失或占位时 fail closed | 18 个聚焦测试通过；无 release artifact、目标 Host 或 Task 证据 |
| `c1a702fe` `fix(harness): enforce v1 read-only execution policy` | WP5 | 中央执行策略覆盖 API、Scheduler、pump、startup/recovery；V1 只读；production/canary execution mode 显式化；长驻服务不再同时拥有 migration | 262 个聚焦测试及 19 个子测试通过，compose contract 已检查；未执行真实维护窗口迁移或硬切 |
| `b3be3b16` `docs(deploy): document single migration owner` | WP5 | 补充唯一 migration owner、roll-forward-only 和部署顺序说明 | L1 文档证据；不是实际 migration 日志 |
| `544bbcc9` `build(worker): lock harness artifact identities` | WP1/WP6 基础 | 固定四个 Harness CLI 的版本、SHA、平台字段；导出 image artifact manifest；加入四个 self-check 与候选制品报告 | 44 个聚焦测试、Ruff、shell syntax 检查通过；旧 remote image 仅是 candidate，不能算 WP6 退出或 L3/L4 |
| `8e6c7e7d` `fix(harness): enforce real protocol capabilities` | WP3/WP4 | Pi/OpenCode 能力收窄为已实现的 `anthropic_messages`；协议专属环境变量；OpenCode 明确 `resume=false`；Pi/OpenCode terminal 判定 fail closed | 125 个测试通过、4 个 deselected、13 个子测试通过；无真实 endpoint matrix 或真实 Host smoke |
| `e167b997` `feat(harness): drive controls from frozen catalog` | WP7 | Backend current/task catalog；命令可用性由冻结 Bundle capability 决定；V1 只读 UI；TaskView/SteeringPanel 去除 Harness 名称硬编码 | Backend 6 passed、12 skipped；Frontend 117 passed 且 production build 通过；无移动端浏览器验收和真实 Task 证据 |
| `0a012fd2` `feat(pi): complete durable rpc command plane` | WP2 | migration 075；`queued -> dispatching -> delivered/rejected/outcome_unknown` journal；常驻 Pi owner；原生 ACK correlation；gate drain/close；race、EOF、socket 权限和安全日志处理 | 本次与 API 一起复核为 35 passed、13 skipped；PostgreSQL/AF_UNIX skip 尚待可用环境重跑；无真实 Pi Host steering/follow-up Task |
| `6eda3f2c` `fix(api): sanitize command history projection` | WP2/WP7 | command history 只投影公开状态和 allowlist rejection；不返回 payload、digest、native diagnostics 或内部计数 | 已包含在上述 35 passed、13 skipped 聚焦复核中；无浏览器/真实 Host 证据 |
| `5b9ec15e` `fix(release): verify frozen multi-harness artifacts` | WP6 | 统一 Kit/Runtime Bundle/image artifact 验证；Backend Harness matrix 成为单一事实源；Kit archive、offline archive checksum 和 portable validators fail closed；移除 offline exec 后不可达的重复 verifier | 第八轮独立 review 无 P0/P1；主线程 focused 145 passed，Ruff、py_compile、shell syntax、diff check、secret scan 均通过；未执行真实 Docker build/export、L3/L4 |

`544bbcc9` 只提供 artifact identity 与 self-check 基础；`5b9ec15e` 才是 WP6 源码层统一验证的最终提交。
两者都不包含真实 Docker build/export，也不能替代 release payload、不可变 image digest、目标 Host 或
真实 Task/MR 证据。

## 3. 工作包状态

### WP0：安全清理与重复实验代码收敛

**源码状态：主要完成；外部动作未完成。**

- 重复的 Provider/Pi/full-chain/resume/recall/benchmark 探针已经合并，旧迭代脚本、key-dump 类脚本和
  结果导出物没有进入提交。
- 统一 secret scanner 已进入仓库；探针约定禁止输出凭据、完整鉴权头和原始敏感诊断。
- `deploy/.env.test` 已恢复为安全占位，不是 secret store。
- 本次曾使用的真实 Provider 凭据仍必须由 operator 在外部系统轮换。仓库清理不能代替吊销、轮换和
  下游配置更新；tracker 不记录旧值、凭据片段或可疑诊断。

**退出前仍需：** operator 留存轮换完成记录，并在新凭据注入前确认仓库、制品和 acceptance 输出的
secret scan 均通过。

### WP1：Runtime Bundle content-addressed truth

**源码状态：已提交；发布制品状态：未验收。**

- 冻结 archive、文件清单、Bundle digest、Adapter identity 和物化输入已收敛到同一字节来源。
- CLI artifact lock 缺失、占位或不匹配时源码路径 fail closed。
- 当前只有本地源码/单测证据；尚无带真实 CLI payload 的 release-stamped Runtime Bundle，也没有
  目标 Host 上的 Snapshot/Bundle/Adapter digest 对账。

### WP2：Pi durable RPC command plane

**源码状态：已提交；环境相关测试与真实 Task 未闭环。**

- Pi owner、真实 socket 往返、native ACK correlation、持久化 dispatch journal、严格队首顺序、
  `outcome_unknown`、gate drain/close 和 terminal race 已进入提交。
- public command history 已脱敏，未知内部原因映射为稳定公开错误。
- 本次聚焦复核：`35 passed, 13 skipped`。其中 12 个 skip 来自 PostgreSQL 测试数据库不可达，1 个
  skip 来自当前 sandbox 不允许 `/tmp` 下 AF_UNIX bind。这些 skip 是验收缺口，不是通过证据。
- 仍需在可访问 PostgreSQL、允许 AF_UNIX 的 Linux Worker 环境重跑，并用真实 Pi Task 对账 command row、
  native ACK、canonical event、TaskLog 和 terminal 顺序。

### WP3：Provider/model protocol 能力

**源码状态：按已证实能力收窄；真实 endpoint 未验收。**

- Pi/OpenCode 当前只声明 `anthropic_messages`，未把尚未实现的 OpenAI 协议作为能力发布。
- Provider 环境变量按冻结 `model_protocol` 精确生成，非当前协议变量不参与 Adapter 选择。
- 若未来重新声明其他协议，必须先补 config unit、mock endpoint、固定 CLI/SDK 的真实 endpoint smoke，
  不能只改 Registry 常量。

### WP4：OpenCode first-class 语义

**源码状态：首发语义已收窄；真实 Host 未验收。**

- 首发明确 `resume=false`，不伪装已有 resume。
- 成功终态要求最终 assistant text、成功 Harness terminal/settled 和无 error；EOF、idle 或 status-only
  不能单独产生成功。
- 仍需真实 OpenCode Server 生命周期、abort/error/disconnect/timeout、repository isolation、Git/MR
  delivery 的 L4 Task 证据。

### WP5：中央执行策略、唯一 migration owner 与 V1 只读

**源码和部署合同状态：已提交；维护窗口未执行。**

- V1 writer、Scheduler claim、Worker start/load、recovery 均受中央 execution policy 约束。
- V1 detail/log/archive/statistics 保持可读；V1 execute/retry/schedule/resume/continue 只读拒绝。
- Backend/Scheduler 长驻服务使用非 migration-owner 模式；migration 由一次性 owner 执行。
- 尚无生产/预发布维护窗口日志、数据库升级记录或 `v2_only` 后的读写验收矩阵。

### WP6：Worker Image、Kit、Runtime Bundle 统一验证

**源码状态：已提交并通过独立 review；制品与 Host 状态：未验收。**

- `5b9ec15e` 分别验证并交叉检查 Kit manifest、Runtime Bundle manifest 与 image CLI artifact identity，
  不把 Kit、Backend 持久化 Bundle 和 launcher projection 混为同一合同。
- Backend Harness matrix 是受支持 Adapter、协议和 artifact 要求的单一事实源；Kit 生成和验证消费该
  matrix，不再维护漂移的第二份四 Harness 列表。
- 四个 first-class/default Harness 必须有 self-check；CLI 版本、SHA、平台、路径或可执行文件字节不匹配
  时 fail closed。
- Kit archive 在安装前由 portable validator 检查路径安全、manifest、文件摘要和归档内容；offline
  archive 生成独立 checksum，解包/执行前必须先校验。
- offline wrapper 只委托给 Kit 内携带、受 archive 摘要保护的 verifier/validator；已经删除 offline exec
  后不可达的重复 verifier 路径，在线、archive 和 offline 不再各自维护不同验证语义。
- 第八轮独立 review 没有 P0/P1；主线程聚焦验证为 `145 passed`，Ruff、py_compile、shell syntax、
  `git diff --check` 和 secret scan 均通过。

上述结果只关闭 WP6 的 L1/L2 源码门槛。本轮没有执行真实 Docker image build、Worker Kit export、offline
bundle export、目标 Host Profile verify-runtime 或真实 Task/MR，因此不得把 WP6 提交登记为 L3/L4。

### WP7：Manifest 驱动 UI 和命令历史

**源码状态：主要完成；浏览器验收和默认值切换未完成。**

- catalog/capability 来自当前 release 或 Task 冻结 Bundle；历史 Task 不受 catalog 切换竞态影响。
- command input 由 Task running、gate accepting 和 manifest capability 共同控制。
- history 已展示公开 lifecycle/时间/拒绝原因，内部 payload 和 diagnostics 不暴露。
- 仍需 390×844、768px 和桌面 viewport 的实际浏览器检查，包括 44px 触控目标、长状态换行、
  safe-area 和断线恢复。
- Pi 默认 migration 只能在 WP8 全部门槛通过后单独提交和执行。

### WP8：真实 Host canary、benchmark 与硬切

**状态：未开始；以下前置条件均不能由旧环境替代。**

仍缺：

1. 四个固定版本 CLI 的可发布 payload；
2. 新的、不可变的 Worker image `repository@sha256:...`，不能使用 mutable tag；
3. 与该 image/runtime release lock 匹配的新 Worker Kit 版本与 digest；
4. 真实 Provider 配置下目标 Docker Host 的 Profile verify-runtime；
5. 同一冻结 Bundle/Image/Kit 上由真实 Worker/Scheduler 执行的四 Harness Task/MR smoke；
6. Pi 至少 20 个同类内部 Task 的原始样本、质量/时延/command race/Git/MR/archive 指标；
7. 唯一 migration owner 的维护窗口执行记录、`v2_only` 双服务启动和 V1 read-only 验收；
8. 新建 Profile 默认 Pi 的独立 migration/commit 和硬切记录。

远端已有的旧 Worker image 不包含本轮 release lock 所要求的完整 artifact manifest；旧容器、旧 probe、
候选报告和 direct RPC 成功都不能登记为 L3/L4 或 WP8 证据。

## 4. 证据分层

后续每次接手都必须按下表登记，不能用较低层证据替代较高层：

| 层级 | 必须记录的事实 | 当前状态 |
|---|---|---|
| L1 合同/源码设计 | architecture、schema、状态机、manifest、runbook 一致，diff 已评审 | WP0–WP7 已按责任拆分提交；WP6 经八轮独立 review 无 P0/P1 |
| L2 本地实现验证 | 精确测试命令、passed/failed/skipped、Ruff/build/bash、secret scan；skip 单列 | 多个工作包已有聚焦测试；WP2 仍有 PostgreSQL/AF_UNIX skip；WP6 主线程复验 145 passed |
| L3 Release/Host 安装验证 | release manifest、Bundle digest、`repository@sha256`、Kit version/digest、平台、四 CLI version/SHA、Profile verify-runtime 结果 | 未完成 |
| L4 真实 Task/交付验收 | 真实 Host Task/attempt ID、Provider 协议、Harness fresh/resume/cancel/failure、command ACK、usage、Skills、Git commit/MR、archive | 未完成 |

Pi 20-task benchmark、迁移/hard-cut 和 V1 read-only 验收属于 L4 之后的发布门槛，不另造一个较低层级来
弱化真实 Task 要求。

每份正式证据至少登记：

```text
source commit:
runtime bundle digest:
worker image repository@sha256:
worker kit version/digest/platform:
harness CLI versions/SHA:
test commands and passed/failed/skipped:
docker host/profile verification record:
task/attempt/project/MR identifiers:
provider protocol (without credentials):
known skips/failures:
acceptance report path:
```

## 5. 严格剩余执行顺序

以下步骤按依赖顺序执行。除 operator 凭据轮换可与源码评审并行外，不得越级把后一步结果当作前一步
通过。

1. **关闭 WP0 外部安全动作。** operator 轮换本次使用过的真实 Provider 凭据；只通过受控 secret/env
   注入新值；保留不含秘密的轮换完成记录。
2. **准备 release lock。** 补齐四个真实 CLI payload，导出版本/SHA/平台；生成非占位 Runtime Bundle
   manifest；冻结 source commit、Bundle/Adapter digest。
3. **构建不可变制品。** 构建新 Worker image 和新 Kit；记录 image `repository@sha256`、Kit
   version/digest/platform；离线包从同一 Kit verifier 构建并校验 archive checksum。
4. **完成 L3。** 在目标 Docker Host 按真实 Profile 执行 verify-runtime；四 Harness 必须使用同一
   release lock；任何 placeholder、mutable tag、平台错配、缺 self-check 或 SHA 不一致都 fail closed。
5. **完成 L4 smoke。** 用真实 Provider 由真实 Worker/Scheduler 执行 Claude、Codex、Pi、OpenCode Task；
   对账事件、result、usage、Skills、cancel/timeout/failure、Git commit/push/MR 和 archive。Pi 额外验证
   steering/follow-up native ACK、严格顺序、terminal/cancel race。
6. **执行 Pi 20-task acceptance。** 使用可比任务集与固定配置，保留全部原始样本和失败；检查质量非劣、
   command latency、protocol error、delivery 和资源指标。
7. **完成产品验收。** 复跑 PostgreSQL 与 AF_UNIX 被跳过的测试；完成 390×844、768px、桌面浏览器验证；
   确认 V1 UI read-only 和 command history 脱敏。
8. **维护窗口硬切。** 排空 V1；唯一 migration owner 执行 upgrade；以显式 `v2_only` 和
   `AUTO_MIGRATE=false` 启动 Backend/Scheduler；验收 V1 read/statistics 与全部 writer 拒绝；最后单独执行
   新建 Profile 默认 Pi 的变更。
9. **归档证据。** 固定 commit、Bundle/Image/Kit digest、测试结果、Host/Profile、Task/attempt/MR、监控和
    操作记录；只有全部门槛通过后才能把本文状态改为 completed。

## 6. 验收与停止条件

以下任一条件出现，必须停止升级或硬切：

- WP6 verifier 回归为失败、重新出现双轨实现，或 manifest truth 再次不明确。
- 真实 CLI payload、image digest、Kit digest、Bundle digest 任一缺失或使用占位值。
- Profile verify-runtime 不是在目标 Host 对同一 release lock 执行。
- PostgreSQL/AF_UNIX skip 未在目标环境重跑。
- command native ACK、outcome-unknown、terminal/cancel race 不能对账。
- 四 Harness 任一缺少真实 Task/MR、usage、archive 或失败路径证据。
- Pi 20-task 原始样本不完整，或只保留成功样本。
- secret scan 失败，或 operator 凭据轮换没有完成。
- migration owner 不唯一、execution mode 不一致、V1 未排空或 V1 writer 仍可执行。

## 7. 回滚和 roll-forward 规则

- **硬切前：** 保持 `dual_canary`；失败的 canary Profile 停止接收新 Task，回到已知可用 Profile；保留
  失败 Task、raw event 和制品 digest，不修改历史记录来制造“通过”。
- **制品回退：** 只能切回已经登记的不可变 image digest、Kit digest 和 Runtime Bundle digest 组合；
  不允许依赖同名 mutable tag，也不允许混搭新 Bundle 与旧 Kit。
- **数据库：** V2 migration 是 roll-forward-only。不得运行依赖恢复 V1 物理 schema 的 downgrade；失败时
  停止 writer、保留数据库和迁移日志，用新的向前修复 migration 处理。
- **硬切窗口：** 在 Pi 默认 migration 前保留明确 abort point。若双服务 preflight、V1 read-only、真实
  Task smoke 或监控任一失败，不执行默认值变更。
- **硬切后：** 保持 V1 历史读取，不恢复 V1 writer；修复通过新代码、向前 migration 和新的不可变
  release lock 交付。

## 8. 接手检查清单

下一个执行者开始工作前先核对：

- [x] `HEAD` 与本文提交台账一致，或补充 HEAD 之后的范围明确提交。
- [x] WP6 已以独立提交 `5b9ec15e` 落地，并保留 review 与测试证据边界。
- [ ] 当前 `pytest` 的 passed/failed/skipped 是否逐项记录，PostgreSQL/AF_UNIX 不再静默跳过。
- [ ] CLI payload、release manifest、image digest、Kit digest 是否均为真实非占位值。
- [ ] operator 凭据轮换是否有外部完成记录，且任何报告均不包含秘密。
- [ ] L3 Host/Profile 和 L4 Task/MR 是否使用同一个冻结 release lock。
- [ ] hard cut、Pi 默认、migration 是否保持独立提交和独立维护窗口记录。

本文仍是阶段 tracker，不是发布声明。当前明确结论是：**WP0–WP7 的源码工作已按责任拆分提交，WP6
通过独立 review；但外部凭据轮换、发布制品、L3/L4、真实 Provider/Host、Task/MR、Pi benchmark 与
hard cut 均未完成。**
